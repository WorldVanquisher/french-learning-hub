# FLH-048 validation: exploratory retrieval comparison runner

Date: 2026-10-12. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64, `go1.26.5`). Owner:
local Claude Code. No Git/GitHub command, subagent, network service, model
download, paid call, `.env` read or daily database was used. Contract:
[plan](../plans/FLH-048-retrieval-experiment-runner.md).

> **Exploratory comparison against author-proposed synthetic judgments.**
> **NOT production `concept_retrieval_eval_policy_v1`.**
> **NOT independently collected human ground truth.**
> **No claim of generalization or semantic improvement.** 56 small, correlated
> synthetic queries; the author has seen the held-out split.

## Offline run

Command:

```sh
go run ./scripts/validation/flh048 -out <scratch>/final-a
```

It was run twice, into `final-a` and `final-b`; both exited 0.

**Inputs**
- Fixture: SHA-256 `92726376…7043a`, equal to the frozen FLH-045 value.
- Ranking inputs: `a2e995fe467644b3a8a806a645a0a4a6c348f55aeeb7925dcc4de6f0a2445a55`.
- Judgments: `91b5ac3a…89cf`.

**Inventory**
- Catalog: 24 Concepts.
- 48 single-target cases: development 32, held out 16; fr 24, en 24.
- 4 ambiguous and 4 no-match cases (unscored).
- K = 5.

| Retriever (existing, untuned) | N | R@1 (hits) | R@3 (hits) | R@5 (hits) | MRR@5 | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| `exact_signature_retriever_v1` | 48 | 0.000 (0) | 0.000 (0) | 0.000 (0) | 0.000 | 0 |
| `weighted_lexical_retriever_v1` | 48 | 0.292 (14) | 0.542 (26) | 0.625 (30) | 0.422 | 0 |
| `bm25_retriever_v1` | 48 | 0.312 (15) | 0.625 (30) | 0.667 (32) | 0.461 | 0 |
| `embedding_retriever_v1` | — | unavailable (not enabled; nothing contacted or substituted) | | | | |

Slices, from the summary:

| Slice | Lexical R@1 / R@5 / MRR@5 | BM25 R@1 / R@5 / MRR@5 |
| --- | --- | --- |
| development (32) | 0.281 / 0.625 / 0.398 | 0.312 / 0.688 / 0.462 |
| held out (16) | 0.312 / 0.625 / 0.469 | 0.312 / 0.625 / 0.458 |
| en (24) | 0.458 / 0.667 / 0.556 | 0.458 / 0.708 / 0.562 |
| fr (24) | 0.125 / 0.583 / 0.288 | 0.167 / 0.625 / 0.359 |

**Unscored cases**

Ambiguous cases, showing where each proposed alternative ranked (`-` means not
returned). These are observations, not scores.
- Lexical: `Q049` C001@5; `Q050` C003@3, C004@2; `Q051` C022@4; `Q052` C023@1.
- BM25: the same, except `Q051` C021@3, C022@2.

No-match cases (descriptive only): for both lexical and BM25, `Q053` and `Q055`
returned 5 Concepts, while `Q054` and `Q056` returned none.

**How to read these numbers**
- The exact baseline's 0 is **structural**: every fixture Concept has a scope
  or features that a derived candidate identity never has (see the plan's
  fixture observations).
- **Small and correlated:** this is 48 cases in 24 bilingual pairs from 12
  families. Differences of one or two hits are within noise. There is no
  significance test and no claim that BM25 is better.
- English beats French for both lexical retrievers. A plausible contributor is
  that the Concept identities are French while the English queries share
  English kind tokens; this is not established. For example, BM25's top hit for
  `Q001` was driven by `le`/`une`, with no stop-word list (as implemented).
- **Reproducible:** per-retriever ranking digests were identical across the two
  runs (exact `b5e92694…`, lexical `2daa58da…`, BM25 `8a88437d…`), as were the
  inputs and source hashes.
- **Timing:** `Retrieve` timings are in-process microbenchmarks. For example,
  BM25 took 6.9 ms in total, with a median of 0.12 ms per query. This is not a
  performance claim.
- **Overwrite protection:** a third run into `final-a` was refused ("not empty;
  refusing to overwrite").

The full `report.json` (about 590 KB) holds per-query top-five IDs, ranks,
scores, evidence, errors and durations. It is in the session scratchpad, not
the repository.

## Tests

`go test ./scripts/validation/flh048/` passes, both normally and with `-race`:
17 top-level tests and 32 subtests.

| Requirement | Test |
| --- | --- |
| Hand-calculated metrics | `TestMetrics_HandCalculated`: ranks 1, 3, 4, miss, 5 give R@1 0.2, R@3 0.4, R@5 0.8, MRR@5 107/300; `N = 0` gives null |
| Misses, ranks, separate denominators | `TestEvaluate_RanksMissesAndSeparateDenominators`: rank 2 and a miss; split and language Ns; ambiguous and no-match excluded from N; alternative ranks; no-match count |
| No partial scoring | `TestEvaluate_FailedOrUnavailableRunHasNoMetrics` |
| Input–label separation | `TestInputs_LabelsNeverReachRetrieversOrProvider`: all judgments, rationales, language, tags, free text and label status perturbed. The ranking-input hash and every provider-submitted text are unchanged, and no ID, rationale, split, bucket or label word appears in them |
| Deterministic mapping and tie order | `TestInputs_DeterministicMappingIndependentOfFileOrder`: reversed file order gives the same mapping, hash and rankings |
| Domain-derived identity | `TestInputs_CandidateIdentityComesFromDomainOnly`: the exact retriever hits when the derived identity really matches |
| Fixture consistency | `TestInputs_RejectsInconsistentFixtures`: 12 refusal cases. `TestInputs_FrozenFixture`: 24/56/48/4/4 inventory, splits, languages, frozen hash |
| Output checks | `TestRunRetriever_RejectsInvalidCandidatesAndStops` |
| Embedding through the real `HTTPProvider` | `TestCLI_EmbeddingThroughHTTPProviderIsCounted`: local `httptest` fake, 56 requests and 1,400 positions counted on both sides; key sent from the named environment variable and absent from the outputs; results kept apart from the baselines |
| Malformed output, timeout, failure, no fallback | `TestCLI_EmbeddingFailuresAreExplicitWithoutFallback`: wrong count, HTTP 500, 1.5 s delay against a 1 s timeout, wrong dimensions. Each gives exit 1, state `failed`, first query `error` (timeout named), the rest `not_run_after_error`, exactly one request, no metrics |
| Configuration refusals | `TestCLI_ConfigurationRefusals`: 11 cases, all exit 2, nothing written, the endpoint never contacted |
| Cap and dimensions | `TestProviderCounter_CapAndDimensionsWithoutRetry` |
| Output safety | `TestCLI_OutputSafety`: missing `-out`, inside the repository, the fixture directory, a symlink into the repository, a non-empty directory, next to an external fixture, containing the fixture, a modified fixture. `TestOutput_EmptyDirectoryRuleAndExclusiveWrites` |
| Determinism and labels | `TestCLI_OfflineBaselinesAreDeterministicAndLabelled` |
| FLH-045 untouched | `TestCLI_LeavesFLH045ByteIdentical` |

**Mutation checks.** Each mutation was applied in place and the files were then
restored byte-identical (SHA-256 checked). All 8 are caught:
- M1: the target leaks into the query example.
- M2: Recall@3 off by one.
- M3: ambiguous cases counted as misses.
- M4: IDs mapped in file order.
- M5: continuing after a provider error.
- M6: input cap ignored.
- M7: non-empty output directory accepted.
- M8: a failed run still scored.

M2, M6 and M7 survived the first test version. The tests were strengthened
(rank 4 added; a direct cap unit test; a non-empty directory without a name
clash) and all three re-checked as caught.

## Repository checks

| Command | Result |
| --- | --- |
| `gofmt -l .` | no output |
| `go vet ./...` | ok |
| `go test ./... -count=1` | all packages ok, including `scripts/validation/flh048` |
| `python3 -B scripts/validation/flh045/validate.py` / its unittest | exit 0 / OK |
| FLH-045 SHA-256 (5 files) | unchanged: fixture `92726376…`, README `10e4733b…`, validate `24d133d9…`, tests `cba0dfb8…`, template `ba399551…` |

During development, one test (the symlink case) briefly ran with a broken
symlink because of a test bug (a relative `findRepoRoot(".")`). It was fixed,
and no file was written into the repository. A data race in the tests' fake
server counters (test code only) was fixed with a lock.

## Limits

- **No embedding quality data.** No real or local model was used. The embedding
  path was exercised only by the tests' local fake server, which tests plumbing.
- **Judgments are author proposals** awaiting human review (FLH-045). This is
  not Protocol A's production evaluation and not Protocol B's free-text
  search.
- **The held-out split is not blinded:** the author has seen it. No parameters
  were tuned and no query was edited.
- **Mirrored converters:** the query and document converters mirror two
  unexported functions. If those change, the runner's `source_sha256` shows a
  different hash, but the mirror isn't automatically updated.
- **Not run:** Linux, CI and FLH-049's review. FLH-049 is independent and not
  integrated.
