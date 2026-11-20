// The practice visit model over the sealed Extraction 2.1 fixtures: checksum
// verification, the revision timeline (withdrawn, restored), late responses,
// recoverable transitions, idempotent actions, the next-exercise rule (parity
// with the tutor packets the sealed code exported), the agent-return review
// (parity with the sealed previews), summaries by skill and day, and export.
import { describe, expect, it } from "vitest";
import { classify, parsePreview, parseReturn } from "./agentReturn";
import { FIXTURE_DOCUMENTS, FIXTURE_SOURCE } from "./extractionPracticeFixture";
import { parsePacket } from "./practiceFeed";
import { buildCatalog, FixtureError, verifyDocuments, type FixtureCatalog } from "./practiceFixture";
import {
  availability,
  byDay,
  checkOp,
  current,
  exportVisit,
  initialVisit,
  lastConfusion,
  localDay,
  nextExercise,
  reduce,
  resolveExport,
  seenOutcomes,
  summarize,
  todaySet,
  weekDays,
  type VisitAction,
  type VisitState,
} from "./practiceSession";
import { sha256Hex } from "./sha256";
import { langRuns, scrollOpts } from "./ConceptPractice";

const catalog = buildCatalog(FIXTURE_SOURCE, FIXTURE_DOCUMENTS);
const doc = (name: string) => JSON.parse(FIXTURE_DOCUMENTS.find((d) => d.name === name)!.text) as unknown;
const Y = "y-en-demo";
const S = "savoir-connaitre-demo";
let clock = 0;
const at = () => new Date(Date.UTC(2026, 10, 19, 9, 0, clock++)).toISOString();
const run = (c: FixtureCatalog, s: VisitState, ...actions: VisitAction[]) => actions.reduce((x, a) => reduce(c, x, a), s);
// type a draft and send it (the op is the draft's version)
const answer = (s: VisitState, src: string, pid: string, text: string, respond = true) => {
  let x = reduce(catalog, s, { type: "draft", sourceId: src, practiceId: pid, text });
  const op = checkOp(x, src, pid, current(catalog, x, src).feed.source.revision_sha256);
  x = reduce(catalog, x, { type: "submit", op, at: at(), sourceId: src, practiceId: pid, text });
  return { s: respond ? reduce(catalog, x, { type: "respond", op, at: at() }) : x, op };
};

describe("sealed fixture verification", () => {
  it("hashes like sha256sum", () => {
    expect(sha256Hex("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect(sha256Hex("« Oui, j’en reviens. »\n")).toHaveLength(64);
  });

  it("verifies all 21 documents and names their provenance", () => {
    expect(verifyDocuments(FIXTURE_DOCUMENTS).size).toBe(21);
    expect(FIXTURE_SOURCE.handoff_sha256sums).toBe("bad6f86e991179f1a0c911e0c4fb3ec1892dabe743da455712e0ded30cae2bc4");
    expect(FIXTURE_SOURCE.snapshot_tar_sha256).toBe("857040c5e8b843db8aa69937769dfde947356b2d327a2c58d1aed5f2b9a9a8ae");
    const feeds = FIXTURE_DOCUMENTS.filter((d) => d.name.startsWith("feed-"));
    expect(feeds.map((d) => [d.name, d.origin, d.sha256.slice(0, 12)])).toEqual([
      ["feed-y-en-demo-r1.json", "sealed", "8705823c8cb8"],
      ["feed-y-en-demo-r2.json", "sealed", "095dc9da0116"],
      ["feed-y-en-demo-r2-reapproved.json", "sealed", "dae0effe4ede"],
      ["feed-savoir-connaitre-demo-r1.json", "sealed", "efdb92e6cc56"],
    ]);
    expect(FIXTURE_DOCUMENTS.filter((d) => d.name.startsWith("tutor-")).every((d) => d.origin === "generated")).toBe(true);
  });

  it("refuses an altered text, a wrong recorded checksum and a missing document", () => {
    const altered = FIXTURE_DOCUMENTS.map((d) => (d.name === "feed-y-en-demo-r2.json" ? { ...d, text: d.text.replace("withdrawn", "withdrawm") } : d));
    expect(() => verifyDocuments(altered)).toThrow(/checksum mismatch for feed-y-en-demo-r2.json/);
    const wrongSum = FIXTURE_DOCUMENTS.map((d) => (d.name === "tutor-y-en-r1.json" ? { ...d, sha256: "0".repeat(64) } : d));
    expect(() => verifyDocuments(wrongSum)).toThrow(FixtureError);
    expect(() => verifyDocuments(FIXTURE_DOCUMENTS.filter((d) => d.name !== "cases.json"))).toThrow(/missing: cases.json/);
    expect(() => buildCatalog(FIXTURE_SOURCE, altered)).toThrow(FixtureError);
  });

  it("matches the sealed MANIFEST and the changed-source case", () => {
    const m = doc("MANIFEST.json") as { feeds: { file: string; practice_ids: Record<string, string>; withdrawn: string[]; revision: number }[] };
    for (const t of catalog.timelines)
      for (const st of t.states) {
        const e = m.feeds.find((f) => f.file === st.feedName)!;
        expect(Object.fromEntries(st.feed.items.map((i) => [i.practice_id, i.kind]))).toEqual(e.practice_ids);
        expect((st.feed.withdrawn ?? []).map((w) => w.practice_id)).toEqual(e.withdrawn);
        expect(st.feed.source.revision).toBe(e.revision);
      }
    const y = catalog.timelines.find((t) => t.sourceId === Y)!;
    expect(y.states.map((s) => [s.feed.source.revision, s.feed.items.length, s.feed.withdrawn?.length ?? null])).toEqual([
      [1, 5, null],
      [2, 0, 5],
      [2, 5, 0],
    ]);
    expect(y.states[2].feed.items.map((i) => i.practice_id).sort()).toEqual(y.states[0].feed.items.map((i) => i.practice_id).sort());
    expect(y.states[1].data).toBeNull();
    expect(catalog.timelines.map((t) => t.concept)).toEqual(["y vs en", "connaître vs savoir"]);
  });
});

describe("next exercise and last confusion: parity with the sealed tutor packets", () => {
  it.each([
    [Y, 0, "tutor-y-en-r1.json"],
    [Y, 2, "tutor-y-en-r2.json"],
    [S, 0, "tutor-savoir-connaitre-r1.json"],
  ])("%s state %i picks what %s says", (src, idx, tutor) => {
    const p = parsePacket(doc(tutor));
    const s = { ...initialVisit(), feedIndex: { [src]: idx } };
    const data = current(catalog, s, src).data!;
    const seen = seenOutcomes(catalog, s, src);
    expect(lastConfusion(data, seen)?.practiceId ?? null).toBe(p.last_confusion?.practice_id ?? null);
    expect(nextExercise(data, seen)?.item.practice_id).toBe(p.next_exercise!.id);
  });

  it("moves to the same contrast in another sentence after a new miss, and to the first unanswered item when nothing is missed", () => {
    const s0 = initialVisit();
    const data = current(catalog, s0, Y).data!;
    // the feed already has an unresolved miss on p-664f…: a correct answer resolves it
    const { s } = answer(s0, Y, "p-664f7533a19d", "Oui, j'en reviens.");
    expect(lastConfusion(data, seenOutcomes(catalog, s, Y))!.resolvedLater).toBe(true);
    expect(nextExercise(data, seenOutcomes(catalog, s, Y))!.why).toBe("first_not_yet_correct");
    // a new miss on p-8d5c… (production): the other sentence of the contrast that is not yet correct
    const { s: s2 } = answer(s, Y, "p-8d5cabf2ab59", "Oui, nous en allons.");
    const n = nextExercise(data, seenOutcomes(catalog, s2, Y))!;
    expect([n.missed, n.why]).toEqual(["p-8d5cabf2ab59", "after_miss_other_sentence"]);
    expect(n.item.practice_id).toBe("p-0e74504cf958");
  });
});

describe("transfer after a repeated confusion (R2-025)", () => {
  it("offers a new sentence to produce once the same contrast was missed twice", () => {
    const s0 = initialVisit();
    const data = current(catalog, s0, S).data!;
    const once = nextExercise(data, seenOutcomes(catalog, s0, S))!;
    expect([once.item.practice_id, once.contrastMisses, once.transfer]).toEqual(["p-3ac3b47e483a", 1, false]);
    const { s } = answer(s0, S, "p-e61b319d2129", "Oui, je connais nager.");
    const twice = nextExercise(data, seenOutcomes(catalog, s, S))!;
    expect([twice.item.practice_id, twice.why, twice.contrastMisses, twice.transfer, twice.item.new_sentence]).toEqual([
      "p-3ac3b47e483a",
      "after_miss_other_sentence",
      2,
      true,
      true,
    ]);
    // y vs en: the other sentence is already correct in the feed, so the rule falls back to recall (no transfer)
    const y = answer(initialVisit(), Y, "p-664f7533a19d", "Oui, j'y reviens.").s;
    const ny = nextExercise(current(catalog, y, Y).data!, seenOutcomes(catalog, y, Y))!;
    expect([ny.item.practice_id, ny.contrastMisses, ny.transfer]).toEqual(["p-2ea892e5eaa0", 2, false]);
  });
});

describe("agent returns: parity with the sealed previews", () => {
  it.each([
    ["session-1-codex-packet.json", "session-1-codex-return.json", "session-1-codex-preview.json", ["c1:accepted_candidate", "c2:duplicate", "c3:accepted_candidate"]],
    ["study-y-en-r1.json", "session-2-claude-code-return.json", "session-2-claude-code-preview.json", ["q1:conflict", "q2:accepted_candidate", "q3:duplicate", "q4:unknown_reference"]],
  ])("%s + %s", (packet, ret, preview, want) => {
    const p = parsePacket(doc(packet));
    const mine = classify(p, parseReturn(doc(ret)));
    const sealed = parsePreview(doc(preview));
    expect(mine.map((r) => `${r.proposal_id}:${r.class}`)).toEqual(want);
    expect(sealed.rows.map((r) => `${r.proposal_id}:${r.class}`)).toEqual(want);
    for (const r of sealed.rows) if (r.why) expect(mine.find((m) => m.proposal_id === r.proposal_id)!.why).toBe(r.why);
  });

  it("marks an unknown concept or target as an unknown reference (R2-036)", () => {
    const p = parsePacket(doc("study-y-en-r1.json"));
    const ret = parseReturn({
      schema: "flh_agent_proposals_v1",
      packet_id: p.packet_id,
      agent: "synthetic",
      proposals: [
        { proposal_id: "u1", type: "correction", target_id: "k-000000000000", text: "x", rationale: "r", evidence_ids: [] },
        { proposal_id: "u2", type: "exercise", knowledge_ids: ["k-111111111111"], kind: "produce", prompt: "p ?", accepted: ["a"], rationale: "r", evidence_ids: ["ev-fd704f2740"] },
        { proposal_id: "u3", type: "correction", target_id: "k-40cbe73ae3f5", text: "« en » replaces a place introduced by « de »: « Je viens de la boulangerie, j'en viens. »", rationale: "r", evidence_ids: [] },
      ],
    });
    expect(classify(p, ret).map((r) => `${r.proposal_id}:${r.class}:${r.why}`)).toEqual([
      "u1:unknown_reference:unknown target k-000000000000",
      "u2:unknown_reference:unknown knowledge k-111111111111",
      "u3:duplicate:same wording as the current k-40cbe73ae3f5",
    ]);
  });

  it("refuses a preview that disagrees with the documented rules", () => {
    const pv = JSON.parse(JSON.stringify(doc("session-2-claude-code-preview.json"))) as { rows: { class: string }[] };
    pv.rows[0].class = "accepted_candidate";
    const docs = FIXTURE_DOCUMENTS.map((d) => (d.name === "session-2-claude-code-preview.json" ? { ...d, text: JSON.stringify(pv), sha256: sha256Hex(JSON.stringify(pv)) } : d));
    expect(() => buildCatalog(FIXTURE_SOURCE, docs)).toThrow(/q1: the preview says accepted_candidate, the documented rules give conflict/);
  });
});

describe("a visit across a source revision", () => {
  it("withdraws items from active practice but keeps their history, then restores the same IDs on the newer revision", () => {
    let { s } = answer(initialVisit(), Y, "p-664f7533a19d", "Oui, j'y reviens.");
    expect(s.attempts).toHaveLength(1);
    s = reduce(catalog, s, { type: "draft", sourceId: Y, practiceId: "p-664f7533a19d", text: "" });
    s = run(catalog, s, { type: "arrive", at: at(), sourceId: Y });
    expect(current(catalog, s, Y).feed.source.revision).toBe(2);
    const a = availability(catalog, s, Y, "p-664f7533a19d");
    expect([a.status, a.code, a.revision]).toEqual(["withdrawn", "withdrawn_source_revised", 2]);
    expect(a.reasonText).toMatch(/needs the learner's review/);
    expect(s.attempts).toHaveLength(1); // history kept
    expect(todaySet(catalog, s).every((p) => p.sourceId !== Y)).toBe(true);
    // a withdrawn item cannot be answered or revealed
    const blocked = answer(s, Y, "p-664f7533a19d", "Oui, j'en reviens.").s;
    expect(blocked.attempts).toHaveLength(1);
    expect(run(catalog, s, { type: "reveal", at: at(), sourceId: Y, practiceId: "p-2ea892e5eaa0" }).attempts).toHaveLength(1);
    s = run(catalog, s, { type: "arrive", at: at(), sourceId: Y });
    const b = availability(catalog, s, Y, "p-664f7533a19d");
    expect([b.status, b.code, b.revision, b.restoredFrom]).toEqual(["active", "restored_same_id", 2, 2]);
    expect(s.events.filter((e) => e.code === "restored_same_id")).toHaveLength(5);
    const after = answer(s, Y, "p-664f7533a19d", "Oui, j'en reviens.").s;
    expect(after.attempts.map((x) => `${x.revision}:${x.outcome}`)).toEqual(["1:incorrect", "2:correct"]);
  });

  it("refuses a late response for a withdrawn exercise and keeps the draft (recoverable transition)", () => {
    let { s, op } = answer(initialVisit(), Y, "p-8d5cabf2ab59", "Oui, on y va !", false);
    s = run(catalog, s, { type: "arrive", at: at(), sourceId: Y });
    // a draft and a check in flight: the revision waits for the learner
    expect(current(catalog, s, Y).feed.source.revision).toBe(1);
    expect(s.waiting[Y]).toBe(1);
    expect(s.events.at(-1)!.code).toBe("revision_waiting");
    s = run(catalog, s, { type: "apply", at: at(), sourceId: Y });
    expect(s.kept.map((k) => [k.practiceId, k.text, k.code])).toEqual([["p-8d5cabf2ab59", "Oui, on y va !", "draft_kept_withdrawn"]]);
    s = run(catalog, s, { type: "respond", op, at: at() });
    expect(s.attempts).toHaveLength(0);
    expect(s.events.at(-1)).toMatchObject({ code: "late_response_withdrawn", practiceId: "p-8d5cabf2ab59" });
    // the same response again changes nothing
    const again = run(catalog, s, { type: "respond", op, at: at() });
    expect(again.attempts).toHaveLength(0);
    expect(again.duplicatesIgnored).toBe(s.duplicatesIgnored + 1);
  });

  it("refuses a late response when the revision changed under it, and the learner can send again", () => {
    let s: VisitState = { ...initialVisit(), feedIndex: { [Y]: 1 } };
    s = run(catalog, s, { type: "arrive", at: at(), sourceId: Y }); // r2 re-approved
    const first = answer(s, Y, "p-22a947cd7f5c", "y", false);
    // simulate: the check was asked on another revision
    s = { ...first.s, pending: first.s.pending.map((p) => ({ ...p, revisionSha: "0".repeat(64), revision: 1 })) };
    s = run(catalog, s, { type: "respond", op: first.op, at: at() });
    expect(s.attempts).toHaveLength(0);
    expect(s.events.at(-1)!.code).toBe("late_response_revision_changed");
    expect(s.drafts[`${Y}/p-22a947cd7f5c`]).toBe("y");
    s = run(catalog, s, { type: "submit", op: first.op, at: at(), sourceId: Y, practiceId: "p-22a947cd7f5c", text: "y" }, { type: "respond", op: first.op, at: at() });
    expect(s.attempts.map((x) => x.outcome)).toEqual(["correct"]);
  });

  it("applies the same action once: an unchanged draft, a double response, a second reveal", () => {
    const one = answer(initialVisit(), S, "p-3ca128617083", "connais");
    let s = run(
      catalog,
      one.s,
      { type: "submit", op: one.op, at: at(), sourceId: S, practiceId: "p-3ca128617083", text: "connais" },
      { type: "respond", op: one.op, at: at() },
      { type: "reveal", at: at(), sourceId: S, practiceId: "p-8d55e5e7255d" },
      { type: "reveal", at: at(), sourceId: S, practiceId: "p-8d55e5e7255d" },
    );
    expect(s.attempts.map((x) => `${x.practiceId}:${x.action}`)).toEqual(["p-3ca128617083:attempt", "p-8d55e5e7255d:reveal"]);
    expect(s.duplicatesIgnored).toBe(3);
    // a changed draft is a new attempt
    s = answer(s, S, "p-3ca128617083", "sais").s;
    expect(s.attempts).toHaveLength(3);
    // two sends while the first is in flight: one pending check
    const p = answer(s, S, "p-baa71166205b", "sais", false);
    const p2 = run(catalog, p.s, { type: "submit", op: "other", at: at(), sourceId: S, practiceId: "p-baa71166205b", text: "sais" });
    expect(p2.pending).toHaveLength(1);
  });
});

describe("the daily loop", () => {
  it("starts with a small actionable set: personal corrections, then misses, never correct items", () => {
    const s0 = initialVisit();
    expect(todaySet(catalog, s0).map((p) => `${p.item.practice_id}:${p.reason}`)).toEqual([
      "p-664f7533a19d:missed_last_time",
      "p-e61b319d2129:missed_last_time",
      "p-baa71166205b:not_an_option_last_time",
    ]);
    const { s } = answer(s0, Y, "p-664f7533a19d", "Oui, j'en reviens.");
    expect(todaySet(catalog, s).map((p) => p.item.practice_id)).not.toContain("p-664f7533a19d");
    // a quote-linked mistake becomes its own practice item, first in the set
    const miss = answer(s, S, "p-3ca128617083", "sais");
    expect(miss.s.attempts.at(-1)!.outcome).toBe("incorrect");
    const m2 = answer(miss.s, Y, "p-8d5cabf2ab59", "Oui, nous en allons.");
    const conv = run(catalog, m2.s, { type: "convert", op: m2.op, at: at() }, { type: "convert", op: m2.op, at: at() });
    expect(conv.personal).toHaveLength(1);
    expect(conv.personal[0]).toMatchObject({ practiceId: "p-8d5cabf2ab59", knownError: "Oui, nous en allons.", evidenceIds: ["ev-17c9dfcc08", "ev-fd704f2740"] });
    expect(todaySet(catalog, conv)[0]).toMatchObject({ reason: "personal_correction", personalId: "personal-1" });
    expect(conv.events.at(-1)!.code).toBe("mistake_converted");
  });

  it("counts independent answers, answers after a reveal and reveals apart, by skill", () => {
    let s = run(catalog, initialVisit(), { type: "reveal", at: at(), sourceId: Y, practiceId: "p-0e74504cf958" });
    s = answer(s, Y, "p-0e74504cf958", "en").s; // after the reveal: not independent
    s = answer(s, Y, "p-22a947cd7f5c", "y").s;
    const ex = answer(s, Y, "p-2ea892e5eaa0", "y après à, en après de");
    s = run(catalog, ex.s, { type: "check", op: ex.op, value: "got" });
    s = answer(s, Y, "p-8d5cabf2ab59", "Oui, ce soir nous y allons avec Paul.").s; // self-check, unmarked
    const sum = summarize(s.attempts, s.checks);
    expect(sum.recognition).toMatchObject({ independent: 1, correct: 1, afterReveal: 1, revealed: 1 });
    expect(sum.recall).toMatchObject({ independent: 1, selfGot: 1 });
    expect(sum.production).toMatchObject({ independent: 1, selfOpen: 1 });
    expect(sum.all).toMatchObject({ independent: 3, afterReveal: 1, revealed: 1 });
  });

  it("groups by the learner's local day across midnight, and lays out the week", () => {
    const mk = (iso: string) => ({ ...answer(initialVisit(), Y, "p-22a947cd7f5c", "y").s.attempts[0], at: iso });
    const xs = [mk("2026-11-19T22:59:30Z"), mk("2026-11-19T23:00:30Z")]; // 23:59:30 and 00:00:30 in Paris
    expect(byDay(xs, "Europe/Paris").map((d) => [d.day, d.attempts.length])).toEqual([
      ["2026-11-20", 1],
      ["2026-11-19", 1],
    ]);
    expect(byDay(xs, "UTC").map((d) => [d.day, d.attempts.length])).toEqual([["2026-11-19", 2]]);
    expect(localDay("2026-11-19T16:30:00Z", "Asia/Shanghai")).toBe("2026-11-20");
    expect(weekDays("2026-11-19")).toEqual(["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22"]);
  });

  it("a prior week's summary keeps an item withdrawn since, counted and marked (R2-067)", () => {
    let { s } = answer(initialVisit(), Y, "p-664f7533a19d", "Oui, j'y reviens.");
    s = { ...s, attempts: s.attempts.map((a) => ({ ...a, at: "2026-11-12T09:30:00Z" })) }; // last week
    s = reduce(catalog, s, { type: "draft", sourceId: Y, practiceId: "p-664f7533a19d", text: "" });
    s = run(catalog, s, { type: "arrive", at: at(), sourceId: Y });
    const lastWeek = weekDays("2026-11-12");
    const inWeek = byDay(s.attempts, "Europe/Paris").filter((d) => lastWeek.includes(d.day));
    expect(inWeek.map((d) => [d.day, d.attempts.length])).toEqual([["2026-11-12", 1]]);
    expect(summarize(inWeek[0].attempts, s.checks).production).toMatchObject({ independent: 1, notYet: 1 });
    expect(availability(catalog, s, Y, "p-664f7533a19d")).toMatchObject({ status: "withdrawn", code: "withdrawn_source_revised", revision: 2 });
  });

  it("exports the visit without answer texts unless asked, and every attempt resolves to its feed revision", () => {
    let s = answer(initialVisit(), Y, "p-664f7533a19d", "Oui, j'y reviens.").s;
    s = reduce(catalog, s, { type: "draft", sourceId: Y, practiceId: "p-664f7533a19d", text: "" });
    s = run(catalog, s, { type: "arrive", at: at(), sourceId: Y }, { type: "arrive", at: at(), sourceId: Y });
    s = answer(s, Y, "p-664f7533a19d", "Oui, j'en reviens.").s;
    const plain = exportVisit(catalog, s, { includeAnswers: false, zone: "Europe/Paris", exportedAt: "2026-11-19T10:00:00Z" });
    expect(JSON.stringify(plain)).not.toContain("j'y reviens");
    expect(plain.answer_texts_included).toBe(false);
    expect(plain.attempts.map((a) => [a.feed, a.revision])).toEqual([
      ["feed-y-en-demo-r1.json", 1],
      ["feed-y-en-demo-r2-reapproved.json", 2],
    ]);
    const full = exportVisit(catalog, s, { includeAnswers: true, zone: "Europe/Paris", exportedAt: "2026-11-19T10:00:00Z" });
    expect(full.attempts.map((a) => (a as { answer_text?: string }).answer_text)).toEqual(["Oui, j'y reviens.", "Oui, j'en reviens."]);
    expect(resolveExport(catalog, plain)).toEqual([]);
    const broken = { ...plain, attempts: [{ ...plain.attempts[0], revision_sha256: "f".repeat(64) }] };
    expect(resolveExport(catalog, broken)[0]).toMatch(/no feed for y-en-demo/);
  });

  it("marks a candidate correction accepted for this visit only, and refuses other classes", () => {
    let s = run(catalog, initialVisit(), { type: "accept", at: at(), session: 2, proposalId: "q2" }, { type: "accept", at: at(), session: 2, proposalId: "q2" });
    expect(s.accepted.map((a) => `${a.agent}:${a.proposalId}:${a.targetId}`)).toEqual(["claude-code:q2:k-40cbe73ae3f5"]);
    for (const pid of ["q1", "q3", "q4"]) s = run(catalog, s, { type: "accept", at: at(), session: 2, proposalId: pid });
    s = run(catalog, s, { type: "accept", at: at(), session: 1, proposalId: "c3" }); // an exercise: never accepted here
    expect(s.accepted).toHaveLength(1);
  });
});

describe("accessibility helpers (R2-074, R2-078)", () => {
  it("marks Chinese runs inside a French excerpt so each part has its language", () => {
    expect(langRuns("我问老师：« Oui, j'en vais. » 对吗？Elle a dit non.")).toEqual([
      { lang: "zh-CN", text: "我问老师：" },
      { lang: "fr", text: "« Oui, j'en vais. » " },
      { lang: "zh-CN", text: "对吗？" },
      { lang: "fr", text: "Elle a dit non." },
    ]);
    expect(langRuns("Tu reviens du marché ?")).toEqual([{ lang: "fr", text: "Tu reviens du marché ?" }]);
  });

  it("scrolls without animation when the learner prefers reduced motion, smoothly otherwise", () => {
    const orig = window.matchMedia;
    window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), media: q })) as unknown as typeof window.matchMedia;
    expect(scrollOpts().behavior).toBe("auto");
    window.matchMedia = ((q: string) => ({ matches: false, media: q })) as unknown as typeof window.matchMedia;
    expect(scrollOpts().behavior).toBe("smooth");
    window.matchMedia = orig;
  });
});
