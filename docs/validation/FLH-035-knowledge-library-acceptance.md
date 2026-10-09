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

