import type { ReviewableUnit, UnitConceptLink } from "./concept";

// FLH-097 advisory Concept membership suggestions. A suggestion is never
// membership and never a human label; only an explicit confirmation records a
// human SAME after the backend revalidates the current state.

export type SuggestionOutcome = "suggested" | "no_suitable_candidate" | "uncertain" | "no_candidates";
export type SuggestionItemState = "open" | "confirmed" | "stale" | "no_suggestion";
export type SuggestionStaleReason =
  | "unit_not_in_current_extraction"
  | "unit_has_current_same"
  | "unit_invalid"
  | "target_retired"
  | "target_identity_changed"
  | "target_distinct_recorded";

export interface SuggestionCandidate {
  concept_id: number;
  rank: number;
  source: "exact_signature" | "bm25" | string;
  signature: string;
  target: string;
}

export interface SuggestionItem {
  id: number;
  run_id: number;
  ordinal: number;
  unit_id: number;
  entry_id: number;
  source_extraction_id: number;
  outcome: SuggestionOutcome;
  suggested_concept_id: number | null;
  reason: string;
  candidates: SuggestionCandidate[];
  state: SuggestionItemState;
  stale_reasons: SuggestionStaleReason[];
  current_concept_id: number | null;
  // Historical attribution; still_current says whether link_id is the unit's
  // CURRENT SAME now.
  confirmation: { id: number; link_id: number; created_at: string; still_current: boolean } | null;
  unit: ReviewableUnit | null;
  created_at: string;
}

export interface SuggestionRun {
  id: number;
  operation_id: string;
  status: "completed" | "failed";
  failure_code: "provider_timeout" | "provider_unavailable" | "invalid_output" | null;
  generator: string;
  candidate_policy: string;
  candidate_limit: number;
  provider_called: boolean;
  unit_ids: number[];
  item_count: number;
  suggested_count: number;
  created_at: string;
  items?: SuggestionItem[];
}

export interface SuggestionLimits {
  max_units: number;
  candidates_per_unit: number;
  member_examples: number;
  max_unit_text_chars: number;
  max_concept_text_chars: number;
  max_reason_chars: number;
}

export interface SuggestionOverview {
  enabled: boolean;
  generator: string | null;
  candidate_policy: string;
  limits: SuggestionLimits;
  runs: SuggestionRun[];
}

export interface SuggestionConfirmResult {
  item: SuggestionItem;
  link: UnitConceptLink;
  replayed: boolean;
}
