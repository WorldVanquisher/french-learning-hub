-- Exam Reading v1. Additive only; nothing existing is altered.
--
-- Source material and exercises are separate records:
--   * reading_lessons: a title, an optional https source link (stored as text,
--     never fetched) and its origin: the learner's own article, or a passage
--     imported from an authored, reviewed pack (pack_passage_id);
--   * reading_passages: versions of the French text, as paragraphs with stable
--     IDs p1..pN. A version is never rewritten; new text is a new version;
--   * reading_exercises: one exercise over one exact passage version, either
--     validated content or a non-secret failure code, with its provenance
--     (authored:<pack> or openai:<model>:reading_exercise_v1);
--   * reading_preparations: one explicit generation attempt, inserted BEFORE
--     the provider call and finished once (the Daily Listening pattern), so a
--     timeout, a lost response or a crash leaves an honest pending or unknown
--     record. There is no automatic retry and no background work.
-- No row here is an entry, analysis, Concept, annotation or mastery judgment.

CREATE TABLE reading_lessons (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT    NOT NULL,
    source_url       TEXT,                     -- https, never fetched
    origin           TEXT    NOT NULL CHECK (origin IN ('learner', 'authored')),
    pack_passage_id  TEXT    UNIQUE,           -- e.g. flh_reading_pack_v1/rd-email-chaudiere
    created_at       TEXT    NOT NULL,
    CHECK ((origin = 'authored') = (pack_passage_id IS NOT NULL))
);

CREATE TABLE reading_passages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id   INTEGER NOT NULL REFERENCES reading_lessons(id),
    version     INTEGER NOT NULL CHECK (version >= 1),
    segments    TEXT    NOT NULL,              -- JSON: [{id: "p1", text}]
    created_at  TEXT    NOT NULL,
    UNIQUE (lesson_id, version)
);

CREATE TABLE reading_exercises (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id     INTEGER NOT NULL REFERENCES reading_lessons(id),
    passage_id    INTEGER NOT NULL REFERENCES reading_passages(id),
    status        TEXT    NOT NULL CHECK (status IN ('completed', 'failed')),
    failure_code  TEXT    CHECK (failure_code IS NULL OR failure_code IN
                                 ('provider_timeout', 'provider_unavailable', 'invalid_output')),
    generator     TEXT    NOT NULL,
    content       TEXT,                        -- validated JSON, completed only
    created_at    TEXT    NOT NULL,
    CHECK ((status = 'failed') = (failure_code IS NOT NULL)),
    CHECK ((status = 'completed') = (content IS NOT NULL))
);

CREATE TABLE reading_preparations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id   TEXT    NOT NULL UNIQUE,
    lesson_id      INTEGER NOT NULL REFERENCES reading_lessons(id),
    passage_id     INTEGER NOT NULL REFERENCES reading_passages(id),
    after_unknown  INTEGER NOT NULL CHECK (after_unknown IN (0, 1)),
    started_at     TEXT    NOT NULL,
    deadline_at    TEXT    NOT NULL,
    finished_at    TEXT,
    outcome        TEXT    CHECK (outcome IS NULL OR outcome IN ('completed', 'failed', 'unknown')),
    exercise_id    INTEGER UNIQUE REFERENCES reading_exercises(id),
    CHECK ((finished_at IS NULL) = (outcome IS NULL)),
    CHECK (outcome IS NULL OR exercise_id IS NOT NULL)
);

CREATE INDEX idx_reading_passages_lesson ON reading_passages(lesson_id);
CREATE INDEX idx_reading_exercises_lesson ON reading_exercises(lesson_id);
CREATE INDEX idx_reading_preparations_lesson ON reading_preparations(lesson_id);
