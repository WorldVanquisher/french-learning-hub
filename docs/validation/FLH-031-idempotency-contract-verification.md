# FLH-031 — FLH-029 annotation idempotency author verification

Date: 2026-10-09 (America/Toronto). Verifier: NAS Codex, also the FLH-029 author.
This is **author verification, not independent review**. No production changes,
migrations, shared harness/documentation edits, Git/GitHub commands, delegation,
real learning data, daily databases, secret reads or paid provider calls occurred.

## Baseline and ownership

The actual working directory was the supplied `flh-nas-codex` workspace.
`AGENTS.md` was read first. The human initially supplied branch name
`test/flh-031-idempotency-contract-verification` and subsequently identified the
current worktree branch as `test/flh-031-idempotency-contract-verification-codex`.
Branch/commit state was not inspected. FLH-029 was present, so dependent checks
proceeded. On resumption, the five completed FLH-031 files were confirmed present;
only this branch attribution was updated. Completed verification and its evidence
were preserved without rerunning the checks.

The exact supplied baseline is a 211-file allowlisted SHA-256 manifest covering
backend/migrations, frontend source, module/lock manifests, packaging, repository
instructions, contract note and read-only FLH-026/028 harness dependencies.
Inventory digest (SHA-256 of `json.dumps(manifest, sort_keys=True).encode()`):

```text
23ead49e225988849fa36be3e547fd609e6525e987260221f8ad3cbb30c2c7a8
```

The complete manifest is retained in both final verification JSON reports and
`/tmp/flh031-checks.json`. Shared baseline equality was checked again after
verification. No Git identity is inferred from a source inventory.

| Baseline file | SHA-256 |
| --- | --- |
| `migrations/009_annotation_operations.sql` | `6329ac4ccc44f70be4e7bd2692a1ea364dc09020afd97fea6b8a5888d3ad3e57` |
| `docs/plans/FLH-029-annotation-idempotency.md` | `bdfdc390849b0707d99388b484850a6292ce62eb8c95e4f5477a8c0cf91c9b6b` |
| `internal/domain/annotation_operation.go` | `73bf9a309d7652e72036280e7eb50f748b184a9ce14c1b22f12a458df13db7ab` |
| `internal/application/annotation_operation.go` | `7dcead625a6d2ede9254b270c9f0fb5af2d61edbbd1e2faa9170edd2769c60fd` |
| `internal/storage/sqlite/annotation_operation.go` | `59f47db07ad3099067480f02153e7f3f57724cd55aff66c362d020fa3f97db64` |
| `internal/transport/http/annotation_operation.go` | `5890bee6caf9f1a9abe1a51e159144dec63bd808e74c544126640dd2d4cd2193` |
| `web/src/pages/annotationOperation.ts` | `09487ec27589fbb0702089a85536cadd6f89888a174421970a11707342e11583` |
| `web/src/pages/reviewOutcome.ts` | `33722e927ec94a77548d4b79d388fc6903158a764b202d890071ef86d7d1062f` |

Private tested source inventories:

- Native: 152 files, `ef36298fa0933262e5aee8c6fcf549e50effbfbae17d329171082973b718cb3d`.
- Container: 207 files, `9f8a6002cdbabf87989a3828b242b68175e7962249d2684dff39845525a70b1c`.

Different inventory sizes reflect the release frontend/packaging copied only for
container builds. Native uses a synthetic static index for `/api` transport.

Only these five task-owned files were created:

- `docs/validation/FLH-031-idempotency-contract-verification.md`
- `scripts/validation/flh031/README.md`
- `scripts/validation/flh031/verify.py`
- `scripts/validation/flh031/checks.py`
- `scripts/validation/flh031/workflow.py`

There was no ownership overlap with FLH-030 or shared FLH-028 files. Both root
English/Chinese READMEs exist and remain part of the supplied baseline.

## Contract reviewed

Affected endpoints, also exposed through the workbench `/api` prefix:

- `POST /knowledge-units/{id}/concept-distinctions`
- `POST /knowledge-units/{id}/concept-links/relation`
- `GET /annotation-operations/{id}`

Keys are optional, canonical hyphenated UUID text normalized to lowercase,
global to the database across endpoint/action/unit/concept and route aliases.
Equivalence is typed canonical JSON of action, positive unit/concept IDs and,
for relations, exact lowercase BROADER/NARROWER/RELATED vocabulary values.
Unknown/trailing keyed JSON is rejected. There are no accepted client reason,
evidence, source, resolver or score fields to omit from canonicalization.

SQLite acquires its write lock before key lookup, then appends event and receipt
in one transaction. Equivalent lookup returns stored domain result before any
current-state validation; conflicting valid payload returns 409 without mutation.
Production uses one database connection; an existing storage test also exercises
two independent connection pools. No external/provider work occurs in the
receipt transaction. Response reconstruction uses the existing event DTO
converters and stored timestamps/evidence/supersession pointers. Equality of raw
original/replay bodies was checked over HTTP, including restart.

Receipt GET exposes committed historical attribution. 404 remains unknown:
there is no pending reservation, cancellation or terminal non-commit fence.
Receipts do not define current membership, preferred representation, support or
current pair labels. Unkeyed append-per-submission behavior is retained.

The frontend uses the same action/target/relation fields and lowercase UUID v4
keys. It stores only versioned minimal operation identity before sending, retries
that saved payload/key explicitly, validates receipt attribution fields, treats
404 as unknown and refreshes backend authority separately. Existing frontend
tests cover reload, edited selection, fresh decisions, storage failure, stale
responses/unit switches and committed attribution despite refresh failure. This
is source/jsdom evidence; it is not real-browser acceptance.

## Expected versus observed results

| Requirement | Expected | Actual |
| --- | --- | --- |
| Equivalent normalized request | Original 201/body; one event and receipt | PASS for four kinds and both aliases; raw bodies identical after key case, JSON order/whitespace and path-leading-zero changes |
| Different payload/action/targets | 409; no writes/provider calls | PASS; concept, unit, relation and action changes; whole-table snapshots unchanged |
| Concurrent first arrivals | At most one event/receipt | PASS: 16 identical requests → 16 identical 201s, exactly one initial commit; 16 competing payloads → eight winner 201s/eight 409s; one event/receipt |
| Atomic event/receipt | Failure leaves neither additional record | PASS: forced receipt INSERT abort returned 500/lookup 404; unchanged tables/projections; later same-key retry committed once |
| Lost response + explicit retry | Original event; no duplicate | PASS: actual socket disconnects, same-key replay/receipt recovery |
| GET before delayed commit | 404 unknown; later recoverable | PASS: original forwarding gated until reads finish; keyed retry can win first and delayed original replays it |
| Restart | Durable receipt and original replay | PASS in native and container replacement, including first-arrival probes |
| Later current-state changes | Original historical result; unchanged authority | PASS after newer annotation, SAME, preferred-unit selection and reassignment |
| Unkeyed operations | Existing repeated-event/supersession behavior | PASS: inherited 104 unkeyed cases retained within each matrix |
| Invalid key/malformed payload | No partial writes | PASS: empty/malformed/combined/duplicate keys; malformed/null/wrong-type/unknown/trailing JSON; invalid relation; missing targets |
| Browser-boundary rejection | Zero writes/provider calls | PASS on root and `/api`; cross-origin keyed POST and unknown Host receipt GET, plus established workflow boundary matrix |
| Migration 008→009 | Existing labels and projections preserved | PASS: 15 existing non-ledger tables unchanged; only empty receipt table and ledger row added; catalog/effective annotations/Dataset identical |
| Receipt versus authority | Historical result cannot restore old authority | PASS: replay leaves current membership, derived support, cleared preferred unit and suppressed historical pair output unchanged |

The rollback fixture aborts specifically after annotation insertion, when the
receipt INSERT is attempted. Relation retry points back to the real prior event,
not a rolled-back event. Whole-table snapshots include SQLite sequence values.
Fixture trigger DDL is installed/removed only in the owned temporary database.

Concrete native persisted/API observations after current-state changes:

| Kind | Unit / original target | Original event | Later unkeyed event | Receipt/replay event | Current SAME target | Effective old-pair count |
| --- | --- | --- | --- | --- | --- | --- |
| DISTINCT | 116 / 235 | 33 | 34 | 33 | 236 | 0 |
| BROADER | 122 / 247 | 134 | 135 | 134 | 248 | 0 |
| NARROWER | 128 / 259 | 143 | 144 | 143 | 260 | 0 |
| RELATED | 134 / 271 | 152 | 153 | 152 | 272 | 0 |

These are actual IDs from this isolated run, not prescribed IDs for reruns. In
all four cases, original-target preferred unit was null, its support was orphaned,
and the new membership target was supported. Before SAME, the latest pair event
was effective. After the later affirmative SAME and reassignment, existing
contradiction rules suppressed old pair evidence. Lookup/replay preserved the
original event without resurrecting the suppressed pair or changing any table.

## Commands, toolchains and totals

Executed successful final commands:

```sh
python3 -B scripts/validation/flh031/verify.py --report /tmp/flh031-native-verified.json
python3 -B scripts/validation/flh031/verify.py --mode container --report /tmp/flh031-container-complete.json
python3 -B scripts/validation/flh031/checks.py --report /tmp/flh031-checks.json
python3 -B scripts/validation/flh031/workflow.py --report /tmp/flh031-workflow-native.json
python3 -B scripts/validation/flh031/workflow.py --mode container --report /tmp/flh031-workflow-container.json
python3 -B scripts/validation/flh026/test_harness.py
python3 -B scripts/validation/flh028/test_proxy.py
```

The helper check ran, in a private source copy:

```sh
go version                         # pinned go1.26.5 inside Docker
go mod verify
go test -json ./internal/storage/sqlite ./internal/application ./internal/transport/http -run 'Test(AnnotationOperation|BrowserBoundary)' -count=1
go test -json ./... -count=1
go vet ./...
go build -o /checks/server ./cmd/server
go build -o /checks/capture ./cmd/capture
# Also required no gofmt output and checked both executable build metadata.
npm run typecheck
npm test -- --reporter=json --outputFile=<private-output>/frontend-tests.json
npm run build
```

Go helper image is the project-pinned digest
`golang:1.26.5-alpine@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2`,
with `--network none`, installed read-only modules and temporary build output.
Native matrices/workflow actually used host
`go1.27.1-X:nodwarf5 linux/amd64`. Container application builds used the release
Dockerfile's pinned Go 1.26.5 stage. Frontend helper used installed Node 26.9.0
with `--no-experimental-webstorage` to let jsdom supply browser storage; release
container builds used the Dockerfile's pinned Node 24.11.1 stage.

| Check | Actual result / total |
| --- | --- |
| Native idempotency/proxy matrix | PASS, 169 cases |
| Container idempotency/proxy matrix | PASS, 168 cases |
| Established native daily workflow | PASS, eight workflow checks |
| Established container daily workflow | PASS, eight workflow checks |
| FLH-026 harness-safety tests | PASS, six tests |
| FLH-028 proxy tests | PASS, five tests |
| Pinned Go focused + full suite | PASS, 1,558 test/subtest pass events; 1,195 distinct package/test names including 545 top-level tests; no failure/skip events |
| Go formatting/modules/vet/server+capture builds | PASS |
| Frontend typecheck/tests/production build | PASS, 198 tests in 16 files |
| Real browser | **NOT RUN**; browser executable/tooling unavailable |

The 1,558 Go pass events include repeated focused tests also executed in the full
suite, and parent/subtest events. They are not 1,558 independent top-level cases.
All command output and full JSON test results are retained in the external report.

## Confirmed verification defects for follow-up

No production idempotency defect was reproduced in the tested baseline. These
findings concern evidence/harness correctness and should be fixed separately by
owners of those shared files.

### F1 — P2: FLH-029 response-loss toolchain claim is inaccurate

Location: `docs/validation/FLH-029-annotation-idempotency.md:43` and the wrapper
command at line 56, together with `scripts/validation/flh026/run.py:32` and its
native preparation commands. The report says the 128-case response-loss harness
used Go 1.26.5. Retained `/tmp/flh029-response-loss-pinned.json` actually contains:

```json
{"argv":["go","version"],"exit":0,"output":"go version go1.27.1-X:nodwarf5 linux/amd64\n"}
```

Reproduction: inspect that command record or rerun the old `PATH=...` invocation.
FLH-026 intentionally resets PATH to `/usr/local/bin:/usr/bin:/bin`, bypassing the
wrapper supplied by the caller. Impact: overstated pinned-toolchain evidence;
it does not negate the observed 128-case results or the separately passing Go
1.26.5 suite. Suggested correction: label that run native Go 1.27.1 and require
recorded compiler/build metadata before claiming a pinned harness run. FLH-031
now supplies actual container/pinned checks separately. Shared report left untouched.

### F2 — P2: inherited random Compose image name can be invalid

Location: `scripts/validation/flh026/run.py:151`. The temporary-directory suffix
is copied directly into project/image names. A suffix starting `_` produced
`flh026-_aditmt8:local`; Docker rejected it with `invalid reference format` before
application startup. Actual initial container report had zero cases, FAIL, clean
cleanup. Impact: flaky container verification depending on the random directory
name. Suggested verification/fix: include a deterministic `_...` suffix test and
normalize/generate a Docker-safe project/image suffix. FLH-031's owned adapter
uses a hexadecimal suffix; FLH-026 was not edited.

### F3 — P3: reused proxy drops duplicate header multiplicity

Location: `scripts/validation/flh028/proxy.py:64`. Headers become a dictionary,
so duplicate `Idempotency-Key` lines collapse before reaching Go. The first new
probe saw a replay 201 because the server received only one key. Impact: this
proxy cannot establish direct-server rejection of duplicate keys/origins.
Suggested follow-up: preserve raw header pairs in a separately scoped proxy
change, or keep multiplicity tests direct. FLH-031 sends duplicate keys directly
to its owned server and observed 400 with unchanged persistence/counters.

## Exploration failures and cleanup

Initial reports are retained, not hidden or counted as passing acceptance:
`/tmp/flh031-native.json` (proxy collapsed duplicate header),
`/tmp/flh031-native-final.json` (proxy accept-queue connection reset under 16
simultaneous first-arrivals), `/tmp/flh031-container.json` (F2), and
`/tmp/flh031-native-complete.json` / `/tmp/flh031-container-final.json` (the new
probe incorrectly expected older pair evidence to remain effective after SAME).
The latter assertion was corrected against existing domain contradiction rules;
production code was not patched. First-arrival probes were moved to the owned Go
listener, rather than adding automatic retry to hide proxy queue failure.

Every initial and final run reported `cleanup_errors=[]` and removal of its
private directory. Final workflow reports likewise show cleanup PASS. The helper
checks report their private directory removed. Cleanup stops only owned native
services/providers or project containers/network/image tags; shared base images
and Docker build cache remain. No new permanent project dependency was installed.
Reports/logs contain synthetic fixtures and the public local-provider fixture key.

## Limits and untested concerns

- This is author verification; independent review remains a separate activity.
- No real browser, actual reload/navigation/network cancellation or Vite/browser
  attack was run. Existing jsdom recovery tests passed. Shared browser tooling
  was not installed or changed.
- Power loss, disk exhaustion, SQLite commit I/O failure and sustained adversarial
  load were NOT RUN. Atomicity was checked through rollback fault injection,
  concurrent HTTP requests, independent pools in the existing storage test and
  ordinary process/container replacement.
- Receipt wire results are reconstructed through current DTO converters. Exact
  equality is proved for this release and its restarts, not arbitrary future
  DTO/schema evolution. Future compatibility needs separate verification.
- Browser storage clearing/origin changes and absent recovery controls for units
  outside the queue remain documented FLH-029 limits. No multi-tab lock or
  cancellation fence was added or claimed.
- Separate GETs are snapshots, not an atomic multi-endpoint read or cancellation
  fence. Proxy gates establish ordering only within this controlled experiment.
- No production deployment, existing daily database, external provider or
  authentication behavior was tested.

Verification complete; editing stopped for human review. Suggested staging:

```sh
git add -- docs/validation/FLH-031-idempotency-contract-verification.md scripts/validation/flh031/README.md scripts/validation/flh031/verify.py scripts/validation/flh031/checks.py scripts/validation/flh031/workflow.py
```

Suggested commit message:
`test: verify FLH-029 annotation idempotency contracts`
