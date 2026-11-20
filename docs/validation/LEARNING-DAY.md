# A synthetic learner's day: note → review → next practice (2026-11-19)

**Run it:**

```bash
python3 -I scripts/validation/learning_day/verify.py "$(mktemp -d)"            # everything below, about 2 min
python3 -I scripts/validation/learning_day/walkthrough.py "$(mktemp -d)"       # the browser part only
python3 -I scripts/demo/learning_day/seed.py http://127.0.0.1:PORT /abs/scratch.db   # the seed alone (empty scratch DB)
```

It runs on synthetic data, a loopback server, a fresh scratch database, and every provider
disabled. The browser part uses real Chromium (Playwright 1.49.1, disposable container) with
reduced motion emulated, in three combinations: desktop 1280×900 English, 320×640 Chinese and
320×640 English.

## The day (`walkthrough.mjs`; every step is checked)

**Seed** (API only, plus one scratch-DB edit):
- A workbook listening script imported, two of its questions saved as mistakes.
- Speaking: take 1 typed, take 2 typed and then corrected by the learner.
- A Writing task with a draft and a revision.
- Revision 1 of the script reworded as an older pack had it, so a pack update is waiting.

1. **Note → practice.** Mistake Notebook → **Make practice**:
   1. Select both notes, then **Preview 2 drafts** (focus moves to the preview).
   2. Rewrite question 1 as `Pourquoi Hélène préfère-t-elle étudier le soir ?⏎« Ça dépend… » —
      c’est l’hôpital Saint-Éloi.`
   3. **Alt+↓** goes to question 2; **Ctrl+Enter** approves both into Review Today.
   4. **Practise these drafts now** shows the edited wording exactly: accents, guillemets and the
      line break.
2. **Review Today.**
   - The queue is the Speaking step (`review_without_feedback`, take 2), then both notes
     (`retry_marked`).
   - Each row says "Based on: …".
   - **↓** moves to the next item. **Hide for this visit** moves focus to the next item, and
     **Show hidden items** brings the row back.
   - **This week**: production practice 3 (in 2 exercises), reviewed 2, your corrections 2,
     feedback received 0, active days 1 of 7. The week is sparse, so counts only.
3. **Speaking.** **Resume take 2**:
   - Focus lands on take 2.
   - It reads "Audio: none (a typed take)" and "Transcript: version 2, corrected", and
     "Version 2 is your correction of the transcript."
   - **← Back to Review Today** returns to the queue.
4. **Revision.** A note's **Open the lesson**:
   1. Review the pack update and confirm it: revision 2.
   2. **Revision history** compares revision 1 → revision 2. The older line's ` Voilà.` is
      labelled `removed:`, and unchanged lines are folded.
   3. **Preview restoring revision 1** says "Revision 3 is added…".
   4. **Not now** returns focus to the button that opened the preview.

**At every step:** every control is named, ids are unique, nothing moves, and on 320 px there is
no horizontal scroll and the week table shows all its columns. There are no page errors.

**This run:** 89/89 checks pass. The six screenshots per combination (`01-practice-preview` …
`06-restore-preview`) are in `handoff-100/evidence/learning-day/shots/`.

## Sample queue: every status a reader should recognize

Review Today orders by priority, then the item waiting longest, then source, then key.

| Priority | Reason code | Source | What the row says (English copy) | Its action |
|---|---|---|---|---|
| 0 | `check_unknown_outcome` | Speaking | Take 2: the outcome of its feedback request is unknown. Check it before requesting again. | Resume take 2 |
| 1 | `request_failed` | Speaking | Take 1: its transcription failed. Send it again, or type what you said. | Resume take 1 |
| 2 | `confirm_transcript` | Speaking | Take 3: a machine transcript is waiting for your check. | Resume take 3 |
| 3 | `add_transcript` | Speaking | Take 1: type what you said. | Resume take 1 |
| 4 | `request_feedback` | Speaking | Take 1: your checked transcript has no feedback yet. Request it when you are ready. | Resume take 1 |
| 5 | `review_without_feedback` | Speaking | Take 2: your checked transcript has no feedback, and feedback is off. Review it against the prompt's requirements yourself, then answer again. | Resume take 2 |
| 6 | `answer_again` | Speaking | Take 1: the feedback suggests 4 improvements. Answer again using them. | Resume take 1 |
| 6 | `retry_marked` | Workbook | You marked this for retry on 19/11/2026. | Open the lesson · Done for today |
| 7 | `start_first_take` | Speaking | Started, no take yet. | Open the exercise |
| 8 | `request_in_progress` | Speaking | Take 1: its feedback is still being prepared. Check again in a moment. | Resume take 1 |
| — | `not_started` | — | never queued: a prompt not started is not due | — |

**Attempt states** in a take's history:
- `awaiting_transcript` ○ Next
- `transcribing` … In progress
- `transcription_failed` ! Recoverable
- `transcription_unknown` ? Interrupted
- `transcript_to_confirm` ○ Next
- `awaiting_feedback` ○ Next
- `feedback_in_progress` … In progress
- `feedback_failed` ! Recoverable
- `feedback_unknown` ? Interrupted
- `feedback_ready` ✓ Completed

## Scope and privacy, next to each decision

| Decision the learner sees | Assumption it rests on |
|---|---|
| Edited practice wording, second versions, answers and self-checks stay in the page | Nothing is stored without a table the owner approved. A reload loses them, and the page says so |
| Approving a draft puts the note in Review Today | Uses the existing retry mark: one per record, append-only, never a score |
| "Hide for this visit" on a Speaking step | Page-only. A persisted defer waits for `review_defers` (013–014) |
| The browser's time zone is sent with Review Today and This week | It goes to the learner's own server only. It is never stored or logged as data, and an unknown zone is refused |
| This week shows counts, and a percentage only from 20 actions | Small samples make claims misleading. Nothing is scored |
| Corrections against the machine transcript are text only | A difference may come from the transcriber. It is never a pronunciation grade |
| Audio plays only inside the page | Audio is never stored or exported. It leaves the browser only on an explicit, confirmed transcription request (existing rule) |
| Exports include transcripts and notes only on request | The default export holds metadata only. Credentials and configuration are never read |
| "Check an export file" never writes | There is no import. A conflict is resolved as "keep stored" |
| Restoring a revision adds a new revision | History is append-only. Notebook records keep the wording they were saved from |
| Everything here is private | None of these routes is on the public demo's allowlist (tested) |

## Which workflows actually run, and which remain experiments

| Workflow | State |
|---|---|
| Review Today queue (both sources, reasons, based-on, Done for today, resume) | **Runs** (browser and API tests) |
| Make practice from notes (preview, edit, approve, practise now) | **Runs**. Storing edited wording is **blocked**, so it is page-only |
| Revision studio (history, compare, restore preview, restore as a new revision) | **Runs** (API and UI tests; browser compare and preview) |
| Speaking workspace (status, attribution, edits, next actions) | **Runs** |
| This week | **Runs** |
| Portable history export, check and CLI | **Runs**. There is no import, by design |
| Spaced-practice recommendations (`NextRecommendation`, `ScheduleInputsFromExport`) | **Experiment**: pure functions, tests only. Not shown in the workbench |
| Defer and undo (013–014), stored practice prompts (021/023/026), personal correction into Review Today (047) | **Proposals** waiting for a migration number |
| Old-server stage of the 021 rehearsal | **Owner-only**: needs a server built from `45be549…` |

## Known defects and limits, each with a synthetic reproduction

| # | Defect or limit | Reproduce |
|---|---|---|
| D1 | `src/demo/SharedLinks.test.tsx` "offers a concrete way on" is load-sensitive (`expected '' to be '#example=y-en'`). It is a public-demo file this batch did not change | `cd web && NODE_OPTIONS=--no-experimental-webstorage npx vitest run --maxWorkers=4 --minWorkers=1` failed in 1 of 3 full runs this session (handoff 050); alone it passed 21/21, twice |
| D2 | The Review Today response grows about 1.1 KB per item (each item carries its source JSON) | `python3 -I scripts/validation/review_today/load.py "$(mktemp -d)"`: 123 items → 134,982 bytes |
| D3 | A kill inside migration 021's transaction was not observed (the kills landed before or after it) | `older_fixtures.py` with the rehearsal 020 copy: kills at 0/20/80/300 ms |
| D4 | `Reading.tsx` scrolls with `behavior: "smooth"` even under `prefers-reduced-motion` (another lane's file; proposal in handoff 075) | Emulate reduced motion and jump to a Reading evidence line |
| D5 | Edited practice wording is lost on reload (by design until `practice_prompts`) | Make practice → edit a question → reload |
| D6 | This week sees only a record's current retry state: an earlier "done" on another day is not counted | Mark then unmark a record on day 1, and again on day 2: only day 2 is counted |
| D7 | A Speaking take counts as production on the day its first transcript was confirmed, not the day it was recorded | Record late on day 1, confirm the transcript on day 2: it counts on day 2 |
| D8 | "Based on" lines show raw reason codes, in Chinese too (wire values are never translated, for traceability) | Review Today in 简体中文 |
| D9 | The browser walkthrough's Chromium runs in UTC, so zone handling is proven by Go and jsdom tests (Europe/Paris, Asia/Shanghai, New York DST), not in the browser | `walkthrough.mjs` "zone (UTC)" text |
| D10 | A learner Writing task's export key uses its creation time; two tasks created in the same nanosecond would share a key (theoretical) | — |
