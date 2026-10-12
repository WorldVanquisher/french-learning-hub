# FLH-052 validation: experiment-runner contract fixes

Date: 2026-10-12. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64; Go `go1.26.5`
through the host's 1.24.5 toolchain switch; Python 3.13). Owner: local Claude
Code. No Git/GitHub command, subagent, download, real model, paid call, secret,
`.env` read or daily data was used. Contract:
[plan](../plans/FLH-052-experiment-runner-contract.md).

Baseline: the FLH-048 runner as reviewed by
[FLH-051](FLH-051-experiment-runner-acceptance.md) (NOT ACCEPTED). This report
does not claim that FLH-051 accepted the fix; FLH-051's harness was rerun
unchanged, and its defect-observation assertions now fail by design (below).

> Exploratory comparison against author-proposed synthetic judgments. NOT
> production `concept_retrieval_eval_policy_v1`. NOT independently collected
> human ground truth. No generalization or semantic-improvement claim.

## FLH-051 reproductions: expected versus actual

Built binary: `go build -o <scratch>/runner ./scripts/validation/flh048`.

| Case | FLH-051 observed | Required | Actual now |
| --- | --- | --- | --- |
| `runner -out D -timeout 1ns` (F1) | exit 0, three baselines `completed` with metrics | explicit failure, no metrics | **exit 1**. Exact, lexical and BM25 are each `failed`, `overall: null`; Q001 `error: overall run timeout (-timeout) expired before Retrieve`; the other 55 `not_run_after_error`. `run.deadline` and the summary line say the timeout expired. |
| `-timeout 0`, `-timeout -1s` | not tested | usage error | **exit 2**, "-timeout must be positive", no output directory |
| Copy with one rationale changed + `-expect-fixture-sha256 <its own sha>` (F2 `digest-override`) | exit 0, summary "matches frozen FLH-045: true" | refused | **exit 2**: "… is not the frozen FLH-045 SHA-256 92726376…; this runner accepts only the frozen fixture"; nothing written. (Copy hash `50c77771…`; FLH-051's `4b806bba…` differs only by its serialization.) |
| Same copy, no flag (`reject-modified`) | exit 3 | exit 3 | **exit 3**, "refusing to run on a modified fixture" |
| Same copy + `-expect-fixture-sha256 92726376…` | — | refused | **exit 3** |
| Frozen fixture + `-expect-fixture-sha256 92726376…` | — | allowed | **exit 0**. `caller_asserted_sha256` recorded; `fixture_matches_frozen: true` against `frozen_reference_sha256` |
| Standalone `summary.md`, exact baseline (R2) | zero without explanation | structural note | "Structural: all 24 fixture Concepts have a non-empty scope or identity features, while every candidate identity derived by domain.DeriveCandidateIdentity has neither, so no exact signature can match …". JSON `structure`: 24/24 Concepts, 0/56 candidates, `exact_match_possible: false` |
| Rerun into an existing output | exit 3 | exit 3 | **exit 3**, "not empty; refusing to overwrite" |

## Offline baselines (unchanged rankings)

`runner -out <scratch>/offline-a` and `offline-b`: both exit 0, schema
`flh048_exploratory_retrieval_comparison_v2`, deadline "not reached". The
ranking digests are identical across the two runs and to FLH-048's macOS
values: exact `b5e926948ae4…`, lexical `2daa58dab4c7…`, BM25 `8a88437ddd2c…`.
Ranking inputs `a2e995fe…5a55`. Metrics are unchanged: exact 0 (measured zeros,
not null); lexical R@5 30/48, MRR@5 0.421528; BM25 R@5 32/48, MRR@5 0.460764.
Embedding is `unavailable`. No parameter or query was changed. FLH-051 reported
a different BM25 digest on Linux; cross-platform equality was not investigated
here.

## Tests (mocked and local fakes only)

`go test ./scripts/validation/flh048`: 28 top-level tests and 32 subtests pass
(17 earlier + 11 new top-level), also with `-race`.

| Requirement | Test |
| --- | --- |
| Expired deadline: no `Retrieve`, explicit error, later queries not run, no metrics; cancellation named separately | `TestRunRetriever_ExpiredDeadlineRunsNothing` (0 calls) |
| Controlled delayed offline retriever that ignores context | `TestRunRetriever_DelayedRetrieverMissesDeadline`: 100 ms per call, 150 ms deadline. Call 1 `ok`; call 2 runs to completion (≥ 90 ms, not interrupted), then its result is discarded with "expired during Retrieve"; exactly 2 calls; no metrics |
| Context-honoring delayed retriever | `TestRunRetriever_ContextHonoringRetrieverStopsAtDeadline`: 1 call, returns at the 50 ms deadline |
| Never completed after the deadline | `TestRunRetriever_NeverCompletesAfterDeadline` (no queries left, ended context → `failed`) |
| CLI `-timeout 1ns` with embedding enabled | `TestCLI_ExpiredOverallTimeoutFailsEveryRetrieverWithoutMetrics`: exit 1; all four retrievers failed, null metrics; **0 requests** at the counted fake endpoint |
| Positive timeout | `TestCLI_TimeoutMustBePositive`: `0`, `0s`, `-1s`, `-1ns` → exit 2, nothing created |
| F2 | `TestCLI_ModifiedFixtureWithItsOwnHashIsRefused` (FLH-051 shape: exit 2 / 3 / 3, nothing written; a foreign expectation is refused even for the frozen file), `TestCLI_FreezeStatusNamesTheCompiledReference` |
| R2 | `TestExactStructure`, `TestCLI_SummaryExplainsStructuralExactZeros` (note under the exact heading only; exact zeros stay numeric) |
| R1 parity | `TestConverterParity_AgainstProductionThroughOverlay` → child `go test -tags flh052parity -overlay … -run ^TestFLH052ConverterParity$`: the 56 queries and 24 Concepts from the raw fixture, plus edge cases (non-nil example, padded and uppercase text, unordered features). Mirror, loader output and the **actual unexported production converters** agree field for field. It also checks that the virtual bridge file never exists on disk |
| Counted fake provider (unchanged) | `TestCLI_EmbeddingThroughHTTPProviderIsCounted`, `TestCLI_EmbeddingFailuresAreExplicitWithoutFallback`, `TestProviderCounter_CapAndDimensionsWithoutRetry`, `TestInputs_LabelsNeverReachRetrieversOrProvider`: pass |

**Mutation checks** (each applied in place, files restored byte-identical; all
12 caught):
- T1 no pre-`Retrieve` check; T2 no post-`Retrieve` check; T3 no completion
  check; T4 no timeout validation.
- Z1 caller hash not compared with the constant; Z2 freeze status always true.
- S1 structural note hidden.
- C1 query mirror drops `Example`; C2 document mirror has the wrong schema
  version; C3 document mirror skips `Validate` normalization. C1–C3 compile and
  are caught by the parity test alone.

## FLH-051 harness rerun (unchanged file)

```sh
PATH=<go1.26.5 toolchain>/bin:$PATH python3 -B scripts/validation/flh051/accept.py --output /tmp/flh051-flh052-recheck
```

The harness hardcodes `GOSUMDB=off`, which blocks this host's toolchain switch,
so the cached go1.26.5 `bin` was put first on `PATH` for this command only.
- **Passed inside the harness:**
  - `build`;
  - `existing-tests`: 28 top-level and 32 subtests pass, 0 fail, 0 skip;
  - `independent-go`: `TestFLH051ProductionParityAndEvidence` and
    `TestFLH051RankValidationAndMetricBoundary` pass;
  - `offline-a` and `offline-b`: equal ranking digests asserted.
- **Then it stopped,** harness exit 1, at its F1 defect observation:
  `AssertionError: ('offline-expired', 1, '')`. It expects the old exit 0; the
  fixed runner exits 1 with three `failed` baselines and null metrics. This is
  the intended change, not an acceptance.
- **Not executed by the harness** because it stopped: its fake-provider modes,
  the path-protection probes and its F2 `digest-override` observation (which
  would also fail now). Equivalent CLI reproductions are in the table above;
  fake-provider behaviour is covered by the existing counted tests.
- Its `/tmp` output was copied to the session scratchpad and removed.

## Repository checks

| Command | Result |
| --- | --- |
| `gofmt -l .` | no output |
| `go vet ./...` | ok |
| `go test ./... -count=1` | all ok |
| `go test ./scripts/validation/flh048 -count=1 -race` | ok |
| `python3 -B scripts/validation/flh045/validate.py` | exit 0 |
| SHA-256 of FLH-045 (5 files), FLH-051 harness (4), FLH-051 report, FLH-048 plan and validation, production evaluation service | unchanged (13/13) |

## Limits

- **No hard deadline.** A synchronous `Retrieve` that ignores its context (all
  existing offline retrievers) is not interrupted; the runner discards its late
  result. A hung retriever would hang the run. The embedding path does honour
  the context through `HTTPProvider`.
- **Parity scope.** It covers the field mappings and the domain derivation and
  normalization. It does not cover the declared synthetic Concept state, or
  whether a production catalog would store these Concepts the same way. It
  needs the Go toolchain and `-overlay` (adds about 1 s to the package tests).
- **JSON change.** Report schema v2 renames the freeze fields. Consumers of v1
  `expected_fixture_sha256`/`fixture_matches_expected` must update; FLH-051's
  harness reads only `fixture_sha256`, which is unchanged.
- **Not run:** Linux, CI, a real model. Results remain exploratory, with an
  author-visible held-out split and unreviewed judgments.
- FLH-051 has not re-reviewed this fix.
