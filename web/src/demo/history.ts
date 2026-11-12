import { hashForScreen, NO_SEARCH, urlForScreen, type LinkSearch } from "./deepLink";

// The public demo's navigation contract (the private workbench keeps no history):
//
// - Every screen (start or results, example, Concept, evidence) is one browser
//   history entry on the same page; its address is the screen's direct link.
// - Opening a screen, submitting a search that changes the results, or clearing
//   one adds an entry. Browser Back and Forward walk those entries.
// - An in-page "← Back …" action goes back in history when the screen it names
//   is earlier in this visit, so it is the same move as the browser's Back and
//   leaves Forward intact. When that screen is not in this visit's history (the
//   visitor arrived by a direct link) it replaces the current entry instead, so
//   it never leaves a loop of entries behind.
// - A reload stays on the entry: its address names the screen and the search.
//
// Each entry the demo writes keeps the trail of this visit's entries up to it
// (their link keys), which is how an in-page back finds how far back to go.
type Screen = { kind: string; example?: string; conceptId?: number; unitId?: number; from?: string };

export interface DemoEntry<S extends Screen> {
  flhLibrary: S;
  flhSearch: LinkSearch;
  flhTrail: string[];
}

const TRAIL_LIMIT = 50;

export const entryKey = (screen: Screen, search: LinkSearch) => hashForScreen(screen, search) || "#";

// readEntry returns the demo entry stored in a history state, or null for any
// other state (a fragment typed into the address bar has none).
export function readEntry<S extends Screen>(state: unknown): DemoEntry<S> | null {
  const s = state as Partial<DemoEntry<S>> | null;
  if (!s || typeof s !== "object" || !s.flhLibrary || typeof s.flhLibrary !== "object") return null;
  const search = s.flhSearch ?? NO_SEARCH;
  const trail = Array.isArray(s.flhTrail) && s.flhTrail.every((k) => typeof k === "string") ? s.flhTrail : [entryKey(s.flhLibrary, search)];
  return { flhLibrary: s.flhLibrary, flhSearch: search, flhTrail: trail };
}

function write<S extends Screen>(how: "push" | "replace", screen: S, search: LinkSearch, trail: string[]): string[] {
  const next = trail.slice(-TRAIL_LIMIT);
  const entry: DemoEntry<S> = { flhLibrary: screen, flhSearch: search, flhTrail: next };
  const state = { ...(window.history.state ?? {}), ...entry };
  if (how === "push") window.history.pushState(state, "", urlForScreen(screen, search));
  else window.history.replaceState(state, "", urlForScreen(screen, search));
  return next;
}

// pushEntry adds an entry for a newly opened screen and returns its trail.
export const pushEntry = <S extends Screen>(screen: S, search: LinkSearch, trail: string[]) =>
  write("push", screen, search, [...trail, entryKey(screen, search)]);

// replaceEntry rewrites the current entry and returns its trail.
export const replaceEntry = <S extends Screen>(screen: S, search: LinkSearch, trail: string[]) =>
  write("replace", screen, search, [...trail.slice(0, -1), entryKey(screen, search)]);

// adoptEntry gives an entry the browser created without demo state (a fragment
// typed or pasted into the address bar, which follows the current entry) its
// place after this trail.
export const adoptEntry = <S extends Screen>(screen: S, search: LinkSearch, trail: string[]) =>
  write("replace", screen, search, [...trail, entryKey(screen, search)]);

// stepsBack is how many entries back the most recent `key` is in this trail,
// not counting the current entry; 0 when it is not there.
export function stepsBack(trail: readonly string[], key: string): number {
  for (let i = trail.length - 2; i >= 0; i--) if (trail[i] === key) return trail.length - 1 - i;
  return 0;
}
