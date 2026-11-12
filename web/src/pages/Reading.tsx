import { useEffect, useRef, useState, type FormEvent } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { StoredText } from "../components/ExplanationText";
import { NotebookOrigin, notebookItemDomId, type NotebookTarget } from "../components/NotebookOrigin";
import { useI18n, type MessageKey } from "../i18n";
import type {
  ReadingEvidence,
  ReadingExamples,
  ReadingExercise,
  ReadingFailureCode,
  ReadingItem,
  ReadingItemKind,
  ReadingLessonState,
  ReadingLessonView,
  ReadingList,
  ReadingPassage,
  ReadingPreparation,
} from "../types/reading";
import { randomOperationId } from "./annotationOperation";
import { alreadySaved, sourceRef } from "./notebookLink";

// Exam Reading v1 (private workbench only; never in the public demo).
//
// - A lesson is a French passage: the learner's own (title, text, optional
//   https link that is never fetched) or an authored, reviewed example from the
//   embedded pack, imported with no model call.
// - The passage stays visible while the learner answers. Reference answers,
//   explanations, wrong-answer reasons and evidence highlights stay hidden
//   until "Reveal answers and evidence"; then each cited excerpt can be shown
//   and highlighted in its paragraph. Answers and self-checks stay in
//   component state: never sent, logged or stored. Practice, not an exam score.
// - Preparing an exercise for a learner passage is one explicit request under
//   a key, with the Listening recovery rules (look a lost response up first;
//   an unknown outcome needs an acknowledged retry; nothing retries itself).
// - A missed point becomes a learning record only through an explicit
//   "Save learning record" via the existing capture path (source "manual").

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

const kindKey: Record<ReadingItemKind, MessageKey> = {
  main_idea: "reading.kind.main_idea",
  detail: "reading.kind.detail",
  inference: "reading.kind.inference",
};
const stateKey: Record<ReadingLessonState, MessageKey> = {
  ready_to_prepare: "reading.state.ready",
  in_progress: "reading.state.inProgress",
  prepared: "reading.state.prepared",
  failed: "reading.state.failed",
  outcome_unknown: "reading.state.unknown",
};
const failureKey: Record<ReadingFailureCode, MessageKey> = {
  provider_timeout: "reading.failure.provider_timeout",
  provider_unavailable: "reading.failure.provider_unavailable",
  invalid_output: "reading.failure.invalid_output",
};

export function Reading({
  onOpenRecord,
  openRequest,
}: { onOpenRecord?: (entryId: number) => void; openRequest?: { lessonId: number; nonce: number; target?: NotebookTarget } | null } = {}) {
  const [screen, setScreen] = useState<{ kind: "list" } | { kind: "lesson"; id: number }>({ kind: "list" });
  // A Mistake Notebook link opens the lesson its item came from.
  useEffect(() => {
    if (openRequest) setScreen({ kind: "lesson", id: openRequest.lessonId });
  }, [openRequest]);
  const [epoch, setEpoch] = useState(0);
  return (
    <main className="reading">
      {screen.kind === "list" ? (
        <LessonList epoch={epoch} onOpen={(id) => setScreen({ kind: "lesson", id })} />
      ) : (
        <LessonScreen
          key={screen.id}
          id={screen.id}
          onBack={() => {
            setEpoch((n) => n + 1);
            setScreen({ kind: "list" });
          }}
          onOpenRecord={onOpenRecord}
          target={openRequest && openRequest.lessonId === screen.id ? openRequest.target ?? null : null}
        />
      )}
    </main>
  );
}

function LessonList({ epoch, onOpen }: { epoch: number; onOpen: (id: number) => void }) {
  const { t } = useI18n();
  const [retry, setRetry] = useState(0);
  const list = useLoad<ReadingList>("list", () => api.listReading(), epoch * 100 + retry);
  const examples = useLoad<ReadingExamples>("examples", () => api.listReadingExamples(), epoch * 100 + retry);
  return (
    <>
      <ExamplesPanel examples={examples} onOpen={onOpen} />
      <AddPassageForm onSaved={onOpen} />
      <section className="panel" aria-label={t("reading.list.region")}>
        <h2>{t("reading.list.heading")}</h2>
        {list.status === "loading" ? (
          <p className="hint" role="status">{t("reading.list.loading")}</p>
        ) : list.status === "error" ? (
          <div className="banner error" role="alert">
            {t("reading.list.failed", { message: list.message })}{" "}
            <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
              {t("common.retry")}
            </button>
          </div>
        ) : list.data.lessons.length === 0 ? (
          <p className="empty">{t("reading.list.empty")}</p>
        ) : (
          <ul className="listening-list">
            {list.data.lessons.map((row) => (
              <li key={row.lesson.id}>
                <button type="button" className="link-button" onClick={() => onOpen(row.lesson.id)}>
                  {row.lesson.title}
                </button>{" "}
                <span className="tag">{t(stateKey[row.state])}</span>
                {row.lesson.origin === "authored" ? (
                  <>
                    {" "}
                    <span className="tag">{t("reading.origin.authored")}</span>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function ExamplesPanel({ examples, onOpen }: { examples: Load<ReadingExamples>; onOpen: (id: number) => void }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const use = async (passageId: string) => {
    setBusy(passageId);
    setError(null);
    try {
      const v = await api.importReadingExample(passageId);
      onOpen(v.lesson.id);
    } catch (e) {
      setError(e instanceof NetworkError ? t("reading.examples.unknown") : t("reading.examples.failed", { message: describe(e) }));
      setBusy(null);
    }
  };
  return (
    <section className="panel" aria-label={t("reading.examples.region")}>
      <h2>{t("reading.examples.heading")}</h2>
      <p className="hint">{t("reading.examples.hint")}</p>
      {examples.status === "loading" ? (
        <p className="hint" role="status">{t("reading.list.loading")}</p>
      ) : examples.status === "error" ? (
        <p className="hint" role="status">{t("reading.examples.failed", { message: examples.message })}</p>
      ) : (
        <ul className="listening-list">
          {examples.data.examples.map((e) => (
            <li key={e.id}>
              <span className="reading-example-title">{e.title}</span>{" "}
              <span className="hint">{t("reading.examples.meta", { format: e.format, level: e.style_level, questions: e.questions })}</span>{" "}
              {e.imported_lesson_id !== null ? (
                <button type="button" className="ghost" onClick={() => onOpen(e.imported_lesson_id!)}>
                  {t("reading.examples.open")}
                </button>
              ) : (
                <button type="button" disabled={busy !== null} onClick={() => use(e.id)}>
                  {t("reading.examples.use")}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error ? (
        <div className="banner error" role="alert">
          {error}
        </div>
      ) : null}
    </section>
  );
}

function AddPassageForm({ onSaved }: { onSaved: (id: number) => void }) {
  const { t } = useI18n();
  const [title, setTitle] = useState("");
  const [link, setLink] = useState("");
  const [text, setText] = useState("");
  const [state, setState] = useState<{ status: "idle" | "saving" } | { status: "error"; message: string }>({ status: "idle" });
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setState({ status: "saving" });
    try {
      const v = await api.createReading({ title, text, source_url: link });
      onSaved(v.lesson.id);
    } catch (e) {
      setState({ status: "error", message: e instanceof NetworkError ? t("reading.add.unknown") : t("reading.add.failed", { message: describe(e) }) });
    }
  };
  return (
    <form className="panel listening-add" aria-label={t("reading.add.region")} onSubmit={submit}>
      <h2>{t("reading.add.heading")}</h2>
      <p className="hint">{t("reading.add.hint")}</p>
      <label htmlFor="reading-title">{t("reading.add.title")}</label>
      <input id="reading-title" type="text" value={title} required maxLength={200} onChange={(e) => setTitle(e.target.value)} />
      <label htmlFor="reading-link">{t("reading.add.link")}</label>
      <input id="reading-link" type="url" value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://…" />
      <label htmlFor="reading-text">{t("reading.add.text")}</label>
      <textarea id="reading-text" lang="fr" rows={10} value={text} required onChange={(e) => setText(e.target.value)} />
      <p className="hint">{t("reading.add.format")}</p>
      {state.status === "error" ? (
        <div className="banner error" role="alert">
          {state.message}
        </div>
      ) : null}
      <div className="actions">
        <button type="submit" className="primary" disabled={state.status === "saving"}>
          {t("reading.add.save")}
        </button>
      </div>
    </form>
  );
}

type Highlight = { segment: string; excerpt: string } | null;

function LessonScreen({
  id,
  onBack,
  onOpenRecord,
  target = null,
}: {
  id: number;
  onBack: () => void;
  onOpenRecord?: (entryId: number) => void;
  target?: NotebookTarget | null;
}) {
  const { t } = useI18n();
  const [epoch, setEpoch] = useState(0);
  const lesson = useLoad<ReadingLessonView>(String(id), () => api.getReading(id), epoch);
  const [highlight, setHighlight] = useState<Highlight>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), [lesson.status]);
  const back = (
    <button type="button" className="ghost" onClick={onBack}>
      {t("reading.back")}
    </button>
  );
  if (lesson.status !== "ready")
    return (
      <section className="panel" aria-label={t("reading.lesson.region")}>
        <h2 ref={headingRef} tabIndex={-1}>
          {t("reading.lesson.heading", { id })}
        </h2>
        {back}
        {lesson.status === "loading" ? (
          <p className="hint" role="status">{t("reading.lesson.loading")}</p>
        ) : (
          <div className="banner error" role="alert">
            {t("reading.lesson.failed", { message: lesson.message })}{" "}
            <button type="button" className="ghost" onClick={() => setEpoch((n) => n + 1)}>
              {t("common.retry")}
            </button>
          </div>
        )}
      </section>
    );
  const v = lesson.data;
  const current = v.exercises.find((e) => e.passage_id === v.passage.id && e.status === "completed") ?? null;
  const latestPrep = v.preparations[0] ?? null;
  const latestForPassage = v.exercises.find((e) => e.passage_id === v.passage.id) ?? null;
  const settled = !latestPrep || (latestPrep.state !== "unknown" && latestPrep.state !== "in_progress");
  const lastFailed = settled && latestForPassage && latestForPassage.status === "failed" ? latestForPassage : null;
  const showIn = (e: ReadingEvidence) => {
    setHighlight(e);
    document.getElementById(segmentDomId(v.lesson.id, e.segment))?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  };
  return (
    <div>
      <section className="panel" aria-label={t("reading.lesson.region")}>
        <h2 ref={headingRef} tabIndex={-1} className="library-title">
          {v.lesson.title}
        </h2>
        <div className="actions">
          {back}
          {v.lesson.source_url ? (
            <a href={v.lesson.source_url} target="_blank" rel="noopener noreferrer">
              {t("reading.source.open")}
            </a>
          ) : null}
        </div>
        <p className="hint">
          {v.lesson.origin === "authored"
            ? t("reading.lesson.authored")
            : t("reading.lesson.version", { version: v.passage.version, count: v.passage.segments.length })}
        </p>
        <p className="hint">{t("reading.practiceNotice")}</p>
      </section>
      {target ? <NotebookOrigin skill="reading" target={target} shownExerciseId={current?.id ?? null} currentVersion={v.passage.version} /> : null}
      <div className="reading-layout">
        <PassageView lessonId={v.lesson.id} passage={v.passage} highlight={highlight} />
        <div>
          {lastFailed && !current ? (
            <div className="banner error" role="status">
              {t("reading.prepare.lastFailed", { reason: t(failureKey[lastFailed.failure_code ?? "provider_unavailable"]) })}
            </div>
          ) : null}
          {current ? (
            <ExerciseView
              key={current.id}
              view={v}
              exercise={current}
              onShow={showIn}
              onHide={() => setHighlight(null)}
              onOpenRecord={onOpenRecord}
              targetItem={target && target.exerciseId === current.id ? target.item : null}
            />
          ) : (
            <PrepareSection
              id={id}
              enabled={v.generation.enabled}
              generator={v.generation.generator}
              latest={latestPrep}
              onDone={() => setEpoch((n) => n + 1)}
            />
          )}
        </div>
      </div>
    </div>
  );
}

const segmentDomId = (lessonId: number, segment: string) => `reading-${lessonId}-${segment}`;

// PassageView always shows the passage. A highlight exists only after reveal,
// when the learner asks to see a cited excerpt; the excerpt occurs exactly once
// in its paragraph (validated by the backend), so it is marked where it is.
function PassageView({ lessonId, passage, highlight }: { lessonId: number; passage: ReadingPassage; highlight: Highlight }) {
  const { t } = useI18n();
  return (
    <section className="panel reading-passage" aria-label={t("reading.passage.region")}>
      <h3>{t("reading.passage.heading")}</h3>
      {passage.segments.map((s) => {
        const hit = highlight && highlight.segment === s.id ? s.text.indexOf(highlight.excerpt) : -1;
        return (
          <p key={s.id} id={segmentDomId(lessonId, s.id)} className={hit >= 0 ? "reading-paragraph cited" : "reading-paragraph"}>
            <span className="hint reading-pid">{s.id}</span>{" "}
            <span lang="fr" className="french">
              {hit >= 0 && highlight ? (
                <>
                  {s.text.slice(0, hit)}
                  <mark>{highlight.excerpt}</mark>
                  {s.text.slice(hit + highlight.excerpt.length)}
                </>
              ) : (
                s.text
              )}
            </span>
          </p>
        );
      })}
    </section>
  );
}

type PrepareState =
  | { status: "idle" }
  | { status: "sending" }
  | { status: "unknown"; key: string; confirm: boolean }
  | { status: "error"; message: string };

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
  latest: ReadingPreparation | null;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const [state, setState] = useState<PrepareState>({ status: "idle" });
  const check = async (key: string, confirm: boolean) => {
    try {
      await api.getReadingPreparation(key);
      onDone();
    } catch {
      setState({ status: "unknown", key, confirm });
    }
  };
  const send = async (key: string, confirm: boolean) => {
    setState({ status: "sending" });
    try {
      await api.prepareReadingExercise(id, key, confirm);
      onDone();
    } catch (e) {
      if (e instanceof ApiError && (e.status === 502 || e.status === 504 || e.status === 409)) {
        onDone();
        return;
      }
      if (e instanceof NetworkError || (e instanceof ApiError && e.status >= 500 && e.status !== 503)) {
        await check(key, confirm);
        return;
      }
      setState({ status: "error", message: t("reading.prepare.failed", { message: describe(e) }) });
    }
  };
  const inProgress = latest?.state === "in_progress";
  const unknown = latest?.state === "unknown";
  return (
    <section className="panel" aria-label={t("reading.prepare.region")}>
      <h3>{t("reading.prepare.heading")}</h3>
      {!enabled ? (
        <p className="hint">{t("reading.prepare.disabled")}</p>
      ) : inProgress ? (
        <div className="banner info" role="status">
          {t("reading.prepare.inProgress")}{" "}
          <button type="button" className="ghost" onClick={onDone}>
            {t("reading.checkAgain")}
          </button>
        </div>
      ) : (
        <>
          <p className="hint">{t("reading.prepare.hint", { generator: generator ?? "" })}</p>
          {unknown ? (
            <div className="banner info" role="status">
              {t("reading.prepare.outcomeUnknown")}
            </div>
          ) : null}
          <button
            type="button"
            className={unknown ? "ghost" : "primary"}
            disabled={state.status === "sending"}
            onClick={() => send(randomOperationId(), unknown)}
          >
            {state.status === "sending" ? t("reading.prepare.sending") : unknown ? t("reading.prepare.retryUnknown") : t("reading.prepare.button")}
          </button>
        </>
      )}
      {state.status === "unknown" ? (
        <div className="banner info" role="alert">
          {t("reading.prepare.lost")}{" "}
          <button type="button" className="ghost" onClick={() => check(state.key, state.confirm)}>
            {t("reading.checkAgain")}
          </button>
          <button type="button" className="ghost" onClick={() => send(state.key, state.confirm)}>
            {t("reading.sendSame")}
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
  view,
  exercise,
  onShow,
  onHide,
  onOpenRecord,
  targetItem = null,
}: {
  view: ReadingLessonView;
  exercise: ReadingExercise;
  onShow: (e: ReadingEvidence) => void;
  onHide: () => void;
  onOpenRecord?: (entryId: number) => void;
  targetItem?: number | null;
}) {
  const { t, tn } = useI18n();
  const content = exercise.content!;
  const [answers, setAnswers] = useState<string[]>(() => content.items.map(() => ""));
  const [revealed, setRevealed] = useState(false);
  const [checks, setChecks] = useState<Record<number, SelfCheck>>({});
  return (
    <section className="panel listening-exercise" aria-label={t("reading.exercise.region")}>
      <h3>{t("reading.exercise.heading")}</h3>
      <p className="hint">{t(revealed ? "reading.exercise.revealedHint" : "reading.exercise.hint")}</p>
      <ol className="listening-items">
        {content.items.map((item, i) => (
          <li
            key={i}
            id={notebookItemDomId("reading", exercise.id, i + 1)}
            className={targetItem === i + 1 ? "listening-item notebook-target" : "listening-item"}
          >
            <p className="label">{t(kindKey[item.kind])}</p>
            <p lang="fr" className="french">
              {item.question}
            </p>
            <label htmlFor={`reading-answer-${exercise.id}-${i}`}>{t("reading.answer.label", { n: i + 1 })}</label>
            <textarea
              id={`reading-answer-${exercise.id}-${i}`}
              rows={2}
              autoComplete="off"
              value={answers[i]}
              onChange={(e) => setAnswers((prev) => prev.map((a, j) => (j === i ? e.target.value : a)))}
            />
            {revealed ? (
              <Revealed
                view={view}
                exercise={exercise}
                item={item}
                index={i}
                answer={answers[i]}
                check={checks[i]}
                onCheck={(c) => setChecks((prev) => ({ ...prev, [i]: c }))}
                onShow={onShow}
                onOpenRecord={onOpenRecord}
              />
            ) : null}
          </li>
        ))}
      </ol>
      {!revealed ? (
        <div className="actions">
          <button type="button" className="primary" onClick={() => setRevealed(true)}>
            {t("reading.reveal")}
          </button>
        </div>
      ) : (
        <>
          {content.no_inference_reason ? (
            <p className="hint">{t("reading.noInference", { reason: content.no_inference_reason })}</p>
          ) : null}
          <div className="actions">
            <button type="button" className="ghost" onClick={onHide}>
              {t("reading.evidence.clear")}
            </button>
          </div>
          <p className="hint">
            {tn(exercise.generator.startsWith("authored:") ? "reading.exercise.provenanceAuthored" : "reading.exercise.provenance", {
              generator: <code>{exercise.generator}</code>,
            })}
          </p>
        </>
      )}
    </section>
  );
}

function Revealed({
  view,
  exercise,
  item,
  index,
  answer,
  check,
  onCheck,
  onShow,
  onOpenRecord,
}: {
  view: ReadingLessonView;
  exercise: ReadingExercise;
  item: ReadingItem;
  index: number;
  answer: string;
  check: SelfCheck | undefined;
  onCheck: (c: SelfCheck) => void;
  onShow: (e: ReadingEvidence) => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [saving, setSaving] = useState(false);
  return (
    <div className="listening-reveal" role="group" aria-label={t("reading.reveal.region", { n: index + 1 })}>
      <p>
        <span className="label">{t("reading.reveal.expected")}</span>{" "}
        <span lang="fr" className="french">
          {item.reference_answer}
        </span>
      </p>
      {item.accepted_alternatives.length > 0 ? (
        <p>
          <span className="label">{t("reading.reveal.alternatives")}</span>{" "}
          <span lang="fr" className="french">
            {item.accepted_alternatives.join(" / ")}
          </span>
        </p>
      ) : null}
      <p>
        <span className="label">{t("reading.reveal.why")}</span>{" "}
        <StoredText primary={item.explanation_en} variants={{ en: item.explanation_en, zh: item.explanation_zh }} kind="explanation" />
      </p>
      <p className="label">{t("reading.reveal.evidence")}</p>
      <ul className="listening-steps">
        {item.evidence.map((e, k) => (
          <li key={k}>
            <span className="hint">{e.segment}</span>{" "}
            <span lang="fr" className="french">
              « {e.excerpt} »
            </span>{" "}
            <button type="button" className="ghost" onClick={() => onShow(e)}>
              {t("reading.evidence.show", { segment: e.segment })}
            </button>
          </li>
        ))}
      </ul>
      {item.wrong_answers.length > 0 ? (
        <>
          <p className="label">{t("reading.reveal.wrong")}</p>
          <ul className="listening-steps">
            {item.wrong_answers.map((w, k) => (
              <li key={k}>
                <span lang="fr" className="french">
                  {w.answer}
                </span>{" "}
                — <StoredText primary={w.why_wrong_en} variants={{ en: w.why_wrong_en, zh: w.why_wrong_zh }} kind="explanation" />
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <div className="actions" role="group" aria-label={t("reading.check.label", { n: index + 1 })}>
        <button type="button" aria-pressed={check === "got"} onClick={() => onCheck("got")}>
          {t("reading.check.got")}
        </button>
        <button type="button" aria-pressed={check === "missed"} onClick={() => onCheck("missed")}>
          {t("reading.check.missed")}
        </button>
        {!saving ? (
          <button type="button" className="ghost" onClick={() => setSaving(true)}>
            {t("reading.save.open")}
          </button>
        ) : null}
      </div>
      {saving ? (
        <SaveMissedPoint view={view} exercise={exercise} item={item} index={index} answer={answer} onCancel={() => setSaving(false)} onOpenRecord={onOpenRecord} />
      ) : null}
    </div>
  );
}

// missedPointContext is the source evidence attached to the learner's record:
// the lesson, its origin and passage version, the source link when there is
// one, the question and the cited excerpts, exactly as stored.
export function missedPointContext(view: ReadingLessonView, exercise: ReadingExercise, item: ReadingItem): string {
  const lines = [
    `Reading lesson #${view.lesson.id}: ${view.lesson.title}`,
    `Passage version ${view.passage.version}${view.lesson.pack_passage_id ? ` (authored example ${view.lesson.pack_passage_id})` : ""}`,
  ];
  if (view.lesson.source_url) lines.push(`Source: ${view.lesson.source_url}`);
  lines.push(`Question (${item.kind}): ${item.question}`);
  for (const e of item.evidence) lines.push(`Excerpt (${e.segment}): « ${e.excerpt} »`);
  lines.push(`Reference answer: ${item.reference_answer}`);
  lines.push(`Exercise #${exercise.id} (${exercise.generator}); practice material, not an official exam item.`);
  return lines.join("\n");
}

type SaveState =
  | { status: "editing" }
  | { status: "saving" }
  | { status: "saved"; entryId: number; created: boolean; duplicate?: boolean }
  | { status: "unknown" }
  | { status: "error"; message: string };

function SaveMissedPoint({
  view,
  exercise,
  item,
  index,
  answer,
  onCancel,
  onOpenRecord,
}: {
  view: ReadingLessonView;
  exercise: ReadingExercise;
  item: ReadingItem;
  index: number;
  answer: string;
  onCancel: () => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  // One capture ID per form: resending after a lost response replays it.
  const [captureId] = useState(() => `reading-${view.lesson.id}-${exercise.id}-${index + 1}-${randomOperationId()}`);
  const [state, setState] = useState<SaveState>({ status: "editing" });
  const [includeAnswer, setIncludeAnswer] = useState(false);
  const context = missedPointContext(view, exercise, item);
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
          source_ref: sourceRef("reading_item", exercise.id, index, includeAnswer ? answer : ""),
        }),
      );
      setState({ status: "saved", entryId: result.entry_id, created: result.created });
    } catch (e) {
      const dup = alreadySaved(e);
      if (dup !== null) setState({ status: "saved", entryId: dup, created: false, duplicate: true });
      else setState(e instanceof NetworkError ? { status: "unknown" } : { status: "error", message: describe(e) });
    }
  };
  const fieldId = `reading-missed-${exercise.id}-${index}`;
  if (state.status === "saved")
    return (
      <div className="banner success" role="status">
        {t(state.duplicate ? "notebook.save.duplicate" : state.created ? "reading.save.saved" : "reading.save.replayed", { id: state.entryId })}{" "}
        {onOpenRecord ? (
          <button type="button" className="ghost" onClick={() => onOpenRecord(state.entryId)}>
            {t("reading.save.openRecord", { id: state.entryId })}
          </button>
        ) : null}
      </div>
    );
  return (
    <form className="listening-save" aria-label={t("reading.save.region", { n: index + 1 })} onSubmit={send}>
      <label htmlFor={fieldId}>{t("reading.save.label")}</label>
      <textarea id={fieldId} rows={3} value={text} required onChange={(e) => setText(e.target.value)} disabled={state.status === "saving"} />
      {answer.trim() ? (
        <label className="notebook-attempt">
          <input type="checkbox" checked={includeAnswer} onChange={(e) => setIncludeAnswer(e.target.checked)} disabled={state.status === "saving"} />{" "}
          {t("notebook.save.includeAnswer", { answer: answer.trim() })}
        </label>
      ) : null}
      <p className="label">{t("reading.save.attached")}</p>
      <pre className="listening-context" lang="fr">
        {context}
      </pre>
      <p className="hint">{t("reading.save.hint")}</p>
      <p className="hint">{t("notebook.save.linked")}</p>
      {state.status === "unknown" ? (
        <div className="banner info" role="alert">
          {t("reading.save.unknown")}
        </div>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {t("reading.save.failed", { message: state.message })}
        </div>
      ) : null}
      <div className="actions">
        <button type="submit" className="primary" disabled={state.status === "saving" || !text.trim()}>
          {state.status === "unknown" ? t("reading.save.retrySame") : t("reading.save.confirm")}
        </button>
        <button type="button" className="ghost" onClick={onCancel} disabled={state.status === "saving"}>
          {t("reading.save.cancel")}
        </button>
      </div>
    </form>
  );
}
