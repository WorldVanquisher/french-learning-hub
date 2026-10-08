# Personal-use release

One Docker image contains the Go service and the built workbench. Compose runs
it on one browser origin, `http://127.0.0.1:8080`, with a persistent SQLite
directory on the host. This is a local, single-user release: there is no
authentication, so the port is bound to `127.0.0.1` only. Do not publish it to a
network you do not trust.

## Requirements

- Docker with the Compose plugin (verified with Docker 29.7 and Compose 5.5).
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

## First start

The data directory must already exist and be writable by `FLH_UID`. Compose
refuses to start if it is missing (`bind source path does not exist`) instead
of creating it as root.

```bash
mkdir -p data/release
docker compose up -d --build
docker compose ps          # wait for "(healthy)"
```

Open `http://127.0.0.1:8080`. The capture CLI uses the same origin:

```bash
go run ./cmd/capture -url http://127.0.0.1:8080 -file examples/captures/manual-example.json
```

`./data/release` starts as a fresh database. Your existing daily database is
not moved or copied automatically. To use it, stop whatever server uses it,
then follow **Restore** below with that database directory as the source.

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

Back up only while the service is stopped, so SQLite has checkpointed its WAL
and nothing is writing.

```bash
docker compose stop
backup="data/backups/flh-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup"
cp -a data/release/. "$backup/"            # app.db plus any -wal/-shm files
sqlite3 -readonly "$backup/app.db" 'PRAGMA integrity_check;'   # expect: ok
(cd "$backup" && sha256sum * > SHA256SUMS)
docker compose start
```

Copy the whole directory, not just `app.db`. If `-wal`/`-shm` files are
present, they are part of the database. `data/` is ignored by Git, so backups
under `data/backups/` are not committed; copy them off the machine as well.

## Restore

Restore into an empty directory, verify it, then switch to it.

```bash
docker compose stop
restore=data/release-restored
mkdir "$restore"                            # must be new and empty
cp -a "$backup/." "$restore/"
rm -f "$restore/SHA256SUMS"
sqlite3 -readonly "$restore/app.db" 'PRAGMA integrity_check;'
FLH_DATA_DIR="./$restore" docker compose up -d
```

To check a backup without touching the running instance, run a second instance
on another port and project name:

```bash
FLH_DATA_DIR="./$restore" FLH_HOST_PORT=18081 docker compose -p flh-restore-check up -d
curl -s http://127.0.0.1:18081/readyz
docker compose -p flh-restore-check down
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
  into a new directory, and start the older image on that directory. Data
  written after that backup is not carried back.

## Troubleshooting

- `bind source path does not exist`: create `FLH_DATA_DIR` first.
- `unable to open database file`, or the container exits right away: the data
  directory is not writable by `FLH_UID:FLH_GID`. Set them to the owner, e.g.
  `FLH_UID=$(id -u) FLH_GID=$(id -g)`.
- Stays `unhealthy`: `docker compose logs app` shows configuration errors (for
  example `EXTRACTOR_PROVIDER=openai requires OPENAI_API_KEY to be set`). They
  never include key values.
- Port in use: set `FLH_HOST_PORT`; the container port stays `8080`.
