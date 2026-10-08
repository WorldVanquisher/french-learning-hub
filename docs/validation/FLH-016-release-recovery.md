# FLH-016 — Durable release recovery and verification

Date: 2026-10-08 (America/Toronto). Owner: Codex. Working directory:
`/home/worldvanquisher/workspace/flh-nas-codex`. Requested branch label:
`fix/flh-016-release-recovery`; branch state was not inspected. No Git/GitHub
commands were executed. Status: implemented, validated, stopped for review.

Read `AGENTS.md`, `docs/validation/FLH-011-release-acceptance.md`, and
`docs/validation/FLH-013-release-edge-cases.md` before implementation.

## Ownership and changes

- `Makefile`: `set -e` before temporary-directory creation and both executable
  builds. Either failed build aborts the recipe; the EXIT trap removes the
  temporary directory on successful creation and subsequent failure/success.
- `docs/RELEASE.md`: restore a validated staging directory at the configured
  active path after preserving the old directory by rename. Configuration stays
  unchanged, including custom `FLH_DATA_DIR`; the shell variable alone cannot
  resolve a Compose env-file value. Backup and daily migration copy only app.db
  and present WAL/SHM files. Bash fail-fast blocks require SQLite output `ok`,
  check backup checksums on restore, and describe failure recovery. Document
  required tools, private directories, ownership, restart loops and healthcheck
  behavior. Correct rollback instructions to use the same persistent procedure.
- `docs/validation/FLH-016-validate.py`: repeatable isolated validation harness;
  `--files-only` omits dependency installation, real verification and Docker.
- This report.

No API, schema, shared README, frontend, backend, Compose, configuration,
manifest or lockfile was edited. `README.zh-CN.md` exists; shared README edits
were explicitly outside ownership. No business or API contract changed.

## Isolation and commands

Main evidence: `/tmp/flh-016-v2xle2f_/commands.log`, copied sources, synthetic
DBs, backup and preserved-old directory. Supplemental failure/WAL evidence:
`/tmp/flh-016-gy18rp7f/commands.log`. Earlier harness attempts remain under
`/tmp/flh-016-vqbs5ouf` and `/tmp/flh-016-wgy8x3v0`.

The harness copies only specified source/build inputs, excluding env/secret-like
files, databases, generated frontend output and dependencies. Installs `npm ci`
only in the isolated source copy; all frontend generated output is isolated.
Every subprocess receives a constructed environment: rule-based analyzer,
disabled extractor/embedding, empty credentials/provider settings, temporary
HOME/DOCKER_CONFIG/GOCACHE and the existing Go module cache. All Compose calls
use `--env-file /dev/null`, a unique project name and an OS-selected loopback
port. No .env was inspected, daily database accessed, or paid provider called.

Executed:

```sh
python3 docs/validation/FLH-016-validate.py
python3 docs/validation/FLH-016-validate.py --files-only
```

The first command completed successfully before supplemental file checks were
added; the second executes those additions and the unchanged build failure
checks. The retained main log includes the actual commands for npm ci,
make verify, Compose build/start/stop/down/recreation, SQLite and mount inspect.

Relevant command expansion:

```sh
# In the isolated source copy, with the constructed environment:
npm ci                       # cwd: source/web
make verify                  # cwd: source
# Compose transport used for every main Docker operation:
docker compose --env-file /dev/null -p flh-016-v2xle2f_ \
  -f /tmp/flh-016-v2xle2f_/source/compose.yaml \
  -f /tmp/flh-016-v2xle2f_/override.yaml up -d --build
```

Final read-only `docker ps -a` filtered by the task project returned no
containers. Compose down removed the task network. Dedicated image retained:
`french-learning-hub:flh-016-v2xle2f_`,
`sha256:82225bfe9369308ac06d89ccf6d37d0379410c706f42489d9121ebf092a50f25`.
No pre-existing image tag was replaced.

## Results

| Check | Observed result |
| --- | --- |
| BR1 reproduction | Create A, back up, add B; one-off alternate-directory restore shows A, add C shows A/C; plain up reverts to A/B |
| Corrected restore | Execute documented Restore block with only fixture path/Compose transport substitutions; A restored, C added; A/C survives down/up and up --build --force-recreate |
| Mount selection | Docker inspect after both recreation checks confirms /data source is the original configured active path |
| Old data preserved | Sibling before-restore directory contains A/B; no deletion |
| Nested daily layout | Fake release, local-trial, synthetic-demo and backups subdirectories contain unrelated canaries; migration output contains only app.db and SHA256SUMS |
| WAL migration | Synthetic WAL writer commits and exits before copy; present app.db-wal/app.db-shm copied, both committed daily/wal rows readable in copied DB |
| Copy failure | Missing source aborts migration; controlled restore copy failure aborts before rename/start |
| Integrity errors | Corrupt DB fails; stub SQLite exits zero with non-ok output and migration/restore still fail |
| Checksum failure | Tampered backup aborts restore before active-directory rename; original marker unchanged |
| Build failure injection | Stub go fails server or capture build separately; make verify exits nonzero, skips frontend commands; server failure skips capture build |
| Temporary cleanup | TMPDIR empty after each injected executable failure |
| Full make verify | Formatting check, all Go tests, vet, both executable builds, frontend typecheck, 97 tests in 9 files, production build pass |
| Cleanup | No remaining task containers/network; synthetic evidence and dedicated image retained |

Documented shell blocks are executed directly by the harness rather than
reimplemented. Copy-error and non-ok integrity tests inspect that active data
was not renamed. No production databases were used.

## Limitations and corrections during validation

- Initial synthetic SQL used double quotes for a string; SQLite rejected it.
  Corrected to a single-quoted literal and reran successfully.
- Initial full verification passed Go checks/builds but stopped because shared
  web/node_modules was absent. Removed the proposed dependency symlink and
  installed locked dependencies in the isolated copy; full verification passed.
- Docker used the available legacy builder; buildx/BuildKit and no-cache builds
  were not separately tested. npm reported dependency advisories; no dependency
  upgrades were made within this task.
- Custom FLH_DATA_DIR guidance is documented; container persistence testing used
  the default path plus the alternate-path BR1 reproduction, not a second
  persistent custom-path recovery run.
- Restart-loop behavior is based on the supplied FLH-013 evidence and unchanged
  restart policy, not new deliberate startup misconfiguration.
- Second-rename filesystem failure, off-machine transfer, real daily migration,
  image-version/schema rollback and concurrent writer enforcement were not run.
  Recovery requires the operator to stop all writers and preserve ownership.
- FLH-013 routing/build-context findings remain outside this assigned scope.

Human-only staging command (displayed, never executed):

```sh
git add -- Makefile docs/RELEASE.md docs/validation/FLH-016-validate.py docs/validation/FLH-016-release-recovery.md
```

Suggested commit message:
`fix: make release recovery durable and propagate verification build failures`
