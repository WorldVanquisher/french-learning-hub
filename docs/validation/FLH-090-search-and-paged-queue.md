# FLH-090 — Record text search and bounded review-queue loading

Owner: NAS Claude Code. Continues FLH-089 in the same working tree; FLH-089's
changes are preserved.

**Status: implemented and validated on synthetic data only.**
- **Not daily-use acceptance:** this is not daily-use acceptance and not
  v1.0.0 readiness.
- **No browser:** no browser is installed on the NAS, so browser behaviour is
  **unverified**. UI results come from jsdom component tests.
- **Not touched:** schema migrations, dependencies, AI or embedding calls,
  ranking.

## 1. Contracts

### 1.1 `GET /learning-records?q=` (also `/export`)

| Aspect | Contract |
|---|---|
| Searched fields | The learner-authored `original_input` **or** `original_context` only. Never analyses, corrections, feedback notes or provenance |
| Match | A literal substring, `instr()` not `LIKE`, so `%`, `_` and `\` are ordinary characters. Parameterized SQL |
| Case and Unicode | Case-insensitive through Unicode lower-casing: Go `strings.ToLower`, applied to both sides by the deterministic read-time SQLite function `flh_search_fold_v1` (`internal/storage/sqlite/search_fold.go`). No accent folding; no Unicode normalization (composed and decomposed accents differ) |
| Bounds | Trimmed. Blank means no filter. More than 200 characters (runes), or invalid UTF-8, is `400`. Page `limit` as before (default 50, max 200) |
| Composition | With `state`, `category`, `analyzer`, `before_entry_id` (descending cursor and the record jump) |
| Order | Entry ID descending; no relevance ranking |
| Cost | A full scan of entries per request (no index) |

### 1.2 `GET /reviewable-units`, paged contract (opt-in)

- **Opting in:** any of `limit`, `after` or `from_unit_id` selects the paged
  contract.
- **Without them:** the original complete-list response is unchanged.
- **Only difference to the complete list:** entry order is now an explicit
  `ORDER BY entry_id ASC`, which is the order SQLite already produced.

| Aspect | Contract |
|---|---|
| Eligibility | Identical to the complete list: units of each entry's current extraction (pinned, else latest version), with no CURRENT SAME and not currently INVALID. Optional `entry_id` scope |
| Order | One strict total order: `entry_id ASC, ordinal ASC, unit_id ASC` (unit ID is the final tie-breaker) |
| Cursor | Opaque `next_cursor` (the last unit's key); `after=<cursor>` continues strictly after it. Never an array offset |
| Locator | `from_unit_id=<id>` starts at that unit's key, inclusive. It works whether or not the unit is still reviewable or current, with one bounded lookup instead of a scan. Exclusive with `after`; outside the scoped entry it is `400` |
| Limit | Default 50, max 200, clamped |
| Response | `{"reviewable_units":[{..., "entry_id"}], "next_cursor": string\|null, "limit": n}`. The repository reads `limit + 1` rows, so a queue ending on a page boundary returns `null` without an empty trailing page |
| Errors | `400`: limit, cursor or locator syntax, both `after` and `from_unit_id`, or a locator in another entry. `404`: unknown entry or unit |
| Consistency | Pages are separate reads, not a snapshot. A unit decided between requests is absent from later pages. A unit whose key sorts before the cursor (a new extraction of an earlier entry) appears only after a restart. No unit repeats within one cursor chain |

**Callers:**
- **Unchanged:** the record extraction panel (`?entry_id=`) and every other
  existing caller use the complete list.
- **Paged:** Concept Review, general and record-scoped, now uses the paged
  contract.

## 2. Workbench behaviour

**Learning Records:**
- **Explicit search:** **Search text** is applied explicitly with **Search**
  and cleared with **Clear search**. Applying or clearing restarts from the
  first page.
- **Stale responses:** a response for an earlier search is discarded by the
  existing generation guard.
- **Limits:** over 200 characters is refused before any request. A blank
  search means no search.
- **Status line:** it says what is matched: letter case ignored, accents must
  match.
- **Distinct messages:** no records, no search matches with the current
  filters, and a jump target that is absent or excluded.
- **No local filtering:** the browser filters nothing over loaded pages.

**Concept Review:**
- **Page sizes:** 50 units for the general queue; up to 200 for a record's
  queue.
- **Next page:** read only when skipping past the last loaded unit, or when
  deciding it (one request). Units already loaded are never added twice.
- **Position text:** "unit N of M" only when the whole queue is loaded.
  Otherwise it says "loaded", "more units follow" or "earlier units are not
  loaded".
- **Resume** (FLH-089 behaviour kept):
  - App keeps the unit ID and search text;
  - on return, or on reload queue, one page is read with `from_unit_id`;
  - a unit that left the queue is reported, and review continues with the
    next unit in queue order;
  - **Start from the beginning of the queue** reads the first page.
- **A failed next-page read:** it is shown as its own error, which no decision
  notice can overwrite. It is read again only by an explicit **skip →** or
  **Load the next units**. There is no automatic retry, and no decision is
  resent.
- **Unchanged:** the pending-write, saved-operation and unknown-outcome
  protections, and backend re-reads after decisions.

## 3. Validation (agent-run)

**Go:**

| Command | Result |
|---|---|
| `go test ./internal/storage/sqlite -run 'InventoryText\|TextBounds'` (new `inventory_text_search_test.go`) | 4 passed |
| `go test ./internal/storage/sqlite -run ReviewQueuePage` (new `review_queue_page_test.go`) | 4 passed |
| `go test ./internal/transport/http -run 'LearningRecordsTextSearch\|ReviewableUnitsPagedContract'` (new `flh090_integration_test.go`) | 2 passed |
| `unshare -rn … go test ./...` | all packages ok |

**What the text-search tests cover:**
- **Literal characters:** `%`, `_`, `\` and punctuation.
- **Unicode:**
  - case (`état` finds `ÉTAT`);
  - no accent folding;
  - composed and decomposed accents differ, while identical code points match.
- **Scope:** the original context is searched; generated, corrected and
  provenance text never matches.
- **Pagination and filters:** matches are walked beyond the first page, and
  the filter composes with state and the jump.
- **Bounds:** blank is no filter; 200 characters `é` are accepted; 201
  characters and invalid UTF-8 are refused.

**What the paged-queue tests cover:**
- **Equivalence:** on a fixture with uneven entries, a re-extracted entry and
  a pinned older extraction, complete traversal equals the legacy list, each
  unit once, for page sizes 1, 2, 3, 5, 11, 12, 13 and 200. Exact page counts
  are asserted.
- **Entry scoping:** an entry-scoped page equals the legacy entry list.
- **Decisions between requests:** SAME, INVALID, and a SAME on a page-1 unit.
- **Locator:** a reviewable, a decided and a historical unit; an unknown unit;
  another entry; `after` together with `from_unit_id`.
- **HTTP:** the legacy shape is exact (one key, no `entry_id`); paged keys;
  default and clamped limits; nine `400`/`404` cases.

**Frontend** (`NODE_OPTIONS=--no-experimental-webstorage web/node_modules/.bin/vitest run`): **265 passed**, against 256 after FLH-089. The 9 new tests:
- **Records (5):**
  - the trimmed query is sent, matches page beyond the first page, and clear
    returns to all records, with every read sent to the backend;
  - wildcards are sent literally (`q=50%25_x`), combined with state, category
    and the jump, and the no-match and excluded-jump messages appear;
  - 201 characters are refused with no request, and 200 are sent;
  - a blank search means no search;
  - a slower earlier search that finishes later is discarded.
- **App (2 new, 4 rewritten for paging):**
  - one page of 50, and the next page only past the loaded end;
  - a slow next page that finishes after a reload is not appended.

  The rewritten ones: resume through `from_unit_id`, **Start from the
  beginning**, a decided unit moving to the next in order, reload, and a
  failed re-read.
- **ReviewQueue (2):**
  - deciding the last loaded unit reads the next page once and continues;
  - a failed next-page read is reported, retried only on explicit skip, and
    the POST is sent exactly once.
- **Existing tests updated:** `RecordToConcept.test.tsx` mocks now include the
  paged URLs (the record panel keeps the legacy URL).

**Repository and frontend checks:**
- `web/node_modules/.bin/tsc -b --noEmit`: ok.
- `unshare -rn bash -c 'ip link set lo up; GOPROXY=off GOFLAGS=-mod=readonly GOTOOLCHAIN=local NODE_OPTIONS=--no-experimental-webstorage make verify'`: **exit 0**.

**Fixture** (`bash scripts/validation/flh089/run.sh <scratch>`, the FLH-089
harness extended; 11.2 s): 1,000 records, 3,000 units, 500 Concepts, 1,543
reviewable units, exactly as FLH-089.

| Measurement (`measure.py`, GET only) | Result |
|---|---|
| Normal Concept Review load: `GET /reviewable-units?limit=50` | **50 units, 26,967 bytes, 3.3 ms** (median of 5) |
| Previous full load: `GET /reviewable-units` | 1,543 units, 821,246 bytes, 109.8 ms |
| `?limit=200` | 200 units, 108,182 bytes, 4.6 ms |
| Full paged walk, limit 50 | 31 pages, 1,543 units, **equals legacy order, every unit once**, max page 27,670 bytes |
| Full paged walk, limit 200 | 8 pages, equals legacy order, every unit once |
| `from_unit_id` of the middle unit | starts at it; equals the legacy slice; 27,266 bytes, 3.1 ms |
| 25 entry-scoped paged queues vs legacy | all equal |
| `q=est-ce que` (every input) | 51 pages, 1,000 records, descending, unique; 9.2 ms per page |
| `q=Synthetic context` / `SYNTHETIC CONTEXT` (context only) | 750 records each (case-insensitive) |
| `q=Synthetic question 5:` | record #5 found in **one request** (11.1 ms) |
| `q=journal` (20 long inputs) | 20 records, 2 pages |
| `q=%`, `q=_` | 0 records (literal; the fixture has neither character) |
| `q=Synthetic correction` (feedback text only) | 0 records (interpretations not searched) |
| `q` with state and category; `q` with a jump to #500 | filtered and descending; 500 records from #500 |
| 201-character `q` / 200 characters `é` | 400 / 200 |

**`workflow.py`: 23 passed, 0 failed.**
- **Carried over from FLH-089:** its 16 checks.
- **Text search:** it finds the new record case-insensitively, reaches #7 in
  one request, and treats `% est-ce` literally.
- **Paged queue:**
  - an INVALID recorded between page 1 and page 2 leaves that unit out of
    page 2, with no page-1 overlap;
  - `from_unit_id` of that decided unit starts at the next unit in order;
  - the record-scoped paged queue lists the remaining unit.

**Harness bug found and fixed:** in the first fixture run, a measurement walk
passed `before_entry_id` twice. The server used the first value, so the walk
repeated one page until I stopped it. The walk was fixed and given a page cap.
This was a script defect, not a server one.

## 4. Remaining bottlenecks and limitations

- **No index for text search:** each request scans every entry's input and
  context, about 9–11 ms here. That grows linearly; an FTS or index design
  would need a migration (not authorized).
- **`GET /concepts`:** the full catalog (301 KB at 500) is still loaded once
  for client-side discovery. Full-catalog pagination is out of scope.
- **Annotation Inspector:** it still loads every effective annotation
  (1.27 MB, about 350 ms) and renders them all.
- **Knowledge Library keyword search:** about 320 ms for a specific query at
  500 Concepts.
- **The paged queue is not a snapshot** (§1.2). After a resume, earlier units
  are not loaded until **Start from the beginning**, and "previous" stops at
  the window start.
- **The legacy complete list** remains for its existing callers (the record
  extraction panel) and keeps its cost if called globally.
- **Browser:** rendering, keyboard flow and long-text layout are unverified.
- **Scope of the evidence:** synthetic data and one machine; no claim of
  unlimited scale or v1.0.0 readiness.

## 5. Owner walkthrough (owner-run; not yet done)

1. **Search:** in **Learning Records**, search for a phrase from an old
   question.
   - Check that it is found, that **Load older records** pages through further
     matches, and that it combines with **Record state**, **Effective
     category** and **Go to record #**.
   - Try a phrase with capitals or `%`.
2. **Bounded review:** open **Concept Review**. The position reads
   "… of 50 loaded; more units follow". Skip to the end of the page and once
   more: one further page loads.
3. **Resume:** switch to another view and back. The same unit appears ("loaded
   from where you left off"); **Start from the beginning of the queue** returns
   to the first unit.
4. **Decide at a page end:** decide the last loaded unit and check that the
   next one appears.
5. **Record your observations** on your own data and browser. These are the
   daily-use acceptance this report does not provide.

## 6. Queued follow-up (recorded only; not implemented)

**Unified question intake window** (owner direction, 2026-10-21):
- **Default mode:** paste the original learning question with optional
  context. Save it without triggering analysis or extraction, then show it as
  `unanalyzed`.
- **Alternative mode:** import an existing `learning_capture_v1` JSON,
  preserving its original source and optional candidate Analysis.
- **Imported Analysis:** it remains `unreviewed`; importing JSON never implies
  human acceptance.
- **Afterwards:** both modes lead into the existing record → analysis/review →
  extraction → Concept workflow.
- **To decide later:** backend contracts, payload construction, idempotency
  and reuse of existing endpoints are to be decided after inspecting the
  current implementation in that task.
