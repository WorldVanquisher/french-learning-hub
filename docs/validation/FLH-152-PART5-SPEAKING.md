# FLH-152 part 5: Speaking practice loop (2026-11-17)

Follows `FLH-152-PART4-RESTORE-REHEARSAL.md`. Synthetic data and local fakes
only: servers on loopback, every provider disabled except Speaking, whose
OpenAI base URL pointed at a loopback fake. No real key, no external call, no
container for the service, the daily instance untouched. No migration: the
ledger stays at 21.

## Product discovery (items 1–8)

**Audit.** Speaking v1 (migration `018`) already had the core records:
- one exercise per authored prompt, storing the prompt's wording;
- numbered takes with audio metadata only;
- machine transcriptions and their attempt-first requests;
- confirmed transcript versions (`transcription`, `corrected`, `typed`);
- feedback reports tied to one version, with their requests;
- Notebook captures (`speaking_improvement`) that link a mistake to report
  item N and open the exercise at that take and version.

Confirmed gaps, reproduced on the unchanged build:

| Gap | Before | After |
|---|---|---|
| What to do next, what is done | the list showed "N takes" only; no route | `GET /speaking/practice`: summary, queue with reasons, per-exercise progress |
| A take's state | derived piecemeal in the browser | `state` on every take, one backend rule |
| Resent save (lost response, double click) | `201`, `201`: two takes with the same SHA-256; the page then took "the last take" | `201`, `200 Idempotency-Replayed`: one take; `take_id` names it |
| Audio after a reload or a restore | nothing offered: the take could never be transcribed | **Choose the same audio file again** (same SHA-256 only) |
| A prompt corrected after it was started | the list opened the old exercise silently; the exercise showed the set's new example beside the old wording | `pack_status: changed`, a notice, no example; the takes keep their wording |
| Export | no route (`404`) | `GET /speaking/export`, NDJSON |

**Three practice workflows considered.**
1. **Task repetition with feedback** (Bygate's task-repetition studies): do
   the same task again after attention to form. Second performances tend to
   gain fluency and accuracy. This is what the stored records already
   support: take → checked transcript → feedback → take again → compare.
2. **4/3/2 fluency practice** (Maurice 1983; Nation 1989): the same content
   three times in shrinking time. Takes and the prompt's duration range could
   carry it, but it needs timing goals. Deferred.
3. **Shadowing a model answer**: needs model audio (speech synthesis) or a
   model answer to imitate. The set's example transcript deliberately contains
   mistakes, and new speech processing is out of scope. Not chosen.

**Chosen loop:** task repetition with feedback, made into a daily routine. A
queue gives the next step for each exercise and why, and a summary counts
only what was actually completed.

**Lifecycles.**
- **Exercise:** started once per prompt and stores that wording. It is never
  edited or deleted. It holds up to 20 takes. It reports `pack_status`
  against the embedded set: `current`, `changed` or `removed`.
- **Attempt (take):** saved metadata, then the transcript states:
  - a transcription request (`in_progress`, then `completed`, `failed` or
    `unknown`), giving a machine transcript;
  - confirmed versions `1…10`.
  
  Each version can have feedback requests (`in_progress`, then `completed`,
  `failed` or `unknown`). The derived `state` follows the latest version only
  (A.19).
- **Recording reference:** the audio bytes stay in the browser's memory (an
  object URL). The server stores only type, size, SHA-256 and duration. The
  audio is sent only on an explicit transcription request, checked against
  the take's SHA-256 and type, and never stored. After a reload it is gone.
  The same file can be attached again by its SHA-256. Replacing a take's
  audio releases the old object URL.
- **Feedback:** a report about one confirmed version, never carried over.
  Failed reports stay stored. Learner notes are captures (`source: manual`)
  linked to `(feedback id, improvement)`. They are never edits to the report.

**Reused, not rebuilt:**
- the exercise, take, transcript and feedback tables;
- the attempt-first request rules (§4.4);
- the NDJSON export conventions of the learning-record export;
- Notebook captures and retry marks;
- the existing table and banner styles (no CSS change).

**Proposed contract:** published before implementation as the lane's
`PLAN.md`, then implemented as written, additive with no migration
(ARCHITECTURE.md §4.7, A.19).

## Persistence (items 9–16)

| Item | Status | Evidence |
|---|---|---|
| 9 create an exercise | covered; exercised | start `201`, again `200` |
| 10 attempt ↔ exact prompt revision | covered by construction (take → exercise with its stored wording); identity now visible | `content_fingerprint`, `pack_status`; changed-prompt test |
| 11 recording metadata | covered | type, size, SHA-256 and duration only; no audio column |
| 12 duration, format, size | covered; exercised at both entry points | take save `422` for size > 8 MiB, duration 0 or > 120 s, `audio/ogg`, bad digest, a typed take with audio; transcription `422` for other audio or another type, before any call |
| 13 source evidence of prompts | covered for authored prompts (the only kind) | `prompt_set` and fingerprint on the exercise and in the export. No generated or imported prompts exist |
| 14 list and retrieve attempts | covered and extended | exercise view; **Attempts** table; export |
| 15 deletion | not implemented (decision) | Records are append-only and referenced by transcripts, feedback and captures. There is no audio file to clean up. A discarded recording and replaced audio release their object URLs |
| 16 seal | this record and the lane checkpoint | ledger 21; walk 33/33 |

## Model integration and learning features (items 17–32)

| Item | Status | Evidence |
|---|---|---|
| 17 adapter | covered | The existing OpenAI-shaped transcriber and feedback clients (`OPENAI_BASE_URL`) were exercised against the loopback fake. No other model contract was proposed by another lane |
| 18 processing state, failures | covered, exercised | Request rows with outcome, failure code and deadline; failed reports stay stored |
| 19 repeated submission | implemented (takes); covered (requests) | Take replay by SHA-256 (`take_conflict` otherwise); a request key replays its result without a second call |
| 20 concurrency | verified | 8 parallel saves of one recording give one take; distinct recordings get consecutive numbers; a second request for a take while one is in progress is `409 request_in_progress`, sending nothing |
| 21 interrupted processing | verified | Server killed (SIGKILL) while the provider hung. After restart the request stays `in_progress` until its deadline, then `unknown`: the take is `transcription_unknown` and the queue's first item is `check_unknown_outcome`. An unacknowledged retry is `409 outcome_unknown` with no call; `confirm_unknown_retry` succeeds once |
| 22 model and schema version | covered, with an observation | `openai:<model>:speaking_feedback_v1` and `…:speaking_transcription_v1` record the configured model name. The provider's resolved model snapshot is not recorded (owner decision) |
| 23 user edits vs model output | covered | Transcript origin `transcription`/`corrected`/`typed`; reports are immutable; learner notes are captures |
| 24 unavailable model | verified | `500`: a failed report, queue `request_failed`, a later request completes. Slower than `OPENAI_TIMEOUT`: `unknown` (`provider_timeout`), queue `check_unknown_outcome`, an explicit retry completes. Restart with providers off: records and counts unchanged, no feedback suggested |
| 25 retry with context | covered, extended | The Notebook opens the take and version; the queue's **Open** lands on the take concerned |
| 26 attempt history | implemented | **Attempts** list (a table did not fit a phone, so it was replaced by a list) |
| 27 feedback across attempts | implemented | Per take: the report that counts (rating, number of improvements) and the state; word diff between transcripts (existing) |
| 28–29 learner note, traceable | covered | **Save this mistake…** stores "how you would say it now" as a capture linked to `(report, improvement)`. The Notebook link names exercise, take, version and report. A free note on a take with no improvement is not supported (it would need storage) |
| 30–31 queue and reasons | implemented | `GET /speaking/practice` and **Next steps** |
| 32 seal with examples | done | Synthetic practice fixture (lane handoff `fixture-practice/`); `web/src/test/speakingPracticeFixture.ts` is the backend's own answer from the walk |

## Revision behaviour (items 33–40)

A real correction was rehearsed: this tree built with one prompt's situation
changed, against the walk's records. 9/9 checks:
- the exercise keeps the wording answered (same content fingerprint) and says
  `changed`;
- the new example is not shown, while the prompt list shows the new wording;
- takes, transcripts, machine transcripts, reports and states are unchanged;
- counts and queue are unchanged; the export differs only in `pack_status`;
- a second exercise for the corrected wording is `409 prompt_conflict`, and
  practice continues on the started wording (a new take saves);
- back on the current build it reads `current` again, with nothing rewritten.

**Item 34, how revised prompts enter future practice:** today they do not.
The learner keeps practising the wording they started, and the corrected
wording is shown in the prompt list only. Making it practisable needs several
exercises per prompt, which means a migration (owner decision).

Items 36–39 (listening workbook updates) were covered in part 3:
- unsaved answers, **Not now** and stale previews;
- revision names on retry cards;
- renumbering shifts summarised apart from genuine moves;
- long previews at 390 px.

That code is unchanged here. Its tests pass again: the revision integration
tests, and 33 web tests across `ListeningRevisions`, `ListeningScripts` and
`MistakeNotebook`. Item 40: real Chromium at 390×844 in English and Chinese,
and at 1280×900, all 30/30:
- the overview, the attempts and the re-attach control fit the width;
- the text comes from the catalogs;
- there are no page errors.

## Restore and upgrade (items 41–48)

One rehearsal from the predecessor build `c53b42c` (ledger 21, no practice
route, no take replay), with the part-4 harness: 29/29.
- **Seed (predecessor build):**
  - a recorded take with a machine transcript, a corrected version and a
    report;
  - a typed take with a failed report;
  - a resent save, which that build stores as a duplicate take;
  - a mistake marked for retry.
- **Backup:** `flh-daily.sh backup`, then made read-only (directory 0500,
  files 0400, parent 0700).
- **Restore** into an isolated candidate. `flh-daily.sh restore` refuses at
  the write check (rc 2) and does not start the service. After `chmod 600` the
  check passes. The candidate equals the predecessor row for row.
- **New build:** ready; the practice overview is readable. The first write
  (a new take) adds exactly one row. The source is byte-, mode- and
  mtime-identical, its checksums pass, and it is still read-only.
- **After restore:**
  - audio metadata and model provenance are unchanged;
  - no 64-byte window of any audio sent or saved is in the database files;
  - another file is refused before any call, while the same file transcribes
    again (what **Choose the same audio file again** relies on);
  - a resent save of take 1 names take 1;
  - states over the restored records are right (take 3, the predecessor's
    duplicate, simply waits for a transcript);
  - the export has 4 lines;
  - the mistake still resolves and stays marked.
- **Rollback:**
  - Binary-only: the predecessor build reads the upgraded data. It has no
    replay, so a resent save makes a duplicate there.
  - Documented (restore of the read-only predecessor backup): the write check
    refuses, then passes after `chmod 600`. The data equals the backup; the
    removed rows are unchanged in `data.before-restore-…`. The older build is
    ready, re-import replays, and its first write is `200`.
- **Roll forward:** redoing the same new take creates it once, with the same
  id as before the rollback, then replays.
- **Ids:** every pre-existing id survives every state, and integrity and
  foreign keys are ok throughout. The only duplicate audio in any state is the
  predecessor's own; the new build added none.

**Item 47, an audio artifact that is unavailable:** audio is never stored, so
a restored (or reloaded) take never has audio. Its metadata, transcripts and
reports are complete. To transcribe it again, choose the same file (the
SHA-256 must match); otherwise type or correct the transcript. A recording
made in the browser and never saved as a file cannot be recovered. That is by
design.

## Progress, export and final verification (items 49–64)

| Item | Status | Evidence |
|---|---|---|
| 49–50 summary, honest counts | implemented, verified | Only `feedback_ready` on the latest confirmed version counts. A new version takes a take out of the completed count. The counts always add up to the takes |
| 51–52 export with references | implemented | `speaking_attempt_export_v1` keeps the exercise id, prompt id, set, fingerprint, pack status, and every provenance string |
| 53 re-import | not applicable | The export has no import route, by design: it is a record of practice. The database backup is the restore path: the restore rehearsal showed every row identical after a restore, and the export is derived from those rows |
| 54 English and Chinese | verified | Typed catalog parity and placeholder test. Real Chromium in Chinese at 390 px, with text read from the catalogs |
| 55 empty and partial history | verified | Empty history (three prompts not started, nothing counted, no export link); partial (one completed, one waiting, one to check) |
| 56 daily loop, fresh data | verified | Through the UI on a fresh database, 8/8: start, upload a file, transcribe, check, confirm, feedback; the overview says "answer again with 4 improvements"; a typed take 2; then "request feedback"; then export |
| 57 checks | see Results | |
| 58 migration from the predecessor | verified | `c53b42c` database (ledger 21): no schema step. The new build reads it, derives states, counts and the export, and names take 1 on a resend |
| 59 existing records | verified | Every pre-existing row and id unchanged through restore, first write, both rollbacks and the roll forward. The predecessor's own duplicate take is left as it is |
| 60 partial failure and retry | verified | Failed, unknown, timed-out and interrupted requests; key replays; no silent retry |
| 61 API examples, frontend fixture | done | Recorded request and response pairs in the lane handoff; `web/src/test/speakingPracticeFixture.ts` |
| 62 walkthrough | done | Lane `WALKTHROUGH.md`; its commands were run |
| 63 patch and data formats | done | Lane `snapshot-5/part5.patch` (applies to the batch start and reproduces this tree); `DATA-FORMATS.md` |
| 64 ranking | below | |

## Remaining learning features, ranked by what this batch demonstrated

1. **Prompt revisions.** Shown: a corrected prompt cannot be practised (`409 prompt_conflict`); only
   its wording is shown. Needs several exercises per prompt, so a migration.
2. **More authored prompts.** Shown: with three prompts the queue soon holds only "answer again".
   This is content work, not code.
3. **One daily queue across skills** (Speaking, Notebook retry marks, Listening and Reading
   lessons). Shown: the Speaking queue works and the Home tab only opens sections.
4. **A free note on a take.** Shown: notes exist only as mistakes tied to an improvement. Needs
   storage.
5. **Timed repetition (4/3/2).** The takes and duration range are there; it needs timing goals.
6. **Recording the provider's resolved model snapshot** with the configured name: provenance
   precision. It changes the provenance format, so it needs an owner decision.

## Observations (not changed)

- With feedback disabled, an exercise whose latest take only waits for feedback has no queue item.
  Nothing can be done there, so this is deliberate, and it is documented.
- The browser's native file button ("Choose File") is not translated: it is the browser's own
  control.
- Dates use the browser locale (`toLocaleString()`), as Listening does.
- `make verify` hit 4–7 timeouts in untouched web tests under host load (load average 24–69 on 8
  cores from other lanes). The same tree passed with fewer workers and at lower load.

## Results

- **Go:** the new integration tests (queue, states, counts, export, changed prompt, unknown outcome
  with feedback disabled, concurrent saves) pass, also under `-race`. With the replay removed (a
  mutation), two tests fail.
- **Web:** 5 new tests: overview, plural and empty queue, attempts with a changed prompt,
  re-attach, and the backend's own overview. 44 files, 501 tests.
- **Built server and tools:**

  | Tool | Result |
  |---|---|
  | API walk | 33/33 |
  | interruption | 10/10 |
  | corrected prompt | 9/9 |
  | restore and upgrade from `c53b42c` | 29/29 |
  | Chromium, en/zh, phone and desktop | 30/30 |
  | UI daily loop | 8/8 |
