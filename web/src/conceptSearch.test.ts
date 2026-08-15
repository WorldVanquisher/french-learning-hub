import { describe, expect, it } from "vitest";
import type { Concept } from "./types/concept";
import { discoverConcepts, normalizeConceptSearch } from "./conceptSearch";

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
