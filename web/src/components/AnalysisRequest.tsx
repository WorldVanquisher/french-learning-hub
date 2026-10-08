import { useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import type { Analysis } from "../types/learning";
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
  const [pending, setPending] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const mounted = useRef(true);
  useEffect(() => () => {
    mounted.current = false;
  }, []);

  async function submit() {
    setPending(true);
    setOutcome(null);
    onStart();
    let next: Outcome;
    let created: Analysis | null = null;
    try {
      created = await api.createAnalysis(entryId);
      next = {
        kind: "succeeded",
        text: (
          <>
            Created analysis v{created.version} with <span className="mono">{created.analyzer}</span>.
            It is unreviewed until a human gives feedback.
          </>
        ),
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
      ? "Unavailable until the analysis versions have been re-read after the unknown outcome. Use Retry if the re-read failed, then check for a new version."
      : null;

  return (
    <div className="workflow-action">
      <ExplicitAction
        label="Request analysis"
        confirmLabel="Create a new analysis version"
        pending={pending}
        disabledReason={disabledReason}
        onConfirm={submit}
        explanation={
          <>
            <p>
              The server runs its configured analyzer on this record&apos;s original input and
              context and stores the result as a new, immutable analysis version. The record
              state then follows the new latest version, which is unreviewed. Earlier versions
              and their feedback are not changed.
            </p>
            <p>
              The default local rule-based analyzer makes no external call. If the server is
              configured with an external analyzer (<span className="mono">AI_PROVIDER=openai</span>),
              this request calls it and may be billed. The request is sent once and never retried
              automatically.
            </p>
          </>
        }
      />
      <OutcomeBanner outcome={outcome} />
      <RefreshBanner refresh={refresh} what="analysis versions" />
    </div>
  );
}

// describeAnalysisFailure states only what the backend contract supports: every
// error response is returned before the analysis is committed, so nothing was
// stored. Errors can occur after the configured analyzer ran (including a 404
// re-checked inside the store transaction), so none implies it was not called.
function describeAnalysisFailure(error: unknown): Outcome {
  if (error instanceof NetworkError) {
    return {
      kind: "uncertain",
      text:
        "No response was received, so a new analysis may or may not have been created, and the configured analyzer may have been called.",
    };
  }
  if (error instanceof ApiError) {
    return {
      kind: "rejected",
      text: `No analysis was stored (${error.status}): ${error.message}. The configured analyzer may have been called.`,
    };
  }
  return { kind: "rejected", text: `The analysis request failed: ${String(error)}` };
}
