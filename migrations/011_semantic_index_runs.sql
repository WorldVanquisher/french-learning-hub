-- FLH-042 semantic index run consistency. Additive only.
--
-- Every indexing run writes a private physical Qdrant collection and publishes
-- it with one compare-and-set on semantic_index_spaces, guarded by a lease. The
-- FLH-040 tables semantic_index_collections and semantic_index_points are left
-- in place but are no longer read or written; semantic_embedding_cache is still
-- the reusable embedding cache.

-- One row per vector space (representation, model identity, dimensions).
-- lease_*      : the run currently allowed to work on the space (serialization).
-- published_*  : the physical collection search reads; changed only by the
--                lease holder in one transaction.
-- last_run_*   : outcome of the latest run that still owned the space when it
--                finished. This is run history, not verified index health.
CREATE TABLE semantic_index_spaces (
    space                 TEXT    PRIMARY KEY,
    representation        TEXT    NOT NULL,
    model_id              TEXT    NOT NULL,
    dimensions            INTEGER NOT NULL CHECK (dimensions > 0),
    lease_run_id          TEXT,
    lease_operation       TEXT,
    lease_started_at      TEXT,
    lease_expires_at      TEXT,
    published_collection  TEXT,
    published_run_id      TEXT,
    published_at          TEXT,
    last_run_id           TEXT,
    last_run_operation    TEXT,
    last_run_outcome      TEXT CHECK (last_run_outcome IN
                              ('published', 'verified_unchanged', 'failed', 'interrupted', 'sources_changed')),
    last_run_started_at   TEXT,
    last_run_finished_at  TEXT,
    last_error            TEXT    NOT NULL DEFAULT '',
    UNIQUE (representation, model_id, dimensions)
);

-- Every physical collection a run created (the row is written before the
-- Qdrant collection, so no task-created collection is ever unrecorded).
CREATE TABLE semantic_index_physical_collections (
    collection  TEXT PRIMARY KEY,
    space       TEXT NOT NULL REFERENCES semantic_index_spaces (space) ON DELETE CASCADE,
    run_id      TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('writing', 'published', 'retired', 'abandoned')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- What a run wrote into its own physical collection (after Qdrant acknowledged
-- each batch). Rows are keyed by that collection, so no run can touch another
-- run's manifest.
CREATE TABLE semantic_index_manifest (
    collection   TEXT    NOT NULL REFERENCES semantic_index_physical_collections (collection) ON DELETE CASCADE,
    concept_id   INTEGER NOT NULL,
    content_hash TEXT    NOT NULL,
    PRIMARY KEY (collection, concept_id)
);
