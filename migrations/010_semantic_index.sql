-- FLH-040 semantic index bookkeeping. Additive only: no existing table changes.
-- SQLite stays the authority for Concepts; these tables record reusable
-- document embeddings and what this system believes it published to the
-- disposable vector index.

-- Reusable document embeddings. The key covers the document content hash, the
-- representation version, the operator-declared model identity and the vector
-- dimensions, so unchanged documents are reused across runs and restarts and
-- two models' vectors can never be mixed.
CREATE TABLE semantic_embedding_cache (
    content_hash   TEXT    NOT NULL,
    representation TEXT    NOT NULL,
    model_id       TEXT    NOT NULL,
    dimensions     INTEGER NOT NULL CHECK (dimensions > 0),
    vector         BLOB    NOT NULL CHECK (length(vector) = 4 * dimensions),
    created_at     TEXT    NOT NULL,
    PRIMARY KEY (content_hash, representation, model_id, dimensions)
);

-- One row per vector space (collection). state is the outcome of the latest
-- operator run that owns run_id: building (started, not finished or
-- interrupted without cleanup), complete (published and revalidated), or
-- partial (failed, interrupted, or sources changed during the run).
CREATE TABLE semantic_index_collections (
    collection     TEXT    PRIMARY KEY,
    representation TEXT    NOT NULL,
    model_id       TEXT    NOT NULL,
    dimensions     INTEGER NOT NULL CHECK (dimensions > 0),
    state          TEXT    NOT NULL CHECK (state IN ('building', 'complete', 'partial')),
    run_id         TEXT    NOT NULL,
    run_operation  TEXT    NOT NULL CHECK (run_operation IN ('build', 'sync', 'rebuild')),
    run_started_at TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    completed_at   TEXT,
    last_error     TEXT    NOT NULL DEFAULT '',
    UNIQUE (representation, model_id, dimensions)
);

-- Points this system published (after the vector store acknowledged them),
-- with the document hash they were published for. Not a foreign key to
-- knowledge_concepts: index bookkeeping must never constrain the authority.
CREATE TABLE semantic_index_points (
    collection   TEXT    NOT NULL REFERENCES semantic_index_collections (collection) ON DELETE CASCADE,
    concept_id   INTEGER NOT NULL,
    content_hash TEXT    NOT NULL,
    published_at TEXT    NOT NULL,
    PRIMARY KEY (collection, concept_id)
);
