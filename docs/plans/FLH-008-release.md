# FLH-008 — Minimal personal-use release packaging

Owner: Claude Code (implementation). Status: implemented, awaiting Codex review.

## Scope

Owned and changed: `Dockerfile`, `.dockerignore`, `compose.yaml`,
`cmd/server/main.go`, `internal/transport/http/handler.go`,
`internal/transport/http/workbench.go` (+ `workbench_test.go`),
`internal/transport/http/readiness_test.go`, `docs/RELEASE.md`, `README.md`,
`README.zh-CN.md`, `docs/QUICKSTART.md`, `docs/LOCAL_LEARNING_WORKFLOW.zh-CN.md`,
`AGENTS.md`, and this note.

Not touched (FLH-009): `internal/config/`, `.env.example`, `.gitignore`,
`go.mod`, `go.sum`. Also not touched: `web/src`, migrations, `Makefile`, CI.

## Configuration contract used (provisional)

From `docs/plans/FLH-009-env.md`, still marked awaiting review: the server
reads an optional `.env` from its working directory; a key present in the
process environment wins even when empty; empty values behave as unset.
The image's working directory (`/app`) contains no `.env`, so in the
container only the Compose-provided environment applies. Compose forwards
`AI_PROVIDER` (default `rule-based`), `EXTRACTOR_PROVIDER` (`disabled`),
`EMBEDDING_PROVIDER` (`disabled`), and the other provider and timeout keys
from `.env.example` as empty by default. `PORT` and `DB_PATH` are fixed
literals.

If FLH-009 changes key names, defaults, or the empty-means-unset rule,
`compose.yaml`, `docs/RELEASE.md`, and the `.env` wording in both READMEs,
QUICKSTART, and the workflow guide need to be rechecked.

## Evidence (2026-10-07, this machine)

All runs used temporary directories under `/tmp`, host ports 18080–18082, and
separate Compose project names. The daily `data/app.db` was not read, mounted,
or modified; its mtime is unchanged (2026-08-17).

- Go unit tests: `TestWorkbench_*` (7) and `TestReadiness_*` (5) pass. They
  cover root index, asset MIME types, no listings or traversal, `/api` strip,
  root routes unchanged (including `/api` not redirecting), rejection of an
  unusable directory, the real mux behind the prefix, readiness that is
  bounded, hides error detail, and stays independent of liveness.
- Build context, checked by copying it into a throwaway image: 105 files, only
  `cmd`, `internal`, `migrations`, `web` sources, `go.mod`, `go.sum`. No
  `.env`, database, `captures/`, `node_modules`, `dist`, `.git` or tests. The
  only filename match was `migrations/004_create_learning_captures.sql`.
- Image build: `npm ci` (178 packages), `go mod verify` printed
  "all modules verified", build exit 0, 20.4 MB. Runtime user `1000:1000`,
  image env holds only `PATH`, `PORT`, `DB_PATH`. No `.env`, `*.db` or
  `captures` anywhere in the image filesystem.
- Compose: ports `127.0.0.1:18080->8080`, provider defaults as above. Healthy
  after 3 s.
- HTTP:
  - `/healthz`, `/api/healthz`, `/readyz`, `/api/readyz` → 200.
  - `/entries` and `/api/entries` → 200.
  - Unknown, `/api/no-such` and bare `/api` → 404. `/assets/` → 404.
  - `/` → 200 `text/html`, `no-cache`. JS 186,555 B and CSS 9,567 B → 200
    with correct types.
  - The served bundle contains the `"/api"` base.
- Capture:
  - HTTP: new 201, replay 200, modified copy 409.
  - CLI: replay exit 0, conflict exit 1.
  - `GET /api/captures/manual-example-001` → 200.
  - Extraction while disabled → 503.
- Container replacement: after `down` and `up`, the container ID changed
  (`05b4d836dec7` → `10354aa5840b`). Entries and summary JSON were
  byte-identical, and replay still returned 200.
- Lifecycle: `restart`, `stop` (exit 0, graceful "shutting down") and `start`
  were each healthy again within 3 s.
- Backup and restore:
  - Backup taken while stopped: `integrity_check` ok, 8 migrations recorded,
    checksums verified.
  - Restored into a new, empty directory and started as a second project on
    18081, healthy in 3 s.
  - Entries, summary and capture receipt were byte-identical to the source.
  - On the restored instance, replay → 200 and conflict → 409. The source
    instance stayed healthy.
- Missing data directory: `up` exit 1 with "bind source path does not exist".
  The directory was not created.
- Compose `.env` parsing, checked with placeholder values only:
  - Unquoted and double-quoted values expand `$NAME`; single-quoted values are
    literal.
  - Trailing ` # comment` is dropped; `export` is accepted; `a#b` is kept.

## NOT RUN

- Browser interaction with the workbench. No headless or desktop browser was
  found (chromium, chrome, firefox, playwright cache). Static delivery, asset
  types and API routing were checked over HTTP only; React rendering and
  in-page API calls were not exercised.
- OpenAI analyzer and extractor, and the HTTP embedding provider, in the
  container (no paid or real providers used).
- Restore of the real daily database (by design).
- Non-default `FLH_UID`/`FLH_GID`.

## Known risks

- The image builds the frontend with Node 24.11.1; CI uses Node 22. The
  lockfile installed and built cleanly, but the versions differ.
- Compose's `.env` parser is not godotenv. A repo-root `.env` that godotenv
  accepts could still fail or parse differently in Compose; `docs/RELEASE.md`
  documents the observed differences and recommends single quotes.
- Compose prints values in full with a bare `docker compose config`;
  `docs/RELEASE.md` warns against this and gives a redacting check.
- An older image does not refuse a database migrated by a newer image. This
  is documented; no guard was added (out of scope).
