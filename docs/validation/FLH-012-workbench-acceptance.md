# FLH-012 — Browser acceptance of the release workbench

- Branch under review: `review/flh-012-workbench-acceptance`
- Date: 2026-10-07
- Reviewer: Claude Code (validation only; no production code changed)
- Result: **27 / 27 browser checks passed. One reproducible usability defect found
  (pre-existing CSS), plus three low-severity observations.**

## Environment and method

| Item | Value |
| --- | --- |
| Release path | `cmd/server -web-dir <built workbench>`, the command the release image runs (`docs/RELEASE.md`, "What the image contains") |
| Workbench build | `npm ci` + `npm run build` of the current `web/` sources in a scratch copy |
| Server | `go build ./cmd/server`, started with `env -i` from an empty scratch working directory (so no `.env` could be loaded) |
| Configuration | `PORT=18212`, fresh scratch `DB_PATH`, `AI_PROVIDER=rule-based`, `EXTRACTOR_PROVIDER=disabled`, `EMBEDDING_PROVIDER=disabled` |
| Browser | Google Chrome 154.0.8037.98, headless, fresh profile, driven by `playwright-core` 1.49.1 installed in a scratch directory |
| Vite | Not running (`pgrep vite`: no process) |
| Repository `.env` | Not read. Not used by Compose (not run) or the server (different working directory). |

Startup log (scratch path elided):

```text
analyzer provider: rule-based
extractor provider: disabled
embedding provider: disabled
workbench enabled from <scratch>/webdist (API also under /api/)
listening on :18212 (db=<scratch>/app.db)
```

Probe results: `GET /healthz` 200 `{"status":"ok"}`, `GET /readyz` 200
`{"status":"ready"}`, `GET /api/healthz` 200, `GET /` 200 with
`Cache-Control: no-cache`, the built JS asset 200 `text/javascript`,
`GET /assets/` 404 (no directory listing).

### Fixtures

All data is synthetic and created through the public API on the scratch
database. No personal data and no provider were used.

- Entry 1: `examples/captures/chatgpt-example.json` via `POST /captures`
  (imported analysis, `unreviewed`).
- Entries 2–25: `POST /entries` with text `FLH-012 question synthétique NN` /
  `Contexte de test FLH-012 n°NN`.
- Local rule-based analysis (`POST /entries/{id}/analysis`) plus feedback:
  entry 2 accepted, entry 3 rejected, entry 4 corrected, entry 5 unreviewed.
- Entry 6 has three analysis versions: v1 rejected, v2 corrected, v3 unreviewed
  (latest).
- Resulting inventory: 19 unanalyzed, 3 unreviewed, 1 accepted, 1 corrected,
  1 rejected (25 records, 20 per page, so a second page exists).

### Controlled injection

Checks marked **[injected]** change specific responses inside the browser with
Playwright `page.route` (HTTP 500/404, aborted connection, or a 1.5 s delay).
The backend never sees those requests. Concept Review check H2 uses the
`ReviewQueue.test.tsx` unit/concept fixtures served the same way, because the
real backend has no KnowledgeUnits with extraction disabled. No extraction or
provider output was created or simulated in the database.

## Results

| ID | Check | Result | Evidence |
| --- | --- | --- | --- |
| A1 | Workbench loads from the release server without Vite | PASS | `GET /` 200, `no-cache`; Concept Review heading rendered |
| A2 | API calls are same-origin under `/api` | PASS | Requests: `/`, `/assets/*.js`, `/assets/*.css`, `/api/reviewable-units`, `/api/concepts`, `/api/learning-records` |
| B1 | First page lists the 20 newest records | PASS | Rows #25…#6, "Showing 20 records.", Load older visible |
| B2 | Load older appends page 2 and reports the end | PASS | Request `?limit=20&before_entry_id=6`; 25 rows ending #1; "End of records." |
| B3 | State filters list only backend matches | PASS | rejected → #3; accepted → #2; corrected → #4; unreviewed → #6, #5, #1; state tags match |
| B4 | `unanalyzed` filter | PASS | 19 rows, all "No analysis", "End of records." |
| C1 | Return from a page-2 detail keeps pages, position, focus | PASS | Detail focus on "Record #1"; back: 25 rows kept, focus on "Open record #1", `scrollY=4845`, button in viewport, 0 list refetches |
| C2 | Return keeps the selected filter | PASS | Filter still `unreviewed`, 3 rows |
| D1 | Latest version selected by default | PASS | v1, v2, v3 (latest); v3 pressed; "unreviewed" + not-human-confirmed note |
| D2 | Historical v1 (rejected) | PASS | "Rejected interpretation." banner; only rejected category/explanation; no effective values |
| D3 | Historical v2 (corrected) | PASS | Corrected explanation shown beside the original |
| E1 | [injected] Effective 500 on historical v1, then Retry | PASS | Alert "Could not load the effective interpretation: (500) could not resolve effective analysis"; no other version's content shown; after Retry v1 still pressed, v1 rejected interpretation shown, version list **not** refetched, alert cleared |
| E2 | [injected] Version-list 500, then Retry | PASS | "Could not load analysis versions: (500) could not list analyses"; no false "No analysis."; entry text stayed visible; Retry loaded "v1 (latest)" |
| F1 | [injected delay] Slow record #6 after switching to #5 | PASS | After #6 responses arrived: heading "Record #5", versions "v1 (latest)", #6 text absent |
| F2 | [injected delay] Slow v1 interpretation after selecting v2 | PASS | v2 still pressed and shown; no rejected banner |
| F3 | [injected delay] Slow `rejected` list after switching to `accepted` | PASS | Rows remained "Record #2" |
| G1 | [injected] List 500 | PASS | "Could not load learning records: (500) could not list learning records" with Retry; no empty-inventory message; Retry recovered 20 rows |
| G2 | [injected] Network failure on Load older | PASS | "Could not load older records: Failed to fetch"; 20 rows kept; "Retry loading older records" offered |
| G3 | [injected] Detail entry 404 | PASS | "Could not load the original record: (404) entry not found"; corrected interpretation still shown from its own reads |
| H1 | Concept Review against the real backend | PASS | Empty state "No units are awaiting review." (no units exist: extraction disabled) |
| H2 | [injected test fixtures] Concept Review rendering | PASS | Unit evidence; lone exact match #42 preselected; identity editor with feature `tense`; SAME enabled; accent-insensitive search "etre quebec" found #43; **0 write requests** |
| I1 | Inspector and Dashboard from the release server | PASS | Inspector empty state; Dashboard shows embedding `unavailable` |
| Z1 | No request left the release origin | PASS | All requests to the release origin |
| Z2 | No unexpected console errors | PASS | 6 console errors, all caused by injected 404/500/network failures |

Screenshots were captured during the run (records page, capture detail, v1
rejected, effective error, list error, Concept Review fixture, hover states).
They stay in the reviewer's scratch directory and are not committed.

## Not run

| Check | Status | Reason |
| --- | --- | --- |
| `docker compose up -d --build` container path, healthcheck, bind-mounted data directory | NOT RUN | Docker daemon not running on the review machine (`docker version`: cannot connect to the daemon socket). The equivalent `server -web-dir` process was tested instead. Starting Docker Desktop was not authorized. |
| Concept Review against real extracted units | NOT RUN | Requires `EXTRACTOR_PROVIDER=openai` (paid provider). Rendering verified only with injected test fixtures (H2). |
| Concept Review write actions in the browser | NOT RUN | No real units to act on; writes against injected fixtures would not exercise the backend. Covered by existing unit tests only. |
| Touch devices, mobile viewports, screen readers | NOT RUN | Out of scope; headless desktop Chrome only. |

## Issues

### 1. Hovered primary/selected buttons become unreadable (reproducible, medium)

- **Location:** `web/src/styles.css:185`
  `button:hover:not(:disabled) { background: #f2f4f7; }` has higher specificity
  (0,2,1) than `button.primary` / `button.same` / `button.invalid` (0,1,1, lines
  188–190). It also overrides `.view-tabs button[aria-pressed="true"]` (0,2,1,
  line 68) because it appears later in the file.
- **Steps:** open the release workbench, then hover the active view tab, the
  selected analysis version (Learning Records detail), or NEW CONCEPT / INVALID /
  SAME in Concept Review.
- **Expected:** the button keeps a readable label; hover never removes the
  selected/primary background.
- **Actual:** background becomes `rgb(242, 244, 247)` while text stays
  `rgb(255, 255, 255)` (≈1.1:1 contrast). Measured computed styles:

  ```text
  selected v3, pointer elsewhere : color=rgb(255, 255, 255) bg=rgb(29, 78, 216)
  selected v3, pointer on button : color=rgb(255, 255, 255) bg=rgb(242, 244, 247)
  Concept Review tab   hover: color=rgb(255, 255, 255) bg=rgb(242, 244, 247)
  NEW CONCEPT          hover: color=rgb(255, 255, 255) bg=rgb(242, 244, 247)
  INVALID              hover: color=rgb(255, 255, 255) bg=rgb(180, 35, 24) → rgb(242, 244, 247)
  ```

- **Impact:** the label of the button under the pointer disappears, including
  write actions (NEW CONCEPT, INVALID) at the moment of clicking. On touch
  devices the hover state can persist after a tap (not verified).
- **Note:** this CSS predates the release work. It is a concrete usability
  defect, not a visual-polish preference.
- **Suggested verification:** after a fix, hover each listed button in a real
  browser and confirm the computed background is unchanged or darker and the
  text remains readable.

### 2. Concept Review celebrates an empty queue when extraction is disabled (low)

- **Steps:** start the release with default providers and open Concept Review.
- **Expected:** a neutral empty state, or one that distinguishes "nothing
  extracted / extraction disabled" from "all units reviewed".
- **Actual:** "No units are awaiting review. 🎉" for a database where no
  extraction has ever been possible. This is the indistinct empty state already
  recorded in the FLH-003 audit; it is reproducible in the release.

### 3. Browser tab title is always "Concept Review — French Learning Hub" (low)

- **Location:** `web/index.html` `<title>`.
- **Actual:** the title does not change for Learning Records, Inspector, or
  Dashboard, and Learning Records is now the first tab.

### 4. Network failures show the raw browser message (low)

- **Actual (G2):** "Could not load older records: Failed to fetch". The state is
  correct and not misleading (rows kept, retry offered), but the text does not
  say that the server could not be reached.

Not an issue, recorded for clarity: reloading the page always returns to
Concept Review with the list reset. The release documents that the workbench
never changes the URL path.

## Reproduction outline

1. Build the workbench (`cd web && npm ci && npm run build`) and the server
   (`go build -o <scratch>/server ./cmd/server`) into a scratch directory.
2. From an empty scratch working directory run
   `env -i PATH=/usr/bin:/bin HOME=<scratch> PORT=18212 DB_PATH=<scratch>/app.db AI_PROVIDER=rule-based EXTRACTOR_PROVIDER=disabled EMBEDDING_PROVIDER=disabled <scratch>/server -web-dir <scratch>/dist`.
3. Seed through the API as described under Fixtures.
4. Drive installed Chrome with `playwright-core` (`chromium.launch({ executablePath })`)
   and apply the [injected] routes described in each check.
5. Stop the server and delete the scratch directory.

## Handoff

- Owned file: `docs/validation/FLH-012-workbench-acceptance.md` (this file).
- No production code, tests, configuration, or other documentation changed.
- Recommended follow-ups: fix issue 1 (CSS specificity) before relying on the
  release for daily annotation; rerun the container path when Docker is available.
