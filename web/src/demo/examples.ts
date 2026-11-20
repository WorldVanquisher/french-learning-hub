import * as api from "../api/client";
import discovery from "./discovery.json";
import type { MessageKey } from "../i18n";
import type { Concept } from "../types/concept";
import type { LibraryConcept, LibrarySource, LibraryUnit } from "../types/library";

// The public demo's guided examples: the three questions written in French in
// the synthetic catalog (scripts/demo/flh073/fixtures/catalog.json), the most
// beginner-friendly first, and one written in English whose two units are the
// imparfait/passé composé comparison (R2). An example
// names application text, how to find its question through the existing read
// API (a keyword query, the library's own search, and a word from the stored
// wording of one unit extracted from that question) and, for the starting
// screen's card only, the synthetic question's exact French wording, so a
// visitor chooses by the French itself before anything is read. The question,
// units and Concepts of an opened example are always read from the server;
// GuidedExample.test.tsx keeps these definitions, the card wording included,
// in step with the catalog.
export interface DemoExample {
  key: string;
  title: MessageKey;
  // The catalog question, verbatim (never translated), and the language it is
  // written in (French unless the data says otherwise).
  question: string;
  lang: string;
  // Existing keyword search; its Concepts hold the example's units.
  query: string;
  // Lower-case text found in the canonical wording of exactly one unit of the
  // example's question.
  seed: string;
  // The comparison (comparisons.ts) built from this example's units, if any.
  compare?: string;
}

// The example data lives in discovery.json (also read by the package check);
// the titles are application text, by key.
const EXAMPLE_TITLES: Readonly<Record<string, MessageKey>> = {
  "y-en": "demo.example.yEn.title",
  "il-faut-venir": "demo.example.ilFaut.title",
  "en-train-de": "demo.example.enTrainDe.title",
  imparfait: "demo.example.imparfait.title",
};

type ExampleData = { key: string; question: string; query: string; seed: string; lang?: string; compare?: string };

export const DEMO_EXAMPLES: readonly DemoExample[] = (discovery.examples as ExampleData[])
  .filter((e) => EXAMPLE_TITLES[e.key])
  .map((e) => ({ ...e, lang: e.lang ?? "fr", title: EXAMPLE_TITLES[e.key] }));

// One unit taken from the example's question, with the Concept it is filed under.
export interface ExtractedUnit {
  unit: LibraryUnit;
  concept: Concept;
}

// A Concept the example's question contributed to, with how much other evidence it has.
export interface ExampleConcept {
  concept: Concept;
  fromThisQuestion: number;
  supporting: number;
}

export interface ResolvedExample {
  source: LibrarySource;
  extracted: ExtractedUnit[];
  concepts: ExampleConcept[];
}

// `missing` means this demo build does not contain the example (another
// catalog); the page then offers the example's search instead of guessing.
export type ExampleResolution = { kind: "found"; example: ResolvedExample } | { kind: "missing" };

const norm = (s: string) => s.toLocaleLowerCase("fr");

// resolveExample reads only: one keyword search, the matched Concepts, and the
// source of the seed unit. Units count as extracted from the question only when
// they currently support a matched Concept and come from the seed's record.
export async function resolveExample(example: DemoExample, fetchImpl: typeof fetch = fetch): Promise<ExampleResolution> {
  const search = await api.searchLibrary({ q: example.query, state: "all" }, fetchImpl);
  const details: LibraryConcept[] = await Promise.all(
    search.results.map((r) => api.getLibraryConcept(r.concept.id, fetchImpl)),
  );
  const seeds = details.flatMap((d) => d.supporting_units).filter((u) => norm(u.canonical).includes(example.seed));
  const seedIds = new Set(seeds.map((u) => u.unit_id));
  if (seedIds.size !== 1) return { kind: "missing" };
  const seed = seeds[0];
  const extracted: ExtractedUnit[] = [];
  const concepts: ExampleConcept[] = [];
  for (const d of details) {
    const mine = d.supporting_units.filter((u) => u.entry_id === seed.entry_id);
    if (mine.length === 0) continue;
    for (const u of mine) if (!extracted.some((e) => e.unit.unit_id === u.unit_id)) extracted.push({ unit: u, concept: d.concept });
    concepts.push({ concept: d.concept, fromThisQuestion: mine.length, supporting: d.supporting_units.length });
  }
  const source = await api.getLibraryUnitSource(seed.unit_id, fetchImpl);
  return { kind: "found", example: { source, extracted, concepts } };
}
