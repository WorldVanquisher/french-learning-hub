import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { useI18n } from "../i18n";
import { DEMO_EXAMPLES, resolveExample, type DemoExample, type ExampleResolution, type ResolvedExample } from "./examples";

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: ExampleResolution };

const exampleCardId = (key: string) => `demo-example-${key}`;

// ExamplePicker is the public demo's first step: three authored French
// questions, each opened as a guided example. Opening one records nothing.
export function ExamplePicker({ onOpen }: { onOpen: (key: string) => void }) {
  const { t } = useI18n();
  return (
    <section className="panel demo-examples" aria-labelledby="demo-examples-heading">
      <h2 id="demo-examples-heading" className="library-title">
        {t("demo.examples.heading")}
      </h2>
      <ol className="demo-example-list">
        {DEMO_EXAMPLES.map((ex) => (
          <li key={ex.key}>
            <button type="button" className="demo-example-card" id={exampleCardId(ex.key)} onClick={() => onOpen(ex.key)}>
              <span className="demo-example-title">{t(ex.title)}</span>
              <span className="demo-example-summary">{t(ex.summary)}</span>
              <span className="demo-example-open" aria-hidden="true">
                {t("demo.examples.open")}
              </span>
            </button>
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
}: {
  resolved: ResolvedExample;
  onOpenSource: (conceptId: number, unitId: number) => void;
}) {
  const { t } = useI18n();
  const s = resolved.source;
  const seed = resolved.extracted.find((e) => e.unit.unit_id === s.unit.unit_id);
  return (
    <section className="panel demo-step" aria-labelledby="demo-step-evidence">
      <h3 id="demo-step-evidence">
        <span className="demo-step-n" aria-hidden="true">
          4
        </span>
        {t("demo.example.step.evidence")}
      </h3>
      <p className="hint">
        {t("demo.example.step.evidence.hint", {
          record: s.entry.id,
          extraction: s.extraction.version,
          analysis: s.source_interpretation.analysis.version,
        })}
      </p>
      {seed ? (
        <button type="button" className="primary" onClick={() => onOpenSource(seed.concept.id, seed.unit.unit_id)}>
          {t("demo.example.openEvidence", { unit: seed.unit.canonical })}
        </button>
      ) : null}
    </section>
  );
}

// ExampleScreen walks one example: the learner's question, the units extracted
// from it, and the Concepts they are filed under, all read from the server.
export function ExampleScreen({
  example,
  onBack,
  onSearch,
  onOpenExample,
  onOpenConcept,
  onOpenSource,
}: {
  example: DemoExample;
  onBack: () => void;
  // Runs the example's keyword query in the ordinary search (fallback only).
  onSearch: (q: string) => void;
  onOpenExample: (key: string) => void;
  onOpenConcept: (conceptId: number) => void;
  onOpenSource: (conceptId: number, unitId: number) => void;
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
    heading.current?.focus();
  }, [load.status]);

  const others = DEMO_EXAMPLES.filter((e) => e.key !== example.key);
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
          <button type="button" className="ghost" onClick={() => onSearch(example.query)}>
            {t("demo.example.searchInstead", { q: example.query })}
          </button>
        </div>
      ) : (
        <>
          <section className="panel demo-step" aria-labelledby="demo-step-question">
            <h3 id="demo-step-question">
              <span className="demo-step-n" aria-hidden="true">
                1
              </span>
              {t("demo.example.step.question")}
            </h3>
            <blockquote className="demo-question french" lang="fr">
              {load.data.example.source.entry.original_input}
            </blockquote>
            {load.data.example.source.entry.original_context ? (
              <p className="hint">{load.data.example.source.entry.original_context}</p>
            ) : null}
          </section>

          <section className="panel demo-step" aria-labelledby="demo-step-extracted">
            <h3 id="demo-step-extracted">
              <span className="demo-step-n" aria-hidden="true">
                2
              </span>
              {tp("demo.example.step.extracted", load.data.example.extracted.length)}
            </h3>
            <p className="hint">{t("demo.example.step.extracted.hint")}</p>
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
                        <button type="button" className="link-button" onClick={() => onOpenConcept(concept.id)}>
                          {concept.target}
                        </button>
                      ),
                    })}{" "}
                    <button type="button" className="link-button" onClick={() => onOpenSource(concept.id, unit.unit_id)}>
                      {t("demo.example.howExtracted")}
                    </button>
                  </p>
                </li>
              ))}
            </ul>
          </section>

          <section className="panel demo-step" aria-labelledby="demo-step-concepts">
            <h3 id="demo-step-concepts">
              <span className="demo-step-n" aria-hidden="true">
                3
              </span>
              {tp("demo.example.step.concepts", load.data.example.concepts.length)}
            </h3>
            <p className="hint">{t("demo.example.step.concepts.hint")}</p>
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
                  <button type="button" className="primary" onClick={() => onOpenConcept(c.concept.id)}>
                    {t("demo.example.openConcept")}
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <EvidenceStep resolved={load.data.example} onOpenSource={onOpenSource} />
        </>
      )}

      <section className="panel demo-next" aria-labelledby="demo-next-heading">
        <h3 id="demo-next-heading">{t("demo.example.next")}</h3>
        <div className="actions">
          {others.map((o) => (
            <button key={o.key} type="button" className="ghost" onClick={() => onOpenExample(o.key)}>
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
