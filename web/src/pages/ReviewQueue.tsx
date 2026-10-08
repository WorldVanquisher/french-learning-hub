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
  resolvesUnit,
  sendDecision,
  type Baseline,
  type Decision,
} from "./reviewOutcome";

type Notice = { kind: "success" | "error" | "info"; text: string } | null;

// The latest decision outcome and the re-read that followed it, per unit.
type UnitStatus = { outcome: Outcome | null; refresh: { what: string; state: RefreshState } | null };

// A decision whose outcome is unknown (no response) and the check of the backend
// for its effect. Until the check finds it, or the reviewer explicitly accepts the
// risk, no other decision can be sent for that unit.
type Reconciliation = {
  decision: Decision;
  baseline: Baseline;
  check: "checking" | "found" | "not-found" | "failed";
  text: string;
  acknowledged: boolean;
};

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
  const [pendingWrite, setPendingWrite] = useState<{ unitId: number; label: string } | null>(null);
  const writeInFlight = useRef(false);
  const [unitStatus, setUnitStatus] = useState<Record<number, UnitStatus>>({});
  const [reconciliations, setReconciliations] = useState<Record<number, Reconciliation>>({});
  const reconciliationsRef = useRef(reconciliations);
  reconciliationsRef.current = reconciliations;
  // Only the latest check per unit is applied.
  const checkRequest = useRef(new Map<number, number>());
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const [notice, setNotice] = useState<Notice>(null);
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
      setNotice({ kind: "error", text: describe(e, "Could not load the review queue.") });
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
      setNotice({ kind: "error", text: describe(e, "Could not load the concept catalog.") });
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
    try {
      const [mEnv, outcome] = await Promise.all([
        api.getCurrentMembership(unit.unit_id),
        api.resolveUnit(unit.unit_id),
      ]);
      setMembership(mEnv.current_membership);
      setCandidates(outcome.matches);
      // Pre-select a lone exact match to speed up the common SAME decision.
      if (preselectLoneMatch && outcome.matches.length === 1) {
        setSelectedConceptId(outcome.matches[0].id);
      }
      setLoadedUnitContextId(unit.unit_id);
    } catch (e) {
      setNotice({ kind: "error", text: describe(e, "Could not load unit context.") });
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
      setNotice({ kind: "error", text: describe(e, "Could not load concept history.") });
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
    async (unit: ReviewableUnit, what: string) => {
      const id = unit.unit_id;
      setStatus(id, { refresh: { what, state: { kind: "refreshing" } } });
      try {
        const [env, outcome] = await Promise.all([api.getCurrentMembership(id), api.resolveUnit(id)]);
        if (!mounted.current) return;
        if (currentUnitRef.current === id) {
          setMembership(env.current_membership);
          setCandidates(outcome.matches);
          setSelectedConceptId(null);
          setLoadedUnitContextId(id);
        }
        setStatus(id, { refresh: { what, state: { kind: "refreshed" } } });
      } catch (e) {
        if (mounted.current) setStatus(id, { refresh: { what, state: { kind: "failed", message: errorText(e) } } });
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
        const label = describeDecision(rec.decision);
        if (resolvesUnit(rec.decision)) {
          removeUnit(unitId);
          setNotice({
            kind: "info",
            text: `Unit #${unitId}: the server shows ${label} is stored (${evidence.text}), so the unit left the queue.`,
          });
        } else {
          const unit = queueRef.current.find((u) => u.unit_id === unitId);
          if (unit) await rereadUnit(unit, `unit #${unitId}'s membership and exact matches`);
        }
      } catch (e) {
        if (!stale()) updateReconciliation(unitId, { check: "failed", text: errorText(e) });
      }
    },
    [removeUnit, rereadUnit, updateReconciliation],
  );

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
  async function act(action: ActionKind) {
    if (!current || writeInFlight.current || blockedFor(current.unit_id)) return;
    const unit = current;
    const unitId = unit.unit_id;
    const decision = buildDecision(action, unit);
    if (!decision) return;
    const label = describeDecision(decision);
    writeInFlight.current = true;
    setPendingWrite({ unitId, label });
    setNotice(null);
    setStatus(unitId, { outcome: null, refresh: null });
    try {
      let baseline: Baseline;
      try {
        baseline = await readBaseline(decision);
      } catch (e) {
        setStatus(unitId, {
          outcome: { kind: "rejected", text: `Nothing was sent: the existing events for ${label} could not be read first ${errorText(e)}.` },
        });
        return;
      }
      try {
        const text = await sendDecision(decision);
        if (!mounted.current) return;
        if (resolvesUnit(decision)) {
          removeUnit(unitId);
          setNotice({ kind: "success", text: `Unit #${unitId}: ${text}` });
        } else {
          setStatus(unitId, { outcome: { kind: "succeeded", text } });
          await rereadUnit(unit, `unit #${unitId}'s membership and exact matches`);
        }
      } catch (e) {
        if (!mounted.current) return;
        if (e instanceof NetworkError || !(e instanceof ApiError)) {
          setStatus(unitId, {
            outcome: {
              kind: "uncertain",
              text: `No response was received for ${label} on unit #${unitId}, so it may or may not have been recorded. It was not sent again.`,
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
            outcome: { kind: "rejected", text: `The server did not record ${label} ${errorText(e)}.` },
          });
          // A conflict means authority may have changed underneath; re-read it.
          if (e.isConflict) await rereadUnit(unit, `unit #${unitId}'s current membership`);
        }
      }
    } finally {
      writeInFlight.current = false;
      if (mounted.current) setPendingWrite(null);
    }
  }

  const context = focus ? (
    <section className="panel record-context" aria-label="Record context">
      <h2 ref={focusHeadingRef} tabIndex={-1}>
        Concept Review for record #{focus.entryId}
      </h2>
      <p className="hint">
        Opened from unit #{focus.unitId} of extraction v{focus.extractionVersion}. Only this record&apos;s
        units that the server lists as awaiting review are shown here.
      </p>
      {onBack ? (
        <button type="button" className="ghost" onClick={onBack}>
          ← Back to record #{focus.entryId}
        </button>
      ) : null}
    </section>
  ) : null;

  const missing =
    focus && focusMissing ? (
      <div className="banner info" role="alert">
        <strong>Unit #{focus.unitId} is not awaiting review.</strong> The server does not list it as
        reviewable now: it may already be resolved or marked INVALID, or its extraction is no longer
        current. It is not shown as a review candidate.{" "}
        {onInspect ? (
          <button type="button" className="ghost" onClick={() => onInspect(focus.unitId)}>
            Inspect unit #{focus.unitId}
          </button>
        ) : null}
      </div>
    ) : null;

  if (loadingQueue) {
    return (
      <div>
        {context}
        <p className="empty">Loading review queue…</p>
      </div>
    );
  }

  if (!current) {
    return (
      <div>
        {context}
        {missing}
        {notice ? <div className={`banner ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.text}</div> : null}
        <div className="empty">
          <p>{focus ? `No units of record #${focus.entryId} are awaiting review.` : "No units are awaiting review. 🎉"}</p>
          <button
            className="ghost"
            onClick={() => {
              void loadQueue();
              void loadCatalog();
            }}
          >
            Reload queue
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
        <p className="hint">Other units of record #{focus.entryId} are awaiting review below.</p>
      ) : null}
      {notice ? <div className={`banner ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.text}</div> : null}

      <div className="queue-nav">
        <button
          className="ghost"
          disabled={index === 0 || pendingWrite !== null}
          onClick={() => setIndex((i) => Math.max(0, i - 1))}
        >
          ← previous
        </button>
        <span className="position">
          unit {index + 1} of {queue.length}
        </span>
        <button
          className="ghost"
          disabled={index >= queue.length - 1 || pendingWrite !== null}
          onClick={() => setIndex((i) => Math.min(queue.length - 1, i + 1))}
        >
          skip →
        </button>
        <button
          className="ghost"
          onClick={() => {
            void loadQueue();
            void loadCatalog();
          }}
        >
          reload queue
        </button>
      </div>

      <div className="grid">
        <div>
          <UnitCard unit={current} />
          <MembershipPanel membership={membership} />
        </div>

        <div>
          <div className="panel">
            <h2>Exact identity matches</h2>
            <p className="hint">
              From the deterministic exact-signature resolver. Showing or selecting
              a match records no label; only an explicit human action below does.
            </p>
            {!unitContextReady ? (
              <p className="value">Loading exact resolver context…</p>
            ) : candidates.length === 0 ? (
              <p className="value">
                <em>No exact-signature concept exists for this identity.</em> Create a
                new concept below, or select nothing and mark INVALID.
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
            <h2>Search existing concepts</h2>
            <p className="hint">
              Retrieval-only catalog search, not an automatic SAME recommendation.
              Showing, searching, selecting, or skipping a result records nothing.
            </p>
            <label className="discovery-search" htmlFor="concept-discovery-search">
              Search target, intent, scope, or identity features
            </label>
            <div className="discovery-search-row">
              <input
                id="concept-discovery-search"
                type="search"
                aria-label="Search existing concepts"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
              <button type="button" className="ghost" onClick={() => setSearchQuery("")}>
                clear
              </button>
            </div>
            {catalogLoading ? (
              <p className="value">Loading concept catalog…</p>
            ) : !unitContextReady ? (
              <p className="value">Loading exact unit context before candidate discovery…</p>
            ) : discoveryCandidates.length === 0 ? (
              <p className="value">
                <em>No discoverable concepts match this search.</em>
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
            <h2>Reviewed identity (for NEW CONCEPT)</h2>
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

      <ResolutionActions
        membership={membership}
        selectedConceptId={selectedConceptId}
        busy={pendingWrite !== null || blockedFor(current.unit_id)}
        onAct={act}
      />
      {pendingWrite ? (
        <p className="hint" role="status">
          Sending {pendingWrite.label} for unit #{pendingWrite.unitId}… Other decisions and unit switches wait for the
          server&apos;s answer.
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
        />
      ) : null}

      <HistoryPanel
        title={
          historyConceptId !== null
            ? `Events for concept #${historyConceptId} (current membership shown separately above).`
            : "Select a concept to inspect its resolution events."
        }
        links={history}
        loading={historyLoading}
        unitId={current.unit_id}
      />
      {historyConceptId !== null ? (
        <button className="ghost" disabled={historyLoading} onClick={() => void loadHistory(historyConceptId)}>
          load history for concept #{historyConceptId}
        </button>
      ) : null}
    </div>
  );
}

// describe extracts a human-readable message from an error, preferring the backend's
// error text. Errors are never swallowed — this feeds the visible banner.
function describe(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    return `${fallback} (${e.status}) ${e.message}`;
  }
  if (e instanceof Error) {
    return `${fallback} ${e.message}`;
  }
  return fallback;
}

// ReconciliationPanel shows the check of an unknown decision outcome and the only
// ways forward: check again, or explicitly allow another decision knowing the
// risk. It never resends anything itself.
function ReconciliationPanel({
  unitId,
  rec,
  onCheck,
  onAllow,
}: {
  unitId: number;
  rec: Reconciliation;
  onCheck: () => void;
  onAllow: () => Promise<void>;
}) {
  const label = describeDecision(rec.decision);
  if (rec.check === "checking") {
    return (
      <p className="hint" role="status">
        Checking the server for {label} on unit #{unitId}…
      </p>
    );
  }
  if (rec.check === "found") {
    return (
      <p className="hint" role="status">
        Found on the server: {rec.text} {label} is stored.
      </p>
    );
  }
  return (
    <section className="panel reconciliation" aria-label="Unknown decision outcome">
      <h2>Outcome of {label} still unknown</h2>
      {rec.check === "failed" ? (
        <div className="banner error" role="alert">
          Could not check the server for {label}: {rec.text}
        </div>
      ) : (
        <p>
          Not visible on the server yet: {rec.text} The original request may still be in progress on the server, or
          may never have arrived. It was not sent again.
        </p>
      )}
      {rec.acknowledged ? (
        <p className="hint">
          You allowed another decision for unit #{unitId} although the outcome of {label} is still unknown.
        </p>
      ) : (
        <p className="hint">Decisions for unit #{unitId} wait until the check finds it or you allow another decision.</p>
      )}
      <div className="actions">
        <button type="button" className="ghost" onClick={onCheck}>
          Check again
        </button>
      </div>
      {!rec.acknowledged ? (
        <ExplicitAction
          label={`Allow another decision for unit #${unitId}`}
          confirmLabel="Allow another decision"
          pending={false}
          onConfirm={onAllow}
          explanation={
            <p>
              The earlier request may still be stored later. {duplicateRisk(rec.decision)} Check again first if you
              can. Nothing is sent until you choose a decision yourself.
            </p>
          }
        />
      ) : null}
    </section>
  );
}
