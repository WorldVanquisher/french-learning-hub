# FLH-035 — Knowledge Library independent acceptance

Date: 2026-10-09 (America/Toronto). Owner/verifier: NAS Codex.
Human-supplied branch: test/flh-035-knowledge-library-acceptance; no Git/GitHub
inspection or operations. AGENTS.md was read and actual pwd was reported in chat
as the supplied flh-nas-codex workspace. Claude implements FLH-034 in a separate
working copy. This checkpoint completes **Phase A preparation only**; no FLH-034
integration or demo acceptance is asserted.

## Inspected baseline and authority

Inspection was limited to existing Concept/catalog identity and search,
support/preferred membership, extraction/entry provenance, and relevant validation
helpers: `internal/domain/concept.go`, `knowledge.go`, `admission.go`;
`internal/application/concept_service.go`; Concept/knowledge SQLite repositories;
Concept/knowledge HTTP DTOs and the relevant entry DTO/route registrations;
`web/src/conceptSearch.ts`, `web/src/types/concept.ts`; FLH-026 launcher/local
provider and relevant FLH-028 fixture/helper contracts. No demo or guessed Library
implementation was read, created or modified.

Confirmed existing contracts:

- `GET /concepts` returns `{concepts:[...]}` in **Concept ID descending** order;
  `?state=active|orphaned|retired` filters derived effective state and preserves order.
- `GET /concepts/{id}` returns `{concept,links}`. Links are the full append-only
  resolution history, not a CURRENT SAME membership list or active-source list.
- Concept fields include durable identity/schema/signature, nullable
  `preferred_unit_id`, persisted `lifecycle_state`, derived `support_state` and
  effective `state`. Unsupported normal Concepts remain `orphaned`, not deleted.
- Current membership is exclusively `GET /knowledge-units/{id}/concept-membership`.
  Support requires that membership plus effective admission `active` plus the
  entry's selected current extraction. RELATED/BROADER/NARROWER supply no support.
- `GET /entries/{id}/current-extraction` returns nullable extraction ID and
  `selection_mode`. PUT pins, DELETE resumes latest-successful automatic selection.
- `GET /extractions/{id}` and `/entries/{id}/extractions` expose Units and immutable
  extraction entry/version/analysis/feedback/extractor provenance. Entry GET exposes
  original input/context and timestamps. These are sufficient for source attribution
  checks; they do not themselves implement source-entry navigation.
- INVALID clears SAME and invalid preferred selection. Restore does not recreate
  membership. Reassignment supersedes historical SAME and clears an invalid old
  preferred selection. Old accepted rows remain unchanged.
- Preferred selection requires current SAME membership. A preferred Unit may be
  historical or admission-suppressed and thus provide no current support. Do not
  equate preferred, current source, and supporting source.
- Existing `discoverConcepts` normalizes NFD/diacritics/case/punctuation, applies AND
  substring checks to query tokens over target/intent/scope/feature keys/values,
  excludes retired and exact-match IDs, and preserves catalog order. This is
  Concept Review discovery; it is **not an established Library search contract**.
- There is currently no inspected Library endpoint or public supporting-source-list
  DTO. No such endpoint, response shape, fallback or URL is invented by this task.

## Reusable synthetic expectations

Symbols stand for IDs obtained from API receipts, never assumed numeric IDs.
The probe uses a fresh database and the existing counted local fake provider.
This small contract fixture is not FLH-034's demo seed.

| Symbol | Meaning / expected evidence |
| --- | --- |
| E_A / E_B | Two distinct learner source entries; original input and context remain exact |
| X_A1 / U_A1 | E_A version 1, imported analysis, null source feedback |
| X_A2 / U_A2 | E_A version 2, same analysis, explicit accepted-feedback ID |
| X_B1 / U_B1 | E_B version 1, its own imported analysis, null source feedback |
| C_SHARED | Target `négation ne pas`; grammar intent; synthetic scope; language feature `français` |
| C_MOVED | Target `accord adjectif`; initially unsupported; later reassigned membership |
| C_EMPTY | Target `être auxiliaire`; never SAME; RELATED history alone cannot support it |

Concepts are created C_SHARED, C_MOVED, C_EMPTY, so baseline catalog order is
C_EMPTY, C_MOVED, C_SHARED, deliberately different from alphabetical order.
Extraction evidence is captured before later actions and compared field-for-field;
admission is a live projection and is excluded from the immutable Unit comparison.
All original SAME/relation event payloads must remain unchanged. The reader/oracle
can be reused with integrated fixture IDs once its actual contract is supplied.

| Checkpoint | C_SHARED supporting Units / preferred | C_MOVED supporting Units | Authority/provenance expectation |
| --- | --- | --- | --- |
| A1 two sources | U_A1, U_B1 / null | none | SAME does not auto-set preferred; C_EMPTY orphaned |
| A2 preferred | U_A1, U_B1 / U_A1 | none | Explicit representation, stable Concept ID |
| A3 RELATED | U_A1, U_B1 / U_A1 | none | C_EMPTY has relation history but remains orphaned |
| A4 newer extraction | U_B1 / U_A1 | none | X_A2 current; old preferred still SAME but historical |
| A5 pin X_A1 | U_A1, U_B1 / U_A1 | none | Persistent pinned selection restores old support |
| A6 INVALID U_B1 | U_A1 / U_A1 | none | B membership null; invalid true; history survives |
| A7 restore U_B1 | U_A1 / U_A1 | none | Invalid false; membership remains null |
| A8 clear pin | none / U_A1 | none | X_A2 automatic; durable C_SHARED now orphaned |
| A9 reassign U_A1 | none / null | none | Current SAME → C_MOVED; historical accepted C_SHARED row survives |
| A10 pin X_A1 | none / null | U_A1 | Support follows changed membership, not historical accepted link |
| A11 SAME U_A2 + clear pin | U_A2 / U_A2 | none | X_A2 automatic; explicitly choose new preferred |
| A12 suppress U_A2 | none / U_A2 | none | Membership/preferred remain; effective admission removes support |
| A13 admit U_A2 | U_A2 / U_A2 | none | Support recovers without replacing Concept identity |
| A14 restart | U_A2 / U_A2 | none | All tables, catalog, provenance, selection and HTTP views unchanged |

Each checkpoint reads all tracked Concepts, sources, Units, memberships, INVALID
states and selections on root and `/api`; payloads must agree. Active/orphaned
catalog filters must agree with unfiltered backend states/order. Whole-table
SQLite snapshots (including sequences) and local analysis/extraction counters
must remain unchanged throughout those GET sequences. Explicit fixture mutations
are setup transitions and are not misreported as read-only browsing.

## Phase B concrete acceptance matrix

Pending means **not executed**, not passing or failing. Before acceptance, read
FLH-034's implemented contract and lock its documented ordering/search behavior.
If it reuses the inspected search helper, the exact query expectations below apply;
otherwise document the implemented deterministic contract and assess requirements
without silently importing Concept Review semantics.

| ID | Action / fixture | Expected result and required evidence | Phase A / Phase B |
| --- | --- | --- | --- |
| L01 | Empty/whitespace search; repeat; reload | Stable IDs/order, no duplicate Concepts; backend baseline order above unless Library explicitly documents another stable sort/tie-break | Catalog HTTP checked; Library pending |
| L02 | `NEGATION`, `négation`, `  ne—pas  ` | C_SHARED for existing-helper semantics; case/diacritic/punctuation variants agree; stored signature/identity unchanged | Search expectations prepared; pending |
| L03 | `grammar`, `synthetic`, `language`, `francais` | All three Concepts if helper is reused; verifies intent, scope, feature key and value coverage | Pending integrated search |
| L04 | `negation absenttoken`; clear query | Zero results, clear restores results/context, no provider/write requests; no fuzzy or AI assumption | Pending |
| L05 | Open supported and unsupported Concepts | Correct explicit backend state; C_EMPTY/orphaned C_SHARED remain durable and inspectable; retired policy requires implemented contract | Backend normal states checked; UI/retired fixture pending |
| L06 | Open C_SHARED at A1/A2 | Two distinct supporting source entries; preferred explicit, not inferred from first source; no duplicates from repeated history | Backend support qualification checked; source-list DTO/rendering pending |
| L07 | Open C_SHARED at A4/A8/A12 | Preferred historical/suppressed evidence distinguished from active support; never falsely presented as supporting merely because preferred | Backend checked; UI pending |
| L08 | Pin old / clear / inspect history | Current selection modes shown correctly; historical Units retain exact source IDs/content and do not silently count as current support | Backend checked; Library pending |
| L09 | INVALID then restore U_B1 | Source history remains; active support/membership removed; restore alone adds no SAME; no stale accepted history promoted | Backend checked; Library refresh pending |
| L10 | Reassign U_A1 to C_MOVED | C_SHARED preferred clears; support tracks selection + new CURRENT SAME; original event is unchanged | Backend checked; Library refresh pending |
| L11 | Open each source-entry link | Correct E_A/E_B originals/context; extraction/Unit/analysis/feedback provenance points to real source; no wrong entry selected | Source HTTP checked; navigation pending |
| L12 | Search → select Concept → source → return, then browser Back/Forward | Preserve query, filters, selected Concept and documented return context; verify existing entry navigation integration and URL/history behavior | Pending actual UI; route/state names not guessed |
| L13 | Search/open/switch/source/return/reload | GET-only workflow; every table and provider counter unchanged; inspect browser requests in addition to persisted/API evidence | Existing GET sequence checked; browser workflow pending |
| L14 | Restart documented demo deployment | Same Concept IDs/preferred/source evidence survive; production `/api` serves real Library assets and API responses | Native restart + synthetic-index `/api` checked; demo/release pending |
| L15 | Follow actual two-minute demo instructions verbatim | Record commands, start/finish elapsed time, observable checkpoints, expected versus actual; distinguish setup time from claimed two-minute presentation | Pending human-supplied integrated checkout |
| L16 | Run documented setup twice; cleanup; fresh rerun | Documented refusal/replay/reset behavior, no duplicate unintended data, no personal service/database touched; owned processes/ports/data removed | Acceptance probe repeatability checked separately; demo pending |
| L17 | Empty database, missing/deep-linked Concept/source and read failure | Honest loading/empty/not-found/error state; no auto-extraction, hidden writes or invented representation; return navigation remains usable | Pending implemented contract/browser |

## Precise integration inputs and requirements

Phase B begins only when the human supplies the integrated FLH-034 checkout.
Do not poll Claude's copy or run a partially integrated demo.

1. Read the implemented Library routes/navigation and API contract (including
   search fields, normalization, matching, sort/tie-breaks, unsupported/retired
   inclusion and any pagination). Record actual file/line locations. No guessed
   endpoint should be added to this preparation harness.
2. Read actual Concept detail/representation/source DTOs or composition logic.
   Confirm which sources are current supporting evidence versus history; record
   mapping of Unit → extraction → entry → analysis/feedback. Count source entries
   separately from Units when multiple Units share a source. Clarify preferred
   fallback when unset; never silently call a fallback an explicit preferred Unit.
3. Read the author's maintained two-minute demo instructions and existing fixture
   implementation. Use that implementation unchanged, not this probe as a demo
   substitute. Obtain IDs/receipts from actual setup output or documented lookups.
4. Require an isolated, task-owned data path and loopback port, offline/local fake
   provider behavior or precomputed evidence, and documented repeat/setup/cleanup
   rules. If the supplied instructions target daily data, secrets or paid calls,
   report the concrete blocker and prepare an isolated invocation supported by
   those instructions before execution.
5. Read production frontend/API wiring and source-entry return-state handling.
   Run its actual release delivery path; a synthetic index cannot validate assets.
   Browser availability is checked then without installing permanent dependencies.
6. Capture before/after whole-table snapshots and provider counters around browsing,
   and repeat after ordinary restart. Record demo setup separately from browsing.
   If the fixture lacks an edge above, report the gap and use only already-supported
   test transitions on the isolated fixture; do not edit author demo files.
7. Record actual browser binary/version and observed actions/screenshots/network
   evidence if available. HTTP evidence, component/jsdom mocks and real-browser
   evidence remain separate. If no browser is available, state NOT RUN; never
   promote mocked navigation to actual-browser acceptance.
8. Report defects with exact location, reproducible fixture/action, expected/actual
   state, impact and suggested verification. Do not patch production code.

## Phase A files, commands and checkpoint evidence

Owned files only:

- `docs/validation/FLH-035-knowledge-library-acceptance.md`
- `scripts/validation/flh035/README.md`
- `scripts/validation/flh035/expectations.py`
- `scripts/validation/flh035/test_expectations.py`
- `scripts/validation/flh035/verify_existing.py`

No production, shared harness, demo, dependency, shared documentation or frontend
file changed. README.zh-CN.md exists; neither root README is changed by Phase A.

Executed commands:

```sh
python3 -B scripts/validation/flh035/test_expectations.py
python3 -B scripts/validation/flh035/verify_existing.py --report /tmp/flh035-phase-a-existing.json
python3 -B scripts/validation/flh035/verify_existing.py --report /tmp/flh035-phase-a-final.json
python3 -B scripts/validation/flh035/verify_existing.py --report /tmp/flh035-phase-a-repeat.json
```

All three task Python files were parsed with `ast.parse` without writing bytecode.
Formatting is scoped to these owned Python/Markdown files; no shared formatter,
frontend output or dependency changes were made.

| Evidence | Actual result | Meaning |
| --- | --- | --- |
| `/tmp/flh035-oracle-tests.log` | PASS, 13 tests | In-memory assertion checks, not mocked UI acceptance |
| `/tmp/flh035-phase-a-existing.json` / `.log` | FAIL after 11 checkpoint groups; cleanup PASS | Initial test setup omitted required suppression reason; 422 was correct server validation |
| `/tmp/flh035-phase-a-final.json` / `.log` | PASS, 14 checkpoint groups | Real HTTP + persisted-state checks against existing contracts |
| `/tmp/flh035-phase-a-repeat.json` / `.log` | PASS, 14 checkpoint groups | Independent fresh-directory/database/port rerun of the same contract probe |
| Library component/jsdom tests | NOT RUN | No integrated FLH-034 UI supplied |
| Real browser / actual two-minute demo / release assets | NOT RUN | Reserved for Phase B |

The initial failure is retained and not counted as passing acceptance. The
suppression request was corrected to the already-supported
`{decision:"suppressed",reason:"other"}`. No production patch was made. No
production defect was reproduced within this bounded existing-contract probe;
this does not establish FLH-034 correctness.

Both passing runs recorded compiler `go version go1.27.1-X:nodwarf5 linux/amd64`
and server build metadata `go1.27.1-X:nodwarf5`. No pinned Go 1.26.5 run is claimed.
The launcher recorded resolved compiler path/hash, binary hash/metadata, offline
module verification/build commands, its Python inventory and the 152-file private
backend source inventory. The new probe's Python hashes and every checkpoint's
expected/actual HTTP models are retained in each JSON report. The two builds have
separate temporary caches and directories; identical source identity does not
imply identical binary hashes when native build paths differ.

Both final runs ended with provider counters `{analysis:0, extraction:3}`. Those
three calls are explicit synthetic fixture setup to the loopback fake provider.
All read-only checkpoints and process replacement left counters and entire table
snapshots unchanged. Both final reports and the initial failed report show
`cleanup_errors=[]` and `temporary_directory_removed=true`. Owned native server,
fake-provider listener/thread, source copy, database and cache were removed.
Only chosen `/tmp` reports/logs remain. No permanent dependency, paid API, secret,
personal/daily database, demo resource, Docker resource or frontend build was used.

## Phase A handoff and limits

Completed: inspected existing authority contracts; seventeen-row acceptance
matrix; symbolic fixture/provenance expectations and fourteen transition groups;
reusable GET reader and independent fixture oracle; thirteen oracle tests; two
passing isolated existing-contract runs with root/production `/api` parity,
read-only snapshots/counters and ordinary process replacement; cleanup evidence.

Pending: all FLH-034 integration requirements above, actual supporting-source DTO
or composition validation, documented search/sort and preferred fallback, actual
Library rendering and error states, source-entry navigation/return context, real
frontend assets/container delivery, author's demo setup/repeat/cleanup and timed
two-minute demonstration, actual-browser evidence if available. No additional
investigation or polling of Claude's working copy is scheduled by Phase A.

HTTP reads use a synthetic static index and real production prefix transport;
this cannot prove compiled Library assets or browser routing. The probe does not
exhaustively test zero-unit/failed extractions, retired Concepts, every admission
state, multiple Units within one source entry, power loss, disk failures, or load.
Those are distinct from the tested current/historical and normal-supported versus
normal-orphaned cases. SQLite snapshots prove persisted equality, not the absence
of transient SQL statements. Cleanup cannot survive SIGKILL/host power loss.

Human staging command (displayed only, never executed):

```sh
git add -- docs/validation/FLH-035-knowledge-library-acceptance.md scripts/validation/flh035/README.md scripts/validation/flh035/expectations.py scripts/validation/flh035/test_expectations.py scripts/validation/flh035/verify_existing.py
```

Phase A checkpoint delivered; editing stops here until the human supplies the
integrated checkout and authorizes Phase B under this task.


## Phase B — integrated acceptance, 2026-10-09

Supplied branch: `test/flh-035-knowledge-library-integrated`. Actual `pwd`:
`/home/worldvanquisher/workspace/flh-nas-codex`. NAS Codex read AGENTS.md, the
integrated FLH-034 plan, DEMO.md and this Phase A report before proceeding.
Phase A above is preserved as its original checkpoint; its pending list is
superseded by the evidence below. No Git/GitHub command or subagent was used.

**Checks complete, acceptance has five P2 findings.** Final runner state is
`CHECKS_COMPLETE`, with 71 successful probe groups, five recorded defects,
no execution error and no cleanup error. Exit status is deliberately 1 because
findings remain. Successful probe groups include reproductions of defects;
they do not mean the release passed acceptance.

Exact owned files identified before editing: this report, and
`scripts/validation/flh035/{README.md,integrated_checks.py,test_integrated_checks.py,verify_integrated.py}`.
No production, author demo, shared documentation/harness or dependency file was
edited. Phase A helper hashes and unchanged author demo hashes are retained in
the final JSON. The shared FLH-026 isolation/listener/snapshot helpers were read
and reused without changes. README.zh-CN.md exists; no root README behavior or
command was changed.

### Executed evidence and toolchains

Final artifacts, retained locally outside the repository:

- `/tmp/flh035-integrated-verified.json` and `.log`: complete 71-group run.
- `/tmp/flh035-focused-go.json` and `.log`: four existing HTTP tests pass.
- `/tmp/flh035-integrated-oracles.log`: six new oracle tests pass.
- `/tmp/flh035-phase-a-regression.log`: thirteen preserved Phase A oracle tests pass.

Commands executed:

```sh
python3 -B scripts/validation/flh035/test_integrated_checks.py
python3 -B scripts/validation/flh035/test_expectations.py
python3 -B scripts/validation/flh035/verify_integrated.py --report /tmp/flh035-integrated-verified.json > /tmp/flh035-integrated-verified.log 2>&1
```

An isolated source-copy helper also executed:

```sh
go mod verify
go test -json ./internal/transport/http -run '^TestKnowledgeLibrary_' -count=1
```

That focused Go command passed four top-level tests, zero failures/skips. The
private frontend ran the author's four Library Vitest tests (all pass), plus
one independent real React/jsdom test with mocked API responses reproducing B3
(pass means the defect was observed). These totals are separate from the 71
HTTP/safety probe groups and 19 Python oracle tests; no full repository suite is
claimed. Offline production frontend build and native server build succeeded.

Actual native compiler and built binary metadata both report
`go1.27.1-X:nodwarf5 linux/amd64`; compiler path `/usr/lib/go/bin/go` and compiler
SHA-256 are recorded in focused Go evidence. Binary metadata includes
`GOEXPERIMENT=nodwarf5`, `CGO_ENABLED=0` and `GOAMD64=v1`. This is an observed
local toolchain, not a claimed release pin. Node is `v26.9.0`, npm `12.0.2`.
Native builds used isolated HOME/cache, GOENV off, GOTOOLCHAIN local, offline
modules, readonly module mode and `-buildvcs=false`. npm used a private copy of
already cached public packages, offline `npm ci --ignore-scripts`, and separate
empty user/global configuration files. No dependency was permanently installed.

Measured times are separate:

| Activity | Seconds | Evidence meaning |
| --- | ---: | --- |
| Private npm install and production build | 4.507 | Frontend setup |
| Author native build/start/seed | 14.169 | Demo setup |
| Walkthrough content through HTTP | 0.070 | Automated content traversal only |
| Human two-minute presentation | NOT RUN | No browser available |

### Coverage against the implemented contract

The unchanged author's setup/seed was used first: four Entries, seven Concepts,
ten Units and five successful local extractions. Documented stop/start and cleanup
were executed. DEMO_PORT/STUB_PORT overrides selected isolated reserved ports;
the Phase A fixture was not substituted. Only after pristine demo acceptance did
public API writes add isolated edge probes.

| Check | Expected / actual result |
| --- | --- |
| Normalization and search | Uppercase, composed/decomposed accents and punctuation normalize consistently; duplicate terms deduplicate; one-rune tokens drop. `ÊTRE—COMPOSÉ` finds C5; `subj bie` finds C3; interior substring `jonctif` finds nothing. AND-prefix, not Phase A substring assumptions. |
| Search tiers/order | Identity before Unit evidence, then active/orphaned/retired, lowercased target, ID ascending. Two API-created orphaned identity Concepts named `fasse` precede active evidence hits and retain ascending-ID tie order. |
| Filters/bounds/errors | all/active/orphaned filters, empty retired filter, browse/default limit20, limit1/50 and truncation, no-match and whitespace browse checked. Invalid state/limit, invalid UTF-8, nonempty zero-token input, over200 trimmed UTF-8 bytes and over8 unique terms reject with400; accepted boundary cases checked. |
| Support/preference | C1 supports U9; old U1 is CURRENT SAME but non-supporting. C2 is orphaned despite member U2. C3 supports U3 while suppressed U4 is non-supporting. C4 relation-only carries no support. Explicit preferred membership can be historical without acquiring support. |
| History/reassignment/INVALID | U6 is historical under C5 and current member/support under C6; INVALID U8 remains evidence, not support. API reassignment of historical U2 updates search authority; INVALID clears membership/preference. Removing old CURRENT SAME eliminates its wording from search. |
| Multiple sources/provenance | Reassigning U3 to C1 produces supporting sources E1/E2 with explicit preferred U3. All ten pristine Unit source DTOs checked; historical E1 extraction uses analysisv1 while latest isv2. Later rejected feedback and analysisv2 on E2 do not replace the exact corrected analysis/feedback used at extraction. |
| API/assets | Root and `/api` Library search/detail/source parity checked. Real production index/assets served by native server match privately built dist bytes. No synthetic Phase A index used. |
| Read-only/restart | Whole-table SQLite logical snapshots, including sequence state, equal before/after pristine browsing, restart and post-edge browsing. No changes in local extractor POST count: five seed calls, zero browsing/restart calls. Persisted demo state survives documented restart. |
| Navigation | HTTP source/detail content verified. Four author mocked UI tests include search→Concept→source→return with same query and GETs only, orphan honesty, stale-result handling and empty/error retry. Actual browser interaction NOT RUN. |
| Demo safety | Repeat setup/seed, existing nonempty/relative/repository directories, unmarked lifecycle directories and nonloopback seed URL refusals checked. Controlled PID and occupied-port probes expose B4/B5. Normal cleanup verified. |

CURRENT SAME is a membership authority, not extraction currency or support.
Implementation searches the canonical/statement/example text of CURRENT SAME
members **including historical-extraction and suppressed members**. Former SAME
members cease matching under their old Concept; reassigned members can match
under their new Concept. Relation-only and INVALID Units do not supply search
wording. Entry input/context and analysis explanations are not search fields.
This behavior agrees with the demo's historical-member step and current-membership
architecture, but conflicts with the plan sentence and ambiguous result labels
identified in B1.

### Concrete findings (production fixes belong to its owner)

**B1 — P2: historical search contract and labels disagree.**
`docs/plans/FLH-034-knowledge-library.md:38` excludes historical/reassigned Units
from searched wording. Fresh demo `GET /knowledge-library/concepts?q=fasse`
actually returns C1/C2 through historical extraction X1 CURRENT SAME U1/U2.
`GET /knowledge-library/concepts/2` shows one member, zero support, orphaned.
`irreg` also finds historical U2; `malgre` finds suppressed U4. The demo relies on
this behavior. Results labels at `web/src/pages/KnowledgeLibrary.tsx:61–63`
say “current unit wording/statement/example”, which can imply current extraction.
Detail/source pages distinguish historical evidence correctly. Clarify the
intended CURRENT SAME search contract and labels, then verify those examples and
that former membership is excluded under the former Concept. Impact: a reader
can mistake searchable historical membership for current supporting evidence.

**B2 — P2: advertised loopback-only demo app listens on wildcard.**
`scripts/demo/flh034/demo.sh:37–40` supplies PORT but no loopback binding;
`internal/config/config.go:185` constructs `":" + PORT`. Owned socket inspection
found an all-zero IPv6 wildcard listener, despite the script's loopback-only
claim. The stub is loopback-bound. Reproduce with documented setup and inspect
the recorded server PID's listener; no nonloopback request was needed or sent.
Owner should bind the app appropriately or state the actual exposure and
isolation requirement. Verify the app listener address, not merely curl's URL.

**B3 — P2: independent legal relation rows have duplicate React keys.**
`web/src/pages/KnowledgeLibrary.tsx:291` keys UnitCard by unit_id; relation rows
at line338 can legally repeat that Unit for different relation types. On fresh
demo POST `/knowledge-units/9/concept-links/relation` with
`{"concept_id":3,"relation":"related"}`, then with relation `broader`.
Concept3 detail contains both Unit9 rows. Independent real-component React/jsdom
probe renders two cards and captures the duplicate-key warning for9. This is
mocked UI evidence, not actual-browser evidence. Both relations are legitimate;
no API uniqueness violation is asserted. Owner should use stable relation identity
or group presentation without dropping relation types. Verify both remain visible
and reconciliation emits no warning. Impact: unsupported React reconciliation
can duplicate or omit children. Final JSON retained an older location282; the
current exact location is291. The runner's locator string was corrected after
the full run, with no executable behavior change.

**B4 — P2: demo stop trusts a raw PID without process ownership.**
`scripts/demo/flh034/demo.sh:25–28` unconditionally kills the PID in server.pid.
In an owned marked disposable directory, server.pid was set to an owned
non-demo `sleep 120` child; author `stop` terminated it with signal15.
Marker presence does not prove a live/reused PID belongs to the demo. Owner
should attribute processes before signaling. Verify stale/misattributed PID
refusal and normal stop. No unrelated user process was touched by this probe.

**B5 — P2: setup returns success after server and seed failure.**
`scripts/demo/flh034/demo.sh:43` accepts readiness from any listener on the port;
line61 pipes seed through tee and masks its failure. An owned HTTP collision
fixture served readyz200, empty Entries/Concepts and POST503. Running unchanged
setup in a new empty owned directory produced server “address already in use”,
failed seed, empty seed.json, yet exit0. Fixture recorded the attempted requests;
no existing/personal listener was contacted. Owner should attribute readiness to
the started child and preserve seed exit status. Verify occupied-port setup
fails and creates no false successful receipt.

### Evidence isolation, initial failures and cleanup

The author stub has no counter endpoint. A temporary sitecustomize hook observed
completed POSTs at its stdlib handler boundary, logging only “POST”; hook source
is retained in JSON. It changed no payload/response and applied only to the local
stub. Analyzer was local rule-based and embedding disabled; no analyzer counter
is invented. HTTP requests required PID/socket ownership before proceeding.
Snapshots show persisted equality, not absence of transient SQL operations.

Intermediate artifacts remain distinct from final evidence:

| Report stem under `/tmp` | Actual outcome |
| --- | --- |
| flh035-integrated-initial | Failed before probes: npm attempted to load `/dev/null` as both configs; wrapper changed to separate empty files. |
| flh035-integrated-second / third | Failed after59 groups: post-stop `/proc` fd access race; cleanup completed. Wrapper closure check corrected. |
| flh035-integrated-fourth | Failed after59 groups: immediate restarted stub listener check preceded its startup; bounded ownership wait added. Cleanup completed. |
| flh035-integrated-final | Complete69 groups/five findings before additional search cases and independent React reproduction. |
| flh035-integrated-verified | Complete71 groups/five findings, no execution/cleanup error; definitive full-run evidence. |

Final evidence confirms author demo directory and private build/cache/data
root removed, all reserved owned listeners stopped, and cleanup_errors empty.
Focused Go copy also removed with no cleanup errors. Owned collision responder
and sleep sentinel were cleaned. Only reports/logs and temporary verification
helper evidence remain in `/tmp`. No daily/personal database, secret, external
paid provider, permanent dependency, Docker resource or shared frontend output
was used. Author scripts and Phase A helpers retained their hashes.

### Remaining limits and handoff

Actual browser source navigation/return context and actual human two-minute
presentation are **NOT RUN**: no browser tool/executable was available. The
optional author walkthrough.mjs was not executed. HTTP and mocked React evidence
must not be relabeled browser acceptance. Contract uses local view state; browser
Back/reload preservation from Phase A hypothetical expectations is not imposed.
Positive retired-Concept ordering/support was not exercised (retired filter is
empty and no supported retirement API was available). Container delivery, full
release suite, disk/power failure, load and malicious external clients were not
verified. Native production assets and production `/api` transport were verified.
Cleanup cannot survive SIGKILL or host power loss. Local `/tmp` evidence is not a
committed artifact; the reusable runner can regenerate it given README prerequisites.

Completed: implemented-contract HTTP/data/search/provenance, authored demo
setup/restart/cleanup, production asset delivery, read-only snapshots/counter
checks, focused tests and five reproducible findings. Pending: owner fixes,
independent rerun of affected checks, actual-browser and human presentation.
Editing stops at this handoff; no production fix is included.

Human staging command (display only; never executed):

```sh
git add -- docs/validation/FLH-035-knowledge-library-acceptance.md scripts/validation/flh035/README.md scripts/validation/flh035/integrated_checks.py scripts/validation/flh035/test_integrated_checks.py scripts/validation/flh035/verify_integrated.py
```
