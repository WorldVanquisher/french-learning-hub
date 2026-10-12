# FLH-052 Experiment-runner contract fixes

Owner: local Claude Code. Branch label supplied:
`fix/flh-052-experiment-runner-contract`. No Git/GitHub command or subagent was
used.

Fixes the defects that [FLH-051](../validation/FLH-051-experiment-runner-acceptance.md)
reproduced in the FLH-048 runner (verdict NOT ACCEPTED): F1 (overall timeout
ignored offline), F2 (expected-hash override redefined "frozen"), R2 (exact
zeros unexplained in the standalone summary) and, where feasible, R1
(converter parity). Evidence:
[validation](../validation/FLH-052-experiment-runner-contract.md).

## Files (exact edit set, all under `scripts/validation/flh048/`)

| File | Change |
| --- | --- |
| `rank.go` | `RunRetriever` checks the context before and after every `Retrieve` and before declaring completion; `deadlineError` |
| `main.go` | `-timeout` must be positive; `-expect-fixture-sha256` is an extra assertion that must equal the frozen constant; run deadline recorded; exact `structure` attached |
| `inputs.go` | `Digests(raw, in)` compares with the compiled FLH-045 constant only; new freeze fields |
| `report.go` | schema `…_v2`; `Structure`/`ExactStructure`; summary freeze line, timeout line, structural note, first error of a failed retriever |
| `runner_test.go` | call sites for the new `Digests` signature |
| `contract_test.go` (new) | F1, F2 and R2 tests |
| `parity_test.go`, `parity_overlay_test.go`, `testdata/production_bridge.go.txt` (new) | R1 parity through `go test -overlay` |
| `README.md` | timeout, freeze, structural note, parity |

Plus this plan and the validation report. Not changed: FLH-045 files, the
FLH-051 harness, historical FLH-048/FLH-051 reports, production code,
dependencies, shared docs, CI. No production function was exported.

## Contract

**F1: overall timeout**
- `-timeout` ≤ 0 is a usage error (exit `2`, nothing written).
- Before each `Retrieve`: an expired or canceled context makes that query an
  `error` (no call), later queries `not_run_after_error`, state `failed`.
- After each `Retrieve`: if the context expired meanwhile, the result is
  discarded and the query is an `error` the same way.
- After the loop: a retriever is never declared `completed` once the context has
  ended.
- Failed retrievers have null metrics (unchanged rule). Every later retriever,
  including embedding, fails at its first pre-check, so no further `Retrieve`
  or provider request happens. Exit `1`, report written.
- **Limit:** the existing offline retrievers are synchronous and ignore their
  context. A running `Retrieve` cannot be interrupted by these checks; it
  completes and its result is then discarded. No goroutine or hard process
  deadline is introduced or claimed.

**F2: frozen fixture only**
- The fixture must hash to the compiled FLH-045 constant
  `92726376…7043a`, whatever the caller passes (exit `3` otherwise).
- `-expect-fixture-sha256` (default empty) is kept only as an extra equality
  assertion: any value other than the constant is refused (exit `2`).
- JSON `inputs`: `fixture_sha256`, `frozen_reference`,
  `frozen_reference_sha256`, `fixture_matches_frozen`,
  `caller_asserted_sha256` (when given). The former `expected_fixture_sha256`
  and `fixture_matches_expected` are removed; the schema becomes
  `flh048_exploratory_retrieval_comparison_v2`.
- The summary names the reference: "frozen reference (FLH-045 …, SHA-256
  compiled into this runner) `<sha>`; matches the frozen reference: true".

**R2: exact structural zeros**
- `ExactStructure` counts Concepts with scope/features and derived candidate
  identities with scope/features from the ranking inputs (never labels). The
  exact baseline's report carries it as `structure`, and the summary prints its
  note under the exact baseline.
- Inputs are unchanged: no target identity is copied into queries.

**R1: converter parity**
- A virtual bridge (`testdata/production_bridge.go.txt`) is added to
  `internal/application` only through `-overlay` and calls the real unexported
  converters. A build-tagged test compares them with the mirrors over the raw
  fixture and edge cases. An ordinary test runs that child `go test`, so
  `go test ./...` fails on drift.
- Remaining limit: the declared synthetic Concept state (normal, supported,
  active) and the persisted-Concept construction are fixture assumptions that
  parity cannot verify against a production catalog.

Preserved: label/input separation, ranking implementations, null versus zero,
denominators, provider cap, no fallback or retry, output safety.
