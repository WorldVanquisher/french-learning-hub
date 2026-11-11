import { useEffect, useState, type FormEvent } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import { StoredText } from "../components/ExplanationText";
import { useI18n, type MessageKey } from "../i18n";
import { sourceOpen, type KindConcepts, type KindView, type NotebookItem, type Skill, type SourceOpen } from "../types/notebook";

// Mistake Notebook v1 (private workbench only; never in the public demo).
//
// - Items are ordinary learning records saved from an exercise with a source
//   link. What an item shows (prompt, the learner's own words or included
//   answer, the reference) is read from that stored item, never from prose.
//   Records saved without a link are never linked by guessing.
// - "Mark for retry" is the learner's explicit, append-only decision. A retry
//   session follows Recall Practice: the reference stays hidden until Reveal,
//   and the self-check stays in this page: it is never sent, scored, scheduled
//   or turned into a Concept judgment.
// - Grammar / Vocabulary list Concepts by the kinds of their current
//   supporting units (concept_kind_view_v1); anything else stays unclassified.

type Mode = "mistakes" | "retry" | KindView;
type Load<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };

const describe = (e: unknown) => (e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e));
const SKILLS: Skill[] = ["listening", "reading", "writing", "speaking"];
const skillKey: Record<Skill, MessageKey> = {
  listening: "notebook.skill.listening",
  reading: "notebook.skill.reading",
  writing: "notebook.skill.writing",
  speaking: "notebook.skill.speaking",
};

function useNotebook(filter: { skill?: Skill; marked?: boolean }, epoch: number): [Load<NotebookItem[]>, (it: NotebookItem) => void] {
  const [state, setState] = useState<Load<NotebookItem[]>>({ status: "loading" });
  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    api.listNotebookItems(filter).then(
      (r) => active && setState({ status: "ready", data: r.items }),
      (e: unknown) => active && setState({ status: "error", message: describe(e) }),
    );
    return () => {
      active = false;
    };
    // The filter's fields and the epoch identify the request.
  }, [filter.skill, filter.marked, epoch]);
  const replace = (it: NotebookItem) =>
    setState((s) => (s.status === "ready" ? { status: "ready", data: s.data.map((x) => (x.entry_id === it.entry_id ? it : x)) } : s));
  return [state, replace];
}

export function MistakeNotebook({
  onOpenSource,
  onOpenRecord,
  onOpenConcept,
}: {
  onOpenSource?: (open: SourceOpen) => void;
  onOpenRecord?: (entryId: number) => void;
  onOpenConcept?: (conceptId: number) => void;
} = {}) {
  const { t } = useI18n();
  const [mode, setMode] = useState<Mode>("mistakes");
  const modes: [Mode, MessageKey][] = [
    ["mistakes", "notebook.mode.mistakes"],
    ["retry", "notebook.mode.retry"],
    ["grammar", "notebook.mode.grammar"],
    ["vocabulary", "notebook.mode.vocabulary"],
    ["unclassified", "notebook.mode.unclassified"],
  ];
  return (
    <main className="notebook">
      <div className="view-tabs review-modes" role="group" aria-label={t("notebook.mode.label")}>
        {modes.map(([m, key]) => (
          <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)}>
            {t(key)}
          </button>
        ))}
      </div>
      {mode === "mistakes" ? (
        <MistakeList onOpenSource={onOpenSource} onOpenRecord={onOpenRecord} />
      ) : mode === "retry" ? (
        <RetrySession onOpenSource={onOpenSource} />
      ) : (
        <ConceptKinds key={mode} kind={mode} onOpenConcept={onOpenConcept} />
      )}
    </main>
  );
}

// sourceLine names the exact stored item, from its link.
export function SourceLine({ item }: { item: NotebookItem }) {
  const { t } = useI18n();
  const l = item.link;
  const n = item.source.item;
  const text =
    item.skill === "listening"
      ? t("notebook.source.listening", { exercise: l.listening_exercise_id ?? 0, transcript: l.listening_transcript_version ?? 0, n })
      : item.skill === "reading"
        ? t("notebook.source.reading", { lesson: l.reading_lesson_id ?? 0, version: l.reading_passage_version ?? 0, exercise: l.reading_exercise_id ?? 0, n })
        : item.skill === "writing"
          ? t("notebook.source.writing", { task: l.writing_task_id ?? 0, version: l.writing_draft_version ?? 0, feedback: l.writing_feedback_id ?? 0, n })
          : t("notebook.source.speaking", {
              exercise: l.speaking_exercise_id ?? 0,
              take: l.speaking_take_number ?? 0,
              version: l.speaking_transcript_version ?? 0,
              feedback: l.speaking_feedback_id ?? 0,
              n,
            });
  return <p className="hint">{text}</p>;
}

function Attempt({ item }: { item: NotebookItem }) {
  const { t } = useI18n();
  if (item.quote)
    return (
      <p>
        <span className="label">{t("notebook.item.yourWords")}</span>{" "}
        <span lang="fr" className="french">
          « {item.quote} »
        </span>
      </p>
    );
  if (item.source.attempt)
    return (
      <p>
        <span className="label">{t("notebook.item.yourAnswer")}</span>{" "}
        <span lang="fr" className="french">
          {item.source.attempt}
        </span>
      </p>
    );
  return <p className="hint">{t("notebook.item.noAttempt")}</p>;
}

function Reference({ item }: { item: NotebookItem }) {
  const { t } = useI18n();
  return (
    <div className="notebook-reference" role="group" aria-label={t("notebook.item.referenceRegion")}>
      <p>
        <span className="label">{t(item.quote ? "notebook.item.suggestion" : "notebook.item.reference")}</span>{" "}
        <span lang="fr" className="french">
          {item.reference}
        </span>
      </p>
      <p>
        <span className="label">{t("notebook.item.why")}</span>{" "}
        <StoredText primary={item.explanation_en} variants={{ en: item.explanation_en, zh: item.explanation_zh }} kind="explanation" />
      </p>
    </div>
  );
}

function RetryToggle({ item, onChanged }: { item: NotebookItem; onChanged: (it: NotebookItem) => void }) {
  const { t } = useI18n();
  const [state, setState] = useState<{ status: "idle" | "sending" } | { status: "error"; message: string }>({ status: "idle" });
  const toggle = async () => {
    setState({ status: "sending" });
    try {
      onChanged((await api.setNotebookRetry(item.entry_id, !item.retry.marked)).item);
      setState({ status: "idle" });
    } catch (e) {
      setState({ status: "error", message: describe(e) });
    }
  };
  return (
    <>
      <button type="button" className={item.retry.marked ? "ghost" : undefined} aria-pressed={item.retry.marked} disabled={state.status === "sending"} onClick={toggle}>
        {item.retry.marked ? t("notebook.retry.marked") : t("notebook.retry.mark")}
      </button>
      {state.status === "error" ? (
        <span className="banner error" role="alert">
          {t("notebook.retry.failed", { message: state.message })}
        </span>
      ) : null}
    </>
  );
}

function MistakeList({ onOpenSource, onOpenRecord }: { onOpenSource?: (o: SourceOpen) => void; onOpenRecord?: (entryId: number) => void }) {
  const { t, tp } = useI18n();
  const [skill, setSkill] = useState<Skill | undefined>(undefined);
  const [marked, setMarked] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [items, replace] = useNotebook({ skill, marked }, epoch);
  return (
    <section className="panel" aria-label={t("notebook.list.region")}>
      <h2>{t("notebook.list.heading")}</h2>
      <p className="hint">{t("notebook.list.hint")}</p>
      <div className="view-tabs" role="group" aria-label={t("notebook.filter.skill")}>
        <button type="button" aria-pressed={skill === undefined} onClick={() => setSkill(undefined)}>
          {t("notebook.filter.all")}
        </button>
        {SKILLS.map((s) => (
          <button key={s} type="button" aria-pressed={skill === s} onClick={() => setSkill(s)}>
            {t(skillKey[s])}
          </button>
        ))}
      </div>
      <label className="notebook-filter">
        <input type="checkbox" checked={marked} onChange={(e) => setMarked(e.target.checked)} /> {t("notebook.filter.marked")}
      </label>
      {items.status === "loading" ? (
        <p className="hint" role="status">{t("notebook.loading")}</p>
      ) : items.status === "error" ? (
        <div className="banner error" role="alert">
          {t("notebook.list.failed", { message: items.message })}{" "}
          <button type="button" className="ghost" onClick={() => setEpoch((n) => n + 1)}>
            {t("common.retry")}
          </button>
        </div>
      ) : items.data.length === 0 ? (
        <p className="empty">{t("notebook.list.empty")}</p>
      ) : (
        <>
          <p className="hint" role="status">{tp("notebook.list.count", items.data.length)}</p>
          <ol className="listening-items">
            {items.data.map((it) => (
              <NotebookEntry key={it.entry_id} item={it} onChanged={replace} onOpenSource={onOpenSource} onOpenRecord={onOpenRecord} />
            ))}
          </ol>
        </>
      )}
      <p className="hint">{t("notebook.unlinked")}</p>
    </section>
  );
}

function NotebookEntry({
  item,
  onChanged,
  onOpenSource,
  onOpenRecord,
}: {
  item: NotebookItem;
  onChanged: (it: NotebookItem) => void;
  onOpenSource?: (o: SourceOpen) => void;
  onOpenRecord?: (entryId: number) => void;
}) {
  const { t } = useI18n();
  const [shown, setShown] = useState(false);
  const open = sourceOpen(item);
  return (
    <li className="listening-item notebook-item" role="group" aria-label={t("notebook.item.region", { id: item.entry_id })}>
      <p>
        <span className="tag">{t(skillKey[item.skill])}</span> <strong>{item.title}</strong>{" "}
        {item.retry.marked ? <span className="tag">{t("notebook.retry.tag")}</span> : null}
      </p>
      <p>
        <span className="label">{t("notebook.item.prompt")}</span>{" "}
        <span lang="fr" className="french">
          {item.prompt}
        </span>
      </p>
      <Attempt item={item} />
      <p>
        <span className="label">{t("notebook.item.record")}</span> <span lang="fr">{item.record.original_input}</span>
      </p>
      {shown ? <Reference item={item} /> : null}
      <SourceLine item={item} />
      <div className="actions">
        {!shown ? (
          <button type="button" onClick={() => setShown(true)}>
            {t("notebook.item.show")}
          </button>
        ) : null}
        {open && onOpenSource ? (
          <button type="button" className="ghost" onClick={() => onOpenSource(open)}>
            {t("notebook.item.openSource")}
          </button>
        ) : null}
        {onOpenRecord ? (
          <button type="button" className="ghost" onClick={() => onOpenRecord(item.entry_id)}>
            {t("notebook.item.openRecord", { id: item.entry_id })}
          </button>
        ) : null}
        <RetryToggle item={item} onChanged={onChanged} />
      </div>
    </li>
  );
}

type SelfCheck = "got" | "notyet";

// RetrySession is Recall Practice over marked items from every skill. Typed
// answers and self-checks live in this component only: nothing is sent except
// an explicit "Remove from the retry list".
function RetrySession({ onOpenSource }: { onOpenSource?: (o: SourceOpen) => void }) {
  const { t, tp } = useI18n();
  const [epoch, setEpoch] = useState(0);
  const [items, replace] = useNotebook({ marked: true }, epoch);
  const [started, setStarted] = useState<NotebookItem[] | null>(null);
  const [pos, setPos] = useState(0);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [revealed, setRevealed] = useState<Record<number, boolean>>({});
  const [checks, setChecks] = useState<Record<number, SelfCheck>>({});
  if (items.status === "loading") return <p className="hint" role="status">{t("notebook.loading")}</p>;
  if (items.status === "error")
    return (
      <div className="banner error" role="alert">
        {t("notebook.list.failed", { message: items.message })}{" "}
        <button type="button" className="ghost" onClick={() => setEpoch((n) => n + 1)}>
          {t("common.retry")}
        </button>
      </div>
    );
  if (!started) {
    const skills = SKILLS.filter((s) => items.data.some((it) => it.skill === s));
    return (
      <section className="panel" aria-label={t("notebook.retry.region")}>
        <h2>{t("notebook.retry.heading")}</h2>
        <p className="hint">{t("notebook.retry.hint")}</p>
        {items.data.length === 0 ? (
          <p className="empty">{t("notebook.retry.none")}</p>
        ) : (
          <>
            <p role="status">
              {tp("notebook.retry.ready", items.data.length)} {t("notebook.retry.skills", { skills: skills.map((s) => t(skillKey[s])).join(", ") })}
            </p>
            <div className="actions">
              <button type="button" className="primary" onClick={() => setStarted(items.data)}>
                {t("notebook.retry.start")}
              </button>
            </div>
          </>
        )}
      </section>
    );
  }
  if (pos >= started.length) {
    const got = started.filter((it) => checks[it.entry_id] === "got");
    return (
      <section className="panel" aria-label={t("notebook.retry.region")}>
        <h2>{t("notebook.retry.done")}</h2>
        <p role="status">{t("notebook.retry.summary", { total: started.length, got: got.length, notyet: started.length - got.length })}</p>
        <p className="hint">{t("notebook.retry.notSaved")}</p>
        {got.length > 0 ? (
          <ul className="listening-steps">
            {got.map((it) => {
              const current = items.data.find((x) => x.entry_id === it.entry_id) ?? it;
              return (
                <li key={it.entry_id}>
                  {t(skillKey[it.skill])} · {it.title} — {current.retry.marked ? <RetryToggle item={current} onChanged={replace} /> : t("notebook.retry.removed")}
                </li>
              );
            })}
          </ul>
        ) : null}
        <div className="actions">
          <button
            type="button"
            className="ghost"
            onClick={() => {
              setStarted(null);
              setPos(0);
              setAnswers({});
              setRevealed({});
              setChecks({});
              setEpoch((n) => n + 1);
            }}
          >
            {t("notebook.retry.again")}
          </button>
        </div>
      </section>
    );
  }
  const it = started[pos];
  const open = sourceOpen(it);
  const id = it.entry_id;
  return (
    <section className="panel" aria-label={t("notebook.retry.region")}>
      <h2>{t("notebook.retry.itemHeading", { n: pos + 1, total: started.length })}</h2>
      <div className="listening-item" role="group" aria-label={t("notebook.retry.card", { n: pos + 1 })}>
        <p>
          <span className="tag">{t(skillKey[it.skill])}</span> <strong>{it.title}</strong>
        </p>
        <p>
          <span className="label">{t("notebook.item.prompt")}</span>{" "}
          <span lang="fr" className="french">
            {it.prompt}
          </span>
        </p>
        <Attempt item={it} />
        {it.hint_en ? (
          <p>
            <span className="label">{t("notebook.item.hint")}</span>{" "}
            <StoredText primary={it.hint_en} variants={{ en: it.hint_en, zh: it.hint_zh }} kind="explanation" />
          </p>
        ) : null}
        <label htmlFor={`notebook-retry-${id}`}>{t("notebook.retry.try")}</label>
        <textarea
          id={`notebook-retry-${id}`}
          lang="fr"
          rows={2}
          value={answers[id] ?? ""}
          onChange={(e) => setAnswers((a) => ({ ...a, [id]: e.target.value }))}
        />
        {revealed[id] ? (
          <>
            <Reference item={it} />
            <div className="actions" role="group" aria-label={t("notebook.retry.checkLabel")}>
              <button type="button" aria-pressed={checks[id] === "got"} onClick={() => setChecks((c) => ({ ...c, [id]: "got" }))}>
                {t("notebook.retry.got")}
              </button>
              <button type="button" aria-pressed={checks[id] === "notyet"} onClick={() => setChecks((c) => ({ ...c, [id]: "notyet" }))}>
                {t("notebook.retry.notyet")}
              </button>
            </div>
            <p className="hint">{t("notebook.retry.checkHint")}</p>
          </>
        ) : null}
        <div className="actions">
          {!revealed[id] ? (
            <button type="button" className="primary" onClick={() => setRevealed((r) => ({ ...r, [id]: true }))}>
              {t("notebook.retry.reveal")}
            </button>
          ) : (
            <button type="button" className="primary" onClick={() => setPos((p) => p + 1)}>
              {pos + 1 < started.length ? t("notebook.retry.next") : t("notebook.retry.finish")}
            </button>
          )}
          {open && onOpenSource ? (
            <button type="button" className="ghost" onClick={() => onOpenSource(open)}>
              {t("notebook.item.openSource")}
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}

const reasonKey: Record<"no_supporting_unit" | "mixed_kinds" | "other_kind", MessageKey> = {
  no_supporting_unit: "notebook.kinds.reason.no_supporting_unit",
  mixed_kinds: "notebook.kinds.reason.mixed_kinds",
  other_kind: "notebook.kinds.reason.other_kind",
};
const kindHint: Record<KindView, MessageKey> = {
  grammar: "notebook.kinds.grammarHint",
  vocabulary: "notebook.kinds.vocabularyHint",
  unclassified: "notebook.kinds.unclassifiedHint",
};

function ConceptKinds({ kind, onOpenConcept }: { kind: KindView; onOpenConcept?: (conceptId: number) => void }) {
  const { t, tp } = useI18n();
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [state, setState] = useState<Load<KindConcepts>>({ status: "loading" });
  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    api.getKindConcepts(kind, query).then(
      (data) => active && setState({ status: "ready", data }),
      (e: unknown) => active && setState({ status: "error", message: describe(e) }),
    );
    return () => {
      active = false;
    };
  }, [kind, query]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setQuery(text);
  };
  return (
    <section className="panel" aria-label={t("notebook.kinds.region", { kind: t(`notebook.mode.${kind}` as MessageKey) })}>
      <h2>{t(`notebook.mode.${kind}` as MessageKey)}</h2>
      <p className="hint">{t(kindHint[kind])}</p>
      <form className="actions" onSubmit={submit} role="search" aria-label={t("notebook.kinds.search")}>
        <input type="search" value={text} onChange={(e) => setText(e.target.value)} aria-label={t("notebook.kinds.search")} />
        <button type="submit">{t("notebook.kinds.searchButton")}</button>
      </form>
      {state.status === "loading" ? (
        <p className="hint" role="status">{t("notebook.loading")}</p>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {t("notebook.kinds.failed", { message: state.message })}
        </div>
      ) : state.data.concepts.length === 0 ? (
        <p className="empty">{t("notebook.kinds.empty")}</p>
      ) : (
        <>
          <p className="hint" role="status">
            {tp("notebook.kinds.count", state.data.concepts.length)} {t("notebook.kinds.classified", { n: state.data.classified })}
            {state.data.truncated ? ` ${t("notebook.kinds.truncated")}` : ""}
          </p>
          <ul className="listening-list">
            {state.data.concepts.map((c) => (
              <li key={c.concept_id}>
                {onOpenConcept ? (
                  <button type="button" className="link-button" onClick={() => onOpenConcept(c.concept_id)}>
                    {c.target}
                  </button>
                ) : (
                  c.target
                )}{" "}
                <span className="hint">
                  {t("notebook.kinds.meta", { id: c.concept_id, intent: c.pedagogical_intent, units: c.supporting_unit_count })}
                </span>{" "}
                {c.kinds.map((k) => (
                  <span key={k} className="tag">
                    {k}
                  </span>
                ))}{" "}
                {c.reason ? <span className="hint">{t(reasonKey[c.reason])}</span> : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
