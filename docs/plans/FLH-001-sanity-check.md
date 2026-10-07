# FLH-001 — Bounded engineering sanity check

Date: 2026-10-07 (America/Toronto). Owner: Codex. Scope: verification only; no fixes.

## Outcome and ownership

The documented release verification passed in an isolated source copy after accommodating environment restrictions. Independent server/capture builds passed. The real HTTP capture workflow passed with and without imported Analysis, including identical replay, conflicting replay and persistence after clean restart. No P0 data-integrity or capture-workflow failure was observed.

Confirmed findings: one P1 verification defect (server-build failure can be masked), one P1 production deployment/documentation gap, and a P2 install-documentation inconsistency. Missing late-write rollback evidence is a P2 suspected risk, not a demonstrated integrity defect. Four follow-up tasks are proposed below.

Only this report was created. The destination did not exist at initial inspection or before writing; exclusive creation prevents overwriting another session. The plans directory was absent and was created for this owned file. Application source, migrations, manifests, lockfiles and existing documentation were not edited. SHA-256 comparison of 168 inspected source/documentation/configuration files found no changes before report creation. This is a bounded content check, not a Git status inspection or a guarantee against subsequent concurrent edits.

## Instructions and actual module responsibilities

Before checks, read root CLAUDE.md (a symlink to AGENTS.md), AGENTS.md, README.md, README.zh-CN.md, Makefile, .github/workflows/ci.yml and docs/QUICKSTART.md. A filesystem search excluding dependencies and VCS directories found no nested CLAUDE.md/AGENTS.md. Also inspected web/README.md, toolchain manifests, configuration, server composition, routes, SQLite transactions, and relevant tests. Current on-disk instructions include updated role/ownership guidance; this task's explicit read-only scope controls.

| Module | Responsibility |
| --- | --- |
| cmd/server | Configuration, repositories/providers/services, HTTP listener and graceful shutdown |
| cmd/capture, internal/captureclient | File/stdin HTTP transport; no model calls or domain rewriting |
| internal/domain | Entities, validation, identity/annotation semantics and small interfaces |
| internal/application | Use cases, effective projections, admission and dataset/evaluation orchestration |
| internal/storage/sqlite, migrations | Persistence, transaction boundaries, embedded migrations and ledger |
| internal/transport/http | DTOs, routing, request adaptation and safe status/error mapping |
| internal/analyzer, extractor, embedding | Local analyzer and independent optional provider adapters |
| web/src/api, pages/components | Fetch client, human annotation and read-only inspection/report views |

Entry owns original input/context; Analysis owns versioned interpretation. unit_concept_memberships owns CURRENT SAME; historical links are append-only evidence. This pass introduced no authority or business behavior.

## Environment and isolation

| Toolchain | Requirement / observed version |
| --- | --- |
| Go | go.mod declares 1.26.5; installed go1.27.1-X:nodwarf5 linux/amd64; GOTOOLCHAIN auto |
| Node/npm | Node v26.9.0, npm 12.0.2; CI uses Node 22; frontend package declares no engines policy |
| Frontend dependencies | Existing Vite 5.4.21, Vitest 2.1.9; their Node engine ranges allow 18 or >=20; jsdom requires >=18 |
| Make | GNU Make 4.4.1 |
| HTTP tooling | curl 8.22.0; smoke harness used Python urllib |
| Harness/DB inspection | Python 3.14.7, stdlib sqlite3 |
| Platform/storage | Linux x86_64; modernc.org/sqlite v1.54.0 embedded pure-Go, no SQLite server/CGO requirement |

A unique temporary directory held copied cmd/, internal/, migrations/, examples/, frontend source/configuration, Go manifests and Makefile. Existing web/node_modules was reused through a symlink. No dependency installation or upgrade occurred; clean npm ci and installed dependency/lockfile equivalence remain unverified. Task binaries, frontend outputs, temporary smoke scripts/logs and synthetic DBs were placed in the temporary copy. No repository-wide mutating formatter ran.

Backend subprocesses received a constructed environment with temporary DB_PATH, unused ports, AI_PROVIDER=rule-based, EXTRACTOR_PROVIDER=disabled and EMBEDDING_PROVIDER=disabled; credentials were not inherited. Only task-started processes were stopped, using SIGTERM and bounded waits. Both capture-run backend instances exited 0; all frontend-check processes also stopped. No user's database, .env or credential file was read. Provider tests use local httptest servers/fakes, not paid providers.

No Git/GitHub command was explicitly issued. A standalone Go build unexpectedly failed during Go's automatic VCS stamping lookup; subsequent builds and final verification explicitly disabled stamping with GOFLAGS=-buildvcs=false. CI's Git whitespace check was inspected but not executed.

## Commands actually executed

$TASK_DIR below means the unique temporary workspace; machine-specific paths are deliberately omitted. Inspection used rg --files, rg -n, find, cat, sed, nl, ls and Python pathlib/hashlib. Inspected make -n verify before execution. Version commands: go version, go env GOVERSION GOTOOLCHAIN, node --version, npm --version, make --version, curl --version, python3 --version and uname -sm.

| Executed command/check | Result |
| --- | --- |
| make verify in temporary copy | Environment blocker: default Go cache read-only; stopped at tests |
| GOCACHE="$TASK_DIR/go-cache" make verify | Environment blocker: sandbox denied httptest local sockets. SQLite, application/domain/config tests passed; socket-dependent packages failed to start servers |
| Same command with local sockets permitted | Exit 0, complete release workflow passed |
| Standalone server/capture builds | Initial attempts failed during automatic VCS stamping; not application compile defects |
| GOFLAGS=-buildvcs=false GOCACHE="$TASK_DIR/go-cache" go build -o "$TASK_DIR/server" ./cmd/server | Exit 0 |
| Same independent build for ./cmd/capture, output "$TASK_DIR/capture" | Exit 0 |
| GOFLAGS=-buildvcs=false GOCACHE="$TASK_DIR/go-cache" make verify with local sockets permitted | Final exit 0; all stages passed |
| python3 http-smoke.py | First temporary harness incorrectly JSON-decoded a plain-text 404; own server stopped in finally. Corrected harness and new DB: exit 0, 34 recorded checks passed |
| python3 frontend-smoke.py | Exit 0; Vite preview API JSON 200, plain static API HTML 404 |
| /bin/sh build-recipe simulation | Server command simulated exit 42, capture exit 0; combined recipe incorrectly exit 0 |
| Python protected-file hash comparison | 168 inspected files unchanged |

Successful make verify ran gofmt -l . (read-only), go test ./..., go vet ./..., temporary server/capture builds, npm run typecheck, npm test and npm run build. All Go packages passed; the final run reused the task's successful test cache, while the earlier permitted full run executed socket-dependent tests. Frontend: 6 test files, 39 tests passed. Vite built 42 modules. No remaining check failure after environmental accommodations.

Temporary evidence files: release-verify.log, release-verify-isolated-cache.log, release-verify-network-enabled.log, release-verify-final.log, http-smoke-results.json, server-smoke.log, frontend-smoke-results.json and frontend-smoke.log. These are not staging candidates. Material outcomes are preserved here independently of their retention.

## Real HTTP capture evidence

Synthetic source was manual; French input included accents. IDs: flh-001-source (no Analysis) and flh-001-analysis (morphology Analysis, confidence 0.9). Completed run used port 37111, discovered by binding port 0; restart reused its port/database.

| Operation | Expected / actual |
| --- | --- |
| Health | HTTP 200, status ok: passed |
| New POST /captures | 201, created true: passed for both |
| GET /captures/{capture_id} | 200, matching Entry/Analysis references: passed |
| GET /entries/{id} | Exact original French input/context: passed |
| GET /entries/{id}/analyses | Zero or one version-1 Analysis: passed; imported:manual:learning_capture_v1 provenance |
| Identical replay | 200, created false, stable IDs: passed |
| Changed original_input, same capture_id | 409; existing Entry unchanged: passed |
| Real capture CLI file replay | Exit 0, idempotent-replay summary: passed for both |
| SIGTERM, wait, restart, repeat reads/replay/conflict | Content/IDs persist; 200 replay and 409 conflict: passed for both |
| Disabled extraction for analyzed Entry | 503, no persisted extraction: passed |
| Quality/comparison report GETs | HTTP 200 on fresh-data state |
| GET /api/concepts directly on Go | 404: confirms need to strip prefix in forwarding layer |

After two clean server lifecycles: 2 learning_entries, 1 entry_analyses, 2 learning_captures, 8 schema_migrations, 0 knowledge_extractions. PRAGMA integrity_check = ok; PRAGMA foreign_key_check returned no rows.

Reproduce using independently built binaries, a fresh temporary DB, an unused port and the following prepared file. Repeat POST identically, then change original_input while retaining capture_id. Read the returned Entry ID. SIGTERM only the server you started, wait for exit, restart with the same DB, and repeat read/replay/conflict.

```json
{"schema_version":"learning_capture_v1","capture_id":"flh-001-source","source":"manual","original_input":"Pourquoi dit-on je vais ?","original_context":"Étude du verbe aller au présent."}
```

```sh
AI_PROVIDER=rule-based EXTRACTOR_PROVIDER=disabled EMBEDDING_PROVIDER=disabled \
  DB_PATH="$TASK_DIR/smoke.db" PORT="$PORT" "$TASK_DIR/server"
# Separate terminal:
curl -i -H 'Content-Type: application/json' --data-binary @"$TASK_DIR/capture.json" \
  "http://127.0.0.1:$PORT/captures"
curl -i "http://127.0.0.1:$PORT/captures/flh-001-source"
```

## Existing tests and important evidence gaps

All listed tests are existing suite evidence; FLH-001 added no test suite.

| Area | Test inventory / evidence | Limits |
| --- | --- | --- |
| Extraction | internal/application/knowledge_service_test.go:109 onwards: disabled, eligibility, corrected/original source, admission, provider failures. internal/transport/http/knowledge_integration_test.go:82: HTTP→service→SQLite with stub extractor. internal/extractor/openai_test.go:171 onwards: multiple/zero units, validation, timeout/cancellation, safe errors with mock provider | No real provider quality/configuration tested; default production extraction remains disabled |
| Extraction persistence | internal/storage/sqlite/knowledge_repository_test.go:51 onwards: zero/multiple units, versions/provenance, cross-entry analysis/feedback rejection, immutable older extraction | AtomicRollbackOnBadRecommendationCount at :241 returns before BeginTx; no injected unit/recommendation insert failure found |
| Concept creation | internal/storage/sqlite/concept_repository_test.go:656: seed success; :738 refuses existing membership without changing history/preferred. concept_invalid_distinct_test.go:443: INVALID seed rolls back inserted concept. HTTP concept_integration_test.go:155 | Missing-unit CreateAndAttachRollsBack at :686 rejects before concept insertion; other tests provide post-insert semantic-conflict coverage |
| SAME correction | concept_repository_test.go:166, :223, :251: moved membership, append-only history/back-pointer, human correction of automatic SAME, preferred-unit clearing. HTTP concept_integration_test.go:299 | No injected late reassignment write failure found; no real browser correction session |
| INVALID/restore | concept_invalid_distinct_test.go:30, :91, :125, :198, :488: unresolved invalidation, idempotence, restored history, membership clear, explicit later SAME. HTTP concept_invalid_distinct_integration_test.go:69 includes restore/queue re-entry, :211 membership clear. domain/effective_annotation_test.go:140 prevents resurrecting cleared SAME | No late failure injection across judgment/history/membership/preferred writes found |
| Rollback | capture_repository_test.go:225 drops analysis table; :253 abort trigger fails receipt after Entry/Analysis inserts and verifies no surviving rows. Concept INVALID/existing-membership seed tests check partial-state rollback | Capture has genuine storage fault injection; extraction and SAME/INVALID need narrower late-write evidence |
| Migration/reopen | migration_ledger_test.go:87, :145; migration_upgrade_test.go:47: reopen and historical fixture upgrades | No real user DB inspection or crash/power-loss recovery claim |
| Frontend | ReviewQueue.test.tsx:8 tests cover rendering/empty, unresolved INVALID, DISTINCT→NEW and discovery authority. api/client.test.ts:19 tests include reassign, restore, rejection and 409 mapping | No component-level stale-membership/409 refresh or restore interaction coverage found; mocks do not establish deployment |

SQLite test locations in the table are under internal/storage/sqlite unless otherwise stated; HTTP integration tests are under internal/transport/http; frontend tests under web/src/pages and web/src/api. The successful suite covers both domain semantics and real SQLite/HTTP integration with deterministic stubs, distinct from production-binary capture smoke evidence.

## Findings and recommended validation

P0 = data integrity/core workflow failure. P1 = daily-use/release blocker. P2 = usability/maintenance improvement. No P0 confirmed.

### F1 — P1 confirmed defect: release verification masks server-build failure

Location: Makefile:53–56. Two builds share a shell recipe without fail-fast behavior or explicit chaining.

Reproduction actually executed: the same /bin/sh recipe with a function replacing go, returning 42 for ./cmd/server and 0 for ./cmd/capture. Combined exit = 0. Expected: failure of either required build fails verification. Actual: first failure is masked by second success. Impact: false-green release check. Independent real builds passed in this task; this finding is about failure propagation, not a current compile defect.

Recommended validation: after the assigned owner changes the recipe, simulate each binary failing independently and require make verify nonzero; then confirm normal builds succeed.

```sh
# Isolated simulation only: no application or Makefile edits.
/bin/sh <<'SH'
go() { case "$*" in *./cmd/server*) return 42;; *) return 0;; esac; }
verify_dir="$(mktemp -d)"
trap 'rm -rf "$verify_dir"' EXIT
go build -o "$verify_dir/server" ./cmd/server
go build -o "$verify_dir/capture" ./cmd/capture
SH
# Observed shell exit: 0; expected nonzero.
```

### F2 — P1 confirmed production deployment/documentation gap

Locations: web/src/api/client.ts:49 (fixed /api), web/vite.config.ts:16–23 (runtime proxy), internal/transport/http/handler.go:119 (unprefixed routes), web/README.md:15–58 and docs/QUICKSTART.md (local guidance).

Reproduction actually executed: build assets; serve isolated dist with Python SimpleHTTPRequestHandler; GET / = 200, GET /api/concepts = 404 HTML. Direct Go GET /api/concepts = 404. Start Vite preview with FRENCH_HUB_URL pointing at isolated backend: /api/concepts = JSON 200, {"concepts":[]}.

Expected for a release: a documented supported serving arrangement connecting built assets and API. Actual: development and preview forwarding work, but no production serving/reverse-proxy arrangement was found in inspected repository files. Installed Vite preview inherits server.proxy; claiming preview lacks forwarding would be incorrect. Plain static hosting requires additional routing.

Impact: dist-only deployment breaks data access despite green build/tests. This is a readiness/documentation gap, not proof an uninspected external deployment is broken. Recommended validation: select/document one production serving path, then test built assets and API through that path, requiring JSON rather than HTML and one safe synthetic write.

### F3 — P2 suspected integrity risk / missing late-write evidence

Locations: internal/storage/sqlite/knowledge_repository_test.go:241, knowledge_repository.go:42, and correction/INVALID repositories/tests.

Inspection reproduction: count-mismatch extraction test rejects before opening a transaction. Production code does have transaction/deferred rollback; no integrity failure was demonstrated. Capture tests inject real storage failures; concept seed-conflict tests check rollback after insert.

Expected evidence: late failure preserves all related rows/projections. Actual: strong happy-path/semantic-conflict checks, but no unit/recommendation insert or late SAME/INVALID multi-write failure injection found. Impact: atomic-failure guarantees are less directly evidenced than capture. Recommended validation: a few isolated abort-trigger tests after initial writes, checking extraction/unit/recommendation counts and membership/history/preferred/judgment invariants. Pre-write rejection is not rollback evidence.

### F4 — P2 confirmed install-documentation inconsistency / toolchain validation gap

Locations: web/README.md:31 recommends npm install; docs/QUICKSTART.md:35–40 and both root READMEs use npm ci. .github/workflows/ci.yml uses Node 22; web/package.json has no engines policy; go.mod declares 1.26.5.

Reproduction: compare first-install commands and CI toolchains with observed versions above. Expected: one reproducible first-run path and a clear supported runtime policy. Actual: inconsistent install commands; this pass used newer Go/Node and existing dependencies. Impact: reproducibility uncertainty, not demonstrated incompatibility. Recommended validation: align locked-install guidance and supported Node policy, then verify declared Go/CI Node with clean npm ci. No upgrade is required by this finding.

## Unverified checks and follow-up tasks

Unverified: clean npm ci and dependency/lockfile equivalence; exact Go 1.26.5/Node 22 execution; remote CI; production deployment; real browser annotation end-to-end; paid-provider output quality; crash recovery/production backup and restore; exhaustive concurrency/fault injection. CI's Git whitespace check was intentionally omitted. Passing checks do not establish these outcomes.

At most four follow-up tasks, in order:

1. Fix/test each binary build's failure propagation in make verify (F1).
2. Implement/document one production frontend/API serving path with built-asset HTTP smoke validation (F2).
3. Add targeted late-write rollback tests for extraction and SAME/INVALID operations (F3).
4. Align install/toolchain guidance and rerun on documented/CI versions with clean locked dependencies (F4).

No implementation ownership transfers implicitly to the other Claude session. These are handoff tasks requiring explicit assignment. All six requested check areas were completed without fixes or a comprehensive new test suite; the pass stayed below its 60–90 minute ceiling.
