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

// The number of discovery results shown at first and added by each "show more".
// Every match stays reachable; the count of all matches is always shown.
export const DISCOVERY_PAGE_SIZE = 50;

// ConceptDiscovery is the catalog prepared for repeated searches: each
// non-retired Concept's durable identity fields are normalized once, so a
// keystroke filters prepared text instead of re-normalizing the whole catalog.
export type ConceptDiscovery = (query: string, exactConceptIds: ReadonlySet<number>) => Concept[];

export function createConceptDiscovery(concepts: readonly Concept[]): ConceptDiscovery {
  const prepared = concepts
    .filter((concept) => concept.lifecycle_state !== "retired")
    .map((concept) => {
      const featureText = Object.entries(concept.identity_features ?? {})
        .sort(([left], [right]) => left.localeCompare(right))
        .flatMap(([key, value]) => [key, value]);
      const searchable = normalizeConceptSearch(
        [concept.target, concept.pedagogical_intent, concept.scope, ...featureText].join(" "),
      );
      return { concept, searchable };
    });

  return (query, exactConceptIds) => {
    const tokens = normalizeConceptSearch(query).split(/\s+/).filter(Boolean);
    return prepared
      .filter(({ concept, searchable }) => !exactConceptIds.has(concept.id) && tokens.every((token) => searchable.includes(token)))
      .map(({ concept }) => concept);
  };
}

// discoverConcepts performs transparent local catalog filtering. Every query token
// must appear somewhere in the durable identity fields. Results preserve backend
// catalog order; presentation has no annotation authority.
export function discoverConcepts(
  concepts: readonly Concept[],
  query: string,
  exactConceptIds: ReadonlySet<number>,
): Concept[] {
  return createConceptDiscovery(concepts)(query, exactConceptIds);
}

// visibleDiscovery returns the first `shown` matches, plus the selected Concept
// when it is a match further down, so a selection is never hidden.
export function visibleDiscovery(matches: readonly Concept[], shown: number, selectedId: number | null): Concept[] {
  const visible = matches.slice(0, shown);
  if (selectedId !== null && !visible.some((c) => c.id === selectedId)) {
    const selected = matches.find((c) => c.id === selectedId);
    if (selected) visible.push(selected);
  }
  return visible;
}
