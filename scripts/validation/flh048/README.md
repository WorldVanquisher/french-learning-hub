# FLH-048 exploratory retrieval comparison runner

**Exploratory comparison against author-proposed synthetic judgments.**
- It is **not** the production `concept_retrieval_eval_policy_v1` report.
- Its judgments are **not** independently collected human ground truth.
- No claim of generalization or semantic improvement follows from it.

Contract and rationale: [plan](../../../docs/plans/FLH-048-retrieval-experiment-runner.md).
Evidence: [validation](../../../docs/validation/FLH-048-retrieval-experiment-runner.md).
Fixture: [FLH-045](../flh045/README.md), read-only.

## Run (offline, from the repository root)

```sh
go run ./scripts/validation/flh048 -out "${TMPDIR:-/tmp}/flh048-$(date +%Y%m%d-%H%M%S)"
go test ./scripts/validation/flh048/
```

**What a run does**
- **Inputs.** It reads `scripts/validation/flh045/fixture.json` and refuses any
  file whose SHA-256 isn't the frozen
  `92726376…7043a`.
- **Retrievers.** It runs the existing exact-signature, weighted-lexical and
  BM25 `ConceptRetriever` implementations for all 56 queries against all 24
  Concepts, with `K = 5`.
- **Outputs.** It writes `report.json` (full) and `summary.md` (compact, also
  printed) into `-out`.

**Output safety**
- `-out` must be a new or empty directory outside the repository.
- Existing files are never overwritten.
- A location inside the repository, next to the fixture, or one that contains
  the fixture is refused.

**Exit status:** `0` OK; `1` report written but an enabled retriever failed;
`2` usage or configuration; `3` input or output error. `go run` itself
reports a child's non-zero exit as `1`, so build the binary if you need the
exact code.

## What reaches a retriever

**Concepts.** Each Concept's `identity` passes through
`ConceptIdentity.Validate` and `Signature`.

**Queries.** Each query's `unit_evidence` (kind, canonical, statement, example)
becomes a `KnowledgeUnit`, and its candidate identity comes from
`domain.DeriveCandidateIdentity`.

**Separation from evaluator data.** The fixture is decoded twice, into a
ranking view and an evaluator view. The ranking view has no field for
judgments, rationales, splits, languages, buckets, tags or free text.
Evaluator data meets results only in `Evaluate`.

**ID mapping.** Runtime IDs are `1..n` in ascending fixture-ID order
(`C001 → 1`, `Q001 → 1`). Every existing retriever breaks ties by ascending ID,
so ties follow fixture-ID order whatever the file order.

## Metrics

**Scored cases:** the 48 single-target cases (development 32, held out 16;
fr 24, en 24).
- **Recall@1/3/5:** whether the proposed target appears in the top K.
- **MRR@5:** `1/rank` within the top five, `0` otherwise; it is truncated, not
  full-catalog MRR.
- **Breakdowns:** by split, language, split × language and family.
- **Failed runs:** a failed or unavailable retriever gets `null` metrics; a
  partial run is never scored.

**Unscored cases:** the 4 ambiguous and 4 no-match cases. They have no asserted
relevant target, so they get raw results plus descriptive observations only:
- **Ambiguous:** the rank of each proposed alternative.
- **No-match:** how many results each query returned.

## Embedding: off unless deliberately enabled

By default `embedding_retriever_v1` is reported as **unavailable**: no provider
is constructed or contacted, and nothing is substituted. To use a
caller-supplied OpenAI-compatible endpoint (the existing `HTTPProvider`):

```sh
go run ./scripts/validation/flh048 -out "$OUT" -embedding http \
  -embedding-base-url https://host/v1 -embedding-model NAME \
  -embedding-max-inputs 1400 [-embedding-dimensions D] [-embedding-api-key-env VAR]
```

**Configuration rules**
- **Cap.** `-embedding-max-inputs` is required, and must cover the planned
  1,400 input positions (56 queries × (1 query + 24 Concepts)). Every call is
  also checked against the cap.
- **Base URL.** It must be absolute http(s), with no credentials, query string
  or fragment.
- **API key.** It is read only from the environment variable *named* by
  `-embedding-api-key-env`. No `.env` file is read, and the key never appears in
  output.

**Counting and failures**
- Requests, input positions, unique input hashes, failures, refusals and
  observed dimensions are counted.
- The first error stops the retriever: no retry, no fallback, no metrics.
- Embedding results are reported separately from the offline baselines. A stub
  or fake endpoint tests plumbing, not quality. In FLH-048 the embedding path
  was exercised only by the tests' local fake server.
