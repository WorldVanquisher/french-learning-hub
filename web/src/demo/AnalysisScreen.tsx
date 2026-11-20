import { useEffect, useRef, useState, type MouseEvent, type MutableRefObject } from "react";
import { ApiError } from "../api/client";
import { EffectiveText, StoredText } from "../components/ExplanationText";
import { useI18n } from "../i18n";
import { resolveExample, type DemoExample, type ExampleResolution } from "./examples";
import { focusControl } from "./history";
import { CORRECTION_REPLAY } from "./journeyFixtures";

// R5: a guided example's analysis and how a correction is recorded
// (`#analysis=<example>`, the guided tour's step 2).
//
// The stored analysis is read from this demo's server (the source record of the
// example's seed unit: its stored interpretation). Below it, a fixture replay
// (journeyFixtures.ts), always labelled as such, shows how the private workbench
// records a person's correction of that analysis: as a new record, with the
// analysis unchanged and the effective interpretation becoming the correction.
// Nothing here is written anywhere.

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: ExampleResolution };

export function AnalysisScreen({
  example,
  onBack,
  href,
  onOpenSource,
  onReady,
  returnFocus,
}: {
  example: DemoExample;
  onBack: () => void;
  // The source screen of a unit (its link and the in-page move to it).
  href: (conceptId: number, unitId: number) => string;
  onOpenSource: (conceptId: number, unitId: number) => void;
  // The seed unit, once known (the guided tour's next step opens its source).
  onReady?: (seed: { conceptId: number; unitId: number }) => void;
  returnFocus?: MutableRefObject<string | null>;
}) {
  const { t, status } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [retry, setRetry] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    let active = true;
    setLoad({ status: "loading" });
    resolveExample(example)
      .then((data) => {
        if (!active) return;
        setLoad({ status: "ready", data });
        if (data.kind === "found") {
          const seed = data.example.source.unit;
          const concept = data.example.extracted.find((e) => e.unit.unit_id === seed.unit_id)?.concept.id ?? data.example.source.annotation.current_concept_id;
          if (concept !== null && concept !== undefined) onReady?.({ conceptId: concept, unitId: seed.unit_id });
        }
      })
      .catch((e: unknown) => active && setLoad({ status: "error", message: e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e) }));
    return () => {
      active = false;
    };
  }, [example, retry]);
  // Coming back: the control that left this screen, if it is this screen's own
  // (R4-DEM-030); otherwise the heading.
  useEffect(() => {
    const id = returnFocus?.current;
    if (id && load.status !== "loading") {
      const el = document.getElementById(id);
      if (el && heading.current?.closest(".demo-analysis")?.contains(el)) {
        returnFocus.current = null;
        if (focusControl(el)) return;
      }
    }
    heading.current?.focus();
  }, [load.status]);

  const found = load.status === "ready" && load.data.kind === "found" ? load.data.example : null;
  const replay = found && example.key === CORRECTION_REPLAY.example ? CORRECTION_REPLAY : null;
  const seedConcept = found ? (found.extracted.find((e) => e.unit.unit_id === found.source.unit.unit_id)?.concept.id ?? found.source.annotation.current_concept_id) : null;
  const move = (e: MouseEvent<HTMLAnchorElement>, conceptId: number, unitId: number) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    onOpenSource(conceptId, unitId);
  };
  return (
    <div className="demo-analysis">
      <section className="panel" aria-labelledby="demo-analysis-heading">
        <p className="demo-eyebrow">{t("demo.analysis.eyebrow")}</p>
        <h2 id="demo-analysis-heading" ref={heading} tabIndex={-1} className="library-title">
          {t(example.title)}
        </h2>
        <p className="hint">{t("demo.analysis.lead")}</p>
        <div className="actions">
          <button type="button" className="ghost" id="demo-analysis-back" onClick={onBack}>
            {t("demo.example.backTo", { title: t(example.title) })}
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
      ) : !found ? (
        <p className="hint" role="status">
          {t("demo.analysis.missing")}
        </p>
      ) : (
        <>
          <section className="panel" aria-labelledby="demo-analysis-question">
            <h3 id="demo-analysis-question">{t("demo.example.step.question")}</h3>
            <blockquote className="demo-question french" lang={example.lang} dir="auto">
              {found.source.entry.original_input}
            </blockquote>
          </section>
          <section className="panel" aria-labelledby="demo-analysis-stored" data-analysis-stored>
            <h3 id="demo-analysis-stored">{t("demo.analysis.stored", { version: found.source.source_interpretation.analysis.version })}</h3>
            <p className="hint">{t("demo.analysis.storedHint", { entry: found.source.entry.id })}</p>
            <dl className="demo-analysis-fields">
              <dt>{t("demo.analysis.explanation")}</dt>
              <dd>
                <StoredText
                  primary={found.source.source_interpretation.analysis.explanation}
                  variants={found.source.source_interpretation.analysis.explanations}
                  kind="explanation"
                />
              </dd>
              <dt>{t("demo.analysis.category")}</dt>
              <dd>{found.source.source_interpretation.analysis.category}</dd>
              <dt>{t("demo.analysis.confidence")}</dt>
              <dd>{found.source.source_interpretation.analysis.confidence}</dd>
              <dt>{t("demo.analysis.analyzer")}</dt>
              <dd>
                <code>{found.source.source_interpretation.analysis.analyzer}</code>
              </dd>
              <dt>{t("demo.analysis.review")}</dt>
              <dd data-analysis-review>{status(found.source.source_interpretation.effective.resolution)}</dd>
            </dl>
          </section>
          {replay ? (
            <section className="panel demo-replay" aria-labelledby="demo-analysis-replay" data-fixture-replay="correction">
              <p className="demo-replay-tag">{t("demo.replay.tag")}</p>
              <h3 id="demo-analysis-replay">{t("demo.analysis.replayHeading")}</h3>
              <p className="hint">{t("demo.analysis.replayHint")}</p>
              <dl className="demo-analysis-fields">
                <dt>{t("demo.analysis.replayAction")}</dt>
                <dd>{t("demo.analysis.replayCorrected")}</dd>
                <dt>{t("demo.analysis.replayText")}</dt>
                <dd>
                  <StoredText primary={replay.corrected.en} variants={replay.corrected} kind="explanation" />
                </dd>
              </dl>
              <h4>{t("demo.analysis.effective")}</h4>
              <p data-analysis-effective>
                <EffectiveText
                  fallback={replay.corrected.en}
                  original={found.source.source_interpretation.analysis.explanation}
                  originalVariants={found.source.source_interpretation.analysis.explanations}
                  effective={{ en: { text: replay.corrected.en, basis: "corrected" }, zh: { text: replay.corrected.zh, basis: "corrected" } }}
                />
              </p>
              <p className="hint">{t("demo.analysis.effectiveHint")}</p>
            </section>
          ) : null}
          {seedConcept !== null && seedConcept !== undefined ? (
            <p className="demo-related">
              <a href={href(seedConcept, found.source.unit.unit_id)} id="demo-analysis-next" onClick={(e) => move(e, seedConcept, found.source.unit.unit_id)}>
                {t("demo.analysis.next", { unit: found.source.unit.unit_id })}
              </a>
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
