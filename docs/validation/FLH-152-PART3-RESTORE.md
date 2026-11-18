# FLH-152 part 3: restoring a read-only backup (2026-11-17)

Items 53–58, recorded apart from the learner-facing work
(`FLH-152-PART3-UX.md`). **Disposable synthetic data only:** copies of the
FLH-152 pre-upgrade backup and of an upgraded, used database, in a scratch
directory; servers on loopback with providers disabled; no `.env`; no Docker
container started; the daily instance and its data untouched.

## 53. Reproduced

A backup made read-only (files 0444) restored with `cp -a` stays read-only.
The server starts, `/readyz` answers 200, the lesson and the preview read
200, and the first supported write (`POST …/script-update`) answers **500
"could not update the listening script"** with **nothing logged**.

## 54. File permissions versus directory permissions

| Case | Server | `/readyz` | Read | First write | `restore_write_check.py` |
|---|---|---|---|---|---|
| A app.db 600, sidecars 600, dir 700 | starts | 200 | 200 | 201 | pass |
| B app.db 444, sidecars 444, dir 700 | starts | 200 | 200 | **500** | fail (file, sidecars) |
| C app.db 444, no sidecars, dir 700 | starts | 200 | 200 | **500** | fail (file) |
| D app.db 600, sidecars 600, dir 500 | starts | 200 | 200 | 201 | fail (directory) |
| E app.db 600, no sidecars, dir 500 | **exits**: "ping sqlite: attempt to write a readonly database" | — | — | — | fail (directory) |
| F app.db 444, no sidecars, dir 500 | **exits** | — | — | — | fail (file, directory) |
| G app.db 600, -shm 444, dir 700 | starts | 200 | 200 | **500** | fail (sidecars) |

The silent failures come from **file** permissions (app.db or a sidecar). A
read-only **directory** is loud when SQLite must create its WAL files (E, F)
and harmless while writable sidecars exist (D); the check still fails D,
because the next start without sidecars would be E.

## 55. Why readiness passes

- `/readyz` is `db.PingContext` (`cmd/server/main.go`): it runs no statement.
- `sqlite.Open` sets WAL (already set) and the migration runner creates the
  ledger only if missing and reads it: with every migration recorded nothing
  is written at startup.
- SQLite opens a file it may not write read-write **without an error**, reads
  it, and even takes the write lock (`BEGIN IMMEDIATE` succeeds); only an
  actual write fails ("attempt to write a readonly database").
- The listening handler maps that error to a generic 500 and logs nothing.

## 56. The documented restore leaves the backup untouched

The RELEASE.md Restore block, run as written (with `docker compose stop/up`
replaced by no-ops) on disposable copies:

- writable backup: the write check passes, the service then writes (201); the
  backup's files are identical in content, mode and mtime and its
  `SHA256SUMS` still verifies; the previous data is kept beside it;
- read-only backup: the block stops at the write check before the service
  would start; after the documented `chmod 600` the check passes and the
  service writes (201); the backup is still identical.

## 57. First-write check

`scripts/release/restore_write_check.py DATA_DIR [--uid N --gid N]`: for the
service's uid/gid it checks that app.db and present sidecars are writable
regular files and that the directory is writable, then, when run as that
uid, **writes inside a transaction it rolls back** (a temporary table) and
confirms app.db is unchanged. A lock-only probe is not enough (see 55). A
running writer fails it at once ("stop it first"). Wired into the RELEASE.md
Restore block and `flh-daily.sh restore` (which takes the uid from the data
directory it already requires to be owned by FLH_UID, and does not start the
service when the check fails). It failed every case above except A, before
any server started.

**Limitations:** run as another user (for example root) it judges mode bits
for the given uid/gid only (no supplementary groups or ACLs) and skips the
write probe; it may create or remove the empty -wal/-shm sidecars, as the
service does; it does not detect a full disk; `/readyz` itself is unchanged.

## 58. Rollback, then re-import

- **Binary rollback** (the `c53b42c` server on the upgraded, used database):
  re-importing all 12 scripts answers 200 and writes nothing (it compares with
  revision 1, its own pack); a mistake saved there links the newest
  revision's exercise. Rolled forward: no revision lost or duplicated, no
  duplicate lesson, all 7 Notebook items resolve.
- **Restore rollback** (pre-upgrade backup over the used database): what was
  written after the backup (4 transcript versions, 5 exercises, 3 captures)
  is gone from the active database and kept only in the moved-aside
  directory; nothing older is lost. Re-updating appends exactly one revision
  per lesson; re-import replays; nothing is duplicated. **IDs are reused:**
  exercises 14 and 15 belonged to u05 and u01 before the rollback and to u01
  and u05 after it, so a reference kept outside the database (an export, a
  note) from before the rollback can name other content.

## Commands and results

| Command | Result |
|---|---|
| lane tool `part3_restore.py` (items 53–56, 58) | 11/11 |
| `python3 -B -m unittest discover -s scripts/release -p 'test_*.py'` | 17 tests OK (6 new) |
| `bash scripts/validation/flh094/test_wrapper.sh WORK` | exit 0, 84 PASS (new: a read-only backup is restored but the service is not started) |
| `make verify` | exit 0 |
