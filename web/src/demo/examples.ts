import * as api from "../api/client";
import type { MessageKey } from "../i18n";
import type { Concept } from "../types/concept";
import type { LibraryConcept, LibrarySource, LibraryUnit } from "../types/library";

// The public demo's guided examples: the three questions written in French in
// the synthetic catalog (scripts/demo/flh073/fixtures/catalog.json). An example
// names only application text and how to find its question through the existing
// read API: a keyword query (the library's own search) and a word from the
// stored wording of one unit extracted from that question. Nothing here is
// learner content; the question, units and Concepts shown are read from the
// server. examples.test.ts keeps these in step with the catalog.
export interface DemoExample {
  key: string;
  title: MessageKey;
  summary: MessageKey;
  // Existing keyword search; its Concepts hold the example's units.
  query: string;
  // Lower-case text found in the canonical wording of exactly one unit of the
  // example's question.
  seed: string;
}

export const DEMO_EXAMPLES: readonly DemoExample[] = [
  { key: "y-en", title: "demo.example.yEn.title", summary: "demo.example.yEn.summary", query: "pronouns", seed: "y remplace" },
  {
    key: "il-faut-venir",
    title: "demo.example.ilFaut.title",
    summary: "demo.example.ilFaut.summary",
    query: "viennes",
    seed: "subjonctif de venir",
  },
  {
    key: "en-train-de",
    title: "demo.example.enTrainDe.title",
    summary: "demo.example.enTrainDe.summary",
    query: "action en cours",
    seed: "en train de",
  },
];

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
