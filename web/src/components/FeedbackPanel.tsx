import { useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import {
  FR_L2_TAXONOMY_V1,
  type Analysis,
  type Feedback,
  type FeedbackStatus,
  type NewFeedback,
} from "../types/learning";
import { OutcomeBanner, RefreshBanner, type Outcome, type RefreshState } from "./ExplicitAction";

type Load<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

// A reviewer's unsent feedback for one analysis version.
type Draft = { status: FeedbackStatus | null; category: string; explanation: string; note: string };
const EMPTY_DRAFT: Draft = { status: null, category: "", explanation: "", note: "" };

// Everything the panel tracks for one analysis version. Keeping it per version
// means a draft, a pending request, or a late response can only ever affect the
// version it belongs to, and switching versions never discards any of it.
type Slot = {
  draft: Draft;
  pending: boolean;
  outcome: Outcome | null;
  history: Load<Feedback[]>;
  historyRefresh: RefreshState;
  historyReload: number;
};
const EMPTY_SLOT: Slot = {
  draft: EMPTY_DRAFT,
  pending: false,
  outcome: null,
  history: { status: "loading" },
  historyRefresh: { kind: "idle" },
  historyReload: 0,
};

const DECISIONS: Array<{ status: FeedbackStatus; label: string; help: string }> = [
  { status: "accepted", label: "Accept", help: "The interpretation is correct as stored." },
  { status: "corrected", label: "Correct", help: "Supply a better category, explanation, or both." },
  { status: "rejected", label: "Reject", help: "The interpretation is wrong; it then has no effective interpretation." },
];

function describeError(error: unknown): string {
  if (error instanceof ApiError) return `(${error.status}) ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

// toRequest sends only the fields the feedback contract accepts for the chosen
// decision. The server trims, normalizes, and validates them.
function toRequest(draft: Draft): NewFeedback {
  const body: NewFeedback = { status: draft.status as FeedbackStatus };
  if (draft.status === "corrected") {
    if (draft.category !== "") body.corrected_category = draft.category;
    if (draft.explanation.trim() !== "") body.corrected_explanation = draft.explanation;
  }
  if (draft.note.trim() !== "") body.user_note = draft.note;
  return body;
}

// FeedbackPanel records explicit human feedback for the selected analysis version
// and shows that version's immutable feedback history. It stays mounted for the
// whole record, so the record's own read refreshes never discard drafts.
export function FeedbackPanel({
  analysis,
  latest,
  effectiveFeedbackId,
  effectiveResolution,
  effectiveRefresh,
  onRecorded,
}: {
  analysis: Analysis | undefined;
  latest: Analysis | undefined;
  // The backend's effective interpretation of `analysis`, when loaded for it.
  effectiveFeedbackId: number | null | undefined;
  effectiveResolution: string | undefined;
  // The re-read of that effective interpretation after feedback.
  effectiveRefresh: RefreshState;
  // Called when feedback was stored or its outcome is unknown, so the record
  // detail and the list row are re-read from the backend.
  onRecorded: (analysisId: number) => void;
}) {
  const [slots, setSlots] = useState<Record<number, Slot>>({});
  const inFlight = useRef(new Set<number>());
  const mounted = useRef(true);
  useEffect(() => () => {
    mounted.current = false;
  }, []);

  const update = (id: number, change: (slot: Slot) => Slot) =>
    setSlots((all) => ({ ...all, [id]: change(all[id] ?? EMPTY_SLOT) }));

  const id = analysis?.id;
  const slot = id !== undefined ? slots[id] ?? EMPTY_SLOT : EMPTY_SLOT;

  // Load the selected version's feedback history. A response is stored under the
  // version it was requested for, and a response for a version the reader has
  // left is dropped (it is read again on return).
  useEffect(() => {
    if (id === undefined) return;
    let active = true;
    update(id, (s) => ({
      ...s,
      history: { status: "loading" },
      historyRefresh: s.historyRefresh.kind === "idle" ? s.historyRefresh : { kind: "refreshing" },
    }));
    api.listFeedback(id)
      .then((data) => {
        if (!active) return;
        update(id, (s) => ({
          ...s,
          history: { status: "ready", data },
          historyRefresh: s.historyRefresh.kind === "idle" ? s.historyRefresh : { kind: "refreshed" },
        }));
      })
      .catch((error: unknown) => {
        if (!active) return;
        const message = describeError(error);
        update(id, (s) => ({
          ...s,
          history: { status: "error", message },
          historyRefresh: s.historyRefresh.kind === "idle" ? s.historyRefresh : { kind: "failed", message },
        }));
      });
    return () => {
      active = false;
    };
  }, [id, slot.historyReload]);

  if (!analysis || id === undefined) return null;
  const target = analysis;
  const isLatest = latest?.id === target.id;

  async function submit() {
    const targetId = target.id;
    if (inFlight.current.has(targetId)) return;
    const draft = (slots[targetId] ?? EMPTY_SLOT).draft;
    if (draft.status === null) return;
    inFlight.current.add(targetId);
    update(targetId, (s) => ({ ...s, pending: true, outcome: null, historyRefresh: { kind: "idle" } }));

    let outcome: Outcome;
    let stored = false;
    let reread = false;
    try {
      const created = await api.createFeedback(targetId, toRequest(draft));
      stored = true;
      reread = true;
      outcome = {
        kind: "succeeded",
        text: (
          <>
            Recorded feedback #{created.id} ({created.status}) for analysis v{target.version}.
            {isLatest
              ? " This is the latest analysis, so the record's state follows it."
              : ` This is a historical version: the record's state and any new extraction still use the latest analysis v${latest?.version ?? "?"}.`}
          </>
        ),
      };
    } catch (error) {
      if (error instanceof NetworkError) {
        reread = true;
        outcome = {
          kind: "uncertain",
          text: `No response was received, so feedback for analysis v${target.version} may or may not have been recorded.`,
        };
      } else {
        outcome = {
          kind: "rejected",
          text: `No feedback was stored for analysis v${target.version} ${describeError(error)}. Your draft is kept.`,
        };
      }
    } finally {
      inFlight.current.delete(targetId);
    }

    if (reread) onRecorded(targetId);
    if (!mounted.current) return;
    update(targetId, (s) => ({
      ...s,
      pending: false,
      outcome,
      // A stored decision clears its draft; a rejected or unknown one keeps it.
      draft: stored ? EMPTY_DRAFT : s.draft,
      historyRefresh: reread ? { kind: "refreshing" } : s.historyRefresh,
      historyReload: reread ? s.historyReload + 1 : s.historyReload,
    }));
  }

  const draft = slot.draft;
  const setDraft = (change: Partial<Draft>) => update(target.id, (s) => ({ ...s, draft: { ...s.draft, ...change } }));
  const blocked = slot.outcome?.kind === "uncertain" && slot.historyRefresh.kind !== "refreshed";
  const prefix = `feedback-${target.id}`;

  return (
    <section className="panel" aria-label="Feedback">
      <h2>
        Feedback for analysis v{target.version}{" "}
        <span className="hint">({isLatest ? "latest version" : `historical version; latest is v${latest?.version ?? "?"}`})</span>
      </h2>
      <p className="hint">
        Feedback is stored as a new immutable record for this analysis version only. It never changes
        the original entry, the analysis, or stored extractions; the latest feedback decides this
        version&apos;s effective interpretation.
        {isLatest
          ? " Because this is the latest version, the record's state and the source for a new extraction follow it."
          : " The record's state and any new extraction use the latest analysis, not this historical version."}
      </p>

      <h3>Feedback history</h3>
      <FeedbackHistory
        load={slot.history}
        effectiveFeedbackId={effectiveFeedbackId}
        onReload={() => update(target.id, (s) => ({ ...s, historyReload: s.historyReload + 1 }))}
      />

      <form
        className="feedback-form"
        aria-label={`Record feedback for analysis v${target.version}`}
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <fieldset disabled={slot.pending}>
          <legend>Decision for analysis v{target.version}</legend>
          {effectiveResolution === "rejected" ? (
            <p className="hint">
              This version is currently rejected. New feedback becomes its latest judgment; the
              rejection stays in its history.
            </p>
          ) : null}
          {DECISIONS.map((d) => (
            <label key={d.status} className="feedback-decision">
              <input
                type="radio"
                name={`${prefix}-status`}
                value={d.status}
                checked={draft.status === d.status}
                onChange={() => setDraft({ status: d.status })}
              />
              <strong>{d.label}</strong> <span className="hint">{d.help}</span>
            </label>
          ))}

          {draft.status === "corrected" ? (
            <div className="feedback-correction">
              <label htmlFor={`${prefix}-category`}>Corrected category</label>
              <select
                id={`${prefix}-category`}
                value={draft.category}
                onChange={(event) => setDraft({ category: event.target.value })}
              >
                <option value="">Keep the original ({target.category})</option>
                {FR_L2_TAXONOMY_V1.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <label htmlFor={`${prefix}-explanation`}>Corrected explanation</label>
              <textarea
                id={`${prefix}-explanation`}
                rows={4}
                value={draft.explanation}
                placeholder="Leave empty to keep the original explanation"
                onChange={(event) => setDraft({ explanation: event.target.value })}
              />
              <p className="hint">The server requires a new category, a new explanation, or both.</p>
            </div>
          ) : null}

          <label htmlFor={`${prefix}-note`}>Note (optional)</label>
          <textarea
            id={`${prefix}-note`}
            rows={2}
            value={draft.note}
            onChange={(event) => setDraft({ note: event.target.value })}
          />
        </fieldset>

        <div className="actions">
          <button type="submit" className="primary" disabled={slot.pending || blocked || draft.status === null}>
            {slot.pending
              ? "Recording feedback…"
              : draft.status === null
                ? "Choose a decision to record"
                : `Record "${draft.status}" for analysis v${target.version}`}
          </button>
        </div>
        {blocked ? (
          <p className="hint">
            Unavailable until this version&apos;s feedback history has been re-read after the unknown
            outcome. Reload it and check whether your feedback was recorded before submitting again.
          </p>
        ) : null}
      </form>

      <OutcomeBanner outcome={slot.outcome} />
      <RefreshBanner refresh={slot.historyRefresh} what="feedback history" />
      <RefreshBanner refresh={effectiveRefresh} what="effective interpretation" />
    </section>
  );
}

function FeedbackHistory({
  load,
  effectiveFeedbackId,
  onReload,
}: {
  load: Load<Feedback[]>;
  effectiveFeedbackId: number | null | undefined;
  onReload: () => void;
}) {
  if (load.status === "loading") return <p className="value">Loading feedback history…</p>;
  if (load.status === "error") {
    return (
      <div className="banner error" role="alert">
        Could not load feedback history: {load.message}{" "}
        <button type="button" className="ghost" onClick={onReload}>
          Reload feedback history
        </button>
      </div>
    );
  }
  if (load.data.length === 0) {
    return (
      <p className="value">
        <strong>No feedback yet.</strong> No human has accepted, corrected, or rejected this version.
      </p>
    );
  }
  return (
    <ol className="annotation-list" aria-label="Feedback history (oldest first)">
      {load.data.map((f) => (
        <li key={f.id}>
          <strong>{f.status}</strong> <span className="mono">feedback #{f.id}</span>
          {f.id === effectiveFeedbackId ? <span className="record-state accepted"> in effect</span> : null}
          {f.corrected_category !== undefined ? <div>Category → {f.corrected_category}</div> : null}
          {f.corrected_explanation !== undefined ? <div>Explanation → {f.corrected_explanation}</div> : null}
          {f.user_note ? <div className="hint">Note: {f.user_note}</div> : null}
          <time className="hint" dateTime={f.created_at}>{f.created_at}</time>
        </li>
      ))}
    </ol>
  );
}
