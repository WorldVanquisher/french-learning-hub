-- Migration 005: create the knowledge-extraction tables.
--
-- This milestone turns one learning interaction (an entry plus its current
-- effective interpretation) into zero or more durable, atomic knowledge units,
-- each carrying a machine admission recommendation and an append-only history of
-- human admission overrides.
--
-- Design notes:
--   * knowledge_extractions is an immutable, per-entry versioned record of one
--     extraction run. version is unique per entry and increments from 1, giving
--     an append-only audit trail (mirrors entry_analyses). source_analysis_id and
--     source_feedback_id record the exact effective-analysis provenance used, so
--     staleness can be DERIVED later by comparison; there is no mutable "stale"
--     flag. A later analysis or feedback never mutates an existing extraction; a
--     re-run appends a new version.
--   * knowledge_units are the atomic units of one extraction. ordinal is assigned
--     deterministically from the extractor's output order and is unique within an
--     extraction. canonical is a stable, concise human label, NOT a database
--     identity: it has no UNIQUE constraint, globally or per entry, because the
--     same label may legitimately recur across interactions.
--   * knowledge_admission_recommendations holds the machine's non-authoritative
--     recommendation from a named, versioned ruleset (knowledge_admission_v1).
--     Exactly one recommendation is written per unit at extraction time, so
--     unit_id is UNIQUE here. The ruleset never rewrites itself; the row is
--     immutable once written.
--   * knowledge_admission_overrides is the append-only history of human
--     decisions. Many overrides may reference one unit; the latest (by created_at,
--     then id) determines the effective admission state. Overrides never mutate or
--     delete the machine recommendation, preserving a full machine-vs-human record.
--   * All timestamps are RFC3339 UTC strings, consistent with the other tables.
--   * ON DELETE CASCADE flows entry -> extraction -> unit -> (recommendation,
--     override): the AI-derived layer is disposable relative to the immutable
--     original entry, matching entry_analyses.

CREATE TABLE IF NOT EXISTS knowledge_extractions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id           INTEGER NOT NULL,
    version            INTEGER NOT NULL,

    -- Provenance of the effective interpretation this extraction was derived
    -- from. source_feedback_id is NULL when the source analysis was unreviewed.
    source_analysis_id INTEGER NOT NULL,
    source_feedback_id INTEGER,

    -- Extractor provenance, e.g. "openai:<model>:knowledge_extraction_v1".
    extractor          TEXT    NOT NULL,

    created_at         TEXT    NOT NULL,

    FOREIGN KEY (entry_id) REFERENCES learning_entries (id) ON DELETE CASCADE,
    FOREIGN KEY (source_analysis_id) REFERENCES entry_analyses (id) ON DELETE RESTRICT,
    FOREIGN KEY (source_feedback_id) REFERENCES analysis_feedback (id) ON DELETE RESTRICT,
    UNIQUE (entry_id, version)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_extractions_entry_id
    ON knowledge_extractions (entry_id);

CREATE TABLE IF NOT EXISTS knowledge_units (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    extraction_id INTEGER NOT NULL,
    ordinal       INTEGER NOT NULL,

    -- Validated knowledge-unit fields. canonical is a label, not an identity, and
    -- is intentionally not unique.
    kind          TEXT    NOT NULL,
    canonical     TEXT    NOT NULL,
    statement     TEXT    NOT NULL,
    example       TEXT,
    confidence    REAL    NOT NULL,

    created_at    TEXT    NOT NULL,

    FOREIGN KEY (extraction_id) REFERENCES knowledge_extractions (id) ON DELETE CASCADE,
    UNIQUE (extraction_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_units_extraction_id
    ON knowledge_units (extraction_id);

CREATE TABLE IF NOT EXISTS knowledge_admission_recommendations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id    INTEGER NOT NULL UNIQUE,

    -- Named, versioned ruleset that produced this recommendation.
    ruleset    TEXT    NOT NULL,
    -- Machine state: active | suppressed | needs_review.
    state      TEXT    NOT NULL,
    -- Stable reason identifier, e.g. default_active | exact_duplicate | low_confidence.
    reason     TEXT    NOT NULL,

    created_at TEXT    NOT NULL,

    FOREIGN KEY (unit_id) REFERENCES knowledge_units (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS knowledge_admission_overrides (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id    INTEGER NOT NULL,

    -- Human decision direction: active | suppressed.
    decision   TEXT    NOT NULL,
    -- Suppression reason (mastered | ignored | other); empty for an activation.
    reason     TEXT    NOT NULL DEFAULT '',
    -- Optional bounded free-form note.
    note       TEXT    NOT NULL DEFAULT '',

    created_at TEXT    NOT NULL,

    FOREIGN KEY (unit_id) REFERENCES knowledge_units (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_knowledge_admission_overrides_unit_id
    ON knowledge_admission_overrides (unit_id);
