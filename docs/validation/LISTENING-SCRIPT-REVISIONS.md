# Workbook script revisions lane: validation (2026-11-12)

Lane `workbook-revisions`. No Git command was run; nothing was committed,
deployed or run against the daily instance or its data; no provider was
called. Every run used a fresh scratch database on loopback, an empty working
directory (no `.env`) and a clean environment. Screenshots, browser results,
the regenerated outputs and the printed PDFs are in the lane's evidence
directory outside the repository (named in the Release handoff).

"Old" is a server built from `c53b42c` (its embedded pack predates the
2026-11-11 evidence audit); "before" is the tree handed to this lane
(`521279a`); "after" is this change set.

## 1. The post-merge conflict, reproduced

Old server: import `ls-wb1-u05` (201), save question 4 (`u05-l04`) as a
mistake with an attempt (201). Before server, same database:

| What | Seen |
|---|---|
| Script list | listed as imported, nothing else |
| Lesson | `current_exercise_id` 1, transcript version 1; u05-l04 still explains "Work ends before the 18:30 class." (a class time the dialogue never says) |
| Signal that a correction exists | none |
| Re-import | `409 script_conflict`, nothing written; the workbench never re-imports, so the learner sees no error and no way to update |
| Mistake Notebook item | unchanged, `source_status: resolved`, linked to exercise 1 / transcript 1, `latest_version: null` |
| A fresh import (u06) | 201 with the corrected wording |

In real Chromium (four combinations, see 10) the before tree scores 16/32: no
tag, no notice, the old wording after reveal, re-import 409.

## 2. Revision contract

ARCHITECTURE.md §4.3 ("Pack corrections, revisions and explicit updates") and
A.15. Revision *N* = transcript version *N* + the authored exercise on it.
Same-content import replays; reads report `script_revision.pack_status`; only
the confirmed `POST /listening/materials/{id}/script-update` writes, appending
a revision; earlier revisions and Notebook records are never touched. No
migration (revisions use the existing tables), so no migration number was
needed from Release.

## 3. Update path

`internal/domain/listening_script_revision.go` (fingerprint, diff, errors),
`ListeningRepository.ScriptRevision` / `ReviseAuthoredScript` (one
transaction under the write lock; replay when already applied; stale
otherwise), `ListeningService.ScriptUpdatePreview` / `UpdateScript` /
`GetScriptRevision`, `internal/transport/http/listening_script_revision.go`.

## 4. End-to-end tests (local fixtures)

`internal/transport/http/listening_script_revisions_integration_test.go`, on
fixture packs built from the embedded one:

| Case | Test |
|---|---|
| unchanged import replays, preview empty, confirm replays, nothing written | `UnchangedImportReplaysAndOffersNoUpdate` |
| corrected pack: reads change nothing, 409 names the lesson, preview lists the line and two questions, update 201 → revision 2, lost response resent → 200, re-import 200, old mistakes keep wording and link (`latest_version` 2), revision 1 still reads, new mistake on revision 2 | `CorrectedPackExplicitUpdateEndToEnd` |
| stale preview: pack changed after the preview; lesson moved to another revision | `StalePreviewIsRefusedWithAFreshOne` |
| eight concurrent confirmations → one 201, seven 200, one revision | `ConcurrentConfirmationsAppendOnce` |
| YouTube unaffected (`script_revision: null`, routes 409, transcripts unchanged); refusals write nothing; renamed script; script gone from the pack | `RefusalsAndYouTubeUnaffected` |
| not in the public demo | `UnavailableInThePublicDemo` |

Plus `TestListeningScriptFingerprint_*` and `TestDiffListeningScript_*`.
Mutation check: removing the replay rule fails three of these tests.

## 5. UI (English and Simplified Chinese)

Notice on load (no update button), **Review the changes** preview with the
one-sentence note on earlier practice, confirmation, success, stale and
lost-response states, list tags, the earlier-revision view.
`web/src/pages/ListeningRevisions.test.tsx` (5 tests, one in Chinese).

## 6. Answer overview friction (phone walkthrough)

Found on a 390×844 walk of `u05`: after reveal, a typed answer's overview row
said "compare it yourself" but offered no way to record the comparison; the
learner had to go to the question, mark it, and come back, and the row never
showed the mark (the "Self-checked N of M" line sat about 10,000 px lower).

| | Taps to self-assess question 7 from the overview | Page scrolled | Row shows the mark |
|---|---|---|---|
| before | 3 | 13,406 px | no |
| after | 1 | 0 px | yes (shared with the question's own self-check) |

Typed answers stay self-assessed; nothing is judged, totalled or sent.

## 7. Answer-context check

`audit.answer_context`: the answer's anchors (numbers in digits or words,
ordinals, clock times, days and months, names) must be heard in the script.
Result: 83 anchors, 80 in a cited line, 2 in another line, 1 reviewed
(`u04-l04` « Irlande »), 0 errors. The deliberately bad fixture
`tools/workbooks/tests/fixtures/answer_context_bad.json` fails with exactly
three errors (exit 1) while its two controls pass. What still needs a person:
`content/workbooks/review/listening-evidence-audit-v1.md`.

## 8. Study packs

New: u01 (directions and an address), u06 (problem, solution, next steps),
u12 (advice: do, avoid, why). Seven packs in all, each with a distinct goal;
transfer answers must now also be heard in their own dialogue and no transfer
option may show another transfer answer.

## 9. Regeneration and exposure scan

- Generated workbook files (8): built twice in memory, equal to each other and
  to the committed files.
- Study packs: 49 files built twice, byte-identical; audit report identical.
- HTML: student and reader sheets 0 findings (7 packs); the student workbook
  edition 0; teacher sheets 65–68 and the teacher edition 1,403 (positive
  controls); two planted leaks in a student sheet copy caught.
- Print: all 25 sheets printed to PDF with Chromium 131 and read with
  pdftotext 22.12.0: student and reader 0 findings, every teacher sheet and
  both planted copies caught.

## 10. Real-browser walk

`scripts/validation/listening_workbook/revisions.py` (README there): Chromium
131.0.6778.33 (Playwright 1.49.1), phone 390×844 and desktop 1280×900,
English and Chinese. After: 120/120. Before: 16/32. The earlier study
walkthrough (`run.py`) still passes all 62 checks on the final build,
including YouTube preparation with the local fake provider.

Skipped: Safari, Firefox, a real phone (Chromium emulation only), the old
server's part in Chinese (it is the setup), audio (there is none).

## 11. Learner guide

`docs/LISTENING_WORKBOOK.md` and `.zh-CN.md`: worked example of an old import
and of a fresh import, where 409 still applies, the overview self-check.

## 12. Commands and results

| Command | Result |
|---|---|
| `NODE_OPTIONS=--no-experimental-webstorage make verify` (private `GOTMPDIR`/`TMPDIR`) | exit 0: Go fmt, vet, tests, builds; 43 frontend files / 476 tests; production build |
| `go test ./internal/transport/http/ -run 'ListeningScript' -count=1` | ok |
| `cd tools/workbooks && python3 -m flh_workbooks check` | exit 0 |
| `cd tools/workbooks && python3 -m unittest discover -s tests` | 35 tests OK |
| `python3 -m flh_workbooks audit --doc tests/fixtures/answer_context_bad.json --out DIR` | exit 1, 3 errors (as intended) |
| `python3 -I scripts/validation/listening_workbook/revisions.py OLD… NEW… OUT TAG` | 120/120 (after), 16/32 (before) |

## Not verified

- Chromium only; no human reader; no real phone.
- A real database from the daily instance was not inspected or upgraded; the
  old-import case used scratch databases written by the old binary.
- The new packs and the reviewed answer-context entry are self-review by the
  authoring model, not a teacher's or native speaker's review.
- An update when the pack also changes a script's lines was tested with
  fixture packs (Go) only: the shipped correction changed questions, not lines.
