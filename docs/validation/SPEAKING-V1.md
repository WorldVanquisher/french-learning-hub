# Speaking v1 — validation

Owner: Claude Code (sole implementation owner). Date: 2026-11-09 (UTC).
Built on a scratch copy of the Writing v1 tree (Daily Listening, Reading v1
and Writing v1 applied). The owner applies it as an incremental patch after
Writing; see the handoff report for the baseline hash.

**Status: implemented and tested** against local fakes of the transcription
and Responses endpoints. The tests used real SQLite, the real handler, the real
server binary in the packaged image, and real Chromium 156 recording from its
fake capture device fed with a synthetic WAV.
- **Real provider:** not used. **Real voice:** not used; the audio is
  synthetic, and the fake transcriber returns a fixed transcript.

Contract: [ARCHITECTURE.md §4.7](../ARCHITECTURE.md#47-speaking-v1) and
Appendix A.19. Owner walkthrough: [DAILY_USE.md §13](../DAILY_USE.md#13-speaking-practice).
Content: `internal/speaking/prompts/speaking_prompts_v1.json`, three authored
practical prompts (`flh_speaking_prompts_v1`), each with an example transcript
that contains deliberate mistakes. The set is validated at startup. Feedback
fixture: `internal/speaking/testdata/invitation_feedback.json`.

**Provider facts checked before the adapter was written**, from the provider's
speech-to-text guide and its Create transcription reference:
- the limit is 25 MB;
- the guide lists mp3/mp4/mpeg/mpga/m4a/wav/webm; the reference also lists
  flac and ogg;
- `gpt-transcribe` is recommended, and older models shut down on 2027-02-26;
- `gpt-transcribe` takes `languages` instead of `language`.

FLH accepts only the formats both pages list. It sends `file`, `model` and
`response_format=json`: no language field and no prompt. Its own limits are
8 MiB and 120 s.

## Acceptance

| Requirement | Evidence | Result |
|---|---|---|
| Three original practical prompts (invitation, information, change of plan) | Go: embedded set parsed and validated; malformed sets refused. Chromium: both started prompts are rendered, with the practice notice ("cannot judge pronunciation … no score") | pass |
| Record a short take in the browser, play it back, try another take; no provider call while recording or playing back | Chromium: a webm take of about 3.5 s is recorded from the fake device and played back (≥ 1 s of playback). There is no request at all while recording or playing back, and the fake log is empty. A second take is recorded later. jsdom: the fake recorder path, and no request before **Use as take 1** | pass |
| Denied permission, unsupported browser, file and typed fallbacks | Chromium (`--deny-permission-prompts`): "Microphone permission was refused, so nothing was recorded", no request, both fallbacks offered, the typed take confirmed as `typed`. Chromium (`MediaRecorder` removed): "This browser cannot record audio here", no record button. The synthetic WAV upload is previewed (0:06, 188 KB, audio/wav) and played back, then stored as metadata only (`file`, size, SHA-256, 6000 ms). jsdom: ogg refused before anything is sent; a missing device has its own message | pass |
| Opt-in transcription for one selected take; formats and limits; show when audio is sent; no raw audio stored | Go: type, size, magic bytes, "not this take's audio" and typed-take refusals all happen before any call (no request row, no fake call). The adapter sends `take.<ext>` with its type, `model` and `response_format=json` only. No column can hold audio, and no 32-byte window of the audio is in the database or its WAL. Chromium: the panel names the take, length, size, `audio/webm` and the transcriber; **Cancel** sends nothing. **Send audio** makes one keyed POST whose decoded body starts with the WebM magic and whose SHA-256 equals the take's and the one the fake received. After the run, the database and WAL scan finds no informative window of either audio file | pass |
| Correct the transcript before feedback; versions are immutable | Go: confirming against the machine transcript is `corrected` (edited) or `transcription` (unchanged); an identical text is refused `409 unchanged`; a foreign transcription is `422`. Chromium: the editor holds the machine transcript with both slips; one slip is fixed and confirmed as v1 (`corrected`), the other later as v2; take 2's machine transcript is confirmed unchanged (`machine transcript, confirmed`) | pass |
| Feedback on task fulfilment, clarity and a few grounded improvements, tied to that exact transcript version; no pronunciation or score claims | Domain: quotes grounded `located,located,ambiguous,not_found` (rune offsets 100 and 166). Pronunciation, accent and intonation comments, 发音, score, CEFR and exam claims, and spelling or pronunciation categories are refused; more than 4 improvements are refused. Go: a pronunciation comment from the model is stored as `invalid_output`. Chromium: "About take 1, transcript version 1 (generator)", "nothing here is about pronunciation", hints before the suggestion, the located quote marked, the repeated « très » without position, the invented quote listed apart | pass |
| A failed provider request | Go: transcription 500 → `failed`; a dropped transcription → `unknown`, then `409 outcome_unknown` until acknowledged; feedback timeout → `504 unknown`; a lost response is found by key and replays on resend; transcripts intact. Chromium: feedback 500 → "The last request failed: the provider was unavailable. Nothing was retried." The transcript is unchanged and no report is shown | pass |
| Feedback still refers to the original version after a revision | Go: after v2, the only report has `transcript_id` = v1. Chromium: v2 is selected with no report; "Other versions of this take have their own feedback (v1)"; back on v1, the report still reads "About take 1, transcript version 1"; v1's text is unchanged; and after a restart all of this holds | pass |
| Compare confirmed transcripts of two takes | jsdom and Chromium: "Compare: Take 1 · v2 → Take 2 · v1", with `je suis arrivé` struck through and `j'arriverai` / `apporter` added | pass |
| Capture one recurring mistake with a link back to the exercise | Chromium: nothing is sent when revealing or opening the form. One `learning_capture_v1` (`source: manual`): `« je suis arrivé vers midi et demi » → « j'arriverai vers midi et demi »` plus the stored reason, and a context naming the exercise, the authored prompt, take 1, transcript version 1 (corrected), the feedback and the generator. **Open record #N** shows it; **← Back to Speaking** returns to the exercise. Database: 1 capture, 1 entry, 0 Concepts | pass |
| Disabled providers | Go: transcription `503` before the body is read, feedback `503`, nothing recorded, the typed flow works. jsdom: notices and no buttons | pass |
| Public demo | Go and jsdom: not routed, no tab. A fresh FLH-073 artifact on this tree: the smoke passes, the ledger includes `018`, and the seven Speaking tables are empty. A live probe of 10 routes at root and `/api` (20 requests): `404` GET, `405` POST | pass |

## Commands and results

| Command | Result |
|---|---|
| `go test -race -count=1 -run Speaking ./internal/transport/http/` | 4 integration tests pass |
| `go test -race -count=1 ./internal/domain ./internal/speaking/... ./internal/config` | ok |
| `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/pages/Speaking.test.tsx src/i18n` | 23 pass (10 Speaking, 13 i18n) |
| 12 mutations, each restored: audio digest check, magic bytes, pronunciation/score refusal, server-side grounding, no language field, unchanged transcript, unknown-outcome acknowledgement, origin decided server-side, audio only after the panel, metadata-only take, feedback per version, permission refusal message | 12/12 caught |
| Wrapper test (`scripts/validation/flh094/test_wrapper.sh`) | `{"failures": 0}`, 82 checks (7 new Speaking cases, one shown below) |
| Packaged Chromium walkthrough, run with `run_browser_speaking.sh` in the handoff | 67 checks, 0 failures (refuse 8, unsupported 10, record 15, fail 4, feedback 12, take 2 6, capture 5, reopen after restart 7); 2 transcription calls and 2 feedback calls; daily instance unchanged |
| `NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0: 23 Go packages, 30 files / 374 frontend tests, build |

The wrapper also accepts transcription without a text model
(`SPEAKING_TRANSCRIPTION_PROVIDER=openai` and `SPEAKING_TRANSCRIPTION_MODEL`,
no `OPENAI_MODEL`), as the server does.

## Not verified, and limits

- **Real provider and real voices:** the transcription quality, the feedback
  prompt and its usefulness are untested. Grounding checks only that a quote is
  in the text.
- **Duration** is measured by the browser; the server cannot decode audio. It
  enforces the byte limit, the type, the magic bytes and that the audio sent is
  the take's.
- **Audio after a reload is gone by design.** A take whose audio was lost can
  still have its transcript typed or corrected. An unknown transcription outcome
  can only be retried while the audio is still in the page.
- **Browsers:** only Chromium 156 headless was exercised for real (webm/opus).
  Safari records `audio/mp4` (accepted), but it was not run. A browser that
  records only ogg can play back and type, not transcribe.
- **Authored prompts** were reviewed by their author only; "A2–B1" describes the
  intended style, not a certified level.
