# Semantic search (FLH-040, run consistency FLH-042, recovery FLH-044)

An optional **Semantic** mode in the Knowledge Library ranks Concepts by
embedding similarity to a free-text query, using a persistent, rebuildable
vector index. The contract is in
[ARCHITECTURE §9.3](ARCHITECTURE.md#93-optional-semantic-search-flh-040). This
page is the operator guide and a walkthrough of the Go code.

It is off by default. Keyword search, the retrieval-evaluation reports and
every other feature behave exactly as before whether it is on or off.

## What you need

- An OpenAI-compatible embedding service (`EMBEDDING_PROVIDER=http`), with
  a known model, version and vector size.
- One Qdrant instance, reachable only from your machine. The Compose profile
  below pins `qdrant/qdrant:v1.19.1` by digest; any local Qdrant 1.x with the
  REST API works.
- The `semantic-index` CLI (`make build-semantic-index`, or `/app/semantic-index`
  inside the release image).

A real embedding service may be paid or remote: indexing sends every Concept's
identity text (title, intent, scope, identity features) and each search sends
the query text. Use the synthetic demo below to try the mechanics without one.

## Configuration

Set these for both the server and the CLI (same `.env` or environment):

```bash
EMBEDDING_PROVIDER=http
EMBEDDING_BASE_URL=http://127.0.0.1:9000/v1      # your embedding service
EMBEDDING_MODEL=model-name-the-service-expects
EMBEDDING_MODEL_ID=org/model-name@2026-05        # explicit identity; see below
EMBEDDING_DIMENSIONS=1024
SEMANTIC_SEARCH=qdrant
QDRANT_URL=http://127.0.0.1:6333
```

`EMBEDDING_MODEL_ID` is how cached vectors are keyed. **Change it whenever the
model, its version, its weights or its serving configuration change**, even if
the model name stays the same. A new identity creates a new collection and a
fresh embedding run; it can never mix two models' vectors. Optional:
`QDRANT_API_KEY`, `QDRANT_TIMEOUT` (default 5 s), `QDRANT_COLLECTION_PREFIX`
(default `flh_concepts`), `SEMANTIC_BATCH_SIZE` (default 32, at most 256).

## Operations

Run from the directory whose `.env` the server uses (or export the variables):

```bash
make build-semantic-index
bin/semantic-index build     # first publication; refuses if one exists
bin/semantic-index status    # last run + live verification; read-only, no provider call
bin/semantic-index sync      # verify; republish only if the publication is not healthy
bin/semantic-index rebuild   # always republish; also removes leftover collections
```

Add `-json` for machine-readable output and `-batch N` to override the batch
size. Nothing runs on a schedule: new or changed Concepts appear in semantic
results only after you run `sync`; until then `status` reports them as stale or
missing, and search drops stale hits.

| Exit | Meaning |
| --- | --- |
| `0` | Published a new collection, or `sync` verified the publication healthy and published nothing (it may still have removed recorded leftovers) |
| `1` | Error (provider, Qdrant, invalid vectors, interruption, sources kept changing); the previous publication is unchanged |
| `2` | Usage |
| `3` | Ownership lost: another run took over; this run published nothing |
| `4` | Busy: another run holds an unexpired lease |

### How runs are serialized and published (FLH-042)

- **One run per space at a time.** A run takes a lease in SQLite (120 s,
  renewed at every step). A second run exits `4` while the lease is unexpired.
  `-takeover` takes the lease anyway: use it only when the holder is known to be
  dead (killed, crashed); a live holder stops at its next step without
  publishing.
- **Each run writes its own collection.** Every `build`, `sync` (when
  repairing) or `rebuild` creates a new physical collection named
  `<space>_r<run>` and fills it from the embedding cache (embedding only cache
  misses). No run ever modifies a collection another run created or published.
- **Publication is one SQLite step.** Before publishing, the run re-reads the
  Concepts, catches up with changes (twice at most) and verifies its own
  collection completely. It then switches the space's published collection in
  one transaction that succeeds only while it still holds the lease. Search
  reads that pointer.
- **Old collections are removed afterwards.** The replaced collection is
  deleted after publication; if that fails it stays recorded as `retired` and
  the next run removes it, including a `sync` that finds the publication
  healthy (FLH-044). Such a no-op `sync` removes only `retired` and `abandoned`
  collections, which no run writes or publishes again. `writing` collections of
  other (dead or superseded) runs are removed only by a run that has just
  published. Each deletion is gated by the lease, and the record is forgotten
  by a fenced write only after the deletion succeeded.
- **Incomplete cleanup is reported.** A run whose cleanup failed or stopped still
  succeeds (the publication is unaffected), but its report lists
  `cleanup_pending` and `cleanup_error`, and its `last_error` reads
  `cleanup incomplete: N leftover collection(s) remain (...)`.
- **No cross-store atomicity is claimed.** The SQLite switch is the single
  publication point; search re-checks every hit against SQLite. A search can
  read the pointer just before a newer run publishes and deletes that
  collection, so the collection is missing either at its metadata check or at
  the query. Search then re-reads the pointer. If it changed, search retries
  once on the new collection (reusing the query vector if it already embedded
  one); if it did not change, the collection really is lost and search reports
  that. One retry per search in total: a second replacement ends the search
  with "publication changed during the search" (HTTP `500`, generic message);
  searching again works.

With Docker (release image and the `semantic` profile):

```bash
mkdir -p data/qdrant
docker compose --profile semantic up -d --build
docker compose exec app /app/semantic-index build
docker compose exec app /app/semantic-index status
```

Set the variables above in the shell or Compose `.env`. Inside Compose
`QDRANT_URL` defaults to `http://qdrant:6333`; Qdrant is also published on
`127.0.0.1:${FLH_QDRANT_PORT:-6333}` only. This Compose path was validated with
`docker compose config` only; it has not been run against a Docker daemon.

## Reading `status`

`status` reports three different things and never conflates them:

| Section | Meaning |
| --- | --- |
| `published` | The collection search uses, and the run and time that published it (recorded history). |
| `last run` | The outcome of the latest run that still owned the space when it finished: `published`, `verified_unchanged`, `failed`, `interrupted` or `sources_changed`, with its error. A successful run whose cleanup was incomplete shows `cleanup incomplete: …` as its error. History, not health. |
| `lease` | A run currently holding the space, or an EXPIRED lease left by a killed run. |
| `verification` | Live check of the published collection, computed now: existence, vector size and distance, and every point's id, payload (content hash, model, representation, dimensions) and vector compared with SQLite's current documents and the cached embeddings. `HEALTHY` only if all match; a point count alone is never enough. |
| `leftover` / `unrecorded` | Collections awaiting removal by the next run (`retired`/`abandoned` also by a healthy `sync`; other runs' `writing` collections by the next publishing run), or present in Qdrant without a record (for example an FLH-040 collection); `rebuild` removes unrecorded ones. |
| `other space` | Spaces for other model identities; not used by the current configuration. |

Search responses (schema `knowledge_library_semantic_search_v2`) carry the
publication and last-run fields as recorded history with
`health_verified: false`; search does not verify the index. What a search did
verify is in its per-hit counts (`skipped.missing`, `stale`, `incompatible`).

## Recovery

| Situation | What happens | What to do |
| --- | --- | --- |
| Embedding service fails or returns malformed vectors | Run stops before publishing (`failed`); its collection is removed; completed batches stay cached; search keeps using the previous publication | Fix the service; run `sync` |
| Ctrl-C / SIGTERM | Run stops (`interrupted`); same as above | Run `sync` |
| Process killed with SIGKILL or power loss | Its lease stays until it expires (120 s); its collection may stay as a leftover | Wait for expiry, or run with `-takeover` if you are sure it is dead; the next run removes leftovers |
| Another run is in progress | New run exits `4` | Wait; check `status` |
| A run was taken over | The superseded run stops at its next step (exit `3`); its writes went only to its own collection | Nothing; `status` shows the newer run |
| Deleting the replaced collection failed | Publication succeeds; the old collection stays recorded as `retired`; the report lists it in `cleanup_pending` and `last_error` says `cleanup incomplete` | Fix Qdrant; run `sync` (no re-embedding, publication unchanged) |
| A search raced a publication | Search retries once on the new collection; if a second publication replaces that one too, the search fails with `500` | Search again |
| Concepts change during a run | Absorbed by catch-up; if they keep changing, `sources_changed` and nothing is published | Run `sync` again |
| One point missing, replaced, stale or foreign in the published collection | `status` shows it under `verification` | Run `sync` (republishes from cache, no re-embedding) |
| Published collection lost entirely | `status`: collection missing; search `409` | Run `sync` |
| Published collection has the wrong size or distance | `status`: shape mismatch; search `409` | Run `sync` |
| Qdrant down | Search `502`; `status` cannot verify; keyword search unaffected | Start Qdrant; run `status` |
| Model changed | New `EMBEDDING_MODEL_ID` → new space, not built → search `409` | Run `build` for the new identity |

There is no automatic retry anywhere. Backups need only the SQLite database:
the embedding cache lives there, and Qdrant can always be rebuilt from it.

## Synthetic demo

[`scripts/demo/flh040/`](../scripts/demo/flh040/README.md) seeds the FLH-034
demo library, then runs a deterministic fake embedding service, a Qdrant binary
you supply, and the server with semantic search enabled, all on loopback. The
fake turns texts into hashed bag-of-words vectors, so "similarity" means shared
words. It demonstrates the mechanics (caching, publication, re-validation and
recovery); it is not evidence about semantic quality.

## Go walkthrough

Read the code in this order.

### Interfaces: who may do what

`internal/application/semantic_index.go` defines the narrow boundaries:

- `EmbeddingProvider` (existing): text in, vectors out.
- `VectorIndex`: inspect, list, create and delete collections; upsert, delete
  and scroll points; query. `internal/vectorindex/qdrant.go` implements it with
  `net/http` only.
- `SemanticIndexStore`: the SQLite bookkeeping
  (`internal/storage/sqlite/semantic_index_repository.go`). Every method that
  takes a run ID is *fenced*: it acts only while that run holds the lease.
- `SemanticConceptReader`: `ListConcepts` only.

`SemanticIndexService` (operations) and `SemanticSearchService` (queries,
`semantic_search.go`) depend only on these. Tests use in-memory fakes
(`semantic_fakes_test.go`) plus the real SQLite store, and the integration tests
(`internal/vectorindex/qdrant_integration_test.go`) use a real Qdrant.

### Ownership: lease, gates and the publication switch

`run()` takes the lease with `AcquireLease` (busy unless expired or
`-takeover`). From then on every guarded action goes through `checkpoint()`,
which calls `RenewLease` (it fails with `ErrSemanticIndexOwnershipLost` if
another run took over) before:

- each provider batch (`embed`);
- registering and creating the run's collection;
- each upsert and each manifest write;
- each point deletion during catch-up;
- the publication switch;
- each cleanup deletion.

A checkpoint alone leaves a window between the check and the action. The
design therefore never depends on it:

- **Vector writes go only to the run's own collection.** A superseded run that
  slips through the window can only write into a collection that is never
  published.
- **Bookkeeping writes are fenced inside their own transaction.** `fenced()`
  begins with `UPDATE … WHERE lease_run_id = ?`. That statement both checks
  ownership and takes SQLite's write lock, so the lease cannot change before the
  transaction commits.
- **`Publish` is that kind of fenced transaction.** It switches
  `published_collection`, marks the new collection `published` and the previous
  one `retired`. It is the only way to change what search reads.

`TestQdrantIntegration_FencedPublishAfterNoOpTakeover` exercises the narrowest
window, where only the fence stops the old run; disabling the fence makes that
test fail.

### Cancellation

Every call takes a `context.Context`:

- **CLI.** `cmd/semantic-index/main.go` cancels it on SIGINT/SIGTERM.
- **Adapters.** They attach it to every HTTP request.
- **Checkpoints.** Each one checks `ctx.Err()` first.
- **`run`'s deferred block** uses a fresh short context
  (`context.WithoutCancel(ctx)` plus a 10 s timeout) only to remove the run's
  own unpublished collection and record the outcome. It does not keep working
  after Ctrl-C.

### Bounded work

There are no goroutines in indexing or search, and batches are sequential:
- **Batch size.** Each provider call, upsert, delete and scroll page handles at
  most `batchSize` items (1–256).
- **Catch-up.** It is limited to two passes.
- **Search.** It embeds one text at most once, asks Qdrant for
  `min(limit*4, 200)` hits, and retries at most once in total when the
  publication was replaced (before the metadata check or before the query).
- **Response bodies** are read through `io.LimitReader`.
- **Timeouts** bound every Qdrant and provider request.

### Transactions: never across a network call

Each repository method is one short transaction, and none is held while the
provider or Qdrant is called.
`TestQdrantIntegration_NoSQLiteWriteLockDuringNetworkCalls` proves it against
a real Qdrant: during every provider call and every Qdrant HTTP request, an
independent connection must take an immediate write transaction within 50 ms.
A positive control shows the probe fails when a lock is held.

### Verification and repair

- **`verify()`** reads the collection's shape, then scrolls every point with its
  payload and vector, comparing each with the current SQLite document and the
  cached embedding. Qdrant normalizes cosine vectors, so the comparison
  normalizes both. Problems are listed by kind: missing, extra, foreign payload,
  stale, vector mismatch, unverifiable.
- **`sync`** runs the same verification first and republishes when anything is
  wrong. The cache makes repair free of provider calls.

### Failure recovery in code

- **`semanticErrorCategory`** maps every error to a short, secret-free text for
  `last_error`.
- **On failure, `run`'s deferred block** removes the run's unpublished
  collection, or marks it `abandoned` if deletion fails. It then records the
  outcome with `CompleteRun`, a fenced write, so a superseded run records
  nothing.
- **`cleanup()`** runs under the lease with one of three scopes:
  - `cleanupLeftovers` (healthy `sync`): retired and abandoned collections;
  - `cleanupRecorded` (after publishing): also other runs' writing collections;
  - `cleanupUnrecorded` (after `rebuild`): also unrecorded collections of the
    space.

  Every deletion is preceded by a lease checkpoint. If the lease is lost, the
  remaining collections are not touched and the run ends with ownership lost.
  A deletion already past its gate can still complete; that is harmless because
  retired and abandoned collections are never read or published again, and
  their records stay (fenced) until a later run. What remains is reported in
  `CleanupPending`/`CleanupError`.
- **Search's replacement recovery** (`SemanticSearchService.Search`) runs at
  most two attempts. Each attempt reads the pointer, checks the collection's
  shape, embeds the query once per search and queries. After a "missing" error
  it re-reads the pointer and retries only if the pointer changed; a second
  change returns `ErrSemanticPublicationChanged`. It never writes, never loops
  and never falls back to keyword search.
- **`ValidateEmbedding`** rejects wrong dimensions, NaN/Inf, values outside
  float32 and zero vectors before anything is cached.

### Legacy FLH-040 bookkeeping

Migration 010's `semantic_index_collections` and `semantic_index_points` are no
longer read or written. `internal/storage/sqlite/semantic_index_legacy.go`
keeps their old, unfenced methods. They were kept so that the FLH-041
diagnostic compiled; FLH-043 retargeted that probe to the current API, so no
code calls them any more. Removing them is left to a separate cleanup task. After upgrading from FLH-040, run `build`
once: the old collection is unrecorded and `rebuild` removes it. Cached
embeddings are reused, so nothing is re-embedded.

## Limits

- **Quality.** The tests and the demo use a deterministic fake provider. No real
  embedding model has been evaluated; semantic quality and any Recall@K or MRR
  change are a later evaluation task.
- **Index content.** Only Concept identity text is indexed; unit wording,
  French examples and source records are not.
- **Full republish.** Every repairing `sync` or `rebuild` republishes all points
  from the cache: O(Concepts) upserts and a full verification scan. That is fine
  at personal scale; the trade-off buys isolation between runs.
- **Lease timing.** A lease assumes a run makes progress at least every 120 s
  (each external call is bounded by its timeout, far below that). A process
  paused for longer can be taken over; it then publishes nothing.
- **Search does not verify.** Search re-checks each hit but does not scan the
  collection; use `status` for health.
- **Single instance.** One Qdrant instance, no replication; the index is
  disposable by design.
- **Cache growth.** The cache is never pruned automatically.
