-- Authored listening scripts. 018-020 are reserved for the private stack
-- (Speaking, Mistake Notebook, Mock Exam), so this is 021.
--
-- listening_materials gains a source kind:
--   * 'youtube': every existing row and every new link or pulled video. The
--     video ID and canonical link stay required, exactly as in 014;
--   * 'authored_script': a script imported from the embedded pack
--     (internal/listening/pack). It has NO video ID and NO link: the CHECK below
--     makes a fabricated one impossible. pack_script_id names the script once.
-- Its lines are an ordinary transcript version (no timestamps) and its authored
-- questions an ordinary completed exercise (generator
-- authored:flh_listening_script_pack_v1), so transcripts, exercises,
-- preparations, playlist items and notifications are unchanged. An authored
-- script is never a playlist item, so pulls never select or announce it.
--
-- SQLite cannot relax NOT NULL in place, so the table is rebuilt inside this
-- migration's transaction with foreign keys ON. Order matters: the parent rows
-- are re-inserted AFTER the rebuilt table takes the old name, which resolves
-- the deferred foreign-key counts of the four child tables (transcripts,
-- exercises, playlist items, preparations) before commit. IDs and the
-- AUTOINCREMENT counter are kept, so no material ID is ever reused. Nothing is
-- backfilled or deleted; any failure rolls the whole migration back.

PRAGMA defer_foreign_keys = ON;

CREATE TABLE listening_materials_021_rows AS
    SELECT id, video_id, source_url, title, created_at FROM listening_materials;
CREATE TABLE listening_materials_021_seq AS
    SELECT seq FROM sqlite_sequence WHERE name = 'listening_materials';

CREATE TABLE listening_materials_021 (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind     TEXT    NOT NULL CHECK (source_kind IN ('youtube', 'authored_script')),
    video_id        TEXT    CHECK (video_id IS NULL OR length(video_id) = 11),
    source_url      TEXT,                     -- youtube only: canonical https://www.youtube.com/watch?v=<video_id>
    pack_script_id  TEXT    UNIQUE,           -- authored only: flh_listening_script_pack_v1/<script id>
    title           TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    CHECK ((source_kind = 'youtube' AND video_id IS NOT NULL AND source_url IS NOT NULL AND pack_script_id IS NULL)
        OR (source_kind = 'authored_script' AND video_id IS NULL AND source_url IS NULL AND pack_script_id IS NOT NULL))
);

DROP TABLE listening_materials;
ALTER TABLE listening_materials_021 RENAME TO listening_materials;

INSERT INTO listening_materials (id, source_kind, video_id, source_url, pack_script_id, title, created_at)
    SELECT id, 'youtube', video_id, source_url, NULL, title, created_at
    FROM listening_materials_021_rows ORDER BY id;

-- Keep the AUTOINCREMENT high-water mark (never lower it).
UPDATE sqlite_sequence
    SET seq = MAX(seq, (SELECT seq FROM listening_materials_021_seq))
    WHERE name = 'listening_materials' AND EXISTS (SELECT 1 FROM listening_materials_021_seq);
INSERT INTO sqlite_sequence (name, seq)
    SELECT 'listening_materials', seq FROM listening_materials_021_seq
    WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'listening_materials');

DROP TABLE listening_materials_021_rows;
DROP TABLE listening_materials_021_seq;
