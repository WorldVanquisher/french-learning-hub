import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import * as api from "../api/client";
import { useI18n, type MessageKey } from "../i18n";
import { sourceOpen, type SourceOpen } from "../types/notebook";
import type { ReviewToday as ReviewTodayData, ReviewTodayItem } from "../types/reviewToday";
import { ConceptPractice } from "../prototype/ConceptPractice";
import { openerId, PracticePrototype } from "../prototype/PracticePrototype";
import { closeConcept, openConcept, usePracticeVisit } from "../prototype/practiceStore";
import { HistoryExport } from "./HistoryExport";
import { LearningWeek } from "./LearningWeek";
import { QueueReason } from "./Speaking";

// Review Today (private workbench): one queue of what the learner can act on
// now, from the backend's review_today_v1. Speaking steps open the exercise at
// its take; a workbook item (a Mistake Notebook record marked for retry) opens
// the lesson it was saved from, and "Done for today" removes its retry mark
// through the notebook's own save (the record itself stays). Saved history is
// never queued; it is counted and linked. Nothing is stored in the browser.

const skillKey: Record<string, MessageKey> = {
  listening: "notebook.skill.listening",
  reading: "notebook.skill.reading",
  writing: "notebook.skill.writing",
  speaking: "notebook.skill.speaking",
};

const dateIn = (locale: string) => (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(locale);
};

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: ReviewTodayData };

export function ReviewToday({
  onOpenSpeaking,
  onOpenSource,
  onShow,
}: {
  onOpenSpeaking: (exerciseId: number, takeId?: number) => void;
  onOpenSource: (open: SourceOpen) => void;
  onShow: (view: "speaking" | "listening" | "notebook") => void;
}) {
  const { t, tp, locale } = useI18n();
  const when = dateIn(locale);
  const [epoch, setEpoch] = useState(0);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  // "Hide for this visit" (Speaking steps): page-only, nothing is deleted or
  // stored; a persisted defer needs storage the owner has not allocated.
  const [hidden, setHidden] = useState<string[]>([]);
  const listRef = useRef<HTMLOListElement>(null);
  // The practice prototype (sealed synthetic fixture): page memory only
  // (practiceStore), so its panel, the opened concept and every answer survive
  // moving around the workbench but disappear on reload.
  const practice = usePracticeVisit();
  const practiceReturn = useRef<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    let live = true;
    api.getReviewToday().then(
      (data) => live && setLoad({ status: "ready", data }),
      (e) => live && setLoad({ status: "error", message: e instanceof Error ? e.message : String(e) }),
    );
    return () => {
      live = false;
    };
  }, [epoch]);

  // After an item leaves the queue, focus goes to the item that took its
  // place (or the one before it, or the heading when the queue is empty).
  const focusRow = (index: number) =>
    requestAnimationFrame(() => {
      const rows = listRef.current?.querySelectorAll<HTMLElement>("li[data-key]");
      const row = rows ? (rows[index] ?? rows[index - 1]) : undefined;
      (row?.querySelector<HTMLElement>("button") ?? headingRef.current)?.focus();
    });
  // Up/Down (and Home/End) move between the queue's items: each item's first
  // button, so a keyboard user reaches the next action in one key press.
  const onQueueKey = (e: KeyboardEvent<HTMLOListElement>) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const rows = [...(listRef.current?.querySelectorAll<HTMLElement>("li[data-key]") ?? [])];
    const at = rows.findIndex((r) => r.contains(document.activeElement));
    if (at < 0) return;
    const to = e.key === "Home" ? 0 : e.key === "End" ? rows.length - 1 : e.key === "ArrowDown" ? Math.min(rows.length - 1, at + 1) : Math.max(0, at - 1);
    e.preventDefault();
    rows[to].querySelector<HTMLElement>("button")?.focus();
  };

  // "Done for today": the notebook's own retry save, then a fresh read; the
  // item leaves the queue without a page reload and focus moves on.
  const done = async (it: ReviewTodayItem, index: number) => {
    if (!it.notebook) return;
    setBusy(it.key);
    setError(null);
    try {
      await api.setNotebookRetry(it.notebook.entry_id, false);
      const data = await api.getReviewToday();
      setLoad({ status: "ready", data });
      setAnnounce(t("today.doneAnnounce", { title: it.notebook.title }));
      // Focus goes to the item that took this one's place (or the one before
      // it, or the heading when the queue is empty).
      focusRow(index);
    } catch (e) {
      setError(t("today.doneFailed", { message: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusy(null);
    }
  };

  const body = () => {
    if (load.status === "loading") return <p className="hint" role="status">{t("today.loading")}</p>;
    if (load.status === "error")
      return (
        <div className="banner error" role="alert">
          {t("today.failed", { message: load.message })}{" "}
          <button type="button" className="ghost" onClick={() => setEpoch((n) => n + 1)}>
            {t("common.retry")}
          </button>
        </div>
      );
    const { history } = load.data;
    const items = load.data.items.filter((it) => !hidden.includes(it.key));
    const hiddenHere = load.data.items.length - items.length;
    const hasHistory = history.notebook_items > 0 || history.speaking_takes > 0 || history.speaking_exercises > 0;
    const showHidden =
      hiddenHere > 0 ? (
        <p className="hint" data-today="hidden">
          {tp("today.hiddenCount", hiddenHere)}{" "}
          <button type="button" className="link-button" onClick={() => setHidden([])}>
            {t("today.showHidden")}
          </button>
        </p>
      ) : null;
    if (items.length === 0 && hiddenHere > 0) return showHidden;
    if (items.length === 0)
      return hasHistory ? (
        <div className="today-empty" data-empty="all-done">
          <p>{t("today.allDone")}</p>
          <div className="actions">
            <button type="button" className="primary" onClick={() => onShow("notebook")}>
              {t("today.openNotebook")}
            </button>
            <button type="button" className="ghost" onClick={() => onShow("speaking")}>
              {t("today.openSpeaking")}
            </button>
          </div>
        </div>
      ) : (
        <div className="today-empty" data-empty="nothing-yet">
          <p>{t("today.nothingYet")}</p>
          <div className="actions">
            <button type="button" className="primary" onClick={() => onShow("speaking")}>
              {t("today.startSpeaking")}
            </button>
            <button type="button" className="ghost" onClick={() => onShow("listening")}>
              {t("today.startWorkbook")}
            </button>
          </div>
        </div>
      );
    return (
      <>
        <p className="hint">{t("today.keys")}</p>
        <ol className="listening-list today-queue" aria-label={t("today.queue")} ref={listRef} onKeyDown={onQueueKey}>
          {items.map((it, i) => (
            <li key={it.key} data-key={it.key} data-source={it.source} data-reason={it.reason}>
              <p>
                <span className="tag">{it.source === "speaking" ? t("today.source.speaking") : t("today.source.workbook")}</span>{" "}
                {it.notebook ? <span className="tag">{t(skillKey[it.notebook.skill] ?? "notebook.skill.listening")}</span> : null}{" "}
                <span className="reading-example-title">{it.speaking?.title ?? it.notebook?.title}</span>
              </p>
              {it.speaking ? (
                <>
                  <QueueReason q={it.speaking} />
                  <p className="hint" data-based-on="speaking">
                    {it.speaking.take_number
                      ? t("today.basedOn.speakingTake", { exercise: it.speaking.exercise_id ?? 0, take: it.speaking.take_number, reason: it.reason, day: it.since_day ?? when(it.since) })
                      : t("today.basedOn.speaking", { exercise: it.speaking.exercise_id ?? 0, reason: it.reason, day: it.since_day ?? when(it.since) })}
                  </p>
                  <div className="actions">
                    <button type="button" className="primary" onClick={() => onOpenSpeaking(it.speaking!.exercise_id!, it.speaking!.take_id ?? undefined)}>
                      {it.speaking.take_number ? t("today.openTake", { n: it.speaking.take_number }) : t("today.openExercise")}
                    </button>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => {
                        setHidden((h) => [...h, it.key]);
                        setAnnounce(t("today.hiddenAnnounce", { title: it.speaking!.title }));
                        focusRow(i);
                      }}
                    >
                      {t("today.hide")}
                    </button>
                  </div>
                </>
              ) : it.notebook ? (
                <>
                  <p>{t("today.reason.retry_marked", { date: when(it.since) })}</p>
                  <p className="hint">
                    <span lang="fr" className="french">
                      {it.notebook.prompt}
                    </span>
                  </p>
                  <p className="hint" data-based-on="notebook">
                    {t("today.basedOn.notebook", {
                      entry: it.notebook.entry_id,
                      type: it.notebook.source.type,
                      record: it.notebook.source.record_id,
                      n: it.notebook.source.item,
                      day: it.since_day ?? when(it.since),
                    })}
                  </p>
                  <div className="actions">
                    {sourceOpen(it.notebook) ? (
                      <button type="button" className="primary" onClick={() => onOpenSource(sourceOpen(it.notebook!)!)}>
                        {t("today.openLesson")}
                      </button>
                    ) : (
                      <span className="hint">{t("today.sourceMissing")}</span>
                    )}
                    <button type="button" className="ghost" disabled={busy !== null} onClick={() => void done(it, i)}>
                      {busy === it.key ? t("today.doneSaving") : t("today.done")}
                    </button>
                  </div>
                </>
              ) : null}
            </li>
          ))}
        </ol>
        {showHidden}
      </>
    );
  };

  if (practice.openConcept && practice.catalog) {
    const sourceId = practice.openConcept;
    return (
      <main className="writing review-today">
        <ConceptPractice
          key={sourceId}
          sourceId={sourceId}
          onExit={() => {
            closeConcept();
            // Back to the control that opened it; if it left the list, to the concept's own row.
            requestAnimationFrame(() => (document.getElementById(practiceReturn.current ?? "") ?? document.getElementById(openerId(sourceId)) ?? headingRef.current)?.focus());
          }}
        />
      </main>
    );
  }
  const history = load.status === "ready" ? load.data.history : null;
  return (
    <main className="writing review-today">
      <section className="panel" aria-label={t("today.region")}>
        <h2 ref={headingRef} tabIndex={-1}>
          {t("today.heading")}
        </h2>
        <p className="hint">{t("today.hint")}</p>
        {error ? (
          <div className="banner error" role="alert">
            {error}
          </div>
        ) : null}
        {body()}
        <p className="visually-hidden" aria-live="polite" aria-atomic="true">
          {announce}
        </p>
        {history ? (
          <p className="hint today-history">
            {t("today.history", { notebook: history.notebook_items, takes: history.speaking_takes })}{" "}
            <button type="button" className="link-button" onClick={() => onShow("notebook")}>
              {t("today.historyNotebook")}
            </button>{" "}
            <button type="button" className="link-button" onClick={() => onShow("speaking")}>
              {t("today.historySpeaking")}
            </button>
          </p>
        ) : null}
        <PracticePrototype
          onOpen={(sourceId, focusItem, returnTo) => {
            practiceReturn.current = returnTo;
            openConcept(sourceId, focusItem);
          }}
        />
        <LearningWeek onOpenSource={onOpenSource} epoch={epoch} />
        <HistoryExport />
      </section>
    </main>
  );
}
