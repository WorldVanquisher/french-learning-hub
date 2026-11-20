# Release checks, 2026-11-17

Release-tooling evidence on the baseline that run 20261112T044723Z tested and
that was merged (1,088 files, identical content). Disposable directories,
databases, ports and Compose projects only; no real backup, provider, daily
database or daily container was used. Two defects in the release tooling were
found and fixed; everything else held.

## Migrations

21 files, `001`…`021`, contiguous and all embedded. The documented
predecessor of the latest migration (`021_listening_authored_scripts.sql`) is
`020_mock_exams.sql`. No migration file differs from any of 23 earlier tree
manifests (levels 015–021), so no applied migration was edited.

## Release smoke

`bash scripts/release/smoke.sh WORK_DIR` passed every stage. Observed from
outside while it ran:

- the app and demo containers ran the image the smoke had just built (same
  image ID as its `flh-smoke:<id>` tag), on the mapped loopback ports;
- the server binary copied out of the running container embeds all 21
  migrations and the listening, reading, writing and exam packs of this tree
  byte for byte; the disposable database's ledger is exactly those 21
  migrations; the demo's `/knowledge-library/demo` identity names the artifact
  the smoke prepared;
- decoys a careless cleanup would hit (a container named `flh-smoke-decoy-*`
  under another Compose project label, a process and a loopback listener named
  flh-smoke, files beside `WORK_DIR` and in `TMPDIR`) were untouched, no
  repository file changed, and every Docker removal in the window belonged to
  the run (its project, network, image and build intermediates).

`--inject-failure persistence` failed with the same clean teardown.

**Defect (fixed):** a `SIGTERM` while the app was up tore everything down but
the run printed `SMOKE PASS` and exited 0, although readiness, persistence and
the demo never ran: the `EXIT` trap's `exit 0` replaced the signal trap's
`exit 1`. A timed-out or cancelled smoke reported success. Now PASS requires
every stage to have run; otherwise the summary gets an `incomplete` FAIL line
(naming the signal) and the exit status is 1. Rerun: `incomplete FAIL
interrupted by SIGTERM`, exit 1, clean teardown; an uninterrupted run still
passes.

## Publishing metadata check

**Defect (fixed):** `scripts/release/publish_metadata_check.py` rejected people
called Claude: `Co-authored-by: Jean-Claude Martin`, `Co-authored-by: Claude
Monet` and an author `Claude Dupont` were findings. The assistant is now an
`anthropic.com` address, a name containing "Anthropic", or "Claude" alone or
with a model or product word ("Claude Opus 5.5", "Claude Code",
`claude[bot]`). Before the fix 10 of 13 attribution cases were right, after it
13 of 13: AI co-author trailers, session trailers, private links and AI
identities are rejected; human co-authors, people called Claude, prose about
AI and the public "Generated with Claude Code" line pass. Unit tests:
`python3 -B -m unittest discover -s scripts/release -p 'test_*.py'` (13 tests:
historical snapshot of 2026-11-17; see "Current rerun" below).

## Readiness, failed-request log and backup failures (later the same day)

The migration rehearsals of this run, with synthetic data on disposable
Compose projects, found three operator-facing gaps. All three are fixed here.

- **A read-only database reported ready.**
  - **How it showed:** a restored copy that kept its backup's `0444` modes
    answered `/readyz` 200 and then 500 to every write, with nothing in the log.
  - **Why `BEGIN IMMEDIATE` was not enough:** it succeeds on a read-only WAL
    database (checked with the `sqlite3` CLI and in `readiness_test.go`). Only
    a write statement fails.
  - **The probe now:** `DELETE FROM schema_migrations WHERE 0` inside
    `BEGIN IMMEDIATE` … `ROLLBACK`, with no busy wait. A writable database stays
    byte-identical, and the WAL does not grow. A read-only one is
    `503 {"status":"not_ready","reason":"storage_read_only"}`.
  - **Observed on the image:** the files were set to `0444` and the container
    restarted. `/readyz` answered 503 `storage_read_only`, reads 200, the write
    500 with one log line. After `chmod 600` and a restart, the write was 201
    and the earlier data was intact.
- **Failed requests left no log line.**
  - **Now:** every response ≥ 500 logs
    `request failed: status=… method=… route="<pattern>" duration_ms=… request_id=…`.
  - **Request ID:** also sent as `X-Request-Id` on every response.
  - **Observed with a fake transcription provider** (500, then a lost
    response): one line per failure, with the Speaking route pattern. No key,
    audio, base64 or transcript text appeared in the log.
  - **Disk full** (a 6 MiB tmpfs filled by a ballast file): six writes 500 and
    six lines. Reads still worked, and after the ballast was removed the next
    write was 201 without a restart.
- **A backup that failed partway was silent.**
  - **How it showed:** under a 64 KiB file-size limit (as on a full disk),
    `flh-daily.sh backup` exited 153 with the shell's own "File size limit
    exceeded … cp -a" line. The service stayed stopped, and nothing said so.
  - **Now:** it prints `backup FAILED`, says the service is stopped (as
    DAILY_USE.md documents), names `flh-daily.sh start`, and renames the copy
    it created to `.incomplete` (restore refuses it anyway: no `SHA256SUMS`).
  - **Name collision:** a backup that collides with an earlier one of the same
    second leaves the earlier one untouched.
  - **Tests:** two new wrapper checks in
    `scripts/validation/flh094/test_wrapper.sh`. Both fail on the previous
    wrapper and pass now.

Commands:
- `go test ./...`, `go vet ./...`, `gofmt -l .`;
- `python3 -B -m unittest discover -s scripts/release -p 'test_*.py'` (14 tests:
  historical snapshot of 2026-11-17, later the same day; see "Current rerun" below);
- `bash scripts/validation/flh094/test_wrapper.sh WORK_DIR` (84 checks).

## Current rerun (2026-11-19, recorded separately)

The 13 and 14 above are snapshots of the suite as it was on 2026-11-17. The
same command on the tree merged after it (Git tree `2bf1d9f6…`), run through
`scripts/ci/python_suites.py --suite release` (the CI job `python-tools`),
printed `Ran 20 tests` / `OK` on Python 3.14.9 and 3.12 (`python:3.12-slim`).
Later counts come from that job's output, not from this file.

## Not covered

- The upgrade rehearsal was not rerun (same tree as its last run, all stages
  PASS on the synthetic fixture). The older-binary stage still needs the owner
  to build the server from the commit before 021; no copy of a real 020 backup
  was rehearsed.
- No CI workflow runs `scripts/release/test_*.py`.
