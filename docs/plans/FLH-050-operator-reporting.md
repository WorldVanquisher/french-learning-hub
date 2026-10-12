# FLH-050 Close reproduced cleanup/reporting defects

Owner: local Claude Code. Branch label supplied:
`fix/flh-050-operator-reporting`. No Git/GitHub command or subagent was used.

Evidence: [validation](../validation/FLH-050-operator-reporting.md).

## Findings closed

| Finding | Source | Defect |
| --- | --- | --- |
| Endpoint cleanup PASS | [FLH-049](../validation/FLH-049-evaluation-and-ci.md), `qdrant_regression.py:402–403` | In endpoint mode a failed leftover sweep (for example the final collection listing returns HTTP 503) is recorded in `leftover_cleanup.error`, but the helper still exits `0` and prints PASS. |
| O1 | [FLH-047](../validation/FLH-047-semantic-recovery-acceptance.md), `cmd/semantic-index/main.go:159–163` | Default text output of `sync`/`build`/`rebuild` omits `cleanup_pending` and `cleanup_error`; a healthy `sync` says "nothing written" even when it deleted leftovers. |
| O2 | FLH-047, `cmd/semantic-index/main.go:249` | `status` says every leftover is "removed by the next run", but a healthy `sync` never removes another run's `writing` collection. |

Historical reports (FLH-046, FLH-047, FLH-049) are not edited.

## Files (exact edit set)

- `scripts/ci/flh046/qdrant_regression.py`: endpoint sweep and pre-run listing.
- `scripts/ci/flh046/test_qdrant_regression.py`: orchestration regressions.
- `cmd/semantic-index/main.go`: `printReport`, `printStatus` text only.
- `cmd/semantic-index/main_test.go`: text-output regressions.
- `docs/SEMANTIC_SEARCH.md`: helper and CLI wording.
- this plan and the validation report (new).

Not changed: application/storage engine, JSON structs, migrations, frontend,
dependencies, CI workflow, `expected_tests.txt`, FLH-049 files.

## Contract

**Helper (endpoint mode)**
- The sweep ends with a verifying listing that must show no new
  `flh042_it_` collection. If any listing or deletion fails, or a collection
  remains, the sweep is a cleanup failure.
- A cleanup failure turns an otherwise successful run into exit `3` and FAIL.
  An earlier nonzero code (`1` regression, `4` timeout) is kept; the verdict,
  its reasons and all artifacts are preserved.
- `summary.json` gains `cleanup_error` and `leftover_cleanup.verified`.
- A failure to list collections before the suite is an environment error
  (exit `3`), not a Python traceback.

**`semantic-index` text output (JSON unchanged)**
- Every run prints `cleanup: removed N; pending M` plus the pending names and
  the cleanup error when present.
- A healthy `sync` says "published nothing" instead of "nothing written".
- Exit codes are unchanged: a successful run with pending cleanup still exits
  `0`. This is an operator outcome, separate from the CI helper's acceptance.

**`status` leftovers**
- `retired`/`abandoned`: removed by the next run, including a healthy `sync`.
- `writing` of the run holding an active lease: in progress.
- other `writing`: removed only by the next publishing run (`build`,
  `rebuild`, or a `sync` that republishes); a healthy `sync` keeps it.
