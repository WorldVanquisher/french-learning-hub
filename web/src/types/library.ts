// FLH-034 Knowledge Library wire types (read-only GET /knowledge-library/...).
// Every field is a backend fact; the browser only renders and labels them.
import type { Concept, UnitConceptLink } from "./concept";
import type { Analysis, EffectiveAnalysis, Entry, Feedback } from "./learning";

export type LibraryStateFilter = "all" | "active" | "orphaned" | "retired";

export interface LibraryQuery {
  q: string;
  state: LibraryStateFilter;
}

export interface LibrarySearchResult {
  concept: Concept;
  match_tier: "identity" | "unit_evidence" | "browse";
  matched_fields: string[];
  current_member_count: number;
  supporting_unit_count: number;
}

export interface LibrarySearch {
  schema_version: "knowledge_library_search_v1";
  query: string;
  tokens: string[];
  state: LibraryStateFilter;
  limit: number;
  total_matches: number;
  truncated: boolean;
  results: LibrarySearchResult[];
}

// One unit with the provenance facts needed to label it honestly.
export interface LibraryUnit {
  unit_id: number;
  kind: string;
  canonical: string;
  statement: string;
  example: string | null;
  entry_id: number;
  extraction_id: number;
  extraction_version: number;
  in_current_extraction: boolean;
  admission: "active" | "suppressed" | "needs_review" | string;
}

export interface LibraryRelation {
  relation: "broader" | "narrower" | "related";
  link_id: number;
  decision_source: string;
  decided_at: string;
  unit: LibraryUnit;
}

export interface LibraryHistoricalUnit {
  unit: LibraryUnit;
  latest_event: UnitConceptLink;
  effective_status: "invalid" | "resolved" | "unresolved";
  current_concept_id: number | null;
}

export interface LibraryConcept {
  schema_version: "knowledge_library_concept_v1";
  concept: Concept;
  preferred_unit: LibraryUnit | null;
  supporting_units: LibraryUnit[];
  non_supporting_members: LibraryUnit[];
  current_relations: LibraryRelation[];
  historical_units: LibraryHistoricalUnit[];
  history_event_count: number;
}

export interface LibrarySource {
  schema_version: "knowledge_library_source_v1";
  unit: LibraryUnit;
  entry: Entry;
  extraction: {
    id: number;
    version: number;
    extractor: string;
    source_analysis_id: number;
    source_feedback_id: number | null;
    created_at: string;
  };
  current_extraction: { extraction_id: number | null; selection_mode: "automatic" | "pinned" };
  source_interpretation: { analysis: Analysis; feedback: Feedback | null; effective: EffectiveAnalysis };
  latest_analysis: { id: number; version: number; created_at: string } | null;
  annotation: { status: "invalid" | "resolved" | "unresolved"; current_concept_id: number | null };
}
