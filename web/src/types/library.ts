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

// FLH-040 semantic search: an explicit, opt-in mode. The backend embeds the
// query, reads stored concept vectors and re-checks every hit against SQLite.
// FLH-071 hybrid: an explicit third mode that fuses both rankings on the server.
export type LibrarySearchMode = "keyword" | "semantic" | "hybrid";

export interface SemanticSearchResult {
  concept: Concept;
  // Cosine similarity between query and concept-document embeddings. Evidence
  // only: not a probability and not a SAME judgment.
  similarity: number;
  current_member_count: number;
  supporting_unit_count: number;
}

export interface SemanticSearch {
  schema_version: "knowledge_library_semantic_search_v2";
  query: string;
  query_representation: string;
  state: LibraryStateFilter;
  limit: number;
  // Recorded publication and last-run history (FLH-042). Not verified for this
  // request: health_verified is always false; operators verify with
  // `semantic-index status`.
  index: {
    space: string;
    collection: string;
    representation: string;
    model_id: string;
    dimensions: number;
    published_run_id: string;
    published_at: string | null;
    last_run_operation: string;
    last_run_outcome: "" | "published" | "verified_unchanged" | "failed" | "interrupted" | "sources_changed";
    last_run_finished_at: string | null;
    last_error: string;
    health_verified: false;
    note: string;
  };
  considered: number;
  skipped: { missing: number; stale: number; incompatible: number; non_positive: number };
  filtered_by_state: number;
  score_note: string;
  results: SemanticSearchResult[];
}

// FLH-071 hybrid search: the server fuses the keyword and semantic candidate
// rankings by Concept ID with reciprocal rank fusion. Every value below is a
// backend fact; the browser never recomputes ranks or scores.
export interface HybridSearchResult {
  concept: Concept;
  // Σ 1/(rrf_k + rank) over the components that ranked the concept. Not a
  // probability or a relevance estimate; comparable only within one response.
  fused_score: number;
  sources: Array<"keyword" | "semantic">;
  // Keyword rank is the keyword order (tier, status, title, id); it has no score.
  keyword: { rank: number; match_tier: "identity" | "unit_evidence"; matched_fields: string[] } | null;
  semantic: { rank: number; similarity: number } | null;
  current_member_count: number;
  supporting_unit_count: number;
}

export interface HybridSearch {
  schema_version: "knowledge_library_hybrid_search_v1";
  query: string;
  state: LibraryStateFilter;
  limit: number;
  depth: number;
  policy: { version: string; rrf_k: number; weights: { keyword: number; semantic: number }; tie_break: string };
  score_note: string;
  components: {
    keyword: { returned: number; total_matches: number; truncated_at_depth: boolean; matching: string };
    semantic: {
      returned: number;
      considered: number;
      skipped: { missing: number; stale: number; incompatible: number; non_positive: number };
      filtered_by_state: number;
      query_representation: string;
      index: SemanticSearch["index"];
      score_note: string;
    };
  };
  total_candidates: number;
  truncated: boolean;
  dropped_after_fusion: { missing: number; filtered_by_state: number; changed_during_search: number; duplicate_component_ids: number };
  results: HybridSearchResult[];
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
