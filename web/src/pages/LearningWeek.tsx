import { useEffect, useState } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import { useI18n } from "../i18n";
import type { SourceOpen } from "../types/notebook";
import type { LearningCorrection, LearningWeek as LearningWeekData } from "../types/reviewToday";

// This week (learning_week_v1, private workbench): counts of what the learner
// did in the last seven local days, read from stored records on every visit.
// Production practice and reviewed material are counted apart; the learner's
// own corrections apart from feedback a provider wrote. Each count is one
// item per kind and day, so a repeated save never inflates it. Below the
// server's threshold only counts are shown, never a percentage.

const describe = (e: unknown) => (e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e));

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: LearningWeekData };

export function LearningWeek({ onOpenSource, epoch = 0 }: { onOpenSource: (open: SourceOpen) => void; epoch?: number }) {
  const { t, tp, locale } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  useEffect(() => {
    let live = true;
    api.getLearningWeek().then(
      (data) => live && setLoad({ status: "ready", data }),
      (e) => live && setLoad({ status: "error", message: describe(e) }),
    );
    return () => {
      live = false;
    };
  }, [epoch]);
  // A stored day (YYYY-MM-DD in the learner's zone) shown as that calendar day.
  const dayLabel = (day: string) => {
    const d = new Date(`${day}T12:00:00Z`);
    return Number.isNaN(d.getTime()) ? day : d.toLocaleDateString(locale, { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
  };
  if (load.status === "loading") return <p className="hint" role="status">{t("week.loading")}</p>;
  if (load.status === "error")
    return (
      <p className="hint" role="status">
        {t("week.unavailable", { message: load.message })}
      </p>
    );
  const w = load.data;
  const n = w.totals;
  const open = (c: LearningCorrection): SourceOpen | null =>
    c.skill === "speaking" && c.exercise_id && c.take_id
      ? { skill: "speaking", exerciseId: c.exercise_id, takeId: c.take_id, transcriptVersion: c.version }
      : c.skill === "writing" && c.task_id
        ? { skill: "writing", taskId: c.task_id, draftVersion: c.version }
        : null;
  return (
    <section className="today-week" aria-label={t("week.region")}>
      <h3>{t("week.heading", { from: dayLabel(w.from), to: dayLabel(w.to) })}</h3>
      <p className="hint">{t("week.zone", { zone: w.zone })}</p>
      <dl className="studio-facts week-definitions">
        <dt>{t("week.col.production")}</dt>
        <dd>{t("week.def.production")}</dd>
        <dt>{t("week.col.reviewed")}</dt>
        <dd>{t("week.def.reviewed")}</dd>
        <dt>{t("week.col.corrections")}</dt>
        <dd>{t("week.def.corrections")}</dd>
        <dt>{t("week.col.feedback")}</dt>
        <dd>{t("week.def.feedback")}</dd>
      </dl>
      <table className="week-table">
        <caption className="visually-hidden">{t("week.caption", { zone: w.zone })}</caption>
        <thead>
          <tr>
            <th scope="col">{t("week.col.day")}</th>
            <th scope="col">{t("week.col.production")}</th>
            <th scope="col">{t("week.col.reviewed")}</th>
            <th scope="col">{t("week.col.corrections")}</th>
            <th scope="col">{t("week.col.feedback")}</th>
          </tr>
        </thead>
        <tbody>
          {w.days.map((d) => (
            <tr key={d.day} data-day={d.day}>
              <th scope="row">{dayLabel(d.day)}</th>
              <td>{d.production}</td>
              <td>{d.reviewed}</td>
              <td>{d.own_corrections}</td>
              <td>{d.provider_feedback}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p role="status" data-week="totals">
        {t("week.totals", {
          production: n.production,
          exercises: n.distinct_exercises,
          reviewed: n.reviewed,
          corrections: n.own_corrections,
          feedback: n.provider_feedback,
          active: n.active_days,
        })}
      </p>
      <p className="hint" data-week="share">
        {w.sparse || w.production_share === null
          ? t("week.sparse", { min: w.min_for_shares })
          : t("week.share", { share: w.production_share, total: n.production + n.reviewed })}
      </p>
      {n.duplicates_ignored > 0 ? <p className="hint">{tp("week.duplicates", n.duplicates_ignored)}</p> : null}
      <h4>{t("week.corrections.heading")}</h4>
      {w.corrections.length === 0 ? (
        <p className="hint">{t("week.corrections.none")}</p>
      ) : (
        <ul className="listening-steps" aria-label={t("week.corrections.heading")}>
          {w.corrections.map((c) => {
            const target = open(c);
            return (
              <li key={`${c.skill}-${c.exercise_id ?? c.task_id}-${c.take_id ?? 0}-${c.version}`} data-skill={c.skill}>
                {c.skill === "speaking"
                  ? c.prior_version === 0
                    ? t("week.corrections.speakingMachine", { title: c.title, take: c.take_number ?? 0, version: c.version, day: dayLabel(c.day) })
                    : t("week.corrections.speaking", { title: c.title, take: c.take_number ?? 0, version: c.version, prior: c.prior_version, day: dayLabel(c.day) })
                  : t("week.corrections.writing", { title: c.title, version: c.version, prior: c.prior_version, day: dayLabel(c.day) })}{" "}
                {target ? (
                  <button type="button" className="link-button" onClick={() => onOpenSource(target)}>
                    {c.skill === "speaking" ? t("week.corrections.openTake", { take: c.take_number ?? 0, version: c.version }) : t("week.corrections.openDraft", { version: c.version })}
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
