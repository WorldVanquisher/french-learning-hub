import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import { useI18n, type MessageKey } from "../i18n";
import { sourceOpen, type NotebookItem, type Skill, type SourceOpen } from "../types/notebook";
import { Reference, SourceLine } from "./MistakeNotebook";
import {
  approvalTargets,
  buildDraft,
  draftProblem,
  draftReady,
  nextCopy,
  PRACTICE_ACTIONS,
  type PracticeAction,
  type PracticeDraft,
} from "./practiceDraft";

// Notebook to practice (private workbench). Select notes, preview each draft
// (source text, draft question, expected action) side by side, edit it, then
// approve: approval puts each record into Review Today through the notebook's
// own retry save (one mark per record, so a repeated click or a second version
// never adds a second item). The drafts' edited wording, the answers and the
// self-checks stay in this page; nothing else is sent or stored.

const skillKey: Record<Skill, MessageKey> = {
  listening: "notebook.skill.listening",
  reading: "notebook.skill.reading",
  writing: "notebook.skill.writing",
  speaking: "notebook.skill.speaking",
};
const actionKey: Record<PracticeAction, MessageKey> = {
  answer_again: "notePractice.action.answer_again",
  write_corrected: "notePractice.action.write_corrected",
  say_corrected: "notePractice.action.say_corrected",
};

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; items: NotebookItem[] };
type Saved = "saved" | "already" | { failed: string } | "gone";
type Stage = "select" | "preview" | "approved" | "practise";

const describe = (e: unknown) => (e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e));

export function NotebookPractice({
  onOpenSource,
  onOpenRecord,
  onOpenToday,
}: {
  onOpenSource?: (o: SourceOpen) => void;
  onOpenRecord?: (entryId: number) => void;
  onOpenToday?: () => void;
}) {
  const { t, tp } = useI18n();
  const [epoch, setEpoch] = useState(0);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [selected, setSelected] = useState<number[]>([]);
  const [drafts, setDrafts] = useState<PracticeDraft[]>([]);
  const [stage, setStage] = useState<Stage>("select");
  const [saved, setSaved] = useState<Record<number, Saved>>({});
  const [busy, setBusy] = useState(false);
  const [invalidTried, setInvalidTried] = useState(false);
  const sending = useRef(false); // a second click before React re-renders is still one approval
  const previewHeading = useRef<HTMLHeadingElement>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const previewButton = useRef<HTMLButtonElement>(null);
  const questionRefs = useRef<Record<string, HTMLTextAreaElement | null>>({});
  const [pendingFocus, setPendingFocus] = useState<"preview" | "result" | "select" | string | null>(null);

  useEffect(() => {
    let live = true;
    setLoad({ status: "loading" });
    api.listNotebookItems().then(
      (r) => live && setLoad({ status: "ready", items: r.items }),
      (e) => live && setLoad({ status: "error", message: describe(e) }),
    );
    return () => {
      live = false;
    };
  }, [epoch]);

  // Focus follows the step the learner moved to (029).
  useEffect(() => {
    if (!pendingFocus) return;
    if (pendingFocus === "preview") previewHeading.current?.focus();
    else if (pendingFocus === "result") resultHeading.current?.focus();
    else if (pendingFocus === "select") previewButton.current?.focus();
    else questionRefs.current[pendingFocus]?.focus();
    setPendingFocus(null);
  }, [pendingFocus, stage, drafts]);

  if (load.status === "loading") return <p className="hint" role="status">{t("notebook.loading")}</p>;
  if (load.status === "error")
    return (
      <div className="banner error" role="alert">
        {t("notebook.list.failed", { message: load.message })}{" "}
        <button type="button" className="ghost" onClick={() => setEpoch((n) => n + 1)}>
          {t("common.retry")}
        </button>
      </div>
    );
  const items = load.items;
  const byEntry = new Map(items.map((it) => [it.entry_id, it]));

  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const preview = () => {
    // Keep drafts already edited for records still selected; add the new ones.
    setDrafts((prev) => {
      const kept = prev.filter((d) => selected.includes(d.provenance.entryId));
      const fresh = selected
        .filter((id) => !kept.some((d) => d.provenance.entryId === id))
        .map((id) => byEntry.get(id))
        .map((it) => (it ? buildDraft(it) : null))
        .filter((d): d is PracticeDraft => d !== null);
      return [...kept, ...fresh];
    });
    setStage("preview");
    setPendingFocus("preview");
  };
  const edit = (key: string, patch: Partial<PracticeDraft>) => setDrafts((ds) => ds.map((d) => (d.key === key ? { ...d, ...patch } : d)));
  const secondCopy = (d: PracticeDraft) => {
    const it = byEntry.get(d.provenance.entryId);
    const copy = it ? buildDraft(it, nextCopy(drafts, d.provenance.entryId)) : null;
    if (!copy) return;
    setDrafts((ds) => {
      const at = ds.findIndex((x) => x.key === d.key);
      return [...ds.slice(0, at + 1), copy, ...ds.slice(at + 1)];
    });
    setPendingFocus(copy.key);
  };
  const remove = (d: PracticeDraft) => {
    const rest = drafts.filter((x) => x.key !== d.key);
    setDrafts(rest);
    if (!rest.some((x) => x.provenance.entryId === d.provenance.entryId)) setSelected((s) => s.filter((x) => x !== d.provenance.entryId));
    if (rest.length === 0) {
      setStage("select");
      setPendingFocus("select");
    }
  };
  const back = () => {
    setStage("select");
    setPendingFocus("select");
  };

  // approve: one retry mark per record not yet saved; a failed save keeps
  // every draft and edit, and a second approval only resends what failed.
  const approve = async () => {
    const blank = drafts.find((d) => !draftReady(d));
    if (blank) {
      // The button stays reachable: it says what to fix and goes there.
      setInvalidTried(true);
      questionRefs.current[blank.key]?.focus();
      return;
    }
    if (sending.current || drafts.length === 0) return;
    sending.current = true;
    setBusy(true);
    const next: Record<number, Saved> = { ...saved };
    for (const id of approvalTargets(drafts)) {
      if (next[id] === "saved" || next[id] === "already") continue;
      const it = byEntry.get(id);
      if (it?.retry.marked) {
        next[id] = "already";
        continue;
      }
      try {
        const r = await api.setNotebookRetry(id, true);
        next[id] = r.changed ? "saved" : "already";
      } catch (e) {
        next[id] = e instanceof ApiError && e.status === 404 ? "gone" : { failed: describe(e) };
      }
    }
    setSaved(next);
    sending.current = false;
    setBusy(false);
    const allSaved = approvalTargets(drafts).every((id) => next[id] === "saved" || next[id] === "already");
    if (allSaved) {
      setStage("approved");
      setPendingFocus("result");
    }
  };

  const onPreviewKey = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      back();
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void approve();
    } else if (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      // Alt+Arrow moves between the drafts' questions.
      const keys = drafts.map((d) => d.key);
      const at = keys.findIndex((k) => questionRefs.current[k] === document.activeElement);
      const to = e.key === "ArrowDown" ? Math.min(keys.length - 1, at + 1) : Math.max(0, at - 1);
      if (keys[to]) {
        e.preventDefault();
        questionRefs.current[keys[to]]?.focus();
      }
    }
  };

  if (stage === "practise") return <PractiseNow drafts={drafts} byEntry={byEntry} onOpenSource={onOpenSource} onDone={() => setStage("approved")} />;

  if (stage === "approved")
    return (
      <section className="panel" aria-label={t("notePractice.region")}>
        <h2 ref={resultHeading} tabIndex={-1}>
          {t("notePractice.approved.heading")}
        </h2>
        <p role="status">{tp("notePractice.approved.count", approvalTargets(drafts).length)}</p>
        <ul className="listening-steps">
          {approvalTargets(drafts).map((id) => (
            <li key={id} data-entry={id} data-saved={String(saved[id])}>
              {byEntry.get(id)?.title} — {t(saved[id] === "already" ? "notePractice.approved.already" : "notePractice.approved.saved")}
            </li>
          ))}
        </ul>
        <p className="hint">{t("notePractice.approved.pageOnly")}</p>
        <div className="actions">
          <button type="button" className="primary" onClick={() => setStage("practise")}>
            {t("notePractice.practiseNow")}
          </button>
          {onOpenToday ? (
            <button type="button" className="ghost" onClick={onOpenToday}>
              {t("notePractice.openToday")}
            </button>
          ) : null}
          <button
            type="button"
            className="ghost"
            onClick={() => {
              setDrafts([]);
              setSelected([]);
              setSaved({});
              setStage("select");
              setEpoch((n) => n + 1);
            }}
          >
            {t("notePractice.again")}
          </button>
        </div>
      </section>
    );

  if (stage === "preview") {
    const failed = approvalTargets(drafts).filter((id) => typeof saved[id] === "object" || saved[id] === "gone");
    return (
      <section className="panel notebook-practice" aria-label={t("notePractice.region")} onKeyDown={onPreviewKey}>
        <h2 ref={previewHeading} tabIndex={-1}>
          {tp("notePractice.preview.heading", drafts.length)}
        </h2>
        <p className="hint">{t("notePractice.preview.hint")}</p>
        <p className="hint">{t("notePractice.preview.keys")}</p>
        {failed.length > 0 ? (
          <div className="banner error" role="alert">
            {tp("notePractice.saveFailed", failed.length)}
          </div>
        ) : null}
        <ol className="listening-items">
          {drafts.map((d, i) => {
            const it = byEntry.get(d.provenance.entryId);
            const s = saved[d.provenance.entryId];
            const qid = `practice-q-${d.key.replace(":", "-")}`;
            return (
              <li key={d.key} className="listening-item practice-draft" data-key={d.key} role="group" aria-label={t("notePractice.draft.region", { n: i + 1, title: d.title })}>
                <p>
                  <span className="tag">{t(skillKey[d.skill])}</span> <strong>{d.title}</strong>{" "}
                  {d.copy > 1 ? <span className="tag">{t("notePractice.draft.copy", { n: d.copy })}</span> : null}
                </p>
                <div className="practice-columns">
                  <div className="practice-source" role="group" aria-label={t("notePractice.draft.source")}>
                    <p className="notebook-side">{t("notePractice.draft.source")}</p>
                    <p>
                      <span className="label">{t("notebook.item.prompt")}</span>{" "}
                      <span lang="fr" className="french">
                        {d.sourcePrompt}
                      </span>
                    </p>
                    {d.sourceWords ? (
                      <p>
                        <span className="label">{t("notebook.item.yourWords")}</span>{" "}
                        <span lang="fr" className="french">
                          {d.sourceWords}
                        </span>
                      </p>
                    ) : null}
                    {it ? <SourceLine item={it} /> : null}
                    {d.provenance.latestVersion ? (
                      <p className="hint" data-problem="newer">
                        {t("notePractice.draft.newer", { version: d.provenance.version, latest: d.provenance.latestVersion })}
                      </p>
                    ) : null}
                  </div>
                  <div className="practice-edit">
                    <label htmlFor={qid}>{t("notePractice.draft.question")}</label>
                    <textarea
                      id={qid}
                      lang="fr"
                      rows={3}
                      ref={(el) => {
                        questionRefs.current[d.key] = el;
                      }}
                      value={d.question}
                      aria-invalid={!draftReady(d)}
                      aria-describedby={!draftReady(d) ? `${qid}-empty` : undefined}
                      onChange={(e) => edit(d.key, { question: e.target.value })}
                    />
                    {!draftReady(d) ? (
                      <p id={`${qid}-empty`} className="banner error" role="alert">
                        {t("notePractice.draft.empty")}
                      </p>
                    ) : null}
                    <label htmlFor={`${qid}-action`}>{t("notePractice.draft.action")}</label>
                    <select id={`${qid}-action`} value={d.action} onChange={(e) => edit(d.key, { action: e.target.value as PracticeAction })}>
                      {PRACTICE_ACTIONS.map((a) => (
                        <option key={a} value={a}>
                          {t(actionKey[a])}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                {s === "gone" ? (
                  <div className="banner error" role="alert" data-problem="gone">
                    {t("notePractice.draft.gone", { id: d.provenance.entryId })}
                  </div>
                ) : typeof s === "object" ? (
                  <div className="banner error" role="alert" data-problem="failed">
                    {t("notePractice.draft.failed", { message: s.failed })}
                  </div>
                ) : null}
                <div className="actions">
                  <button type="button" className="ghost" onClick={() => secondCopy(d)}>
                    {t("notePractice.draft.second")}
                  </button>
                  <button type="button" className="ghost" onClick={() => remove(d)}>
                    {t("notePractice.draft.remove")}
                  </button>
                  {s === "gone" && onOpenRecord ? (
                    <button type="button" className="ghost" onClick={() => onOpenRecord(d.provenance.entryId)}>
                      {t("notebook.item.openRecord", { id: d.provenance.entryId })}
                    </button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
        <div className="actions">
          {invalidTried && !drafts.every(draftReady) ? (
            <p className="banner error" role="alert">
              {tp("notePractice.blankBeforeApprove", drafts.filter((d) => !draftReady(d)).length)}
            </p>
          ) : null}
          <button type="button" className="primary" disabled={busy || drafts.length === 0} onClick={() => void approve()}>
            {busy ? t("notePractice.approving") : failed.length > 0 ? t("notePractice.retryApprove") : tp("notePractice.approve", approvalTargets(drafts).length)}
          </button>
          <button type="button" className="ghost" onClick={back}>
            {t("notePractice.back")}
          </button>
        </div>
      </section>
    );
  }

  // Select: every notebook record, with what stops it becoming a draft.
  return (
    <section className="panel notebook-practice" aria-label={t("notePractice.region")}>
      <h2>{t("notePractice.heading")}</h2>
      <p className="hint">{t("notePractice.hint")}</p>
      {items.length === 0 ? (
        <p className="empty">{t("notePractice.none")}</p>
      ) : (
        <ul className="listening-items practice-select" aria-label={t("notePractice.select.label")}>
          {items.map((it) => {
            const problem = draftProblem(it);
            const blocked = problem === "missing" || problem === "unusable";
            const id = `practice-pick-${it.entry_id}`;
            const open = sourceOpen(it);
            return (
              <li key={it.entry_id} className="listening-item" data-entry={it.entry_id} data-problem={problem ?? undefined}>
                <input type="checkbox" id={id} disabled={blocked} checked={selected.includes(it.entry_id)} onChange={() => toggle(it.entry_id)} />{" "}
                <label htmlFor={id}>
                  <span className="tag">{t(skillKey[it.skill])}</span> {blocked ? t("notePractice.select.unavailable", { id: it.entry_id }) : it.title}
                  {!blocked ? (
                    <>
                      {" — "}
                      <span lang="fr" className="french">
                        {it.quote ?? it.prompt}
                      </span>
                    </>
                  ) : null}
                </label>
                {blocked ? (
                  <div className="banner error" role="status">
                    {t(problem === "missing" ? "notePractice.select.missing" : "notePractice.select.unusable", { type: it.source.type, record: it.source.record_id, n: it.source.item })}{" "}
                    {onOpenRecord ? (
                      <button type="button" className="ghost" onClick={() => onOpenRecord(it.entry_id)}>
                        {t("notebook.item.openRecord", { id: it.entry_id })}
                      </button>
                    ) : null}
                  </div>
                ) : problem === "newer" ? (
                  <p className="hint">
                    {t("notePractice.select.newer", { version: it.latest_version ?? 0 })}{" "}
                    {open && onOpenSource ? (
                      <button type="button" className="link-button" onClick={() => onOpenSource(open)}>
                        {t("notebook.item.openSource")}
                      </button>
                    ) : null}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      <div className="actions">
        <button type="button" className="primary" ref={previewButton} disabled={selected.length === 0} onClick={preview}>
          {tp("notePractice.previewSelected", selected.length)}
        </button>
      </div>
    </section>
  );
}

type SelfCheck = "got" | "notyet";

// PractiseNow goes through the approved drafts with their edited wording.
// Answers and self-checks stay in this component.
function PractiseNow({
  drafts,
  byEntry,
  onOpenSource,
  onDone,
}: {
  drafts: PracticeDraft[];
  byEntry: Map<number, NotebookItem>;
  onOpenSource?: (o: SourceOpen) => void;
  onDone: () => void;
}) {
  const { t, tp } = useI18n();
  const [pos, setPos] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [checks, setChecks] = useState<Record<string, SelfCheck>>({});
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), [pos]);
  if (pos >= drafts.length) {
    const got = drafts.filter((d) => checks[d.key] === "got").length;
    return (
      <section className="panel" aria-label={t("notePractice.region")}>
        <h2 ref={heading} tabIndex={-1}>
          {t("notePractice.run.done")}
        </h2>
        <p role="status">{tp("notePractice.run.summary", drafts.length, { got, notyet: drafts.length - got })}</p>
        <p className="hint">{t("notebook.retry.notSaved")}</p>
        <div className="actions">
          <button type="button" className="primary" onClick={onDone}>
            {t("notePractice.run.back")}
          </button>
        </div>
      </section>
    );
  }
  const d = drafts[pos];
  const it = byEntry.get(d.provenance.entryId);
  const open = it ? sourceOpen(it) : null;
  const aid = `practice-answer-${d.key.replace(":", "-")}`;
  return (
    <section className="panel" aria-label={t("notePractice.region")}>
      <h2 ref={heading} tabIndex={-1}>
        {t("notebook.retry.itemHeading", { n: pos + 1, total: drafts.length })}
      </h2>
      <div className="listening-item" role="group" aria-label={t("notePractice.draft.region", { n: pos + 1, title: d.title })}>
        <p>
          <span className="tag">{t(skillKey[d.skill])}</span> <strong>{d.title}</strong>{" "}
          {d.copy > 1 ? <span className="tag">{t("notePractice.draft.copy", { n: d.copy })}</span> : null}
        </p>
        {it ? <SourceLine item={it} /> : null}
        <p>
          <span lang="fr" className="french practice-question">
            {d.question}
          </span>
        </p>
        <p className="hint">{t(actionKey[d.action])}</p>
        <label htmlFor={aid}>{t("notebook.retry.try")}</label>
        <textarea id={aid} lang="fr" rows={2} value={answers[d.key] ?? ""} onChange={(e) => setAnswers((a) => ({ ...a, [d.key]: e.target.value }))} />
        {revealed[d.key] && it ? (
          <>
            <Reference item={it} />
            <div className="actions" role="group" aria-label={t("notebook.retry.checkLabel")}>
              <button type="button" aria-pressed={checks[d.key] === "got"} onClick={() => setChecks((c) => ({ ...c, [d.key]: "got" }))}>
                {t("notebook.retry.got")}
              </button>
              <button type="button" aria-pressed={checks[d.key] === "notyet"} onClick={() => setChecks((c) => ({ ...c, [d.key]: "notyet" }))}>
                {t("notebook.retry.notyet")}
              </button>
            </div>
          </>
        ) : null}
        <div className="actions">
          {!revealed[d.key] ? (
            <button type="button" className="primary" onClick={() => setRevealed((r) => ({ ...r, [d.key]: true }))}>
              {t("notebook.retry.reveal")}
            </button>
          ) : (
            <button type="button" className="primary" onClick={() => setPos((p) => p + 1)}>
              {pos + 1 < drafts.length ? t("notebook.retry.next") : t("notebook.retry.finish")}
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
