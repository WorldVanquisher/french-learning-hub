import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { StoredText } from "../components/ExplanationText";
import { useI18n, type MessageKey } from "../i18n";
import type {
  WritingCorrection,
  WritingDraft,
  WritingFeedback,
  WritingPrompts,
  WritingRequest,
  WritingTaskSummary,
  WritingTaskView,
} from "../types/writing";
import { randomOperationId } from "./annotationOperation";

// Exam Writing v1 (private workbench only; never in the public demo).
//
// - A task is an authored practice prompt or the learner's own. Every saved
//   draft is an immutable version; a revision is a new version, and the
//   original is never overwritten. Drafting, revising and comparing call no
//   provider.
// - Feedback is one explicit request for one selected version, under a key,
//   with the Listening/Reading recovery rules. A report always says which
//   version it is about and is never carried over to another one.
// - Hints are shown first; the suggested wording and its reason only on
//   request. Quoted spans are highlighted only when the server located them
//   exactly once in that version; a repeated or missing quote gets no position.
// - One mistake becomes a learning record only through an explicit "Save
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
  // A reload of the same key keeps showing the last data, so an unsaved
  // revision in the editor is never unmounted by a refresh.
  if (state.key === key && (state.epoch === epoch || state.load.status === "ready")) return state.load;
  return { status: "loading" };
}

const occurrences = (text: string, quote: string) => (quote === "" ? 0 : text.split(quote).length - 1);

// shownAsGrounded is a display guard on the server's grounding: a correction is
// shown against the text only when its quote really occurs in this version
// (exactly once for "located"). Anything else is listed as not found.
export function shownAsGrounded(text: string, k: WritingCorrection): boolean {
  const n = occurrences(text, k.quote);
  return (k.grounding === "located" && n === 1) || (k.grounding === "ambiguous" && n > 1);
}

// countWords mirrors the backend convention shown to the learner.
export function countWords(text: string): number {
  return (text.match(/[\p{L}\p{N}]+(?:['’-][\p{L}\p{N}]+)*/gu) ?? []).length;
}

export type DiffPart = { op: "same" | "del" | "add"; text: string };

// diffWords is a word-level longest-common-subsequence diff (whitespace kept).
export function diffWords(before: string, after: string): DiffPart[] {
  const a = before.split(/(\s+)/).filter((t) => t !== "");
  const b = after.split(/(\s+)/).filter((t) => t !== "");
  const n = a.length;
  const m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: DiffPart[] = [];
  const push = (op: DiffPart["op"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.op === op) last.text += text;
    else out.push({ op, text });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      push("same", a[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) push("del", a[i++]);
    else push("add", b[j++]);
  }
  while (i < n) push("del", a[i++]);
  while (j < m) push("add", b[j++]);
  return out;
}

const ratingKey: Record<"met" | "partly_met" | "not_met", MessageKey> = {
  met: "writing.rating.met",
  partly_met: "writing.rating.partly_met",
  not_met: "writing.rating.not_met",
};
const failureKey: Record<"provider_timeout" | "provider_unavailable" | "invalid_output", MessageKey> = {
  provider_timeout: "writing.failure.provider_timeout",
  provider_unavailable: "writing.failure.provider_unavailable",
  invalid_output: "writing.failure.invalid_output",
};

export function Writing({ onOpenRecord }: { onOpenRecord?: (entryId: number) => void } = {}) {
  const [screen, setScreen] = useState<{ kind: "list" } | { kind: "task"; id: number }>({ kind: "list" });
  const [epoch, setEpoch] = useState(0);
  return (
    <main className="writing">
      {screen.kind === "list" ? (
        <TaskList epoch={epoch} onOpen={(id) => setScreen({ kind: "task", id })} />
      ) : (
        <TaskScreen
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

function TaskList({ epoch, onOpen }: { epoch: number; onOpen: (id: number) => void }) {
  const { t, tp } = useI18n();
  const [retry, setRetry] = useState(0);
  const prompts = useLoad<WritingPrompts>("prompts", () => api.listWritingPrompts(), epoch * 100 + retry);
  const tasks = useLoad<{ tasks: WritingTaskSummary[] }>("tasks", () => api.listWritingTasks(), epoch * 100 + retry);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const start = async (promptId: string) => {
    setBusy(true);
    setError(null);
    try {
      onOpen((await api.startWritingPrompt(promptId)).task.id);
    } catch (e) {
      setError(e instanceof NetworkError ? t("writing.prompts.unknown") : t("writing.prompts.failed", { message: describe(e) }));
      setBusy(false);
    }
  };
  return (
    <>
      <section className="panel" aria-label={t("writing.prompts.region")}>
        <h2>{t("writing.prompts.heading")}</h2>
        <p className="hint">{t("writing.prompts.hint")}</p>
        {prompts.status === "ready" ? (
          <ul className="listening-list">
            {prompts.data.prompts.map((p) => (
              <li key={p.id}>
                <span className="reading-example-title">{p.title}</span>{" "}
                <span className="hint">{t("writing.prompts.meta", { format: p.format, min: p.word_min, max: p.word_max })}</span>{" "}
                {p.started_task_id !== null ? (
                  <button type="button" className="ghost" onClick={() => onOpen(p.started_task_id!)}>
                    {t("writing.prompts.open")}
                  </button>
                ) : (
                  <button type="button" disabled={busy} onClick={() => start(p.id)}>
                    {t("writing.prompts.start")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        ) : prompts.status === "error" ? (
          <p className="hint" role="status">{t("writing.prompts.failed", { message: prompts.message })}</p>
        ) : (
          <p className="hint" role="status">{t("writing.loading")}</p>
        )}
        {error ? (
          <div className="banner error" role="alert">
            {error}
          </div>
        ) : null}
      </section>
      <OwnTaskForm onSaved={onOpen} />
      <section className="panel" aria-label={t("writing.list.region")}>
        <h2>{t("writing.list.heading")}</h2>
        {tasks.status === "loading" ? (
          <p className="hint" role="status">{t("writing.loading")}</p>
        ) : tasks.status === "error" ? (
          <div className="banner error" role="alert">
            {t("writing.list.failed", { message: tasks.message })}{" "}
            <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
              {t("common.retry")}
            </button>
          </div>
        ) : tasks.data.tasks.length === 0 ? (
          <p className="empty">{t("writing.list.empty")}</p>
        ) : (
          <ul className="listening-list">
            {tasks.data.tasks.map((row) => (
              <li key={row.task.id}>
                <button type="button" className="link-button" onClick={() => onOpen(row.task.id)}>
                  {row.task.title}
                </button>{" "}
                <span className="tag">{tp("writing.list.versions", row.versions)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function OwnTaskForm({ onSaved }: { onSaved: (id: number) => void }) {
  const { t } = useI18n();
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [points, setPoints] = useState("");
  const [state, setState] = useState<{ status: "idle" | "saving" } | { status: "error"; message: string }>({ status: "idle" });
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setState({ status: "saving" });
    try {
      const requirements = points.split("\n").map((s) => s.trim()).filter(Boolean);
      onSaved((await api.createWritingTask({ title, prompt, requirements })).task.id);
    } catch (e) {
      setState({ status: "error", message: e instanceof NetworkError ? t("writing.own.unknown") : t("writing.own.failed", { message: describe(e) }) });
    }
  };
  return (
    <form className="panel listening-add" aria-label={t("writing.own.region")} onSubmit={submit}>
      <h2>{t("writing.own.heading")}</h2>
      <label htmlFor="writing-title">{t("writing.own.title")}</label>
      <input id="writing-title" type="text" value={title} required maxLength={200} onChange={(e) => setTitle(e.target.value)} />
      <label htmlFor="writing-prompt">{t("writing.own.prompt")}</label>
      <textarea id="writing-prompt" lang="fr" rows={3} value={prompt} required onChange={(e) => setPrompt(e.target.value)} />
      <label htmlFor="writing-points">{t("writing.own.points")}</label>
      <textarea id="writing-points" lang="fr" rows={3} value={points} onChange={(e) => setPoints(e.target.value)} />
      <p className="hint">{t("writing.own.hint")}</p>
      {state.status === "error" ? (
        <div className="banner error" role="alert">
          {state.message}
        </div>
      ) : null}
      <div className="actions">
        <button type="submit" className="primary" disabled={state.status === "saving"}>
          {t("writing.own.save")}
        </button>
      </div>
    </form>
  );
}

function TaskScreen({ id, onBack, onOpenRecord }: { id: number; onBack: () => void; onOpenRecord?: (entryId: number) => void }) {
  const { t } = useI18n();
  const [epoch, setEpoch] = useState(0);
  const view = useLoad<WritingTaskView>(String(id), () => api.getWritingTask(id), epoch);
  const [selected, setSelected] = useState<number | null>(null); // version number; null = latest
  const [highlight, setHighlight] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), [view.status]);
  const back = (
    <button type="button" className="ghost" onClick={onBack}>
      {t("writing.back")}
    </button>
  );
  if (view.status !== "ready")
    return (
      <section className="panel" aria-label={t("writing.task.region")}>
        <h2 ref={headingRef} tabIndex={-1}>
          {t("writing.task.heading", { id })}
        </h2>
        {back}
        {view.status === "loading" ? (
          <p className="hint" role="status">{t("writing.loading")}</p>
        ) : (
          <div className="banner error" role="alert">
            {t("writing.task.failed", { message: view.message })}{" "}
            <button type="button" className="ghost" onClick={() => setEpoch((n) => n + 1)}>
              {t("common.retry")}
            </button>
          </div>
        )}
      </section>
    );
  const v = view.data;
  const latest = v.drafts[v.drafts.length - 1] ?? null;
  const draft = v.drafts.find((d) => d.version === selected) ?? latest;
  const reload = () => setEpoch((n) => n + 1);
  return (
    <div>
      <section className="panel" aria-label={t("writing.task.region")}>
        <h2 ref={headingRef} tabIndex={-1} className="library-title">
          {v.task.title}
        </h2>
        <div className="actions">{back}</div>
        <p lang="fr" className="french">
          {v.task.prompt}
        </p>
        {v.task.requirements.length > 0 ? (
          <ul className="listening-steps">
            {v.task.requirements.map((r, i) => (
              <li key={i} lang="fr" className="french">
                {r}
              </li>
            ))}
          </ul>
        ) : null}
        <p className="hint">{t("writing.task.range", { min: v.task.word_min, max: v.task.word_max })}</p>
        <p className="hint">{t("writing.task.convention")}</p>
        <p className="hint">{t("writing.practiceNotice")}</p>
      </section>
      {draft ? (
        <>
          <VersionsPanel view={v} draft={draft} highlight={highlight} onSelect={(n) => { setSelected(n); setHighlight(null); }} />
          <ComparePanel drafts={v.drafts} current={draft} />
          <FeedbackSection view={v} draft={draft} onChanged={reload} onHighlight={setHighlight} onOpenRecord={onOpenRecord} />
        </>
      ) : null}
      <EditorPanel
        key={latest?.id ?? 0}
        taskId={v.task.id}
        latest={latest}
        promptId={v.task.prompt_id}
        onSaved={(version) => {
          setSelected(version);
          setHighlight(null);
          reload();
        }}
      />
    </div>
  );
}

function VersionsPanel({ view, draft, highlight, onSelect }: { view: WritingTaskView; draft: WritingDraft; highlight: string | null; onSelect: (v: number) => void }) {
  const { t } = useI18n();
  const hit = highlight ? draft.text.indexOf(highlight) : -1;
  return (
    <section className="panel" aria-label={t("writing.versions.region")}>
      <h3>{t("writing.versions.heading")}</h3>
      <div className="view-tabs" role="group" aria-label={t("writing.versions.choose")}>
        {view.drafts.map((d) => (
          <button key={d.id} type="button" aria-pressed={d.id === draft.id} onClick={() => onSelect(d.version)}>
            {t("writing.versions.item", { version: d.version, words: d.word_count })}
          </button>
        ))}
      </div>
      <p className="hint">
        {t("writing.versions.shown", { version: draft.version, words: draft.word_count, min: view.task.word_min, max: view.task.word_max })}
      </p>
      <pre className="writing-draft" lang="fr" aria-label={t("writing.versions.text", { version: draft.version })}>
        {hit >= 0 && highlight ? (
          <>
            {draft.text.slice(0, hit)}
            <mark>{highlight}</mark>
            {draft.text.slice(hit + highlight.length)}
          </>
        ) : (
          draft.text
        )}
      </pre>
    </section>
  );
}

function ComparePanel({ drafts, current }: { drafts: WritingDraft[]; current: WritingDraft }) {
  const { t } = useI18n();
  const others = drafts.filter((d) => d.id !== current.id);
  const [baseVersion, setBaseVersion] = useState<number>(drafts[0]?.version ?? 1);
  const base = others.find((d) => d.version === baseVersion) ?? others[others.length - 1];
  // Always shown from the older version to the newer one.
  const [older, newer] = base && base.version > current.version ? [current, base] : [base, current];
  const parts = useMemo(() => (older ? diffWords(older.text, newer.text) : []), [older, newer]);
  if (!base || !older) return null;
  return (
    <section className="panel" aria-label={t("writing.compare.region")}>
      <h3>{t("writing.compare.heading", { a: older.version, b: newer.version })}</h3>
      <label htmlFor="writing-compare-base">{t("writing.compare.with")}</label>{" "}
      <select id="writing-compare-base" value={base.version} onChange={(e) => setBaseVersion(Number(e.target.value))}>
        {others.map((d) => (
          <option key={d.id} value={d.version}>
            {t("writing.compare.option", { version: d.version })}
          </option>
        ))}
      </select>
      <p className="hint">{t("writing.compare.legend")}</p>
      <pre className="writing-draft writing-diff" lang="fr">
        {parts.map((p, i) =>
          p.op === "same" ? <span key={i}>{p.text}</span> : p.op === "del" ? <del key={i}>{p.text}</del> : <ins key={i}>{p.text}</ins>,
        )}
      </pre>
    </section>
  );
}

function EditorPanel({
  taskId,
  latest,
  promptId,
  onSaved,
}: {
  taskId: number;
  latest: WritingDraft | null;
  promptId: string | null;
  onSaved: (version: number) => void;
}) {
  const { t } = useI18n();
  const [text, setText] = useState(latest?.text ?? "");
  const [state, setState] = useState<{ status: "idle" | "saving" } | { status: "error"; message: string }>({ status: "idle" });
  const [example, setExample] = useState<string | null>(null);
  useEffect(() => {
    if (latest || !promptId) return;
    let active = true;
    api.listWritingPrompts().then(
      (p) => active && setExample(p.prompts.find((x) => x.id === promptId)?.example_draft ?? null),
      () => undefined,
    );
    return () => {
      active = false;
    };
  }, [latest, promptId]);
  const next = (latest?.version ?? 0) + 1;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setState({ status: "saving" });
    try {
      await api.saveWritingDraft(taskId, text);
      onSaved(next);
    } catch (e) {
      const unchanged = e instanceof ApiError && (e.body as { code?: string } | undefined)?.code === "unchanged";
      setState({
        status: "error",
        message: unchanged ? t("writing.editor.unchanged") : e instanceof NetworkError ? t("writing.editor.unknown") : t("writing.editor.failed", { message: describe(e) }),
      });
    }
  };
  return (
    <form className="panel listening-add" aria-label={t("writing.editor.region")} onSubmit={submit}>
      <h3>{latest ? t("writing.editor.reviseHeading", { version: next }) : t("writing.editor.firstHeading")}</h3>
      <p className="hint">{latest ? t("writing.editor.reviseHint", { version: latest.version }) : t("writing.editor.firstHint")}</p>
      {example && !latest ? (
        <div className="actions">
          <button type="button" className="ghost" onClick={() => setText(example)}>
            {t("writing.editor.useExample")}
          </button>
        </div>
      ) : null}
      <label htmlFor={`writing-editor-${taskId}`}>{t("writing.editor.label", { version: next })}</label>
      <textarea id={`writing-editor-${taskId}`} lang="fr" rows={10} value={text} required onChange={(e) => setText(e.target.value)} />
      <p className="hint" role="status">
        {t("writing.editor.count", { words: countWords(text) })}
      </p>
      {state.status === "error" ? (
        <div className="banner error" role="alert">
          {state.message}
        </div>
      ) : null}
      <div className="actions">
        <button type="submit" className="primary" disabled={state.status === "saving" || !text.trim()}>
          {t("writing.editor.save", { version: next })}
        </button>
      </div>
    </form>
  );
}

type RequestState =
  | { status: "idle" }
  | { status: "sending" }
  | { status: "unknown"; key: string; confirm: boolean }
  | { status: "error"; message: string };

function FeedbackSection({
  view,
  draft,
  onChanged,
  onHighlight,
  onOpenRecord,
}: {
  view: WritingTaskView;
  draft: WritingDraft;
  onChanged: () => void;
  onHighlight: (quote: string | null) => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [state, setState] = useState<RequestState>({ status: "idle" });
  const reports = view.feedback.filter((f) => f.draft_id === draft.id);
  const elsewhere = [...new Set(view.feedback.filter((f) => f.draft_id !== draft.id && f.status === "completed").map((f) => view.drafts.find((d) => d.id === f.draft_id)?.version))]
    .filter((n): n is number => n !== undefined)
    .sort((a, b) => a - b);
  const latestRequest: WritingRequest | undefined = view.requests.find((r) => r.draft_id === draft.id);
  const anyInProgress = view.requests.some((r) => r.state === "in_progress");
  const unknown = latestRequest?.state === "unknown";
  const check = async (key: string, confirm: boolean) => {
    try {
      await api.getWritingFeedbackRequest(key);
      onChanged();
    } catch {
      setState({ status: "unknown", key, confirm });
    }
  };
  const send = async (key: string, confirm: boolean) => {
    setState({ status: "sending" });
    try {
      await api.requestWritingFeedback(draft.id, key, confirm);
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
      setState({ status: "error", message: t("writing.feedback.failed", { message: describe(e) }) });
    }
  };
  const lastFailed = reports[0]?.status === "failed" && !unknown ? reports[0] : null;
  const completed = reports.find((f) => f.status === "completed") ?? null;
  return (
    <section className="panel" aria-label={t("writing.feedback.region")}>
      <h3>{t("writing.feedback.heading", { version: draft.version })}</h3>
      {elsewhere.length > 0 ? <p className="hint">{t("writing.feedback.elsewhere", { versions: elsewhere.map((n) => `v${n}`).join(", ") })}</p> : null}
      {!view.generation.enabled ? (
        <p className="hint">{t("writing.feedback.disabled")}</p>
      ) : anyInProgress ? (
        <div className="banner info" role="status">
          {t("writing.feedback.inProgress")}{" "}
          <button type="button" className="ghost" onClick={onChanged}>
            {t("writing.checkAgain")}
          </button>
        </div>
      ) : (
        <>
          <p className="hint">{t("writing.feedback.hint", { version: draft.version, generator: view.generation.generator ?? "" })}</p>
          {unknown ? (
            <div className="banner info" role="status">
              {t("writing.feedback.outcomeUnknown")}
            </div>
          ) : null}
          {lastFailed ? (
            <div className="banner error" role="status">
              {t("writing.feedback.lastFailed", { reason: t(failureKey[lastFailed.failure_code ?? "provider_unavailable"]) })}
            </div>
          ) : null}
          <button type="button" className={unknown ? "ghost" : "primary"} disabled={state.status === "sending"} onClick={() => send(randomOperationId(), unknown)}>
            {state.status === "sending"
              ? t("writing.feedback.sending")
              : unknown
                ? t("writing.feedback.retryUnknown")
                : t("writing.feedback.button", { version: draft.version })}
          </button>
        </>
      )}
      {state.status === "unknown" ? (
        <div className="banner info" role="alert">
          {t("writing.feedback.lost")}{" "}
          <button type="button" className="ghost" onClick={() => check(state.key, state.confirm)}>
            {t("writing.checkAgain")}
          </button>
          <button type="button" className="ghost" onClick={() => send(state.key, state.confirm)}>
            {t("writing.sendSame")}
          </button>
        </div>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {state.message}
        </div>
      ) : null}
      {completed ? <Report view={view} draft={draft} report={completed} onHighlight={onHighlight} onOpenRecord={onOpenRecord} /> : null}
    </section>
  );
}

function Report({
  view,
  draft,
  report,
  onHighlight,
  onOpenRecord,
}: {
  view: WritingTaskView;
  draft: WritingDraft;
  report: WritingFeedback;
  onHighlight: (quote: string | null) => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t, tn } = useI18n();
  const c = report.content!;
  const all = c.corrections.map((k, i) => ({ k, i }));
  const grounded = all.filter(({ k }) => shownAsGrounded(draft.text, k));
  const missing = all.filter(({ k }) => !shownAsGrounded(draft.text, k));
  return (
    <div className="writing-report" role="group" aria-label={t("writing.report.region", { version: draft.version })}>
      <p className="hint">{tn("writing.report.about", { version: <strong>{draft.version}</strong>, generator: <code>{report.generator}</code> })}</p>
      <p>
        <span className="label">{t("writing.report.task")}</span> <span className="tag">{t(ratingKey[c.task_fulfilment.rating])}</span>{" "}
        <StoredText primary={c.task_fulfilment.comment_en} variants={{ en: c.task_fulfilment.comment_en, zh: c.task_fulfilment.comment_zh }} kind="explanation" />
      </p>
      <p>
        <span className="label">{t("writing.report.clarity")}</span>{" "}
        <StoredText primary={c.clarity.comment_en} variants={{ en: c.clarity.comment_en, zh: c.clarity.comment_zh }} kind="explanation" />
      </p>
      {c.corrections.length === 0 ? <p className="hint">{t("writing.report.none")}</p> : null}
      <ol className="listening-items">
        {grounded.map(({ k, i }) => (
          <CorrectionItem key={i} view={view} draft={draft} report={report} k={k} index={i} onHighlight={onHighlight} onOpenRecord={onOpenRecord} />
        ))}
      </ol>
      {missing.length > 0 ? (
        <section className="library-section" aria-label={t("writing.report.missingRegion")}>
          <h4>{t("writing.report.missingHeading")}</h4>
          <p className="hint">{t("writing.report.missingHint")}</p>
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

function CorrectionItem({
  view,
  draft,
  report,
  k,
  index,
  onHighlight,
  onOpenRecord,
}: {
  view: WritingTaskView;
  draft: WritingDraft;
  report: WritingFeedback;
  k: WritingCorrection;
  index: number;
  onHighlight: (quote: string | null) => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [showSuggestion, setShowSuggestion] = useState(false);
  const [saving, setSaving] = useState(false);
  return (
    // The marker is the correction's number in the report, so it matches its
    // label even when an earlier correction is listed as not found.
    <li className="listening-item" value={index + 1} role="group" aria-label={t("writing.correction.region", { n: index + 1 })}>
      <p>
        <span lang="fr" className="french">
          « {k.quote} »
        </span>{" "}
        <span className="tag">{t(`writing.category.${k.category}` as MessageKey)}</span>{" "}
        {k.grounding === "located" ? (
          <button type="button" className="ghost" onClick={() => onHighlight(k.quote)}>
            {t("writing.correction.show", { version: draft.version })}
          </button>
        ) : (
          <span className="hint">{t("writing.correction.ambiguous")}</span>
        )}
      </p>
      <p>
        <span className="label">{t("writing.correction.hint")}</span>{" "}
        <StoredText primary={k.hint_en} variants={{ en: k.hint_en, zh: k.hint_zh }} kind="explanation" />
      </p>
      {showSuggestion ? (
        <>
          <p>
            <span className="label">{t("writing.correction.suggestion")}</span>{" "}
            <span lang="fr" className="french">
              {k.suggestion}
            </span>
          </p>
          <p>
            <span className="label">{t("writing.correction.reason")}</span>{" "}
            <StoredText primary={k.reason_en} variants={{ en: k.reason_en, zh: k.reason_zh }} kind="explanation" />
          </p>
        </>
      ) : null}
      <div className="actions">
        {!showSuggestion ? (
          <button type="button" onClick={() => setShowSuggestion(true)}>
            {t("writing.correction.reveal")}
          </button>
        ) : null}
        {!saving ? (
          <button type="button" className="ghost" onClick={() => setSaving(true)}>
            {t("writing.capture.open")}
          </button>
        ) : null}
      </div>
      {saving ? <CaptureMistake view={view} draft={draft} report={report} k={k} index={index} onCancel={() => setSaving(false)} onOpenRecord={onOpenRecord} /> : null}
    </li>
  );
}

// mistakeContext links the record back to the writing task and the exact version.
export function mistakeContext(view: WritingTaskView, draft: WritingDraft, report: WritingFeedback, k: WritingCorrection): string {
  return [
    `Writing task #${view.task.id}: ${view.task.title}${view.task.prompt_id ? ` (authored prompt ${view.task.prompt_id})` : ""}`,
    `Draft version ${draft.version}, feedback #${report.id} (${report.generator})`,
    `Category: ${k.category}`,
    `Hint: ${k.hint_en}`,
    `Suggested wording: ${k.suggestion}`,
    "Practice feedback, not an exam score.",
  ].join("\n");
}

// mistakeInput is the record itself: the learner's phrase, their revised
// wording and the stored explanation (both languages, as stored).
export function mistakeInput(k: WritingCorrection, revised: string): string {
  return [`« ${k.quote} » → « ${revised.trim()} »`, k.reason_en, k.reason_zh].join("\n");
}

type CaptureState = { status: "editing" | "saving" } | { status: "saved"; entryId: number; created: boolean } | { status: "unknown" } | { status: "error"; message: string };

function CaptureMistake({
  view,
  draft,
  report,
  k,
  index,
  onCancel,
  onOpenRecord,
}: {
  view: WritingTaskView;
  draft: WritingDraft;
  report: WritingFeedback;
  k: WritingCorrection;
  index: number;
  onCancel: () => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [revised, setRevised] = useState("");
  const [captureId] = useState(() => `writing-${view.task.id}-${draft.id}-${report.id}-${index + 1}-${randomOperationId()}`);
  const [state, setState] = useState<CaptureState>({ status: "editing" });
  const context = mistakeContext(view, draft, report, k);
  const input = mistakeInput(k, revised);
  const send = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!revised.trim()) return;
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
        {t(state.created ? "writing.capture.saved" : "writing.capture.replayed", { id: state.entryId })}{" "}
        {onOpenRecord ? (
          <button type="button" className="ghost" onClick={() => onOpenRecord(state.entryId)}>
            {t("writing.capture.openRecord", { id: state.entryId })}
          </button>
        ) : null}
      </div>
    );
  const fieldId = `writing-capture-${report.id}-${index}`;
  return (
    <form className="listening-save" aria-label={t("writing.capture.region", { n: index + 1 })} onSubmit={send}>
      <p>
        <span className="label">{t("writing.capture.original")}</span>{" "}
        <span lang="fr" className="french">
          « {k.quote} »
        </span>
      </p>
      <label htmlFor={fieldId}>{t("writing.capture.revised")}</label>
      <input id={fieldId} type="text" lang="fr" value={revised} required onChange={(e) => setRevised(e.target.value)} disabled={state.status === "saving"} />
      <p className="label">{t("writing.capture.attached")}</p>
      <pre className="listening-context" lang="fr">
        {context}
      </pre>
      <p className="hint">{t("writing.capture.hint")}</p>
      {state.status === "unknown" ? (
        <div className="banner info" role="alert">
          {t("writing.capture.unknown")}
        </div>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {t("writing.capture.failed", { message: state.message })}
        </div>
      ) : null}
      <div className="actions">
        <button type="submit" className="primary" disabled={state.status === "saving" || !revised.trim()}>
          {state.status === "unknown" ? t("writing.capture.retrySame") : t("writing.capture.confirm")}
        </button>
        <button type="button" className="ghost" onClick={onCancel} disabled={state.status === "saving"}>
          {t("writing.capture.cancel")}
        </button>
      </div>
    </form>
  );
}
