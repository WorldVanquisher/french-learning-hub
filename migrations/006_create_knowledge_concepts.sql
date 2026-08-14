-- Migration 006: knowledge concept resolution (milestone 10.5).
--
-- Milestone 10 made KnowledgeUnit the atomic, per-extraction output. It is now
-- reframed as immutable EVIDENCE / candidate representation produced by one
-- extraction. The durable learning identity that future review / mastery /
-- scheduling attaches to is the KnowledgeConcept introduced here. Units are never
-- deleted or rewritten; concepts are resolved from them.
--
-- Design notes:
--   * knowledge_concepts is the durable identity. Its identity is described under
--     an explicit versioned schema (fr_l2_concept_identity_v1): target,
--     pedagogical_intent, scope, and an extensible identity_features map. The
--     canonical signature is a deterministic canonical JSON of the NORMALIZED
--     identity, used for exact-match resolution. A concept's id is stable even
--     when its preferred representation (preferred_unit_id) changes. Canonical /
--     normalized unit text is retrieval evidence and is NOT concept identity.
--   * A partial unique index enforces that at most one ACTIVE concept exists per
--     signature, so creating a concept first checks for an existing active one.
--     Orphaned/retired concepts keep their (possibly colliding) signature for
--     history without blocking a fresh active identity.
--   * unit_concept_links is the append-only resolution history. Each row records
--     the full auditable decision: unit, concept, relation, status, decision
--     source, resolver version, optional score, structured evidence, timestamp. A
--     superseding decision inserts a new row and marks the prior one superseded;
--     rows are never rewritten or deleted. Only relation='same' with
--     status='accepted' is a membership; the at-most-one-accepted-SAME-per-unit
--     invariant is enforced in the repository transaction (SQLite cannot express a
--     partial-unique across two columns' values cleanly enough to rely on alone),
--     backed by the partial unique index below as a second line of defense.
--   * entry_current_extractions stores an EXPLICIT current-extraction selection
--     for an entry (e.g. a human rollback to an older successful extraction). When
--     absent, the current extraction is derived as the entry's latest extraction
--     (MAX(version)); because a failed extraction never persists a row, it can
--     never replace the last successful current extraction. Only units of the
--     current extraction feed the live concept pool; historical extractions and
--     their units remain fully queryable.
--
-- No embeddings, vectors, or ML tables: v1 resolution is exact-signature only.

CREATE TABLE IF NOT EXISTS knowledge_concepts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,

    identity_schema_version TEXT    NOT NULL,

    -- Identity-bearing fields (normalized before storage).
    target                  TEXT    NOT NULL,
    pedagogical_intent      TEXT    NOT NULL,
    scope                   TEXT    NOT NULL DEFAULT '',
    -- Extensible identity features as canonical JSON object of normalized k/v.
    identity_features       TEXT    NOT NULL DEFAULT '{}',
    -- Deterministic canonical signature of the normalized identity.
    signature               TEXT    NOT NULL,

    -- Chosen representation; a separate decision from membership. Nullable.
    preferred_unit_id       INTEGER,

    -- active | orphaned | retired.
    state                   TEXT    NOT NULL,

    created_at              TEXT    NOT NULL,
    updated_at              TEXT    NOT NULL,

    FOREIGN KEY (preferred_unit_id) REFERENCES knowledge_units (id) ON DELETE RESTRICT
);

-- At most one ACTIVE concept per identity signature.
CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_concepts_active_signature
    ON knowledge_concepts (signature)
    WHERE state = 'active';

CREATE INDEX IF NOT EXISTS idx_knowledge_concepts_state
    ON knowledge_concepts (state);

CREATE TABLE IF NOT EXISTS unit_concept_links (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id          INTEGER NOT NULL,
    concept_id       INTEGER NOT NULL,

    -- same | broader | narrower | related. Only 'same' is a membership.
    relation         TEXT    NOT NULL
        CHECK (relation IN ('same', 'broader', 'narrower', 'related')),
    -- accepted | superseded | rejected.
    status           TEXT    NOT NULL
        CHECK (status IN ('accepted', 'superseded', 'rejected')),
    -- resolver:automatic | human.
    decision_source  TEXT    NOT NULL,
    resolver_version TEXT    NOT NULL,
    -- Optional resolver score (NOT a learned probability). Nullable.
    score            REAL,
    -- Structured, auditable evidence JSON. Never secrets or raw provider bodies.
    evidence         TEXT    NOT NULL DEFAULT '{}',

    created_at       TEXT    NOT NULL,

    FOREIGN KEY (unit_id) REFERENCES knowledge_units (id) ON DELETE CASCADE,
    FOREIGN KEY (concept_id) REFERENCES knowledge_concepts (id) ON DELETE CASCADE
);

-- Second line of defense for the membership invariant: at most one accepted SAME
-- membership per unit, regardless of concept.
CREATE UNIQUE INDEX IF NOT EXISTS idx_unit_concept_links_one_accepted_same
    ON unit_concept_links (unit_id)
    WHERE relation = 'same' AND status = 'accepted';

CREATE INDEX IF NOT EXISTS idx_unit_concept_links_unit_id
    ON unit_concept_links (unit_id);
CREATE INDEX IF NOT EXISTS idx_unit_concept_links_concept_id
    ON unit_concept_links (concept_id);

CREATE TABLE IF NOT EXISTS entry_current_extractions (
    -- One explicit selection per entry. Absent => derive latest (MAX version).
    entry_id      INTEGER PRIMARY KEY,
    extraction_id INTEGER NOT NULL,
    updated_at    TEXT    NOT NULL,

    FOREIGN KEY (entry_id) REFERENCES learning_entries (id) ON DELETE CASCADE,
    FOREIGN KEY (extraction_id) REFERENCES knowledge_extractions (id) ON DELETE RESTRICT
);
