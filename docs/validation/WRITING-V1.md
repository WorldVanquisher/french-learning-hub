# Exam Writing v1 — validation

Owner: Claude Code (sole implementation owner). Date: 2026-11-09 (UTC).
Built on a scratch copy of the Daily Listening working tree **with Exam Reading
v1 applied**. The owner applies it as an incremental patch after Reading; see
the handoff report for the baseline hash.

**Status: implemented and tested** against a local fake provider, with real
SQLite, the real handler, the real server binary in the packaged image, and
real Chromium 156.
- **Real model:** not used.

Contract: [ARCHITECTURE.md §4.6](../ARCHITECTURE.md#46-exam-writing-v1) and
Appendix A.18. Owner walkthrough: [DAILY_USE.md §12](../DAILY_USE.md#12-writing-practice).
Content: `internal/writing/prompts/writing_prompts_v1.json`, three authored
practice tasks (`flh_writing_prompts_v1`), each with an example draft that
contains deliberate mistakes. The set is validated at startup. Model output
fixture: `internal/writing/testdata/invitation_feedback.json`.

## Acceptance

| Requirement | Evidence | Result |
|---|---|---|
| Authored or own prompt; word convention shown; immutable versions | Go: `TestWriting_WholeLoopOnTheAuthoredDraft` (start twice replays; v1 byte-identical after v2; identical text refused `409 unchanged`); `…DraftingWorksWithoutAProvider…` (own task, invalid range and blank prompt `422`); domain: `TestCountWritingWords_FollowsTheDisplayedConvention`. Chromium: prompt, points, range, convention and practice notice shown; database: v1 SHA-256 equals the authored example draft | pass |
| One explicit call for one selected version, with task fulfilment, clarity and bounded corrections (quote, hint, suggestion, reason) | Go: one model call per request, the report's `draft_id` is the requested version; `TestOpenAI_RequestDisciplineAndServerSideGrounding`; `TestValidateWritingFeedback_RefusesUnusableOutput` (unknown rating or category, more than 8 corrections, a suggestion equal to its quote, blank or oversized fields). Chromium: one keyed POST for version 1 | pass |
| Quoted spans verified; a repeated fragment gets no invented location | Domain: `TestValidateWritingFeedback_GroundsQuotesAgainstTheExactDraft`. Go integration: v1 groundings `located,located,ambiguous,not_found`, with rune offsets 210 and 314 pinned; the model cannot send grounding (`invalid_output`); every invented quote → `not_found`. jsdom and Chromium: « Je suis » (three times in v1) shows "appears more than once … no position"; a missing quote is listed under **Not found in this version**, never as a correction | pass |
| A failed or unknown request never loses a version | Go: `TestWriting_FailedAndUnknownRequestsNeverLoseAVersion` (provider 500 → `failed`; a dropped connection → `unknown`; without acknowledgement `409`, no call; v2 is not blocked; with acknowledgement one call; a lost response is found by key and a same-key resend replays with no call; both texts intact). Chromium: a claimed-grounding output is refused (`502`); a timeout after sending is `unknown` (`504`) with no retry; the acknowledged retry sends `confirm_unknown_retry` under a new key; versions intact | pass |
| No background grading, automatic retries or score claims | Go: reads never call; the rating is a label. Chromium: exactly 4 model calls for 4 clicks; none on reads, saves, compares, reveals or after a restart. "There is no score, mark or level" is shown | pass |
| Revise from hints before the suggestion is revealed; new version; compare; each report shows its version; nothing carried over | jsdom and Chromium: hints visible and suggestion hidden; the editor starts from v1; **Save as version 2**; "Feedback on version 2", "Other versions have their own feedback (v1)", no report on v2; word diff v1 → v2; back on v1 its report is unchanged. After v2's own request, the three quotes fixed in v2 are `not_found` there and only « Je suis » (now once) is located | pass |
| Capture one mistake as an ordinary learning record with a link back | jsdom and Chromium: nothing sent when the form opens; one `learning_capture_v1` (`source: manual`, exact keys). The input is `« phrase » → « revised wording »` plus the stored reason. The context names the task, authored prompt, version, feedback and generator. **Open record #N** → **← Back to Writing**. Database: 1 capture, 1 entry, 0 Concepts, 0 analyses | pass |
| Explanation-language preference; zh-CN | jsdom: the `zh` preference hides the English hint; the zh-CN tab, button and labels render, and French stays as written | pass |
| Disabled provider | Go: `503`, no attempt stored; tasks and drafts work. jsdom: no request button, an explanatory notice | pass |
| Public demo | Go and jsdom: not routed, no tab, no `/writing` call. A fresh FLH-073 artifact on this tree: the smoke passes, the ledger includes `017`, and the four Writing tables are empty. A live probe of 8 Writing routes at root and `/api` (16 requests): `404` GET, `405` POST | pass |
| Packaged image | `flh-daily.sh up` builds the image from this tree; it serves the 3 embedded prompts and logs `writing provider: openai` | pass |

## Commands and results

| Command | Result |
|---|---|
| `go test -race -count=1 ./internal/domain ./internal/writing ./internal/config ./internal/storage/sqlite ./internal/application ./internal/transport/http ./internal/publicdemo ./cmd/server` | ok (8 packages) |
| `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/pages/Writing.test.tsx` | 12 pass |
| 8 mutations of `Writing.tsx`, each restored: suggestion shown at once, `not_found` shown as grounded, no key lookup after a lost response, feedback carried over to another version, a reload unmounting an unsaved revision, an ambiguous quote given a position, no acknowledgement after unknown, a new key on resend | all caught |
| Wrapper test (`scripts/validation/flh094/test_wrapper.sh`) | `{"failures": 0}`, 75 checks (4 new `WRITING_PROVIDER` cases) |
| Packaged Chromium walkthrough: isolated Compose project, the fake model in a sidecar on the app's loopback, a disposable database | 44 checks, 0 failures (loop 24, refused output 5, unknown outcome 4, acknowledged retry 7, reopen after restart 4); 4 model calls; daily instance unchanged |
| `NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0: 22 Go packages, 29 files / 364 frontend tests, build |

## Not verified, and limits

- **Real model:** the prompt and the quality of the feedback have not been
  tried with a real model. Grounding checks only that a quote exists in the
  text; it says nothing about whether the correction is right.
- **Authored prompts** were reviewed by their author only. "A2" describes the
  intended style; it is not a certified level.
- **Quote matching is exact** (no normalisation). A model that changes an
  apostrophe or a space gets `not_found`.
- **A lost response to "Start this task" or "Save as version N"** is not
  keyed. Starting replays safely. A repeated save of the same text is refused
  as unchanged, so it cannot duplicate a version; the UI asks the learner to
  reopen the task to check.
- **Other browsers** than Chromium 156 headless, and narrow screens, were not
  exercised in a real browser.
