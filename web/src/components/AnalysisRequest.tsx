import { useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import type { Analysis } from "../types/learning";
import { msg, useI18n } from "../i18n";
import {
  ExplicitAction,
  OutcomeBanner,
  RefreshBanner,
  type Outcome,
  type RefreshState,
} from "./ExplicitAction";

// AnalysisRequest explicitly asks the server for one new analysis version. The
// backend decides which analyzer runs and stores the result; this component only
// sends the request once and reports what the server answered.
export function AnalysisRequest({
  entryId,
  refresh,
  onStart,
  onSettled,
}: {
  entryId: number;
  // The parent's re-read of the analysis versions after this request. Reported
  // separately from the request's outcome.
  refresh: RefreshState;
  onStart: () => void;
  // Called after every request. `reread` is true when the record may have changed
  // (confirmed, or no response) and must be re-read from the backend. `created` is
  // set only when the server confirmed the new version.
  onSettled: (created: Analysis | null, reread: boolean) => void;
}) {
  const { t, tn } = useI18n();
  const [pending, setPending] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const mounted = useRef(true);
  // Set in setup, cleared in cleanup: StrictMode's development effect replay
  // (setup, cleanup, setup) must leave it true, while a real unmount clears it.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function submit() {
    setPending(true);
    setOutcome(null);
    onStart();
    let next: Outcome;
    let created: Analysis | null = null;
    try {
      const stored: Analysis = await api.createAnalysis(entryId);
      created = stored;
      next = {
        kind: "succeeded",
        text: (i) =>
          i.tn("analysis.created", { version: stored.version, analyzer: <span className="mono">{stored.analyzer}</span> }),
      };
    } catch (error) {
      next = describeAnalysisFailure(error);
    }
    // Re-read whenever the record may have changed, including an unknown outcome,
    // so what is shown is backend state rather than an assumption.
    onSettled(created, next.kind !== "rejected");
    if (!mounted.current) return;
    setOutcome(next);
    setPending(false);
  }

  // After an unknown outcome a new request could add a duplicate version, so it
  // stays unavailable until the versions were re-read successfully.
  const disabledReason =
    outcome?.kind === "uncertain" && refresh.kind !== "refreshed"
      ? t("analysis.blocked")
      : null;

  return (
    <div className="workflow-action">
      <ExplicitAction
        label={t("analysis.label")}
        confirmLabel={t("analysis.confirm")}
        pending={pending}
        disabledReason={disabledReason}
        onConfirm={submit}
        explanation={
          <>
            <p>{t("analysis.explain.store")}</p>
            <p>{tn("analysis.explain.provider", { setting: <span className="mono">AI_PROVIDER=openai</span> })}</p>
          </>
        }
      />
      <OutcomeBanner outcome={outcome} />
      <RefreshBanner refresh={refresh} what={msg("analysis.what")} />
    </div>
  );
}

// describeAnalysisFailure states only what the backend contract supports: every
// error response is returned before the analysis is committed, so nothing was
// stored. Errors can occur after the configured analyzer ran (including a 404
// re-checked inside the store transaction), so none implies it was not called.
function describeAnalysisFailure(error: unknown): Outcome {
  if (error instanceof NetworkError) {
    return { kind: "uncertain", text: msg("analysis.noResponse") };
  }
  if (error instanceof ApiError) {
    return { kind: "rejected", text: msg("analysis.rejected", { status: error.status, message: error.message }) };
  }
  return { kind: "rejected", text: msg("analysis.failed", { error: String(error) }) };
}
