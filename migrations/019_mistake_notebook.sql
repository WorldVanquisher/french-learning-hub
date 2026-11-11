-- Mistake Notebook v1. Additive only; nothing existing is altered or backfilled.
--
--   * learning_capture_sources: the structured source of a capture saved from a
--     skill exercise (an optional source_ref of learning_capture_v1), written in
--     the SAME transaction as the entry and the capture receipt and never
--     changed. It names the exact stored item (an exercise item, a writing
--     correction or a speaking improvement) and, only when the learner chose
--     to include it, their own attempt. One record per source item
--     (UNIQUE type, record_id, item): a second save of the same item is refused.
--     Records saved before this table existed have no row and are never linked
--     by parsing their prose or their capture_id.
--   * mistake_retry_marks: the learner's explicit "mark for retry" and
--     "remove from retry" decisions, append-only; the latest row per entry is
--     the current state. A mark is not a Concept judgment, a score or a
--     schedule.

CREATE TABLE learning_capture_sources (
    capture_row_id  INTEGER PRIMARY KEY REFERENCES learning_captures(id),
    entry_id        INTEGER NOT NULL UNIQUE REFERENCES learning_entries(id),
    source_type     TEXT    NOT NULL CHECK (source_type IN
                            ('listening_item', 'reading_item', 'writing_correction', 'speaking_improvement')),
    record_id       INTEGER NOT NULL CHECK (record_id >= 1),   -- listening/reading exercise, writing/speaking feedback
    item            INTEGER NOT NULL CHECK (item >= 1),        -- 1-based position in that record's content
    attempt         TEXT,                                      -- learner-included answer; listening/reading only
    created_at      TEXT    NOT NULL,
    UNIQUE (source_type, record_id, item)
);

CREATE TABLE mistake_retry_marks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER NOT NULL REFERENCES learning_capture_sources(entry_id),
    marked      INTEGER NOT NULL CHECK (marked IN (0, 1)),
    created_at  TEXT    NOT NULL
);

CREATE INDEX idx_mistake_retry_marks_entry ON mistake_retry_marks(entry_id, id);
