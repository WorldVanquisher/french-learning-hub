import { useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import type { Analysis, EffectiveAnalysis, Entry } from "../types/learning";

// Load is the lifecycle of one independent read. Each section of the detail has its
// own Load so a failure in one read never hides the data of another.
type Load<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return `(${error.status}) ${error.message}`;
  }
  return error instanceof Error ? error.message : String(error);
}

// latestAnalysis is the highest version, which is the one the inventory state
// reflects. The backend returns versions oldest first; this does not rely on order.
function latestAnalysis(analyses: Analysis[]): Analysis | undefined {
  return analyses.reduce<Analysis | undefined>(
    (latest, a) => (latest === undefined || a.version > latest.version ? a : latest),
    undefined,
  );
}

// RecordDetail is a GET-only view of one learning record: the learner-authored
// Entry, its immutable analysis versions, and the backend-owned effective
// interpretation of the selected version. A response that arrives after the reader
// has moved on (another record, another version) is discarded.
export function RecordDetail({ entryId, onBack }: { entryId: number; onBack: () => void }) {
  const [entry, setEntry] = useState<Load<Entry>>({ status: "loading" });
  const [analyses, setAnalyses] = useState<Load<Analysis[]>>({ status: "loading" });
  const [selectedAnalysisId, setSelectedAnalysisId] = useState<number | null>(null);
  const [effective, setEffective] = useState<Load<EffectiveAnalysis>>({ status: "loading" });
  const [reloadCount, setReloadCount] = useState(0);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Move focus to the detail heading so keyboard and screen-reader users land on
  // the record they opened.
  useEffect(() => {
    headingRef.current?.focus();
  }, [entryId]);

  useEffect(() => {
    let active = true;
    setEntry({ status: "loading" });
    setAnalyses({ status: "loading" });
    setSelectedAnalysisId(null);

    api.getEntry(entryId)
      .then((data) => {
        if (active) setEntry({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (active) setEntry({ status: "error", message: describeError(error) });
      });

    api.listAnalyses(entryId)
      .then((data) => {
        if (!active) return;
        setAnalyses({ status: "ready", data });
        setSelectedAnalysisId(latestAnalysis(data)?.id ?? null);
      })
      .catch((error: unknown) => {
        if (active) setAnalyses({ status: "error", message: describeError(error) });
      });

    return () => {
      active = false;
    };
  }, [entryId, reloadCount]);

  useEffect(() => {
    if (selectedAnalysisId === null) return;
    let active = true;
    setEffective({ status: "loading" });
    api.getEffectiveAnalysis(selectedAnalysisId)
      .then((data) => {
        if (active) setEffective({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (active) setEffective({ status: "error", message: describeError(error) });
      });
    return () => {
      active = false;
    };
    // A retry re-reads the analyses, which resets and re-selects the version and so
    // re-runs this effect; reloadCount is deliberately not a dependency here.
  }, [selectedAnalysisId]);

  const analysisList = analyses.status === "ready" ? analyses.data : [];
  const latest = latestAnalysis(analysisList);
  const selected = analysisList.find((a) => a.id === selectedAnalysisId);
  const anyError = entry.status === "error" || analyses.status === "error" || effective.status === "error";

  return (
    <main className="record-detail">
      <div className="queue-nav">
        <button type="button" className="ghost" onClick={onBack}>
          ← Back to records
        </button>
        {anyError ? (
          <button type="button" className="ghost" onClick={() => setReloadCount((n) => n + 1)}>
            Retry
          </button>
        ) : null}
      </div>

      <h2 ref={headingRef} tabIndex={-1} className="record-detail-heading">
        Record #{entryId}
      </h2>

      <section className="panel" aria-label="Original input and context">
        <h2>Original input and context</h2>
        {entry.status === "loading" ? (
          <p className="value">Loading the original record…</p>
        ) : entry.status === "error" ? (
          <div className="banner error" role="alert">
            Could not load the original record: {entry.message}
          </div>
        ) : (
          <dl className="unit-evidence">
            <div><dt>Original input</dt><dd className="french">{entry.data.original_input}</dd></div>
            <div>
              <dt>Original context</dt>
              <dd className="french">{entry.data.original_context || <em>(no context recorded)</em>}</dd>
            </div>
            <div><dt>Created</dt><dd><time dateTime={entry.data.created_at}>{entry.data.created_at}</time></dd></div>
          </dl>
        )}
      </section>

      <section className="panel" aria-label="Analysis versions">
        <h2>Analysis versions</h2>
        {analyses.status === "loading" ? (
          <p className="value">Loading analysis versions…</p>
        ) : analyses.status === "error" ? (
          <div className="banner error" role="alert">
            Could not load analysis versions: {analyses.message}
          </div>
        ) : analysisList.length === 0 ? (
          <p className="value">
            <strong>No analysis.</strong> This record has not been analyzed, so it has no
            interpretation to show.
          </p>
        ) : (
          <>
            <p className="hint">
              Analyses are immutable versions. The record&apos;s state reflects the latest
              version; selecting another version only changes what is shown here.
            </p>
            <div className="version-list">
              {analysisList.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  className={a.id === selectedAnalysisId ? "primary" : "ghost"}
                  aria-pressed={a.id === selectedAnalysisId}
                  onClick={() => setSelectedAnalysisId(a.id)}
                >
                  v{a.version}
                  {a.id === latest?.id ? " (latest)" : ""}
                </button>
              ))}
            </div>
          </>
        )}
      </section>

      {selected ? (
        <section className="panel" aria-label="Selected analysis">
          <h2>Analysis v{selected.version}</h2>
          <dl className="unit-evidence">
            <div><dt>Analyzer</dt><dd className="mono">{selected.analyzer}</dd></div>
            <div><dt>Confidence</dt><dd>{selected.confidence}</dd></div>
            <div><dt>Uncertainty</dt><dd>{selected.uncertainty || <em>(none stated)</em>}</dd></div>
            <div><dt>Created</dt><dd><time dateTime={selected.created_at}>{selected.created_at}</time></dd></div>
          </dl>
          <EffectiveInterpretation load={effective} />
        </section>
      ) : null}
    </main>
  );
}

// EffectiveInterpretation shows the backend's resolution of one analysis verbatim.
// A rejected analysis has no effective interpretation; its original values stay
// visible only as rejected evidence.
function EffectiveInterpretation({ load }: { load: Load<EffectiveAnalysis> }) {
  if (load.status === "loading") {
    return <p className="value">Loading the effective interpretation…</p>;
  }
  if (load.status === "error") {
    return (
      <div className="banner error" role="alert">
        Could not load the effective interpretation: {load.message}
      </div>
    );
  }
  const eff = load.data;
  return (
    <div className="annotation-section" aria-label="Effective interpretation">
      <h3>
        Effective interpretation{" "}
        <span className={`record-state ${eff.resolution}`}>{eff.resolution}</span>
      </h3>
      {eff.effective === null ? (
        <>
          <div className="banner info">
            <strong>Rejected interpretation.</strong> A human rejected this analysis, so
            it has no effective interpretation.
          </div>
          <dl className="unit-evidence">
            <div><dt>Rejected category</dt><dd>{eff.original.category}</dd></div>
            <div><dt>Rejected explanation</dt><dd>{eff.original.explanation}</dd></div>
          </dl>
        </>
      ) : (
        <>
          <dl className="unit-evidence">
            <div><dt>Category</dt><dd>{eff.effective.category}</dd></div>
            <div><dt>Explanation</dt><dd>{eff.effective.explanation}</dd></div>
          </dl>
          {eff.resolution === "unreviewed" ? (
            <p className="hint">Unreviewed candidate: no human has accepted or corrected it.</p>
          ) : null}
          {eff.resolution === "corrected" ? (
            <dl className="unit-evidence">
              <div><dt>Original category</dt><dd>{eff.original.category}</dd></div>
              <div><dt>Original explanation</dt><dd>{eff.original.explanation}</dd></div>
            </dl>
          ) : null}
        </>
      )}
      <div className="annotation-provenance">
        <span>analysis #{eff.analysis_id}</span>
        <span>{eff.feedback_id !== null ? `feedback #${eff.feedback_id}` : "no feedback"}</span>
      </div>
    </div>
  );
}
