# FLH-078 validation: real-model public-demo release candidate

Date: 2026-10-15 (UTC).

**Branch label (supplied):** `fix/flh-078-demo-release-candidate`.
**Baseline (supplied):** `41de9f067359159618f05c88cfe0e4c28a89802b`.

**Hosts:**

| Host | Details |
| --- | --- |
| Mac | `/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64; Chrome 155.0.8059.41) |
| NAS | `worldvanquisher@100.98.239.98`, Linux x86_64, Go 1.27.1 |
| Windows E5 host | `awake@100.118.109.6`, RTX 4070 Laptop GPU |

Builds on [FLH-076](FLH-076-public-demo-release-preparation.md) and
[FLH-077](FLH-077-linux-demo-package.md). Operator guide:
[PUBLIC_DEMO.md](../PUBLIC_DEMO.md).

**Not used:** Git/GitHub, subagents, Docker, AWS or paid calls, model
downloads, package installation, nginx, systemd installation, public
listeners, DNS, TLS issuance or publication.

**Windows actions** (all before the owner's scope update at about 04:12Z, none
after):
- one recorded encoder restart;
- a task-local copy of the FLH-065 wrapper in `C:\Users\awake\flh078\`.

There were no authentication, firewall, Tailscale or package changes.

**Outcome: a release CANDIDATE exists and passed every local check. It is not
deployed.**

| Part | Result |
| --- | --- |
| A. Linux packaging (D2) | **FIXED.** Checksum tests PASS on macOS (both implementations, missing tool) and on Linux (`sha256sum`; `shasum` NOT RUN, absent) |
| B. Real-model artifact | **DONE.** 20 positions in 3 POSTs to the pinned `singleton_v1` deployment; artifact `d025f217f4d76396`, `validate -release` exit 0 |
| C. Linux package verification | **PASS**, no shim or overlay: `accept.sh` 84/0/1 (nginx BLOCKED), `ctl_regression.sh` 35/0, candidate package smoke PASS |
| D. Real browser, real artifact, encoder unreachable | **PASS**: `accept.mjs` 37/0 and `candidate_browser.mjs` 50/0 against the packaged Linux server in a loopback-only network namespace |
| E. Deployment/rollback rehearsal | **PASS** 31/0 (loopback; local rehearsal only) |
| F. Handoff | This report; PUBLIC_DEMO.md and the FLH-076/077 status banners updated |

## Source provenance

**The NAS checkout `~/workspace/flh-nas-codex` was synced by the human:**
- `ctl.sh` is `74ec63d4…`;
- `accept.sh` is `e88dcd16…`;
- `ctl_regression.sh` is `63d0a0b4…`.

**Local tree vs NAS checkout:** a per-file SHA-256 comparison (568 vs 569
files, excluding `.git`, `node_modules`, `dist` and `data`) found **no
differences except this task's files**. No Git was run, so the baseline
revision is the label supplied by the human. It was not verified here.

**Task-local copy `/tmp/flh078-src` (NAS):**
- the checkout without `.git` and `flh-nas-codex.code-workspace`;
- plus this task's uncommitted files. `diff -rq` lists exactly these:

| File | SHA-256 | In the packages? |
| --- | --- | --- |
| `scripts/demo/flh076/package.sh` | `4d43b25ec3ecb102a095d1443393b6f3c6353bac94e1fcea192376343854d800` | It built them |
| `scripts/demo/flh076/test_package_checksums.sh` (new) | `9cbcffaf471f5cfcb3a5ab4096b974255ea3d0fb329ff35641db26609fe3c9f4` | No |
| `scripts/demo/flh076/smoke_package.sh` | `8cd6569e126560cb25a93c52bbb34ee28eb5d3400906b813d3d90894b3e10e19` | No (added after the packages were built) |
| `scripts/validation/flh078/rehearse_rollback.sh` (new) | `b43bbbad4898cba8ae8383288aa71e474441d6c84cd5c906304d28244247187c` | No |

**Revision label in every package:**
`41de9f067359159618f05c88cfe0e4c28a89802b+flh078-wt`. It means baseline plus
this task's working-tree changes. It is **not a clean commit**. After commit,
rebuild with the real revision if a clean label is wanted. Package contents
other than `RELEASE.json` don't depend on the label.

## A. Checksum portability (D2 fix)

**`package.sh`:**
- **Tool selection, before building:** `sha256sum` when present, else
  `shasum -a 256`; else `refused: no SHA-256 tool (need sha256sum or shasum)`,
  exit 2, with nothing built or written.
- **Both uses changed:** the `SHA256SUMS` loop (now `IFS= read -r`) and the
  tarball `.sha256`.
- **Output format** unchanged: `HASH  PATH`.

**`smoke_package.sh`:** its two tree hashes used `xargs shasum`, which fails
on Linux and breaks on spaces. They now use the same selection, per file.

**`test_package_checksums.sh WORK ARTIFACT [EXPECTED]`:**
- runs `package.sh` with a restricted PATH: a farm of symlinks that hides
  chosen tools;
- **checks for each package:**
  - every line matches `^[0-9a-f]{64}  path$`;
  - the list covers exactly the other files;
  - `sha256sum -c` and `shasum -c` both verify it;
  - the tarball `.sha256` matches;
  - the packaged `validate-release.sh`, under the same PATH, gives the
    expected exit;
  - tampering with `web/index.html` gives `INVALID: checksums differ`
    (exit 1);
- the work directory contains spaces.

| Host | Work dir | Result |
| --- | --- | --- |
| Mac (both tools) | `/private/tmp/flh078/cks mac` | **20 PASS**, both implementations; same path lists |
| NAS (no `shasum`) | NAS `~/flh078/nas-evidence/flh078 nas cks` | **PASS** for no-tool and `sha256sum`-only; `shasum`-only NOT RUN (absent) |

The real artifact was used, so each package was a `CANDIDATE` and
`validate-release.sh` exits 0.

## B. Real E5 artifact

**Encoder before the restart:** found with read-only queries.
- **Process:** PID 37180,
  `python -B -m flh_e5 serve … --port 8765 --dtype float16 --microbatch 8 --batching dynamic_v1`.
- **Origin:** created 2026-10-14 22:52:49 (Windows local time) in a Windows
  Terminal PowerShell console (parent 26404).
- **Port 8765 listeners:** 127.0.0.1 (that PID), plus `tailscaled` PID 9544 on
  the tailnet addresses, the existing Serve forward.
- **Clients:** no established connections.
- **FLH-065 wrapper:** not deployed in the runtime checkout.

**The wrapper:** `flh-e5.ps1`, `FlhE5Ops.psm1` and `runner.py` were copied,
hash-identical to the repository, into `C:\Users\awake\flh078\operations`.
`check` returned ok.

**Restart, recorded:**

| UTC | Action |
| --- | --- |
| 03:51:21 | After checking its creation time and command line, `Stop-Process 37180`, the documented `stop.ps1` method. The tailnet listener stayed |
| 03:51:29 | Wrapper `start`: **refused, exit 2**: `port 8765 is already in use by PID 9544 tailscaled.exe` (finding W1). Nothing launched |
| 03:51:52 | Launched detached through `Win32_Process.Create`, with the wrapper's exact service argv and offline environment (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `PYTHONUNBUFFERED`, `PYTHONIOENCODING`): `cmd.exe` PID 41860, which runs python PID 8452, `--host 127.0.0.1 --port 8765 --dtype float16 --microbatch 8 --batching singleton_v1`. Logs: `C:\Users\awake\flh078\e5-run\` |
| 03:52:14 | `/readyz` 200; `/manifest` reports **the pinned id** (`multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff`) |

**Embed:** one invocation in the **existing** work directory
`~/flh076/e5-work`.
- The first attempt, run outside the repository root, failed on a fixtures
  path before any probe. `state.json` was unchanged.
- **Result:** 20 positions in 3 POSTs (8, 8 and 4 inputs; all HTTP 200;
  250 ms, 203 ms and 94 ms in the service log).

**Accounting**, cumulative and never reset:
- 20/64 positions, 3/16 POSTs, 2/2 probes;
- 20 receipts: **complete 20, failed 0, uncertain 0**.

**Files:**
- `state.json` `41cf83b486591969c8b003a6100f57f018d8afd350889b88bcb756f2f072d8d3`;
- `plan.json` `239b159a73f9ce8e105f73eec0a63cf1f5d3a5181d01f9265799ef975db7a91a`
  (plan hash `083a35ef…`);
- pre-embed snapshot in `~/flh078/e5-work-before/`.

**Artifact** `~/flh076/artifact-e5` (made read-only; a copy is on the NAS at
`/tmp/flh078-artifact/artifact-e5`):
- `artifact_version` `d025f217f4d76396`;
- `manifest.json` `dfe6e94de6664c18be2ae65a27ad9b6c107e7ceefb56a1627fe3f54d4788bcab`;
- `demo.db` `00180b4c…`, `vectors.json` `6a916e28…`, `provenance.json`
  `45ae960f…`, `fixtures.json` `0e3d1912…`;
- domain fingerprint v3 `c92c71c4…`; 768 dimensions;
- `prepare validate -release` exit 0, "valid (real-model vectors)".

**Encoder state at handoff:**
- **Last observed (03:53Z):** the restarted `singleton_v1` encoder (PID 8452)
  running and ready.
- **Not checked afterwards:** after the owner's 04:12Z instruction to stop all
  Windows contact, its state was not checked again, and the owner reported
  Windows as unstable.
- **Restoring the earlier `dynamic_v1` service** (owner's choice), on the
  laptop:
  1. stop PID 8452 after checking its command line, or use `windows\stop.ps1
     -Confirmed`;
  2. in a console: `conda activate flh-embedding`, then
     `tools\embedding\e5\windows\start.ps1 -ModelDir
     C:\Users\awake\models\multilingual-e5-base -Batching dynamic_v1`.

## C. Linux package verification (NAS, no shim, no overlay)

`PATH=/usr/local/sbin:/usr/local/bin:/usr/bin`; the host has no `shasum`, and
the FLH-077 shim directory is not in PATH. Everything was run from
`/tmp/flh078-src`. Evidence was then moved to NAS `~/flh078/nas-evidence/`,
because tmpfs `/tmp` hit a per-user quota ([E](#e-deploymentrollback-rehearsal)).

| Run | Result |
| --- | --- |
| `ctl_regression.sh "/tmp/flh078 nas ctl" 19840` | **35 PASS / 0 FAIL** (fixed controller, unmodified) |
| `FLH077_REVISION=41de9f06…+flh078-wt accept.sh "/tmp/flh078 nas accept" 19870` | **84 PASS / 0 FAIL / 1 BLOCKED** (`nginx -t`: not installed; not installed by this task) |
| `package.sh` for the real artifact, label `flh078-rc1`, with `--expected-deployment` set to the pinned id | **CANDIDATE**, built natively on Linux |
| Packaged `validate-release.sh` | exit 0, "CANDIDATE: checksums, artifact, model provenance and release validation passed" |
| `smoke_package.sh <rc1> "/tmp/flh078 nas smoke" 19960` | **PACKAGE SMOKE PASSED** |

**What `accept.sh` covered** (mechanical artifact, so the package is
`…-BLOCKED`, as designed):
- native x86_64 execution, ELF machines, layout, `SHA256SUMS`;
- lifecycle, repeats, spaces in paths, stale or dead pid files, an unrelated
  process never signalled;
- bounded startup and the occupied port;
- denied routes, 405, `q=` 400;
- restart identity;
- tamper refusals;
- `systemd-analyze verify`.

**What the smoke covered** (packaged native binary, real artifact):
- `real_model=True model_vectors`;
- the allowed routes 200 and denied ones 404;
- writes 405;
- counters unchanged by denied requests;
- exactly two cached preset lookups;
- package bytes unchanged.

**Candidate package** `flh-public-demo-flh078-rc1`:

| Item | Value |
| --- | --- |
| Tarball SHA-256 | `78fb5495499d185212ca1fcf0ebf484da73f2b200983e5dd2c2de0e8d45aa906` (41,342,937 bytes) |
| Tarball copies | NAS `~/flh078/release/`; Mac `~/flh078/release/` (verified, also unpacked there) |
| Unpacked tree | NAS `~/flh078/nas-evidence/flh078-release/flh-public-demo-flh078-rc1/` |
| `SHA256SUMS` | `08ece45ce8496b717c8896277c7915a48fc664756bfc2b61f6b195e8add08240` |
| `RELEASE.json` | `56412945c22c96030c133683a18c40fb8be79e378a6fee51081a4c0fd7ed571e` (built 03:56:42Z, Go 1.27.1, `release_status: CANDIDATE`) |
| `bin/linux-amd64/flh-server` | `95f4bb73…` |
| `bin/linux-arm64/flh-server` | `5a2d239e…` |
| Model provenance in `RELEASE.json` | the pinned deployment, plan `083a35ef…`, 20 positions, 3 POSTs, 2 probes. The first, mismatched probe from 02:58Z is recorded honestly |

## D. Real browser against the candidate, encoder unreachable

**Harness:** `scripts/validation/flh078/browser_offline.sh` (Mac).
- On the NAS, `offline_serve.sh` runs **the packaged server**, through its own
  `deploy/ctl.sh`, inside `unshare -rn`.
- **Namespace proof** (`netns.txt`): only `lo`, no IPv4 or IPv6 routes. A
  probe to the encoder from inside fails: `http_code=000 curl_exit=7`. With
  no route, no packet can leave the host. So this is no contact with
  Windows.
- **Path to Chrome:** `netns_bridge.py` bridges loopback to a Unix socket to
  loopback, then `ssh -N -L` carries it to the Mac, loopback at both ends.
- **Browser:** installed Chrome 155.0.8059.41, headless, driven by
  `playwright-core@1.49.1` installed in the work directory (no browser
  download).

**Final run** (`~/flh078/browser-offline4`; earlier runs 2 and 3 gave the same
results):

| Suite | Result | `results.json` SHA-256 |
| --- | --- | --- |
| Existing `accept.mjs --expect-vectors model` | **37 PASS / 0 FAIL**, 14 requests | `5567ceac5295f1713fa83f622967953e1afb0b9c36f7e30cb5b0330da93593c4` |
| New `candidate_browser.mjs` | **50 PASS / 0 FAIL**, 28 requests | `91d8d8f68a15191dc0ebb88730f8e41b61392aeee45141213e8e6aac6c934c0c` |

**`accept.mjs` covered:**
- notices, no mechanical banner, no editing controls;
- keyword search with evidence, empty result, server 400 with retry;
- semantic and hybrid evidence, the hybrid policy line;
- concept detail, source record, back navigation with focus restored;
- an injected hybrid 503;
- the request allowlist.

**`candidate_browser.mjs` covered:**
- **Identity shown to visitors:** the page reads `Artifact d025f217f4d76396 ·
  vectors: model (<pinned id>, 768 dimensions)`, and the server agrees
  (`real_model: true`).
- **All 8 presets** in both semantic and hybrid mode:
  - results with similarity, policy and score evidence;
  - **the UI order equals the server's answer** for every preset.
- **All status filters:** all 12, active 10, orphaned 2, retired 0. Each count
  equals the server's, every result carries its state tag, and the filters
  partition the catalog.
- **Navigation:** semantic result to concept detail, and back with focus
  restored.
- **Injected failures:** a semantic HTTP 503 and a dropped connection. Each
  shows an explicit error with retry and no substitute results.
- **Requests:** every request is same-origin, GET and on the public-demo
  allowlist. Semantic and hybrid requests carry preset ids only.
- **Console:** no errors except the deliberate ones.
- **Screenshots:** 25.

**Top results with real E5 vectors** (semantic; hybrid differs only where
keyword evidence adds):

| Preset | Semantic top result |
| --- | --- |
| miss-someone | tu me manques: saying you miss someone |
| still-going-on | depuis with the present for something still going on |
| no-longer | ne … plus: no longer |
| past-habits | imparfait for background and past habits |
| subjunctive | subjunctive after « bien que » |
| il-faut-que | subjunctive after « il faut que » |
| passe-compose | passé composé for a completed event |
| although | ne … pas encore: not yet |

For `although`, hybrid ranks « bien que » means although first. These are
illustrations on 12 invented Concepts, not a relevance evaluation.

**Mechanical-artifact browser evidence:** none was produced in FLH-078. The
FLH-076 mechanical 37/37 remains separate history.

**Development runs (not evidence):** `/private/tmp/flh078/peek/dev1–3`, a host
build on the Mac used to debug the new script.

**Failed harness attempt:** `~/flh078/browser-offline`. A remote background
subshell held the SSH channel open, so the remote side was torn down by
verified PID, and no results were taken. The fix is in `browser_offline.sh`.

## E. Deployment/rollback rehearsal

**Harness:** `rehearse_rollback.sh ROOT PREVIOUS.tar.gz CANDIDATE.tar.gz
19990`. It follows the PACKAGE_README procedure on the NAS (Linux, packaged
native binaries, loopback):
- `releases/<package>/` read-only after validation;
- the `current` symlink beside them, switched atomically with `ln -sfn` plus
  `mv -T`;
- a separate runtime directory;
- `current/deploy/ctl.sh` stop and start.

**The two releases:**
- **PREVIOUS:** the **mechanical, BLOCKED** `flh-public-demo-flh077-BLOCKED`
  that `accept.sh` built from the same source (tarball `67c84f6f…`, artifact
  `e4ee51c6dffcabe3`). It is started with `ALLOW_MECHANICAL=1` and labelled as
  such: it stands in for "the release in service", not for a public release.
- **CANDIDATE:** `rc1`.

**Final run `~/flh078/nas rehearsal 3`: 31 PASS / 0 FAIL.**
1. **Install:** tarball checksums; PREVIOUS validates as BLOCKED (exit 3),
   CANDIDATE as CANDIDATE (exit 0).
2. **Previous in service:** it reports identity `e4ee51c6dffcabe3`,
   `real_model` false.
3. **Switch to the candidate:**
   - `stop` through the switched symlink stops the previous server, and the
     port closes;
   - `start` serves `d025f217f4d76396`, `real_model` true, manifest
     `dfe6e94d…`;
   - `status` names the real-model artifact.
4. **Roll back:** the previous identity is served again after restart.
5. **Forward again:** the candidate identity.
6. **Invalid candidate** (one byte of `fixtures.json` changed in a copy):
   - `validate-release.sh` exits 1, `INVALID: checksums differ`, and the
     service keeps running the candidate;
   - selected anyway: startup is refused (`public demo artifact rejected:
     fixtures.json SHA-256 … differs from the manifest`), and nothing serves;
   - **recovery:** switch back and start, and the candidate identity is back.
7. **Final state:**
   - final stop, port closed;
   - release trees byte-identical before and after (PREVIOUS `f5b9fcda…`,
     CANDIDATE `6e9336df…`);
   - every file in the releases read-only;
   - no server left running.

**Earlier attempts, kept:**
- **Attempt 1** (`/tmp/flh078 nas rehearsal`, now under NAS
  `~/flh078/nas-evidence/`): 25/6.
  - NAS tmpfs `/tmp` hit the **per-user disk quota**. The copy for the
    invalid release failed.
  - Then `ctl.sh start` launched a server but could not write its pid file
    (D3). That server was found by its full command line and stopped.
- **Attempt 2** (`~/flh078/nas rehearsal 2`): 30/1. A harness bug: the
  read-only check included the `releases/` parent. Fixed with `-mindepth 1`.

This is a **local rehearsal, not production acceptance**. There was no
systemd, proxy, TLS, service user, public listener or real host name.

## Findings

| Id | Severity | Location (owner) | Finding | Status |
| --- | --- | --- | --- | --- |
| D2 | Medium | `scripts/demo/flh076/package.sh` (this task) | Required `shasum`, absent on Linux | **Fixed**, with focused tests |
| D3 | Low | `scripts/demo/flh076/deploy/ctl.sh` (FLH-077; not owned) | If `start` cannot write the pid file (disk full, quota, pid path unwritable), it exits 1 under `set -e` and leaves the launched server running untracked. `stop` then can't find it | **Reported, not fixed**. Workaround documented in PUBLIC_DEMO.md |
| W1 | Medium | `tools/embedding/e5/windows/operations/FlhE5Ops.psm1` (FLH-065; not owned) | `start` refuses whenever any process listens on the port, on any address. With the documented Tailscale Serve forward, `tailscaled` always holds 8765 on the tailnet addresses, so `start` can never launch next to the Serve forward clients use | **Reported, not fixed**. Worked around once by launching the identical argv (above) |
| H1 | Low | `scripts/validation/flh077/accept.sh` (FLH-077; not owned) | The systemd check's `mktemp -d /tmp/flh077-unit-XXXXXX` is never removed: 19 MB per run (2 on the NAS: `vCz1XT` from FLH-077, `vuS4ZN` from this task's run) | **Reported**; directories left in place |

**D3 reproducer** (NAS, `~/flh078/d3-repro`, cleaned up):

```sh
mkdir -p R/run/flh-public-demo.pid
PORT=19995 PKG/deploy/ctl.sh start R/run    # exit 1, "Is a directory"; the server stays running
PORT=19995 PKG/deploy/ctl.sh stop R/run     # exit 1; the server is still running
```

**Suggested fix:** write the pid file before launching (to a temporary name),
or stop `$launched` when the write fails.

**W1 reproducer:** with a Serve forward on 8765, stop any console encoder,
then run `flh-e5.ps1 start`. It exits 2 with "port 8765 is already in use by
PID … tailscaled.exe". **Suggested fix:** consider only listeners on
`127.0.0.1:<port>`, or exempt `tailscaled`.

## Evidence and cleanup

**Mac** (`~/flh078/`, outside the repository):
- `CHECKPOINT.md`, the phase checkpoints with resume commands;
- `b-*.log` / `.json`: restart, manifest, embed, import and validate records;
- `e5-work-before/`;
- `release/`: the candidate tarball, its `.sha256`, and the unpacked tree;
- `browser-offline{,2,3,4}/`;
- `wps.sh`, the helper used to send PowerShell commands to Windows.

Also on the Mac:
- `/private/tmp/flh078/` holds the checksum tests and the dev runs;
- `~/flh076/artifact-e5` is the read-only artifact;
- `~/flh076/e5-work` is the work directory.

**NAS:**
- `~/flh078/release/`: the candidate tarball;
- `~/flh078/nas-evidence/`: `cks`, `ctl`, `accept`, `smoke`, `browser*`,
  rehearsal attempt 1, `flh078-release/`;
- `~/flh078/nas rehearsal 2`, `~/flh078/nas rehearsal 3`,
  `~/flh078/nas browser3`, `~/flh078/nas browser4`, `~/flh078/d3-repro`;
- `/tmp/flh078-src`, the source copy;
- `/tmp/flh078-artifact`.

**Windows:**
- `C:\Users\awake\flh078\operations\`: the wrapper copy;
- `C:\Users\awake\flh078\e5-state\`: written by the `check` and the refused
  `start`;
- `C:\Users\awake\flh078\e5-run\`: the encoder logs.

**Processes:**
- **Stopped:** every task-owned server, bridge and tunnel. This was verified
  on the NAS (no `offline_serve`, `netns_bridge` or `-public-demo-artifact`
  processes; ports closed) and on the Mac.
- **Still running:** the restarted shared encoder on Windows, as recorded in
  [B](#b-real-e5-artifact).

No repository, database, backup, credential, weight or earlier evidence was
modified or deleted. The only moves were this task's own NAS `/tmp` outputs,
which went to `~/flh078/nas-evidence/`.

## Remaining blockers and limits

- **Not production acceptance:**
  - nginx is BLOCKED (not installed);
  - there was no TLS, public host name, service user or installed systemd
    unit;
  - `systemd-analyze verify` checks syntax only.
- **Not claimed:** relevance (12 synthetic Concepts) and security auditing.
- **Untested:**
  - the arm64 binaries were built but not executed;
  - `shasum`-only packaging was not run on Linux (the NAS lacks it).
- **Encoder:** its state after 03:53Z is unknown. Restoring `dynamic_v1` is
  the owner's choice (steps in [B](#b-real-e5-artifact)).
- **Labels:** the packages carry the working-tree revision label, not a clean
  commit.
- **Open findings:** D3, W1 and H1, in files outside this task.

## Human launch checklist

1. **Review and commit** this change, then optionally rebuild with the clean
   revision label. Use the same artifact `~/flh076/artifact-e5` and
   `--expected-deployment` set to the pinned id. The artifact and
   `SHA256SUMS` content stay the same except for `RELEASE.json`.
2. **Decide publication.** It is not authorized by FLH-078. Then choose the
   host, the public host name and the certificate method.
3. **On the host:**
   - create the user `flh-demo` and `/srv/flh-demo/releases/`;
   - copy the tarball;
   - `sha256sum -c flh-public-demo-flh078-rc1.tar.gz.sha256`;
   - unpack into `releases/`, run `./validate-release.sh` (expect 0), then
     `chmod -R a-w`;
   - `ln -sfn releases/flh-public-demo-flh078-rc1 /srv/flh-demo/current`.
4. **Install** the reviewed systemd unit and nginx block (proposal below).
   Then `systemd-analyze verify` and `nginx -t`, enable, and reload.
5. **Check:**
   - locally, `curl -s http://127.0.0.1:18970/knowledge-library/demo`: version
     `d025f217f4d76396`, `real_model: true`, manifest `dfe6e94d…`;
   - then the same through the proxy, and a browser pass.
6. **Keep the previous release directory for rollback.** Rollback is: switch
   `current`, `systemctl restart flh-public-demo`, then check the identity.

## Proposed hosting configuration (for review; nothing applied)

**Recommended:** a small Linux amd64 VM that runs nothing else. 1 vCPU and
512 MB are ample: the unit caps memory at 256 MB, and the package is 41 MB.

**Alternative:** the NAS, where the candidate is already verified. That would
need inbound exposure (a router port-forward or Tailscale Funnel), which is a
network decision outside FLH-078. The VM keeps the home network out of
scope.

| Setting | Proposed value |
| --- | --- |
| Release root | `/srv/flh-demo/releases/<package>`, with `/srv/flh-demo/current` → the selected release (read-only) |
| Service | `deploy/flh-public-demo.service.example`, as shipped: `User=flh-demo`, `WorkingDirectory=/srv/flh-demo/current`, `LISTEN_HOST=127.0.0.1`, `PORT=18970`, every provider disabled, `ProtectSystem=strict`, `ReadOnlyPaths=/srv/flh-demo`, `MemoryMax=256M`, `Restart=on-failure`. Replace only `HTTP_ALLOWED_HOSTS=<public host>`, and `linux-arm64` if relevant |
| Proxy | `deploy/nginx-flh-public-demo.conf.example`: TLS on 443, 80 redirected, GET/HEAD only, `client_max_body_size 1k`, 10 r/s with burst 20 per client, 20 connections, forwarding headers stripped, `proxy_pass http://127.0.0.1:18970`. Replace `server_name` and the certificate paths |
| TLS | The operator's ACME client (for example certbot's webroot or nginx mode), installed and run by the human after DNS points at the host |
| Firewall | Inbound 80 and 443 only, plus SSH from the operator's network or tailnet. Port 18970 is never exposed |
| Logs and monitoring | journald for the service, nginx access and error logs, and an external HTTP check of `/readyz` |
| Rollback | As rehearsed: switch `current`, restart, check the identity |

## Files changed by FLH-078

- `scripts/demo/flh076/package.sh`: the D2 fix;
- `scripts/demo/flh076/smoke_package.sh`: portable tree hash;
- `scripts/demo/flh076/test_package_checksums.sh`: new, focused tests;
- `scripts/validation/flh078/`: new task tooling:
  - `browser_offline.sh` `5490bc17…`;
  - `candidate_browser.mjs` `e2c911e7…`;
  - `netns_bridge.py` `a391e4f4…`;
  - `offline_serve.sh` `cc82fe46…`;
  - `rehearse_rollback.sh` `b43bbbad…`;
- `docs/PUBLIC_DEMO.md`: status, packaging host, completed continuation,
  rehearsed restart, rollback and recovery, D3 note;
- `docs/validation/FLH-076-public-demo-release-preparation.md` and
  `docs/validation/FLH-077-linux-demo-package.md`: current-status banners, with
  history kept;
- this report.
