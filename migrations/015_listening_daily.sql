-- Daily Listening: pull, prepare and notify. Additive only; 014 is unchanged.
--
-- Operational receipts for the daily delivery. Each attempt row is inserted
-- BEFORE the outside call it describes and finished exactly once afterwards
-- (an UPDATE guarded by "finished_at IS NULL"), so a crash, a timeout or a lost
-- response leaves a visible pending or unknown record instead of nothing. Rows
-- are never deleted, and a finished row is never changed again.
--   * listening_pull_runs: one pull (workbench button or operator command);
--   * listening_playlist_items: each video ID seen in the playlist, once (the
--     deduplication key) and the material it created or matched;
--   * listening_preparations: one exercise preparation attempt, explicit or
--     made by a pull (at most one pull attempt per local day);
--   * listening_notifications: one notification send attempt.
-- No transcript is ever fetched: a pulled video waits for the learner's own.

CREATE TABLE listening_pull_runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id       TEXT    NOT NULL UNIQUE,      -- caller's key (button) or generated (command)
    trigger            TEXT    NOT NULL CHECK (trigger IN ('manual', 'scheduled')),
    status             TEXT    NOT NULL CHECK (status IN ('running', 'finished', 'interrupted')),
    started_at         TEXT    NOT NULL,
    lease_expires_at   TEXT    NOT NULL,             -- fixed-width UTC, compared as text
    finished_at        TEXT,
    source_outcome     TEXT    CHECK (source_outcome IS NULL OR source_outcome IN ('disabled', 'ok', 'failed')),
    source_failure     TEXT    CHECK (source_failure IS NULL OR source_failure IN
                                      ('source_timeout', 'source_unavailable', 'source_refused', 'invalid_response')),
    items_seen         INTEGER NOT NULL DEFAULT 0,
    materials_created  INTEGER NOT NULL DEFAULT 0,
    items_known        INTEGER NOT NULL DEFAULT 0,
    items_skipped      INTEGER NOT NULL DEFAULT 0,
    prepare_outcome    TEXT    CHECK (prepare_outcome IS NULL OR prepare_outcome IN
                                      ('disabled', 'nothing_to_prepare', 'daily_cap_reached', 'completed', 'failed', 'unknown')),
    notify_outcome     TEXT    CHECK (notify_outcome IS NULL OR notify_outcome IN
                                      ('disabled', 'nothing_ready', 'sent', 'failed', 'unknown')),
    CHECK ((status = 'running') = (finished_at IS NULL)),
    CHECK (source_failure IS NULL OR source_outcome = 'failed'),
    CHECK (source_outcome IS NOT 'failed' OR source_failure IS NOT NULL),
    CHECK (status != 'finished' OR (source_outcome IS NOT NULL AND prepare_outcome IS NOT NULL AND notify_outcome IS NOT NULL))
);

-- At most one running pull. A run whose lease expired is marked interrupted by
-- the next pull before it starts.
CREATE UNIQUE INDEX ux_listening_pull_runs_running ON listening_pull_runs(status) WHERE status = 'running';

CREATE TABLE listening_playlist_items (
    video_id          TEXT    PRIMARY KEY CHECK (length(video_id) = 11),
    material_id       INTEGER NOT NULL REFERENCES listening_materials(id),
    playlist_id       TEXT    NOT NULL,
    material_created  INTEGER NOT NULL CHECK (material_created IN (0, 1)), -- 0: matched an existing material
    source_title      TEXT    NOT NULL,              -- official metadata title when first seen
    published_at      TEXT,                          -- official metadata, when given
    pull_run_id       INTEGER NOT NULL REFERENCES listening_pull_runs(id),
    created_at        TEXT    NOT NULL
);

CREATE INDEX idx_listening_playlist_items_material ON listening_playlist_items(material_id);

CREATE TABLE listening_preparations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id   TEXT    NOT NULL UNIQUE,
    material_id    INTEGER NOT NULL REFERENCES listening_materials(id),
    transcript_id  INTEGER NOT NULL REFERENCES listening_transcripts(id),
    trigger        TEXT    NOT NULL CHECK (trigger IN ('explicit', 'pull')),
    pull_run_id    INTEGER REFERENCES listening_pull_runs(id),
    pull_day       TEXT,                             -- YYYY-MM-DD in LISTENING_TIMEZONE, pull only
    after_unknown  INTEGER NOT NULL CHECK (after_unknown IN (0, 1)), -- an explicit retry that acknowledged an unknown outcome
    started_at     TEXT    NOT NULL,
    deadline_at    TEXT    NOT NULL,                 -- unfinished after this: outcome unknown
    finished_at    TEXT,
    outcome        TEXT    CHECK (outcome IS NULL OR outcome IN ('completed', 'failed', 'unknown')),
    exercise_id    INTEGER UNIQUE REFERENCES listening_exercises(id),
    CHECK ((trigger = 'pull') = (pull_run_id IS NOT NULL)),
    CHECK ((trigger = 'pull') = (pull_day IS NOT NULL)),
    CHECK ((finished_at IS NULL) = (outcome IS NULL)),
    CHECK (outcome IS NULL OR exercise_id IS NOT NULL)
);

-- The daily cap: one pull preparation attempt per local day, whatever its outcome.
CREATE UNIQUE INDEX ux_listening_preparations_pull_day ON listening_preparations(pull_day) WHERE trigger = 'pull';
CREATE INDEX idx_listening_preparations_material ON listening_preparations(material_id);

CREATE TABLE listening_notifications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id   TEXT    NOT NULL UNIQUE,
    exercise_id    INTEGER NOT NULL REFERENCES listening_exercises(id),
    channel        TEXT    NOT NULL CHECK (channel IN ('telegram')),
    trigger        TEXT    NOT NULL CHECK (trigger IN ('pull', 'explicit')),
    pull_run_id    INTEGER REFERENCES listening_pull_runs(id),
    after_unknown  INTEGER NOT NULL CHECK (after_unknown IN (0, 1)),
    started_at     TEXT    NOT NULL,
    deadline_at    TEXT    NOT NULL,
    finished_at    TEXT,
    outcome        TEXT    CHECK (outcome IS NULL OR outcome IN ('sent', 'failed', 'unknown')),
    failure_code   TEXT    CHECK (failure_code IS NULL OR failure_code IN ('not_sent', 'refused', 'no_response')),
    CHECK ((trigger = 'pull') = (pull_run_id IS NOT NULL)),
    CHECK ((finished_at IS NULL) = (outcome IS NULL)),
    CHECK (failure_code IS NULL OR outcome IN ('failed', 'unknown')),
    CHECK (outcome IS NULL OR outcome = 'sent' OR failure_code IS NOT NULL)
);

-- A pull announces an exercise at most once; only an explicit request sends again.
CREATE UNIQUE INDEX ux_listening_notifications_pull ON listening_notifications(exercise_id) WHERE trigger = 'pull';
CREATE INDEX idx_listening_notifications_exercise ON listening_notifications(exercise_id);
