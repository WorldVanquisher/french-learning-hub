import { useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import type { Analysis, EffectiveAnalysis, Entry } from "../types/learning";
import { AnalysisRequest } from "./AnalysisRequest";
import type { RefreshState } from "./ExplicitAction";
import { ExtractionPanel } from "./ExtractionPanel";
import { FeedbackPanel } from "./FeedbackPanel";
import { recordHeadingId, type UnitTarget } from "../navigation";

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
// has moved on (another record, another version) is discarded. Explicit Analysis
// and Extraction requests live here; after a write the record is re-read from the
// backend and onRecordChanged lets the list refresh its row.
export function RecordDetail({
  entryId,
  onBack,
  onRecordChanged,
  returnEpoch = 0,
  onNavigateToUnit,
}: {
  entryId: number;
  onBack: () => void;
  onRecordChanged?: (entryId: number) => void;
  // Changes when the reader returns from Concept Review or the Inspector.
  returnEpoch?: number;
  onNavigateToUnit?: (target: UnitTarget) => void;
}) {
  const [entry, setEntry] = useState<Load<Entry>>({ status: "loading" });
  const [analyses, setAnalyses] = useState<Load<Analysis[]>>({ status: "loading" });
  const [selectedAnalysisId, setSelectedAnalysisId] = useState<number | null>(null);
  const [effective, setEffective] = useState<Load<EffectiveAnalysis>>({ status: "loading" });
  const [reloadCount, setReloadCount] = useState(0);
  const [effectiveReloadCount, setEffectiveReloadCount] = useState(0);
  // The re-read of analysis versions after an analysis request; any later reload
  // (including Retry) settles it.
  const [analysisRefresh, setAnalysisRefresh] = useState<RefreshState>({ kind: "idle" });
  // The re-read of one analysis version's effective interpretation after feedback,
  // tied to that version so it is never shown for another one.
  const [effectiveRefresh, setEffectiveRefresh] = useState<{ analysisId: number; state: RefreshState } | null>(null);
  // The selection at the moment an asynchronous feedback result arrives.
  const selectedRef = useRef<number | null>(null);
  selectedRef.current = selectedAnalysisId;
  // The record shown now. A write callback created for an earlier record may
  // still refresh that record's list row, but must not touch this one.
  const entryRef = useRef(entryId);
  entryRef.current = entryId;
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

    setAnalysisRefresh((r) => (r.kind === "idle" ? r : { kind: "refreshing" }));
    api.listAnalyses(entryId)
      .then((data) => {
        if (!active) return;
        setAnalyses({ status: "ready", data });
        setSelectedAnalysisId(latestAnalysis(data)?.id ?? null);
        setAnalysisRefresh((r) => (r.kind === "idle" ? r : { kind: "refreshed" }));
      })
      .catch((error: unknown) => {
        if (!active) return;
        const message = describeError(error);
        setAnalyses({ status: "error", message });
        setAnalysisRefresh((r) => (r.kind === "idle" ? r : { kind: "failed", message }));
      });

    return () => {
      active = false;
    };
  }, [entryId, reloadCount]);

  useEffect(() => {
    if (selectedAnalysisId === null) return;
    const id = selectedAnalysisId;
    let active = true;
    const settle = (state: RefreshState) =>
      setEffectiveRefresh((r) => (r && r.analysisId === id && r.state.kind !== "idle" ? { analysisId: id, state } : r));
    setEffective({ status: "loading" });
    settle({ kind: "refreshing" });
    api.getEffectiveAnalysis(id)
      .then((data) => {
        if (!active) return;
        setEffective({ status: "ready", data });
        settle({ kind: "refreshed" });
      })
      .catch((error: unknown) => {
        if (!active) return;
        const message = describeError(error);
        setEffective({ status: "error", message });
        settle({ kind: "failed", message });
      });
    return () => {
      active = false;
    };
    // Retry the selected interpretation without reloading the version list.
    // Cleanup also discards a retry response after another version is selected.
  }, [selectedAnalysisId, effectiveReloadCount]);

  const analysisList = analyses.status === "ready" ? analyses.data : [];
  const latest = latestAnalysis(analysisList);
  const selected = analysisList.find((a) => a.id === selectedAnalysisId);
  const anyError = entry.status === "error" || analyses.status === "error" || effective.status === "error";

  // A confirmed or uncertain analysis request re-reads the record, which selects
  // the latest version; a request the server rejected leaves the selection alone.
  const analysisAction = (
    <AnalysisRequest
      key={entryId}
      entryId={entryId}
      refresh={analysisRefresh}
      onStart={() => setAnalysisRefresh({ kind: "idle" })}
      onSettled={(_created, reread) => {
        if (!reread) return;
        onRecordChanged?.(entryId);
        if (entryRef.current !== entryId) return;
        setAnalysisRefresh({ kind: "refreshing" });
        setReloadCount((n) => n + 1);
      }}
    />
  );

  return (
    <main className="record-detail">
      <div className="queue-nav">
        <button type="button" className="ghost" onClick={onBack}>
          ← Back to records
        </button>
        {anyError ? (
          <button
            type="button"
            className="ghost"
            onClick={() => {
              if (entry.status === "error" || analyses.status === "error") {
                setReloadCount((n) => n + 1);
              } else {
                setEffectiveReloadCount((n) => n + 1);
              }
            }}
          >
            Retry
          </button>
        ) : null}
      </div>

      <h2 ref={headingRef} id={recordHeadingId(entryId)} tabIndex={-1} className="record-detail-heading">
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
        {/* Always mounted: the re-read it triggers must not discard its outcome. */}
        {analysisAction}
      </section>

      {selected ? (
        <section className="panel" aria-label="Selected analysis">
          <h2>
            Analysis v{selected.version}{" "}
            <span className="hint">
              ({selected.id === latest?.id ? "latest version" : `historical version; latest is v${latest?.version ?? "?"}`})
            </span>
          </h2>
          <dl className="unit-evidence">
            <div><dt>Analyzer</dt><dd className="mono">{selected.analyzer}</dd></div>
            <div><dt>Confidence</dt><dd>{selected.confidence}</dd></div>
            <div><dt>Uncertainty</dt><dd>{selected.uncertainty || <em>(none stated)</em>}</dd></div>
            <div><dt>Created</dt><dd><time dateTime={selected.created_at}>{selected.created_at}</time></dd></div>
          </dl>
          <EffectiveInterpretation load={effective} />
        </section>
      ) : null}

      {/* Always mounted for this record so drafts survive its read refreshes. Sibling
          keys must differ from ExtractionPanel's, or React mixes up the two panels. */}
      <FeedbackPanel
        key={`feedback-${entryId}`}
        analysis={selected}
        latest={latest}
        effectiveFeedbackId={
          effective.status === "ready" && effective.data.analysis_id === selected?.id ? effective.data.feedback_id : undefined
        }
        effectiveResolution={
          effective.status === "ready" && effective.data.analysis_id === selected?.id ? effective.data.resolution : undefined
        }
        effectiveRefresh={
          effectiveRefresh && effectiveRefresh.analysisId === selected?.id ? effectiveRefresh.state : { kind: "idle" }
        }
        onRecorded={(analysisId) => {
          // Feedback can change this version's effective interpretation and, for
          // the latest version, the record's inventory state.
          onRecordChanged?.(entryId);
          if (entryRef.current !== entryId) return;
          setEffectiveRefresh({ analysisId, state: { kind: "refreshing" } });
          if (selectedRef.current === analysisId) setEffectiveReloadCount((n) => n + 1);
        }}
      />

      {/* Keyed by entry so a late response for another record never reaches it. */}
      <ExtractionPanel
        key={`extraction-${entryId}`}
        entryId={entryId}
        latestVersion={latest?.version ?? null}
        returnEpoch={returnEpoch}
        onNavigateToUnit={onNavigateToUnit}
      />
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
