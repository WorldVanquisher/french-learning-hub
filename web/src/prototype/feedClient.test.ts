// The Extraction 2.2 feeds against Workbooks' consumer: the sealed copy's
// checksums, the feed parser on every 2.2 feed (the contract additions), the
// feed IDs, and the extraction lane's own sealed replay cases run through
// Workbooks' client (parity with their reference client).
import { describe, expect, it } from "vitest";
import { format } from "../i18n";
import { FIXTURE22_DOCUMENTS, FIXTURE22_SOURCE } from "./extraction22Fixture";
import { applyFeed, emptyClient, feedIdOf } from "./feedClient";
import { parseFeed } from "./practiceFeed";
import { isKnownReasonCode, reasonCodeMessage } from "./reasonCodes";
import { sha256Hex } from "./sha256";

const text = (n: string) => FIXTURE22_DOCUMENTS.find((d) => d.name === n)!.text;
const doc = (n: string) => JSON.parse(text(n)) as Record<string, never>;
const FEEDS = FIXTURE22_DOCUMENTS.filter((d) => d.name.startsWith("feed-")).map((d) => d.name);

describe("Extraction 2.2 feeds (sealed) in Workbooks", () => {
  it("re-hashes every sealed document", () => {
    expect(FIXTURE22_SOURCE.handoff_sha256sums).toBe("e529568b5e5761677ca5de041fdab1cf253fc9f9d611a010defcece12651cde0");
    for (const d of FIXTURE22_DOCUMENTS) expect([d.name, sha256Hex(d.text)]).toEqual([d.name, d.sha256]);
    expect(FEEDS).toHaveLength(5);
  });

  it("parses every 2.2 feed with the contract additions (withdrawn reason codes, restored, added)", () => {
    const parsed = FEEDS.map((n) => [n, parseFeed(doc(n))] as const);
    const r2 = parsed.find(([n]) => n === "feed-3-r2-withdrawn.json")![1];
    expect(r2.withdrawn!.map((w) => [w.practice_id, w.kind, w.reason_code, w.since_revision])).toEqual([["p-3e03bff58a01", "choose", "rule_not_approved", 2]]);
    expect(parsed.map(([, f]) => f.items.length)).toEqual([5, 6, 5, 5, 6]);
  });

  it("computes each feed's ID exactly as the extraction lane does", () => {
    for (const n of FEEDS) {
      const f = doc(n) as Record<string, never> & { feed_id: string };
      expect([n, feedIdOf(f)]).toEqual([n, f.feed_id]);
    }
  });

  it("runs the sealed replay cases with the same actions and final state as the reference client", () => {
    const cases = (JSON.parse(text("replay-cases.json")) as { cases: Record<string, { deliver: string[]; expect: { actions: string[]; items: Record<string, unknown> } }> }).cases;
    expect(Object.keys(cases).length).toBeGreaterThanOrEqual(4);
    for (const [name, c] of Object.entries(cases)) {
      let st = emptyClient();
      const actions = c.deliver.map((n) => {
        const r = applyFeed(st, doc(n));
        st = r.state;
        return r.action;
      });
      const got = Object.fromEntries(
        Object.entries(st.items)
          .sort(([a], [b]) => (a < b ? -1 : 1))
          .map(([pid, v]) => [pid, { offered: v.offered, history: v.history.length, ...(v.withdrawnReason ? { reason: v.withdrawnReason } : {}) }]),
      );
      expect([name, actions]).toEqual([name, c.expect.actions]);
      expect([name, got]).toEqual([name, c.expect.items]);
    }
  });

  it("explains every 2.2 reason code in both languages; an unknown code is shown verbatim, never guessed", () => {
    const codes = FEEDS.flatMap((n) => parseFeed(doc(n)).withdrawn ?? []).map((w) => [w.reason_code!, w.since_revision!] as const);
    expect([...new Set(codes.map(([c]) => c))].sort()).toEqual(["awaiting_confirmation", "rule_not_approved"]);
    for (const [code, since] of codes) {
      expect(isKnownReasonCode(code)).toBe(true);
      for (const loc of ["en", "zh-CN"] as const) {
        const m = reasonCodeMessage(code, since);
        const s = format(loc, m.key, m.vars);
        expect([code, loc, s.includes(String(since)), /[{}]/.test(s)]).toEqual([code, loc, true, false]);
      }
    }
    const u = reasonCodeMessage("rule_not_aproved", 4);
    expect(format("en", u.key, u.vars)).toBe("Withdrawn in revision 4 for a reason Workbooks does not know (rule_not_aproved).");
    expect(format("zh-CN", u.key, u.vars)).toContain("rule_not_aproved");
  });

  it("never adds a question or an outcome on a duplicated or retried delivery", () => {
    let st = emptyClient();
    for (const n of ["feed-1-r1.json", "feed-2-r1-newly-approved.json"]) st = applyFeed(st, doc(n)).state;
    const before = JSON.stringify(st.items);
    for (let i = 0; i < 3; i++) {
      const r = applyFeed(st, doc("feed-2-r1-newly-approved.json"));
      expect(r.action).toBe("replay");
      st = r.state;
    }
    const older = applyFeed(st, doc("feed-1-r1.json"));
    expect(older.action).toBe("replay");
    expect(JSON.stringify(st.items)).toBe(before);
    expect(Object.keys(st.items)).toHaveLength(6);
  });

  it("withdraws on a revision, keeps the reason and the history, and restores the same ID", () => {
    let st = emptyClient();
    for (const n of ["feed-1-r1.json", "feed-2-r1-newly-approved.json", "feed-3-r2-withdrawn.json"]) st = applyFeed(st, doc(n)).state;
    const pid = "p-3e03bff58a01";
    expect([st.items[pid].offered, st.items[pid].withdrawnReason, st.items[pid].history.length]).toEqual([false, "rule_not_approved", 1]);
    st = applyFeed(st, doc("feed-4-r3-awaiting-confirmation.json")).state;
    expect(st.items[pid].withdrawnReason).toBe("awaiting_confirmation");
    st = applyFeed(st, doc("feed-5-r3-restored.json")).state;
    expect([st.items[pid].offered, st.items[pid].withdrawnReason, st.items[pid].history.length]).toEqual([true, undefined, 1]);
    // the same feed again is a replay; an older feed never seen is stale (a late delivery)
    expect(applyFeed(st, doc("feed-3-r2-withdrawn.json")).action).toBe("replay");
    let late = applyFeed(emptyClient(), doc("feed-5-r3-restored.json")).state;
    const r = applyFeed(late, doc("feed-1-r1.json"));
    late = r.state;
    expect([r.action, late.items[pid].offered]).toEqual(["stale", true]);
  });
});
