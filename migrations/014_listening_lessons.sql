-- Exam Listening Lesson v1. Additive only; nothing existing is altered.
--
-- Source material and generated exercises are separate records, and every row
-- is written once and never updated:
--   * listening_materials: a YouTube link (parsed from its text, never fetched)
--     and a title;
--   * listening_transcripts: versions of the learner-supplied French transcript,
--     as numbered segments with a timestamp only where the source supplied one;
--   * listening_exercises: one explicit generation attempt over one transcript
--     version, either the validated content or a non-secret failure code, with
--     the generator provenance.
-- No row here is an entry, analysis, Concept, annotation or mastery judgment.

CREATE TABLE listening_materials (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT    NOT NULL CHECK (length(video_id) = 11),
    source_url  TEXT    NOT NULL,             -- canonical https://www.youtube.com/watch?v=<video_id>
    title       TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);

CREATE TABLE listening_transcripts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id     INTEGER NOT NULL REFERENCES listening_materials(id),
    version         INTEGER NOT NULL CHECK (version >= 1),
    segments        TEXT    NOT NULL,         -- JSON: [{index, start_seconds|null, text}]
    has_timestamps  INTEGER NOT NULL CHECK (has_timestamps IN (0, 1)),
    created_at      TEXT    NOT NULL,
    UNIQUE (material_id, version)
);

CREATE TABLE listening_exercises (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id    INTEGER NOT NULL REFERENCES listening_materials(id),
    transcript_id  INTEGER NOT NULL REFERENCES listening_transcripts(id),
    status         TEXT    NOT NULL CHECK (status IN ('completed', 'failed')),
    failure_code   TEXT    CHECK (failure_code IS NULL OR failure_code IN
                                  ('provider_timeout', 'provider_unavailable', 'invalid_output')),
    generator      TEXT    NOT NULL,          -- e.g. openai:<model>:listening_exercise_v1
    content        TEXT,                      -- validated JSON, completed only
    created_at     TEXT    NOT NULL,
    CHECK ((status = 'failed') = (failure_code IS NOT NULL)),
    CHECK ((status = 'completed') = (content IS NOT NULL))
);

CREATE INDEX idx_listening_transcripts_material ON listening_transcripts(material_id);
CREATE INDEX idx_listening_exercises_material ON listening_exercises(material_id);
