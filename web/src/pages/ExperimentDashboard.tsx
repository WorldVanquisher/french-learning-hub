import { useEffect, useState } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import type {
  AnnotationDatasetQualityReport,
  RetrievalComparisonReport,
} from "../types/experiment";
import { useI18n } from "../i18n";

// Retriever names are identifiers of backend experiments and are never translated.
const retrieverLabels: Record<string, string> = {
  exact_signature_retriever_v1: "Exact Signature",
  weighted_lexical_retriever_v1: "Weighted Lexical",
  bm25_retriever_v1: "BM25",
  embedding_retriever_v1: "Embedding",
};

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return `(${error.status}) ${error.message}`;
  }
  return error instanceof Error ? error.message : String(error);
}

export function formatRetrievalMetric(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function QualitySummary({ report }: { report: AnnotationDatasetQualityReport }) {
  const { t, tn } = useI18n();
  const { summary, label_inventory: labels } = report;

  return (
    <>
      <div className={`quality-state ${report.valid ? "valid" : "invalid"}`}>
        <strong>{report.valid ? t("experiments.valid") : t("experiments.invalid")}</strong>
        <span>{report.valid ? t("experiments.valid.detail") : t("experiments.invalid.detail")}</span>
      </div>

      <dl className="dashboard-stats" aria-label={t("experiments.qualitySummary")}>
        <div><dt>{t("experiments.errors")}</dt><dd>{report.error_count}</dd></div>
        <div><dt>{t("experiments.warnings")}</dt><dd>{report.warning_count}</dd></div>
        <div><dt>{t("experiments.totalRecords")}</dt><dd>{summary.total_records}</dd></div>
        <div><dt>{t("experiments.totalEntries")}</dt><dd>{summary.total_entries}</dd></div>
        <div><dt>{t("experiments.humanSame")}</dt><dd>{labels.human_same_records}</dd></div>
        <div><dt>{t("experiments.humanDistinct")}</dt><dd>{labels.human_distinct_pairs}</dd></div>
        <div><dt>{t("experiments.humanInvalid")}</dt><dd>{labels.human_invalid_records}</dd></div>
        <div><dt>{t("experiments.unlabeled")}</dt><dd>{labels.unlabeled_unresolved_records}</dd></div>
        <div><dt>{t("experiments.resolvedHuman")}</dt><dd>{summary.authority.resolved_human_same}</dd></div>
        <div><dt>{t("experiments.resolvedAutomatic")}</dt><dd>{summary.authority.resolved_automatic_same}</dd></div>
      </dl>

      <p className="report-metadata">
        {tn("experiments.qualityMeta", {
          report: <code>{report.schema_version}</code>,
          dataset: <code>{report.dataset_schema_version}</code>,
        })}
      </p>
    </>
  );
}

function RetrievalComparison({ report }: { report: RetrievalComparisonReport }) {
  const { t, tn, status } = useI18n();
  return (
    <>
      <dl className="dashboard-stats comparison-context" aria-label={t("experiments.context")}>
        <div><dt>{t("experiments.state")}</dt><dd className="state-value">{status(report.state)}</dd></div>
        <div><dt>{t("experiments.datasetValid")}</dt><dd>{report.dataset_valid ? t("common.yes") : t("common.no")}</dd></div>
        <div><dt>{t("experiments.candidates")}</dt><dd>{report.candidate_universe.concepts}</dd></div>
        <div><dt>{t("experiments.samples")}</dt><dd>{report.evaluation_samples.eligible_samples}</dd></div>
      </dl>

      <div className="comparison-table-scroll">
        <table className="comparison-table">
          <caption>{t("experiments.caption")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("experiments.retriever")}</th>
              <th scope="col">{t("experiments.rowState")}</th>
              <th scope="col">Recall@1</th>
              <th scope="col">Recall@3</th>
              <th scope="col">Recall@5</th>
              <th scope="col">MRR</th>
            </tr>
          </thead>
          <tbody>
            {report.retrievers.map((row) => (
              <tr key={row.retriever}>
                <th scope="row">
                  <span className="retriever-label">
                    {retrieverLabels[row.retriever] ?? row.retriever}
                  </span>
                  <code className="retriever-id">{row.retriever}</code>
                </th>
                <td><span className={`experiment-state ${row.state}`}>{status(row.state)}</span></td>
                <td>{formatRetrievalMetric(row.metrics.recall_at_1)}</td>
                <td>{formatRetrievalMetric(row.metrics.recall_at_3)}</td>
                <td>{formatRetrievalMetric(row.metrics.recall_at_5)}</td>
                <td>{formatRetrievalMetric(row.metrics.mrr)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="report-metadata">
        {tn("experiments.comparisonMeta", { report: <code>{report.schema_version}</code> })}
      </p>
    </>
  );
}

// ExperimentDashboard is a presentation-only view over the existing M11-D and
// M13-A0 reports. Both sections load independently, and neither request records
// annotations, selects a retriever, or configures an embedding provider.
export function ExperimentDashboard() {
  const { t } = useI18n();
  const [quality, setQuality] = useState<AnnotationDatasetQualityReport | null>(null);
  const [comparison, setComparison] = useState<RetrievalComparisonReport | null>(null);
  const [qualityLoading, setQualityLoading] = useState(true);
  const [comparisonLoading, setComparisonLoading] = useState(true);
  const [qualityError, setQualityError] = useState<string | null>(null);
  const [comparisonError, setComparisonError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    api.getAnnotationDatasetQuality()
      .then((report) => {
        if (active) setQuality(report);
      })
      .catch((error: unknown) => {
        if (active) setQualityError(describeError(error));
      })
      .finally(() => {
        if (active) setQualityLoading(false);
      });

    api.getRetrievalComparison()
      .then((report) => {
        if (active) setComparison(report);
      })
      .catch((error: unknown) => {
        if (active) setComparisonError(describeError(error));
      })
      .finally(() => {
        if (active) setComparisonLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="experiment-dashboard">
      <div className="banner info">{t("experiments.notice")}</div>

      <section className="panel experiment-section" aria-labelledby="dataset-quality-heading">
        <h2 id="dataset-quality-heading">{t("experiments.quality")}</h2>
        <p className="section-description">{t("experiments.quality.description")}</p>
        {qualityLoading ? <p className="section-loading">{t("experiments.quality.loading")}</p> : null}
        {qualityError ? (
          <div className="banner error" role="alert">
            {t("experiments.quality.failed", { message: qualityError })}
          </div>
        ) : null}
        {quality ? <QualitySummary report={quality} /> : null}
      </section>

      <section className="panel experiment-section" aria-labelledby="retrieval-comparison-heading">
        <h2 id="retrieval-comparison-heading">{t("experiments.comparison")}</h2>
        <p className="section-description">{t("experiments.comparison.description")}</p>
        {comparisonLoading ? <p className="section-loading">{t("experiments.comparison.loading")}</p> : null}
        {comparisonError ? (
          <div className="banner error" role="alert">
            {t("experiments.comparison.failed", { message: comparisonError })}
          </div>
        ) : null}
        {comparison ? <RetrievalComparison report={comparison} /> : null}
      </section>
    </main>
  );
}
