# Semantic search for French-learning notes: the model only makes vectors

> Retrospective draft, prepared 2026-10-12. Not yet published. The reports cited
> here are dated 2026-10-10 to 2026-10-12. Chinese original:
> [flh-semantic-search-engineering.md](flh-semantic-search-engineering.md).

French Learning Hub (FLH) is my personal French-learning service. I record the
questions I meet while learning, the system extracts knowledge units, and I
organize them into durable Concepts (for example "depuis for something still
going on"). The code was implemented mainly by AI coding agents (Claude Code
and Codex) under my task contracts and review. I ran the GPU diagnostic and the
NAS acceptance myself. This article separates four kinds of evidence:
- **facts:** code and schema;
- **author tests:** tests the implementing agent ran itself;
- **independent tests:** acceptance by a different agent;
- **human observations:** results I executed myself and the agents did not
  re-check.

## Why keyword search was not enough

The Knowledge Library already had keyword prefix search, with no stemming,
synonyms or semantics. What you are looking for is often a meaning, perhaps
phrased in English, while a Concept's identity is a French grammar point.

In the FLH-060 demo's real-model run (author test, synthetic data):
- the keyword `weather` returned nothing;
- the semantic query "what the weather was like when I was a child" ranked
  "imparfait for background and habits in the past" first;
- the keyword `miss` found "tu me manques" only because the title happens to
  contain the word "miss".

## Who owns what: authority, generator, index

```text
SQLite (authority: Concepts + vector cache + publication pointer)
   │  semantic-index build/sync/rebuild (explicit commands)
   ├──> E5 service (Windows RTX 4070, over Tailscale): text in, vectors out
   └──> Qdrant (a disposable index, rebuildable from SQLite)
search: query vector → Qdrant candidates → each one re-checked against SQLite
```

- **SQLite is the only authority.** Every search hit is re-checked against
  SQLite. Missing, stale or foreign-model hits are dropped, never substituted,
  and search never falls back to keywords.
- **The model is only a vector generator.**
  - E5 has roles: queries get the `query: ` prefix and Concept documents
    `passage: `.
  - The prefix comes only from the versioned representation and type
    (`concept_search_query_v2` or `concept_embedding_text_v1`), never from the
    text.
- **Deployment identity is immutable.**
  - `EMBEDDING_MODEL_ID` is the full deployment id: model revision, role
    contract, dtype, batching policy and a manifest digest.
  - Any setting that changes vectors gets a new identity, a new index space and
    a new cache, so two models' vectors never mix.

## What independent acceptance found

The first version (FLH-040) passed its author tests.

**FLH-041 (independent test).** Acceptance reproduced a defect using two SQLite
connections. An older index run that had lost ownership could still overwrite
and clear a newer run's completed bookkeeping, because only the final
"complete" step checked ownership.

**FLH-042's fix:**
- **Lease:** one run per index space holds a SQLite lease, and every
  bookkeeping write is checked against it.
- **Private collections:** each run writes its own Qdrant collection.
- **Single-point publication:** publishing is one lease-fenced pointer switch.

**FLH-043 (second independent acceptance).** It simulated a write that took
effect but whose acknowledgement was lost: Qdrant held four private points
while SQLite recorded two rows. The command exited 1, the previous publication
was unchanged, and recovery made zero embedding calls. That case passed. The
same pass found two defects:
- a search that met a publication switch reported the healthy new publication
  as "not built";
- a healthy `sync` didn't clean up an old collection whose deletion had failed.

**FLH-044** fixed both. A search now retries at most once on a publication
switch, and a second switch is an explicit error.

What this adds up to:
- There is no transaction across Qdrant and SQLite, and I don't claim one.
- Each run writes only its own collection, and search reads only the published
  pointer.
- "Healthy" comes only from a full check of every point's id, payload and
  vector, never from a point count.
- `status` shows recorded history and currently verified health separately.

## Explicit indexing and a persistent cache

Document vectors are cached in SQLite, keyed by (content hash, representation,
model identity, dimensions). Only the `semantic-index` command calls the
embedding service. A search embeds just its query, and server startup sends no
embedding requests. The FLH-060 demo puts a counting gateway in front of the
service: it counts queries and documents separately, and charges a budget
before sending.

**Budgeted macOS run (author test).** The implementing agent ran the demo once
against the real E5 service:
- 9 POSTs and 22 positions in all: indexing took 2 POSTs with 15 document
  positions, and 7 searches each took 1 query position;
- keyword search made 0 calls;
- after a restart, `sync` made 0 calls, and `rebuild` reused all 15 cached
  vectors with 0 calls;
- the service's own `/metrics` deltas matched the gateway's counts.

With the service simulated offline, semantic search returned 502 while keyword
search and index status kept working. After recovery, no rebuild was needed.

**NAS rerun (human observation).** I reran the demo on the NAS myself:
- 18/18 mechanical checks passed;
- again 9 POSTs and 22 positions;
- zero calls for `sync`/`rebuild`;
- the data survived a restart;
- offline and recovery behaved as expected.

Browser interaction was not tested.

## GPU, Tailscale and float16

The E5 service runs on my Windows laptop's RTX 4070, and the NAS reaches it
through Tailscale. Because the embedding service is on another machine and may
be offline at any time, "service unavailable" has to be an explicitly handled
state, not a hidden fallback.

**FLH-058 (independent test).** One exploratory run found that identical
documents encoded in different batch shapes gave 112 repeated vectors outside
the previously declared tolerance. The report named float16 plus per-batch
padding as a plausible explanation, without establishing the cause.

**FLH-059** wrote a bounded diagnostic: 6 configurations of 456 positions each,
with a pre-registered rule. I ran it on that GPU (human observation):
- float16 `dynamic_v1`: 359 tolerance failures, and 4 of 32 rankings changed
  their top-5 order;
- float16 `singleton_v1` (each input encoded alone): 424/424 compared vectors
  bitwise equal, with zero failures.

So the service now runs the singleton deployment. This describes this machine
and this input set only; it is not a universal determinism claim. No GPU
benchmark was run either.

## Retrieval evaluation: the numbers and their limits

FLH-058 ran the existing Go retrievers on one frozen fixture of 48
single-target queries against 24 Concepts:

| Retriever | Recall@5 |
| --- | --- |
| E5 | **44/48** (MRR@5 0.653) |
| BM25 | 32/48 |
| Weighted lexical | 30/48 |
| Exact signature | 0/48 |

The exact zero is structural: no signature in this fixture can match.

The limits belong with the numbers:
- The labels are author-proposed synthetic proposals, **not reviewed by a
  human**.
- Each Concept has a pair of French and English paraphrases, and 7 example
  strings recur within those pairs.
- **Not blind:** the held-out and development sets are semantically related on
  quantity, negation and inversion constructions, and the author saw every
  proposal. It is not a blind test and says nothing about generalization.
- No significance test was run.
- At top 1, E5 lost 4 cases that weighted lexical got right and 5 that BM25 got
  right.
- **No-match queries:** the 4 still returned 5 results each. For example,
  "PostgreSQL backup" ranked imparfait first at 0.846.

## An honest failure

In the FLH-060 real-model run (author test; raw evidence outside the
repository), "saying I don't do something anymore" ranked "tu me manques"
first (0.8531). The demo's intended pairing, "ne … plus", came second (0.8426).

All scores sat between 0.81 and 0.87. A cosine score is not a probability, not
a relevance judgment and not a "same Concept" decision; it only orders
results, and here the order did not match the design intent. The demo's search
sentences are example inputs, not labels, so this is an observation, not a
score.

## What remains

- Browser acceptance.
- Human-reviewed relevance labels, and a regrouped, decorrelated holdout.
- Any new model experiment, which needs its own authorization.

This is not RAG, no model was trained, and nothing automatically files units
under Concepts: SAME decisions still come only from a human.

## Sources

- **Code:**
  [semantic_index.go](https://github.com/WorldVanquisher/french-learning-hub/blob/main/internal/application/semantic_index.go),
  [semantic_search.go](https://github.com/WorldVanquisher/french-learning-hub/blob/main/internal/application/semantic_search.go),
  [migrations/010](https://github.com/WorldVanquisher/french-learning-hub/blob/main/migrations/010_semantic_index.sql),
  [migrations/011](https://github.com/WorldVanquisher/french-learning-hub/blob/main/migrations/011_semantic_index_runs.sql),
  [cmd/semantic-index](https://github.com/WorldVanquisher/french-learning-hub/tree/main/cmd/semantic-index),
  [E5 service](https://github.com/WorldVanquisher/french-learning-hub/tree/main/tools/embedding/e5),
  [FLH-060 demo](https://github.com/WorldVanquisher/french-learning-hub/tree/main/scripts/demo/flh060)
- **Guide:** [SEMANTIC_SEARCH.md](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/SEMANTIC_SEARCH.md)
- **Reports:**
  [FLH-041](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/validation/FLH-041-vector-search-acceptance.md),
  [FLH-043](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/validation/FLH-043-index-consistency-acceptance.md),
  [FLH-045 plan](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/plans/FLH-045-retrieval-evaluation.md),
  [FLH-049](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/validation/FLH-049-evaluation-and-ci.md),
  [FLH-058](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/validation/FLH-058-real-e5-exploration.md),
  [FLH-059](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/plans/FLH-059-e5-reproducibility.md),
  [FLH-060](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/validation/FLH-060-semantic-demo.md),
  [FLH-061](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/validation/FLH-061-nas-semantic-demo.md)

Raw evidence from the real runs (individual requests, counters, diagnostic
output) is kept outside the repository.
