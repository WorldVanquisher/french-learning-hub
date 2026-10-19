import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, NetworkError } from "../api/client";
import type { Concept } from "../types/concept";
import { CandidateConceptCard } from "../components/CandidateConceptCard";
import {
  ExplicitAction,
  OutcomeBanner,
  RefreshBanner,
  type Outcome,
  type RefreshState,
} from "../components/ExplicitAction";
import { discoverConcepts } from "../conceptSearch";
import {
  basisOf,
  checkCorrection,
  correctionEligibility,
  describeCorrection,
  sameBasis,
  sendCorrection,
  type Correction,
  type Inspection,
} from "./unitCorrection";

export type ConceptCatalog =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; concepts: Concept[] };

// A correction whose outcome is unknown (no response) and the read-only check of
// the backend for its effect. Until the check finds it, or the reviewer explicitly
// allows another correction, no other correction can be sent for this unit.
type Reconciliation = {
  correction: Correction;
  check: "checking" | "found" | "not-found" | "failed";
  text: string;
  acknowledged: boolean;
};

// Discovery results shown at once; the search narrows a larger catalog.
const shownTargets = 12;

function errorText(e: unknown): string {
  if (e instanceof ApiError) return `(${e.status}) ${e.message}`;
  return e instanceof Error ? e.message : String(e);
}

// UnitCorrections lets the reviewer correct a current-extraction unit that was
// already reviewed, with the existing backend operations only: REASSIGN SAME
// (PUT concept-membership), INVALID (POST invalid) and RESTORE (POST
// invalid/restore). Each is explained and confirmed first, re-checked against a
// fresh read of the backend state immediately before sending, sent once, and
// reported by what the server answered. The re-read after a write is reported
// separately. Nothing is ever resent automatically.
export function UnitCorrections({
  inspection,
  catalog,
  onReloadCatalog,
  refresh,
  onPendingChange,
}: {
  inspection: Inspection;
  catalog: ConceptCatalog;
  onReloadCatalog: () => void;
  // Re-reads the inspection and shows it. Resolves null when a newer read or
  // leaving the view superseded it; rejects when the read failed.
  refresh: () => Promise<Inspection | null>;
  onPendingChange: (pending: boolean) => void;
}) {
  const unitId = inspection.item.unit.id;
  const eligibility = correctionEligibility(inspection);
  const [query, setQuery] = useState("");
  const [targetId, setTargetId] = useState<number | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const inFlight = useRef(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [reread, setReread] = useState<RefreshState>({ kind: "idle" });
  const [rec, setRec] = useState<Reconciliation | null>(null);
  // Only the latest check is applied.
  const checkRequest = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const conceptsById = useMemo(
    () => new Map(catalog.status === "ready" ? catalog.concepts.map((c) => [c.id, c]) : []),
    [catalog],
  );
  const conceptName = (id: number) => {
    const c = conceptsById.get(id);
    return c ? `concept #${id} ("${c.target}")` : `concept #${id}`;
  };

  const fromConceptId = eligibility.kind === "reassign-or-invalid" ? eligibility.conceptId : null;
  const targets = useMemo(
    () =>
      catalog.status === "ready" && fromConceptId !== null
        ? discoverConcepts(catalog.concepts, query, new Set([fromConceptId]))
        : [],
    [catalog, query, fromConceptId],
  );
  // A target that is no longer offered (search changed, or it became the current
  // concept) is not a valid selection.
  const target = targetId !== null ? targets.find((c) => c.id === targetId) ?? null : null;

  // rereadAfter re-reads the unit after a write or a found check and reports that
  // re-read separately from the write's outcome.
  const rereadAfter = useCallback(async () => {
    setReread({ kind: "refreshing" });
    try {
      const fresh = await refresh();
      if (mounted.current) setReread(fresh ? { kind: "refreshed" } : { kind: "idle" });
    } catch (e) {
      if (mounted.current) setReread({ kind: "failed", message: errorText(e) });
    }
  }, [refresh]);

  const runCheck = useCallback(
    async (correction: Correction) => {
      const request = ++checkRequest.current;
      const stale = () => !mounted.current || checkRequest.current !== request;
      setRec((r) => (r ? { ...r, check: "checking" } : r));
      try {
        const evidence = await checkCorrection(correction);
        if (stale()) return;
        setRec((r) => (r ? { ...r, check: evidence.found ? "found" : "not-found", text: evidence.text } : r));
        if (evidence.found) await rereadAfter();
      } catch (e) {
        if (!stale()) setRec((r) => (r ? { ...r, check: "failed", text: errorText(e) } : r));
      }
    },
    [rereadAfter],
  );

  const unresolvedOutcome = rec !== null && rec.check !== "found" && !rec.acknowledged;
  const blockedReason = pending
    ? null
    : unresolvedOutcome
      ? "Wait until the earlier correction is found on the server, or explicitly allow another correction."
      : reread.kind === "failed"
        ? "Re-read the unit's state before another correction."
        : reread.kind === "refreshing"
          ? "Re-reading the unit's state…"
          : null;

  // perform sends one confirmed correction once. Immediately before sending it
  // re-reads the unit; if the backend state differs from the one the reviewer
  // confirmed against, nothing is sent and the new state is shown instead.
  async function perform(correction: Correction) {
    if (inFlight.current) return;
    const confirmedBasis = basisOf(inspection);
    const label = describeCorrection(correction);
    inFlight.current = true;
    setPending(label);
    onPendingChange(true);
    setOutcome(null);
    setReread({ kind: "idle" });
    if (rec?.check === "found" || rec?.acknowledged) setRec(null);
    try {
      let fresh: Inspection | null;
      try {
        fresh = await refresh();
      } catch (e) {
        if (mounted.current) {
          setOutcome({ kind: "rejected", text: `Nothing was sent: the unit's current state could not be re-read first ${errorText(e)}.` });
        }
        return;
      }
      if (!mounted.current) return;
      if (!fresh) {
        setOutcome({ kind: "rejected", text: "Nothing was sent: a newer read of the unit replaced the state you confirmed. Review it and confirm again." });
        return;
      }
      if (!sameBasis(confirmedBasis, basisOf(fresh))) {
        setTargetId(null);
        setOutcome({
          kind: "rejected",
          text: `Nothing was sent: unit #${unitId} changed on the server since it was shown. Its current state is shown now; review it before correcting.`,
        });
        return;
      }
      try {
        const text = await sendCorrection(correction);
        if (!mounted.current) return;
        setTargetId(null);
        setOutcome({ kind: "succeeded", text });
        await rereadAfter();
      } catch (e) {
        if (!mounted.current) return;
        if (e instanceof NetworkError || !(e instanceof ApiError)) {
          setOutcome({
            kind: "uncertain",
            text: `No response was received for ${label} on unit #${unitId}, so it may or may not have been recorded. It was not sent again.`,
          });
          setRec({ correction, check: "checking", text: "", acknowledged: false });
          void runCheck(correction);
        } else {
          setOutcome({ kind: "rejected", text: `The server did not record ${label} ${errorText(e)}.` });
          // Authority may have changed underneath, or the unit or concept is gone.
          if (e.isConflict || e.isNotFound) await rereadAfter();
        }
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        setPending(null);
        onPendingChange(false);
      }
    }
  }

  const status = (
    <>
      {pending ? (
        <p className="hint" role="status">
          Sending {pending} for unit #{unitId}… Other corrections and leaving this view wait for the server&apos;s
          answer.
        </p>
      ) : null}
      <OutcomeBanner outcome={outcome} />
      <RefreshBanner refresh={reread} what={`unit #${unitId}'s annotation and the record's current extraction`} />
      {reread.kind === "failed" ? (
        <button type="button" className="ghost" onClick={() => void rereadAfter()}>
          Re-read unit #{unitId}
        </button>
      ) : null}
      {rec ? (
        <CorrectionReconciliation
          unitId={unitId}
          rec={rec}
          onCheck={() => void runCheck(rec.correction)}
          onAllow={async () => setRec((r) => (r ? { ...r, acknowledged: true } : r))}
        />
      ) : null}
    </>
  );

  if (eligibility.kind === "none") {
    return (
      <section className="panel unit-corrections" aria-label={`Correct unit #${unitId}`}>
        <h2>Corrections</h2>
        <p className="hint">{eligibility.reason}</p>
        {status}
      </section>
    );
  }

  return (
    <section className="panel unit-corrections" aria-label={`Correct unit #${unitId}`}>
      <h2>Correct unit #{unitId}</h2>
      {eligibility.kind === "reassign-or-invalid" ? (
        <>
          <p>
            Current backend state: <strong>resolved</strong>. CURRENT SAME membership is{" "}
            {conceptName(eligibility.conceptId)}, in force by SAME event #{eligibility.linkId}.
          </p>
          <p className="hint">
            Each correction is sent once after you confirm it. History is appended, never rewritten; selecting or
            searching a concept records nothing.
          </p>

          <h3>Reassign SAME to another concept</h3>
          {catalog.status === "loading" ? (
            <p className="value">Loading the concept catalog…</p>
          ) : catalog.status === "error" ? (
            <div className="banner error" role="alert">
              Could not load the concept catalog ({catalog.message}), so no reassignment target can be chosen.{" "}
              <button type="button" className="ghost" onClick={onReloadCatalog}>
                Reload concepts
              </button>
            </div>
          ) : (
            <>
              <label className="discovery-search" htmlFor={`correction-target-search-${unitId}`}>
                Search target, intent, scope, or identity features
              </label>
              <div className="discovery-search-row">
                <input
                  id={`correction-target-search-${unitId}`}
                  type="search"
                  aria-label="Search reassignment targets"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </div>
              {targets.length === 0 ? (
                <p className="value">
                  <em>No other non-retired concept matches this search.</em>
                </p>
              ) : (
                <div className="candidate-list" aria-label="Reassignment targets" role="list">
                  {targets.slice(0, shownTargets).map((concept) => (
                    <div role="listitem" key={concept.id} aria-label={`Concept #${concept.id}`}>
                      <CandidateConceptCard
                        concept={concept}
                        selected={target?.id === concept.id}
                        onSelect={() => setTargetId(target?.id === concept.id ? null : concept.id)}
                      />
                    </div>
                  ))}
                </div>
              )}
              {targets.length > shownTargets ? (
                <p className="hint">
                  Showing {shownTargets} of {targets.length} matching concepts; refine the search to see others.
                </p>
              ) : null}
            </>
          )}
          <ExplicitAction
            label={target ? `Reassign SAME to concept #${target.id}` : "Reassign SAME"}
            confirmLabel={target ? `Confirm reassignment to concept #${target.id}` : "Confirm reassignment"}
            pending={pending !== null}
            disabledReason={blockedReason ?? (target ? null : "Select the concept the unit should belong to instead.")}
            onConfirm={() =>
              target
                ? perform({
                    kind: "reassign",
                    unitId,
                    fromConceptId: eligibility.conceptId,
                    fromLinkId: eligibility.linkId,
                    toConceptId: target.id,
                  })
                : Promise.resolve()
            }
            explanation={
              target ? (
                <>
                  <p>
                    Moves unit #{unitId}&apos;s CURRENT SAME membership from {conceptName(eligibility.conceptId)} to{" "}
                    {conceptName(target.id)} (PUT concept-membership).
                  </p>
                  <p>
                    A new human SAME event superseding event #{eligibility.linkId} is appended; the earlier event stays
                    in history. If {conceptName(eligibility.conceptId)} uses this unit as its preferred unit, that
                    preference is cleared. Concept support follows current membership, so it may change for both
                    concepts. DISTINCT and relation records are unchanged.
                  </p>
                </>
              ) : null
            }
          />

          <h3>Mark INVALID</h3>
          <ExplicitAction
            label={`Mark unit #${unitId} INVALID`}
            confirmLabel={`Confirm INVALID for unit #${unitId}`}
            pending={pending !== null}
            disabledReason={blockedReason}
            onConfirm={() =>
              perform({ kind: "invalid", unitId, fromConceptId: eligibility.conceptId, fromLinkId: eligibility.linkId })
            }
            explanation={
              <>
                <p>
                  Records that unit #{unitId} itself is an invalid candidate for concept resolution (POST invalid).
                  In the same transaction the server clears its CURRENT SAME membership to{" "}
                  {conceptName(eligibility.conceptId)}, appending a rejected-SAME event that refers to event #
                  {eligibility.linkId}; history is kept. A preferred-unit reference to this unit is cleared.
                </p>
                <p>RESTORE can later withdraw the INVALID judgment, but it does not bring this membership back.</p>
              </>
            }
          />
        </>
      ) : (
        <>
          <p>
            Current backend state: <strong>invalid</strong>, by judgment #{eligibility.judgmentId}. It has no CURRENT
            SAME membership.
          </p>
          <ExplicitAction
            label={`Restore unit #${unitId}`}
            confirmLabel={`Confirm RESTORE for unit #${unitId}`}
            pending={pending !== null}
            disabledReason={blockedReason}
            onConfirm={() => perform({ kind: "restore", unitId, judgmentId: eligibility.judgmentId })}
            explanation={
              <>
                <p>
                  Appends a &quot;restored&quot; judgment that withdraws INVALID judgment #{eligibility.judgmentId}{" "}
                  (POST invalid/restore). The INVALID judgment stays in history.
                </p>
                <p>
                  No SAME membership is recreated: the unit becomes unresolved and awaits a new decision in Concept
                  Review.
                </p>
              </>
            }
          />
        </>
      )}
      {status}
    </section>
  );
}

// CorrectionReconciliation shows the check of an unknown correction outcome and the
// only ways forward: check again, or explicitly allow another correction. It never
// resends anything itself.
function CorrectionReconciliation({
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
  const label = describeCorrection(rec.correction);
  if (rec.check === "checking") {
    // A check that hangs can be replaced; only the newest check's answer is used.
    return (
      <p className="hint" role="status">
        Checking the server for {label} on unit #{unitId}…{" "}
        <button type="button" className="ghost" onClick={onCheck}>
          Check again
        </button>
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
    <section className="panel reconciliation" aria-label="Unknown correction outcome">
      <h2>Outcome of {label} still unknown</h2>
      {rec.check === "failed" ? (
        <div className="banner error" role="alert">
          Could not check the server for {label}: {rec.text}
        </div>
      ) : (
        <p>
          Not visible on the server yet: {rec.text} The original request may still be in progress on the server, or may
          never have arrived. It was not sent again.
        </p>
      )}
      {rec.acknowledged ? (
        <p className="hint">
          You allowed another correction for unit #{unitId} although the outcome of {label} is still unknown.
        </p>
      ) : (
        <p className="hint">Corrections for unit #{unitId} wait until the check finds it or you allow another one.</p>
      )}
      <div className="actions">
        <button type="button" className="ghost" onClick={onCheck}>
          Check again
        </button>
      </div>
      {!rec.acknowledged ? (
        <ExplicitAction
          label={`Allow another correction for unit #${unitId}`}
          confirmLabel="Allow another correction"
          pending={false}
          onConfirm={onAllow}
          explanation={
            <p>
              The earlier request may still be stored later. The server applies each of these corrections at most once
              to the same state, but a later different correction could be overtaken by it. Check again first if you
              can. Nothing is sent until you confirm a correction yourself.
            </p>
          }
        />
      ) : null}
    </section>
  );
}
