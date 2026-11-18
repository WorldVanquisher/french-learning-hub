import type { LibraryStateFilter } from "../types/library";

// Recent Knowledge Library searches (private workbench only). After DocSearch's
// stored searches (algolia/docsearch packages/docsearch-react/src/stored-searches.ts):
// a short list, newest first, a repeat moves to the front, each item can be
// removed and the whole list cleared.
//
// Storage behaviour, stated on the page next to the list:
// - kept only in this browser's localStorage under RECENT_SEARCHES_KEY, never
//   sent to the server and never part of an address or export;
// - only submitted keyword searches with text (the words and the status
//   filter), at most RECENT_SEARCHES_LIMIT;
// - unreadable or invalid stored data counts as an empty list; a browser that
//   refuses storage gets no list and is told so.

export const RECENT_SEARCHES_KEY = "flh.library.recent.v1";
export const RECENT_SEARCHES_LIMIT = 5;
const MAX_Q = 200;
const STATES: readonly LibraryStateFilter[] = ["all", "active", "orphaned", "retired"];

export interface RecentSearch {
  q: string;
  state: LibraryStateFilter;
}

const same = (a: RecentSearch, b: RecentSearch) => a.q === b.q && a.state === b.state;

function valid(x: unknown): x is RecentSearch {
  if (!x || typeof x !== "object") return false;
  const r = x as Record<string, unknown>;
  return typeof r.q === "string" && r.q.trim() !== "" && r.q.length <= MAX_Q && STATES.includes(r.state as LibraryStateFilter);
}

// readRecent returns the stored list, or null when this browser refuses storage.
export function readRecent(): RecentSearch[] | null {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(RECENT_SEARCHES_KEY);
  } catch {
    return null;
  }
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const out: RecentSearch[] = [];
    for (const item of parsed) {
      if (valid(item) && !out.some((o) => same(o, item))) out.push({ q: item.q, state: item.state });
      if (out.length === RECENT_SEARCHES_LIMIT) break;
    }
    return out;
  } catch {
    return [];
  }
}

function write(list: RecentSearch[]): boolean {
  try {
    if (list.length === 0) window.localStorage.removeItem(RECENT_SEARCHES_KEY);
    else window.localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(list));
    return true;
  } catch {
    return false;
  }
}

// Each change returns the new list, or null when it could not be stored.
export function addRecent(list: RecentSearch[], entry: RecentSearch): RecentSearch[] | null {
  const q = entry.q.trim();
  if (!q || q.length > MAX_Q) return list;
  const next = [{ q, state: entry.state }, ...list.filter((r) => !same(r, { q, state: entry.state }))].slice(0, RECENT_SEARCHES_LIMIT);
  return write(next) ? next : null;
}

export function removeRecent(list: RecentSearch[], entry: RecentSearch): RecentSearch[] | null {
  const next = list.filter((r) => !same(r, entry));
  return write(next) ? next : null;
}

export function clearRecent(): RecentSearch[] | null {
  return write([]) ? [] : null;
}
