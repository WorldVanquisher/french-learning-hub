# FLH-013 — Release edge-case audit

Owner: Claude Code (audit, read-only). Status: complete, handed off.
Date: 2026-10-07. Scope: merged `Dockerfile`, `.dockerignore`, `compose.yaml`,
`internal/transport/http/workbench.go`, `/readyz` in `handler.go`,
`cmd/server/main.go` wiring, `docs/RELEASE.md`, and the configuration contract
in `docs/plans/FLH-009-env.md`.

**Independence caveat:** the same Claude Code session wrote FLH-008, so this is
a self-audit, not an independent review. A separate Codex review is still
worthwhile.

## Method and isolation

- All runs used a copy of the working tree under `<tmp>`. The copy's `.env`
  was an empty file, `data/`, `captures/`, `.git`, `node_modules` and `dist`
  were excluded, and an override file pointed Compose at a separate
  `flh013-audit:local` image.
- Every run used its own Compose project name (`flh013-*`) and host ports
  18130–18134.
- Planted "secret" files contained only the word `CANARY`, and every env file
  held placeholder values only. The repository `.env` was never opened; only
  its existence and mode were checked.
- No production code was changed, no provider was called, no Git command was
  run, and the daily `data/app.db` was not read, mounted or modified (its mtime
  is still 2026-08-17).
- Cleanup: all `flh013-*` containers, images and temp directories were
  removed. None of the planted paths exist in the real tree. Five
  pre-existing dangling images were left in place; none contains an audit
  canary.

## Summary

| ID  | Area           | Finding | Status | Severity |
| --- | -------------- | ------- | ------ | -------- |
| BR1 | Backup/restore | Restore only lasts until the next plain `up`; then the service silently runs on the old database again | Confirmed | Medium-high |
| BR2 | Backup/restore | The documented daily-database migration fails for the real `data/` layout and copies other databases | Confirmed | Medium |
| X1  | Routing        | Cross-site `text/plain` POSTs from any web page are accepted and write data | Confirmed (2 endpoints) | Medium, pre-existing |
| X2  | Routing        | Any `Host` header is accepted, enabling DNS rebinding | Server behavior confirmed; attack NOT RUN | Medium, pre-existing |
| B1  | Build context  | Secret-like files under allowlisted directories reach the build stages | Confirmed | Low |
| P2  | Permissions    | The database is created world-readable (`644`) | Confirmed | Low |
| R1  | Config/perms   | Startup failures restart-loop; the docs say "unhealthy" / "exits right away" | Confirmed | Low (docs) |
| D1  | Docs           | Requirements omit the host `sqlite3` and `sha256sum` the backup steps use | Confirmed | Low (docs) |

Verified correct, with no defect found: runtime configuration completeness,
provider defaults, fixed `PORT`/`DB_PATH`, no `.env` in the container, the
read-only `/app`, static path handling, and backup integrity.

## 1. Build-context exclusions — complete

**B1 (confirmed, low).** `.dockerignore` allowlists whole directories
(`!cmd/`, `!internal/`, `!web/src/`, lines 7, 8, 17) but denies secret-like
files only by name: `**/.env`, `**/.env.*`, `**/*.db`, `**/*.db-*`
(lines 24–27).

- **Scenario:** 24 canary files were planted in a copy of the tree. Eight
  reached the build context and were copied into the build stages:
  - `internal/`: `*.pem`, `*.key`, `*.sqlite`, `*.sqlite3`
  - `cmd/server/`: `credentials.json`, `.netrc`
  - `web/src/`: `.envrc`, `secrets.json`
- **Not affected:**
  - None reached the runtime image, which copies only the server binary and
    `dist`, and `dist` contained no canary.
  - `.env`, `.env.*`, `*.db`, `*.db-wal`, `data/`, `captures/`,
    `node_modules`, `dist`, `.git`, `bin`, `testdata` and `_test.go` were all
    excluded.
- **Impact:** such files persist in local build-stage layers and the build
  cache. `RELEASE.md` line 26 ("never reach Docker") overstates the guarantee.
- **Suggested verification:** repeat the canary build after either narrowing
  the allowlist (for example `!cmd/**/*.go`, `!internal/**/*.go`; the only
  `go:embed` is in `migrations/`) or adding deny patterns (`**/*.pem`,
  `**/*.key`, `**/*.sqlite*`, `**/.envrc`, `**/.netrc`, `**/*credentials*`,
  `**/*secret*`).

Observation: Docker on this host has no buildx, so the legacy builder was used.
BuildKit's `.dockerignore` matching is expected to be the same but was not
tested.

## 2. Runtime configuration completeness — complete

Confirmed correct:
- The variables Compose passes to the container are exactly the 15 the server
  reads. `FRENCH_HUB_URL` is read only by the capture CLI, so leaving it out is
  correct.
- With an empty env file, the providers resolve to `rule-based`, `disabled`
  and `disabled`. A file that sets `AI_PROVIDER=`, `EXTRACTOR_PROVIDER=` and
  `EMBEDDING_PROVIDER=` to blank resolves to the same defaults.
- A host `PORT=9999` / `DB_PATH=/elsewhere/app.db` is ignored; the container
  keeps `8080` and `/data/app.db`.
- A shell variable overrides the env file.
- Using `.env.example` as the Compose env file yields defaults, with only the
  timeouts set.
- Inside the container, the working directory is `/app`, there is no `.env`,
  the user is uid 1000 and the umask is `0022`.

**R1 (confirmed, low, docs).** With `EXTRACTOR_PROVIDER=openai` and no key,
`restart: unless-stopped` (`compose.yaml` line 46) puts the container into a
restart loop: 7 restarts in about 12 s, and `docker compose ps` shows
`Restarting (1)`. The log line names the missing key but not its value. The
docs say "Stays `unhealthy`" (`RELEASE.md` line 190); the user sees
`Restarting` instead.
- **Suggested verification:** reword the troubleshooting entries, or consider
  `restart: on-failure:N`, then repeat the bad-config start.

Note (by inspection, not run with a value): a key set in the Compose `.env` is
passed into the container even when every provider is disabled, and
`docker inspect` shows it to anyone with Docker access.

## 3. Container file permissions — complete

Confirmed correct:
- `/app/server` and `/app/web` are owned by root and read-only to the app
  user; writing to `/app` fails.
- A missing `FLH_DATA_DIR` makes `up` fail without creating the directory
  (verified in FLH-008).

**UID mismatch (confirmed, part of R1).** With `FLH_UID=1234` on a directory
owned by uid 1000, the container restart-loops on `ping sqlite: unable to open
database file (14)` and creates no files. The cause in `RELEASE.md` line 187 is
right, but the container restarts in a loop rather than exiting once.

**P2 (confirmed, low).** The server creates `app.db`, `-wal` and `-shm` with
mode `644`, and `mkdir -p data/release` gives `755` under the default host
umask. The backup step `cp -a` keeps those modes.
- **Impact:** other local users can read the learning database if the parent
  directories allow it. That wasn't checked for this machine's home directory.
- **Suggested verification:** document `chmod 700` on the data and backup
  directories, or set a stricter umask in the image, then check the modes
  after first start.

## 4. API/static routing boundaries — complete

Confirmed correct:

| Request | Result |
| ------- | ------ |
| `/index.html`, `/favicon.ico` | `404` |
| `/api`, `/api/`, `/API/healthz`, `/api/api/healthz` | `404` |
| `/api/%2e%2e/healthz`, `/api%2Fhealthz` | `404` |
| `/assets/` | `404` (no listing) |
| `/assets` | `307` to `/assets/` |
| `/assets/%2e%2e/index.html` | `301` to `/` |
| `/assets/..%2findex.html` | `301` to `/assets/` |
| `/api//healthz` | `307` to `/api/healthz` (path cleaning) |
| `HEAD /` | `200` |
| `POST /assets/x` | `404` |

No traversal was possible. Readiness is a bounded `SELECT 1` through the
driver's `Ping` (`modernc.org/sqlite` `conn.Ping`).

**X1 (confirmed for two endpoints, medium, pre-existing).** A request with
`Origin: https://attacker.example` and `Content-Type: text/plain`, which
browsers send without a CORS preflight, got `201` from `POST /entries` and
`POST /api/captures`. The handlers decode JSON without checking
`Content-Type` (no check exists in `internal/transport/http`), and nothing
checks `Origin`. No CORS headers come back, so the attacking page can't read
the response.
- **Impact:** any web page the user visits while the service runs can write
  into the learning database.
- **Hypotheses (code inspection only, not run):** the same applies to other
  POST routes, including concept SAME/relation/INVALID/distinction labels,
  which would forge human annotation authority. It also applies to
  `POST /entries/{id}/extractions`, which can cost provider money when
  extraction is enabled. PUT routes need a preflight and are not affected.
- **Browser behavior:** some browsers are adding limits on public sites
  calling localhost. That wasn't tested and shouldn't be relied on.
- **Suggested verification:** after the owner decides on a fix (for example,
  reject a mismatched `Origin` on writes, or require `application/json`), rerun
  the curl probe and confirm the workbench and capture CLI still work. Check
  first which `Content-Type` the CLI sends.

**X2 (server behavior confirmed, medium, pre-existing; attack NOT RUN).**
`GET /api/entries` with `Host: attacker.example:18133` returned `200` with
data.
- **Impact (hypothesis):** a DNS-rebinding page could become same-origin with
  the service and read or write all learning records.
- **Suggested verification:** after any `Host` allowlist (`127.0.0.1:<port>`,
  `localhost:<port>`), repeat the probe and expect `4xx`.

X1 and X2 predate FLH-008, because the API never checked `Origin` or `Host`.
The release makes `127.0.0.1:8080` the documented daily origin, which raises
their practical relevance. Any fix is a backend change for the owner to scope;
it is not authentication.

Hardening observations, not defects: assets have no `Cache-Control` and no
`X-Content-Type-Options: nosniff`. `localhost:<port>` also works and is a
different browser origin from `127.0.0.1`.

## 5. Backup/restore instructions — complete

The documented Backup and Restore commands were run literally in the
isolated copy. Backup integrity was `ok` with matching checksums, and the
restored instance showed exactly the pre-backup data.

**BR1 (confirmed, medium-high).** The Restore section starts the restored
directory with a one-off `FLH_DATA_DIR="./$restore" docker compose up -d`.
`FLH_DATA_DIR` isn't stored anywhere, so any later documented `up` without it
recreates the container on the default `./data/release`. That includes
`docker compose up -d --build` after an image upgrade, which is exactly when
a backup matters.
- **Scenario:**
  1. Write entry A, take a backup, then write B on the old database.
  2. Restore and write C on the restored database.
  3. Run a plain `docker compose up -d`.
  4. The mount is back on `data/release`, the API shows `[A, B]`, and C is no
     longer visible.
- **Impact:** data seems to disappear after a restore. It's actually still in
  `data/release-restored`, but new writes go to the stale database.
- **Suggested verification:** document either restoring into `data/release`
  itself (move the old directory aside first), or saving `FLH_DATA_DIR` in
  the Compose `.env`. Then repeat the A/B/C scenario across `down`/`up` and
  `up --build`.

**BR2 (confirmed, medium).** `RELEASE.md` line 108 says to move the daily
database in by following Restore "with that database directory as the
source". For the daily `data/app.db`, that directory is `data/`, which also
holds `release/`, `local-trial/`, `flh-synthetic-demo/`, `backups/` and the
restore target itself.
- **Scenario (fake files):** `cp -a data/. data/release-restored/` failed with
  "cannot copy a directory into itself" and exit 1. It still left
  `app.db`, `local-trial/app.db`, `flh-synthetic-demo/app.db` and
  `release/app.db` inside the restore target.
- **Impact:** the documented steps have no stop-on-error, so the following
  integrity check and `up` still proceed. The user ends up with a partial copy
  that also contains unrelated private databases, all under one directory.
- **Suggested verification:** give an explicit daily-migration command that
  copies only `data/app.db` (plus any `-wal`/`-shm`) after `make run` has
  stopped. Test it against a fake `data/` layout.

**D1 (confirmed, low, docs).** `RELEASE.md` Requirements list only Docker and
Compose, but Backup and Restore use the host's `sqlite3` and `sha256sum`.

## NOT RUN

- Browser interaction: no browser on this machine. X1 was probed with curl
  only, and X2's DNS-rebinding attack was not executed.
- The other cross-site POST endpoints named under X1 (inspection only).
- Running an older image on a newer database, and an image upgrade that
  applies a new migration: no older or newer image with different migrations
  was available without Git.
- BuildKit or buildx builds (not installed).
- Real provider configurations and real secrets (by design).
- `make verify`: no code changed in this task.

## Inherited risks (not re-tested)

- The image builds the frontend with Node 24.11.1, while CI uses Node 22.
- FLH-009's contract is still marked awaiting review; this audit relied on
  `docs/plans/FLH-009-env.md` as written.
