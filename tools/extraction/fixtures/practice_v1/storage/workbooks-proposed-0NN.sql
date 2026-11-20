-- PINNED COPY, read-only for the extraction lane. Source: the Workbooks lane's sealed handoff
-- workbooks-increment-4/handoff-practice-feed/PRACTICE-STORAGE-DECISION.md (status PROPOSED),
-- the block between its proposed-sql markers. Document SHA-256: 4020c40d91ea5019b4a0479e7163ea3d4816991b37c64637d025ec5bd6882a21
-- Copied on 2026-11-19 for a fixture-only round trip; no migration file exists or is added.

-- 0NN_practice_state.sql (PROPOSED; number allocated by the owner). Additive only.

-- Approvals, and edits of proposed content: one row per learner decision.
-- subject_kind/subject_id name what was decided: an extraction item (k-…) on
-- its source revision, or a notebook practice draft (notebook:entry:N#copy).
-- A decision counts only while item_hash equals the item's current hash (the
-- extraction contract's carry-forward rule); otherwise the item needs review.
CREATE TABLE practice_decisions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key           TEXT    NOT NULL UNIQUE,
    subject_kind            TEXT    NOT NULL CHECK (subject_kind IN ('extraction_item', 'notebook_draft')),
    subject_id              TEXT    NOT NULL,
    source_id               TEXT    NOT NULL,
    source_revision_sha256  TEXT    NOT NULL CHECK (length(source_revision_sha256) = 64),
    item_hash               TEXT    NOT NULL,
    action                  TEXT    NOT NULL CHECK (action IN ('approve', 'reject', 'edit')),
    edited_text             TEXT,
    reason                  TEXT,
    created_at              TEXT    NOT NULL,
    CHECK ((action = 'edit') = (edited_text IS NOT NULL AND length(trim(edited_text)) > 0))
);
CREATE INDEX idx_practice_decisions_subject ON practice_decisions(subject_kind, subject_id, id);

-- Attempts and reveals. A reveal is never an attempt and carries no answer.
-- answer_text is the learner's own text: stored locally, never put in a feed
-- or a packet (the extraction contract excludes attempt texts).
CREATE TABLE practice_attempts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key           TEXT    NOT NULL UNIQUE,
    practice_id             TEXT    NOT NULL,
    source_id               TEXT    NOT NULL,
    source_revision_sha256  TEXT    NOT NULL CHECK (length(source_revision_sha256) = 64),
    action                  TEXT    NOT NULL CHECK (action IN ('attempt', 'reveal')),
    outcome                 TEXT    NOT NULL CHECK (outcome IN ('correct', 'incorrect', 'self_check', 'revealed', 'invalid')),
    self_check              TEXT    CHECK (self_check IS NULL OR self_check IN ('got', 'notyet')),
    answer_text             TEXT,
    local_day               TEXT    NOT NULL,
    zone                    TEXT    NOT NULL,
    created_at              TEXT    NOT NULL,
    CHECK ((action = 'reveal') = (outcome = 'revealed')),
    CHECK (action = 'attempt' OR answer_text IS NULL),
    CHECK (self_check IS NULL OR outcome IN ('self_check', 'revealed'))
);
CREATE INDEX idx_practice_attempts_item ON practice_attempts(practice_id, id);

-- Deferred items (013–014), append-only: a defer hides item_key from Review
-- Today until defer_until_day in zone; an undo row cancels one defer row.
CREATE TABLE review_defers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key    TEXT    NOT NULL UNIQUE,
    item_key         TEXT    NOT NULL,
    action           TEXT    NOT NULL CHECK (action IN ('defer', 'undo')),
    defer_until_day  TEXT,
    zone             TEXT    NOT NULL,
    refers_to        INTEGER REFERENCES review_defers(id),
    created_at       TEXT    NOT NULL,
    CHECK ((action = 'defer') = (defer_until_day IS NOT NULL AND refers_to IS NULL)),
    CHECK ((action = 'undo') = (refers_to IS NOT NULL AND defer_until_day IS NULL))
);
CREATE INDEX idx_review_defers_item ON review_defers(item_key, id);

-- Personal corrections to practise later, append-only: 'add' keeps the
-- learner's corrected wording beside the original and the exact version it
-- corrects; 'retire' (done) refers to one add. Review Today lists open adds.
CREATE TABLE personal_corrections (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key    TEXT    NOT NULL UNIQUE,
    action           TEXT    NOT NULL CHECK (action IN ('add', 'retire')),
    subject_kind     TEXT    CHECK (subject_kind IS NULL OR subject_kind IN ('speaking_transcript', 'writing_draft', 'notebook_entry', 'extraction_item')),
    subject_ref      TEXT,
    subject_version  INTEGER,
    original_text    TEXT,
    corrected_text   TEXT,
    refers_to        INTEGER REFERENCES personal_corrections(id),
    created_at       TEXT    NOT NULL,
    CHECK ((action = 'add') = (subject_kind IS NOT NULL AND subject_ref IS NOT NULL AND corrected_text IS NOT NULL
                               AND length(trim(corrected_text)) > 0 AND refers_to IS NULL)),
    CHECK ((action = 'retire') = (refers_to IS NOT NULL AND corrected_text IS NULL))
);
CREATE INDEX idx_personal_corrections_subject ON personal_corrections(subject_kind, subject_ref, id);
