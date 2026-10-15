# FLH-080 validation: public-demo process and temporary-file leaks

Date: 2026-10-15 (UTC). Host: the NAS (Arch Linux x86_64; `/bin/sh` is bash;
go 1.27.1, node 26.9.0, Python 3.14.7). Working directory:
`/home/worldvanquisher/workspace/flh-nas-claude`. Designated branch:
`fix/flh-080-demo-process-cleanup`, baseline
`263c8b4976060c95bedd95e47d59a1a1f70866f5`. Implementation owner: NAS Claude
Code.

**Scope:** the two defects reported in FLH-078 (D3 and H1). This is not a
general audit.

**Not used:** Git/GitHub, subagents, Windows, Docker, AWS, model calls, vector
regeneration, retrieval changes, public deployment or service installation. No
permanent dependency was installed.

**Outcome:**

| Defect | Status | Baseline | Fixed |
| --- | --- | --- | --- |
| D3 (untracked server after a pid-file failure) | **Fixed** | 30 PASS / 15 FAIL, 5 leaked servers | 45 PASS / 0 FAIL, no leak |
| H1 (`/tmp/flh077-unit-*` leak) | **Fixed** | 5 PASS / 5 FAIL | 15 PASS / 0 FAIL across the success, failing-check and SIGTERM paths |

## Changed files

| File | Change | SHA-256 after |
| --- | --- | --- |
| `scripts/demo/flh076/deploy/ctl.sh` | D3 fix | `1cb5746ab4188296e6ec92db559c6c5d3c503132bdbd1695a9fe67acc734ef9b` |
| `scripts/validation/flh077/accept.sh` | H1 fix | `aae1c635ff8c67c9bbac49ada6f408f2a7adb514f0c372676c95dfc12d8827bc` |
| `scripts/validation/flh080/ctl_pidfile_regression.py` | New D3 regression | `cfe5eccb740ee9d942a5686dd2c1c07a5c794bec3b1dcd52e8d8b61e74876e72` |
| `scripts/validation/flh080/accept_tmp_regression.py` | New H1 regression | `7c6310f82a685b13f8ac543626c46e72d01a2e52c07518f5bf94486fa07d26fd` |
| `docs/PUBLIC_DEMO.md` | The D3 workaround paragraph replaced by the new behaviour | — |
| `docs/validation/FLH-080-demo-process-cleanup.md` | This report | — |

`scripts/validation/flh077/ctl_regression.sh` is **unchanged**. It passed as is
against the fixed `ctl.sh`, and the new D3 cases live in `flh080/`.

Baseline copies, taken from the working tree before editing and used for the
before/after runs, are in the session scratchpad:
- `ctl.sh`: `74ec63d4a94e6160e4883e1aa818d76c65f8cb9608a403c499203664b12fe5b0`
- `accept.sh`: `e88dcd162098ea51a72f5fca297a09c343549877deffb4b8cda37b3c23e7197c`

## D3: untracked server after a pid-file failure

**Cause:** `start` launched the server, then ran `echo "$launched" >
"$PIDFILE"` under `set -e`. A failed write (pid path is a directory, unwritable
directory, quota, ENOSPC) exited 1. The launched server kept running with no
pid file, so `stop` could not find it.

**Fix:** `scripts/demo/flh076/deploy/ctl.sh`, `start` only. `status`/`stop` are
unchanged.

1. **Before launch:**
   - refuse if the pid path exists and is not a regular file, or is a symlink;
   - write a temporary `RUN/.flh-public-demo.pid.<ctl pid>`; refuse if that
     fails.

   Both refusals exit 1 with "start refused … nothing launched".
2. **Cleanup trap:** an `EXIT` trap is installed, and HUP/INT/TERM are turned
   into exits so the trap runs. Until `start` reports `started`, any exit stops
   the launched process and removes only this start's bookkeeping. The pid file
   is removed only if it holds this start's pid.
3. **After launch:**
   - write the pid to the temporary file, `mv -f` it into place, and require a
     regular, non-symlink pid file whose content equals the launched pid;
   - on any failure, stop the launched process and exit 1 with "could not
     record pid …; stopped the launched process".
4. **How the launched process is identified:**
   - **`live_child`:** the process's parent is this shell (`ppid == $$`) and
     it is not a zombie. Because `start` has not reaped it, its pid cannot have
     been reused, and this holds before or after the server's `exec`.
   - **`stop_child`:**
     - sends SIGTERM and waits up to 5 s;
     - escalates to SIGKILL only for that same live child;
     - reaps it with `wait`;
     - reports if it did not stop.
5. **Unchanged:**
   - `stop` and `status` (command-line identity check of the recorded pid);
   - readiness bounds and the timeout path (`stop_launched`);
   - the occupied-port rules.

Nothing signals by port, process name or an unverified stale pid.

**Remaining window:** SIGKILL of `ctl.sh` between the launch and the rename can
still leave the server untracked, since no trap can run. That window is
documented in `docs/PUBLIC_DEMO.md`.

### D3 regression: `scripts/validation/flh080/ctl_pidfile_regression.py`

```sh
python3 -B scripts/validation/flh080/ctl_pidfile_regression.py --work "/abs/new/work dir" [--ctl PATH] [--port-base 19880]
```

**Setup:**
- builds the host server and `prepare`;
- lays out a minimal package around the `ctl.sh` under test in a path with
  spaces: the real mechanical artifact, a tiny web directory, and a
  `bin/server` wrapper that logs each launch and then execs the real server or
  a never-ready stand-in with the same argv.

**Detecting leaks:** a leak is any process whose argv holds
`-public-demo-artifact <this run's unique package>/artifact`, read from `/proc`.
A leaked server is stopped by the test only after that exact argv match and a
kernel start time after the run began; this is never done by port or name.

| Case | Injection | Required |
| --- | --- | --- |
| `prelaunch-dir` | Pid path is a directory (FLH-078 reproducer) | Exit 1 and **nothing launched** |
| `prelaunch-ro` | Runtime directory mode 555 (an existing log file stays writable) | Exit 1 and **nothing launched** (NOT RUN as root) |
| `postlaunch-mv-fail` | PATH shim: ctl.sh's `mv` exits 1 with "No space left on device". The server's own `env -i` PATH is unaffected | Server launched, exit 1, "could not record pid" |
| `postlaunch-mv-noop` | PATH shim: `mv` exits 0 without renaming, so the read-back fails | As above |
| `interrupt-term` / `interrupt-int` | SIGTERM / SIGINT to `ctl.sh` (its own process only) while it waits for a never-ready process | Exit nonzero |
| `control-ok` | none | Start, repeated start (same pid), stop |

After every case:
- no task server is left running;
- the port is closed;
- no temporary pid file and (except `prelaunch-dir`) no pid file is left.

**Results** (`~/flh080/d3 baseline/`, `~/flh080/d3 fixed/`):

| `ctl.sh` | Result | Failed checks |
| --- | --- | --- |
| Baseline `74ec63d4…` | **30 PASS / 15 FAIL**, exit 1; 5 leaked servers stopped by the test | See below |
| Fixed `1cb5746a…` | **45 PASS / 0 FAIL**, exit 0; 0 leaks; 2.8 s | — |

Baseline failures:
- `prelaunch-dir`: server left running; this is the original defect.
- `prelaunch-ro`: server left running. The quota/permission case is
  reproduced: the existing log stays writable while the pid write fails.
- Both `postlaunch-*` cases: the baseline never notices; it reports `started`
  and leaves the pid file and server.
- `interrupt-term`: server and pid file left.
- `interrupt-int`: pid file left.

Messages from the fixed version:
- `start refused: …/flh-public-demo.pid exists and is not a regular file; nothing launched`
- `start refused: cannot write pid bookkeeping in …/run read only; nothing launched`
- `start failed: could not record pid 3673991 in …/flh-public-demo.pid; stopped the launched process`

## H1: temporary binary leak

**Cause:** `accept.sh` step 6 created `mktemp -d /tmp/flh077-unit-XXXXXX` (a
19 MB server copy plus the unit file) and never removed it.

**Fix** (`scripts/validation/flh077/accept.sh`):
- **Tracking:** the directory is held in `UNITDIR`. `remove_unitdir` removes
  only that exact path, and only if it matches `/tmp/flh077-unit-??????`, is a
  directory and is not a symlink.
- **When it is removed:** right after `systemd-analyze verify` (recorded as the
  check "temporary unit directory removed"), and from an `EXIT` trap, with
  HUP/INT/TERM mapped to exits 129/130/143.
- **mktemp/cp failure:** reported as a FAIL. Previously the unit file would
  have been written to `/`.
- **Never touched:** other `/tmp/flh077-unit-*` directories, `WORK`, and
  evidence. Nothing can clean up after SIGKILL or power loss.

### H1 regression: `scripts/validation/flh080/accept_tmp_regression.py`

```sh
python3 -B scripts/validation/flh080/accept_tmp_regression.py --src /abs/source/tree \
  --work "/abs/new/work dir" [--accept PATH] [--modes success,failure,interrupt] --revision LABEL
```

**How it runs:**
- each mode is one full `accept.sh` run;
- a `systemd-analyze` PATH shim records the directory it was handed, then
  passes through (success), exits 1 (failing check), or SIGTERMs its parent
  `accept.sh` (catchable interruption);
- it snapshots `/tmp/flh077-unit-*` (inode and mtime) before and after.

It removes nothing.

**Results:**

| `accept.sh` | Mode | Exit | Directory | Verdict |
| --- | --- | --- | --- | --- |
| Baseline `e88dcd16…` | success | 0 | `wC32c6` **left** | FAIL |
| Baseline | interrupt | killed by SIGTERM (no trap) | `qvyIDq` **left** | FAIL (exit −15, not 143) |
| Fixed `aae1c635…` | success | 0 | `RqVsxc` removed | PASS |
| Fixed | failure | 1 | `ksoTic` removed | PASS |
| Fixed | interrupt | 143 | `rjvDe4` removed | PASS |

In every run, every pre-existing directory was untouched.

- **Baseline totals:** 5 PASS / 5 FAIL.
- **Fixed totals:** 15 PASS / 0 FAIL, 34 s for the three runs.
- **Fixed success run as native Linux package acceptance:** `accept.sh`
  reported **85 PASS / 0 FAIL / 1 BLOCKED**. The new check "temporary unit
  directory removed" is included. **BLOCKED:** `nginx -t` (nginx not
  installed).

## Other verification (all local on the NAS)

All Linux package runs used the task-local source copy `~/flh080/src`, which
holds this working tree with the fixes and no `.git` or `captures/`, plus
`npm ci` run in its `web/`. Every package carries the revision label
`263c8b4976060c95bedd95e47d59a1a1f70866f5+flh080-uncommitted`. They are built
from **uncommitted** fixes on that baseline and are not release candidates.
The FLH-078 candidate and its evidence (`~/flh078/`, `/tmp/flh078-*`) were
not touched.

| Command | Result |
| --- | --- |
| `bash scripts/validation/flh077/ctl_regression.sh "~/flh080/ctl regression" 19840` (from `~/flh080/src`) | **35 PASS / 0 FAIL**: occupant cases (tool and log fallback, via `ss`), immediate failure, start/repeated start/status/stop, slow readiness, bounded never-ready (only the launched process stopped, unrelated process untouched), invalid `READY_TIMEOUT` |
| `bash scripts/demo/flh076/test_package_checksums.sh "~/flh080/checksum tests" ARTIFACT` | **20 PASS**, `CHECKSUM TESTS PASSED`; host reported `sha256sum=1 shasum=1` (this shell's PATH includes `/usr/bin/core_perl`) |
| `accept.sh` via the H1 regression (fixed, success mode) | 85 PASS / 0 FAIL / 1 BLOCKED (nginx) |
| `python3 -B -m unittest discover -s scripts/validation/flh079 -p 'test_*.py'` | OK |
| `python3 -B scripts/validation/flh079/run.py --work "~/flh080/flh079 accept"` | OVERALL PASS, 210/0; browser **NOT RUN** (no Chrome/Chromium on the NAS) |
| `python3 -B scripts/validation/flh079/failure_probe.py --work "~/flh080/flh079 probe"` | FAILURE PROBE PASS |
| `sh -n ctl.sh`, `bash -n accept.sh`, `py_compile` of the new scripts | OK |

**Not run or BLOCKED:**

| Item | Status | Reason |
| --- | --- | --- |
| nginx | **BLOCKED** | Not installed |
| Real-browser checks | **NOT RUN** | No browser on the NAS |
| `ctl.sh` under dash | **NOT RUN** | No dash/ash/busybox available. `/bin/sh` here is bash, which runs `#!/bin/sh` in POSIX mode. The new code uses only POSIX constructs (`trap … EXIT`, `${x##*/}`, `awk -v`, `ps -o ppid= -o stat=`) |
| macOS | **NOT RUN** | — |
| GitHub Actions | **NOT RUN** | — |

## Cleanup evidence

- **After all runs:**
  - no process with `-public-demo-artifact` or `flh080` in its command line;
  - ports 19840–19887, 19771/19791/19811, 18990 and 18992 closed;
  - no `.flh-public-demo.pid.*` file under `~/flh080`.
- **Servers leaked by the baseline D3 run:** all 5 were stopped by that test,
  through the verified argv and start time.
- **`/tmp/flh077-unit-*`:**
  - the baseline H1 run leaked `wC32c6` and `qvyIDq`. Each was 19 MB and was
    created by this task's own reproduction; their exact paths are recorded in
    `~/flh080/h1 baseline/unitdir-*.txt`. Both were removed by exact path
    afterwards;
  - **left in place, as instructed:** the pre-existing `vCz1XT` (FLH-077) and
    `vuS4ZN` (FLH-078).
- **Evidence kept:** `~/flh080/` (about 3.3 GB, mostly unpacked test packages):
  `d3 baseline`, `d3 fixed`, `h1 baseline`, `h1 fixed`, `ctl regression`,
  `checksum tests`, `flh079 accept`, `flh079 probe`, `src`, `npm-cache`, and
  the `*.out` logs. The human owner may delete it.

## Reproduction

From the repository root on Linux:

```sh
# D3 (2–35 s)
python3 -B scripts/validation/flh080/ctl_pidfile_regression.py --work "$HOME/flh080-repro/d3 fixed"
python3 -B scripts/validation/flh080/ctl_pidfile_regression.py --work "$HOME/flh080-repro/d3 old" --ctl /path/to/baseline/ctl.sh

# H1 (about 35 s for three modes on the NAS). Needs a source copy with web/node_modules:
mkdir -p "$HOME/flh080-repro/src"
tar --exclude=./.git --exclude=./web/node_modules -cf - . | tar -xf - -C "$HOME/flh080-repro/src"
(cd "$HOME/flh080-repro/src/web" && npm ci)
python3 -B scripts/validation/flh080/accept_tmp_regression.py --src "$HOME/flh080-repro/src" \
  --work "$HOME/flh080-repro/h1" --revision "<baseline>+flh080-uncommitted"
```

**A baseline H1 run leaks one 19 MB directory per mode, by design of the
reproduction.** Remove it by the exact path recorded in `WORK/unitdir-*.txt`.

## Remaining risks

- **D3:**
  - SIGKILL of `ctl.sh` between launch and rename can still leave an untracked
    server. Recovery is documented.
- **H1:** SIGKILL or power loss during step 6 leaves the directory, since no
  trap can run. A tiny window also exists between `mktemp` creating the
  directory and the assignment to `UNITDIR`.
- **Interrupted `accept.sh`:** this task does not stop the harness's own
  background helpers (`sleep`/occupant listeners) or a server started through
  `ctl.sh` if an interruption happens before step 6. That is outside H1.
- **`stop` with a pid path that is a directory** exits 1 (`rm` fails). That
  behaviour is unchanged and outside this task.
- **Coverage gaps:** dash execution, macOS and GitHub Actions were not run.
