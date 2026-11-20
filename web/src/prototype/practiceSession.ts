// One practice visit (PROTOTYPE, private workbench): a pure reducer and its
// selectors over the sealed Extraction 2.1 fixture. Nothing here is stored or
// sent; the store (practiceStore.ts) keeps this state for the life of the page
// and it DISAPPEARS ON RELOAD. Storing it needs the owner's migration
// (docs/plans/PRACTICE-STORAGE-DECISION.md).
//
// Rules this module owns (Workbooks' side of the feed contract):
// - A feed revision arrives; while the learner has an unsent draft or a check
//   in flight for that source it waits ("recoverable transition") until the
//   learner applies it. Applying it moves drafts of withdrawn items aside
//   (kept, never lost) instead of discarding them.
// - A withdrawn practice_id is no longer offered, but every attempt made on it
//   stays in the visit's history. When a later feed lists the same ID again it
//   is offered again as "restored", on the newer revision.
// - A check is answered later than it was asked (a simulated delay). If the
//   item was withdrawn, or its revision changed, in between, the late response
//   is refused and the draft is kept: it can never complete a withdrawn
//   exercise.
// - The same action is applied once: an answer is keyed by its draft version
//   (re-sending an unchanged draft is ignored), a reveal by its item.
// Every refusal and transition carries a reason code (ReasonCode), kept for
// tests and browser evidence (data-reason-code).

import type { FixtureCatalog, RevisionState } from "./practiceFixture";
import { grade, type ConceptPracticeData, type FeedItem, type Grade, type Outcome, type PracticeKind } from "./practiceFeed";

export type ReasonCode =
  | "in_feed"
  | "restored_same_id"
  | "withdrawn_source_revised"
  | "not_in_feed"
  | "late_response_withdrawn"
  | "late_response_revision_changed"
  | "draft_kept_withdrawn"
  | "revision_waiting"
  | "revision_applied"
  | "mistake_converted"
  | "proposal_accepted_for_visit";

export type SelfCheck = "got" | "notyet";
// Where an outcome comes from (shown on every history entry).
export type OutcomeOrigin = "exact_match" | "learner_judgment" | "revealed" | "extraction_record";

export interface VisitAttempt {
  op: string;
  at: string; // ISO time of the response
  sourceId: string;
  revision: number;
  revisionSha: string;
  practiceId: string;
  kind: PracticeKind;
  action: "attempt" | "reveal";
  outcome: Outcome;
  grade?: Grade;
  afterReveal: boolean; // an attempt made after this visit revealed the item
  text: string | null; // the learner's answer: page memory only, never in a packet or a default export
}

export interface PendingCheck {
  op: string;
  askedAt: string;
  sourceId: string;
  practiceId: string;
  revision: number;
  revisionSha: string;
  text: string;
}

export interface KeptDraft {
  sourceId: string;
  practiceId: string;
  text: string;
  code: ReasonCode;
  revision: number;
}

export interface VisitEvent {
  at: string;
  code: ReasonCode;
  sourceId: string;
  practiceId?: string;
  revision?: number;
  detail?: string;
}

// A quote-linked mistake turned into its own practice item (R2-063): it keeps
// the attempt, the exercise and the evidence it rests on.
export interface PersonalItem {
  id: string;
  fromOp: string;
  sourceId: string;
  practiceId: string;
  revision: number;
  evidenceIds: string[];
  knownError: string;
  at: string;
  done: boolean;
}

export interface AcceptedForVisit {
  session: number;
  proposalId: string;
  agent: string;
  targetId: string;
  text: string;
  at: string;
}

export interface VisitState {
  feedIndex: Record<string, number>;
  waiting: Record<string, number>;
  attempts: VisitAttempt[];
  pending: PendingCheck[];
  drafts: Record<string, string>;
  draftVersion: Record<string, number>;
  kept: KeptDraft[];
  checks: Record<string, SelfCheck>;
  events: VisitEvent[];
  personal: PersonalItem[];
  accepted: AcceptedForVisit[];
  resume: { sourceId: string; practiceId: string } | null;
  committedOps: string[];
  duplicatesIgnored: number;
}

export const initialVisit = (): VisitState => ({
  feedIndex: {},
  waiting: {},
  attempts: [],
  pending: [],
  drafts: {},
  draftVersion: {},
  kept: [],
  checks: {},
  events: [],
  personal: [],
  accepted: [],
  resume: null,
  committedOps: [],
  duplicatesIgnored: 0,
});

export type VisitAction =
  | { type: "draft"; sourceId: string; practiceId: string; text: string }
  | { type: "submit"; op: string; at: string; sourceId: string; practiceId: string; text: string }
  | { type: "respond"; op: string; at: string }
  | { type: "reveal"; at: string; sourceId: string; practiceId: string }
  | { type: "check"; op: string; value: SelfCheck }
  | { type: "arrive"; at: string; sourceId: string }
  | { type: "apply"; at: string; sourceId: string }
  | { type: "discardKept"; sourceId: string; practiceId: string }
  | { type: "resume"; sourceId: string; practiceId: string }
  | { type: "resumeClear" }
  | { type: "convert"; op: string; at: string }
  | { type: "personalDone"; id: string }
  | { type: "accept"; at: string; session: number; proposalId: string };

export const draftKey = (sourceId: string, practiceId: string) => `${sourceId}/${practiceId}`;
// The op of a check: one per draft version on one source revision, so an
// unchanged draft sent twice is one action, while the same answer on a newer
// revision is a new one.
export const checkOp = (s: VisitState, sourceId: string, practiceId: string, revisionSha: string) =>
  `${draftKey(sourceId, practiceId)}@${revisionSha.slice(0, 12)}#v${s.draftVersion[draftKey(sourceId, practiceId)] ?? 0}`;
export const revealOp = (sourceId: string, practiceId: string) => `${draftKey(sourceId, practiceId)}#reveal`;

export const timeline = (c: FixtureCatalog, sourceId: string) => {
  const t = c.timelines.find((x) => x.sourceId === sourceId);
  if (!t) throw new Error(`unknown source ${sourceId}`);
  return t;
};
export const currentIndex = (s: VisitState, sourceId: string) => s.feedIndex[sourceId] ?? 0;
export const current = (c: FixtureCatalog, s: VisitState, sourceId: string): RevisionState => timeline(c, sourceId).states[currentIndex(s, sourceId)];
export const nextIndex = (c: FixtureCatalog, s: VisitState, sourceId: string): number | null => {
  const i = (s.waiting[sourceId] ?? currentIndex(s, sourceId)) + 1;
  return i < timeline(c, sourceId).states.length ? i : null;
};

export interface Availability {
  status: "active" | "withdrawn" | "unknown";
  code: ReasonCode;
  revision: number;
  reasonText?: string; // the producer's sentence, verbatim
  restoredFrom?: number; // the revision that had withdrawn it
}

export function availability(c: FixtureCatalog, s: VisitState, sourceId: string, practiceId: string): Availability {
  const t = timeline(c, sourceId);
  const i = currentIndex(s, sourceId);
  const cur = t.states[i];
  const rev = cur.feed.source.revision;
  if (cur.feed.items.some((it) => it.practice_id === practiceId)) {
    for (let j = i - 1; j >= 0; j--) {
      if (t.states[j].feed.items.some((it) => it.practice_id === practiceId)) break;
      if (t.states[j].feed.withdrawn?.some((w) => w.practice_id === practiceId))
        return { status: "active", code: "restored_same_id", revision: rev, restoredFrom: t.states[j].feed.source.revision };
    }
    return { status: "active", code: "in_feed", revision: rev };
  }
  const w = cur.feed.withdrawn?.find((x) => x.practice_id === practiceId);
  if (w) return { status: "withdrawn", code: "withdrawn_source_revised", revision: rev, reasonText: w.reason };
  return { status: "unknown", code: "not_in_feed", revision: rev };
}

// The item as it was last offered (for a withdrawn item: from the latest feed that listed it).
export function lastOffered(c: FixtureCatalog, s: VisitState, sourceId: string, practiceId: string): { item: FeedItem; data: ConceptPracticeData } | null {
  const t = timeline(c, sourceId);
  for (let j = currentIndex(s, sourceId); j >= 0; j--) {
    const d = t.states[j].data;
    const item = d?.items.find((it) => it.practice_id === practiceId);
    if (d && item) return { item, data: d };
  }
  return null;
}

// A draft is unsent while its current version was never recorded as an attempt.
export const unsent = (s: VisitState, key: string) =>
  (s.drafts[key] ?? "").trim() !== "" && !s.committedOps.some((op) => op.startsWith(`${key}@`) && op.endsWith(`#v${s.draftVersion[key] ?? 0}`));
const hasWork = (s: VisitState, sourceId: string) =>
  s.pending.some((p) => p.sourceId === sourceId) || Object.keys(s.drafts).some((k) => k.startsWith(`${sourceId}/`) && unsent(s, k));

function applyIndex(c: FixtureCatalog, s: VisitState, sourceId: string, idx: number, at: string): VisitState {
  const next: VisitState = { ...s, feedIndex: { ...s.feedIndex, [sourceId]: idx }, waiting: { ...s.waiting } };
  delete next.waiting[sourceId];
  const st = timeline(c, sourceId).states[idx];
  const events: VisitEvent[] = [{ at, code: "revision_applied", sourceId, revision: st.feed.source.revision }];
  const drafts = { ...s.drafts };
  const kept = [...s.kept];
  for (const w of st.feed.withdrawn ?? []) {
    const k = draftKey(sourceId, w.practice_id);
    events.push({ at, code: "withdrawn_source_revised", sourceId, practiceId: w.practice_id, revision: st.feed.source.revision, detail: w.reason });
    if (unsent(s, k)) {
      kept.push({ sourceId, practiceId: w.practice_id, text: drafts[k], code: "draft_kept_withdrawn", revision: st.feed.source.revision });
      events.push({ at, code: "draft_kept_withdrawn", sourceId, practiceId: w.practice_id, revision: st.feed.source.revision });
      delete drafts[k];
    }
  }
  for (const it of st.feed.items) {
    const a = availability(c, next, sourceId, it.practice_id);
    if (a.code === "restored_same_id") events.push({ at, code: "restored_same_id", sourceId, practiceId: it.practice_id, revision: a.revision });
  }
  return { ...next, drafts, kept, events: [...s.events, ...events] };
}

export function reduce(c: FixtureCatalog, s: VisitState, a: VisitAction): VisitState {
  switch (a.type) {
    case "draft": {
      const k = draftKey(a.sourceId, a.practiceId);
      if ((s.drafts[k] ?? "") === a.text) return s;
      return { ...s, drafts: { ...s.drafts, [k]: a.text }, draftVersion: { ...s.draftVersion, [k]: (s.draftVersion[k] ?? 0) + 1 } };
    }
    case "submit": {
      const busy = s.pending.some((p) => p.op === a.op || (p.sourceId === a.sourceId && p.practiceId === a.practiceId));
      if (busy || s.committedOps.includes(a.op) || !a.text.trim()) return { ...s, duplicatesIgnored: s.duplicatesIgnored + (a.text.trim() ? 1 : 0) };
      if (availability(c, s, a.sourceId, a.practiceId).status !== "active") return s;
      const cur = current(c, s, a.sourceId);
      return {
        ...s,
        pending: [...s.pending, { op: a.op, askedAt: a.at, sourceId: a.sourceId, practiceId: a.practiceId, revision: cur.feed.source.revision, revisionSha: cur.feed.source.revision_sha256, text: a.text }],
      };
    }
    case "respond": {
      const p = s.pending.find((x) => x.op === a.op);
      if (!p) return { ...s, duplicatesIgnored: s.duplicatesIgnored + 1 };
      const rest = { ...s, pending: s.pending.filter((x) => x.op !== a.op) };
      const av = availability(c, rest, p.sourceId, p.practiceId);
      const cur = current(c, rest, p.sourceId);
      if (av.status !== "active")
        return { ...rest, events: [...rest.events, { at: a.at, code: "late_response_withdrawn", sourceId: p.sourceId, practiceId: p.practiceId, revision: av.revision }] };
      if (cur.feed.source.revision_sha256 !== p.revisionSha)
        return {
          ...rest,
          events: [...rest.events, { at: a.at, code: "late_response_revision_changed", sourceId: p.sourceId, practiceId: p.practiceId, revision: cur.feed.source.revision, detail: `asked on revision ${p.revision}` }],
        };
      const item = cur.data!.items.find((it) => it.practice_id === p.practiceId)!;
      const g = grade(item.kind, item.options, cur.data!.rubric(item.practice_id), p.text);
      const afterReveal = s.attempts.some((x) => x.sourceId === p.sourceId && x.practiceId === p.practiceId && x.action === "reveal");
      return {
        ...rest,
        committedOps: [...rest.committedOps, p.op],
        attempts: [
          ...rest.attempts,
          { op: p.op, at: a.at, sourceId: p.sourceId, revision: p.revision, revisionSha: p.revisionSha, practiceId: p.practiceId, kind: item.kind, action: "attempt", outcome: g.outcome, grade: g, afterReveal, text: p.text },
        ],
      };
    }
    case "reveal": {
      const op = revealOp(a.sourceId, a.practiceId);
      if (s.committedOps.includes(op)) return { ...s, duplicatesIgnored: s.duplicatesIgnored + 1 };
      if (availability(c, s, a.sourceId, a.practiceId).status !== "active") return s;
      const cur = current(c, s, a.sourceId);
      const item = cur.data!.items.find((it) => it.practice_id === a.practiceId)!;
      return {
        ...s,
        committedOps: [...s.committedOps, op],
        attempts: [
          ...s.attempts,
          { op, at: a.at, sourceId: a.sourceId, revision: cur.feed.source.revision, revisionSha: cur.feed.source.revision_sha256, practiceId: a.practiceId, kind: item.kind, action: "reveal", outcome: "revealed", afterReveal: false, text: null },
        ],
      };
    }
    case "check":
      if (!s.attempts.some((x) => x.op === a.op) || s.checks[a.op] === a.value) return s;
      return { ...s, checks: { ...s.checks, [a.op]: a.value } };
    case "arrive": {
      const idx = nextIndex(c, s, a.sourceId);
      if (idx === null) return s;
      if (hasWork(s, a.sourceId))
        return {
          ...s,
          waiting: { ...s.waiting, [a.sourceId]: idx },
          events: [...s.events, { at: a.at, code: "revision_waiting", sourceId: a.sourceId, revision: timeline(c, a.sourceId).states[idx].feed.source.revision }],
        };
      return applyIndex(c, s, a.sourceId, idx, a.at);
    }
    case "apply": {
      const idx = s.waiting[a.sourceId];
      return idx === undefined ? s : applyIndex(c, s, a.sourceId, idx, a.at);
    }
    case "discardKept":
      return { ...s, kept: s.kept.filter((k) => !(k.sourceId === a.sourceId && k.practiceId === a.practiceId)) };
    case "resume":
      return { ...s, resume: { sourceId: a.sourceId, practiceId: a.practiceId } };
    case "resumeClear":
      return s.resume ? { ...s, resume: null } : s;
    case "convert": {
      const at = s.attempts.find((x) => x.op === a.op);
      if (!at || at.outcome !== "incorrect" || !at.grade?.knownError || s.personal.some((p) => p.fromOp === a.op)) return s;
      const off = lastOffered(c, s, at.sourceId, at.practiceId);
      const id = `personal-${s.personal.length + 1}`;
      return {
        ...s,
        personal: [
          ...s.personal,
          { id, fromOp: a.op, sourceId: at.sourceId, practiceId: at.practiceId, revision: at.revision, evidenceIds: off?.item.evidence_ids ?? [], knownError: at.grade.knownError, at: a.at, done: false },
        ],
        events: [...s.events, { at: a.at, code: "mistake_converted", sourceId: at.sourceId, practiceId: at.practiceId, revision: at.revision, detail: id }],
      };
    }
    case "personalDone":
      return { ...s, personal: s.personal.map((p) => (p.id === a.id ? { ...p, done: true } : p)) };
    case "accept": {
      const session = c.sessions.find((x) => x.n === a.session);
      const row = session?.proposals.find((p) => p.proposal.proposal_id === a.proposalId);
      if (!session || !row || row.class !== "accepted_candidate" || row.proposal.type !== "correction") return s;
      if (s.accepted.some((x) => x.session === a.session && x.proposalId === a.proposalId)) return { ...s, duplicatesIgnored: s.duplicatesIgnored + 1 };
      return {
        ...s,
        accepted: [...s.accepted, { session: a.session, proposalId: a.proposalId, agent: session.agent, targetId: row.proposal.target_id!, text: row.proposal.text!, at: a.at }],
        events: [...s.events, { at: a.at, code: "proposal_accepted_for_visit", sourceId: session.packet.source.source_id, detail: `${session.agent} ${a.proposalId}` }],
      };
    }
  }
}

// ---- outcomes, next exercise and today's set ----

export interface Seen {
  practiceId: string;
  outcome: Outcome;
  seq: number;
  fromVisit: boolean;
}

// Every outcome known for a source's items: the feed's record (the extraction
// tool's own attempts, by seq) followed by this visit's, in order.
export function seenOutcomes(c: FixtureCatalog, s: VisitState, sourceId: string): Seen[] {
  const cur = current(c, s, sourceId);
  const fromFeed = cur.feed.items.flatMap((it) => it.outcomes.map((o) => ({ practiceId: it.practice_id, outcome: o.outcome, seq: o.seq, fromVisit: false })));
  const base = fromFeed.reduce((m, o) => Math.max(m, o.seq), 0);
  const visit = s.attempts.filter((x) => x.sourceId === sourceId).map((x, i) => ({ practiceId: x.practiceId, outcome: x.outcome, seq: base + i + 1, fromVisit: true }));
  return [...fromFeed.sort((a, b) => a.seq - b.seq), ...visit];
}

export interface Confusion {
  practiceId: string;
  contrastId: string | null;
  seq: number;
  resolvedLater: boolean;
}

// The latest incorrect attempt and whether a later attempt fixed it
// (packet v2's last_confusion, computed the same way).
export function lastConfusion(data: ConceptPracticeData, seen: Seen[]): Confusion | null {
  const items = new Map(data.items.map((it) => [it.practice_id, it]));
  const misses = seen.filter((o) => o.outcome === "incorrect" && items.has(o.practiceId));
  const last = misses[misses.length - 1];
  if (!last) return null;
  const it = items.get(last.practiceId)!;
  const contrast = it.knowledge_ids.find((k) => data.knowledge.find((x) => x.id === k)?.type === "contrast") ?? null;
  return { practiceId: last.practiceId, contrastId: contrast, seq: last.seq, resolvedLater: seen.some((o) => o.seq > last.seq && o.practiceId === last.practiceId && o.outcome === "correct") };
}

export interface Next {
  item: FeedItem;
  why: "after_miss_other_sentence" | "after_miss_recall_rule" | "after_miss_retry" | "first_not_yet_correct";
  missed?: string;
  contrastMisses: number; // misses so far on the missed item's contrast (feed and visit)
  transfer: boolean; // a repeated confusion (2 or more misses) answered with a new sentence to produce
}

// The next useful exercise from the current Concept: flh_next_exercise_rule_v1
// (the extraction lane's documented hypothesis), applied by Workbooks to the
// outcomes it knows, in the tutor packet's exercise order. It never sets a
// due date or interval.
export function nextExercise(data: ConceptPracticeData, seen: Seen[]): Next | null {
  const correct = new Set(seen.filter((o) => o.outcome === "correct").map((o) => o.practiceId));
  const order = data.exerciseOrder.length ? data.exerciseOrder : data.items.map((i) => i.practice_id);
  const ex = order.map((id) => data.items.find((i) => i.practice_id === id)).filter((x): x is FeedItem => !!x);
  const last = lastConfusion(data, seen);
  if (last && !last.resolvedLater) {
    const missed = data.items.find((i) => i.practice_id === last.practiceId)!;
    const kRank = { produce: 0, choose: 1, explain: 2 } as const;
    const cands = ex
      .filter((x) => last.contrastId && x.knowledge_ids.includes(last.contrastId) && x.kind !== "explain" && x.knowledge_ids[0] !== missed.knowledge_ids[0] && !correct.has(x.practice_id))
      .sort((a, b) => kRank[a.kind] - kRank[b.kind] || (a.practice_id < b.practice_id ? -1 : 1));
    const contrastMisses = seen.filter((o) => o.outcome === "incorrect" && last.contrastId !== null && (data.items.find((i) => i.practice_id === o.practiceId)?.knowledge_ids ?? []).includes(last.contrastId)).length;
    const base = { missed: missed.practice_id, contrastMisses };
    if (cands.length) return { item: cands[0], why: "after_miss_other_sentence", ...base, transfer: contrastMisses >= 2 && cands[0].kind === "produce" && cands[0].new_sentence === true };
    const expl = ex.find((x) => x.kind === "explain" && last.contrastId !== null && x.knowledge_ids.includes(last.contrastId));
    return expl ? { item: expl, why: "after_miss_recall_rule", ...base, transfer: false } : { item: missed, why: "after_miss_retry", ...base, transfer: false };
  }
  const rest = ex.find((x) => !correct.has(x.practice_id));
  return rest ? { item: rest, why: "first_not_yet_correct", contrastMisses: 0, transfer: false } : null;
}

export type PickReason = "personal_correction" | "missed_last_time" | "not_an_option_last_time" | "revealed_last_time" | "self_checked_last_time" | "not_tried_yet";
export interface Pick {
  sourceId: string;
  item: FeedItem;
  concept: string;
  reason: PickReason;
  personalId?: string;
}

// Today's practice at the start of a visit: a small actionable set (at most
// `max`), across concepts. A personal correction first, then by the latest
// known outcome: missed, not an option, revealed, self-checked, never tried.
// Items answered correctly, or self-checked "I had it", in this visit leave
// the set. Correct items are never picked.
export function todaySet(c: FixtureCatalog, s: VisitState, max = 3): Pick[] {
  const rank: Record<PickReason, number> = { personal_correction: 0, missed_last_time: 1, not_an_option_last_time: 2, revealed_last_time: 3, self_checked_last_time: 4, not_tried_yet: 5 };
  const out: Pick[] = [];
  for (const t of c.timelines) {
    const cur = current(c, s, t.sourceId);
    if (!cur.data) continue;
    const seen = seenOutcomes(c, s, t.sourceId);
    for (const it of cur.data.items) {
      const mine = s.attempts.filter((x) => x.sourceId === t.sourceId && x.practiceId === it.practice_id);
      const settled = mine.some((x) => x.outcome === "correct" || s.checks[x.op] === "got");
      const personal = s.personal.find((p) => p.sourceId === t.sourceId && p.practiceId === it.practice_id && !p.done);
      if (settled && !personal) continue;
      const last = [...seen].reverse().find((o) => o.practiceId === it.practice_id)?.outcome ?? null;
      if (last === "correct" && !personal) continue;
      const reason: PickReason = personal
        ? "personal_correction"
        : last === "incorrect"
          ? "missed_last_time"
          : last === "invalid"
            ? "not_an_option_last_time"
            : last === "revealed"
              ? "revealed_last_time"
              : last === "self_check"
                ? "self_checked_last_time"
                : "not_tried_yet";
      out.push({ sourceId: t.sourceId, item: it, concept: cur.data.concept, reason, personalId: personal?.id });
    }
  }
  return out.sort((a, b) => rank[a.reason] - rank[b.reason]).slice(0, max);
}

// ---- summaries, days and export ----

export type Skill = "recall" | "recognition" | "production";
export const skillOf: Record<PracticeKind, Skill> = { explain: "recall", choose: "recognition", produce: "production" };

export interface SkillCounts {
  independent: number; // attempts made without first revealing the item in this visit
  correct: number;
  notYet: number; // incorrect
  selfGot: number;
  selfNotYet: number;
  selfOpen: number; // a self-check outcome not yet marked
  invalid: number;
  afterReveal: number; // attempts after a reveal: not independent
  revealed: number;
}

const emptyCounts = (): SkillCounts => ({ independent: 0, correct: 0, notYet: 0, selfGot: 0, selfNotYet: 0, selfOpen: 0, invalid: 0, afterReveal: 0, revealed: 0 });

export function summarize(attempts: VisitAttempt[], checks: Record<string, SelfCheck>): Record<Skill | "all", SkillCounts> {
  const out = { recall: emptyCounts(), recognition: emptyCounts(), production: emptyCounts(), all: emptyCounts() };
  for (const a of attempts) {
    for (const c of [out[skillOf[a.kind]], out.all]) {
      if (a.action === "reveal") {
        c.revealed++;
        continue;
      }
      if (a.afterReveal) {
        c.afterReveal++;
        continue;
      }
      c.independent++;
      if (a.outcome === "correct") c.correct++;
      else if (a.outcome === "incorrect") c.notYet++;
      else if (a.outcome === "invalid") c.invalid++;
      else if (checks[a.op] === "got") c.selfGot++;
      else if (checks[a.op] === "notyet") c.selfNotYet++;
      else c.selfOpen++;
    }
  }
  return out;
}

export const originOf = (a: VisitAttempt, checks: Record<string, SelfCheck>): OutcomeOrigin =>
  a.action === "reveal" ? "revealed" : a.outcome === "self_check" || checks[a.op] ? "learner_judgment" : "exact_match";

// The learner's local day of an instant, in a named time zone (YYYY-MM-DD).
export function localDay(iso: string, zone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(iso));
  const get = (t: string) => parts.find((p) => p.type === t)!.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function byDay(attempts: VisitAttempt[], zone: string): { day: string; attempts: VisitAttempt[] }[] {
  const m = new Map<string, VisitAttempt[]>();
  for (const a of attempts) {
    const d = localDay(a.at, zone);
    m.set(d, [...(m.get(d) ?? []), a]);
  }
  return [...m.entries()].sort(([a], [b]) => (a < b ? 1 : -1)).map(([day, list]) => ({ day, attempts: list }));
}

// The seven local days (Monday first) of the week that contains `today`.
export function weekDays(today: string): string[] {
  const d = new Date(`${today}T12:00:00Z`);
  const dow = (d.getUTCDay() + 6) % 7;
  return Array.from({ length: 7 }, (_, i) => new Date(d.getTime() + (i - dow) * 86400000).toISOString().slice(0, 10));
}

export const EXPORT_SCHEMA = "flh_wb_practice_visit_export_v0";

// The visit as JSON the learner can keep (copied, never uploaded). Answer
// texts are left out unless the learner explicitly asks for them.
export function exportVisit(c: FixtureCatalog, s: VisitState, opts: { includeAnswers: boolean; zone: string; exportedAt: string }) {
  const feeds = new Map<string, RevisionState>();
  for (const t of c.timelines) for (const st of t.states) feeds.set(`${t.sourceId}@${st.feed.source.revision_sha256}`, st);
  return {
    schema: EXPORT_SCHEMA,
    prototype: true,
    synthetic: true,
    exported_at: opts.exportedAt,
    zone: opts.zone,
    answer_texts_included: opts.includeAnswers,
    fixture: { handoff: c.source.handoff, handoff_sha256sums: c.source.handoff_sha256sums },
    sources: c.timelines.map((t) => {
      const st = current(c, s, t.sourceId);
      return { source_id: t.sourceId, revision: st.feed.source.revision, revision_sha256: st.feed.source.revision_sha256, feed: st.feedName, feed_sha256: st.feedSha };
    }),
    attempts: s.attempts.map((a) => ({
      op: a.op,
      at: a.at,
      local_day: localDay(a.at, opts.zone),
      source_id: a.sourceId,
      revision: a.revision,
      revision_sha256: a.revisionSha,
      feed: feeds.get(`${a.sourceId}@${a.revisionSha}`)?.feedName ?? null,
      practice_id: a.practiceId,
      kind: a.kind,
      action: a.action,
      outcome: a.outcome,
      origin: originOf(a, s.checks),
      after_reveal: a.afterReveal,
      ...(s.checks[a.op] ? { self_check: s.checks[a.op] } : {}),
      ...(opts.includeAnswers && a.text !== null ? { answer_text: a.text } : {}),
    })),
    personal_items: s.personal.map((p) => ({ id: p.id, from_op: p.fromOp, source_id: p.sourceId, practice_id: p.practiceId, revision: p.revision, evidence_ids: p.evidenceIds, done: p.done })),
    accepted_for_visit: s.accepted.map((x) => ({ session: x.session, proposal_id: x.proposalId, agent: x.agent, target_id: x.targetId })),
    events: s.events.map((e) => ({ at: e.at, code: e.code, source_id: e.sourceId, practice_id: e.practiceId ?? null, revision: e.revision ?? null })),
  };
}

// Every exported attempt must resolve to the feed revision it was made on,
// and that feed must list (or have withdrawn) its practice ID.
export function resolveExport(c: FixtureCatalog, x: ReturnType<typeof exportVisit>): string[] {
  const problems: string[] = [];
  for (const a of x.attempts) {
    const st = c.timelines.find((t) => t.sourceId === a.source_id)?.states.find((s) => s.feed.source.revision_sha256 === a.revision_sha256);
    if (!st) problems.push(`${a.op}: no feed for ${a.source_id} at ${a.revision_sha256.slice(0, 12)}`);
    else if (st.feed.source.revision !== a.revision) problems.push(`${a.op}: revision ${a.revision} != ${st.feed.source.revision}`);
    else if (!st.feed.items.some((i) => i.practice_id === a.practice_id) && !st.feed.withdrawn?.some((w) => w.practice_id === a.practice_id))
      problems.push(`${a.op}: ${a.practice_id} is not in ${st.feedName}`);
  }
  return problems;
}
