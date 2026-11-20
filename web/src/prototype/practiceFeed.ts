// Practice feed consumer (PROTOTYPE, private workbench). Reads the extraction
// lane's documented contracts, never trusting their shape:
//   - flh_practice_review_feed_v1: approved practice items and their recorded
//     outcomes, for Review Today (no answer keys, no attempt texts, no schedule);
//     When made against an earlier feed it also lists `withdrawn` items (no
//     longer offered, with the producer's reason) and the `previous` revision;
//   - flh_practice_packet_v1 or v2, tutor mode with rubrics (the learner's
//     explicit choice): the answer keys, approved knowledge and excerpts, used
//     only to reveal and to show the source;
//   - flh_practice_packet_v1 or v2, study mode: what the learner copies for
//     another agent (no answer keys or rubrics). v2 adds last_confusion,
//     next_exercise, continuity and knowledge[].accepted_from.
// Grading mirrors the extraction lane's practice.grade() exactly (fr_norm:
// NFC, apostrophes unified, lower case, punctuation removed, spaces collapsed);
// scripts/validation/extraction_practice/grade_parity.py runs the same cases
// through their Python. Nothing here stores anything.

export const FEED_SCHEMA = "flh_practice_review_feed_v1";
export const PACKET_SCHEMA = "flh_practice_packet_v1";
export const PACKET_SCHEMA_V2 = "flh_practice_packet_v2";
const PACKET_SCHEMAS = [PACKET_SCHEMA, PACKET_SCHEMA_V2];

export type PracticeKind = "explain" | "choose" | "produce";
export type Outcome = "correct" | "incorrect" | "self_check" | "revealed" | "invalid";
const OUTCOMES: Outcome[] = ["correct", "incorrect", "self_check", "revealed", "invalid"];

export interface FeedOutcome {
  seq: number;
  action: "attempt" | "reveal";
  outcome: Outcome;
}

export interface FeedItem {
  practice_id: string;
  kind: PracticeKind;
  measures: string;
  prompt: string;
  options: string[] | null;
  knowledge_ids: string[];
  evidence_ids: string[];
  new_sentence: boolean | null;
  grading: string;
  outcomes: FeedOutcome[];
}

export interface SourceRef {
  source_id: string;
  revision: number;
  revision_sha256: string;
}

// An item the feed no longer offers. `reason` is the producer's own sentence
// (shown verbatim, never translated); Workbooks adds its own reason code.
export interface Withdrawn {
  practice_id: string;
  kind: PracticeKind;
  reason: string;
  reason_code: string | null; // Extraction 2.2: rule_not_approved, awaiting_confirmation, …
  since_revision: number | null;
}

export interface Feed {
  schema: typeof FEED_SCHEMA;
  source: SourceRef & { capture_id: string; proposer: string };
  items: FeedItem[];
  not_included: string[];
  previous: { revision: number; revision_sha256: string } | null;
  withdrawn: Withdrawn[] | null; // null: the feed was made without --previous
}

export interface Knowledge {
  id: string;
  type: string;
  origin: "source" | "learner" | "generated" | string;
  support: string;
  text: string | null; // claims; a contrast or example carries its own fields
  proposed_text: string | null; // the proposal beside a learner correction
  evidence_ids: string[];
  raw: Record<string, unknown>;
  accepted_from: { agent: string; packet_id: string; proposal_id: string } | null; // v2: an accepted agent correction
}

export interface Evidence {
  evidence_id: string;
  field: string;
  quote: string;
  excerpt: string;
  status: string;
  source_revision: string;
}

export interface Rubric {
  grading: string;
  answer: string | null;
  accepted: string[];
  known_errors: string[];
  explanation: string | null;
  reference: string[];
}

// packet v2 "Where we left off" (never an attempt text or an answer).
export interface LastConfusion {
  practice_id: string;
  kind: PracticeKind;
  forms: string[];
  prompt: string;
  resolved_later: boolean;
}
export interface NextExercise {
  id: string;
  kind: PracticeKind;
  prompt: string;
  rule: string;
  why: string;
}
export interface Continuity {
  previous_packet_id: string;
  changed: { id: string; what: string }[];
  new_misses: string[];
}

export interface Packet {
  schema: typeof PACKET_SCHEMA | typeof PACKET_SCHEMA_V2;
  packet_id: string;
  mode: "study" | "tutor";
  concept: string;
  learner_goal: string;
  language_level: string;
  source: SourceRef;
  knowledge: Knowledge[];
  evidence: Evidence[];
  rubrics: Map<string, Rubric>; // tutor packets with rubrics only
  rubrics_included: boolean;
  exercise_ids: string[];
  exercise_prompts: string[];
  known_confusions: string[]; // the "wrong" form of each known confusion
  last_confusion: LastConfusion | null;
  next_exercise: NextExercise | null;
  continuity: Continuity | null;
}

export class ContractError extends Error {}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (o: Obj, k: string, where: string): string => {
  const v = o[k];
  if (typeof v !== "string" || v === "") throw new ContractError(`${where}: ${k} must be a non-empty string`);
  return v;
};
const strs = (o: Obj, k: string, where: string): string[] => {
  const v = o[k];
  if (!Array.isArray(v) || !v.every((x) => typeof x === "string")) throw new ContractError(`${where}: ${k} must be a list of strings`);
  return v as string[];
};
const optStr = (o: Obj, k: string): string | null => (typeof o[k] === "string" ? (o[k] as string) : null);
const source = (o: unknown, where: string): SourceRef => {
  if (!isObj(o)) throw new ContractError(`${where}: source missing`);
  const revision = Number(o.revision);
  if (!Number.isInteger(revision) || revision < 1) throw new ContractError(`${where}: source.revision must be a positive integer`);
  const sha = str(o, "revision_sha256", `${where} source`);
  if (!/^[0-9a-f]{64}$/.test(sha)) throw new ContractError(`${where}: source.revision_sha256 must be 64 hex characters`);
  return { source_id: str(o, "source_id", `${where} source`), revision, revision_sha256: sha };
};

// parseFeed checks a flh_practice_review_feed_v1 document. It refuses another
// schema, an item without its required fields, an unknown kind or outcome,
// and a feed that carries what the contract excludes (answer keys, attempt
// texts, due dates).
export function parseFeed(x: unknown): Feed {
  if (!isObj(x) || x.schema !== FEED_SCHEMA) throw new ContractError(`not a ${FEED_SCHEMA} document`);
  const src = source(x.source, "feed");
  if (!isObj(x.source)) throw new ContractError("feed: source missing");
  // An empty list is valid: every item may have been withdrawn by a revision.
  if (!Array.isArray(x.items)) throw new ContractError("feed: items must be a list");
  const seen = new Set<string>();
  const items = x.items.map((raw, i): FeedItem => {
    const where = `feed item ${i + 1}`;
    if (!isObj(raw)) throw new ContractError(`${where}: not an object`);
    for (const banned of ["answer", "accepted", "hidden", "rubric", "due", "due_at", "interval", "text"])
      if (banned in raw) throw new ContractError(`${where}: carries "${banned}", which the feed must not contain`);
    const id = str(raw, "practice_id", where);
    if (!/^p-[0-9a-f]{12}$/.test(id) || seen.has(id)) throw new ContractError(`${where}: practice_id ${id} is malformed or repeated`);
    seen.add(id);
    const kind = str(raw, "kind", where);
    if (kind !== "explain" && kind !== "choose" && kind !== "produce") throw new ContractError(`${where}: unknown kind ${kind}`);
    const options = raw.options === undefined ? null : strs(raw, "options", where);
    if (kind === "choose" && (!options || options.length < 2)) throw new ContractError(`${where}: a choose item needs options`);
    if (!Array.isArray(raw.outcomes)) throw new ContractError(`${where}: outcomes must be a list`);
    const outcomes = raw.outcomes.map((o, j): FeedOutcome => {
      if (!isObj(o) || typeof o.seq !== "number" || (o.action !== "attempt" && o.action !== "reveal") || !OUTCOMES.includes(o.outcome as Outcome))
        throw new ContractError(`${where} outcome ${j + 1}: needs seq, action (attempt | reveal) and a known outcome`);
      if (o.action === "reveal" && o.outcome !== "revealed") throw new ContractError(`${where} outcome ${j + 1}: a reveal is recorded as revealed`);
      return { seq: o.seq, action: o.action, outcome: o.outcome as Outcome };
    });
    return {
      practice_id: id,
      kind,
      measures: str(raw, "measures", where),
      prompt: str(raw, "prompt", where),
      options,
      knowledge_ids: strs(raw, "knowledge_ids", where),
      evidence_ids: strs(raw, "evidence_ids", where),
      new_sentence: typeof raw.new_sentence === "boolean" ? raw.new_sentence : null,
      grading: str(raw, "grading", where),
      outcomes,
    };
  });
  let previous: Feed["previous"] = null;
  if (x.previous !== undefined) {
    if (!isObj(x.previous)) throw new ContractError("feed: previous must be an object");
    const r = Number(x.previous.revision);
    const sha = str(x.previous, "revision_sha256", "feed previous");
    if (!Number.isInteger(r) || r < 1 || !/^[0-9a-f]{64}$/.test(sha)) throw new ContractError("feed: previous needs a revision and a 64-hex revision_sha256");
    previous = { revision: r, revision_sha256: sha };
  }
  let withdrawn: Withdrawn[] | null = null;
  if (x.withdrawn !== undefined) {
    if (!Array.isArray(x.withdrawn)) throw new ContractError("feed: withdrawn must be a list");
    withdrawn = x.withdrawn.map((w, i): Withdrawn => {
      const where = `feed withdrawn ${i + 1}`;
      if (!isObj(w)) throw new ContractError(`${where}: not an object`);
      const id = str(w, "practice_id", where);
      if (!/^p-[0-9a-f]{12}$/.test(id) || seen.has(id)) throw new ContractError(`${where}: ${id} is malformed, repeated or still offered`);
      seen.add(id);
      const kind = str(w, "kind", where);
      if (kind !== "explain" && kind !== "choose" && kind !== "produce") throw new ContractError(`${where}: unknown kind ${kind}`);
      return {
        practice_id: id,
        kind,
        reason: str(w, "reason", where),
        reason_code: typeof w.reason_code === "string" ? w.reason_code : null,
        since_revision: Number.isInteger(w.since_revision) ? (w.since_revision as number) : null,
      };
    });
  }
  return {
    schema: FEED_SCHEMA,
    source: { ...src, capture_id: str(x.source, "capture_id", "feed source"), proposer: str(x.source, "proposer", "feed source") },
    items,
    not_included: Array.isArray(x.not_included) ? x.not_included.filter((s): s is string => typeof s === "string") : [],
    previous,
    withdrawn,
  };
}

const kindOf = (v: unknown, where: string): PracticeKind => {
  if (v !== "explain" && v !== "choose" && v !== "produce") throw new ContractError(`${where}: unknown kind ${String(v)}`);
  return v;
};

// parsePacket checks a flh_practice_packet_v1 or v2 document (study or tutor).
export function parsePacket(x: unknown): Packet {
  if (!isObj(x) || !PACKET_SCHEMAS.includes(x.schema as string)) throw new ContractError(`not a ${PACKET_SCHEMAS.join(" or ")} document`);
  const mode = str(x, "mode", "packet");
  if (mode !== "study" && mode !== "tutor") throw new ContractError(`packet: unknown mode ${mode}`);
  const list = (k: string) => {
    if (!Array.isArray(x[k])) throw new ContractError(`packet: ${k} must be a list`);
    return (x[k] as unknown[]).map((v, i) => {
      if (!isObj(v)) throw new ContractError(`packet ${k} ${i + 1}: not an object`);
      return v;
    });
  };
  const knowledge = list("knowledge").map(
    (k): Knowledge => ({
      id: str(k, "id", "packet knowledge"),
      type: str(k, "type", "packet knowledge"),
      origin: str(k, "origin", "packet knowledge"),
      support: str(k, "support", "packet knowledge"),
      text: optStr(k, "text"),
      proposed_text: optStr(k, "proposed_text"),
      evidence_ids: Array.isArray(k.evidence_ids) ? strs(k, "evidence_ids", "packet knowledge") : [],
      raw: k,
      accepted_from: isObj(k.accepted_from)
        ? {
            agent: str(k.accepted_from, "agent", "packet accepted_from"),
            packet_id: str(k.accepted_from, "packet_id", "packet accepted_from"),
            proposal_id: str(k.accepted_from, "proposal_id", "packet accepted_from"),
          }
        : null,
    }),
  );
  const evidence = list("evidence").map(
    (e): Evidence => ({
      evidence_id: str(e, "evidence_id", "packet evidence"),
      field: str(e, "field", "packet evidence"),
      quote: str(e, "quote", "packet evidence"),
      excerpt: str(e, "excerpt", "packet evidence"),
      status: str(e, "status", "packet evidence"),
      source_revision: String(e.source_revision ?? ""),
    }),
  );
  const rubrics = new Map<string, Rubric>();
  const exercises = list("next_exercises");
  for (const ex of exercises) {
    const r = ex.rubric;
    if (!isObj(r)) continue;
    if (mode === "study") throw new ContractError("packet: a study packet must not carry rubrics");
    rubrics.set(str(ex, "id", "packet exercise"), {
      grading: str(r, "grading", "packet rubric"),
      answer: optStr(r, "answer"),
      accepted: Array.isArray(r.accepted) ? strs(r, "accepted", "packet rubric") : [],
      known_errors: Array.isArray(r.known_errors) ? strs(r, "known_errors", "packet rubric") : [],
      explanation: optStr(r, "explanation"),
      reference: Array.isArray(r.reference) ? strs(r, "reference", "packet rubric") : [],
    });
  }
  const v2 = x.schema === PACKET_SCHEMA_V2;
  const lc = v2 && isObj(x.last_confusion) ? x.last_confusion : null;
  const nx = v2 && isObj(x.next_exercise) ? x.next_exercise : null;
  const ct = v2 && isObj(x.continuity) ? x.continuity : null;
  return {
    schema: v2 ? PACKET_SCHEMA_V2 : PACKET_SCHEMA,
    packet_id: str(x, "packet_id", "packet"),
    mode,
    concept: str(x, "concept", "packet"),
    learner_goal: optStr(x, "learner_goal") ?? "",
    language_level: optStr(x, "language_level") ?? "",
    source: source(x.source, "packet"),
    knowledge,
    evidence,
    rubrics,
    rubrics_included: x.rubrics_included === true,
    exercise_ids: exercises.map((e) => String(e.id)),
    exercise_prompts: exercises.map((e) => (typeof e.prompt === "string" ? e.prompt : "")),
    known_confusions: (Array.isArray(x.known_confusions) ? x.known_confusions : []).filter(isObj).map((c) => (typeof c.wrong === "string" ? c.wrong : "")).filter(Boolean),
    last_confusion: lc
      ? {
          practice_id: str(lc, "practice_id", "packet last_confusion"),
          kind: kindOf(lc.kind, "packet last_confusion"),
          forms: strs(lc, "forms", "packet last_confusion"),
          prompt: str(lc, "prompt", "packet last_confusion"),
          resolved_later: lc.resolved_later === true,
        }
      : null,
    next_exercise: nx
      ? {
          id: str(nx, "id", "packet next_exercise"),
          kind: kindOf(nx.kind, "packet next_exercise"),
          prompt: str(nx, "prompt", "packet next_exercise"),
          rule: str(nx, "rule", "packet next_exercise"),
          why: str(nx, "why", "packet next_exercise"),
        }
      : null,
    continuity: ct
      ? {
          previous_packet_id: str(ct, "previous_packet_id", "packet continuity"),
          changed: (Array.isArray(ct.changed) ? ct.changed : []).filter(isObj).map((c) => ({ id: str(c, "id", "packet continuity"), what: str(c, "what", "packet continuity") })),
          new_misses: (Array.isArray(ct.new_misses) ? ct.new_misses : []).filter(isObj).map((m) => String(m.practice_id)),
        }
      : null,
  };
}

// An approved concept as the workbench shows it: the feed's items joined with
// the tutor packet's keys and source, and the study packet to copy.
export interface ConceptPracticeData {
  concept: string;
  goal: string;
  level: string;
  source: Feed["source"];
  items: FeedItem[]; // in practice order: explain, produce, choose
  rubric: (practiceId: string) => Rubric;
  knowledge: Knowledge[];
  evidence: Evidence[];
  studyPacket: { id: string; markdown: string; packet: Packet };
  tutorId: string;
  exerciseOrder: string[]; // the tutor packet's exercise order (used by the next-exercise rule)
}

const sameSource = (a: SourceRef, b: SourceRef) => a.source_id === b.source_id && a.revision === b.revision && a.revision_sha256 === b.revision_sha256;

// joinConcept refuses inputs from different source revisions (a stale packet
// beside a newer feed), a feed item the tutor packet has no key for, and an
// evidence or knowledge ID the packet does not carry.
export function joinConcept(feed: Feed, tutor: Packet, study: Packet, studyMarkdown: string): ConceptPracticeData {
  if (tutor.mode !== "tutor" || !tutor.rubrics_included) throw new ContractError("the answer keys come from a tutor packet exported with rubrics");
  if (study.mode !== "study" || study.rubrics_included || study.rubrics.size > 0) throw new ContractError("the packet to copy must be a study packet without keys");
  if (!sameSource(feed.source, tutor.source) || !sameSource(feed.source, study.source))
    throw new ContractError("the feed and the packets come from different source revisions; rebuild them together");
  const ev = new Set(tutor.evidence.map((e) => e.evidence_id));
  const kn = new Set(tutor.knowledge.map((k) => k.id));
  for (const it of feed.items) {
    if (!tutor.rubrics.has(it.practice_id)) throw new ContractError(`no answer key for ${it.practice_id} in the tutor packet`);
    const lostE = it.evidence_ids.filter((e) => !ev.has(e));
    const lostK = it.knowledge_ids.filter((k) => !kn.has(k));
    if (lostE.length || lostK.length) throw new ContractError(`${it.practice_id} cites ${[...lostE, ...lostK].join(", ")}, which the packet does not carry`);
  }
  if (!studyMarkdown.includes(study.packet_id)) throw new ContractError("the study packet text does not name its packet ID");
  const order: Record<PracticeKind, number> = { explain: 0, produce: 1, choose: 2 };
  return {
    concept: tutor.concept,
    goal: tutor.learner_goal,
    level: tutor.language_level,
    source: feed.source,
    items: [...feed.items].sort((a, b) => order[a.kind] - order[b.kind] || a.practice_id.localeCompare(b.practice_id)),
    rubric: (id) => tutor.rubrics.get(id)!,
    knowledge: tutor.knowledge,
    evidence: tutor.evidence,
    studyPacket: { id: study.packet_id, markdown: studyMarkdown, packet: study },
    tutorId: tutor.packet_id,
    exerciseOrder: tutor.exercise_ids,
  };
}

// The latest recorded outcome of an item (the feed's own record).
export const latestOutcome = (it: FeedItem): Outcome | null =>
  it.outcomes.length ? [...it.outcomes].sort((a, b) => b.seq - a.seq)[0].outcome : null;

// Counts of latest outcomes, for the Review Today row.
export function outcomeCounts(items: FeedItem[]): Record<Outcome | "none", number> {
  const out: Record<Outcome | "none", number> = { correct: 0, incorrect: 0, self_check: 0, revealed: 0, invalid: 0, none: 0 };
  for (const it of items) out[latestOutcome(it) ?? "none"]++;
  return out;
}

// ---- grading: the extraction lane's practice.grade(), mirrored ----

const APOS: Record<string, string> = { "’": "'", "‘": "'", "ʼ": "'" };
export const fold = (s: string) => (s ?? "").normalize("NFC").replace(/[’‘ʼ]/g, (c) => APOS[c]);
export const frNorm = (s: string) =>
  fold(s)
    .toLowerCase()
    .replace(/[.,!?;:«»"()…]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");

export interface Grade {
  outcome: Exclude<Outcome, "revealed">;
  matched?: string; // the accepted variant it equals
  knownError?: string; // the listed error it contains
  chosen?: string; // the option chosen
}

// grade: explain is always a self-check; choose is exact among the options
// (anything else is invalid); produce is correct for an accepted variant,
// incorrect when it contains a listed error, and otherwise a self-check,
// because it may still be correct French.
export function grade(kind: PracticeKind, options: string[] | null, r: Rubric, text: string): Grade {
  const t = frNorm(text);
  if (kind === "explain") return { outcome: "self_check" };
  if (kind === "choose") {
    const opt = (options ?? []).find((o) => frNorm(o) === t);
    if (opt === undefined) return { outcome: "invalid" };
    return { outcome: opt === r.answer ? "correct" : "incorrect", chosen: opt };
  }
  const ok = r.accepted.find((v) => frNorm(v) === t);
  if (ok !== undefined) return { outcome: "correct", matched: ok };
  const bad = r.known_errors.find((w) => frNorm(w) !== "" && ` ${t} `.includes(` ${frNorm(w)} `));
  if (bad !== undefined) return { outcome: "incorrect", knownError: bad };
  return { outcome: "self_check" };
}

// The bracketed quote inside an excerpt ("… « [Oui, j'en vais.] » …"), split
// so the page can mark it without parsing anything else.
export function excerptParts(excerpt: string): { before: string; quote: string; after: string } | null {
  const i = excerpt.indexOf("[");
  const j = excerpt.indexOf("]", i + 1);
  if (i < 0 || j < 0) return null;
  return { before: excerpt.slice(0, i), quote: excerpt.slice(i + 1, j), after: excerpt.slice(j + 1) };
}
