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
