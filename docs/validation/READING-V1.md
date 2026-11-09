# Exam Reading v1 — validation

Owner: Claude Code (sole implementation owner). Date: 2026-11-09 (UTC).
Built on a scratch copy of the Daily Listening working tree. The owner applies
it as a patch; see the handoff report for the baseline hash.

**Status: implemented and tested** against a local fake provider, with real
SQLite, the real handler, the real server binary in the packaged image, and
real Chromium 156.
- **Real model:** not used.

Contract: [ARCHITECTURE.md §4.5](../ARCHITECTURE.md#45-exam-reading-v1) and
Appendix A.17. Owner walkthrough: [DAILY_USE.md §11](../DAILY_USE.md#11-reading-practice).
Content: `internal/reading/pack/reading_pack_v1.json`, six authored passages
(`flh_reading_pack_v1`) validated by the pack's own `validate_pack.py` and,
again, at server startup.

## Acceptance

| Requirement | Evidence | Result |
|---|---|---|
| Create and reopen; wording and paragraph IDs kept; source link stored, never fetched | Go: `TestReading_CreateReopenAfterRestartKeepsWordingAndParagraphIDs` (a new server over the same file; the segments are byte-identical to the pack's); Chromium: reopen after `flh-daily.sh restart` | pass |
| Authored example without a model call; import again replays | Go: `…AuthoredExampleImportsWithoutAModelCall` (6 examples, `authored:flh_reading_pack_v1`, inference item with its wrong answer, re-import `200`, authored text cannot be replaced, 0 calls); Chromium: one POST, no `/exercises` | pass |
| Generated exercise validated against the exact passage version | Go: `…GeneratedExerciseIsValidatedAndTiedToItsPassageVersion` (inference kept and labelled; a new version gets its own exercise; the first stays on v1) | pass |
| Wrong or invented citation, provider failure | Go: `…InvalidCitationsAndProviderFailurePreserveThePassage`: a wrong paragraph, an invented excerpt, an excerpt that occurs twice, and HTTP 500 each give `502` with a stored `failed` exercise; the passage is byte-identical; the next explicit request succeeds. Chromium: a citation that is not in the article is refused and shown | pass |
| Unknown outcomes and lost responses | Go: `…UnknownOutcomesAndLostResponsesNeverCallTwiceSilently`: a dropped connection gives `unknown`; without acknowledgement `409`, no call; with it, one call; a lost response is found by key, and a same-key resend gives `200` with no call | pass |
| Reading, answering and revealing make no model call | Go: repeated reads, 0 calls; jsdom: only the import request; Chromium: 0 model calls through the authored walkthrough, and none after restart | pass |
| Passage visible; answers, explanations, highlights hidden until reveal; jump to the excerpt | jsdom and Chromium: paragraphs with IDs visible; no `<mark>` and no reference, explanation or wrong answer before reveal; **Show in the passage (pN)** marks the exact excerpt in that paragraph; the typed answer is kept | pass |
| English/Chinese explanation preference; inference labelled; practice label | jsdom: the `zh`-only preference hides English; zh-CN labels; "Inference — not stated directly in the text"; "not an official exam assessment" | pass |
| Missed point only on explicit action, via the capture path, with a route back | jsdom and Chromium: nothing sent when the form opens; one `learning_capture_v1` (`source: manual`, exact keys) naming the lesson, authored example, question and excerpts; **Open record #N** → **← Back to Reading** with answers kept. Go: traceable entry, 0 Concepts | pass |
| Disabled provider | Go: `503`, no attempt stored; examples still import | pass |
| Public demo | Go: every route `404` (GET) / `405` (POST) at root and `/api`; a fresh FLH-073 artifact (ledger includes `016`, the four tables empty) validates and its smoke passes; live probe of 14 Reading routes in demo mode | pass |
| Packaged image | The first `flh-daily.sh up` **failed**: the pack was embedded from `examples/`, which the image build does not copy. It moved to `internal/reading/pack/`; the image then builds, and `/reading/examples` serves 6 examples from the image | fixed, pass |

## Commands and results

| Command | Result |
|---|---|
| `go test -count=1 -race -run Reading ./internal/transport/http` | 8 integration tests pass |
| `go test -count=1 ./internal/domain ./internal/reading ./internal/config` | ok (domain parsing, validation, pack; generator discipline and failure classes; config) |
| `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/pages/Reading.test.tsx src/i18n/i18n.test.tsx` | 8 + 13 pass |
| 7 mutations (each restored): accept a repeated excerpt, accept an invented excerpt, a model call on import, retry an unknown outcome without acknowledgement, answers before reveal, a highlight before reveal, a capture when the form opens | all caught |
| Wrapper test (`scripts/validation/flh094/test_wrapper.sh`) | `{"failures": 0}`, 71 checks (4 new `READING_PROVIDER` cases) |
| Packaged Chromium walkthrough: isolated Compose project, the fake model in a sidecar on the app's loopback, a disposable database | 34 checks, 0 failures (authored 22, own passages 7, reopen 5); 2 model calls in total; daily instance unchanged |
| `NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0: 21 Go packages, 28 files / 352 frontend tests, build |

## Not verified, and limits

- **Real model:** the prompt and the quality of generated questions have not
  been tried with a real model. A real model may cite an excerpt that occurs
  twice, or paraphrase one; each is refused and stored as `invalid_output`.
- **The authored pack** was reviewed by its author only (see the pack's
  `REVIEW.md`). "A2–B1 style" describes the writing; it is not a certified
  level.
- **A lost response to "Use this example"** is safe to repeat (it replays) but
  is not keyed.
- **Other browsers** than Chromium 156 headless; narrow screens use a single
  column, which was not exercised in the browser.
