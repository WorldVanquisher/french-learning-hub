import { useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import type { CurrentExtraction, Extraction } from "../types/learning";
import {
  ExplicitAction,
  OutcomeBanner,
  RefreshBanner,
  type Outcome,
  type RefreshState,
} from "./ExplicitAction";

type Load<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

type ExtractionState = { extractions: Extraction[]; current: CurrentExtraction };

// The selection the reader asked the server to make, kept until the re-read
// shows what the server actually stores.
type Requested = { extractionId: number; version: number };

function describeError(error: unknown): string {
  if (error instanceof ApiError) return `(${error.status}) ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

const latestOf = (extractions: Extraction[]) =>
  extractions.reduce<Extraction | undefined>((a, b) => (a === undefined || b.version > a.version ? b : a), undefined);

// ExtractionPanel shows every stored extraction version of one record, keeps the
// version being viewed separate from the backend's current version and from the
// latest stored version, and offers two explicit writes: request a new
// extraction, and select a stored version as current. Viewing is read-only. The
// backend decides eligibility, runs the provider, and owns which version is
// current; the panel re-reads it after every write instead of assuming.
export function ExtractionPanel({
  entryId,
  latestVersion = null,
}: {
  entryId: number;
  // The record's latest analysis version, only to explain the extraction source.
  latestVersion?: number | null;
}) {
  const [state, setState] = useState<Load<ExtractionState>>({ status: "loading" });
  const [reloadCount, setReloadCount] = useState(0);
  const [pending, setPending] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  // The version being viewed; null follows the current version. A reader's pick
  // survives this record's re-reads.
  const [viewedId, setViewedId] = useState<number | null>(null);
  const [selectPending, setSelectPending] = useState(false);
  const [selectOutcome, setSelectOutcome] = useState<Outcome | null>(null);
  const [requested, setRequested] = useState<Requested | null>(null);
  // The re-read after a write, reported separately from the write's outcome.
  const [refresh, setRefresh] = useState<RefreshState>({ kind: "idle" });
  // Set when an action's outcome is unknown; cleared only by a later successful
  // re-read. Kept per action so one action's refresh never unblocks or blocks the other.
  const [extractionNeedsCheck, setExtractionNeedsCheck] = useState(false);
  const [selectionNeedsCheck, setSelectionNeedsCheck] = useState(false);
  const mounted = useRef(true);
  // Set in setup, cleared in cleanup: StrictMode's development effect replay
  // (setup, cleanup, setup) must leave it true, while a real unmount clears it.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    // Any reload (after a write, or the reader's own "Reload extractions") also
    // settles an outstanding post-write refresh.
    setRefresh((r) => (r.kind === "idle" ? r : { kind: "refreshing" }));
    Promise.all([api.listExtractions(entryId), api.getCurrentExtraction(entryId)])
      .then(([extractions, current]) => {
        if (!active) return;
        setState({ status: "ready", data: { extractions, current } });
        setRefresh((r) => (r.kind === "idle" ? r : { kind: "refreshed" }));
        // Only the latest read gets here (the active guard), so it reflects any
        // write whose outcome was unknown.
        setExtractionNeedsCheck(false);
        setSelectionNeedsCheck(false);
      })
      .catch((error: unknown) => {
        if (!active) return;
        const message = describeError(error);
        setState({ status: "error", message });
        setRefresh((r) => (r.kind === "idle" ? r : { kind: "failed", message }));
      });
    return () => {
      active = false;
    };
  }, [entryId, reloadCount]);

  async function submit() {
    setPending(true);
    setOutcome(null);
    setRequested(null);
    setRefresh({ kind: "idle" });
    let next: Outcome;
    try {
      const created = await api.createExtraction(entryId);
      const n = created.units.length;
      next = {
        kind: "succeeded",
        text: `Stored extraction v${created.version} with ${n} unit${n === 1 ? "" : "s"}${n === 0 ? " (a valid empty result)" : ""}.`,
      };
    } catch (error) {
      next = describeExtractionFailure(error);
    }
    if (!mounted.current) return;
    setOutcome(next);
    setPending(false);
    if (next.kind === "uncertain") setExtractionNeedsCheck(true);
    // Always re-read the stored extractions; RefreshBanner reports whether that
    // GET succeeded, so the outcome above never claims it.
    setRefresh({ kind: "refreshing" });
    setReloadCount((n) => n + 1);
  }

  async function selectCurrent(target: Extraction) {
    const wanted: Requested = { extractionId: target.id, version: target.version };
    setSelectPending(true);
    setSelectOutcome(null);
    setRequested(null);
    setRefresh({ kind: "idle" });
    let next: Outcome;
    let confirmable = false;
    try {
      // The 200 body only echoes the request, so it is not read as stored state.
      await api.setCurrentExtraction(entryId, target.id);
      confirmable = true;
      next = { kind: "succeeded", text: `The server accepted v${target.version} as the current extraction.` };
    } catch (error) {
      next = describeSelectionFailure(error, target.version);
      // An unknown outcome is also checked against the re-read.
      confirmable = error instanceof NetworkError;
    }
    if (!mounted.current) return;
    setSelectOutcome(next);
    setSelectPending(false);
    if (next.kind === "uncertain") setSelectionNeedsCheck(true);
    setRequested(confirmable ? wanted : null);
    setRefresh({ kind: "refreshing" });
    setReloadCount((n) => n + 1);
  }

  // After an unknown outcome a new write could repeat it, so the same action
  // stays unavailable until stored state was re-read.
  const extractionBlocked =
    extractionNeedsCheck
      ? "Unavailable until the stored extractions have been re-read after the unknown outcome. Reload them and check for a new version first."
      : null;
  const selectionBlocked =
    selectionNeedsCheck
      ? "Unavailable until the current extraction has been re-read after the unknown outcome. Reload extractions and check which version is current first."
      : null;

  return (
    <section className="panel" aria-label="Knowledge extraction">
      <h2>Knowledge extraction</h2>
      <p className="hint">
        Stored extractions are historical evidence: feedback never changes or regenerates them. A new
        extraction uses the record&apos;s latest analysis{latestVersion !== null ? ` (v${latestVersion})` : ""} and
        its latest feedback as the server resolves them when you request it, not the version selected
        above.
      </p>
      <ExtractionBrowser
        load={state}
        viewedId={viewedId}
        onView={setViewedId}
        onRetry={() => setReloadCount((n) => n + 1)}
        selectPending={selectPending}
        selectionBlocked={selectionBlocked}
        onSelect={selectCurrent}
      />
      <OutcomeBanner outcome={selectOutcome} />
      <SelectionCheck requested={requested} load={state} refresh={refresh} />
      <div className="workflow-action">
        <ExplicitAction
          label="Request extraction"
          confirmLabel="Send to the extraction provider"
          pending={pending}
          disabledReason={extractionBlocked}
          onConfirm={submit}
          explanation={
            <>
              <p>
                The server sends this record&apos;s original input and its current effective
                interpretation to the configured extraction provider, which may be an external,
                billed service. Extraction is disabled by default; the server then refuses before
                calling any provider.
              </p>
              <p>
                The server decides eligibility: a record without an analysis, or whose latest
                analysis was rejected, is refused. If the interpretation changes while the provider
                runs, the server refuses to store the result. A successful request stores a new,
                immutable extraction version (zero units is a valid result). It becomes current only
                while no version has been selected as current for this record. The request is sent
                once and never retried automatically.
              </p>
            </>
          }
        />
        <OutcomeBanner outcome={outcome} />
      </div>
      <RefreshBanner refresh={refresh} what="stored extractions" />
    </section>
  );
}

// SelectionCheck compares a selection the server accepted (or whose outcome is
// unknown) with the re-read, so the panel reports stored state rather than its own
// request. It says nothing until the re-read has succeeded.
function SelectionCheck({
  requested,
  load,
  refresh,
}: {
  requested: Requested | null;
  load: Load<ExtractionState>;
  refresh: RefreshState;
}) {
  if (!requested || refresh.kind !== "refreshed" || load.status !== "ready") return null;
  const currentId = load.data.current.current_extraction_id;
  if (currentId === requested.extractionId) {
    return (
      <p className="hint" role="status">
        Confirmed by re-read: the server reports v{requested.version} as the current extraction.
      </p>
    );
  }
  const actual = load.data.extractions.find((e) => e.id === currentId);
  return (
    <div className="banner error" role="alert">
      The re-read shows {actual ? `v${actual.version}` : currentId === null ? "no extraction" : `extraction #${currentId}`} as
      current, not v{requested.version}. It may have been changed again elsewhere; check before acting.
    </div>
  );
}

function ExtractionBrowser({
  load,
  viewedId,
  onView,
  onRetry,
  selectPending,
  selectionBlocked,
  onSelect,
}: {
  load: Load<ExtractionState>;
  viewedId: number | null;
  onView: (id: number) => void;
  onRetry: () => void;
  selectPending: boolean;
  selectionBlocked: string | null;
  onSelect: (target: Extraction) => Promise<void>;
}) {
  if (load.status === "loading") {
    return <p className="value">Loading extractions…</p>;
  }
  if (load.status === "error") {
    return (
      <div className="banner error" role="alert">
        Could not load extractions: {load.message}{" "}
        <button type="button" className="ghost" onClick={onRetry}>
          Reload extractions
        </button>
      </div>
    );
  }
  const { extractions, current } = load.data;
  if (extractions.length === 0) {
    return (
      <p className="value">
        <strong>No extraction stored.</strong> No extraction has been run for this record.
      </p>
    );
  }
  const versions = [...extractions].sort((a, b) => a.version - b.version);
  const latest = latestOf(extractions) as Extraction;
  const currentExtraction = extractions.find((e) => e.id === current.current_extraction_id);
  // A reader's pick stays while it exists; otherwise follow the current version.
  const viewed =
    extractions.find((e) => e.id === viewedId) ?? currentExtraction ?? latest;

  return (
    <>
      <p className="value" aria-label="Extraction summary">
        Current: {currentExtraction ? `v${currentExtraction.version}` : "none"} · Latest stored: v
        {latest.version} · {extractions.length} version{extractions.length === 1 ? "" : "s"} stored
      </p>
      {currentExtraction && currentExtraction.id !== latest.id ? (
        <p className="hint">
          A newer version (v{latest.version}) is stored, but the server keeps v{currentExtraction.version} as
          current. Once a version has been selected as current, later extractions do not replace it
          automatically.
        </p>
      ) : null}
      {!currentExtraction ? (
        <p className="hint">
          <strong>No current extraction.</strong> Stored versions exist, but the server reports none as
          current.
        </p>
      ) : null}
      <p className="hint">Choosing a version below only changes what is shown; it changes nothing on the server.</p>
      <div className="version-list" role="group" aria-label="Stored extraction versions">
        {versions.map((e) => {
          const tags = [e.id === currentExtraction?.id ? "current" : null, e.id === latest.id ? "latest" : null].filter(Boolean);
          return (
            <button
              key={e.id}
              type="button"
              className={e.id === viewed.id ? "primary" : "ghost"}
              aria-pressed={e.id === viewed.id}
              onClick={() => onView(e.id)}
            >
              v{e.version}
              {tags.length ? ` (${tags.join(", ")})` : ""}
            </button>
          );
        })}
      </div>
      <ExtractionVersionView
        extraction={viewed}
        isCurrent={viewed.id === currentExtraction?.id}
        isLatest={viewed.id === latest.id}
        currentVersion={currentExtraction?.version ?? null}
      />
      {viewed.id !== currentExtraction?.id ? (
        <div className="workflow-action">
          <ExplicitAction
            // Keyed by version so an open confirmation never carries over to another one.
            key={viewed.id}
            label={`Make v${viewed.version} the current extraction`}
            confirmLabel={`Set v${viewed.version} as current`}
            pending={selectPending}
            disabledReason={selectionBlocked}
            onConfirm={() => onSelect(viewed)}
            explanation={
              <>
                <p>
                  The server will treat v{viewed.version} as this record&apos;s current extraction. Its
                  units become the ones offered in Concept Review and counted as concept support; units of
                  other versions stay stored but are not reviewable and give no support while v
                  {viewed.version} is current.
                </p>
                <p>
                  Nothing is deleted or rewritten: every version&apos;s units, SAME memberships, DISTINCT
                  and relation labels, and INVALID judgments stay stored and apply again if their version
                  becomes current later. No extraction is run.
                </p>
                <p>
                  A selected version stays current even when the record is extracted again; later
                  versions will not replace it automatically. The workbench cannot yet return a record to
                  automatic latest selection. The request is sent once and never retried automatically.
                </p>
              </>
            }
          />
        </div>
      ) : null}
    </>
  );
}

function ExtractionVersionView({
  extraction,
  isCurrent,
  isLatest,
  currentVersion,
}: {
  extraction: Extraction;
  isCurrent: boolean;
  isLatest: boolean;
  currentVersion: number | null;
}) {
  return (
    <div className="annotation-section" aria-label="Viewed extraction">
      <h3>
        Viewing extraction v{extraction.version}{" "}
        <span className="hint">
          ({[isCurrent ? "current" : "not current", isLatest ? "latest stored" : null].filter(Boolean).join(", ")})
        </span>
      </h3>
      <p className="hint">
        {isCurrent
          ? "This is the current extraction: its units are the ones offered for concept review and counted as concept support."
          : `Not current: its units stay stored as history but are not offered for review and give no concept support${
              currentVersion !== null ? ` while v${currentVersion} is current` : ""
            }.`}
      </p>
      <div className="annotation-provenance">
        <span className="mono">{extraction.extractor}</span>
        <span>from analysis #{extraction.source_analysis_id}</span>
        <span>
          {extraction.source_feedback_id !== null ? `feedback #${extraction.source_feedback_id}` : "no feedback"}
        </span>
        <time dateTime={extraction.created_at}>{extraction.created_at}</time>
      </div>
      {extraction.units.length === 0 ? (
        <p className="value">
          <strong>Zero units.</strong> This successful extraction produced no knowledge units.
        </p>
      ) : (
        <ul className="annotation-list" aria-label="Extracted units">
          {extraction.units.map((unit) => (
            <li key={unit.id}>
              <dl className="unit-evidence">
                <div><dt>Unit</dt><dd>#{unit.id} · {unit.kind}</dd></div>
                <div><dt>Canonical</dt><dd className="french">{unit.canonical}</dd></div>
                <div><dt>Statement</dt><dd className="french">{unit.statement}</dd></div>
                {unit.example ? <div><dt>Example</dt><dd className="french">{unit.example}</dd></div> : null}
                <div><dt>Confidence</dt><dd>{unit.confidence}</dd></div>
                <div>
                  <dt>Admission</dt>
                  <dd>
                    {unit.admission.effective_state}
                    {unit.admission.latest_override
                      ? ` (human override: ${unit.admission.latest_override.decision})`
                      : ` (machine: ${unit.admission.machine_reason})`}
                  </dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// describeSelectionFailure reports a rejected selection. Every error from the PUT
// is returned before its transaction commits, so the current extraction was not
// changed; a missing response leaves the outcome unknown.
function describeSelectionFailure(error: unknown, version: number): Outcome {
  if (error instanceof NetworkError) {
    return {
      kind: "uncertain",
      text: `No response was received, so v${version} may or may not have become the current extraction.`,
    };
  }
  if (error instanceof ApiError) {
    return {
      kind: "rejected",
      text: `The server did not change the current extraction (${error.status}): ${error.message}.`,
    };
  }
  return { kind: "rejected", text: `The selection request failed: ${String(error)}` };
}

// describeExtractionFailure states only what the backend contract supports. Every
// error response means nothing was stored. Only 503 (extraction disabled) is
// returned before any provider call; a 409 can come from the eligibility check
// before the provider runs or from the source-changed check after it returns, so
// it never implies that no provider was called.
function describeExtractionFailure(error: unknown): Outcome {
  if (error instanceof NetworkError) {
    return {
      kind: "uncertain",
      text:
        "No response was received, so a new extraction may or may not have been stored, and the extraction provider may have been called.",
    };
  }
  if (!(error instanceof ApiError)) {
    return { kind: "rejected", text: `The extraction request failed: ${String(error)}` };
  }
  const detail = `(${error.status}) ${error.message}`;
  switch (error.status) {
    case 503:
      return {
        kind: "rejected",
        text: `Extraction is not enabled on this server ${detail}. The server refuses before calling any extraction provider; nothing was stored.`,
      };
    case 409:
      return {
        kind: "rejected",
        text: `The server did not store an extraction ${detail}. This conflict can be detected before the provider runs or after it returns, so the extraction provider may have been called. Check the record's current analysis before requesting again.`,
      };
    case 422:
      return {
        kind: "rejected",
        text: `The server rejected the extraction result ${detail}. Nothing was stored; the extraction provider may have been called.`,
      };
    case 502:
    case 504:
      return {
        kind: "rejected",
        text: `The extraction provider failed ${detail}. Nothing was stored; the provider may have been called.`,
      };
    default:
      return {
        kind: "rejected",
        text: `No extraction was stored ${detail}. The extraction provider may have been called.`,
      };
  }
}
