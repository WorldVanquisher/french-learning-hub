# 020 → 021 rehearsal: the pinned old server (2026-11-19)

## Which commit

- Migration 021 is `migrations/021_listening_authored_scripts.sql`. Its documented predecessor is
  `020_mock_exams.sql` (`RELEASE-CHECKS-20261117.md`).
- **The pinned pre-021 commit is `45be54921925fddf7422f23f83b23f6fa2775e5e`.** The owner
  verified it with Git as the parent of the commit that added 021. It has 001–020 and no 021.
  Agents run no Git, so the agent did not re-derive it; the build steps below re-check it.
- **Not a candidate: `c53b42c`.** It is used in other rehearsals as "the predecessor". A
  `c53b42c` build embeds 021: `go version -m` shows `vcs.revision=c53b42c5…`, its own ledger on
  a fresh database ends at `021`, and the required stage refuses it.

## Owner commands (Git is the owner's)

Every path is quoted, so a checkout or cache path with spaces works.

```bash
REPO="/path/to/french-learning-app"                      # your checkout (spaces are fine)
OLD=45be54921925fddf7422f23f83b23f6fa2775e5e             # pinned: do not resolve it again
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}"
BIN="$CACHE/flh-old-server/server-$OLD"
cd "$REPO"
git cat-file -e "$OLD^{commit}" && echo "commit present"                          # fetch first if absent
git ls-tree --name-only "$OLD" migrations/ | grep -c '\.sql$'                     # expect: 20
git ls-tree --name-only "$OLD" migrations/020_mock_exams.sql                      # expect: the file
git ls-tree --name-only "$OLD" migrations/021_listening_authored_scripts.sql      # expect: nothing
SRC="$(mktemp -d "$CACHE/flh-old-server-src.XXXXXX")"                             # outside any tracked tree
git worktree add --detach "$SRC" "$OLD"
mkdir -p "$(dirname "$BIN")"
(cd "$SRC" && go build -trimpath -o "$BIN" ./cmd/server)                          # VCS stamping on (default)
git worktree remove "$SRC"
```

**Check the build metadata:**

```bash
go version -m "$BIN" | grep -E 'vcs\.revision|vcs\.modified|GOOS|GOARCH|-trimpath|CGO_ENABLED'
```

| Line | Expected |
|---|---|
| `vcs.revision` | `45be54921925fddf7422f23f83b23f6fa2775e5e` |
| `vcs.modified` | `false` |
| `GOOS` / `GOARCH` | `linux` / `amd64` (this machine) |
| `-trimpath` | `true` |
| `CGO_ENABLED` | the toolchain default; the SQLite driver is pure Go (`modernc.org/sqlite`) |

**Check its own ledger on a fresh, disposable database** (expect `20` and `020_mock_exams.sql`):

```bash
T="$(mktemp -d "$CACHE/flh-old-ledger.XXXXXX")"
( cd "$T" && exec env -i PATH=/usr/bin:/bin HOME="$T" LISTEN_HOST=127.0.0.1 PORT=18299 DB_PATH="$T/app.db" \
    "$BIN" > "$T/server.log" 2>&1 ) &
echo $! > "$T/server.pid"            # exec: this is the server's own PID
sleep 3; kill "$(cat "$T/server.pid")"
while kill -0 "$(cat "$T/server.pid")" 2>/dev/null; do sleep 0.2; done   # let it release the database
sqlite3 "$T/app.db" 'SELECT COUNT(*), MAX(name) FROM schema_migrations'
```

`PORT=18299` is any free loopback port. The `exec` matters: without it the saved PID is a
subshell's, and `kill` leaves the server running. The rehearsal's required stage repeats this
check by itself.

## Rehearsal

```bash
cd "$REPO"
python3 -I scripts/release/upgrade_021/rehearse.py "$(mktemp -d "$CACHE/flh-upgrade-021.XXXXXX")" \
    --old-server "$BIN"
```

- Giving `--old-server` makes the `old-server` stage required.
- A missing or non-executable path is refused before anything runs (exit 2).
- The stage writes `evidence/old_server_identity.json`. It holds each binary's file path and
  sha256, and the old binary's `go version -m` facts under `go_build`.
- It refuses the server the rehearsal itself built.
- It starts the old binary on a fresh database: its own ledger must be exactly 001–020.
- It then starts the old binary on a copy of the restored database: listening and Notebook
  reads must return 200, with no new migration.
- Expected line: `old-server PASS required; old binary … (vcs.revision <OLD>, linux/amd64)
  started …`; exit 0.

**Fixture compatibility versus the old binary:**

| Evidence | What it shows |
|---|---|
| `fixture` stage | The synthetic database has the exact 020 schema |
| `old-server` stage | An actual pre-021 binary started on it |

Without `--old-server`, the line says `NOT RUN optional, not requested: only fixture
compatibility was checked … no pre-021 binary was started`.

## Agent runs on synthetic data (2026-11-19)

All runs used disposable `WORK_DIR`s under `~/.cache`, ephemeral loopback ports and no daily
data:

| Run | Result |
|---|---|
| No `--old-server` | `build`, `populate`, `fixture`, `backup`, `upgrade`, `notebook`, `scripts`, `conflict`, `rollback` and `reupgrade` PASS; `rollback` restores the ledger to end at 020; `old-server` NOT RUN with the wording above; exit 0; 9 s |
| `--old-server` = the `c53b42c` build | every stage PASS except `old-server` FAIL "applies 021_listening_authored_scripts.sql (vcs.revision c53b42c…): it is not a pre-021 build"; exit 1; 3–9 s |
| `--old-server` absent or non-executable | refused, exit 2, nothing written (`scripts/release/test_upgrade_021_options.py`) |

Second pass (same day): paths with spaces throughout (work directory, `--old-server` and the
ledger snippet above, run verbatim).

- Backup and rollback pass.
- The `c53b42c` copy fails with the binary's path, the migration it applies, its revision and the
  expected ledger end (`020_mock_exams.sql`).
- A missing binary is refused (exit 2, nothing written).
- The snippet reports `21|021_…` for that build and leaves no server running.

**What the stage proves on PASS.** It records the restored database's ledger before and after,
and the read statuses, in `old_server_identity.json`. It exercises **reads only**: GET
`/listening/materials` and `/mistake-notebook/items`. No write runs on the old binary.

**Rollback failure in required mode.** The stage reads FAIL ("required … but not run"). This is
covered by a unit test of the decision, not by an end-to-end run: the harness has no
rollback-failure switch.

The pinned pre-021 binary was not available to the agent. The required stage with that binary is
**NOT RUN** until the owner builds it with the commands above.
