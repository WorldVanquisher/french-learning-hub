-- Migration 004: create learning_captures table.
--
-- Design notes:
--   * A learning capture is a structured handoff from a French discussion (e.g.
--     ChatGPT) into the backend. It becomes an ordinary learning_entries row and,
--     when an analysis was included, an immutable entry_analyses version-1 row.
--     This table stores only the *import receipt*: it never duplicates the
--     original input, context, category, or explanation, which live in
--     learning_entries and entry_analyses respectively.
--   * capture_id is a client-generated idempotency identifier and is globally
--     unique. Re-submitting the same capture_id with identical content is a
--     no-op replay; with different content it is a conflict (handled in the
--     application/storage layers, not by this schema).
--   * entry_id is UNIQUE: each learning entry is associated with at most one
--     capture, and each capture references exactly one entry. ON DELETE RESTRICT
--     keeps a capture receipt from being silently orphaned.
--   * analysis_id references the imported version-1 analysis when one was
--     provided; it is NULL for a capture without analysis. It is a reference, not
--     a copy, so analysis content is never duplicated here. ON DELETE RESTRICT
--     preserves the receipt's integrity.
--   * content_fingerprint is a SHA-256 over a deterministic canonicalization of
--     the meaningful request content. It supports conflict detection for repeated
--     capture_id submissions and is internal: it is never returned to clients.
--   * created_at is an RFC3339 UTC string, consistent with the other tables.

CREATE TABLE IF NOT EXISTS learning_captures (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id          TEXT    NOT NULL UNIQUE,
    entry_id            INTEGER NOT NULL UNIQUE,
    analysis_id         INTEGER UNIQUE,
    source              TEXT    NOT NULL,
    schema_version      TEXT    NOT NULL,
    discussion_summary  TEXT    NOT NULL DEFAULT '',
    content_fingerprint TEXT    NOT NULL,
    created_at          TEXT    NOT NULL,

    FOREIGN KEY (entry_id)
        REFERENCES learning_entries (id)
        ON DELETE RESTRICT,
    FOREIGN KEY (analysis_id)
        REFERENCES entry_analyses (id)
        ON DELETE RESTRICT
);
