# Personal-use release

One Docker image contains the Go service and the built workbench. Compose runs
it on one browser origin, `http://127.0.0.1:8080`, with a persistent SQLite
directory on the host. This is a local, single-user release: there is no
authentication, so the port is bound to `127.0.0.1` only. Do not publish it to a
network you do not trust.

## Requirements

- Docker with the Compose plugin (verified with Docker 29.7 and Compose 5.5).
- Host `sqlite3` and GNU `sha256sum` for integrity and checksum checks; Bash
  for the fail-fast recovery blocks below; Python 3 for the restore write
  check.
- The repository checkout. Nothing is pulled from a private registry and no
  image is published.

## What the image contains

| Stage   | Base image (pinned by digest in `Dockerfile`) | Work                                   |
| ------- | --------------------------------------------- | -------------------------------------- |
| web     | `node:24.11.1-alpine3.22`                     | `npm ci` from `web/package-lock.json`, `npm run build` |
| server  | `golang:1.26.5-alpine`                        | `go mod download` + `go mod verify`, static `CGO_ENABLED=0` build with `GOTOOLCHAIN=local` and `-mod=readonly` |
| runtime | `alpine:3.22.2`                               | `/app/server`, `/app/web`, non-root user `1000:1000` |

The build context is an allowlist (`.dockerignore`): only `go.mod`, `go.sum`,
`cmd/`, `internal/`, `migrations/` and the `web/` sources and lockfile. `.env`
files, `data/`, databases, `captures/`, `.git`, `node_modules`, `dist` and test
files never reach Docker. The image sets only `PORT=8080` and
`DB_PATH=/data/app.db`; it contains no `.env`, credential or database.

The server starts as `/app/server -web-dir /app/web`:

| Path                 | Served by                                                  |
| -------------------- | ---------------------------------------------------------- |
| `GET /`              | workbench `index.html` (`Cache-Control: no-cache`)         |
| `GET /assets/...`    | built JS/CSS (no directory listings)                       |
| `/api/...`           | the API, with `/api` stripped (what the workbench calls)   |
| every other path     | the API unchanged (`/entries`, `/captures`, ... and 404s)  |
| `GET /healthz`       | liveness: the process serves HTTP; no database access      |
| `GET /readyz`        | readiness, bounded to 2 s: SQLite answers and accepts a write statement (`DELETE … WHERE 0` inside `BEGIN IMMEDIATE`/`ROLLBACK`: no row, nothing written); `503 not_ready` on failure, with `"reason":"storage_read_only"` when the database opened read-only |

The workbench never changes the URL path, so there is no SPA fallback. Without
`-web-dir` the server is API-only, exactly as `make run`.

The container healthcheck polls `/readyz` every 15 s (1 s during a 20 s start
period, 3 s timeout, 3 retries). `docker compose ps` shows `healthy` once SQLite
answers and can write. A restored copy that kept read-only permissions, or a
filesystem remounted read-only, now shows `unhealthy` and
`{"status":"not_ready","reason":"storage_read_only"}` instead of `ready`
followed by a 500 on every write.

**Failed requests in the log.** Every response with status 500 or more writes
one line: `request failed: status=500 method=POST route="POST /captures"
duration_ms=3 request_id=<16 hex>`. The line holds the route pattern, never
path values, the query, a body, a header, audio or a provider message. The
same `request_id` is sent on every response as `X-Request-Id`, so a failure
seen in the browser can be found in the log. Read it with
`bash scripts/daily/flh-daily.sh logs` or `docker compose logs app`.

## Configuration

For private daily use with real providers, prefer `scripts/daily/flh-daily.sh`
([DAILY_USE.md](DAILY_USE.md)). It runs this same service with one settings
file on every command. A plain `docker compose up` run without the values used
before recreates the container with the defaults below: the rule-based analyzer,
disabled extraction and `./data/release`.

`compose.yaml` passes configuration explicitly:

- `PORT=8080` and `DB_PATH=/data/app.db` are fixed. A host `DB_PATH` or `PORT`
  is ignored, so the container cannot be pointed at another database by
  accident.
- `HTTP_ALLOWED_HOSTS` and `HTTP_TRUSTED_ORIGINS` are forwarded for the browser
  boundary described below. Empty values use the server defaults.
- Only these provider variables are forwarded, with the server's defaults:
  `AI_PROVIDER` (`rule-based`), `EXTRACTOR_PROVIDER` (`disabled`),
  `SUGGESTION_PROVIDER` (`disabled`), `LISTENING_PROVIDER` (`disabled`), `READING_PROVIDER` (`disabled`), `WRITING_PROVIDER` (`disabled`), `SPEAKING_PROVIDER` (`disabled`), `SPEAKING_TRANSCRIPTION_PROVIDER` (`disabled`), `EMBEDDING_PROVIDER` (`disabled`), and `SPEAKING_TRANSCRIPTION_MODEL`, `OPENAI_API_KEY`, `OPENAI_MODEL`,
  `OPENAI_BASE_URL`, `OPENAI_TIMEOUT`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`,
  `EMBEDDING_BASE_URL`, `EMBEDDING_TIMEOUT`, `HTTP_READ_TIMEOUT`,
  `HTTP_WRITE_TIMEOUT`, which default to empty. Empty means unset, so the
  server applies its own defaults (see [`.env.example`](../.env.example)).
- Daily Listening settings are forwarded the same way, all off by default:
  `LISTENING_PLAYLIST_SOURCE` and `LISTENING_AUTO_PREPARE` and
  `LISTENING_NOTIFY` (`disabled`), `LISTENING_TIMEZONE` (`UTC`), and
  `LISTENING_PLAYLIST_ID`, `LISTENING_PLAYLIST_MAX_ITEMS`, `YOUTUBE_API_KEY`,
  `YOUTUBE_API_BASE_URL`, `YOUTUBE_TIMEOUT`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`, `TELEGRAM_API_BASE_URL`, `TELEGRAM_TIMEOUT` (empty).
  The image also contains `/app/listening-pull`, which runs one pull only when
  invoked (`docker compose exec app /app/listening-pull`); see
  [DAILY_USE.md §10](DAILY_USE.md#10-daily-listening-pull-prepare-notify).
- Release-only settings: `FLH_DATA_DIR` (default `./data/release`),
  `FLH_HOST_PORT` (default `8080`), `FLH_UID`/`FLH_GID` (default `1000`).

Values come from your shell environment or from a `.env` file next to
`compose.yaml`, which Compose reads only to fill in `${...}`. That file is never
copied or mounted into the image or container. A shell variable wins over the
file.

Compose's `.env` parsing is close to, but not the same program as, the
server's (`godotenv`). Observed with Compose 5.5 using placeholder values:

- `KEY=value # note`: the ` # note` comment is dropped.
- Unquoted and double-quoted values expand `$NAME` and `${NAME}`.
- Single-quoted values are literal.
- `export KEY=value` is accepted.

Put any secret that contains `$`, `#`, spaces or quotes in single quotes.
That keeps it literal under both parsers. Check what the container will
receive without printing secrets, for example:

```bash
docker compose config --format json | python3 -c 'import json,sys; e=json.load(sys.stdin)["services"]["app"]["environment"]; print({k: ("set" if v else "empty") for k, v in e.items()})'
```

Do not run a bare `docker compose config` where its output might be logged or
shared, because it prints values in full.

## Browser-request boundary and NAS access

The complete HTTP handler validates Host before serving either the workbench
or the API, including both root and `/api/` routes. Unapproved or malformed
Host values return `403` with `request host is not allowed`, including reads.
This prevents an arbitrary rebinding hostname from reaching the service;
blocking `text/plain` alone would not prevent DNS rebinding. The allowlist does
not pin DNS or verify who controls an approved name. If an attacker controls an
explicitly approved hostname, that name can still be rebound to the service
and pass Host/same-origin checks. Only approve names you control; literal IP
entries avoid this DNS-name gap. This policy is not authentication.

- `HTTP_ALLOWED_HOSTS`: empty/unset means only `localhost`, `127.0.0.1`, and
  `::1`. A nonempty comma-separated list **adds** exact NAS DNS names or IP
  addresses to those loopback defaults. Names are case-insensitive ASCII DNS
  labels (letters, digits, internal hyphens; up to 63 bytes per label and 253
  total). No wildcard, URL scheme, port, path, trailing dot, empty list item,
  underscore, network range or IPv6 zone is accepted. IPv6 addresses in this
  setting are unbracketed and canonicalized. Request Host IPv6 literals must
  use brackets; request ports, when present, must be numeric 1–65535. An allowed
  hostname/IP is accepted on any valid port; no DNS resolution or suffix match
  grants access. Invalid configuration stops startup with a value-free error.
- `HTTP_TRUSTED_ORIGINS`: empty/unset defaults to
  `http://localhost:5173,http://127.0.0.1:5173,http://[::1]:5173` for the existing
  Vite proxy, which rewrites Host but retains Origin. A nonempty comma-separated
  list **replaces** these defaults. Entries must be exact `http://host[:port]`
  or `https://host[:port]` origins, with the same hostname/port rules above:
  no credentials, path (including trailing `/`), query, fragment, wildcard,
  `null`, or empty item. IPv6 origin literals require brackets. Surrounding list
  whitespace is trimmed; DNS names are lowercased, IP literals canonicalized,
  and default HTTP/HTTPS ports omitted. A trusted origin does not add an allowed
  Host. Each listed origin is deliberately trusted to issue mutations. For a
  release-only process, set this explicitly to its own browser origin to remove
  the development exceptions, e.g. `http://127.0.0.1:8080`.

Mutations (all methods except GET/HEAD/OPTIONS) check Origin and Go's standard
CrossOriginProtection/Fetch Metadata before application services run. Malformed,
multiple, `null`, or mismatched origins return `403` unless a valid origin is an
explicit trusted exception. Same-origin comparison includes scheme and port;
the scheme comes from the direct connection's TLS state. Cross-site/same-site
Fetch Metadata without a trusted Origin is rejected; same-site alone is not
same-origin. Browser mutation bodies require `application/json` (parameters
such as `charset=utf-8` are allowed), otherwise `415`. Bodyless workbench
analysis/extraction POSTs remain supported. Existing CLI requests with neither
Origin nor Fetch Metadata retain their content-type behavior; the capture CLI
already sends JSON. Safe methods do not mutate data and need no Origin check.
No CORS response permissions are added, including for OPTIONS preflights.

For direct API-only NAS use, set the actual names/IPs clients use before starting,
for example `HTTP_ALLOWED_HOSTS=nas.home,192.168.1.20,fd00::20`. Access at an
unlisted NAS address returns an explicit `403`; it is not silently accepted.
The setting does not change listening addresses or Compose's loopback-only
publish rule. Keep any separately arranged NAS exposure restricted to a trusted
network. For Vite on another port, set `HTTP_TRUSTED_ORIGINS` to the actual
frontend origin(s), e.g. `http://localhost:5174`; include :5173 entries too if
both are used. No frontend proxy change is required.

Forwarded, X-Forwarded-Host, and X-Forwarded-Proto headers are ignored for trust.
For an explicitly deployed TLS reverse proxy, preserve an allowed Host and
configure the externally advertised HTTPS origin in `HTTP_TRUSTED_ORIGINS`;
forwarded headers alone cannot make an insecure backend connection HTTPS.

This is **browser-request protection, not authentication**. Native clients can
supply their own headers or omit browser headers, and anyone with network access
can still use the CLI/API. An approved hostname and each trusted-origin site
remain part of the trust boundary. Protect the network and trusted development
server; these checks do not authorize exposure to an untrusted network.

## First start

The data directory must already exist and be writable by `FLH_UID`. Compose
refuses to start if it is missing (`bind source path does not exist`) instead
of creating it as root.

```bash
umask 077
mkdir -p data/release
chmod 700 data/release
docker compose up -d --build
docker compose ps          # wait for "(healthy)"
```

Open `http://127.0.0.1:8080`. The capture CLI uses the same origin:

```bash
go run ./cmd/capture -url http://127.0.0.1:8080 -file examples/captures/manual-example.json
```

`./data/release` starts as a fresh database. Your existing daily database is
not moved or copied automatically. Use **Migrate the daily database** below.
Keep data, staging, preserved-old and backup directories mode `700`, owned by
`FLH_UID:FLH_GID` (set ownership appropriately before starting). The container
creates database files with mode `644`; private parent directories prevent other
local users from reading them. Docker administrators still have access.

## Start, stop, restart

```bash
docker compose up -d --build   # build (if needed) and start
docker compose stop            # stop; container and data kept
docker compose start           # start the stopped container
docker compose restart         # stop + start
docker compose down            # remove the container and network; data kept
docker compose logs -f app     # follow logs
docker compose ps              # status and health
```

`stop` sends SIGTERM, the server shuts down gracefully, and it exits with
status 0. `down` followed by `up -d` creates a new container on the same data
directory.

## Backup

Run each block in Bash from the Compose project directory. `set -e` stops on
copy, checksum, SQLite or rename failure; never continue to start after an error.
Resolve `active` to the directory Compose actually mounts: the default is
`./data/release`. For custom `FLH_DATA_DIR`, use that same configured path in
**all** blocks and ordinary Compose commands. If configured in Compose `.env`,
set `active` explicitly to its resolved path; shell `${FLH_DATA_DIR:-...}` alone
cannot read Compose's configuration. Keep that configuration unchanged during
recovery. Do not point `active` at the parent `data/` directory.

Stop the service before copying; no other process may write the database.
Copy only the database and its present WAL/SHM sidecars, never recursively copy
a directory. Keep backups off-machine too.

```bash
set -e
umask 077
active=./data/release                       # use your configured path
backup="data/backups/flh-$(date -u +%Y%m%dT%H%M%SZ)"
docker compose stop
mkdir -p data/backups
chmod 700 data/backups
mkdir -m 700 "$backup"                     # fails if already present
cp -a "$active/app.db" "$backup/app.db"
for suffix in -wal -shm; do
  if [ -e "$active/app.db$suffix" ]; then
    cp -a "$active/app.db$suffix" "$backup/"
  fi
done
integrity=$(sqlite3 -readonly "$backup/app.db" 'PRAGMA integrity_check;')
[ "$integrity" = ok ] || { echo 'Backup integrity check failed' >&2; exit 1; }
(cd "$backup" && sha256sum app.db* > SHA256SUMS)
docker compose start
```

A zero SQLite exit status alone does not prove integrity. The comparison above
requires the complete output to be exactly `ok` (apart from the final newline).

## Restore

Restore at the **same configured path**, so ordinary `down`/`up` and
`up --build` keep selecting it. Run the final `up` with the same configuration
source as before (or use `scripts/daily/flh-daily.sh restore`, which does). Preserve the old directory by renaming it;
do not delete it or use a one-command `FLH_DATA_DIR` override. The staging and
old paths below are siblings of `active`, on the same filesystem. They must
not already exist. Use a known backup from the procedure above.

```bash
set -e
umask 077
active=./data/release                       # use your configured path
# Set backup to the chosen backup directory before running this block.
: "${backup:?Set backup to the chosen backup directory}"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
stage="$active.restore-$stamp"
old="$active.before-restore-$stamp"
docker compose stop
test ! -e "$old"
mkdir -m 700 "$stage"
(cd "$backup" && sha256sum -c SHA256SUMS)
cp -a "$backup/app.db" "$stage/app.db"
for suffix in -wal -shm; do
  if [ -e "$backup/app.db$suffix" ]; then
    cp -a "$backup/app.db$suffix" "$stage/"
  fi
done
integrity=$(sqlite3 -readonly "$stage/app.db" 'PRAGMA integrity_check;')
[ "$integrity" = ok ] || { echo 'Restore integrity check failed' >&2; exit 1; }
# Both directories must be owned by the configured FLH_UID:FLH_GID.
mv "$active" "$old"
mv "$stage" "$active"
# /readyz cannot tell that the service may not write the restored files (a
# backup made read-only, or owned by another user, restores that way).
python3 -I scripts/release/restore_write_check.py --uid "${FLH_UID:-1000}" --gid "${FLH_GID:-1000}" "$active"
docker compose up -d --force-recreate
```

If the second rename fails, leave the service stopped and move `old` back to
`active` before retrying. If the write check fails, the restored files are in
`active` and the service is still stopped: make `active`, `app.db` and any
`app.db-wal`/`app.db-shm` writable by the service user (for example
`chmod 600 "$active"/app.db*` and `chown FLH_UID:FLH_GID`), run the check
again, then `docker compose up -d --force-recreate`. On earlier errors, the
original active directory is untouched; inspect the failed staging directory
before removing it. Preserve `old` for review. The backup itself is only read.
Check `/readyz` and expected records after starting; `/readyz` shows that
SQLite answers, not that it can write, which is what the write check is for.
It runs as you: when the service user differs, it judges mode bits for that
uid and skips its write probe (see the script's header).

For an independent backup check, copy into another private directory, validate
it as above, then use a separate project and port. This is a test instance,
not the durable restore procedure. A copy of a read-only backup is read-only
too (`cp -a` keeps the modes): its instance answers `/readyz` but fails its
first write, so the write check runs first and `up` only after it passes. If
it fails, run `chmod 600 "$check_dir"/app.db*` and the block again:

```bash
: "${check_dir:?Set check_dir to the separately copied and validated directory}"
python3 -I scripts/release/restore_write_check.py --uid "${FLH_UID:-1000}" --gid "${FLH_GID:-1000}" "$check_dir" &&
FLH_DATA_DIR="$check_dir" FLH_HOST_PORT=18081 docker compose -p flh-restore-check up -d &&
curl --fail http://127.0.0.1:18081/readyz
docker compose -p flh-restore-check down
```

## Migrate the daily database

Stop `make run` (or whichever process owns `data/app.db`) and wait for it to
exit. Stop the release container too. No writer may remain active. Never run
`cp -a data/. ...`: `data/` may contain nested releases, backups and unrelated
databases. First make a private, file-only backup, then run **Restore** with
that backup. If the configured release directory does not yet exist, create
it privately first so Restore can preserve it, even if empty.

```bash
set -e
umask 077
source_db=./data/app.db
backup="data/backups/daily-$(date -u +%Y%m%dT%H%M%SZ)"
docker compose stop
mkdir -p data/backups
chmod 700 data/backups
mkdir -m 700 "$backup"
cp -a "$source_db" "$backup/app.db"
for suffix in -wal -shm; do
  if [ -e "$source_db$suffix" ]; then
    cp -a "$source_db$suffix" "$backup/"
  fi
done
integrity=$(sqlite3 -readonly "$backup/app.db" 'PRAGMA integrity_check;')
[ "$integrity" = ok ] || { echo 'Migration integrity check failed' >&2; exit 1; }
(cd "$backup" && sha256sum app.db* > SHA256SUMS)
# Continue with Restore only after this entire block succeeds.
```

## Optional semantic search (Qdrant profile)

Semantic search (FLH-040) is off unless you set `SEMANTIC_SEARCH=qdrant` and
its required variables. The `semantic` profile adds one Qdrant container
(`qdrant/qdrant:v1.19.1`, pinned by digest) published on
`127.0.0.1:${FLH_QDRANT_PORT:-6333}` only, with its storage in
`${FLH_QDRANT_DIR:-./data/qdrant}`, which must already exist:

```bash
mkdir -p data/qdrant
docker compose --profile semantic up -d --build
docker compose exec app /app/semantic-index build
```

Without the profile, `docker compose up` starts exactly the same single service
as before. Configuration, operations and recovery are in
[SEMANTIC_SEARCH.md](SEMANTIC_SEARCH.md). This profile was validated with
`docker compose config` only; it was not started against a Docker daemon in
FLH-040.

**Backups.** Back up only the SQLite database as described above: it contains
the reusable embedding cache and the index bookkeeping. The Qdrant directory is
disposable. After restoring a database, run
`docker compose exec app /app/semantic-index sync` (or `rebuild`); cached
embeddings are reused, so no document is re-embedded.

## Upgrades and migration rollback limits

Migrations are forward-only. On start, the server applies any embedded
migration not yet recorded in `schema_migrations`. There are no down
migrations.

- **Back up before every image upgrade.** A newer image may migrate the
  database the moment it starts.
- An older image does not refuse a database migrated by a newer one. It skips
  the migrations it knows are recorded and runs against a schema it was not
  built for (for example, migration `007` drops columns). Never run an older
  image on a newer database.
- To roll back, stop the service, restore the backup taken before the upgrade
  at the configured path using Restore above, and start the older image there.
  Data written after that backup is not carried back.
- Make the older image current **before** the restore recreates the
  container: Restore's `up -d --force-recreate` uses whatever
  `french-learning-hub:local` is at that moment. The simplest way:
  - **before upgrading:** run
    `docker image tag french-learning-hub:local french-learning-hub:before-upgrade`;
  - **to roll back:** stop, run
    `docker image tag french-learning-hub:before-upgrade french-learning-hub:local`,
    then Restore.

  The daily wrapper's order is in
  [DAILY_USE.md](DAILY_USE.md#roll-back-a-failed-upgrade-nas).

### Rehearse the 020 → 021 upgrade before applying it

Migration `021` rebuilds `listening_materials` (authored listening scripts). To
see what it does to a populated database before upgrading the real one, run
the rehearsal. It needs Go, `sqlite3`, `sha256sum` and Python 3, starts no
container and touches nothing outside `WORK_DIR`:

```bash
python3 -I scripts/release/upgrade_021/rehearse.py /abs/new/empty/dir
```

Without options it builds a 020 database through the real API (YouTube lessons,
exercises from a local fake provider, Notebook records, a retry mark, reading,
writing and a submitted mock exam), converts it to the exact 020 schema
(checked against a pristine 001–020 database), then runs the **Backup** block
above, starts the current server (which applies 021), checks every table, the
Notebook and script import/replay/conflict, runs the **Restore** block, and
upgrades the restored copy again. `WORK_DIR/summary.txt` has one line per stage.

Two checks need the owner:

- `--fixture-db PATH`: rehearse on a **copy** of your own validated 020 backup
  (the source file is only copied, never opened).
- `--old-server BINARY`: the server built from the parent of the commit that
  added 021. Giving it makes the `old-server` stage required. A missing or
  non-executable path is refused before anything runs (exit 2). The stage
  records both binaries' identities, checks that the binary's own ledger on a
  fresh database is exactly 001–020, then starts it on the restored copy and
  fails if it records a migration. Without it that stage is `NOT RUN`, and the
  line says only fixture compatibility was checked. Owner build commands:
  `docs/validation/UPGRADE-021-OLD-SERVER.md`.

## Release smoke

`scripts/release/smoke.sh` checks a release build end to end without going near
the daily instance:

```bash
bash scripts/release/smoke.sh /abs/new/empty/dir        # exit 0 PASS, 1 FAIL, 2 refused, 3 BLOCKED
```

It builds the image as `flh-smoke:<id>` (never `french-learning-hub:local`)
and runs it as Compose project `flh-smoke-<id>` on free `127.0.0.1` ports with
its own data directory. Every variable `compose.yaml` interpolates is removed
from the environment and a generated `--env-file` is used, so neither a `.env`
next to `compose.yaml` nor exported keys reach it, and every provider is
disabled. It checks:

- readiness (`/readyz`, container `healthy`, `/healthz`, `/`, `/api/...`);
- the browser boundary (foreign Host `403`, cross-origin write `403`,
  `text/plain` browser write `415`);
- persistence of a capture across a container restart;
- the same image in public-demo mode with a mechanical artifact: allowlisted
  reads `200`, private routes under `/` and `/api` `404`, path tricks `404`,
  writes `405`, and startup refused when a provider is enabled.

The project, its network and the image are always removed at the end
(`--keep-image` keeps the image), and the daily project's containers are
fingerprinted with `docker inspect` before and after; a change fails the run.
`--inject-failure readiness|persistence|demo` proves that a failed run still
tears down. An interrupted run (Ctrl-C, `SIGTERM`, a timeout) also tears down
and ends with an `incomplete` FAIL line and exit 1: only a run whose every stage
ran and passed is a PASS. The build leaves its intermediate stage images as
Docker build cache; the smoke never prunes them. The demo stage uses the private workbench bundle only to exercise
the static and `/api` paths; the real demo bundle is checked by
[PUBLIC_DEMO.md](PUBLIC_DEMO.md).

### Disk preflight

Before anything is built, the smoke and the packaged browser check
(`scripts/validation/v1_rehearsal/browser_check.sh`) run
`scripts/release/disk_preflight.sh`. It checks the free space of the work
directory (1024 MiB), `TMPDIR` (512 MiB) and Docker's root directory when it is
readable (4096 MiB), and writes and deletes one 32 MiB probe file in each
writable location. The probe catches a per-user quota on a shared tmpfs, which
`df` does not show. If a location fails, the job stops with exit 3 (BLOCKED)
before starting anything and prints the directory, the space available and
needed, and the effective `TMPDIR`. It never cleans anything; free space
yourself or point `TMPDIR` and the work directory at a disk with room. The
thresholds can be raised or lowered with `FLH_SMOKE_MIN_{WORK,TMP,DOCKER}_MB` and
`FLH_BROWSER_MIN_{WORK,TMP,DOCKER}_MB`. Run it alone with, for example:

```bash
bash scripts/release/disk_preflight.sh work=/abs/work:1024 tmp="${TMPDIR:-/tmp}":512
```

### Publishing metadata check

`scripts/release/publish_metadata_check.py` checks commit messages and PR
bodies before they are published. It rejects a `Co-authored-by:` trailer or an
author/committer identity naming the assistant (an `anthropic.com` address, a
name containing "Anthropic", or "Claude" alone or with a model or product name
such as "Claude Opus 5.5", "Claude Code" or `claude[bot]`), a `Claude-Session:`
trailer, and private `claude.ai` session, chat, project or share links. It keeps
prose about using AI and co-author trailers for people, including people called
Claude ("Claude Monet", "Jean-Claude Martin"); write a person's full name, since
a bare "Claude" counts as the assistant. Findings are printed
with private links redacted (`--redact` filters any text the same way). Check a
merged commit with:

```bash
git log -1 --format='Author: %an <%ae>%nCommitter: %cn <%ce>%n%n%B' origin/main |
  python3 -I scripts/release/publish_metadata_check.py --kind commit --label main -
```

The helper scripts' tests: `python3 -B -m unittest discover -s scripts/release -p 'test_*.py'`.

## Python tool suites (CI job `python-tools`)

The CI job and a local run use the same entry point. It runs each
standard-library suite in its normal working directory:

| Suite | Working directory | Command |
| --- | --- | --- |
| `ci-runner` | repository root | `python3 -B -m unittest discover -s scripts/ci -p test_python_suites.py` |
| `release` | repository root | `python3 -B -m unittest discover -s scripts/release -p 'test_*.py'` |
| `private-staging` | repository root | `python3 -B -m unittest discover -s deploy/aws/private-staging/staging/tests -p 'test_*.py'` |
| `extraction` | `tools/extraction` | `python3 -B -m unittest discover -s tests -t tests` |
| `workbooks` | `tools/workbooks` | `python3 -B -m unittest discover -s tests` |
| `speaking` (optional) | `tools/speaking` | `PYTHONPATH=. python3 -B scripts/run_tests.py` (offline; runs only once `scripts/run_tests.py` exists) |

```bash
python3 -B scripts/ci/python_suites.py                     # every suite, from any directory
python3 -B scripts/ci/python_suites.py --suite extraction  # one suite (repeatable)
python3 -B scripts/ci/python_suites.py --list              # the exact commands
python3 -B scripts/ci/python_suites.py --hermetic --json results.json   # what CI runs
```

**What the runner does:**
- **Before each suite:** prints its label, working directory and command.
  In CI each suite is a collapsible log group.
- **Before running anything:** checks that the interpreter and the files the
  suite reads exist. A missing one fails with its full path.
- **Every suite runs**, even after a failure. The runner then prints a table
  of runs, skips, expected failures, failures and errors, parsed from each
  suite's own output, and exits 1 if any suite failed.
- **No external access:** no AWS account, credentials, network service or
  third-party package is needed. CI proves it with `--hermetic`:
  - `AWS_*` is removed, the AWS config and credentials files point at nothing,
    and HOME is an empty directory;
  - `aws`, `terraform`, `docker` and `session-manager-plugin` are traps, and
    any call fails the run.
- **Kept apart in the table:** test-level skips, expected failures, and an
  optional suite that is `NOT-PRESENT` (its entry file is absent). None of
  them counts as a pass.
  - `--require speaking` makes a missing suite fail.
  - `--fail-on-skip LABEL` makes any skip in that suite fail.
- **Timings and resources:** each suite's row and the `--json` file also hold
  its start time, wall and CPU seconds, and peak RSS.
- **The artifact:** CI uploads `python-suites.json` (artifact
  `python-suites`) even when a suite failed. The job still fails.

**Not in this job:** suites that need numpy, PyAV, torch or a model.
- The Speaking dependency run is the separate workflow `speaking.yml`,
  proposed by the release lane. It lands after the Speaking Lab commit and
  runs `scripts/run_tests.py --require-deps` with the hash-locked
  `requirements-cpu.lock` and the weights-free fixture. Its first step fails,
  never skips, if the entry is absent.
- The extraction backend tests (`TINY_SFT`).
- `tools/embedding/e5/tests` and `tools/cloud/aws/tests`.

**Reproduce a CI failure locally:**
1. **Open the failure in the log:** open the failing job and the step
   "Python tool suites". Expand the group named by the `::error::` line.
   The job summary has the same table.
2. **Check out the run's commit:** check out the commit the run tested
   (`git switch --detach <sha>`) in a clean checkout. Local Terraform state,
   `terraform.tfvars`, plans and filled IAM policies are ignored by the tests,
   so a working checkout also works.
3. **Rerun the suite:** run that suite alone with the printed command, or
   `python3 -B scripts/ci/python_suites.py --suite <label>`. CI uses the
   runner's `python3` (3.12 on `ubuntu-latest`). To match it exactly:
   ```bash
   docker run --rm --network none -u "$(id -u):$(id -g)" -e HOME=/tmp -e TMPDIR=/tmp -v "$PWD:/repo:ro" -w /tmp \
     --entrypoint python3 python:3.12-slim -B /repo/scripts/ci/python_suites.py --suite <label>
   ```
4. **Read the cause:** a `MISSING` row names the absent file. A `FAIL` row
   with no counts means the suite crashed before unittest printed its
   summary; the traceback is in the group. `trapped calls: N (docker)` means
   a test called that tool: run the suite with `--hermetic` locally to find
   it. The `python-suites` artifact holds the same rows as JSON.

**Reproduce the Speaking job locally** (after the Speaking Lab commit; CPU
only, about 1 GB of wheels, no weights):

```bash
cd tools/speaking
python3.12 -m venv /tmp/spk && /tmp/spk/bin/pip install --require-hashes --no-deps \
  --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple -r requirements-cpu.lock
PYTHONPATH=. python3 -B -m flh_speaking fetch --dest /tmp/spk-fixture --what whisper-tiny --no-weights
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=. \
  FLH_SPEAKING_TOKENIZER_DIR=/tmp/spk-fixture/openai/whisper-tiny/169d4a4341b33bc18d8881c4b69c2e104e1cc0af \
  /tmp/spk/bin/python -B scripts/run_tests.py --require-deps --json /tmp/speaking-tests.json
```

`--require-deps` fails on any skip, missing module or missing fixture
(docs/validation/SPEAKING-TEST-ENTRY.md).

## Release control dashboard (`scripts/release/release_report.py`)

One versioned report (`flh-release-report/v1`) says why a candidate bundle is READY or BLOCKED
for a target. Every view is computed from that file and its evidence, never typed by hand. The
surface below is stable: gate IDs, states and exit codes do not change meaning.
`scripts/release/test_release_report.py` checks this table against the code.

**Inputs (`collect`):**

| Option | Required | What it is |
| --- | --- | --- |
| `--candidate TAR --candidate-sha256 HEX` | yes | the transfer file and the SHA-256 recorded at build time |
| `--rollback TAR --rollback-sha256 HEX` | no | the previous verified bundle (its ledger must cover the candidate's) |
| `--source DIR` | no | a checkout of the candidate's tree (for the suites, preflight and the tree check) |
| `--target local-rehearsal\|staging` | no (local-rehearsal) | staging also requires the owner-only gates |
| `--plan-json FILE` | owner | `terraform show -json` of the staging plan |
| `--host-status FILE` | owner | the saved output of `flh-staging-bundle status` on the host |
| `--receipt DIR` | no | the integration receipt (`scripts/release/integration_receipt.py`) of the sealed lane sources |
| `--out DIR` | yes | where `report.json` and `evidence/` are written |

**Outputs:** `DIR/report.json` and `DIR/evidence/*.txt` from `collect`; `check` (one line),
`terminal [--width N]` (every line fits N columns), `commands` (the command behind each gate,
fastest check first), `record` (the owner's release record: the digests to type and the
verification policy; `check` also names exactly which gates, agent or owner-only, block), `markdown [--out]`, `html --out` (static, no script; evidence links are
relative to the page, so the report directory can move) and `attest [--source] [--probe-docker]`
(`flh-release-attestation/v1`). Markdown and HTML render the same rows. With `--receipt`, every
view also lists the sealed handoffs the candidate came from. Exit: 0 READY, 1 BLOCKED, 2 invalid
report.

**Gates:**

| Gate | Owner | Required for | Passes when |
| --- | --- | --- | --- |
| `bundle-verify` | agent | both targets | the candidate verifies (sums, manifest, image blobs, labels) |
| `rollback-target` | agent | both targets | a previous verified bundle knows at least the candidate's migrations |
| `python-suites` | agent | both targets | `scripts/ci/python_suites.py` passes on the source |
| `staging-preflight` | agent | both targets | `preflight.py` repository checks are READY |
| `integration-receipt` | agent | both targets (with `--receipt`) | the receipt's sealed lanes and every required check pass on the bundle's tree |
| `browser-evidence` | agent | both targets (with `--receipt`) | learning-day, practice-feed and demo browser runs pass on the bundle's tree |
| `aws-plan-check` | owner | staging | `plan_check.py --mode create` says SAFE on the owner's plan |
| `staging-identity` | owner | staging | the host's status shows `IDENTITY OK` for the candidate |

**Effective states** (evaluated, never trusted from the file): `pass`, `fail`, `pending`,
`unavailable` (no evidence, or the file is missing), `skipped`, `stale` (the evidence names
another bundle or source tree: old evidence to rerun, not a failure), `changed` (the evidence
file's SHA-256 differs). READY needs every required gate `pass`. Views count failed and stale
gates apart.

```bash
python3 -I scripts/release/release_report.py check scripts/release/fixtures/release-report/ready/report.json   # READY
python3 -I scripts/release/release_report.py html scripts/release/fixtures/release-report/ready/report.json --out /tmp/flh-dashboard.html
bash scripts/release/control_center_demo.sh /tmp/flh-control-center      # every tool on synthetic data, offline, about 20 s
```

## Integration candidate from sealed lanes (`scripts/release/integration_*`)

Lanes hand over sealed snapshots (a `SHA256SUMS` plus a tar, a path list, or a hash manifest with
patches). These tools turn the selected seals into one candidate tree without Git, and record
every check run on that exact tree. No network, no AWS. The selection file names local
directories, so it stays outside the repository.

| Tool | What it does |
| --- | --- |
| `integration_candidate.py select SELECTION.json --out SELECTED.json` | verifies every seal (each listed file, the pinned `SHA256SUMS` digest, the snapshot covered by it), each lane's base against the shared base, and refuses inconsistent snapshots: a path deleted and supplied, listed twice, a symlink leaving the tree, a pending proposal already present. A `patch-chain` store rebuilds a manifest-only lane from its sealed patches |
| `integration_candidate.py assemble SELECTED.json --out TREE` | base plus every lane in order. Bytes are read only where their SHA-256 matches; a source that changes while it is copied, or a seal that changes, stops it. Shared paths merge with `diff3 -m`; every lane's changed lines and catalog keys must survive. Writes `TREE.assembly.json` (provenance of every path) |
| `integration_candidate.py reproduce SELECTION.json --expect TREE_ID` | select and assemble in a fresh scratch directory: the one command that reproduces a verified tree |
| `integration_candidate.py verify SELECTED.json TREE` | every lane change holds in TREE (also after a real `git merge`) |
| `integration_candidate.py catalogs TREE [--base DIR --lane L=DIR]` | duplicate keys, key and `{placeholder}` parity of `en.ts`/`zh-CN.ts`, and lost key changes |
| `integration_candidate.py compare OLD NEW --selected S` / `lane-tree S LANE` | differences between two trees by lane; the tree of the base plus one lane |
| `integration_candidate.py slices S --work DIR` | the tree after each lane in review order (what `git rev-parse HEAD^{tree}` should print after each merge) and which added scripts other lanes use |
| `owner_preflight.py EXPECT.json --ref main=REF [--ref LANE=REF]... [--after-merge LANE]` | owner-run, read-only Git checks before and during integration: main still at the rehearsed base, a clean tree, each lane branch holding its sealed tree, the tree after each merge (agents never run it) |
| `integration_receipt.py init/run/record/check/summary/markdown/order/carry` | the `flh-integration-receipt/v1` receipt: lanes (seal, digest, lane tree), pending proposals, and checks (start, exit, seconds, counts, log digest, tree id re-identified after the command). A check on other bytes, or whose artifact changed under the same name, is STALE; a claimed READY with a missing required check is invalid; `carry` brings older results in as STALE |
| `evidence_share.py audit PATH...` / `share SRC --out DIR --include GLOB...` / `verify-seal DIR` | audit outputs for private addresses, session links, home paths, e-mail, AWS identities, keys, env files and databases (classes and value digests, never values); copy a redacted text subset with `REDACTIONS.json`, `SHA256SUMS.redacted` and `REDACTED-COPY.json`; a redacted copy never verifies as the original seal |
| `pin_audit.py TREE` | workflow action pins, digest-pinned `FROM`s, `go.sum`, npm integrity, hash-locked Python locks, Terraform lock hashes (offline) |
| `integration_battery.sh TREE RECEIPT WORK [STAGE...]` | runs go, web, python, speaking, learning, practice, demo, bundle and report on a copy of TREE and records each; `RESUME=1` keeps current passes after an interruption |

Quickstart, from an empty directory (synthetic lanes, no credentials needed):

```bash
mkdir -p ~/flh-quickstart && cd ~/flh-quickstart        # empty
python3 -B -m unittest discover -s <repo>/scripts/release -p 'test_integration_candidate.py'   # tools on synthetic lanes
bash <repo>/scripts/release/control_center_demo.sh ./cc                          # dashboard, preflight, backup, cutover
python3 -I <repo>/scripts/release/release_report.py terminal <repo>/scripts/release/fixtures/release-report/ready/report.json --width 60
```

For a real integration, write the selection (seal directories and pinned digests), then run
`reproduce --expect`, `integration_battery.sh`, and `release_report.py collect --receipt`.

## Reason codes (release and staging tools)

Each tool ends with one short, stable code and its next step. Scripts and the
runbooks match these codes; `scripts/release/test_reason_codes.py` fails when a
code is renamed, removed or added without this table.

| Tool | Code | Meaning | Next step |
| --- | --- | --- | --- |
| `diagnose.py` | `settings-missing` | the settings file does not exist | copy `scripts/daily/daily.env.example`, `chmod 600`, fill it in |
| `diagnose.py` | `settings-readable` | the settings file is readable by others | `chmod 600` it |
| `diagnose.py` | `data-missing` | `FLH_DATA_DIR` does not exist | `mkdir -m 700` it and `chown` it to the service user |
| `diagnose.py` | `data-owner` | `FLH_DATA_DIR` is not owned by the service user | `chown -R` to `FLH_UID:FLH_GID` |
| `diagnose.py` | `data-mode` | `FLH_DATA_DIR` is readable by others | `chmod 700` it |
| `diagnose.py` | `db-readonly` | the service could read but not write `app.db` (`/readyz` 503 `storage_read_only`) | `chmod 600` and `chown` the `app.db*` files, then restart (a running server keeps it open read-only) |
| `diagnose.py` | `db-corrupt` | `integrity_check` fails | restore `"$(backup_tool.py latest <data>.backups)"` |
| `diagnose.py` | `db-newer` | the database has migrations this release does not know | install the newer release again, or restore a backup made by this one |
| `diagnose.py` | `port-busy` | `127.0.0.1:FLH_HOST_PORT` is in use | find it with `ss -ltnp`; stop it or change the port |
| `diagnose.py` | `disk-low` | less free space than twice the database | free space first |
| `backup_tool.py inspect` | `COMPLETE` | sums, integrity and ledger all check | restorable |
| `backup_tool.py inspect` | `INCOMPLETE` | an `.incomplete` copy from a failed backup | never restore it; delete it after inspection |
| `backup_tool.py inspect` | `UNSEALED` | no `SHA256SUMS`: the backup stopped before sealing | take a new backup |
| `backup_tool.py inspect` | `CORRUPT` | a sum mismatch, a listed file missing, or a failed integrity check | use another backup |
| `backup_tool.py inspect` | `NOT_A_BACKUP` | no `app.db` | — |
| `backup_tool.py next-action` | `ok` | every backup is complete | — |
| `backup_tool.py next-action` | `no-backup` | none yet | `flh-daily.sh backup` |
| `backup_tool.py next-action` | `free-space` | an interrupted backup and too little room | free space, then back up |
| `backup_tool.py next-action` | `rerun-backup` | the last backup was interrupted | `flh-daily.sh start`, then `backup` again |
| `backup_tool.py restore-state` | `CLEAN` | nothing left beside the data | — |
| `backup_tool.py restore-state` | `PREPARE-INTERRUPTED` | a staging copy is left; the data and service are untouched | delete the named copy, restore again |
| `backup_tool.py restore-state` | `SWAP-INTERRUPTED` | the data directory is missing, the previous copy exists | `mv` the named previous copy back |
| `backup_tool.py restore-state` | `RESTORED` | the last restore completed; the previous data is kept | check the first write, start |
| `backup_tool.py restore-state` | `NO-ACTIVE-DATA` | no data and no previous copy | restore a complete backup |
| `backup_tool.py unpack` | `DAMAGED` | the archive ends early or is damaged; nothing unpacked | make the archive again on the sending side |
| `backup_tool.py unpack` | `REFUSED` | a wrong SHA-256, an unsafe member, or an existing target; nothing unpacked | copy again or move the target aside |
| `backup_tool.py receipt` | `RECOVERED` | the active data is the backup, intact, writable | start; keep the previous copy for now |
| `backup_tool.py receipt` | `NOT RECOVERED` | the active data is not the backup, or the write check failed | do not start on it |
| `cutover_check.py check` | `HOLD` | steps before the switch are pending | the step named next |
| `cutover_check.py check` | `DO-NOT-SWITCH` | a check before the switch failed | keep the NAS; roll back case A |
| `cutover_check.py check` | `SWITCHED` | AWS is the only writer | keep the NAS stopped for the window |
| `cutover_check.py check` | `ROLLBACK-A` | AWS took no write | NAS settings back, start the NAS |
| `cutover_check.py check` | `ROLLBACK-B` | AWS accepted writes | procedure B only (a NAS restart would discard them) |
| `cutover_check.py check` | `ROLLED-BACK` | the NAS holds the AWS backup's data | point access back to the NAS |
| `cutover_check.py check` | `DIVERGED` | both sides written after the boundary | stop both; never merge |
| `plan_review.py` | `SAME` | two plans make the same changes | — |
| `plan_review.py` | `DIFFERENT` | the plans differ (grouped by service and blast radius) | review the new plan |
| `plan_review.py` | `FRESH` | the plan was made from the current inputs | apply |
| `plan_review.py` | `STALE` | an input changed after the reviewed plan | plan again |
| `plan_review.py` | `NOT COSTED` | a planned type has no rate | add an assumption |

## Troubleshooting

- `bind source path does not exist`: create `FLH_DATA_DIR` first.
- `unable to open database file` in restart-loop logs: the data
  directory is not writable by `FLH_UID:FLH_GID`. Set them to the owner, e.g.
  `FLH_UID=$(id -u) FLH_GID=$(id -g)`.
- Startup configuration errors cause a restart loop under
  `restart: unless-stopped`, rather than a single exit or a stable `unhealthy`
  state. Stop the service, correct the problem, then start it.
  `docker compose logs app` shows configuration errors (for example
  `EXTRACTOR_PROVIDER=openai requires OPENAI_API_KEY to be set`). They never
  include key values.
- A running process whose readiness checks fail can become `unhealthy`; the
  restart policy does not restart it merely for failing healthchecks.
- Port in use: set `FLH_HOST_PORT`; the container port stays `8080`.
