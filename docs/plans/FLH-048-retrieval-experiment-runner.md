# FLH-048 Executable exploratory retrieval comparison

Owner: local Claude Code. Branch label supplied:
`feat/flh-048-retrieval-experiment-runner`. No Git/GitHub command or subagent
was used.

This task builds an isolated exploratory harness over the frozen FLH-045 fixture
([plan](FLH-045-retrieval-evaluation.md)), using the **existing** retrievers.
It adds no production retrieval capability, model download, paid call,
annotation or evaluation-policy change. FLH-049 is a parallel independent
review; its findings are not assumed and its files are not touched.

Evidence: [validation](../validation/FLH-048-retrieval-experiment-runner.md).
Usage: [runner README](../../scripts/validation/flh048/README.md).

## What the outputs are

Every report and summary carries these labels:
- an EXPLORATORY comparison against author-proposed synthetic judgments;
- NOT `concept_retrieval_eval_policy_v1`;
- NOT independently collected human ground truth;
- no generalization or semantic-improvement claim.

The author has seen the held-out split, so "held out" means reserved before
tuning, not blinded. No tuning was done.

## Files

All new:
- `scripts/validation/flh048/` (Go `package main` inside the module, so it can
  call `internal/` code):
  - `main.go`: CLI, embedding opt-in validation, orchestration
  - `inputs.go`: two-view fixture decoding, ID mapping, hashes
  - `rank.go`: runs the existing retrievers, candidate checks, counting provider
  - `metrics.go`: exploratory metrics and unscored observations
  - `report.go`: JSON/Markdown output and output-path safety
  - `runner_test.go`, `cli_test.go`, `README.md`
- this plan and the validation report

No production, migration, frontend, shared-document, dependency or CI file
changed. FLH-045 files are read-only, and their SHA-256 values are unchanged.
Because the runner is a package in the module, the existing `go test ./...` and
`go vet ./...` (CI and `make verify`) now build and test it too. It needs no
network and no service.

## Interfaces used (called, not reimplemented)

**Retrievers**
- `application.ConceptRetriever.Retrieve(ctx, query, documents, limit)`
- `NewExactSignatureConceptRetriever`, `NewWeightedLexicalConceptRetriever`,
  `NewBM25ConceptRetriever`, `NewEmbeddingConceptRetriever(provider)`

**Domain**
- `domain.DeriveCandidateIdentity`
- `ConceptIdentity.Validate` and `Signature`
- `ValidKnowledgeKind`

**Embedding**
- `embedding.NewHTTPProvider`, the existing OpenAI-compatible adapter

**Mirrored, because they are unexported**

The evaluation service's `toConceptRetrievalQuery` and
`toConceptRetrievalDocument` are plain field copies. The runner mirrors them in
`toQuery`/`toDocument` and hashes the service file in `source_sha256`. The
fixture has no lifecycle or support facts, so every Concept is treated as
normal, supported and active. Retrievers don't read these fields.

## Contract

1. **Inputs.**
   - Concepts become retrieval documents: identity → `Validate` (normalizes, as
     on creation) → `Signature`.
   - Queries: `unit_evidence` → `KnowledgeUnit` → `DeriveCandidateIdentity`.
   - Duplicate identities, unknown kinds, missing fields and bad IDs are
     refused.
   - The fixture's SHA-256 must equal the frozen FLH-045 value.
2. **Separation.**
   - The fixture is decoded into a ranking view whose struct has no field for
     evaluator data, and separately into an evaluator view.
   - Judgments, rationales, splits, languages, buckets, tags and free text can't
     reach a retriever or provider.
   - Tests perturb all of these and check that the ranking-input hash and every
     submitted provider text are unchanged.
3. **Deterministic IDs.**
   - Runtime IDs are `1..n` in ascending fixture-ID order, whatever the file
     order.
   - Existing retrievers break ties by ascending ID, so tie order is fixture-ID
     order.
   - Each `Retrieve` call gets a fresh copy of the full catalog (no split
     filtering).
4. **Runs.**
   - Exact, weighted lexical and BM25 always run.
   - Results are checked as the evaluation service checks them: ≤5,
     consecutive ranks, unique, in catalog, finite.
   - The first error stops that retriever: the rest is `not_run_after_error`,
     with no retry and no fallback.
   - Embedding is `unavailable` unless `-embedding=http` is deliberately
     configured.
5. **Output.**
   - Per query: the top-five IDs (fixture and runtime), ranks, scores, evidence
     (structured JSON), status, error and `Retrieve` duration.
   - Run-level records:
     - fixture SHA-256;
     - a length-prefixed ranking-input hash over the actual Go-encoded
       documents and queries;
     - the judgments hash;
     - source hashes of the retriever, domain and runner files;
     - configuration, denominators and the ID mapping.
   - A timing-free `ranking_digest` per retriever lets reruns be compared.
6. **Metrics.**
   - Recall@1/3/5 and MRR@5 (truncated) over single-target cases, by split,
     language, split × language and family.
   - `N = 0` or a failed run gives `null`, never `0`.
   - Ambiguous cases report the rank of each alternative; no-match cases report
     the returned count. Neither has a positive metric or a false-positive
     rate.
7. **Embedding opt-in.**
   - The base URL must be http(s) with no credentials, query string or
     fragment.
   - A model name and a 1–300 s timeout are required.
   - An input-position cap is required and must be ≥ the planned positions
     (`Q × (C + 1)` = 1,400); it is also enforced on every call.
   - An optional dimension check.
   - The key comes only from a named environment variable and is never output.
   - Counted: requests, positions, unique input hashes, failures, refusals and
     observed dimensions.
   - Results are reported separately from the baselines.
8. **Output safety.**
   - `-out` must be a new or empty directory outside the repository (symlinks
     resolved), not next to the fixture, and not containing it.
   - Files are created exclusively (`O_EXCL`).

## Fixture observations (reported, FLH-045 unchanged)

- **The exact baseline is structurally zero on this fixture.** All 24 Concepts
  have a non-empty scope or identity features, while `DeriveCandidateIdentity`
  always yields an empty scope and no features. No derived signature can match,
  whatever the wording. FLH-045 anticipated this; the fixture was not altered.
- **Metadata sits beside model inputs.** `bucket`, `split`, `language`, `tags`
  and `free_text` are in the same query record as `unit_evidence`. The runner
  doesn't depend on that layout for separation (separate decoding), but a
  future fixture version could put model inputs in their own object.
- **The judgments hash coincides.** FLH-045's documented canonical
  `judgments` hash equals this runner's Go re-encoding hash (`91b5ac3a…`). The
  runner documents its own encoding and doesn't rely on the coincidence.
