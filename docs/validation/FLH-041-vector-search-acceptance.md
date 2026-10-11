# FLH-041 — Independent persistent-vector-search acceptance

## Phase A checkpoint — 2026-10-10

**PREPARED; production acceptance NOT RUN.** Nineteen fixture/oracle self-tests
pass. Persistent cache reuse, index consistency/recovery, actual Qdrant and
frontend interaction remain Phase B work after the human supplies the integrated
implementation. Fake embeddings establish mechanics only; there is no claim
about semantic relevance, ANN speed, Recall@K or MRR.

Supplied branch label: `test/flh-041-vector-search-acceptance` (not inspected).
Actual `pwd`: `/home/worldvanquisher/workspace/flh-nas-codex`.
Codex read AGENTS.md and inspected bounded embedding/provider/retrieval contracts.
Claude remains the FLH-040 production owner in the separate checkout; Codex owns
only this report and `scripts/validation/flh041/`. No Git/GitHub command, subagent,
production change, migration, shared harness/documentation edit, secret, paid
provider or daily database was used.

The supplied tree already contains FLH-040 source and owner-written documentation.
Their presence is an inspected planning reference, **not a human Phase B handoff**.
No semantic CLI/server/demo, production test suite, actual Qdrant or browser was
launched in Phase A. There will be no polling of Claude's checkout.

## Existing contracts and dependency boundaries

Inspected existing files include `internal/embedding/{http.go,http_test.go,factory.go}`,
`internal/application/{concept_retrieval.go,concept_embedding_retrieval.go,concept_retriever_registry.go,concept_retrieval_evaluation_service.go}`,
and embedding configuration in `internal/config/config.go`.

- `EmbeddingProvider` accepts a context and batch of exact texts; it owns no
  persistence, annotation, evaluation or resolution policy.
- The HTTP adapter posts `{model, input: [string, ...]}` to `<base>/embeddings`.
  Response `data` indices must cover each input once; vector counts, nonempty
  dimensions, equal dimensions and finite components are validated. Timeouts and
  failures are categorized; headers/body details are not public errors. Empty
  input avoids a provider call. Provider Name is a display name, not cache identity.
- `concept_embedding_text_v1` serializes query evidence and Concept identity
  fields with sorted identity features. IDs, signatures, labels and derived
  support/lifecycle are not embedding text. The existing evaluation retriever
  embeds query plus supplied documents in one per-call batch and persists nothing.
- The M12/M13 evaluation registry/population/metrics are separate from Library
  semantic search. Its retired-excluding evaluation universe must not be silently
  imposed on Library state filtering; retired and orphaned are different facts.

For planning only, read the present FLH-040 plan, SEMANTIC_SEARCH.md,
ARCHITECTURE §9.3 and bounded semantic source definitions. The documented contract
says SQLite is authoritative; document vectors are cached by content hash,
representation, explicit model identity and dimensions; indexing is an explicit
bounded sequential CLI operation with context/run ownership; Qdrant is disposable;
search re-reads hits, embeds only its query, never writes and never falls back.
`GET /knowledge-library/semantic-search` and `semantic-index build/sync/rebuild/status`
are **documented existing interfaces**, not endpoints invented by this task.
Re-read their actual integrated implementation/schema/config/exit contracts at
Phase B before creating any adapter or executable acceptance command.

Current docs describe the fixed `concept_embedding_text_v1` representation and
all/active/orphaned/retired Library filters. A representation-change test must use
confirmed old-space/cache fixture evidence or a real version upgrade; no guessed
representation selector or new identity-mutation/retire/delete endpoint is supplied.

## Owned preparation and acceptance criteria

Created exactly these task files:

| File | Purpose |
| --- | --- |
| `scripts/validation/flh041/fixtures.json` | Opaque synthetic documents/queries, duplicate and changed inputs, model/dimension/representation axes and authority scenarios; no production payload or relevance labels |
| `scripts/validation/flh041/fake_embeddings.py` | Ephemeral IPv4-loopback batch fixture, deterministic exact-input/model vectors, request/per-text attempt counters, classified input digests, faults and bounded gates |
| `scripts/validation/flh041/oracles.py` | Assertions over explicit supplied cache/point/ID/ledger/snapshot observations; no serializer, caching, upsert, filtering, ranking or state implementation |
| `scripts/validation/flh041/test_fixtures.py` | Real fixture HTTP and negative assertion tests; cleanup tests; no application/Qdrant acceptance |
| `scripts/validation/flh041/README.md` | Executable self-test command, library usage, counter semantics and Phase B adapter limits |
| `docs/validation/FLH-041-vector-search-acceptance.md` | This plan/evidence/handoff |

Phase A criteria: deterministic repeated values; per-input accounting even on
failed calls; controllable late-batch failures/gates; demonstrable batch/concurrency
measurement; oracle rejection of false reuse, wrong cache identities, stale
record substitution, search writes and false completion; owned listener/thread
cleanup. All are met by self-tests, not by production execution.

Dependencies remain read-only. No runtime Qdrant HTTP adapter, fake vector index,
cache schema, collection-name generator, Concept serializer or production seed is
implemented here. Fake fixtures do not duplicate Claude's production design.
README.zh-CN.md exists; root README behavior/setup/contracts were not changed, so
no shared Chinese documentation edit was needed or authorized.

## Phase B bounded acceptance matrix

Each row requires real observed SQLite rows, complete owned Qdrant vector/payload
records and fake-provider ledger evidence, not response text alone. All rows are
**NOT RUN in Phase A**. Fixture/oracle readiness is not production coverage.

| ID | Setup/fault and expected result | Required evidence |
| --- | --- | --- |
| P01 | Fresh synthetic catalog with two Concepts sharing identical document text plus distinct documents. Build embeds each unique cache key once, publishes all eligible Concept IDs. | Exact input-hash multiset, cache keys/vector values, all point IDs/vectors/payloads, owning complete run; duplicates count once by document key rather than Concept count. |
| P02 | Keep provider ledger alive; restart server/CLI, unchanged sync, status and rebuild. Unchanged documents reuse persistent vectors without document attempts. | Full before/after SQLite cache contents and real Qdrant contents; zero document delta; status makes no embedding calls; rebuild point values agree with cache. |
| P03 | Add a distinct document and exercise a supported content change or explicitly labelled isolated source-fixture mutation. Only new content keys embed; old vectors remain attributable. | Independent predeclared keys and exact deltas; source hash is from the integrated representation, not the fixture's opaque text digest. No guessed edit endpoint. |
| P04 | Change explicit model identity while keeping wire model constant, then wire model with correctly changed identity. Existing collection/cache must not supply new-space vectors. | Old/new cache tuples, collection metadata, payload identity and new document attempts; compare actual vectors even when wire-model-constant values happen to coincide. |
| P05 | Change dimensions; verify new space and configured-size vectors. Inject wrong provider dimension and incompatible collection. Neither invalid vectors nor wrong space can be published as healthy. | Cache vector byte lengths, actual Qdrant dimensions/payloads, exact expected failure, no invalid cache insert or false complete. |
| P06 | Representation-axis isolation: old representation cache/foreign points must not be reused by current representation. Actual version-change execution only if integrated API supports it. | Distinct supplied keys and payloads; no invented production version flag; unsupported real upgrade reported NOT RUN rather than simulated production support. |
| P07 | Fail embedding batch 2 after batch 1 succeeds; also malformed/count/index/NaN/zero/dimension failures. Retry through documented sync only. | Per-input attempted and valid-response counts, committed vectors from successful batches only, partial state; recovery does not re-embed already committed good keys or cache invalid output. Failure attempts are not successful persistence. |
| P08 | Real Qdrant behind a task-owned fault gate/proxy, grounded in inspected adapter requests. Fail a later upsert; optionally apply upstream then lose its acknowledgement. | Actual Qdrant records and SQLite publication ledger disagree only at observed failure boundary; no false complete; sync/rebuild reconcile and reuse cache, with no automatic fallback/retry. |
| P09 | Hold acknowledgement after upstream applied points; interrupt only owned CLI before bookkeeping. Exercise graceful SIGINT/SIGTERM and a separately owned SIGKILL run. | Upstream applied vector proof versus absent bookkeeping, actual CLI exit/run state, no false complete; next owning sync recovers. Lost ack is distinguished from ack consumed by CLI. |
| P10 | Gate old run; start newer run for same space. Release old after newer owns/completes. | Both run IDs/CLI exits, final stored owner, all vectors and cache; old cannot overwrite newer completion. Per-run providers/ledgers isolate concurrency observations. No universal cross-run exactly-once embedding assertion is imposed without a contract. |
| P11 | Source changes after selection and before publication or final validation, using confirmed API or clearly labelled task-owned SQLite/source fault. | Pre/post source observations, blocked publication/changed hash, partial/not-complete run; sync converges with expected provider deltas. Source-fixture changes are not evidence of an unsupported user edit workflow. |
| P12 | More unique documents than a small confirmed batch limit; gated in-flight request; cancel CLI. | Every provider/upsert batch within actual bound, per-run max active request <=1, prompt owned process exit, no later batch, partial/run error; release fixture gate and verify recovery. Held network call must not retain an SQLite write transaction: independent bounded write probe on isolated DB. |
| P13 | Inject missing/deleted IDs, stale hashes and foreign model/representation/dimensions into real owned Qdrant records. | Read all payloads/vectors; compare exact returned IDs/order against explicitly supplied SQLite facts and skip counts; no substituted candidates, no provider document calls. Deleted rows are synthetic fault fixtures if no deletion API exists. |
| P14 | Supported/orphaned/retired current SQLite Concepts, membership/admission/reassignment transitions, state filters. | Current facts/counts and expected IDs, not historical SAME links or vector payload state. Orphaned is not deleted; retired is a lifecycle/filter fact, not automatically the M12 excluded universe. No current support fabricated from historical/suppressed evidence. |
| P15 | Repeated valid searches after build, plus invalid query/unbuilt/incompatible/provider-failed search cases. | One query input per reached healthy search, zero document inputs and no vector-cache writes; early-rejected requests need not call provider. SQLite all-table snapshots incl. sequence/index state and vector records unchanged. |
| P16 | Search, view source, change mode/filters or retry in browser if available. | Real browser network/console/navigation evidence and unchanged annotation/judgment/link/membership tables; no indexing write or keyword fallback. Without browser mark NOT RUN; HTTP/mock evidence stays separately labelled. |
| P17 | Stop only owned Qdrant; search/status expose actual unavailable/timeout category. Restart preserved storage; separately delete only owned vector storage/collection then sync/rebuild. | Real process/collection state, error categories/CLI exits, source/cache preserved, recreated full point inventory and zero re-embedding of good cached documents. Partial indexes labelled honestly. |
| P18 | Success and every failure path clean up task-owned server/CLI/provider/proxy/Qdrant. | PID/start-time/command and socket/container attribution, joined fixture threads, closed reserved ports, removed owned temp dirs/storage; no unrelated process/volume/container signaling/deletion. Cleanup failure fails acceptance. |

Documented state names/HTTP/CLI codes are references to confirm at integration;
Phase A does not hardcode a production DTO or database layout into an executable
adapter. Exact expectations must be recorded before each probe, including every
allowed surviving partial record. Do not erase assertions to accommodate a failure.

## Phase B execution and resource plan

1. Human supplies the integrated checkout/handoff. Re-read AGENTS.md, actual
   FLH-040 contract, migrations, provider and Qdrant adapter, CLI flags/signals,
   setup/recovery commands and frontend transport. Record exact hashes/toolchains
   and available Qdrant binary/container identity. No Git commands.
2. Use a new task-owned /tmp root, fresh SQLite, synthetic API records and isolated
   HOME/config/cache. Copy builds/frontend source privately if checks could write.
   Use default rule-based analysis and disabled extraction unless a counted local
   extractor is specifically required to make a support fixture. No production
   credential/env files. Check ports before launch and verify actual loopback
   listener/PID ownership; never attach to an existing Qdrant or app.
3. Launch **actual local Qdrant** using a human-supplied available binary/image
   and private storage; record binary hash/version or image digest. No permanent
   dependency installation or implicit download. Missing actual Qdrant is NOT RUN,
   not acceptance via an in-memory substitute. Allocate separate run prefixes and
   owned ports; delete only resources the task created.
4. Implement a thin task-owned observation adapter only after mapping actual
   contracts. Read all SQLite tables in a consistent read-only snapshot; decode
   cached vectors and inspect every Qdrant point (pagination, payload, vector), not
   just count/top hits. Use observed serialization/exported application functions
   for attribution rather than reimplementing document or identity rules.
5. Map exact provider texts to document/query roles, retain one ledger across
   application/index restarts, and run pristine build/search/restart/sync/rebuild
   before fault mutations. Use fake vectors with sufficiently separated synthetic
   values only to make mechanical IDs/order assertions reproducible. Do not turn
   that fixture into French semantic truth or force Qdrant tie-order guarantees.
6. Run independent per-case faults and recoveries; compare all three authorities
   (SQLite source/cache/publication, actual vector points, provider events). Gate
   boundaries give deterministic competing/source-change/interruption probes;
   Qdrant upsert fault adapter will be written against actual inspected requests,
   never a guessed endpoint. Restore or discard each isolated fixture after its case.
7. Execute documented production setup/checks on the supplied integrated source
   with private output. Use a real browser if available, otherwise explicitly NOT
   RUN. Record all argv/expected/actual/exit/time, state snapshots, counters, point
   inventories, cleanup and unexecuted cases. Report production findings with file
   location, concrete failure scenario, impact and reproduction; never patch them.
8. Deliver Phase B evidence and stop editing. Fake-vector mechanics do not justify
   relevance/ANN/Recall@K/MRR claims; such measurements require a separate dataset,
   evaluation policy and actual recorded run.

## Phase A executed evidence, cleanup and limits

Commands actually executed:

```sh
pwd
cat AGENTS.md
python3 -B scripts/validation/flh041/test_fixtures.py > /tmp/flh041-phase-a-initial.log 2>&1
python3 -B scripts/validation/flh041/test_fixtures.py > /tmp/flh041-phase-a-tests.log 2>&1
python3 -B scripts/validation/flh041/test_fixtures.py > /tmp/flh041-phase-a-verified.log 2>&1
env GOENV=off GOTOOLCHAIN=local go version
node --version
npm --version
```

Bounded rg/sed/cat reads inspected the files named above; the hypothesized split
`internal/config/embedding.go` did not exist, so configuration was read from its
actual `internal/config/config.go`. No missing file was fabricated. Inline Python
parsed all three owned Python files with ast.parse, loaded fixtures.json, and
verified inspected baseline hashes unchanged; no bytecode was written.

| Check | Expected / actual |
| --- | --- |
| First sandboxed self-test | Expected 19 passing tests; actual 15 socket-permission errors from fixture tests/subtests. No production or Qdrant test; retained initial log. |
| Same self-test with permitted loopback sockets | All 19 tests PASS; initial permitted run 0.558 s in `/tmp/flh041-phase-a-tests.log`, final strengthened cleanup run 0.542 s in `/tmp/flh041-phase-a-verified.log`. Permission change only enabled task-owned local sockets. |
| Stable vectors and exact indexed response | Same values across fixture instances; changed exact text/model gives changed values; dimensions and reversed indices checked. This is fake reproducibility, not persistent cache reuse. |
| Failure controls/counters | Every programmed failure reached its expected status/body/disconnect; attempted duplicate texts counted twice, successful first batch remained distinct from failed second batch. |
| Gates/concurrency/cancellation | Gate allowed measured overlap of two requests; max-concurrency=1 oracle rejected it. Client timeout happened while one fixture request remained active; release/cleanup ended it. Production Go cancellation was not tested. |
| Negative oracle mutations | Wrong cache axes/values/count/dimensions/nonfinite/zero, ledger reset, unknown input, document attempt during query-only search, changed SQLite/vector snapshot, stale payload with equal count, reordered/substituted/duplicate IDs and false complete all rejected. |
| Cleanup | Context success/error closed fixture listeners and joined threads, including release of an active gated request on an exception; explicit post-exit connection refusal test passed. No child process, database, Qdrant storage, package or repository-generated output was created. |

Actual tools: Python 3.14.7 (GCC 16.1.1), Linux 7.1.8-arch1-3 x86_64, glibc 2.44.
Version commands reported Go `go1.27.1-X:nodwarf5 linux/amd64`, Node `v26.9.0`,
npm `12.0.2`; no Go or frontend build/test was run in this phase. go.mod declares
Go 1.26.5; the observed compiler is not claimed to be that release pin.

`/tmp/flh041-phase-a-baseline.json` retains the inspected pre-edit file hashes.
The following were verified unchanged after preparation:

| File | SHA-256 |
| --- | --- |
| `AGENTS.md` | `ce868474059bc109a16a332d24ea2b328a57296367616437c88a3bad4300d057` |
| `internal/embedding/http.go` | `1bea0ee93479e7c1f84f5a799667402f6ab78fb76d092aa3a96c6590ec6710c2` |
| `internal/embedding/http_test.go` | `80d3c55287206fb307c2f22992888824fceafa5dd6262e41e623d96e06ca3375` |
| `internal/embedding/factory.go` | `e760a6b5c1edfadb445f0db074b8f329e9fd02874dc19255f4c5100817156ee0` |
| `internal/application/concept_embedding_retrieval.go` | `234d8ee5d17c05c0474a6f4102ceed7659cde9ff3cc024aa4a956f1cd17ff30d` |
| `internal/application/concept_retrieval.go` | `0768fd4b77a2beca63900c09329e9472df8b8f078a48c16393c4894b0d6e2b77` |
| `internal/application/semantic_index.go` | `5e40a3f9f72957778fd04446f7c9b7068ddf56433255731d3493fc18ef58a0bc` |
| `internal/application/semantic_search.go` | `b85391cf82ab4f41303f53bf308891d1f0e9e6314bbf38c0ea8fce1e996da2c2` |
| `docs/plans/FLH-040-persistent-vector-search.md` | `300d350aad9fb55e84171f679de57df4ff97fc65c4995b218b7f9c3091534e4a` |
| `docs/SEMANTIC_SEARCH.md` | `f3557826429fcd9b6f25dd20ffe10f918f2432bc83379d14e602e79f60bb1dc4` |
| `README.zh-CN.md` | `a70ca8affa33151029e959a56a35363b2afe65670386830981c20ff59bc62ce2` |

This is a bounded inspected-file baseline, not a whole-repository audit. Only the
six new task files listed above were written. Evidence logs/baseline JSON remain
under /tmp; they are not committed files. Fixture self-tests use ephemeral socket
resources and have no persistent data directory to remove. No external network
request was made.

Remaining limits: no production persistence/index/search assertion has run;
no actual Qdrant outage/rebuild/upsert or publication gap was exercised; no
application context cancellation, competing production build, source mutation,
frontend/browser interaction, real embedding quality, performance or retrieval
metric measurement is claimed. The oracles rely on correctly captured complete
observations; they deliberately do not reconstruct production authority. Phase B
must inspect source and real state to make those observations trustworthy. No
reproducible production defect is asserted by Phase A.

## Handoff

Phase A acceptance preparation is complete. Pending: human integrated handoff and
all P01–P18 production probes. No polling, production takeover or further editing
is scheduled. Human staging command (displayed only, never executed):

```sh
git add -- docs/validation/FLH-041-vector-search-acceptance.md scripts/validation/flh041/README.md scripts/validation/flh041/fixtures.json scripts/validation/flh041/fake_embeddings.py scripts/validation/flh041/oracles.py scripts/validation/flh041/test_fixtures.py
```

Suggested commit message:
test: prepare persistent vector search acceptance fixtures and plan


---

## Phase B integrated checkpoint — 2026-10-10 (local date)

**NOT ACCEPTED — prerequisite limited, with a reproduced SQLite ownership
finding.** Human handoff supplied `test/flh-041-vector-search-integrated`; branch
state was not inspected. Actual `pwd`:
`/home/worldvanquisher/workspace/flh-nas-codex`. Read AGENTS.md, implemented
ARCHITECTURE §9.3, SEMANTIC_SEARCH.md, FLH-040 validation, this acceptance matrix,
and bounded indexing/search/repository/Qdrant/CLI/Compose contracts. Phase A
investigation, report prefix and four fixture/oracle files are preserved.

The exact pinned Qdrant image is absent:
`qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10`.
`docker image inspect` returned 1, `No such image`. Cached-image inventory
contained no Qdrant image; `qdrant` was absent from the isolated PATH and a bounded
local artifact search. No artifact was downloaded. Therefore no real Qdrant
collection, point inventory, build/search/restart/sync/rebuild or fault recovery
was exercised. No mock is counted as that acceptance. Docker itself was available
through approved sandbox escalation; this is an artifact blocker, not a claim
that Docker was unavailable.

### Executed checks and expected/actual results

| Check | Expected | Actual and evidence class |
| --- | --- | --- |
| Phase A regression | Existing deterministic fixture/oracle checks pass without persistent dependencies | 19 tests passed; real loopback fixture HTTP, synthetic oracle observations; no production provider ledger |
| Focused integrated Go checks | Selected semantic/Qdrant-adapter/embedding/config/HTTP tests pass; unavailable external tests stay explicit | 44 top-level tests passed, 4 real-Qdrant integration tests skipped, 0 failed; unit/mocked adapter evidence only |
| Native build and modules | Cached modules verify; server, semantic-index and diagnostic build offline into private output | Passed `go mod verify` and three builds; binary metadata/hashes recorded |
| SQLite persistent cache diagnostic | Existing vector survives duplicate save and reopen; explicit model/dimension/representation keys remain separate | Actual production repository returned `[1,2]`, other model `[3,4]`, other dimensions `[5,6,7]`, alternate representation `[7,8]`; no embedding calls or collection publication |
| SQLite ownership diagnostic | Older work cannot overwrite, clear or remove newer completed-run bookkeeping | **FAIL:** all three mutations succeeded while collection remained `complete`, owned by `newer-run`; old completion was correctly refused. See F1 |
| Unchanged Dockerfile | Build from local pinned bases and cached dependencies; package both executables/workbench | Passed offline build. First run compiled updated Go/workbench source; final run reused those build layers. No npm/Go download; no permanent dependency installation |
| Actual container executable/storage | UID:GID 1000:1000 can initialize isolated SQLite and execute `/app/semantic-index -json status` | Passed standalone network-disabled container and actual Compose app exec; database UID:GID 1000:1000, mode 0644, 10 migrations |
| Full Compose semantic profile | Start local services without downloading; absent required image prevents acceptance | Attempted actual profile with `--no-build --pull never`; exit 1, exact missing pinned-Qdrant image error. Full runtime and Qdrant storage permissions **NOT RUN** |
| App-only Compose | Owned app becomes ready; unavailable status is honest; keyword browse works | Passed app-only start/readiness, container CLI exit 0 with `vector_store_error="vector index unavailable"`, `state=null`, `searchable_complete=false`; empty keyword results. App-only success does not certify the semantic profile |
| Available read-only checks | CLI status and empty keyword browse leave SQLite rows unchanged | All 20 tables equal before/after, including migration, sequence, cache, bookkeeping and annotation tables; learning/annotation/index rows all empty. No semantic query, Qdrant snapshot or production embedding-counter assertion |
| Cleanup | Remove only owned resources and prove absence | Passed exact-project container/network queries, CLI-name query, tag removal and temporary directory removal; no Qdrant resource existed |
| Browser | Real interaction and network/console evidence | **NOT RUN:** no browser tool or Chromium/Chrome/Firefox executable available; Docker frontend build is not browser interaction |

Skipped tests were `TestQdrantIntegration_BuildSearchRestartRebuild`,
`TestQdrantIntegration_StaleAndMissingCandidatesAreDropped`,
`TestQdrantIntegration_InterruptedBuildThenRecovery` and
`TestQdrantIntegration_UnavailableQdrant`. The existing test named
`ControlledFrenchSemanticRegression` uses controlled vectors; its passing result
establishes no measured French relevance. The CLI package's usage-only test was
not selected by the bounded test expression; actual packaged CLI execution is
recorded separately. No full release verifier or full frontend test suite was run.

### P01–P18 coverage disposition

The matrix above remains the expected-state plan. The following records execution
coverage, without promoting narrower diagnostics to whole-row acceptance.

| ID | Phase B result |
| --- | --- |
| P01 | **NOT RUN real Qdrant:** no fresh catalog publication/provider/point inventory; mocked reuse tests passed |
| P02 | **NOT RUN integrated restart/sync/rebuild:** actual SQLite cache reopen passed; no document-attempt deltas across real indexing runs |
| P03 | **NOT RUN real source-change indexing:** existing mocked content-change test passed |
| P04 | **NOT RUN real model-space collections:** actual repository model-key isolation and mocked model-change test passed |
| P05 | **NOT RUN real dimensions/incompatible collection:** actual cache dimension isolation and existing malformed/dimension tests passed |
| P06 | **NOT RUN real representation upgrade/foreign point:** actual alternate-representation repository key isolation passed; no invented production selector |
| P07 | **NOT RUN integrated partial-provider recovery:** existing batch/invalid-response/cancellation unit tests passed; provider self-test counters are not CLI counters |
| P08 | **NOT RUN:** real upsert failure/lost acknowledgement and cross-store convergence unavailable |
| P09 | **NOT RUN:** real interrupted publication, SIGINT/SIGTERM/SIGKILL and acknowledgement boundary unavailable; mocked interruption test passed |
| P10 | **FAIL bookkeeping fence diagnostic (F1); NOT RUN full competing CLI/Qdrant scenario:** direct ordered repository calls used two handles, not simultaneous processes |
| P11 | **NOT RUN real source mutation during vector write:** mocked pre-publication source-change test passed |
| P12 | **NOT RUN actual CLI batches/cancellation/write-lock probe:** mocked bounded sequential batching/context tests passed; no held production network request with independent SQLite writer |
| P13 | **NOT RUN real missing/stale/foreign hits:** mocked SQLite-authority revalidation tests passed |
| P14 | **NOT RUN real populated supported/orphaned/retired/filter/annotation transitions:** mocked state filtering passed; empty app does not establish membership authority |
| P15 | **NOT RUN real semantic searches/query-only counters/vector equality:** actual empty keyword/status all-table equality passed only |
| P16 | **NOT RUN browser:** no interactive traversal or human presentation claimed |
| P17 | **NOT RUN real Qdrant outage/storage restart/rebuild:** absence reported honestly by actual packaged CLI; a never-running Qdrant is not an outage/recovery test |
| P18 | **PASS cleanup of observed fixture/native/Compose paths; NOT RUN Qdrant/fault-process lifecycle:** exact owned resources absent; unexercised interruption paths are not certified |

### F1 — High priority: superseded runs can mutate newer point bookkeeping

Affected implementation: `internal/storage/sqlite/semantic_index_repository.go`
`BeginRun` at 90, `FinishRun` at 107, `ClearPoints` at 126, `RecordPoints` at 151,
`RemovePoints` at 168. Corresponding unfenced service operations are in
`internal/application/semantic_index.go`: rebuild deletion/clear at 295–301,
point deletion/removal at 359–363, and upsert/bookkeeping at 482–486.

Reproduction uses `ownership_probe/main.go`, actual migrations/repository, a
fresh private SQLite database, two opened handles and opaque fault-fixture
hashes. Ordered calls model delayed older work; no vector store or provider is
substituted for Qdrant:

1. A calls `BeginRun(older-run, rebuild)`.
2. B calls `BeginRun(newer-run, sync)`, records `{1: newer-hash}` and successfully
   completes the collection.
3. A calls `RecordPoints({1: older-hash})`; it succeeds and overwrites B's record.
4. A calls `FinishRun(older-run, complete)`; it returns `owned=false`. Collection
   still says `state=complete`, `run_id=newer-run`, `last_error=""`.
5. A calls `ClearPoints`; records become empty. After B restores its record, A
   calls `RemovePoints([1])`; records again become empty.

Expected: ownership loss prevents older destructive/publication bookkeeping.
Actual: only final completion is fenced; mutation methods accept no run identity
and apply unconditionally. `unfenced_mutations_observed=true`. Diagnostic exit 0
means execution completed, not acceptance passed. Cache fixtures pass separately.

Impact: a completed newer run can have its publication ledger overwritten or
removed by old work. Source inspection also shows vector upsert/delete operations
have no ownership fence, so final-flag protection alone cannot establish the
requested protection of actual Qdrant writes. **The Qdrant race itself has not
been reproduced here.** No cross-store atomicity claim or production fix is made.
Owner verification should gate A immediately before upsert/delete and separately
before bookkeeping; let B publish/complete, release A, then inspect every actual
Qdrant vector/payload and SQLite record, not merely which `FinishRun` won.

### Additional focused source findings requiring actual Qdrant verification

These are inspection findings, not reproduced real-vector defects:

- `semantic_index.go:600–602` computes `searchable_complete` from fresh SQLite
  hashes, stored run state and Qdrant **count**. It does not inspect point IDs,
  payload identity or vector contents, and that predicate does not check returned
  collection dimensions/distance. Test a same-count corrupt/foreign inventory
  and an incompatible collection against the promised completeness signal.
- `semantic_index.go:335–339` skips documents whose SQLite publication hash is
  unchanged. Existing-collection sync does not reconcile every actual point;
  final stale count rechecks SQLite bookkeeping. Test loss of one point while
  retaining a collection, and same-count replacement, then sync; compare repair,
  CLI completion and status to real contents. Missing-whole-collection recovery
  is a separate code path and does not prove these cases.
- `semantic_search.go:123–144` sets `index_complete` solely from stored collection
  state before dropping incompatible/missing/stale hits. Test whether a prior
  complete run plus externally altered contents/source can advertise completeness
  while omitting those hits; compare that field with CLI status and current
  inventory. Filtering a valid state or nonpositive score is a different case.

### Commands, evidence and toolchains

Executed root orchestration commands (each runner exit was intentionally 1):

```sh
python3 -B scripts/validation/flh041/phase_b_checks.py --report /tmp/flh041-phase-b-run1.json
python3 -B scripts/validation/flh041/phase_b_checks.py --docker-only --report /tmp/flh041-phase-b-compose.json
python3 -B scripts/validation/flh041/phase_b_checks.py --docker-only --report /tmp/flh041-phase-b-compose-verified.json
python3 -B scripts/validation/flh041/phase_b_checks.py --docker-only --report /tmp/flh041-phase-b-compose-final.json
python3 -B scripts/validation/flh041/phase_b_checks.py --docker-only --report /tmp/flh041-phase-b-compose-handoff.json
```

The first Docker-only version had a harness branch-placement omission: it ran
build/standalone CLI but did not attempt Compose launch. That owned harness error
was corrected; only `compose-verified`, `compose-final` and `compose-handoff`
are Compose runtime evidence. Final rerun added cached-base enforcement to ensure
`--pull=false` could not fetch an absent base. No production file was changed.
All reports/logs were retained, with exact argv/stdout/stderr/exit/durations,
source hashes, fixture hashes and cleanup observations.

Native commands actually executed inside the private source copy:

```sh
go mod verify
go test -json ./internal/application ./internal/storage/sqlite ./internal/vectorindex ./internal/embedding ./internal/transport/http ./internal/config ./cmd/semantic-index -run 'Test.*(Semantic|Qdrant|HTTPProvider|Embedding)' -count=1
go build -o <owned-temp>/server ./cmd/server
go build -o <owned-temp>/semantic-index ./cmd/semantic-index
go build -o <owned-temp>/ownership-probe ./scripts/validation/flh041/ownership_probe
go version -m <each-built-binary>
<owned-temp>/ownership-probe <owned-temp>/diagnostic.db
```

Angle-bracket paths summarize deleted private paths; full executable argv are in
`phase-b-run1.json`. Actual environment used isolated HOME/cache/TMPDIR,
`GOENV=off`, `GOTOOLCHAIN=local`, `GOFLAGS='-mod=readonly -buildvcs=false'`,
`GOPROXY=off`, `GOSUMDB=off`, `CGO_ENABLED=0`. The existing module cache was read,
not upgraded. Fixture tests required approved loopback socket access.

Packaging used the unchanged copied Dockerfile/Compose file, `DOCKER_BUILDKIT=0`,
`docker build --pull=false --network none --tag <unique-task-tag> <private-copy>`
and an image-only task override. Exact empty-env-file, project, bind-mount,
`--profile semantic`, `--pull never`, container-run/exec and teardown commands
are retained in the JSON. No caller provider/proxy/Docker context environment or
repository `.env` was read; fake-only inherited helper values were sanitized.

Observed Linux amd64 toolchains: native Go `go1.27.1-X:nodwarf5`; Python 3.14.7;
Docker client 29.8.1 (API 1.56 downgraded to 1.55), daemon 29.7.2/API 1.55;
Compose 5.5.1. Docker bases were locally inspected pinned Node
24.11.1-alpine3.22, Go 1.26.5-alpine and Alpine 3.22.2 images; tags identify build
bases, not a separately executed in-container toolchain-version command.
Final built image was `sha256:21f6793a3ca5f8730b45c9d7aa28a6411350d335afe3e9152e6c90e1abb857f3`.
Final owned app ID was
`6f674868914cdabf736b93a5167a4964042b038f51497e4347bdb46f76d1acd0`.
No unrelated container/service was stopped or inspected for its data.

Native binary SHA-256, prior to deleting private output:

| Binary | SHA-256 |
| --- | --- |
| server | `5049f57189ecf73bbc870bb632ec658d589833a2fdd96fb39fa685e1a4c32ad4` |
| semantic-index | `412b11bfbbdfa5d37795c0a6275ff08bbd5d771f0a02e97a918c42f53d42b41a` |
| ownership-probe | `8a32df365a8beb5dd1cb7d1f4941e67f820faa7019a461b0d74fb7b5cc021f9c` |

Full bounded baseline: `/tmp/flh041-phase-b-baseline.json` (185 files). Executed
source-copy hashes are also in each runner JSON. Relevant starting SHA-256:

| File | Baseline SHA-256 |
| --- | --- |
| `AGENTS.md` | `ce868474059bc109a16a332d24ea2b328a57296367616437c88a3bad4300d057` |
| `docs/SEMANTIC_SEARCH.md` | `f3557826429fcd9b6f25dd20ffe10f918f2432bc83379d14e602e79f60bb1dc4` |
| `docs/ARCHITECTURE.md` | `3fc3108963d493cd52a32e5738b32291efc2c15c6cf0f543cfc6f94e2c3764f2` |
| `docs/validation/FLH-040-persistent-vector-search.md` | `686cbe7dc6f186ae10887388451946a422b9a6105bbe45369c9f7ce683f75a13` |
| `internal/application/semantic_index.go` | `5e40a3f9f72957778fd04446f7c9b7068ddf56433255731d3493fc18ef58a0bc` |
| `internal/application/semantic_search.go` | `b85391cf82ab4f41303f53bf308891d1f0e9e6314bbf38c0ea8fce1e996da2c2` |
| `internal/storage/sqlite/semantic_index_repository.go` | `3e8e5bb867bbcc096e552f158bc7afdece06f222f4d675e90fe0724f9c05577a` |
| `internal/vectorindex/qdrant.go` | `58c7ec8cf86016aeb20657a5193511c70d191224863ab9ed394622769f68dc82` |
| `cmd/semantic-index/main.go` | `a93a34ebcf8c649a0e096ba1a97ec845b1bf5e1dd0ac415a6c1a64dd32e901b7` |
| `migrations/010_semantic_index.sql` | `0973b3608b5e36ca10b553e3ad1e3145aa5b4b6314a3f9128ab8b9eece5781a1` |
| `compose.yaml` | `8d3ba02486dcb1128fcd63c5b7dbaaf6213dcfd779d00b642c5c1bbce4e50728` |
| `Dockerfile` | `f13da53fdac48e44160442d3f44e554638449553f4851ccea68ee644f2480f63` |
| `docs/validation/FLH-041-vector-search-acceptance.md` | `27769f74f7bd7401a65c6919cd417f0d072e47ce5e1b7e937427d021925da60d` |
| `scripts/validation/flh041/README.md` | `24f8399e66f9c66a326231a30c08db72522cd6c2fb9654643a3c96519096755b` |
| `scripts/validation/flh041/fixtures.json` | `71e6ad734ce17bd49afffd1186ef99ef4d1cdf83ad9f1170edf67f5d28ce409e` |
| `scripts/validation/flh041/fake_embeddings.py` | `ddcb5df1d12fc9fbed7416e487e8d4951ab467ecaacc3e263099285646919d74` |
| `scripts/validation/flh041/oracles.py` | `0988fd2852a1d6a08997ac498ab7692a0237a0cbc5701ced92168aec3cf8565a` |
| `scripts/validation/flh041/test_fixtures.py` | `1df0a63e43edd5d43565f7f932ba8dd2dd3a994a1b88175ee306564087f8cb06` |

The report/README hashes above cover their unchanged historical Phase A prefixes.
Other baseline files remain byte-identical. Phase A report/README copies under
`/tmp/flh041-phase-a-{report,readme}-preserved.md` allow prefix verification.
Only the four Phase B files below changed. Baseline checks are bounded, not a new
whole-repository audit.

### Cleanup, limits and handoff

All five runner reports record empty `errors` and `cleanup_errors`, and
`temporary_directory_removed=true`. Every attempted Compose project was torn
down; exact-label container/network queries and exact CLI-name queries returned
no IDs. Owned image tags were removed successfully. No owned Qdrant was launched,
so Qdrant storage permissions/cleanup are untested. Temporary databases, native
binaries, source copies and bind-mount directories were removed. Evidence JSON
and logs intentionally remain under `/tmp`; they are local and may expire.
Shared Docker layer cache was retained; no global prune removed others' resources.
Completed builds do not prove cleanup after an interrupted Docker build.

Final read-only snapshot SHA-256 within the last run:
`47557596b0a76c0e178886388124e387aedb05e43f72e72524385fdb563ae230`.
The snapshot covers sorted table rows, including sqlite_sequence, not byte-level
SQLite/WAL pages or all schema/index definitions. Empty keyword/status evidence
cannot establish populated semantic-search authority or provider-counter safety.
There are no relevance, ANN speed, Recall@K/MRR or performance improvement claims.

Remaining prerequisites/work: human-supplied local Qdrant artifact, actual
P01–P18 vector/cache/provider observations and fault/recovery runs, Qdrant bind
storage permissions and browser interaction if a browser becomes available.
F1 needs implementation-owner review; no production fix was attempted. Phase B
acceptance is incomplete and no unattended polling is scheduled.

Final hygiene checks passed: Python AST parsing of all owned Python files,
`gofmt -l scripts/validation/flh041/ownership_probe/main.go` (empty output),
185-file baseline comparison (only the owned report/README changed among those
baseline files), byte-prefix preservation of both Phase A documents, and
assertions over all five reports' cleanup/error fields. README.zh-CN.md remains
present and unchanged. These checks do not expand the integration coverage.

Exactly modified/created for Phase B:

- `docs/validation/FLH-041-vector-search-acceptance.md` — appended checkpoint;
- `scripts/validation/flh041/README.md` — appended diagnostic usage/limits;
- `scripts/validation/flh041/phase_b_checks.py` — available-prerequisite runner;
- `scripts/validation/flh041/ownership_probe/main.go` — actual SQLite diagnostic.

Human staging command, displayed only; no Git/GitHub command was executed:

```sh
git add -- docs/validation/FLH-041-vector-search-acceptance.md scripts/validation/flh041/README.md scripts/validation/flh041/phase_b_checks.py scripts/validation/flh041/ownership_probe/main.go
```

Codex stops editing at this handoff.

Suggested commit message:
test: record vector search diagnostics and integration limits
