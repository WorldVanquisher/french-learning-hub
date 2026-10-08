// Wire types mirroring the Go transport DTOs for learning records
// (internal/transport/http/handler.go). Keep them in sync with the Go structs.
// The frontend displays these backend-owned values; it never derives a record's
// state or effective interpretation itself.

// The inventory state of a learning entry, derived by the backend from its latest
// analysis and that analysis's latest feedback.
export type LearningRecordState = "unanalyzed" | "unreviewed" | "accepted" | "corrected" | "rejected";

export const LEARNING_RECORD_STATES: readonly LearningRecordState[] = [
  "unanalyzed",
  "unreviewed",
  "accepted",
  "corrected",
  "rejected",
];

// A category/explanation pair, used for both the original and effective values.
export interface AnalysisValues {
  category: string;
  explanation: string;
}

// One row of GET /learning-records. Analysis fields are null when the entry has
// no analysis; `effective` is also null when the latest analysis was rejected.
export interface LearningRecord {
  entry_id: number;
  original_input: string;
  original_context: string;
  entry_created_at: string;
  state: LearningRecordState;
  analysis_id: number | null;
  analysis_version: number | null;
  analyzer: string | null;
  confidence: number | null;
  uncertainty: string | null;
  analysis_created_at: string | null;
  original: AnalysisValues | null;
  effective: AnalysisValues | null;
  feedback_id: number | null;
}

// One page of GET /learning-records. `next_before_entry_id` is the cursor for the
// next (older) page, or null when this page reached the end.
export interface LearningRecordPage {
  records: LearningRecord[];
  next_before_entry_id: number | null;
}

// GET /entries/{id}: the learner-authored source record only.
export interface Entry {
  id: number;
  original_input: string;
  original_context: string;
  created_at: string;
  updated_at: string;
}

// One immutable, versioned analysis from GET /entries/{id}/analyses.
export interface Analysis {
  id: number;
  entry_id: number;
  version: number;
  category: string;
  explanation: string;
  confidence: number;
  uncertainty: string;
  analyzer: string;
  created_at: string;
}

export type AnalysisResolution = "unreviewed" | "accepted" | "corrected" | "rejected";

// GET /analyses/{id}/effective: the backend-resolved interpretation of one
// analysis. `effective` is null for a rejected analysis (no current
// interpretation); `feedback_id` is null for an unreviewed analysis.
export interface EffectiveAnalysis {
  analysis_id: number;
  entry_id: number;
  version: number;
  original: AnalysisValues;
  effective: AnalysisValues | null;
  resolution: AnalysisResolution;
  feedback_id: number | null;
}

// ---- capture import (POST /captures, GET /captures/{capture_id}) ----

// The POST /captures result. `created` is false for an idempotent replay of
// identical content (HTTP 200); `analysis_id` is null when the capture carried no
// analysis.
export interface CaptureResult {
  capture_id: string;
  entry_id: number;
  analysis_id: number | null;
  created: boolean;
}

// GET /captures/{capture_id}: the stored receipt (references and metadata only).
export interface CaptureReceipt {
  capture_id: string;
  schema_version: string;
  source: string;
  entry_id: number;
  analysis_id: number | null;
  discussion_summary: string;
  created_at: string;
}

// ---- knowledge extraction (POST/GET /entries/{id}/extractions) ----

export interface AdmissionOverride {
  id: number;
  unit_id: number;
  decision: string;
  reason?: string;
  note?: string;
  created_at: string;
}

// A unit's backend-derived admission: the machine recommendation and the
// effective state after any human override.
export interface UnitAdmission {
  ruleset: string;
  machine_state: string;
  machine_reason: string;
  effective_state: string;
  latest_override: AdmissionOverride | null;
}

export interface ExtractedUnit {
  id: number;
  ordinal: number;
  kind: string;
  canonical: string;
  statement: string;
  example: string | null;
  confidence: number;
  created_at: string;
  admission: UnitAdmission;
}

// One immutable extraction version with the analysis/feedback it was derived
// from. Zero units is a valid successful result.
export interface Extraction {
  id: number;
  entry_id: number;
  version: number;
  source_analysis_id: number;
  source_feedback_id: number | null;
  extractor: string;
  created_at: string;
  units: ExtractedUnit[];
}

// GET /entries/{id}/current-extraction: null when no extraction is current.
export interface CurrentExtraction {
  entry_id: number;
  current_extraction_id: number | null;
}

// ---- human feedback (POST/GET /analyses/{id}/feedback) ----

export type FeedbackStatus = "accepted" | "corrected" | "rejected";

// One immutable feedback record about one analysis. Corrected fields are present
// only for "corrected" feedback, and only the ones the reviewer supplied.
export interface Feedback {
  id: number;
  analysis_id: number;
  status: FeedbackStatus;
  corrected_category?: string;
  corrected_explanation?: string;
  user_note: string;
  created_at: string;
}

// The POST /analyses/{id}/feedback body. Corrected fields are allowed only with
// status "corrected", which needs at least one of them; the server validates.
export interface NewFeedback {
  status: FeedbackStatus;
  corrected_category?: string;
  corrected_explanation?: string;
  user_note?: string;
}

// fr_l2_taxonomy_v1 categories, offered for corrections. The backend exposes no
// taxonomy endpoint, so this mirrors internal/domain/analysis.go; the server still
// validates every value and rejects one it does not know (HTTP 422).
export const FR_L2_TAXONOMY_V1: readonly string[] = [
  "vocabulary",
  "grammar",
  "morphology",
  "orthography",
  "pronunciation",
  "pragmatics",
  "discourse",
  "comprehension",
  "translation",
  "mixed",
  "other",
];
