# FLH-077 validation: Linux public-demo package acceptance

Date: 2026-10-15 (UTC). Local working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64). Target: the NAS
checkout `~/workspace/flh-nas-codex` at `100.98.239.98`. Source-revision label
supplied by the human workflow: `1dc491141de7ae2aab5d5b2c941b8f37cd38d408`.

**Not used:** Git/GitHub, subagents, Docker, Windows changes, a GPU, AWS, paid
calls or model downloads.

**Not touched:** remote source, NAS services and FLH evidence.

**Current outcome:** Linux acceptance on the NAS **ran** (2026-10-15)
([NAS Linux acceptance](#nas-linux-acceptance-third-part)):
- with the D1-fixed `ctl.sh` overlaid: **84 PASS / 0 FAIL / 1 BLOCKED**
  (nginx), and the D1 regression suite **35/0**;
- the integrated checkout as shipped **FAILS** packaging on Linux (**D2**,
  `shasum` missing) and still has D1;
- the NAS checkout is **stale**: a human sync is required
  ([below](#nas-checkout-sync-required)).

The sections that follow, up to that one, are kept as history.

**Earlier outcome: Linux package acceptance BLOCKED (no SSH access to the NAS).** A
reproducible harness (`scripts/validation/flh077/accept.sh`) is delivered and
was debugged in a labelled macOS dry run. That dry run found one controller
defect (D1), which is **fixed** in the second part of this task
([D1 fix](#d1-fix-second-part-of-flh-077)), with focused regression tests.

## NAS access: BLOCKED

```sh
ssh -o BatchMode=yes -o ConnectTimeout=15 worldvanquisher@100.98.239.98 '…'
# worldvanquisher@100.98.239.98: Permission denied (publickey,password).
```

- **Diagnosis:** one verbose attempt.
  - The server is `OpenSSH_10.5`, accepting `publickey,password`.
  - The client's agent held one key, which it offered: `~/.ssh/id_ed25519`,
    ED25519 `SHA256:8VeQZisfGuJYwBF0XrXe402azuzP7U+CWbt7kwX6vhY`.
  - The server refused it.
- **Tailscale:** shows `nas-wv 100.98.239.98 linux active`, so the host is
  reachable; it is authentication that fails.
- **What this means:** no authorized Mac→NAS SSH connection exists. Earlier
  NAS work ran inside a NAS-local agent.
- **Not done:** no retries, and no authentication settings were changed.
- **Therefore NOT RUN:** remote checkout verification (FLH-076 presence),
  building and packaging on Linux, executing the packaged native binary, and
  every NAS check below.

**To unblock (human, on the NAS):** append this Mac's *public* key line to
`~worldvanquisher/.ssh/authorized_keys` (mode 600, directory 700):

```text
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIF0xBhIPnBKghwi3NWHxoxoyltGuMmJdPgM9dSwuRtmx s789liu@uwaterloo.ca
```

- **Check:** `ssh -o BatchMode=yes worldvanquisher@100.98.239.98 'uname -m'`.
- **Revoke:** delete the line.

**Alternative:** run the harness directly in a NAS shell. It needs no SSH.

## Harness (delivered; run on the NAS)

```sh
cd ~/workspace/flh-nas-codex
test -f scripts/demo/flh076/package.sh && grep -q flh076_domain_fingerprint_v3 internal/publicdemo/database.go   # FLH-076 present
(cd web && npm ci)    # only if web/node_modules is absent; the harness reports BLOCKED rather than installing
bash scripts/validation/flh077/accept.sh "/tmp/flh077 nas run" 19770
# results: "/tmp/flh077 nas run/results.tsv", summary.txt; exit 0 only if no FAIL
```

**What it does, using the existing tooling and loopback ports only:**
1. **Prerequisites:** `go`, `python3`, `curl`, `tar` and `web/node_modules`;
   a missing one is BLOCKED and stops the run, with nothing installed.
2. **Build and package:** a mechanical artifact, then `package.sh` with the
   supplied revision label. It expects a `…-BLOCKED` tarball and verifies the
   tarball checksum.
3. **Unpack** into `…/install root with spaces/`, then check:
   - the exact top-level layout, no symlinks and `SHA256SUMS`;
   - the `RELEASE.json` revision label and `BLOCKED` status;
   - the ELF machine of both binaries (x86_64, aarch64);
   - that the host matches a packaged binary, and that the **packaged native**
     `flh-server` executes.
4. **Release and controller:**
   - `validate-release.sh` exits 3 (mechanical refusal);
   - a start without `ALLOW_MECHANICAL` is refused, with the reason logged;
   - start, repeated start (same pid), status, the process command line being
     the packaged binary, stop, repeated stop, status after stop, restart and
     final stop;
   - a runtime directory with spaces;
   - every controller call runs under a hard timeout in its own session.
5. **HTTP:**
   - static index and JS bytes equal the package files;
   - allowed API routes return 200;
   - denied routes return 404: `/favicon.ico`, `artifact/demo.db`,
     `RELEASE.json`, `/assets/`, write-surface and free-text semantic/hybrid
     search;
   - POST/PUT/PATCH/DELETE return 405; `q=` on a preset route returns 400; an
     unknown preset returns 404;
   - provenance: the original synthetic question, and the fixture extractor;
   - keyword, semantic and hybrid preset responses;
   - the same four responses are byte-identical after restart, and the
     artifact identity and counters persist;
   - the package tree hash is unchanged by every run.
6. **Isolation:**
   - an unrelated process (`sleep 3600`) named in a stale pid file is never
     signalled by `status` or `stop`;
   - a dead pid gives status 3;
   - a non-HTTP listener occupying the port stays alive, and `start` must fail
     promptly;
   - a corrupted artifact copy fails at startup, with the reason logged.
7. **Tampering** (package copies): an edited file, an added symlink, an extra
   file and a relabelled `RELEASE.json` each make `validate-release.sh` exit 1.
8. **Templates** (installed tools only; nothing installed, enabled or
   reloaded):
   - `systemd-analyze verify` on a copy of the unit with task-local paths;
   - `nginx -t -p <task dir>` on the server block, included in a task-local
     main config with a throwaway self-signed certificate and loopback
     listeners;
   - `sh -n ctl.sh`.

   An absent tool is BLOCKED.
9. **Cleanup:** the owned loopback ports are confirmed closed. Owned helpers
   are killed explicitly. Logs, packages and copies are retained.

## macOS dry run: harness debugging only, NOT Linux evidence

```sh
FLH077_HOST_SUBSTITUTE=1 bash scripts/validation/flh077/accept.sh "/tmp/flh077 dryrun3" 19810
```

The run is labelled `NOTE host-substitute dry run … NOT Linux package
evidence`. The packaged Linux binaries cannot run on macOS, so host builds of
the same source were substituted. The package itself was still built from the
local source and unpacked into a path with spaces.

**Final result: 81 PASS / 1 FAIL / 1 BLOCKED.**
- **FAIL:** D1, below.
- **BLOCKED:** `systemd-analyze verify` (systemd is not on macOS).
- **`nginx -t` PASS** with the Mac's existing Homebrew nginx 1.29.2, in test
  mode only, against the task-local config. Its running service (`nginx:
  master`, pre-existing) was not touched. This is nginx syntax evidence on
  macOS, not on the NAS.

**Harness bugs found and fixed during the dry runs:**
- The process identity check split the binary path at a space.
- The nginx test config's paths, and the substituted certificate paths, were
  unquoted in a path with spaces.
- The first run's "unrelated process not signalled" and "listener untouched"
  failures were **not** signals. The occupied-port `start` hung (D1) until the
  300-second helpers exited by themselves. I reproduced this directly: with a
  pid file naming an unrelated live `sleep`, `ctl.sh status` exits 3 and
  `ctl.sh stop` prints `stopped`, and the `sleep` stays alive. The helpers now
  live for one hour, every controller call is bounded, and a hang is reported
  as a precise FAIL.
- The hung test processes (bash, sleep, python listener, `ctl.sh`, curl) were
  owned by me. They were stopped by PID after checking their command lines.

**Passing in the dry run** (host-substituted binaries):
- **Package:** layout, checksums, revision label, BLOCKED status, ELF
  machines.
- **Controller:**
  - mechanical refusal (`validate-release.sh` exit 3, and start refused
    without `ALLOW_MECHANICAL`);
  - start, repeat, status, stop, repeat stop and restart;
  - stale, dead and unrelated pid files, with no unrelated process signalled;
  - corrupted-artifact startup failure;
  - the occupying listener still alive at the end.
- **HTTP:** every allowed, denied and preset check, provenance, and identical
  results and identity after restart.
- **Package:** bytes unchanged; the 4 tamper refusals; `ctl.sh` syntax; all
  ports closed.

## Defects

**D1: `ctl.sh start` hangs when the port is held by a non-HTTP listener.**
Medium; operational.
- **Expected:** `start` fails promptly. The server itself fails at once
  (`bind: address already in use`, logged).
- **Actual:** `ctl.sh` polls `curl -fsS http://127.0.0.1:$PORT/readyz` with
  **no timeout**. When the occupant accepts connections but never answers,
  that `curl` blocks indefinitely, so `start` never returns. An HTTP occupant
  would answer, so it would not hang. It is not a signalling defect: `ctl.sh`
  never signals that occupant.
- **Location:** `scripts/demo/flh076/deploy/ctl.sh`, in the `start` readiness
  loop. Ownership was later extended to FLH-077, which fixed it (below).
- **Shortest reproducer** (any host; uses a BLOCKED package `PKG` and a host
  or packaged server):

  ```sh
  python3 -c 'import socket,time; s=socket.socket(); s.bind(("127.0.0.1",19792)); s.listen(); time.sleep(3600)' &
  PORT=19792 ALLOW_MECHANICAL=1 "$PKG/deploy/ctl.sh" start /tmp/flh077-occ   # never returns
  ```

- **Mismatch between the documented release status and the controller:**
  none found in the dry run. The README says not to publish a BLOCKED package.
  `ctl.sh` refuses to start one unless `ALLOW_MECHANICAL=1` is set, which is
  documented as "local smoke of a BLOCKED package only".

## Status per requested area

| Area | NAS (Linux) | macOS dry run |
| --- | --- | --- |
| 1. Build/package with the revision label | **FAIL as shipped (D2: `shasum` missing on Linux)**; PASS with a task-local `shasum`→`sha256sum` test shim | PASS |
| 2. Packaged native Linux binary: architecture, checksums, layout | **PASS** (x86_64 binary executed; ELF machines, `SHA256SUMS`, layout, revision label) | Layout/checksums/ELF headers PASS; execution not possible on macOS |
| 3. Controller lifecycle, repeats, stale pid, unrelated process, spaces | Integrated `ctl.sh`: PASS except **D1 FAIL** (reproduced on Linux). Fixed `ctl.sh` (overlay): **PASS**, `ctl_regression.sh` **35/0** | First run: D1 FAIL. After the fix: PASS (82/0/1; 35/0) |
| 4. Static, presets, provenance, denied requests, bytes, restart identity | **PASS** | PASS |
| 5. Mechanical release refusal, tampering | **PASS** (exit 3; the 4 tamperings exit 1) | PASS |
| 6. systemd / nginx template syntax | systemd-analyze verify **PASS**; nginx **BLOCKED** (not installed; not installed by me) | systemd BLOCKED; nginx PASS (macOS nginx 1.29.2) |

## E5 readiness (requested after FLH-077; FLH-076 not resumed)

- **Prior FLH-076 state:** no work directory (`~/flh076` absent), so 0
  positions and 0 POSTs used. One readiness probe was used during FLH-076, and
  it timed out.
- **Tailscale now:** `worldvanquisher 100.118.109.6 windows`, online, with
  the earlier "offline" note gone.
- **One bounded probe** at 2026-10-15T02:06:30Z:
  - `GET http://100.118.109.6:8765/readyz` → `http=000`, 5.0 s timeout;
  - `GET /manifest` → `http=000`.
- **Result: E5 NOT READY.** Windows is online, but the encoder (or its port
  forward) is not answering. Nothing was sent, and no retry was made.
- The FLH-076 real-artifact preparation waits for an explicit resume. Its
  `embed` command makes its own built-in readiness probe, limited to 2 per
  work directory.

## Evidence (outside the repository)

- **Dry runs:** `/tmp/flh077 dryrun/` (first), `/tmp/flh077 dryrun2/`,
  `/tmp/flh077 dryrun3/` (final). Each holds `results.tsv`, `summary.txt`,
  the package and its tarball, logs, and the template test configs.
- **D1 reproduction:** `/tmp/flh077-occ/`.
- **E5 probe:** this report; the probe wrote no response files.

## D1 fix (second part of FLH-077)

The human owner extended ownership to `scripts/demo/flh076/deploy/ctl.sh` and
its focused tests. NAS access is still BLOCKED, so everything below ran
locally on macOS, with host builds of the same source. It is not Linux
package evidence.

**1. The original hang, reproduced before editing.** Using the unchanged
`ctl.sh`, packaged from this source, and a Python listener on
`127.0.0.1:19830` that accepts but never answers: `ctl.sh start` was
**still running after 20 s** and was stopped by its own outer session. The
occupant was alive, and the server log showed `bind: address already in
use`. Evidence: `/tmp/flh077-d1-before/`.

**2. The fix (`ctl.sh start`).**
- **Bounded requests:** every readiness request uses `curl --max-time 2`
  (and `status` uses `--max-time 5`).
- **Bounded total wait:** `READY_TIMEOUT`, default 30 s. It must be whole
  seconds, otherwise the script exits 2 before launching anything. The wait
  is at least `READY_TIMEOUT` and under one second more.
- **Exit detection:** the launched pid is checked on every poll. If it has
  exited, start fails at once ("exited during startup") and the pid file is
  removed.
- **Ready means all of the following:**
  - the launched pid is alive, and its command line is this package's
    (`-public-demo-artifact <root>/artifact`);
  - `GET /knowledge-library/demo` reports this package's artifact manifest
    SHA-256;
  - the launched pid owns the listening socket. This uses `lsof` or `ss` when
    available. Otherwise, the server's own `listening on 127.0.0.1:PORT` log
    line must appear since this launch, with no `server error` after a 0.5 s
    settle.

  So an unrelated HTTP service, even one imitating the demo's identity
  answer, is never reported as ready.
- **On timeout:** stop only the launched pid, after re-checking its command
  line (TERM, then KILL after 5 s), remove the pid file and exit 1.
- **Never signalled:** a process occupying the port, or a pid whose command
  line is not this package's.
- **Unchanged:** `stop` and `status` keep their ownership checks.

**3. Focused regression tests** (`scripts/validation/flh077/ctl_regression.sh`).
They build a BLOCKED package that carries the `ctl.sh` under test. Every call
runs under an outer hard timeout in its own session. Checks 1–2 and 4 run in
two ownership modes:
- **`tool`:** `lsof` available;
- **`nolsof`:** `PATH` without `/usr/sbin`, exercising the log fallback.

```sh
bash scripts/validation/flh077/ctl_regression.sh "/tmp/flh077 ctl regression2" 19840   # exit 0
```

| Case | Result with the fixed `ctl.sh` |
| --- | --- |
| Non-HTTP occupant (D1), both modes | start exits 1 within 2 s; occupant alive; no pid file left |
| HTTP occupant imitating the identity answer, both modes | not reported ready (exit 1, within 1 s); occupant alive |
| Immediate startup failure (corrupted artifact) | exit 1 within 1 s, "exited during startup" |
| Successful start, repeated start, status, stop, both modes | 0; same pid on repeat; status 0; stop 0 and the process gone |
| Slow readiness (ready after about 2 s, `READY_TIMEOUT=15`) | succeeds after waiting ≥ 2 s |
| Never ready (`READY_TIMEOUT=3`) | exit 1 in 3–4 s, "not ready within 3s; stopped the launched process only"; launched process stopped; an unrelated `sleep 3600` alive; pid file removed |
| Invalid `READY_TIMEOUT` | exit 2, nothing launched |

**Final run: 35 PASS / 0 FAIL**, with no leftover processes or listeners.

**The tests detect D1.** The same suite was run against the **original**
`ctl.sh`: it was temporarily swapped back, then restored and checked
byte-identical with `cmp`. Result: **23 PASS / 12 FAIL**.
- The non-HTTP occupant hung until the 60 s outer bound, in both modes.
- Immediate failure and never-ready took 11 s, with no timeout bound or
  message.
- Stale pid files were left behind, and `READY_TIMEOUT` was not validated.
- The old controller also **leaked** the never-ready launched process. That
  test process was stopped afterwards by its verified command line.

**Test-harness corrections made while writing these tests:**
- The timer's capture mixed in `ctl.sh` stdout.
- A "never-ready" fake that `exec sleep` dropped the demo arguments from its
  command line. `ctl.sh` therefore correctly refused to stop it, leaving one
  orphaned test `sleep`, which I stopped after identifying it by its start
  time.
- The fake now keeps its arguments, as a real server does.

**4. Existing harnesses, run unchanged:**
- `scripts/validation/flh077/accept.sh`, as a macOS dry run
  (`/tmp/flh077 dryrun4/`): **82 PASS / 0 FAIL / 1 BLOCKED**. The previous
  FAIL ("start on an occupied port fails promptly") now passes. The
  unrelated process was not signalled, and the occupant stayed alive.
  `systemd-analyze` is still BLOCKED on macOS.
- `scripts/demo/flh076/smoke_package.sh`, on the package from that run:
  `PACKAGE SMOKE PASSED`.

**Updated status:** D1 is **FIXED and locally verified**. Linux package
acceptance on the NAS remains **BLOCKED** (SSH): run `accept.sh` and
`ctl_regression.sh` on the NAS to obtain Linux evidence. On Linux, both use
the packaged native binary.

## NAS Linux acceptance (third part)

**Access:** `ssh -o BatchMode=yes worldvanquisher@100.98.239.98` now works.
The host is `x86_64`, Linux, Go 1.27.1. These tools are present: `python3`,
`curl`, `tar`, `ss`, `systemd-analyze`, `openssl`, and `web/node_modules`
(vite). These are absent: `nginx`, `lsof`, `shasum`.

**Remote checkout** `~/workspace/flh-nas-codex`, inspected read-only and never
modified:
- **Contains FLH-076:** `flh076_domain_fingerprint_v3`, and `package.sh`
  identical to the local one (SHA-256 `8e08a736…`).
- **Does not contain FLH-077:** no `scripts/validation/flh077/`, and the
  pre-fix `ctl.sh` (SHA-256 `1e9e2b06…`; the fixed one is `74ec63d4…`).
  Rechecked on 2026-10-15 after PR #104: **unchanged (stale)**.

**Harness copies:** in `/tmp/flh077-harness/` on the NAS. `accept.sh` there
is `e88dcd16…`, byte-identical to the repository version in this change,
which includes the systemd-check fix below. They were run from the checkout
root and write only to their work directories under `/tmp`.

| Run | Source | Result |
| --- | --- | --- |
| A (`/tmp/flh077 nas A`) | Integrated checkout, label `1dc49114…`, as is | **FAIL at packaging:** `package.sh` exit 127, `line 103: shasum: command not found` (D2). Nothing further ran |
| A2 (`/tmp/flh077 nas A2`) | Integrated checkout plus a task-local test shim `/tmp/flh077-shim/shasum` (`shasum -a 256 ARGS` → `sha256sum ARGS`) first in `PATH` | **82 PASS / 2 FAIL / 1 BLOCKED.** FAIL: **D1 reproduced on Linux** with the packaged native binary ("ctl.sh start hung >30 s"), and `systemd-analyze verify`, which was a harness bug (fixed below). BLOCKED: nginx |
| B, regression (`/tmp/flh077 nas B ctl`) | `/tmp/flh077-overlay-src`: a copy of the checkout without `.git`. It differs only by the **fixed `ctl.sh`** and the harness directory (`diff -rq`), and uses the shim | **35 PASS / 0 FAIL** (`ss` ownership) |
| B, acceptance (`/tmp/flh077 nas B`) | Same overlay, label `1dc49114…+flh077-ctl-overlay` | **84 PASS / 0 FAIL / 1 BLOCKED** (nginx) |

**Linux evidence from run B** (the packaged native binary,
`bin/linux-amd64/flh-server`):
- **Package and binary:**
  - ELF machines x86_64 and aarch64, matching the host; the binary executes;
  - layout, no symlinks, `SHA256SUMS`, revision label, `BLOCKED` status.
- **Release and controller:**
  - `validate-release.sh` exits 3, and start without `ALLOW_MECHANICAL` is
    refused;
  - start, repeated start (same pid, the process is the packaged binary),
    status, stop, repeated stop and restart;
  - a runtime path with spaces;
  - the occupied port fails promptly with the bind error logged;
  - stale and dead pid files; an unrelated `sleep` never signalled;
  - the corrupted-artifact startup failure.
- **HTTP:** static index and JS bytes, allowed routes 200, denied 404, writes
  405, `q=` 400, unknown preset 404, provenance, and byte-identical results
  and identity after restart.
- **Package and teardown:** bytes unchanged; the 4 tamper refusals;
  `systemd-analyze verify` on the unit template; `sh -n ctl.sh`; owned ports
  closed; no leftover processes.

**Harness fix (`accept.sh`):** the systemd check substituted a path containing
spaces into `ExecStart`, which unit files split, and used `User=nobody`, which
systemd flags. The test copy now lives in a space-free task-local directory
and uses the current user. The unit template itself was unchanged and
verified clean.

**D2: `package.sh` requires `shasum`, which Linux hosts may lack.** Medium;
release tooling.
- **Expected:** packaging works on the Linux target.
- **Actual:** exit 127 at `SHA256SUMS`, `line 103: shasum: command not found`.
  The tarball `.sha256` step would follow.
- **Location:** `scripts/demo/flh076/package.sh` (FLH-076; not owned in this
  task and not modified). `validate-release.sh`, `ctl.sh` and `accept.sh`
  already prefer `sha256sum`.
- **Shortest reproducer:** on the NAS, `bash scripts/demo/flh076/package.sh
  --artifact A --revision R --label x --out /tmp/out` with no `shasum` in
  `PATH`.
- **Suggested fix:** use `sha256sum` when present.
- **Workaround used:** the test shim above, labelled. It changes no source.

**Linux limits:**
- The `nolsof` regression mode still finds `ss` in `/usr/bin` on this host,
  so the log-only ownership fallback was exercised on macOS only.
- `nginx -t` is BLOCKED on the NAS. Its macOS result is syntax evidence only.

**Retained on the NAS** (logs and packages kept): `/tmp/flh077 nas A`, `A2`,
`B ctl`, `B`, `/tmp/flh077-overlay-src`, `/tmp/flh077-shim`,
`/tmp/flh077-harness`. No service was installed, enabled or reloaded.

### NAS checkout sync required

`~/workspace/flh-nas-codex` predates FLH-077. Its `ctl.sh` is `1e9e2b06…`
(pre-fix), and it has no `scripts/validation/flh077/`. No Git was run here.

**Human step:** bring the checkout to the integrated revision that contains
PR #104, then confirm:

```sh
cd ~/workspace/flh-nas-codex && sha256sum scripts/demo/flh076/deploy/ctl.sh && ls scripts/validation/flh077/
# ctl.sh must be 74ec63d4a94e6160e4883e1aa818d76c65f8cb9608a403c499203664b12fe5b0 (or a later reviewed fix)
```

**Afterwards (no overlay needed):**

```sh
PATH=/tmp/flh077-shim:$PATH bash scripts/validation/flh077/ctl_regression.sh "/tmp/flh077 nas C ctl" 19840
PATH=/tmp/flh077-shim:$PATH bash scripts/validation/flh077/accept.sh "/tmp/flh077 nas C" 19870
```

Drop the shim once D2 is fixed. The overlay run B already exercised exactly
this `ctl.sh` on Linux, so these are confirmation runs only.

