import { useRef, useState } from "react";
import { useI18n, type MessageKey } from "../i18n";
import { outcomeKey, outcomeMark } from "./ConceptPractice";
import { dispatch, focusSoon } from "./practiceStore";
import type { FixtureCatalog } from "./practiceFixture";
import {
  availability,
  byDay,
  current,
  exportVisit,
  localDay,
  originOf,
  summarize,
  timeline,
  weekDays,
  type OutcomeOrigin,
  type Skill,
  type VisitState,
} from "./practiceSession";

// This visit's history (PROTOTYPE): what was practised, by skill and by the
// learner's local day, where each outcome comes from, what changed during the
// visit (with reason codes), and a JSON copy the learner can keep. It is page
// memory only and disappears on reload, as the heading says.

const originKey: Record<OutcomeOrigin | "agent_suggestion", MessageKey> = {
  agent_suggestion: "feedPractice.log.origin.agent_suggestion",
  exact_match: "feedPractice.log.origin.exact_match",
  learner_judgment: "feedPractice.log.origin.learner_judgment",
  revealed: "feedPractice.log.origin.revealed",
  extraction_record: "feedPractice.log.origin.extraction_record",
};
const skillKey: Record<Skill, MessageKey> = {
  recall: "feedPractice.skill.recall",
  recognition: "feedPractice.skill.recognition",
  production: "feedPractice.skill.production",
};
const eventKey: Record<string, MessageKey> = {
  revision_waiting: "feedPractice.event.revision_waiting",
  revision_applied: "feedPractice.event.revision_applied",
  withdrawn_source_revised: "feedPractice.event.withdrawn_source_revised",
  restored_same_id: "feedPractice.event.restored_same_id",
  draft_kept_withdrawn: "feedPractice.event.draft_kept_withdrawn",
  late_response_withdrawn: "feedPractice.event.late_response_withdrawn",
  late_response_revision_changed: "feedPractice.event.late_response_revision_changed",
  mistake_converted: "feedPractice.event.mistake_converted",
  proposal_accepted_for_visit: "feedPractice.event.proposal_accepted_for_visit",
};

export const learnerZone = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
};

export function PracticeLog({
  catalog,
  visit,
  onPractise,
  zone = learnerZone(),
  now = () => new Date(),
}: {
  catalog: FixtureCatalog;
  visit: VisitState;
  onPractise: (sourceId: string, practiceId: string) => void;
  zone?: string;
  now?: () => Date;
}) {
  const { t, tp } = useI18n();
  const [withAnswers, setWithAnswers] = useState(false);
  const [copy, setCopy] = useState<"idle" | "copied" | "selected">("idle");
  const [shown, setShown] = useState<string | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const sum = summarize(visit.attempts, visit.checks);
  const today = localDay(now().toISOString(), zone);
  const week = weekDays(today);
  const days = byDay(visit.attempts, zone);
  const acceptedByDay = new Map<string, VisitState["accepted"]>();
  for (const a of visit.accepted) acceptedByDay.set(localDay(a.at, zone), [...(acceptedByDay.get(localDay(a.at, zone)) ?? []), a]);
  for (const d of acceptedByDay.keys()) if (!days.some((x) => x.day === d)) days.push({ day: d, attempts: [] });
  days.sort((a, b) => (a.day < b.day ? 1 : -1));
  const perDay = new Map(days.map((d) => [d.day, d.attempts]));
  const weekTotal = week.reduce((n, d) => n + (perDay.get(d)?.length ?? 0), 0);
  const conceptOf = (sourceId: string) => timeline(catalog, sourceId).concept;
  const time = (iso: string) => new Intl.DateTimeFormat("en-GB", { timeZone: zone, hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
  const confusions = [...new Map(visit.attempts.filter((a) => a.outcome === "incorrect").map((a) => [`${a.sourceId}/${a.practiceId}`, a])).values()];
  const doExport = async () => {
    const text = JSON.stringify(exportVisit(catalog, visit, { includeAnswers: withAnswers, zone, exportedAt: now().toISOString() }), null, 1);
    try {
      if (!navigator.clipboard?.writeText) throw new Error("no clipboard");
      await navigator.clipboard.writeText(text);
      setCopy("copied");
      setShown(null);
    } catch {
      setShown(text);
      setCopy("selected");
      requestAnimationFrame(() => {
        area.current?.focus();
        area.current?.select();
      });
    }
  };
  return (
    <div className="feed-log" data-log="visit">
      <h4>{t("feedPractice.log.heading")}</h4>
      <p className="hint" data-ephemeral="page">
        {t("feedPractice.log.ephemeral", { zone })}
      </p>

      <table className="feed-skills" data-skills="visit">
        <caption>{t("feedPractice.log.bySkill")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("feedPractice.log.col.skill")}</th>
            <th scope="col">{t("feedPractice.log.col.independent")}</th>
            <th scope="col">{t("feedPractice.log.col.afterReveal")}</th>
            <th scope="col">{t("feedPractice.log.col.revealed")}</th>
          </tr>
        </thead>
        <tbody>
          {(["recall", "recognition", "production"] as Skill[]).map((k) => (
            <tr key={k} data-skill={k}>
              <th scope="row">{t(skillKey[k])}</th>
              <td>
                {t("feedPractice.log.independentCell", {
                  n: sum[k].independent,
                  correct: sum[k].correct,
                  notYet: sum[k].notYet,
                  self: sum[k].selfGot + sum[k].selfNotYet + sum[k].selfOpen,
                  invalid: sum[k].invalid,
                })}
              </td>
              <td>{sum[k].afterReveal}</td>
              <td>{sum[k].revealed}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h5>{t("feedPractice.log.week", { from: week[0], to: week[6] })}</h5>
      {weekTotal === 0 ? (
        <p className="hint" data-week="empty">
          {t("feedPractice.log.weekEmpty")}
        </p>
      ) : (
        <ul className="feed-week" data-week="active" aria-label={t("feedPractice.log.week", { from: week[0], to: week[6] })}>
          {week.map((d) => {
            const xs = perDay.get(d) ?? [];
            const s = summarize(xs, visit.checks).all;
            return (
              <li key={d} data-day={d} data-count={xs.length}>
                <span className="label">{d}</span> {xs.length ? t("feedPractice.log.dayCounts", { independent: s.independent, afterReveal: s.afterReveal, revealed: s.revealed }) : t("feedPractice.log.dayNone")}
              </li>
            );
          })}
        </ul>
      )}

      {days.length ? (
        <>
          <h5>{t("feedPractice.log.history")}</h5>
          {days.map((d) => (
            <div key={d.day} data-history-day={d.day}>
              <p className="label">{d.day}</p>
              <ul className="listening-steps feed-history">
                {d.attempts.map((a) => {
                  const av = availability(catalog, visit, a.sourceId, a.practiceId);
                  const origin = originOf(a, visit.checks);
                  return (
                    <li key={a.op} data-entry={a.op} data-origin={origin} data-availability={av.status} data-reason-code={av.code}>
                      <span className="hint">{time(a.at)}</span> <span className="tag">{t(originKey[origin])}</span>{" "}
                      <span className="tag" data-outcome-tag={a.outcome}>
                        <span aria-hidden="true">{outcomeMark[a.outcome]} </span>
                        {t(outcomeKey[a.outcome])}
                      </span>{" "}
                      {a.afterReveal ? <span className="tag">{t("feedPractice.afterReveal")}</span> : null} {conceptOf(a.sourceId)} <code>{a.practiceId}</code>{" "}
                      <span className="hint">{t("feedPractice.log.onRevision", { revision: a.revision })}</span>{" "}
                      {av.status === "withdrawn" ? <span className="tag">{t("feedPractice.log.withdrawnSince", { revision: av.revision })}</span> : null}
                      {av.status === "active" && av.code === "restored_same_id" ? <span className="tag">{t("feedPractice.log.restoredOn", { revision: av.revision })}</span> : null}
                    </li>
                  );
                })}
                {(acceptedByDay.get(d.day) ?? []).map((a) => (
                  <li key={`acc-${a.session}-${a.proposalId}`} data-entry={`accepted:${a.session}:${a.proposalId}`} data-origin="agent_suggestion">
                    <span className="hint">{time(a.at)}</span> <span className="tag">{t(originKey.agent_suggestion)}</span>{" "}
                    {t("feedPractice.log.acceptedEntry", { agent: a.agent, proposal: a.proposalId, target: a.targetId })}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </>
      ) : null}

      {confusions.length ? (
        <>
          <h5>{t("feedPractice.log.confusions")}</h5>
          <ul className="listening-steps" aria-label={t("feedPractice.log.confusions")}>
            {confusions.map((a) => {
              const av = availability(catalog, visit, a.sourceId, a.practiceId);
              return (
                <li key={`${a.sourceId}/${a.practiceId}`} data-confusion={a.practiceId}>
                  {conceptOf(a.sourceId)} <code>{a.practiceId}</code>{" "}
                  {a.grade?.knownError ? <span className="hint">{t("feedPractice.result.knownError", { error: a.grade.knownError })}</span> : null}{" "}
                  {av.status === "active" ? (
                    <button type="button" className="link-button" onClick={() => onPractise(a.sourceId, a.practiceId)}>
                      {t("feedPractice.log.practiseAgain", { id: a.practiceId })}
                    </button>
                  ) : (
                    <span className="tag">{t("feedPractice.log.withdrawnSince", { revision: av.revision })}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      ) : null}

      {visit.personal.length ? (
        <>
          <h5>{t("feedPractice.log.personal")}</h5>
          <ul className="listening-steps">
            {visit.personal.map((p) => (
              <li key={p.id} data-personal={p.id} data-done={p.done} id={`practice-personal-${p.id}`} tabIndex={-1}>
                <code>{p.id}</code> {t("feedPractice.log.personalFrom", { id: p.practiceId, revision: p.revision, evidence: p.evidenceIds.join(", ") || "—", error: p.knownError })}{" "}
                {p.done ? (
                  <span className="tag">{t("feedPractice.log.personalDone")}</span>
                ) : (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => {
                      dispatch({ type: "personalDone", id: p.id });
                      focusSoon(`practice-personal-${p.id}`);
                    }}
                  >
                    {t("feedPractice.log.markDone", { id: p.id })}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <h5>{t("feedPractice.log.recorded")}</h5>
      <ul className="listening-steps" data-recorded="feed">
        {catalog.timelines.map((tl) => {
          const st = current(catalog, visit, tl.sourceId);
          const n = st.feed.items.reduce((m, it) => m + it.outcomes.length, 0);
          const fromAgents = (st.data?.knowledge ?? []).filter((k) => k.accepted_from);
          return (
            <li key={tl.sourceId} data-origin="extraction_record">
              <span className="tag">{t(originKey.extraction_record)}</span> {tp("feedPractice.log.recordedRow", n, { concept: tl.concept, revision: st.feed.source.revision })}
              {fromAgents.map((k) => (
                <span key={k.id} className="hint" data-origin="agent_suggestion" data-accepted-in-tool={`${k.accepted_from!.agent}:${k.accepted_from!.proposal_id}`}>
                  {" "}
                  <span className="tag">{t(originKey.agent_suggestion)}</span>{" "}
                  {t("feedPractice.log.acceptedInTool", { agent: k.accepted_from!.agent, proposal: k.accepted_from!.proposal_id, target: k.id })}
                </span>
              ))}
            </li>
          );
        })}
      </ul>

      {visit.events.length ? (
        <details className="feed-events">
          <summary>{tp("feedPractice.log.events", visit.events.length)}</summary>
          <ul className="listening-steps">
            {visit.events.map((e, i) => (
              <li key={i} data-reason-code={e.code}>
                <code>{e.code}</code> {t(eventKey[e.code] ?? "feedPractice.event.unknown", { source: e.sourceId, id: e.practiceId ?? "", revision: e.revision ?? "", detail: e.detail ?? "" })}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <div className="feed-export">
        <label className="checkbox">
          <input type="checkbox" checked={withAnswers} onChange={(e) => setWithAnswers(e.target.checked)} /> {t("feedPractice.log.includeAnswers")}
        </label>
        <div className="actions">
          <button type="button" onClick={() => void doExport()}>
            {t("feedPractice.log.export")}
          </button>
        </div>
        <p role="status" aria-live="polite" data-export={copy}>
          {copy === "copied" ? t(withAnswers ? "feedPractice.log.exportedWith" : "feedPractice.log.exportedWithout") : copy === "selected" ? t("feedPractice.packet.selected") : ""}
        </p>
        {shown !== null ? (
          <>
            <label htmlFor="feed-visit-export">{t("feedPractice.log.exportLabel")}</label>
            <textarea id="feed-visit-export" ref={area} className="feed-packet-text" readOnly rows={8} value={shown} />
          </>
        ) : null}
      </div>
    </div>
  );
}
