# Exam Listening Lesson v1 — validation

Owner: Claude Code (sole implementation owner). Date: 2026-11-08 (UTC).
Branch: `feat/listening-lesson-v1` (prepared by the owner).

**Status: implemented and tested** against a local fake provider, with real
SQLite, the real handler and the real server binary.
- **Real browser:** not yet seen. The workbench is tested in jsdom.
- **Real model:** not yet used.

Contract: [ARCHITECTURE.md §4.3](../ARCHITECTURE.md#43-listening-lessons-exam-listening-lesson-v1)
and Appendix A.15. Owner walkthrough: [DAILY_USE.md §9](../DAILY_USE.md#9-listening-practice-with-your-own-transcript).

## 1. What was built

- **Storage:** migration `014_listening_lessons.sql` adds append-only
  `listening_materials`, `listening_transcripts` and `listening_exercises`.
  Source material and generated exercises are separate. Provenance is
  `openai:<model>:listening_exercise_v1`, and a failure keeps its code.
- **API:** private `/listening/materials…` routes. They are refused by the
  public-demo allowlist, and the three tables must be empty in demo artifacts.
- **Provider:** `LISTENING_PROVIDER` (`disabled` by default, or `openai`),
  reusing `OPENAI_*`. It is forwarded by `compose.yaml` and checked by
  `flh-daily.sh`.
- **Workbench:**
  - a **Listening** view: add a video (link, title, optional transcript),
    **Waiting for a transcript**, **Prepare exercise**;
  - a hidden-until-reveal exercise, with reference answers, English and Chinese
    reasons, cited French lines with source timestamps, and notes;
  - session-only self-checks;
  - **Save as a learning question…**, which posts `POST /captures` with
    `source: manual` only after an explicit **Save learning record**.
- **Authored fixture:** `examples/listening/synthetic-lesson.fr.txt`, an
  8-line synthetic French radio item with source timestamps.

## 2. Acceptance checks

| Requirement | Test | Result |
|---|---|---|
| The lesson opens again after a reload | Go: a new server over the same database file (`TestListeningLesson_PrepareReopenAndSaveMissedPoint`). Real binary: restart with the provider disabled. jsdom: remount over a persistent fake server | pass |
| A link without a transcript never produces a lesson | Go: `409`, **0 provider calls**, 0 exercise rows; jsdom: waiting state, no **Prepare exercise**, no exercise POST; real binary: `409` | pass |
| Answers and evidence hidden until reveal | jsdom: no transcript line, reference answer, reason (either language) or note before **Reveal**; afterwards each is present, and the `0:16` link points at `&t=16s` | pass |
| Invalid references and provider failure preserve the source | Go: an out-of-range segment, an invented time (`0:16` in a reason), an invented excerpt and HTTP 500 each give `502` with a stored `failed` exercise (`invalid_output` / `provider_unavailable`); the transcript JSON is byte-identical before and after; all 4 failed attempts are kept, and the next explicit request succeeds. Generator unit tests also refuse an extra `timestamp` field, trailing output, non-JSON output and a timeout | pass |
| A missed point becomes a normal, traceable record only after explicit confirmation | jsdom: opening the form, self-checking and typing send nothing; **Save learning record** posts exactly one `learning_capture_v1` (`source: manual`, the learner's text, a context with the video link at `&t=16s`, the question and the cited line); the record link opens Learning Records. Go: through `POST /captures`, `GET /captures/{id}` and `GET /entries/{id}` it is traceable; Concepts, links, memberships, extractions, analyses and exercises are unchanged | pass |
| Browsing and playback call no provider | Go and real binary: list and detail reads leave the provider call count at 0; jsdom: clicking **Open the video on YouTube ↗** sends nothing; links are `target=_blank rel="noopener noreferrer"` | pass |
| Unavailable in the public demo | Go: through `NewPublicDemoBoundary`, every listening route (root and `/api`) is `404` for GET and `405` for POST; publicdemo: removing the tables from the must-be-empty list fails `TestFingerprint_CoversEveryTableInTheSchema`; jsdom: the demo renders its Library and has no Listening view and no `/api/listening` request | pass |
| Disabled provider | Go and real binary: `503`, nothing stored, `generation.enabled=false`; jsdom: "Exercise preparation is off" and no button | pass |
| English and Simplified Chinese | jsdom: zh-CN labels; the French questions stay French; the reasons follow **Explanation language**; `i18n.test` key and placeholder parity | pass |
| No answer or key leaks | jsdom: typed answers are absent from every request and every `Storage.setItem`; Go: errors never contain the key or transcript text; real binary: the placeholder key is absent from the server log | pass |

## 3. Commands and results

Go 1.27.3, Node v26.13.0, run in `~/workspace/flh-nas-claude`.

| Command | Result |
|---|---|
| `go test -count=1 ./internal/config` (with the new `listening_config_test.go`) | ok |
| `go test -count=1 -run 'Listening\|YouTube\|ParseTranscript' ./internal/domain` | ok |
| `go test -count=1 -v ./internal/listening` | 3 tests pass |
| `go test -count=1 -v -run Listening ./internal/transport/http` | 6 tests pass |
| `go test -count=1 ./internal/publicdemo ./cmd/server ./internal/storage/sqlite` (after adding migration 014) | ok |
| `bash scripts/validation/flh094/test_wrapper.sh <scratch>` (docker shim; only `docker compose config` is real) | `{"failures": 0}`, including 4 new `LISTENING_PROVIDER` cases |
| `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/pages/Listening.test.tsx` | 8 passed. The first run passed but logged a render error from the test's own fake server (wrong demo-info body); the fake was corrected |
| Mutations, each restored afterwards: drop the verbatim-excerpt check; drop the no-transcript guard; drop the listening tables from the demo's must-be-empty list; show answers before reveal; post the capture when the form opens | each failed tests (domain + generator + HTTP; HTTP; publicdemo coverage; 2 jsdom; 1 jsdom) |
| Real-binary smoke (scratch script, not committed): `go build ./cmd/server`; under `unshare -rn`, run with `env -i`, `LISTEN_HOST=127.0.0.1`, a disposable `hub.db`, `LISTENING_PROVIDER=openai` and `OPENAI_BASE_URL` pointing at a loopback fake Responses server; then restart with `LISTENING_PROVIDER=disabled` | **14 PASS, 0 FAIL** |
| `set -o pipefail; NODE_OPTIONS=--no-experimental-webstorage make verify` | **exit 0**: gofmt, Go tests (19 packages ok), vet, builds, typecheck, **27 files / 337 tests**, production build |

## 4. Not verified, and limits

- **Real browser:** layout, the new-tab video link and keyboard flow have not
  been seen in Chromium. The packaged browser smoke does not cover Listening.
- **Real model:** the prompt, the schema and the quality of the questions,
  answers and French notes have not been tried with a real OpenAI model. The
  fake provider proves mechanics only. A real model may refuse, time out under
  `OPENAI_TIMEOUT`, or produce output that validation rejects (for example a
  paraphrased excerpt); each is stored as an honest failure.
- **The learner supplies the transcript.** It is not checked against the video,
  and the timestamps are the source's.
- **A lost response to Prepare** may already have stored an exercise. The UI
  says so and asks for a reload; there is no idempotency key, so a second click
  is a second (possibly billed) request.
- **A line that starts with a clock time** (`8:30 je me lève`) is read as a
  timestamp, so a mixed transcript is refused. Add the source's timestamps to
  every line, or rephrase the line.
- **The public demo:** a demo artifact built before migration `014` is refused
  by a server that has it (ledger check). The deployed demo runs its own pinned
  release and was not touched.
- **Next assignment, not built here:** scheduled discovery and notification.
