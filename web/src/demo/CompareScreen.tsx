import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type MutableRefObject, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { useI18n } from "../i18n";
import { blankForm, DEMO_COMPARISONS, resolveSide, type DemoComparison, type PracticeItem, type SideResolution } from "./comparisons";
import { CopyLink } from "./CopyLink";
import { hashForScreen } from "./deepLink";
import { DEMO_EXAMPLES } from "./examples";
import { focusControl } from "./history";
import { readCompareVisit, writeCompareVisit, type CompareVisit, type PracticeAnswer } from "./visit";

// Public demo: a comparison of two public units (comparisons.ts).
//
// R2 layout, the same at every width:
// 1. The pair: each side's unit wording (its rule, as a label) and its example
//    sentence, compact, so both sentences are read together, on a 320 px
//    phone too. Wide screens put the two sides next to each other. Since R3
//    each side links to its exact evidence (the unit's source record), and a
//    "Where these come from" panel shows the learner's question and context.
// 2. "Show the evidence": the rest of each side (the learner's question, the
//    stored interpretation, the rule, the Concept, links to the source and the
//    Concept) behind one disclosure button. It starts open on wide screens and
//    closed on phones; the visitor's choice is kept for this visit (visit.ts),
//    and coming back to a control inside it opens it again. Opening or closing
//    it never changes the address: the comparison's link stays the same.
// 3. An optional choose-first practice question, for a comparison that has one
//    (Practice below), with the pair hidden while it is shown. The question is
//    part of the link (`#compare=…&practice=N`, R3-056); answers are not.
//
// Everything shown is read from the server; nothing is written.

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; sides: SideResolution[] };

export const compareCardId = (key: string) => `demo-compare-${key}`;
export const practiceCardId = (key: string) => `demo-practice-pick-${key}`;

// Controls inside the evidence: coming back to one of them opens the evidence.
const IN_EVIDENCE = /^demo-compare-(src|concept)-/;
const wideScreen = () => typeof window.matchMedia === "function" && window.matchMedia("(min-width: 721px)").matches;

// A link that is also an in-page move: a plain click moves within the demo (a
// history entry, focus handling); a modified click keeps the browser's default
// (a new tab or window at the same address).
function MoveLink({ href, id, onMove, children }: { href: string; id: string; onMove: () => void; children: ReactNode }) {
  const click = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    onMove();
  };
  return (
    <a href={href} id={id} onClick={click}>
      {children}
    </a>
  );
}

export function ComparePicker({ onOpen, onPractice }: { onOpen: (key: string) => void; onPractice: (key: string) => void }) {
  const { t } = useI18n();
  return (
    <section className="panel demo-compare-picker" aria-labelledby="demo-compare-picker-heading">
      <h2 id="demo-compare-picker-heading" className="library-title" tabIndex={-1}>
        {t("demo.compare.pickerHeading")}
      </h2>
      <ul className="demo-example-list">
        {DEMO_COMPARISONS.map((c) => (
          <li key={c.key}>
            <button type="button" className="demo-compare-pick" id={compareCardId(c.key)} onClick={() => onOpen(c.key)}>
              <span className="demo-compare-pick-title">{t(c.title)}</span>
              <span className="demo-compare-pick-summary">{t(c.summary)}</span>
              <span className="demo-example-open" aria-hidden="true">
                {t("demo.compare.open")}
              </span>
            </button>
            {c.practice ? (
              <button type="button" className="ghost demo-practice-pick" id={practiceCardId(c.key)} onClick={() => onPractice(c.key)}>
                {t("demo.practice.pick", { title: t(c.title) })}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

// The practice items this build can offer: both sides found, and the item's
// form occurring exactly once in its side's example.
type FoundSide = Extract<SideResolution, { kind: "found" }>;
interface ReadyItem {
  item: PracticeItem;
  side: FoundSide;
  parts: [string, string];
}
function readyItems(comparison: DemoComparison, sides: SideResolution[]): ReadyItem[] {
  const p = comparison.practice;
  if (!p || sides.length !== 2 || sides.some((s) => s.kind !== "found")) return [];
  return p.items.flatMap((item) => {
    const side = sides[item.side] as FoundSide;
    const parts = blankForm(side.unit.example, p.choices[item.side].form);
    return parts ? [{ item, side, parts }] : [];
  });
}

export function CompareScreen({
  comparison,
  onBack,
  onSearch,
  onOpenComparison,
  onOpenExample,
  href,
  onOpenConcept,
  onOpenSource,
  onReady,
  returnFocus,
  practice,
  onStartPractice,
  onPracticeItem,
  onLeavePractice,
}: {
  comparison: DemoComparison;
  onBack: () => void;
  // A side this build lacks: its keyword query in the ordinary search; "" is the whole library.
  onSearch: (q: string) => void;
  // Another comparison, on its first question when `practice`.
  onOpenComparison: (key: string, practice?: boolean) => void;
  // The guided example both units come from (`comparison.example`).
  onOpenExample?: (key: string) => void;
  // The demo links of a Concept or a source opened from this comparison.
  href: (conceptId: number, unitId?: number) => string;
  onOpenConcept: (conceptId: number) => void;
  onOpenSource: (conceptId: number, unitId: number) => void;
  // The sides as this build resolved them (the 60-second tour's next step).
  onReady?: (sides: SideResolution[]) => void;
  returnFocus?: MutableRefObject<string | null>;
  // The practice question shown (1-based, from the link), or none: the pair.
  practice?: number;
  // Open a question (a new history entry), move to another (the same entry),
  // and back to the pair.
  onStartPractice?: (n: number) => void;
  onPracticeItem?: (n: number) => void;
  onLeavePractice?: () => void;
}) {
  const { t } = useI18n();
  const [retry, setRetry] = useState(0);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const heading = useRef<HTMLHeadingElement>(null);
  const [visit, setVisitState] = useState<CompareVisit>(() => {
    const kept = readCompareVisit(comparison.key);
    const back = returnFocus?.current ?? "";
    return { ...kept, evidence: kept.evidence ?? (IN_EVIDENCE.test(back) || wideScreen()) };
  });
  const setVisit = (next: CompareVisit) => {
    writeCompareVisit(comparison.key, next);
    setVisitState(next);
  };
  // The element to focus once the change it follows is on the page.
  const focusNext = useRef<string | null>(null);
  useEffect(() => {
    const id = focusNext.current;
    if (!id) return;
    focusNext.current = null;
    const el = document.getElementById(id);
    if (el) focusControl(el);
  });
  useEffect(() => {
    let active = true;
    setLoad({ status: "loading" });
    Promise.all(comparison.sides.map((side) => resolveSide(side)))
      .then((sides) => {
        if (!active) return;
        setLoad({ status: "ready", sides });
        onReady?.(sides);
      })
      .catch(
        (e: unknown) =>
          active &&
          setLoad({
            status: "error",
            message: e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e),
          }),
      );
    return () => {
      active = false;
    };
  }, [comparison, retry]);
  // Coming back (Back, an in-page back action): the control that left this
  // comparison, once it is shown again; otherwise the comparison's heading.
  useEffect(() => {
    const id = returnFocus?.current;
    if (id && load.status !== "loading") {
      returnFocus.current = null;
      const el = document.getElementById(id);
      if (el && heading.current?.closest(".demo-compare")?.contains(el) && focusControl(el)) return;
    }
    // At the top of the screen, so on a phone the pair below it is in view too.
    heading.current?.focus({ preventScroll: true });
    heading.current?.scrollIntoView?.({ block: "start" });
  }, [load.status]);
  // Moving between the pair and a question (a button, Back, Forward): the
  // control that left the entry when coming back to it, else the new heading.
  const shownPractice = useRef(practice);
  useEffect(() => {
    if (shownPractice.current === practice || load.status !== "ready") return;
    shownPractice.current = practice;
    const id = returnFocus?.current;
    if (id) {
      returnFocus.current = null;
      const el = document.getElementById(id);
      if (el && focusControl(el)) return;
    }
    const el = document.getElementById(practice !== undefined ? "demo-practice-heading" : "demo-compare-pair-heading");
    if (el) focusControl(el);
  }, [practice, load.status]);
  const sides = load.status === "ready" ? load.sides : [];
  const found = sides.filter((s): s is FoundSide => s.kind === "found");
  const entries = new Set(found.map((s) => s.unit.entry_id));
  const items = readyItems(comparison, sides);
  const practicing = practice !== undefined && items.length > 0;
  const others = DEMO_COMPARISONS.filter((c) => c.key !== comparison.key);
  const example = comparison.example ? DEMO_EXAMPLES.find((e) => e.key === comparison.example) : undefined;
  const shown = visit.evidence === true;
  const toggle = () => setVisit({ ...visit, evidence: !shown });
  const closeEvidence = (e: KeyboardEvent) => {
    if (e.key !== "Escape") return;
    e.stopPropagation();
    setVisit({ ...visit, evidence: false });
    focusNext.current = "demo-compare-evidence-toggle";
  };
  // R3-046: the learner's question(s) and recorded context, once per record.
  const records = found.filter((s, i) => found.findIndex((x) => x.unit.entry_id === s.unit.entry_id) === i);
  return (
    <div className="demo-compare">
      <section className="panel" aria-labelledby="demo-compare-heading">
        <p className="demo-eyebrow">{t("demo.compare.eyebrow")}</p>
        <h2 id="demo-compare-heading" ref={heading} tabIndex={-1} className="library-title">
          {t(comparison.title)}
        </h2>
        {/* R3-078: the question carries its own context; on a phone the summary
            would push its choices below the first view. */}
        {practicing ? null : <p>{t(comparison.summary)}</p>}
        <div className="actions demo-compare-head-actions">
          <button type="button" className="ghost" onClick={onBack}>
            {t("demo.compare.back")}
          </button>
        </div>
      </section>
      {load.status === "loading" ? (
        <p className="empty" role="status">
          {t("demo.compare.loading")}
        </p>
      ) : load.status === "error" ? (
        <div className="banner error" role="alert">
          {t("demo.compare.failed", { message: load.message })}{" "}
          <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
            {t("common.tryAgain")}
          </button>
        </div>
      ) : practicing ? (
        <Practice
          key={practice}
          comparison={comparison}
          items={items}
          sides={load.sides}
          index={Math.min(Math.max(practice - 1, 0), items.length - 1)}
          visit={visit}
          setVisit={setVisit}
          focusNext={focusNext}
          href={href}
          onOpenSource={onOpenSource}
          onItem={(n) => onPracticeItem?.(n)}
          onLeave={() => onLeavePractice?.()}
          onOpenComparison={onOpenComparison}
          onSearch={onSearch}
        />
      ) : (
        <>
          <section className="panel demo-compare-pair" aria-labelledby="demo-compare-pair-heading">
            <h3 id="demo-compare-pair-heading" tabIndex={-1}>
              {t("demo.compare.pairHeading")}
            </h3>
            <ul className="demo-compare-pair-list">
              {load.sides.map((side, i) => (
                <li key={i} className="demo-compare-pair-side" data-side={i}>
                  {side.kind === "found" ? (
                    <>
                      <p className="demo-compare-tense" lang="fr" dir="auto" data-compare-label>
                        {side.unit.canonical}
                      </p>
                      {side.unit.example ? (
                        <p className="french demo-compare-sentence" lang="fr" dir="auto" data-compare-example>
                          {side.unit.example}
                        </p>
                      ) : (
                        <p className="hint">{t("demo.compare.noExample")}</p>
                      )}
                      {side.source ? (
                        // R3-043: each example's exact public evidence.
                        <p className="demo-compare-pair-src">
                          <MoveLink
                            href={href(side.concept.id, side.unit.unit_id)}
                            id={`demo-pair-src-${side.unit.unit_id}`}
                            onMove={() => onOpenSource(side.concept.id, side.unit.unit_id)}
                          >
                            {t("demo.compare.pairEvidence", { unit: side.unit.unit_id, entry: side.unit.entry_id })}
                          </MoveLink>
                        </p>
                      ) : null}
                    </>
                  ) : (
                    <>
                      <p className="demo-compare-tense">{t("demo.compare.missingHeading", { query: comparison.sides[i].query })}</p>
                      <button type="button" className="ghost" id={`demo-compare-search-${i}`} onClick={() => onSearch(comparison.sides[i].query)}>
                        {t("demo.compare.search", { query: comparison.sides[i].query })}
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
            <div className="actions demo-compare-pair-actions">
              <button
                type="button"
                className="ghost demo-compare-evidence-toggle"
                id="demo-compare-evidence-toggle"
                aria-expanded={shown}
                aria-controls="demo-compare-evidence"
                onClick={toggle}
              >
                {t(shown ? "demo.compare.evidenceHide" : "demo.compare.evidenceShow")}
              </button>
              {records.length ? (
                <button
                  type="button"
                  className="ghost"
                  id="demo-compare-source-toggle"
                  aria-expanded={visit.source === true}
                  aria-controls="demo-compare-source"
                  onClick={() => setVisit({ ...visit, source: !visit.source })}
                >
                  {t(visit.source ? "demo.compare.sourceHide" : "demo.compare.sourceShow")}
                </button>
              ) : null}
            </div>
            <div id="demo-compare-source" className="demo-compare-source" hidden={visit.source !== true}>
              {records.map((s) => (
                <div key={s.unit.entry_id} className="demo-compare-source-record">
                  <h4>{t("demo.compare.question", { entry: s.unit.entry_id })}</h4>
                  {s.source ? (
                    <>
                      <blockquote dir="auto">{s.source.entry.original_input}</blockquote>
                      {s.source.entry.original_context ? (
                        <p className="hint" dir="auto">
                          {s.source.entry.original_context}
                        </p>
                      ) : null}
                    </>
                  ) : (
                    <p className="hint">{t("demo.compare.noSource", { unit: s.unit.unit_id })}</p>
                  )}
                </div>
              ))}
            </div>
          </section>
          <div id="demo-compare-evidence" hidden={!shown} onKeyDown={closeEvidence}>
            {found.length === 2 && entries.size === 1 ? (
              <p className="hint demo-compare-same">{t("demo.compare.sameQuestion", { entry: [...entries][0] })}</p>
            ) : null}
            <div className="demo-compare-grid">
              {load.sides.map((side, i) => (
                <Side
                  key={i}
                  index={i}
                  side={side}
                  query={comparison.sides[i].query}
                  href={href}
                  onOpenConcept={onOpenConcept}
                  onOpenSource={onOpenSource}
                />
              ))}
            </div>
          </div>
          {items.length ? (
            <section className="panel demo-practice-offer" aria-labelledby="demo-practice-offer-heading">
              <h3 id="demo-practice-offer-heading">{t("demo.practice.offerHeading")}</h3>
              <p className="hint">{t("demo.practice.offer")}</p>
              <button type="button" className="primary" id="demo-practice-start" onClick={() => onStartPractice?.(1)}>
                {t("demo.practice.start")}
              </button>
            </section>
          ) : null}
        </>
      )}
      <nav className="panel demo-compare-others" aria-label={t("demo.example.next")}>
        {/* R2-084: a clean link to this comparison: no practice answer, no open evidence. */}
        <p className="demo-related">
          <CopyLink fragment={hashForScreen({ kind: "compare", compare: comparison.key })} id="demo-compare-copy" label="demo.compare.copy" done="demo.link.copied" />
        </p>
        {example && onOpenExample ? (
          <p className="demo-related">
            <button type="button" className="ghost" id={`demo-compare-example-${example.key}`} onClick={() => onOpenExample(example.key)}>
              {t("demo.compare.openExample", { title: t(example.title) })}
            </button>
          </p>
        ) : null}
        {others.length ? <p className="label">{t("demo.compare.others")}</p> : null}
        {others.map((c) => (
          <button key={c.key} type="button" className="ghost" id={`demo-compare-other-${c.key}`} onClick={() => onOpenComparison(c.key)}>
            {t(c.title)}
          </button>
        ))}
      </nav>
    </div>
  );
}

// One side's evidence: the learner's question, the stored interpretation of
// it, the rule taken from it, the Concept it is filed under, and links to the
// Concept and the source record. (Its example is in the pair above.) Wide
// screens align these rows across both sides; phones stack the sides.
function Side({
  index,
  side,
  query,
  href,
  onOpenConcept,
  onOpenSource,
}: {
  index: number;
  side: SideResolution;
  query: string;
  href: (conceptId: number, unitId?: number) => string;
  onOpenConcept: (conceptId: number) => void;
  onOpenSource: (conceptId: number, unitId: number) => void;
}) {
  const { t, status } = useI18n();
  const headingId = `demo-compare-side-${index}`;
  if (side.kind === "missing")
    return (
      <article className="panel demo-compare-card demo-compare-missing" aria-labelledby={headingId}>
        <h3 id={headingId}>{t("demo.compare.missingHeading", { query })}</h3>
        <p role="status">{t("demo.compare.missing", { query })}</p>
      </article>
    );
  const { unit, concept, source, supporting } = side;
  const interp = source?.source_interpretation.effective;
  const eff = interp?.effective;
  return (
    <article className="panel demo-compare-card" aria-labelledby={headingId}>
      <h3 id={headingId} dir="auto">
        {concept.target}
      </h3>
      <div className="demo-compare-row">
        <h4>{t("demo.compare.question", { entry: unit.entry_id })}</h4>
        {source ? (
          <blockquote dir="auto">{source.entry.original_input}</blockquote>
        ) : (
          <p className="hint">{t("demo.compare.noSource", { unit: unit.unit_id })}</p>
        )}
      </div>
      <div className="demo-compare-row">
        <h4>{t("demo.compare.interpretation")}</h4>
        {interp && eff ? (
          <p dir="auto">
            {eff.explanation}{" "}
            <span className="hint">{t("demo.compare.interpretationMeta", { category: eff.category, resolution: status(interp.resolution) })}</span>
          </p>
        ) : (
          <p className="hint">{t("demo.compare.noInterpretation")}</p>
        )}
      </div>
      <div className="demo-compare-row">
        <h4>{t("demo.compare.rule")}</h4>
        <p>
          <span className="french" lang="fr" dir="auto">
            {unit.canonical}
          </span>
        </p>
        <p className="hint" dir="auto">
          {unit.statement}
        </p>
      </div>
      <div className="demo-compare-row">
        <h4>{t("demo.compare.concept")}</h4>
        <p>
          {t(supporting ? "demo.compare.supports" : "demo.compare.member", { id: concept.id, state: status(concept.state) })}
        </p>
      </div>
      <div className="actions demo-compare-actions">
        {source ? (
          <MoveLink href={href(concept.id, unit.unit_id)} id={`demo-compare-src-${unit.unit_id}`} onMove={() => onOpenSource(concept.id, unit.unit_id)}>
            {t("demo.compare.openSource", { unit: unit.unit_id, entry: unit.entry_id })}
          </MoveLink>
        ) : null}
        <MoveLink href={href(concept.id)} id={`demo-compare-concept-${concept.id}`} onMove={() => onOpenConcept(concept.id)}>
          {t("demo.compare.openConcept", { id: concept.id })}
        </MoveLink>
      </div>
    </article>
  );
}

// One offered answer: a side's form (with its tense name) or a distractor.
interface PracticeOption {
  form: string;
  tense?: string;
  side?: 0 | 1;
}

// Practice (R2, R3): choose the form that completes one example before seeing
// it. The learner's question and its recorded context come first; the example
// follows with its form blanked; then the offered forms (any distractor first,
// then the two sides' forms in side order, so the position never gives the
// answer away) and an explicit skip; a hint is under them on request. The
// answer, every form's explanation with a link to its evidence (a side's rule;
// for a distractor, the stored interpretation of the learner's question, which
// names it), and a valid alternative (where the item has one) are shown only
// after a choice or a skip. The outcome is announced (a status
// region) and focused. Then: ways to continue. Answers stay in this page's
// memory (visit.ts): no score, no record, no request beyond the reads the
// comparison already made. The question itself is the link (copyable).
function Practice({
  comparison,
  items,
  sides,
  index,
  visit,
  setVisit,
  focusNext,
  href,
  onOpenSource,
  onItem,
  onLeave,
  onOpenComparison,
  onSearch,
}: {
  comparison: DemoComparison;
  items: ReadyItem[];
  // Both sides as resolved: each form's rule and evidence, with or without an item of its own.
  sides: SideResolution[];
  index: number;
  visit: CompareVisit;
  setVisit: (v: CompareVisit) => void;
  focusNext: MutableRefObject<string | null>;
  href: (conceptId: number, unitId?: number) => string;
  onOpenSource: (conceptId: number, unitId: number) => void;
  onItem: (n: number) => void;
  onLeave: () => void;
  onOpenComparison: (key: string, practice?: boolean) => void;
  onSearch: (q: string) => void;
}) {
  const { t, tn } = useI18n();
  const practice = comparison.practice!;
  const choices = practice.choices;
  const { item, side, parts } = items[index];
  const options: PracticeOption[] = [
    ...practice.distractors.map((d) => ({ form: d.form })),
    { ...choices[0], side: 0 as const },
    { ...choices[1], side: 1 as const },
  ];
  const answer: PracticeAnswer | undefined = visit.answers[index];
  const revealed = answer !== undefined;
  const chosen = typeof answer === "number" ? options[answer] : undefined;
  const used = choices[item.side];
  const other = choices[item.side === 0 ? 1 : 0];
  const source = side.source;
  const interpretation = source?.source_interpretation.effective?.effective?.explanation;
  const [hint, setHint] = useState(false);
  const setAnswer = (a: PracticeAnswer | undefined) => {
    const answers = [...visit.answers];
    answers[index] = a;
    setVisit({ ...visit, answers });
  };
  const choose = (a: PracticeAnswer) => {
    if (revealed) return;
    setAnswer(a);
    focusNext.current = "demo-practice-outcome";
  };
  const fr = (text: string) => (
    <span lang="fr" className="french">
      {text}
    </span>
  );
  // Each side form's rule and evidence: the unit of the side whose example uses it.
  const sideOf = (i: number) => {
    const sd = sides[i];
    return sd?.kind === "found" ? sd : undefined;
  };
  const nextOthers = DEMO_COMPARISONS.filter((c) => c.key !== comparison.key && c.practice);
  const outcome =
    answer === "skip"
      ? tn("demo.practice.skipped", { form: fr(used.form) })
      : chosen?.side === undefined
        ? tn("demo.practice.chosenDistractor", { chosen: fr(chosen?.form ?? ""), form: fr(used.form) })
        : chosen.side === item.side
          ? tn("demo.practice.same", { form: fr(used.form) })
          : tn(item.alternate ? "demo.practice.chosenOtherAlso" : "demo.practice.chosenOther", { chosen: fr(other.form), form: fr(used.form) });
  return (
    <section className="panel demo-practice" aria-labelledby="demo-practice-heading">
      <p className="demo-eyebrow">{t("demo.practice.eyebrow")}</p>
      <h3 id="demo-practice-heading" tabIndex={-1}>
        {t("demo.practice.heading")}
      </h3>
      <p className="hint">{t("demo.practice.progress", { n: index + 1, total: items.length })}</p>
      <div className="demo-practice-context">
        <h4>{t("demo.compare.question", { entry: side.unit.entry_id })}</h4>
        {source ? (
          <>
            <blockquote dir="auto">{source.entry.original_input}</blockquote>
            {source.entry.original_context ? (
              <p className="hint" dir="auto">
                {source.entry.original_context}
              </p>
            ) : null}
          </>
        ) : (
          <p className="hint">{t("demo.compare.noSource", { unit: side.unit.unit_id })}</p>
        )}
      </div>
      <h4 id="demo-practice-sentence-label">{t("demo.practice.complete")}</h4>
      <p className="french demo-practice-sentence" lang="fr" dir="auto" data-practice-sentence>
        {parts[0]}
        {revealed ? (
          <mark>{used.form}</mark>
        ) : (
          <span className="demo-practice-blank">
            <span aria-hidden="true">_____</span>
            <span className="visually-hidden">{t("demo.practice.blank")}</span>
          </span>
        )}
        {parts[1]}
      </p>
      <div className="demo-practice-choices" role="group" aria-labelledby="demo-practice-sentence-label">
        {options.map((o, i) => (
          <button
            key={i}
            type="button"
            id={`demo-practice-choice-${i}`}
            className={answer === i ? "demo-practice-choice chosen" : "demo-practice-choice"}
            aria-pressed={answer === i}
            aria-disabled={revealed || undefined}
            data-practice-choice={i}
            data-practice-kind={o.side === undefined ? "distractor" : "form"}
            // A form and its tense name, both French; only the brackets are
            // interface text.
            lang="fr"
            onClick={() => choose(i)}
          >
            {o.tense ? t("demo.practice.choice", { form: o.form, tense: o.tense }) : o.form}
          </button>
        ))}
        {!revealed ? (
          <button type="button" className="ghost" id="demo-practice-skip" onClick={() => choose("skip")}>
            {t("demo.practice.skip")}
          </button>
        ) : null}
      </div>
      {item.hint && !revealed ? (
        // R3-052: a short hint before the answer, under the choices so they stay
        // where they were; it never names the form.
        <div className="demo-practice-hint">
          <button type="button" className="ghost" id="demo-practice-hint-toggle" aria-expanded={hint} aria-controls="demo-practice-hint" onClick={() => setHint(!hint)}>
            {t(hint ? "demo.practice.hintHide" : "demo.practice.hintShow")}
          </button>
          <p id="demo-practice-hint" className="hint" hidden={!hint}>
            {t(item.hint)}
          </p>
        </div>
      ) : null}
      <div role="status" className="demo-practice-status">
        {revealed ? (
          <p
            id="demo-practice-outcome"
            tabIndex={-1}
            className="demo-practice-outcome"
            data-practice-outcome={answer === "skip" ? "skip" : chosen?.side === undefined ? "distractor" : chosen.side === item.side ? "used" : "other"}
          >
            {outcome}
          </p>
        ) : null}
      </div>
      {revealed ? (
        <>
          <h4>{t("demo.practice.why")}</h4>
          <ul className="demo-practice-why">
            {choices.map((c, i) => {
              const s = sideOf(i);
              return (
                <li key={`f${i}`} data-practice-form={i === item.side ? "used" : "other"}>
                  <p className="demo-practice-form">
                    {tn(i === item.side ? "demo.practice.formUsed" : "demo.practice.formOther", {
                      form: fr(c.form),
                      tense: <span lang="fr">{c.tense}</span>,
                    })}
                  </p>
                  {s ? (
                    <>
                      <p dir="auto">
                        <span className="french" lang="fr" dir="auto">
                          {s.unit.canonical}
                        </span>
                        {": "}
                        {s.unit.statement}
                      </p>
                      {s.source ? (
                        <MoveLink href={href(s.concept.id, s.unit.unit_id)} id={`demo-practice-src-${s.unit.unit_id}`} onMove={() => onOpenSource(s.concept.id, s.unit.unit_id)}>
                          {t("demo.practice.evidence", { unit: s.unit.unit_id, entry: s.unit.entry_id })}
                        </MoveLink>
                      ) : (
                        <p className="hint">{t("demo.compare.noSource", { unit: s.unit.unit_id })}</p>
                      )}
                    </>
                  ) : null}
                </li>
              );
            })}
            {practice.distractors.map((d) => (
              // R3-053: why a distractor does not work, in the stored interpretation's own words.
              <li key={`d${d.form}`} data-practice-form="distractor">
                <p className="demo-practice-form">{tn("demo.practice.formDistractor", { form: fr(d.form) })}</p>
                {interpretation ? (
                  <>
                    <p className="hint">{t("demo.practice.distractorWhy", { entry: side.unit.entry_id })}</p>
                    <blockquote dir="auto">{interpretation}</blockquote>
                    <MoveLink
                      href={href(side.concept.id, side.unit.unit_id)}
                      id={`demo-practice-why-${side.unit.unit_id}`}
                      onMove={() => onOpenSource(side.concept.id, side.unit.unit_id)}
                    >
                      {t("demo.practice.evidence", { unit: side.unit.unit_id, entry: side.unit.entry_id })}
                    </MoveLink>
                  </>
                ) : (
                  <p className="hint">{t("demo.compare.noInterpretation")}</p>
                )}
              </li>
            ))}
          </ul>
          {item.alternate && item.alternateText ? (
            <div className="demo-practice-alternate" data-practice-alternate>
              <h4>{t("demo.practice.alsoPossible")}</h4>
              <p>{tn(item.alternateText, { other: fr(other.form) })}</p>
            </div>
          ) : null}
          <div className="actions demo-practice-actions">
            {items.length > 1 ? (
              <button type="button" className="primary" id="demo-practice-next" onClick={() => onItem(((index + 1) % items.length) + 1)}>
                {t("demo.practice.next")}
              </button>
            ) : null}
            <button
              type="button"
              className="ghost"
              id="demo-practice-again"
              onClick={() => {
                setAnswer(undefined);
                focusNext.current = `demo-practice-choice-0`;
              }}
            >
              {t("demo.practice.again")}
            </button>
            <button type="button" className="ghost" id="demo-practice-to-pair" onClick={onLeave}>
              {t("demo.practice.toPair")}
            </button>
          </div>
          {/* R3-060: where to go after one question. */}
          <nav className="demo-practice-continue" aria-labelledby="demo-practice-continue-heading">
            <h4 id="demo-practice-continue-heading">{t("demo.practice.continue")}</h4>
            <ul>
              {nextOthers.map((c) => (
                <li key={c.key}>
                  <button type="button" className="ghost" id={`demo-practice-next-${c.key}`} onClick={() => onOpenComparison(c.key, true)}>
                    {t("demo.practice.nextQuestion", { title: t(c.title) })}
                  </button>
                </li>
              ))}
              {/* The guided example is in the comparison's own navigation, just below. */}
              <li>
                <button type="button" className="ghost" id="demo-practice-search" onClick={() => onSearch("")}>
                  {t("demo.start.search")}
                </button>
              </li>
            </ul>
          </nav>
        </>
      ) : (
        <div className="actions demo-practice-actions">
          <button type="button" className="ghost" id="demo-practice-leave" onClick={onLeave}>
            {t("demo.practice.leave")}
          </button>
        </div>
      )}
      <p className="demo-related">
        {/* R3-056: a link to exactly this question; the answer is never in it. */}
        <CopyLink
          fragment={hashForScreen({ kind: "compare", compare: comparison.key, practice: index + 1 })}
          id="demo-practice-copy"
          label="demo.practice.copy"
          done="demo.link.copied"
        />
      </p>
    </section>
  );
}
