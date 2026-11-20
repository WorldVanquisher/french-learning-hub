// The sealed Extraction 2.1 fixtures as the prototype reads them (PROTOTYPE,
// private workbench). Every embedded document is re-hashed here before it is
// parsed: a missing document or a checksum that differs from the one recorded
// when the module was generated from the seal stops the prototype with a
// FixtureError (the panel shows it; the browser walkthrough fails on it).
//
// Sources and revisions (y vs en arrives as three feeds, in the order the
// extraction lane wrote them):
//   y-en-demo              r1 -> r2 (all five items withdrawn) -> r2 re-approved
//   savoir-connaitre-demo  r1
// Grading keys come from the tutor packets the generator exported with the
// sealed code at the moment each feed was written (FIXTURE_SOURCE says how).

import { agentReturnOf, type TutorSession } from "./tutorSessions";
import { ContractError, joinConcept, parseFeed, parsePacket, type ConceptPracticeData, type Feed } from "./practiceFeed";
import { sha256Hex } from "./sha256";

export class FixtureError extends Error {}

export interface FixtureDocumentLike {
  name: string;
  origin: "sealed" | "generated";
  path: string | null;
  role: string;
  sha256: string;
  text: string;
}

export interface FixtureSourceLike {
  handoff: string;
  handoff_sha256sums: string;
  snapshot_tar_sha256: string;
  generated_by: string;
  owner: string;
}

// One state of a source as one feed describes it. `data` is null when the feed
// offers nothing (every item withdrawn).
export interface NotOffered {
  item_id: string;
  type: string;
  statement: string | null;
  support: string;
  state: string;
  groundings: { quote: string; status: string; note: string | null }[];
}

export interface RevisionState {
  feedName: string;
  feedSha: string;
  feed: Feed;
  data: ConceptPracticeData | null;
  grading: string | null; // the tutor packet document that holds the keys
  notOffered: NotOffered[]; // items of this revision the feed does not offer, with why (when the fixture has them)
}

export interface SourceTimeline {
  sourceId: string;
  concept: string;
  states: RevisionState[];
}

export interface FixtureCatalog {
  source: FixtureSourceLike;
  documents: { name: string; origin: string; path: string | null; role: string; sha256: string }[];
  timelines: SourceTimeline[];
  sessions: TutorSession[];
  forbiddenInStudy: string[]; // cases.json: strings a study packet must never carry
}

// The documents the prototype needs, and how each source's feeds pair with
// their grading and study packets.
export const TIMELINES: { sourceId: string; states: { feed: string; tutor: string | null; study: string | null; studyMd: string | null; notOffered?: string }[] }[] = [
  {
    sourceId: "y-en-demo",
    states: [
      { feed: "feed-y-en-demo-r1.json", tutor: "tutor-y-en-r1.json", study: "study-y-en-r1.json", studyMd: "study-y-en-r1.md", notOffered: "not-offered-y-en-r1.json" },
      { feed: "feed-y-en-demo-r2.json", tutor: null, study: null, studyMd: null },
      { feed: "feed-y-en-demo-r2-reapproved.json", tutor: "tutor-y-en-r2.json", study: "study-y-en-r2.json", studyMd: "study-y-en-r2.md" },
    ],
  },
  {
    sourceId: "savoir-connaitre-demo",
    states: [{ feed: "feed-savoir-connaitre-demo-r1.json", tutor: "tutor-savoir-connaitre-r1.json", study: "study-savoir-connaitre-r1.json", studyMd: "study-savoir-connaitre-r1.md" }],
  },
];
export const SESSIONS = [
  { n: 1, packet: "session-1-codex-packet.json", markdown: "session-1-codex-packet.md", ret: "session-1-codex-return.json", preview: "session-1-codex-preview.json" },
  { n: 2, packet: "study-y-en-r1.json", markdown: "study-y-en-r1.md", ret: "session-2-claude-code-return.json", preview: "session-2-claude-code-preview.json" },
];
export const REQUIRED = [
  ...new Set([
    ...TIMELINES.flatMap((t) => t.states.flatMap((s) => [s.feed, s.tutor, s.study, s.studyMd, s.notOffered ?? null])),
    ...SESSIONS.flatMap((s) => [s.packet, s.markdown, s.ret, s.preview]),
    "cases.json",
    "MANIFEST.json",
  ]),
].filter((n): n is string => !!n);

// verifyDocuments re-hashes every document and returns their texts by name.
export function verifyDocuments(docs: readonly FixtureDocumentLike[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const d of docs) {
    if (out.has(d.name)) throw new FixtureError(`fixture document ${d.name} appears twice`);
    const got = sha256Hex(d.text);
    if (got !== d.sha256) throw new FixtureError(`fixture checksum mismatch for ${d.name}: recorded ${d.sha256.slice(0, 12)}…, computed ${got.slice(0, 12)}…`);
    out.set(d.name, d.text);
  }
  for (const n of REQUIRED) if (!out.has(n)) throw new FixtureError(`fixture document missing: ${n}`);
  return out;
}

const json = (texts: Map<string, string>, name: string): unknown => {
  try {
    return JSON.parse(texts.get(name)!);
  } catch {
    throw new FixtureError(`fixture document ${name} is not JSON`);
  }
};

function parseNotOffered(x: unknown, feed: Feed): NotOffered[] {
  const d = x as { schema?: string; source?: { revision_sha256?: string }; items?: unknown[] };
  if (d.schema !== "flh_wb_not_offered_v0" || !Array.isArray(d.items)) throw new FixtureError("not-offered document: unknown schema");
  if (d.source?.revision_sha256 !== feed.source.revision_sha256) throw new FixtureError("not-offered document is about another revision than its feed");
  return d.items.map((i) => {
    const o = i as Record<string, unknown>;
    return {
      item_id: String(o.item_id),
      type: String(o.type),
      statement: typeof o.statement === "string" ? o.statement : null,
      support: String(o.support),
      state: String(o.state),
      groundings: (Array.isArray(o.groundings) ? o.groundings : []).map((g) => {
        const r = g as Record<string, unknown>;
        return { quote: String(r.quote), status: String(r.status), note: typeof r.note === "string" ? r.note : null };
      }),
    };
  });
}

export function buildCatalog(source: FixtureSourceLike, docs: readonly FixtureDocumentLike[]): FixtureCatalog {
  const texts = verifyDocuments(docs);
  const sha = new Map(docs.map((d) => [d.name, d.sha256]));
  const timelines = TIMELINES.map((tl): SourceTimeline => {
    const states = tl.states.map((st): RevisionState => {
      const feed = parseFeed(json(texts, st.feed));
      if (feed.source.source_id !== tl.sourceId) throw new FixtureError(`${st.feed} is about ${feed.source.source_id}, not ${tl.sourceId}`);
      const notOffered = st.notOffered ? parseNotOffered(json(texts, st.notOffered), feed) : [];
      if (feed.items.length === 0) return { feedName: st.feed, feedSha: sha.get(st.feed)!, feed, data: null, grading: null, notOffered };
      if (!st.tutor || !st.study || !st.studyMd) throw new FixtureError(`${st.feed} offers items but has no grading or study packet`);
      const data = joinConcept(feed, parsePacket(json(texts, st.tutor)), parsePacket(json(texts, st.study)), texts.get(st.studyMd)!);
      return { feedName: st.feed, feedSha: sha.get(st.feed)!, feed, data, grading: st.tutor, notOffered };
    });
    // Revisions only move forward within one source.
    for (let i = 1; i < states.length; i++)
      if (states[i].feed.source.revision < states[i - 1].feed.source.revision) throw new FixtureError(`${tl.sourceId}: feeds out of revision order`);
    const concept = states.find((s) => s.data)?.data?.concept ?? tl.sourceId;
    return { sourceId: tl.sourceId, concept, states };
  });
  const sessions = SESSIONS.map((s) =>
    agentReturnOf(s.n, parsePacket(json(texts, s.packet)), texts.get(s.markdown)!, json(texts, s.ret), json(texts, s.preview)),
  );
  const cases = json(texts, "cases.json") as { cases?: Record<string, { expect?: { forbidden_strings?: unknown } }> };
  const forb = cases.cases?.["study-packet-without-answers"]?.expect?.forbidden_strings;
  if (!Array.isArray(forb) || !forb.every((x) => typeof x === "string")) throw new FixtureError("cases.json: the study-packet case lists no forbidden strings");
  return {
    source,
    documents: docs.map(({ name, origin, path, role, sha256 }) => ({ name, origin, path, role, sha256 })),
    timelines,
    sessions,
    forbiddenInStudy: forb as string[],
  };
}

export async function loadCatalog(): Promise<FixtureCatalog> {
  const fx = await import("./extractionPracticeFixture");
  try {
    return buildCatalog(fx.FIXTURE_SOURCE, fx.FIXTURE_DOCUMENTS);
  } catch (e) {
    if (e instanceof FixtureError || e instanceof ContractError) throw e;
    throw new FixtureError(String(e));
  }
}
