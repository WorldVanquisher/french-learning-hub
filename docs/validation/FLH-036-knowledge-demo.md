# FLH-036 validation: Knowledge Library acceptance fixes and demo

Date: 2026-10-09. Branch supplied: `fix/flh-036-knowledge-demo`. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub`. Implementation owner: local
Claude Code. No Git/GitHub command or subagent was used. The contract is in
[FLH-036 plan](../plans/FLH-036-knowledge-demo.md).

**Host and tools**
- Host: macOS 27.2 (arm64).
- Toolchain: Go 1.26.5, Node v24.16.0, Python 3.13.5, Google Chrome 154 (headless).
- `playwright-core` 1.49.1 lives only in a session scratch directory; it is not a project dependency.

**Isolation**
- All runs used synthetic data in fresh demo directories under the session scratchpad.
- The extractor was the local stub and the analyzer the rule-based one; embedding was disabled.
- No secret, `.env`, personal or daily database, paid provider, Docker resource or permanent dependency was used.
- Frontend checks ran in a scratch copy of `web/` whose `node_modules` came from an earlier identical lockfile (same SHA-256); `web/node_modules` was not installed.

## Automated checks

| Command | Result |
| --- | --- |
| `gofmt -l cmd internal` | no output |
| `go vet ./...` | ok |
| `go test ./... -count=1` | all packages ok |
| `go test ./internal/transport/http -run '^TestKnowledgeLibrary_' -count=1` | ok (5 tests, incl. new `SearchFollowsCurrentSameMembership`) |
| `go test ./internal/config -count=1` | ok (incl. 3 new `LISTEN_HOST` tests) |
| `go build ./cmd/server`, `go build ./cmd/capture` (output to scratch) | ok |
| `npm run typecheck` (scratch copy) | ok |
| `npm run test` (scratch copy) | 17 files, 212 tests passed |
| `npm run build` (scratch copy) | ok; bundle `index-zkwpNrxy.js`, the same bundle the browser runs used |
| `python3 -B scripts/validation/flh035/test_integrated_checks.py` | 6 tests OK (unchanged harness) |
| `python3 -B scripts/validation/flh035/test_expectations.py` | 13 tests OK (unchanged harness) |

`make verify` itself was not run, because it needs `web/node_modules` in the
repository; its steps were run equivalently as above.

### FLH-035 integrated verifier (unchanged): could not run on this host

`python3 -B scripts/validation/flh035/verify_integrated.py --report <scratch>/flh035-verify-macos.json`
exited 1 during `Acceptance()` construction, before any check, with
`FileNotFoundError: 'go'`.

- **Why it can't run here.** Its isolated `PATH` and its prerequisites target the
  Linux NAS: `/proc`, `/tmp/flh029-npm-cache`, and a Go compiler on that path.
  None exist on this host.
- **Outcome.** No report file was written and no process was launched. Its one
  temporary directory (three empty config/home entries) was removed.
- **Not edited.** The harness was not modified.

**Expected result of an unchanged rerun on the NAS, stated so it isn't
misread.** That harness was written to reproduce the defects, so some of its
assertions require the defects to exist:

| Probe | What it asserts | What the fixed code does | Effect on the run |
| --- | --- | --- | --- |
| B3 `RELATION_UI_PROBE` | `expect(duplicate).toBe(true)` | No longer emits the duplicate-key warning | The probe fails inside `build_and_setup`, so the run aborts before later checks |
| B5 collision probe | Setup exits `0` and the server log contains "address already in use" | Setup refuses the occupied port and exits 1 | Fails its fixture precondition |
| B2 and B4 | Record a defect if one is observed | Loopback listener; sentinel survives | Should record none |

Updating those probes to assert the fixed behaviour belongs to the FLH-035
owner. **FLH-035 acceptance remains pending a NAS rerun.**

## Focused regressions per finding

| Finding | Regression | Mutation check |
| --- | --- | --- |
| B1 | Go `TestKnowledgeLibrary_SearchFollowsCurrentSameMembership`: a historical-extraction member matches (C3, orphaned, 0 support); after `ReassignSame` it matches only its new Concept, not the former; a suppressed member still matches while its Concept is orphaned. Vitest asserts the new result label and "CURRENT SAME members" count. | — (contract was already implemented; labels/docs changed) |
| B2 | Go `TestLoad_ListenHost*`: unset → `:18080`; `127.0.0.1`, `::1` (`[::1]:18080`), `0.0.0.0`, padded value; `localhost`, `example.com`, `127.0.0.1:80`, `[::1]`, `256.0.0.1` rejected | — |
| B3 | Vitest "keeps every relation one unit holds to a concept, with no duplicate React keys": real `App` → library → concept; one unit with RELATED (link 7) and BROADER (link 8); both visible, two source buttons, zero "same key" console errors | Reverting the key to `unit_id` in the scratch copy fails the test with React's duplicate-key warning for `13`; restored afterwards |
| B4/B5 | Executed demo probes below | — |

## Socket binding and process identity (direct)

Fresh `demo.sh setup` with the production `dist`:

```
stub pid 24520 listens on 127.0.0.1 port 18933 (loopback only)
server pid 24533 listens on 127.0.0.1 port 18934 (loopback only)
```

**Independent checks**
- `lsof -nP -iTCP:18933 -iTCP:18934 -sTCP:LISTEN`: `python3.1 24520 … TCP 127.0.0.1:18933 (LISTEN)` and `server 24533 … TCP 127.0.0.1:18934 (LISTEN)`.
- `netstat -an -p tcp`: `tcp4 127.0.0.1.18934 LISTEN` and `tcp4 127.0.0.1.18933 LISTEN`.
- Connections: `/readyz` on 127.0.0.1 returned 200; `[::1]:18934` was refused; the host's LAN address `10.36.45.36:18934` was refused.
- Identity records: `server.id` = PID 24533, start time `Fri Oct  9 20:39:58 2026`, command `<WORK>/server -web-dir <dist>`. `ps -ww -p 24533 -o pid=,lstart=,command=` matched exactly; likewise for the stub (`python3 -B …/stub_extractor.py 18933 <WORK>`).

**Default bind preserved.** The same binary, started with `LISTEN_HOST` unset on port 18935 against a throwaway database, showed `lsof` `TCP *:18935 (LISTEN)` (IPv6 wildcard), as before. Started with `LISTEN_HOST=localhost`, it exited: `server error: LISTEN_HOST must be an IP address such as 127.0.0.1 or ::1`.

## Demo lifecycle and failure probes (task-owned processes only)

Every sentinel and collision responder was started by this task. No other process was signalled.

| # | Probe | Result |
| --- | --- | --- |
| 1 | Marked dir; `server.pid` = owned `sleep 300` sentinel; no `.id` (FLH-035 B4 reproduction); `stop` | "pid 25500 is not this demo's server …; NOT signalled"; exit 0; sentinel alive |
| 2 | Stale: `server.pid` = PID of an exited, reaped child | "recorded pid 25514 is not running; stale record removed"; exit 0 |
| 3 | Reused: `stub.pid` = sentinel; `stub.id` claims this demo's stub command with a different start time | NOT signalled; sentinel alive |
| 4 | `cleanup` of the probe directory | removed; sentinel alive |
| 5 | Live demo: `server.pid` and `server.id` replaced by an exact copy of the sentinel's real start time and command (`sleep 300`); `cleanup` | Sentinel NOT signalled; stub (verified) stopped; scan found real server 25149 still carrying this directory's identity, so `cleanup` exit 1 "refusing to delete … while its demo processes may still run"; directory kept. After the true records were restored, `stop` stopped 25149; ports free; sentinel still alive (it exited on its own when `sleep 300` elapsed) |
| 6 | Owned responder on `127.0.0.1:18934` (200 readyz/empty catalog, 503 POST); `setup` in a new dir | "DEMO_PORT 18934 is in use"; `setup FAILED`, exit 1; no seed file; responder logged **0 requests**; no demo process |
| 7 | Same on STUB_PORT 18933 | "STUB_PORT 18933 is in use"; exit 1; 0 requests; no demo process |
| 8 | Partial startup: stub starts, server fails (missing `WEB_DIST`) | "server is not running as recorded …"; "stub: stopped pid 25890"; `setup FAILED`, exit 1; server log `workbench index.html: … no such file`; ports free |
| 9 | Seed failure after an owned, ready server (test-only `PATH` shim makes `seed.py` exit 7) | "seed failed"; server and stub stopped; exit 1; only `seed.partial.json`, no `seed.json`; no demo process; ports free |
| 10 | Normal `stop` then `start` (restart, production) on the same DB | Old PIDs gone; new verified listeners; row counts `4\|7\|10\|15\|5` (entries\|concepts\|units\|links\|extractions) unchanged; search still answers |
| 11 | Repeat setup in a new directory | exit 0, `setup complete`, receipt with 4 entries and 7 concepts |
| 12 | `setup` again on that populated directory | refused, exit 2 |
| — | `cleanup` of every failed and successful demo directory | all removed; ports 18933/18934 free; no demo processes |

Probes 6–9 used `cleanup` afterwards, which succeeded for each failed directory.
The early port check (before the build) was added after probes 6–7 had passed
with the check that runs just before launch. Probe 11 then used the final
script.

## Real-browser walkthrough (headless Chrome)

`scripts/demo/flh034/walkthrough.mjs`, copied unchanged into the scratch
`playwright-core` directory.

| Run | Server | Result |
| --- | --- | --- |
| PROD, fresh `demo1` | `-web-dir` production build | 11/11 (W1–W10 and W11 `--multi-relation`, which POSTed the two relations) |
| DEV, after `demo.sh start` (API only) on the same DB | Vite 5.4 on 127.0.0.1:5334 proxying to the demo, React development build | 11/11. W11 found both relations already present (no POST); the React dev build logged **no duplicate-key warning**. An earlier DEV attempt failed W11 only because the walkthrough's direct API call bypassed `/api`; it was fixed to use `/api` for both servers. |
| PROD, fresh `demo2` (final script) | production build | 10/10 read-only, then 11/11 with `--multi-relation` |

**Read-only evidence**
- SQLite `.dump` SHA-256 was identical before and after the read-only runs: DEV `b7ea0be1…`; PROD `demo2` `2dc2fb30…`.
- W10: 0 non-GET browser requests and no failed API response. The only console error is the browser's `/favicon.ico` 404; the workbench has no favicon, which predates FLH-034.

**What the walkthrough checked**
- **Search labels (W2, W6).** Rows show "N supporting unit(s), N CURRENT SAME member(s)". A `fasse` result reads "not in the concept identity. A CURRENT SAME member matched; membership is not support." and contains no "current unit" wording.
- **Source navigation and return context (W4, W5, W9).** Source of the historical v1 member → back to the concept → back to results for "subjonctif". The query is kept and focus returns to the opened result. Switching views keeps the source screen.
- **Multiple relations (W11).** Concept #3 lists two rows for unit #9, BROADER (link #15) and RELATED (link #14), each with its own source link. The screenshot was inspected.

**HTTP checks of the B1 examples (fresh demo2)**

| Query | Results |
| --- | --- |
| `fasse` | C1 (active, `unit_example`, 2 members, 1 support) and C2 (orphaned, `unit_statement`, 1 member, 0 support) |
| `irreg` | C2 only (historical-extraction member) |
| `malgre` | C3 (suppressed member U4) |
| `accorde` | C6 only (`unit_statement` of reassigned U6), not former C5. C5 lists U6 as historical, "now concept 6". |

## Timing: setup vs presentation

Measured on this host; setup is preparation, not part of the two-minute presentation.

| Activity | Time |
| --- | --- |
| Frontend production build (`npm run build`, dependencies present) | ≈1.7 s |
| Cold server build (fresh `GOCACHE`, modules cached) | 7 s |
| `demo.sh setup` with warm Go cache (build + start + seed) | 1–2 s |
| Automated read-only walkthrough W1–W10 | ≈3–4 s |
| Human two-minute presentation | **NOT RUN** (no human presenter in this session); the `docs/DEMO.md` steps are the script |

## Remaining limits and risks

- **Linux not executed here.** `proc_guard.py`'s Linux branch (`/proc` stat, cmdline, socket inodes) was written to the documented `/proc` formats but was not run on this macOS host. The FLH-035 NAS rerun or a Linux run of the probes above is needed.
- **Unsupported platforms.** Platforms other than Linux and macOS are refused. macOS `ps -o lstart` has one-second resolution, so ownership also requires the full command line to match.
- **Same-user process.** A process started by the same user with the identical command line, in the same second as a reused PID, could not be distinguished. This is not plausible for the demo's PIDs.
- **Tampered records.** These stop the demo conservatively: `cleanup` refuses and names the PID instead of signalling it.
- **Interrupted cleanup.** `SIGKILL` of `demo.sh` or a power loss skips the failure cleanup; run `cleanup`.
- **IPv4 loopback only.** The demo binds `127.0.0.1`. A client resolving `localhost` to `::1` first will retry IPv4 (curl and browsers do); use `127.0.0.1` as documented.
- **Scope of `LISTEN_HOST`.** It is a plain bind option, not an access-control mechanism. The HTTP boundary's Host and Origin checks are unchanged.
- **Unchanged FLH-035 verifier.** As described above, it is expected to fail its defect-reproduction probes against the fixed code.
- **Fixed IDs.** The walkthrough assumes freshly seeded IDs, and W11 writes to the demo database.
