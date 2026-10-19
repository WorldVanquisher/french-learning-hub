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
import { msg, useI18n } from "../i18n";

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
  const { t } = useI18n();
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
      const version = created.version;
      next = {
        kind: "succeeded",
        text: (i) => (n === 0 ? i.t("extraction.stored.empty", { version }) : i.tp("extraction.stored", n, { version })),
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
      return { kind: "succeeded", text: msg("extraction.pinAccepted", { version: target.version }) };
    });

  const resumeAutomatic = () =>
    changeSelection({ kind: "automatic" }, async () => {
      const reported = await api.clearCurrentExtraction(entryId);
      return {
        kind: "succeeded",
        text: (i) =>
          i.t(reported.current_extraction_id === null ? "extraction.unpinned.none" : "extraction.unpinned", {
            mode: i.status(reported.selection_mode),
          }),
      };
    });

  // After an unknown outcome a new write could repeat it, so the same action
  // stays unavailable until stored state was re-read.
  const extractionBlocked = extractionNeedsCheck ? t("extraction.blocked") : null;
  const selectionBlocked = selectionNeedsCheck ? t("extraction.selectionBlocked") : null;

  return (
    <section className="panel" aria-label={t("extraction.title")}>
      <h2>{t("extraction.title")}</h2>
      <p className="hint">
        {latestVersion !== null ? t("extraction.hint.version", { version: latestVersion }) : t("extraction.hint")}
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
          label={t("extraction.request")}
          confirmLabel={t("extraction.confirm")}
          pending={pending}
          disabledReason={extractionBlocked}
          onConfirm={submit}
          explanation={
            <>
              <p>{t("extraction.explain.provider")}</p>
              <p>{t("extraction.explain.eligibility")}</p>
            </>
          }
        />
        <OutcomeBanner outcome={outcome} />
      </div>
      <RefreshBanner refresh={refresh} what={msg("extraction.what")} />
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
  const { t, status } = useI18n();
  if (!requested || refresh.kind !== "refreshed" || load.status !== "ready") return null;
  const { current, extractions } = load.data;
  const versionOf = (id: number | null) => {
    const e = extractions.find((x) => x.id === id);
    return e
      ? t("record.version", { version: e.version })
      : id === null
        ? t("extraction.noExtraction")
        : t("extraction.byId", { id });
  };
  const stored = t("extraction.storedSelection", {
    version: versionOf(current.current_extraction_id),
    mode: status(current.selection_mode),
  });
  const matches =
    requested.kind === "pin"
      ? current.selection_mode === "pinned" && current.current_extraction_id === requested.extractionId
      : current.selection_mode === "automatic";
  if (matches) {
    return (
      <p className="hint" role="status">
        {t("extraction.confirmedByReread", { stored })}
      </p>
    );
  }
  const wanted =
    requested.kind === "pin" ? t("extraction.wantedPinned", { version: requested.version }) : t("extraction.wantedAutomatic");
  return (
    <div className="banner error" role="alert">
      {t("extraction.rereadMismatch", { stored, wanted })}
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
  const { t, tp } = useI18n();
  if (load.status === "loading") {
    return <p className="value">{t("extraction.loading")}</p>;
  }
  if (load.status === "error") {
    return (
      <div className="banner error" role="alert">
        {t("extraction.loadFailed", { message: load.message })}{" "}
        <button type="button" className="ghost" onClick={onRetry}>
          {t("extraction.reload")}
        </button>
      </div>
    );
  }
  const { extractions, current } = load.data;
  const pinned = current.selection_mode === "pinned";
  if (extractions.length === 0) {
    return (
      <p className="value">
        <strong>{t("extraction.none")}</strong> {t("extraction.none.detail")}
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
      <p className="value" aria-label={t("extraction.summary")}>
        {tp("extraction.summaryLine", extractions.length, {
          current: currentExtraction ? t("record.version", { version: currentExtraction.version }) : t("extraction.currentNone"),
          mode: pinned ? t("status.pinned") : t("status.automatic"),
          latest: latest.version,
        })}
      </p>
      <p className="hint" aria-label={t("extraction.selectionMode")}>
        {pinned
          ? currentExtraction && currentExtraction.id === latest.id
            ? t("extraction.pinnedLatest", { version: currentExtraction.version })
            : t("extraction.pinnedOlder", { version: currentExtraction?.version ?? "?", latest: latest.version })
          : t("extraction.automatic")}
      </p>
      {!currentExtraction ? (
        <p className="hint">
          <strong>{t("extraction.noCurrent")}</strong> {t("extraction.noCurrent.detail")}
        </p>
      ) : null}
      {pinned ? (
        <div className="workflow-action">
          <ExplicitAction
            label={t("extraction.resume")}
            confirmLabel={t("extraction.resume.confirm")}
            pending={selectPending}
            disabledReason={selectionBlocked}
            onConfirm={onResumeAutomatic}
            explanation={
              <>
                <p>{t("extraction.resume.explain", { version: latest.version })}</p>
                <p>{t("extraction.resume.nothingDeleted")}</p>
              </>
            }
          />
        </div>
      ) : null}
      <p className="hint">{t("extraction.viewOnly")}</p>
      <div className="version-list" role="group" aria-label={t("extraction.versions")}>
        {versions.map((e) => {
          const tags = [
            e.id === currentExtraction?.id ? (pinned ? t("extraction.tag.currentPinned") : t("extraction.tag.current")) : null,
            e.id === latest.id ? t("extraction.tag.latest") : null,
          ].filter(Boolean);
          return (
            <button
              key={e.id}
              type="button"
              className={e.id === viewed.id ? "primary" : "ghost"}
              aria-pressed={e.id === viewed.id}
              onClick={() => onView(e.id)}
            >
              {tags.length
                ? t("extraction.versionTagged", { version: e.version, tags: tags.join(t("extraction.tagSeparator")) })
                : t("record.version", { version: e.version })}
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
            label={t("extraction.pin", { version: viewed.version })}
            confirmLabel={t("extraction.pin.confirm", { version: viewed.version })}
            pending={selectPending}
            disabledReason={selectionBlocked}
            onConfirm={() => onPin(viewed)}
            explanation={
              <>
                <p>{t("extraction.pin.explain", { version: viewed.version })}</p>
                <p>{t("extraction.pin.nothingDeleted")}</p>
                <p>{t("extraction.pin.stays", { resume: t("extraction.resume") })}</p>
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
  const { t, status: useStatus } = useI18n();
  // Review status applies only when it was read for this (current) extraction.
  const status =
    isCurrent && reviewable && (reviewable.status !== "ready" || reviewable.forExtractionId === extraction.id)
      ? reviewable
      : null;
  return (
    <div className="annotation-section" aria-label={t("extraction.viewed")}>
      <h3>
        {t("extraction.viewing", { version: extraction.version })}{" "}
        <span className="hint">
          {t(isCurrent ? (isLatest ? "extraction.viewTags.currentLatest" : "extraction.viewTags.current") : isLatest ? "extraction.viewTags.notCurrentLatest" : "extraction.viewTags.notCurrent")}
        </span>
      </h3>
      <p className="hint">
        {isCurrent
          ? t("extraction.isCurrent")
          : currentVersion !== null
            ? t("extraction.notCurrent.while", { version: currentVersion })
            : t("extraction.notCurrent")}
      </p>
      <div className="annotation-provenance">
        <span className="mono">{extraction.extractor}</span>
        <span>{t("extraction.fromAnalysis", { id: extraction.source_analysis_id })}</span>
        <span>
          {extraction.source_feedback_id !== null ? `feedback #${extraction.source_feedback_id}` : t("provenance.noFeedback")}
        </span>
        <time dateTime={extraction.created_at}>{extraction.created_at}</time>
      </div>
      {status?.status === "error" ? (
        <div className="banner error" role="alert">
          {t("extraction.reviewCheckFailed", { message: status.message })}{" "}
          <button type="button" className="ghost" onClick={onRecheckReview}>
            {t("extraction.recheckReview")}
          </button>
        </div>
      ) : null}
      {extraction.units.length === 0 ? (
        <p className="value">
          <strong>{t("extraction.zeroUnits")}</strong> {t("extraction.zeroUnits.detail")}
        </p>
      ) : (
        <ul className="annotation-list" aria-label={t("extraction.units")}>
          {extraction.units.map((unit) => (
            // Focus returns here when the reader comes back from another view.
            <li key={unit.id} id={unitFocusId(unit.id)} tabIndex={-1}>
              <dl className="unit-evidence">
                <div><dt>{t("unit.unit")}</dt><dd>#{unit.id} · {unit.kind}</dd></div>
                <div><dt>{t("unit.canonical")}</dt><dd className="french">{unit.canonical}</dd></div>
                <div><dt>{t("unit.statement")}</dt><dd className="french">{unit.statement}</dd></div>
                {unit.example ? <div><dt>{t("unit.example")}</dt><dd className="french">{unit.example}</dd></div> : null}
                <div><dt>{t("unit.confidence")}</dt><dd>{unit.confidence}</dd></div>
                <div>
                  <dt>{t("unit.admission")}</dt>
                  <dd>
                    {unit.admission.latest_override
                      ? t("unit.admission.override", {
                          state: useStatus(unit.admission.effective_state),
                          decision: unit.admission.latest_override.decision,
                        })
                      : t("unit.admission.machine", {
                          state: useStatus(unit.admission.effective_state),
                          reason: unit.admission.machine_reason,
                        })}
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
  const { t } = useI18n();
  let note: string;
  let canReview = false;
  if (!isCurrent) {
    note = t("unitLinks.historical");
  } else if (!status || status.status === "loading") {
    note = t("unitLinks.checking");
  } else if (status.status === "error") {
    note = t("unitLinks.unknown");
  } else if (status.data.has(unitId)) {
    note = t("unitLinks.awaiting");
    canReview = true;
  } else {
    note = t("unitLinks.notAwaiting");
  }
  return (
    <div className="actions unit-links">
      <span className="hint">{note}</span>
      {canReview ? (
        <button type="button" className="ghost" onClick={onReview}>
          {t("unitLinks.review", { id: unitId })}
        </button>
      ) : null}
      <button type="button" className="ghost" onClick={onInspect}>
        {isCurrent ? t("unitLinks.inspect", { id: unitId }) : t("unitLinks.inspectHistorical", { id: unitId })}
      </button>
    </div>
  );
}

// describeSelectionFailure reports a rejected selection change. Every error from
// the PUT or DELETE is returned before its transaction commits, so the selection
// was not changed; a missing response leaves the outcome unknown.
function describeSelectionFailure(error: unknown, wanted: Requested): Outcome {
  if (error instanceof NetworkError) {
    return {
      kind: "uncertain",
      text: wanted.kind === "pin" ? msg("extraction.pinUnknown", { version: wanted.version }) : msg("extraction.unpinUnknown"),
    };
  }
  if (error instanceof ApiError) {
    return { kind: "rejected", text: msg("extraction.selectionRejected", { status: error.status, message: error.message }) };
  }
  return { kind: "rejected", text: msg("extraction.selectionFailed", { error: String(error) }) };
}

// describeExtractionFailure states only what the backend contract supports. Every
// error response means nothing was stored. Only 503 (extraction disabled) is
// returned before any provider call; a 409 can come from the eligibility check
// before the provider runs or from the source-changed check after it returns, so
// it never implies that no provider was called.
function describeExtractionFailure(error: unknown): Outcome {
  if (error instanceof NetworkError) {
    return { kind: "uncertain", text: msg("extraction.noResponse") };
  }
  if (!(error instanceof ApiError)) {
    return { kind: "rejected", text: msg("extraction.failed", { error: String(error) }) };
  }
  const detail = `(${error.status}) ${error.message}`;
  switch (error.status) {
    case 503:
      return { kind: "rejected", text: msg("extraction.disabled", { detail }) };
    case 409:
      return { kind: "rejected", text: msg("extraction.conflict", { detail }) };
    case 422:
      return { kind: "rejected", text: msg("extraction.resultRejected", { detail }) };
    case 502:
    case 504:
      return { kind: "rejected", text: msg("extraction.providerFailed", { detail }) };
    default:
      return { kind: "rejected", text: msg("extraction.notStored", { detail }) };
  }
}
