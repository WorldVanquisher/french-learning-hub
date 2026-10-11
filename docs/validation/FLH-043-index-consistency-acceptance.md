# FLH-043 — Independent acceptance of FLH-042 index consistency

Date: 2026-10-11, Canada/Eastern. Supplied branch label:
`test/flh-043-index-consistency-acceptance` (not inspected).
Actual `pwd`: `/home/worldvanquisher/workspace/flh-nas-codex`.
Codex read AGENTS.md, FLH-042 plan/validation, SEMANTIC_SEARCH.md, migration 011,
and the active application/repository/vector/CLI/HTTP contracts. The FLH-041
investigation and four deterministic fixture/oracle files were reused; its
historical acceptance report remains byte-identical. No general audit, Git or
GitHub command, subagent, production/shared documentation/migration edit,
secret, daily database, paid provider or permanent installation was used.

**INDEPENDENT ACCEPTANCE FAILED: two reproducible production defects.** Across
38 independent cases, 36 passed and two failed. Publication fencing/private
collection isolation, repair, cache reuse, interruption and the populated Linux
Compose path passed. The search metadata replacement race and no-op cleanup
failures below remain for the implementation owner; no production fix was made.
Separately, 53 top-level focused Go tests passed with zero skips, including all
eight real-Qdrant integration tests. Nineteen preserved fixture/oracle tests passed.
Repeated cases are not counted twice. Browser interaction: **NOT RUN**.

## Scope and active interfaces

Codex owns only `scripts/validation/flh041/` and this report. Modified exactly:

- `scripts/validation/flh041/ownership_probe/main.go` — retargeted to FLH-042's
  lease, manifest, physical collection and publication APIs; real service gates;
- `scripts/validation/flh041/phase_b_checks.py` — real-Qdrant acceptance runner,
  observations, fault proxy, CLI processes and actual Compose checks;
- `scripts/validation/flh041/compose_embeddings.py` — counted deterministic
  fixture in the task's Compose network, no host-published embedding port;
- `scripts/validation/flh041/README.md` — current executable harness usage;
- `docs/validation/FLH-043-index-consistency-acceptance.md` — new evidence/handoff.

Active bookkeeping is `semantic_index_spaces`,
`semantic_index_physical_collections` and `semantic_index_manifest`; cache remains
`semantic_embedding_cache`. The probe uses `AcquireLease`, `RenewLease`,
`RegisterCollection`, `RecordManifest`, `RemoveManifest`, `Publish`,
`MarkCollection`, `ForgetCollection`, `CompleteRun` and active read APIs. No
migration-010 `BeginRun`/`RecordPoints`/`FinishRun` invocation is used as evidence.
Production legacy files were neither changed nor removed.

Synthetic seeding uses an isolated migrated SQLite database, four Concepts
(IDs 1–4), three unique production-rendered documents, three normal/orphaned
Concepts and one retired Concept with duplicate wording. Direct fixture inserts
and the source/lease fault mutations are explicitly test-only SQL, not guessed
user edit endpoints. Exported `BuildSemanticIndexDocument` supplies actual texts
and content hashes; indexing's inspected ID order supplies batch attribution.
Fake vectors establish mechanics, not French relevance or performance gains.

## Executed expected/actual checks

| Check | Expected | Actual |
| --- | --- | --- |
| Lease acquisition | Unexpired lease refuses another run; explicit takeover and expired acquisition work | PASS: direct actual repository busy/expiry/takeover; actual killed-holder CLI `sync` exit 4; explicit takeover only after owned process wait confirmed death; CLI accepted an explicitly synthetic expired lease record without takeover |
| Fenced writes | All superseded active writes fail and change no newer record | PASS: nine refusals (renew, record own/newer manifest, remove, publish, mark, forget, register, complete), exact active-state/manifest equality on two real SQLite handles |
| Gated old work | Pause A after ownership renewal at upsert, manifest or publish; B takes over and completes; releasing A cannot alter B | PASS: three real service/Qdrant cases, old `ownership_lost`, no old publication, identical B state, manifest and every point/vector/payload before/after release |
| No-op takeover | B takes over by verified healthy sync; A's writing record alone must not permit publication | PASS: B `verified_unchanged`, same active collection, fenced A publish refused; identical full newer publication observations |
| Build/dedup | Four Concepts sharing three document keys embed each key once; complete publication matches authority/cache | PASS: three attempted documents in two sequential batches, four exact point IDs/payloads, cache vectors and Qdrant-normalized directions agree |
| Restart/sync/rebuild | New CLI processes, server restart, healthy sync and rebuild reuse persistent vectors | PASS: zero document-attempt deltas; sync no-op; rebuild new private collection; full inventories; restarted server keeps same publication |
| Model/dimension isolation | Same wire model under a new identity or dimension cannot reuse the wrong cache/index | PASS: each new space embedded its three keys; separate model identity at 8 dimensions and same identity at 9 dimensions, verified cache tuples/payloads/vectors/collections |
| Invalid provider output | Wrong dimension, zero, nonfinite, short, duplicate index and malformed response cannot cache or publish | PASS: six failed first-batch CLI runs, exit 1, `failed`, zero cache rows for each model identity, no publication |
| Partial embedding | Successful first batch survives later failure; recovery embeds only remaining key | PASS: two valid cached rows after batch-2 failure; retry embedded exactly one remaining document; healthy full inventory |
| Partial upsert | Later refused upsert leaves matching partial private manifest and preserves prior publication | PASS: actual first two points/manifest rows captured while second request's injected 503 held; exit 1; recovery uses cache |
| Lost acknowledgement | Applied points without received acknowledgement do not become published bookkeeping | PASS: real Qdrant had four private points while SQLite manifest had two rows; proxy never sent acknowledgement; CLI exit 1; prior publication unchanged; recovery zero embeddings |
| SIGINT/SIGTERM/SIGKILL | Interrupt only owned CLI; prior publication survives; recover from persistent cache | PASS: graceful signals exit 1/`interrupted`; SIGKILL exit -9 leaves busy lease, explicit takeover rebuild recovers; exact held inventories and no document-attempt deltas |
| Source change | Catch up a changed selected source before publication | PASS: one labelled SQL target fault at first upsert, `catch_up_changes=1`, exactly one new production-rendered input, final points/manifest/cache match current source |
| Missing point | Honest unhealthy status; repairing sync republishes without embeddings | PASS: `missing=[2]`, healthy exact inventory after sync |
| Same count, wrong vector | Count alone must not certify health | PASS: replacing point 2's vector with point 1's gave `vector_mismatch=[2]` at unchanged count; repaired with zero embeddings |
| Foreign/stale/extra point | Full payload/ID/hash verification detects damage | PASS: `foreign_payload=[2]`, `stale=[2]`, `extra=[999]` in separate cases; repaired without embeddings |
| Wrong size/distance | Existing publication shape is incompatible and not healthy | PASS: recreated 9-dimensional or Dot collection reported `shape_ok=false`; sync republished 8-dimensional Cosine points without embeddings |
| Whole collection loss | Status reports absent, search 409 before provider call, sync reuses cache | PASS: observed `exists=false`, actual HTTP 409, zero embedding delta, healthy repaired full inventory |
| Search history/authority | Schema v2 keeps history distinct from health, reads current SQLite authority, writes nothing | PASS: `health_verified=false`, no `complete` field; positive synthetic stale/foreign/missing hits dropped; all SQLite schema/table rows and published point/shape records unchanged; exactly one query input per reached search |
| Current state filtering | SQLite orphaned/retired state filters positive hits, without invented support | PASS: all/orphaned/retired/active HTTP result ID sets match independently calculated positive fake-vector hits and current SQLite lifecycle facts; member/support counts remain zero |
| Search replacement at Query | Retry once with the original query vector against new publication | PASS: real adapter Query gate, B rebuild/deletion, A retry returns current collection; exactly one query attempt |
| Search replacement at CollectionInfo | Same replacement contract applies before metadata request | **FAIL F1:** old metadata request sees deleted collection; service returns not-built despite healthy newer publication, before embedding |
| SQLite write acquisition | Network calls must not hold a write transaction | PASS: `BEGIN IMMEDIATE` acquired during held provider and held real-Qdrant acknowledgements; positive control with held writer failed as required |
| Failed cleanup deletion | Failed retired collection deletion remains recorded; next run retries | Retention PASS, **next healthy sync FAIL F2**; later rebuild successfully removes it without embeddings |
| Unrecorded collection | Rebuild removes an owned unrecorded collection of this space | PASS: visible in status, deleted by rebuild, current publication/cached vectors preserved |
| Compose semantic profile | Populated real profile, writable storage, packaged CLI, counted search and outage/restart | PASS: all services started from cached images; build published four points from three inputs; actual packaged CLI status verified healthy; actual search v2; Qdrant stop gave search 502 and unavailable status while keyword returned all four Concepts; preserved-storage restart + sync reused cache |
| Resource cleanup | Own processes reaped; exact containers/networks/tags and temp data removed | PASS on all recorded executions; final complementary run also bound every used loopback port successfully after teardown; shared Docker build cache retained |

The existing eight real-Qdrant integration tests all ran: build/sync/rebuild/
restart/cache reuse, superseded gates, fence-only no-op takeover, point loss/
same-count replacement, whole-collection loss/wrong shape, interruption,
independent SQLite write locks and unavailable Qdrant. Their Concept source is
in-memory and their provider is deterministic test code; they are corroborating
real-Qdrant evidence, not the independent actual-SQLite Concept cases above.
Their passing results do not erase the two independent failures.

## F1 — Medium: replacement before metadata lookup gives false not-built error

Location: `internal/application/semantic_search.go:82–100` (`published`) and
`:108–110` (initial Search failure). Retry logic exists only at `:125–137`, after
Query fails.

Reproduction (`search-info-race`, actual service/repository/provider/Qdrant):

1. Start from a verified healthy publication. A reads its SQLite pointer.
2. Pause A immediately before the real adapter's `CollectionInfo` request.
3. B rebuilds/publishes a new private collection and deletes the replaced one.
4. Release A. The old collection no longer exists; the new one is healthy and
   published. A returns `ErrSemanticIndexNotBuilt` for the deleted old name.

Expected: re-read the publication pointer and retry once on the current
collection, as the documented replacement-race contract says. Actual:
`semantic index has not been built: published collection ... is missing from
the vector store; run: semantic-index sync`. There are zero query embedding
attempts in this early-failure case. The positive Query-gate control does retry
and consumes exactly one query vector. Before/after current publication records,
manifest and full points appear in the failed case's report; this is an actual
replacement race, not whole-collection loss.

Impact: ordinary successful rebuild can transiently break search and incorrectly
suggest operator repair. The existing HTTP error mapping would expose 409
(source-based attribution; this gated reproduction invoked the service directly).
Suggested owner verification: retain both metadata and Query window cases, plus
unchanged-pointer true-loss behavior; no unbounded retry or extra query embedding.

## F2 — Medium: verified healthy sync skips pending cleanup

Location: `internal/application/semantic_index.go:481–489` returns on healthy
verification before the cleanup path at `:621–662`.

Reproduction (`failed-retired-deletion` then `cleanup-next-healthy-sync`):

1. Hold a healthy existing publication.
2. Rebuild through the owned forwarding proxy. Inject one HTTP 503 only on
   deleting the replaced collection; other Qdrant requests are real.
3. New publication succeeds. The old actual collection remains and its SQLite
   physical record is `retired`, as expected after failed deletion.
4. Remove the injection and run normal `sync`. It verifies the new publication
   healthy and exits 0 with `verified_unchanged`, `cleaned_collections=0`.
5. Status still lists the same retired record; the vector collection remains.
   A subsequent rebuild successfully removes it, without document embeddings.

Expected: the documented next-run cleanup retries recorded leftovers, even if
current publication is healthy. Actual: every healthy no-op sync returns before
cleanup. Similar leftovers can follow a killed run or no-op takeover. Impact is
retained disposable collections/bookkeeping and misleading next-run recovery
instructions; current publication safety is not compromised by this defect.
Suggested owner verification: fail one deletion, clear the fault, perform only
sync, then inspect actual old collection absence and its record/manifest removal.
No expectation was relaxed to green this case.

## Provider and inventory evidence

Authoritative independent runs: `/tmp/flh043-run2/` and
`/tmp/flh043-extra-final/`. Reports include expected/actual case results, complete
commands/toolchains/binary hashes and owned Docker/process identities. Related
JSONs retain full SQLite schema/table rows, cache bytes, production-rendered
texts/hashes, full paginated actual point/payload/vector inventories, before/after
race observations, held private records and exact provider input-hash ledgers.
Each directory has `artifact-sha256.json` for all retained files.

| Ledger | Requests | Attempted documents | Attempted queries | Measured max active |
| --- | --- | --- | --- | --- |
| run2 native HTTP provider | 19 | 25 | 4 | 1 |
| final complementary 8-dimensional provider | 6 | 3 | 4 | 1 |
| complementary 9-dimensional provider | 2 | 3 | 0 | 1 |
| run2 Compose provider | 3 | 3 | 1 | 1 |

Every native provider batch was at most two texts; normal and failed-input
attempts are distinguished. The native ledger's 25 document attempts include
six intentionally invalid batches, later-failed batch attempts and the canceled
provider request. `valid_response_texts` are wire-fixture outcomes, not a claim
of committed cache rows or consumed acknowledgements. Cache keys/bytes and
publication inventories are independently checked. Per-operation delta evidence
proves status, healthy sync, rebuild, repair and server restart add no document
attempts; the sole source catch-up input and new model/dimension inputs are
explicitly attributed. Search contributes only the expected query inputs.

For every healthy inventory, explicit expected IDs are 1–4, duplicate IDs share
the same content hash, payloads exactly match `(concept_id, content_hash,
representation, model_id, dimensions)`, float32 cached values match the existing
deterministic fixture, and Qdrant vectors agree after cosine normalization
(tolerance 1e-5). Full manifest hashes equal the current production document
hashes. No search top hits or Qdrant point count is accepted as full-inventory
proof. Query ID assertions do not force a tie order between duplicate documents.

Held lost-ack/SIGINT/SIGTERM/SIGKILL records in run2 show four actual private
points versus two acknowledged manifest rows, prior publication unchanged and
SQLite write acquisitions around 0.10–0.11 ms (a lock-mechanics observation,
not a performance claim). The complementary refused-upsert case has two actual
points and two manifest rows. `final-all-qdrant-points.json` and
`final-all-sqlite-rows.json` in the final complementary run capture every remaining
collection/point and active/legacy/cache row before destroying owned resources.
Run2 retains per-publication/per-race full inventories; its earlier runner did
not additionally capture a single final whole-instance scroll file.

## Commands, baseline and toolchains

Root commands actually executed, with output redirected to adjacent /tmp logs:

```sh
pwd
cat AGENTS.md
python3 -B scripts/validation/flh041/phase_b_checks.py --output /tmp/flh043-run1
python3 -B scripts/validation/flh041/phase_b_checks.py --output /tmp/flh043-run2
python3 -B scripts/validation/flh041/phase_b_checks.py --extra-only --output /tmp/flh043-extra
python3 -B scripts/validation/flh041/phase_b_checks.py --extra-only --output /tmp/flh043-extra-final
python3 -B scripts/validation/flh041/test_fixtures.py
```

Run1 exited 1 and was an intermediate harness run. Seven additional apparent
failures were harness mistakes: repository list order differed from indexing's
sorted ID order; the source fixture registration used that wrong order; raw
Qdrant optimizer/segment telemetry was compared as immutable vector data; and
the early metadata race incorrectly expected a query embedding before its error.
Those owned harness issues were corrected. Immutable shape/point/payload/vector,
SQLite, cache and per-input counter assertions remain; raw metadata is retained.
Run2 exited 1 with only the two production failures. Both complementary runs
exited 0 (six cases each, counted once). Fixture self-tests exited 0, 19 tests.
No failed run or test was erased. No expectation for either production defect
was changed. Later runner changes add current source hashes and final whole-
instance/port cleanup evidence; the final complementary run exercised them.

Inside the private source copies, actually executed:

```sh
go build -o <private>/server ./cmd/server
go build -o <private>/semantic-index ./cmd/semantic-index
go build -o <private>/probe ./scripts/validation/flh041/ownership_probe
go version -m <each-binary>
go test -json ./internal/application ./internal/storage/sqlite ./internal/vectorindex ./internal/embedding ./internal/transport/http ./internal/config ./cmd/semantic-index -run 'Test.*(Semantic|Qdrant|HTTPProvider|Embedding)' -count=1
```

The focused Go invocation had `FLH_QDRANT_URL` set to the owned actual instance.
All builds/tests used sanitized environment, private HOME/GOCACHE/TMPDIR,
`GOENV=off`, `GOTOOLCHAIN=local`,
`GOFLAGS='-mod=readonly -buildvcs=false'`, `GOPROXY=off`, `GOSUMDB=off`,
`CGO_ENABLED=0`, and the existing module cache. No .env/credential was read.
Exact deleted-private argv are preserved in `report.json`; angle-bracket paths
above summarize them, not executable staging instructions.

Docker was accessed through approved sandbox escalation. The unchanged copied
Dockerfile was built with cached pinned bases, `DOCKER_BUILDKIT=0`,
`--pull=false --network none`, and a unique tag; each base was locally inspected
first. Compose used its actual semantic profile, empty env file, unique project,
image-only app override and an extra owned counted provider service, with
`up --no-build --pull never`. The cached Python fixture image was inspected and
run by image ID; nothing was downloaded. App/Qdrant host publications were
127.0.0.1 only. Exact `docker run/inspect/compose exec/stop/start/down` commands
and resolved configuration are in the report.

Observed Linux amd64 toolchains: native Go `go1.27.1-X:nodwarf5`, Python 3.14.7,
Docker client 29.8.1/API 1.55 (downgraded), daemon 29.7.2/API 1.55,
Compose 5.5.1. Actual Qdrant HTTP version 1.19.1, commit
`6ab21cac18ebb6f4ae29102c7f8f5cc11affd5de`, image ID
`sha256:dd57172b0bbebb29b0a96a37c1f378a317449730c36cdfe68feabe36e740a92b`,
pinned reference from compose.yaml. Docker build bases identify pinned Node
24.11.1-alpine3.22, Go 1.26.5-alpine and Alpine 3.22.2; these are inspected
image identities, not separate in-container compiler version executions.

Run2 application image:
`sha256:c879717af1597e13d428be294aff5d0b49b635f5b54bdd5c4d947da890b3f542`.
App runs UID:GID 1000:1000. Its bound SQLite file was UID:GID 1000:1000/mode
0644. Actual Qdrant runs UID:GID 0:0; the provided parent storage directory was
1000:1000/mode 0755, with root-owned nested collections. Both wrote successfully
and preserved storage across the observed Compose Qdrant stop/start. Root-owned
nested data was removed through an already cached Alpine cleanup container
mounted only on the exact task-owned storage paths. No host chmod/chown,
installation or unrelated resource deletion was performed.

Run2 native binary SHA-256:

| Binary | SHA-256 |
| --- | --- |
| `server` | `16142a40bc118ce6117d7ddefc50e9fad2e383e884a385964eacb6cbe9b0bf38` |
| `semantic-index` | `17b4b215072215e846eea9afa28296a1364cefd2445faf072b88e70c9b3639f7` |
| `probe` | `4329636b612fd21040989ed7faceeb66e784dfc317cd13d1d7169a438dfa34d2` |

Pre-edit bounded baseline: `/tmp/flh043-baseline.json`, 190 inspected files;
this is not a general repository audit. Final complementary run also recorded
191 current public file hashes and 232 private source-copy hashes. Current
harness hashes differ from the pre-edit baseline as intended; production and
historical report hashes do not. Selected pre-edit SHA-256:

| File | SHA-256 |
| --- | --- |
| `AGENTS.md` | `3e29b4127ac46851fa878b522016949e3c8b8c9d2493668776b4b8136bbf7281` |
| `docs/plans/FLH-042-index-run-consistency.md` | `a8d907ded38d48de2a4e8584317e265b49f455470dc47b85b32775174df072b3` |
| `docs/validation/FLH-042-index-run-consistency.md` | `2638239ee55ef8a59e7ceaf61ca20a1a3159a97ad77c125d74d62955e862b010` |
| `docs/SEMANTIC_SEARCH.md` | `a8ad8b0ed5f53b39539ffc269f8430e8bdc08968b2d9e7683b1b9a5800af256d` |
| `docs/validation/FLH-041-vector-search-acceptance.md` | `eae2005f911247121732ff44545ce1ab907724625ac179e48f40f51d9e982683` |
| `migrations/011_semantic_index_runs.sql` | `cc97962afe6f6207a788a77a60af5366d90d5082d4b4aae7a45af091bf0682d3` |
| `internal/application/semantic_index.go` | `b0d2fb4c9e55d32a43a327427b38dd624ff5da3ff38fd2fd28d302ee22b41a72` |
| `internal/application/semantic_search.go` | `955201dfef635ed9d6000ac836c1a673af0d826922489328592e5077d8ed3c14` |
| `internal/storage/sqlite/semantic_index_repository.go` | `6936a91f7df81bcfba1236212c02de1773780d67614abc32aecea0c3e6218d47` |
| `internal/vectorindex/qdrant.go` | `d606d181bca8798d214e00aaf778a125553c20b67eb52f23c373ee70b0395865` |
| `cmd/semantic-index/main.go` | `a0f4551f1315b8245ae02c2f52eae8e129cbadd984a9a4ddc77720c3ec9f679d` |
| `compose.yaml` | `8d3ba02486dcb1128fcd63c5b7dbaaf6213dcfd779d00b642c5c1bbce4e50728` |
| `Dockerfile` | `f13da53fdac48e44160442d3f44e554638449553f4851ccea68ee644f2480f63` |
| `scripts/validation/flh041/fake_embeddings.py` | `ddcb5df1d12fc9fbed7416e487e8d4951ab467ecaacc3e263099285646919d74` |
| `scripts/validation/flh041/fixtures.json` | `71e6ad734ce17bd49afffd1186ef99ef4d1cdf83ad9f1170edf67f5d28ce409e` |
| `scripts/validation/flh041/oracles.py` | `0988fd2852a1d6a08997ac498ab7692a0237a0cbc5701ced92168aec3cf8565a` |
| `scripts/validation/flh041/test_fixtures.py` | `1df0a63e43edd5d43565f7f932ba8dd2dd3a994a1b88175ee306564087f8cb06` |

## Relation to FLH-041 matrix and remaining limits

| Matrix IDs | FLH-043 coverage |
| --- | --- |
| P01–P05 | Real dedup/persistence/restart/content/model/dimension cases and exact inventories/counters; invalid output refused |
| P06 | Current representation and payload identity verified; **actual representation-version upgrade NOT RUN**, no supported version selector exists and no flag was invented |
| P07–P09 | Actual partial provider/upsert, lost acknowledgement and owned process signals/recovery |
| P10 | Active repository fences, real gated takeover and the narrow no-op takeover window; prior legacy probe is not evidence |
| P11–P12 | Actual single-source catch-up; bounded provider/upsert/scroll batches and held-call write probe with positive control; continuous churn/deletion catch-up only existing Go unit evidence, not an independent SQL source scenario |
| P13 | Positive actual stale/foreign/missing IDs excluded, exact current SQLite source and full-record health verification |
| P14 | Actual orphaned/retired/all/active filters and zero support/member facts; **populated human membership/admission/INVALID/reassignment transitions NOT RUN** in this index-focused fixture |
| P15 | Populated Concept HTTP search, query-only counters, all SQLite schema/table rows and point/shape equality; annotation tables empty before/after |
| P16 | **Browser NOT RUN**: no Chromium/Chrome/Firefox executable or browser tool was available; no automated traversal is claimed as human interaction |
| P17 | Actual whole-loss/shape repair, Compose Qdrant stop/start outage/storage restart and cached recovery |
| P18 | Observed success and failure paths cleaned; no untested Docker-build interruption cleanup guarantee |

Gate races use exported in-process service hooks/wrappers and actual adapters,
not two OS CLI processes. Interruption/busy recovery additionally uses actual
CLI processes. Expiry uses API-supplied clocks or an explicit expired SQLite
fault record, not a 120-second wall-clock wait. Provider/Qdrant failure injection
is local; every successful point mutation/scan is against real Qdrant. Search
races use a zero-count summarizer because the independent seed has no Units;
HTTP authority/read-only checks use the actual production service wiring.

Full root `make verify`, frontend test suite and browser interaction were not
run. The unchanged Dockerfile build succeeded with the actual allowlisted source;
run1 compiled changed frontend/Go layers and run2 reused those layers. This
certifies packaging/executable behavior, not interactive presentation. No real
embedding provider, measured relevance/ANN speed, Recall@K, MRR or performance
gain is asserted.

## Cleanup and handoff

All four runner executions recorded no fatal or cleanup error and removed their
private source copies/databases/storage/binaries. Owned native processes were
identified by PID/start time/command and reaped; SIGKILL applied only to an owned
CLI. Exact task container names/project labels checked empty after removal;
Compose project networks and unique image tags were removed. Fixture/proxy
threads joined. Final complementary cleanup also re-bound all four used loopback
ports after teardown. Earlier runs establish container/process absence; they
pre-date the explicit final port-binding assertion. Raw evidence/logs remain
under /tmp intentionally and may expire. Shared Docker build cache was retained,
with no global prune. No unrelated process was signaled.

Final checks: owned Go formatting, owned Python AST parsing, unchanged bounded
production and historical FLH-041 report/fixture hashes, and successful cleanup
fields. README.zh-CN.md exists and is unchanged; root README behavior was not
modified by this task. Acceptance awaits owner resolution of F1/F2 and rerun of
those cases. Remaining matrix limits above are explicit, not green substitutes.

Human staging command (displayed only; never executed):

```sh
git add -- scripts/validation/flh041/README.md scripts/validation/flh041/phase_b_checks.py scripts/validation/flh041/ownership_probe/main.go scripts/validation/flh041/compose_embeddings.py docs/validation/FLH-043-index-consistency-acceptance.md
```

Codex stops editing at handoff.

Suggested commit message:
test: verify fenced index publication and record acceptance defects
