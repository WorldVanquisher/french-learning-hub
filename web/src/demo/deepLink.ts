import type { LibraryQuery, LibrarySearchMode, LibraryStateFilter } from "../types/library";
import { DEMO_EXAMPLES } from "./examples";

// Direct links for the public demo. The server serves the demo only at `/`
// (no SPA fallback, and the demo boundary refuses unknown paths), so a link
// must be a URL fragment, which browsers never send to the server:
//
//   #example=y-en                  a guided example
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
// Anything else, including an unknown example key or preset, a malformed ID or
// an over-long query, opens the starting screen, and `malformed` says so: the
// page then tells the visitor that the link matched nothing. A link names IDs
// only; every screen still reads its data from the server, so a well-formed
// link to an ID this build lacks opens that screen's "not in this demo" state.
export type LinkScreen =
  | { kind: "results" }
  | { kind: "example"; example: string }
  | { kind: "concept"; conceptId: number; from?: string }
  | { kind: "source"; conceptId: number; unitId: number; from?: string };

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
const STATES: readonly LibraryStateFilter[] = ["all", "active", "orphaned", "retired"];
const PRESET = /^[a-z0-9][a-z0-9-]{0,63}$/;

type ParsedSearch = LinkSearch | "malformed";

function searchFromParams(params: URLSearchParams, presets?: readonly string[]): ParsedSearch {
  const mode = params.get("mode") ?? "keyword";
  const state = params.get("state") ?? "all";
  const q = (params.get("q") ?? "").trim();
  const preset = params.get("preset");
  if (!STATES.includes(state as LibraryStateFilter)) return "malformed";
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
  if (exampleKey && !example) return "malformed";
  if (concept === null) {
    if (unit !== null) return "malformed";
    return example ? { kind: "example", example } : { kind: "results" };
  }
  if (!ID.test(concept) || (unit !== null && !ID.test(unit))) return "malformed";
  const conceptId = Number(concept);
  if (unit !== null) return { kind: "source", conceptId, unitId: Number(unit), from: example };
  return { kind: "concept", conceptId, from: example };
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

type AnyScreen = { kind: string; example?: string; conceptId?: number; unitId?: number; from?: string };

export function hashForScreen(screen: AnyScreen, search: LinkSearch = NO_SEARCH): string {
  const params = new URLSearchParams();
  if (search.mode === "keyword") {
    if (search.q) params.set("q", search.q);
  } else if (search.preset) {
    params.set("mode", search.mode);
    params.set("preset", search.preset);
  }
  if (search.state !== "all" && (search.mode === "keyword" || search.preset)) params.set("state", search.state);
  if (screen.kind === "example" && screen.example) params.set("example", screen.example);
  if ((screen.kind === "concept" || screen.kind === "source") && screen.conceptId) {
    if (screen.from) params.set("example", screen.from);
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
