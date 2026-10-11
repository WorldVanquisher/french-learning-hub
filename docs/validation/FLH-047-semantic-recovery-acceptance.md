# FLH-047 — Independent integrated semantic recovery acceptance

Date: 2026-10-11, Canada/Eastern. Owner: NAS Codex. Human-supplied branch label:
`test/flh-047-semantic-recovery-acceptance` (not inspected through Git).
Actual `pwd`: `/home/worldvanquisher/workspace/flh-nas-codex`.
`AGENTS.md` was read from disk.

**ACCEPTED for the six assigned FLH-044 recovery priorities.** The exact
FLH-043 F1 and F2 reproductions now pass. Final main run: 46/46 independent
cases; complementary run: 6/6. All 38 inherited FLH-043 cases and 14 added
recovery cases passed, without counting repeated executions twice. Sixty
focused top-level Go tests passed with zero skips, including all eight actual
Qdrant integration tests. Nineteen preserved fixture/oracle self-tests passed.

Two low-severity operator text findings remain below. Acceptance covers recovery
mechanics, JSON/status observability and the declared FLH-044 contract; it does
not certify the default CLI wording as complete or accurate. The FLH-044 plan
already declared default CLI visibility a bounded dependency, not part of its
production changes. Repeated-replacement HTTP 500 is the implemented documented
mapping, independently observed here, not a new mapping or a claimed ideal UX.
No newly reproduced recovery-engine defect remains in these scenarios.

No author-reported result is used as independent proof. Author reports were
read to identify the contract; results here come from the supplied integrated
source and new execution. FLH-046 CI work was not assumed present or evaluated.
No Git/GitHub commands, subagents, paid/real provider, model installation,
secret, personal/daily database, migration, production/shared documentation,
frontend, dependency or CI edit occurred.

## Ownership and reused evidence

Exactly six files created/modified:

- `scripts/validation/flh041/phase_b_checks.py`: existing runner, FLH-047 labels,
  persistent exact-owned DELETE faults, corrected successful metadata-race
  counter, original F2 actual-collection absence check, recovery integration.
- `scripts/validation/flh041/ownership_probe/main.go`: dispatch new recovery
  modes, retaining the active migration-011 publication/fencing probes.
- `scripts/validation/flh041/ownership_probe/recovery.go`: new independent actual
  adapter search/count/HTTP probes and cleanup lease/writing probes.
- `scripts/validation/flh041/recovery_checks.py`: new orchestrated assertions,
  full publication/cache equality, deletion/bookkeeping and CLI observations.
- `scripts/validation/flh041/README.md`: current execution and evidence limits.
- This new report.

Historical FLH-041/043 reports and the four Phase A fixture/oracle files remain
byte-identical. The existing actual-Qdrant harness, deterministic embeddings,
source seed/rendering, proxy, private-source build, process and Compose lifecycle
were reused. No general audit or new retrieval experiment was started.

Dependencies were read-only: FLH-044 plan/validation and SEMANTIC_SEARCH.md,
actual search/index/repository/Qdrant/HTTP/CLI APIs and migration 011. Current
bookkeeping is `semantic_index_spaces`, `semantic_index_physical_collections`
and `semantic_index_manifest`; the persisted vector cache is
`semantic_embedding_cache`. Legacy migration-010 methods are neither invoked
as publication evidence nor removed.

## Executed commands and evidence locations

All commands ran from the actual working directory above. Docker socket access
was denied in the filesystem sandbox; authorized tool escalation succeeded.
There was no approval-review rejection and no missing prerequisite.

```sh
python3 -B scripts/validation/flh041/test_fixtures.py
python3 -B scripts/validation/flh041/phase_b_checks.py --output /tmp/flh047-integrated-1
python3 -B scripts/validation/flh041/phase_b_checks.py --output /tmp/flh047-integrated-2
python3 -B scripts/validation/flh041/phase_b_checks.py --extra-only --output /tmp/flh047-complementary
```

The initial run exited 1: 43/46 cases passed; three **new harness** assertions
looked for Go's `Cleaned` name as JSON `cleaned` instead of the actual
`cleaned_collections` tag. Actual responses reported the expected 1/2/0 cleanup
counts. This was corrected only in the owned adapter; no assertion was removed
or threshold relaxed. The final complete rerun and complementary run each exited
0, with no fatal or cleanup error. The first run also independently passed F1,
the original F2 check, all eight new search windows and populated Compose; its
raw red result is preserved rather than relabelled as green.

The runner executed in private source/output, with sanitized environment,
`GOENV=off`, `GOTOOLCHAIN=local`, `GOPROXY=off`, `GOSUMDB=off`,
`GOFLAGS=-mod=readonly -buildvcs=false`, `CGO_ENABLED=0`:

```text
go build -o <owned-work>/server ./cmd/server
go build -o <owned-work>/semantic-index ./cmd/semantic-index
go build -o <owned-work>/probe ./scripts/validation/flh041/ownership_probe
go test -json ./internal/application ./internal/storage/sqlite ./internal/vectorindex ./internal/embedding ./internal/transport/http ./internal/config ./cmd/semantic-index -run 'Test.*(Semantic|Qdrant|HTTPProvider|Embedding)' -count=1
```

The last command had `FLH_QDRANT_URL` pointing only to that run's actual owned
Qdrant. Exact argv/env-relevant settings, stdout/stderr/exit codes, binary hashes,
197 bounded source-baseline hashes and 234 private source-copy hashes are in each
main `report.json`. Focused Go JSON output is `integrated-go-tests.json`.
Go test passes are supplementary independently executed evidence, not substitutes
for the 52 independent SQLite/Qdrant cases.

Docker operations used locally inspected pinned bases, `--pull=never` on runs,
`docker build --pull=false --network none`, and actual Compose with an empty env
file, unique project, image-only app override and
`--profile semantic up --no-build --pull never`. No global app tag was replaced.
Both main executions used the actual Dockerfile and Compose profile. Nothing
was silently fetched; unavailable caches would fail the run.

Executable human reproduction with fresh output paths:

```sh
python3 -B scripts/validation/flh041/phase_b_checks.py --output /tmp/flh047-human
python3 -B scripts/validation/flh041/phase_b_checks.py --extra-only --output /tmp/flh047-human-extra
```

Evidence intentionally remains in `/tmp/flh047-integrated-1`,
`/tmp/flh047-integrated-2`, `/tmp/flh047-complementary`,
`/tmp/flh047-baseline.json` and `/tmp/flh047-final-resource-check.json` for review.
Runtime databases/storage/source/binaries were deleted; evidence JSON/logs may
expire with `/tmp`. Each report contains case names, expected/actual assertions
and auxiliary evidence filenames. `inventory-*.json` retains production-rendered
documents, complete SQLite schema/table rows, all cache tuples/float32 vectors,
and fully paginated raw Qdrant points including exact payloads/vectors. Final
`final-all-qdrant-points.json` spans every collection in the owned instance;
`final-all-sqlite-rows.json` spans every table. No count-only health assertion
replaced the preserved full inventory assertions.
`/tmp/flh047-evidence-manifest.json` records hashes for all 189 retained evidence
files across the three runs. All four final executable harness files were
rehashed equal to the final passing run baseline; subsequent edits were only
the owned README and this report.

## F1 closed — independent replacement windows and retry budget

The exact original `search-info-race` and Query positive control were reused:
A reads SQLite's publication, pauses before the selected actual adapter call;
B rebuilds, publishes and deletes the old actual collection; releasing A must
recover on the new pointer. Both pass, each with exactly one query embedding.
The old metadata counter of zero described FLH-043's early failure; retaining
zero after a successful recovery would be wrong. The successful target/current
collection assertion is retained and the count is now exactly one.

Additional probes intercept only the selected actual adapter boundary. Every
successful metadata/query/mutation still contacts actual Qdrant. Single or mixed
replacements run real cached rebuilds; old collections must be actually absent.
Loss probes delete the collection without changing SQLite's pointer. The actual
production HTTP handler runs via `httptest`, wrapping the actual application,
repository, counted HTTP provider and Qdrant adapter. This is transport execution,
not a mock service or browser/OS-process race.

First-request counts below exclude the separately counted successful follow-up:

| Fault window(s) | Metadata calls | Query calls | Embedding calls / input texts | HTTP | Actual outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| metadata replacement | 2 | 1 | 1 / 1 | 200 | Current replacement publication returned |
| Query replacement | 2 | 2 | 1 / 1 | 200 | Original query vector reused |
| metadata → metadata replacement | 2 | 0 | 0 / 0 | 500 | `ErrSemanticPublicationChanged` |
| Query → metadata replacement | 2 | 1 | 1 / 1 | 500 | Same explicit churn category |
| metadata → Query replacement | 2 | 1 | 1 / 1 | 500 | One shared budget, no third attempt |
| Query → Query replacement | 2 | 2 | 1 / 1 | 500 | No re-embedding or third attempt |
| unchanged-pointer loss before metadata | 1 | 0 | 0 / 0 | 409 | `ErrSemanticIndexNotBuilt`, no replacement retry |
| unchanged-pointer loss before Query | 1 | 1 | 1 / 1 | 409 | Same true-loss category, no extra request |

Repeated replacement is **not** classified as not-built. HTTP body is the
implemented generic `{"error":"could not run semantic search"}`; service error
retains the publication-changed category. True loss remains the configured-model
not-built 409 message. A subsequent request succeeds after churn stops, with its
own exactly one query input. Loss repair republishes from cache, zero document
inputs. All current manifests, payloads and vectors match the prior cached
contents after replacement/repair, then independent raw inventory verification
passes. Follow-up calls are shown separately so two requests are not presented
as two embeddings for one search. There is no keyword fallback.

## F2 closed — healthy sync cleanup and fencing

| Scenario | Strong expected state | Actual |
| --- | --- | --- |
| Original FLH-043 F2 | Inject failed DELETE of replaced actual collection; remove fault; next healthy sync forgets retired bookkeeping | PASS, retained original assertion plus actual Qdrant GET 404 |
| Persistent deletion failure | Healthy current publication, old retired collection still exists; pending/error/last_error remain visible; zero embeddings | PASS: `verified_unchanged`, pending exactly old name, `cleanup_error="vector index unavailable"`, status HEALTHY plus `last_error="cleanup incomplete: 1 leftover collection(s) remain (vector index unavailable)"` |
| Fault removed, ONLY healthy sync | No rebuild/publication change; delete old actual collection, physical row and manifest; zero document/query embeddings | PASS: `cleaned_collections=1`, `published=false`, pending empty/error absent, old GET 404, old manifest count 0, last_error cleared |
| Publication/content preservation | Same publication collection/run/time, active physical row, current manifest, every raw point/payload/vector and entire cache | PASS: exact before/after equality; full independent healthy inventory |
| Lease taken after first deletion checkpoint | One already-gated terminal deletion may finish; no subsequent deletion or old bookkeeping/last-run mutation | PASS: one gate and one actual DELETE; the other retired collection still exists; both physical records/manifests remain; exact newer full state/current points equality |
| Recovery after ownership loss | Plain healthy sync reconciles both retained records, including already-missing first collection | PASS: cleaned 2, no publication change, pending empty, zero embeddings, healthy full inventory |
| Another run's writing collection | Healthy takeover sync retains its actual point/vector/payload/manifest/record; reports pending, no DELETE | PASS; a second healthy sync also cleans 0 and leaves actual collection present |
| Later publication cleanup | Publishing rebuild may remove superseded writing collection; no re-embedding | PASS: actual GET 404, physical and manifest rows gone, pending empty and verified current inventory |

The lease-loss probe creates two real retired collections through rebuilds with
proxy DELETE failures. At the first post-renewal gate a new owner takes over
through actual repository APIs, verifies the full healthy publication and
records a verified no-op outcome. Releasing old work may finish its already-gated
terminal deletion, as the contract explicitly permits. Its fenced forget and
completion cannot write. A second deletion never reaches Qdrant. This is an
in-process lease boundary, not an assertion that an HTTP deletion is atomically
fenced across SQLite and Qdrant. Private publication fences remain the protection
for current vector data.

The writing fixture uses actual AcquireLease/RegisterCollection/RecordManifest
and actual Qdrant CreateCollection/Upsert; its point is preserved exactly.
A takeover sync must distinguish it from terminal retired/abandoned leftovers.
No migration or production bookkeeping method is replaced by test SQL in these
new cleanup probes.

## Other inherited integrated checks

All inherited checks reran on this source: busy/expiry/explicit takeover; nine
fenced repository mutations; service upsert/manifest/publication gates; verified
no-op takeover; three unique vectors for four Concepts; restart/sync/rebuild
cache reuse; model/dimension isolation; six invalid provider outputs; partial
embedding/upsert; applied-but-unacknowledged points vs manifest; SIGINT/SIGTERM/
SIGKILL interruption and recovery; missing/same-count/foreign/stale/extra points;
wrong dimensions/distance; whole collection loss; current SQLite authority;
source catch-up; schema v2 history with health_verified=false; HTTP state filters;
owned unrecorded collection cleanup; independent SQLite writer acquisition during
held provider and Qdrant calls, with a blocking positive control.

The eight independently rerun real-Qdrant Go tests cover build/cache/restart,
superseded gates, no-op takeover fencing, point/same-count damage, whole loss/
shape, interruption, held-network SQLite writes and unavailable Qdrant. Their
Concept reader is an in-memory fixture; the runner's 52 cases supply the separate
actual SQLite/source observations. Annotation tables in the runner's synthetic
fixture are empty and unchanged; populated admission/INVALID/reassignment
behavior is not newly accepted by this index-focused task.

Populated Linux Compose passed with four actual Concepts/four points/three cache
keys. Packaged `/app/semantic-index` build/status/sync ran successfully; exact
host-side point/payload/vector/SQLite verification passed. Search returned schema
v2, query-only embedding and unchanged database snapshots. Actual Qdrant stop
made semantic HTTP search return 502 and status report unavailable/unverified;
keyword search still returned all four Concepts. Restart reused bound storage;
healthy sync consumed zero embeddings and preserved the publication. Host app/
Qdrant ports bound only 127.0.0.1; the counted provider had no published host port.
App ran UID:GID 1000:1000; SQLite was 1000:1000, mode 0644. Qdrant ran UID:GID
0:0; owned storage parent was 1000:1000, mode 0755, with root-owned nested data.
Both wrote successfully. No host chmod/chown or permanent dependency change.

## Independently confirmed operator text findings

These are retained production behavior, not silently patched or declared fixed.
They do not defeat the scoped recovery mechanics or documented JSON/status
observability criteria.

**O1 — default sync output omits pending cleanup (low severity).** Location:
`cmd/semantic-index/main.go:159` (`printReport`), especially `:163`. Reproduction:
`recovery-persistent-cleanup-failure`, using the owned forwarding proxy to keep
DELETE of a known retired actual collection at 503, then actual CLI
`semantic-index -batch 2 sync`. Expected useful operator visibility: disclose
that cleanup remains pending with its error. Actual exit 0 and stdout only:

```text
verified unchanged: <published> is healthy; nothing written
outcome: verified_unchanged
```

No leftover name or cleanup error appears. JSON sync and a separate text/status
request **do** expose pending old name, vector-unavailable cleanup_error and
cleanup-incomplete last_error. This confirms the plan's known bounded CLI
visibility dependency independently. Impact: a text-only operator can miss an
unrecovered storage leftover despite healthy publication. Suggested owner
verification: require text report to expose pending/error/cleanup count while
keeping the documented successful-with-pending outcome; rerun this exact case.

**O2 — status promises next-run deletion for writing collections (low severity).**
Location: `cmd/semantic-index/main.go:249`. Reproduction:
`recovery-other-writing-collection`: another run has a real writing collection
and manifest; a healthy takeover sync retains it. Actual text status says
`(writing, run <id>) — removed by the next run`. Running only another healthy
sync still cleans 0, reports the same name pending and leaves its actual point
present. Expected wording under SEMANTIC_SEARCH.md's scope table: removal by
**the next publishing run**, while retired/abandoned leftovers are also eligible
for healthy sync. A later rebuild actually removes it. Impact: incorrect recovery
advice; no publication data loss. Suggested owner verification: status wording
must distinguish writing from terminal leftovers, using these same actual
collection checks. The harness's PASS for this case means isolation/pending
state is correct, not that the wording is truthful.

Neither finding is hidden behind passing engine assertions. HTTP replacement
500/generic wording is recorded in the F1 table; changing it to a dedicated
retry response is a separate contract decision, not required for this acceptance.

## Counters, toolchains and baseline

Every counter below comes from retained ledger attempts, including deliberate
failure/cancellation, not inferred cache or response text. Ledgers retain each
input hash, role, wire model, batch, outcome/status and reply-write result.

| Independent ledger | Requests | Attempted document inputs | Attempted query inputs | Max simultaneous requests |
| --- | ---: | ---: | ---: | ---: |
| Final native main + recovery | 34 | 25 | 19 | 1 |
| Complementary native | 6 | 3 | 4 | 1 |
| Populated Compose | 3 | 3 | 1 | 1 |

Main query total: five inherited query attempts + 14 first/follow-up recovery
attempts. Main valid-response document count is 10; attempted 25 includes invalid,
partial and canceled calls. No unclassified input or ledger reset was accepted.
Maximum native embedding batch size was 2. Qdrant inventories use paginated
scrolls and include every point, not a returned top-K subset. Exact per-operation
zero deltas for healthy sync/rebuild/restart/cleanup are in the case artifacts.
The integration tests have separate counted fixtures, not merged into this ledger.

Observed Linux `7.1.8-arch1-3`, amd64; native Go
`go1.27.1-X:nodwarf5`; Python 3.14.7; Docker client 29.8.1/API 1.55 (downgraded),
daemon 29.7.2/API 1.55; Compose 5.5.1. Actual Qdrant HTTP 1.19.1, commit
`6ab21cac18ebb6f4ae29102c7f8f5cc11affd5de`. Pinned image:
`qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10`,
local image ID `sha256:dd57172b0bbebb29b0a96a37c1f378a317449730c36cdfe68feabe36e740a92b`.
Cached fixture image ID:
`sha256:9cbfea842643d1cf45df5d841ac78e8cc1a8bfbcc36934a9d31fdc964fcc5917`.
Cached Alpine cleanup image ID:
`sha256:706db57fb2063f39f69632c5b5c9c439633fda35110e65587c5d85553fd1cc38`.
The unchanged Dockerfile bases pin Node 24.11.1-alpine3.22, Go 1.26.5-alpine
and Alpine 3.22.2; image identities were inspected, not claimed as separately
executed compiler versions. Final app image:
`sha256:e0cee44ec9b77bb2c0efc903c3e963c69e64cdc4ad3a7090231a0179969828a4`.

Final main native binary SHA-256 (different temporary build roots can produce
different binary hashes; no byte-for-byte build reproducibility claim):

| Binary | SHA-256 |
| --- | --- |
| server | `4d7fcaf814c50e76c3b48331a42fab190263ab24510f03b9fe76206401784f22` |
| semantic-index | `37902c909134668c2b2c93a1dd13453e28e5240c3dc4e7158196ae3761a4a200` |
| probe | `4692cb1ec18a9c32c672cc0267269b828f04039467edc29d5fcf8851ec0d980e` |

Selected **pre-edit** SHA-256; complete bounded pre-edit manifest is
`/tmp/flh047-baseline.json`. Both final runs' 187 non-owned baseline files
were rehashed unchanged after execution. Historical reports/Phase A helpers
were explicitly checked unchanged.

| File | SHA-256 |
| --- | --- |
| `AGENTS.md` | `3e29b4127ac46851fa878b522016949e3c8b8c9d2493668776b4b8136bbf7281` |
| `docs/plans/FLH-044-semantic-recovery.md` | `d11b8cea66c17772f1258d4563c8cc6d502b30efe197b974411661362e6985bb` |
| `docs/validation/FLH-044-semantic-recovery.md` | `4371fb8f40f6b3360c27a358de9c1746f3c18209662c5716ea03f431bbdc7bf7` |
| `docs/SEMANTIC_SEARCH.md` | `7a134fb34d6bcc94158028048eb10a16f2dbfaed7590853449d497363df6cc48` |
| `internal/application/semantic_search.go` | `a353baf0f39b8daece2fb88262aa82f7159bcde06527ff5f05a6f4c48454dc21` |
| `internal/application/semantic_index.go` | `0fd11f40ed8321f0c2de7905e7b957277467ae6f7b88eb1559699522fce139f4` |
| `internal/storage/sqlite/semantic_index_repository.go` | `6936a91f7df81bcfba1236212c02de1773780d67614abc32aecea0c3e6218d47` |
| `internal/vectorindex/qdrant.go` | `d606d181bca8798d214e00aaf778a125553c20b67eb52f23c373ee70b0395865` |
| `internal/transport/http/semantic_search.go` | `bde6d8c5030d1ec7f8bd7a8e4e8d2cfbc67ff5482991346c0a00ab38b8208838` |
| `cmd/semantic-index/main.go` | `a0f4551f1315b8245ae02c2f52eae8e129cbadd984a9a4ddc77720c3ec9f679d` |
| `migrations/011_semantic_index_runs.sql` | `cc97962afe6f6207a788a77a60af5366d90d5082d4b4aae7a45af091bf0682d3` |
| `compose.yaml` | `8d3ba02486dcb1128fcd63c5b7dbaaf6213dcfd779d00b642c5c1bbce4e50728` |
| `Dockerfile` | `f13da53fdac48e44160442d3f44e554638449553f4851ccea68ee644f2480f63` |
| `docs/validation/FLH-041-vector-search-acceptance.md` | `eae2005f911247121732ff44545ce1ab907724625ac179e48f40f51d9e982683` |
| `docs/validation/FLH-043-index-consistency-acceptance.md` | `a11d2bdade57f05e68c2e09f7f1ec62b847fa8e3694945561f2735274657b78e` |
| `scripts/validation/flh041/phase_b_checks.py` | `45bf5919b08fc9ddc02af6a693896c048e51eb3adb74fbd7df712eaf9694399f` |
| `scripts/validation/flh041/ownership_probe/main.go` | `a991ca63130e2f69bfa1191f6a2f808fedf4bb449a971cde3da8760cf8719cf4` |
| `scripts/validation/flh041/fake_embeddings.py` | `ddcb5df1d12fc9fbed7416e487e8d4951ab467ecaacc3e263099285646919d74` |
| `scripts/validation/flh041/oracles.py` | `0988fd2852a1d6a08997ac498ab7692a0237a0cbc5701ced92168aec3cf8565a` |
| `scripts/validation/flh041/fixtures.json` | `71e6ad734ce17bd49afffd1186ef99ef4d1cdf83ad9f1170edf67f5d28ce409e` |
| `scripts/validation/flh041/test_fixtures.py` | `1df0a63e43edd5d43565f7f932ba8dd2dd3a994a1b88175ee306564087f8cb06` |

Final main external evidence SHA-256:

| Artifact | SHA-256 |
| --- | --- |
| `report.json` | `0282b1833ef3e1198aa7eae299983d7d29633cc4e7d8db6268e6bb14f5fc426e` |
| `recovery-provider-complete-ledger.json` | `3ab5028d9ba480e427055029cf8b19a99c329b54a449cce9d3eb9de9330fcc4e` |
| `recovery-proxy-complete-ledger.json` | `d9b9bac311e0178d375b1cdc10d5a81573577f82d9bc0370054efe6f13d49126` |
| `final-all-qdrant-points.json` | `1bd7afa434dbcacb75e6e595dad6ca06fc941668a4e4d6ca073cd22c7fbc70cf` |
| `final-all-sqlite-rows.json` | `04c67cf6641fc2efc3f99e13c4c6a31ff712cd95ebce633ee0418a5152670984` |
| `integrated-go-tests.json` | `297aa5401f30020fd29cda8e22ebb71142b59c1d17889c0b211f677b8d1f55db` |
| `compose-provider-complete-ledger.json` | `0fa94507d65573202f5d05ba2aa7ac918a03d9fb4ff30849bfa475e83dacf9d4` |

## Cleanup, limits and handoff

All three executions removed their exact task-owned runtime source roots,
SQLite databases, vector storage and binaries; Qdrant's root-owned nested files
were removed through the cached Alpine image mounted **only** at those owned
storage paths. Own native children were recorded by PID/start time/command and
reaped; SIGKILL was applied only to a held task-owned CLI. Fake provider/proxy
threads and listeners joined. Main final cleanup rebound all six used loopback
ports; complementary cleanup rebound all four. Owned Compose containers/networks
and unique app tags were removed, and native Qdrant containers were absent.
An additional read-only check of all three exact FLH-047 project names found no
container or network; results are `/tmp/flh047-final-resource-check.json`.
Shared Docker images/build cache and unrelated resources were retained. No
FLH-047 runtime storage root or harness bytecode directory remained.

Owned Go `gofmt -l` returned no files; Python AST parsing passed. README.zh-CN.md
exists and its bounded baseline hash is unchanged; shared README behavior was
not modified. Final formatting and preservation checks remain scoped to this
harness and recorded baseline, not a repository-wide formatter or audit.

Limits:

- **Browser interaction NOT RUN**: no chromium/chromium-browser/google-chrome/
  firefox executable or local browser tool was available. The actual HTTP
  handler and native/Compose HTTP requests are separately identified evidence.
- Fake embeddings prove mechanics only; no semantic quality, Recall@K/MRR,
  ANN speedup or real-model performance claim.
- Search/cleanup lease race gates are in-process with actual adapters. Owned CLI
  interruption/outage/Compose tests additionally use actual OS processes. Lease
  expiry uses the inherited explicit clock/isolated lease fault, not a 120-second
  wait. No cross-store atomicity or indefinite arbitrary churn guarantee.
- Whole current inventories are checked. A true representation-version upgrade,
  populated human annotations/admission/INVALID/reassignment, full root
  `make verify`, full frontend tests and parallel FLH-046 CI acceptance are not
  covered or claimed by this bounded recovery rerun.
- Evidence directories are temporary and intentionally retained for human review;
  all runtime data is disposable. CLI text findings O1/O2 remain for the owner.

Human staging command (displayed only, never executed):

```sh
git add -- scripts/validation/flh041/README.md scripts/validation/flh041/phase_b_checks.py scripts/validation/flh041/ownership_probe/main.go scripts/validation/flh041/ownership_probe/recovery.go scripts/validation/flh041/recovery_checks.py docs/validation/FLH-047-semantic-recovery-acceptance.md
```

Codex stops editing at handoff.

Suggested commit message:
test: verify integrated semantic recovery and record CLI text limits
