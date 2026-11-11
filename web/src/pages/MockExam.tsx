import { Fragment, useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { StoredText } from "../components/ExplanationText";
import { useI18n } from "../i18n";
import type { ExamPassage, ExamQuestion, ExamResultItem, ExamSessionRow, ExamView, ExamForms } from "../types/exam";
import { randomOperationId } from "./annotationOperation";
import { alreadySaved, sourceRef } from "./notebookLink";

// Mock Exam v1 (private workbench; never in the public demo).
//
// - The server owns the session: its questions are frozen copies of authored
//   reading-pack questions, its deadline is the server's, and every answer is
//   saved to the server as it is chosen, so a reload or a reconnect resumes
//   from the server (no browser storage).
// - Keys, explanations and evidence arrive only after submission or expiry.
// - Submitting twice with the same answers is safe: the server replays the
//   result. A lost response is checked by reading the session back.
// - A missed point becomes a learning record only through the explicit save
//   form; it links the same authored item in Reading. Nothing is scored by a
//   model, and the result is not an official score.

type Load<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };
const describe = (e: unknown) => (e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e));

type Screen = { kind: "home" } | { kind: "session"; id: number };

export function MockExam({ onOpenRecord }: { onOpenRecord?: (entryId: number) => void } = {}) {
  const [screen, setScreen] = useState<Screen>({ kind: "home" });
  const [epoch, setEpoch] = useState(0);
  return (
    <main className="exam">
      {screen.kind === "home" ? (
        <ExamHome epoch={epoch} onOpen={(id) => setScreen({ kind: "session", id })} />
      ) : (
        <ExamSession
          key={screen.id}
          id={screen.id}
          onBack={() => {
            setEpoch((n) => n + 1);
            setScreen({ kind: "home" });
          }}
          onOpen={(id) => setScreen({ kind: "session", id })}
          onOpenRecord={onOpenRecord}
        />
      )}
    </main>
  );
}

function minutes(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function ExamHome({ epoch, onOpen }: { epoch: number; onOpen: (id: number) => void }) {
  const { t, tp } = useI18n();
  const [retry, setRetry] = useState(0);
  const [data, setData] = useState<Load<{ forms: ExamForms; sessions: ExamSessionRow[] }>>({ status: "loading" });
  // One key per start click: a lost response is resent with the same key.
  const [pending, setPending] = useState<{ formId: string; key: string; status: "starting" | "unknown" | "error"; message?: string } | null>(null);
  useEffect(() => {
    let active = true;
    setData({ status: "loading" });
    Promise.all([api.listExamForms(), api.listExamSessions()]).then(
      ([forms, sessions]) => active && setData({ status: "ready", data: { forms, sessions: sessions.sessions } }),
      (e: unknown) => active && setData({ status: "error", message: describe(e) }),
    );
    return () => {
      active = false;
    };
  }, [epoch, retry]);
  const start = async (formId: string, key: string) => {
    setPending({ formId, key, status: "starting" });
    try {
      const v = await api.startExam(formId, key);
      setPending(null);
      onOpen(v.session.id);
    } catch (e) {
      setPending({ formId, key, status: e instanceof NetworkError ? "unknown" : "error", message: describe(e) });
    }
  };
  if (data.status === "loading") return <p className="hint" role="status">{t("exam.loading")}</p>;
  if (data.status === "error")
    return (
      <div className="banner error" role="alert">
        {t("exam.failed", { message: data.message })}{" "}
        <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
          {t("common.retry")}
        </button>
      </div>
    );
  const { forms, sessions } = data.data;
  const open = sessions.filter((s) => s.state === "in_progress");
  return (
    <>
      <section className="panel" aria-labelledby="exam-forms-heading">
        <h2 id="exam-forms-heading">{t("exam.forms.heading")}</h2>
        <p className="hint">{forms.notice}</p>
        <ul className="exam-forms">
          {forms.forms.map((f) => (
            <li key={f.id} className="exam-form">
              <h3 lang="fr">{f.title}</h3>
              <p className="hint">{f.description}</p>
              <p>{t("exam.forms.facts", { count: f.question_count, time: minutes(f.duration_seconds) })}</p>
              {pending?.formId === f.id && pending.status === "unknown" ? (
                <div className="banner info" role="alert">
                  {t("exam.start.unknown")}{" "}
                  <button type="button" onClick={() => start(f.id, pending.key)}>
                    {t("exam.start.retrySame")}
                  </button>
                </div>
              ) : pending?.formId === f.id && pending.status === "error" ? (
                <div className="banner error" role="alert">
                  {t("exam.start.failed", { message: pending.message ?? "" })}
                </div>
              ) : null}
              <button
                type="button"
                className="primary"
                disabled={pending?.status === "starting"}
                onClick={() => start(f.id, pending?.formId === f.id && pending.status === "unknown" ? pending.key : randomOperationId())}
              >
                {t("exam.forms.start", { title: f.title })}
              </button>
            </li>
          ))}
        </ul>
        <p className="hint">{t("exam.forms.rules")}</p>
      </section>
      <section className="panel" aria-labelledby="exam-sessions-heading">
        <h2 id="exam-sessions-heading">{t("exam.sessions.heading")}</h2>
        {open.length > 0 ? <p role="status">{tp("exam.sessions.inProgress", open.length)}</p> : null}
        {sessions.length === 0 ? (
          <p className="empty">{t("exam.sessions.none")}</p>
        ) : (
          <ul className="exam-sessions">
            {sessions.map((s) => (
              <li key={s.id}>
                <span lang="fr">{s.kind === "retry" ? t("exam.sessions.retryTitle", { id: s.retry_of?.session_id ?? 0, n: s.retry_of?.position ?? 0 }) : s.title}</span>{" "}
                <span className="tag">{t(s.state === "in_progress" ? "exam.state.in_progress" : s.state === "submitted" ? "exam.state.submitted" : "exam.state.expired")}</span>{" "}
                {s.result ? <span>{t("exam.sessions.score", { correct: s.result.correct, total: s.result.total })}</span> : null}{" "}
                <button type="button" className={s.state === "in_progress" ? "primary" : "ghost"} onClick={() => onOpen(s.id)}>
                  {s.state === "in_progress" ? t("exam.sessions.resume", { id: s.id }) : t("exam.sessions.results", { id: s.id })}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

type SaveStatus = "saving" | "saved" | "failed";
type SubmitState =
  | { status: "idle" }
  | { status: "confirm" }
  | { status: "submitting" }
  | { status: "lost" }
  | { status: "error"; message: string };

function ExamSession({
  id,
  onBack,
  onOpen,
  onOpenRecord,
}: {
  id: number;
  onBack: () => void;
  onOpen: (id: number) => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [load, setLoad] = useState<Load<ExamView>>({ status: "loading" });
  const [epoch, setEpoch] = useState(0);
  const [choices, setChoices] = useState<Record<number, number | null>>({});
  const [saves, setSaves] = useState<Record<number, SaveStatus>>({});
  const [submit, setSubmit] = useState<SubmitState>({ status: "idle" });
  // Server clock offset: the countdown follows the server's deadline, not the
  // browser's clock.
  const offset = useRef(0);
  const [now, setNow] = useState(() => Date.now());
  const autoSubmitted = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const accept = useCallback((v: ExamView) => {
    const at = Date.now();
    offset.current = Date.parse(v.server_now) - at;
    setNow(at);
    setLoad({ status: "ready", data: v });
    const c: Record<number, number | null> = {};
    for (const a of v.answers) c[a.position] = a.choice;
    setChoices(c);
    setSaves({});
  }, []);

  useEffect(() => {
    let active = true;
    setLoad({ status: "loading" });
    api.getExam(id).then(
      (v) => active && accept(v),
      (e: unknown) => active && setLoad({ status: "error", message: describe(e) }),
    );
    return () => {
      active = false;
    };
  }, [id, epoch, accept]);
  useEffect(() => headingRef.current?.focus(), [load.status]);

  const view = load.status === "ready" ? load.data : null;
  const inProgress = view?.state === "in_progress";
  useEffect(() => {
    if (!inProgress) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [inProgress]);
  const remaining = view && inProgress ? Math.max(0, Math.ceil((Date.parse(view.session.deadline_at) - (now + offset.current)) / 1000)) : 0;

  const doSubmit = useCallback(
    async (answers: Record<number, number | null>) => {
      setSubmit({ status: "submitting" });
      const body: Record<string, number | null> = {};
      for (const [p, c] of Object.entries(answers)) body[p] = c;
      try {
        accept(await api.submitExam(id, body));
        setSubmit({ status: "idle" });
      } catch (e) {
        const closed = e instanceof ApiError && e.status === 409 ? (e.body as { exam?: ExamView } | undefined)?.exam : undefined;
        if (closed) {
          accept(closed);
          setSubmit({ status: "idle" });
        } else if (e instanceof NetworkError) setSubmit({ status: "lost" });
        else setSubmit({ status: "error", message: describe(e) });
      }
    },
    [id, accept],
  );

  // At the server's deadline the page sends what it has once; the server
  // decides (answers saved in time count, anything later does not).
  useEffect(() => {
    if (view && inProgress && remaining === 0 && !autoSubmitted.current) {
      autoSubmitted.current = true;
      void doSubmit(choices);
    }
  }, [view, inProgress, remaining, choices, doSubmit]);

  const choose = async (position: number, choice: number) => {
    setChoices((c) => ({ ...c, [position]: choice }));
    setSaves((s) => ({ ...s, [position]: "saving" }));
    try {
      const r = await api.saveExamAnswer(id, position, choice);
      const at = Date.now();
      offset.current = Date.parse(r.server_now) - at;
      setNow(at);
      setSaves((s) => ({ ...s, [position]: "saved" }));
    } catch (e) {
      const closed = e instanceof ApiError && e.status === 409 ? (e.body as { exam?: ExamView } | undefined)?.exam : undefined;
      if (closed) accept(closed);
      else setSaves((s) => ({ ...s, [position]: "failed" }));
    }
  };

  const back = (
    <button type="button" className="ghost" onClick={onBack}>
      {t("exam.back")}
    </button>
  );
  if (!view)
    return (
      <section className="panel" aria-label={t("exam.session.region")}>
        <h2 ref={headingRef} tabIndex={-1}>
          {t("exam.session.heading", { id })}
        </h2>
        {back}
        {load.status === "loading" ? (
          <p className="hint" role="status">{t("exam.loading")}</p>
        ) : (
          <div className="banner error" role="alert">
            {t("exam.failed", { message: load.status === "error" ? load.message : "" })}{" "}
            <button type="button" className="ghost" onClick={() => setEpoch((n) => n + 1)}>
              {t("common.retry")}
            </button>
          </div>
        )}
      </section>
    );
  const title = view.session.kind === "retry" && view.session.retry_of
    ? t("exam.sessions.retryTitle", { id: view.session.retry_of.session_id, n: view.session.retry_of.position })
    : view.session.title;
  const answered = view.questions.filter((q) => choices[q.position] !== undefined && choices[q.position] !== null).length;
  return (
    <div>
      <section className="panel exam-header" aria-label={t("exam.session.region")}>
        <h2 ref={headingRef} tabIndex={-1} lang="fr">
          {title}
        </h2>
        <div className="actions">{back}</div>
        <p className="hint">{view.notice}</p>
        {inProgress ? (
          <>
            <p className="exam-timer" role="timer" aria-label={t("exam.timer.label")}>
              {t("exam.timer.remaining", { time: minutes(remaining) })}
            </p>
            <TimerAnnouncer remaining={remaining} />
            <p className="hint">{t("exam.progress", { answered, total: view.questions.length })}</p>
            <p className="hint">{t("exam.serverOwned")}</p>
          </>
        ) : null}
      </section>
      {inProgress ? (
        <>
          {view.passages.map((p) => (
            <PassageBlock key={p.id} passage={p} highlight={null}>
              {view.questions
                .filter((q) => q.passage_id === p.id)
                .map((q) => (
                  <QuestionField
                    key={q.position}
                    question={q}
                    choice={choices[q.position] ?? null}
                    save={saves[q.position]}
                    disabled={submit.status === "submitting"}
                    onChoose={(c) => choose(q.position, c)}
                  />
                ))}
            </PassageBlock>
          ))}
          <SubmitPanel
            state={submit}
            unanswered={view.questions.length - answered}
            onAsk={() => setSubmit({ status: "confirm" })}
            onCancel={() => setSubmit({ status: "idle" })}
            onSubmit={() => doSubmit(choices)}
            onCheck={() => {
              setSubmit({ status: "idle" });
              setEpoch((n) => n + 1);
            }}
          />
        </>
      ) : (
        <Results view={view} onOpen={onOpen} onOpenRecord={onOpenRecord} />
      )}
    </div>
  );
}

// TimerAnnouncer speaks only at a few thresholds, never every second.
function TimerAnnouncer({ remaining }: { remaining: number }) {
  const { t } = useI18n();
  const [said, setSaid] = useState("");
  useEffect(() => {
    if (remaining === 300 || remaining === 60) setSaid(t("exam.timer.announce", { time: minutes(remaining) }));
  }, [remaining, t]);
  return (
    <p className="visually-hidden" aria-live="polite">
      {said}
    </p>
  );
}

function marked(text: string, excerpt: string | null): ReactNode {
  if (!excerpt) return text;
  const i = text.indexOf(excerpt);
  if (i < 0) return text;
  return (
    <>
      {text.slice(0, i)}
      <mark>{excerpt}</mark>
      {text.slice(i + excerpt.length)}
    </>
  );
}

function PassageBlock({ passage, highlight, children }: { passage: ExamPassage; highlight: { segment: string; excerpt: string } | null; children?: ReactNode }) {
  const { t } = useI18n();
  return (
    <section className="panel exam-block" aria-label={t("exam.passage.region", { title: passage.title })}>
      <article className="exam-passage reading-passage" lang="fr">
        <h3>{passage.title}</h3>
        {passage.segments.map((s) => (
          <p key={s.id} id={`exam-${passage.id}-${s.id}`}>
            <span className="segment-id" aria-hidden="true">
              {s.id}
            </span>{" "}
            {marked(s.text, highlight && highlight.segment === s.id ? highlight.excerpt : null)}
          </p>
        ))}
      </article>
      {children ? <div className="exam-questions">{children}</div> : null}
    </section>
  );
}

function QuestionField({
  question,
  choice,
  save,
  disabled,
  onChoose,
}: {
  question: ExamQuestion;
  choice: number | null;
  save?: SaveStatus;
  disabled: boolean;
  onChoose: (c: number) => void;
}) {
  const { t } = useI18n();
  const name = `exam-q-${question.position}`;
  return (
    <fieldset className="exam-question">
      <legend>
        {t("exam.question.label", { n: question.position })}{" "}
        <span lang="fr" className="french">
          {question.question}
        </span>
      </legend>
      {question.choices.map((c, i) => (
        <label key={i} className="exam-choice">
          <input type="radio" name={name} checked={choice === i} disabled={disabled} onChange={() => onChoose(i)} />{" "}
          <span lang="fr">{c}</span>
        </label>
      ))}
      {save === "saving" ? (
        <p className="hint" role="status">{t("exam.answer.saving")}</p>
      ) : save === "saved" ? (
        <p className="hint" role="status">{t("exam.answer.saved")}</p>
      ) : save === "failed" && choice !== null ? (
        <div className="banner error" role="alert">
          {t("exam.answer.failed")}{" "}
          <button type="button" className="ghost" onClick={() => onChoose(choice)}>
            {t("exam.answer.retry")}
          </button>
        </div>
      ) : null}
    </fieldset>
  );
}

function SubmitPanel({
  state,
  unanswered,
  onAsk,
  onCancel,
  onSubmit,
  onCheck,
}: {
  state: SubmitState;
  unanswered: number;
  onAsk: () => void;
  onCancel: () => void;
  onSubmit: () => void;
  onCheck: () => void;
}) {
  const { t, tp } = useI18n();
  return (
    <section className="panel" aria-label={t("exam.submit.region")}>
      {state.status === "confirm" ? (
        <div className="banner info" role="alertdialog" aria-label={t("exam.submit.confirmTitle")}>
          <p>{t("exam.submit.confirm")}</p>
          {unanswered > 0 ? <p>{tp("exam.submit.unanswered", unanswered)}</p> : null}
          <div className="actions">
            <button type="button" className="primary" onClick={onSubmit}>
              {t("exam.submit.now")}
            </button>
            <button type="button" className="ghost" onClick={onCancel}>
              {t("exam.submit.keepWorking")}
            </button>
          </div>
        </div>
      ) : state.status === "lost" ? (
        <div className="banner info" role="alert">
          <p>{t("exam.submit.lost")}</p>
          <div className="actions">
            <button type="button" className="primary" onClick={onCheck}>
              {t("exam.submit.check")}
            </button>
            <button type="button" className="ghost" onClick={onSubmit}>
              {t("exam.submit.again")}
            </button>
          </div>
        </div>
      ) : (
        <>
          {state.status === "error" ? (
            <div className="banner error" role="alert">
              {t("exam.submit.failed", { message: state.message })}
            </div>
          ) : null}
          <div className="actions">
            <button type="button" className="primary" disabled={state.status === "submitting"} onClick={onAsk}>
              {state.status === "submitting" ? t("exam.submit.sending") : t("exam.submit.ask")}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function Results({ view, onOpen, onOpenRecord }: { view: ExamView; onOpen: (id: number) => void; onOpenRecord?: (entryId: number) => void }) {
  const { t } = useI18n();
  const r = view.result!;
  const [highlight, setHighlight] = useState<{ passage: string; segment: string; excerpt: string } | null>(null);
  const show = (passage: string, e: { segment: string; excerpt: string }) => {
    setHighlight({ passage, ...e });
    document.getElementById(`exam-${passage}-${e.segment}`)?.scrollIntoView?.({ block: "center" });
  };
  const closedAt = new Date(r.closed_at).toLocaleTimeString();
  return (
    <>
      <section className="panel" aria-label={t("exam.result.region")}>
        <div className={r.closed === "expired" ? "banner info" : "banner success"} role="status">
          {r.closed === "expired" ? t("exam.result.expired", { time: closedAt }) : t("exam.result.submitted", { time: closedAt })}
          {view.replayed ? ` ${t("exam.result.replayed")}` : ""}
        </div>
        <p className="exam-score">{t("exam.result.score", { correct: r.correct, total: r.total })}</p>
        <p className="hint">{t("exam.result.notOfficial")}</p>
      </section>
      {view.passages.map((p) => (
        <PassageBlock key={p.id} passage={p} highlight={highlight && highlight.passage === p.id ? highlight : null}>
          {view.questions
            .filter((q) => q.passage_id === p.id)
            .map((q) => (
              <ResultItem
                key={q.position}
                view={view}
                question={q}
                item={r.items[q.position - 1]}
                onShow={(e) => show(p.id, e)}
                onOpen={onOpen}
                onOpenRecord={onOpenRecord}
              />
            ))}
        </PassageBlock>
      ))}
    </>
  );
}

function ResultItem({
  view,
  question,
  item,
  onShow,
  onOpen,
  onOpenRecord,
}: {
  view: ExamView;
  question: ExamQuestion;
  item: ExamResultItem;
  onShow: (e: { segment: string; excerpt: string }) => void;
  onOpen: (id: number) => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [saving, setSaving] = useState(false);
  const [retry, setRetry] = useState<{ status: "idle" | "starting" } | { status: "error"; message: string; key: string }>({ status: "idle" });
  const startRetry = async (key: string) => {
    setRetry({ status: "starting" });
    try {
      const v = await api.startExamRetry(view.session.id, question.position, key);
      onOpen(v.session.id);
    } catch (e) {
      setRetry({ status: "error", message: describe(e), key });
    }
  };
  return (
    <div className={item.correct ? "exam-result correct" : "exam-result missed"} role="group" aria-label={t("exam.question.label", { n: question.position })}>
      <p>
        <strong>{t("exam.question.label", { n: question.position })}</strong>{" "}
        <span lang="fr" className="french">
          {question.question}
        </span>{" "}
        <span className="tag">{item.correct ? t("exam.result.correct") : item.choice === null ? t("exam.result.unanswered") : t("exam.result.missed")}</span>
      </p>
      <p>
        <span className="label">{t("exam.result.yourAnswer")}</span>{" "}
        {item.choice === null ? <em>{t("exam.result.noAnswer")}</em> : <span lang="fr">{question.choices[item.choice]}</span>}
      </p>
      {!item.correct ? (
        <p>
          <span className="label">{t("exam.result.authoredAnswer")}</span> <span lang="fr">{question.choices[item.key]}</span>
        </p>
      ) : null}
      {item.why_wrong ? (
        <p>
          <span className="label">{t("exam.result.whyWrong")}</span> <StoredText primary={item.why_wrong.en} variants={{ en: item.why_wrong.en, zh: item.why_wrong.zh }} kind="explanation" />
        </p>
      ) : null}
      <p>
        <span className="label">{t("exam.result.why")}</span> <StoredText primary={item.explanation_en} variants={{ en: item.explanation_en, zh: item.explanation_zh }} kind="explanation" />
      </p>
      <div className="actions">
        {item.evidence.map((e, i) => (
          <Fragment key={i}>
            <button type="button" className="ghost" onClick={() => onShow(e)}>
              {t("exam.result.showEvidence", { segment: e.segment })}
            </button>
          </Fragment>
        ))}
      </div>
      <p className="hint">
        {t("exam.result.source", { pack: item.source.pack, passage: item.source.passage_id, question: item.source.question_id, hash: item.source.content_sha256.slice(0, 12) })}
      </p>
      {!item.correct ? (
        <>
          {saving ? <SaveExamMiss view={view} question={question} item={item} onCancel={() => setSaving(false)} onOpenRecord={onOpenRecord} /> : null}
          <div className="actions">
            {!saving ? (
              <button type="button" onClick={() => setSaving(true)}>
                {t("exam.save.open")}
              </button>
            ) : null}
            <button type="button" className="ghost" disabled={retry.status === "starting"} onClick={() => startRetry(retry.status === "error" ? retry.key : randomOperationId())}>
              {t("exam.retry.start")}
            </button>
          </div>
          {retry.status === "error" ? (
            <div className="banner error" role="alert">
              {t("exam.retry.failed", { message: retry.message })}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

type SaveState = { status: "editing" | "saving" } | { status: "saved"; entryId: number; duplicate: boolean } | { status: "unknown" } | { status: "error"; message: string };

// SaveExamMiss saves a missed point after explicit confirmation. The record
// links the same authored item in Reading (importing the authored example
// first, which makes no model call), so it appears in the Mistake Notebook
// with its exact source.
function SaveExamMiss({
  view,
  question,
  item,
  onCancel,
  onOpenRecord,
}: {
  view: ExamView;
  question: ExamQuestion;
  item: ExamResultItem;
  onCancel: () => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [includeAnswer, setIncludeAnswer] = useState(false);
  const [captureId] = useState(() => `exam-${view.session.id}-${question.position}-${randomOperationId()}`);
  const [state, setState] = useState<SaveState>({ status: "editing" });
  const chosen = item.choice === null ? "" : question.choices[item.choice];
  const context = [
    t("exam.save.contextLine", { title: view.session.title, id: view.session.id, n: question.position }),
    `${item.source.pack}/${item.source.passage_id} — ${item.source.question_id}`,
    `Question : ${question.question}`,
  ].join("\n");
  const send = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!text.trim()) return;
    setState({ status: "saving" });
    try {
      const lesson = await api.importReadingExample(item.source.passage_id);
      const exercise = lesson.exercises.find((e) => e.generator.startsWith("authored:") && e.passage_id === lesson.passage.id);
      if (!exercise) throw new Error(t("exam.save.noExercise"));
      const result = await api.importCapture(
        JSON.stringify({
          schema_version: "learning_capture_v1",
          capture_id: captureId,
          source: "manual",
          original_input: text,
          original_context: context,
          source_ref: sourceRef("reading_item", exercise.id, item.source.pack_item - 1, includeAnswer ? chosen : ""),
        }),
      );
      setState({ status: "saved", entryId: result.entry_id, duplicate: false });
    } catch (e) {
      const dup = alreadySaved(e);
      if (dup !== null) setState({ status: "saved", entryId: dup, duplicate: true });
      else setState(e instanceof NetworkError ? { status: "unknown" } : { status: "error", message: describe(e) });
    }
  };
  if (state.status === "saved")
    return (
      <div className="banner success" role="status">
        {t(state.duplicate ? "notebook.save.duplicate" : "exam.save.saved", { id: state.entryId })}{" "}
        {onOpenRecord ? (
          <button type="button" className="ghost" onClick={() => onOpenRecord(state.entryId)}>
            {t("reading.save.openRecord", { id: state.entryId })}
          </button>
        ) : null}
      </div>
    );
  const fieldId = `exam-missed-${view.session.id}-${question.position}`;
  return (
    <form className="listening-save" aria-label={t("exam.save.region", { n: question.position })} onSubmit={send}>
      <label htmlFor={fieldId}>{t("exam.save.label")}</label>
      <textarea id={fieldId} rows={3} value={text} required onChange={(e) => setText(e.target.value)} disabled={state.status === "saving"} />
      {chosen ? (
        <label className="notebook-attempt">
          <input type="checkbox" checked={includeAnswer} onChange={(e) => setIncludeAnswer(e.target.checked)} disabled={state.status === "saving"} />{" "}
          {t("notebook.save.includeAnswer", { answer: chosen })}
        </label>
      ) : null}
      <p className="label">{t("reading.save.attached")}</p>
      <pre className="listening-context" lang="fr">
        {context}
      </pre>
      <p className="hint">{t("exam.save.hint")}</p>
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
