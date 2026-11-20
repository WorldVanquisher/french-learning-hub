// Applying a sequence of practice feeds (PROTOTYPE): Workbooks' side of the
// Extraction 2.2 feed additions (flh_practice_feed_additions_v1). It mirrors
// the extraction lane's reference client (check_feed_compat.py client_apply),
// and feedClient.test.ts runs that lane's sealed replay cases against it:
//   - a feed already applied (same feed_id) is a replay and changes nothing,
//     so a retried or duplicated delivery never adds a question or an outcome;
//   - an older feed (lower revision, then lower feed_seq) is stale and ignored;
//   - a withdrawn practice ID stops being offered and keeps its history, with
//     the producer's reason code; a restored one is offered again with it;
//   - outcomes are merged by seq, never duplicated.
// Nothing here is stored: the state lives in the page like the rest of the
// prototype.

import { sha256Hex } from "./sha256";

export type FeedAction = "applied" | "replay" | "stale" | "other_source";

export interface ClientItem {
  offered: boolean;
  history: { seq: number; action: string; outcome: string }[];
  withdrawnReason?: string;
}

export interface ClientState {
  sourceId: string | null;
  key: [number, number] | null;
  seen: string[];
  items: Record<string, ClientItem>;
}

export const emptyClient = (): ClientState => ({ sourceId: null, key: null, seen: [], items: {} });

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

// The extraction lane's canonical JSON: sorted keys, no spaces, non-ASCII kept.
export function canon(x: Json): string {
  if (x === null || typeof x !== "object") return JSON.stringify(x);
  if (Array.isArray(x)) return `[${x.map(canon).join(",")}]`;
  return `{${Object.keys(x)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${canon(x[k])}`)
    .join(",")}}`;
}

export const feedIdOf = (feed: Record<string, Json>): string => {
  const rest: Record<string, Json> = {};
  for (const k of Object.keys(feed)) if (k !== "feed_id") rest[k] = feed[k];
  return "f-" + sha256Hex(canon(rest)).slice(0, 12);
};

interface FeedLike {
  feed_id?: string;
  feed_seq?: number;
  source: { source_id: string; revision: number };
  items: { practice_id: string; outcomes?: { seq: number; action: string; outcome: string }[] }[];
  withdrawn?: { practice_id: string; reason_code?: string }[];
}

export function applyFeed(state: ClientState, raw: Record<string, Json>): { state: ClientState; action: FeedAction } {
  const f = raw as unknown as FeedLike;
  if (state.sourceId !== null && state.sourceId !== f.source.source_id) return { state, action: "other_source" };
  const fid = f.feed_id ?? feedIdOf(raw);
  if (state.seen.includes(fid)) return { state, action: "replay" };
  const key: [number, number] = [f.source.revision, f.feed_seq ?? 0];
  if (state.key && (state.key[0] > key[0] || (state.key[0] === key[0] && state.key[1] > key[1]))) return { state, action: "stale" };
  const items: Record<string, ClientItem> = {};
  for (const [k, v] of Object.entries(state.items)) items[k] = { ...v, history: [...v.history] };
  const now = new Set(f.items.map((p) => p.practice_id));
  for (const p of f.items) {
    const it = (items[p.practice_id] ??= { offered: true, history: [] });
    it.offered = true;
    delete it.withdrawnReason;
    const have = new Set(it.history.map((o) => o.seq));
    for (const o of p.outcomes ?? []) if (!have.has(o.seq)) it.history.push({ seq: o.seq, action: o.action, outcome: o.outcome });
    it.history.sort((a, b) => a.seq - b.seq);
  }
  for (const x of f.withdrawn ?? []) {
    if (now.has(x.practice_id)) continue;
    const it = (items[x.practice_id] ??= { offered: false, history: [] });
    it.offered = false;
    it.withdrawnReason = x.reason_code ?? "unspecified";
  }
  return { state: { sourceId: f.source.source_id, key, seen: [...state.seen, fid], items }, action: "applied" };
}
