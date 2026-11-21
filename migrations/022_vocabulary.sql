-- 022_vocabulary.sql: the learner's private saved vocabulary (Workbooks). Additive only:
-- two new tables, no existing table, row or index is changed.
--
-- A saved term is a bookmark on a durable Knowledge Concept (its identity, migration 006),
-- never on text: two Concepts with the same wording stay two terms. Saving and removing
-- append rows; nothing is ever updated or deleted, so a removal keeps every example, the
-- Concept, its units and any review history. The public demo holds none of these rows.

-- The learner's decisions: a row per change of state (saved or removed).
CREATE TABLE vocabulary_marks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id  INTEGER NOT NULL REFERENCES knowledge_concepts(id),
    saved       INTEGER NOT NULL CHECK (saved IN (0, 1)),
    created_at  TEXT    NOT NULL
);
CREATE INDEX idx_vocabulary_marks_concept ON vocabulary_marks(concept_id, id);
CREATE TRIGGER vocabulary_marks_no_update BEFORE UPDATE ON vocabulary_marks
BEGIN SELECT RAISE(ABORT, 'vocabulary marks are append-only'); END;
CREATE TRIGGER vocabulary_marks_no_delete BEFORE DELETE ON vocabulary_marks
BEGIN SELECT RAISE(ABORT, 'vocabulary marks are append-only'); END;

-- The source examples attached to a saved Concept: one row per (Concept, unit), with the
-- unit's learner record and the extraction (its source revision) at the time of saving.
CREATE TABLE vocabulary_examples (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id         INTEGER NOT NULL REFERENCES knowledge_concepts(id),
    unit_id            INTEGER NOT NULL REFERENCES knowledge_units(id),
    entry_id           INTEGER NOT NULL REFERENCES learning_entries(id),
    extraction_id      INTEGER NOT NULL REFERENCES knowledge_extractions(id),
    extraction_version INTEGER NOT NULL CHECK (extraction_version >= 1),
    created_at         TEXT    NOT NULL,
    UNIQUE (concept_id, unit_id)
);
CREATE TRIGGER vocabulary_examples_no_update BEFORE UPDATE ON vocabulary_examples
BEGIN SELECT RAISE(ABORT, 'vocabulary examples are append-only'); END;
CREATE TRIGGER vocabulary_examples_no_delete BEFORE DELETE ON vocabulary_examples
BEGIN SELECT RAISE(ABORT, 'vocabulary examples are append-only'); END;
