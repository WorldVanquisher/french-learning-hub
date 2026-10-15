# FLH-077 validation: Linux public-demo package acceptance

Date: 2026-10-15 (UTC). Local working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64). Target: the NAS
checkout `~/workspace/flh-nas-codex` at `100.98.239.98`. Source-revision label
supplied by the human workflow: `1dc491141de7ae2aab5d5b2c941b8f37cd38d408`.

**Not used:** Git/GitHub, subagents, Docker, Windows changes, a GPU, AWS, paid
calls or model downloads.

**Not touched:** remote source, NAS services and FLH evidence.

**Outcome: Linux package acceptance BLOCKED (no SSH access to the NAS).** A
reproducible harness (`scripts/validation/flh077/accept.sh`) is delivered and
was debugged in a labelled macOS dry run. That dry run found one controller
defect (D1).

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
  loop. This is FLH-076-owned and not modified here.
- **Suggested fix** (for the FLH-076 owner): `curl --max-time 2`, and stop
  polling once the recorded pid has exited.
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
| 1. Build/package with the revision label | NOT RUN (SSH BLOCKED) | PASS |
| 2. Packaged native Linux binary: architecture, checksums, layout | NOT RUN | Layout/checksums/ELF headers PASS; execution not possible on macOS |
| 3. Controller lifecycle, repeats, stale pid, unrelated process, spaces | NOT RUN | PASS, except the occupied port: **FAIL (D1)** |
| 4. Static, presets, provenance, denied requests, bytes, restart identity | NOT RUN | PASS |
| 5. Mechanical release refusal, tampering | NOT RUN | PASS |
| 6. systemd / nginx template syntax | NOT RUN | systemd BLOCKED (absent); nginx PASS (macOS nginx 1.29.2) |

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
