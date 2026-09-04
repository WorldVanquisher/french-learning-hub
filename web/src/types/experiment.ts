// Wire types for the read-only M11-D quality and M13-A0 retrieval comparison
// reports. These mirror the Go transport DTOs; the dashboard presents them but
// never recomputes dataset validity, experiment population, or retrieval metrics.

export interface AnnotationQualityStatusSummary {
  resolved: number;
  unresolved: number;
  invalid: number;
}

export interface AnnotationQualityAdmissionSummary {
  active: number;
  suppressed: number;
  needs_review: number;
}

export interface AnnotationQualityAuthoritySummary {
  resolved_human_same: number;
  resolved_automatic_same: number;
}

export interface AnnotationQualitySummary {
  total_records: number;
  total_entries: number;
  total_extractions: number;
  total_referenced_concepts: number;
  effective_status: AnnotationQualityStatusSummary;
  admission_effective: AnnotationQualityAdmissionSummary;
  authority: AnnotationQualityAuthoritySummary;
}

export interface AnnotationQualityHumanRelations {
  broader: number;
  narrower: number;
  related: number;
}

export interface AnnotationQualityLabelInventory {
  records_with_any_human_label: number;
  records_without_human_label: number;
  human_same_records: number;
  human_distinct_pairs: number;
  human_relations: AnnotationQualityHumanRelations;
  human_invalid_records: number;
  unlabeled_unresolved_records: number;
  automatic_same_only_records: number;
}

export interface AnnotationQualityDistribution {
  value: string;
  count: number;
}

export interface AnnotationQualityProvenance {
  extractors: AnnotationQualityDistribution[];
  concept_identity_schema_versions: AnnotationQualityDistribution[];
  human_label_resolver_versions: AnnotationQualityDistribution[];
}

export interface AnnotationQualityLeakageRisk {
  entries_with_multiple_records: number;
  max_records_per_entry: number;
  human_same_concepts: number;
  human_same_concepts_with_multiple_units: number;
  human_same_concepts_spanning_multiple_entries: number;
  max_units_per_human_same_concept: number;
}

export interface AnnotationQualityIssue {
  severity: string;
  code: string;
  entry_id: number;
  unit_id: number;
  concept_id: number | null;
  message: string;
}

export interface AnnotationDatasetQualityReport {
  schema_version: string;
  dataset_schema_version: string;
  valid: boolean;
  error_count: number;
  warning_count: number;
  summary: AnnotationQualitySummary;
  label_inventory: AnnotationQualityLabelInventory;
  provenance: AnnotationQualityProvenance;
  leakage_risk: AnnotationQualityLeakageRisk;
  issues: AnnotationQualityIssue[];
}

export type RetrievalEvaluationState = "evaluated" | "blocked_invalid_dataset";
export type RetrievalComparisonRowState = RetrievalEvaluationState | "unavailable";

export interface RetrievalComparisonMetrics {
  recall_at_1: number | null;
  recall_at_3: number | null;
  recall_at_5: number | null;
  mrr: number | null;
}

export interface RetrievalComparisonRow {
  retriever: string;
  state: RetrievalComparisonRowState;
  metrics: RetrievalComparisonMetrics;
}

export interface RetrievalComparisonReport {
  schema_version: string;
  state: RetrievalEvaluationState;
  dataset_valid: boolean;
  candidate_universe: {
    concepts: number;
  };
  evaluation_samples: {
    eligible_samples: number;
  };
  retrievers: RetrievalComparisonRow[];
}
