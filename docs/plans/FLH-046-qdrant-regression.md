# FLH-046 Real-Qdrant regression as an explicit CI capability

Owner: local Claude Code. Branch label supplied: `ci/flh-046-qdrant-regression`.
No Git/GitHub command or subagent was used. FLH-047 (parallel) owns
`scripts/validation/flh041/`; this task neither edits nor depends on it.
Evidence: [validation](../validation/FLH-046-qdrant-regression.md). Usage:
[SEMANTIC_SEARCH.md](../SEMANTIC_SEARCH.md#real-qdrant-regression-tests-flh-046).

## Problem

CI runs `go test ./...` without `FLH_QDRANT_URL`. Seven of the eight real-Qdrant
integration tests then skip (`TestQdrantIntegration_UnavailableQdrant` runs
anyway), and the job still passes. Nothing in CI proves the index works
against an actual Qdrant.

## Files

**Changed**
- `.github/workflows/ci.yml`:
  - adds a `cmd/semantic-index` build step to `ci`;
  - adds a new `qdrant-integration` job;
  - the existing `ci` and `web` steps are otherwise unchanged.
- `Makefile`: adds a `qdrant-regression` target and help text. `verify` is
  unchanged and starts nothing.
- `docs/SEMANTIC_SEARCH.md`: adds the "Real-Qdrant regression tests" section.

**New**
- `scripts/ci/flh046/qdrant_regression.py`: the helper (standard library only).
- `scripts/ci/flh046/expected_tests.txt`: explicit list of the expected tests.
- `scripts/ci/flh046/test_qdrant_regression.py`: unit tests for the helper's
  pure logic.
- This plan and the validation report.

No production Go, frontend, migration, Dockerfile, dependency or
`scripts/validation/flh041/` change was made.

## Acceptance criteria

1. **Existing checks preserved.** The Go and frontend checks are unchanged, and
   CI builds `cmd/semantic-index`.
2. **Real Qdrant from the exact pin.**
   - The image is the one pinned by digest in `compose.yaml`, which stays the
     single source; the helper refuses unless exactly one digest-pinned Qdrant
     image is found.
   - Storage is disposable tmpfs, and the port is a random one on `127.0.0.1`.
   - Pull, readiness, test and step timeouts are bounded.
   - The running version must match the pinned tag.
3. **The suite runs with `FLH_QDRANT_URL` set and fails on any of these:**
   - a skip at any level, or a failure;
   - zero tests;
   - an expected test not run, or an unexpected test run;
   - drift between the expected list and the declared tests;
   - a build failure;
   - unavailable Qdrant;
   - a timeout (Go `-timeout`, plus a watchdog that kills the process group);
   - leftover test collections.

   Exit codes are distinct: 1 regression, 3 environment, 4 timeout.
4. **Artifacts and cleanup.**
   - The artifacts (`summary.json`, `go-test.jsonl/.txt`, `qdrant.log`,
     `docker-inspect.json`) are kept and uploaded on every outcome.
   - The container is always removed, including after a failure and on
     SIGINT/SIGTERM.
   - In endpoint mode, only test-prefix collections created during the run are
     removed.
   - A CI `always()` step removes any container labelled `org.flh.task=flh046`.
5. **Documented local command.** It is `make qdrant-regression`, which uses the
   same helper; `make verify` never starts a container.
6. **No external dependencies.** There is no embedding service, secret, daily
   data, paid call or fallback; the suite's embeddings are deterministic fakes.

## Design notes

- **Python, not shell,** for subprocess timeouts, `go test -json` parsing,
  signal-safe `finally` cleanup and JSON artifacts, all with the standard
  library only. Python 3 is preinstalled on `ubuntu-latest`.
- **tmpfs storage** avoids root-owned files on the runner, a problem observed
  in FLH-043.
- **Explicit expected list, checked against the source.** A deleted or renamed
  test becomes a visible list change instead of a silent loss of coverage.
- **Repeated leftover sweep in endpoint mode.** A create request already in
  flight when a test binary is killed can complete after the first sweep (this
  was observed), so the sweep repeats until a round finds nothing new (at most
  5 rounds).

## Dependency reported, not edited

`AGENTS.md` (not owned) does not mention `make qdrant-regression`. Its owner may
add one line next to the `make verify` note.
