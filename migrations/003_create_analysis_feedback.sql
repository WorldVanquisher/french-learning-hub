-- Migration 003: create analysis_feedback table.
--
-- Design notes:
--   * Feedback is immutable human judgment about a single analysis. Records are
--     appended, never updated, so the full history of accept/correct/reject
--     decisions is preserved.
--   * Each row references exactly one entry_analyses row. The original entry and
--     the analysis are never modified when feedback is added.
--   * status is one of: accepted, corrected, rejected (enforced by CHECK and by
--     application-layer validation).
--   * corrected_category and corrected_explanation carry the human's improved
--     metadata; they are only populated (and required) when status = corrected.
--     They never overwrite the analysis columns.
--   * user_note is optional free-form commentary.

CREATE TABLE IF NOT EXISTS analysis_feedback (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id           INTEGER NOT NULL,

    status                TEXT    NOT NULL
        CHECK (status IN ('accepted', 'corrected', 'rejected')),

    -- Populated only when status = 'corrected'.
    corrected_category    TEXT,
    corrected_explanation TEXT,

    -- Optional free-form human note.
    user_note             TEXT    NOT NULL DEFAULT '',

    created_at            TEXT    NOT NULL,

    FOREIGN KEY (analysis_id) REFERENCES entry_analyses (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_analysis_feedback_analysis_id
    ON analysis_feedback (analysis_id);
