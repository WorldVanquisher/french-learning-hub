# Mock Exam v1 — validation

Owner: Claude Code (overnight stack, 2026-11-10 UTC). No earlier Mock Exam
specification, work or handoff existed; this slice was built from the
overnight brief. Migration `020` was verified free (highest was `019`).
Contract: `docs/ARCHITECTURE.md` §4.9 and A.21; walkthrough:
`docs/DAILY_USE.md` §15.

| Requirement | Evidence | Result |
|---|---|---|
| Assembly with immutable references to authored material | Go `TestExam_StartFreezesAuthoredQuestionsAndHidesEveryKey` (frozen copies with content hashes; forms and pack hashes); domain `TestFreezeExamItem_ChoicesComeOnlyFromAuthoredAnswers`, `TestMockExamForms_*` | pass |
| Keys out of responses before submission | the same Go test scans the in-progress JSON for keys, explanations, reasons and evidence; jsdom checks the page | pass |
| Server-owned deadline | Go `TestExam_TheServerDeadlineClosesTheExam` (open at the deadline, refused one second after, expired result from answers saved in time, reads write nothing); jsdom late answer and auto-submit at zero | pass |
| Refresh and reconnect resume | Go resume after 30 s of server time; jsdom remount; Chromium reload | pass |
| Safe repeat submission | Go replay of the same final answers, `409` for other answers, one submission row; jsdom and Chromium lost response → check status / submit again | pass |
| Post-submit explanations linked to the source | Go result items (key, explanation en/zh, authored reason, evidence, pack/passage/question/hash); Chromium evidence highlight | pass |
| Save a missed point and retry a related question | Go: import + capture with the same authored `reading_item`, notebook shows it as authored; related question of the same kind from another passage, never repeated | pass |
| Not in the public demo | Go `TestExam_NotInThePublicDemo`; jsdom; demo artifact (empty tables) | pass |
| `NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0 | pass |

Packaged Chromium (express form, every provider disabled): exam 21 checks,
expiry 5, reopen after restart 3, all passing on the Mock Exam tree; the
assembled stack's run is in the overnight handoff's `START-HERE.md`.

## Limits

- Reading comprehension only; listening, writing and speaking sections need
  authored audio and human grading first.
- 18 authored questions in all, 1–2 authored wrong answers each, so some
  questions have two choices and repeated exams quickly repeat questions.
- The result is a raw count of matches with the authored key: no level, no
  official score and no conversion.
