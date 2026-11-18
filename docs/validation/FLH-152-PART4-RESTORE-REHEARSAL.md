# FLH-152 part 4: predecessor → read-only restore → revision 2 → rollback (2026-11-17)

This follows `FLH-152-PART3-RESTORE.md`. It is one continuous rehearsal on
**disposable synthetic data only**:
- servers ran on loopback with every provider disabled and no `.env`;
- no container was started and the daily instance was untouched;
- Docker was replaced by a shim that passes only `docker compose … config` (read-only) to the real CLI and records every other call;
- `flh-daily.sh` ran in its isolated mode (own project and image name);
- the "container" was the server binary, started only after the wrapper asked Compose to start it.

## Inputs

- **Predecessor build:** the pre-revision build `c53b42c`. It still runs, so no substitute was needed.
- **Build under test, and the capture CLI:** both from this tree.
- **Predecessor database:** the old build imported all 12 workbook scripts (revision 1 each). The capture CLI saved one mistake with an attempt:
  - u05 question 4, `part4-u05-q4-rev1`, entry 1, exercise 5;
  - CLI steps: preview, stored (new), then an idempotent replay.
- **Backup:** `flh-daily.sh backup`. The backup was then made read-only: directory 0500, files 0400.

## Restore into an isolated candidate: readiness and the first write

| Path (same read-only source) | Candidate files after copy | Write check | `/readyz` | First write (retry mark) |
|---|---|---|---|---|
| `flh-daily.sh restore` | 0400 (`cp -a`), dir 0700 | FAIL, rc 2, not started | — | — |
| the same copy started anyway | 0400 | — | 200 | **500**, nothing logged |
| after `chmod 600`, `flh-daily.sh start` | 0600 | PASS | 200 | 200, stored |
| RELEASE.md Restore block | 0400 | FAIL, stops before `up` | — | — |
| after `chmod 600` | 0600 | PASS | 200 | 200 |
| RELEASE.md independent check, **as it was** | 0400 | not in the block | **200** | **500** |
| RELEASE.md independent check, **fixed** | 0400 → 0600 | FAIL, `up` skipped; after `chmod 600` PASS | 200 | 200 |

- **Parent directories:** the source's parent (`<data>.backups`, 0700) and the candidate's directory and parent (0700) were writable. The silent failure came only from the file modes copied from the read-only source.
- **Restored candidate:** equal to the predecessor in every revision, mistake and entry id.
- **First write:** added exactly one retry mark.
- **The source after all restores and both rollbacks:**
  - every file is byte-, mode- and mtime-identical;
  - `sha256sum -c SHA256SUMS` passes;
  - the source is still not writable.

## Revision 2, a new attempt, and the old attempt

- **Preview and confirm:** the preview showed revision 1 → 2 (u05-l04 changed). The confirmation appended exactly one transcript version (13) and one exercise (13).
- **New attempt:** the capture CLI in batch mode replayed the old document (entry 1) and created the new one (entry 2, revision 2, its own answer).
- **The old attempt still resolves to revision 1:**
  - The Notebook item matches what the old build showed, apart from `latest_version` and the retry mark.
  - It names exercise 5, question 4 and transcript version 1, with its own answer.
  - Revision 1's read returns the old build's question 4, including its evidence, and the evidence occurs in the lines it cites.
- **Saving either question 4 again:** 409 `source_already_saved`, naming the existing entry.

## Rollback and re-import

- **Binary-only rollback.** The older build ran on a copy of the updated data. This is not the documented procedure: no migration differs.
  - It was ready, and re-importing all 12 scripts answered 200 and wrote nothing.
  - Both attempts resolved on their own revision.
  - Rolled forward, every id and its content were as before.
- **Documented rollback** (DAILY_USE.md: stop, the known-good build, `restore` the pre-update backup):
  - That backup was also a read-only source, so the restore refused at the write check, and passed after `chmod 600`.
  - The active data then equals the pre-update backup.
  - What the rollback removed (u05 revision 2, the new attempt) is unchanged in `<data>.before-restore-…`.
  - The older build re-imported all 12 scripts with 200 and wrote nothing. It showed only the old attempt, and its first write answered 200.
- **Roll forward:**
  - Same preview fingerprint. The re-update was 201, revision 2.
  - The same capture documents: the old one replayed and the new one was created again, because its receipt had been rolled back.
  - Catalog re-import: u05 and unchanged scripts 200, outdated scripts 409 `script_conflict`. The confirmation replayed, and nothing was written.

| State | u05 revisions (version, transcript, exercise) | Mistakes (capture, row, entry, exercise, question) | Retry marks (id/entry/marked) |
|---|---|---|---|
| predecessor, restored candidate | v1 t5 e5 | rev1 r1 e1 x5 q4 | — |
| after the first write = pre-update backup | v1 t5 e5 | rev1 r1 e1 x5 q4 | 1/1/1 |
| revision 2 + new attempt | v1 t5 e5; v2 t13 e13 | rev1 …; rev2 r2 e2 x13 q4 | 1/1/1 |
| rolled back (kept aside: the row above) | v1 t5 e5 | rev1 r1 e1 x5 q4 | 1/1/1 |
| rolled forward, re-updated, re-attempted | v1 t5 e5; v2 t13 e13 | rev1 …; rev2 r2 e2 x13 q4 | 1/1/1; 2/1/0 |

- **Duplicates:** none in any state. Checked per lesson version, per transcript exercise, per pack script, per source reference, per capture id and per capture entry.
- **Loss:** nothing was lost silently. What a rollback removes is kept aside.
- **Id reuse:** ids 13 (transcript, exercise) and 2 (capture, entry) were reused after the rollback, for byte-identical content (row digests without timestamps), because the same steps ran in the same order. Part 3 showed that another order maps reused ids to other content.

## Fixed (confirmed here)

1. **RELEASE.md independent backup check.** Run from a read-only backup, the block as written exited 0 (`up`, `readyz`, `down`). The instance answered `/readyz` 200 but its first write 500.
   - The block now runs `restore_write_check.py` and starts the instance only after it passes.
   - The text says how to fix the copy.
2. **DAILY_USE.md §6 `restore`.** It listed "Recreates the container" as the last step. Since part 3 the wrapper first runs the write check and, when it fails, leaves the service stopped with the restored data in place. The step and what to do are now listed.
3. **AGENTS.md:** the write-check line names the independent check too.

## Observations (not changed)

- **The backup's own sidecars:** a backup made by the Backup block or `flh-daily.sh backup` contains an empty `app.db-wal` and a 32 KiB `app.db-shm`.
  - They are created by the backup's own integrity check: in a writable directory, `sqlite3 -readonly … 'PRAGMA integrity_check;'` creates them. They are not the service's files.
  - `SHA256SUMS` covers them.
  - They are harmless, but read-only with the rest of a read-only backup, and the write check names them.
- **Exit status of the fixed independent check:** it still exits 0 when its write check refuses, because the last command is `down`. That was already true when `curl` failed. The check prints FAIL lines and `up` is skipped.

## Results

| Run | Phase 1 (to restore + first write) | Phase 2 (revision 2 to roll forward) |
|---|---|---|
| independent-check block before the fix | 19/20 (that block FAIL) | — |
| seeded by the predecessor build | 20/20 | 34/34 |
| from the sealed fixture, with the predecessor build | 18/18 | 34/34 |
| from the fixture, predecessor build made unrunnable | 17/17 | 32/32 |

- **Fixture runs vs the seeded run:** the id table is identical.
- **What the unrunnable-predecessor run records:** the substitution, and as NOT RUN:
  - seeding with the old build;
  - the binary-only rollback;
  - the documented rollback with the older build (the newer build was started instead).

## Not verified

- A real container or real Docker volume permissions.
- A source that is read-only because of its mount or owner, rather than its mode bits.
- Another service uid.
- A full disk.
- Any real backup.
