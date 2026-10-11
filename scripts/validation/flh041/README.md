# FLH-041 Phase A — persistent-vector-search acceptance tools

Phase A prepares fixtures and assertion tools; it does not launch the application,
run semantic-index, implement persistence, choose Qdrant collections, or certify
FLH-040. The [acceptance plan and evidence](../../../docs/validation/FLH-041-vector-search-acceptance.md)
identify the Phase B checks, dependencies and limits.

Run from the repository root, using Python 3.10+ and stdlib only:

```sh
python3 -B scripts/validation/flh041/test_fixtures.py
```

Socket permission is required for ephemeral IPv4 loopback HTTP self-tests. No
package installation, database, Qdrant, paid provider or credentials are needed.
The tests create no repository output or bytecode. They close and join their own
listeners/threads, including after fixture failure. They never attach to an
existing service or signal an unrelated process.

## Fixtures and provider

`fixtures.json` contains opaque synthetic texts, duplicate/changed documents,
queries, model names/identities, dimensions, and authority scenario labels. These
are **not production Concept serialization, a seed payload, or relevance truth**.
Representation labels are oracle axes, not invented production flags.

`fake_embeddings.py` implements the inspected provider wire contract only:
POST `/embeddings`, `{model, input: [string, ...]}` and indexed vectors in `data`.
It binds `127.0.0.1` on an OS-assigned port. It has no admin HTTP routes or API key
requirement. In-process controls schedule faults by 1-based received request:

- HTTP failure, malformed JSON, missing vector, duplicate/out-of-range index;
- wrong dimensions, zero vector, NaN, disconnect;
- reversed indexed responses (legal), a gate, or a gate timeout.

The vectors hash the exact input and provider model to finite nonzero values;
they neither tokenize French nor estimate semantic similarity. Fixture instances
with the same inputs/model/dimensions return the same vectors. Changing only the
operator's model identity need not change the provider's output: cache isolation
must still use that explicit identity. No model-identity inference is performed.

A future Phase B runner can keep the provider alive across application/CLI restarts:

```python
import sys
import threading
sys.path.insert(0, "scripts/validation/flh041")
from fake_embeddings import FakeEmbeddings, Fault

with FakeEmbeddings(dimensions=8) as provider:
    # Replace these opaque texts with exact observed production inputs in Phase B.
    provider.register("synthetic document", "document")
    provider.register("synthetic query", "query")
    gate = threading.Event()
    provider.arm(2, Fault(kind="none", gate=gate))
    print(provider.base_url)  # Only owned loopback URL; attach known provider config later.
    before = provider.snapshot()
    # Start the actual CLI/server after mapping its integrated contract.
    # wait_received() exposes the gate boundary; release with gate.set().
```

Controls cannot retroactively change an already received request. Context exit
releases all gates, shuts down the owned server and joins its request threads.
A gate has a bounded timeout (default five seconds); choose an explicit bound for
Phase B orchestration. No indefinite sleep or polling loop is supplied.

Snapshots retain request ordinal, wire model, per-input SHA-256, explicit
query/document/unclassified roles, batch size, outcome, status, and whether the
HTTP reply write succeeded. Attempt counters include failed calls and duplicate
texts; `valid_response_texts` counts well-formed fixture responses, **not client
acceptance, cached vectors or committed publication**. TCP write success does not
prove a client consumed the response. Unknown inputs stay unclassified and make
the query-only oracle fail. Headers, bearer tokens and bodies are not logged.

Keep one ledger alive across application/index restarts, or deliberately combine
separate provider-lifecycle evidence before applying delta assertions; silently
reset counters must fail. Register exact production texts from confirmed contract
observations, not guessed JSON or inferred text roles. Provider hashes are input
attribution and do not substitute for production content hashes.

## Independent oracles

`oracles.py` accepts observations supplied by a later integration adapter:

- `CacheKey` and `assert_cache`: all four cache identity axes, exact key inventory,
  vector dimension, finite/nonzero values and expected component attribution
  (absolute tolerance 1e-6 for fixture float32 storage).
- `assert_index`: exact supplied complete vector/payload inventory, not just count.
- `assert_result_ids`: exact externally supplied SQLite-authority IDs/order;
  rejects duplicates and substitutions without implementing filtering/ranking.
- `assert_embedding_delta`: exact attempted query/document input-hash multisets;
  detects ledger reset, attribution errors, extra attempts and unknown inputs.
- `assert_bounded_provider`: measured batch/concurrency bounds, with no in-flight
  requests when comparing completed observations.
- `assert_read_only`: all supplied SQLite rows and vector records unchanged,
  with only the expected query embeddings.
- `assert_not_complete`: negative predicate for failed/stale/superseded runs;
  it does not calculate production state or replace run-ownership evidence.

The Phase B adapter must capture every relevant table and scroll/read **all**
owned vector records with payloads/vectors. It must pass explicit expected
inventories independently of production reports. These helpers do not seed,
serialize production documents, hash cache identities, construct collections,
cache vectors, publish/upsert, resolve Concepts, infer truth from link history,
filter stale hits, or compute ranking metrics. There is no fake Qdrant or guessed
application endpoint adapter in Phase A.

Nineteen tests include real fixture HTTP plus in-memory oracle mutation checks.
The synthetic snapshot tests are not database acceptance; fake reproducibility
across provider instances is not persisted cache reuse; a timed-out fixture client
is not production context-cancellation evidence. Actual Qdrant and browser tests
remain Phase B work after the human supplies the integrated implementation.

## FLH-043 — active index consistency acceptance

The runner and `ownership_probe/main.go` now target FLH-042's migration-011
leases, private collections, manifests and publication pointer. They make no
legacy `BeginRun`/`RecordPoints`/`FinishRun` calls. Historical FLH-041 reports and
its four Phase A fixtures/oracles remain unchanged. The former prerequisite-only
runner has been replaced; historical commands/results remain in the FLH-041 report.

Run from the repository root with a new external output directory:

```sh
python3 -B scripts/validation/flh041/phase_b_checks.py --output /tmp/flh043-human
python3 -B scripts/validation/flh041/phase_b_checks.py --extra-only --output /tmp/flh043-human-extra
```

The first command executes lease/fence races, repair, fake-provider failures,
interruption, search, focused integrated Go tests and actual Compose. The second
executes the complementary dimension, partial-upsert, expired-lease, unrecorded
collection, state-filter and whole-collection-loss checks. Both are necessary
for the coverage recorded in the FLH-043 report. Exit 1 means an assertion,
prerequisite or cleanup failed; it is never reclassified as green acceptance.

Requirements: local Go/module cache, Python stdlib/socket access, Docker daemon,
the pinned Qdrant image in compose.yaml, every pinned Dockerfile base/dependency
layer already cached, and the existing cached `python:3.12-slim` image for the
owned Compose embedding fixture. Images are inspected locally; the latter is
run by its inspected image ID. No pull or package installation is performed.
Each run captures a bounded current-file baseline and source-copy hashes in
its report. The separate `/tmp/flh043-baseline.json` preserves the original
pre-edit task baseline; it is not required to rerun the harness. Historical
results are never treated as measurements of a different checkout.

The runner copies bounded production source into private temporary output,
disables Go module network/update and VCS stamping, uses sanitized environment
and an empty Compose env file, and builds outside the shared checkout. It reads
the existing FLH-026 environment/listener helpers without editing them. Provider
inputs are classified from actual exported production document rendering, with
IDs sorted to match the inspected indexing batch order. Fake values prove
mechanics only; no semantic relevance, speed or ranking-metric claim follows.

`ownership_probe` modes:

- `seed`/`documents`: direct synthetic Concept fixtures in isolated SQLite and
  actual production-rendered documents; no invented creation/edit endpoint;
- `repository`: actual busy/expired/takeover and nine fenced-write refusals;
- `upsert`, `record-manifest`, `publish`, `publish-noop`: exported gate hook
  after lease renewal, real service/repository/provider/Qdrant, with complete
  before/after active state, manifest and point/vector/payload equality;
- `search-query-race`/`search-info-race`: delegate to the actual Qdrant adapter,
  delaying one selected call while an independent rebuild publishes;
- `source-change`: clearly labelled isolated SQLite source fault and catch-up;
- `inventory`: actual current publication, manifest and full paginated points.

Gate hooks are in-process service instrumentation. SIGINT/SIGTERM/SIGKILL tests
also run the actual CLI process, while an owned HTTP proxy forwards real Qdrant
requests and holds or loses their acknowledgements. The proxy never implements
an index. Manifest/point inventories are captured at the held boundary. An
independent `BEGIN IMMEDIATE` probes SQLite writes during held requests, with a
positive control that holds a writer and must block it.

`compose_embeddings.py` reuses the unchanged deterministic fixture inside one
owned Docker network. Only that container listens on its container interface;
it has no host-published port. The fixture ledger is written to task-owned
output. App/Qdrant host ports bind 127.0.0.1. Compose uses an image-only app
override and a unique project so the user's app tag/resources are not replaced.

Evidence includes exact commands/toolchains, source/binary hashes, full SQLite
schema/table rows, paginated published records/vectors/payloads, per-input
provider ledgers, held private inventories, case assertions and cleanup.
Qdrant telemetry may change autonomously: raw metadata is retained, while
read-only equality asserts shape and actual vector records. Cleanup removes
owned containers/networks/tags/processes and temporary storage. Qdrant writes
root-owned nested files; an already cached Alpine image removes only the exact
owned bind mounts after teardown. Shared Docker build cache remains. Output
JSON/logs deliberately remain in the requested external evidence directory.

See [FLH-043 acceptance](../../../docs/validation/FLH-043-index-consistency-acceptance.md)
for reproducible failures and coverage limits. A successful diagnostic command
or an owner's existing test does not replace these independent assertions.
