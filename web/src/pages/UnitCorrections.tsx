import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, NetworkError } from "../api/client";
import type { Concept } from "../types/concept";
import { CandidateConceptCard } from "../components/CandidateConceptCard";
import { ConceptContent } from "../components/ConceptContent";
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
import { msg, useI18n, type MessageRef, type Msg } from "../i18n";

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
  // A message, or raw error details from a failed check.
  text: Msg;
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
  const { t, tn, render, status: statusLabel } = useI18n();
  const unitId = inspection.item.unit.id;
  const eligibility = correctionEligibility(inspection);
  const [query, setQuery] = useState("");
  const [targetId, setTargetId] = useState<number | null>(null);
  const [pending, setPending] = useState<MessageRef | null>(null);
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
  // The Concept target is stored data, quoted as it is.
  const conceptName = (id: number) => {
    const c = conceptsById.get(id);
    return c ? t("correction.conceptNamed", { id, target: c.target }) : t("correction.concept", { id });
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
      ? t("correction.blocked.unknown")
      : reread.kind === "failed"
        ? t("correction.blocked.reread")
        : reread.kind === "refreshing"
          ? t("correction.blocked.rereading")
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
          setOutcome({ kind: "rejected", text: msg("correction.rereadFirstFailed", { error: errorText(e) }) });
        }
        return;
      }
      if (!mounted.current) return;
      if (!fresh) {
        setOutcome({ kind: "rejected", text: msg("correction.superseded") });
        return;
      }
      if (!sameBasis(confirmedBasis, basisOf(fresh))) {
        setTargetId(null);
        setOutcome({ kind: "rejected", text: msg("correction.changed", { id: unitId }) });
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
          setOutcome({ kind: "uncertain", text: msg("review.unknown", { label, id: unitId }) });
          setRec({ correction, check: "checking", text: "", acknowledged: false });
          void runCheck(correction);
        } else {
          setOutcome({ kind: "rejected", text: msg("review.rejected", { label, error: errorText(e) }) });
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
          {t("correction.sending", { label: pending, id: unitId })}
        </p>
      ) : null}
      <OutcomeBanner outcome={outcome} />
      <RefreshBanner refresh={reread} what={msg("correction.what", { id: unitId })} />
      {reread.kind === "failed" ? (
        <button type="button" className="ghost" onClick={() => void rereadAfter()}>
          {t("correction.reread", { id: unitId })}
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
      <section className="panel unit-corrections" aria-label={t("correction.region", { id: unitId })}>
        <h2>{t("correction.title")}</h2>
        <p className="hint">{render(eligibility.reason)}</p>
        {status}
      </section>
    );
  }

  return (
    <section className="panel unit-corrections" aria-label={t("correction.region", { id: unitId })}>
      <h2>{t("correction.region", { id: unitId })}</h2>
      {eligibility.kind === "reassign-or-invalid" ? (
        <>
          <p>
            {tn("correction.state.resolved", {
              state: <strong>{statusLabel("resolved")}</strong>,
              concept: conceptName(eligibility.conceptId),
              link: eligibility.linkId,
            })}
          </p>
          <p className="hint">{t("correction.hint")}</p>

          <h3>{t("correction.reassign.title")}</h3>
          {catalog.status === "loading" ? (
            <p className="value">{t("correction.catalogLoading")}</p>
          ) : catalog.status === "error" ? (
            <div className="banner error" role="alert">
              {t("correction.catalogFailed", { message: catalog.message })}{" "}
              <button type="button" className="ghost" onClick={onReloadCatalog}>
                {t("correction.reloadConcepts")}
              </button>
            </div>
          ) : (
            <>
              <label className="discovery-search" htmlFor={`correction-target-search-${unitId}`}>
                {t("review.search.label")}
              </label>
              <div className="discovery-search-row">
                <input
                  id={`correction-target-search-${unitId}`}
                  type="search"
                  aria-label={t("correction.searchTargets")}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </div>
              {targets.length === 0 ? (
                <p className="value">
                  <em>{t("correction.noTargets")}</em>
                </p>
              ) : (
                <div className="candidate-list" aria-label={t("correction.targets")} role="list">
                  {targets.slice(0, shownTargets).map((concept) => (
                    <div role="listitem" key={concept.id} aria-label={t("correction.conceptItem", { id: concept.id })}>
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
                <p className="hint">{t("correction.showingTargets", { shown: shownTargets, total: targets.length })}</p>
              ) : null}
            </>
          )}
          {target ? (
            // Read-only: what the reassignment target currently contains (FLH-093).
            <section className="panel comparison" aria-label={t("correction.targetContent", { id: target.id })}>
              <h3>{t("correction.targetContent", { id: target.id })}</h3>
              <ConceptContent key={target.id} conceptId={target.id} />
            </section>
          ) : null}
          <ExplicitAction
            label={target ? t("correction.reassign.to", { id: target.id }) : t("correction.reassign")}
            confirmLabel={target ? t("correction.reassign.confirmTo", { id: target.id }) : t("correction.reassign.confirm")}
            pending={pending !== null}
            disabledReason={blockedReason ?? (target ? null : t("correction.reassign.select"))}
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
                    {t("correction.reassign.explain", {
                      id: unitId,
                      from: conceptName(eligibility.conceptId),
                      to: conceptName(target.id),
                    })}
                  </p>
                  <p>
                    {t("correction.reassign.history", { link: eligibility.linkId, from: conceptName(eligibility.conceptId) })}
                  </p>
                </>
              ) : null
            }
          />

          <h3>{t("correction.invalid.title")}</h3>
          <ExplicitAction
            label={t("correction.invalid", { id: unitId })}
            confirmLabel={t("correction.invalid.confirm", { id: unitId })}
            pending={pending !== null}
            disabledReason={blockedReason}
            onConfirm={() =>
              perform({ kind: "invalid", unitId, fromConceptId: eligibility.conceptId, fromLinkId: eligibility.linkId })
            }
            explanation={
              <>
                <p>
                  {t("correction.invalid.explain", { id: unitId, concept: conceptName(eligibility.conceptId), link: eligibility.linkId })}
                </p>
                <p>{t("correction.invalid.restoreNote")}</p>
              </>
            }
          />
        </>
      ) : (
        <>
          <p>
            {tn("correction.state.invalid", {
              state: <strong>{statusLabel("invalid")}</strong>,
              judgment: eligibility.judgmentId,
            })}
          </p>
          <ExplicitAction
            label={t("correction.restore", { id: unitId })}
            confirmLabel={t("correction.restore.confirm", { id: unitId })}
            pending={pending !== null}
            disabledReason={blockedReason}
            onConfirm={() => perform({ kind: "restore", unitId, judgmentId: eligibility.judgmentId })}
            explanation={
              <>
                <p>{t("correction.restore.explain", { judgment: eligibility.judgmentId })}</p>
                <p>{t("correction.restore.noMembership")}</p>
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
  const { t, render } = useI18n();
  const label = String(render(describeCorrection(rec.correction)));
  const text = String(render(rec.text) ?? "");
  if (rec.check === "checking") {
    // A check that hangs can be replaced; only the newest check's answer is used.
    return (
      <p className="hint" role="status">
        {t("reconcile.checking", { label, id: unitId })}{" "}
        <button type="button" className="ghost" onClick={onCheck}>
          {t("reconcile.checkAgain")}
        </button>
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
  return (
    <section className="panel reconciliation" aria-label={t("correction.reconcile.region")}>
      <h2>{t("reconcile.unknown", { label })}</h2>
      {rec.check === "failed" ? (
        <div className="banner error" role="alert">
          {t("reconcile.checkFailed", { label, text })}
        </div>
      ) : (
        <p>{t("reconcile.notVisible", { text })}</p>
      )}
      {rec.acknowledged ? (
        <p className="hint">{t("correction.reconcile.allowed", { id: unitId, label })}</p>
      ) : (
        <p className="hint">{t("correction.reconcile.waiting", { id: unitId })}</p>
      )}
      <div className="actions">
        <button type="button" className="ghost" onClick={onCheck}>
          {t("reconcile.checkAgain")}
        </button>
      </div>
      {!rec.acknowledged ? (
        <ExplicitAction
          label={t("correction.reconcile.allow", { id: unitId })}
          confirmLabel={t("correction.reconcile.allow.confirm")}
          pending={false}
          onConfirm={onAllow}
          explanation={<p>{t("correction.reconcile.allow.explain")}</p>}
        />
      ) : null}
    </section>
  );
}
