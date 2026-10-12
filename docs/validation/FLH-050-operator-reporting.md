# FLH-050 validation: cleanup and operator reporting

Date: 2026-10-12. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64; Go `go1.26.5`
through the host's toolchain switch; Python 3.13). Owner: local Claude Code.
No Git/GitHub command, subagent, secret, `.env` read, paid provider, daily
database or permanent installation was used. Contract:
[plan](../plans/FLH-050-operator-reporting.md).

Historical reports (FLH-046, FLH-047, FLH-049) were not edited.

## Changes

**Helper, endpoint mode** (`scripts/ci/flh046/qdrant_regression.py`)
- New `endpoint_cleanup()`: the sweep ends with a verifying listing. A listing
  or deletion error, or a collection still present, leaves
  `leftover_cleanup.verified = false`.
- Unverified cleanup sets `summary.cleanup_error`, logs `FAIL`, and changes an
  exit `0` to `3`. An earlier `1` or `4` is kept with its verdict and reasons.
  Artifacts are written as before.
- A failure to list collections before the suite is now an environment error
  (exit `3`) instead of an uncaught traceback.

**`semantic-index` text output** (`cmd/semantic-index/main.go`; JSON unchanged)
- `printCleanup`: `cleanup: removed N leftover collection(s); M pending`, one
  `pending:` line per name, `cleanup error:` when set, and a next-step hint
  when something is pending. Printed whenever cleanup ran or left something;
  not printed for a run that failed before cleanup.
- A healthy `sync` says "published nothing" instead of "nothing written".
- `status`: `retired`/`abandoned` leftovers are "removed by the next run,
  including a healthy sync"; another run's `writing` collection is "removed only
  by the next publishing run (build, rebuild, or a sync that republishes); a
  healthy sync keeps it"; the lease holder's `writing` collection is
  `in progress`.
- Exit codes are unchanged (successful run with pending cleanup: `0`).

## Mocked evidence (no real Qdrant)

`python3 -B -m unittest discover -s scripts/ci/flh046 -p 'test_*.py'`: 24 tests
OK (16 existing + 8 new). The facade is a loopback HTTP stand-in, **not
Qdrant**.

| Test | Shows |
| --- | --- |
| `test_flh049_final_listing_503_after_passing_suite_fails` | FLH-049's case (listings 1–2 succeed, listing 3 answers 503) after 8 passes: exit 3, verdict still ok, `cleanup_error` names 503, `go-test.jsonl` kept |
| `test_clean_endpoint_passes_with_verified_cleanup` | exit 0, `verified: true`, nothing deleted |
| `test_cleanup_failure_keeps_regression_status_and_reasons` | failed suite + 503: exit 1, `failed:` reason kept |
| `test_cleanup_failure_keeps_timeout_status` | timeout + 503: exit 4 |
| `test_deletion_that_does_not_remove_is_caught_by_verification` | DELETE answers 200 but the collection stays: exit 3, `not_deleted` names it |
| `test_leftover_is_deleted_and_preexisting_collections_kept` | leftover deleted and verified; preexisting `flh042_it_` and unrelated kept; exit 1 (leftover is a regression) |
| `test_listing_failure_before_the_suite_is_an_environment_error` | exit 3, suite never started |
| `FLH049Reproduction.test_cleanup_listing_503_exits_nonzero` | The FLH-049 probe shape as a subprocess: unchanged helper file, real `go test` over eight trivial tests named from `expected_tests.txt` in a temporary module, same 503 facade. `go_exit 0`, 8/8 passed, helper `FAIL (exit 3)`, no `[flh046] PASS`. FLH-049 observed exit 0 / PASS for this shape |

`go test ./cmd/semantic-index` (also with `-race`): new pure text tests
`TestPrintReport_HealthySyncShowsPendingCleanup` (FLH-047 O1's report:
pending old name, `vector index unavailable`, `verified_unchanged`),
`TestPrintReport_HealthySyncShowsCleanedCount`,
`TestPrintReport_PublishedAndFailedRuns` and
`TestPrintStatus_DistinguishesLeftoverKinds` (O2: dead run's writing,
lease holder's writing, retired, abandoned, expired lease).

**Mutation checks.** Each was applied in place and the file restored
byte-identical (SHA-256 checked). All 9 are caught:
- H1 cleanup failure ignored; H2 verification always true; H3 earlier exit code
  overwritten by 3; H4 pre-run listing error not converted.
- C1 cleanup lines removed; C2 "nothing written" restored; C3 writing shown as a
  next-run leftover; C4 cleanup error hidden; C5 cleanup line on a failed run.

## Real evidence (pinned Qdrant `v1.19.1@sha256:12364fe8…`)

The image was already in the local Docker cache. My own container used
`--pull never`; the helper's container mode ran its usual `docker pull` of the
pinned digest, which found the cached image.

**CLI reproduction of O1, O2 and point 4.** A disposable container
(`--pull never`, tmpfs, `127.0.0.1` random port, label `org.flh.task=flh050`),
then:

```sh
FLH_QDRANT_URL=http://127.0.0.1:<port> go test ./cmd/semantic-index -count=1 -v -run CLIQdrant
```

`TestCLIQdrant_CleanupReportingAgainstRealQdrant` passed (0.21 s). It runs the
real `run()` with a temporary SQLite database (3 Concepts), a local fake
embedding server and a loopback proxy that answers 503 to DELETE of one named
collection. Observed text, abridged:

```text
sync … (exact FLH-047 O1 command: -batch 2 sync, DELETE of the retired collection blocked)
  verified unchanged:  <space>_r06fb092e10f7 is healthy; published nothing
  cleanup:             removed 0 leftover collection(s); 1 pending
    pending:           <space>_re87785598dda
    cleanup error:     vector index unavailable
  outcome:             verified_unchanged            (exit 0)
status
  leftover:          <space>_re87785598dda (retired, run …) — removed by the next run, including a healthy sync
sync (DELETE unblocked)
  cleanup:             removed 1 leftover collection(s); 0 pending   (collection gone in Qdrant)
status (another run holds the lease, its writing collection exists)
  in progress:       <space>_rother-run-fl (writing, run other-run-flh050 holds the lease)
-takeover sync, then status
  pending:           <space>_rother-run-fl
  leftover:          <space>_rother-run-fl (writing, run other-run-flh050) — removed only by the next publishing run …
sync                 (collection still present in Qdrant, as status says)
rebuild
  cleanup:             removed 2 leftover collection(s); 0 pending   (writing collection gone; status lists no leftover)
```

Afterwards the container listed no collections; it was removed (`docker rm -f
-v`), and no `org.flh.task=flh050` container remains.

**Helper, endpoint mode, real Qdrant** (same disposable container, before its
removal): `python3 -B scripts/ci/flh046/qdrant_regression.py --endpoint
http://127.0.0.1:<port> --artifacts <scratch>/endpoint-real --ready-timeout 10`
→ 8/8 expected tests passed, `leftover_cleanup = {found: [], not_deleted: [],
verified: true}`, exit 0. The endpoint listed no collections afterwards.

**Helper, container mode, real Qdrant:** `python3 -B
scripts/ci/flh046/qdrant_regression.py --artifacts <scratch>/container-real`
→ 8/8 passed, container removed, exit 0; no `org.flh.task=flh046` container
remains.

A real endpoint-mode cleanup *failure* was not induced against Qdrant; it is
covered only by the facade tests and the real-`go` facade reproduction above.

## FLH-049 probe rerun (unchanged file)

`scripts/validation/flh049/probe.py helper --output /tmp/flh049-flh050-recheck`
(the probe only accepts `/tmp/flh049…`; removed afterwards). The probe hardcodes
`GOSUMDB=off`, which blocks this host's Go 1.24.5 → 1.26.5 toolchain switch, so
it was run with the cached go1.26.5 toolchain's `bin` first on `PATH` for that
command only.
- `skip`, `zero`, `fail`, `cleanup`: the probe's own assertions held (exit 1
  each; the controlled leftover was deleted with `verified: true`, the
  preexisting collection kept).
- `cleanup_error`: the probe writes `go 1.27` into its temporary module; Go
  1.27 isn't available offline here, so `go test` failed to build (exit 1) and
  the probe's `exit == 0` assertion failed for that reason. This is **not** the
  exact reproduction. The summary did record the new behaviour
  (`verified: false`, `cleanup_error` naming the 503). The faithful reproduction
  is `FLH049Reproduction` above, which uses `go 1.21`.
- `timeout`: not reached.

## Repository checks

| Command | Result |
| --- | --- |
| `gofmt -l .` | no output |
| `go vet ./...` | ok |
| `go test ./... -count=1` | all ok (the real-Qdrant CLI test skips without `FLH_QDRANT_URL`) |
| `go test ./cmd/semantic-index -count=1 -race` | ok |
| `python3 -B -m unittest discover -s scripts/ci/flh046 -p 'test_*.py'` | 24 OK |

During the work, `go build ./cmd/semantic-index` left a binary in the repository
root and `py_compile` left `scripts/ci/flh046/__pycache__`; both were created by
this task and removed.

## Limits and notes

- **Not run:** Linux, GitHub Actions. The new real-`go` helper test needs the Go
  toolchain; CI's `qdrant-integration` job sets it up before the helper
  self-tests.
- The CLI real-Qdrant test is opt-in (`FLH_QDRANT_URL`) and is not part of the
  helper's expected list, which covers `./internal/vectorindex` only.
- **Engine behaviour observed, not changed:** a healthy `sync` that only leaves
  another run's `writing` collection pending (no error) still records
  `last_error = "cleanup incomplete: 1 leftover collection(s) remain"`. The text
  output now explains that collection's eligibility, but the `last_error`
  wording is engine-owned and out of scope.
- Helper cleanup acceptance (CI) and the CLI's successful-with-pending outcome
  stay separate: the helper fails on unverified cleanup; the CLI exits `0`
  and reports what is pending.
