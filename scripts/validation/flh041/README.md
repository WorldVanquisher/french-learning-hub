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
