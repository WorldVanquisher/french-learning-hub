-- Migration 001: create learning_entries table.
--
-- Design notes:
--   * Original user data is the source of truth and is stored in NOT NULL
--     columns that the application never overwrites with AI output.
--   * AI-generated metadata (category, explanation, confidence) is kept in
--     separate, nullable columns so it can be added or edited later without
--     touching the original record.
--   * Timestamps are stored as RFC3339 UTC strings for portability.

CREATE TABLE IF NOT EXISTS learning_entries (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Original user data (source of truth, immutable after creation).
    original_input    TEXT    NOT NULL,
    original_context  TEXT    NOT NULL DEFAULT '',

    -- Lifecycle timestamps (RFC3339 UTC).
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,

    -- AI-generated / editable metadata (nullable; never replaces originals).
    category          TEXT,
    explanation       TEXT,
    confidence        REAL
);

CREATE INDEX IF NOT EXISTS idx_learning_entries_created_at
    ON learning_entries (created_at);
