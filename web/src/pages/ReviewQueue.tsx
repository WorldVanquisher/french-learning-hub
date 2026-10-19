import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import type {
  Concept,
  ConceptIdentity,
  CurrentMembership,
  ReviewableUnit,
  UnitConceptLink,
} from "../types/concept";
import { UnitCard } from "../components/UnitCard";
import { CandidateConceptCard } from "../components/CandidateConceptCard";
import { IdentityEditor } from "../components/IdentityEditor";
import { MembershipPanel } from "../components/MembershipPanel";
import { HistoryPanel } from "../components/HistoryPanel";
import { ResolutionActions, type ActionKind } from "../components/ResolutionActions";
import { discoverConcepts } from "../conceptSearch";
import type { UnitTarget } from "../navigation";
import {
  ExplicitAction,
  OutcomeBanner,
  RefreshBanner,
  type Outcome,
  type RefreshState,
} from "../components/ExplicitAction";
import {
  checkDecision,
  describeDecision,
  duplicateRisk,
  readBaseline,
  ReceiptMismatchError,
  resolvesUnit,
  sendDecision,
  type Baseline,
  type Decision,
} from "./reviewOutcome";

import {
  clearOperation,
  loadOperations,
  newOperation,
  OperationConflictError,
  recheckStorage,
  saveOperation,
  type StoredDecision,
} from "./annotationOperation";
import { msg, useI18n, type MessageKey, type MessageRef, type Msg } from "../i18n";

// Notice and reconciliation texts are kept as messages, so they follow a language
// switch; raw server error details inside them are never translated.
type Notice = { kind: "success" | "error" | "info"; text: Msg } | null;

// The latest decision outcome and the re-read that followed it, per unit.
type UnitStatus = { outcome: Outcome | null; refresh: { what: Msg; state: RefreshState } | null };

// A decision whose outcome is unknown (no response) and the check of the backend
// for its effect. Until the check finds it, or the reviewer explicitly accepts the
// risk, no other decision can be sent for that unit.
type Reconciliation = {
  decision: Decision;
  baseline: Baseline;
  check: "checking" | "found" | "not-found" | "failed";
  // A message, or raw error details from a failed check.
  text: Msg;
  acknowledged: boolean;
};

const restoredText = msg("review.restoredOperation");
const storageStillFailing = msg("review.storage.stillFailing");
const unitAuthority = (unitId: number) => msg("review.what.authority", { id: unitId });

function errorText(e: unknown): string {
  if (e instanceof ApiError) return `(${e.status}) ${e.message}`;
  return e instanceof Error ? e.message : String(e);
}

// IdentityDraft is the reviewer's editable NEW CONCEPT identity, tagged with the
// unit it was seeded from so a draft can never leak into another unit's editor.
type IdentityDraft = { unitId: number; value: ConceptIdentity };

// ReviewQueue is the single experimental annotation page. It walks the reviewer
// through the reviewable-units queue one at a time, shows current membership as the
// sole authority (never inferred from history), and keeps exact resolver matches
// separate from retrieval-only catalog discovery. Showing, searching, or selecting
// a candidate records nothing; only one of the seven explicit human actions writes
// annotation data. After a successful explicit decision it advances the queue
// without a page refresh.
//
// With `focus` (opened from a record's extracted unit) it shows only that record's
// units the backend lists as awaiting review, opens the focused unit when it is
// listed, and otherwise explains why it is not, without presenting it as a queue
// candidate. Writes are unchanged.
export function ReviewQueue({
  focus = null,
  onBack,
  onInspect,
}: {
  focus?: UnitTarget | null;
  onBack?: () => void;
  onInspect?: (unitId: number) => void;
} = {}) {
  const [queue, setQueue] = useState<ReviewableUnit[]>([]);
  // Set after the first focused load when the focused unit is not reviewable now.
  const [focusMissing, setFocusMissing] = useState(false);
  // Only the latest queue read is applied (StrictMode replays and reloads overlap).
  const queueRequest = useRef(0);
  const focusHeadingRef = useRef<HTMLHeadingElement>(null);
  const [index, setIndex] = useState(0);
  const [loadingQueue, setLoadingQueue] = useState(true);
  // The decision currently being sent. While set, no decision or unit switch is possible.
  const { t, render } = useI18n();
  const [pendingWrite, setPendingWrite] = useState<{ unitId: number; label: MessageRef } | null>(null);
  const writeInFlight = useRef(false);
  const [unitStatus, setUnitStatus] = useState<Record<number, UnitStatus>>({});
  const [reconciliations, setReconciliations] = useState<Record<number, Reconciliation>>({});
  const reconciliationsRef = useRef(reconciliations);
  reconciliationsRef.current = reconciliations;
  // Only the latest check per unit is applied.
  const checkRequest = useRef(new Map<number, number>());
  const unitContextRequest = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const [notice, setNotice] = useState<Notice>(null);
  // Page-wide: browser storage cannot be read or written, so keyed decisions are
  // disabled until an explicit recheck succeeds. A per-unit conflict never sets it.
  const [storageFailure, setStorageFailure] = useState<MessageRef | null>(null);
  // Exact saved operations whose cleanup failed; an explicit recheck retries them.
  const pendingCleanup = useRef(new Map<string, Decision>());
  useEffect(() => {
    try {
      const saved = loadOperations();
      const restored: Record<number, Reconciliation> = {};
      for (const decision of saved) restored[decision.unitId] = {
        decision, baseline: null, check: "not-found", text: restoredText, acknowledged: false,
      };
      setReconciliations(restored);
      reconciliationsRef.current = restored;
    } catch { setStorageFailure(msg("review.storage.unavailable")); }
  }, []);

  // cleanUp removes exactly this saved operation (key and payload), also after the
  // page was left, so a newer operation is never removed. A failure is reported
  // and kept for the explicit storage recheck.
  const cleanUp = useCallback((decision: Decision, failure: MessageRef) => {
    if (!decision.operationId) return;
    try {
      clearOperation(decision);
      pendingCleanup.current.delete(decision.operationId);
    } catch {
      pendingCleanup.current.set(decision.operationId, decision);
      if (mounted.current) setStorageFailure(failure);
    }
  }, []);
  const [catalog, setCatalog] = useState<Concept[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);

  // Per-unit review state.
  const [loadedUnitContextId, setLoadedUnitContextId] = useState<number | null>(null);
  const [membership, setMembership] = useState<CurrentMembership | null>(null);
  const [candidates, setCandidates] = useState<Concept[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedConceptId, setSelectedConceptId] = useState<number | null>(null);
  const [identityDraft, setIdentityDraft] = useState<IdentityDraft | null>(null);
  const [history, setHistory] = useState<UnitConceptLink[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const current: ReviewableUnit | undefined = queue[index];
  // Read by asynchronous results, which must only change the unit still shown.
  const currentUnitRef = useRef<number | null>(null);
  currentUnitRef.current = current?.unit_id ?? null;
  const queueRef = useRef(queue);
  queueRef.current = queue;
  const unitContextReady = current !== undefined && loadedUnitContextId === current.unit_id;
  const identity = current !== undefined && identityDraft?.unitId === current.unit_id ? identityDraft.value : null;
  const exactConceptIds = useMemo(() => new Set(candidates.map((concept) => concept.id)), [candidates]);
  const discoveryCandidates = useMemo(
    () => discoverConcepts(catalog, searchQuery, exactConceptIds),
    [catalog, exactConceptIds, searchQuery],
  );

  // loadQueue fetches the reviewable units. Any error is surfaced, never swallowed.
  const loadQueue = useCallback(async () => {
    const request = ++queueRequest.current;
    setLoadingQueue(true);
    try {
      // Backend eligibility only: a focused view reads the record's reviewable units.
      const units = await api.listReviewableUnits(focus?.entryId);
      if (request !== queueRequest.current) return;
      setQueue(units);
      const focusedIndex = focus ? units.findIndex((u) => u.unit_id === focus.unitId) : -1;
      setIndex(Math.max(0, focusedIndex));
      setFocusMissing(focus !== null && focusedIndex < 0);
    } catch (e) {
      if (request !== queueRequest.current) return;
      setNotice({ kind: "error", text: describe(e, "review.error.queue") });
    } finally {
      if (request === queueRequest.current) setLoadingQueue(false);
    }
  }, [focus]);

  // Opened from a record: move keyboard focus to the record context.
  useEffect(() => {
    if (focus) focusHeadingRef.current?.focus();
  }, [focus]);

  // The durable concept catalog is discovery input only. Loading it records no
  // annotation and does not affect deterministic exact-signature resolution.
  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true);
    try {
      setCatalog(await api.listConcepts());
    } catch (e) {
      setNotice({ kind: "error", text: describe(e, "review.error.catalog") });
    } finally {
      setCatalogLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadQueue();
    void loadCatalog();
  }, [loadCatalog, loadQueue]);

  // readUnitAuthority re-reads the backend-owned context for one unit: current
  // membership (the authority) and any exact-signature candidate concepts. It never
  // touches the reviewer's identity draft or search query.
  const readUnitAuthority = useCallback(async (unit: ReviewableUnit, preselectLoneMatch: boolean) => {
    const request = ++unitContextRequest.current;
    try {
      const [mEnv, outcome] = await Promise.all([
        api.getCurrentMembership(unit.unit_id),
        api.resolveUnit(unit.unit_id),
      ]);
      if (!mounted.current || currentUnitRef.current !== unit.unit_id || unitContextRequest.current !== request) return;
      setMembership(mEnv.current_membership);
      setCandidates(outcome.matches);
      // Pre-select a lone exact match to speed up the common SAME decision.
      if (preselectLoneMatch && outcome.matches.length === 1) {
        setSelectedConceptId(outcome.matches[0].id);
      }
      setLoadedUnitContextId(unit.unit_id);
    } catch (e) {
      setNotice({ kind: "error", text: describe(e, "review.error.unitContext") });
    }
  }, []);

  // loadUnitContext starts reviewing a different unit: all unit-specific state is
  // reset and a fresh editable identity is seeded from the backend candidate.
  const loadUnitContext = useCallback(async (unit: ReviewableUnit) => {
    setLoadedUnitContextId(null);
    setMembership(null);
    setCandidates([]);
    setSearchQuery(unit.candidate_identity.target);
    setSelectedConceptId(null);
    setHistory([]);
    setIdentityDraft({
      unitId: unit.unit_id,
      value: { ...unit.candidate_identity, identity_features: { ...unit.candidate_identity.identity_features } },
    });
    await readUnitAuthority(unit, true);
  }, [readUnitAuthority]);


  useEffect(() => {
    if (current) {
      void loadUnitContext(current);
    }
  }, [current, loadUnitContext]);

  const loadHistory = useCallback(async (conceptId: number) => {
    setHistoryLoading(true);
    try {
      const view = await api.getConcept(conceptId);
      setHistory(view.links);
    } catch (e) {
      setNotice({ kind: "error", text: describe(e, "review.error.history") });
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const setStatus = useCallback((unitId: number, change: Partial<UnitStatus>) => {
    setUnitStatus((all) => ({ ...all, [unitId]: { ...(all[unitId] ?? { outcome: null, refresh: null }), ...change } }));
  }, []);

  // removeUnit drops one unit by ID (never by position) from the in-memory queue,
  // keeping the reviewer on the unit they are looking at.
  const removeUnit = useCallback((unitId: number) => {
    const q = queueRef.current;
    const at = q.findIndex((u) => u.unit_id === unitId);
    if (at < 0) return;
    const next = q.filter((u) => u.unit_id !== unitId);
    setQueue(next);
    setIndex((i) => Math.min(i > at ? i - 1 : i, Math.max(0, next.length - 1)));
  }, []);

  // rereadUnit re-reads a unit's backend authority after a write and reports that
  // re-read separately from the write's outcome. The shown context changes only if
  // the reviewer is still on that unit. The identity draft and search query are
  // kept (e.g. DISTINCT A, then NEW CONCEPT B from the edited identity); the
  // selection is cleared so the concept just judged is not re-targeted by accident.
  const rereadUnit = useCallback(
    async (unit: ReviewableUnit, what: Msg, effective = false) => {
      const id = unit.unit_id;
      const request = checkRequest.current.get(id);
      setStatus(id, { refresh: { what, state: { kind: "refreshing" } } });
      try {
        const [env, outcome] = await Promise.all([api.getCurrentMembership(id), api.resolveUnit(id)]);
        if (!mounted.current || checkRequest.current.get(id) !== request) return;
        if (currentUnitRef.current === id) {
          setMembership(env.current_membership);
          setCandidates(outcome.matches);
          setSelectedConceptId(null);
          setLoadedUnitContextId(id);
        }
        if (effective) await api.getEffectiveAnnotation(id);
        if (!mounted.current || checkRequest.current.get(id) !== request) return;
        setStatus(id, { refresh: { what, state: { kind: "refreshed" } } });
      } catch (e) {
        if (mounted.current && checkRequest.current.get(id) === request) setStatus(id, { refresh: { what, state: { kind: "failed", message: errorText(e) } } });
      }
    },
    [setStatus],
  );

  const updateReconciliation = useCallback((unitId: number, change: Partial<Reconciliation>) => {
    setReconciliations((all) => (all[unitId] ? { ...all, [unitId]: { ...all[unitId], ...change } } : all));
  }, []);

  // runCheck reads the backend authority or history the unknown decision would
  // have changed. Finding nothing never counts as failure: the original request
  // may still be in progress on the server.
  const runCheck = useCallback(
    async (unitId: number) => {
      const rec = reconciliationsRef.current[unitId];
      if (!rec) return;
      const request = (checkRequest.current.get(unitId) ?? 0) + 1;
      checkRequest.current.set(unitId, request);
      const stale = () => !mounted.current || checkRequest.current.get(unitId) !== request;
      updateReconciliation(unitId, { check: "checking" });
      try {
        const evidence = await checkDecision(rec.decision, rec.baseline);
        if (stale()) return;
        if (!evidence.found) {
          updateReconciliation(unitId, { check: "not-found", text: evidence.text });
          return;
        }
        updateReconciliation(unitId, { check: "found", text: evidence.text });
        if (rec.decision.operationId) {
          setStatus(unitId, { outcome: { kind: "succeeded", text: evidence.text } });
          cleanUp(rec.decision, msg("review.storage.cleanupAfterReceipt"));
          if (stale()) return;
        }
        const label = describeDecision(rec.decision);
        if (resolvesUnit(rec.decision)) {
          removeUnit(unitId);
          setNotice({
            kind: "info",
            text: msg("review.foundLeftQueue", { id: unitId, label, evidence: evidence.text }),
          });
        } else {
          const unit = queueRef.current.find((u) => u.unit_id === unitId);
          if (unit) await rereadUnit(unit, unitAuthority(unitId), !!rec.decision.operationId);
        }
      } catch (e) {
        if (!stale()) updateReconciliation(unitId, { check: "failed", text: e instanceof ReceiptMismatchError ? msg("check.receiptMismatch") : errorText(e) });
      }
    },
    [cleanUp, removeUnit, rereadUnit, updateReconciliation, setStatus],
  );

  // adoptConflict keeps the unresolved operation already saved for this unit (for
  // example by another tab) and shows it for this unit only. Nothing is sent and
  // other units are unaffected.
  function adoptConflict(unitId: number, decision: Decision, existing: StoredDecision) {
    const label = describeDecision(existing);
    const text = existing.operationId === decision.operationId
      ? msg("review.conflict.sameKey", { label })
      : msg("review.conflict.otherTab", { label, id: unitId });
    const rec: Reconciliation = { decision: existing, baseline: null, check: "not-found", text, acknowledged: false };
    reconciliationsRef.current = { ...reconciliationsRef.current, [unitId]: rec };
    setReconciliations((all) => ({ ...all, [unitId]: rec }));
  }

  // recheckStorageNow is the explicit recovery from a storage failure: it retries
  // failed cleanups, proves storage can be read and written, and restores saved
  // operations for units this page is not already tracking. It never sends.
  function recheckStorageNow() {
    let saved: StoredDecision[];
    try {
      for (const d of [...pendingCleanup.current.values()]) {
        clearOperation(d);
        pendingCleanup.current.delete(d.operationId!);
      }
      saved = recheckStorage();
    } catch {
      setStorageFailure(storageStillFailing);
      return;
    }
    const next = { ...reconciliationsRef.current };
    for (const decision of saved) {
      const rec = next[decision.unitId];
      if (!rec || rec.check === "found") next[decision.unitId] = { decision, baseline: null, check: "not-found", text: restoredText, acknowledged: false };
    }
    reconciliationsRef.current = next;
    setReconciliations(next);
    setStorageFailure(null);
    setNotice({ kind: "info", text: msg("review.storage.recovered") });
  }

  const blockedFor = (unitId: number) => {
    const rec = reconciliations[unitId];
    return rec !== undefined && rec.check !== "found" && !rec.acknowledged;
  };

  function buildDecision(action: ActionKind, unit: ReviewableUnit): Decision | null {
    const unitId = unit.unit_id;
    switch (action) {
      case "same":
        // An existing membership means an explicit ReassignSame; never create+seed.
        return selectedConceptId === null ? null : { kind: "same", unitId, conceptId: selectedConceptId, reassign: membership !== null };
      case "new":
        // Seed SAME only when the unit is unresolved; otherwise only create the concept.
        return identity ? { kind: "new", unitId, identity, seedAsSame: membership === null } : null;
      case "broader":
      case "narrower":
      case "related":
        return selectedConceptId === null ? null : { kind: "relation", unitId, conceptId: selectedConceptId, relation: action };
      case "distinct":
        return selectedConceptId === null ? null : { kind: "distinct", unitId, conceptId: selectedConceptId };
      case "invalid":
        return { kind: "invalid", unitId };
    }
  }

  // act sends one explicit human decision once. A server answer is either a
  // confirmed success or a rejection; no answer is an unknown outcome, which is
  // reconciled against backend state and never resent automatically.
  async function act(action: ActionKind, retry?: Decision) {
    if (!current || writeInFlight.current || (!retry && blockedFor(current.unit_id))) return;
    const unit = current;
    const unitId = unit.unit_id;
    const draft = retry ?? buildDecision(action, unit);
    if (!draft) return;
    let decision: Decision;
    if ((draft.kind === "distinct" || draft.kind === "relation") && storageFailure) {
      setNotice({ kind: "error", text: msg("review.storage.blocked") });
      return;
    }
    try {
      decision = retry ?? newOperation(draft);
    } catch {
      setNotice({ kind: "error", text: msg("review.keyFailed") });
      return;
    }
    try {
      saveOperation(decision);
    } catch (e) {
      if (e instanceof OperationConflictError) adoptConflict(unitId, decision, e.existing);
      else setStorageFailure(msg("review.storage.saveFailed"));
      return;
    }
    if (!decision) return;
    const label = describeDecision(decision);
    checkRequest.current.set(unitId, (checkRequest.current.get(unitId) ?? 0) + 1);
    writeInFlight.current = true;
    setPendingWrite({ unitId, label });
    if (!retry) setReconciliations((all) => {
      const next = { ...all };
      delete next[unitId];
      return next;
    });
    setNotice(null);
    setStatus(unitId, { outcome: null, refresh: null });
    try {
      let baseline: Baseline;
      try {
        baseline = await readBaseline(decision);
      } catch (e) {
        setStatus(unitId, {
          outcome: { kind: "rejected", text: msg("review.baselineFailed", { label, error: errorText(e) }) },
        });
        return;
      }
      try {
        const text = await sendDecision(decision);
        if (decision.operationId) {
          cleanUp(decision, msg("review.storage.cleanupAfterCommit"));
          updateReconciliation(unitId, { check: "found", text: msg("review.committed") });
        }
        if (!mounted.current) return;
        if (resolvesUnit(decision)) {
          removeUnit(unitId);
          setNotice({ kind: "success", text: msg("review.unitResult", { id: unitId, text }) });
        } else {
          setStatus(unitId, { outcome: { kind: "succeeded", text } });
          await rereadUnit(unit, unitAuthority(unitId), !!decision.operationId);
        }
      } catch (e) {
        const unknown = e instanceof NetworkError || !(e instanceof ApiError) || (!!decision.operationId && e.status >= 500);
        // A definite rejection stored nothing under this key: remove exactly this
        // saved operation, even if Concept Review was left meanwhile. A rejected
        // retry does not cancel the original request, so it is kept.
        if (!unknown && decision.operationId && !retry) {
          cleanUp(decision, msg("review.storage.cleanupAfterReject"));
        }
        if (!mounted.current) return;
        if (unknown || !(e instanceof ApiError)) {
          setStatus(unitId, {
            outcome: {
              kind: "uncertain",
              text: msg(decision.operationId ? "review.unknown.keyed" : "review.unknown", { label, id: unitId }),
            },
          });
          setReconciliations((all) => ({
            ...all,
            [unitId]: { decision, baseline, check: "checking", text: "", acknowledged: false },
          }));
          reconciliationsRef.current = {
            ...reconciliationsRef.current,
            [unitId]: { decision, baseline, check: "checking", text: "", acknowledged: false },
          };
          void runCheck(unitId);
        } else {
          setStatus(unitId, {
            outcome: { kind: "rejected", text: msg("review.rejected", { label, error: errorText(e) }) },
          });
          if (retry?.operationId) {
            updateReconciliation(unitId, { check: "not-found", text: msg("review.retryRejected") });
          }
          // A conflict means authority may have changed underneath; re-read it.
          if (e.isConflict) await rereadUnit(unit, msg("review.what.membership", { id: unitId }));
        }
      }
    } finally {
      writeInFlight.current = false;
      if (mounted.current) setPendingWrite(null);
    }
  }

  const context = focus ? (
    <section className="panel record-context" aria-label={t("focus.context")}>
      <h2 ref={focusHeadingRef} tabIndex={-1}>
        {t("review.focus.heading", { id: focus.entryId })}
      </h2>
      <p className="hint">{t("review.focus.hint", { unit: focus.unitId, version: focus.extractionVersion })}</p>
      {onBack ? (
        <button type="button" className="ghost" onClick={onBack}>
          {t("focus.back", { id: focus.entryId })}
        </button>
      ) : null}
    </section>
  ) : null;

  const missing =
    focus && focusMissing ? (
      <div className="banner info" role="alert">
        <strong>{t("review.focus.missing", { id: focus.unitId })}</strong> {t("review.focus.missing.detail")}{" "}
        {onInspect ? (
          <button type="button" className="ghost" onClick={() => onInspect(focus.unitId)}>
            {t("unitLinks.inspect", { id: focus.unitId })}
          </button>
        ) : null}
      </div>
    ) : null;

  if (loadingQueue) {
    return (
      <div>
        {context}
        <p className="empty">{t("review.loading")}</p>
      </div>
    );
  }

  if (!current) {
    return (
      <div>
        {context}
        {missing}
        {notice ? <div className={`banner ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{render(notice.text)}</div> : null}
        <div className="empty">
          <p>{focus ? t("review.empty.focus", { id: focus.entryId }) : t("review.empty")}</p>
          <button
            className="ghost"
            onClick={() => {
              void loadQueue();
              void loadCatalog();
            }}
          >
            {t("review.reloadQueue")}
          </button>
        </div>
      </div>
    );
  }

  // History is shown for the selected candidate, else for the unit's current concept.
  const historyConceptId = selectedConceptId ?? membership?.concept_id ?? null;

  return (
    <div>
      {context}
      {missing}
      {focus && focusMissing ? (
        <p className="hint">{t("review.focus.others", { id: focus.entryId })}</p>
      ) : null}
      {notice ? <div className={`banner ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{render(notice.text)}</div> : null}

      <div className="queue-nav">
        <button
          className="ghost"
          disabled={index === 0 || pendingWrite !== null}
          onClick={() => setIndex((i) => Math.max(0, i - 1))}
        >
          {t("review.previous")}
        </button>
        <span className="position">{t("review.position", { index: index + 1, total: queue.length })}</span>
        <button
          className="ghost"
          disabled={index >= queue.length - 1 || pendingWrite !== null}
          onClick={() => setIndex((i) => Math.min(queue.length - 1, i + 1))}
        >
          {t("review.skip")}
        </button>
        <button
          className="ghost"
          onClick={() => {
            void loadQueue();
            void loadCatalog();
          }}
        >
          {t("review.reloadQueueLower")}
        </button>
      </div>

      <div className="grid">
        <div>
          <UnitCard unit={current} />
          <MembershipPanel membership={membership} />
        </div>

        <div>
          <div className="panel">
            <h2>{t("review.exact.title")}</h2>
            <p className="hint">{t("review.exact.hint")}</p>
            {!unitContextReady ? (
              <p className="value">{t("review.exact.loading")}</p>
            ) : candidates.length === 0 ? (
              <p className="value">
                <em>{t("review.exact.none")}</em> {t("review.exact.none.detail")}
              </p>
            ) : (
              <div className="candidate-list">
                {candidates.map((c) => (
                  <CandidateConceptCard
                    key={c.id}
                    concept={c}
                    selected={selectedConceptId === c.id}
                    onSelect={() => setSelectedConceptId(selectedConceptId === c.id ? null : c.id)}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="panel">
            <h2>{t("review.search.title")}</h2>
            <p className="hint">{t("review.search.hint")}</p>
            <label className="discovery-search" htmlFor="concept-discovery-search">
              {t("review.search.label")}
            </label>
            <div className="discovery-search-row">
              <input
                id="concept-discovery-search"
                type="search"
                aria-label={t("review.search.title")}
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
              <button type="button" className="ghost" onClick={() => setSearchQuery("")}>
                {t("common.clear")}
              </button>
            </div>
            {catalogLoading ? (
              <p className="value">{t("review.search.catalogLoading")}</p>
            ) : !unitContextReady ? (
              <p className="value">{t("review.search.contextLoading")}</p>
            ) : discoveryCandidates.length === 0 ? (
              <p className="value">
                <em>{t("review.search.none")}</em>
              </p>
            ) : (
              <div className="candidate-list discovery-results">
                {discoveryCandidates.map((concept) => (
                  <CandidateConceptCard
                    key={concept.id}
                    concept={concept}
                    selected={selectedConceptId === concept.id}
                    onSelect={() =>
                      setSelectedConceptId(selectedConceptId === concept.id ? null : concept.id)
                    }
                  />
                ))}
              </div>
            )}
          </div>

          <div className="panel">
            <h2>{t("review.identity.title")}</h2>
            {identity ? (
              // Keyed by unit so the editor's local feature rows reset with the unit.
              <IdentityEditor
                key={current.unit_id}
                value={identity}
                onChange={(value) => setIdentityDraft({ unitId: current.unit_id, value })}
              />
            ) : null}
          </div>
        </div>
      </div>

      {storageFailure ? (
        <div className="banner error" role="alert">
          {render(storageFailure)}{" "}
          <button type="button" className="ghost" onClick={recheckStorageNow}>
            {t("review.storage.recheck")}
          </button>
        </div>
      ) : null}
      <ResolutionActions
        membership={membership}
        selectedConceptId={selectedConceptId}
        busy={pendingWrite !== null || blockedFor(current.unit_id)}
        keyedUnavailable={storageFailure !== null}
        onAct={act}
      />
      {pendingWrite ? (
        <p className="hint" role="status">
          {t("review.sending", { label: pendingWrite.label, id: pendingWrite.unitId })}
        </p>
      ) : null}
      <OutcomeBanner outcome={unitStatus[current.unit_id]?.outcome ?? null} />
      {unitStatus[current.unit_id]?.refresh ? (
        <RefreshBanner
          refresh={unitStatus[current.unit_id]!.refresh!.state}
          what={unitStatus[current.unit_id]!.refresh!.what}
        />
      ) : null}
      {reconciliations[current.unit_id] ? (
        <ReconciliationPanel
          key={current.unit_id}
          unitId={current.unit_id}
          rec={reconciliations[current.unit_id]}
          onCheck={() => void runCheck(current.unit_id)}
          onAllow={async () => updateReconciliation(current.unit_id, { acknowledged: true })}
          onRetry={() => void act("distinct", reconciliations[current.unit_id].decision)}
          busy={pendingWrite !== null}
          storageUnavailable={storageFailure !== null}
        />
      ) : null}

      <HistoryPanel
        title={
          historyConceptId !== null
            ? t("review.history.title", { id: historyConceptId })
            : t("review.history.select")
        }
        links={history}
        loading={historyLoading}
        unitId={current.unit_id}
      />
      {historyConceptId !== null ? (
        <button className="ghost" disabled={historyLoading} onClick={() => void loadHistory(historyConceptId)}>
          {t("review.history.load", { id: historyConceptId })}
        </button>
      ) : null}
    </div>
  );
}

// describe extracts a human-readable message from an error, preferring the backend's
// error text. Errors are never swallowed — this feeds the visible banner.
function describe(e: unknown, what: MessageKey): MessageRef {
  if (e instanceof ApiError) return msg("review.error.detail", { what: msg(what), detail: `(${e.status}) ${e.message}` });
  if (e instanceof Error) return msg("review.error.detail", { what: msg(what), detail: e.message });
  return msg(what);
}

// ReconciliationPanel shows the check of an unknown decision outcome and the only
// ways forward: check again, or explicitly allow another decision knowing the
// risk. It never resends anything itself.
function ReconciliationPanel({
  unitId,
  rec,
  onCheck,
  onAllow,
  onRetry,
  busy,
  storageUnavailable,
}: {
  unitId: number;
  rec: Reconciliation;
  onCheck: () => void;
  onAllow: () => Promise<void>;
  onRetry: () => void;
  busy: boolean;
  storageUnavailable: boolean;
}) {
  const { t, render } = useI18n();
  const label = String(render(describeDecision(rec.decision)));
  const text = String(render(rec.text) ?? "");
  if (rec.check === "checking") {
    return (
      <p className="hint" role="status">
        {t("reconcile.checking", { label, id: unitId })}
      </p>
    );
  }
  if (rec.check === "found") {
    return (
      <p className="hint" role="status">
        {t("reconcile.found", { text, label })}
      </p>
    );
  }
  if (rec.decision.operationId) return (
    <section className="panel reconciliation" aria-label={t("reconcile.region")}>
      <h2>{t("reconcile.unknown", { label })}</h2>
      <p>{text}</p>
      <p>{t("reconcile.savedOperation", { key: rec.decision.operationId })}</p>
      <button disabled={busy} onClick={onCheck}>{t("reconcile.checkReceipt")}</button>
      <button disabled={busy || storageUnavailable} onClick={onRetry}>{t("reconcile.retrySaved")}</button>
      {storageUnavailable ? <p className="hint">{t("reconcile.retryWaits")}</p> : null}
    </section>
  );
  return (
    <section className="panel reconciliation" aria-label={t("reconcile.region")}>
      <h2>{t("reconcile.unknown", { label })}</h2>
      {rec.check === "failed" ? (
        <div className="banner error" role="alert">
          {t("reconcile.checkFailed", { label, text })}
        </div>
      ) : (
        <p>{t("reconcile.notVisible", { text })}</p>
      )}
      {rec.acknowledged ? (
        <p className="hint">{t("reconcile.allowed", { id: unitId, label })}</p>
      ) : (
        <p className="hint">{t("reconcile.waiting", { id: unitId })}</p>
      )}
      <div className="actions">
        <button type="button" className="ghost" onClick={onCheck}>
          {t("reconcile.checkAgain")}
        </button>
      </div>
      {!rec.acknowledged ? (
        <ExplicitAction
          label={t("reconcile.allow", { id: unitId })}
          confirmLabel={t("reconcile.allow.confirm")}
          pending={false}
          onConfirm={onAllow}
          explanation={<p>{t("reconcile.allow.explain", { risk: duplicateRisk(rec.decision) })}</p>}
        />
      ) : null}
    </section>
  );
}
