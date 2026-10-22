-- FLH-097 AI-assisted Concept membership suggestions. Additive only.
--
-- Suggestions are ADVISORY evidence, stored apart from every authority:
--   * they never write unit_concept_memberships, unit_concept_links,
--     knowledge_concepts, unit_resolution_judgments, unit_concept_distinctions
--     or admission tables;
--   * only an explicit human confirmation records a human SAME through the
--     existing membership path, and concept_suggestion_confirmations links that
--     SAME event back to the suggestion as provenance.
-- Rows are written once and never updated.

-- One explicit generation request. operation_id is the client's Idempotency-Key
-- (a committed receipt: equivalent replay returns this run, a different payload
-- conflicts). A failed run records only a non-secret failure code.
CREATE TABLE concept_suggestion_runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id       TEXT    NOT NULL UNIQUE,
    request_unit_ids   TEXT    NOT NULL,           -- canonical JSON array, request order
    status             TEXT    NOT NULL CHECK (status IN ('completed', 'failed')),
    failure_code       TEXT    CHECK (failure_code IS NULL OR failure_code IN
                                      ('provider_timeout', 'provider_unavailable', 'invalid_output')),
    generator          TEXT    NOT NULL,           -- e.g. openai:<model>:concept_suggestion_v1
    candidate_policy   TEXT    NOT NULL,           -- concept_suggestion_candidates_v1
    candidate_limit    INTEGER NOT NULL,
    provider_called    INTEGER NOT NULL CHECK (provider_called IN (0, 1)),
    created_at         TEXT    NOT NULL,
    CHECK ((status = 'failed') = (failure_code IS NOT NULL))
);

-- One unit's suggestion inside a completed run, with the source state and the
-- exact candidates that were supplied. suggested_concept_id is set only for the
-- 'suggested' outcome and is always one of the supplied candidates.
CREATE TABLE concept_suggestion_items (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                INTEGER NOT NULL REFERENCES concept_suggestion_runs(id),
    ordinal               INTEGER NOT NULL,
    unit_id               INTEGER NOT NULL REFERENCES knowledge_units(id),
    entry_id              INTEGER NOT NULL REFERENCES learning_entries(id),
    source_extraction_id  INTEGER NOT NULL REFERENCES knowledge_extractions(id),
    candidates            TEXT    NOT NULL,        -- JSON: [{concept_id, rank, source, signature}]
    outcome               TEXT    NOT NULL CHECK (outcome IN
                                  ('suggested', 'no_suitable_candidate', 'uncertain', 'no_candidates')),
    suggested_concept_id  INTEGER REFERENCES knowledge_concepts(id),
    reason                TEXT    NOT NULL,
    created_at            TEXT    NOT NULL,
    UNIQUE (run_id, ordinal),
    UNIQUE (run_id, unit_id),
    CHECK ((outcome = 'suggested') = (suggested_concept_id IS NOT NULL))
);

CREATE INDEX idx_concept_suggestion_items_unit ON concept_suggestion_items(unit_id);

-- A human confirmation of one suggested item: the human SAME event it recorded.
-- UNIQUE(item_id) makes a repeated confirmation a replay, never a second event.
CREATE TABLE concept_suggestion_confirmations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER NOT NULL UNIQUE REFERENCES concept_suggestion_items(id),
    link_id    INTEGER NOT NULL UNIQUE REFERENCES unit_concept_links(id),
    created_at TEXT    NOT NULL
);
