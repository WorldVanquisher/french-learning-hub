# FLH-011 — Merged release acceptance

Date: 2026-10-07 (Canada/Eastern). Owner: Codex. Requested branch label:
`test/flh-011-release-acceptance`; branch/merge ancestry was **not inspected**
(no Git/GitHub commands). This acceptance applies to the supplied working-tree
snapshot, not an independently established commit or branch.

**Result: the exercised release workflow passes.** The image builds, the
container becomes healthy, the workbench and API are served together, capture
idempotency survives container replacement, and a stopped-service backup
restores correctly into a separate directory and project. No production files
were edited. This report is the only repository file created for FLH-011.

## Scope and instructions

Read root `AGENTS.md` and `CLAUDE.md`, `Makefile`, CI workflow,
`Dockerfile`, `compose.yaml`, `.dockerignore`, `docs/RELEASE.md`,
`docs/QUICKSTART.md`, English/Chinese README release/configuration sections,
and `docs/plans/FLH-008-release.md` / `FLH-009-env.md`. No nested AGENTS.md or
CLAUDE.md was found. Inspected the merged server/workbench/configuration
implementations and their existing tests, plus RecordDetail and its retry tests.
`README.zh-CN.md` exists and reflects the release/configuration behavior.

Ownership: only this previously unused report path. No permanent smoke script
was added; temporary Python harnesses and generated outputs live under the
isolated run directory. No contracts, dependencies, migrations, frontend files,
configuration or existing documentation changed.

The existing `.env`, real databases and credential files were not read.
Provider configuration was constructed from an allowlisted clean process
environment, rather than copied from the current shell. Every Compose invocation
used `--env-file /dev/null`; HOME and DOCKER_CONFIG pointed to empty temporary
directories. Analyzer was explicitly local `rule-based` (there is no disabled
analyzer selector); extraction and embedding were explicitly `disabled`.
All provider credential/model/URL/timeout variables were explicitly empty.
The tests use their existing temporary databases and fake/local HTTP providers;
no external model provider was called.

## Merged feature evidence

| Task | Present evidence | Validation |
| --- | --- | --- |
| FLH-008 | Dockerfile/Compose packaging; `cmd/server/main.go:35` web-dir flag, `:121` SQLite readiness wiring, `:126` workbench wrapper; `internal/transport/http/workbench.go` production prefix/static routing | Actual image, health checks, HTTP delivery, replacement and restore below; 7 workbench and 5 readiness tests pass |
| FLH-009 | `internal/config/dotenv.go` optional working-directory file, process-environment precedence, sanitized parser failures; godotenv v1.5.1 in go.mod; README and QUICKSTART configuration wording | 8 focused configuration tests pass, including empty overrides and secret-safe malformed-file errors; only synthetic test .env files used |
| FLH-010 | `web/src/components/RecordDetail.tsx:39` separate effective retry counter; `:93` selected-analysis effect dependency; `:114` retry preserves selected version; `web/src/pages/RecordsBrowser.test.tsx:402` historical retry tests | RecordsBrowser 18 tests pass in the full frontend suite, including historical-version retry and late response after Entry switch |

The implementation notes still say “awaiting review”; these historical status
labels do not establish current integration state. Presence above is determined
from code and executed tests.

## Environment and isolation

- Host: Linux amd64; Go `go1.27.1-X:nodwarf5`; go.mod requires Go 1.26.5.
- Node v26.9.0, npm 12.0.2; existing web/node_modules reused via a symlink.
- Docker client 29.8.1, daemon 29.7.2, Compose 5.5.1.
- SQLite CLI 3.53.4.
- Image stages remain the documented pinned Node 24.11.1 Alpine, Go 1.26.5
  Alpine, and Alpine 3.22.2 digests. CI uses Node 22.
- Run directory: `/tmp/flh-011-0l7f0o4j`, abbreviated `$RUN_DIR` below.
- Source copy: `$RUN_DIR/source`, containing cmd/internal/migrations/web,
  go.mod/go.sum/Makefile/Dockerfile/compose.yaml/.dockerignore. Copy excluded
  `.env*`, databases and sidecars, .git, node_modules, dist and tsbuildinfo.
  Frontend build/typecheck outputs and Go build/cache outputs were isolated.
- Primary Compose project `flh-011-0l7f0o4j`, data `$RUN_DIR/data`,
  host port 18111. Restore project `flh-011-0l7f0o4j-restore`, separate data
  `$RUN_DIR/restored`, port 18112. Both bind loopback only.
- Image override: `services.app.image=french-learning-hub:flh-011-0l7f0o4j`.
  The default local release tag was not replaced. Runtime user was `1000:1000`.

## Commands actually executed

Read-only inspection used `cat`, `sed`, `rg`, `nl`, `ls`, `id`, version commands
and `go env GOMODCACHE`. The initial unprivileged Docker daemon probe failed
with socket permission denied; elevated daemon access subsequently succeeded.
No automatic approval rejection remained outstanding.

The temporary `$RUN_DIR/run.py` runs subprocesses from `$RUN_DIR/source` with
only PATH, temporary HOME/DOCKER_CONFIG/GOCACHE, the existing Go module cache,
`GOFLAGS=-buildvcs=false`, provider selectors/empty provider settings and these
release settings: FLH_UID=1000, FLH_GID=1000, FLH_HOST_PORT=18111,
FLH_DATA_DIR=$RUN_DIR/data. Its Compose shorthand expands to:

```sh
docker compose --env-file /dev/null -p flh-011-0l7f0o4j   -f "$RUN_DIR/source/compose.yaml" -f "$RUN_DIR/override.yaml"
```

Executed verification/start commands (all exit 0):

```sh
python3 "$RUN_DIR/run.py" make verify
python3 "$RUN_DIR/run.py" compose up -d --build
python3 "$RUN_DIR/run.py" go test ./internal/config ./internal/transport/http   -run 'Test(Load.*DotEnv|ProcessEnvironment.*DotEnv|EmptyPlaceholder.*|DotEnv.*|MalformedDotEnv.*|UnreadableDotEnv.*|SingleQuotedDotEnv.*|Readiness_.*|Workbench_.*)' -count=1 -v
python3 "$RUN_DIR/run.py" go build -o "$RUN_DIR/server" ./cmd/server
python3 "$RUN_DIR/run.py" go build -o "$RUN_DIR/capture" ./cmd/capture
python3 "$RUN_DIR/smoke.py"
python3 "$RUN_DIR/extra.py"
```

The first smoke harness invocation had a Python quoting SyntaxError before any
HTTP checks. Corrected the temporary harness and reran successfully. This was
an acceptance-harness error, not an application failure.

The successful smoke harness used urllib HTTP requests with 5-second timeouts,
asserted status codes, and compared response bytes. It executed the following
Compose sequence, with the shorthand above and the clean environment:

```text
ps -q app → inspect health until healthy
up had already been executed with --build
down → up -d → ps -q app → inspect health
stop → inspect exit code
start → inspect health
restore project: up -d → ps -q app → inspect health
restore project: down
primary project: down
extra confirmation: up -d --wait --wait-timeout 40 → down
```

Inspections were limited to task-owned container health, user, port bindings,
exit code and known provider environment; image inspection requested its ID.
Restore Compose commands used the same files/image with project suffix
`-restore`, FLH_DATA_DIR=$RUN_DIR/restored and FLH_HOST_PORT=18112.

Stopped-service copy/validation commands actually executed:

```sh
cp -a "$RUN_DIR/data/." "$RUN_DIR/backup/"
sqlite3 -readonly "$RUN_DIR/backup/app.db" 'PRAGMA integrity_check;'
# Python SHA-256 over every backup file generated SHA256SUMS.
(cd "$RUN_DIR/backup" && sha256sum -c SHA256SUMS)
cp -a "$RUN_DIR/backup/." "$RUN_DIR/restored/"
# Python unlinked restored/SHA256SUMS before startup.
sqlite3 -readonly "$RUN_DIR/restored/app.db" 'PRAGMA integrity_check;'
"$RUN_DIR/capture" -url http://127.0.0.1:18111 -file "$RUN_DIR/payload.json"
```

Backup and restored directories were created new and empty. Copies included
the entire database directory, as documented; clean stop left only app.db in
this run. The CLI replay exited 0 and reported entry_id=1, created=false.

Synthetic capture payload used throughout:

```json
{"schema_version":"learning_capture_v1","capture_id":"flh-011-release-acceptance","source":"manual","original_input":"vouloir","original_context":"Isolated FLH-011 synthetic capture","discussion_summary":"Synthetic release acceptance"}
```

Reproduction: POST that payload to `/api/captures` on a fresh isolated service;
repeat it at `/captures`; change only original_input to `different` and POST
again to `/api/captures`. Expected/actual statuses are 201, 200, 409. Repeat the
last two after replacement/restoration. See the result table below.

## Actual results

| Check | Actual evidence |
| --- | --- |
| make verify | Exit 0: Go formatting clean; all 9 tested Go packages pass; vet passes; server/capture builds; frontend typecheck, tests and production build pass |
| Frontend tests | 7 files, 67 tests pass, including all 18 RecordsBrowser tests |
| Additional focused Go tests | 8 configuration + 5 readiness + 7 workbench top-level tests pass (plus configuration subtests) |
| Separate executable builds | Both server and capture build commands independently exit 0 |
| Image build/start | Exit 0; image `sha256:a6fae8eb7c4f84c253787c383b549460eb450d808a13b7e9755bb461b37fa301`; healthy container; loopback 18111→8080 |
| Build details | Classic builder used; web/npm ci and Go module download/verify layers were cached; Go server source compiled in this build |
| Workbench | `/` 200 text/html, 423 bytes, Cache-Control=no-cache; JS `/assets/index-BKHiT2gr.js` 200 text/javascript, 186555 bytes; CSS `/assets/index-DFicoYRm.css` 200 text/css, 9567 bytes; JS contains the `/api` base |
| Routing | `/entries` and `/api/entries` 200; prefixed inventory/quality/comparison endpoints 200; `/api`, unknown root/prefixed routes and `/assets/` 404, with no SPA fallback/listing |
| Health | `/healthz` and `/api/healthz` 200 `status=ok`; `/readyz` and `/api/readyz` 200 `status=ready`; Docker health transitions to healthy |
| Health error semantics | Existing tests verify 503 not_ready, no leaked detail, bounded cancellation, missing readiness callback, and independent healthy liveness |
| Capture | New 201 (entry 1, no analysis), identical replay 200, conflicting replay 409; receipt readable; conflict leaves the original payload intact in subsequent snapshots |
| Providers | Actual task container selectors rule-based/disabled/disabled, credential variables empty; explicit POST `/api/entries/1/extractions` 503 `knowledge extraction is not enabled`; comparison represents embedding as unavailable with null metrics |
| Replacement | Container ID changed `088eaac113af…`→`497624118d68…`; entries, inventory, summary and receipt byte-identical; replay/conflict still 200/409 |
| Clean stop/backup | Container exit 0; copied while stopped; backup integrity_check `ok`; app.db checksum verifies |
| Restore | Separate directory/project on 18112 healthy; integrity_check `ok`; all four HTTP snapshots byte-identical; replay/conflict 200/409; original service simultaneously ready |
| Cleanup | Both task-owned projects/containers/networks removed; evidence, isolated databases/backups and dedicated image retained for review |

Logs retained under `$RUN_DIR/logs`: verify.log, build-start.log, focused.log,
smoke.log and extra.log; structured smoke observations in smoke-results.json.
The smoke logger mislabeled its first extraction POST as GET because the empty
JSON object was falsey; urllib sent POST because request data was supplied.
extra.log independently confirms an explicit POST and its 503 response.

## Confirmed failures, risks and NOT RUN

**Confirmed application failures:** none in the exercised acceptance workflow.
No P0/P1 release failure was reproduced.

**Environment limitation:** Docker warned that buildx is missing and fell back
to the classic builder. Build/start still succeeded. Installing buildx is not
required for the current Dockerfile, but modern-builder behavior remains
unverified here.

**Inspection risk (P2):** `Makefile:53–56` runs the server and capture builds in
one shell separated by semicolons without `set -e`/`&&`. A failed server build
could be masked by a succeeding capture build. Both builds passed independently
here, and the container server compiled successfully; this is not an observed
build failure in this run. Recommended validation: in an isolated copy inject a
server-only compiler failure and require make verify to exit nonzero.

**NOT RUN / boundaries:**

- Interactive browser rendering, clicks and browser-issued production API calls.
  HTTP delivery/routing was tested against the real image; React behavior was
  covered by existing jsdom tests, including FLH-010. A browser smoke remains
  useful before daily use.
- Live-container SQLite failure injection and negative readiness transition.
  Error/cancellation/liveness contracts are verified through existing Go tests,
  not through destructive runtime database manipulation.
- A no-cache image rebuild or fresh host npm ci. The successful image build
  reused locked dependency/frontend layers; make verify used installed frontend
  dependencies. Fresh package downloads and BuildKit were not independently
  exercised in this pass.
- Off-machine backup transfer, actual daily-database restoration, older-image
  rollback against upgraded data, non-1000 UID/GID, load testing and remote
  deployment. Restore used only the synthetic database on this host.
- External analyzer/extractor/embedding providers, by explicit task constraint.
- Git state, branch membership and merge ancestry, by explicit task constraint.

Recommended follow-ups (at most five):

1. Run a browser smoke against the built release: open Learning Records, select
   historical Analysis, simulate effective-request failure and Retry; confirm
   the failed historical version remains selected and requested.
2. Validate a no-cache build with buildx and locked dependency installation in
   an isolated environment.
3. Harden the Makefile build recipe to propagate either build failure, with
   isolated failure-injection validation, under separate implementation ownership.

## Handoff

Only `docs/validation/FLH-011-release-acceptance.md` was created. No production
code/configuration or shared documentation changed. Task-owned services are
stopped; further implementation is deferred to review/human ownership. Final
`docker ps -a --filter label=com.docker.compose.project=<task-project>
--format '{{.Names}}'` checks returned no containers for either project. A
Python SHA-256 comparison of 179 copied source/build-input files with the
current working tree found no differences.

Human-only staging command (not executed):

```sh
git add -- docs/validation/FLH-011-release-acceptance.md
```

Suggested commit message:
`docs: record FLH-011 release acceptance evidence`
