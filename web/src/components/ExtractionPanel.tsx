import { useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import type { CurrentExtraction, Extraction } from "../types/learning";
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

function describeError(error: unknown): string {
  if (error instanceof ApiError) return `(${error.status}) ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

// ExtractionPanel shows the backend's stored extraction versions for one record,
// the current one's units, and an explicit request for a new extraction. The
// backend decides eligibility, runs the provider, and chooses the current version.
export function ExtractionPanel({
  entryId,
  latestVersion = null,
}: {
  entryId: number;
  // The record's latest analysis version, only to explain the extraction source.
  latestVersion?: number | null;
}) {
  const [state, setState] = useState<Load<ExtractionState>>({ status: "loading" });
  const [reloadCount, setReloadCount] = useState(0);
  const [pending, setPending] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  // The re-read after a request, reported separately from the request's outcome.
  const [refresh, setRefresh] = useState<RefreshState>({ kind: "idle" });
  const mounted = useRef(true);
  useEffect(() => () => {
    mounted.current = false;
  }, []);

  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    // Any reload (after a request, or the reader's own "Reload extractions") also
    // settles an outstanding post-request refresh.
    setRefresh((r) => (r.kind === "idle" ? r : { kind: "refreshing" }));
    Promise.all([api.listExtractions(entryId), api.getCurrentExtraction(entryId)])
      .then(([extractions, current]) => {
        if (!active) return;
        setState({ status: "ready", data: { extractions, current } });
        setRefresh((r) => (r.kind === "idle" ? r : { kind: "refreshed" }));
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

  async function submit() {
    setPending(true);
    setOutcome(null);
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
    // Always re-read the stored extractions; RefreshBanner reports whether that
    // GET succeeded, so the outcome above never claims it.
    setRefresh({ kind: "refreshing" });
    setReloadCount((n) => n + 1);
  }

  // After an unknown outcome a new request could duplicate a stored (and possibly
  // billed) extraction, so it stays unavailable until stored state was re-read.
  const disabledReason =
    outcome?.kind === "uncertain" && refresh.kind !== "refreshed"
      ? "Unavailable until the stored extractions have been re-read after the unknown outcome. Reload them and check for a new version first."
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
      <ExtractionState load={state} onRetry={() => setReloadCount((n) => n + 1)} />
      <div className="workflow-action">
        <ExplicitAction
          label="Request extraction"
          confirmLabel="Send to the extraction provider"
          pending={pending}
          disabledReason={disabledReason}
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
                immutable extraction version (zero units is a valid result), which normally becomes
                current. The request is sent once and never retried automatically.
              </p>
            </>
          }
        />
        <OutcomeBanner outcome={outcome} />
        <RefreshBanner refresh={refresh} what="stored extractions" />
      </div>
    </section>
  );
}

function ExtractionState({ load, onRetry }: { load: Load<ExtractionState>; onRetry: () => void }) {
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
  if (extractions.length === 0) {
    return (
      <p className="value">
        <strong>No extraction stored.</strong> No extraction has been run for this record.
      </p>
    );
  }
  const selected = extractions.find((e) => e.id === current.current_extraction_id);
  const latest = extractions.reduce((a, b) => (b.version > a.version ? b : a));
  const others = extractions.length - (selected ? 1 : 0);
  return (
    <>
      {selected ? (
        <CurrentExtractionView extraction={selected} />
      ) : (
        <p className="value">
          <strong>No current extraction.</strong> Stored versions exist, but the server reports
          none as current.
        </p>
      )}
      {selected && latest.id !== selected.id ? (
        <p className="hint">
          A newer version (v{latest.version}) is stored, but the server keeps v{selected.version} as
          current.
        </p>
      ) : null}
      {others > 0 ? (
        <p className="hint">
          {others} other stored version{others === 1 ? "" : "s"}.
        </p>
      ) : null}
    </>
  );
}

function CurrentExtractionView({ extraction }: { extraction: Extraction }) {
  return (
    <div className="annotation-section" aria-label="Current extraction">
      <h3>
        Current extraction v{extraction.version}
      </h3>
      <div className="annotation-provenance">
        <span className="mono">{extraction.extractor}</span>
        <span>from analysis #{extraction.source_analysis_id}</span>
        <span>
          {extraction.source_feedback_id !== null ? `feedback #${extraction.source_feedback_id}` : "no feedback"}
        </span>
        <time dateTime={extraction.created_at}>{extraction.created_at}</time>
      </div>
      {extraction.units.length === 0 ? (
        <p className="value">
          <strong>Zero units.</strong> This successful extraction produced no knowledge units.
        </p>
      ) : (
        <ul className="annotation-list" aria-label="Extracted units">
          {extraction.units.map((unit) => (
            <li key={unit.id}>
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
            </li>
          ))}
        </ul>
      )}
    </div>
  );
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
