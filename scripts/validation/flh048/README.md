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
- **Inputs (frozen fixture only).** It reads
  `scripts/validation/flh045/fixture.json` and refuses any file whose SHA-256
  isn't the frozen `92726376…7043a` compiled into the runner (exit `3`). Since
  FLH-052, `-expect-fixture-sha256` is only an extra assertion: any value other
  than that constant is refused (exit `2`), so a caller can never redefine which
  fixture is frozen. Reports record `fixture_matches_frozen` against that
  constant (`frozen_reference_sha256`).
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

**Overall timeout (`-timeout`, default 10m, must be positive).** It is checked
before and after every `Retrieve` and before a retriever is declared completed.
A retriever that misses it fails explicitly: that query is an `error` naming
the timeout, later queries are `not_run_after_error`, later retrievers make no
call (and no provider request), and no metrics are published. A result returned
after the deadline is discarded. **Limit:** the existing offline retrievers are
synchronous and ignore their context, so a `Retrieve` already running is not
interrupted; it finishes first, then its result is discarded. There is no hard
process deadline and no watchdog goroutine.

**Exit status:** `0` OK; `1` report written but an enabled retriever failed
(including an expired overall timeout); `2` usage or configuration; `3` input
or output error. `go run` itself
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

**Exact baseline.** Every fixture Concept has a scope or identity features,
and `DeriveCandidateIdentity` never yields either, so no exact signature can
match on this fixture. The report's `structure` block and the summary say so
under the exact baseline; its zeros are structural, not a semantic result.
Target identities are never copied into query inputs to change that.

**Converter parity.** `toQuery`/`toDocument` mirror two unexported production
converters. `TestConverterParity_AgainstProductionThroughOverlay` runs a child
`go test -tags flh052parity -overlay …` that adds
`testdata/production_bridge.go.txt` to `internal/application` virtually and
compares mirror and production field for field over all 56 queries, all 24
Concepts and a few edge cases. Nothing is written into production. It cannot
check the declared synthetic Concept state (normal, supported, active), which
is a fixture assumption, not a production catalog snapshot.

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
