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
