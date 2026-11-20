import { useState } from "react";
import { useI18n, type MessageKey } from "../i18n";
import type { ProposalClass, ReviewedProposal } from "./agentReturn";
import { PacketShare } from "./PacketShare";
import { dispatch, focusSoon } from "./practiceStore";
import type { FixtureCatalog } from "./practiceFixture";
import type { VisitState } from "./practiceSession";

// From one tutor to another, on the sealed fixture's two sessions (no agent
// was run): the study packet each agent received, what it sent back, and the
// read-only review of every proposal before anything is accepted. A candidate
// correction can be marked accepted FOR THIS VISIT only, after a confirmation
// that shows the exact change; the real decision is the learner's command in
// the extraction tool, shown beside it. Exercise proposals stay in the preview
// (the contract has no acceptance for them yet).

export const classKey: Record<ProposalClass, MessageKey> = {
  accepted_candidate: "feedPractice.tutor.class.accepted_candidate",
  duplicate: "feedPractice.tutor.class.duplicate",
  conflict: "feedPractice.tutor.class.conflict",
  unknown_reference: "feedPractice.tutor.class.unknown_reference",
  invalid: "feedPractice.tutor.class.invalid",
};
const classMark: Record<ProposalClass, string> = { accepted_candidate: "+", duplicate: "=", conflict: "≠", unknown_reference: "?", invalid: "!" };

export function TutorSessions({ catalog, visit }: { catalog: FixtureCatalog; visit: VisitState }) {
  const { t, tp } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="feed-tutors" data-tutors={open ? "open" : "closed"}>
      <h4>{t("feedPractice.tutor.heading")}</h4>
      <button type="button" className="ghost" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? t("feedPractice.tutor.hide") : t("feedPractice.tutor.show")}
      </button>
      {open ? (
        <>
          <p className="hint">{t("feedPractice.tutor.intro")}</p>
          {catalog.sessions.map((s) => (
            <section key={s.n} className="listening-item feed-session" aria-label={t("feedPractice.tutor.session", { n: s.n, agent: s.agent })} data-session={s.n} data-agent={s.agent}>
              <h5>{t("feedPractice.tutor.session", { n: s.n, agent: s.agent })}</h5>
              <p className="hint">{s.note}</p>
              {s.packet.continuity ? (
                <div data-left-off={s.packet.packet_id}>
                  <p>{t("feedPractice.tutor.continues", { previous: s.packet.continuity.previous_packet_id })}</p>
                  <ul className="listening-steps">
                    {s.packet.continuity.changed.map((c) => (
                      <li key={c.id}>
                        <code>{c.id}</code> {c.what}
                      </li>
                    ))}
                    {s.packet.last_confusion ? (
                      <li data-last-confusion={s.packet.last_confusion.practice_id}>
                        {t("feedPractice.tutor.lastConfusion", { forms: s.packet.last_confusion.forms.join(" / "), id: s.packet.last_confusion.practice_id })}
                      </li>
                    ) : null}
                    {s.packet.next_exercise ? (
                      <li data-next-exercise={s.packet.next_exercise.id}>{t("feedPractice.tutor.nextExercise", { id: s.packet.next_exercise.id, why: s.packet.next_exercise.why })}</li>
                    ) : null}
                  </ul>
                </div>
              ) : null}
              <PacketShare packet={s.packet} markdown={s.markdown} feedSha={null} idPrefix={`tutor-packet-${s.n}`} />
              <h5>{tp("feedPractice.tutor.returnHeading", s.proposals.length, { agent: s.agent })}</h5>
              <ul className="listening-items feed-proposals" aria-label={tp("feedPractice.tutor.returnHeading", s.proposals.length, { agent: s.agent })}>
                {s.proposals.map((r) => (
                  <ProposalRow
                    key={r.proposal.proposal_id}
                    session={s.n}
                    agent={s.agent}
                    r={r}
                    accepted={visit.accepted.some((a) => a.session === s.n && a.proposalId === r.proposal.proposal_id)}
                    acceptedIn={
                      catalog.sessions.find((x) =>
                        x.packet.knowledge.some((k) => k.accepted_from?.packet_id === s.packet.packet_id && k.accepted_from.proposal_id === r.proposal.proposal_id),
                      )?.packet.packet_id ?? null
                    }
                  />
                ))}
              </ul>
            </section>
          ))}
        </>
      ) : null}
    </div>
  );
}

function ProposalRow({ session, agent, r, accepted, acceptedIn }: { session: number; agent: string; r: ReviewedProposal; accepted: boolean; acceptedIn: string | null }) {
  const { t } = useI18n();
  const [confirm, setConfirm] = useState(false);
  const [showAnswer, setShowAnswer] = useState(false);
  const p = r.proposal;
  const acceptable = r.class === "accepted_candidate" && p.type === "correction";
  return (
    <li className="listening-item" data-proposal={p.proposal_id} data-class={r.class} data-type={p.type}>
      <p>
        <code>{p.proposal_id}</code> <span className="tag">{t(p.type === "correction" ? "feedPractice.tutor.correction" : "feedPractice.tutor.exercise")}</span>{" "}
        <span className="tag" data-class-tag={r.class}>
          <span aria-hidden="true">{classMark[r.class]} </span>
          {t(classKey[r.class])}
        </span>
      </p>
      {r.why ? (
        <p className="hint">
          {t("feedPractice.tutor.why")} <q>{r.why}</q>
        </p>
      ) : null}
      {p.type === "correction" ? (
        <dl className="feed-diff">
          <dt>{t("feedPractice.tutor.target", { id: p.target_id ?? "—", origin: r.targetOrigin ?? "—" })}</dt>
          <dd className="french" data-current>
            {r.current ?? "—"}
          </dd>
          <dt>{t("feedPractice.tutor.proposed")}</dt>
          <dd className="french" data-proposed>
            {p.text ?? "—"}
          </dd>
        </dl>
      ) : (
        <>
          <p>
            <span className="tag">{p.kind ?? "—"}</span>{" "}
            <span lang="fr" className="french">
              {p.prompt ?? "—"}
            </span>
          </p>
          <p className="hint">{t("feedPractice.tutor.knowledge", { ids: (p.knowledge_ids ?? []).join(", ") || "—" })}</p>
          <button type="button" className="link-button" aria-expanded={showAnswer} onClick={() => setShowAnswer((v) => !v)}>
            {showAnswer ? t("feedPractice.tutor.hideAnswer") : t("feedPractice.tutor.showAnswer")}
          </button>
          {showAnswer ? (
            <p lang="fr" className="french" data-proposed-answer>
              {[p.answer, ...(p.accepted ?? [])].filter(Boolean).join(" · ")}
            </p>
          ) : null}
          <p className="hint">{t("feedPractice.tutor.exerciseStays")}</p>
        </>
      )}
      <p className="hint">
        {t("feedPractice.tutor.rationale")} <q>{p.rationale || "—"}</q>
      </p>
      <p className="hint">{p.evidence_ids.length ? t("feedPractice.tutor.evidence", { ids: p.evidence_ids.join(", ") }) : t("feedPractice.tutor.noEvidence")}</p>
      {r.flags.map((f) => (
        <p key={f} className="hint">
          {f}
        </p>
      ))}
      {acceptedIn ? (
        <p className="banner info" data-accepted-in={acceptedIn}>
          {t("feedPractice.tutor.acceptedInTool", { id: p.proposal_id, packet: acceptedIn })}
        </p>
      ) : acceptable ? (
        accepted ? (
          <p className="banner info" data-accepted-visit={p.proposal_id} id={`tutor-accepted-${session}-${p.proposal_id}`} tabIndex={-1}>
            {t("feedPractice.tutor.acceptedVisit", { id: p.proposal_id })}
          </p>
        ) : confirm ? (
          <div
            className="banner warning"
            role="group"
            aria-label={t("feedPractice.tutor.confirmLabel", { id: p.proposal_id })}
            data-confirm={p.proposal_id}
            id={`tutor-confirm-${session}-${p.proposal_id}`}
            tabIndex={-1}
          >
            <p>{t("feedPractice.tutor.confirm", { id: p.proposal_id, agent, target: p.target_id ?? "" })}</p>
            <p className="hint">{t("feedPractice.tutor.realDecision")}</p>
            <pre className="feed-command">
              <code>{`python3 -B -m flh_extraction practice accept --work W --packet packet.json --proposals proposals.json --proposal ${p.proposal_id}`}</code>
            </pre>
            <div className="actions">
              <button
                type="button"
                className="primary"
                onClick={() => {
                  dispatch({ type: "accept", at: new Date().toISOString(), session, proposalId: p.proposal_id });
                  focusSoon(`tutor-accepted-${session}-${p.proposal_id}`);
                }}
              >
                {t("feedPractice.tutor.confirmAccept")}
              </button>
              <button
                type="button"
                className="ghost"
                onClick={() => {
                  setConfirm(false);
                  focusSoon(`tutor-accept-${session}-${p.proposal_id}`);
                }}
              >
                {t("feedPractice.tutor.cancel")}
              </button>
            </div>
          </div>
        ) : (
          <div className="actions">
            <button
              type="button"
              id={`tutor-accept-${session}-${p.proposal_id}`}
              onClick={() => {
                setConfirm(true);
                focusSoon(`tutor-confirm-${session}-${p.proposal_id}`);
              }}
            >
              {t("feedPractice.tutor.accept", { id: p.proposal_id })}
            </button>
          </div>
        )
      ) : (
        <p className="hint" data-not-acceptable={p.proposal_id}>
          {t(p.type === "exercise" ? "feedPractice.tutor.notAcceptableExercise" : "feedPractice.tutor.notAcceptable")}
        </p>
      )}
    </li>
  );
}
