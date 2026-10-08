import { useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import type { CurrentExtraction, Extraction } from "../types/learning";
import { ExplicitAction, OutcomeBanner, type Outcome } from "./ExplicitAction";

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
export function ExtractionPanel({ entryId }: { entryId: number }) {
  const [state, setState] = useState<Load<ExtractionState>>({ status: "loading" });
  const [reloadCount, setReloadCount] = useState(0);
  const [pending, setPending] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const mounted = useRef(true);
  useEffect(() => () => {
    mounted.current = false;
  }, []);

  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    Promise.all([api.listExtractions(entryId), api.getCurrentExtraction(entryId)])
      .then(([extractions, current]) => {
        if (active) setState({ status: "ready", data: { extractions, current } });
      })
      .catch((error: unknown) => {
        if (active) setState({ status: "error", message: describeError(error) });
      });
    return () => {
      active = false;
    };
  }, [entryId, reloadCount]);

  async function submit() {
    setPending(true);
    setOutcome(null);
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
    // Always re-read: what is shown below is the backend's stored state.
    setReloadCount((n) => n + 1);
  }

  return (
    <section className="panel" aria-label="Knowledge extraction">
      <h2>Knowledge extraction</h2>
      <ExtractionState load={state} onRetry={() => setReloadCount((n) => n + 1)} />
      <div className="workflow-action">
        <ExplicitAction
          label="Request extraction"
          confirmLabel="Send to the extraction provider"
          pending={pending}
          onConfirm={submit}
          explanation={
            <>
              <p>
                The server sends this record&apos;s original input and its current effective
                interpretation to the configured extraction provider. That provider is an
                external service and may be billed. Extraction is disabled by default; the server
                then refuses without sending anything.
              </p>
              <p>
                The server decides eligibility: a record without an analysis, or whose latest
                analysis was rejected, is refused. A successful request stores a new, immutable
                extraction version (zero units is a valid result), which normally becomes current.
                The request is sent once and never retried automatically.
              </p>
            </>
          }
        />
        <OutcomeBanner outcome={outcome} />
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

function describeExtractionFailure(error: unknown): Outcome {
  if (error instanceof NetworkError) {
    return {
      kind: "uncertain",
      text:
        "No response was received, so a new extraction may or may not have been stored, and the provider may have been called. The stored extractions were re-read from the server; check them before requesting again.",
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
        text: `Extraction is not enabled on this server ${detail}. Nothing was sent to a provider or stored.`,
      };
    case 409:
      return {
        kind: "rejected",
        text: `The server refused extraction for this record ${detail}. Nothing was sent to a provider or stored.`,
      };
    case 422:
      return {
        kind: "rejected",
        text: `The provider's output failed validation ${detail}. The provider was called; nothing was stored.`,
      };
    case 502:
    case 504:
      return {
        kind: "rejected",
        text: `The extraction provider failed ${detail}. The provider may have been called; nothing was stored.`,
      };
    default:
      return { kind: "rejected", text: `No extraction was stored ${detail}.` };
  }
}
