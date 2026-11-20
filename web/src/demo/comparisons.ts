import * as api from "../api/client";
import { ApiError } from "../api/client";
import discovery from "./discovery.json";
import type { MessageKey } from "../i18n";
import type { Concept } from "../types/concept";
import type { LibraryConcept, LibrarySource, LibraryUnit } from "../types/library";

// The public demo's comparisons: two units of the synthetic catalog
// (scripts/demo/flh073/fixtures/catalog.json) that illustrate one French
// distinction, shown side by side. Like a guided example (examples.ts), a side
// names only how to find its unit through the existing read API: a keyword
// query, and lower-case text found in the canonical wording of exactly one unit
// of the Concepts that query matches. Everything shown is read from the server
// (one search, the matched Concepts, the unit's source); nothing is written.
// DiscoverySpec.test.ts keeps the data in step with the catalog.
export interface ComparisonSide {
  query: string;
  seed: string;
}

// Optional choose-first practice (R2): one question per item. An item shows its
// side's example (read from the server) with that side's choice form blanked,
// and offers both sides' forms, always in side order, so the position never
// gives the answer away. The answer is the form the example itself uses; it is
// revealed, with each form's rule and a link to its evidence, only after a
// choice or an explicit skip. `alternate`: the other form also makes a correct
// sentence there, with another meaning, which the reveal says (`alternates`,
// application text per item). Forms and tense names are French and never
// translated; a form must occur exactly once in its side's example, or the item
// is not offered (DiscoverySpec.test.ts and check_examples.py hold the data to
// that).
export interface PracticeChoice {
  form: string;
  tense: string;
}
export interface PracticeItem {
  side: 0 | 1;
  alternate: boolean;
  alternateText?: MessageKey;
}
export interface ComparisonPractice {
  choices: readonly [PracticeChoice, PracticeChoice];
  items: readonly PracticeItem[];
}

export interface DemoComparison {
  key: string;
  title: MessageKey;
  summary: MessageKey;
  sides: readonly [ComparisonSide, ComparisonSide];
  // The guided example (examples.ts) whose question both units come from.
  example?: string;
  practice?: ComparisonPractice;
}

// The comparison data lives in discovery.json (also read by the package
// check); the title, summary and practice explanations are application text,
// by key.
const COMPARISON_TEXT: Readonly<Record<string, { title: MessageKey; summary: MessageKey; alternates?: readonly MessageKey[] }>> = {
  "imparfait-passe-compose": {
    title: "demo.compare.imparfait.title",
    summary: "demo.compare.imparfait.summary",
    alternates: ["demo.practice.imparfait.alternate.1", "demo.practice.imparfait.alternate.2"],
  },
  "depuis-pendant": { title: "demo.compare.depuis.title", summary: "demo.compare.depuis.summary" },
};

type ComparisonData = {
  key: string;
  example?: string;
  sides: ComparisonSide[];
  practice?: { choices: PracticeChoice[]; items: Array<{ side: number; alternate: boolean }> };
};

function practiceOf(c: ComparisonData): ComparisonPractice | undefined {
  const p = c.practice;
  if (!p || p.choices.length !== 2) return undefined;
  const alternates = COMPARISON_TEXT[c.key]?.alternates ?? [];
  const items = p.items
    .filter((it) => it.side === 0 || it.side === 1)
    .map((it, i) => ({ side: it.side as 0 | 1, alternate: it.alternate && Boolean(alternates[i]), alternateText: it.alternate ? alternates[i] : undefined }));
  return items.length ? { choices: [p.choices[0], p.choices[1]], items } : undefined;
}

export const DEMO_COMPARISONS: readonly DemoComparison[] = (discovery.comparisons as ComparisonData[])
  .filter((c) => COMPARISON_TEXT[c.key] && c.sides.length === 2)
  .map((c) => ({
    key: c.key,
    title: COMPARISON_TEXT[c.key].title,
    summary: COMPARISON_TEXT[c.key].summary,
    sides: [c.sides[0], c.sides[1]] as const,
    ...(c.example ? { example: c.example } : {}),
    ...(practiceOf(c) ? { practice: practiceOf(c) } : {}),
  }));

// blankForm splits an example around the one occurrence of a practice form:
// [before, after], or null when the form is not there exactly once (this
// build's unit has other wording), so the item is not offered.
export function blankForm(example: string | null | undefined, form: string): [string, string] | null {
  if (!example || !form) return null;
  const at = example.indexOf(form);
  if (at < 0 || example.indexOf(form, at + 1) >= 0) return null;
  return [example.slice(0, at), example.slice(at + form.length)];
}

export const findComparison = (key: string | undefined) => (key ? DEMO_COMPARISONS.find((c) => c.key === key) : undefined);

// One side as this build has it. `missing`: no Concept the query matches holds
// a unit with the seed wording (another catalog). `no-source`: the unit is
// there but its source record cannot be read (404), so the side shows the unit
// without the question it came from.
export type SideResolution =
  | { kind: "found"; unit: LibraryUnit; concept: Concept; supporting: boolean; source: LibrarySource | null }
  | { kind: "missing" };

const norm = (s: string) => s.toLocaleLowerCase("fr");

export async function resolveSide(side: ComparisonSide, fetchImpl: typeof fetch = fetch): Promise<SideResolution> {
  const search = await api.searchLibrary({ q: side.query, state: "all" }, fetchImpl);
  const details: LibraryConcept[] = await Promise.all(search.results.map((r) => api.getLibraryConcept(r.concept.id, fetchImpl)));
  for (const d of details) {
    const unit = [...d.supporting_units, ...d.non_supporting_members].find((u) => norm(u.canonical).includes(side.seed));
    if (!unit) continue;
    let source: LibrarySource | null = null;
    try {
      source = await api.getLibraryUnitSource(unit.unit_id, fetchImpl);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) throw e;
    }
    return { kind: "found", unit, concept: d.concept, supporting: d.supporting_units.some((u) => u.unit_id === unit.unit_id), source };
  }
  return { kind: "missing" };
}
