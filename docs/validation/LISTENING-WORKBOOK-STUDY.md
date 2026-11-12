# Workbook listening study lane: validation (2026-11-11)

Lane `workbook-study`, worktree `flh-workers/workbooks`. No Git command was
run; nothing was committed, deployed or run against the daily instance or its
data; no real provider or credential was used. Browser runs used a fresh
scratch database, loopback only, and the local fake provider in
`scripts/validation/listening_workbook/fake_openai.py`.

Evidence (outside the repository): `~/flh-handoff/workbook-study-20261112/`
- `browser/results-{before,after}.json`, `browser/shots-{before,after}/`,
  `browser/console-{before,after}.txt`;
- `audit/listening-evidence-audit.{md,json}`;
- `studypacks/` (every sheet and `<unit>-verification.md`);
- `listening_scripts_v1.before.json` (the embedded pack extracted from the
  baseline server binary, for the item diff).

"Before" is the tree as handed to this lane; "after" is this change set.

## 1. Authored listening flow: highest-friction issue

Walked phone (390×844) and desktop (1280×900): choose a script → import →
attempt → reveal → save a missed point → Mistake Notebook → reopen.

| Friction (before) | Measured | Fix |
|---|---|---|
| After **Reveal answers and evidence**, finding the questions you got wrong meant scanning every reference block | revealed exercise 10,655 px tall on the phone, 7,328 px on desktop; nothing compared your answer with the reference | **Your answers and the reference** at the top of the exercise, focused on reveal: one row per question, your answer beside the reference, a chosen option tagged Same / Different (exact comparison), a typed answer "compare it yourself", no total; **Go to question N** and **Back to the answer overview** |
| Reopening a saved mistake after a reload landed on the lesson heading | marked question at 2,092 px (phone, viewport 844) and 1,327 px (desktop, viewport 900) below the top | the heading takes focus without scrolling when the notebook asked for a question, and that question is brought to the top |

Result: before 51/61 checks, after 77/77 (`results-*.json`). Screenshots:
`shots-after/phone-04a-after-reveal.png`, `phone-04b-overview.png`,
`phone-09-reopened-after-reload.png`; compare `shots-before/phone-04a-after-reveal.png`
and `shots-before/phone-09-reopened-after-reload.png`.

Not changed (shared, reported): `NotebookOrigin` scrolls a marked item to the
centre, which cuts a tall question's stem on a phone (listening now overrides
it on load); Reading uses the same component and likely has the same
reload-reopen behaviour (not verified).

## 2. Evidence sufficiency of the 120 listening questions

Method, findings and the 17 changes: `content/workbooks/review/listening-evidence-audit-v1.md`.
Summary: 5 questions relied on the reading text (including u05-l04, now
grounded in s1 and s5 without inventing speech), 4 had uncited or overreaching
reasons, 3 had evidence that did not cover the answer, 5 options gave away
another question's short answer. After: `audit` reports 120 questions, 0
errors, basis `script` 115 and `script, restated or computed value` 5;
`check` now fails on any of these defects.

Stable IDs: the pack diff against the baseline pack shows the same 12 script
IDs, the same lines, the same 120 item IDs in order and the same answer
position in every single-choice item; 17 items in 10 scripts changed (wording,
evidence, one kind).

Existing imports: `TestListeningScripts_EarlierImportKeepsItsContentAfterAPackCorrection`
imports u05 with the earlier wording, then serves the corrected pack on the
same database: still listed as imported, re-import `409 script_conflict` with
no row written, the lesson reads its earlier wording, a Mistake Notebook item
resolves unchanged, and a new import gets the corrected wording.

## 3. Ten-minute study packs

Four packs (u02 times and durations, u05 an enrolment, u08 several speakers,
u11 reasons and what is not said), each with its goal, ★ focus questions, plan,
debrief prompts and a three-question transfer dialogue with teacher answers
and line-cited reasons. `studypack --all`: 0 errors for all four; student and
reader sheets 0 key-exposure findings; teacher debriefs 65–68 (positive
control); the only flag is u02-l07's computed 8:15. The separation checks
first caught two real cross-question clues (u02, u11), fixed in the workbook.
Tests: every pack builds twice to identical bytes; no explanation, reference
answer or model sentence in a student checklist.

## 4. Authored lesson preparation boundary

Reproduced before (fake provider): `POST /api/listening/materials/1/exercises`
on the u05 script returned `201`; the fake received the 12 script lines; a
generated exercise was stored (exercises 1 → 2) and the lesson then showed
"(Faux fournisseur local) De quoi parle cet extrait ?" instead of the authored
questions (`shots-before/probe-01-script-after-prepare-attempt.png`).

After: `409 {code: "authored_script"}` before any attempt, no provider call
(the fake's log shows only the YouTube call), nothing stored, lesson shows the
authored questions; `current_exercise_id` names the authored exercise even if
an older generated row exists. YouTube: Prepare → generated exercise shown,
reveal, `0:00` links to `&t=0s` (both runs).
Go: `TestListeningScripts_ModelPreparationNeverDisplacesTheAuthoredExercise`.

## 5. Real-browser study walkthrough and learner guide

Covered by the runs above at both widths (import, attempt, reveal, save,
reopen in place and after a reload; zh-CN overview heading; no horizontal
scroll; no console error). Learner guide: `docs/LISTENING_WORKBOOK.md` and
`docs/LISTENING_WORKBOOK.zh-CN.md` (written scripts, not audio). Reproduction:
`scripts/validation/listening_workbook/README.md`.

## Commands and results

| Command | Result |
|---|---|
| `NODE_OPTIONS=--no-experimental-webstorage make verify` (with a private `GOTMPDIR`/`TMPDIR`) | exit 0: 24 Go packages ok, 39 frontend files / 439 tests, production build |
| `python3 -m flh_workbooks check` (tools/workbooks) | exit 0 |
| `python3 -m unittest discover -s tests` (tools/workbooks) | 28 tests OK |
| `python3 -m flh_workbooks studypack --all --out …` | 4 packs, 0 errors |
| `python3 -m flh_workbooks audit --out …` | 120 questions, 0 errors |
| `python3 -I scripts/validation/listening_workbook/run.py … before` / `… after` | 51/61, 77/77 |

## Not verified

- Chromium only (Playwright 1.49.1); no Safari or Firefox; no human reader and
  no recorded audio.
- The daily database was not inspected; the effect on earlier imports was
  tested on scratch databases only.
- The content corrections and new packs are self-review by the authoring
  model, not a teacher's or native speaker's review.
- No Docker image build; no PDF printing of the packs.
