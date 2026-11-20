import type { LibraryQuery, LibrarySearchMode, LibraryStateFilter } from "../types/library";
import { DEMO_COMPARISONS } from "./comparisons";
import { DEMO_EXAMPLES } from "./examples";

// Direct links for the public demo. The server serves the demo only at `/`
// (no SPA fallback, and the demo boundary refuses unknown paths), so a link
// must be a URL fragment, which browsers never send to the server:
//
//   #example=y-en                  a guided example
//   #example=y-en&step=2           …at step 2 of its walkthrough (1–4)
//   #compare=depuis-pendant        a comparison of two units (comparisons.ts)
//   #compare=…&practice=1          its choose-first question 1 (R3-056: the exact
//                                  exercise; answers are never in a link)
//   …&compare=depuis-pendant       a Concept or source opened from that comparison
//                                  (…&practice=1 too when opened from its question)
//   #concept=12                    a Concept
//   #concept=12&unit=14            the source of unit 14, reached from Concept 12
//   …&example=y-en                 the same, opened from that example (its back
//                                  actions return to that example)
//   #q=il+faut                     the results of a submitted keyword search
//   #q=il+faut&state=active        …with a status filter
//   #mode=semantic&preset=right-now  a semantic (or hybrid) preset search
//
// The search parameters may precede any screen: `#q=il+faut&concept=1` is
// Concept 1 opened from the results for "il faut", so a reload keeps both the
// Concept and the way back to those results. Every identifier is a stable
// fixture identifier: an example key, a preset id, or a Concept or unit ID,
// which the artifact's domain fingerprint fixes for a given catalog.
//
// A blank `q` (or one of spaces) is the start's own empty search.
//
// R2-085: the optional parameters, `step` (an example's walkthrough step) and
// `state` (the search's status filter), are tolerated: an invalid or blank
// value, or a step on a screen that has none, is left out, and the link opens
// what its other parameters name. The page then rewrites the address to that
// screen's own link, so the address bar and a copied link show the canonical
// form. Parameters the demo does not know (`utm_source=…`) are ignored the
// same way.
//
// Any other parameter with a blank value (`#example=`, `#concept=12&unit=`) is
// a link cut short. That, an unknown example key or preset, a malformed ID or
// an over-long query opens the starting screen, and `malformed` says so: the
// page then tells the visitor that the link matched nothing. A link names IDs
// only; every screen still reads its data from the server, so a well-formed
// link to an ID this build lacks opens that screen's "not in this demo" state.
export type LinkScreen =
  | { kind: "results" }
  | { kind: "example"; example: string; step?: number }
  | { kind: "compare"; compare: string; practice?: number }
  | { kind: "concept"; conceptId: number; from?: string; compare?: string; comparePractice?: number }
  | { kind: "source"; conceptId: number; unitId: number; from?: string; compare?: string; comparePractice?: number };

// A submitted search as a link carries it. Semantic and hybrid searches are
// named by their preset only (the demo runs presets only); `q` is then empty.
export interface LinkSearch {
  mode: LibrarySearchMode;
  q: string;
  state: LibraryStateFilter;
  preset?: string;
}

export const NO_SEARCH: LinkSearch = { mode: "keyword", q: "", state: "all" };
export const MAX_LINK_QUERY = 200;

const ID = /^[1-9][0-9]{0,8}$/;
// The guided example's walkthrough steps: question, units, Concept, evidence.
export const WALK_STEPS = 4;
const STEP = /^[1-4]$/;
const PRACTICE = /^[1-9]$/;
const STATES: readonly LibraryStateFilter[] = ["all", "active", "orphaned", "retired"];
const PRESET = /^[a-z0-9][a-z0-9-]{0,63}$/;

type ParsedSearch = LinkSearch | "malformed";

function searchFromParams(params: URLSearchParams, presets?: readonly string[]): ParsedSearch {
  const mode = params.get("mode") ?? "keyword";
  // An unknown or blank status filter is left out (R2-085).
  const given = params.get("state");
  const state = given !== null && STATES.includes(given as LibraryStateFilter) ? given : "all";
  const q = (params.get("q") ?? "").trim();
  const preset = params.get("preset");
  if (mode === "keyword") {
    if (preset !== null || q.length > MAX_LINK_QUERY) return "malformed";
    return { mode: "keyword", q, state: state as LibraryStateFilter };
  }
  if (mode !== "semantic" && mode !== "hybrid") return "malformed";
  if (params.has("q") || preset === null || !PRESET.test(preset)) return "malformed";
  if (presets && !presets.includes(preset)) return "malformed";
  return { mode, q: "", state: state as LibraryStateFilter, preset };
}

function screenFromParams(params: URLSearchParams): LinkScreen | "malformed" {
  const exampleKey = params.get("example");
  const example = exampleKey && DEMO_EXAMPLES.some((e) => e.key === exampleKey) ? exampleKey : undefined;
  const concept = params.get("concept");
  const unit = params.get("unit");
  // A step that is not one of the walkthrough's, or on a screen without a
  // walkthrough, is left out (R2-085).
  const givenStep = params.get("step");
  const step = givenStep !== null && STEP.test(givenStep) && params.get("example") !== null && params.get("concept") === null ? givenStep : null;
  const compareKey = params.get("compare");
  const compare = compareKey && DEMO_COMPARISONS.some((c) => c.key === compareKey) ? compareKey : undefined;
  // A blank value names nothing (a link cut short), like an unknown one.
  if (exampleKey !== null && !example) return "malformed";
  // A comparison is its own screen, or where a Concept or source was opened from.
  if (compareKey !== null && (!compare || example)) return "malformed";
  // R3-056: `practice` names one of the comparison's questions (1-based). It is
  // optional: a value the comparison has no question for is left out.
  const givenPractice = params.get("practice");
  const items = compare ? (DEMO_COMPARISONS.find((c) => c.key === compare)?.practice?.items.length ?? 0) : 0;
  const practice = givenPractice !== null && PRACTICE.test(givenPractice) && Number(givenPractice) <= items ? Number(givenPractice) : undefined;
  const via = compare ? (practice ? { compare, comparePractice: practice } : { compare }) : {};
  if (concept === null) {
    if (unit !== null) return "malformed";
    if (compare) return practice ? { kind: "compare", compare, practice } : { kind: "compare", compare };
    return example ? (step !== null ? { kind: "example", example, step: Number(step) } : { kind: "example", example }) : { kind: "results" };
  }
  if (!ID.test(concept) || (unit !== null && !ID.test(unit))) return "malformed";
  const conceptId = Number(concept);
  if (unit !== null) return { kind: "source", conceptId, unitId: Number(unit), from: example, ...via };
  return { kind: "concept", conceptId, from: example, ...via };
}

// linkFromHash reads a whole fragment. `presets` (the demo's preset ids, when
// known) makes an unknown preset a malformed link like any other.
export function linkFromHash(
  hash: string,
  presets?: readonly string[],
): { screen: LinkScreen; search: LinkSearch; malformed: boolean } {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const screen = screenFromParams(params);
  const search = searchFromParams(params, presets);
  if (screen === "malformed" || search === "malformed") return { screen: { kind: "results" }, search: NO_SEARCH, malformed: true };
  return { screen, search, malformed: false };
}

export function screenFromHash(hash: string): LinkScreen {
  return linkFromHash(hash).screen;
}

type AnyScreen = {
  kind: string;
  example?: string;
  step?: number;
  compare?: string;
  practice?: number;
  comparePractice?: number;
  conceptId?: number;
  unitId?: number;
  from?: string;
};

export function hashForScreen(screen: AnyScreen, search: LinkSearch = NO_SEARCH): string {
  const params = new URLSearchParams();
  if (search.mode === "keyword") {
    if (search.q) params.set("q", search.q);
  } else if (search.preset) {
    params.set("mode", search.mode);
    params.set("preset", search.preset);
  }
  if (search.state !== "all" && (search.mode === "keyword" || search.preset)) params.set("state", search.state);
  if (screen.kind === "example" && screen.example) {
    params.set("example", screen.example);
    if (screen.step) params.set("step", String(screen.step));
  }
  if (screen.kind === "compare" && screen.compare) {
    params.set("compare", screen.compare);
    if (screen.practice) params.set("practice", String(screen.practice));
  }
  if ((screen.kind === "concept" || screen.kind === "source") && screen.conceptId) {
    if (screen.from) params.set("example", screen.from);
    if (screen.compare) {
      params.set("compare", screen.compare);
      if (screen.comparePractice) params.set("practice", String(screen.comparePractice));
    }
    params.set("concept", String(screen.conceptId));
    if (screen.kind === "source" && screen.unitId) params.set("unit", String(screen.unitId));
  }
  const s = params.toString();
  return s ? `#${s}` : "";
}

// The address for a screen: this page, with the screen's fragment (none for the start).
export function urlForScreen(screen: AnyScreen, search: LinkSearch = NO_SEARCH): string {
  return `${window.location.pathname}${window.location.search}${hashForScreen(screen, search)}`;
}

export const sameSearch = (a: LinkSearch, b: LinkSearch) =>
  a.mode === b.mode && a.q === b.q && a.state === b.state && (a.preset ?? "") === (b.preset ?? "");

// The link form of a submitted library search, and back. A preset search is
// named by its id; its text comes from the demo's own preset list.
export function queryToSearch(query: LibraryQuery, mode: LibrarySearchMode): LinkSearch {
  return mode === "keyword" ? { mode, q: query.q, state: query.state } : { mode, q: "", state: query.state, preset: query.preset };
}

export function searchToQuery(search: LinkSearch, presets: ReadonlyArray<{ id: string; text: string }>): { query: LibraryQuery; mode: LibrarySearchMode } {
  if (search.mode === "keyword") return { query: { q: search.q, state: search.state }, mode: "keyword" };
  const preset = presets.find((p) => p.id === search.preset);
  return preset
    ? { query: { q: preset.text, state: search.state, preset: preset.id }, mode: search.mode }
    : { query: { q: "", state: "all" }, mode: "keyword" };
}
