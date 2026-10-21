# FLH-089 — Daily workflow readiness for accumulated learning data

Owner: NAS Claude Code. Scope: the private workbench (`web/`) and synthetic
validation tooling.

**Not touched:**
- the backend, migrations, dependencies or shared contracts;
- AWS or the public demo, deployment;
- providers or models, translation of Concept content.

**Status: implemented and validated on synthetic data only.**
- **Not daily-use acceptance:** this is not daily-use acceptance and not v1.0.0
  readiness.
- **No browser:** no browser is installed on the NAS, so every browser
  behaviour below is **unverified**. The UI results come from jsdom component
  tests of the same source.

## 1. Fixture and environment

| Item | Value |
|---|---|
| Machine | NAS, x86_64, 8 CPUs, Linux; Go 1.27.1, Python 3.14.7; `web/node_modules` as installed (no install in this task) |
| Isolation | `unshare -rn`: loopback-only network namespace; disposable directory under the session scratchpad; the owner's daily database was never opened |
| Generation | `bash scripts/validation/flh089/run.sh WORK_DIR` |

**How `run.sh` builds the fixture:**
- **Build:** it builds `cmd/server`.
- **Providers:** it starts `stub_extractor.py`, a deterministic local stub of
  the extraction provider. The analyzer is the local rule-based one; embedding
  and semantic search are disabled.
- **Seeding:** `seed.py` uses only the public HTTP API, so every domain
  invariant applies. It refuses a non-loopback or non-empty backend.
- **Checks:** it then runs `measure.py` (GET only) and `workflow.py`.

**Actual counts** (`seed.json`). 4,176 API requests took 2.1 s. The run took
9.0 s wall time, including the build.

| Item | Count |
|---|---|
| Learning records | 1,000 |
| Record states | unanalyzed 100, unreviewed 400 (67 of them after a re-analysis: analysis history), accepted 250, corrected 100, rejected 150 |
| Extractions | 1,000 (750 records; 250 extracted twice: extraction history) |
| KnowledgeUnits | 3,000 (2,250 in current extractions, 750 historical) |
| Concepts | 500 (NEW CONCEPT with seed SAME) |
| Further SAME | 188 |
| INVALID | 19 |
| Reviewable units | 1,543 |
| Long learner inputs | 20 records of about 2.6k characters |

**What the counts do not prove:** the counts are test targets, not capacity
claims. Generated text and labels prove neither relevance nor learning
quality.

## 2. Findings (measured before the changes)

**Backend read paths** (`measure.py`, median of 5, this machine):

| Request | Items | Bytes | ms |
|---|---|---|---|
| `GET /learning-records?limit=20` | 20 | 16,416 | 8.7 |
| `…?limit=1&before_entry_id=2` (jump to the oldest) | 1 | 740 | 12.3 |
| `…?category=translation&limit=20` | 17 | 13,454 | 13.4 |
| `GET /learning-records/summary` | — | 307 | 26.6 |
| `GET /reviewable-units` | 1,543 | 821,246 | 107.4 |
| `GET /concepts` | 500 | 301,239 | 69.2 |
| `GET /effective-annotations` | 2,250 | 1,265,804 | 345.0 |
| `GET /knowledge-library/concepts?q=concept%200499` | 1 | 893 | 314.2 |

**Cursor walks to the end:**
- **All records:** 51 pages of 20, from #1000 to #1, strictly descending, no
  duplicates, 514 ms in total.
- **Filtered walks** (`unanalyzed`, `rejected`, `category=grammar`): also
  complete and ordered.
- **Direct jumps:** to #1, #500 and #1000, each one request of about 9 ms.

**Blockers selected (at most three):**
1. **Old records are hard to reach.**
   - **In the UI:** the oldest record needed 50 **Load older records** clicks.
     The view offered only the state filter.
   - **In the backend:** it already supports the exclusive `before_entry_id`
     cursor (one 9–12 ms request to any position) and an effective `category`
     filter. The frontend used neither.
2. **Concept Review loses its place.**
   - **When:** the general queue unmounts whenever another view is shown, and
     **reload queue** reset it as well.
   - **Effect:** returning, for example after checking a record, restarted at
     "unit 1 of 1,543" and dropped the search text.
3. **Concept discovery renders the whole catalog.**
   - **What it did:** with a query that matches everything (the seeded or
     empty search), it rendered all 500 Concept cards. It re-normalized every
     Concept on each keystroke.
   - **Cost:** first render about 678 ms in jsdom, from a temporary probe
     (not a browser measurement).

**Inspected, not changed** (§6):
- record text search;
- the unbounded queue and catalog payloads;
- the Inspector's full list.

## 3. Changes

| # | Change | Files |
|---|---|---|
| 1 | **Go to record #** and an **Effective category** filter in Learning Records. The jump sends `before_entry_id = ID + 1` under the current filters, with a banner (list starts at #ID, newer records not shown), **Show newest records**, a hint when the ID is absent or filtered out, and refusal of invalid input. Stale responses from an earlier filter or jump are discarded by the existing generation guard | `web/src/pages/RecordsBrowser.tsx`, `web/src/api/client.ts` (optional `category` query parameter, already accepted by the backend), `web/src/styles.css` |
| 2 | The general Concept Review queue resumes where it was left (§3.1) | `web/src/App.tsx`, `web/src/pages/ReviewQueue.tsx` |
| 3 | The catalog is normalized once per load. Discovery renders 50 matches at a time with an explicit "Showing N of M matching concepts" and **Show 50 more**; a new search or unit restarts at one page; a selected match is always shown; matching and order are unchanged | `web/src/conceptSearch.ts`, `web/src/pages/ReviewQueue.tsx` |
| — | English and Simplified Chinese messages | `web/src/i18n/en.ts`, `web/src/i18n/zh-CN.ts` |
| — | Tests | `web/src/pages/RecordsBrowser.test.tsx`, `web/src/App.test.tsx`, `web/src/pages/ReviewQueue.test.tsx`, `web/src/conceptSearch.test.ts` |
| — | Fixture and validation tooling | `scripts/validation/flh089/{run.sh,seed.py,stub_extractor.py,measure.py,workflow.py}` |
| — | Documentation | `web/README.md`, `docs/LOCAL_LEARNING_WORKFLOW.zh-CN.md`, this report |

### 3.1 How Concept Review resumes (change 2)

- **What App keeps:** the unit ID, the position and the search text typed for
  that unit.
- **On return or reload:** the queue is always re-read from
  `GET /reviewable-units`, then positioned on the same unit.
- **If that unit left the queue:** it continues at the same position and
  names the unit that is no longer awaiting review. The old search text never
  carries over to another unit.
- **Safeguards:**
  - a failed re-read does not overwrite the saved position;
  - the identity draft and the selection stay per-unit;
  - the pending-write, saved-operation and unknown-outcome handling are
    unchanged.

**Contract changes:**
- **Backend:** none. No endpoint, response, migration or dependency changed.
- **Frontend-internal:**
  - `LearningRecordQuery.category`;
  - `ReviewQueue`'s optional `resume`/`onResumeChange` props and the exported
    `ReviewResume` type;
  - `createConceptDiscovery`, `visibleDiscovery` and `DISCOVERY_PAGE_SIZE`.
  `discoverConcepts` keeps its behaviour, and `UnitCorrections` still uses it.

## 4. Validation (agent-run)

| Command | Result |
|---|---|
| `NODE_OPTIONS=--no-experimental-webstorage web/node_modules/.bin/vitest run` (before changes) | 20 files, **243 passed** |
| same, after changes | 20 files, **256 passed** (13 new) |
| `web/node_modules/.bin/tsc -b --noEmit` | ok |
| `vite build` into a scratch directory | ok (381 kB JS) |
| `unshare -rn bash -c 'ip link set lo up; GOPROXY=off GOFLAGS=-mod=readonly GOTOOLCHAIN=local NODE_OPTIONS=--no-experimental-webstorage make verify'` | **exit 0**: gofmt clean, Go tests ok, vet ok, server/capture/semantic-index builds, frontend typecheck, 256 tests, production build |
| `bash scripts/validation/flh089/run.sh <scratch>` | seed as §1; measurements as §2; `workflow.py` **16 passed, 0 failed** |
| `run.sh` refusals | a non-empty directory and a directory inside the repository are refused; the latter before anything is created |

**The 13 new tests:**
- **Records (6):**
  - a jump to #3 in one request reaches the last page ("End of records."),
    and **Show newest records** returns;
  - an absent or filtered-out ID is reported, and older pages stay reachable;
  - invalid input (`abc`, `0`, `-3`, `1.5`, empty) sends no request;
  - the category filter is kept on older pages, and an empty match is
    reported;
  - a slow newest-first page that finishes after a jump is discarded;
  - the jump, the category and the loaded pages survive opening a record and
    returning, with no list refetch.
- **App (4):**
  - unit and search text are restored after a view switch, with the queue
    re-read;
  - when the unit left the queue: same position, a note, and no search-text
    leak;
  - **reload queue** keeps the position;
  - a failed re-read keeps the saved position for the next success.
- **ReviewQueue (1):** 120 Concepts → 50 rendered with the total, then 100,
  then 120; a new search restarts at one page.
- **conceptSearch (2):**
  - prepared discovery equals `discoverConcepts` for every query, in catalog
    order;
  - a selected match stays visible beyond the page.

**Complete workflow** (`workflow.py`, API level, the same endpoints the
workbench calls):
1. capture import (201) and an idempotent replay (200);
2. the new record is first on the newest page;
3. a jump to #3 reaches the last page;
4. a jump combined with state and category filters stays filtered and
   descending;
5. the imported interpretation is `unreviewed`; an explicit acceptance makes
   the row `accepted`;
6. an explicit extraction makes 3 units, current under automatic selection;
7. the record-scoped queue lists them;
8. SAME to a catalog Concept, then NEW CONCEPT with seed SAME; decided units
   leave the queue;
9. the library Concept lists the new member, and the unit source shows the
   learner's original input.

**Discovery after the change** (the same temporary jsdom probe, 500 Concepts
all matching): 50 cards, 138–152 ms in three runs, against 500 cards and
678 ms before. These are jsdom numbers, not browser frame times.

**The fixture server also served the built workbench:** `/` and
`/api/learning-records` returned 200. No page was rendered in a browser.

## 5. Owner walkthrough (private workbench; owner-run, not yet done)

1. **Records:** open **Learning Records** and enter an old record's number in
   **Go to record #**.
   - The list starts there, with the banner, in one step.
   - Combine it with **Record state** and **Effective category**; open the
     record and go back; the position and filters remain.
2. **Review:** in the record, review the interpretation (accept or correct),
   request an extraction explicitly, then open a unit in **Concept Review**.
3. **Resume:** in the general **Concept Review**, skip to a later unit and
   type a search. Switch to **Learning Records** and back: the same unit and
   search are shown.
4. **Large search:** search broadly. The list states "Showing 50 of N"; use
   **Show 50 more**; select a Concept and decide explicitly.
5. **Source:** open the unit's source in the inspection or the **Knowledge
   Library** and check the original learner text.
6. **Record the results:** layout with long learner text, and performance on
   your own data and browser. These checks are the daily-use acceptance that
   this report does not provide.

## 6. Remaining blockers and limitations

- **No record text search:** finding a record by its words needs a narrow
  backend dependency, for example a bounded `q` filter on
  `GET /learning-records` over the original input and context. Jump and
  filters cover IDs, state and category only.
- **`GET /reviewable-units` is unbounded** and issues one query per entry: 1,543
  units, 821 KB and about 107 ms here, growing with the data. The queue is
  re-read whenever Concept Review is shown. Pagination would be a backend
  contract change.
- **`GET /concepts` is the full catalog:** 301 KB for 500 Concepts. Discovery
  stays client-side.
- **Annotation Inspector:** it loads 2,250 effective annotations (1.27 MB,
  about 345 ms) and renders them all. It is read-only and not on the daily
  path; not changed.
- **Knowledge Library keyword search:** 314 ms for one specific query at 500
  Concepts (backend).
- **Records list growth:** **Load older records** still appends without limit
  if you page through everything. The jump avoids that for targeted access.
- **Browser:** layout with long learner text, rendering speed and keyboard flow
  are unverified.
- **Not covered here:** UnitCorrections discovery, which keeps rendering all
  matches.
- **Scope of the evidence:** synthetic data only; one machine; no claim of
  unlimited scalability or v1.0.0 readiness.
