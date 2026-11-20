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
//    phone too. Wide screens put the two sides next to each other.
// 2. "Show the evidence": the rest of each side (the learner's question, the
//    stored interpretation, the rule, the Concept, links to the source and the
//    Concept) behind one disclosure button. It starts open on wide screens and
//    closed on phones; the visitor's choice is kept for this visit (visit.ts),
//    and coming back to a control inside it opens it again. Opening or closing
//    it never changes the address: the comparison's link stays the same.
// 3. An optional choose-first practice question, for a comparison that has one
//    (Practice below), with the pair hidden while a question is unanswered.
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
}: {
  comparison: DemoComparison;
  onBack: () => void;
  // A side this build lacks: its keyword query in the ordinary search.
  onSearch: (q: string) => void;
  onOpenComparison: (key: string) => void;
  // The guided example both units come from (`comparison.example`).
  onOpenExample?: (key: string) => void;
  // The demo links of a Concept or a source opened from this comparison.
  href: (conceptId: number, unitId?: number) => string;
  onOpenConcept: (conceptId: number) => void;
  onOpenSource: (conceptId: number, unitId: number) => void;
  // The sides as this build resolved them (the 60-second tour's next step).
  onReady?: (sides: SideResolution[]) => void;
  returnFocus?: MutableRefObject<string | null>;
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
  const sides = load.status === "ready" ? load.sides : [];
  const found = sides.filter((s): s is FoundSide => s.kind === "found");
  const entries = new Set(found.map((s) => s.unit.entry_id));
  const items = readyItems(comparison, sides);
  const practicing = visit.practice && items.length > 0;
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
  const startPractice = () => {
    setVisit({ ...visit, practice: true });
    focusNext.current = "demo-practice-heading";
  };
  const leavePractice = () => {
    setVisit({ ...visit, practice: false });
    focusNext.current = "demo-compare-pair-heading";
  };
  return (
    <div className="demo-compare">
      <section className="panel" aria-labelledby="demo-compare-heading">
        <p className="demo-eyebrow">{t("demo.compare.eyebrow")}</p>
        <h2 id="demo-compare-heading" ref={heading} tabIndex={-1} className="library-title">
          {t(comparison.title)}
        </h2>
        <p>{t(comparison.summary)}</p>
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
          comparison={comparison}
          items={items}
          visit={visit}
          setVisit={setVisit}
          focusNext={focusNext}
          href={href}
          onOpenSource={onOpenSource}
          onLeave={leavePractice}
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
              <button type="button" className="primary" id="demo-practice-start" onClick={startPractice}>
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

// Practice (R2): choose the form that completes one example before seeing it.
// The learner's question and its recorded context come first; the example
// follows with its form blanked; the two forms are offered in side order, with
// an explicit skip. The answer, both forms' rules with links to their
// evidence, and a valid alternative (where the item has one) are shown only
// after a choice or a skip. The outcome is announced (a status region) and
// focused. Answers stay in this page's memory (visit.ts): no score, no record,
// no request beyond the reads the comparison already made.
function Practice({
  comparison,
  items,
  visit,
  setVisit,
  focusNext,
  href,
  onOpenSource,
  onLeave,
}: {
  comparison: DemoComparison;
  items: ReadyItem[];
  visit: CompareVisit;
  setVisit: (v: CompareVisit) => void;
  focusNext: MutableRefObject<string | null>;
  href: (conceptId: number, unitId?: number) => string;
  onOpenSource: (conceptId: number, unitId: number) => void;
  onLeave: () => void;
}) {
  const { t, tn } = useI18n();
  const choices = comparison.practice!.choices;
  const index = Math.min(Math.max(visit.item, 0), items.length - 1);
  const { item, side, parts } = items[index];
  const answer: PracticeAnswer | undefined = visit.answers[index];
  const revealed = answer !== undefined;
  const used = choices[item.side];
  const other = choices[item.side === 0 ? 1 : 0];
  const source = side.source;
  const setAnswer = (a: PracticeAnswer | undefined) => {
    const answers = [...visit.answers];
    answers[index] = a;
    setVisit({ ...visit, item: index, answers });
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
  // Each form's rule and evidence: the unit of the side whose example uses it.
  const sideOf = (i: number) => items.find((x) => x.item.side === i)?.side;
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
        {choices.map((c, i) => (
          <button
            key={i}
            type="button"
            id={`demo-practice-choice-${i}`}
            className={answer === i ? "demo-practice-choice chosen" : "demo-practice-choice"}
            aria-pressed={answer === i}
            aria-disabled={revealed || undefined}
            data-practice-choice={i}
            // A form and its tense name, both French; only the brackets are
            // interface text.
            lang="fr"
            onClick={() => choose(i)}
          >
            {t("demo.practice.choice", { form: c.form, tense: c.tense })}
          </button>
        ))}
        {!revealed ? (
          <button type="button" className="ghost" id="demo-practice-skip" onClick={() => choose("skip")}>
            {t("demo.practice.skip")}
          </button>
        ) : null}
      </div>
      <div role="status" className="demo-practice-status">
        {revealed ? (
          <p id="demo-practice-outcome" tabIndex={-1} className="demo-practice-outcome" data-practice-outcome={answer === "skip" ? "skip" : answer === item.side ? "used" : "other"}>
            {answer === "skip"
              ? tn("demo.practice.skipped", { form: fr(used.form) })
              : answer === item.side
                ? tn("demo.practice.same", { form: fr(used.form) })
                : tn(item.alternate ? "demo.practice.chosenOtherAlso" : "demo.practice.chosenOther", { chosen: fr(other.form), form: fr(used.form) })}
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
                <li key={i} data-practice-form={i === item.side ? "used" : "other"}>
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
          </ul>
          {item.alternate && item.alternateText ? (
            <div className="demo-practice-alternate" data-practice-alternate>
              <h4>{t("demo.practice.alsoPossible")}</h4>
              <p>{tn(item.alternateText, { other: fr(other.form) })}</p>
            </div>
          ) : null}
          <div className="actions demo-practice-actions">
            {items.length > 1 ? (
              <button
                type="button"
                className="primary"
                id="demo-practice-next"
                onClick={() => {
                  setVisit({ ...visit, item: (index + 1) % items.length });
                  focusNext.current = "demo-practice-heading";
                }}
              >
                {t("demo.practice.next")}
              </button>
            ) : null}
            <button
              type="button"
              className="ghost"
              id="demo-practice-again"
              onClick={() => {
                setAnswer(undefined);
                focusNext.current = "demo-practice-choice-0";
              }}
            >
              {t("demo.practice.again")}
            </button>
            <button type="button" className="ghost" id="demo-practice-to-pair" onClick={onLeave}>
              {t("demo.practice.toPair")}
            </button>
          </div>
        </>
      ) : (
        <div className="actions demo-practice-actions">
          <button type="button" className="ghost" id="demo-practice-leave" onClick={onLeave}>
            {t("demo.practice.leave")}
          </button>
        </div>
      )}
    </section>
  );
}
