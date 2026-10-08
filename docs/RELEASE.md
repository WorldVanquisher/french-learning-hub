# Personal-use release

One Docker image contains the Go service and the built workbench. Compose runs
it on one browser origin, `http://127.0.0.1:8080`, with a persistent SQLite
directory on the host. This is a local, single-user release: there is no
authentication, so the port is bound to `127.0.0.1` only. Do not publish it to a
network you do not trust.

## Requirements

- Docker with the Compose plugin (verified with Docker 29.7 and Compose 5.5).
- Host `sqlite3` and GNU `sha256sum` for integrity and checksum checks; Bash
  for the fail-fast recovery blocks below.
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
| `GET /readyz`        | readiness: SQLite ping bounded to 2 s; `503 not_ready` on failure |

The workbench never changes the URL path, so there is no SPA fallback. Without
`-web-dir` the server is API-only, exactly as `make run`.

The container healthcheck polls `/readyz` every 15 s (1 s during a 20 s start
period, 3 s timeout, 3 retries). `docker compose ps` shows `healthy` once SQLite
answers.

## Configuration

`compose.yaml` passes configuration explicitly:

- `PORT=8080` and `DB_PATH=/data/app.db` are fixed. A host `DB_PATH` or `PORT`
  is ignored, so the container cannot be pointed at another database by
  accident.
- `HTTP_ALLOWED_HOSTS` and `HTTP_TRUSTED_ORIGINS` are forwarded for the browser
  boundary described below. Empty values use the server defaults.
- Only these provider variables are forwarded, with the server's defaults:
  `AI_PROVIDER` (`rule-based`), `EXTRACTOR_PROVIDER` (`disabled`),
  `EMBEDDING_PROVIDER` (`disabled`), and `OPENAI_API_KEY`, `OPENAI_MODEL`,
  `OPENAI_BASE_URL`, `OPENAI_TIMEOUT`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`,
  `EMBEDDING_BASE_URL`, `EMBEDDING_TIMEOUT`, `HTTP_READ_TIMEOUT`,
  `HTTP_WRITE_TIMEOUT`, which default to empty. Empty means unset, so the
  server applies its own defaults (see [`.env.example`](../.env.example)).
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
blocking `text/plain` alone would not prevent DNS rebinding.

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
`up --build` keep selecting it. Preserve the old directory by renaming it;
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
docker compose up -d --force-recreate
```

If the second rename fails, leave the service stopped and move `old` back to
`active` before retrying. On earlier errors, the original active directory is
untouched; inspect the failed staging directory before removing it. Preserve
`old` for review. Check `/readyz` and expected records after starting.

For an independent backup check, copy into another private directory, validate
it as above, then use a separate project and port. This is a test instance,
not the durable restore procedure:

```bash
: "${check_dir:?Set check_dir to the separately copied and validated directory}"
FLH_DATA_DIR="$check_dir" FLH_HOST_PORT=18081 docker compose -p flh-restore-check up -d
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
