# Speaking practice queue, attempts and workbook revisions (2026-11-18)

Evidence record for the workbooks lane's batch of 20 work packages. All runs used synthetic
data on loopback. Providers were either off or pointed at a local fake (OpenAI-shaped, fixed
placeholder key). No migration (ledger 21), no external call, no audio stored. The tools named
here live in the lane's handoff folder, not in the repository.

## The reproduced gap (item 1)

One synthetic history goes through the real server, which is restarted with the providers
switched on and off (`queue_matrix.py`, 27 checks):

| Phase | Exercise state | Baseline build | This build |
|---|---|---|---|
| Feedback unavailable (500) | `feedback_failed` | `request_failed` | `request_failed`, `feedback`, enabled |
| Lost answer (dropped) | `feedback_unknown` | `check_unknown_outcome` | same, `feedback`, enabled |
| Transcription unavailable | `transcription_failed` | `request_failed` | same, `transcription`, enabled |
| Both providers off | the three above | same reasons, nothing says the request cannot be sent | same reasons, `request_enabled: false` |
| Typed transcript, feedback off | `awaiting_feedback` | **no step: the exercise disappears** | `review_without_feedback`, `feedback`, disabled; `resume` names it |
| Page reload | same | still missing | same queue |
| Feedback back on | `awaiting_feedback` | `request_feedback` | `request_feedback`, enabled |
| Request running | `feedback_in_progress` | **no step: the exercise disappears** | `request_in_progress` |
| Retries (one after an explicit unknown-outcome confirmation) | `feedback_ready` | `answer_again` | `answer_again`; 3 completed, `resume` null |

Result: baseline 11/27, this build 27/27.

## Contract (additive; `speaking_practice_v1`)

- Every started exercise whose latest take is not complete has a step whatever the providers'
  configuration. Only a complete take whose feedback raised nothing has none.
- Reasons, with their ordinal priority:

  | Priority | Reason | Note |
  |---|---|---|
  | 0 | `check_unknown_outcome` | |
  | 1 | `request_failed` | |
  | 2 | `confirm_transcript` | |
  | 3 | `add_transcript` | |
  | 4 | `request_feedback` | |
  | 5 | `review_without_feedback` | new |
  | 6 | `answer_again` | was 5 |
  | 7 | `start_first_take` | was 6 |
  | 8 | `request_in_progress` | new |
  | 9 | `not_started` | was 7 |

- Queue item fields: `request` (`transcription`/`feedback`/null), `request_enabled`, and
  `pack_status` (null for prompts not started).
- Response field: `resume`.
- A completed report on the latest version completes the take. A later request on the same
  version no longer makes it read as in progress, so the completed count no longer dips.
- Take save: a typed save names the latest take (`200`, replayed) while that take is typed and
  has no transcript.
- Exercise view: `current_prompt` (the set's corrected wording when `pack_status` is
  `changed`).
- Script update preview:
  - lines are aligned by content;
  - new fields `before_line`, `after_line` and `lines_renumbered`;
  - equal-length edits are listed exactly as before.

## Items

| # | Status | Evidence |
|---|---|---|
| 1 | Reproduced, defined | table above |
| 2–3 | Implemented | `speaking_queue_integration_test.go` (4 tests); web "keeps every started exercise actionable…" |
| 4 | Implemented | Fixes: lost-answer check on transcript confirmation; "unchanged" after a lost answer recognised as saved; re-attach hint after a reload. Web tests "finds a confirmed transcript…", "says a transcript was not saved…", "after a reload…" |
| 5 | Implemented | Typed-take replay in the save transaction; recorder check for a typed save. `TestSpeakingTakes_TypedSaveNamesTheEmptyTypedTake`; web lost and dropped typed save |
| 6 | Verified | `take_replay.py`: a proxy commits and then drops the answer, plus 12-way concurrency. Baseline 5/9 (a typed resend made a second take; 12 concurrent typed saves made 12); this build 9/9. `TestSpeakingTakes_ConcurrentTypedSavesMakeOneTake` (`-race`) |
| 7 | Implemented | Comparison: earlier feedback points looked up in the later transcript (text check). Web tests |
| 8 | Implemented | `resume` and **Continue where you left off**; focus lands on the take (browser: focused and on screen in all 4 runs) |
| 9 | Implemented | Answered wording with its revision, `current_prompt` read-only, revision on each take and in Attempts |
| 10 | Documented | Needs a migration: `docs/plans/SPEAKING-PROMPT-REVISIONS.md` |
| 11 | Covered (listening), implemented (Speaking) | Notebook and retry cards name script revisions (existing tests); Speaking attempts name their prompt revision |
| 12 | Verified | `TestListeningScriptRevisions_SecondUpdateKeepsEarlierMistakesAndEvidence` (revisions 1 → 2 → 3) |
| 13 | Implemented | Content-aligned line diff (`TestDiffListeningScript_AlignsLinesByContent`); renumbered lines folded in the preview (web test) |
| 14 | Gap fixed, rest covered | Review after another tab updated: no phantom "revision 3", answers kept, nothing written (web test); cancel, stale preview, lost response, concurrent confirmations re-run |
| 15 | Verified | `TestSpeakingExport_CarriesRevisionTranscriptAndFeedbackProvenance`; real binaries with a corrected-prompt build, `pack_change.py` 9/9 |
| 16 | Verified | Restore and upgrade from the predecessor build (`c53b42c`) with Speaking data: 29/29. Browser: after a reload, audio gone, re-attach offered, another file refused, the same file accepted (4/4 runs) |
| 17 | Verified | `TestSpeakingQueue_MixedHistoryCountsAndNextActions` and the matrix above |
| 18 | Verified; highest friction fixed | Real Chromium, en and zh, phone 390×844 and desktop, fresh database: 54/54. **Friction found:** with feedback off, the step said "review it against the prompt's requirements", but Continue landed on the take, screens away from them on a phone. **Fixed:** the take now offers a self-review checklist of the requirements (page-only ticks) with the take's length |
| 19 | Run | `make verify` and the regressions above; mutations of the four main fixes each fail a new test |
| 20 | Delivered | `docs/DAILY_USE.md` §13; compatibility below |

## Compatibility

- **Existing attempts.**
  - No migration, and no stored row is read differently.
  - States are derived on read. The one state change: a take with completed feedback on its
    latest version whose later re-request is still running now reads `feedback_ready` (it was
    `feedback_in_progress`).
  - Duplicate typed takes created by earlier builds stay as they are; a new typed save names
    only the latest take.
- **Exports** (`speaking_attempt_export_v1`).
  - Unchanged fields and order.
  - A take's `state` follows the rule above.
  - Lines written before keep their meaning.
- **Practice overview.**
  - New fields are additive.
  - `priority` numbers changed for `answer_again`, `start_first_take` and `not_started`. They
    are ordinal: compare them, do not store them.
  - The reason texts behind `check_unknown_outcome`, `request_failed` and `add_transcript` are
    now specific per request.
- **Script previews.**
  - New fields are additive.
  - For scripts whose line count changes, previews list fewer, accurate line changes.
- **Backups.**
  - Unchanged format.
  - In the rehearsal from `c53b42c` (29/29):
    - a backup of the predecessor's database restores into this build;
    - after this build's first write, the predecessor still reads the database (binary-only
      rollback).
  - Audio was never in a backup. After a restore, re-attach the same file or type the
    transcript.
