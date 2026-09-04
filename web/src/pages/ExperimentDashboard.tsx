import { useEffect, useState } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import type {
  AnnotationDatasetQualityReport,
  RetrievalComparisonReport,
} from "../types/experiment";

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
  const { summary, label_inventory: labels } = report;

  return (
    <>
      <div className={`quality-state ${report.valid ? "valid" : "invalid"}`}>
        <strong>{report.valid ? "Valid" : "Invalid"}</strong>
        <span>
          {report.valid
            ? "No structural dataset errors were reported."
            : "Structural dataset errors block retrieval evaluation."}
        </span>
      </div>

      <dl className="dashboard-stats" aria-label="Dataset quality summary">
        <div><dt>Errors</dt><dd>{report.error_count}</dd></div>
        <div><dt>Warnings</dt><dd>{report.warning_count}</dd></div>
        <div><dt>Total Records</dt><dd>{summary.total_records}</dd></div>
        <div><dt>Total Entries</dt><dd>{summary.total_entries}</dd></div>
        <div><dt>Human SAME</dt><dd>{labels.human_same_records}</dd></div>
        <div><dt>Human DISTINCT</dt><dd>{labels.human_distinct_pairs}</dd></div>
        <div><dt>Human INVALID</dt><dd>{labels.human_invalid_records}</dd></div>
        <div><dt>Unlabeled Unresolved</dt><dd>{labels.unlabeled_unresolved_records}</dd></div>
        <div><dt>Resolved by human SAME</dt><dd>{summary.authority.resolved_human_same}</dd></div>
        <div><dt>Resolved by automatic SAME</dt><dd>{summary.authority.resolved_automatic_same}</dd></div>
      </dl>

      <p className="report-metadata">
        Report <code>{report.schema_version}</code> · Dataset <code>{report.dataset_schema_version}</code>
      </p>
    </>
  );
}

function RetrievalComparison({ report }: { report: RetrievalComparisonReport }) {
  return (
    <>
      <dl className="dashboard-stats comparison-context" aria-label="Retrieval experiment context">
        <div><dt>Experiment State</dt><dd className="state-value">{report.state}</dd></div>
        <div><dt>Dataset Valid</dt><dd>{report.dataset_valid ? "Yes" : "No"}</dd></div>
        <div><dt>Candidate Concepts</dt><dd>{report.candidate_universe.concepts}</dd></div>
        <div><dt>Eligible Samples</dt><dd>{report.evaluation_samples.eligible_samples}</dd></div>
      </dl>

      <div className="comparison-table-scroll">
        <table className="comparison-table">
          <caption>Retrieval baselines in backend-provided experiment order</caption>
          <thead>
            <tr>
              <th scope="col">Retriever</th>
              <th scope="col">State</th>
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
                <td><span className={`experiment-state ${row.state}`}>{row.state}</span></td>
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
        Report <code>{report.schema_version}</code>. Metrics are supplied by the backend; — means unavailable or not evaluable, not zero.
      </p>
    </>
  );
}

// ExperimentDashboard is a presentation-only view over the existing M11-D and
// M13-A0 reports. Both sections load independently, and neither request records
// annotations, selects a retriever, or configures an embedding provider.
export function ExperimentDashboard() {
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
      <div className="banner info">
        Read-only experiment summary from backend-owned quality and retrieval reports. This page does not compute metrics or create annotation authority.
      </div>

      <section className="panel experiment-section" aria-labelledby="dataset-quality-heading">
        <h2 id="dataset-quality-heading">Dataset Quality</h2>
        <p className="section-description">Structural health and current human-supervision inventory from M11-D.</p>
        {qualityLoading ? <p className="section-loading">Loading dataset quality…</p> : null}
        {qualityError ? (
          <div className="banner error" role="alert">
            Could not load dataset quality: {qualityError}
          </div>
        ) : null}
        {quality ? <QualitySummary report={quality} /> : null}
      </section>

      <section className="panel experiment-section" aria-labelledby="retrieval-comparison-heading">
        <h2 id="retrieval-comparison-heading">Retrieval Comparison</h2>
        <p className="section-description">Backend-computed metrics over the shared M12/M13 experiment population.</p>
        {comparisonLoading ? <p className="section-loading">Loading retrieval comparison…</p> : null}
        {comparisonError ? (
          <div className="banner error" role="alert">
            Could not load retrieval comparison: {comparisonError}
          </div>
        ) : null}
        {comparison ? <RetrievalComparison report={comparison} /> : null}
      </section>
    </main>
  );
}
