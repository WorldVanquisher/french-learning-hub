import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { StoredText } from "../components/ExplanationText";
import { useI18n, type MessageKey } from "../i18n";
import type {
  SpeakingAttemptState,
  SpeakingExerciseSummary,
  SpeakingExerciseView,
  SpeakingFeedback,
  SpeakingImprovement,
  SpeakingPractice,
  SpeakingPrompts,
  SpeakingQueueItem,
  SpeakingRequest,
  SpeakingTake,
  SpeakingTranscript,
} from "../types/speaking";
import { randomOperationId } from "./annotationOperation";
import { alreadySaved, sourceRef } from "./notebookLink";
import { countWords, diffWords } from "./Writing";
import {
  base64Of,
  canonicalAudioType,
  classifyRecordingError,
  microphonePermission,
  SILENT_PEAK,
  type MicrophonePermission,
  formatBytes,
  formatDuration,
  measureDuration,
  recordingSupport,
  sha256Hex,
  startRecording,
  type ActiveRecording,
  type RecordingError,
} from "./speakingRecorder";

// Speaking v1 (private workbench only; never in the public demo).
//
// - A take is recorded and played back in this browser. Nothing is sent while
//   recording or playing back, and the audio is never stored anywhere: "Use
//   this take" saves only its type, size, digest and duration.
// - "Send audio for transcription" is the one request that sends a take's
//   audio, after a panel that says what is sent and to whom. The learner then
//   corrects and confirms the transcript, which becomes an immutable version.
// - Feedback is one explicit request for one confirmed version, about that
//   version only. It reads text, so it says nothing about pronunciation, and
//   there is no score. Hints first; the suggested wording on request.
// - A mistake becomes a learning record only through an explicit "Save
//   learning record" via the existing capture path (source "manual").

type Load<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };

const describe = (e: unknown) =>
  e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e);

function useLoad<T>(key: string, load: () => Promise<T>, epoch: number): Load<T> {
  const [state, setState] = useState<{ key: string; epoch: number; load: Load<T> }>({ key, epoch, load: { status: "loading" } });
  useEffect(() => {
    let active = true;
    load().then(
      (data) => active && setState({ key, epoch, load: { status: "ready", data } }),
      (e: unknown) => active && setState({ key, epoch, load: { status: "error", message: describe(e) } }),
    );
    return () => {
      active = false;
    };
    // `load` is recreated each render; `key` and `epoch` identify the request.
  }, [key, epoch]);
  // A reload of the same key keeps showing the last data, so an open editor or
  // a take being played back is never unmounted by a refresh.
  if (state.key === key && (state.epoch === epoch || state.load.status === "ready")) return state.load;
  return { status: "loading" };
}

// LocalAudio is a take's audio, in this browser's memory only.
export interface LocalAudio {
  blob: Blob;
  url: string;
  mime: string;
  durationMs: number;
  sha256: string;
  source: "recording" | "file";
}

const occurrences = (text: string, quote: string) => (quote === "" ? 0 : text.split(quote).length - 1);

// shownAsGrounded is a display guard on the server's grounding: an improvement
// is shown against the transcript only when its quote really occurs in it.
export function shownAsGrounded(text: string, k: SpeakingImprovement): boolean {
  const n = occurrences(text, k.quote);
  return (k.grounding === "located" && n === 1) || (k.grounding === "ambiguous" && n > 1);
}

const ratingKey: Record<"met" | "partly_met" | "not_met", MessageKey> = {
  met: "writing.rating.met",
  partly_met: "writing.rating.partly_met",
  not_met: "writing.rating.not_met",
};
const failureKey: Record<"provider_timeout" | "provider_unavailable" | "invalid_output", MessageKey> = {
  provider_timeout: "speaking.failure.provider_timeout",
  provider_unavailable: "speaking.failure.provider_unavailable",
  invalid_output: "speaking.failure.invalid_output",
};
const originKey: Record<SpeakingTranscript["origin"], MessageKey> = {
  transcription: "speaking.origin.transcription",
  corrected: "speaking.origin.corrected",
  typed: "speaking.origin.typed",
};
const stateKey: Record<SpeakingAttemptState, MessageKey> = {
  awaiting_transcript: "speaking.state.awaiting_transcript",
  transcribing: "speaking.state.transcribing",
  transcription_failed: "speaking.state.transcription_failed",
  transcription_unknown: "speaking.state.transcription_unknown",
  transcript_to_confirm: "speaking.state.transcript_to_confirm",
  awaiting_feedback: "speaking.state.awaiting_feedback",
  feedback_in_progress: "speaking.state.feedback_in_progress",
  feedback_failed: "speaking.state.feedback_failed",
  feedback_unknown: "speaking.state.feedback_unknown",
  feedback_ready: "speaking.state.feedback_ready",
};
const sourceKey: Record<SpeakingTake["audio_source"], MessageKey> = {
  recording: "speaking.history.source.recording",
  file: "speaking.history.source.file",
  none: "speaking.history.source.none",
};
const when = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
};

export function Speaking({
  onOpenRecord,
  openRequest,
}: {
  onOpenRecord?: (entryId: number) => void;
  openRequest?: { exerciseId: number; takeId?: number; transcriptVersion?: number; nonce: number } | null;
} = {}) {
  const [screen, setScreen] = useState<{ kind: "list" } | { kind: "exercise"; id: number; takeId?: number; version?: number; nonce?: number }>({ kind: "list" });
  // A Mistake Notebook link opens the exercise at the take and transcript version its improvement is about.
  useEffect(() => {
    if (openRequest)
      setScreen({ kind: "exercise", id: openRequest.exerciseId, takeId: openRequest.takeId, version: openRequest.transcriptVersion, nonce: openRequest.nonce });
  }, [openRequest]);
  const [epoch, setEpoch] = useState(0);
  // Takes' audio lives here, in memory, while Speaking is mounted. It is never
  // written to the server or to browser storage.
  const [audio, setAudio] = useState<Map<number, LocalAudio>>(() => new Map());
  // Keeping new audio for a take releases the object URL it replaces.
  const keep = (takeId: number, a: LocalAudio) =>
    setAudio((m) => {
      const old = m.get(takeId);
      if (old && old.url !== a.url) URL.revokeObjectURL(old.url);
      return new Map(m).set(takeId, a);
    });
  return (
    <main className="writing speaking">
      {screen.kind === "list" ? (
        <ExerciseList epoch={epoch} onOpen={(id, takeId) => setScreen({ kind: "exercise", id, takeId, nonce: Date.now() })} />
      ) : (
        <ExerciseScreen
          key={`${screen.id}-${screen.nonce ?? 0}`}
          id={screen.id}
          initialTake={screen.takeId}
          initialVersion={screen.version}
          audio={audio}
          keep={keep}
          onBack={() => {
            setEpoch((n) => n + 1);
            setScreen({ kind: "list" });
          }}
          onOpenRecord={onOpenRecord}
        />
      )}
    </main>
  );
}

// PracticeOverview shows the backend's practice overview: what was actually
// completed, what is waiting, and one next step per exercise with its reason.
function PracticeOverview({ load, onRetry, onOpen, onStart, busy }: {
  load: Load<SpeakingPractice>;
  onRetry: () => void;
  onOpen: (id: number, takeId?: number) => void;
  onStart: (promptId: string) => void;
  busy: boolean;
}) {
  const { t, tp } = useI18n();
  const reason = (q: SpeakingQueueItem) => {
    const n = q.take_number ?? 0;
    switch (q.reason) {
      case "answer_again":
        return tp("speaking.queue.reason.answer_again", q.improvements, { n });
      case "check_unknown_outcome":
      case "request_failed":
      case "confirm_transcript":
      case "add_transcript":
      case "request_feedback":
        return t(`speaking.queue.reason.${q.reason}`, { n });
      default:
        return t(`speaking.queue.reason.${q.reason}`);
    }
  };
  if (load.status !== "ready")
    return (
      <section className="panel" aria-label={t("speaking.practice.region")}>
        <h2>{t("speaking.practice.heading")}</h2>
        {load.status === "error" ? (
          <div className="banner error" role="alert">
            {t("speaking.practice.failed", { message: load.message })}{" "}
            <button type="button" className="ghost" onClick={onRetry}>
              {t("common.retry")}
            </button>
          </div>
        ) : (
          <p className="hint" role="status">{t("speaking.loading")}</p>
        )}
      </section>
    );
  const p = load.data;
  const s = p.summary;
  return (
    <section className="panel" aria-label={t("speaking.practice.region")}>
      <h2>{t("speaking.practice.heading")}</h2>
      <ul className="speaking-summary">
        <li>{t("speaking.practice.started", { started: s.started, prompts: s.prompts })}</li>
        <li>{t("speaking.practice.completed", { completed: s.completed, takes: s.takes })}</li>
        <li>
          {t("speaking.practice.pending", {
            transcript: s.awaiting_transcript,
            feedback: s.awaiting_feedback,
            progress: s.in_progress,
            failed: s.failed,
            unknown: s.unknown,
          })}
        </li>
        {s.last_completed_at ? <li>{t("speaking.practice.lastCompleted", { date: when(s.last_completed_at) })}</li> : null}
      </ul>
      <p className="hint">{t("speaking.practice.countsNote")}</p>
      <h3>{t("speaking.queue.heading")}</h3>
      <p className="hint">{t("speaking.queue.hint")}</p>
      {p.queue.length === 0 ? (
        <p className="empty">{t("speaking.queue.empty")}</p>
      ) : (
        <ol className="listening-list speaking-queue">
          {p.queue.map((q) => (
            <li key={`${q.prompt_id}-${q.exercise_id ?? 0}`} data-reason={q.reason}>
              <span className="reading-example-title">{q.title}</span>
              <p>{reason(q)}</p>
              {q.exercise_id !== null ? (
                <button type="button" className="ghost" onClick={() => onOpen(q.exercise_id!, q.take_id ?? undefined)}>
                  {t("speaking.queue.open")}
                </button>
              ) : (
                <button type="button" disabled={busy} onClick={() => onStart(q.prompt_id)}>
                  {t("speaking.queue.start")}
                </button>
              )}
            </li>
          ))}
        </ol>
      )}
      {s.takes > 0 ? (
        <p className="hint">
          <a href={api.speakingExportUrl} download>
            {t("speaking.export.link")}
          </a>{" "}
          {t("speaking.export.hint")}
        </p>
      ) : null}
    </section>
  );
}

function ExerciseList({ epoch, onOpen }: { epoch: number; onOpen: (id: number, takeId?: number) => void }) {
  const { t, tp } = useI18n();
  const [retry, setRetry] = useState(0);
  const practice = useLoad<SpeakingPractice>("practice", () => api.getSpeakingPractice(), epoch * 100 + retry);
  const prompts = useLoad<SpeakingPrompts>("prompts", () => api.listSpeakingPrompts(), epoch * 100 + retry);
  const exercises = useLoad<{ exercises: SpeakingExerciseSummary[] }>("exercises", () => api.listSpeakingExercises(), epoch * 100 + retry);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const start = async (promptId: string) => {
    setBusy(true);
    setError(null);
    try {
      onOpen((await api.startSpeakingPrompt(promptId)).exercise.id);
    } catch (e) {
      setError(e instanceof NetworkError ? t("speaking.prompts.unknown") : t("speaking.prompts.failed", { message: describe(e) }));
      setBusy(false);
    }
  };
  return (
    <>
      <PracticeOverview load={practice} onRetry={() => setRetry((n) => n + 1)} onOpen={onOpen} onStart={start} busy={busy} />
      <section className="panel" aria-label={t("speaking.prompts.region")}>
        <h2>{t("speaking.prompts.heading")}</h2>
        <p className="hint">{t("speaking.prompts.hint")}</p>
        {prompts.status === "ready" ? (
          <ul className="listening-list">
            {prompts.data.prompts.map((p) => (
              <li key={p.id}>
                <span className="reading-example-title">{p.title}</span>{" "}
                <span className="hint">{t("speaking.prompts.meta", { format: p.format, min: p.seconds_min, max: p.seconds_max })}</span>{" "}
                {p.started_exercise_id !== null ? (
                  <>
                    <button type="button" className="ghost" onClick={() => onOpen(p.started_exercise_id!)}>
                      {t("speaking.prompts.open")}
                    </button>
                    {p.started_pack_status === "changed" ? <p className="hint">{t("speaking.prompts.changed")}</p> : null}
                  </>
                ) : (
                  <button type="button" disabled={busy} onClick={() => start(p.id)}>
                    {t("speaking.prompts.start")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        ) : prompts.status === "error" ? (
          <div className="banner error" role="alert">
            {t("speaking.prompts.failed", { message: prompts.message })}{" "}
            <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
              {t("common.retry")}
            </button>
          </div>
        ) : (
          <p className="hint" role="status">{t("speaking.loading")}</p>
        )}
        {error ? (
          <div className="banner error" role="alert">
            {error}
          </div>
        ) : null}
      </section>
      <section className="panel" aria-label={t("speaking.list.region")}>
        <h2>{t("speaking.list.heading")}</h2>
        {exercises.status === "ready" ? (
          exercises.data.exercises.length === 0 ? (
            <p className="empty">{t("speaking.list.empty")}</p>
          ) : (
            <ul className="listening-list">
              {exercises.data.exercises.map((row) => (
                <li key={row.exercise.id}>
                  <button type="button" className="link-button" onClick={() => onOpen(row.exercise.id)}>
                    {row.exercise.title}
                  </button>{" "}
                  <span className="tag">{tp("speaking.list.takes", row.takes)}</span>
                </li>
              ))}
            </ul>
          )
        ) : exercises.status === "error" ? (
          <div className="banner error" role="alert">
            {t("speaking.list.failed", { message: exercises.message })}
          </div>
        ) : (
          <p className="hint" role="status">{t("speaking.loading")}</p>
        )}
      </section>
    </>
  );
}

function ExerciseScreen({
  id,
  initialTake,
  initialVersion,
  audio,
  keep,
  onBack,
  onOpenRecord,
}: {
  id: number;
  initialTake?: number;
  initialVersion?: number;
  audio: Map<number, LocalAudio>;
  keep: (takeId: number, a: LocalAudio) => void;
  onBack: () => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [epoch, setEpoch] = useState(0);
  const view = useLoad<SpeakingExerciseView>(String(id), () => api.getSpeakingExercise(id), epoch);
  const [selectedTake, setSelectedTake] = useState<number | null>(initialTake ?? null);
  const [retry, setRetry] = useState<(RetryPoints & { nonce: number }) | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), [view.status]);
  const back = (
    <button type="button" className="ghost" onClick={onBack}>
      {t("speaking.back")}
    </button>
  );
  if (view.status !== "ready")
    return (
      <section className="panel" aria-label={t("speaking.exercise.region")}>
        <h2 ref={headingRef} tabIndex={-1}>
          {t("speaking.exercise.heading", { id })}
        </h2>
        {back}
        {view.status === "loading" ? (
          <p className="hint" role="status">{t("speaking.loading")}</p>
        ) : (
          <div className="banner error" role="alert">
            {t("speaking.exercise.failed", { message: view.message })}{" "}
            <button type="button" className="ghost" onClick={() => setEpoch((n) => n + 1)}>
              {t("common.retry")}
            </button>
          </div>
        )}
      </section>
    );
  const v = view.data;
  const reload = () => setEpoch((n) => n + 1);
  const take = v.takes.find((k) => k.id === selectedTake) ?? v.takes[v.takes.length - 1] ?? null;
  return (
    <div>
      <section className="panel" aria-label={t("speaking.exercise.region")}>
        <h2 ref={headingRef} tabIndex={-1} className="library-title">
          {v.exercise.title}
        </h2>
        <div className="actions">{back}</div>
        <p lang="fr" className="french">
          {v.exercise.situation}
        </p>
        <ul className="listening-steps">
          {v.exercise.requirements.map((r, i) => (
            <li key={i} lang="fr" className="french">
              {r}
            </li>
          ))}
        </ul>
        <p className="hint">{t("speaking.exercise.range", { min: v.exercise.seconds_min, max: v.exercise.seconds_max })}</p>
        {v.exercise.pack_status !== "current" ? (
          <div className="banner info" role="note">
            {t(v.exercise.pack_status === "removed" ? "speaking.pack.removed" : "speaking.pack.changed")}
          </div>
        ) : null}
        <p className="hint">{t("speaking.practiceNotice")}</p>
      </section>
      <RecordPanel
        view={v}
        retry={retry}
        onHideRetry={() => setRetry(null)}
        onSaved={(takeId, local) => {
          if (local) keep(takeId, local);
          setSelectedTake(takeId);
          setRetry(null);
          reload();
        }}
      />
      {take ? (
        <>
          <TakesPanel view={v} take={take} onSelect={setSelectedTake} />
          <TakeDetail
            key={take.id}
            view={v}
            take={take}
            initialVersion={take.id === initialTake ? initialVersion : undefined}
            local={audio.get(take.id) ?? null}
            onReattach={(a) => keep(take.id, a)}
            onChanged={reload}
            onOpenRecord={onOpenRecord}
            onRetry={(points) => setRetry((prev) => ({ ...points, nonce: (prev?.nonce ?? 0) + 1 }))}
          />
          <ComparePanel view={v} />
        </>
      ) : null}
    </div>
  );
}

// The points of one feedback report the learner chose to keep in mind for the
// next take ("Record take N with these points in mind"); cleared once a take is
// saved or the learner hides them. Page state only.
export interface RetryPoints {
  take: number;
  version: number;
  points: { quote: string; category: string }[];
}

type RecordState =
  | { status: "idle" }
  | { status: "asking" }
  // `heard`: some sound has reached the microphone during this recording, so a
  // pause between words does not read as "no sound yet".
  | { status: "recording"; elapsed: number; level: number | null; heard: boolean }
  | { status: "recorded"; local: LocalAudio; silent: boolean }
  | { status: "saving"; local: LocalAudio | null }
  | { status: "refused"; kind: RecordingError }
  // A failed save keeps the recording (`local`); `unknown` means no answer
  // arrived, so the take may or may not exist until it is checked.
  | { status: "error"; message: string; local?: LocalAudio | null; unknown?: boolean; checking?: boolean };

const refusedKey: Record<RecordingError, MessageKey> = {
  denied: "speaking.record.denied",
  no_device: "speaking.record.noDevice",
  busy: "speaking.record.busy",
  failed: "speaking.record.failed",
};

const permissionKey: Record<Exclude<MicrophonePermission, "unknown">, MessageKey> = {
  granted: "speaking.record.permission.granted",
  prompt: "speaking.record.permission.prompt",
  denied: "speaking.record.permission.denied",
};

function RecordPanel({
  view,
  onSaved,
  retry = null,
  onHideRetry,
}: {
  view: SpeakingExerciseView;
  onSaved: (takeId: number, local: LocalAudio | null) => void;
  // Points from a feedback report to keep in mind for this take.
  retry?: (RetryPoints & { nonce: number }) | null;
  onHideRetry?: () => void;
}) {
  const { t } = useI18n();
  const panelRef = useRef<HTMLElement>(null);
  const support = useMemo(() => recordingSupport(), []);
  const [state, setState] = useState<RecordState>({ status: "idle" });
  // Discrete announcements for assistive technology (started, stopped, saved…);
  // the running timer and level meter are visual only, so nothing chatters.
  const [announcement, setAnnouncement] = useState("");
  const [permission, setPermission] = useState<MicrophonePermission>("unknown");
  const active = useRef<ActiveRecording | null>(null);
  const limits = view.limits;
  const next = view.takes.length + 1;
  useEffect(
    () => () => {
      active.current?.stop();
    },
    [],
  );
  // "Record take N with these points in mind": bring the recorder into view
  // and put focus on its first action, with the points listed above it.
  const retryNonce = retry?.nonce ?? null;
  useEffect(() => {
    if (retryNonce === null) return;
    const panel = panelRef.current;
    panel?.scrollIntoView({ block: "start" });
    panel?.querySelector<HTMLElement>(".speaking-retry")?.focus();
  }, [retryNonce]);
  useEffect(() => {
    if (support !== "supported") return;
    let live = true;
    void microphonePermission((p) => live && setPermission(p)).then((p) => live && setPermission(p));
    return () => {
      live = false;
    };
  }, [support]);
  const record = async () => {
    setState({ status: "asking" });
    let rec: ActiveRecording;
    let heard = false;
    try {
      rec = await startRecording(limits.max_duration_ms, (elapsed, level) => {
        if (level !== null && level >= SILENT_PEAK) heard = true;
        setState({ status: "recording", elapsed, level, heard });
      });
    } catch (e) {
      setState({ status: "refused", kind: classifyRecordingError(e) });
      void microphonePermission().then(setPermission);
      return;
    }
    active.current = rec;
    setState({ status: "recording", elapsed: 0, level: null, heard: false });
    setAnnouncement(t("speaking.record.started", { max: formatDuration(limits.max_duration_ms) }));
    void microphonePermission().then(setPermission);
    try {
      const r = await rec.done;
      active.current = null;
      const silent = r.peakLevel !== null && r.peakLevel < SILENT_PEAK;
      setState({
        status: "recorded",
        local: { blob: r.blob, url: URL.createObjectURL(r.blob), mime: r.mime, durationMs: r.durationMs, sha256: await sha256Hex(r.blob), source: "recording" },
        silent,
      });
      setAnnouncement(t(silent ? "speaking.record.stoppedSilent" : "speaking.record.stopped", { duration: formatDuration(r.durationMs) }));
    } catch (e) {
      active.current = null;
      setState({ status: "error", message: describe(e) });
    }
  };
  const pickFile = async (file: File | undefined) => {
    if (!file) return;
    const type = canonicalAudioType(file.type);
    if (!type) {
      setState({ status: "error", message: t("speaking.record.fileType", { types: limits.accepted_types.join(", ") }) });
      return;
    }
    if (file.size > limits.max_audio_bytes) {
      setState({ status: "error", message: t("speaking.record.fileTooLarge", { max: formatBytes(limits.max_audio_bytes) }) });
      return;
    }
    const ms = await measureDuration(file);
    if (ms === null || ms > limits.max_duration_ms) {
      setState({ status: "error", message: ms === null ? t("speaking.record.fileNoDuration") : t("speaking.record.fileTooLong", { max: formatDuration(limits.max_duration_ms) }) });
      return;
    }
    setState({ status: "recorded", local: { blob: file, url: URL.createObjectURL(file), mime: file.type, durationMs: ms, sha256: await sha256Hex(file), source: "file" }, silent: false });
  };
  const save = async (local: LocalAudio | null) => {
    setState({ status: "saving", local });
    setAnnouncement(t("speaking.record.saving", { n: next }));
    try {
      const accepted = local ? canonicalAudioType(local.mime) : null;
      const body =
        local && accepted
          ? { audio_source: local.source, audio_mime: local.mime, audio_bytes: local.blob.size, audio_sha256: local.sha256, duration_ms: local.durationMs }
          : { audio_source: "none" as const };
      // take_id names the take saved: a resent save names the existing take.
      const res = await api.addSpeakingTake(view.exercise.id, body);
      const saved = res.takes.find((k) => k.id === res.take_id) ?? res.takes[res.takes.length - 1];
      setAnnouncement(t("speaking.record.saved", { n: saved.number }));
      onSaved(res.take_id, local);
      setState({ status: "idle" });
    } catch (e) {
      // The recording stays: a failed save never costs the learner the take.
      setState(
        e instanceof NetworkError
          ? { status: "error", message: t("speaking.record.saveUnknown"), local, unknown: true }
          : { status: "error", message: t("speaking.record.saveFailed", { message: describe(e) }), local },
      );
    }
  };
  // After a save whose answer was lost: read the exercise again and look for a
  // take with this recording's digest that was not there before.
  const checkSaved = async (local: LocalAudio | null) => {
    if (!local) return;
    setState({ status: "error", message: t("speaking.record.saveUnknown"), local, unknown: true, checking: true });
    const known = new Set(view.takes.map((k) => k.id));
    try {
      const fresh = await api.getSpeakingExercise(view.exercise.id);
      const found = fresh.takes.find((k) => !known.has(k.id) && k.audio_sha256 === local.sha256);
      if (found) {
        setAnnouncement(t("speaking.record.saved", { n: found.number }));
        onSaved(found.id, local);
        setState({ status: "idle" });
      } else {
        setState({ status: "error", message: t("speaking.record.notSavedAfterCheck", { n: fresh.takes.length + 1 }), local });
      }
    } catch (e) {
      setState({ status: "error", message: t("speaking.record.checkFailed", { message: describe(e) }), local, unknown: true });
    }
  };
  const discard = (local: LocalAudio | null | undefined) => {
    if (local) URL.revokeObjectURL(local.url);
    setState({ status: "idle" });
  };
  const local = state.status === "recorded" || state.status === "saving" ? state.local : state.status === "error" ? (state.local ?? null) : null;
  const busy = state.status === "saving" || (state.status === "error" && state.checking === true);
  return (
    <section className="panel" aria-label={t("speaking.record.region")} ref={panelRef}>
      <h3>{t("speaking.record.heading", { n: next })}</h3>
      {retry ? (
        <div className="banner info speaking-retry" tabIndex={-1} role="group" aria-label={t("speaking.retry.region")}>
          <p>{t("speaking.retry.heading", { n: retry.take, version: retry.version })}</p>
          {retry.points.length > 0 ? (
            <ul className="speaking-retry-points">
              {retry.points.map((p, i) => (
                <li key={i}>
                  <span lang="fr" className="french">
                    « {p.quote} »
                  </span>{" "}
                  <span className="tag">{t(`writing.category.${p.category}` as MessageKey)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="hint">{t("speaking.retry.none")}</p>
          )}
          <button type="button" className="ghost" onClick={onHideRetry}>
            {t("speaking.retry.hide")}
          </button>
        </div>
      ) : null}
      <p className="hint">{t("speaking.record.privacy")}</p>
      <p className="visually-hidden speaking-announce" aria-live="polite" aria-atomic="true">
        {announcement}
      </p>
      {support === "unsupported" ? (
        <div className="banner info" role="status">
          {t("speaking.record.unsupported")}
        </div>
      ) : permission !== "unknown" && state.status !== "recording" ? (
        <p className={`hint speaking-permission speaking-permission-${permission}`}>{t(permissionKey[permission])}</p>
      ) : null}
      {state.status === "refused" ? (
        <div className="banner error" role="alert">
          {t(refusedKey[state.kind])}
        </div>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {state.message}
          {state.local ? ` ${t("speaking.record.keptAfterError")}` : ""}
        </div>
      ) : null}
      {state.status === "recording" ? (
        <div className="speaking-recording">
          <div className="actions">
            <span className="tag speaking-timer">
              {t("speaking.record.recording", { elapsed: formatDuration(state.elapsed), max: formatDuration(limits.max_duration_ms) })}
            </span>
            <button type="button" className="primary" onClick={() => active.current?.stop()}>
              {t("speaking.record.stop")}
            </button>
          </div>
          {state.level !== null ? (
            <div className="speaking-level">
              <meter min={0} max={0.3} low={SILENT_PEAK} value={Math.min(0.3, state.level)} aria-label={t("speaking.record.level")} />{" "}
              <span className="hint">{t(state.heard ? "speaking.record.hearing" : "speaking.record.quiet")}</span>
            </div>
          ) : null}
        </div>
      ) : local ? (
        <div className="speaking-local" role="group" aria-label={t(state.status === "saving" ? "speaking.record.savingRegion" : "speaking.record.previewRegion")}>
          <p>
            <span className="tag warn speaking-unsaved">{t(state.status === "saving" ? "speaking.record.savingTag" : "speaking.record.unsavedTag")}</span>
          </p>
          <audio controls src={local.url} aria-label={t("speaking.record.playback")} />
          <p className="hint">
            {t("speaking.record.previewMeta", { duration: formatDuration(local.durationMs), size: formatBytes(local.blob.size), type: local.mime || "?" })}
          </p>
          {state.status === "recorded" && state.silent ? (
            <div className="banner info" role="note">
              {t("speaking.record.silent")}
            </div>
          ) : null}
          {!canonicalAudioType(local.mime) ? <p className="hint">{t("speaking.record.notTranscribable")}</p> : null}
          {state.status === "saving" ? (
            <p className="hint speaking-saving">{t("speaking.record.saving", { n: next })}</p>
          ) : state.status === "recorded" ? (
            <p className="hint">{t("speaking.record.notSent")}</p>
          ) : null}
          <p className="hint">{t("speaking.record.retention")}</p>
          <div className="actions">
            {state.status === "error" && state.unknown ? (
              <button type="button" className="primary" disabled={busy} onClick={() => checkSaved(local)}>
                {state.checking ? t("speaking.record.checking") : t("speaking.record.checkSaved")}
              </button>
            ) : (
              <button type="button" className="primary" disabled={busy} onClick={() => save(local)}>
                {t("speaking.record.use", { n: next })}
              </button>
            )}
            <button type="button" className="ghost" disabled={busy} onClick={() => discard(local)}>
              {t("speaking.record.discard")}
            </button>
          </div>
        </div>
      ) : (
        <div className="actions">
          {support === "supported" ? (
            <button type="button" className="primary" disabled={state.status === "asking" || busy} onClick={record}>
              {state.status === "asking" ? t("speaking.record.asking") : t("speaking.record.start")}
            </button>
          ) : null}
          <label className="ghost speaking-file">
            {t("speaking.record.file")}{" "}
            <input type="file" accept={limits.accepted_types.join(",")} disabled={busy} onChange={(e) => pickFile(e.target.files?.[0])} />
          </label>
          <button type="button" className="ghost" disabled={busy} onClick={() => save(null)}>
            {t("speaking.record.typeInstead")}
          </button>
          {state.status === "saving" ? <span className="hint speaking-saving">{t("speaking.record.saving", { n: next })}</span> : null}
        </div>
      )}
      <p className="hint">{t("speaking.record.limits", { max: formatDuration(limits.max_duration_ms), size: formatBytes(limits.max_audio_bytes) })}</p>
    </section>
  );
}

// attemptReport is the report that counts for a take: the newest completed
// one on its latest confirmed version (the backend's feedback_ready rule).
export function attemptReport(view: SpeakingExerciseView, take: SpeakingTake): SpeakingFeedback | null {
  const versions = view.transcripts.filter((s) => s.take_id === take.id);
  const latest = versions[versions.length - 1];
  if (!latest) return null;
  return view.feedback.find((f) => f.transcript_id === latest.id && f.status === "completed" && f.content) ?? null;
}

function TakesPanel({ view, take, onSelect }: { view: SpeakingExerciseView; take: SpeakingTake; onSelect: (id: number) => void }) {
  const { t, tp } = useI18n();
  return (
    <section className="panel" aria-label={t("speaking.takes.region")}>
      <h3>{t("speaking.takes.heading")}</h3>
      <div className="view-tabs" role="group" aria-label={t("speaking.takes.choose")}>
        {view.takes.map((k) => (
          <button key={k.id} type="button" aria-pressed={k.id === take.id} onClick={() => onSelect(k.id)}>
            {t("speaking.takes.item", { n: k.number })}
          </button>
        ))}
      </div>
      {view.takes.length > 1 ? (
        <>
          <h4>{t("speaking.history.heading")}</h4>
          <p className="hint">{t("speaking.history.hint")}</p>
          <ol className="listening-list speaking-history" aria-label={t("speaking.history.heading")}>
            {view.takes.map((k) => {
              const versions = view.transcripts.filter((s) => s.take_id === k.id);
              const latest = versions[versions.length - 1];
              const report = attemptReport(view, k);
              const rating = report?.content?.task_fulfilment.rating;
              return (
                <li key={k.id} aria-current={k.id === take.id ? "true" : undefined}>
                  <button type="button" className="link-button" onClick={() => onSelect(k.id)}>
                    {t("speaking.history.takeN", { n: k.number })}
                  </button>{" "}
                  {k.state ? <span className="tag">{t(stateKey[k.state])}</span> : null}
                  <p className="hint">
                    {t("speaking.history.line", {
                      saved: when(k.created_at),
                      audio: t(sourceKey[k.audio_source]),
                      transcript: latest ? t("speaking.history.version", { version: latest.version, origin: t(originKey[latest.origin]) }) : t("speaking.history.none"),
                      feedback:
                        report && rating
                          ? tp("speaking.history.feedbackReady", report.content!.improvements.length, { rating: t(ratingKey[rating]) })
                          : t("speaking.history.none"),
                    })}
                  </p>
                </li>
              );
            })}
          </ol>
        </>
      ) : null}
    </section>
  );
}

// Reattach lets the learner give the page a take's audio again after a reload
// or a restore: only a file with the take's exact SHA-256 is kept, in memory.
function Reattach({ take, onReattach }: { take: SpeakingTake; onReattach: (a: LocalAudio) => void }) {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);
  const choose = async (file: File | undefined) => {
    setError(null);
    if (!file) return;
    try {
      const digest = await sha256Hex(file);
      if (digest !== take.audio_sha256) {
        setError(t("speaking.reattach.mismatch", { n: take.number }));
        return;
      }
      onReattach({
        blob: file,
        url: URL.createObjectURL(file),
        mime: take.audio_mime ?? file.type,
        durationMs: take.duration_ms ?? 0,
        sha256: digest,
        source: take.audio_source === "recording" ? "recording" : "file",
      });
    } catch (e) {
      setError(t("speaking.reattach.failed", { message: describe(e) }));
    }
  };
  const id = `speaking-reattach-${take.id}`;
  return (
    <div className="speaking-reattach">
      <label htmlFor={id}>{t("speaking.reattach.label")}</label>{" "}
      <input id={id} type="file" accept={take.audio_mime ?? "audio/*"} onChange={(e) => void choose(e.target.files?.[0])} />
      <p className="hint">{t("speaking.reattach.hint")}</p>
      {error ? (
        <div className="banner error" role="alert">
          {error}
        </div>
      ) : null}
    </div>
  );
}

type RequestState =
  | { status: "idle" }
  | { status: "confirming" }
  | { status: "sending" }
  | { status: "unknown"; key: string; confirm: boolean }
  | { status: "error"; message: string };

function TakeDetail({
  view,
  take,
  initialVersion,
  local,
  onReattach,
  onChanged,
  onOpenRecord,
  onRetry,
}: {
  view: SpeakingExerciseView;
  take: SpeakingTake;
  initialVersion?: number;
  local: LocalAudio | null;
  onReattach: (a: LocalAudio) => void;
  onChanged: () => void;
  onOpenRecord?: (entryId: number) => void;
  onRetry?: (points: RetryPoints) => void;
}) {
  const { t } = useI18n();
  const versions = view.transcripts.filter((s) => s.take_id === take.id);
  const latest = versions[versions.length - 1] ?? null;
  const [selected, setSelected] = useState<number | null>(initialVersion ?? null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const shown = versions.find((s) => s.version === selected) ?? latest;
  const machine = view.transcriptions.find((x) => x.take_id === take.id && x.status === "completed") ?? null;
  const hit = highlight && shown ? shown.text.indexOf(highlight) : -1;
  return (
    <section className="panel" aria-label={t("speaking.take.region", { n: take.number })}>
      <h3>{t("speaking.take.heading", { n: take.number })}</h3>
      {take.audio_source === "none" ? (
        <p className="hint">{t("speaking.take.typed")}</p>
      ) : (
        <>
          <p className="hint">
            {t(take.audio_source === "file" ? "speaking.take.metaFile" : "speaking.take.metaRecording", {
              duration: formatDuration(take.duration_ms ?? 0),
              size: formatBytes(take.audio_bytes ?? 0),
              type: take.audio_mime ?? "",
            })}
          </p>
          {local ? (
            <audio controls src={local.url} aria-label={t("speaking.take.playback", { n: take.number })} />
          ) : (
            <>
              <p className="hint">{t("speaking.take.audioGone")}</p>
              <Reattach take={take} onReattach={onReattach} />
            </>
          )}
        </>
      )}
      {take.audio_source !== "none" ? <TranscriptionSection view={view} take={take} local={local} confirmed={versions.length > 0} onChanged={onChanged} /> : null}
      {shown ? (
        <>
          <h4>{t("speaking.versions.heading")}</h4>
          <div className="view-tabs" role="group" aria-label={t("speaking.versions.choose", { n: take.number })}>
            {versions.map((s) => (
              <button key={s.id} type="button" aria-pressed={s.id === shown.id} onClick={() => { setSelected(s.version); setHighlight(null); }}>
                {t("speaking.versions.item", { version: s.version, origin: t(originKey[s.origin]) })}
              </button>
            ))}
          </div>
          <pre className="writing-draft" lang="fr" aria-label={t("speaking.versions.text", { n: take.number, version: shown.version })}>
            {hit >= 0 && highlight ? (
              <>
                {shown.text.slice(0, hit)}
                <mark>{highlight}</mark>
                {shown.text.slice(hit + highlight.length)}
              </>
            ) : (
              shown.text
            )}
          </pre>
          <p className="hint">{t("speaking.versions.words", { words: shown.word_count })}</p>
          <FeedbackSection view={view} take={take} transcript={shown} onChanged={onChanged} onHighlight={setHighlight} onOpenRecord={onOpenRecord} onRetry={onRetry} />
        </>
      ) : null}
      <TranscriptEditor key={`${take.id}-${latest?.id ?? 0}-${machine?.id ?? 0}`} view={view} take={take} latest={latest} machine={machine} onSaved={(n) => { setSelected(n); setHighlight(null); onChanged(); }} />
    </section>
  );
}

function TranscriptionSection({
  view,
  take,
  local,
  confirmed,
  onChanged,
}: {
  view: SpeakingExerciseView;
  take: SpeakingTake;
  local: LocalAudio | null;
  confirmed: boolean;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const [state, setState] = useState<RequestState>({ status: "idle" });
  const latestRequest: SpeakingRequest | undefined = view.transcription_requests.find((r) => r.take_id === take.id);
  const anyInProgress = view.transcription_requests.some((r) => r.state === "in_progress");
  const unknown = latestRequest?.state === "unknown";
  const results = view.transcriptions.filter((x) => x.take_id === take.id);
  const lastFailed = results[0]?.status === "failed" && !unknown ? results[0] : null;
  const machine = results.find((x) => x.status === "completed") ?? null;
  const provider = view.providers.transcription;
  const check = async (key: string, confirm: boolean) => {
    try {
      await api.getSpeakingTranscriptionRequest(key);
      setState({ status: "idle" });
      onChanged();
    } catch {
      setState({ status: "unknown", key, confirm });
    }
  };
  const send = async (key: string, confirm: boolean) => {
    if (!local) return;
    setState({ status: "sending" });
    try {
      await api.transcribeSpeakingTake(take.id, { audio_base64: await base64Of(local.blob), audio_mime: local.mime }, key, confirm);
      setState({ status: "idle" });
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && (e.status === 502 || e.status === 504 || e.status === 409)) {
        setState({ status: "idle" });
        onChanged();
        return;
      }
      if (e instanceof NetworkError || (e instanceof ApiError && e.status >= 500 && e.status !== 503)) {
        await check(key, confirm);
        return;
      }
      setState({ status: "error", message: t("speaking.transcribe.failed", { message: describe(e) }) });
    }
  };
  if (!provider.enabled) return <p className="hint">{t("speaking.transcribe.disabled")}</p>;
  return (
    <div className="speaking-transcribe" role="group" aria-label={t("speaking.transcribe.region", { n: take.number })}>
      {machine && !confirmed ? <p className="hint">{t("speaking.transcribe.have", { transcriber: machine.transcriber })}</p> : null}
      {lastFailed ? (
        <div className="banner error" role="status">
          {t("speaking.transcribe.lastFailed", { reason: t(failureKey[lastFailed.failure_code ?? "provider_unavailable"]) })}
        </div>
      ) : null}
      {unknown ? (
        <div className="banner info" role="status">
          {t("speaking.transcribe.outcomeUnknown")}
        </div>
      ) : null}
      {anyInProgress ? (
        <div className="banner info" role="status">
          {t("speaking.transcribe.inProgress")}{" "}
          <button type="button" className="ghost" onClick={onChanged}>
            {t("speaking.checkAgain")}
          </button>
        </div>
      ) : !local ? null : state.status === "confirming" ? (
        <div className="banner info" role="alertdialog" aria-label={t("speaking.transcribe.confirmRegion")}>
          <p>
            {t("speaking.transcribe.confirmText", {
              n: take.number,
              duration: formatDuration(take.duration_ms ?? local.durationMs),
              size: formatBytes(local.blob.size),
              type: take.audio_mime ?? local.mime,
              provider: provider.name ?? "",
            })}
          </p>
          <p className="hint">{t("speaking.transcribe.confirmPrivacy")}</p>
          <div className="actions">
            <button type="button" className="primary" onClick={() => send(randomOperationId(), unknown)}>
              {unknown ? t("speaking.transcribe.sendAgain") : t("speaking.transcribe.send")}
            </button>
            <button type="button" className="ghost" onClick={() => setState({ status: "idle" })}>
              {t("speaking.transcribe.cancel")}
            </button>
          </div>
        </div>
      ) : (
        <button type="button" className={machine ? "ghost" : "primary"} disabled={state.status === "sending"} onClick={() => setState({ status: "confirming" })}>
          {state.status === "sending" ? t("speaking.transcribe.sending") : unknown ? t("speaking.transcribe.retryUnknown") : t("speaking.transcribe.open", { n: take.number })}
        </button>
      )}
      {state.status === "unknown" ? (
        <div className="banner info" role="alert">
          {t("speaking.transcribe.lost")}{" "}
          <button type="button" className="ghost" onClick={() => check(state.key, state.confirm)}>
            {t("speaking.checkAgain")}
          </button>
          <button type="button" className="ghost" onClick={() => send(state.key, state.confirm)}>
            {t("speaking.sendSame")}
          </button>
        </div>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {state.message}
        </div>
      ) : null}
    </div>
  );
}

function TranscriptEditor({
  view,
  take,
  latest,
  machine,
  onSaved,
}: {
  view: SpeakingExerciseView;
  take: SpeakingTake;
  latest: SpeakingTranscript | null;
  machine: { id: number; text: string | null } | null;
  onSaved: (version: number) => void;
}) {
  const { t } = useI18n();
  const fromMachine = !latest && machine?.text ? machine : null;
  const [text, setText] = useState(latest?.text ?? fromMachine?.text ?? "");
  const [state, setState] = useState<{ status: "idle" | "saving" } | { status: "error"; message: string }>({ status: "idle" });
  const next = (latest?.version ?? 0) + 1;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setState({ status: "saving" });
    try {
      await api.confirmSpeakingTranscript(take.id, text, fromMachine ? fromMachine.id : null);
      onSaved(next);
    } catch (e) {
      const unchanged = e instanceof ApiError && (e.body as { code?: string } | undefined)?.code === "unchanged";
      setState({
        status: "error",
        message: unchanged ? t("speaking.editor.unchanged") : e instanceof NetworkError ? t("speaking.editor.unknown") : t("speaking.editor.failed", { message: describe(e) }),
      });
    }
  };
  const fieldId = `speaking-editor-${take.id}`;
  return (
    <form className="listening-add" aria-label={t("speaking.editor.region", { n: take.number })} onSubmit={submit}>
      <h4>{latest ? t("speaking.editor.correctHeading", { version: next }) : t("speaking.editor.firstHeading")}</h4>
      <p className="hint">
        {latest ? t("speaking.editor.correctHint", { version: latest.version }) : fromMachine ? t("speaking.editor.machineHint") : t("speaking.editor.typedHint")}
      </p>
      {!latest && !fromMachine && view.example_transcript ? (
        <div className="actions">
          <button type="button" className="ghost" onClick={() => setText(view.example_transcript ?? "")}>
            {t("speaking.editor.useExample")}
          </button>
        </div>
      ) : null}
      <label htmlFor={fieldId}>{t("speaking.editor.label", { n: take.number, version: next })}</label>
      <textarea id={fieldId} lang="fr" rows={6} value={text} required maxLength={view.limits.max_transcript_chars} onChange={(e) => setText(e.target.value)} />
      <p className="hint" role="status">
        {t("speaking.editor.count", { words: countWords(text) })}
      </p>
      {state.status === "error" ? (
        <div className="banner error" role="alert">
          {state.message}
        </div>
      ) : null}
      <div className="actions">
        <button type="submit" className="primary" disabled={state.status === "saving" || !text.trim()}>
          {t("speaking.editor.confirm", { version: next })}
        </button>
      </div>
    </form>
  );
}

function FeedbackSection({
  view,
  take,
  transcript,
  onChanged,
  onHighlight,
  onOpenRecord,
  onRetry,
}: {
  view: SpeakingExerciseView;
  take: SpeakingTake;
  transcript: SpeakingTranscript;
  onChanged: () => void;
  onHighlight: (quote: string | null) => void;
  onOpenRecord?: (entryId: number) => void;
  onRetry?: (points: RetryPoints) => void;
}) {
  const { t } = useI18n();
  const [state, setState] = useState<RequestState>({ status: "idle" });
  const reports = view.feedback.filter((f) => f.transcript_id === transcript.id);
  const sameTake = view.transcripts.filter((s) => s.take_id === take.id && s.id !== transcript.id).map((s) => s.id);
  const elsewhere = [...new Set(view.feedback.filter((f) => sameTake.includes(f.transcript_id) && f.status === "completed").map((f) => view.transcripts.find((s) => s.id === f.transcript_id)?.version))]
    .filter((n): n is number => n !== undefined)
    .sort((a, b) => a - b);
  const latestRequest = view.feedback_requests.find((r) => r.transcript_id === transcript.id);
  const anyInProgress = view.feedback_requests.some((r) => r.state === "in_progress");
  const unknown = latestRequest?.state === "unknown";
  const check = async (key: string, confirm: boolean) => {
    try {
      await api.getSpeakingFeedbackRequest(key);
      setState({ status: "idle" });
      onChanged();
    } catch {
      setState({ status: "unknown", key, confirm });
    }
  };
  const send = async (key: string, confirm: boolean) => {
    setState({ status: "sending" });
    try {
      await api.requestSpeakingFeedback(transcript.id, key, confirm);
      setState({ status: "idle" });
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && (e.status === 502 || e.status === 504 || e.status === 409)) {
        setState({ status: "idle" });
        onChanged();
        return;
      }
      if (e instanceof NetworkError || (e instanceof ApiError && e.status >= 500 && e.status !== 503)) {
        await check(key, confirm);
        return;
      }
      setState({ status: "error", message: t("speaking.feedback.failed", { message: describe(e) }) });
    }
  };
  const lastFailed = reports[0]?.status === "failed" && !unknown ? reports[0] : null;
  const completed = reports.find((f) => f.status === "completed") ?? null;
  return (
    <section className="library-section" aria-label={t("speaking.feedback.region", { n: take.number, version: transcript.version })}>
      <h4>{t("speaking.feedback.heading", { n: take.number, version: transcript.version })}</h4>
      {elsewhere.length > 0 ? <p className="hint">{t("speaking.feedback.elsewhere", { versions: elsewhere.map((n) => `v${n}`).join(", ") })}</p> : null}
      {!view.providers.feedback.enabled ? (
        <p className="hint">{t("speaking.feedback.disabled")}</p>
      ) : anyInProgress ? (
        <div className="banner info" role="status">
          {t("speaking.feedback.inProgress")}{" "}
          <button type="button" className="ghost" onClick={onChanged}>
            {t("speaking.checkAgain")}
          </button>
        </div>
      ) : (
        <>
          <p className="hint">{t("speaking.feedback.hint", { version: transcript.version, generator: view.providers.feedback.name ?? "" })}</p>
          {unknown ? (
            <div className="banner info" role="status">
              {t("speaking.feedback.outcomeUnknown")}
            </div>
          ) : null}
          {lastFailed ? (
            <div className="banner error" role="status">
              {t("speaking.feedback.lastFailed", { reason: t(failureKey[lastFailed.failure_code ?? "provider_unavailable"]) })}
            </div>
          ) : null}
          <button type="button" className={unknown ? "ghost" : "primary"} disabled={state.status === "sending"} onClick={() => send(randomOperationId(), unknown)}>
            {state.status === "sending"
              ? t("speaking.feedback.sending")
              : unknown
                ? t("speaking.feedback.retryUnknown")
                : t("speaking.feedback.button", { version: transcript.version })}
          </button>
        </>
      )}
      {state.status === "unknown" ? (
        <div className="banner info" role="alert">
          {t("speaking.feedback.lost")}{" "}
          <button type="button" className="ghost" onClick={() => check(state.key, state.confirm)}>
            {t("speaking.checkAgain")}
          </button>
          <button type="button" className="ghost" onClick={() => send(state.key, state.confirm)}>
            {t("speaking.sendSame")}
          </button>
        </div>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {state.message}
        </div>
      ) : null}
      {completed ? <Report view={view} take={take} transcript={transcript} report={completed} onHighlight={onHighlight} onOpenRecord={onOpenRecord} onRetry={onRetry} /> : null}
    </section>
  );
}

function Report({
  view,
  take,
  transcript,
  report,
  onHighlight,
  onOpenRecord,
  onRetry,
}: {
  view: SpeakingExerciseView;
  take: SpeakingTake;
  transcript: SpeakingTranscript;
  report: SpeakingFeedback;
  onHighlight: (quote: string | null) => void;
  onOpenRecord?: (entryId: number) => void;
  onRetry?: (points: RetryPoints) => void;
}) {
  const { t, tn } = useI18n();
  const c = report.content!;
  const all = c.improvements.map((k, i) => ({ k, i }));
  const grounded = all.filter(({ k }) => shownAsGrounded(transcript.text, k));
  const missing = all.filter(({ k }) => !shownAsGrounded(transcript.text, k));
  return (
    <div className="writing-report" role="group" aria-label={t("speaking.report.region", { n: take.number, version: transcript.version })}>
      <p className="hint">
        {tn("speaking.report.about", { n: <strong>{take.number}</strong>, version: <strong>{transcript.version}</strong>, generator: <code>{report.generator}</code> })}
      </p>
      <p className="hint">{t("speaking.report.textOnly")}</p>
      <p>
        <span className="label">{t("speaking.report.task")}</span> <span className="tag">{t(ratingKey[c.task_fulfilment.rating])}</span>{" "}
        <StoredText primary={c.task_fulfilment.comment_en} variants={{ en: c.task_fulfilment.comment_en, zh: c.task_fulfilment.comment_zh }} kind="explanation" />
      </p>
      <p>
        <span className="label">{t("speaking.report.clarity")}</span>{" "}
        <StoredText primary={c.clarity.comment_en} variants={{ en: c.clarity.comment_en, zh: c.clarity.comment_zh }} kind="explanation" />
      </p>
      {c.improvements.length === 0 ? <p className="hint">{t("speaking.report.none")}</p> : null}
      <ol className="listening-items">
        {grounded.map(({ k, i }) => (
          <ImprovementItem key={i} view={view} take={take} transcript={transcript} report={report} k={k} index={i} onHighlight={onHighlight} onOpenRecord={onOpenRecord} />
        ))}
      </ol>
      {missing.length > 0 ? (
        <section className="library-section" aria-label={t("speaking.report.missingRegion")}>
          <h4>{t("speaking.report.missingHeading")}</h4>
          <p className="hint">{t("speaking.report.missingHint")}</p>
          <ul className="listening-steps">
            {missing.map(({ k, i }) => (
              <li key={i}>
                <span lang="fr" className="french">
                  « {k.quote} »
                </span>{" "}
                — <StoredText primary={k.reason_en} variants={{ en: k.reason_en, zh: k.reason_zh }} kind="explanation" />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {onRetry && view.takes.length < view.limits.max_takes ? (
        <div className="actions">
          <button
            type="button"
            onClick={() => onRetry({ take: take.number, version: transcript.version, points: grounded.map(({ k }) => ({ quote: k.quote, category: k.category })) })}
          >
            {t("speaking.retry.button", { n: view.takes.length + 1 })}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function ImprovementItem({
  view,
  take,
  transcript,
  report,
  k,
  index,
  onHighlight,
  onOpenRecord,
}: {
  view: SpeakingExerciseView;
  take: SpeakingTake;
  transcript: SpeakingTranscript;
  report: SpeakingFeedback;
  k: SpeakingImprovement;
  index: number;
  onHighlight: (quote: string | null) => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [showSuggestion, setShowSuggestion] = useState(false);
  const [saving, setSaving] = useState(false);
  return (
    <li className="listening-item" value={index + 1} role="group" aria-label={t("speaking.improvement.region", { n: index + 1 })}>
      <p>
        <span lang="fr" className="french">
          « {k.quote} »
        </span>{" "}
        <span className="tag">{t(`writing.category.${k.category}` as MessageKey)}</span>{" "}
        {k.grounding === "located" ? (
          <button type="button" className="ghost" onClick={() => onHighlight(k.quote)}>
            {t("speaking.improvement.show", { version: transcript.version })}
          </button>
        ) : (
          <span className="hint">{t("speaking.improvement.ambiguous")}</span>
        )}
      </p>
      <p>
        <span className="label">{t("speaking.improvement.hint")}</span>{" "}
        <StoredText primary={k.hint_en} variants={{ en: k.hint_en, zh: k.hint_zh }} kind="explanation" />
      </p>
      {showSuggestion ? (
        <>
          <p>
            <span className="label">{t("speaking.improvement.suggestion")}</span>{" "}
            <span lang="fr" className="french">
              {k.suggestion}
            </span>
          </p>
          <p>
            <span className="label">{t("speaking.improvement.reason")}</span>{" "}
            <StoredText primary={k.reason_en} variants={{ en: k.reason_en, zh: k.reason_zh }} kind="explanation" />
          </p>
        </>
      ) : null}
      <div className="actions">
        {!showSuggestion ? (
          <button type="button" onClick={() => setShowSuggestion(true)}>
            {t("speaking.improvement.reveal")}
          </button>
        ) : null}
        {!saving ? (
          <button type="button" className="ghost" onClick={() => setSaving(true)}>
            {t("speaking.capture.open")}
          </button>
        ) : null}
      </div>
      {saving ? (
        <CaptureMistake view={view} take={take} transcript={transcript} report={report} k={k} index={index} onCancel={() => setSaving(false)} onOpenRecord={onOpenRecord} />
      ) : null}
    </li>
  );
}

// mistakeContext links the record back to the exercise, the take and the exact
// transcript version the feedback was about.
export function mistakeContext(view: SpeakingExerciseView, take: SpeakingTake, transcript: SpeakingTranscript, report: SpeakingFeedback, k: SpeakingImprovement): string {
  return [
    `Speaking exercise #${view.exercise.id}: ${view.exercise.title} (authored prompt ${view.exercise.prompt_id})`,
    `Take ${take.number}, transcript version ${transcript.version} (${transcript.origin}), feedback #${report.id} (${report.generator})`,
    `Category: ${k.category}`,
    `Hint: ${k.hint_en}`,
    `Suggested wording: ${k.suggestion}`,
    "Practice feedback on a confirmed transcript: not an exam score and not a pronunciation judgment.",
  ].join("\n");
}

// mistakeInput is the record itself: what the learner said, how they would
// say it now, and the stored explanation (both languages, as stored).
export function mistakeInput(k: SpeakingImprovement, better: string): string {
  return [`« ${k.quote} » → « ${better.trim()} »`, k.reason_en, k.reason_zh].join("\n");
}

type CaptureState = { status: "editing" | "saving" } | { status: "saved"; entryId: number; created: boolean; duplicate?: boolean } | { status: "unknown" } | { status: "error"; message: string };

function CaptureMistake({
  view,
  take,
  transcript,
  report,
  k,
  index,
  onCancel,
  onOpenRecord,
}: {
  view: SpeakingExerciseView;
  take: SpeakingTake;
  transcript: SpeakingTranscript;
  report: SpeakingFeedback;
  k: SpeakingImprovement;
  index: number;
  onCancel: () => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [better, setBetter] = useState("");
  const [captureId] = useState(() => `speaking-${view.exercise.id}-${transcript.id}-${report.id}-${index + 1}-${randomOperationId()}`);
  const [state, setState] = useState<CaptureState>({ status: "editing" });
  const context = mistakeContext(view, take, transcript, report, k);
  const input = mistakeInput(k, better);
  const send = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!better.trim()) return;
    setState({ status: "saving" });
    try {
      const r = await api.importCapture(
        JSON.stringify({ schema_version: "learning_capture_v1", capture_id: captureId, source: "manual", original_input: input, original_context: context, source_ref: sourceRef("speaking_improvement", report.id, index) }),
      );
      setState({ status: "saved", entryId: r.entry_id, created: r.created });
    } catch (e) {
      const dup = alreadySaved(e);
      if (dup !== null) setState({ status: "saved", entryId: dup, created: false, duplicate: true });
      else setState(e instanceof NetworkError ? { status: "unknown" } : { status: "error", message: describe(e) });
    }
  };
  if (state.status === "saved")
    return (
      <div className="banner success" role="status">
        {t(state.duplicate ? "notebook.save.duplicate" : state.created ? "speaking.capture.saved" : "speaking.capture.replayed", { id: state.entryId })}{" "}
        {onOpenRecord ? (
          <button type="button" className="ghost" onClick={() => onOpenRecord(state.entryId)}>
            {t("speaking.capture.openRecord", { id: state.entryId })}
          </button>
        ) : null}
      </div>
    );
  const fieldId = `speaking-capture-${report.id}-${index}`;
  return (
    <form className="listening-save" aria-label={t("speaking.capture.region", { n: index + 1 })} onSubmit={send}>
      <p>
        <span className="label">{t("speaking.capture.original")}</span>{" "}
        <span lang="fr" className="french">
          « {k.quote} »
        </span>
      </p>
      <label htmlFor={fieldId}>{t("speaking.capture.better")}</label>
      <input id={fieldId} type="text" lang="fr" value={better} required onChange={(e) => setBetter(e.target.value)} disabled={state.status === "saving"} />
      <p className="label">{t("speaking.capture.attached")}</p>
      <pre className="listening-context" lang="fr">
        {context}
      </pre>
      <p className="hint">{t("speaking.capture.hint")}</p>
      <p className="hint">{t("notebook.save.linked")}</p>
      {state.status === "unknown" ? (
        <div className="banner info" role="alert">
          {t("speaking.capture.unknown")}
        </div>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {t("speaking.capture.failed", { message: state.message })}
        </div>
      ) : null}
      <div className="actions">
        <button type="submit" className="primary" disabled={state.status === "saving" || !better.trim()}>
          {state.status === "unknown" ? t("speaking.capture.retrySame") : t("speaking.capture.confirm")}
        </button>
        <button type="button" className="ghost" onClick={onCancel} disabled={state.status === "saving"}>
          {t("speaking.capture.cancel")}
        </button>
      </div>
    </form>
  );
}

// CompareEvidence sets the two transcripts side by side on what is recorded
// about them: the take's recorded length (measured by the browser), the word
// count, and the latest completed feedback on that exact version (its task
// rating and how many points it raised). Nothing is computed into a score.
function CompareEvidence({
  view,
  older,
  newer,
  label,
}: {
  view: SpeakingExerciseView;
  older: SpeakingTranscript;
  newer: SpeakingTranscript;
  label: (s: SpeakingTranscript) => string;
}) {
  const { t, tp } = useI18n();
  if (older.id === newer.id) return null;
  const row = (s: SpeakingTranscript) => {
    const take = view.takes.find((k) => k.id === s.take_id);
    const fb = view.feedback.find((f) => f.transcript_id === s.id && f.status === "completed" && f.content);
    return {
      length: take?.duration_ms ? formatDuration(take.duration_ms) : t("speaking.compare.noAudio"),
      words: tp("speaking.compare.words", s.word_count),
      rating: fb?.content ? t(ratingKey[fb.content.task_fulfilment.rating]) : t("speaking.compare.noFeedback"),
      points: fb?.content ? tp("speaking.compare.points", fb.content.improvements.length) : "—",
    };
  };
  const [a, b] = [row(older), row(newer)];
  return (
    <table className="speaking-compare-evidence">
      <caption className="hint">{t("speaking.compare.evidenceCaption")}</caption>
      <thead>
        <tr>
          <th scope="col">{t("speaking.compare.evidenceWhat")}</th>
          <th scope="col">{label(older)}</th>
          <th scope="col">{label(newer)}</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <th scope="row">{t("speaking.compare.length")}</th>
          <td>{a.length}</td>
          <td>{b.length}</td>
        </tr>
        <tr>
          <th scope="row">{t("speaking.compare.wordCount")}</th>
          <td>{a.words}</td>
          <td>{b.words}</td>
        </tr>
        <tr>
          <th scope="row">{t("speaking.report.task")}</th>
          <td>{a.rating}</td>
          <td>{b.rating}</td>
        </tr>
        <tr>
          <th scope="row">{t("speaking.compare.pointsRaised")}</th>
          <td>{a.points}</td>
          <td>{b.points}</td>
        </tr>
      </tbody>
    </table>
  );
}

function ComparePanel({ view }: { view: SpeakingExerciseView }) {
  const { t } = useI18n();
  const number = (s: SpeakingTranscript) => view.takes.find((k) => k.id === s.take_id)?.number ?? 0;
  const all = view.transcripts;
  const latestOf = (takeId: number) => [...all].reverse().find((s) => s.take_id === takeId);
  const firstTake = view.takes[0];
  const lastTake = view.takes[view.takes.length - 1];
  const defaultA = (firstTake && latestOf(firstTake.id)) ?? all[0];
  const defaultB = (lastTake && latestOf(lastTake.id) !== defaultA ? latestOf(lastTake.id) : all[all.length - 1]) ?? all[all.length - 1];
  const [a, setA] = useState<number | null>(null);
  const [b, setB] = useState<number | null>(null);
  const first = all.find((s) => s.id === a) ?? defaultA;
  const second = all.find((s) => s.id === b) ?? defaultB;
  // Always from the earlier transcript (take, then version) to the later one.
  const order = (s: SpeakingTranscript) => number(s) * 1000 + s.version;
  const [older, newer] = first && second && order(first) > order(second) ? [second, first] : [first, second];
  const parts = useMemo(() => (older && newer ? diffWords(older.text, newer.text) : []), [older, newer]);
  if (all.length < 2 || !older || !newer) return null;
  const label = (s: SpeakingTranscript) => t("speaking.compare.option", { n: number(s), version: s.version });
  return (
    <section className="panel" aria-label={t("speaking.compare.region")}>
      <h3>{t("speaking.compare.heading", { a: label(older), b: label(newer) })}</h3>
      <p className="hint">{t("speaking.compare.hint")}</p>
      <label htmlFor="speaking-compare-a">{t("speaking.compare.first")}</label>{" "}
      <select id="speaking-compare-a" value={first?.id} onChange={(e) => setA(Number(e.target.value))}>
        {all.map((s) => (
          <option key={s.id} value={s.id}>
            {label(s)}
          </option>
        ))}
      </select>{" "}
      <label htmlFor="speaking-compare-b">{t("speaking.compare.second")}</label>{" "}
      <select id="speaking-compare-b" value={second?.id} onChange={(e) => setB(Number(e.target.value))}>
        {all.map((s) => (
          <option key={s.id} value={s.id}>
            {label(s)}
          </option>
        ))}
      </select>
      <CompareEvidence view={view} older={older} newer={newer} label={label} />
      <p className="hint">{t("speaking.compare.legend")}</p>
      {older.id === newer.id ? (
        <p className="hint">{t("speaking.compare.same")}</p>
      ) : (
        <pre className="writing-draft writing-diff" lang="fr" aria-label={t("speaking.compare.diff")}>
          {parts.map((p, i) => (p.op === "same" ? <span key={i}>{p.text}</span> : p.op === "del" ? <del key={i}>{p.text}</del> : <ins key={i}>{p.text}</ins>))}
        </pre>
      )}
    </section>
  );
}
