import { useCallback, useEffect, useState } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
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

type Notice = { kind: "success" | "error" | "info"; text: string } | null;

// ReviewQueue is the single experimental annotation page. It walks the reviewer
// through the reviewable-units queue one at a time, shows current membership as the
// sole authority (never inferred from history), and records each of the six human
// decisions against the backend. After a successful decision it advances the queue
// without a page refresh.
export function ReviewQueue() {
  const [queue, setQueue] = useState<ReviewableUnit[]>([]);
  const [index, setIndex] = useState(0);
  const [loadingQueue, setLoadingQueue] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);

  // Per-unit review state.
  const [membership, setMembership] = useState<CurrentMembership | null>(null);
  const [candidates, setCandidates] = useState<Concept[]>([]);
  const [selectedConceptId, setSelectedConceptId] = useState<number | null>(null);
  const [identity, setIdentity] = useState<ConceptIdentity | null>(null);
  const [history, setHistory] = useState<UnitConceptLink[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const current: ReviewableUnit | undefined = queue[index];

  // loadQueue fetches the reviewable units. Any error is surfaced, never swallowed.
  const loadQueue = useCallback(async () => {
    setLoadingQueue(true);
    try {
      const units = await api.listReviewableUnits();
      setQueue(units);
      setIndex(0);
    } catch (e) {
      setNotice({ kind: "error", text: describe(e, "Could not load the review queue.") });
    } finally {
      setLoadingQueue(false);
    }
  }, []);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  // loadUnitContext loads everything needed to review one unit: current membership
  // (the authority), any exact-signature candidate concepts, and a fresh editable
  // identity seeded from the backend candidate.
  const loadUnitContext = useCallback(async (unit: ReviewableUnit) => {
    setMembership(null);
    setCandidates([]);
    setSelectedConceptId(null);
    setHistory([]);
    setIdentity({ ...unit.candidate_identity, identity_features: { ...unit.candidate_identity.identity_features } });
    try {
      const [mEnv, outcome] = await Promise.all([
        api.getCurrentMembership(unit.unit_id),
        api.resolveUnit(unit.unit_id),
      ]);
      setMembership(mEnv.current_membership);
      setCandidates(outcome.matches);
      // Pre-select a lone exact match to speed up the common SAME decision.
      if (outcome.matches.length === 1) {
        setSelectedConceptId(outcome.matches[0].id);
      }
    } catch (e) {
      setNotice({ kind: "error", text: describe(e, "Could not load unit context.") });
    }
  }, []);

  useEffect(() => {
    if (current) {
      void loadUnitContext(current);
    }
  }, [current, loadUnitContext]);

  // refreshMembership re-reads the authority. Used after a 409 conflict, because
  // another operation may have changed the current membership underneath us.
  const refreshMembership = useCallback(async (unitId: number) => {
    try {
      const env = await api.getCurrentMembership(unitId);
      setMembership(env.current_membership);
    } catch {
      // Leave the prior value; the error banner from the failed action still shows.
    }
  }, []);

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

  // advance moves to the next unit. A resolved/invalidated unit is dropped from the
  // in-memory queue so the reviewer is not shown it again this session.
  const advance = useCallback(() => {
    setQueue((q) => {
      const next = q.filter((_, i) => i !== index);
      setIndex((i) => Math.min(i, Math.max(0, next.length - 1)));
      return next;
    });
  }, [index]);

  // act performs one human decision, then confirms and advances on success. Errors
  // stay visible; on conflict it refreshes the authority before letting the reviewer
  // retry.
  async function act(action: ActionKind) {
    if (!current || !identity) return;
    const unitId = current.unit_id;
    setBusy(true);
    setNotice(null);
    try {
      let link: UnitConceptLink | null = null;
      switch (action) {
        case "same": {
          if (selectedConceptId === null) return;
          // Route correctly: an existing membership means an explicit ReassignSame;
          // an unresolved unit means a plain SAME. Never create+seed to reassign.
          link = membership
            ? await api.reassignSame(unitId, selectedConceptId)
            : await api.resolveSame(unitId, selectedConceptId);
          setNotice({ kind: "success", text: `Recorded SAME → concept #${selectedConceptId}.` });
          break;
        }
        case "new": {
          // Seed SAME only when the unit is unresolved; otherwise create the concept
          // without touching the existing membership (reassign is a separate action).
          const seedAsSame = membership === null;
          const res = await api.createConcept(identity, unitId, seedAsSame);
          link = res.link;
          setNotice({
            kind: "success",
            text: seedAsSame
              ? `Created concept #${res.concept.id} and seeded SAME.`
              : `Created concept #${res.concept.id} (membership unchanged; use REASSIGN to move it).`,
          });
          break;
        }
        case "broader":
        case "narrower":
        case "related": {
          if (selectedConceptId === null) return;
          link = await api.recordRelation(unitId, selectedConceptId, action);
          setNotice({ kind: "success", text: `Recorded ${action.toUpperCase()} → concept #${selectedConceptId}.` });
          break;
        }
        case "invalid": {
          const res = await api.rejectInvalid(unitId);
          link = res.link;
          setNotice({ kind: "success", text: "Marked INVALID: current membership cleared." });
          break;
        }
      }

      // A membership-changing action (SAME/NEW+seed/INVALID) resolves the unit, so
      // it leaves the review queue. A non-membership relation does NOT resolve it —
      // keep the unit and just refresh its context so the reviewer can continue.
      const resolved = action === "same" || action === "invalid" || (action === "new" && membership === null);
      if (resolved) {
        advance();
      } else {
        await loadUnitContext(current);
      }
      void link;
    } catch (e) {
      setNotice({ kind: "error", text: describe(e, "The decision could not be recorded.") });
      if (e instanceof ApiError && e.isConflict) {
        // Authority may have changed; refresh it so the next action is well-formed.
        await refreshMembership(unitId);
        setNotice({
          kind: "info",
          text:
            "Conflict: this unit's current membership was refreshed because it may have changed. Review the current membership and try again.",
        });
      }
    } finally {
      setBusy(false);
    }
  }

  if (loadingQueue) {
    return <p className="empty">Loading review queue…</p>;
  }

  if (!current) {
    return (
      <div>
        {notice ? <div className={`banner ${notice.kind}`}>{notice.text}</div> : null}
        <div className="empty">
          <p>No units are awaiting review. 🎉</p>
          <button className="ghost" onClick={() => void loadQueue()}>
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
      {notice ? <div className={`banner ${notice.kind}`}>{notice.text}</div> : null}

      <div className="queue-nav">
        <button className="ghost" disabled={index === 0} onClick={() => setIndex((i) => Math.max(0, i - 1))}>
          ← previous
        </button>
        <span className="position">
          unit {index + 1} of {queue.length}
        </span>
        <button
          className="ghost"
          disabled={index >= queue.length - 1}
          onClick={() => setIndex((i) => Math.min(queue.length - 1, i + 1))}
        >
          skip →
        </button>
        <button className="ghost" onClick={() => void loadQueue()}>
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
            <h2>Existing concept candidates</h2>
            {candidates.length === 0 ? (
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
            <h2>Reviewed identity (for NEW CONCEPT)</h2>
            {identity ? <IdentityEditor value={identity} onChange={setIdentity} /> : null}
          </div>
        </div>
      </div>

      <ResolutionActions
        membership={membership}
        selectedConceptId={selectedConceptId}
        busy={busy}
        onAct={act}
      />

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
