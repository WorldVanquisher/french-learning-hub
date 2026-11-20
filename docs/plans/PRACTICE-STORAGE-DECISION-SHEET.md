# Decision sheet: practice storage (one page, for the owner)

**Status: PROPOSED, revision 2 (2026-11-19).** No migration file exists. Until the owner
decides, every practice action stays in the page and says it disappears on reload. Details and
evidence: `PRACTICE-STORAGE-DECISION.md`.

## Scope of the migration

- **One additive file**, `0NN_practice_state.sql`. It holds:
  - four append-only tables: `practice_decisions`, `practice_attempts`, `review_defers`,
    `personal_corrections`;
  - six indexes (two of them unique partial indexes);
  - two triggers: an undo must name a defer of the same item, and a retire must name an add.
- **Unchanged:** no existing table, row, constraint or index changes. There is no rebuild and no
  backfill.
- **Checked** on scratch databases built exactly like the server's:
  - exactly 12 objects are added;
  - every existing object and row is byte-identical;
  - integrity and foreign keys are clean.
- **Out of scope:**
  - the extraction lane's own JSONL (that needs their agreement);
  - a scheduling algorithm (only `defer_until_day` is stored);
  - any change to Concept support. An approval here never moves Concept authority.

## Numbering

- `migrations/` ends at `021_listening_authored_scripts.sql`. Migrations 018–020 were allocated to
  the private stack and are in use.
- No lane's latest seal proposes a 022. The integration rehearsal of 2026-11-19 lists none.
- **Proposal:** `022_practice_state.sql`. The owner confirms the number at integration time,
  because another lane may claim 022 first.

## Forward

- The file and its ledger row run in one transaction, as `internal/storage/sqlite/db.go` applies
  every migration.
- The current server (without the file) starts on an upgraded database and reads it identically.
  This was rehearsed with a revised listening exercise, Review Today, the learning week, the
  notebook and the history export.

## Rollback and its exact data-loss boundary (RELEASE.md: restore, never downgrade in place)

Restore the backup taken just before the upgrade, then start the previous image.

**Lost:** everything written after that backup:
- every row of the four tables;
- every other write in that window. In the rehearsal: one capture and its entry, one attempt and
  one defer, exactly.

**Kept:** everything before the backup, row for row, including a lesson already at revision 2 and
the history export made before the upgrade.

**Not a rollback path:**
- Running an older image on the newer database would start, because it ignores the tables. The
  documented rule stays: restore instead.
- Dropping the tables by hand is not supported.

**Public demo:**
- The artifact ledger must equal the embedded migrations, so the demo artifacts are rebuilt after
  the merge.
- The four tables must be empty and are not allowlisted. The public-boundary check shows that no
  practice code or route reaches the public package today.

## Decisions for the owner

1. **Option B** (these tables) or stay page-only.
2. **The number** (022 proposed).
3. **Answer text.** Default: never stored; kept only with an explicit per-attempt opt-in
   (`answer_kept = 1`). The alternative is never storing it at all.
4. **The extraction lane.** Whether its decision and attempt JSONL moves into these tables. That
   is their contract and needs their agreement.
5. **After the merge:** who rebuilds the public-demo artifacts (the release lane).

## Blocked until then (migration-dependent)

The following cannot be implemented until decisions 1–2 are made:
- persisting a practice visit;
- "Not today" across reloads (013–014 of the earlier batch);
- stored personal corrections as due practice;
- weekly counts that survive a reload;
- including practice in the portable history export.
