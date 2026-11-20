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
import { hiddenKeys, rememberReturn, setHiddenKeys, takeReturn } from "./reviewTodayMemory";

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
  // Focus to give back after a save, applied by an effect once the buttons are
  // enabled again: a browser refuses focus on a disabled button, so focusing in
  // an animation frame could land before the re-render and lose it (R4).
  const [refocus, setRefocus] = useState<{ key: string; index: number; on: "done" | "next" } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  // "Hide for this visit" (Speaking steps): page-only, nothing is deleted or
  // stored; a persisted defer needs storage the owner has not allocated.
  // Kept in page memory, so leaving for a lesson and coming back keeps it.
  const [hidden, setHiddenState] = useState<string[]>(hiddenKeys);
  const setHidden = (next: string[] | ((h: string[]) => string[])) =>
    setHiddenState((h) => {
      const v = typeof next === "function" ? next(h) : next;
      setHiddenKeys(v);
      return v;
    });
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

  // Coming back from an item's lesson or take (the BackBanner): focus goes to
  // that item's first button, or, when it has left the queue, to the heading.
  useEffect(() => {
    if (load.status !== "ready") return;
    const key = takeReturn();
    if (key === null) return;
    requestAnimationFrame(() => {
      const row = listRef.current?.querySelector<HTMLElement>(`li[data-key="${key}"]`);
      (row?.querySelector<HTMLElement>("button") ?? headingRef.current)?.focus();
    });
  }, [load]);

  useEffect(() => {
    if (!refocus || busy !== null) return;
    const rows = [...(listRef.current?.querySelectorAll<HTMLElement>("li[data-key]") ?? [])];
    const { key, index, on } = refocus;
    if (on === "done") {
      // the same item's button; after a partial group save, the row at the same place
      const row = rows.find((r) => r.dataset.key === key) ?? rows[index] ?? rows[index - 1];
      (row?.querySelector<HTMLElement>('[data-action="done"]') ?? row?.querySelector<HTMLElement>("button") ?? headingRef.current)?.focus();
    } else {
      const row = rows[index] ?? rows[index - 1];
      (row?.querySelector<HTMLElement>("button") ?? headingRef.current)?.focus();
    }
    setRefocus(null);
  }, [refocus, busy, load]);

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
  // An item standing for several records of the same question clears each
  // (the same save, one record at a time; a repeated save is a no-op).
  const done = async (it: ReviewTodayItem, index: number) => {
    if (!it.notebook) return;
    setBusy(it.key);
    setError(null);
    let cleared = 0;
    try {
      for (const id of [it.notebook.entry_id, ...(it.also_entry_ids ?? [])]) {
        await api.setNotebookRetry(id, false);
        cleared++;
      }
      const data = await api.getReviewToday();
      setLoad({ status: "ready", data });
      setAnnounce(t("today.doneAnnounce", { title: it.notebook.title }));
      // Focus goes to the item that took this one's place (or the one before
      // it, or the heading when the queue is empty), once the buttons are enabled.
      setRefocus({ key: it.key, index, on: "next" });
    } catch (e) {
      setError(t("today.doneFailed", { message: e instanceof Error ? e.message : String(e) }));
      // Part of a group cleared: re-read so the row shows the truth (it stays
      // while any record is still marked). A failed re-read keeps the row.
      if (cleared > 0) await api.getReviewToday().then((data) => setLoad({ status: "ready", data }), () => undefined);
      // The button was disabled while saving, which drops focus: give it back to
      // the same item's button so the learner can retry from where they were
      // (after a partial group save, the row at the same place: it may now
      // stand for the record still marked).
      setRefocus({ key: it.key, index, on: "done" });
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
                    <button
                      type="button"
                      className="primary"
                      onClick={() => {
                        rememberReturn(it.key);
                        onOpenSpeaking(it.speaking!.exercise_id!, it.speaking!.take_id ?? undefined);
                      }}
                    >
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
                  {it.also_entry_ids?.length ? (
                    <p className="hint" data-also={it.also_entry_ids.join(" ")}>
                      {tp("today.also", it.also_entry_ids.length)}
                    </p>
                  ) : null}
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
                      <button
                        type="button"
                        className="primary"
                        onClick={() => {
                          rememberReturn(it.key);
                          onOpenSource(sourceOpen(it.notebook!)!);
                        }}
                      >
                        {t("today.openLesson")}
                      </button>
                    ) : (
                      <span className="hint">{t("today.sourceMissing")}</span>
                    )}
                    <button type="button" className="ghost" data-action="done" disabled={busy !== null} onClick={() => void done(it, i)}>
                      {busy === it.key ? t("today.doneSaving") : t("today.done")}
                    </button>
                  </div>
                </>
              ) : null}
              {it.schedule ? <NextReview s={it.schedule} /> : null}
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

// The next-review recommendation (R4-WB-011, R4-WB-014): when the item is due,
// and what one more attempt today would change, completed or missed. The
// learner's queue itself is still only what they marked; nothing is stored.
function NextReview({ s }: { s: NonNullable<ReviewTodayItem["schedule"]> }) {
  const { t, tp } = useI18n();
  return (
    <details className="today-schedule" data-schedule={s.class}>
      <summary>{t(s.class === "recovery" ? "today.schedule.recovery" : "today.schedule.due")}</summary>
      <p data-if="completed">{tp("today.schedule.ifCompleted", s.if_completed.interval_days, { day: s.if_completed.day })}</p>
      <p data-if="missed">
        {s.if_missed.interval_days === 0 ? t("today.schedule.ifMissedToday") : tp("today.schedule.ifMissed", s.if_missed.interval_days, { day: s.if_missed.day })}
      </p>
      <p className="hint">{t("today.schedule.rule", { completed: s.if_completed.rule, missed: s.if_missed.rule })}</p>
    </details>
  );
}
