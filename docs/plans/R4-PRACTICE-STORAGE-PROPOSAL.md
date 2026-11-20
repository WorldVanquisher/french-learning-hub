# R4 practice storage proposal: scheduling and retention (PROPOSED, no migration allocated)

**Status:** a proposal for the owner. `migrations/` is unchanged; the SQL below runs only in scratch
databases (`scripts/validation/review_today_r4/storage_r4.py`). It builds on
`PRACTICE-STORAGE-DECISION.md` revision 3 and `PRACTICE-STORAGE-RELEASE-RECORD.md`.

## Current persistence compared with the proposal (R4-WB-036)

| Need | Persisted today | R3 proposal | This proposal |
|---|---|---|---|
| A retry decision on a notebook record | `mistake_retry_marks`, append-only | unchanged | unchanged |
| The outcome of a Review Today item (completed or missed) | nothing: the next-review recommendation shows both outcomes instead | none: `practice_attempts` accepts feed practice IDs (`p-…`) only | `review_outcomes`: one row per learner-reported outcome, linked to the notebook record or the Speaking exercise it is about |
| A defer to a later day | nothing: "Hide for this visit" is page memory | `review_defers` (item key, one undo per defer) | reused as is |
| Free-text retention | never stored | optional part A: `practice_text_retention` plus a column | reused as is (the decision table only; no text column here) |
| Feed practice attempts | nothing (page state) | `practice_attempts` | out of scope here: R3 minimum |

**Links:**
- A `review_outcomes` row names its record by a foreign key: `entry_id` to `learning_entries`, or
  `speaking_exercise_id` to `speaking_exercises`, never by parsing a key.
- A CHECK ties `item_key` to that foreign key, so the two cannot disagree.

## Forward SQL (R4-WB-037, R4-WB-040)

<!-- r4-forward:start -->
```sql
-- 0NN_review_outcomes.sql (number allocated by the owner). Additive only.
CREATE TABLE review_outcomes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key        TEXT    NOT NULL UNIQUE,
    item_key             TEXT    NOT NULL,
    entry_id             INTEGER REFERENCES learning_entries(id),
    speaking_exercise_id INTEGER REFERENCES speaking_exercises(id),
    outcome              TEXT    NOT NULL CHECK (outcome IN ('completed', 'missed')),
    local_day            TEXT    NOT NULL CHECK (local_day GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    zone                 TEXT    NOT NULL,
    created_at           TEXT    NOT NULL,
    CHECK ((entry_id IS NOT NULL AND speaking_exercise_id IS NULL AND item_key = 'notebook:entry:' || entry_id)
        OR (speaking_exercise_id IS NOT NULL AND entry_id IS NULL AND item_key = 'speaking:exercise:' || speaking_exercise_id))
);
CREATE INDEX idx_review_outcomes_item ON review_outcomes(item_key, id);
CREATE INDEX idx_review_outcomes_day ON review_outcomes(local_day);
CREATE TRIGGER review_outcomes_no_update BEFORE UPDATE ON review_outcomes
BEGIN SELECT RAISE(ABORT, 'review outcomes are append-only'); END;
CREATE TRIGGER review_outcomes_no_delete BEFORE DELETE ON review_outcomes
BEGIN SELECT RAISE(ABORT, 'review outcomes are append-only'); END;

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
CREATE UNIQUE INDEX idx_review_defers_one_undo ON review_defers(refers_to) WHERE action = 'undo';
CREATE TRIGGER review_defers_no_change BEFORE UPDATE ON review_defers
BEGIN SELECT RAISE(ABORT, 'review defers are append-only'); END;
CREATE TRIGGER review_defers_no_delete BEFORE DELETE ON review_defers
BEGIN SELECT RAISE(ABORT, 'review defers are append-only'); END;

CREATE TABLE practice_text_retention (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key TEXT    NOT NULL UNIQUE,
    keep_text     INTEGER NOT NULL CHECK (keep_text IN (0, 1)),
    zone          TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);
CREATE TRIGGER practice_text_retention_append_only BEFORE UPDATE ON practice_text_retention
BEGIN SELECT RAISE(ABORT, 'retention decisions are append-only'); END;
CREATE TRIGGER practice_text_retention_no_delete BEFORE DELETE ON practice_text_retention
BEGIN SELECT RAISE(ABORT, 'retention decisions are append-only'); END;
```
<!-- r4-forward:end -->

## Rollback SQL (R4-WB-039, R4-WB-040)

This drops only what the forward SQL added, in reverse order. It is the rollback for a database
upgraded in place, when no backup is restored. Restoring the pre-upgrade backup stays the
documented rollback; both give the same original tables back (`storage_r4.py`).

<!-- r4-rollback:start -->
```sql
DROP TRIGGER IF EXISTS practice_text_retention_no_delete;
DROP TRIGGER IF EXISTS practice_text_retention_append_only;
DROP TABLE IF EXISTS practice_text_retention;
DROP TRIGGER IF EXISTS review_defers_no_delete;
DROP TRIGGER IF EXISTS review_defers_no_change;
DROP INDEX IF EXISTS idx_review_defers_one_undo;
DROP INDEX IF EXISTS idx_review_defers_item;
DROP TABLE IF EXISTS review_defers;
DROP TRIGGER IF EXISTS review_outcomes_no_delete;
DROP TRIGGER IF EXISTS review_outcomes_no_update;
DROP INDEX IF EXISTS idx_review_outcomes_day;
DROP INDEX IF EXISTS idx_review_outcomes_item;
DROP TABLE IF EXISTS review_outcomes;
```
<!-- r4-rollback:end -->

## What cannot survive a rollback (R4-WB-039)

Every row of the three new tables:
- the outcomes the learner reported;
- their defers and undos;
- their retention decisions.

These are counted before the rollback (`storage_r4.py` prints them). Nothing in the original tables
changes: their digests equal the pre-upgrade inventory.

An older binary (the start tree's server) also starts on the upgraded database, because no
migration is recorded, and reads it identically. Running it there is still not a rollback: the new
tables would stay unread.

## Owner decisions reserved (R4-WB-074)

1. Whether outcomes are stored at all. The page shows both outcomes without storing either.
2. The migration number.
3. Whether a defer persists across visits (today: page memory only).
4. Whether a retention decision may later allow kept answer text (R3 optional A's column), and its
   erase path.
