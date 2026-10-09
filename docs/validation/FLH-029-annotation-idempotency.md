# FLH-029 integrated verification — 2026-10-08

Implementation owner: NAS Codex, sole writer. Actual working directory was the
provided `flh-nas-codex` workspace. No Git/GitHub commands, delegation, real data,
real `.env` reads or paid providers were used. Editing stopped after verification
and this evidence report for human review.

## Contract and compatibility

The [exact contract](../plans/FLH-029-annotation-idempotency.md) covers only
DISTINCT and BROADER/NARROWER/RELATED POSTs. Optional canonical UUID keys are
normalized to lowercase and scoped globally to the database. Action, unit ID,
concept ID and exact relation form canonical typed payload equivalence. A replay
returns the original HTTP 201 event; conflicting valid payload/action returns
409 with no writes. Receipt lookup returns committed historical attribution;
404 is unknown, never canceled or safe to duplicate using a new key.

Migration 009 is additive; allocation was inspected through migration 008.
Receipt and annotation event share a transaction and SQLite writer lock. No old
migration, label, authority projection or unkeyed response was rewritten.
Receipts survive restart and must be retained with the database/backups. Running
an older service does not provide this keyed contract; restoring an older backup
can lose newer receipts/events. No receipt expiration or cancellation API exists.

The client saves minimal versioned operation identity before writing and restores
it on reload. Explicit retry keeps the original key and payload even after
selection edits. New deliberate decisions get new keys. Storage failure blocks
new keyed submissions with a visible notice. Receipt attribution and current
backend-authority refresh are separate, including refresh failure after commit.

## Actual checks

| Check | Result |
| --- | --- |
| Native targeted SQLite/HTTP tests | PASS after enabling authorized local sockets; initial sandbox listener attempt was blocked |
| Project-pinned Go 1.26.5 targeted tests | PASS |
| Project-pinned `go mod verify` | PASS |
| Project-pinned full `go test ./... -count=1` | PASS |
| Project-pinned `go vet ./...` and server/capture builds | PASS; built binaries identify Go 1.26.5 |
| Final root `make verify`, using Go 1.26.5 | PASS: formatting, all Go tests/vet, both builds, frontend typecheck/tests/build |
| Frontend test suite | PASS: 16 files, 198 tests |
| FLH-028 proxy unit tests | PASS: 5 tests |
| Updated FLH-028 response-loss harness | PASS: 128 cases using native Go 1.27.1-X:nodwarf5; cleanup verified |
| Real-browser verification | **NOT RUN**: no Chromium/Chrome/Firefox executable, Playwright package or browser tool available |

Commands executed included:

```sh
# Existing dependency lockfile only; npm ci does not upgrade dependencies.
(cd web && npm ci --cache /tmp/flh029-npm-cache --ignore-scripts)
GOCACHE=/tmp/flh029-go-cache go test ./internal/storage/sqlite ./internal/transport/http
python3 /tmp/flh029-go126.py
NODE_OPTIONS=--no-experimental-webstorage npm --prefix web run typecheck
NODE_OPTIONS=--no-experimental-webstorage npm --prefix web test -- --reporter=dot
python3 -B scripts/validation/flh028/test_proxy.py
PATH=/tmp/flh029-bin:$PATH python3 -B scripts/validation/flh028/reproduce.py --report /tmp/flh029-response-loss-pinned.json
PATH=/tmp/flh029-bin:$PATH NODE_OPTIONS=--no-experimental-webstorage make verify
```

The temporary `go` wrapper invokes the Dockerfile's digest-pinned Go 1.26.5
image with `--network none`, the installed read-only module cache and temporary
build cache/output. It sets `-mod=readonly -buildvcs=false`; it never inspects VCS.
The isolated Go verification script copied only backend source, migrations and
module manifests. Its full uncached check log is in
`/tmp/flh-029-go126-4jdroogq/go126.log`. Final release-check output is in
`/tmp/flh029-verify-final.log`.

Evidence correction (FLH-033): the response-loss command above did **not** use
that wrapper. FLH-026 resets PATH to `/usr/local/bin:/usr/bin:/bin`; retained
`/tmp/flh029-response-loss-pinned.json` records `go version
go1.27.1-X:nodwarf5 linux/amd64`. Its filename and caller PATH do not establish
pinning. The observed 128 passing cases and cleanup remain valid native evidence;
the separately recorded Go 1.26.5 checks remain distinct.

Host Go is 1.27.1; targeted native checks were supplemental. Node is 26.9.0.
Node's experimental native Web Storage shadows jsdom storage in this older
Vitest environment; the final frontend checks disable it with
`--no-experimental-webstorage`. Tests use jsdom's storage, not a fake claim of
reload persistence. No configuration/dependency upgrade was introduced.

## Evidence and failure paths

Storage tests exercise 12 concurrent same-key requests, two independent SQLite
pools, historical replay after SAME changes, cross-action/unit/concept conflicts,
restart/reopen, validation failure and a trigger forcing receipt INSERT failure
after event INSERT. Rollback leaves neither receipt nor event. HTTP tests cover
key case normalization, equivalent JSON, malformed/empty/multiple-value keys,
unknown fields/trailing JSON, lookup and original DTO equality. Existing suites
retain effective annotation, Dataset, historical labels and unkeyed workflows.

The updated harness preserves all 104 unkeyed cases and adds 24 keyed cases:
four annotation kinds × root/workbench aliases × never/commit-drop/delay-drop.
It verifies receipt attribution after actual socket response loss, lookup before
forwarding, explicit retry winning before delayed original forwarding, eight
concurrent replays, conflict snapshots, browser-blocked zero-write requests,
fresh-key later decisions, original historical payloads, current projections and
process replacement. An initial run found an incorrect new assertion using the
wrong response property; that harness assertion was corrected and the complete
native-toolchain run passed. No backend behavior was patched to force that pass.

Retained synthetic evidence: `/tmp/flh029-response-loss-pinned.json`:
`status=PASS`, 128 cases, `cleanup_errors=[]`,
`temporary_directory_removed=true`. Every keyed annotation case checks unchanged
local provider counters. Fixture extraction alone uses the counted local fake.
The harness records source hashes, proxy ordering/results, receipt and history
payloads. Backend production code did not change after that passing harness run;
subsequent additions were focused tests, frontend handling and documentation.

Frontend tests cover reload of unknown identity, saved payload retry despite
changed selection, a fresh key for a later decision, no automatic writes, receipt
mismatch refusal, 404 remaining unknown, unit switches/stale reads, storage
failure before POST, and committed attribution surviving refresh failure.

## Changed files

Backend:

- `internal/domain/annotation_operation.go`
- `internal/application/annotation_operation.go`
- `internal/storage/sqlite/annotation_operation.go`
- `internal/storage/sqlite/annotation_operation_test.go`
- `internal/storage/sqlite/concept_repository.go`
- `internal/transport/http/annotation_operation.go`
- `internal/transport/http/annotation_operation_test.go`
- `internal/transport/http/concept.go`
- `internal/transport/http/handler.go`
- `migrations/009_annotation_operations.sql`

Frontend:

- `web/src/api/client.ts`
- `web/src/api/client.test.ts`
- `web/src/pages/reviewOutcome.ts`
- `web/src/pages/ReviewQueue.tsx`
- `web/src/pages/ReviewQueue.test.tsx`
- `web/src/pages/ReviewOutcomes.test.tsx`
- `web/src/pages/annotationOperation.ts`
- `web/src/pages/annotationOperation.test.ts`

Harness/documentation:

- `scripts/validation/flh028/reproduce.py`
- `scripts/validation/flh028/README.md`
- `docs/plans/FLH-029-annotation-idempotency.md`
- `docs/validation/FLH-029-annotation-idempotency.md`
- `docs/ARCHITECTURE.md`
- `README.md`
- `README.zh-CN.md`
- `AGENTS.md`

## Remaining limits

No real-browser/DOM acceptance, power-loss/disk-failure injection or live
production verification is claimed. jsdom remount plus persisted browser storage
checks reload semantics; actual browser verification remains NOT RUN. No
multi-tab storage lock, cancellation fence, authentication, paid provider call
or extension to other mutations exists. Clearing browser storage/changing origin
loses client identity. Saved operations for units no longer reviewable remain
stored, but the current queue UI has no recovery controls for those units;
the receipt API remains available. Receipts distinguish historical committed
requests from current effective labels, and neither 404 nor a later state change
cancels an outstanding request.
