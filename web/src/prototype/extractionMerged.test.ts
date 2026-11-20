// R4-WB-021 to R4-WB-025: the MERGED Extraction contract in this tree
// (tools/extraction/fixtures/practice_v1/workbooks2 and the service_v1 feed)
// against Workbooks' parser, feed client and reason codes. Read from the
// repository files, not from the sealed copy, so a later change shows here.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { format } from "../i18n";
import { FIXTURE22_DOCUMENTS } from "./extraction22Fixture";
import { applyFeed, emptyClient, feedIdOf } from "./feedClient";
import { parseFeed } from "./practiceFeed";
import { isKnownReasonCode, reasonCodeMessage } from "./reasonCodes";
import { sha256Hex } from "./sha256";

const TOOLS = resolve(process.cwd(), "../tools/extraction");
const read = (p: string) => readFileSync(resolve(TOOLS, p), "utf8");
const FEEDS = ["feed-1-r1.json", "feed-2-r1-newly-approved.json", "feed-3-r2-withdrawn.json", "feed-4-r3-awaiting-confirmation.json", "feed-5-r3-restored.json"];
const merged = (n: string) => read(`fixtures/practice_v1/workbooks2/${n}`);
const doc = (n: string) => JSON.parse(merged(n)) as Record<string, never>;
// The reason codes the merged PRACTICE.md §13 lists for withdrawn entries.
const CONTRACT_CODES = (() => {
  const s = read("PRACTICE.md");
  const at = s.indexOf("`withdrawn`: each entry has a `reason_code`, one of");
  const until = s.indexOf("It is repeated", at);
  return [...s.slice(at, until).matchAll(/`([a-z_]+)`/g)].map((m) => m[1]).filter((c) => c !== "withdrawn" && c !== "reason_code");
})();

describe("the merged Extraction contract in Workbooks", () => {
  it("has the same 2.2 bytes as the sealed copy the page uses (R4-WB-021, R4-WB-025)", () => {
    for (const n of [...FEEDS, "replay-cases.json", "compat-report.json"]) {
      const sealed = FIXTURE22_DOCUMENTS.find((d) => d.name === n)!;
      expect([n, sha256Hex(merged(n))]).toEqual([n, sealed.sha256]);
    }
  });

  it("parses every merged 2.2 feed and the service_v1 feed with the existing parser (R4-WB-021)", () => {
    for (const n of FEEDS) expect(() => parseFeed(doc(n))).not.toThrow();
    const res = JSON.parse(read("fixtures/service_v1/03-feed.response.json")) as { status: number; body: { contract: string; feed: Record<string, never> & { feed_id: string } } };
    expect([res.status, res.body.contract]).toEqual([200, "flh_extraction_service_v1"]);
    const f = parseFeed(res.body.feed);
    expect(f.items.length).toBeGreaterThan(0);
    expect(feedIdOf(res.body.feed)).toBe(res.body.feed.feed_id);
    expect(applyFeed(emptyClient(), res.body.feed).action).toBe("applied");
  });

  it("reports replay and stale and leaves the state untouched, the same object (R4-WB-022)", () => {
    let st = emptyClient();
    for (const n of ["feed-1-r1.json", "feed-3-r2-withdrawn.json"]) st = applyFeed(st, doc(n)).state;
    const frozen = JSON.stringify(st);
    const replay = applyFeed(st, doc("feed-3-r2-withdrawn.json"));
    const stale = applyFeed(st, doc("feed-2-r1-newly-approved.json"));
    expect([replay.action, stale.action]).toEqual(["replay", "stale"]);
    expect(replay.state).toBe(st);
    expect(stale.state).toBe(st);
    expect(JSON.stringify(st)).toBe(frozen);
  });

  it("keeps a withdrawn exercise's history through withdrawal and restore (R4-WB-023)", () => {
    let st = emptyClient();
    for (const n of FEEDS.slice(0, 3)) st = applyFeed(st, doc(n)).state;
    const pid = "p-3e03bff58a01";
    const history = st.items[pid].history.length;
    expect([st.items[pid].offered, history > 0]).toEqual([false, true]);
    for (const n of FEEDS.slice(3)) st = applyFeed(st, doc(n)).state;
    expect([st.items[pid].offered, st.items[pid].history.length]).toEqual([true, history]);
  });

  it("keeps an activity withdrawn for an unknown reason code, shown verbatim (R4-WB-024)", () => {
    let st = emptyClient();
    for (const n of FEEDS.slice(0, 2)) st = applyFeed(st, doc(n)).state;
    const f3 = doc("feed-3-r2-withdrawn.json") as unknown as { feed_id?: string; withdrawn: { reason_code: string }[] };
    const changed = JSON.parse(JSON.stringify(f3)) as typeof f3;
    delete changed.feed_id;
    changed.withdrawn[0].reason_code = "rule_retired_v9";
    st = applyFeed(st, changed as unknown as Record<string, never>).state;
    const pid = "p-3e03bff58a01";
    expect([st.items[pid].offered, st.items[pid].withdrawnReason, st.items[pid].history.length]).toEqual([false, "rule_retired_v9", 1]);
    const m = reasonCodeMessage("rule_retired_v9", 2);
    expect(format("en", m.key, m.vars)).toBe("Withdrawn in revision 2 for a reason Workbooks does not know (rule_retired_v9).");
  });

  it("explains every reason code the merged contract lists, in both languages (R4-WB-025)", () => {
    expect(CONTRACT_CODES).toEqual(["knowledge_changed", "awaiting_confirmation", "rejected", "rule_not_approved", "absent"]);
    for (const code of CONTRACT_CODES) {
      expect([code, isKnownReasonCode(code)]).toEqual([code, true]);
      const m = reasonCodeMessage(code, 3);
      for (const loc of ["en", "zh-CN"] as const) expect(format(loc, m.key, m.vars)).not.toMatch(/[{}]|does not know|不认识/);
    }
  });
});
