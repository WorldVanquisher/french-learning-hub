// The view and trail tables App navigates by. Behaviour (each banner and its
// return) is covered by the App-level tests in DailyJourney, RecordToConcept,
// ConceptSuggestions and the Listening/Reading/Writing page tests; this checks
// the tables themselves in both catalogs.
import { describe, expect, it } from "vitest";
import { en } from "./i18n/en";
import { zhCN } from "./i18n/zh-CN";
import { KEPT_VIEWS, ORIGIN_TRAIL, VIEW_COPY, VIEWS, isKeptView, trailVars, type Origin } from "./workbenchViews";

describe("workbench view tables", () => {
  it("lists every view once, with copy, and keeps only known views mounted", () => {
    expect(new Set(VIEWS).size).toBe(VIEWS.length);
    expect(Object.keys(VIEW_COPY).sort()).toEqual([...VIEWS].sort());
    for (const v of KEPT_VIEWS) expect(VIEWS).toContain(v);
    expect(VIEWS.filter(isKeptView)).toEqual([...KEPT_VIEWS]);
  });

  it("returns every origin to a real view, with messages in both languages", () => {
    for (const [kind, trail] of Object.entries(ORIGIN_TRAIL)) {
      expect(VIEWS).toContain(trail.view);
      for (const key of [trail.from, trail.back]) {
        const hasId = kind === "record";
        expect(en[key].includes("{id}")).toBe(hasId);
        expect(zhCN[key].includes("{id}")).toBe(hasId);
      }
    }
  });

  it("passes the record id only to record trails", () => {
    const record: Origin = { kind: "record", target: { kind: "review", entryId: 7, unitId: 3, extractionId: 2, extractionVersion: 1 } };
    expect(trailVars(record)).toEqual({ id: 7 });
    expect(trailVars({ kind: "writing" })).toBeUndefined();
  });
});
