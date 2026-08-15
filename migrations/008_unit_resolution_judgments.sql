-- Migration 008: unit-level INVALID judgment + explicit DISTINCT negative pairs
-- (milestone 10.6 annotation-semantics correctness patch).
--
-- Two distinct annotation gaps are closed here. Both are recorded in NEW,
-- dedicated, append-only tables rather than by abusing unit_concept_links. That
-- table already carries a strict CHECK on relation ('same'|'broader'|'narrower'|
-- 'related') and status, plus a self-referential FK and an inbound FK from
-- unit_concept_memberships; SQLite cannot ALTER a CHECK constraint in place, and
-- rebuilding the table would be an invasive, risky change to immutable resolution
-- history. Small purpose-built tables keep each judgment explicit and auditable.
--
--   (1) UNIT-LEVEL INVALID. unit_concept_links can only express "this unit is not
--       SAME to concept A" (a rejected SAME membership), which requires a current
--       SAME membership to exist. It cannot express "this KnowledgeUnit candidate
--       is itself invalid and should not participate in concept resolution" for a
--       freshly extracted, never-resolved unit. That judgment is recorded in
--       unit_resolution_judgments below. It deliberately does NOT invent a fake
--       concept id and is NOT a ConceptRelation.
--
--       INVALID is distinct from "unresolved": absence of a SAME membership means
--       unresolved (still reviewable); an effective INVALID judgment means the unit
--       was explicitly reviewed and rejected as a candidate. The two must stay
--       distinguishable, so INVALID is positive recorded evidence, never inferred
--       from absence.
--
--       Reversibility: judgments are append-only. A unit can be marked 'invalid'
--       and later 'restored'; the EFFECTIVE invalid state is the latest judgment by
--       (created_at, id). History is never destroyed, so a wrongly-invalidated unit
--       can return to the review queue without losing the audit trail.
--
--   (2) EXPLICIT DISTINCT NEGATIVE PAIRS. When a reviewer is shown candidate concept
--       A and decides the unit is NOT the same learning identity as A, that negative
--       judgment must be recorded explicitly (future ML training needs real negative
--       pairs). It must not be inferred later from the absence of a SAME link, and it
--       is NOT a membership, NOT a relation (broader/narrower/related), and NOT
--       INVALID. It is recorded in unit_concept_distinctions below and never changes
--       SAME membership, so the unit stays reviewable and the reviewer can then pick
--       another concept, create a new one, or mark the unit INVALID.
--
-- No embeddings, vectors, or ML tables: this patch only records human judgments.

-- ---------------------------------------------------------------------------
-- (1) Unit-level INVALID / restored judgments (append-only).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS unit_resolution_judgments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id         INTEGER NOT NULL,

    -- 'invalid'  : the unit is an invalid candidate for concept resolution.
    -- 'restored' : a prior 'invalid' judgment is withdrawn; the unit is valid again.
    -- The effective state is the latest row for the unit by (created_at, id).
    judgment        TEXT    NOT NULL
        CHECK (judgment IN ('invalid', 'restored')),

    -- Who made the judgment. 'human' in this milestone; kept as a column so a future
    -- automatic quality gate could record its own judgments without a schema change.
    decision_source TEXT    NOT NULL,

    -- Optional free-form reviewer note (short). Structured detail lives in evidence.
    note            TEXT    NOT NULL DEFAULT '',
    -- Structured, auditable evidence JSON. Never secrets or raw provider bodies.
    evidence        TEXT    NOT NULL DEFAULT '{}',

    created_at      TEXT    NOT NULL,

    FOREIGN KEY (unit_id) REFERENCES knowledge_units (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_unit_resolution_judgments_unit_id
    ON unit_resolution_judgments (unit_id);

-- ---------------------------------------------------------------------------
-- (2) Explicit DISTINCT negative pairs (append-only).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS unit_concept_distinctions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id          INTEGER NOT NULL,
    concept_id       INTEGER NOT NULL,

    -- 'resolver:automatic' | 'human'. Human in this milestone.
    decision_source  TEXT    NOT NULL,
    resolver_version TEXT    NOT NULL,
    -- Structured, auditable evidence JSON. Never secrets or raw provider bodies.
    evidence         TEXT    NOT NULL DEFAULT '{}',

    created_at       TEXT    NOT NULL,

    FOREIGN KEY (unit_id) REFERENCES knowledge_units (id) ON DELETE CASCADE,
    FOREIGN KEY (concept_id) REFERENCES knowledge_concepts (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_unit_concept_distinctions_unit_id
    ON unit_concept_distinctions (unit_id);
CREATE INDEX IF NOT EXISTS idx_unit_concept_distinctions_concept_id
    ON unit_concept_distinctions (concept_id);
