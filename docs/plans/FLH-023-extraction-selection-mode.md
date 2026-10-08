# FLH-023 — Extraction selection mode and return to automatic latest

Owner: NAS Codex in the supplied flh-nas-codex working tree; actual pwd reported
in chat. Requested branch label: feat/flh-023-extraction-selection-mode. No Git
or GitHub commands. FLH-020 is not available in supplied docs; work proceeds
independently. Contract was specified before implementation. Status: complete,
stopped for review. Date: 2026-10-08 (America/Toronto).

## Frontend handoff: exact HTTP contract

GET, PUT and DELETE `/entries/{id}/current-extraction` return HTTP 200 JSON:

```json
{"entry_id": 12, "current_extraction_id": 34, "selection_mode": "pinned"}
```

Exactly these fields are defined:

- `entry_id`: integer, unchanged existing field.
- `current_extraction_id`: integer or null, unchanged existing field. The
  successful extraction currently selected, regardless of mode.
- `selection_mode`: new string, exactly `automatic` or `pinned`. The presence
  of an explicit persisted selection defines pinned, even if it selects the
  latest version. Do not infer mode by comparing extraction IDs or versions.

GET is read-only. Existing consumers ignoring the added field remain compatible.
An existing entry without any successful extraction returns:

```json
{"entry_id": 12, "current_extraction_id": null, "selection_mode": "automatic"}
```

PUT retains its existing request `{"extraction_id":34}` and persists an
explicit pin. New extractions never advance that pin. Its response also adds
selection_mode=pinned while retaining the existing fields and status. Invalid
or cross-entry extraction IDs return 422; the prior pin remains intact.

DELETE takes no request body. It clears the explicit pin, if any, and returns
selection_mode=automatic with the latest successful extraction ID, or null when
none exists. It is idempotent for an existing entry: repeated DELETE is 200.
Automatic mode may advance between repeated requests if new extractions arrive.
No provider call or extraction run is triggered by selection operations.

GET/PUT/DELETE: malformed/nonpositive entry ID => 400; unknown entry => 404;
storage failure => 500 with a value-free public error. PUT invalid JSON => 400;
invalid/missing/foreign extraction ID => existing 422 behavior. Browser boundary
runs first: forbidden Host or mutation Origin/Fetch Metadata => 403 before any
selection write/provider call. Bodies on browser mutations retain existing JSON
content-type enforcement; frontend DELETE should send no body. Production
workbench also exposes these routes under `/api/` with identical semantics.

## Repository semantics and preservation

No migration. `entry_current_extractions` is a mutable selection projection:
presence => pinned; absence => automatic latest successful by version. Only
successful runs are persisted, including successful zero-unit runs.

A new domain selection read reports ID and mode from one SQL statement so the
metadata and ID describe the same snapshot. The existing ID-only read remains
available. PUT keeps its existing transaction/ownership validation.

Clear starts a transaction, verifies the entry exists, deletes only that entry's
selection row, reads the resulting automatic selection inside that transaction,
and commits. Failed clear does not leave partial selection changes. Unknown
entry returns ErrNotFound; an existing entry with no pin succeeds. Subsequent
successful extractions advance automatic selection normally.

Extraction/unit evidence, human/automatic SAME events and current memberships,
INVALID judgments, DISTINCT pairs, relations, admission records and analysis/
feedback history are untouched. Derived support, reviewability and current-unit
projections consume the existing selected extraction authority immediately;
no label rewrite, provider call, preferred-unit policy or retirement change.
Clearing a pin does not retain a separate pin-decision history: the existing
selection table is a mutable projection, not an immutable annotation event log.

## Exact owned files

- internal/domain/concept.go
- internal/application/concept_service.go
- internal/application/concept_service_test.go
- internal/storage/sqlite/concept_repository.go
- internal/storage/sqlite/extraction_selection_test.go (new)
- internal/transport/http/concept.go
- internal/transport/http/handler.go
- internal/transport/http/current_extraction_test.go (new)
- internal/transport/http/browser_boundary_test.go
- docs/ARCHITECTURE.md (existing API documentation)
- docs/plans/FLH-023-extraction-selection-mode.md (this handoff)
- AGENTS.md (minimal implemented contract)

No frontend, shared READMEs, packaging, configuration, dependency or migration
edits. README.zh-CN.md must remain present. README-owner handoff: mention the
new selection_mode field and DELETE reset operation in both languages when the
owner next updates shared API documentation.

## Acceptance and planned validation

Temporary migrated SQLite databases and deterministic fake providers only.
Cover pin old -> create newer -> remain pinned -> clear -> newest -> another
success -> automatic advance; pin latest still reports pinned; repeated clear;
empty and unknown entries; invalid/cross-entry pin; persistent pin across
repository reopening; all immutable label/history contents unchanged; immediate
support and reviewability/current-unit changes. Browser tests cover DELETE at
root and /api routes with zero writes/provider calls when rejected.

Run targeted and full Go tests, vet, server/capture builds and formatting checks
using isolated source/output and the project-pinned Go 1.26.5 toolchain. Record
actual commands/results here before review. No .env, credentials, real daily
DB, paid provider, Git/GitHub command or subagent.


## Executed verification and handoff

Evidence: `/tmp/flh-023-go126-4ipq6_zb/go126.log`, fresh backend source copy and
isolated server/capture binaries under checks/. The temporary harness
`/tmp/flh023-go126.py` ran the Dockerfile's digest-pinned Go 1.26.5 image with
`--rm --network none`, read-only source/module cache, isolated writable output,
GOTOOLCHAIN=local, GOPROXY=off, CGO_ENABLED=0, and
GOFLAGS="-mod=readonly -buildvcs=false". Constructed environment sets analyzer
rule-based, extraction/embedding disabled and provider credentials/settings
empty; tests use fake/local providers. No host-port exposure, real database,
.env read, paid provider, Git/GitHub command or subagent.

Actually executed with exit 0:

```sh
go version                         # go1.26.5 linux/amd64
test "$(go env GOVERSION)" = go1.26.5
go mod verify                      # all modules verified
go test ./internal/storage/sqlite ./internal/application ./internal/transport/http \
  -run 'Test(ExtractionSelection|CurrentExtractionSelection|BrowserBoundary)' -count=1
go test ./... -count=1
go vet ./...
go build -o /checks/server ./cmd/server
go build -o /checks/capture ./cmd/capture
go version -m /checks/server        # records go1.26.5
go version -m /checks/capture       # records go1.26.5
```

The targeted filter exercises storage, HTTP and browser-boundary cases; the
application package has no matching tests for that filter, but its full suite
passes and new service methods are exercised through the real HTTP stack.
All nine changed Go files match the tested source byte-for-byte. `gofmt -w`
was limited to changed Go files; final `gofmt -l` returned empty.

| Acceptance case | Result |
| --- | --- |
| Old pin + newer run + clear + another run | Pin remains old; clear selects newest; next run advances automatic selection |
| Pin latest | Same ID is distinguishable as pinned; clear changes only mode when latest remains same |
| Persistent pin | Separate reopened SQLite database/repository sees the pin |
| Repeated clear / empty entry / unknown entry | 200 automatic, including null with no extraction; unknown 404 |
| Invalid or cross-entry pin | 422 at HTTP / ErrValidation at repository; prior pin unchanged |
| Clear failure | Injected AFTER DELETE trigger failure rolls back and preserves pin; later clear succeeds |
| Other entry's pin | Clearing one entry leaves another entry pinned |
| Latest successful zero-unit extraction | Selected in automatic mode after clearing old pin |
| SAME / INVALID / DISTINCT and evidence | Full persisted table contents (excluding mutable pin) identical before/after selection changes |
| Support and reviewability | Old-pin SAME support active, automatic latest makes it orphaned; repinning recovers support; only selected, non-SAME, non-INVALID units remain reviewable |
| Current-unit projection | After clear, contains only newest extraction units |
| HTTP contract/status | Exact three fields, legacy field decoding, root/prefix GET/PUT/DELETE, 400/404/422 and secret-safe 500 verified |
| Browser DELETE rejection | Active pin preserved, SQLite total_changes unchanged, fake provider counters unchanged; root and /api covered |
| Selection/provider independence | Only three explicit extraction calls reach the counted fake provider; selection calls do not |

The first targeted run caught an unused net/http import in the new HTTP test;
removed it and reran the complete verification successfully. Initial attempt
log retained at `/tmp/flh-023-go126-c04c90j9/go126.log`.

No known unresolved implementation failure. Real-browser clicking, frontend
integration, packaging rebuild and concurrent-load stress tests were not run;
frontend/packaging are outside ownership. HTTP boundary behavior uses real
backend services over synthetic SQLite and counted fake providers. The test
container was auto-removed. No migrations or preferred-unit/retirement policy
changes. README.zh-CN.md exists; shared README edits remain human-owned/outside
scope as requested.

Modified files are exactly the owned list above. Implementation stops for human
review; no staging/commit/branch operation was performed.

Human-only staging command (displayed, not executed):

```sh
git add -- internal/domain/concept.go internal/application/concept_service.go internal/application/concept_service_test.go internal/storage/sqlite/concept_repository.go internal/storage/sqlite/extraction_selection_test.go internal/transport/http/concept.go internal/transport/http/handler.go internal/transport/http/current_extraction_test.go internal/transport/http/browser_boundary_test.go docs/ARCHITECTURE.md docs/plans/FLH-023-extraction-selection-mode.md AGENTS.md
```

Suggested commit message:
`feat: add extraction selection mode and automatic reset`
