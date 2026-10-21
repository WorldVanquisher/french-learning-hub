import { useRef, useState, type ReactNode } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { CaptureImport } from "./CaptureImport";
import { OutcomeBanner, type Outcome } from "./ExplicitAction";
import { msg, useI18n, type I18n } from "../i18n";

// The question as the learner typed it. Kept only in memory, never in browser storage.
type Draft = { question: string; context: string };

// Attempt is one submission: a stable capture ID and the exact JSON body sent.
// Resending it is idempotent on the server (the same capture_id with the same
// content replays the stored record), so an explicit resend after an unknown
// outcome can never create a second record. A different text never reuses it.
type Attempt = { captureId: string; body: string; draft: Draft; settled: boolean };

type Mode = "question" | "capture";

// newCaptureId returns "question-<uuid v4>". getRandomValues also works on plain
// HTTP origins (a LAN address), where randomUUID needs a secure context.
export function newCaptureId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `question-${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// questionCapture builds the learning_capture_v1 document for a plain question:
// source "manual" (entered by hand), the learner's text exactly as typed, and no
// analysis or discussion summary. The server trims only leading and trailing
// whitespace, as for every entry, and stores it as an unanalyzed record.
export function questionCapture(captureId: string, draft: Draft): string {
  return JSON.stringify({
    schema_version: "learning_capture_v1",
    capture_id: captureId,
    source: "manual",
    original_input: draft.question,
    original_context: draft.context,
  });
}

const sameDraft = (a: Draft, b: Draft) => a.question === b.question && a.context === b.context;

function describeError(error: unknown): string {
  if (error instanceof ApiError) return `(${error.status}) ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

// QuestionIntake is the single "add a learning question" panel (FLH-091). The
// default mode saves a typed question (and optional context) as an unanalyzed
// record: no analysis, extraction, provider request or human acceptance. The
// second mode is the existing Capture JSON import, unchanged. Both modes stay
// mounted, so switching keeps each draft and sends nothing.
export function QuestionIntake({
  onSaved,
  onOpenRecord,
}: {
  // Called after the server confirms a stored record (new or replayed).
  onSaved: (entryId: number) => void;
  onOpenRecord: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [mode, setMode] = useState<Mode>("question");
  const [draft, setDraft] = useState<Draft>({ question: "", context: "" });
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [pending, setPending] = useState(false);
  const [checking, setChecking] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const inFlight = useRef(false);
  // Ignores a status check that finishes after a newer submission started.
  const generation = useRef(0);

  const unresolved = attempt !== null && !attempt.settled;
  const editedSinceAttempt = unresolved && !sameDraft(attempt.draft, draft);
  const blank = draft.question.trim() === "";

  function openButton(i: I18n, entryId: number): ReactNode {
    return (
      <button type="button" className="ghost" onClick={() => onOpenRecord(entryId)}>
        {i.t("intake.open", { id: entryId })}
      </button>
    );
  }

  // stored reports a confirmed record and starts a fresh, empty question.
  function stored(entryId: number, kind: "new" | "replay" | "checked") {
    setOutcome({
      kind: "succeeded",
      text: (i) =>
        i.tn(kind === "new" ? "intake.saved" : kind === "replay" ? "intake.alreadySaved" : "intake.foundSaved", {
          record: entryId,
          open: openButton(i, entryId),
        }),
    });
    setAttempt(null);
    setDraft({ question: "", context: "" });
    onSaved(entryId);
  }

  async function send(current: Attempt) {
    if (inFlight.current) return;
    inFlight.current = true;
    const run = ++generation.current;
    setPending(true);
    setOutcome(null);
    try {
      const result = await api.importCapture(current.body);
      if (generation.current !== run) return;
      stored(result.entry_id, result.created ? "new" : "replay");
    } catch (error) {
      if (generation.current !== run) return;
      if (error instanceof NetworkError || (error instanceof ApiError && error.status >= 500)) {
        // The server may have stored it. Keep the draft and the attempt; offer
        // only a read-only check or an explicit resend of the same attempt.
        setAttempt({ ...current, settled: false });
        setOutcome({ kind: "uncertain", text: msg("intake.unknown", { error: describeError(error) }) });
      } else if (error instanceof ApiError && error.isConflict) {
        // Not expected for a fresh random ID; never overwrite, never retry.
        setAttempt(null);
        setOutcome({ kind: "rejected", text: msg("intake.conflict", { error: describeError(error) }) });
      } else {
        // Validation rejection: nothing was stored. A corrected text gets a new ID.
        setAttempt(null);
        setOutcome({ kind: "rejected", text: msg("intake.rejected", { error: describeError(error) }) });
      }
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }

  function save() {
    if (blank || editedSinceAttempt) return;
    // The unchanged text of an unconfirmed attempt is resent as the same attempt.
    if (attempt && !attempt.settled && sameDraft(attempt.draft, draft)) {
      void send(attempt);
      return;
    }
    const captureId = newCaptureId();
    const snapshot = { ...draft };
    const next: Attempt = { captureId, body: questionCapture(captureId, snapshot), draft: snapshot, settled: false };
    setAttempt(next);
    void send(next);
  }

  // checkStatus reads the receipt of the unconfirmed attempt (GET only).
  async function checkStatus() {
    if (!attempt) return;
    const run = generation.current;
    setChecking(true);
    try {
      const receipt = await api.getCaptureReceipt(attempt.captureId);
      if (generation.current !== run) return;
      stored(receipt.entry_id, "checked");
    } catch (error) {
      if (generation.current !== run) return;
      if (error instanceof ApiError && error.isNotFound) {
        // Confirmed not stored: the draft stays and can be saved normally.
        setAttempt(null);
        setOutcome({ kind: "rejected", text: msg("intake.notSaved") });
      } else {
        setOutcome({ kind: "uncertain", text: msg("intake.checkFailed", { error: describeError(error) }) });
      }
    } finally {
      setChecking(false);
    }
  }

  // discardAttempt is the explicit choice to stop tracking an unconfirmed attempt,
  // accepting that it may already be stored. It sends nothing.
  function discardAttempt() {
    setAttempt(null);
    setOutcome({ kind: "uncertain", text: msg("intake.discarded") });
  }

  return (
    <section className="panel question-intake" aria-labelledby="question-intake-title">
      <h2 id="question-intake-title">{t("intake.title")}</h2>
      <div className="intake-modes" role="group" aria-label={t("intake.modes")}>
        <button type="button" aria-pressed={mode === "question"} onClick={() => setMode("question")}>
          {t("intake.mode.question")}
        </button>
        <button type="button" aria-pressed={mode === "capture"} onClick={() => setMode("capture")}>
          {t("intake.mode.capture")}
        </button>
      </div>

      <div hidden={mode !== "question"}>
        <p className="hint">{t("intake.hint")}</p>
        <label className="intake-field">
          {t("intake.question")}
          <textarea
            rows={4}
            value={draft.question}
            aria-required="true"
            onChange={(event) => setDraft((d) => ({ ...d, question: event.target.value }))}
          />
        </label>
        <label className="intake-field">
          {t("intake.context")}
          <textarea
            rows={3}
            value={draft.context}
            onChange={(event) => setDraft((d) => ({ ...d, context: event.target.value }))}
          />
        </label>
        {editedSinceAttempt ? <p className="hint" role="status">{t("intake.editedWhileUnknown")}</p> : null}
        <div className="actions">
          <button
            type="button"
            className="primary"
            disabled={pending || checking || blank || editedSinceAttempt}
            onClick={save}
          >
            {pending ? t("intake.saving") : unresolved ? t("intake.resend") : t("intake.save")}
          </button>
          {unresolved ? (
            <>
              <button type="button" className="ghost" disabled={pending || checking} onClick={() => void checkStatus()}>
                {checking ? t("intake.checking") : t("intake.check")}
              </button>
              <button type="button" className="ghost" disabled={pending || checking} onClick={discardAttempt}>
                {t("intake.discard")}
              </button>
            </>
          ) : null}
        </div>
        <OutcomeBanner outcome={outcome} />
      </div>

      <div hidden={mode !== "capture"}>
        <CaptureImport onImported={onSaved} onOpenRecord={onOpenRecord} />
      </div>
    </section>
  );
}
