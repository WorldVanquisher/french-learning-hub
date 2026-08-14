-- Migration 007: concept-resolution correctness fixes (milestone 10.5.1).
--
-- Migration 006 introduced the KnowledgeConcept identity layer but conflated
-- several concerns. This migration corrects them WITHOUT editing 006 and without
-- destroying stored history. Five defects are addressed:
--
--   1. Human correction of a wrong SAME link was impossible. A unit's accepted
--      SAME membership was pinned by a partial unique index and by the repository
--      refusing any second accepted SAME. That made a wrong machine/human
--      resolution effectively permanent. We now model CURRENT SAME membership as a
--      separate, mutable, single-row-per-unit projection
--      (unit_concept_memberships) derived from an append-only event log, so a
--      human can move a unit to a different concept while the old decision is kept
--      as history.
--
--   2. Resolution history was not actually immutable: superseding a decision
--      rewrote the old row's status to 'superseded' with UPDATE. History is now
--      append-only. unit_concept_links is a pure event log; a superseding decision
--      inserts a NEW row that references the one it replaces via supersedes_link_id
--      and never rewrites the earlier row. (Legacy 'superseded' rows written by 006
--      are left untouched as historical data.)
--
--   3. Concept support (active/orphaned) was stored in knowledge_concepts.state
--      and could go stale, because support depends on the current extraction,
--      effective admission, and current SAME membership — all of which can change
--      without a write to that concept. Support is now DERIVED at read time. The
--      persisted column records only human LIFECYCLE state (normal | retired).
--
--   4. Concept identity could be released by orphaning: the uniqueness index only
--      applied to state='active', so an orphaned concept's signature could be
--      taken over by a brand-new concept and later collide. A durable identity
--      (identity_schema_version + signature) now belongs to a single concept for
--      as long as it is not retired.
--
--   5. (Enforced in the repository, enabled here.) create-concept + seed SAME is
--      now one transaction; this migration provides the membership projection that
--      the combined operation writes to.
--
-- No embeddings, vectors, or ML tables: v1 resolution remains exact-signature only.

-- ---------------------------------------------------------------------------
-- (2) Append-only event log: stop pretending 'status' is mutable history.
-- ---------------------------------------------------------------------------

-- The 006 partial unique index enforced "one accepted SAME per unit" over the
-- links table itself. That is what made a unit's membership impossible to move
-- (a second accepted SAME row could never be inserted, and the only way 006 had
-- to change it was an UPDATE that rewrote history). Drop it: the invariant now
-- lives on the current-membership projection (one row per unit) below, and the
-- links table is free to accumulate the full accepted/superseding event history.
DROP INDEX IF EXISTS idx_unit_concept_links_one_accepted_same;

-- Provenance for an append-only supersession: a correcting decision points back
-- to the decision it replaces instead of mutating it. NULL for an original
-- decision. Self-referential FK; RESTRICT so a referenced historical row cannot
-- be deleted out from under its successor.
ALTER TABLE unit_concept_links
    ADD COLUMN supersedes_link_id INTEGER
        REFERENCES unit_concept_links (id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_unit_concept_links_supersedes
    ON unit_concept_links (supersedes_link_id);

-- ---------------------------------------------------------------------------
-- (1) & (5) Current SAME membership projection (derived current authority).
-- ---------------------------------------------------------------------------
--
-- Exactly one row per unit (PRIMARY KEY unit_id) names the unit's CURRENT SAME
-- concept and the event-log row that established it. A unit with no row has no
-- current SAME membership (it is reviewable). Reassigning membership updates this
-- row and appends a new event; deleting it (not used yet) would clear membership.
-- This is the single mutable projection the spec allows: historical evidence
-- (unit_concept_links) stays immutable; current authority lives here.
CREATE TABLE IF NOT EXISTS unit_concept_memberships (
    unit_id    INTEGER PRIMARY KEY,
    concept_id INTEGER NOT NULL,
    -- The accepted event-log row currently in force for this unit.
    link_id    INTEGER NOT NULL,
    updated_at TEXT    NOT NULL,

    FOREIGN KEY (unit_id) REFERENCES knowledge_units (id) ON DELETE CASCADE,
    FOREIGN KEY (concept_id) REFERENCES knowledge_concepts (id) ON DELETE CASCADE,
    FOREIGN KEY (link_id) REFERENCES unit_concept_links (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_unit_concept_memberships_concept_id
    ON unit_concept_memberships (concept_id);

-- Backfill the projection from 006 data: for each unit, its most recent accepted
-- SAME link becomes the current membership. (In 006 there was at most one accepted
-- SAME per unit, so MAX(id) simply selects it.)
INSERT OR IGNORE INTO unit_concept_memberships (unit_id, concept_id, link_id, updated_at)
SELECT l.unit_id, l.concept_id, l.id, l.created_at
FROM unit_concept_links l
JOIN (
    SELECT unit_id, MAX(id) AS max_id
    FROM unit_concept_links
    WHERE relation = 'same' AND status = 'accepted'
    GROUP BY unit_id
) latest ON latest.unit_id = l.unit_id AND latest.max_id = l.id;

-- ---------------------------------------------------------------------------
-- (3) & (4) Lifecycle state distinct from derived support; durable identity.
-- ---------------------------------------------------------------------------

-- Human lifecycle state: 'normal' (support is derived) or 'retired' (sticky human
-- decision; the concept keeps its identity/history but is out of the live pool
-- and releases its durable-identity claim). Derived support (supported/orphaned)
-- is NOT stored: it is computed at read time from current extraction + effective
-- admission + current SAME membership.
ALTER TABLE knowledge_concepts
    ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'normal'
        CHECK (lifecycle_state IN ('normal', 'retired'));

-- Carry any 006 human 'retired' decision across to the new column. The 006
-- active/orphaned values were derived support and are intentionally dropped as
-- persisted truth.
UPDATE knowledge_concepts SET lifecycle_state = 'retired' WHERE state = 'retired';

-- Retire the old support-based index (it keyed uniqueness on state='active', which
-- let an orphaned concept's identity be taken over).
DROP INDEX IF EXISTS idx_knowledge_concepts_active_signature;
DROP INDEX IF EXISTS idx_knowledge_concepts_state;

-- Remove the stale-truth column entirely. Support (active/orphaned) is now derived
-- at read time from current extraction + effective admission + current SAME
-- membership, so there is no persisted support value left to drift. Done AFTER the
-- retire backfill above and after dropping every index that referenced it.
ALTER TABLE knowledge_concepts DROP COLUMN state;

-- A durable identity (schema + signature) belongs to a single concept for as long
-- as it is not retired. Orphaning (a derived state) no longer releases it; only an
-- explicit human retire does. This prevents duplicate durable identities.
CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_concepts_durable_identity
    ON knowledge_concepts (identity_schema_version, signature)
    WHERE lifecycle_state != 'retired';

CREATE INDEX IF NOT EXISTS idx_knowledge_concepts_lifecycle
    ON knowledge_concepts (lifecycle_state);
