import type { LibraryStateFilter } from "./types/library";
import { VIEWS, type View } from "./workbenchViews";

// Workbench section addresses: each section has one canonical URL fragment,
// `#/<view>` (for example `#/speaking`). The server serves the workbench only
// at `/` and has deliberately no SPA fallback, so an address must be a
// fragment, which the browser never sends to the server. Choosing a section
// adds a history entry, so Back and Forward move between sections and a reload
// reopens the section.
//
// The Knowledge Library's keyword search is part of its address:
// `#/library?q=il+faut&state=active` (q at most 200 characters; state omitted
// when "all"), so a search can be reloaded, bookmarked or copied. Submitting a
// search replaces the current entry rather than adding one.
//
// Nothing else a section keeps (drafts, recorded audio, an open item) is in
// the address and, as before, none of it survives a reload. Nothing is written
// to browser storage.

export const DEFAULT_VIEW: View = "review";
export const MAX_ADDRESS_QUERY = 200;

export interface LibraryAddress {
  q: string;
  state: LibraryStateFilter;
}

export interface Address {
  view: View;
  library?: LibraryAddress;
}

export const NO_LIBRARY_SEARCH: LibraryAddress = { q: "", state: "all" };
const STATES: readonly LibraryStateFilter[] = ["all", "active", "orphaned", "retired"];

export function sectionHash(view: View): string {
  return `#/${view}`;
}

// addressFor is the canonical fragment for a view (and the library's search).
export function addressFor(view: View, library: LibraryAddress = NO_LIBRARY_SEARCH): string {
  if (view !== "library" || (library.q === "" && library.state === "all")) return sectionHash(view);
  const params = new URLSearchParams();
  if (library.q) params.set("q", library.q);
  if (library.state !== "all") params.set("state", library.state);
  return `${sectionHash(view)}?${params.toString()}`;
}

// parseAddress reads a fragment strictly: the empty fragment is the default
// section, a known `#/<view>` is that section, the library may carry `q` and
// `state`, and anything else (an unknown section, an unknown or repeated
// parameter, a query on another section, an over-long query) is "unknown".
export function parseAddress(hash: string): Address | "unknown" {
  if (hash === "" || hash === "#") return { view: DEFAULT_VIEW };
  const m = /^#\/([a-z]{1,20})(?:\?(.*))?$/.exec(hash);
  if (!m || !(VIEWS as readonly string[]).includes(m[1])) return "unknown";
  const view = m[1] as View;
  if (m[2] === undefined) return view === "library" ? { view, library: NO_LIBRARY_SEARCH } : { view };
  if (view !== "library") return "unknown";
  const params = new URLSearchParams(m[2]);
  const keys = [...params.keys()];
  if (keys.some((k) => k !== "q" && k !== "state") || new Set(keys).size !== keys.length) return "unknown";
  const q = (params.get("q") ?? "").trim();
  const state = params.get("state") ?? "all";
  if (q.length > MAX_ADDRESS_QUERY || !STATES.includes(state as LibraryStateFilter)) return "unknown";
  return { view, library: { q, state: state as LibraryStateFilter } };
}

// viewFromHash is parseAddress's section only.
export function viewFromHash(hash: string): View | "unknown" {
  const a = parseAddress(hash);
  return a === "unknown" ? "unknown" : a.view;
}

export function sameLibrarySearch(a: LibraryAddress | undefined, b: LibraryAddress | undefined): boolean {
  const x = a ?? NO_LIBRARY_SEARCH;
  const y = b ?? NO_LIBRARY_SEARCH;
  return x.q === y.q && x.state === y.state;
}
