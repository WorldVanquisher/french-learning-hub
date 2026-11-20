// Tutor packets with rubrics are the learner's explicit (owner-only) choice in
// the extraction tool. Even they must never carry the learner's own answer
// texts, the full question or its context: only the cited excerpts. Checked on
// every packet of the sealed fixtures (R3-036).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { FIXTURE_DOCUMENTS } from "./extractionPracticeFixture";

// Answers the sealed 2.1 pipeline typed (practice_flow.py) that are not rubric content.
const LEARNER_ANSWERS = ["y with à, en with de", "conait", "Oui, je le connais bien."];
// The y/en source's full question and context (the extraction fixture in this tree): a packet
// may quote short excerpts around a cited quote, never the whole text.
const SOURCE = (JSON.parse(readFileSync(resolve(process.cwd(), "../tools/extraction/fixtures/practice_v1/y_en.r1.json"), "utf8")) as { capture: { original_input: string; original_context: string } }).capture;
const UNQUOTED_SOURCE = [SOURCE.original_input, SOURCE.original_context];

describe("owner-only tutor packets", () => {
  const packets = FIXTURE_DOCUMENTS.filter((d) => /^(tutor-|study-|session-1-codex-packet)/.test(d.name));
  it("are present: three tutor packets with rubrics and the study packets", () => {
    expect(packets.filter((d) => d.name.startsWith("tutor-")).length).toBe(3);
    for (const d of packets.filter((x) => x.name.startsWith("tutor-"))) expect(JSON.parse(d.text).rubrics_included).toBe(true);
  });

  it("never carry the learner's answer texts, the full question or its context", () => {
    for (const d of packets) {
      for (const s of [...LEARNER_ANSWERS, ...UNQUOTED_SOURCE]) expect([d.name, d.text.includes(s)]).toEqual([d.name, false]);
      const j = d.name.endsWith(".json") ? (JSON.parse(d.text) as Record<string, unknown>) : null;
      if (j) for (const k of ["original_input", "original_context", "attempts", "answer_text"]) expect([d.name, k in j]).toEqual([d.name, false]);
    }
  });
});
