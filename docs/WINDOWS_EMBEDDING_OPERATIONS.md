# Windows E5 embedding runtime: remote operations (FLH-065)

This guide covers starting, checking, stopping and recovering the local E5
service on the Windows laptop. It works over plain OpenSSH on the Tailscale
network, with no Moonlight session and no console left open.

- **Tool:**
  [`tools/embedding/e5/windows/operations/flh-e5.ps1`](../tools/embedding/e5/windows/operations/flh-e5.ps1).
- **Service:** [`tools/embedding/e5/README.md`](../tools/embedding/e5/README.md).
- **Contract:** [plan](plans/FLH-065-windows-embedding-operations.md).
- **Evidence:** [validation](validation/FLH-065-windows-embedding-operations.md).

> **Status: real Windows execution is NOT RUN.** None of this has run on the
> laptop yet: start, readiness, stop, GPU use, survival of an SSH disconnect
> and the Tailscale Serve actions. SSH key authentication was not yet
> authorized. Only the local fake-platform tests have run.

## What it does

- **Fixed configuration:** one service, always on `127.0.0.1:8765` (`-Port`
  changes the port, not the address), with the pinned model, `float16`,
  microbatch 8 and `singleton_v1` batching.
- **Expected identity:** `start` succeeds only when the service reports this
  `deployment_id` (FLH-060's singleton deployment):
  ```
  multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff
  ```
  The identity covers library versions and the GPU. If an upgrade changes it,
  `start` reports the mismatch and stops the run it launched. Only pass
  `-ExpectedDeploymentId` after deciding to adopt the new identity, which is a
  new index space.
- **Detached:**
  - `start` launches a small supervisor (`runner.py`) through WMI
    (`Win32_Process.Create`). It runs as your user, outside the SSH session's
    job object, so closing SSH doesn't stop it.
  - The supervisor starts `python -B -m flh_e5 serve` and records its PIDs, its
    logs and how it exited.
- **Not persistent:**
  - Nothing restarts it after a reboot, and nothing is installed: no scheduled
    task, service, autostart, firewall rule or execution-policy change.
  - Whether it survives a Windows *logout* of an interactive desktop session
    hasn't been exercised. Treat it as unknown.

## Prerequisites (Windows, once)

1. **OpenSSH Server** is running on the laptop, and the Mac/NAS key is
   authorized.
   - If `awake` is an administrator, Windows OpenSSH reads only
     `C:\ProgramData\ssh\administrators_authorized_keys`. Run this in an
     **elevated** PowerShell, replacing the key with the client's
     `~/.ssh/id_ed25519.pub` line:
     ```powershell
     $k = 'ssh-ed25519 AAAA... flh-mac'
     Add-Content -Path C:\ProgramData\ssh\administrators_authorized_keys -Value $k
     icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"
     ```
   - If `awake` is **not** an administrator, append the same line to
     `C:\Users\awake\.ssh\authorized_keys` instead.
   - **Check from the Mac:** `ssh -o BatchMode=yes awake@100.118.109.6 whoami`.
   - **To revoke:** delete that line.
2. **Runtime checkout:** `C:\Users\awake\projects\flh-embedding-runtime`
   contains `tools\embedding\e5\` from this repository, including
   `windows\operations\`. Update it the way you normally do; the tool never
   runs Git.
3. **Conda environment:** `flh-embedding` exists with the E5 requirements
   installed, and `check-env.ps1` passes. The tool calls the environment's own
   `python.exe` directly, so neither `conda init` nor activation is needed in
   SSH sessions.
4. **Model files:** the pinned files are in
   `C:\Users\awake\models\multilingual-e5-base` (see the E5 README). Nothing is
   downloaded: the tool sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

**Defaults:**

| Setting | Default | Flag |
| --- | --- | --- |
| Runtime | `%USERPROFILE%\projects\flh-embedding-runtime` (`tools\embedding\e5` inside it is used if present) | `-RuntimeDir` / `-E5Dir` |
| Model | `%USERPROFILE%\models\multilingual-e5-base` | `-ModelDir` |
| Conda env | `flh-embedding`, found under `miniconda3`, `anaconda3`, `miniforge3` or `mambaforge` in `%USERPROFILE%`, `%LOCALAPPDATA%` or `%ProgramData%`, or `%USERPROFILE%\.conda\envs` | `-CondaEnvName` / `-CondaPrefix` / `-PythonExe` |
| State and logs | `%LOCALAPPDATA%\FLH\e5-runtime` | `-StateDir` |
| Port | 8765 | `-Port` |

All paths must be absolute and must not contain `"`. Spaces are fine.

## Running it over SSH

On Windows the default OpenSSH shell is `cmd.exe`, so call PowerShell
explicitly. `-ExecutionPolicy Bypass` applies to that one process only.

```sh
# from the Mac or the NAS
W=awake@100.118.109.6
OPS='C:\Users\awake\projects\flh-embedding-runtime\tools\embedding\e5\windows\operations\flh-e5.ps1'
e5() { ssh -o BatchMode=yes "$W" "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $OPS $*"; }

e5 check                 # read-only preflight; add -Cuda to run check_env.py, -VerifyFiles to hash the model
e5 start                 # detached; waits up to 300 s (-ReadyTimeoutSec) for ready + identity
e5 status                # process state and model state; -Json for machine-readable output
e5 logs                  # stderr tail of the latest run; -Stream all, -Tail 200, -List, -Run <id>
e5 stop                  # graceful (Ctrl+Break to the service, 30 s), then terminate; -Force skips the grace
e5 serve-status          # Tailscale Serve forwards, read-only
```

You can close the SSH session (or the Mac's lid) as soon as `start` returns.
`status` from a new session shows the same run.

**Exit codes**

| Action | 0 | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- | --- |
| `start` | ready with the expected identity (new or already running) | startup failed or identity mismatch; a run it launched is stopped | refused (bad path/option, port in use, another encoder); nothing launched | — | not ready by the timeout; left running |
| `status` | ready | failed, mismatch or unrelated listener | usage | stopped | running, model not ready |
| `stop` | stopped, or nothing to stop | an owned process could not be stopped | usage | — | — |
| `logs`, `check`, `serve-*` | ok | failure | usage or refusal | — | — |

**From the NAS (Go side)**
- **Settings:**
  - `EMBEDDING_BASE_URL=http://100.118.109.6:8765/v1` (through the existing
    Tailscale Serve forward);
  - `EMBEDDING_MODEL` and `EMBEDDING_MODEL_ID` set to the identity above;
  - `EMBEDDING_DIMENSIONS=768`.
- **Readiness check:** run `e5 status` first. The NAS can only tell that the
  port answers; `status` also tells "process running" apart from "model
  ready".

## Safety rules the tool enforces

- **Idempotent:**
  - `start` while its own run is alive launches nothing; it only waits for
    readiness.
  - `stop` with nothing running exits 0.
- **Refuses before launching:**
  - any listener on the port that isn't its own service;
  - any other `python -m flh_e5 serve` process, such as a foreground
    `start.ps1` console or another client's encoder.

  It never stops either of those.
- **Proves ownership before stopping anything:** a PID is signalled or
  terminated only if all of these still match the record in `current.json`:
  - its creation time;
  - its command line (the supervisor's names this run's unique `launch.json`;
    the service's is `-m flh_e5 serve --port <port>`);
  - for the service, its parent (the recorded supervisor, while that is
    alive).

  A reused PID is reported as unrelated and left alone. Nothing is ever
  matched by process name, and it never kills "all Python".
- **Stop order:**
  1. a stop-request file makes the supervisor send `CTRL_BREAK_EVENT` to the
     service's own process group (the service handles it like Ctrl+C: it
     drains the running request, frees the GPU and closes the port);
  2. after `-GracefulTimeoutSec` (default 30), the supervisor terminates the
     service;
  3. if the supervisor is gone, `stop` terminates the proven-owned service
     itself.
- **Bounded logs:** each run has its own directory under
  `%LOCALAPPDATA%\FLH\e5-runtime\runs\<run-id>\`:
  - `launch.json` (exact argv, cwd and environment additions);
  - `runner.json`, `runner.log`, `stdout.log`, `stderr.log`, `exit.json`;
  - `final.json`, written once the run is closed.

  Each `start` keeps the newest `-KeepRuns` (default 10) and deletes older run
  directories. Only names matching the run-ID pattern are touched. The service
  doesn't log requests, so each run's logs are small.

## Tailscale Serve

- **Existing forward:** the earlier remote clients used the human's own Serve
  forward on tailnet port 8765.
- **`serve-status`:** prints every forward and marks the one targeting
  `127.0.0.1:8765`.
- **`serve-enable [-ServePort 8765]`:**
  - **reuses** a matching forward and changes nothing;
  - **refuses** if that Serve port already carries a different target, or if
    Funnel is enabled anywhere;
  - otherwise runs exactly `tailscale serve --bg --http=8765
    http://127.0.0.1:8765`. That is **persistent**: it survives reboots.
  - It records the before/after configuration under `<state>\serve\`.
- **`serve-disable`:** removes only a forward that `serve-enable` recorded
  adding, and only while it's unchanged.
- **Never used:** `serve reset` and `funnel`. The service has no
  authentication; Serve shares it only within your tailnet, under its access
  rules.
- **Permissions:** `tailscale serve` may need the user that runs Tailscale on
  Windows, or an administrator. A failure is reported, not worked around.

## Failure recovery

| Symptom | What to do |
| --- | --- |
| `start` exit 2, "port 8765 is already in use by PID N" | Something else listens there, perhaps a foreground `start.ps1`. Stop it where it was started, or pick `-Port`. The tool won't touch it |
| `start` exit 2, "another flh_e5 service is running" | Same: a console-started service exists. Use `windows\stop.ps1` on the laptop (lists it, and needs `-Confirmed`) |
| `start` exit 1, "the service exited (exit code 3)" | Read the stderr tail it prints, or `e5 logs -Stream all`. Typical causes: model file verification failed, CUDA unavailable, the port was taken |
| `start` exit 1, identity mismatch | The runtime changed (library upgrade, other GPU or settings). Don't relabel vectors; decide whether to adopt the new identity |
| `start` exit 4 | Still loading: `e5 status` again later, or `e5 logs`; `e5 stop` to give up |
| `status` "stopped" with a last exit | The service ended (crash, reboot, logout). `e5 logs` shows why, then `e5 start` |
| Supervisor killed, service still up | `e5 stop` terminates the proven-owned service |
| `stop` says a PID "is now an unrelated process" | The machine rebooted and the PID was reused; the record is archived and nothing was touched |
| SSH "Permission denied (publickey…)" | Authorize the key (Prerequisites 1) |

## Cleanup

- `e5 stop` returns the GPU and port.
- `e5 serve-disable` is needed only if `serve-enable` added a forward.
- Deleting `%LOCALAPPDATA%\FLH\e5-runtime` removes all logs and records. Do it
  only while stopped.
- No other state exists: no scheduled task, service, registry entry or
  firewall rule.

## Tests (no Windows needed)

```sh
python3 -B -m unittest discover -s tools/embedding/e5/windows/operations/tests -p 'test_*.py'
pwsh -NoProfile -File tools/embedding/e5/windows/operations/tests/Test-FlhE5Ops.ps1
```

- **What they use:** a fake `flh_e5` service and a POSIX process/listener
  platform. They exercise the real decision logic, supervisor, quoting,
  ownership proofs, retention and Serve decisions.
- **What they don't exercise:** WMI, `Get-NetTCPConnection`, `CTRL_BREAK_EVENT`,
  CUDA or Windows OpenSSH. Those need the real laptop.
