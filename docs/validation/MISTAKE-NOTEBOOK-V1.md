# Mistake Notebook v1 — validation

Owner: Claude Code (sole implementation owner). Date: 2026-11-09 (UTC).
Built on a scratch copy of the Speaking v1 tree (Daily Listening, Reading v1,
Writing v1 and Speaking v1 applied). The owner applies it as an incremental
patch after Speaking; see the handoff report for the baseline hash.

**Status: implemented and tested.** Tests used real SQLite, the real handler,
the real server binary in the packaged image, and real Chromium 156. Model
calls went to a local fake. No real provider was used.

Contract: [ARCHITECTURE.md §4.8](../ARCHITECTURE.md#48-mistake-notebook-v1),
A.7 (`source_ref`) and A.20. Owner walkthrough:
[DAILY_USE.md §14](../DAILY_USE.md#14-mistake-notebook).

## Save paths inspected, and the change chosen

All four skills already saved a miss as one `learning_capture_v1` (`source:
manual`), named only in prose. The capture ID was random per form, so the same
item could be saved twice.

The smallest additive change is one optional field, `source_ref`, on the same
request:
- The server checks it against stored items.
- It is stored in `learning_capture_sources` in the capture's transaction.
- It is fingerprinted only when present.
- It is unique per item.

There is no new save endpoint, no backfill, and no parsing of prose or capture
IDs.

## Acceptance

| Requirement | Evidence | Result |
|---|---|---|
| Structured source, persisted additively; old records untouched and shown honestly | Go: `TestCaptureFingerprintUnchangedWithoutSourceRef` (goldens computed with the pre-notebook code); `TestNotebook_DuplicatesReplaysInvalidSourcesAndOldRecords` (a capture without `source_ref` behaves as before, and `/entries/{id}/source` → `linked:false` with the notice). Chromium: a record saved without a link is not a notebook item, and its record view says "no structured source link … not linked by guessing" | pass |
| One end-to-end case per skill, with exact source links | Go: `TestNotebook_EachSkillSavesWithAnExactSourceLink`: each link equals the stored IDs exactly, with no extra fields; prompt, reference, quote and attempt come from the stored item. Chromium (`skills`, `notebook`): listening (prepared exercise, included answer), reading (authored example, unticked answer not sent), writing (correction 1 of draft v1), speaking (improvement 2 of take 1, v1). **Open source** opens the writing task at draft version 1 and speaking take 1 at transcript version 1 (`aria-pressed`), and the listening and reading lessons, each with **← Back to Mistake Notebook**; from a record view, with **← Back to Learning Records** | pass |
| Duplicate-save handling | Go: same `capture_id` → `200` replay; same item, new `capture_id` → `409 source_already_saved` naming the record; same ID, other source → `409`; no new entry. jsdom: Speaking shows "already saved as learning record #55". Chromium: saving writing correction 1 again from a new form names the existing record; the database still holds one source row per item | pass |
| Invalid references refused, nothing stored | Go: unknown record, failed exercise, item out of range, writing and speaking quotes the server did not find, unknown type, an attempt on writing, an unknown field. The entry count is unchanged | pass |
| Prompt, attempt when explicitly saved, reference, link | Chromium: listening shows "Your answer une carte d'identité" (ticked); reading shows "Your answer was not saved with this item." (unticked; the typed answer was not in the request). Writing and speaking show the learner's quoted words. The reference stays hidden until **Show reference** | pass |
| Filter by skill; mark for retry | Go: `skill` filter, unknown skill `400`; marks append-only (3 rows for mark, repeat no-op, unmark), notebook records only (`404` otherwise), no annotation rows touched. Chromium: the Writing filter gives 1 item; three explicit `PUT`s | pass |
| Retry session spanning skills, Recall Practice pattern, no judgment | jsdom and Chromium: "3 items … Skills: Listening, Writing, Speaking". For each item, the reference is hidden until **Reveal reference**, with a self-check (`aria-pressed`). The summary says nothing was saved; there were **no writes** during the session, and the typed answers never left the page. Removing one item is one explicit `PUT {"marked":false}`. Database: marks `(1,1) (3,1) (4,1) (4,0)` | pass |
| Grammar / Vocabulary views over the existing model, unclassified when unsure | Domain: `TestClassifyConceptKindsNeverGuesses`. Go: a pure-grammar and a pure-vocabulary Concept are listed; a mixed Concept is `mixed_kinds` and a morphology one `other_kind`; an orphaned Concept (no support) is not listed; the search narrows the view. jsdom: rows, reasons, search, and opening the Concept in the Knowledge Library. Chromium: the views load with GET only (this database has no Concepts) | pass |
| Nothing creates a mistake automatically | Chromium: zero `POST /captures` across preparing, answering, revealing and self-checking (listening and reading); drafting, feedback and showing a suggestion (writing); recording, playback, confirming, feedback and showing a suggestion (speaking); and opening a save form. Exactly 4 captures, one per **Save learning record** | pass |
| Not in the public demo | Go and jsdom: not routed, no tab. A fresh FLH-073 artifact on this tree: the smoke passes, the ledger includes `019`, and both tables are empty. A live probe at root and `/api` (12 requests): `404` GET, `405` PUT/POST | pass |

## Commands and results

| Command | Result |
|---|---|
| `go test -race -count=1 -run Notebook ./internal/transport/http/` | 5 integration tests pass |
| `go test -count=1 ./internal/domain ./internal/storage/sqlite ./internal/application` | ok |
| `NODE_OPTIONS=--no-experimental-webstorage npx vitest run` | 31 files, 383 tests pass. This includes `MistakeNotebook.test.tsx` (7), the new Reading include-answer and Speaking duplicate cases, and the updated capture-body assertions in Listening, Reading and Writing |
| 15 mutations, each restored: duplicate refusal, source row in the transaction, fingerprint compatibility, source in the fingerprint, writing grounding, failed content, attempt scope, append-only marks, mixed kinds, active-only views, hidden reference, writing `source_ref`, unticked answer, duplicate message, exact draft version | 15/15 caught |
| Packaged Chromium walkthrough, run with `run_browser_notebook.sh` in the handoff | 48 checks, 0 failures (skills 14, duplicate 3, notebook 14, retry 9, record 5, reopen after restart 3); 3 model calls (one per explicit request); daily instance unchanged |
| `NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0 |

## Not verified, and limits

- **No guessed links:** records saved before this feature are not in the
  notebook. They are never linked by guessing. There is no "add an old record
  by hand" action yet.
- **Listening and Reading open the lesson** that holds the item, not a scroll
  position inside it. Writing and Speaking open the exact version.
- **Grammar and Vocabulary** are only as complete as the kinds of the
  supporting units. A Concept supported by `expression` or `morphology` units
  is unclassified by design.
- **Self-checks** are not stored. A retry is not a Concept judgment, a mastery
  score or a schedule.
