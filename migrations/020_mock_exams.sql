-- Mock Exam v1 (private workbench). Additive: four new tables, no backfill.
-- A session freezes a copy of every authored question it asks (with a content
-- hash) when it starts; answers are append-only events accepted only before
-- the server-owned deadline; one submission closes a session. Never in the
-- public demo: these tables must be empty in demo artifacts.

CREATE TABLE exam_sessions (
    id                  INTEGER PRIMARY KEY,
    operation_id        TEXT    NOT NULL UNIQUE,              -- the start request's Idempotency-Key
    kind                TEXT    NOT NULL CHECK (kind IN ('exam', 'retry')),
    form_id             TEXT    NOT NULL,
    form_title          TEXT    NOT NULL,
    retry_of_session_id INTEGER REFERENCES exam_sessions(id),
    retry_of_position   INTEGER,
    forms_sha256        TEXT    NOT NULL,                     -- the embedded forms file
    pack_sha256         TEXT    NOT NULL,                     -- the embedded reading pack
    duration_seconds    INTEGER NOT NULL CHECK (duration_seconds > 0),
    started_at          TEXT    NOT NULL,
    deadline_at         TEXT    NOT NULL,
    CHECK ((kind = 'exam' AND retry_of_session_id IS NULL AND retry_of_position IS NULL)
        OR (kind = 'retry' AND retry_of_session_id IS NOT NULL AND retry_of_position >= 1))
);

CREATE TABLE exam_session_items (
    session_id     INTEGER NOT NULL REFERENCES exam_sessions(id),
    position       INTEGER NOT NULL CHECK (position >= 1),
    pack_id        TEXT    NOT NULL,
    passage_id     TEXT    NOT NULL,
    question_id    TEXT    NOT NULL,
    content_json   TEXT    NOT NULL,                          -- the frozen question, choices, key and explanations
    content_sha256 TEXT    NOT NULL,
    PRIMARY KEY (session_id, position)
);

CREATE TABLE exam_answers (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES exam_sessions(id),
    position   INTEGER NOT NULL CHECK (position >= 1),
    choice     INTEGER CHECK (choice IS NULL OR choice >= 0), -- NULL clears the answer
    saved_at   TEXT    NOT NULL
);
CREATE INDEX exam_answers_session ON exam_answers (session_id, position, id);

CREATE TABLE exam_submissions (
    session_id     INTEGER PRIMARY KEY REFERENCES exam_sessions(id),
    answers_json   TEXT    NOT NULL,                          -- final answers by position
    answers_sha256 TEXT    NOT NULL,
    correct        INTEGER NOT NULL CHECK (correct >= 0),
    total          INTEGER NOT NULL CHECK (total >= 1),
    submitted_at   TEXT    NOT NULL
);
