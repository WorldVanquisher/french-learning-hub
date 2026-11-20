import { useEffect, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { useI18n } from "../i18n";
import { DEMO_EXAMPLES, resolveExample, type DemoExample, type ExampleResolution, type ResolvedExample } from "./examples";
import { focusControl } from "./history";
import { WALK_STEPS } from "./deepLink";
import { CONFUSION, findComparison } from "./comparisons";

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: ExampleResolution };

const exampleCardId = (key: string) => `demo-example-${key}`;

// The walkthrough's steps, in order: the headings each step focuses.
const STEP_HEADINGS = ["demo-step-question", "demo-step-extracted", "demo-step-concepts", "demo-step-evidence"] as const;
const STEP_TITLES = ["demo.walk.title.1", "demo.walk.title.2", "demo.walk.title.3", "demo.walk.title.4"] as const;

function focusStep(step: number) {
  const el = document.getElementById(STEP_HEADINGS[step - 1]);
  if (!el) return;
  el.focus({ preventScroll: true });
  el.scrollIntoView?.({ block: "start" });
}

// The words of the learner's question that reappear in the wording of the
// rules extracted from it are marked, so a visitor can see what the extraction
// kept and what it added. Words are compared without case or accents; a rule
// word of five letters or more also marks a longer form of it in the question
// (« remplace » marks « remplacent »). Shorter words must match whole, so
// « de » never marks « demain ». One-letter words are ignored.
const fold = (w: string) => w.toLocaleLowerCase("fr").normalize("NFD").replace(/\p{M}/gu, "");
function sharedWordTest(wordings: readonly string[]): ((word: string) => boolean) | null {
  const words = [...new Set(wordings.flatMap((w) => w.split(/[^\p{L}]+/u)).map(fold).filter((w) => w.length >= 2))];
  if (words.length === 0) return null;
  return (word: string) => {
    const f = fold(word);
    return words.some((w) => f === w || (w.length >= 5 && f.startsWith(w)));
  };
}
export function markSharedWords(text: string, wordings: readonly string[]): ReactNode {
  const shared = sharedWordTest(wordings);
  if (!shared) return text;
  return text.split(/(\p{L}+)/u).map((part, i) => (i % 2 === 1 && shared(part) ? <mark key={i}>{part}</mark> : part));
}
// The question's words that reappear in the rules, in question order, once each.
export function sharedWords(text: string, wordings: readonly string[]): string[] {
  const shared = sharedWordTest(wordings);
  if (!shared) return [];
  return [...new Set(text.split(/(\p{L}+)/u).filter((part, i) => i % 2 === 1 && shared(part)))];
}

// WalkBar is the optional walkthrough: one step at a time, each step its own
// history entry and link (`#example=…&step=N`), so Back and Forward retrace the
// steps and a shared link opens at that step. The whole example stays on the
// page. Before the walk starts, the bar is a start button under the title;
// during it, the bar sits inside the current step, under its heading, so the
// way on is where the visitor is reading (on a phone the title is off-screen).
// ChangedWords: at step 2, the question's words that reappear in its rules,
// marked, beside the rules (the question itself is above, often off-screen).
function ChangedWords({ question, wordings }: { question: string; wordings: readonly string[] }) {
  const { t, tn } = useI18n();
  const words = sharedWords(question, wordings);
  if (words.length === 0) return <p className="demo-walk-changed">{t("demo.walk.changedNone")}</p>;
  return (
    <p className="demo-walk-changed">
      {tn("demo.walk.changed", {
        words: (
          <span lang="fr">
            {words.map((w, i) => (
              <span key={w}>
                {i > 0 ? t("library.fieldSeparator") : ""}
                <mark>{w}</mark>
              </span>
            ))}
          </span>
        ),
      })}
    </p>
  );
}

function WalkBar({ step, onStep }: { step?: number; onStep: (step: number) => void }) {
  const { t } = useI18n();
  if (!step)
    return (
      <p className="demo-walk-start">
        <button type="button" className="primary" id="demo-walk-start" onClick={() => onStep(1)}>
          {t("demo.walk.start")}
        </button>
      </p>
    );
  return (
    <nav className="demo-walk" aria-label={t("demo.walk.region")}>
      <p className="demo-walk-where">{t("demo.walk.where", { n: step, total: WALK_STEPS, title: t(STEP_TITLES[step - 1]) })}</p>
      <div className="actions">
        <button type="button" className="ghost" id="demo-walk-prev" disabled={step <= 1} onClick={() => onStep(step - 1)}>
          {t("demo.walk.previous")}
        </button>
        <button type="button" className="primary" id="demo-walk-next" disabled={step >= WALK_STEPS} onClick={() => onStep(step + 1)}>
          {t("demo.walk.next")}
        </button>
      </div>
    </nav>
  );
}

// ExamplePicker is the public demo's first step: the authored learner
// questions (three in French, the most beginner-friendly first, and one in
// English), each opened as a guided example. A card leads with the learner's
// question as written (the visitor picks by the question itself, in every
// interface language), then says in the interface language what the example
// shows. Opening one records nothing. Under the card of the example a common
// confusion comes from, one more way in opens its practice question (R3-042).
export function ExamplePicker({ onOpen, onConfusion }: { onOpen: (key: string) => void; onConfusion?: (compare: string) => void }) {
  const { t, tn } = useI18n();
  // A local binding, so the guard below also narrows it inside the click handler.
  const confusion = CONFUSION;
  return (
    <section className="panel demo-examples" aria-labelledby="demo-examples-heading">
      <h2 id="demo-examples-heading" className="library-title" tabIndex={-1}>
        {t("demo.examples.heading")}
      </h2>
      <ol className="demo-example-list">
        {DEMO_EXAMPLES.map((ex) => (
          <li key={ex.key}>
            <button type="button" className="demo-example-card" id={exampleCardId(ex.key)} onClick={() => onOpen(ex.key)}>
              <span className="demo-example-question french" lang={ex.lang} dir="auto">
                {ex.question}
              </span>
              <span className="demo-example-title">{t(ex.title)}</span>
              <span className="demo-example-open" aria-hidden="true">
                {t("demo.examples.open")}
              </span>
            </button>
            {confusion && onConfusion && confusion.example === ex.key ? (
              <button type="button" className="ghost demo-example-confusion" id="demo-example-confusion" onClick={() => onConfusion(confusion.compare)}>
                {tn("demo.examples.confusion", {
                  form: (
                    <span lang="fr" className="french">
                      {confusion.form}
                    </span>
                  ),
                })}
              </button>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

export function focusExampleCard(key: string) {
  document.getElementById(exampleCardId(key))?.focus();
}

// EvidenceStep is the walk's last step: the record this question became and the
// extraction and interpretation its units came from, with the way to the
// evidence screen of the unit the example was found by.
function EvidenceStep({
  resolved,
  onOpenSource,
  current = false,
  walk = null,
}: {
  resolved: ResolvedExample;
  onOpenSource: (conceptId: number, unitId: number) => void;
  // The walkthrough is at this step, and its bar.
  current?: boolean;
  walk?: ReactNode;
}) {
  const { t } = useI18n();
  const s = resolved.source;
  const seed = resolved.extracted.find((e) => e.unit.unit_id === s.unit.unit_id);
  return (
    <section className={`panel demo-step${current ? " demo-step-current" : ""}`} aria-labelledby="demo-step-evidence" aria-current={current ? "step" : undefined}>
      <h3 id="demo-step-evidence" tabIndex={-1}>
        <span className="demo-step-n" aria-hidden="true">
          4
        </span>
        {t("demo.example.step.evidence")}
      </h3>
      {walk}
      <p className="hint">
        {t("demo.example.step.evidence.hint", {
          record: s.entry.id,
          extraction: s.extraction.version,
          analysis: s.source_interpretation.analysis.version,
        })}
      </p>
      {seed ? (
        <button
          type="button"
          className="primary"
          id="demo-ex-evidence"
          onClick={() => onOpenSource(seed.concept.id, seed.unit.unit_id)}
        >
          {t("demo.example.openEvidence", { unit: seed.unit.canonical })}
        </button>
      ) : null}
    </section>
  );
}

// ExampleScreen walks one example: the learner's question, the units extracted
// from it, and the Concepts they are filed under, all read from the server.
// Every control that opens another screen has an id, so coming back focuses it
// (`returnFocus`, demo/history.ts); opening the example focuses its heading.
export function ExampleScreen({
  example,
  onBack,
  onSearch,
  onOpenExample,
  onOpenComparison,
  onOpenConcept,
  onOpenSource,
  step,
  onStep,
  returnFocus,
}: {
  example: DemoExample;
  onBack: () => void;
  // Runs the example's keyword query in the ordinary search: step 3's "find it
  // by search", and the fallback when this build lacks the example.
  onSearch: (q: string) => void;
  onOpenExample: (key: string) => void;
  // The comparison built from this example's units (`example.compare`), if any.
  onOpenComparison?: (key: string) => void;
  onOpenConcept: (conceptId: number) => void;
  onOpenSource: (conceptId: number, unitId: number) => void;
  // The walkthrough step shown (none: the walkthrough is not started), and
  // how to move to another step (a new history entry).
  step?: number;
  onStep?: (step: number) => void;
  returnFocus?: MutableRefObject<string | null>;
}) {
  const { t, tp, tn, status } = useI18n();
  const [retry, setRetry] = useState(0);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    let active = true;
    setLoad({ status: "loading" });
    resolveExample(example)
      .then((data) => active && setLoad({ status: "ready", data }))
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
  }, [example, retry]);
  useEffect(() => {
    const id = returnFocus?.current;
    if (id && load.status !== "loading") {
      returnFocus.current = null;
      const el = document.getElementById(id);
      if (el && heading.current?.closest(".demo-example")?.contains(el) && focusControl(el)) return;
    }
    if (step && load.status === "ready" && load.data.kind === "found") {
      focusStep(step);
      return;
    }
    heading.current?.focus();
  }, [load.status]);
  // A step change on the same example (Next, Previous, Back, Forward): the
  // control that left the entry when coming back to it, else the step's heading.
  const shownStep = useRef(step);
  useEffect(() => {
    if (shownStep.current === step) return;
    shownStep.current = step;
    if (load.status !== "ready" || load.data.kind !== "found") return;
    const id = returnFocus?.current;
    if (id) {
      returnFocus.current = null;
      const el = document.getElementById(id);
      if (el && heading.current?.closest(".demo-example")?.contains(el) && focusControl(el)) return;
    }
    if (step) focusStep(step);
    else heading.current?.focus();
  }, [step]);
  const found = load.status === "ready" && load.data.kind === "found" ? load.data.example : null;
  const current = (n: number) => (step === n ? { "aria-current": "step" as const } : {});
  const stepClass = (n: number) => `panel demo-step${step === n ? " demo-step-current" : ""}`;
  const walkHere = (n: number) => (onStep && step === n ? <WalkBar step={step} onStep={onStep} /> : null);

  const others = DEMO_EXAMPLES.filter((e) => e.key !== example.key);
  const related = findComparison(example.compare);
  return (
    <div className="demo-example">
      <section className="panel" aria-label={t("demo.example.region")}>
        <p className="demo-eyebrow">{t("demo.example.eyebrow")}</p>
        <h2 ref={heading} tabIndex={-1} className="library-title">
          {t(example.title)}
        </h2>
        <button type="button" className="ghost" onClick={onBack}>
          {t("demo.example.back")}
        </button>
        {onStep && found && !step ? <WalkBar onStep={onStep} /> : null}
      </section>

      {load.status === "loading" ? (
        <p className="empty" role="status">
          {t("demo.example.loading")}
        </p>
      ) : load.status === "error" ? (
        <div className="banner error" role="alert">
          {t("demo.example.failed", { message: load.message })}{" "}
          <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
            {t("common.tryAgain")}
          </button>
        </div>
      ) : load.data.kind === "missing" ? (
        <div className="banner info" role="status">
          {t("demo.example.missing")}{" "}
          <button type="button" className="ghost" id="demo-ex-search" onClick={() => onSearch(example.query)}>
            {t("demo.example.searchInstead", { q: example.query })}
          </button>
        </div>
      ) : (
        <>
          <section className={stepClass(1)} aria-labelledby="demo-step-question" {...current(1)}>
            <h3 id="demo-step-question" tabIndex={-1}>
              <span className="demo-step-n" aria-hidden="true">
                1
              </span>
              {t("demo.example.step.question")}
            </h3>
            {walkHere(1)}
            {/* Learner text keeps its own direction (dir="auto"): a question that
                starts in a right-to-left script reads in its own order. */}
            <blockquote className="demo-question french" lang={example.lang} dir="auto">
              {step && step >= 2
                ? markSharedWords(load.data.example.source.entry.original_input, load.data.example.extracted.map((e) => e.unit.canonical))
                : load.data.example.source.entry.original_input}
            </blockquote>
            {load.data.example.source.entry.original_context ? (
              <p className="hint" dir="auto">
                {load.data.example.source.entry.original_context}
              </p>
            ) : null}
          </section>

          <section className={stepClass(2)} aria-labelledby="demo-step-extracted" {...current(2)}>
            <h3 id="demo-step-extracted" tabIndex={-1}>
              <span className="demo-step-n" aria-hidden="true">
                2
              </span>
              {tp("demo.example.step.extracted", load.data.example.extracted.length)}
            </h3>
            {walkHere(2)}
            <p className="hint">{t("demo.example.step.extracted.hint")}</p>
            {step === 2 ? <ChangedWords question={load.data.example.source.entry.original_input} wordings={load.data.example.extracted.map((e) => e.unit.canonical)} /> : null}
            <ul className="demo-units">
              {load.data.example.extracted.map(({ unit, concept }) => (
                <li key={unit.unit_id} className="demo-unit">
                  <p className="demo-unit-canonical" lang="fr">
                    {unit.canonical}
                  </p>
                  <p>{unit.statement}</p>
                  {unit.example ? (
                    <p className="hint">
                      {t("library.frenchExample")}{" "}
                      <span lang="fr" className="french">
                        {unit.example}
                      </span>
                    </p>
                  ) : null}
                  <p className="hint">
                    {tn("demo.example.filedUnder", {
                      concept: (
                        <button
                          type="button"
                          className="link-button"
                          id={`demo-ex-concept-of-${unit.unit_id}`}
                          onClick={() => onOpenConcept(concept.id)}
                        >
                          {concept.target}
                        </button>
                      ),
                    })}{" "}
                    <button
                      type="button"
                      className="link-button"
                      id={`demo-ex-source-${unit.unit_id}`}
                      onClick={() => onOpenSource(concept.id, unit.unit_id)}
                    >
                      {t("demo.example.howExtracted")}
                    </button>
                  </p>
                </li>
              ))}
            </ul>
          </section>

          <section className={stepClass(3)} aria-labelledby="demo-step-concepts" {...current(3)}>
            <h3 id="demo-step-concepts" tabIndex={-1}>
              <span className="demo-step-n" aria-hidden="true">
                3
              </span>
              {tp("demo.example.step.concepts", load.data.example.concepts.length)}
            </h3>
            {walkHere(3)}
            <p className="hint">{t("demo.example.step.concepts.hint")}</p>
            {/* The Concept is now searchable: the example's own keyword query
                finds it, and the results mark the words that matched. */}
            <p className="demo-find">
              {tn("demo.example.findBySearch", {
                query: (
                  <button type="button" className="ghost" id={`demo-ex-find-${example.key}`} onClick={() => onSearch(example.query)}>
                    {t("demo.example.findBySearch.button", { q: example.query })}
                  </button>
                ),
              })}
            </p>
            <ul className="demo-units">
              {load.data.example.concepts.map((c) => (
                <li key={c.concept.id} className="demo-unit">
                  <p className="demo-concept-title">
                    {c.concept.target} <span className={`tag ${c.concept.state}`}>{status(c.concept.state)}</span>
                  </p>
                  <p className="hint">
                    {c.supporting > c.fromThisQuestion
                      ? tp("demo.example.conceptEvidence.more", c.supporting, { mine: c.fromThisQuestion, others: c.supporting - c.fromThisQuestion })
                      : tp("demo.example.conceptEvidence.only", c.supporting)}
                  </p>
                  <button
                    type="button"
                    className="primary"
                    id={`demo-ex-open-concept-${c.concept.id}`}
                    onClick={() => onOpenConcept(c.concept.id)}
                  >
                    {t("demo.example.openConcept")}
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <EvidenceStep resolved={load.data.example} onOpenSource={onOpenSource} current={step === 4} walk={walkHere(4)} />
        </>
      )}

      <section className="panel demo-next" aria-labelledby="demo-next-heading">
        <h3 id="demo-next-heading">{t("demo.example.next")}</h3>
        {related && onOpenComparison ? (
          <p className="demo-related">
            <button type="button" className="ghost" id={`demo-ex-compare-${related.key}`} onClick={() => onOpenComparison(related.key)}>
              {t("demo.example.compareRelated", { title: t(related.title) })}
            </button>
          </p>
        ) : null}
        <div className="actions">
          {others.map((o) => (
            <button key={o.key} type="button" className="ghost" id={`demo-ex-next-${o.key}`} onClick={() => onOpenExample(o.key)}>
              {t(o.title)}
            </button>
          ))}
          <button type="button" className="ghost" onClick={onBack}>
            {t("demo.example.searchYourself")}
          </button>
        </div>
      </section>
    </div>
  );
}
