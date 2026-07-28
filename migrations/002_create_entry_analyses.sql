-- Migration 002: create entry_analyses table.
--
-- Design notes:
--   * A learning entry may have many analyses. Each analysis is an immutable,
--     versioned record of AI-generated metadata; new analyses are appended
--     rather than overwriting older ones or the original entry.
--   * version is unique per entry and increments from 1, giving an audit trail.
--   * The original entry row (learning_entries) is never modified by analysis.
--   * confidence is a probability in [0, 1]; uncertainty is free-form text
--     describing caveats the analyzer wants to preserve.
--   * analyzer records which analyzer produced the record (e.g. "rule-based").

CREATE TABLE IF NOT EXISTS entry_analyses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id     INTEGER NOT NULL,
    version      INTEGER NOT NULL,

    -- Validated AI-generated metadata.
    category     TEXT    NOT NULL,
    explanation  TEXT    NOT NULL,
    confidence   REAL    NOT NULL,
    uncertainty  TEXT    NOT NULL DEFAULT '',
    analyzer     TEXT    NOT NULL,

    created_at   TEXT    NOT NULL,

    FOREIGN KEY (entry_id) REFERENCES learning_entries (id) ON DELETE CASCADE,
    UNIQUE (entry_id, version)
);

CREATE INDEX IF NOT EXISTS idx_entry_analyses_entry_id
    ON entry_analyses (entry_id);
