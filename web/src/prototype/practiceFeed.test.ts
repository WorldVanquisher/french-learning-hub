// The practice feed consumer against the SEALED Extraction 2.1 fixtures: the
// contract checks, the join, the grading mirror (the same cases grade_parity.py
// runs through the sealed Python), and what may be copied.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { FIXTURE_DOCUMENTS } from "./extractionPracticeFixture";
import { ContractError, excerptParts, frNorm, grade, joinConcept, latestOutcome, outcomeCounts, parseFeed, parsePacket } from "./practiceFeed";

const text = (name: string) => FIXTURE_DOCUMENTS.find((d) => d.name === name)!.text;
const doc = (name: string) => JSON.parse(text(name)) as unknown;
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;
const concept = (feed = "feed-y-en-demo-r1.json", tutor = "tutor-y-en-r1.json", study = "study-y-en-r1.json") =>
  joinConcept(parseFeed(doc(feed)), parsePacket(doc(tutor)), parsePacket(doc(study)), text(study.replace(".json", ".md")));

describe("practice feed consumer (sealed Extraction 2.1)", () => {
  it("joins a feed with its tutor keys and study packet, in practice order", () => {
    const c = concept();
    expect(c.concept).toBe("y vs en");
    expect(c.source).toMatchObject({ source_id: "y-en-demo", revision: 1, capture_id: "synthetic-y-en-001" });
    expect(c.items.map((i) => `${i.kind}:${i.practice_id}`)).toEqual([
      "explain:p-2ea892e5eaa0",
      "produce:p-664f7533a19d",
      "produce:p-8d5cabf2ab59",
      "choose:p-0e74504cf958",
      "choose:p-22a947cd7f5c",
    ]);
    expect(c.rubric("p-664f7533a19d").answer).toBe("Oui, j'en reviens.");
    expect(c.rubric("p-2ea892e5eaa0").reference.length).toBeGreaterThan(0);
    expect(c.studyPacket.id).toBe("pk-afdb387f3af6");
    expect(c.studyPacket.packet.schema).toBe("flh_practice_packet_v2");
    expect(outcomeCounts(c.items)).toEqual({ correct: 2, incorrect: 1, self_check: 1, revealed: 1, invalid: 0, none: 0 });
    expect(latestOutcome(c.items.find((i) => i.practice_id === "p-0e74504cf958")!)).toBe("revealed");
    const contrast = c.knowledge.find((k) => k.id === "k-0d3281b28da6")!;
    expect(contrast.accepted_from).toEqual({ agent: "codex", packet_id: "pk-e2920fe276cb", proposal_id: "c1" });
  });

  it("reads `withdrawn` and `previous`, and an empty item list, from a revised feed", () => {
    const r2 = parseFeed(doc("feed-y-en-demo-r2.json"));
    expect(r2.items).toEqual([]);
    expect(r2.previous).toEqual({ revision: 1, revision_sha256: "fd55a3600f1c2dd1ab69503dcba4c5cfb20562d845ece7f3f76e9fc0ba6eb0a5" });
    expect(r2.withdrawn!.map((w) => `${w.kind}:${w.practice_id}`)).toEqual([
      "explain:p-2ea892e5eaa0",
      "choose:p-0e74504cf958",
      "choose:p-22a947cd7f5c",
      "produce:p-664f7533a19d",
      "produce:p-8d5cabf2ab59",
    ]);
    expect(r2.withdrawn![0].reason).toMatch(/^not offered from revision 2/);
    expect(parseFeed(doc("feed-y-en-demo-r1.json")).withdrawn).toBeNull();
    expect(parseFeed(doc("feed-y-en-demo-r2-reapproved.json")).withdrawn).toEqual([]);
    const both = clone(doc("feed-y-en-demo-r2-reapproved.json")) as { withdrawn: unknown[] };
    both.withdrawn = [{ practice_id: "p-2ea892e5eaa0", kind: "explain", reason: "x" }];
    expect(() => parseFeed(both)).toThrow(/still offered/);
  });

  it("grades exactly like the extraction lane (shared cases, three grading fixtures)", () => {
    const cases = JSON.parse(readFileSync(resolve(process.cwd(), "../scripts/validation/extraction_practice/grading_cases.json"), "utf8")).cases as {
      grading: string;
      feed: string;
      practice_id: string;
      text: string;
      outcome: string;
    }[];
    expect(cases.length).toBeGreaterThanOrEqual(26);
    expect(new Set(cases.map((k) => k.grading)).size).toBe(3);
    for (const k of cases) {
      const study = k.grading.replace("tutor-", "study-");
      const c = concept(k.feed, k.grading, study);
      const it = c.items.find((i) => i.practice_id === k.practice_id)!;
      expect([k.grading, k.practice_id, k.text, grade(it.kind, it.options, c.rubric(it.practice_id), k.text).outcome]).toEqual([k.grading, k.practice_id, k.text, k.outcome]);
    }
    expect(frNorm("« Oui, J’EN reviens… »")).toBe("oui j'en reviens");
  });

  it("refuses what the contract excludes, stale pairs and keys in a study packet", () => {
    const FEED = doc("feed-y-en-demo-r1.json");
    expect(() => parseFeed({ schema: "other" })).toThrow(ContractError);
    const withKey = clone(FEED) as { items: Record<string, unknown>[] };
    withKey.items[0].answer = "en";
    expect(() => parseFeed(withKey)).toThrow(/must not contain/);
    const withDue = clone(FEED) as { items: Record<string, unknown>[] };
    withDue.items[1].due = "2026-11-20";
    expect(() => parseFeed(withDue)).toThrow(/must not contain/);
    const badReveal = clone(FEED) as { items: { outcomes: Record<string, unknown>[] }[] };
    badReveal.items[1].outcomes[0] = { seq: 5, action: "reveal", outcome: "correct" };
    expect(() => parseFeed(badReveal)).toThrow(/recorded as revealed/);
    // a revision-1 tutor packet beside the revision-2 feed: refused
    expect(() =>
      joinConcept(parseFeed(doc("feed-y-en-demo-r2-reapproved.json")), parsePacket(doc("tutor-y-en-r1.json")), parsePacket(doc("study-y-en-r2.json")), text("study-y-en-r2.md")),
    ).toThrow(/different source revisions/);
    expect(() => joinConcept(parseFeed(FEED), parsePacket(doc("study-y-en-r1.json")), parsePacket(doc("study-y-en-r1.json")), text("study-y-en-r1.md"))).toThrow(/tutor packet/);
    const keyed = clone(doc("study-y-en-r1.json")) as { next_exercises: Record<string, unknown>[] };
    keyed.next_exercises[0].rubric = { grading: "exact", answer: "en" };
    expect(() => parsePacket(keyed)).toThrow(/must not carry rubrics/);
  });

  it("copies study packets that hold no answer key (the sealed case's forbidden strings, every study packet)", () => {
    const cases = doc("cases.json") as { cases: Record<string, { expect: { forbidden_strings: string[] } }> };
    const forbidden = cases.cases["study-packet-without-answers"].expect.forbidden_strings;
    expect(forbidden.length).toBe(9);
    for (const name of ["study-y-en-r1", "study-y-en-r2", "study-savoir-connaitre-r1", "session-1-codex-packet"]) {
      for (const t of [text(`${name}.json`), text(`${name}.md`)]) {
        if (name.includes("y-en") || name.includes("codex")) for (const f of forbidden) expect(t).not.toContain(f);
        expect(t).not.toMatch(/"rubric"/);
      }
    }
    const sc = concept("feed-savoir-connaitre-demo-r1.json", "tutor-savoir-connaitre-r1.json", "study-savoir-connaitre-r1.json");
    for (const it of sc.items) {
      const r = sc.rubric(it.practice_id);
      if (it.kind === "produce") for (const key of [...r.accepted, r.answer!]) expect(sc.studyPacket.markdown).not.toContain(key);
    }
  });

  it("marks the quoted words inside an excerpt", () => {
    expect(excerptParts("…langerie ? » J'ai répondu : « [Oui, j'en vais.] » Elle…")).toEqual({
      before: "…langerie ? » J'ai répondu : « ",
      quote: "Oui, j'en vais.",
      after: " » Elle…",
    });
    expect(excerptParts("no brackets")).toBeNull();
  });
});
