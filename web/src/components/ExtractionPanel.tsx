import { useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import type { CurrentExtraction, Extraction } from "../types/learning";
import { unitFocusId, type UnitTarget } from "../navigation";
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

// The selection change the reader asked for, kept until the re-read shows what
// the server actually stores.
type Requested =
  | { kind: "pin"; extractionId: number; version: number }
  | { kind: "automatic" };

// The backend's reviewable units for this entry's current extraction, read from
// GET /reviewable-units?entry_id. It is the only source of review eligibility.
type Reviewability = Load<ReadonlySet<number>> & { forExtractionId?: number };

function describeError(error: unknown): string {
  if (error instanceof ApiError) return `(${error.status}) ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

const latestOf = (extractions: Extraction[]) =>
  extractions.reduce<Extraction | undefined>((a, b) => (a === undefined || b.version > a.version ? b : a), undefined);

// ExtractionPanel shows every stored extraction version of one record, keeps the
// version being viewed separate from the backend's current version, its selection
// mode, and the latest stored version, and offers explicit writes: request a new
// extraction, pin a stored version as current, and resume automatic latest
// selection. Viewing is read-only. The backend owns eligibility, the provider,
// and which version is current; the panel re-reads it after every write.
export function ExtractionPanel({
  entryId,
  latestVersion = null,
  returnEpoch = 0,
  onNavigateToUnit,
}: {
  entryId: number;
  // The record's latest analysis version, only to explain the extraction source.
  latestVersion?: number | null;
  // Changes when the reader returns from another view, so review status that
  // may have changed there is read again.
  returnEpoch?: number;
  onNavigateToUnit?: (target: UnitTarget) => void;
}) {
  const [state, setState] = useState<Load<ExtractionState>>({ status: "loading" });
  const [reloadCount, setReloadCount] = useState(0);
  const [pending, setPending] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  // The version being viewed; null follows the current version. A reader's pick
  // survives this record's re-reads and navigation to other views.
  const [viewedId, setViewedId] = useState<number | null>(null);
  // Pinning and resuming automatic selection change the same authority, so they
  // share one lifecycle and can never overlap.
  const [selectPending, setSelectPending] = useState(false);
  const [selectOutcome, setSelectOutcome] = useState<Outcome | null>(null);
  const [requested, setRequested] = useState<Requested | null>(null);
  const [reviewable, setReviewable] = useState<Reviewability | null>(null);
  const [reviewReload, setReviewReload] = useState(0);
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

  // Review eligibility of the current extraction's units, from the backend. Read
  // again whenever the current version changes, after writes, and on return from
  // Concept Review or the Inspector.
  const currentId = state.status === "ready" ? state.data.current.current_extraction_id : null;
  const currentHasUnits =
    state.status === "ready" && (state.data.extractions.find((e) => e.id === currentId)?.units.length ?? 0) > 0;
  // Read only when unit links are offered. A boolean, not the callback, is the
  // dependency, because the callback's identity changes on every parent render.
  const linksEnabled = onNavigateToUnit !== undefined;
  useEffect(() => {
    if (!linksEnabled || currentId === null || !currentHasUnits) {
      setReviewable(null);
      return;
    }
    let active = true;
    setReviewable({ status: "loading" });
    api.listReviewableUnits(entryId)
      .then((units) => {
        if (active) setReviewable({ status: "ready", data: new Set(units.map((u) => u.unit_id)), forExtractionId: currentId });
      })
      .catch((error: unknown) => {
        if (active) setReviewable({ status: "error", message: describeError(error) });
      });
    return () => {
      active = false;
    };
  }, [entryId, linksEnabled, currentId, currentHasUnits, reloadCount, reviewReload, returnEpoch]);

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

  // changeSelection sends one selection write (pin or resume automatic), then
  // always re-reads. Its response is reported only as the server's answer.
  async function changeSelection(wanted: Requested, send: () => Promise<Outcome>) {
    setSelectPending(true);
    setSelectOutcome(null);
    setRequested(null);
    setRefresh({ kind: "idle" });
    let next: Outcome;
    let confirmable = false;
    try {
      next = await send();
      confirmable = true;
    } catch (error) {
      next = describeSelectionFailure(error, wanted);
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

  const pin = (target: Extraction) =>
    changeSelection({ kind: "pin", extractionId: target.id, version: target.version }, async () => {
      // The PUT body is built from the request, so it is not read as stored state.
      await api.setCurrentExtraction(entryId, target.id);
      return { kind: "succeeded", text: `The server accepted v${target.version} as the pinned current extraction.` };
    });

  const resumeAutomatic = () =>
    changeSelection({ kind: "automatic" }, async () => {
      const reported = await api.clearCurrentExtraction(entryId);
      return {
        kind: "succeeded",
        text: `The server removed the pin and reported ${reported.selection_mode} selection${
          reported.current_extraction_id === null ? " with no current extraction" : ""
        }.`,
      };
    });

  // After an unknown outcome a new write could repeat it, so the same action
  // stays unavailable until stored state was re-read.
  const extractionBlocked = extractionNeedsCheck
    ? "Unavailable until the stored extractions have been re-read after the unknown outcome. Reload them and check for a new version first."
    : null;
  const selectionBlocked = selectionNeedsCheck
    ? "Unavailable until the current extraction has been re-read after the unknown outcome. Reload extractions and check the current selection first."
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
        entryId={entryId}
        load={state}
        viewedId={viewedId}
        onView={setViewedId}
        onRetry={() => setReloadCount((n) => n + 1)}
        selectPending={selectPending}
        selectionBlocked={selectionBlocked}
        onPin={pin}
        onResumeAutomatic={resumeAutomatic}
        reviewable={reviewable}
        onRecheckReview={() => setReviewReload((n) => n + 1)}
        onNavigateToUnit={onNavigateToUnit}
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
                immutable extraction version (zero units is a valid result). It becomes current
                under automatic selection; a pinned version stays current. The request is sent once
                and never retried automatically.
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

// SelectionCheck compares a selection change the server accepted (or whose
// outcome is unknown) with the re-read, so the panel reports stored state rather
// than its own request. It says nothing until the re-read has succeeded.
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
  const { current, extractions } = load.data;
  const versionOf = (id: number | null) => {
    const e = extractions.find((x) => x.id === id);
    return e ? `v${e.version}` : id === null ? "no extraction" : `extraction #${id}`;
  };
  const stored = `${versionOf(current.current_extraction_id)} (${current.selection_mode})`;
  const matches =
    requested.kind === "pin"
      ? current.selection_mode === "pinned" && current.current_extraction_id === requested.extractionId
      : current.selection_mode === "automatic";
  if (matches) {
    return (
      <p className="hint" role="status">
        Confirmed by re-read: the server reports {stored} as the current extraction.
      </p>
    );
  }
  const wanted = requested.kind === "pin" ? `v${requested.version} (pinned)` : "automatic selection";
  return (
    <div className="banner error" role="alert">
      The re-read shows {stored} as current, not {wanted}. It may have been changed again elsewhere;
      reload extractions before acting.
    </div>
  );
}

function ExtractionBrowser({
  entryId,
  load,
  viewedId,
  onView,
  onRetry,
  selectPending,
  selectionBlocked,
  onPin,
  onResumeAutomatic,
  reviewable,
  onRecheckReview,
  onNavigateToUnit,
}: {
  entryId: number;
  load: Load<ExtractionState>;
  viewedId: number | null;
  onView: (id: number) => void;
  onRetry: () => void;
  selectPending: boolean;
  selectionBlocked: string | null;
  onPin: (target: Extraction) => Promise<void>;
  onResumeAutomatic: () => Promise<void>;
  reviewable: Reviewability | null;
  onRecheckReview: () => void;
  onNavigateToUnit?: (target: UnitTarget) => void;
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
  const pinned = current.selection_mode === "pinned";
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
  const viewed = extractions.find((e) => e.id === viewedId) ?? currentExtraction ?? latest;

  return (
    <>
      <p className="value" aria-label="Extraction summary">
        Current: {currentExtraction ? `v${currentExtraction.version}` : "none"} · Selection:{" "}
        {pinned ? "pinned" : "automatic"} · Latest stored: v{latest.version} · {extractions.length} version
        {extractions.length === 1 ? "" : "s"} stored
      </p>
      <p className="hint" aria-label="Selection mode">
        {pinned
          ? currentExtraction && currentExtraction.id === latest.id
            ? `Pinned: v${currentExtraction.version} is pinned and is also the latest stored version. It stays current even if a newer extraction is stored later.`
            : `Pinned: the server keeps v${currentExtraction?.version ?? "?"} as current although v${latest.version} is the latest stored version. Newer extractions do not replace a pinned version.`
          : "Automatic: the server treats the latest stored extraction as current and follows new extractions."}
      </p>
      {!currentExtraction ? (
        <p className="hint">
          <strong>No current extraction.</strong> Stored versions exist, but the server reports none as
          current.
        </p>
      ) : null}
      {pinned ? (
        <div className="workflow-action">
          <ExplicitAction
            label="Resume automatic latest selection"
            confirmLabel="Remove the pin"
            pending={selectPending}
            disabledReason={selectionBlocked}
            onConfirm={onResumeAutomatic}
            explanation={
              <>
                <p>
                  The server removes the pin for this record and treats the latest stored extraction
                  (now v{latest.version}) as current, following later extractions automatically. Its
                  units become the ones offered in Concept Review and counted as concept support;
                  units of the previously pinned version stay stored but give no support while another
                  version is current.
                </p>
                <p>
                  Nothing is deleted or rewritten: every version&apos;s units, SAME memberships,
                  DISTINCT and relation labels, and INVALID judgments stay stored. No extraction is run
                  and no provider is called. The request is sent once and never retried automatically.
                </p>
              </>
            }
          />
        </div>
      ) : null}
      <p className="hint">Choosing a version below only changes what is shown; it changes nothing on the server.</p>
      <div className="version-list" role="group" aria-label="Stored extraction versions">
        {versions.map((e) => {
          const tags = [
            e.id === currentExtraction?.id ? (pinned ? "current, pinned" : "current") : null,
            e.id === latest.id ? "latest" : null,
          ].filter(Boolean);
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
        entryId={entryId}
        extraction={viewed}
        isCurrent={viewed.id === currentExtraction?.id}
        isLatest={viewed.id === latest.id}
        currentVersion={currentExtraction?.version ?? null}
        reviewable={reviewable}
        onRecheckReview={onRecheckReview}
        onNavigateToUnit={onNavigateToUnit}
      />
      {viewed.id !== currentExtraction?.id || !pinned ? (
        <div className="workflow-action">
          <ExplicitAction
            // Keyed by version so an open confirmation never carries over to another one.
            key={viewed.id}
            label={`Pin v${viewed.version} as the current extraction`}
            confirmLabel={`Pin v${viewed.version}`}
            pending={selectPending}
            disabledReason={selectionBlocked}
            onConfirm={() => onPin(viewed)}
            explanation={
              <>
                <p>
                  The server will keep v{viewed.version} as this record&apos;s current extraction. Its
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
                  A pinned version stays current even when the record is extracted again, including when
                  it is the latest now. &quot;Resume automatic latest selection&quot; removes the pin later. The
                  request is sent once and never retried automatically.
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
  entryId,
  extraction,
  isCurrent,
  isLatest,
  currentVersion,
  reviewable,
  onRecheckReview,
  onNavigateToUnit,
}: {
  entryId: number;
  extraction: Extraction;
  isCurrent: boolean;
  isLatest: boolean;
  currentVersion: number | null;
  reviewable: Reviewability | null;
  onRecheckReview: () => void;
  onNavigateToUnit?: (target: UnitTarget) => void;
}) {
  const target = (kind: UnitTarget["kind"], unitId: number): UnitTarget => ({
    kind,
    entryId,
    unitId,
    extractionId: extraction.id,
    extractionVersion: extraction.version,
  });
  // Review status applies only when it was read for this (current) extraction.
  const status =
    isCurrent && reviewable && (reviewable.status !== "ready" || reviewable.forExtractionId === extraction.id)
      ? reviewable
      : null;
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
      {status?.status === "error" ? (
        <div className="banner error" role="alert">
          Could not check which units await review: {status.message}{" "}
          <button type="button" className="ghost" onClick={onRecheckReview}>
            Recheck review status
          </button>
        </div>
      ) : null}
      {extraction.units.length === 0 ? (
        <p className="value">
          <strong>Zero units.</strong> This successful extraction produced no knowledge units.
        </p>
      ) : (
        <ul className="annotation-list" aria-label="Extracted units">
          {extraction.units.map((unit) => (
            // Focus returns here when the reader comes back from another view.
            <li key={unit.id} id={unitFocusId(unit.id)} tabIndex={-1}>
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
              {onNavigateToUnit ? (
                <UnitLinks
                  unitId={unit.id}
                  isCurrent={isCurrent}
                  status={status}
                  onReview={() => onNavigateToUnit(target("review", unit.id))}
                  onInspect={() => onNavigateToUnit(target("inspect", unit.id))}
                />
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// UnitLinks offers Concept Review only for a unit the backend currently lists as
// awaiting review. Historical, resolved, and INVALID units can only be inspected.
function UnitLinks({
  unitId,
  isCurrent,
  status,
  onReview,
  onInspect,
}: {
  unitId: number;
  isCurrent: boolean;
  status: Reviewability | null;
  onReview: () => void;
  onInspect: () => void;
}) {
  let note: string;
  let canReview = false;
  if (!isCurrent) {
    note = "Historical unit: not reviewable while another version is current.";
  } else if (!status || status.status === "loading") {
    note = "Checking review status…";
  } else if (status.status === "error") {
    note = "Review status unknown.";
  } else if (status.data.has(unitId)) {
    note = "Awaiting concept review.";
    canReview = true;
  } else {
    note = "Not awaiting review (already resolved or marked INVALID).";
  }
  return (
    <div className="actions unit-links">
      <span className="hint">{note}</span>
      {canReview ? (
        <button type="button" className="ghost" onClick={onReview}>
          Review unit #{unitId} in Concept Review
        </button>
      ) : null}
      <button type="button" className="ghost" onClick={onInspect}>
        {isCurrent ? `Inspect unit #${unitId}` : `Inspect stored labels of unit #${unitId}`}
      </button>
    </div>
  );
}

// describeSelectionFailure reports a rejected selection change. Every error from
// the PUT or DELETE is returned before its transaction commits, so the selection
// was not changed; a missing response leaves the outcome unknown.
function describeSelectionFailure(error: unknown, wanted: Requested): Outcome {
  const what = wanted.kind === "pin" ? `v${wanted.version} may or may not have been pinned as current` : "the pin may or may not have been removed";
  if (error instanceof NetworkError) {
    return { kind: "uncertain", text: `No response was received, so ${what}.` };
  }
  if (error instanceof ApiError) {
    return {
      kind: "rejected",
      text: `The server did not change the current extraction selection (${error.status}): ${error.message}.`,
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
