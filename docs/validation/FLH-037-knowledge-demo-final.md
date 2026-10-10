# FLH-037 — Final integrated Knowledge Library and Linux demo acceptance

Date: 2026-10-10 (America/Toronto). Supplied branch label:
`test/flh-037-knowledge-demo-final`; no Git state was inspected.
Actual `pwd`: `/home/worldvanquisher/workspace/flh-nas-codex`.
Codex read AGENTS.md, FLH-035 Phase B, FLH-036 validation, DEMO.md and
proc_guard.py, and reused the completed investigations and acceptance runner.
No general audit, Git/GitHub command, subagent or production fix was performed.

**PASS within the executed Linux/HTTP/mocked-UI scope:** 84 integrated probe
groups, zero defects, no execution or cleanup errors. Browser interaction and
the human two-minute presentation are **NOT RUN**. This does not replace those
presentation checks with automated HTTP timing.

## Ownership and acceptance changes

Codex was the sole implementation owner in the supplied directory. Owned scope
was `scripts/validation/flh035/` and this report. Modified files:

- `scripts/validation/flh035/verify_integrated.py`: acceptance rather than defect
  reproduction; mocked React expects two labelled relation cards and no warning;
  records actual compiler/binary/platform evidence; cleans socket-reservation
  construction failure; emits PASS only when assertions and cleanup pass.
- `scripts/validation/flh035/integrated_checks.py`: allows multiple independent
  relations for one Unit within that section, while rejecting duplicate link IDs,
  duplicate Unit/relation pairs, duplicate Units in other sections, and cross-section
  overlap. Expected relation inventory remains exact.
- `scripts/validation/flh035/test_integrated_checks.py`: four additional oracle
  regressions, including rejection of invalid duplicate and cross-section evidence.
- `scripts/validation/flh035/linux_demo_checks.py` (new): independent /proc identity
  and listener checks, task-owned sentinels, both collision ports and startup/seed
  failure injection.
- `scripts/validation/flh035/README.md`: current acceptance behavior and prerequisites.
- `docs/validation/FLH-037-knowledge-demo-final.md` (new): this handoff.

No API/schema/shared-file contract changed. The unchanged author demo and existing
FLH-026 isolation/snapshot helpers are dependencies. All writes used private
builds, fresh synthetic databases, local fake extraction and task-owned resources
under /tmp. README.zh-CN.md exists and remains unchanged: no root README behavior,
setup or API documentation changed. The historical FLH-035 report is preserved.

## Commands and evidence

Executed from the reported working directory (output reports are new files):

```sh
python3 -B scripts/validation/flh035/test_integrated_checks.py > /tmp/flh037-integrated-oracles.log 2>&1
python3 -B scripts/validation/flh035/test_expectations.py > /tmp/flh037-phase-a-oracles.log 2>&1
python3 -B scripts/validation/flh035/verify_integrated.py --report /tmp/flh037-integrated-verified.json > /tmp/flh037-integrated-verified.log 2>&1
python3 -B /tmp/flh037-focused.py > /tmp/flh037-focused-go-verified.log 2>&1
```

The focused helper copied cmd/, internal/, migrations/, go.mod and go.sum into
an isolated directory and ran these commands with offline module resolution,
readonly modules, a private HOME/cache/TMPDIR, local toolchain, provider defaults
rule-based/disabled/disabled, and `-buildvcs=false`:

```sh
go mod verify
go test -json ./internal/config ./internal/transport/http -run 'Test.*(KnowledgeLibrary|ListenHost)' -count=1
```

| Evidence | Result |
| --- | --- |
| Integrated Python oracles | 10 tests PASS |
| Preserved Phase A oracles | 13 tests PASS |
| Final integrated verifier | exit 0, PASS, 84 groups, defects=[], error=null, cleanup_errors=[] |
| Private frontend | offline npm ci, production build PASS; five author Library jsdom tests PASS |
| Independent React/jsdom mocked API probe | PASS: two cards, RELATED and BROADER, zero duplicate-key warnings, console_messages=[] |
| Focused Go tests | eight top-level tests PASS: five KnowledgeLibrary, three ListenHost; go mod verify PASS |
| Changed Python syntax | all four files parsed with ast.parse; no bytecode generated |

The verifier's JSON retains every exact argv, exit status, output and duration,
fixture/source/detail models, observer source, identity evidence and hashes.
Focused Go JSON is `/tmp/flh037-focused-go-verified.json`; its private directory
was removed. The final passing verifier was preceded by a separate complete
passing `/tmp/flh037-integrated-run1.json` (84 groups); it predates added metadata.
Only the final verified report identifies the final executable harness.

Toolchains actually executed (no release-pin claim):

- Linux 7.1.8-arch1-3, x86_64.
- Python 3.14.7 (main, Aug 10 2026, 07:46:56) [GCC 16.1.1 20260728].
- go version go1.27.1-X:nodwarf5 linux/amd64; resolved compiler /usr/lib/go/bin/go.
- Node v26.9.0, npm 12.0.2.
- Compiler SHA-256: `678de66bea2ad8ae67f23b7faa63e1bab32dd21a406bb0c224de853a64480117`.
- Built demo server SHA-256: `87b107db4eed3ef361bde4d23fbe728a7882dde3f9dea6542665bbed599966f9`; full go version -m
  metadata retained in JSON (CGO_ENABLED=0, GOAMD64=v1, nodwarf5).

Measured separately: private frontend setup 5.787 s;
author build/start/seed 19.351 s;
automated HTTP content traversal 0.061 s.
Human two-minute presentation: NOT RUN.

## Integrated behavior and Linux lifecycle

The unchanged documented setup used the privately built production workbench,
normal API seed, four Entries, seven Concepts, ten Units and five successful
local extraction calls. Search/detail/source, production index/assets byte parity,
root and /api parity, documented stop/start against the same database, and cleanup
all passed. Successful setup was preparation, not a timed presentation.

| Requirement | Expected and actual evidence |
| --- | --- |
| Listener ownership | Independently resolved /proc/PID/fd socket inodes against /proc/net/tcp and tcp6. Both server and stub owned exactly 127.0.0.1 listeners, before and after restart; no wildcard listener. |
| Linux identity | server.id/stub.id equalled PID, kernel stat field 22 start tick, and full cmdline reconstructed from NUL-separated argv. Server command names WORK/server; stub command names stub_extractor.py and ends in WORK. |
| Normal stop/restart | Both old listeners closed; new attributed processes acquired the same loopback ports; search models and complete table snapshots unchanged, no provider increment. |
| Dead record | Reaped owned child PID: stop exit 0, stale record removed. |
| Misattributed records | Owned sleep sentinel with missing identity, exact non-demo identity, changed start tick or changed command: stop exit 0, NOT signalled, records removed, sentinel remained alive. Cleanup did not signal it. |
| Newer identity mismatch | Reaped predecessor and replacement sentinel both used an owned WORK/server copy of sleep. Replacement PID with older start tick was NOT signalled; stop and cleanup exit 1, scan named remaining process, directory retained. Restoring exact live identity permitted SIGTERM, reaping and cleanup. |
| App-port collision | Owned HTTP responder: setup exit 1 before build/seed, 0 GET/POST requests, no seed.json/server binary, empty directory-identity scan; cleanup passed. |
| Stub-port collision | Same expected/actual outcomes, 0 requests to collision fixture; no demo children launched. |
| Partial startup | Missing WEB_DIST let stub start but server failed at workbench index.html. setup exit 1, setup FAILED, no seed.json; stub stopped, no attributed children, both ports closed; cleanup passed. |
| Seed failure | Private PATH shim exited 7 only for seed.py after both owned listeners/readiness. setup exit 1, seed failed, seed.partial.json only, no success receipt; both children stopped, both ports closed; cleanup passed. |
| Other refusals | Repeated setup/seed, nonempty/relative/repository paths, unmarked lifecycle directories, non-loopback seed URL rejected without state/counter changes. |

Direct final-run identity examples: server PID 3179485, start tick 360673322;
stub PID 3179482, start tick 360673316; after restart server PID 3179564/start
360673431 and stub PID 3179561/start 360673426. Full matching records/commands
and listener addresses are in `observations.linux_identity`.

The replacement probe is controlled stale-identity evidence, not forced kernel
PID reuse. If successive launches share a kernel tick, it explicitly uses an older
simulated tick. All signalled sentinels and collision resources belonged to this
task. No unrelated process was signalled or existing service contacted.

| Knowledge authority | Expected and actual evidence |
| --- | --- |
| Support versus historical membership | C1 supports U9 while old U1 remains CURRENT SAME without support; C2 has historical U2 membership, zero support, orphaned. Preferred historical CURRENT SAME remains valid without becoming support. |
| Suppressed admission | C3 supports U3; suppressed U4 remains a searchable member, not support. `malgre` returns only C3. |
| Search and corrected labels | `fasse` returns C1/C2 via historical CURRENT SAME; `irreg` returns C2; member wording is distinguished from identity. Author mocked UI test asserts “member unit statement”, CURRENT SAME count and “membership is not support”. HTTP evidence is not rendered-label evidence. |
| Reassignment | Pristine U6 is former history under C5 and support under C6; `allee` returns only C6. Moving historical U2 to C1 makes `irreg` match C1 only and changes counts without increasing support. |
| INVALID | U8 remains historical INVALID evidence; marking U2 INVALID clears membership/preference and its search wording; marking U1 INVALID removes remaining historical fasse member hits. |
| Exact interpretation | All ten Unit source chains attributed to original Entry, extraction source analysis/feedback and current membership. Historical E1 uses analysis v1 with latest v2; E2 uses exact corrected feedback/explanation. Later rejected feedback and analysis v2 never replace the extraction's interpretation. |
| Multiple legal relations | HTTP C3 contains both U9 RELATED/BROADER with distinct immutable link IDs. Independent mocked real React component renders both labelled cards with no duplicate-key warning. Relations confer neither membership nor support. |
| Search contract | AND-prefix normalization, accents/punctuation/token deduplication, identity/evidence tiers, status/ID ordering, filters, limits/truncation, bounds/invalid UTF-8 and 400/404 errors all asserted. |

Every read-only sequence compares all SQLite tables including sequence state and
the local extractor POST counter before/after: pristine traversal, search/error
matrix, asset/source reads, restart and post-edge browsing all remain equal.
Pristine snapshot SHA-256 (sorted JSON representation):
`29dfc6d74aa36ceeebe03325cdc369f289242a9a88aaadd169964de123e8a97c`.
Final counter: `{'stub_received_posts': 5}`; all five calls were explicit fixture
seed extractions. A private sitecustomize observer counted completed stub POSTs
without modifying payloads/responses. Local rule-based analysis has no HTTP
provider counter; embedding stayed disabled. No external/paid call was made.
Snapshot equality proves persisted read-only behavior, not absence of transient SQL.

## Baseline, intermediate failures and cleanup

Before edits, `/tmp/flh037-baseline.json` captured all demo files, the acceptance
harness, AGENTS.md, both historical reports, DEMO.md and README.zh-CN.md. The
following baseline hashes were rechecked unchanged at handoff:

| File | Baseline SHA-256 (unchanged) |
| --- | --- |
| `AGENTS.md` | `bb62dcc7be0f7190119e14bce8e5bf6e75cb08719216a14c08aff64718c41206` |
| `README.zh-CN.md` | `8ebca8fa2de8c60bf83ddade2f7e8c6fdb3ba33e281f8ca5effba313c07b366e` |
| `docs/DEMO.md` | `9a5ab477af6f82dd92c52ca4a20ad09746d0d7ec7ef7cc7e5437cbae8f432e62` |
| `docs/validation/FLH-035-knowledge-library-acceptance.md` | `a3006521cf3a4c5cc31400e8737bdfddf4529f4e46afd9615724be601a974a9d` |
| `docs/validation/FLH-036-knowledge-demo.md` | `e593e90ef2cb03c6f501ebf26352141a7bf23073ae64dd6d3525ced791124827` |
| `scripts/demo/flh034/README.md` | `525429bbe6257b2dc191eb925a56a8977f60e722c43019671dd8c30cc2354537` |
| `scripts/demo/flh034/demo.sh` | `a8a7847ca86a296d4810ea1197eedc4cb0c14e4e2c9bcb7415f4e41d2042dc55` |
| `scripts/demo/flh034/proc_guard.py` | `eb394fa552e8f70b448b4364b824b5ff9ec1df6f5e5dcc2703bdfb225c98e710` |
| `scripts/demo/flh034/seed.py` | `9a612951602914448efab8dfa05af9ddb571e572f565082b2d83d507e51b7591` |
| `scripts/demo/flh034/stub_extractor.py` | `8e113aadfdc22729490c775a887f29a78acbcb5aacdbdd9bf68781387b30b6da` |
| `scripts/demo/flh034/walkthrough.mjs` | `a997974386eef89f30cd095e42cb6c39ccacf268e3f90ec1b3745fa35a1ff7f9` |

Owned pre-edit harness hashes are also retained in that baseline JSON; final
Python hashes are in `acceptance_sha256` in the passing integrated evidence.
Phase A helpers remained identical. No production/demo/shared dependency file was
edited; no repository node_modules, dist, bytecode, generated output or database
was created by these checks.

Failed attempts are retained as failures, with reproducible expected/actual outcomes:

| Artifact under /tmp | Actual outcome and resolution |
| --- | --- |
| flh037-integrated-initial.log | Expected socket reservation; sandbox denied socket creation before checks; no JSON or launched children. Its constructor-only directory was inspected and removed. Harness now unwinds socket reservation failure. |
| flh037-focused-go.json/.log | Expected test-ready private copy; migrations omitted and inherited EXTRACTOR_PROVIDER=openai disagreed with config tests clearing the fake key. No production defect; helper copied migrations and used defaults. Directory removed. |
| flh037-focused-go-final.json/.log | Config regressions passed; HTTP httptest socket denied by sandbox. Rerun with socket access passed eight tests. Directory removed. |
| flh037-integrated-final.json/.log | 49 groups passed before asset check raised NameError: re; metadata edit accidentally removed required import. Import restored in harness, cleanup passed, definitive rerun passed 84 groups. |

The final run reports owned_listeners_stopped=true, demo_directory_removed=true,
temporary_directory_removed=true and cleanup_errors=[]. Failed demo directories,
sentinels, collision thread/socket, observer, databases, private frontend/source,
public package cache copies and native caches were cleaned. Only evidence logs,
JSON and temporary focused/report-generation helpers remain under /tmp. No
secrets, personal/daily database, permanent dependency, paid call or Docker resource
was used. SIGKILL/power loss remain outside ordinary cleanup guarantees.

## Limits and human handoff

No browser tool/executable was available (command lookup and bounded executable
search found none). Actual browser interaction and walkthrough.mjs are NOT RUN.
HTTP traversal, authored/mock React navigation and label checks remain distinct
from browser interaction. The human two-minute presentation is NOT RUN. Full
make verify/container release, macOS rerun, load, disk/power failures, positive
retired-Concept fixtures and hostile-client scenarios were not tested here.
The report establishes the requested integrated Linux acceptance scope, not
universal deployment certification. No unresolved failure remains in that scope.

Editing stops at this handoff. Human staging command (displayed only; never executed):

```sh
git add -- scripts/validation/flh035/README.md scripts/validation/flh035/integrated_checks.py scripts/validation/flh035/test_integrated_checks.py scripts/validation/flh035/verify_integrated.py scripts/validation/flh035/linux_demo_checks.py docs/validation/FLH-037-knowledge-demo-final.md
```

Suggested commit message:
test: verify integrated knowledge library and Linux demo acceptance
