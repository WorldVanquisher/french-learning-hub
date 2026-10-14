# FLH-065 validation: Windows E5 embedding operations (checkpoint)

Date: 2026-10-14. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` on **macOS arm64**.

**Not used:**
- Git/GitHub commands or subagents;
- Docker (unavailable, and the human said not to use it);
- `.env` or private keys. Only the public `id_ed25519.pub` line was read, to
  give the human the authorization line.

Contract: [plan](../plans/FLH-065-windows-embedding-operations.md). Guide:
[WINDOWS_EMBEDDING_OPERATIONS.md](../WINDOWS_EMBEDDING_OPERATIONS.md).
FLH-064 evidence was not touched.

This is a **checkpoint**, by the human's decision: implementation and local
tests are done, and real Windows verification is deferred.

## Windows execution: BLOCKED / NOT RUN

**SSH connectivity check (Mac → laptop)**
- `tailscale status` listed `worldvanquisher`, `100.118.109.6`, Windows, idle
  (reachable).
- `ssh -o BatchMode=yes awake@100.118.109.6 …` gave **`Permission denied
  (publickey,password,keyboard-interactive)`**:
  - the server is `OpenSSH_for_Windows_9.5`;
  - the client offered `~/.ssh/id_ed25519` (ED25519), and the server rejected
    it;
  - the agent had no identities.

The connection was tried four times in all, one of them verbose. On the human's instruction, no
further retries were made and no authentication setting was changed.

**Therefore NOT RUN on Windows:**
- WMI launch;
- the `Get-NetTCPConnection` listener check;
- `CTRL_BREAK_EVENT` graceful stop;
- Conda environment discovery on the laptop;
- CUDA/GPU loading;
- readiness with the real `deployment_id`;
- the ≤ 32-position synthetic smoke;
- **survival after closing the initiating SSH session**;
- the Tailscale Serve actions against the real configuration;
- restoring the initial service and forward state.

Logout and reboot survival are also not claimed: reboot survival is by design
**no**, and logout is not exercised. No mocked result here stands in for any of
these.

**Unblocking (human, on the laptop, elevated PowerShell)**
- The line is this Mac's public key:
  ```powershell
  $k = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIF0xBhIPnBKghwi3NWHxoxoyltGuMmJdPgM9dSwuRtmx flh-mac'
  Add-Content -Path C:\ProgramData\ssh\administrators_authorized_keys -Value $k
  icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"
  ```
- If `awake` is not an administrator, append the same line to
  `C:\Users\awake\.ssh\authorized_keys` instead.
- **Check:** `ssh -o BatchMode=yes awake@100.118.109.6 whoami`.
- **Revoke:** delete the line.

## Local tests (fake platform, no Windows)

**Tools:**
- system `python3` 3.13.5;
- PowerShell **7.4.6**, run from a portable tarball in the session scratchpad.
  Its SHA-256 `a482d668…9072a8` matches the v7.4.6 release notes. It was not
  installed.
- PSScriptAnalyzer 1.23.0, saved into the scratchpad.

| Command | Result |
| --- | --- |
| `python3 -B -m unittest discover -s tools/embedding/e5/windows/operations/tests -p 'test_*.py'` | **9 OK** |
| `pwsh -NoProfile -File tools/embedding/e5/windows/operations/tests/Test-FlhE5Ops.ps1 -Python /opt/anaconda3/bin/python3` | **64 passed, 0 failed** |
| `ast.parse(..., feature_version=(3, 8))` on `runner.py`, the test and the fake | OK |
| Parser on every `.ps1`/`.psm1` (inside the PowerShell tests) | 0 errors |
| PSScriptAnalyzer `PSUseCompatibleSyntax` (target 5.1) on `flh-e5.ps1`, `FlhE5Ops.psm1` and the test | **0** |
| PSScriptAnalyzer `PSUseCompatibleTypes` and `PSUseCompatibleCommands` (Windows 10, PowerShell 5.1 profile) | 0 type findings. The only command findings are `ps` arguments in the POSIX test platform and the test, which never run on Windows |
| Non-ASCII bytes in `.ps1`/`.psm1` | 0. Windows PowerShell 5.1 reads BOM-less files as ANSI |

**What the tests cover.** Each lifecycle action in the PowerShell test is a
separate `pwsh -File flh-e5.ps1` process, like separate SSH commands. The test
paths contain spaces.
- **T1 quoting:** ten awkward values survive a real process creation exactly:
  spaces, embedded `"`, backslash runs before a quote, a trailing backslash, an
  empty string, a tab and `é`. On Unix, .NET parses the argument string with
  the Windows rules.
- **T2 lifecycle:**
  - `start` gives exit 0 with the expected identity, and the model path with
    spaces reaches the service as one argument;
  - a second `start` reuses the run (same PID);
  - `status` gives 0;
  - `stop` is graceful and frees the port;
  - a second `stop` is a no-op (exit 0), and `status` then gives 3;
  - a full second cycle works, and each run keeps `final.json` and its logs.
- **T3 unrelated listener on the port:**
  - `start` gives exit 2 and records nothing;
  - `stop` leaves the listener alone;
  - `status` gives 1;
  - the process is still alive afterwards.
- **T4 another `flh_e5 serve` process:** `start` gives exit 2, and the process
  is untouched.
- **T5 refusals (exit 2), with nothing listening afterwards:**
  - a missing model file or model directory;
  - a missing `python`;
  - an E5 directory without `flh_e5`;
  - a relative path, or a path containing `"`;
  - a port below 1024;
  - `logs -Tail 0`.
- **T6 startup failure:** exit 1 reports the service's exit code 3 and shows
  the stderr tail; the record is archived, and `logs` shows the failure.
- **T7 identity mismatch:** exit 1, and the launched run is stopped with no
  leftover process.
- **T8 forced stop:** a service that ignores signals is terminated after the
  graceful timeout (`stop_requested_forced`).
- **T9 slow readiness:**
  - `start` gives exit 4 and leaves the run running;
  - `status` gives exit 4, "running, model not ready" (process state is
    distinct from model state);
  - `stop` then works.
- **T10 killed supervisor:** `stop` terminates the proven-owned orphan service.
- **T11 PID reuse:** a forged record pointing at an unrelated process is
  reported as "unrelated; not touched", and that process survives.
- **T12 retention:** `-KeepRuns 3` keeps 3 run directories, leaves a
  non-run-ID directory alone, and `logs -List` shows the runs.
- **T13 Tailscale Serve (fake `tailscale`):**
  - enable adds exactly `serve --bg --http=8765 http://127.0.0.1:<port>`;
  - nothing ever runs `reset` or `funnel`;
  - an unrelated `:443` forward is preserved;
  - a second enable reuses the forward;
  - disable removes only the recorded forward;
  - a pre-existing matching forward is reused, and disable never removes it;
  - a port carrying another target is refused, and Funnel is refused;
  - foreground-session configurations parse, and target matching is exact.
- **Runner unittest:**
  - graceful stop with `exit.json` recorded;
  - argv with spaces;
  - environment and `PATH` additions;
  - the startup-failure exit code;
  - forced stop after the graceful timeout, and `force` mode skipping the
    grace;
  - launch failure;
  - an invalid spec, including a BOM-prefixed spec;
  - the service stays up after its launcher exits, and still stops through the
    stop file.

**Bugs the tests found (fixed):**
- `[IO.File]::Replace(..., $null)`: PowerShell passed `""` for `$null`. It now
  uses `[NullString]::Value`.
- `logs -List` failed on an empty run directory (`Measure-Object .Sum` under
  StrictMode).
- The POSIX test platform let the detached supervisor inherit the caller's
  stdout pipe. It is now detached through `sh`. WMI doesn't inherit handles.
- The rest were test-script mistakes: repeated parameters, test order, and a
  runner-test pipe that leaked two fake processes. Those processes were
  stopped and the cleanup made failure-safe.

No test process or listener remains, and no `__pycache__` is left in the
repository.

## What the fakes don't prove

The POSIX platform replaces exactly the Windows-specific parts:
- WMI `Win32_Process.Create` and its escape from the OpenSSH job object;
- `Get-CimInstance Win32_Process`;
- `Get-NetTCPConnection`;
- `CTRL_BREAK_EVENT` delivery in the supervisor's console.

The fake service has no CUDA or model. CUDA working from a WMI-created
(non-interactive) process is **an untested assumption**. If it fails, `start`
reports the startup failure and the stderr log shows why.

## Remaining verification (next session, after key authorization)

1. `e5 check -Cuda`, plus `e5 serve-status` to record the initial Serve state.
2. Record whether an encoder is already running. If one is, the lifecycle
   tests are BLOCKED, not forced.
3. `e5 start`, then `e5 status`. Close that SSH session and run `e5 status`
   from a **new** one: this is the disconnect-survival test.
4. A smoke of at most 32 synthetic positions through `windows\smoke.ps1`
   (2 positions) or equivalent; `e5 logs`.
5. `e5 start` again (idempotent), `e5 stop`, `e5 stop` again, and check that
   the port is free (`nvidia-smi`).
6. An unrelated occupied port (for example `python -m http.server 8765 --bind
   127.0.0.1`), then a missing model path and a startup failure (a wrong
   `-ModelDir`).
7. Restore the initial service and Serve state.
