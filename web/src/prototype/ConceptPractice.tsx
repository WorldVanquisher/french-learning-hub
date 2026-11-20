import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useI18n, type MessageKey } from "../i18n";
import { excerptParts, type ConceptPracticeData, type FeedItem, type Outcome } from "./practiceFeed";
import { applyWaiting, consumeFocus, dispatch, focusSoon, reveal, submitAnswer, usePracticeVisit } from "./practiceStore";
import {
  availability,
  current,
  draftKey,
  lastOffered,
  nextExercise,
  seenOutcomes,
  summarize,
  timeline,
  type VisitAttempt,
  type VisitState,
} from "./practiceSession";
import type { FixtureCatalog } from "./practiceFixture";
import { PacketShare } from "./PacketShare";

// Practice from an approved concept (PROTOTYPE, private workbench), on the
// sealed Extraction 2.1 fixture. The learner recalls before anything is
// revealed, opens the source after recalling (or by an explicit reveal),
// answers new-sentence and choice exercises graded like the extraction lane,
// can leave an exercise to inspect its evidence and come back to it, and
// copies a study packet (no answer keys) for another agent.
//
// A source revision can arrive during the visit: withdrawn exercises leave
// active practice with the reason, their history stays, unsent drafts are kept,
// and a late check can never complete a withdrawn exercise.
//
// Nothing here is stored or sent: the visit lives in practiceStore (page
// memory) and DISAPPEARS ON RELOAD, as the page says. Storing it needs the
// owner's migration (docs/plans/PRACTICE-STORAGE-DECISION.md).

export const outcomeKey: Record<Outcome, MessageKey> = {
  correct: "feedPractice.outcome.correct",
  incorrect: "feedPractice.outcome.incorrect",
  self_check: "feedPractice.outcome.self_check",
  revealed: "feedPractice.outcome.revealed",
  invalid: "feedPractice.outcome.invalid",
};
// A text mark beside every outcome, so it never relies on colour alone.
export const outcomeMark: Record<Outcome, string> = { correct: "✓", incorrect: "✗", self_check: "?", revealed: "👁", invalid: "!" };
const fieldKey: Record<string, MessageKey> = {
  original_input: "feedPractice.field.original_input",
  original_context: "feedPractice.field.original_context",
  explanation: "feedPractice.field.explanation",
};
const originKey: Record<string, MessageKey> = {
  source: "feedPractice.origin.source",
  learner: "feedPractice.origin.learner",
  generated: "feedPractice.origin.generated",
};
const nextWhyKey: Record<string, MessageKey> = {
  after_miss_other_sentence: "feedPractice.next.after_miss_other_sentence",
  after_miss_recall_rule: "feedPractice.next.after_miss_recall_rule",
  after_miss_retry: "feedPractice.next.after_miss_retry",
  first_not_yet_correct: "feedPractice.next.first_not_yet_correct",
};
export const fieldId = (practiceId: string) => `feed-${practiceId}`;
const cardId = (practiceId: string) => `feed-card-${practiceId}`;

const reducedMotion = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
// Scrolling follows the learner's motion preference.
export const scrollOpts = (): ScrollIntoViewOptions => ({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });

export function ConceptPractice({ sourceId, onExit }: { sourceId: string; onExit: () => void }) {
  const { t, tp } = useI18n();
  const { catalog, visit, focusItem } = usePracticeVisit();
  const heading = useRef<HTMLHeadingElement>(null);
  const sections = useRef<Record<string, HTMLHeadingElement | null>>({});
  useEffect(() => {
    // Open on the heading, or straight on one exercise (from today's set).
    if (focusItem) {
      const el = document.getElementById(fieldId(focusItem)) ?? document.getElementById(cardId(focusItem));
      if (el) {
        el.scrollIntoView?.(scrollOpts());
        el.focus();
        consumeFocus();
        return;
      }
    }
    heading.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (!catalog) return null;
  const tl = timeline(catalog, sourceId);
  const st = current(catalog, visit, sourceId);
  const data = st.data;
  const s = st.feed.source;
  const jump = (k: string) => {
    const el = sections.current[k];
    el?.scrollIntoView?.(scrollOpts());
    el?.focus();
  };
  const sectionHead = (k: string, label: string) => (
    <h3
      ref={(el) => {
        sections.current[k] = el;
      }}
      tabIndex={-1}
    >
      {label}
    </h3>
  );
  const focusExercise = (pid: string) => {
    const el = document.getElementById(fieldId(pid)) ?? document.getElementById(cardId(pid));
    el?.scrollIntoView?.(scrollOpts());
    el?.focus();
  };
  const inspect = (pid: string) => {
    dispatch({ type: "resume", sourceId, practiceId: pid });
    jump("source");
  };
  const mine = visit.attempts.filter((a) => a.sourceId === sourceId);
  const explain = data?.items.find((i) => i.kind === "explain") ?? null;
  const recalled = !explain || mine.some((a) => a.practiceId === explain.practice_id);
  const next = data ? nextExercise(data, seenOutcomes(catalog, visit, sourceId)) : null;
  return (
    <section className="panel concept-practice" aria-label={t("feedPractice.region")} data-source-id={sourceId} data-revision={s.revision}>
      <div className="actions">
        <button type="button" className="ghost" onClick={onExit}>
          {t("feedPractice.exit")}
        </button>
      </div>
      <h2 ref={heading} tabIndex={-1}>
        {t("feedPractice.heading", { concept: tl.concept })}
      </h2>
      <p>
        <span className="tag">{t("feedPractice.tag.prototype")}</span> <span className="tag">{t("feedPractice.tag.synthetic")}</span>{" "}
        <span className="tag">{t("feedPractice.tag.approved")}</span>
      </p>
      {data ? <p className="hint">{t("feedPractice.goal", { goal: data.goal, level: data.level })}</p> : null}
      <p className="hint" data-revision-line={s.revision} id={`feed-revision-${sourceId}`} tabIndex={-1}>
        {t("feedPractice.sourceLine", { source: s.source_id, revision: s.revision, sha: s.revision_sha256.slice(0, 12) })}
      </p>
      <div className="banner info" role="note" data-ephemeral="page">
        {t("feedPractice.ephemeral")}
      </div>
      <RevisionNotices catalog={catalog} visit={visit} sourceId={sourceId} />
      <VisitSummary attempts={mine} checks={visit.checks} />
      {data ? (
        <>
          {next ? (
            <div className="feed-next" data-next={next.item.practice_id} data-next-why={next.why} data-transfer={next.transfer}>
              {next.transfer ? (
                <p className="banner info" data-reason-code="transfer_after_repeated_confusion">
                  {t("feedPractice.next.transfer", { count: next.contrastMisses })}
                </p>
              ) : null}
              <p>
                <span className="label">{t("feedPractice.next.label")}</span>{" "}
                <span lang="fr" className="french">
                  {next.item.prompt}
                </span>{" "}
                <code>{next.item.practice_id}</code>
              </p>
              <p className="hint">{t(nextWhyKey[next.why], { missed: next.missed ?? "" })}</p>
              <div className="actions">
                <button type="button" className="primary" onClick={() => focusExercise(next.item.practice_id)}>
                  {t("feedPractice.next.start")}
                </button>
              </div>
            </div>
          ) : (
            <p className="hint" data-next="none">
              {t("feedPractice.next.none")}
            </p>
          )}
          <nav className="actions concept-practice-jump" aria-label={t("feedPractice.jump")}>
            {(
              [
                ["recall", "feedPractice.recall.heading"],
                ["source", "feedPractice.source.heading"],
                ["produce", "feedPractice.produce.heading"],
                ["choose", "feedPractice.choose.heading"],
                ["packet", "feedPractice.packet.heading"],
              ] as [string, MessageKey][]
            ).map(([k, key]) => (
              <button key={k} type="button" className="link-button" onClick={() => jump(k)}>
                {t(key)}
              </button>
            ))}
          </nav>
          <p className="hint">{t("feedPractice.keys")}</p>

          {explain ? (
            <div className="concept-practice-section" data-section="recall">
              {sectionHead("recall", t("feedPractice.recall.heading"))}
              <ExerciseCard sourceId={sourceId} item={explain} data={data} visit={visit} onInspect={inspect} />
            </div>
          ) : null}

          <div className="concept-practice-section" data-section="source">
            {sectionHead("source", t("feedPractice.source.heading"))}
            {visit.resume && visit.resume.sourceId === sourceId ? (
              <div className="actions" data-resume={visit.resume.practiceId}>
                <button
                  type="button"
                  className="primary"
                  onClick={() => {
                    const pid = visit.resume!.practiceId;
                    dispatch({ type: "resumeClear" });
                    focusExercise(pid);
                  }}
                >
                  {t("feedPractice.resume.back", { id: visit.resume.practiceId })}
                </button>
              </div>
            ) : null}
            <SourceView
              data={data}
              recalled={recalled}
              doneWith={(id) => mine.some((a) => a.practiceId === id)}
              onRevealRecall={() => explain && reveal(sourceId, explain.practice_id)}
              accepted={visit.accepted}
            />
          </div>

          <div className="concept-practice-section" data-section="produce">
            {sectionHead("produce", t("feedPractice.produce.heading"))}
            <p className="hint">{t("feedPractice.produce.hint")}</p>
            {data.items
              .filter((i) => i.kind === "produce")
              .map((it) => (
                <ExerciseCard key={it.practice_id} sourceId={sourceId} item={it} data={data} visit={visit} onInspect={inspect} />
              ))}
          </div>

          <div className="concept-practice-section" data-section="choose">
            {sectionHead("choose", t("feedPractice.choose.heading"))}
            {data.items
              .filter((i) => i.kind === "choose")
              .map((it) => (
                <ExerciseCard key={it.practice_id} sourceId={sourceId} item={it} data={data} visit={visit} onInspect={inspect} />
              ))}
          </div>

          <div className="concept-practice-section" data-section="packet">
            {sectionHead("packet", t("feedPractice.packet.heading"))}
            <PacketShare packet={data.studyPacket.packet} markdown={data.studyPacket.markdown} feedSha={st.feedSha} idPrefix={`feed-packet-${sourceId}`} />
          </div>
          <p className="hint">{tp("feedPractice.feedOutcomes", data.items.length)}</p>
        </>
      ) : (
        <p className="banner info" data-nothing-offered={s.revision}>
          {t("feedPractice.nothingOffered", { revision: s.revision })}
        </p>
      )}
    </section>
  );
}

// What a revision changed for this source: waiting, withdrawn, restored, kept drafts.
export function RevisionNotices({ catalog, visit, sourceId }: { catalog: FixtureCatalog; visit: VisitState; sourceId: string }) {
  const { t, tp } = useI18n();
  const st = current(catalog, visit, sourceId);
  const waiting = visit.waiting[sourceId];
  const tl = timeline(catalog, sourceId);
  const withdrawn = st.feed.withdrawn ?? [];
  const restored = st.feed.items.filter((it) => availability(catalog, visit, sourceId, it.practice_id).code === "restored_same_id");
  const kept = visit.kept.filter((k) => k.sourceId === sourceId);
  return (
    <>
      {waiting !== undefined ? (
        <div className="banner warning" role="alert" data-reason-code="revision_waiting">
          <p>{t("feedPractice.rev.waiting", { revision: tl.states[waiting].feed.source.revision })}</p>
          <div className="actions">
            <button
              type="button"
              className="primary"
              onClick={() => {
                applyWaiting(sourceId);
                focusSoon(`feed-revision-${sourceId}`);
              }}
            >
              {t("feedPractice.rev.apply", { revision: tl.states[waiting].feed.source.revision })}
            </button>
          </div>
        </div>
      ) : null}
      {withdrawn.length ? (
        <div className="feed-withdrawn" data-reason-code="withdrawn_source_revised">
          <h3>{tp("feedPractice.rev.withdrawnHeading", withdrawn.length, { revision: st.feed.source.revision })}</h3>
          <p>{t("feedPractice.rev.withdrawnWhy")}</p>
          <ul className="listening-steps">
            {withdrawn.map((w) => {
              const off = lastOffered(catalog, visit, sourceId, w.practice_id);
              const n = visit.attempts.filter((a) => a.sourceId === sourceId && a.practiceId === w.practice_id).length;
              return (
                <li key={w.practice_id} data-withdrawn={w.practice_id} data-reason-code="withdrawn_source_revised">
                  <code>{w.practice_id}</code> {off ? <span lang="fr" className="french">{off.item.prompt}</span> : null}
                  <span className="hint">
                    {" "}
                    {t("feedPractice.rev.producerReason")} <q>{w.reason}</q> {n ? tp("feedPractice.rev.historyKept", n) : t("feedPractice.rev.historyNone")}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {restored.length ? (
        <p className="banner info" data-reason-code="restored_same_id">
          {tp("feedPractice.rev.restored", restored.length, { revision: st.feed.source.revision, ids: restored.map((r) => r.practice_id).join(", ") })}
        </p>
      ) : null}
      {kept.length ? (
        <div className="feed-kept" data-reason-code="draft_kept_withdrawn">
          <h3 id={`feed-kept-${sourceId}`} tabIndex={-1}>
            {t("feedPractice.kept.heading")}
          </h3>
          <p className="hint">{t("feedPractice.kept.why")}</p>
          <ul className="listening-steps">
            {kept.map((k) => (
              <li key={k.practiceId} data-kept={k.practiceId}>
                <code>{k.practiceId}</code>{" "}
                <span lang="fr" className="french">
                  {k.text}
                </span>{" "}
                <button
                  type="button"
                  className="link-button"
                  onClick={() => {
                    dispatch({ type: "discardKept", sourceId, practiceId: k.practiceId });
                    focusSoon(kept.length > 1 ? `feed-kept-${sourceId}` : `feed-revision-${sourceId}`);
                  }}
                >
                  {t("feedPractice.kept.discard", { id: k.practiceId })}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
}

// This visit's counts: independent answers, answers after a reveal, and reveals, kept apart.
export function VisitSummary({ attempts, checks }: { attempts: VisitAttempt[]; checks: Record<string, "got" | "notyet"> }) {
  const { t } = useI18n();
  const a = summarize(attempts, checks).all;
  return (
    <p role="status" aria-live="polite" data-practice="summary" data-independent={a.independent} data-after-reveal={a.afterReveal} data-revealed={a.revealed}>
      {t("feedPractice.summary2", {
        independent: a.independent,
        correct: a.correct,
        notYet: a.notYet,
        selfGot: a.selfGot,
        selfNotYet: a.selfNotYet,
        selfOpen: a.selfOpen,
        invalid: a.invalid,
        afterReveal: a.afterReveal,
        revealed: a.revealed,
      })}
    </p>
  );
}

// One exercise. Answers before keys: the key, accepted answers, explanation
// and excerpts appear only after an attempt or an explicit reveal, and a
// reveal is recorded as "revealed", never as an attempt (the contract).
function ExerciseCard({ sourceId, item, data, visit, onInspect }: { sourceId: string; item: FeedItem; data: ConceptPracticeData; visit: VisitState; onInspect: (pid: string) => void }) {
  const { t } = useI18n();
  const [empty, setEmpty] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const k = draftKey(sourceId, item.practice_id);
  const text = visit.drafts[k] ?? "";
  const mine = visit.attempts.filter((a) => a.sourceId === sourceId && a.practiceId === item.practice_id);
  const last = mine[mine.length - 1];
  const pending = visit.pending.some((p) => p.sourceId === sourceId && p.practiceId === item.practice_id);
  const refused = [...visit.events].reverse().find((e) => e.sourceId === sourceId && e.practiceId === item.practice_id && e.code.startsWith("late_response"));
  const showRefused = refused && (!last || last.at < refused.at);
  const id = fieldId(item.practice_id);
  const submit = (answer: string) => {
    if (!answer.trim()) {
      setEmpty(true);
      field.current?.focus();
      return;
    }
    setEmpty(false);
    submitAnswer(sourceId, item.practice_id, answer);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      submit(text);
    }
  };
  const label: MessageKey = item.kind === "explain" ? "feedPractice.answer.recall" : "feedPractice.answer.sentence";
  const converted = last ? visit.personal.find((p) => p.fromOp === last.op) : undefined;
  return (
    <div
      className="listening-item feed-exercise"
      role="group"
      id={cardId(item.practice_id)}
      tabIndex={-1}
      aria-label={t("feedPractice.card", { id: item.practice_id })}
      data-practice={item.practice_id}
      data-kind={item.kind}
      data-state={pending ? "pending" : last ? (last.action === "reveal" ? "revealed" : "done") : "open"}
    >
      <p>
        <span lang="fr" className="french">
          {item.prompt}
        </span>
      </p>
      <p className="hint">
        {t("feedPractice.measures", { measures: item.measures })}{" "}
        {item.new_sentence ? <span className="tag">{t("feedPractice.newSentence")}</span> : null} <code>{item.practice_id}</code>
      </p>
      {item.kind === "choose" ? (
        <div className="actions" role="group" aria-label={t("feedPractice.choose.options")}>
          {(item.options ?? []).map((o) => (
            <button
              key={o}
              type="button"
              lang="fr"
              id={o === item.options![0] ? id : undefined}
              aria-pressed={last?.grade?.chosen === o}
              aria-disabled={pending}
              onClick={() => {
                if (pending) return;
                dispatch({ type: "draft", sourceId, practiceId: item.practice_id, text: o });
                submitAnswer(sourceId, item.practice_id, o);
              }}
            >
              {o}
            </button>
          ))}
        </div>
      ) : (
        <>
          <label htmlFor={id}>{t(label)}</label>
          <textarea
            id={id}
            ref={field}
            lang="fr"
            rows={item.kind === "explain" ? 3 : 2}
            value={text}
            aria-invalid={empty}
            aria-describedby={empty ? `${id}-empty` : undefined}
            onKeyDown={onKey}
            onChange={(e) => {
              dispatch({ type: "draft", sourceId, practiceId: item.practice_id, text: e.target.value });
              if (e.target.value.trim()) setEmpty(false);
            }}
          />
          {empty ? (
            <p id={`${id}-empty`} className="banner error" role="alert">
              {t("feedPractice.answer.empty")}
            </p>
          ) : null}
          <div className="actions">
            <button type="button" className="primary" aria-disabled={pending} onClick={() => !pending && submit(text)}>
              {item.kind === "explain" ? t("feedPractice.answer.checkRecall") : t("feedPractice.answer.check")}
            </button>
          </div>
        </>
      )}
      <div className="actions">
        {mine.length === 0 ? (
          <button type="button" className="ghost" aria-disabled={pending} onClick={() => !pending && reveal(sourceId, item.practice_id)}>
            {t("feedPractice.revealOnly")}
          </button>
        ) : null}
        <button type="button" className="link-button" onClick={() => onInspect(item.practice_id)}>
          {t("feedPractice.resume.inspect")}
        </button>
      </div>
      <p className="feed-state" role="status" aria-live="polite" data-announce={pending ? "pending" : last ? (last.action === "reveal" ? "revealed" : "done") : "none"}>
        {pending
          ? t("feedPractice.state.pending")
          : showRefused
            ? t(refused!.code === "late_response_withdrawn" ? "feedPractice.state.refusedWithdrawn" : "feedPractice.state.refusedRevision")
            : last
              ? last.action === "reveal"
                ? t("feedPractice.state.revealed")
                : t("feedPractice.state.done", { outcome: t(outcomeKey[last.outcome]) })
              : ""}
      </p>
      {last ? (
        <div className="feed-result" data-outcome={last.outcome}>
          <p>
            <span className="tag" data-outcome-tag={last.outcome}>
              <span aria-hidden="true">{outcomeMark[last.outcome]} </span>
              {t(outcomeKey[last.outcome])}
            </span>{" "}
            {last.afterReveal ? <span className="tag">{t("feedPractice.afterReveal")}</span> : null}{" "}
            {last.grade?.matched ? t("feedPractice.result.matched", { answer: last.grade.matched }) : null}
            {last.grade?.knownError ? t("feedPractice.result.knownError", { error: last.grade.knownError }) : null}
            {last.outcome === "self_check" && item.kind !== "explain" ? t("feedPractice.result.selfCheck") : null}
            {last.outcome === "invalid" ? t("feedPractice.result.invalid", { options: (item.options ?? []).join(" / ") }) : null}
          </p>
          <Reveal item={item} data={data} />
          {last.outcome === "self_check" || item.kind === "explain" ? (
            <div className="actions" role="group" aria-label={t("notebook.retry.checkLabel")}>
              <button type="button" aria-pressed={visit.checks[last.op] === "got"} onClick={() => dispatch({ type: "check", op: last.op, value: "got" })}>
                {t("notebook.retry.got")}
              </button>
              <button type="button" aria-pressed={visit.checks[last.op] === "notyet"} onClick={() => dispatch({ type: "check", op: last.op, value: "notyet" })}>
                {t("notebook.retry.notyet")}
              </button>
            </div>
          ) : null}
          {last.outcome === "incorrect" && last.grade?.knownError ? (
            converted ? (
              <p className="hint" data-converted={converted.id} id={`feed-converted-${item.practice_id}`} tabIndex={-1}>
                {t("feedPractice.convert.done", { id: converted.id })}
              </p>
            ) : (
              <div className="actions">
                <button
                  type="button"
                  className="ghost"
                  onClick={() => {
                    dispatch({ type: "convert", op: last.op, at: new Date().toISOString() });
                    focusSoon(`feed-converted-${item.practice_id}`);
                  }}
                >
                  {t("feedPractice.convert.action")}
                </button>
              </div>
            )
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// The key, shown only once the learner attempted or chose to reveal.
function Reveal({ item, data }: { item: FeedItem; data: ConceptPracticeData }) {
  const { t } = useI18n();
  const r = data.rubric(item.practice_id);
  const excerpts = data.evidence.filter((e) => item.evidence_ids.includes(e.evidence_id));
  return (
    <div className="notebook-reference" role="group" aria-label={t("feedPractice.reveal.region")}>
      {item.kind === "explain" ? (
        <ul className="listening-steps">
          {/* English statements with French examples inside: no single lang. */}
          {r.reference.map((s, i) => (
            <li key={i} className="french">
              {s}
            </li>
          ))}
        </ul>
      ) : (
        <>
          <p>
            <span className="label">{t("feedPractice.reveal.answer")}</span>{" "}
            <span lang="fr" className="french">
              {r.answer}
            </span>
          </p>
          {r.accepted.length > 1 ? (
            <p>
              <span className="label">{t("feedPractice.reveal.accepted")}</span>{" "}
              <span lang="fr" className="french">
                {r.accepted.join(" · ")}
              </span>
            </p>
          ) : null}
        </>
      )}
      {r.explanation ? <p className="hint">{r.explanation}</p> : null}
      {excerpts.length > 0 ? (
        <ul className="listening-steps" aria-label={t("feedPractice.reveal.excerpts")}>
          {excerpts.map((e) => (
            <li key={e.evidence_id}>
              <Excerpt text={e.excerpt} /> <code>{e.evidence_id}</code>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// A learner's words may mix French with Chinese (a question asked in Chinese
// about a French sentence). Chinese runs get lang="zh-CN", the rest lang="fr",
// so a screen reader switches voice and the browser picks the right fonts.
const HAN = /([\p{Script=Han}\u3000-\u303f\uff00-\uffef]+)/u;
export const langRuns = (s: string): { lang: "fr" | "zh-CN"; text: string }[] =>
  s
    .split(HAN)
    .filter((x) => x !== "")
    .map((x) => ({ lang: HAN.test(x) ? "zh-CN" : "fr", text: x }));
const Runs = ({ text }: { text: string }) => (
  <>
    {langRuns(text).map((r, i) =>
      r.lang === "fr" ? (
        <span key={i}>{r.text}</span>
      ) : (
        <span key={i} lang="zh-CN">
          {r.text}
        </span>
      ),
    )}
  </>
);

export function Excerpt({ text }: { text: string }) {
  const p = excerptParts(text);
  return (
    <span lang="fr" className="french feed-excerpt">
      {p ? (
        <>
          <Runs text={p.before} />
          <mark>
            <Runs text={p.quote} />
          </mark>
          <Runs text={p.after} />
        </>
      ) : (
        <Runs text={text} />
      )}
    </span>
  );
}

// The source: the learner's own words the approved knowledge rests on, and
// that knowledge. It is the recall's answer, so it opens after the recall
// (or by an explicit reveal, recorded as one). While closed it holds no
// focusable content. A generated example's key stays withheld until its
// exercises were answered or revealed.
function SourceView({
  data,
  recalled,
  doneWith,
  onRevealRecall,
  accepted,
}: {
  data: ConceptPracticeData;
  recalled: boolean;
  doneWith: (id: string) => boolean;
  onRevealRecall: () => void;
  accepted: VisitState["accepted"];
}) {
  const { t } = useI18n();
  if (!recalled)
    return (
      <div className="banner info" role="note" data-source="locked">
        {t("feedPractice.source.locked")}{" "}
        <button type="button" className="ghost" onClick={onRevealRecall}>
          {t("feedPractice.source.openAnyway")}
        </button>
      </div>
    );
  const keyOpen = (kid: string) => {
    const uses = data.items.filter((i) => i.kind !== "explain" && i.knowledge_ids.includes(kid));
    return uses.length > 0 && uses.every((i) => doneWith(i.practice_id));
  };
  const usedBy = (kid: string) =>
    data.items
      .filter((i) => i.knowledge_ids.includes(kid))
      .map((i) => i.practice_id)
      .sort();
  return (
    <div data-source="open">
      <h4>{t("feedPractice.source.evidence")}</h4>
      <ul className="listening-steps" aria-label={t("feedPractice.source.evidence")}>
        {data.evidence.map((e) => (
          <li key={e.evidence_id} data-evidence={e.evidence_id}>
            <Excerpt text={e.excerpt} />
            <span className="hint">
              {" "}
              {t(fieldKey[e.field] ?? "feedPractice.field.unknown", { field: e.field })} · {t("feedPractice.grounding", { status: e.status, revision: e.source_revision })} ·{" "}
              <code>{e.evidence_id}</code>
            </span>
          </li>
        ))}
      </ul>
      <h4>{t("feedPractice.source.knowledge")}</h4>
      <ul className="listening-items feed-knowledge" aria-label={t("feedPractice.source.knowledge")}>
        {data.knowledge.map((k) => {
          const raw = k.raw;
          const isExample = k.type === "worked_example";
          const open = !isExample || keyOpen(k.id);
          const acc = accepted.find((a) => a.targetId === k.id);
          return (
            <li key={k.id} className="listening-item" data-knowledge={k.id} data-origin={k.origin}>
              <p>
                <span className="tag">{k.type}</span> <span className="tag">{t(originKey[k.origin] ?? "feedPractice.origin.unknown", { origin: k.origin })}</span>{" "}
                <span className="tag">{t("feedPractice.support", { support: k.support })}</span> <code>{k.id}</code>
              </p>
              {isExample ? (
                open ? (
                  <>
                    <p lang="fr" className="french">
                      {String(raw.example ?? "")}
                    </p>
                    {k.text ? <p className="hint">{k.text}</p> : null}
                  </>
                ) : (
                  <>
                    <p lang="fr" className="french">
                      {exampleQuestion(String(raw.example ?? ""))}
                    </p>
                    <p className="hint" data-withheld="key">
                      {t("feedPractice.source.withheld", { ids: usedBy(k.id).join(", ") })}
                    </p>
                  </>
                )
              ) : k.text ? (
                <p className="french">{k.text}</p>
              ) : (
                <KnowledgeFields raw={raw} />
              )}
              {k.accepted_from ? (
                <p className="hint" data-accepted-from={`${k.accepted_from.agent}:${k.accepted_from.proposal_id}`}>
                  {t("feedPractice.source.acceptedFrom", { agent: k.accepted_from.agent, proposal: k.accepted_from.proposal_id, packet: k.accepted_from.packet_id })}
                </p>
              ) : null}
              {acc ? (
                <p className="hint" data-accepted-visit={`${acc.agent}:${acc.proposalId}`}>
                  {t("feedPractice.source.acceptedVisit", { agent: acc.agent, proposal: acc.proposalId })} <span className="french">{acc.text}</span>
                </p>
              ) : null}
              {k.origin === "learner" && k.proposed_text ? (
                <p className="hint">
                  {t("feedPractice.source.proposed")} <span className="french">{k.proposed_text}</span>
                </p>
              ) : null}
              <p className="hint">{k.evidence_ids.length ? t("feedPractice.source.cites", { ids: k.evidence_ids.join(", ") }) : t("feedPractice.source.citesNone")}</p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// A worked example reads "question — answer": before its exercises are
// answered only the question is shown, as the study packet does.
export const exampleQuestion = (example: string) => {
  const i = example.indexOf(" — ");
  return i >= 0 ? `${example.slice(0, i)} — …` : "…";
};

// A contrast or common error carries named fields instead of one text.
function KnowledgeFields({ raw }: { raw: Record<string, unknown> }) {
  const rows: ReactNode[] = [];
  for (const k of ["a", "b", "distinction", "wrong", "right", "why"]) {
    const v = raw[k];
    if (v === undefined || v === null) continue;
    rows.push(
      <li key={k}>
        <code>{k}</code>{" "}
        <span lang="fr" className="french">
          {typeof v === "string" ? v : JSON.stringify(v)}
        </span>
      </li>,
    );
  }
  return <ul className="listening-steps">{rows}</ul>;
}
