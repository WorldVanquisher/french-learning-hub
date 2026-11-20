import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import discovery from "./discovery.json";
import { DEMO_COMPARISONS } from "./comparisons";
import { DEMO_EXAMPLES } from "./examples";
import { DEMO_QUERIES } from "./queries";

// discovery.json holds every French phrase the public demo keeps in its bundle
// (example questions, seed wording, suggested searches). Each must come from
// the synthetic catalog the demo artifact is built from, so the bundle carries
// no other text. The package check (check_examples.py) verifies the same
// entries against a running package's artifact.

const catalog = JSON.parse(readFileSync(resolve(process.cwd(), "../scripts/demo/flh073/fixtures/catalog.json"), "utf8")) as {
  data_classification: string;
  entries: Array<{ key: string; original_input: string; units: Array<{ key: string; canonical: string; statement: string; example?: string }> }>;
  concepts: Array<{ key: string; target: string; pedagogical_intent: string; scope: string; identity_features: Record<string, string>; members: string[] }>;
};
const fold = (s: string) => s.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "");
const units = catalog.entries.flatMap((e) => e.units.map((u) => ({ entry: e.key, ...u })));

describe("the demo's example data", () => {
  it("is synthetic catalog data", () => {
    expect(discovery.schema).toBe("flh_public_demo_discovery_v1");
    expect(catalog.data_classification).toBe("synthetic");
  });

  it("has every entry in the page: no example, comparison or query is dropped for want of text", () => {
    expect(DEMO_EXAMPLES.map((e) => e.key)).toEqual(discovery.examples.map((e) => e.key));
    expect(DEMO_COMPARISONS.map((c) => c.key)).toEqual(discovery.comparisons.map((c) => c.key));
    expect(DEMO_QUERIES.map((q) => q.q)).toEqual(discovery.queries.map((q) => q.q));
  });

  it("quotes each example question verbatim from one catalog record, and its seed from exactly one unit of that record", () => {
    for (const e of discovery.examples) {
      const records = catalog.entries.filter((x) => x.original_input === e.question);
      expect(records.map((r) => r.key), e.key).toHaveLength(1);
      const seeded = units.filter((u) => u.canonical.toLocaleLowerCase("fr").includes(e.seed));
      expect(seeded.map((u) => u.entry), e.key).toEqual([records[0].key]);
    }
  });

  it("takes each comparison side's seed from exactly one catalog unit, with an example", () => {
    for (const c of discovery.comparisons)
      for (const s of c.sides) {
        const seeded = units.filter((u) => u.canonical.toLocaleLowerCase("fr").includes(s.seed));
        expect(seeded, `${c.key}: ${s.seed}`).toHaveLength(1);
        expect(seeded[0].example).toBeTruthy();
      }
  });

  it("gives each practice item a form found exactly once in its side's catalog example, and only public data (R2-053)", () => {
    type Practice = { choices: Array<{ form: string; tense: string }>; items: Array<{ side: number; alternate: boolean }> };
    const withPractice = (discovery.comparisons as Array<{ key: string; example?: string; sides: Array<{ seed: string }>; practice?: Practice }>).filter((c) => c.practice);
    expect(withPractice.map((c) => c.key)).toEqual(["imparfait-passe-compose"]);
    for (const c of withPractice) {
      const p = c.practice!;
      expect(p.choices, c.key).toHaveLength(2);
      // Exactly these fields: forms and French tense names, no IDs, answers or other text.
      for (const ch of p.choices) expect(Object.keys(ch).sort()).toEqual(["form", "tense"]);
      for (const it of p.items) expect(Object.keys(it).sort()).toEqual(["alternate", "side"]);
      p.choices.forEach((ch, side) => {
        const u = units.find((x) => x.canonical.toLocaleLowerCase("fr").includes(c.sides[side].seed))!;
        expect(u.example!.split(ch.form).length - 1, `${c.key} side ${side}: ${ch.form}`).toBe(1);
        // The tense name is the unit's own wording.
        expect(u.canonical).toContain(ch.tense);
      });
      expect(new Set(p.items.map((it) => it.side))).toEqual(new Set([0, 1]));
      // The comparison names the guided example both its units come from.
      const sideEntries = c.sides.map((sd) => units.find((x) => x.canonical.toLocaleLowerCase("fr").includes(sd.seed))!.entry);
      const ex = discovery.examples.find((e) => e.key === c.example)!;
      expect(catalog.entries.find((e) => e.original_input === ex.question)!.key).toBe(sideEntries[0]);
      expect(sideEntries[1]).toBe(sideEntries[0]);
    }
  });

  it("suggests searches whose words occur in the catalog, except the one that shows finding nothing", () => {
    const text = fold(
      JSON.stringify([catalog.concepts, units.map((u) => [u.canonical, u.statement, u.example ?? ""])]),
    );
    for (const q of discovery.queries) {
      const words = fold(q.q).split(/[^\p{L}\p{N}]+/u).filter((w) => w.length > 1);
      const found = words.every((w) => text.includes(w));
      expect(found, q.q).toBe(q.shows !== "no_match");
    }
    const follow = discovery.queries.filter((q) => "follow_up" in q && q.follow_up);
    expect(follow).toHaveLength(1);
    for (const q of follow) {
      const f = (q as { follow_up: { q: string; example: string } }).follow_up;
      expect(discovery.examples.map((e) => e.key)).toContain(f.example);
      expect(fold(JSON.stringify(catalog.concepts))).toContain(fold(f.q));
    }
  });
});
