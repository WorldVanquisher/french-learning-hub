import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { StoredText } from "../components/ExplanationText";
import { useI18n, type MessageKey } from "../i18n";
import type {
  SpeakingExerciseSummary,
  SpeakingExerciseView,
  SpeakingFeedback,
  SpeakingImprovement,
  SpeakingPrompts,
  SpeakingRequest,
  SpeakingTake,
  SpeakingTranscript,
} from "../types/speaking";
import { randomOperationId } from "./annotationOperation";
import { countWords, diffWords } from "./Writing";
import {
  base64Of,
  canonicalAudioType,
  classifyRecordingError,
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

export function Speaking({ onOpenRecord }: { onOpenRecord?: (entryId: number) => void } = {}) {
  const [screen, setScreen] = useState<{ kind: "list" } | { kind: "exercise"; id: number }>({ kind: "list" });
  const [epoch, setEpoch] = useState(0);
  // Takes' audio lives here, in memory, while Speaking is mounted. It is never
  // written to the server or to browser storage.
  const [audio, setAudio] = useState<Map<number, LocalAudio>>(() => new Map());
  const keep = (takeId: number, a: LocalAudio) => setAudio((m) => new Map(m).set(takeId, a));
  return (
    <main className="writing speaking">
      {screen.kind === "list" ? (
        <ExerciseList epoch={epoch} onOpen={(id) => setScreen({ kind: "exercise", id })} />
      ) : (
        <ExerciseScreen
          key={screen.id}
          id={screen.id}
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

function ExerciseList({ epoch, onOpen }: { epoch: number; onOpen: (id: number) => void }) {
  const { t, tp } = useI18n();
  const [retry, setRetry] = useState(0);
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
                  <button type="button" className="ghost" onClick={() => onOpen(p.started_exercise_id!)}>
                    {t("speaking.prompts.open")}
                  </button>
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
  audio,
  keep,
  onBack,
  onOpenRecord,
}: {
  id: number;
  audio: Map<number, LocalAudio>;
  keep: (takeId: number, a: LocalAudio) => void;
  onBack: () => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [epoch, setEpoch] = useState(0);
  const view = useLoad<SpeakingExerciseView>(String(id), () => api.getSpeakingExercise(id), epoch);
  const [selectedTake, setSelectedTake] = useState<number | null>(null);
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
        <p className="hint">{t("speaking.practiceNotice")}</p>
      </section>
      <RecordPanel
        view={v}
        onSaved={(takeId, local) => {
          if (local) keep(takeId, local);
          setSelectedTake(takeId);
          reload();
        }}
      />
      {take ? (
        <>
          <TakesPanel view={v} take={take} onSelect={setSelectedTake} />
          <TakeDetail key={take.id} view={v} take={take} local={audio.get(take.id) ?? null} onChanged={reload} onOpenRecord={onOpenRecord} />
          <ComparePanel view={v} />
        </>
      ) : null}
    </div>
  );
}

type RecordState =
  | { status: "idle" }
  | { status: "asking" }
  | { status: "recording"; elapsed: number }
  | { status: "recorded"; local: LocalAudio }
  | { status: "saving"; local: LocalAudio | null }
  | { status: "refused"; kind: RecordingError }
  | { status: "error"; message: string };

function RecordPanel({ view, onSaved }: { view: SpeakingExerciseView; onSaved: (takeId: number, local: LocalAudio | null) => void }) {
  const { t } = useI18n();
  const support = useMemo(() => recordingSupport(), []);
  const [state, setState] = useState<RecordState>({ status: "idle" });
  const active = useRef<ActiveRecording | null>(null);
  const limits = view.limits;
  const next = view.takes.length + 1;
  useEffect(
    () => () => {
      active.current?.stop();
    },
    [],
  );
  const record = async () => {
    setState({ status: "asking" });
    let rec: ActiveRecording;
    try {
      rec = await startRecording(limits.max_duration_ms, (elapsed) => setState({ status: "recording", elapsed }));
    } catch (e) {
      setState({ status: "refused", kind: classifyRecordingError(e) });
      return;
    }
    active.current = rec;
    setState({ status: "recording", elapsed: 0 });
    try {
      const r = await rec.done;
      active.current = null;
      setState({
        status: "recorded",
        local: { blob: r.blob, url: URL.createObjectURL(r.blob), mime: r.mime, durationMs: r.durationMs, sha256: await sha256Hex(r.blob), source: "recording" },
      });
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
    setState({ status: "recorded", local: { blob: file, url: URL.createObjectURL(file), mime: file.type, durationMs: ms, sha256: await sha256Hex(file), source: "file" } });
  };
  const save = async (local: LocalAudio | null) => {
    setState({ status: "saving", local });
    try {
      const accepted = local ? canonicalAudioType(local.mime) : null;
      const body =
        local && accepted
          ? { audio_source: local.source, audio_mime: local.mime, audio_bytes: local.blob.size, audio_sha256: local.sha256, duration_ms: local.durationMs }
          : { audio_source: "none" as const };
      const res = await api.addSpeakingTake(view.exercise.id, body);
      const saved = res.takes[res.takes.length - 1];
      onSaved(saved.id, local);
      setState({ status: "idle" });
    } catch (e) {
      setState({ status: "error", message: e instanceof NetworkError ? t("speaking.record.saveUnknown") : t("speaking.record.saveFailed", { message: describe(e) }) });
    }
  };
  const discard = () => {
    if (state.status === "recorded") URL.revokeObjectURL(state.local.url);
    setState({ status: "idle" });
  };
  const local = state.status === "recorded" ? state.local : null;
  return (
    <section className="panel" aria-label={t("speaking.record.region")}>
      <h3>{t("speaking.record.heading", { n: next })}</h3>
      <p className="hint">{t("speaking.record.privacy")}</p>
      {support === "unsupported" ? (
        <div className="banner info" role="status">
          {t("speaking.record.unsupported")}
        </div>
      ) : null}
      {state.status === "refused" ? (
        <div className="banner error" role="alert">
          {t(state.kind === "denied" ? "speaking.record.denied" : state.kind === "no_device" ? "speaking.record.noDevice" : "speaking.record.failed")}
        </div>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {state.message}
        </div>
      ) : null}
      {state.status === "recording" ? (
        <div className="actions">
          <span className="tag" role="status">
            {t("speaking.record.recording", { elapsed: formatDuration(state.elapsed), max: formatDuration(limits.max_duration_ms) })}
          </span>
          <button type="button" className="primary" onClick={() => active.current?.stop()}>
            {t("speaking.record.stop")}
          </button>
        </div>
      ) : local ? (
        <div className="speaking-local" role="group" aria-label={t("speaking.record.previewRegion")}>
          <audio controls src={local.url} aria-label={t("speaking.record.playback")} />
          <p className="hint">
            {t("speaking.record.previewMeta", { duration: formatDuration(local.durationMs), size: formatBytes(local.blob.size), type: local.mime || "?" })}
          </p>
          {!canonicalAudioType(local.mime) ? <p className="hint">{t("speaking.record.notTranscribable")}</p> : null}
          <p className="hint">{t("speaking.record.notSent")}</p>
          <div className="actions">
            <button type="button" className="primary" onClick={() => save(local)}>
              {t("speaking.record.use", { n: next })}
            </button>
            <button type="button" className="ghost" onClick={discard}>
              {t("speaking.record.discard")}
            </button>
          </div>
        </div>
      ) : (
        <div className="actions">
          {support === "supported" ? (
            <button type="button" className="primary" disabled={state.status === "asking" || state.status === "saving"} onClick={record}>
              {state.status === "asking" ? t("speaking.record.asking") : t("speaking.record.start")}
            </button>
          ) : null}
          <label className="ghost speaking-file">
            {t("speaking.record.file")}{" "}
            <input type="file" accept={limits.accepted_types.join(",")} disabled={state.status === "saving"} onChange={(e) => pickFile(e.target.files?.[0])} />
          </label>
          <button type="button" className="ghost" disabled={state.status === "saving"} onClick={() => save(null)}>
            {t("speaking.record.typeInstead")}
          </button>
        </div>
      )}
      <p className="hint">{t("speaking.record.limits", { max: formatDuration(limits.max_duration_ms), size: formatBytes(limits.max_audio_bytes) })}</p>
    </section>
  );
}

function TakesPanel({ view, take, onSelect }: { view: SpeakingExerciseView; take: SpeakingTake; onSelect: (id: number) => void }) {
  const { t } = useI18n();
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
    </section>
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
  local,
  onChanged,
  onOpenRecord,
}: {
  view: SpeakingExerciseView;
  take: SpeakingTake;
  local: LocalAudio | null;
  onChanged: () => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const versions = view.transcripts.filter((s) => s.take_id === take.id);
  const latest = versions[versions.length - 1] ?? null;
  const [selected, setSelected] = useState<number | null>(null);
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
            <p className="hint">{t("speaking.take.audioGone")}</p>
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
          <FeedbackSection view={view} take={take} transcript={shown} onChanged={onChanged} onHighlight={setHighlight} onOpenRecord={onOpenRecord} />
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
          <button type="button" className="ghost" onClick={() => setText(view.example_transcript)}>
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
}: {
  view: SpeakingExerciseView;
  take: SpeakingTake;
  transcript: SpeakingTranscript;
  onChanged: () => void;
  onHighlight: (quote: string | null) => void;
  onOpenRecord?: (entryId: number) => void;
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
      {completed ? <Report view={view} take={take} transcript={transcript} report={completed} onHighlight={onHighlight} onOpenRecord={onOpenRecord} /> : null}
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
}: {
  view: SpeakingExerciseView;
  take: SpeakingTake;
  transcript: SpeakingTranscript;
  report: SpeakingFeedback;
  onHighlight: (quote: string | null) => void;
  onOpenRecord?: (entryId: number) => void;
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

type CaptureState = { status: "editing" | "saving" } | { status: "saved"; entryId: number; created: boolean } | { status: "unknown" } | { status: "error"; message: string };

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
        JSON.stringify({ schema_version: "learning_capture_v1", capture_id: captureId, source: "manual", original_input: input, original_context: context }),
      );
      setState({ status: "saved", entryId: r.entry_id, created: r.created });
    } catch (e) {
      setState(e instanceof NetworkError ? { status: "unknown" } : { status: "error", message: describe(e) });
    }
  };
  if (state.status === "saved")
    return (
      <div className="banner success" role="status">
        {t(state.created ? "speaking.capture.saved" : "speaking.capture.replayed", { id: state.entryId })}{" "}
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
