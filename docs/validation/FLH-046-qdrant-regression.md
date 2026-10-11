# FLH-046 validation: real-Qdrant regression helper and CI job

Date: 2026-10-11. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64, Python 3.13.5,
Docker client/server 29.5.3, server linux/arm64). Owner: local Claude Code. No
Git/GitHub command or subagent was used. Contract:
[plan](../plans/FLH-046-qdrant-regression.md).

**GitHub Actions has not run this workflow.** Nothing here claims a CI pass;
that needs the human's push. The workflow YAML was parsed by PyYAML and Ruby
YAML only (no `actionlint` was available).

## Evidence kinds

- **Real, container mode:** Docker started the image pinned in `compose.yaml`,
  `qdrant/qdrant:v1.19.1@sha256:12364fe8…9246a10`. It reported version 1.19.1,
  commit `6ab21cac…`.
- **Real, endpoint mode:** the official native Qdrant 1.19.1 binary (same
  commit), run from the session scratch directory on `127.0.0.1:16446` with
  scratch storage.
- **Mock:** `test_qdrant_regression.py`, with synthetic `go test -json` events.
  It covers verdict logic only and certifies nothing about Qdrant.

At first the Docker daemon wasn't running, so the no-daemon case below is
real. Later the daemon was available, and container mode was exercised
against it.

## Results

| Case | Command (artifacts under the session scratchpad) | Expected | Actual |
| --- | --- | --- | --- |
| Container pass | `make qdrant-regression QDRANT_REGRESSION_ARGS="--artifacts …/run-container"` | exit 0, 8/8 | **exit 0, 8/8 passed** (see container details below) |
| Endpoint pass | `make qdrant-regression QDRANT_REGRESSION_ARGS="--endpoint http://127.0.0.1:16446 --artifacts …"` | exit 0, 8/8 | **exit 0, 8/8**; leftover sweep found none |
| Unavailable endpoint | `--endpoint http://127.0.0.1:9 --ready-timeout 5` | fail honestly | **exit 3** `not ready within 5s (last: Connection refused)` |
| No Docker daemon | container mode with the daemon stopped | fail, nothing started | **exit 3** `docker version … failed: … daemon is running`; no container created |
| Test timeout | `--endpoint … --test-timeout 1` | timeout exit | **exit 4**: Go `-timeout` panic, 1/8 passed, `go test did not finish`. The one collection left by the killed binary was deleted by the sweep; the instance ended empty |
| SIGTERM, endpoint | helper SIGTERMed after 4–8 s (3 runs) | interrupted, cleaned | **exit 3** each time; no `vectorindex.test` process left; 3, 2 and 2 leftover collections deleted; instance empty |
| SIGTERM, container | helper SIGTERMed after the suite started | interrupted, container removed | **exit 3**; container removed; 0 task containers left |
| Qdrant killed mid-run, endpoint | native Qdrant killed about 6 s in | regression failure | **exit 1**: 4 named failures, 4 passed; cleanup error recorded (`Connection refused`) |
| Container killed under the suite | `docker kill` at readiness | regression failure, cleanup | **exit 1**: 7 failures named (only `UnavailableQdrant` passed); container removed; `qdrant.log` and `docker-inspect.json` retained |
| Helper self-tests (mock) | `python3 -B -m unittest discover -s scripts/ci/flh046 -p 'test_*.py'` | pass | **16 tests OK**. Each of these is rejected: skip, all-skip (missing URL), subtest skip, failure, zero tests, missing expected, unexpected test, list drift, build failure, non-zero exit, unfinished run, unpinned or duplicate image. Also covered: the real compose pin parses, `expected_tests.txt` equals the declared tests, usage errors |
| `make verify` | no `FLH_QDRANT_URL` | unchanged, no container | **exit 0**; Go ok, frontend 215 tests, build ok; zero task containers |
| Skip baseline | `go test ./internal/vectorindex -run TestQdrantIntegration -v` without the URL | shows the gap | 7 `--- SKIP` lines (only `UnavailableQdrant` runs). This is the gap the job closes |

**Container details (from `docker-inspect.json`)**
- Image: the exact pinned digest.
- Storage: tmpfs `rw,size=1g`.
- Port: bound to `127.0.0.1` with a random host port (65420).
- Artifacts: `summary.json`, `go-test.jsonl`, `go-test.txt`, `qdrant.log`,
  `docker-inspect.json`.
- After the run: container removed; `docker ps -a --filter
  label=org.flh.task=flh046` was empty.

## Defects found and fixed while exercising the helper

- **Collections left after a timeout.** A Go timeout kills the test binary
  before `t.Cleanup`, so endpoint mode left a test collection behind. The
  helper now deletes only test-prefix collections that appeared during its run,
  on every exit path, and still fails the run.
- **Collections left after SIGTERM.** The helper waited only for `go`, so the
  child test binary could still create a collection. It now waits until the
  whole process group is gone.
- **Collections created after the sweep.** A create request already in flight
  could still complete after the sweep. The sweep now repeats until a round
  finds nothing new (at most 5 rounds).
- **Wrong cleanup message.** "Removed container" was printed when no container
  had started; that is fixed.

Each fix was re-run against real Qdrant (rows above).

## Cleanup and host state

- **Native Qdrant:** stopped, scratch storage deleted, ports 16446/16447 free.
- **Processes and containers:** no test process remained, and no task
  container remains.
- **Pre-existing containers:** unrelated containers on the daemon were not
  touched; the helper addresses only its own uniquely named container.
- **Image cache:** the pinned Qdrant image (about 300 MB) is now in the local
  Docker image cache. A pre-run listing showed no Qdrant image, so this run's
  pull added it. To remove it:
  `docker image rm qdrant/qdrant@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10`.

## Limits

- **GitHub Actions has not run this.** Runner behaviour (pull speed, Docker on
  `ubuntu-latest`, artifact upload) is unverified until the workflow runs.
  `actions/upload-artifact@v4` is assumed to be available.
- **Container mode ran on macOS Docker Desktop (linux/arm64),** not on Linux
  amd64 as CI uses.
- **A readiness timeout of a started container** wasn't induced: the image
  became ready within a second. The same `wait_ready` code produced the
  unavailable-endpoint failure.
- **Endpoint mode assumes no concurrent run** on the same endpoint (documented).
- **The suite proves index mechanics** with fake embeddings, not semantic
  quality.
