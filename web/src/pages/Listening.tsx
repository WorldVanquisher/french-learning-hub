import { useEffect, useRef, useState, type FormEvent } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { StoredText } from "../components/ExplanationText";
import { NotebookOrigin, notebookItemDomId, type NotebookTarget } from "../components/NotebookOrigin";
import { useI18n, type MessageKey } from "../i18n";
import type {
  ListeningDaily,
  ListeningExercise,
  ListeningFailureCode,
  ListeningItem,
  ListeningItemKind,
  ListeningLesson,
  ListeningList,
  ListeningMaterial,
  ListeningMaterialState,
  ListeningPreparation,
  ListeningQuestionField,
  ListeningScriptRevisionState,
  ListeningScriptRevisionView,
  ListeningScriptUpdatePreview,
  ListeningTranscript,
  TranscriptSegment,
} from "../types/listening";
import { randomOperationId } from "./annotationOperation";
import { alreadySaved, sourceRef } from "./notebookLink";
import { DailyPanel, NotificationsSection } from "./ListeningDaily";
import { NextScript, ScriptsPanel } from "./ListeningScripts";

// Exam Listening Lesson v1 (private workbench only; never in the public demo).
//
// - Material: a YouTube link, a title and an optional learner-supplied French
//   transcript. The link is opened on YouTube; nothing is downloaded, scraped or
//   fetched, and opening it calls no provider.
// - Preparation is one explicit request to the opt-in provider, under a key.
//   A failure is shown as stored; the material and transcript are kept; nothing
//   retries. After a lost response the key is looked up first; an unknown
//   outcome needs an acknowledged retry.
// - Daily Listening (ListeningDaily.tsx): "Pull now" and the last pull; pulled
//   videos wait here for the learner's transcript.
// - The exercise view hides the transcript, answers and notes until the learner
//   reveals them. Answers and self-checks stay in component state: never sent,
//   logged or stored, and there is no score or level.
// - A missed point becomes a normal learning record only through an explicit
//   "Save learning record", via the existing capture path (source "manual").
// - Workbook scripts (ListeningScripts.tsx) import as script-only lessons:
//   no link, video, audio or timestamp exists, so none is shown or attached.
//   Their authored questions may offer choices; the script can be shown to the
//   person reading it aloud, while answers and notes stay hidden until reveal.
//   Their exercise is fixed: the server never prepares a generated one.
// - After reveal, an answer overview puts each answer beside the reference
//   (a chosen option is compared exactly; a short answer is left to the
//   learner) with a link to the question. It is not a score and sends nothing.
// - Script revisions: when the server's pack corrects an imported script, the
//   lesson says so and stays as it is. "Review the changes" reads a preview;
//   only its confirm button writes, appending the next revision (resending the
//   same confirmation never adds a second one). Nothing updates on load. A
//   Mistake Notebook item saved from an earlier revision opens that revision.

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
const stateKey: Record<ListeningMaterialState, MessageKey> = {
  waiting_for_transcript: "listening.state.waiting",
  ready_to_prepare: "listening.state.prepare",
  in_progress: "listening.state.inProgress",
  prepared: "listening.state.ready",
  failed: "listening.state.failed",
  outcome_unknown: "listening.state.unknown",
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

// videoAt links the standard YouTube player at a source-supplied time. An
// authored script has no link, so it has no video position either.
const videoAt = (m: ListeningMaterial, seconds: number | null) =>
  m.source_url === null ? null : seconds === null ? m.source_url : `${m.source_url}&t=${seconds}s`;

const isScript = (m: ListeningMaterial) => m.source_kind === "authored_script";

function VideoLink({ material, seconds = null, label }: { material: ListeningMaterial; seconds?: number | null; label: string }) {
  const href = videoAt(material, seconds);
  if (href === null) return null;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {label}
    </a>
  );
}

export function Listening({
  onOpenRecord,
  openRequest,
}: { onOpenRecord?: (entryId: number) => void; openRequest?: { materialId: number; nonce: number; target?: NotebookTarget } | null } = {}) {
  const [screen, setScreen] = useState<{ kind: "list" } | { kind: "lesson"; id: number }>({ kind: "list" });
  // A Mistake Notebook link opens the lesson its item came from.
  useEffect(() => {
    if (openRequest) setScreen({ kind: "lesson", id: openRequest.materialId });
  }, [openRequest]);
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
          onOpenLesson={(next) => setScreen({ kind: "lesson", id: next })}
          target={openRequest && openRequest.materialId === screen.id ? openRequest.target ?? null : null}
        />
      )}
    </main>
  );
}

function MaterialList({ epoch, onOpen, onSaved }: { epoch: number; onOpen: (id: number) => void; onSaved: (id: number) => void }) {
  const { t } = useI18n();
  const [retry, setRetry] = useState(0);
  const [pulls, setPulls] = useState(0);
  const list = useLoad<ListeningList>("list", () => api.listListening(), epoch * 1000 + retry * 100 + pulls);
  const daily = useLoad<ListeningDaily>("daily", () => api.getListeningDaily(), epoch * 1000 + retry);
  return (
    <>
      {daily.status === "ready" ? (
        <DailyPanel daily={daily.data} onPulled={() => setPulls((n) => n + 1)} />
      ) : daily.status === "error" ? (
        <p className="hint" role="status">
          {t("listening.daily.statusFailed", { message: daily.message })}
        </p>
      ) : null}
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
                <span className="tag">{t(stateKey[row.state])}</span>
                {isScript(row.material) ? (
                  <>
                    {" "}
                    <span className="tag">{t("listening.source.scriptOnly")}</span>
                  </>
                ) : null}
                {row.in_playlist ? (
                  <>
                    {" "}
                    <span className="tag">{t("listening.state.fromPlaylist")}</span>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
      <ScriptsPanel epoch={epoch} onOpen={onOpen} />
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

function LessonScreen({
  id,
  onBack,
  onOpenRecord,
  onOpenLesson,
  target = null,
}: {
  id: number;
  onBack: () => void;
  onOpenRecord?: (entryId: number) => void;
  onOpenLesson?: (materialId: number) => void;
  target?: NotebookTarget | null;
}) {
  const { t } = useI18n();
  const [epoch, setEpoch] = useState(0);
  const lesson = useLoad<ListeningLesson>(String(id), () => api.getListening(id), epoch);
  const headingRef = useRef<HTMLHeadingElement>(null);
  // The outcome of an explicit script update, kept here so it survives the
  // lesson reload that follows it.
  const [updated, setUpdated] = useState<{ from: number; to: number; replayed: boolean } | null>(null);
  const [earlierShown, setEarlierShown] = useState(false);
  // Focus the lesson heading when it loads. When the Mistake Notebook asked for
  // a question that this lesson shows, focus must not scroll the page back to
  // the heading: the question is brought to the top of the screen instead (this
  // runs after NotebookOrigin's own scroll, so it also keeps the stem visible on
  // a phone, where a long revealed question is taller than the screen).
  useEffect(() => {
    const item =
      lesson.status === "ready" && target ? document.getElementById(notebookItemDomId("listening", target.exerciseId, target.item)) : null;
    headingRef.current?.focus({ preventScroll: item !== null });
    item?.scrollIntoView?.({ block: "start" });
  }, [lesson.status, target]);
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
  const { material, transcript, exercises, generation, preparations, notifications, notification } = lesson.data;
  // The server names the exercise to show: the newest completed one on the
  // latest transcript, or for an authored script always its authored exercise.
  const current = exercises.find((e) => e.id === lesson.data.current_exercise_id && e.status === "completed") ?? null;
  const latest = exercises[0] ?? null;
  const latestPrep = preparations[0] ?? null;
  const settled = !latestPrep || (latestPrep.state !== "unknown" && latestPrep.state !== "in_progress");
  const lastFailed = settled && latest && latest.status === "failed" && transcript && latest.transcript_id === transcript.id ? latest : null;
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
        {isScript(material) ? (
          <>
            <p>
              <span className="tag">{t("listening.source.scriptOnly")}</span>
              {lesson.data.script_revision ? (
                <>
                  {" "}
                  <span className="tag">{t("listening.revision.tag", { n: lesson.data.script_revision.revision })}</span>
                </>
              ) : null}
            </p>
            <div className="banner info" role="note">
              {t("listening.script.hint")}
            </div>
          </>
        ) : (
          <p className="hint">{t("listening.video.hint")}</p>
        )}
        {lesson.data.in_playlist ? <p className="hint">{t("listening.lesson.inPlaylist")}</p> : null}
        <p className="hint">
          {transcript && isScript(material)
            ? t("listening.script.summary", { count: transcript.segments.length })
            : transcript
              ? t(transcript.has_timestamps ? "listening.transcript.summaryTimed" : "listening.transcript.summary", {
                  version: transcript.version,
                  count: transcript.segments.length,
                })
              : t("listening.transcript.none")}
        </p>
      </section>

      {updated ? (
        <div className="banner success" role="status">
          {updated.replayed ? t("listening.revision.already", { to: updated.to }) : t("listening.revision.updated", { from: updated.from, to: updated.to })}
        </div>
      ) : null}
      {isScript(material) && lesson.data.script_revision ? (
        <ScriptUpdate
          key={`${lesson.data.script_revision.revision}-${lesson.data.script_revision.pack_fingerprint ?? ""}`}
          materialId={id}
          state={lesson.data.script_revision}
          onUpdated={(from, to, replayed) => {
            setUpdated({ from, to, replayed });
            setEpoch((n) => n + 1);
          }}
          onReload={() => setEpoch((n) => n + 1)}
        />
      ) : null}
      {target ? (
        <NotebookOrigin
          skill="listening"
          target={target}
          shownExerciseId={earlierShown ? target.exerciseId : (current?.id ?? null)}
          currentVersion={transcript?.version ?? null}
        />
      ) : null}
      {target && transcript && current && isScript(material) && target.exerciseId !== current.id && target.version < transcript.version &&
      exercises.some((e) => e.id === target.exerciseId && e.generator.startsWith("authored:")) ? (
        <EarlierRevision
          material={material}
          target={target}
          currentRevision={transcript.version}
          onShown={setEarlierShown}
          onOpenRecord={onOpenRecord}
        />
      ) : null}
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
            <ExerciseView
              key={current.id}
              material={material}
              transcript={transcript}
              exercise={current}
              onOpenRecord={onOpenRecord}
              targetItem={target && target.exerciseId === current.id ? target.item : null}
            />
          ) : (
            <PrepareSection
              id={id}
              enabled={generation.enabled}
              generator={generation.generator}
              latest={latestPrep}
              onDone={() => setEpoch((n) => n + 1)}
            />
          )}
        </>
      )}
      <NotificationsSection notifications={notifications} enabled={notification.enabled} onChanged={() => setEpoch((n) => n + 1)} />
      <nav className="panel actions" aria-label={t("listening.nav.region")}>
        <button type="button" className="ghost" onClick={onBack}>
          {t("listening.nav.back")}
        </button>
        {isScript(material) && material.pack_script_id && onOpenLesson ? <NextScript packScriptId={material.pack_script_id} onOpen={onOpenLesson} /> : null}
      </nav>
    </div>
  );
}

const fieldKey: Record<ListeningQuestionField, MessageKey> = {
  kind: "listening.revision.field.kind",
  question: "listening.revision.field.question",
  choices: "listening.revision.field.choices",
  expected_answer: "listening.revision.field.expected_answer",
  accepted_alternatives: "listening.revision.field.accepted_alternatives",
  wrong_answers: "listening.revision.field.wrong_answers",
  rationale: "listening.revision.field.rationale",
  segments: "listening.revision.field.segments",
  evidence: "listening.revision.field.evidence",
  position: "listening.revision.field.position",
};

type UpdateFlow =
  | { step: "closed" }
  | { step: "loading" }
  | { step: "failed"; message: string }
  | { step: "preview"; preview: ListeningScriptUpdatePreview; stale: boolean; sending: boolean; unknown: boolean; error: string | null };

// ScriptUpdate offers an explicit update of an imported script when the
// server's pack has a corrected version. Nothing changes on load: the notice
// opens a read-only preview, and only its confirm button writes. The
// confirmation names the revision and pack fingerprint the learner read, so a
// resend (after a lost response or from another tab) never adds a second
// revision, and a preview that went stale is replaced by a fresh one.
function ScriptUpdate({
  materialId,
  state,
  onUpdated,
  onReload,
}: {
  materialId: number;
  state: ListeningScriptRevisionState;
  onUpdated: (from: number, to: number, replayed: boolean) => void;
  onReload: () => void;
}) {
  const { t } = useI18n();
  const [flow, setFlow] = useState<UpdateFlow>({ step: "closed" });
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (flow.step === "preview" && !flow.sending) headingRef.current?.focus();
  }, [flow.step, flow.step === "preview" && flow.stale]);
  if (state.pack_status === "title_changed" || state.pack_status === "not_in_pack")
    return <p className="hint">{t("listening.revision.cannotUpdate")}</p>;
  if (state.pack_status !== "update_available") return null;
  const open = async () => {
    setFlow({ step: "loading" });
    try {
      const preview = await api.getListeningScriptUpdate(materialId);
      setFlow({ step: "preview", preview, stale: false, sending: false, unknown: false, error: null });
    } catch (e) {
      setFlow({ step: "failed", message: describe(e) });
    }
  };
  const confirm = async (preview: ListeningScriptUpdatePreview) => {
    setFlow({ step: "preview", preview, stale: false, sending: true, unknown: false, error: null });
    try {
      const res = await api.updateListeningScript(materialId, preview.current_revision, preview.pack_fingerprint);
      onUpdated(preview.current_revision, res.revision, res.replayed);
    } catch (e) {
      const body = e instanceof ApiError ? (e.body as { code?: string; preview?: ListeningScriptUpdatePreview } | null) : null;
      if (e instanceof ApiError && e.status === 409 && body?.code === "stale_preview" && body.preview) {
        if (body.preview.pack_status !== "update_available") {
          // Already applied elsewhere (another tab): say so, then show the lesson as it is.
          onUpdated(preview.current_revision, body.preview.current_revision, true);
          return;
        }
        setFlow({ step: "preview", preview: body.preview, stale: true, sending: false, unknown: false, error: null });
      } else if (e instanceof NetworkError) {
        setFlow({ step: "preview", preview, stale: false, sending: false, unknown: true, error: null });
      } else {
        setFlow({ step: "preview", preview, stale: false, sending: false, unknown: false, error: t("listening.revision.failed", { message: describe(e) }) });
      }
    }
  };
  return (
    <section className="panel listening-revision" aria-label={t("listening.revision.region")}>
      {flow.step !== "preview" ? (
        <div className="banner info" role="note">
          {t("listening.revision.available", { revision: state.revision })}{" "}
          <button type="button" className="ghost" disabled={flow.step === "loading"} onClick={open}>
            {flow.step === "loading" ? t("listening.revision.loading") : t("listening.revision.review")}
          </button>
        </div>
      ) : null}
      {flow.step === "failed" ? (
        <div className="banner error" role="alert">
          {t("listening.revision.loadFailed", { message: flow.message })}
        </div>
      ) : null}
      {flow.step === "preview" ? (
        <>
          <h3 ref={headingRef} tabIndex={-1}>
            {t("listening.revision.heading", { from: flow.preview.current_revision, to: flow.preview.next_revision ?? flow.preview.current_revision + 1 })}
          </h3>
          {flow.stale ? (
            <div className="banner info" role="alert">
              {t("listening.revision.stale")}
            </div>
          ) : null}
          <p>{t("listening.revision.previous", { from: flow.preview.current_revision, to: flow.preview.next_revision ?? flow.preview.current_revision + 1 })}</p>
          <ScriptChanges preview={flow.preview} />
          {flow.unknown ? (
            <div className="banner info" role="alert">
              {t("listening.revision.unknown")}
            </div>
          ) : null}
          {flow.error ? (
            <div className="banner error" role="alert">
              {flow.error}
            </div>
          ) : null}
          <div className="actions">
            <button type="button" className="primary" disabled={flow.sending} onClick={() => confirm(flow.preview)}>
              {flow.sending
                ? t("listening.revision.updating")
                : flow.unknown
                  ? t("listening.revision.retry")
                  : t("listening.revision.confirm", { to: flow.preview.next_revision ?? flow.preview.current_revision + 1 })}
            </button>
            {flow.unknown ? (
              <button type="button" className="ghost" onClick={onReload}>
                {t("listening.revision.check")}
              </button>
            ) : (
              <button type="button" className="ghost" disabled={flow.sending} onClick={() => setFlow({ step: "closed" })}>
                {t("listening.revision.cancel")}
              </button>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}

// ScriptChanges lists what an update changes without showing the script or a
// key; the exact before and after (lines and reference answers) are behind an
// explicit disclosure, since the lesson hides them until reveal.
function ScriptChanges({ preview }: { preview: ListeningScriptUpdatePreview }) {
  const { t } = useI18n();
  const { lines, questions, annotations_changed } = preview.changes;
  const lineKey = { changed: "listening.revision.lineChanged", added: "listening.revision.lineAdded", removed: "listening.revision.lineRemoved" } as const;
  const where = (q: ListeningScriptUpdatePreview["changes"]["questions"][number]) => q.after_position ?? q.before_position ?? 0;
  return (
    <>
      <ul className="listening-revision-changes">
        {lines.map((l) => (
          <li key={l.line}>{t(lineKey[l.change], { line: l.line })}</li>
        ))}
        {questions.map((q) => (
          <li key={`${q.item_id}-${q.change}`}>
            {q.change === "added"
              ? t("listening.revision.questionAdded", { n: where(q) })
              : q.change === "removed"
                ? t("listening.revision.questionRemoved", { n: where(q), from: preview.current_revision })
                : t("listening.revision.questionChanged", { n: where(q) })}
            {q.change === "changed"
              ? q.fields.map((f) => (
                  <span key={f}>
                    {" "}
                    <span className="tag">{t(fieldKey[f])}</span>
                  </span>
                ))
              : null}
          </li>
        ))}
        {annotations_changed ? <li>{t("listening.revision.notesChanged")}</li> : null}
      </ul>
      <details className="listening-revision-details">
        <summary>{t("listening.revision.details")}</summary>
        {lines.map((l) => (
          <div key={l.line} className="listening-revision-pair">
            <p className="label">{t("listening.revision.lineLabel", { line: l.line })}</p>
            {(["before", "after"] as const).map((side) =>
              l[side] ? (
                <p key={side}>
                  <span className="label">{t(side === "before" ? "listening.revision.before" : "listening.revision.after")}</span>{" "}
                  <strong lang="fr">{l[side]!.speaker} :</strong>{" "}
                  <span lang="fr" className="french">
                    {l[side]!.text}
                  </span>
                </p>
              ) : null,
            )}
          </div>
        ))}
        {questions.map((q) => (
          <div key={`${q.item_id}-${q.change}`} className="listening-revision-pair">
            <p className="label">{t("listening.revision.questionLabel", { n: where(q) })}</p>
            {(["before", "after"] as const).map((side) => {
              const it = q[side];
              return it ? (
                <div key={side}>
                  <p>
                    <span className="label">{t(side === "before" ? "listening.revision.before" : "listening.revision.after")}</span>{" "}
                    <span lang="fr" className="french">
                      {it.question}
                    </span>
                  </p>
                  <p>
                    <span className="label">{t("listening.overview.reference")}</span>{" "}
                    <span lang="fr" className="french">
                      {it.expected_answer}
                    </span>
                  </p>
                  <StoredText primary={it.rationale_en} variants={{ en: it.rationale_en, zh: it.rationale_zh }} kind="explanation" />
                </div>
              ) : null;
            })}
          </div>
        ))}
      </details>
    </>
  );
}

// EarlierRevision shows the revision a Mistake Notebook item was saved from,
// when the lesson has moved on to a later one: the same lines and questions
// the learner practised, with that question marked and brought to the top.
function EarlierRevision({
  material,
  target,
  currentRevision,
  onShown,
  onOpenRecord,
}: {
  material: ListeningMaterial;
  target: NotebookTarget;
  currentRevision: number;
  onShown: (shown: boolean) => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const rev = useLoad<ListeningScriptRevisionView>(`${material.id}-${target.version}`, () => api.getListeningScriptRevision(material.id, target.version), 0);
  const shown = rev.status === "ready" && rev.data.exercise.id === target.exerciseId && rev.data.exercise.content !== null;
  useEffect(() => {
    onShown(shown);
    if (shown) document.getElementById(notebookItemDomId("listening", target.exerciseId, target.item))?.scrollIntoView?.({ block: "start" });
  }, [shown, target.exerciseId, target.item]);
  if (rev.status === "loading")
    return (
      <p className="hint" role="status">
        {t("listening.revision.earlierLoading", { revision: target.version })}
      </p>
    );
  if (rev.status === "error")
    return (
      <div className="banner error" role="alert">
        {t("listening.revision.earlierFailed", { revision: target.version, message: rev.message })}
      </div>
    );
  if (!shown) return null;
  return (
    <section className="listening-earlier" aria-label={t("listening.revision.earlierRegion")}>
      <div className="panel">
        <h3>{t("listening.revision.earlierHeading", { revision: rev.data.revision })}</h3>
        <p className="hint">{t("listening.revision.earlierHint", { current: currentRevision })}</p>
      </div>
      <ExerciseView
        key={rev.data.exercise.id}
        material={material}
        transcript={rev.data.transcript}
        exercise={rev.data.exercise}
        onOpenRecord={onOpenRecord}
        targetItem={target.item}
      />
    </section>
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

type PrepareState =
  | { status: "idle" }
  | { status: "sending" }
  | { status: "unknown"; key: string; confirm: boolean }
  | { status: "error"; message: string };

// PrepareSection is the explicit Prepare button. Each click has its own key.
// When no response arrives, the key is looked up before anything else; only if
// nothing is recorded is the SAME request offered again (the server replays
// it). After an attempt whose outcome is unknown, a new call needs the
// learner's acknowledgement that it may be billed again.
function PrepareSection({
  id,
  enabled,
  generator,
  latest,
  onDone,
}: {
  id: number;
  enabled: boolean;
  generator: string | null;
  latest: ListeningPreparation | null;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const [state, setState] = useState<PrepareState>({ status: "idle" });
  const check = async (key: string, confirm: boolean) => {
    try {
      await api.getListeningPreparation(key);
      onDone(); // recorded: the lesson re-read shows its state
    } catch {
      setState({ status: "unknown", key, confirm });
    }
  };
  const send = async (key: string, confirm: boolean) => {
    setState({ status: "sending" });
    try {
      await api.prepareListeningExercise(id, key, confirm);
      onDone();
    } catch (e) {
      if (e instanceof ApiError && (e.status === 502 || e.status === 504 || e.status === 409)) {
        onDone(); // stored (a failure or an unknown outcome), or refused by an attempt the re-read shows
        return;
      }
      if (e instanceof NetworkError || (e instanceof ApiError && e.status >= 500 && e.status !== 503)) {
        await check(key, confirm);
        return;
      }
      setState({ status: "error", message: t("listening.prepare.failed", { message: describe(e) }) });
    }
  };
  const inProgress = latest?.state === "in_progress";
  const unknown = latest?.state === "unknown";
  return (
    <section className="panel" aria-label={t("listening.prepare.region")}>
      <h3>{t("listening.prepare.heading")}</h3>
      {!enabled ? (
        <p className="hint">{t("listening.prepare.disabled")}</p>
      ) : inProgress ? (
        <div className="banner info" role="status">
          {t("listening.prepare.inProgress", { when: new Date(latest.started_at).toLocaleString() })}{" "}
          <button type="button" className="ghost" onClick={onDone}>
            {t("listening.daily.checkAgain")}
          </button>
        </div>
      ) : (
        <>
          <p className="hint">{t("listening.prepare.hint", { generator: generator ?? "" })}</p>
          {unknown ? (
            <div className="banner info" role="status">
              {t("listening.prepare.outcomeUnknown")}
            </div>
          ) : null}
          <button
            type="button"
            className={unknown ? "ghost" : "primary"}
            disabled={state.status === "sending"}
            onClick={() => send(randomOperationId(), unknown)}
          >
            {state.status === "sending"
              ? t("listening.prepare.sending")
              : unknown
                ? t("listening.prepare.retryUnknown")
                : t("listening.prepare.button")}
          </button>
        </>
      )}
      {state.status === "unknown" ? (
        <div className="banner info" role="alert">
          {t("listening.prepare.unknown")}{" "}
          <button type="button" className="ghost" onClick={() => check(state.key, state.confirm)}>
            {t("listening.daily.checkAgain")}
          </button>
          <button type="button" className="ghost" onClick={() => send(state.key, state.confirm)}>
            {t("listening.daily.sendSame")}
          </button>
        </div>
      ) : state.status === "error" ? (
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
  targetItem = null,
}: {
  material: ListeningMaterial;
  transcript: ListeningTranscript;
  exercise: ListeningExercise;
  onOpenRecord?: (entryId: number) => void;
  targetItem?: number | null;
}) {
  const { t, tn } = useI18n();
  const content = exercise.content!;
  const [answers, setAnswers] = useState<string[]>(() => content.items.map(() => ""));
  const [revealed, setRevealed] = useState(false);
  const [checks, setChecks] = useState<Record<number, SelfCheck>>({});
  const [showTranscript, setShowTranscript] = useState(false);
  const [showForReader, setShowForReader] = useState(false);
  const readerToggle = useRef<HTMLButtonElement>(null);
  const segment = (n: number) => transcript.segments.find((s) => s.index === n);
  const script = isScript(material);
  const authored = exercise.generator.startsWith("authored:");
  const overviewRef = useRef<HTMLHeadingElement>(null);
  // Revealing moves to the overview at the top of the exercise; reopening an
  // already revealed exercise (e.g. from the Mistake Notebook) does not.
  useEffect(() => {
    if (!revealed) return;
    overviewRef.current?.scrollIntoView?.({ block: "start" });
    overviewRef.current?.focus({ preventScroll: true });
  }, [revealed]);
  const toQuestion = (i: number) => {
    document.getElementById(notebookItemDomId("listening", exercise.id, i + 1))?.scrollIntoView?.({ block: "start" });
    document.getElementById(revealDomId(exercise.id, i))?.focus({ preventScroll: true });
  };
  const toOverview = () => {
    overviewRef.current?.scrollIntoView?.({ block: "start" });
    overviewRef.current?.focus({ preventScroll: true });
  };
  return (
    <section className="panel listening-exercise" aria-label={t("listening.exercise.region")}>
      <h3>{t("listening.exercise.heading")}</h3>
      <p className="hint">{t(revealed ? "listening.exercise.revealedHint" : script ? "listening.exercise.hintScript" : "listening.exercise.hint")}</p>
      {script && !revealed ? (
        <>
          <div className="actions">
            <button
              ref={readerToggle}
              type="button"
              className="ghost"
              aria-expanded={showForReader}
              onClick={() => setShowForReader((v) => !v)}
            >
              {t(showForReader ? "listening.script.hideForReader" : "listening.script.showForReader")}
            </button>
          </div>
          {showForReader ? (
            <section className="source-view" aria-label={t("listening.script.readerRegion")}>
              <p className="hint">{t("listening.script.readerHint")}</p>
              {transcript.segments.map((s) => (
                <SegmentLine key={s.index} material={material} s={s} />
              ))}
              <div className="actions">
                <button
                  type="button"
                  className="ghost"
                  onClick={() => {
                    setShowForReader(false);
                    readerToggle.current?.focus(); // back to the start of the exercise
                  }}
                >
                  {t("listening.script.hideAtEnd")}
                </button>
              </div>
            </section>
          ) : null}
        </>
      ) : null}
      {revealed ? (
        <section className="library-section listening-overview" aria-labelledby={`listening-overview-${exercise.id}`}>
          <h4 id={`listening-overview-${exercise.id}`} ref={overviewRef} tabIndex={-1}>
            {t("listening.overview.heading")}
          </h4>
          <p className="hint">{t("listening.overview.hint")}</p>
          <ol className="listening-overview-list">
            {content.items.map((item, i) => (
              <OverviewRow
                key={i}
                item={item}
                index={i}
                answer={answers[i]}
                check={checks[i]}
                onCheck={(c) => setChecks((prev) => ({ ...prev, [i]: c }))}
                onOpen={() => toQuestion(i)}
              />
            ))}
          </ol>
        </section>
      ) : null}
      <ol className="listening-items">
        {content.items.map((item, i) => (
          <li
            key={i}
            id={notebookItemDomId("listening", exercise.id, i + 1)}
            className={targetItem === i + 1 ? "listening-item notebook-target" : "listening-item"}
          >
            <p className="label">{t(kindKey[item.kind])}</p>
            <p lang="fr" className="french">
              {item.question}
            </p>
            {item.choices && item.choices.length > 0 ? (
              <fieldset className="listening-choices">
                <legend>{t("listening.answer.choiceLabel", { n: i + 1 })}</legend>
                {item.choices.map((choice, c) => (
                  <label key={c} className="listening-choice">
                    <input
                      type="radio"
                      name={`listening-choice-${exercise.id}-${i}`}
                      value={choice}
                      checked={answers[i] === choice}
                      onChange={() => setAnswers((prev) => prev.map((a, j) => (j === i ? choice : a)))}
                    />{" "}
                    <span lang="fr" className="french">
                      {choice}
                    </span>
                  </label>
                ))}
              </fieldset>
            ) : (
              <>
                <label htmlFor={`listening-answer-${exercise.id}-${i}`}>{t("listening.answer.label", { n: i + 1 })}</label>
                <textarea
                  id={`listening-answer-${exercise.id}-${i}`}
                  rows={2}
                  autoComplete="off"
                  value={answers[i]}
                  onChange={(e) => setAnswers((prev) => prev.map((a, j) => (j === i ? e.target.value : a)))}
                />
              </>
            )}
            {revealed ? (
              <Revealed
                material={material}
                exercise={exercise}
                item={item}
                index={i}
                answer={answers[i]}
                segments={item.segments.map(segment).filter((s): s is TranscriptSegment => !!s)}
                check={checks[i]}
                onCheck={(c) => setChecks((prev) => ({ ...prev, [i]: c }))}
                onOpenRecord={onOpenRecord}
                onOverview={toOverview}
              />
            ) : null}
          </li>
        ))}
      </ol>
      <p className="hint" aria-live="polite">
        {revealed
          ? t("listening.progress.checked", { checked: Object.keys(checks).length, total: content.items.length })
          : t("listening.progress.answered", { answered: answers.filter((a) => a.trim() !== "").length, total: content.items.length })}
      </p>
      {!revealed ? (
        <div className="actions">
          <button type="button" className="primary" onClick={() => setRevealed(true)}>
            {t("listening.reveal")}
          </button>
        </div>
      ) : (
        <>
          {content.annotations.length > 0 ? (
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
          ) : null}
          <div className="actions">
            <button type="button" className="ghost" aria-expanded={showTranscript} onClick={() => setShowTranscript((s) => !s)}>
              {t(showTranscript ? "listening.transcript.hide" : "listening.transcript.show")}
            </button>
          </div>
          {showTranscript ? <TranscriptView material={material} transcript={transcript} /> : null}
          <p className="hint">
            {tn(authored ? "listening.exercise.provenanceAuthored" : "listening.exercise.provenance", { generator: <code>{exercise.generator}</code> })}
          </p>
        </>
      )}
    </section>
  );
}

const revealDomId = (exerciseId: number, index: number) => `listening-reveal-${exerciseId}-${index + 1}`;

type Comparison = "same" | "different" | "compare" | "unanswered";

// compareAnswer puts the learner's answer beside the reference without
// judging free text: a chosen option is either the authored answer or not; a
// typed short answer is left for the learner to compare.
export function compareAnswer(item: ListeningItem, answer: string): Comparison {
  if (answer.trim() === "") return "unanswered";
  if (item.choices && item.choices.length > 0) return answer === item.expected_answer ? "same" : "different";
  return "compare";
}

const comparisonKey: Record<Comparison, MessageKey> = {
  same: "listening.overview.same",
  different: "listening.overview.different",
  compare: "listening.overview.compare",
  unanswered: "listening.overview.unanswered",
};

// OverviewRow: a typed short answer stands beside the reference here, so the
// learner can mark their own comparison in the row (the same page-only
// self-check as under the question, shared with it); nothing judges it.
function OverviewRow({
  item,
  index,
  answer,
  check,
  onCheck,
  onOpen,
}: {
  item: ListeningItem;
  index: number;
  answer: string;
  check: SelfCheck | undefined;
  onCheck: (c: SelfCheck) => void;
  onOpen: () => void;
}) {
  const { t } = useI18n();
  const c = compareAnswer(item, answer);
  return (
    <li className="listening-overview-row">
      <p>
        <button type="button" className="link-button" onClick={onOpen}>
          {t("listening.overview.open", { n: index + 1 })}
        </button>{" "}
        <span className={`tag listening-${c}`}>{t(comparisonKey[c])}</span>
      </p>
      {c !== "unanswered" ? (
        <p>
          <span className="label">{t("listening.overview.yours")}</span>{" "}
          <span lang="fr" className="french">
            {answer.trim()}
          </span>
        </p>
      ) : null}
      <p>
        <span className="label">{t("listening.overview.reference")}</span>{" "}
        <span lang="fr" className="french">
          {item.expected_answer}
        </span>
      </p>
      {c === "compare" ? (
        <div className="actions" role="group" aria-label={t("listening.overview.check", { n: index + 1 })}>
          <button type="button" aria-pressed={check === "got"} onClick={() => onCheck("got")}>
            {t("listening.check.got")}
          </button>
          <button type="button" aria-pressed={check === "missed"} onClick={() => onCheck("missed")}>
            {t("listening.check.missed")}
          </button>
        </div>
      ) : null}
    </li>
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
      {s.speaker ? (
        <>
          <strong lang="fr">{s.speaker} :</strong>{" "}
        </>
      ) : null}
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
  answer,
  segments,
  check,
  onCheck,
  onOpenRecord,
  onOverview,
}: {
  material: ListeningMaterial;
  exercise: ListeningExercise;
  item: ListeningItem;
  index: number;
  answer: string;
  segments: TranscriptSegment[];
  check: SelfCheck | undefined;
  onCheck: (c: SelfCheck) => void;
  onOpenRecord?: (entryId: number) => void;
  onOverview?: () => void;
}) {
  const { t } = useI18n();
  const [saving, setSaving] = useState(false);
  return (
    <div
      className="listening-reveal"
      id={revealDomId(exercise.id, index)}
      tabIndex={-1}
      role="group"
      aria-label={t("listening.reveal.region", { n: index + 1 })}
    >
      <p>
        <span className="label">{t("listening.reveal.expected")}</span>{" "}
        <span lang="fr" className="french">
          {item.expected_answer}
        </span>
      </p>
      {item.accepted_alternatives && item.accepted_alternatives.length > 0 ? (
        <p>
          <span className="label">{t("listening.reveal.alsoAccepted")}</span>{" "}
          <span lang="fr" className="french">
            {item.accepted_alternatives.join(" / ")}
          </span>
        </p>
      ) : null}
      <p>
        <span className="label">{t("listening.reveal.why")}</span>{" "}
        <StoredText primary={item.rationale_en} variants={{ en: item.rationale_en, zh: item.rationale_zh }} kind="explanation" />
      </p>
      {item.wrong_answers && item.wrong_answers.length > 0 ? (
        <ul className="listening-wrong">
          {item.wrong_answers.map((w, k) => (
            <li key={k}>
              <span className="label">{t("listening.reveal.whyNot", { answer: w.answer })}</span>{" "}
              <StoredText primary={w.why_wrong_en} variants={{ en: w.why_wrong_en, zh: w.why_wrong_zh }} kind="explanation" />
            </li>
          ))}
        </ul>
      ) : null}
      <p className="label">{t(isScript(material) ? "listening.reveal.evidenceScript" : "listening.reveal.evidence")}</p>
      {segments.map((s) => (
        <SegmentLine key={s.index} material={material} s={s} />
      ))}
      {item.evidence && item.evidence.length > 0 ? (
        <ul className="listening-evidence">
          {item.evidence.map((e, k) => (
            <li key={k}>
              <span className="label">{t("listening.reveal.quote", { n: e.segment })}</span>{" "}
              <mark lang="fr" className="french">
                « {e.excerpt} »
              </mark>
            </li>
          ))}
        </ul>
      ) : null}
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
        {onOverview ? (
          <button type="button" className="link-button" onClick={onOverview}>
            {t("listening.overview.back")}
          </button>
        ) : null}
      </div>
      {saving ? (
        <SaveMissedPoint
          material={material}
          exercise={exercise}
          item={item}
          index={index}
          answer={answer}
          segments={segments}
          onCancel={() => setSaving(false)}
          onOpenRecord={onOpenRecord}
        />
      ) : null}
    </div>
  );
}

// missedPointContext is the source evidence attached to the learner's record:
// the lesson, its source (the video link, at the cited time when the source
// supplied one; or the authored script, which has no link, video or time), the
// question and the cited French excerpts, exactly as stored.
export function missedPointContext(material: ListeningMaterial, item: ListeningItem, segments: TranscriptSegment[]): string {
  const at = segments.find((s) => s.start_seconds !== null)?.start_seconds ?? null;
  const video = videoAt(material, at);
  const source = video === null ? `Source: authored script, no audio or video (${material.pack_script_id ?? "no pack id"})` : `Video: ${video}`;
  const question = item.id ? `Question ${item.id} (${item.kind}): ${item.question}` : `Question (${item.kind}): ${item.question}`;
  const lines = [`Listening exercise: ${material.title}`, source, question];
  for (const s of segments) {
    const where = [`segment ${s.index}`, s.speaker, s.start_seconds !== null ? clock(s.start_seconds) : undefined].filter(Boolean).join(", ");
    lines.push(`Excerpt (${where}): « ${s.text} »`);
  }
  return lines.join("\n");
}

type SaveState =
  | { status: "editing" }
  | { status: "saving" }
  | { status: "saved"; entryId: number; created: boolean; duplicate?: boolean }
  | { status: "unknown" }
  | { status: "error"; message: string };

function SaveMissedPoint({
  material,
  exercise,
  item,
  index,
  answer,
  segments,
  onCancel,
  onOpenRecord,
}: {
  material: ListeningMaterial;
  exercise: ListeningExercise;
  item: ListeningItem;
  index: number;
  answer: string;
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
  const [includeAnswer, setIncludeAnswer] = useState(false);
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
          source_ref: sourceRef("listening_item", exercise.id, index, includeAnswer ? answer : ""),
        }),
      );
      setState({ status: "saved", entryId: result.entry_id, created: result.created });
    } catch (e) {
      const dup = alreadySaved(e);
      if (dup !== null) setState({ status: "saved", entryId: dup, created: false, duplicate: true });
      else setState(e instanceof NetworkError ? { status: "unknown" } : { status: "error", message: describe(e) });
    }
  };
  const fieldId = `listening-missed-${exercise.id}-${index}`;
  if (state.status === "saved")
    return (
      <div className="banner success" role="status">
        {t(state.duplicate ? "notebook.save.duplicate" : state.created ? "listening.save.saved" : "listening.save.replayed", { id: state.entryId })}{" "}
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
      <textarea
        id={fieldId}
        rows={3}
        value={text}
        required
        onChange={(e) => setText(e.target.value)}
        // While the outcome is unknown the record may already exist under this
        // capture ID, so a resend must be identical: editing is locked.
        disabled={state.status === "saving" || state.status === "unknown"}
      />
      {answer.trim() ? (
        <label className="notebook-attempt">
          <input
            type="checkbox"
            checked={includeAnswer}
            onChange={(e) => setIncludeAnswer(e.target.checked)}
            disabled={state.status === "saving" || state.status === "unknown"}
          />{" "}
          {t("notebook.save.includeAnswer", { answer: answer.trim() })}
        </label>
      ) : null}
      <p className="label">{t("listening.save.attached")}</p>
      <pre className="listening-context" lang="fr">
        {context}
      </pre>
      <p className="hint">{t("listening.save.hint")}</p>
      <p className="hint">{t("notebook.save.linked")}</p>
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
        <button type="button" className="ghost" onClick={onCancel} disabled={state.status === "saving" || state.status === "unknown"}>
          {t("listening.save.cancel")}
        </button>
      </div>
    </form>
  );
}
