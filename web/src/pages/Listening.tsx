import { useEffect, useRef, useState, type FormEvent } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { StoredText } from "../components/ExplanationText";
import { useI18n, type MessageKey } from "../i18n";
import type {
  ListeningExercise,
  ListeningFailureCode,
  ListeningItem,
  ListeningItemKind,
  ListeningLesson,
  ListeningList,
  ListeningMaterial,
  ListeningTranscript,
  TranscriptSegment,
} from "../types/listening";
import { randomOperationId } from "./annotationOperation";

// Exam Listening Lesson v1 (private workbench only; never in the public demo).
//
// - Material: a YouTube link, a title and an optional learner-supplied French
//   transcript. The link is opened on YouTube; nothing is downloaded, scraped or
//   fetched, and opening it calls no provider.
// - Preparation is one explicit request to the opt-in provider. A failure is
//   shown as stored; the material and transcript are kept; nothing retries.
// - The exercise view hides the transcript, answers and notes until the learner
//   reveals them. Answers and self-checks stay in component state: never sent,
//   logged or stored, and there is no score or level.
// - A missed point becomes a normal learning record only through an explicit
//   "Save learning record", via the existing capture path (source "manual").

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
  return state.key === key && state.epoch === epoch ? state.load : { status: "loading" };
}

const kindKey: Record<ListeningItemKind, MessageKey> = {
  main_idea: "listening.kind.main_idea",
  detail: "listening.kind.detail",
  inference: "listening.kind.inference",
};
const failureKey: Record<ListeningFailureCode, MessageKey> = {
  provider_timeout: "listening.failure.provider_timeout",
  provider_unavailable: "listening.failure.provider_unavailable",
  invalid_output: "listening.failure.invalid_output",
};

// clock formats a source-supplied timestamp as m:ss or h:mm:ss.
export function clock(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

// videoAt links the standard YouTube player at a source-supplied time.
const videoAt = (m: ListeningMaterial, seconds: number | null) => (seconds === null ? m.source_url : `${m.source_url}&t=${seconds}s`);

function VideoLink({ material, seconds = null, label }: { material: ListeningMaterial; seconds?: number | null; label: string }) {
  return (
    <a href={videoAt(material, seconds)} target="_blank" rel="noopener noreferrer">
      {label}
    </a>
  );
}

export function Listening({ onOpenRecord }: { onOpenRecord?: (entryId: number) => void } = {}) {
  const [screen, setScreen] = useState<{ kind: "list" } | { kind: "lesson"; id: number }>({ kind: "list" });
  const [epoch, setEpoch] = useState(0);
  return (
    <main className="listening">
      {screen.kind === "list" ? (
        <MaterialList
          epoch={epoch}
          onOpen={(id) => setScreen({ kind: "lesson", id })}
          onSaved={(id) => setScreen({ kind: "lesson", id })}
        />
      ) : (
        <LessonScreen
          key={screen.id}
          id={screen.id}
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

function MaterialList({ epoch, onOpen, onSaved }: { epoch: number; onOpen: (id: number) => void; onSaved: (id: number) => void }) {
  const { t } = useI18n();
  const [retry, setRetry] = useState(0);
  const list = useLoad<ListeningList>("list", () => api.listListening(), epoch * 1000 + retry);
  return (
    <>
      <AddMaterialForm onSaved={onSaved} />
      <section className="panel" aria-label={t("listening.list.region")}>
        <h2>{t("listening.list.heading")}</h2>
        {list.status === "loading" ? (
          <p className="hint" role="status">{t("listening.list.loading")}</p>
        ) : list.status === "error" ? (
          <div className="banner error" role="alert">
            {t("listening.list.failed", { message: list.message })}{" "}
            <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
              {t("common.retry")}
            </button>
          </div>
        ) : list.data.materials.length === 0 ? (
          <p className="empty">{t("listening.list.empty")}</p>
        ) : (
          <ul className="listening-list">
            {list.data.materials.map((row) => (
              <li key={row.material.id}>
                <button type="button" className="link-button" onClick={() => onOpen(row.material.id)}>
                  {row.material.title}
                </button>{" "}
                <span className="tag">
                  {row.transcript_version === null
                    ? t("listening.state.waiting")
                    : row.latest_exercise?.status === "completed"
                      ? t("listening.state.ready")
                      : row.latest_exercise?.status === "failed"
                        ? t("listening.state.failed")
                        : t("listening.state.prepare")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function AddMaterialForm({ onSaved }: { onSaved: (id: number) => void }) {
  const { t } = useI18n();
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [transcript, setTranscript] = useState("");
  const [state, setState] = useState<{ status: "idle" | "saving" } | { status: "error"; message: string }>({ status: "idle" });
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setState({ status: "saving" });
    try {
      const lesson = await api.createListening({ source_url: url, title, transcript });
      onSaved(lesson.material.id);
    } catch (e) {
      setState({
        status: "error",
        message: e instanceof NetworkError ? t("listening.add.unknown") : t("listening.add.failed", { message: describe(e) }),
      });
    }
  };
  return (
    <form className="panel listening-add" aria-label={t("listening.add.region")} onSubmit={submit}>
      <h2>{t("listening.add.heading")}</h2>
      <p className="hint">{t("listening.add.hint")}</p>
      <label htmlFor="listening-url">{t("listening.add.url")}</label>
      <input id="listening-url" type="url" value={url} required onChange={(e) => setUrl(e.target.value)} placeholder="https://www.youtube.com/watch?v=…" />
      <label htmlFor="listening-title">{t("listening.add.title")}</label>
      <input id="listening-title" type="text" value={title} required maxLength={200} onChange={(e) => setTitle(e.target.value)} />
      <label htmlFor="listening-transcript">{t("listening.add.transcript")}</label>
      <textarea id="listening-transcript" lang="fr" rows={8} value={transcript} onChange={(e) => setTranscript(e.target.value)} />
      <p className="hint">{t("listening.transcript.format")}</p>
      {state.status === "error" ? (
        <div className="banner error" role="alert">
          {state.message}
        </div>
      ) : null}
      <div className="actions">
        <button type="submit" className="primary" disabled={state.status === "saving"}>
          {t("listening.add.save")}
        </button>
      </div>
    </form>
  );
}

function LessonScreen({ id, onBack, onOpenRecord }: { id: number; onBack: () => void; onOpenRecord?: (entryId: number) => void }) {
  const { t } = useI18n();
  const [epoch, setEpoch] = useState(0);
  const lesson = useLoad<ListeningLesson>(String(id), () => api.getListening(id), epoch);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), [lesson.status]);
  const back = (
    <button type="button" className="ghost" onClick={onBack}>
      {t("listening.back")}
    </button>
  );
  if (lesson.status !== "ready")
    return (
      <section className="panel" aria-label={t("listening.lesson.region")}>
        <h2 ref={headingRef} tabIndex={-1}>
          {t("listening.lesson.heading", { id })}
        </h2>
        {back}
        {lesson.status === "loading" ? (
          <p className="hint" role="status">{t("listening.lesson.loading")}</p>
        ) : (
          <div className="banner error" role="alert">
            {t("listening.lesson.failed", { message: lesson.message })}{" "}
            <button type="button" className="ghost" onClick={() => setEpoch((n) => n + 1)}>
              {t("common.retry")}
            </button>
          </div>
        )}
      </section>
    );
  const { material, transcript, exercises, generation } = lesson.data;
  const current = transcript ? exercises.find((e) => e.transcript_id === transcript.id && e.status === "completed") ?? null : null;
  const latest = exercises[0] ?? null;
  const lastFailed = latest && latest.status === "failed" && transcript && latest.transcript_id === transcript.id ? latest : null;
  return (
    <div>
      <section className="panel" aria-label={t("listening.lesson.region")}>
        <h2 ref={headingRef} tabIndex={-1} className="library-title">
          {material.title}
        </h2>
        <div className="actions">
          {back}
          <VideoLink material={material} label={t("listening.video.open")} />
        </div>
        <p className="hint">{t("listening.video.hint")}</p>
        <p className="hint">
          {transcript
            ? t(transcript.has_timestamps ? "listening.transcript.summaryTimed" : "listening.transcript.summary", {
                version: transcript.version,
                count: transcript.segments.length,
              })
            : t("listening.transcript.none")}
        </p>
      </section>

      {!transcript ? (
        <AddTranscriptForm id={id} onSaved={() => setEpoch((n) => n + 1)} />
      ) : (
        <>
          {lastFailed && !current ? (
            <div className="banner error" role="status">
              {t("listening.prepare.lastFailed", { reason: t(failureKey[lastFailed.failure_code ?? "provider_unavailable"]) })}
            </div>
          ) : null}
          {current ? (
            <ExerciseView key={current.id} material={material} transcript={transcript} exercise={current} onOpenRecord={onOpenRecord} />
          ) : (
            <PrepareSection id={id} enabled={generation.enabled} generator={generation.generator} onDone={() => setEpoch((n) => n + 1)} />
          )}
        </>
      )}
    </div>
  );
}

function AddTranscriptForm({ id, onSaved }: { id: number; onSaved: () => void }) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.addListeningTranscript(id, text);
      onSaved();
    } catch (e) {
      setError(e instanceof NetworkError ? t("listening.add.unknown") : t("listening.transcript.failed", { message: describe(e) }));
      setSaving(false);
    }
  };
  return (
    <form className="panel" aria-label={t("listening.waiting.region")} onSubmit={submit}>
      <h3>{t("listening.waiting.heading")}</h3>
      <p className="hint">{t("listening.waiting.hint")}</p>
      <label htmlFor={`listening-add-transcript-${id}`}>{t("listening.add.transcript")}</label>
      <textarea id={`listening-add-transcript-${id}`} lang="fr" rows={8} value={text} required onChange={(e) => setText(e.target.value)} />
      <p className="hint">{t("listening.transcript.format")}</p>
      {error ? (
        <div className="banner error" role="alert">
          {error}
        </div>
      ) : null}
      <div className="actions">
        <button type="submit" className="primary" disabled={saving}>
          {t("listening.transcript.save")}
        </button>
      </div>
    </form>
  );
}

function PrepareSection({ id, enabled, generator, onDone }: { id: number; enabled: boolean; generator: string | null; onDone: () => void }) {
  const { t } = useI18n();
  const [state, setState] = useState<{ status: "idle" | "sending" } | { status: "error"; message: string }>({ status: "idle" });
  const prepare = async () => {
    setState({ status: "sending" });
    try {
      await api.prepareListeningExercise(id);
      onDone();
    } catch (e) {
      if (e instanceof ApiError && (e.status === 502 || e.status === 504)) {
        onDone(); // the failure is stored; the lesson re-read shows it
        return;
      }
      setState({
        status: "error",
        message: e instanceof NetworkError ? t("listening.prepare.unknown") : t("listening.prepare.failed", { message: describe(e) }),
      });
    }
  };
  return (
    <section className="panel" aria-label={t("listening.prepare.region")}>
      <h3>{t("listening.prepare.heading")}</h3>
      {enabled ? (
        <>
          <p className="hint">{t("listening.prepare.hint", { generator: generator ?? "" })}</p>
          <button type="button" className="primary" disabled={state.status === "sending"} onClick={prepare}>
            {state.status === "sending" ? t("listening.prepare.sending") : t("listening.prepare.button")}
          </button>
        </>
      ) : (
        <p className="hint">{t("listening.prepare.disabled")}</p>
      )}
      {state.status === "error" ? (
        <div className="banner error" role="alert">
          {state.message}
        </div>
      ) : null}
    </section>
  );
}

type SelfCheck = "got" | "missed";

function ExerciseView({
  material,
  transcript,
  exercise,
  onOpenRecord,
}: {
  material: ListeningMaterial;
  transcript: ListeningTranscript;
  exercise: ListeningExercise;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t, tn } = useI18n();
  const content = exercise.content!;
  const [answers, setAnswers] = useState<string[]>(() => content.items.map(() => ""));
  const [revealed, setRevealed] = useState(false);
  const [checks, setChecks] = useState<Record<number, SelfCheck>>({});
  const [showTranscript, setShowTranscript] = useState(false);
  const segment = (n: number) => transcript.segments.find((s) => s.index === n);
  return (
    <section className="panel listening-exercise" aria-label={t("listening.exercise.region")}>
      <h3>{t("listening.exercise.heading")}</h3>
      <p className="hint">{t(revealed ? "listening.exercise.revealedHint" : "listening.exercise.hint")}</p>
      <ol className="listening-items">
        {content.items.map((item, i) => (
          <li key={i} className="listening-item">
            <p className="label">{t(kindKey[item.kind])}</p>
            <p lang="fr" className="french">
              {item.question}
            </p>
            <label htmlFor={`listening-answer-${exercise.id}-${i}`}>{t("listening.answer.label", { n: i + 1 })}</label>
            <textarea
              id={`listening-answer-${exercise.id}-${i}`}
              rows={2}
              autoComplete="off"
              value={answers[i]}
              onChange={(e) => setAnswers((prev) => prev.map((a, j) => (j === i ? e.target.value : a)))}
            />
            {revealed ? (
              <Revealed
                material={material}
                exercise={exercise}
                item={item}
                index={i}
                segments={item.segments.map(segment).filter((s): s is TranscriptSegment => !!s)}
                check={checks[i]}
                onCheck={(c) => setChecks((prev) => ({ ...prev, [i]: c }))}
                onOpenRecord={onOpenRecord}
              />
            ) : null}
          </li>
        ))}
      </ol>
      {!revealed ? (
        <div className="actions">
          <button type="button" className="primary" onClick={() => setRevealed(true)}>
            {t("listening.reveal")}
          </button>
        </div>
      ) : (
        <>
          <section className="library-section" aria-labelledby={`listening-notes-${exercise.id}`}>
            <h4 id={`listening-notes-${exercise.id}`}>{t("listening.notes.heading")}</h4>
            <ul className="listening-notes">
              {content.annotations.map((a, i) => (
                <li key={i}>
                  <span className="tag">{t(a.kind === "grammar" ? "listening.notes.grammar" : "listening.notes.vocabulary")}</span>{" "}
                  <span lang="fr" className="french">
                    « {a.excerpt} »
                  </span>{" "}
                  <span className="hint">{t("listening.segmentRef", { n: a.segment })}</span>
                  <div>
                    <StoredText primary={a.note_en} variants={{ en: a.note_en, zh: a.note_zh }} kind="explanation" />
                  </div>
                </li>
              ))}
            </ul>
          </section>
          <div className="actions">
            <button type="button" className="ghost" aria-expanded={showTranscript} onClick={() => setShowTranscript((s) => !s)}>
              {t(showTranscript ? "listening.transcript.hide" : "listening.transcript.show")}
            </button>
          </div>
          {showTranscript ? <TranscriptView material={material} transcript={transcript} /> : null}
          <p className="hint">{tn("listening.exercise.provenance", { generator: <code>{exercise.generator}</code> })}</p>
        </>
      )}
    </section>
  );
}

function SegmentLine({ material, s }: { material: ListeningMaterial; s: TranscriptSegment }) {
  const { t } = useI18n();
  return (
    <p className="listening-segment">
      <span className="hint">
        {t("listening.segmentRef", { n: s.index })}
        {s.start_seconds !== null ? (
          <>
            {" · "}
            <VideoLink material={material} seconds={s.start_seconds} label={clock(s.start_seconds)} />
          </>
        ) : null}
      </span>{" "}
      <span lang="fr" className="french">
        {s.text}
      </span>
    </p>
  );
}

function TranscriptView({ material, transcript }: { material: ListeningMaterial; transcript: ListeningTranscript }) {
  const { t } = useI18n();
  return (
    <section className="source-view" aria-label={t("listening.transcript.region")}>
      {transcript.segments.map((s) => (
        <SegmentLine key={s.index} material={material} s={s} />
      ))}
    </section>
  );
}

function Revealed({
  material,
  exercise,
  item,
  index,
  segments,
  check,
  onCheck,
  onOpenRecord,
}: {
  material: ListeningMaterial;
  exercise: ListeningExercise;
  item: ListeningItem;
  index: number;
  segments: TranscriptSegment[];
  check: SelfCheck | undefined;
  onCheck: (c: SelfCheck) => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [saving, setSaving] = useState(false);
  return (
    <div className="listening-reveal" role="group" aria-label={t("listening.reveal.region", { n: index + 1 })}>
      <p>
        <span className="label">{t("listening.reveal.expected")}</span>{" "}
        <span lang="fr" className="french">
          {item.expected_answer}
        </span>
      </p>
      <p>
        <span className="label">{t("listening.reveal.why")}</span>{" "}
        <StoredText primary={item.rationale_en} variants={{ en: item.rationale_en, zh: item.rationale_zh }} kind="explanation" />
      </p>
      <p className="label">{t("listening.reveal.evidence")}</p>
      {segments.map((s) => (
        <SegmentLine key={s.index} material={material} s={s} />
      ))}
      <div className="actions" role="group" aria-label={t("listening.check.label", { n: index + 1 })}>
        <button type="button" aria-pressed={check === "got"} onClick={() => onCheck("got")}>
          {t("listening.check.got")}
        </button>
        <button type="button" aria-pressed={check === "missed"} onClick={() => onCheck("missed")}>
          {t("listening.check.missed")}
        </button>
        {!saving ? (
          <button type="button" className="ghost" onClick={() => setSaving(true)}>
            {t("listening.save.open")}
          </button>
        ) : null}
      </div>
      {saving ? (
        <SaveMissedPoint
          material={material}
          exercise={exercise}
          item={item}
          index={index}
          segments={segments}
          onCancel={() => setSaving(false)}
          onOpenRecord={onOpenRecord}
        />
      ) : null}
    </div>
  );
}

// missedPointContext is the source evidence attached to the learner's record:
// the lesson, the video link (at the cited time when the source supplied one),
// the question and the cited French excerpts, exactly as stored.
export function missedPointContext(material: ListeningMaterial, item: ListeningItem, segments: TranscriptSegment[]): string {
  const at = segments.find((s) => s.start_seconds !== null)?.start_seconds ?? null;
  const lines = [`Listening exercise: ${material.title}`, `Video: ${videoAt(material, at)}`, `Question (${item.kind}): ${item.question}`];
  for (const s of segments) {
    lines.push(`Excerpt (segment ${s.index}${s.start_seconds !== null ? `, ${clock(s.start_seconds)}` : ""}): « ${s.text} »`);
  }
  return lines.join("\n");
}

type SaveState =
  | { status: "editing" }
  | { status: "saving" }
  | { status: "saved"; entryId: number; created: boolean }
  | { status: "unknown" }
  | { status: "error"; message: string };

function SaveMissedPoint({
  material,
  exercise,
  item,
  index,
  segments,
  onCancel,
  onOpenRecord,
}: {
  material: ListeningMaterial;
  exercise: ListeningExercise;
  item: ListeningItem;
  index: number;
  segments: TranscriptSegment[];
  onCancel: () => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  // One capture ID per form: resending after a lost response replays the same
  // capture on the server instead of creating a second record.
  const [captureId] = useState(() => `listening-${material.id}-${exercise.id}-${index + 1}-${randomOperationId()}`);
  const [state, setState] = useState<SaveState>({ status: "editing" });
  const context = missedPointContext(material, item, segments);
  const send = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!text.trim()) return;
    setState({ status: "saving" });
    try {
      const result = await api.importCapture(
        JSON.stringify({
          schema_version: "learning_capture_v1",
          capture_id: captureId,
          source: "manual",
          original_input: text,
          original_context: context,
        }),
      );
      setState({ status: "saved", entryId: result.entry_id, created: result.created });
    } catch (e) {
      setState(e instanceof NetworkError ? { status: "unknown" } : { status: "error", message: describe(e) });
    }
  };
  const fieldId = `listening-missed-${exercise.id}-${index}`;
  if (state.status === "saved")
    return (
      <div className="banner success" role="status">
        {t(state.created ? "listening.save.saved" : "listening.save.replayed", { id: state.entryId })}{" "}
        {onOpenRecord ? (
          <button type="button" className="ghost" onClick={() => onOpenRecord(state.entryId)}>
            {t("listening.save.openRecord", { id: state.entryId })}
          </button>
        ) : null}
      </div>
    );
  return (
    <form className="listening-save" aria-label={t("listening.save.region", { n: index + 1 })} onSubmit={send}>
      <label htmlFor={fieldId}>{t("listening.save.label")}</label>
      <textarea id={fieldId} rows={3} value={text} required onChange={(e) => setText(e.target.value)} disabled={state.status === "saving"} />
      <p className="label">{t("listening.save.attached")}</p>
      <pre className="listening-context" lang="fr">
        {context}
      </pre>
      <p className="hint">{t("listening.save.hint")}</p>
      {state.status === "unknown" ? (
        <div className="banner info" role="alert">
          {t("listening.save.unknown")}
        </div>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {t("listening.save.failed", { message: state.message })}
        </div>
      ) : null}
      <div className="actions">
        <button type="submit" className="primary" disabled={state.status === "saving" || !text.trim()}>
          {state.status === "unknown" ? t("listening.save.retrySame") : t("listening.save.confirm")}
        </button>
        <button type="button" className="ghost" onClick={onCancel} disabled={state.status === "saving"}>
          {t("listening.save.cancel")}
        </button>
      </div>
    </form>
  );
}
