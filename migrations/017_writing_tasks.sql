-- Exam Writing v1. Additive only; nothing existing is altered.
--
-- A writing task and the learner's drafts are separate from any feedback:
--   * writing_tasks: an authored prompt (prompt_id) or the learner's own, with
--     its content points and word range;
--   * writing_drafts: immutable versions of the learner's text. A revision is a
--     new version; nothing overwrites the original;
--   * writing_feedback: one feedback report for exactly one draft version
--     (validated content whose quoted spans the server grounded against that
--     exact text, or a non-secret failure code), with its provenance;
--   * writing_feedback_requests: one explicit request, inserted BEFORE the
--     provider call and finished once (the Daily Listening pattern), so a
--     timeout, a lost response or a crash leaves an honest record. No automatic
--     retry, no background grading.
-- No row here is an entry, analysis, Concept, annotation, score or mastery judgment.

CREATE TABLE writing_tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    prompt        TEXT    NOT NULL,
    requirements  TEXT    NOT NULL,            -- JSON array of content points (may be empty)
    word_min      INTEGER NOT NULL CHECK (word_min >= 1),
    word_max      INTEGER NOT NULL CHECK (word_max >= word_min),
    origin        TEXT    NOT NULL CHECK (origin IN ('learner', 'authored')),
    prompt_id     TEXT    UNIQUE,              -- authored prompt, e.g. wr-invitation-anniversaire
    created_at    TEXT    NOT NULL,
    CHECK ((origin = 'authored') = (prompt_id IS NOT NULL))
);

CREATE TABLE writing_drafts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES writing_tasks(id),
    version     INTEGER NOT NULL CHECK (version >= 1),
    text        TEXT    NOT NULL,
    word_count  INTEGER NOT NULL,
    created_at  TEXT    NOT NULL,
    UNIQUE (task_id, version)
);

CREATE TABLE writing_feedback (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       INTEGER NOT NULL REFERENCES writing_tasks(id),
    draft_id      INTEGER NOT NULL REFERENCES writing_drafts(id),
    status        TEXT    NOT NULL CHECK (status IN ('completed', 'failed')),
    failure_code  TEXT    CHECK (failure_code IS NULL OR failure_code IN
                                 ('provider_timeout', 'provider_unavailable', 'invalid_output')),
    generator     TEXT    NOT NULL,            -- openai:<model>:writing_feedback_v1
    content       TEXT,                        -- validated, grounded JSON; completed only
    created_at    TEXT    NOT NULL,
    CHECK ((status = 'failed') = (failure_code IS NOT NULL)),
    CHECK ((status = 'completed') = (content IS NOT NULL))
);

CREATE TABLE writing_feedback_requests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id   TEXT    NOT NULL UNIQUE,
    task_id        INTEGER NOT NULL REFERENCES writing_tasks(id),
    draft_id       INTEGER NOT NULL REFERENCES writing_drafts(id),
    after_unknown  INTEGER NOT NULL CHECK (after_unknown IN (0, 1)),
    started_at     TEXT    NOT NULL,
    deadline_at    TEXT    NOT NULL,
    finished_at    TEXT,
    outcome        TEXT    CHECK (outcome IS NULL OR outcome IN ('completed', 'failed', 'unknown')),
    feedback_id    INTEGER UNIQUE REFERENCES writing_feedback(id),
    CHECK ((finished_at IS NULL) = (outcome IS NULL)),
    CHECK (outcome IS NULL OR feedback_id IS NOT NULL)
);

CREATE INDEX idx_writing_drafts_task ON writing_drafts(task_id);
CREATE INDEX idx_writing_feedback_draft ON writing_feedback(draft_id);
CREATE INDEX idx_writing_feedback_requests_task ON writing_feedback_requests(task_id);
