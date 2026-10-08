import { useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import type { Analysis } from "../types/learning";
import { ExplicitAction, OutcomeBanner, type Outcome } from "./ExplicitAction";

// AnalysisRequest explicitly asks the server for one new analysis version. The
// backend decides which analyzer runs and stores the result; this component only
// sends the request once and reports what the server answered.
export function AnalysisRequest({
  entryId,
  onSettled,
}: {
  entryId: number;
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

  return (
    <div className="workflow-action">
      <ExplicitAction
        label="Request analysis"
        confirmLabel="Create a new analysis version"
        pending={pending}
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
    </div>
  );
}

function describeAnalysisFailure(error: unknown): Outcome {
  if (error instanceof NetworkError) {
    return {
      kind: "uncertain",
      text:
        "No response was received, so a new analysis may or may not have been created. The analysis versions were re-read from the server; check them before requesting again.",
    };
  }
  if (error instanceof ApiError) {
    const provider = error.status === 502 || error.status === 504;
    return {
      kind: "rejected",
      text: (
        <>
          No analysis was stored ({error.status}): {error.message}.
          {provider ? " The analysis provider may have been contacted." : null}
        </>
      ),
    };
  }
  return { kind: "rejected", text: `The analysis request failed: ${String(error)}` };
}
