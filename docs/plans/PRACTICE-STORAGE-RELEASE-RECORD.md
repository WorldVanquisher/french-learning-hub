# Practice storage: decision record for Release (R3-050, 2026-11-20)

**Status: PROPOSED.** No migration file exists, and nothing ships until the owner decides.
Details are in `PRACTICE-STORAGE-DECISION.md` (revision 3) and its one-page sheet.

## What Release would receive, once approved

| Part | Objects | Additive? | Measured on scratch databases |
|---|---|---|---|
| minimum: `practice_attempts` (outcome only), `review_defers` | 2 tables, 4 indexes, 5 append-only triggers | yes: `CREATE` only | the migration took 17 ms on a 50 MB database (100,000 entries and notebook records) |
| optional A: answer text under the learner's retention decision | 1 table, 1 column (`ALTER TABLE … ADD COLUMN`), 3 triggers (one replaced) | yes | included in the 17 ms |
| optional B: amended decisions, personal corrections | 2 tables, 3 indexes, 4 triggers | yes | included in the 17 ms |

## Release checks to add when it lands

1. `migrations/` gains one file. The public-demo artifacts must be rebuilt, because the demo
   requires its ledger to equal the embedded migrations. The new tables must be empty in the
   artifact and absent from the demo allowlist.
2. The upgrade rehearsal (`upgrade_rehearsal.py`) runs the real server against the upgraded
   database: the reads, a revised lesson and the history export are identical.
3. Backup and restore stay `flh-daily.sh backup` / restore. Restoring the pre-upgrade backup is the
   only rollback. It took 0.56 s (copy plus integrity) at 50 MB.

## The data-loss boundary on rollback

Restoring the pre-upgrade backup discards exactly what was written after it. In the rehearsals that
was one capture and its entry, one attempt and one defer, as counted. Nothing written before the
backup is lost. Never run an older image on the newer database.

## Owner decisions that gate it

| Decision | Options |
|---|---|
| The parts | minimum only, plus A, plus B, or page-only |
| The migration number | 022 proposed; no other lane's seal claims it |
| Answer text | kept only while the learner chooses to keep it (A), or never |
| The extraction lane's agreement | needed for B, which moves its JSONL authority |
