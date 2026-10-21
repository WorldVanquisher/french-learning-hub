import { describe, expect, it } from "vitest";
import type { Concept } from "./types/concept";
import { createConceptDiscovery, discoverConcepts, normalizeConceptSearch, visibleDiscovery } from "./conceptSearch";

function concept(id: number, target: string, overrides: Partial<Concept> = {}): Concept {
  return {
    id,
    identity_schema_version: "fr_l2_concept_identity_v1",
    target,
    pedagogical_intent: "grammar",
    scope: "",
    identity_features: {},
    signature: `{${id}}`,
    preferred_unit_id: null,
    state: "active",
    lifecycle_state: "normal",
    support_state: "supported",
    created_at: "t",
    updated_at: "t",
    ...overrides,
  };
}

describe("concept discovery search", () => {
  it("matches all durable identity fields with multiple case-insensitive tokens", () => {
    const concepts = [
      concept(1, "passé composé"),
      concept(2, "liaison", { pedagogical_intent: "Pronunciation" }),
      concept(3, "vocabulary", { scope: "Québec travel" }),
      concept(4, "register", { identity_features: { register: "familier" } }),
      concept(5, "Être", { pedagogical_intent: "GRAMMAR", scope: "Québec" }),
    ];

    expect(discoverConcepts(concepts, "passé", new Set<number>()).map((item) => item.id)).toEqual([1]);
    expect(discoverConcepts(concepts, "PRONUNCIATION", new Set<number>()).map((item) => item.id)).toEqual([2]);
    expect(discoverConcepts(concepts, "travel", new Set<number>()).map((item) => item.id)).toEqual([3]);
    expect(discoverConcepts(concepts, "register familier", new Set<number>()).map((item) => item.id)).toEqual([4]);
    expect(discoverConcepts(concepts, "etre grammar quebec", new Set<number>()).map((item) => item.id)).toEqual([5]);
  });

  it("normalizes French accents for search convenience only", () => {
    expect(normalizeConceptSearch("Élève à Noël")).toBe("eleve a noel");
    expect(normalizeConceptSearch("vouloir + infinitif")).toBe("vouloir infinitif");
  });

  it("excludes retired and exact-match concepts while keeping orphaned concepts discoverable", () => {
    const concepts = [
      concept(1, "active exact"),
      concept(2, "orphaned", { state: "orphaned", support_state: "orphaned" }),
      concept(3, "retired", { state: "retired", lifecycle_state: "retired" }),
    ];

    expect(discoverConcepts(concepts, "", new Set([1])).map((item) => item.id)).toEqual([2]);
  });
});

// FLH-089: the catalog is prepared once; results and order must not change.
describe("prepared concept discovery", () => {
  const catalog = [
    concept(3, "subjonctif après il faut que", { identity_features: { mood: "subjonctif" } }),
    concept(2, "passé composé", { lifecycle_state: "retired" }),
    concept(1, "accord du participe", { support_state: "orphaned", state: "orphaned" }),
    concept(4, "Être ou avoir", { scope: "auxiliaire" }),
  ];

  it("returns exactly what discoverConcepts returns, in catalog order, for every query", () => {
    const prepared = createConceptDiscovery(catalog);
    for (const query of ["", "subjonctif", "ETRE", "etre auxiliaire", "participe", "mood", "nothing", "  "]) {
      for (const exact of [new Set<number>(), new Set([3])]) {
        expect(prepared(query, exact)).toEqual(discoverConcepts(catalog, query, exact));
      }
    }
    expect(prepared("", new Set()).map((c) => c.id)).toEqual([3, 1, 4]);
  });

  it("shows one page of matches and keeps a selected match visible beyond it", () => {
    const many = Array.from({ length: 7 }, (_, i) => concept(i + 1, `c${i + 1}`));
    expect(visibleDiscovery(many, 3, null).map((c) => c.id)).toEqual([1, 2, 3]);
    expect(visibleDiscovery(many, 3, 6).map((c) => c.id)).toEqual([1, 2, 3, 6]);
    expect(visibleDiscovery(many, 3, 2).map((c) => c.id)).toEqual([1, 2, 3]);
    // A selection that no longer matches is not invented into the results.
    expect(visibleDiscovery(many, 3, 99).map((c) => c.id)).toEqual([1, 2, 3]);
  });
});
