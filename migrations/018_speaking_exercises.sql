-- Speaking v1. Additive only; nothing existing is altered.
--
-- A speaking exercise starts from an authored prompt. The learner records
-- takes in the browser and plays them back there; no audio is ever stored:
--   * speaking_exercises: one per authored prompt (prompt_id);
--   * speaking_takes: numbered takes with audio METADATA only (source, type,
--     size, SHA-256, browser-measured duration). There is no audio column;
--   * speaking_transcriptions: one machine transcript of one take, or a
--     non-secret failure code, with its provenance;
--   * speaking_transcription_requests: one explicit request, inserted BEFORE
--     the provider call (with the SHA-256 of the audio sent) and finished once;
--   * speaking_transcripts: the learner's confirmed transcript versions of a
--     take. A correction is a new version; nothing is overwritten;
--   * speaking_feedback: one report for exactly one confirmed transcript
--     version (validated, server-grounded content, or a failure code);
--   * speaking_feedback_requests: one explicit request, inserted before the
--     call and finished once.
-- The request tables follow the Daily Listening attempt-first rules: no
-- automatic retry, no background work. No row here is an entry, analysis,
-- Concept, annotation, score, pronunciation judgment or mastery judgment.

CREATE TABLE speaking_exercises (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id     TEXT    NOT NULL UNIQUE,     -- e.g. sp-invitation-reponse
    title         TEXT    NOT NULL,
    situation     TEXT    NOT NULL,
    requirements  TEXT    NOT NULL,            -- JSON array of content points
    seconds_min   INTEGER NOT NULL CHECK (seconds_min >= 1),
    seconds_max   INTEGER NOT NULL CHECK (seconds_max >= seconds_min),
    created_at    TEXT    NOT NULL
);

CREATE TABLE speaking_takes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id   INTEGER NOT NULL REFERENCES speaking_exercises(id),
    take_number   INTEGER NOT NULL CHECK (take_number >= 1),
    audio_source  TEXT    NOT NULL CHECK (audio_source IN ('recording', 'file', 'none')),
    audio_mime    TEXT,
    audio_bytes   INTEGER CHECK (audio_bytes IS NULL OR audio_bytes >= 1),
    audio_sha256  TEXT,
    duration_ms   INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 1),
    created_at    TEXT    NOT NULL,
    UNIQUE (exercise_id, take_number),
    CHECK ((audio_source = 'none') = (audio_sha256 IS NULL)),
    CHECK ((audio_sha256 IS NULL) = (audio_mime IS NULL)),
    CHECK ((audio_sha256 IS NULL) = (audio_bytes IS NULL))
);

CREATE TABLE speaking_transcriptions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    take_id       INTEGER NOT NULL REFERENCES speaking_takes(id),
    status        TEXT    NOT NULL CHECK (status IN ('completed', 'failed')),
    failure_code  TEXT    CHECK (failure_code IS NULL OR failure_code IN
                                 ('provider_timeout', 'provider_unavailable', 'invalid_output')),
    transcriber   TEXT    NOT NULL,            -- openai:<model>:speaking_transcription_v1
    text          TEXT,                        -- machine transcript; completed only
    created_at    TEXT    NOT NULL,
    CHECK ((status = 'failed') = (failure_code IS NOT NULL)),
    CHECK ((status = 'completed') = (text IS NOT NULL))
);

CREATE TABLE speaking_transcription_requests (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id      TEXT    NOT NULL UNIQUE,
    exercise_id       INTEGER NOT NULL REFERENCES speaking_exercises(id),
    take_id           INTEGER NOT NULL REFERENCES speaking_takes(id),
    audio_sha256      TEXT    NOT NULL,        -- the audio sent; equals the take's
    after_unknown     INTEGER NOT NULL CHECK (after_unknown IN (0, 1)),
    started_at        TEXT    NOT NULL,
    deadline_at       TEXT    NOT NULL,
    finished_at       TEXT,
    outcome           TEXT    CHECK (outcome IS NULL OR outcome IN ('completed', 'failed', 'unknown')),
    transcription_id  INTEGER UNIQUE REFERENCES speaking_transcriptions(id),
    CHECK ((finished_at IS NULL) = (outcome IS NULL)),
    CHECK (outcome IS NULL OR transcription_id IS NOT NULL)
);

CREATE TABLE speaking_transcripts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    take_id           INTEGER NOT NULL REFERENCES speaking_takes(id),
    version           INTEGER NOT NULL CHECK (version >= 1),
    text              TEXT    NOT NULL,
    word_count        INTEGER NOT NULL,
    origin            TEXT    NOT NULL CHECK (origin IN ('transcription', 'corrected', 'typed')),
    transcription_id  INTEGER REFERENCES speaking_transcriptions(id),
    created_at        TEXT    NOT NULL,
    UNIQUE (take_id, version),
    CHECK (origin != 'transcription' OR transcription_id IS NOT NULL)
);

CREATE TABLE speaking_feedback (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id    INTEGER NOT NULL REFERENCES speaking_exercises(id),
    transcript_id  INTEGER NOT NULL REFERENCES speaking_transcripts(id),
    status         TEXT    NOT NULL CHECK (status IN ('completed', 'failed')),
    failure_code   TEXT    CHECK (failure_code IS NULL OR failure_code IN
                                  ('provider_timeout', 'provider_unavailable', 'invalid_output')),
    generator      TEXT    NOT NULL,           -- openai:<model>:speaking_feedback_v1
    content        TEXT,                       -- validated, grounded JSON; completed only
    created_at     TEXT    NOT NULL,
    CHECK ((status = 'failed') = (failure_code IS NOT NULL)),
    CHECK ((status = 'completed') = (content IS NOT NULL))
);

CREATE TABLE speaking_feedback_requests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id   TEXT    NOT NULL UNIQUE,
    exercise_id    INTEGER NOT NULL REFERENCES speaking_exercises(id),
    transcript_id  INTEGER NOT NULL REFERENCES speaking_transcripts(id),
    after_unknown  INTEGER NOT NULL CHECK (after_unknown IN (0, 1)),
    started_at     TEXT    NOT NULL,
    deadline_at    TEXT    NOT NULL,
    finished_at    TEXT,
    outcome        TEXT    CHECK (outcome IS NULL OR outcome IN ('completed', 'failed', 'unknown')),
    feedback_id    INTEGER UNIQUE REFERENCES speaking_feedback(id),
    CHECK ((finished_at IS NULL) = (outcome IS NULL)),
    CHECK (outcome IS NULL OR feedback_id IS NOT NULL)
);

CREATE INDEX idx_speaking_takes_exercise ON speaking_takes(exercise_id);
CREATE INDEX idx_speaking_transcriptions_take ON speaking_transcriptions(take_id);
CREATE INDEX idx_speaking_transcription_requests_take ON speaking_transcription_requests(take_id);
CREATE INDEX idx_speaking_transcripts_take ON speaking_transcripts(take_id);
CREATE INDEX idx_speaking_feedback_transcript ON speaking_feedback(transcript_id);
CREATE INDEX idx_speaking_feedback_requests_exercise ON speaking_feedback_requests(exercise_id);
