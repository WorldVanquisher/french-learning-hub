import type { UnitTarget } from "../navigation";
import { useI18n, type MessageKey } from "../i18n";
import type { NextAction, RecordStage as Stage, StepState } from "./recordStage";

const stepTag: Record<StepState, MessageKey> = {
  done: "stage.tag.done",
  pending: "stage.tag.pending",
  blocked: "stage.tag.blocked",
  unknown: "stage.tag.unknown",
};

// RecordStage shows where one record is in the daily journey and the next
// action. It is read-only: every line restates what the record's own reads
// returned (see recordStage.ts), and the only control navigates to Concept Review.
export function RecordStage({
  entryId,
  stage,
  onNavigateToUnit,
}: {
  entryId: number;
  stage: Stage;
  onNavigateToUnit?: (target: UnitTarget) => void;
}) {
  const { t, tp, status } = useI18n();
  const { analysis, extraction, decisions, next } = stage;
  const latest = analysis.facts.status === "ready" ? analysis.facts.latest : undefined;
  const ex = extraction.facts.status === "ready" ? extraction.facts : null;

  const analysisLine =
    latest === undefined
      ? t("stage.analysis.unknown")
      : latest === null
        ? t("stage.analysis.none")
        : t("stage.analysis.latest", { version: latest.version, resolution: status(latest.resolution) });
  const extractionLine = !ex
    ? t("stage.extraction.unknown")
    : ex.current
      ? tp("stage.extraction.current", ex.current.unitIds.length, { version: ex.current.version })
      : ex.anyStored
        ? t("stage.extraction.noCurrent")
        : t("stage.extraction.none");
  const decisionsLine =
    decisions.total === null
      ? ex && !ex.current
        ? t("stage.decisions.notYet")
        : t("stage.decisions.unknown")
      : decisions.total === 0
        ? t("stage.decisions.zeroUnits")
        : decisions.awaiting === null
          ? t("stage.decisions.unknown")
          : decisions.awaiting > 0
            ? t("stage.decisions.awaiting", { awaiting: decisions.awaiting, total: decisions.total })
            : decisions.filed !== null && decisions.invalid !== null
              ? t("stage.decisions.completeCounts", { total: decisions.total, filed: decisions.filed, invalid: decisions.invalid })
              : t("stage.decisions.complete", { total: decisions.total });

  return (
    <section className="panel record-stage" aria-label={t("stage.region", { id: entryId })}>
      <h2>{t("stage.title")}</h2>
      <ol className="stage-steps">
        <Step n={1} title={t("stage.step.analysis")} purpose={t("stage.step.analysis.purpose")} state={analysis.state} line={analysisLine} />
        <Step n={2} title={t("stage.step.extraction")} purpose={t("stage.step.extraction.purpose")} state={extraction.state} line={extractionLine} />
        <Step n={3} title={t("stage.step.decisions")} purpose={t("stage.step.decisions.purpose")} state={decisions.state} line={decisionsLine} />
      </ol>
      <NextStep next={next} entryId={entryId} onNavigateToUnit={onNavigateToUnit} />
      {stage.analysisReviewPending && latest ? (
        <p className="hint">{t("stage.analysisReviewPending", { version: latest.version })}</p>
      ) : null}
      <p className="hint">{t("stage.derived")}</p>
    </section>
  );
}

function Step({ n, title, purpose, state, line }: { n: number; title: string; purpose: string; state: StepState; line: string }) {
  const { t } = useI18n();
  return (
    <li className={`stage-step stage-${state}`}>
      <strong>
        {t("stage.step.heading", { n, title })}
      </strong>{" "}
      <span className={`tag stage-tag-${state}`}>{t(stepTag[state])}</span>
      <div>{line}</div>
      <div className="hint">{purpose}</div>
    </li>
  );
}

function NextStep({
  next,
  entryId,
  onNavigateToUnit,
}: {
  next: NextAction;
  entryId: number;
  onNavigateToUnit?: (target: UnitTarget) => void;
}) {
  const { t } = useI18n();
  let text: string;
  switch (next.kind) {
    case "loading":
      text = t("stage.next.loading");
      break;
    case "unknown":
      text = t("stage.next.unknown");
      break;
    case "analyze":
      text = t("stage.next.analyze");
      break;
    case "reanalyze":
      text = t("stage.next.reanalyze", { version: next.version });
      break;
    case "reviewAnalysis":
      text = t("stage.next.reviewAnalysis", { version: next.version });
      break;
    case "extract":
      text = t("stage.next.extract");
      break;
    case "selectExtraction":
      text = t("stage.next.selectExtraction");
      break;
    case "zeroUnits":
      text = t("stage.next.zeroUnits", { version: next.version });
      break;
    case "reviewUnit":
      text = t("stage.next.reviewUnit", { awaiting: next.awaiting, total: next.total, unit: next.unitId });
      break;
    case "complete":
      text = t("stage.next.complete");
      break;
  }
  return (
    <div className="banner info stage-next" role="status">
      <strong>{t("stage.next.label")}</strong> {text}
      {next.kind === "reviewUnit" && onNavigateToUnit ? (
        <>
          {" "}
          <button
            type="button"
            className="ghost"
            onClick={() =>
              onNavigateToUnit({
                kind: "review",
                entryId,
                unitId: next.unitId,
                extractionId: next.extractionId,
                extractionVersion: next.extractionVersion,
              })
            }
          >
            {t("stage.next.open", { id: next.unitId })}
          </button>
        </>
      ) : null}
    </div>
  );
}
