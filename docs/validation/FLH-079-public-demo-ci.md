# FLH-079 validation: offline public-demo acceptance in CI

Date: 2026-10-15 (UTC). Working directory: `/home/worldvanquisher/workspace/flh-nas-claude`
(NAS, Arch Linux x86_64; go 1.27.1, node 26.9.0, npm 12.0.2, Python 3.14.7).
Implementation owner: NAS Claude Code.

**Not used:** Git/GitHub, subagents, Windows, a GPU, Docker, Qdrant, AWS, any
model or provider call, public deployment, or changes to NAS services. No
permanent dependency was installed: npm packages went into task-local
directories, and actionlint ran through `go run` with module and build caches
in a temporary directory.

**Outcome:**
- **Local: PASS.** 210 HTTP/artifact/process checks passed and 0 failed. The
  browser stage was **NOT RUN** because this host has no Chrome or Chromium.
- **Controlled failure probe: PASS.** A deliberate assertion failure exits 1, and
  SIGTERM exits 143. Both runs clean up.
- **GitHub-hosted execution: NOT RUN.** It runs only after the human owner
  pushes and Actions executes `public-demo.yml`. The local results above are
  not an Actions result.

Mechanical vectors prove routing, preset and ranking **mechanics**. They say
nothing about retrieval quality.

## Files (all new)

| File | Purpose |
| --- | --- |
| `.github/workflows/public-demo.yml` | The workflow |
| `scripts/validation/flh079/run.py` | Single entry point; writes `summary.json` |
| `scripts/validation/flh079/failure_probe.py` | Controlled failure and interruption probes |
| `scripts/validation/flh079/test_run.py` | Helper unit tests and static workflow-policy tests |
| `scripts/validation/flh079/README.md` | Pointer to this report |
| `docs/validation/FLH-079-public-demo-ci.md` | This report |

No shared workflow, Makefile, manifest, AGENTS.md, production code, or shared
documentation was edited. No FLH-078-owned file was touched: `package.sh`,
packaging tests, PUBLIC_DEMO.md and the FLH-076/077 reports.

## Reuse: what is under test vs. what the harness adds

The application behaviour is the repository's own, built from source:

| Reused | Role |
| --- | --- |
| `cmd/server` | The server under test, in `-public-demo-artifact` mode with `-web-dir` |
| `scripts/demo/flh073/prepare` | `build` makes the synthetic mechanical artifact. `validate`, plus `-release` (exit 3 = BLOCKED) |
| `scripts/demo/flh073/fixtures/catalog.json` | Synthetic data. It is also the oracle for Concept and original-question provenance |
| `web/` (copied) | The `VITE_FLH_PUBLIC_DEMO=1` production bundle |
| `scripts/demo/flh034/proc_guard.py` | Port check, PID + start-time + command-line record, loopback-listener wait, verified stop, leftover scan |
| `scripts/demo/flh076/browser/accept.mjs` | The real-browser acceptance. Each of its checks is imported as DOM evidence |

The harness adds assertions, orchestration and reporting only.

The existing wrappers were **not** called directly, for three reasons:
- `flh073/smoke.sh` and `flh076/browser/run.sh` build the web bundle with the
  repository's `web/node_modules`. On the NAS that directory is absent, and
  creating it would change the shared working tree.
- `run.sh` defaults to the macOS Chrome path.
- `smoke.sh` hashes with `shasum`.

`run.py` therefore copies an allowlist of `web/` sources into WORK, runs
`npm ci` there and hashes with Python's `hashlib`. It does not touch
packaging.

### Packaging (FLH-078 dependency)

`package.sh` is **not invoked**. This is source-based CI. The known `shasum`
defect (FLH-077 D2) belongs to FLH-078's packaging and is neither shimmed nor
hidden here.

## Entry point: `run.py`

```sh
python3 -B scripts/validation/flh079/run.py --work /abs/new/dir [--port 18990] \
  [--require-browser] [--chrome PATH] [--npm-cache DIR] [--keep-work]
```

**WORK must be a new absolute directory outside the repository.** Otherwise
the script exits 2 and creates nothing. It also exits 2 if the port is
occupied, before anything is launched.

Stages:
1. **preflight** checks the tools and that the port is free. A missing tool
   makes the run BLOCKED.
2. **build** builds the server and `prepare`.
3. **artifact** builds the mechanical artifact and then checks:
   - `validate` exits 0;
   - `validate -release` exits 3 with `RELEASE BLOCKED`;
   - the manifest's `release_status` is `blocked_mechanical_vectors`;
   - the server refuses the artifact without `-public-demo-allow-mechanical`;
   - the server refuses a live embedding provider;
   - the artifact files are recorded by SHA-256 and made read-only.
4. **web** runs `npm ci` and the demo `vite build` in WORK.
5. **serve-http** starts the server through `env -i` (loopback, cwd
   WORK/run) and checks that it listens on loopback only. HTTP checks:
   - **static:** `/` is HTML with the app root, and every `/assets/` file
     referenced by `index.html` returns 200 to GET and HEAD with the right
     content type. The bundle is the public-demo build. A missing asset and an
     unknown page are 404 (no SPA fallback).
   - **routing:** health, readiness and demo info answer at the root and under
     `/api`. Six representative GETs return the same bytes at both. `/api`
     alone is 404. Demo info says read-only, synthetic, mechanical and blocked
     from release, and lists the fixture presets.
   - **keyword:** `subj` matches the subjunctive Concepts, a nonsense query
     returns nothing, and a 201-byte query is rejected with 400.
   - **semantic and hybrid (presets):** every preset's semantic search returns
     its exact preset text and results with none stale. A hybrid search uses
     `concept_hybrid_rrf_v1` with a status filter and both components. An
     unknown preset is 404. Each preset call consumed exactly one cached
     vector.
   - **Concepts and provenance:** every Concept matches its fixture (identity,
     scope, support state, supporting-unit statements). Supported Concepts
     have units and the empty ones are orphaned. For each of the 11 supporting
     units, the source record's original question and context equal the
     fixture's, its extractor and analyzer are the fixture provenance, and its
     current Concept is the one it was reached from. An unknown Concept or
     unit is 404.
   - **denied** (at the root and under `/api`):
     - writes: POST/PUT/PATCH/DELETE on 7 paths return 405;
     - private API routes return 404;
     - free-text semantic/hybrid routes return 404;
     - free text on demo routes returns 400.

     Sixteen raw private-file paths return 404 without SQLite or vector
     content: artifact files, `.env`, logs, `..` and `%2e%2e` traversal, and
     `/assets/`. Denied requests consumed no vector.
6. **restart** stops the server through `proc_guard` and checks that the port
   is free and the artifact bytes are unchanged. It starts the server again:
   the in-memory counters are back at zero, and 28 responses are
   byte-identical to the first run.
7. **browser** runs `accept.mjs` with a task-local `playwright-core@1.49.1`,
   the same pin as FLH-076, and no browser download. Its checks become `dom.*`
   entries: title and notices, no editing controls, keyword/empty/error
   states, preset semantic and hybrid results, Concept → source → back
   navigation with focus restore, an injected client-side 503, and its own
   request allowlist. Its artifact bytes are rechecked afterwards. If no
   browser is found, this stage is **NOT RUN**, or **BLOCKED** with
   `--require-browser`.
8. **final** stops the server and checks that the port is free. The artifact
   bytes are unchanged, there is no `-wal`/`-shm`/`-journal` file, and
   `validate` still passes.

### Evidence separation

Every check has an `evidence` field:

| Value | Source |
| --- | --- |
| `http` | Python `http.client` against the server, with raw paths |
| `dom` | `accept.mjs` in a real browser |
| `artifact` | File hashes and the `prepare` tool |
| `process` | `proc_guard` |

### Summary and exit codes

The summary is `WORK/diagnostics/summary.json`, with schema
`flh079_public_demo_ci_summary_v1`:
- `overall` is PASS, FAIL or BLOCKED; `exit_code`;
- `interrupted_by_signal`;
- each stage's status (PASS, FAIL, BLOCKED or NOT RUN) and duration;
- every check, the failed checks, `counts_by_evidence`, `not_run`;
- cleanup facts and the environment.

Overall status: any FAIL makes the run FAIL; otherwise any BLOCKED makes it
BLOCKED; otherwise it is PASS. NOT RUN stages are listed separately and are
never counted as passed.

| Exit | Meaning |
| --- | --- |
| 0 | PASS |
| 1 | FAIL |
| 2 | Usage error or refused preflight |
| 3 | BLOCKED |
| 128+N | Interrupted by signal N |

### Cleanup

Cleanup runs on success, failure and SIGINT/SIGTERM/SIGHUP. Further signals are
ignored during cleanup.

- **Server:** it is signalled only through `proc_guard stop`, which signals a
  PID only when its recorded start time and command line still match. Cleanup
  then requires no matching process and a free port.
- **Bounded children:** builds and npm run through `subprocess.run` with
  timeouts, which kills only that child.
- **Files:** log tails of at most 200 kB are copied to `diagnostics/logs/`.
  Unless `--keep-work`, everything else in WORK is removed: binaries, the
  artifact (database, vectors, manifest), `node_modules`, the npm cache and
  the web build.

## Controlled failure probe: `failure_probe.py`

```sh
python3 -B scripts/validation/flh079/failure_probe.py --work /abs/new/dir [--port 18992] [--npm-cache DIR]
```

It changes no production source. Both probes use the hidden `run.py --probe`
switch.

| Probe | What happens | PASS only if |
| --- | --- | --- |
| `assertion` | Once the server is up, the harness asserts a deliberately wrong expectation: `GET /demo.db` → 200. The boundary correctly answers 404 | `run.py` exits 1, overall is FAIL, and the only failed check is `probe.deliberate_wrong_expectation`. Cleanup reported OK, no matching process remains and the port is free |
| `interrupt` | `run.py` holds with the server running. The probe sends SIGTERM to that `run.py`, its own direct child | Exit 143, `interrupted_by_signal` is 15, the recorded server PID is gone, no matching process remains and the port is free |

The probe summary is `WORK/probe-summary.json` (`flh079_failure_probe_v1`).

## Workflow: `.github/workflows/public-demo.yml`

**Triggers:**
- `pull_request` and `push` to `main`, path-filtered to:
  - `cmd/server/**`, `internal/**`, `migrations/**`, `web/**`;
  - `go.mod`, `go.sum`;
  - the reused tooling (`flh034/proc_guard.py`, `flh073/**`,
    `flh076/browser/**`);
  - `scripts/validation/flh079/**` and the workflow itself;
- `workflow_dispatch`.

There is no `pull_request_target` and no secret.

**Safety settings:**
- `permissions: contents: read`, and checkout uses `persist-credentials: false`;
- concurrency is per PR or ref with `cancel-in-progress: true`;
- the job timeout is 30 min, and every `run` step has its own timeout;
- actions follow `ci.yml`'s tag pins: `actions/checkout@v6`,
  `actions/setup-go@v7`, `actions/setup-node@v4` (Node 22, npm cache keyed on
  `web/package-lock.json`) and `actions/upload-artifact@v4`.

**Steps:**
1. tooling self-tests;
2. `run.py --require-browser --npm-cache ~/.npm`. ubuntu-latest's Google Chrome
   is found on PATH; if it is missing the run is BLOCKED and the job fails;
3. `failure_probe.py`, which runs unless the job was cancelled;
4. a `proc_guard stop` safety net for a killed harness, which always runs.

**Diagnostics** are collected and uploaded only on failure or cancellation, as
`public-demo-diagnostics` with 5-day retention:
- summaries;
- log tails of at most 200 kB;
- browser `results.json` and PNG screenshots.

Databases, vectors, receipts, credentials, binaries, `node_modules` and work
directories are never uploaded.

## Commands executed and results (local, NAS)

| Command | Result |
| --- | --- |
| `python3 -B -m unittest discover -s scripts/validation/flh079 -p 'test_*.py'` | 25 tests, OK |
| `run.py --work <scratch>/final-accept --port 18990` | Exit 0, **OVERALL PASS**: 210 PASS / 0 FAIL (http 193, artifact 10, process 7); browser **NOT RUN** (no Chrome/Chromium); 8.6 s wall (warm Go cache, task-local npm cache) |
| `run.py --work <scratch>/final-reqbrowser --port 18990 --require-browser` | Exit 3, **OVERALL BLOCKED** (browser), 210 PASS / 0 FAIL |
| `run.py ... --chrome /usr/bin/false` (wiring check) | Exit 1, browser stage FAIL. `playwright-core` installed task-locally, `accept.mjs` started and failed to launch the "browser", and no `results.json` was reported. This proves the stage's plumbing and failure path only |
| `failure_probe.py --work <scratch>/final-probe --port 18992` | Exit 0, **FAILURE PROBE PASS**. assertion: exit 1, one failed check, cleanup OK. interrupt: exit 143, signal 15, server gone, port free. 15.7 s |
| `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 public-demo.yml ci.yml` (temporary caches) | Exit 0, no findings. shellcheck is not installed, so inline shell was not shellchecked |
| After the runs: `ss -ltn`, `pgrep` | Ports 18990–18992 free, no task process left. Each WORK held only `diagnostics/` (about 80 kB) |

**Not run:**
- The browser stage locally: no Chrome or Chromium on the NAS, and none was
  installed.
- GitHub-hosted execution.

## Reproduction

**Prerequisites:**
- Go (version per `go.mod`), Node 22+ with npm, Python 3, and network access
  for `npm ci` / `go build` module downloads;
- optionally a Chrome or Chromium, located by `--chrome`, then `$CHROME`, then
  `google-chrome`, `google-chrome-stable`, `chromium` or `chromium-browser` on
  PATH;
- Linux or macOS (`proc_guard`). The harness has been run on Linux only.

```sh
W=$(mktemp -d)/flh079   # any new absolute path outside the repository
python3 -B scripts/validation/flh079/run.py --work "$W/accept"
python3 -B scripts/validation/flh079/failure_probe.py --work "$W/probe"
python3 -B -m unittest discover -s scripts/validation/flh079 -p 'test_*.py'
```

**Diagnostics:**
- Read `"$W/accept/diagnostics/summary.json"`, in particular `failed_checks`,
  then the matching file in `diagnostics/logs/`.
- Browser evidence is in `diagnostics/browser/`.
- Use `--keep-work` to keep the artifact and builds; the artifact files stay
  read-only.
- If a harness was killed with SIGKILL, run
  `python3 -B scripts/demo/flh034/proc_guard.py stop "$W/accept/run"`.

**Expected runtime:**

| Run | Time | Status |
| --- | --- | --- |
| Local, warm caches | about 9 s (acceptance), about 16 s (probe) | Measured |
| Local, first run | Add the Go module download and a cold build | Not measured |
| GitHub Actions | 3–6 min including setup and the browser | **Estimate only, not measured** |

## Limitations and risks

- **The DOM path is unexercised.** Neither GitHub-hosted execution nor a real
  local browser run has happened. `accept.mjs` with `playwright-core@1.49.1`
  passed on Chrome 155 on macOS (FLH-076); on the Linux runner's Chrome it is
  untested until Actions runs.
- **The DOM checks depend on FLH-076's UI copy.** `accept.mjs` is reused
  unchanged, so its assertions on copy (title, notices, labels) are what the
  DOM evidence checks. A UI wording change in FLH-078 or later must update
  `accept.mjs`, which is owned outside this task.
- **Path filters can skip relevant changes.** A change outside the filtered
  paths does not trigger the workflow; use `workflow_dispatch`.
  `cancel-in-progress` also cancels superseded runs on `main`.
- **A SIGKILL bypasses in-process cleanup.** The workflow's safety-net step,
  or the manual `proc_guard stop` above, covers it.
- **Local runs reuse the user's Go build cache.** This is a cache, not an
  installed dependency. The npm cache is task-local unless `--npm-cache` is
  given.
- **Server logs contain the absolute artifact path** (the runner's temporary
  directory in CI).
- **Pending for the human owner:**
  - integrate and push;
  - observe the first Actions run;
  - decide whether `CLAUDE.md`/`AGENTS.md` should mention the new workflow
    (shared files, not edited here).
