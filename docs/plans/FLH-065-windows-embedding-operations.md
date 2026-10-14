# FLH-065 Reliable remote operation of the Windows E5 embedding runtime

Owner: local Claude Code. No Git/GitHub command or subagent is used. Evidence:
[validation](../validation/FLH-065-windows-embedding-operations.md). Operator
guide: [WINDOWS_EMBEDDING_OPERATIONS.md](../WINDOWS_EMBEDDING_OPERATIONS.md).

**Goal:** start, inspect, stop and recover the existing E5 service over
ordinary OpenSSH (Tailscale network), with no Moonlight session and no
foreground terminal left open.

**Unchanged:**
- the encoder, `flh_e5` and the deployment identity;
- Go production code, the database schema and the validation fixtures;
- `AGENTS.md`;
- the existing `windows/*.ps1` helpers.

**Not added:** new permanent dependencies, a model download, WSL, Docker, cloud
calls, firewall rules, a machine-wide execution-policy change, a scheduled task
or reboot autostart.

## Files (exact edit set)

| File | Purpose |
| --- | --- |
| `tools/embedding/e5/windows/operations/flh-e5.ps1` | Operator entry point (PowerShell 5.1+): `check`, `start`, `status`, `stop`, `logs`, `serve-status`, `serve-enable`, `serve-disable` |
| `tools/embedding/e5/windows/operations/FlhE5Ops.psm1` | All decision logic, with platform operations injected so they can be tested off Windows |
| `tools/embedding/e5/windows/operations/runner.py` | Stdlib-only detached supervisor: launches `python -B -m flh_e5 serve`, redirects its logs, performs graceful/forced stop on request, records the exit |
| `tools/embedding/e5/windows/operations/README.md` | Short pointer to the guide |
| `tools/embedding/e5/windows/operations/tests/test_runner.py` | Python unittest for the runner |
| `tools/embedding/e5/windows/operations/tests/Test-FlhE5Ops.ps1` | Dependency-free PowerShell test script (POSIX fake platform) |
| `tools/embedding/e5/windows/operations/tests/fake_e5/flh_e5/__main__.py` | Fake `flh_e5 serve` (readiness, manifest, signal handling, failure modes); no model, no GPU |
| `docs/WINDOWS_EMBEDDING_OPERATIONS.md` | Operator guide |
| This plan and the validation report | Documentation |
| `tools/embedding/e5/README.md` | One link to the guide only |

## Contracts

**Detached mechanism.** `start` creates the supervisor with WMI
`Win32_Process.Create` (`Invoke-CimMethod`).
- **Why WMI:** Windows OpenSSH places a session's processes in a job object
  that is closed when the session ends. A process created by the WMI provider
  host is not in that job, so it survives the SSH disconnect.
- **Permissions:** it runs as the same user, needs no administrator right, and
  installs nothing.
- **Logout and reboot:** it does not survive a reboot, and nothing restarts it.
  Survival of a Windows logout is not claimed unless the validation exercises
  it.
- **No scheduled task:** none is installed or offered in this milestone.

**Supervisor (`runner.py`)**
- **Launch:** started with the Conda environment's own `python.exe -B -I`. It
  reads one JSON launch spec (`flh065_e5_launch_v1`) from a task-owned run
  directory, so no user value is ever embedded in a shell string.
- **Child process:** `python.exe -B -m flh_e5 serve --model-dir <dir> --host
  127.0.0.1 --port <port> --dtype float16 --microbatch 8 --batching
  singleton_v1`. It runs with the E5 directory as its working directory, gets
  Conda-activation `PATH` entries plus `CONDA_PREFIX`, `CONDA_DEFAULT_ENV`,
  `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and `PYTHONUNBUFFERED=1`, and is
  created in its own process group. Arguments go through `subprocess` list
  quoting.
- **Logs:** the child's stdout and stderr go straight to files, so it never
  depends on the supervisor for I/O.
- **Stop:** a stop request file makes the supervisor send `CTRL_BREAK_EVENT`
  (Windows) or `SIGINT` (POSIX). The service already handles both gracefully.
  After the graceful timeout, the supervisor terminates the child.
- **Records:** `runner.json` (PIDs) and `exit.json` (exit code and reason).

**Operator actions and exit codes**

| Action | 0 | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- | --- |
| `start` | ready with the expected identity (new or already running) | startup failed or identity mismatch (the run it launched is stopped) | refused: bad path or option, occupied port, another encoder; nothing launched | — | still not ready at the timeout; left running |
| `status` | ready | failed, mismatch or unrelated listener | usage | stopped | process running, model not ready |
| `stop` | stopped, or nothing to stop | could not stop a proven-owned process | usage | — | — |
| `logs`, `check`, `serve-*` | ok | failure | usage or refusal | — | — |

**Ownership proof.** `current.json` records:
- the run ID and the spec path (a unique run directory);
- the supervisor PID, creation time and command line;
- the child PID and its creation time.

A process counts as owned only if:
- its PID, creation time and command line still match the record; and
- for the child, its parent is the recorded supervisor, while that supervisor
  is alive.

Nothing else is ever signalled or killed. In particular, `stop` never matches
by process name.

**Refusals before launch**
- **Bad options:** a relative or nonexistent path; a path containing `"`;
  missing model files (the six pinned names); a missing `python.exe`; a missing
  `flh_e5` package; or a port outside 1024–65535.
- **Busy machine:** any listener on the port that isn't the owned child, or any
  other `flh_e5 serve` process.
- **Concurrent use:** a lock file serializes `start` and `stop`.

**Readiness**
- `start` polls `GET /readyz` for up to `-ReadyTimeoutSec` (default 300).
- "Ready" means `/readyz` returns 200 **and** `GET /manifest` has
  `deployment_id` equal to `-ExpectedDeploymentId`. The default is the FLH-060
  singleton identity
  `multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff`.
- The listener must belong to the owned child.
- If the child exits, the start fails at once and shows the exit record and the
  stderr tail.

**Logs and retention**
- **Location:** `%LOCALAPPDATA%\FLH\e5-runtime\runs\<yyyymmddThhmmssZ-xxxxxxxx>\`
  holds `launch.json`, `runner.json`, `runner.log`, `stdout.log`, `stderr.log`
  and `exit.json`.
- **Pruning:** at each start, finished runs beyond the newest `-KeepRuns`
  (default 10) are deleted. Only directories matching the run-ID pattern are
  touched.
- **Size:** the service logs no request lines, so each run's logs stay small.

**Tailscale Serve**
- **`serve-status`:** read-only (`tailscale serve status --json`). It reports
  each forward and whether one targets `127.0.0.1:<port>`.
- **`serve-enable`:**
  - reuses a matching forward with no change;
  - refuses if the requested Serve port already carries something else, or if
    Funnel is on;
  - otherwise runs exactly `tailscale serve --bg --http=<ServePort>
    http://127.0.0.1:<port>` and records before/after JSON in the state
    directory.
- **`serve-disable`:** removes (`--http=<ServePort> off`) only a forward this
  tool recorded adding, and only while it is unchanged.
- **Never used:** `serve reset` and Funnel.

## Acceptance

| # | Criterion | How |
| --- | --- | --- |
| S1 | PowerShell parses; no syntax beyond Windows PowerShell 5.1 | Parser and PSScriptAnalyzer `PSUseCompatibleSyntax` 5.1, if available |
| S2 | Quoting and paths with spaces | Round trip through real process creation |
| S3 | Repeated start/stop; occupied port; missing model/runtime; startup failure; identity mismatch; forced stop; orphan child; PID reuse; retention; Serve decisions | Fake platform tests (macOS/pwsh 7 and the runner unittest) |
| W1 | Real Windows start, readiness with identity, status, logs, stop | Needs SSH access |
| W2 | Survives closing the initiating SSH session | Start in one SSH session, check from a new one |
| W3 | ≤ 32 synthetic positions; initial service and forward state restored | Live smoke |
