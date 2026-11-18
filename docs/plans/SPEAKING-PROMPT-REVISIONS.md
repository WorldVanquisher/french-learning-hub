# Plan: practising a corrected Speaking prompt (needs a migration)

Status: proposal for the owner. Nothing here is implemented; the migration number is the
owner's to allocate.

## Why the current model cannot hold it

- `speaking_exercises.prompt_id` is `UNIQUE` (migration 018): one exercise per authored prompt.
- An exercise stores the wording it was started with. Takes, transcriptions, transcripts, feedback
  and both request tables point at `speaking_exercises(id)`.
- When the set corrects a prompt, the exercise reads `pack_status: changed`. Since this batch, the
  view also returns the corrected wording as `current_prompt`, read-only.

Two shortcuts were considered and rejected:

- **Rewriting the stored wording in place.** Every earlier take would then point at words the
  learner never answered, and its feedback would be about another prompt.
- **A second exercise row under an invented `prompt_id`** (for example `sp-x~r2`). `prompt_id`
  would stop naming an authored prompt. That breaks prompt lookup, the export's identity and the
  "one exercise per prompt" reads.

A practice of the corrected wording that saves nothing would fit without a migration. It would be
session-only, like Recall Practice. But it could not have a transcript version, feedback or a
notebook record, so it is not offered as the slice.

## Proposed migration (next free number)

Rebuild `speaking_exercises`, following migration 021's method:

- `PRAGMA defer_foreign_keys = ON`;
- copy the rows and the `sqlite_sequence` value;
- create the new table, drop the old one, rename the new one;
- re-insert the rows after the rename;
- keep the IDs and the AUTOINCREMENT counter.

```sql
CREATE TABLE speaking_exercises_new (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id     TEXT    NOT NULL,
    revision      INTEGER NOT NULL CHECK (revision >= 1),   -- 1 for every existing row
    title         TEXT    NOT NULL,
    situation     TEXT    NOT NULL,
    requirements  TEXT    NOT NULL,
    seconds_min   INTEGER NOT NULL CHECK (seconds_min >= 1),
    seconds_max   INTEGER NOT NULL CHECK (seconds_max >= seconds_min),
    created_at    TEXT    NOT NULL,
    UNIQUE (prompt_id, revision)
);
```

**What stays unchanged:**

- No child table changes: every child row keeps its `exercise_id`, which still means "the wording
  this take answered".
- Mistake Notebook sources (`speaking_improvement`) name feedback IDs, so they keep resolving.
- Nothing is backfilled or rewritten.

## Behaviour on top of it

1. **Start.** `POST /speaking/prompts/{id}` keeps replaying the latest revision whose fingerprint
   equals the set. It never creates a revision by itself.
2. **Explicit, previewed revision**, like the listening `script-update`:
   - `POST /speaking/prompts/{id}/revisions` with `from_revision` and `content_fingerprint` (the
     preview the learner saw) appends `revision + 1` with the set's wording;
   - it replays when that revision already exists;
   - it answers `409 stale_preview` otherwise.
3. **Reads.**
   - Every revision is its own exercise, with its own takes and `pack_status`.
   - Prompts list the latest revision.
   - The practice queue keeps one step per exercise, so an older revision with an incomplete take
     stays actionable, labelled with its `pack_status`.
   - `resume` and counts are unchanged.
4. **Export.** `exercise.revision` is added (additive); `content_fingerprint` already
   distinguishes the wordings.
5. **UI.** "Practise the corrected wording" sits in the prompt-correction note, behind a preview
   and a confirmation. Each take line names its revision (today it shows the fingerprint).

## Upgrade and rollback

- **Forward.** Rehearse it like 020 → 021 (`scripts/release/upgrade_021/rehearse.py`):
  - read-only backup;
  - ledger check;
  - first write;
  - row counts and IDs equal before and after;
  - `sqlite_sequence` kept;
  - an existing exercise reads `revision = 1` with the same takes.
- **Rollback.** Restore the pre-upgrade backup (`docs/RELEASE.md`). An older build cannot read a
  database that holds two revisions of one prompt; with one revision per prompt, only the new
  column differs.

## Tests to add with it

- Repository: revision append, replay, `stale_preview`, the unique pair, and IDs kept by the
  rebuild.
- HTTP: the revision route, takes on both revisions, the queue with an incomplete older revision,
  and the export's `revision`.
- Web: preview, then confirm, then the new exercise; earlier takes still on the earlier wording.
