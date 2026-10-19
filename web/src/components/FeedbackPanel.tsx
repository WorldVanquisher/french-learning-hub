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
import { msg, useI18n, type MessageKey } from "../i18n";

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

const DECISIONS: Array<{ status: FeedbackStatus; label: MessageKey; help: MessageKey }> = [
  { status: "accepted", label: "feedback.accept", help: "feedback.accept.help" },
  { status: "corrected", label: "feedback.correct", help: "feedback.correct.help" },
  { status: "rejected", label: "feedback.reject", help: "feedback.reject.help" },
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
  const { t, status: statusLabel } = useI18n();
  const [slots, setSlots] = useState<Record<number, Slot>>({});
  const inFlight = useRef(new Set<number>());
  const mounted = useRef(true);
  // Set in setup, cleared in cleanup: StrictMode's development effect replay
  // (setup, cleanup, setup) must leave it true, while a real unmount clears it.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
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
      const latestVersion = latest?.version ?? "?";
      outcome = {
        kind: "succeeded",
        text: (i) =>
          i.t(isLatest ? "feedback.recorded.latest" : "feedback.recorded.historical", {
            id: created.id,
            status: i.status(created.status),
            version: target.version,
            latest: latestVersion,
          }),
      };
    } catch (error) {
      if (error instanceof NetworkError) {
        reread = true;
        outcome = { kind: "uncertain", text: msg("feedback.noResponse", { version: target.version }) };
      } else {
        outcome = {
          kind: "rejected",
          text: msg("feedback.rejected", { version: target.version, error: describeError(error) }),
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
    <section className="panel" aria-label={t("feedback.region")}>
      <h2>
        {t("feedback.heading", { version: target.version })}{" "}
        <span className="hint">
          {isLatest ? t("version.latestTag") : t("version.historicalTag", { latest: latest?.version ?? "?" })}
        </span>
      </h2>
      <p className="hint">{t(isLatest ? "feedback.hint.latest" : "feedback.hint.historical")}</p>

      <h3>{t("feedback.history")}</h3>
      <FeedbackHistory
        load={slot.history}
        effectiveFeedbackId={effectiveFeedbackId}
        onReload={() => update(target.id, (s) => ({ ...s, historyReload: s.historyReload + 1 }))}
      />

      <form
        className="feedback-form"
        aria-label={t("feedback.form", { version: target.version })}
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <fieldset disabled={slot.pending}>
          <legend>{t("feedback.legend", { version: target.version })}</legend>
          {effectiveResolution === "rejected" ? <p className="hint">{t("feedback.currentlyRejected")}</p> : null}
          {DECISIONS.map((d) => (
            <label key={d.status} className="feedback-decision">
              <input
                type="radio"
                name={`${prefix}-status`}
                value={d.status}
                checked={draft.status === d.status}
                onChange={() => setDraft({ status: d.status })}
              />
              <strong>{t(d.label)}</strong> <span className="hint">{t(d.help)}</span>
            </label>
          ))}

          {draft.status === "corrected" ? (
            <div className="feedback-correction">
              <label htmlFor={`${prefix}-category`}>{t("feedback.correctedCategory")}</label>
              <select
                id={`${prefix}-category`}
                value={draft.category}
                onChange={(event) => setDraft({ category: event.target.value })}
              >
                <option value="">{t("feedback.keepCategory", { category: target.category })}</option>
                {FR_L2_TAXONOMY_V1.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <label htmlFor={`${prefix}-explanation`}>{t("feedback.correctedExplanation")}</label>
              <textarea
                id={`${prefix}-explanation`}
                rows={4}
                value={draft.explanation}
                placeholder={t("feedback.keepExplanation")}
                onChange={(event) => setDraft({ explanation: event.target.value })}
              />
              <p className="hint">{t("feedback.correctionRequired")}</p>
            </div>
          ) : null}

          <label htmlFor={`${prefix}-note`}>{t("feedback.note")}</label>
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
              ? t("feedback.recording")
              : draft.status === null
                ? t("feedback.choose")
                : t("feedback.submit", { status: statusLabel(draft.status), version: target.version })}
          </button>
        </div>
        {blocked ? (
          <p className="hint">{t("feedback.blocked")}</p>
        ) : null}
      </form>

      <OutcomeBanner outcome={slot.outcome} />
      <RefreshBanner refresh={slot.historyRefresh} what={msg("feedback.what.history")} />
      <RefreshBanner refresh={effectiveRefresh} what={msg("feedback.what.effective")} />
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
  const { t, status } = useI18n();
  if (load.status === "loading") return <p className="value">{t("feedback.historyLoading")}</p>;
  if (load.status === "error") {
    return (
      <div className="banner error" role="alert">
        {t("feedback.historyFailed", { message: load.message })}{" "}
        <button type="button" className="ghost" onClick={onReload}>
          {t("feedback.historyReload")}
        </button>
      </div>
    );
  }
  if (load.data.length === 0) {
    return (
      <p className="value">
        <strong>{t("feedback.none")}</strong> {t("feedback.none.detail")}
      </p>
    );
  }
  return (
    <ol className="annotation-list" aria-label={t("feedback.historyList")}>
      {load.data.map((f) => (
        <li key={f.id}>
          <strong>{status(f.status)}</strong> <span className="mono">feedback #{f.id}</span>
          {f.id === effectiveFeedbackId ? <span className="record-state accepted"> {t("feedback.inEffect")}</span> : null}
          {f.corrected_category !== undefined ? <div>{t("feedback.categoryArrow")} {f.corrected_category}</div> : null}
          {f.corrected_explanation !== undefined ? <div>{t("feedback.explanationArrow")} {f.corrected_explanation}</div> : null}
          {f.user_note ? <div className="hint">{t("feedback.noteLabel")} {f.user_note}</div> : null}
          <time className="hint" dateTime={f.created_at}>{f.created_at}</time>
        </li>
      ))}
    </ol>
  );
}
