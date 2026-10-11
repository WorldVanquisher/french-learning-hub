# Semantic search (FLH-040)

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
bin/semantic-index build     # first time; refuses if an index already exists
bin/semantic-index status    # read-only; never calls the embedding service
bin/semantic-index sync      # after Concepts change; embeds only new documents
bin/semantic-index rebuild   # drop and republish; reuses cached embeddings
```

Add `-json` for machine-readable output and `-batch N` to override the batch
size. Exit status: `0` complete, `3` finished but partial or superseded, `1`
error, `2` usage. Nothing runs on a schedule: new or changed Concepts appear in
semantic results only after you run `sync`. Until then `status` reports them
as missing or stale, and search drops stale hits.

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
`docker compose config` but not run against a Docker daemon in FLH-040.

## Reading `status`

| Line | Meaning |
| --- | --- |
| `state: complete` | The last run published every Concept's current document and re-validated it. |
| `state: partial` + `last error` | The last run failed, was interrupted, or saw Concepts change. Run `sync`. |
| `state: building` | A run is in progress, or one was killed without cleanup. If none is running, run `sync`. |
| `stale` / `missing` / `orphaned points` | Concepts whose published hash is outdated, never published, or published for an ID that no longer exists. |
| `vector store: … points` vs `concepts` | Qdrant's actual count; a mismatch means Qdrant lost or gained data. |
| `other space` | Collections for other model identities; not used by the current configuration. |
| `searchable: complete` | All of the above agree. |

## Recovery

| Situation | What happens | What to do |
| --- | --- | --- |
| Embedding service fails or returns malformed vectors during `build`/`sync` | Run stops; space `partial`; vectors from completed batches stay cached; nothing invalid is stored | Fix the service; run `sync` (only missing documents are embedded) |
| Ctrl-C / SIGTERM during a run | Context canceled; space `partial` with `interrupted (canceled)` | Run `sync` |
| Process killed with SIGKILL or power loss | Space stays `building` | Run `sync`; it takes over with a new run ID |
| Two runs at once | The newer run owns the space; the older cannot mark it complete and exits `3` | Let the newer finish; run `status` |
| Concepts change during a run | Changed documents are not published; space `partial` | Run `sync` |
| Qdrant down | Search answers `502`; `status` shows `vector index unavailable`; keyword search unaffected | Start Qdrant; no sync needed if its storage survived |
| Qdrant data lost | `status` shows a missing collection or a point-count mismatch | Run `sync` or `rebuild` (no re-embedding) |
| Collection with the wrong vector size | `sync` refuses (`incompatible`) | Run `rebuild` |
| Model changed | New `EMBEDDING_MODEL_ID` → new space, not built yet → search `409` | Run `build` for the new identity |

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

- `EmbeddingProvider` (existing): text in, vectors out. It knows nothing about
  Concepts.
- `VectorIndex`: create/inspect/delete a collection, upsert/delete points, query.
  `internal/vectorindex/qdrant.go` implements it with `net/http` only.
- `SemanticIndexStore`: the SQLite bookkeeping
  (`internal/storage/sqlite/semantic_index_repository.go`).
- `SemanticConceptReader`: `ListConcepts` only, so indexing cannot modify
  Concepts.

`SemanticIndexService` (operations) and `SemanticSearchService` (queries,
`semantic_search.go`) depend only on these interfaces. The tests swap in
in-memory fakes (`semantic_fakes_test.go`) and the real SQLite store, and the
integration tests (`internal/vectorindex/qdrant_integration_test.go`) use a real
Qdrant.

### Cancellation

Every call takes a `context.Context`:

- `cmd/semantic-index/main.go` creates it with
  `signal.NotifyContext(..., SIGINT, SIGTERM)`.
- The provider and Qdrant adapters attach it to each HTTP request
  (`http.NewRequestWithContext`), so Ctrl-C aborts an in-flight call.
- `ensureVectors` also checks `ctx.Err()` before each batch.
- The Qdrant adapter's `classify` preserves `context.Canceled` in the error
  chain.
- `run`'s deferred block adds the context error when an adapter reported a
  canceled call only as "unavailable".

The final bookkeeping write must happen even after cancellation, so the
deferred block uses
`context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)`. This is a
new, short-lived context for exactly one SQLite update, not a way to keep
working after the user pressed Ctrl-C.

### Bounded work

There are no goroutines in indexing or search: batches run one after another.

- **Batch size.** Each provider call and each Qdrant upsert or delete handles at
  most `batchSize` items, clamped to 1–256 in `NewSemanticIndexService` and
  validated in configuration.
- **Search.** It asks Qdrant for `min(limit*4, 200)` hits and embeds exactly one
  text.
- **Request size.** SQLite IN-lists are chunked (`sqliteMaxBatch`). Response
  bodies are read through `io.LimitReader`: 32 MiB for Qdrant, 16 MiB for
  embeddings.
- **Timeouts.** Each Qdrant request is bounded by `QDRANT_TIMEOUT`, and each
  provider request by `EMBEDDING_TIMEOUT`.

### Transactions: never across a network call

Every `SemanticIndexRepository` method is one short transaction. The service
never holds one while calling the provider or Qdrant. The order inside `run` is
deliberate:

1. `BeginRun` (one transaction) takes ownership of the space under a new run ID.
2. `ensureCollection` and `ListConcepts` read state; then `ensureVectors`
   embeds cache misses batch by batch, saving each batch with `SaveVectors`
   (one transaction each) before the next provider call. Work already paid for
   survives an interruption.
3. `publish` re-reads the Concepts, skips any whose hash changed, calls
   `Upsert`, and only after Qdrant acknowledged it calls `RecordPoints`.
4. `staleCount` re-validates all published hashes.
5. The deferred `FinishRun` writes `complete` or `partial` *only if this run
   still owns the space* (`WHERE run_id = ?`).

Because SQLite and Qdrant cannot commit together, the design never relies on
it. A crash between `Upsert` and `RecordPoints` leaves a point the bookkeeping
does not know about. The next `sync` republishes that Concept: the upsert is
idempotent because the point ID is the Concept ID. Search, in turn, trusts
neither store alone: `SemanticSearchService.Search` re-reads every candidate
from `ListConcepts`, recomputes its document hash, and drops mismatches.

### Failure recovery in code

- `semanticErrorCategory` turns any error into the short, secret-free text
  stored in `last_error` and shown by `status` and the UI.
- `ensureCollection` treats a missing Qdrant collection as "everything
  unpublished" (it clears the point records first) and refuses a collection
  whose vector size or distance is wrong.
- `ValidateEmbedding` rejects wrong dimensions, NaN/Inf, values outside float32
  and zero vectors before anything is cached or published.
- The HTTP layer (`internal/transport/http/semantic_search.go`) maps error
  categories to `503`, `409`, `502` and `504`, and never falls back to keyword
  search.

## Limits

- **Quality.** The tests and the demo use a deterministic fake provider. No real
  embedding model was evaluated in FLH-040; semantic quality and any Recall@K or
  MRR change are a later evaluation task.
- **Index content.** Only Concept identity text is indexed: unit wording, French
  examples and source records are not. A Concept is found by what its identity
  says.
- **Scale.** Each search re-reads all Concepts from SQLite (fine at personal
  scale) and every `sync` re-hashes all Concepts.
- **Single instance.** One Qdrant instance, no replication. The index is
  disposable by design.
- **Cache growth.** The cache is never pruned automatically; vectors for old
  model identities stay until removed by hand.
