# Overnight integration checks, 2026-11-12

Release-tooling evidence on the post-merge baseline (the tree that run
20261112T021654Z tested and that was merged: 1,031 files, identical content).
Disposable databases and directories only; no real backup, provider, daily
database or daily container was used. What was observed is separated from
what needs the owner.

## Upgrade rehearsal (020 → 021), rerun

`python3 -I scripts/release/upgrade_021/rehearse.py WORK_DIR`: build, populate,
fixture, backup, upgrade, notebook, scripts, conflict, rollback and reupgrade
all PASS on the synthetic fixture (the same stages and results as
[RELEASE-READINESS-20261112.md](RELEASE-READINESS-20261112.md)).

This is **fixture evidence**: a database the current server populated and the
harness converted to the exact 020 schema. It is not evidence about any real
backup. Still for the owner:

- `old-server` is NOT RUN. No source tree or binary at migration 020 exists on
  this machine outside Git, and agents do not run Git. Build the server from the
  commit before the one that added `migrations/021_listening_authored_scripts.sql`
  and rerun with `--old-server BINARY`.
- `--fixture-db` on a copy of a validated real 020 backup.

## Release smoke, rerun and forced failure

- `bash scripts/release/smoke.sh WORK_DIR`: every stage PASS (exit 0); the
  daily project's container fingerprint was unchanged.
- `--inject-failure persistence` with a decoy container named
  `flh-smoke-decoy-*` under another Compose project label and decoy files next
  to `WORK_DIR`: exit 1; the run's own project, network and image were removed;
  the decoy container (same ID, status and start time) and the decoy files
  (same hashes) were untouched; `WORK_DIR` kept its data for inspection.

## Disk preflight

`scripts/release/disk_preflight.sh` now runs before the smoke and the packaged
browser check. Forced with an impossible threshold, both stopped with exit 3
before building or starting anything and printed the directory, the space
available and needed, and the effective `TMPDIR`. A writable-directory probe
(32 MiB, its own file only) catches per-user tmpfs quotas that `df` does not
show; it was the cause of an earlier "disk quota exceeded" failure of
`make verify`. Unit tests: `python3 -B -m unittest discover -s scripts/release -p 'test_*.py'`
(11 tests, including that another worker's files are left untouched).

## Publishing metadata

The publish kit of run 20261112T021654Z verified file contents only. One lane's
commit message carried an AI co-author trailer and a private session link, and
its PR body the same link; every gate passed. `scripts/release/publish_metadata_check.py`
now rejects those (and an AI author/committer identity) while keeping prose
about using AI and trailers for people; the owner publisher runs it on every
message, PR body and actual commit before pushing.
