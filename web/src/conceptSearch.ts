import type { Concept } from "./types/concept";

// Search normalization is retrieval-only. It never changes a stored Concept,
// identity signature, or SAME semantics.
export function normalizeConceptSearch(value: string): string {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

// discoverConcepts performs transparent local catalog filtering. Every query token
// must appear somewhere in the durable identity fields. Results preserve backend
// catalog order; presentation has no annotation authority.
export function discoverConcepts(
  concepts: readonly Concept[],
  query: string,
  exactConceptIds: ReadonlySet<number>,
): Concept[] {
  const tokens = normalizeConceptSearch(query).split(/\s+/).filter(Boolean);

  return concepts.filter((concept) => {
    if (concept.lifecycle_state === "retired" || exactConceptIds.has(concept.id)) {
      return false;
    }

    const featureText = Object.entries(concept.identity_features ?? {})
      .sort(([left], [right]) => left.localeCompare(right))
      .flatMap(([key, value]) => [key, value]);
    const searchable = normalizeConceptSearch(
      [concept.target, concept.pedagogical_intent, concept.scope, ...featureText].join(" "),
    );

    return tokens.every((token) => searchable.includes(token));
  });
}
