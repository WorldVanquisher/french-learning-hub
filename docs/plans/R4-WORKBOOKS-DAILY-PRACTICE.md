# R4 Workbooks: traceable daily practice and learner integrity across a restore (2026-11-20)

**Base:** `58c0ba8b…`, confirmed by the owner. Evidence is in the sealed handoffs
(`flh-handoff/overnight-20261120-flh/workbooks-r4/handoff-0NN`). All data is synthetic; nothing
touches daily data.

## 1. The Review Today flow as merged (R4-WB-001)

1. **Load.** `ReviewToday` mounts and reads `GET /review-today`.
   - The server builds the queue on every read, in `BuildReviewTodayCounted`: started Speaking
     steps, plus Mistake Notebook records marked for retry.
   - It resolves only the marked records (R3-065).
   - It orders by priority, then the longest wait, then source, then key.
2. **Item selection.** Each row has one primary action.
   - A Speaking step uses `onOpenSpeaking(exercise, take)`.
   - A notebook record uses `onOpenSource(sourceOpen(item))`.
   - In both cases, `App` sets `origin = {from: today}` and switches to the lesson or take view.
3. **Evidence.**
   - **Lesson:** the lesson opens at the saved exercise, item and version. The notebook item
     carries the link: material, exercise, transcript version.
   - **Speaking:** a step opens the take.
   - **Back banner:** `BackBanner` says "Opened from Review Today".
4. **Back.** `goBack({kind: today})` shows Review Today again. Because Review Today is not one of
   the kept views, it **mounts again** and re-reads the queue.
   - **Before R4:** focus went to the page body, and "Hide for this visit" was forgotten. The
     baseline browser run recorded `BODY` and the hidden step reappearing.
5. **Done for today.** It calls the notebook's own `PUT …/retry {"marked": false}`, re-reads the
   queue, and moves focus to the item that took the row's place. On failure, the row and focus
   stay (R3-087).

## 2. Checks for save failure, retry and empty queues (R4-WB-002)

| Path | English at baseline | Chinese at baseline | R4 |
|---|---|---|---|
| "Done for today" save fails | jsdom (row kept, focus back) | none | jsdom in both languages; browser at 1280 px and 320 px in both languages |
| Retry after a failed save | none | none | jsdom, and browser via the keyboard (Enter twice) |
| A grouped save that partly fails | n/a | n/a | jsdom: re-read, the row tells the truth, focus kept |
| Retry a failed load | none | none | jsdom in both languages |
| Empty: nothing yet / all done | jsdom | none | Chinese all-done (jsdom); emptied queue with focus on the heading (browser) |

## 3. The profile, screenshots and the friction point (R4-WB-003 to R4-WB-005)

- **Profile:** `scripts/demo/review_today_r4/profile.py`, through the API only. Seven queue items:
  - 2 Speaking steps;
  - 5 notebook rows, one of which stands for 2 records (question 2 saved from revisions 1 and 2);
  - a reading mistake;
  - a record with no source;
  - a refused duplicate save (409 `source_already_saved`);
  - a long French mistake.
- **Screenshots:** `walkthrough.py --baseline` (start tree) and the R4 run, at desktop 1280 px,
  320 px Chinese and 320 px English.
- **The friction point chosen: losing one's place on the way back from an item's evidence.**
  Alternatives considered:
  - two rows for the same question: rarer, needs a revision update;
  - no next-review information: informational only.

  Why this one:
  - **Frequency:** it happens on every evidence round trip, which is the main flow traced in §1.
  - **Measured on the start tree:** focus `BODY` and the hidden step returned, in all three
    combinations.
  - **Keyboard users** must tab from the top of the page again.
  - **Small fix:** it is local and reversible.

## 4. Decisions made in this lane (reversible)

| # | Decision | Why | How to reverse |
|---|---|---|---|
| D1 | Page memory for Review Today (`pages/reviewTodayMemory.ts`): hidden steps and the item to return to, in a module, never in storage | Keeping the view mounted would show a stale queue after a lesson changes it. Only the learner's place is needed | Delete the module and its three call sites; behaviour returns to re-mount from scratch |
| D2 | One queue row per workbook question (`groupEquivalentNotebookItems`): same lesson and item position, listening or reading only, resolved sources only. The row is led by the newest source version (then the newest record) and waits since the earliest mark; the others go in `also_entry_ids` | Pack corrections keep item positions, so these are the same question. Two equivalent actions confused the learner. Business rule kept in the backend | Remove the one call in `BuildReviewTodayCounted`; the UI works without `also_entry_ids` |
| D3 | The next-review recommendation computed by the server from the existing ladder (`ScheduleFor` → `NextRecommendation`), added as an optional `schedule` field on each `review_today_v1` item | "Backed by the existing scheduling logic"; an additive field breaks no reader. The queue itself stays what the learner marked | Drop the field and `ScheduleFor`; nothing reads it but Review Today |
| D4 | A missed attempt restarts the ladder at its first step from that date (`LastMissed`) | The most conservative rule; it says plainly what a miss costs | Remove `LastMissed`; every attempt counts as completed again |
| D5 | Inputs mapped as `ScheduleInputsFromExport` maps the export. A notebook record is a review completed when saved. Speaking takes are attempts, with only the latest take's time known. A stuck step is recovery, and a review once done | One mapping for both paths; no new query | Change `ScheduleInputFor` |
| D6 | "Done for today" on a grouped row sends the existing save once per record. On a partial failure it re-reads, and focus stays on the row at the same place | No new endpoint; each save is idempotent (`changed: false` on repeat) | A batch endpoint, if wanted later |
| D7 | Summary wording "When to review it next" (no day), with the completed and missed lines below | The ladder's own "due" day contradicted the queue for a record saved today (tomorrow vs now) | Wording only |
| D8 | All five reason codes of the merged contract explained, an unknown code shown verbatim | The merged `PRACTICE.md` §13 lists five; Workbooks explained two | Remove entries from `reasonCodes.ts` |
| D9 | Focus after a save is restored by an effect once the buttons are enabled again, not in an animation frame | Repeated phone-size browser runs lost focus intermittently: a frame could run before the re-render and focus a still-disabled button, which a browser refuses. jsdom accepts it, so the unit tests could not show it | Return to `requestAnimationFrame` (not advised) |

## 5. Spaced practice details (R4-WB-012 to R4-WB-015)

- **Midnight and zones:** each due day is a calendar day at local midnight in the zone the browser
  sends (`zone=`).
  - Tested: midnight; both Paris transitions of 2026 (a time inside the skipped hour, both
    occurrences of the repeated hour); a learner reading in Paris and then in Tokyo (each zone's
    own days, never mixed).
  - Tests: `review_today_r4_test.go`, `review_schedule_test.go`.
- **Missing previous attempt date (R4-WB-013):** the attempt still counts toward the step. The
  start is the latest attempt that has a time. If none has one, the record's creation time is
  used; if that is unknown too, today. The rule says which, e.g. "today (fallback: no timestamp)".
- **Interval after a correct or missed attempt (R4-WB-014):** shown on each row, with the rule.
  For example: if completed, +3 days; if missed, +1 day. A stuck step stays due today when missed.
- **Simulated persistence (R4-WB-015):** a recorded outcome, or a defer to a later day, needs the
  practice storage the owner has not approved. Until then:
  - "Hide for this visit" lives in page memory (D1);
  - outcomes stay in the practice page's state;
  - the recommendation shows both outcomes instead of storing one.

## 6. The merged Extraction contract against Workbooks (R4-WB-021 to R4-WB-025, R4-WB-030)

**Exact differences found** (`web/src/prototype/extractionMerged.test.ts`):

1. **2.2 fixtures:** the merged `tools/extraction/fixtures/practice_v1/workbooks2/` files are
   byte-identical to the sealed copy Workbooks embeds (`extraction22Fixture.ts`): 5 feeds, the
   replay cases and the compatibility report.
2. **Reason codes:** the merged `PRACTICE.md` §13 lists five: `knowledge_changed`,
   `awaiting_confirmation`, `rejected`, `rule_not_approved`, `absent`. Before R4, Workbooks
   explained two; now all five, plus a verbatim fallback (D8).
3. **The service contract `flh_extraction_service_v1`:**
   - It wraps the feed: `{status, body: {contract, deployment_id, feed, operation, schema, status}}`.
   - The inner feed has a `consumer` field.
   - Workbooks' parser and client accept `body.feed` unchanged: the same `feed_id`, applied.
4. **Still open on their side** (R3 note): their compatibility checker and
   `EXTRACTION-3.md` (R3-025) still model the increment-4 consumer, which refused an
   all-withdrawn feed. The current consumer accepts it.

**What Workbooks can infer locally, and what needs the extraction service (R4-WB-030):**

| Workbooks infers, from the feed and its own state | Needs the extraction service |
|---|---|
| Replay and stale feeds (`feed_id`, then revision and `feed_seq`) | Whether a claim is supported by the learner's text (grounding) |
| Withdrawn and restored IDs, kept history, the reason code's sentence | Why knowledge changed between revisions, and new revisions themselves |
| The next exercise after a miss (`flh_next_exercise_rule_v1`, on known outcomes) | Approval, rejection and confirmation of knowledge (learner decisions recorded there) |
| An attempt's trace: source, revision, evidence IDs (from the packet of that revision) | Evidence of a revision Workbooks never received, and quotes of a source Workbooks never stored |
| The evidence a withdrawn exercise was built on (from the last revision that offered it) | Agent proposals' classification and the import preview |

## 7. Privacy: which fields are transient, retained or exported (R4-WB-031)

| Data | Where it lives | Retained? | In the default history export? |
|---|---|---|---|
| Practice answers, reveals, self-checks, drafts (prototype) | page state | no: gone on reload | not on the server; the visit export only on the learner's opt-in ("Include my answer texts") |
| Review Today hidden steps, return target | page memory (D1) | no | no |
| Captured record: question and context | `learning_entries` | yes (learner-authored) | `notes=true` only |
| A listening or reading attempt on a notebook source | `learning_capture_sources.attempt` | only when the learner ticks it | `notes=true` only |
| Retry marks (who/when, marked or not) | `mistake_retry_marks`, append-only | yes | yes (no text) |
| Speaking transcript texts | `speaking_transcripts` | yes (the learner confirmed them) | `transcripts=true` only |
| Speaking audio | browser only | never stored | never |
| Writing drafts | `writing_drafts` | yes | `notes=true` only |
| Provenance (`authored:<pack>`, `openai:<model>:<contract>`, …) | beside each generated item | yes | yes: values match the approved patterns (restore rehearsal) |
| Tutor and study packets | built in the extraction tool | never the learner's answers, never the full question or context | n/a |

**Erasure:** there is no learner-facing erase on the server; records are append-only by design. A
practice text retention table with erase is optional part A of the storage proposal, reserved for
the owner.

## 8. Learner-critical data families and their checks (R4-WB-041 to R4-WB-045)

The families are defined in `scripts/validation/migration/entities.py` (`CRITICAL`). Every check is
run by `inventory.py`, which only ever reads a scratch copy.

| Family | Tables | Checks |
|---|---|---|
| learning records | `learning_entries`, `learning_captures`, `entry_analyses`, `analysis_feedback` | rows; digest; foreign keys; UTF-8 without control characters; NFC capture IDs |
| mistake notebook | `learning_capture_sources`, `mistake_retry_marks` | every source item resolves to a stored item; marks name a record |
| listening lessons | `listening_materials`, `listening_transcripts`, `listening_exercises` | versions 1..N; one authored exercise per script revision; exercise and transcript of the same material |
| reading lessons | `reading_lessons`, `reading_passages`, `reading_exercises` | passage versions 1..N |
| writing | `writing_tasks`, `writing_drafts`, `writing_feedback` | draft versions 1..N; feedback about a draft of its own task |
| speaking | `speaking_exercises`, `speaking_takes`, `speaking_transcriptions`, `speaking_transcripts`, `speaking_feedback` | transcript versions 1..N; audio metadata only (no audio column) |
| mock exams | `exam_sessions`, `exam_session_items`, `exam_answers`, `exam_submissions` | no answer after the deadline or the submission |
| knowledge | extractions, units, admission overrides, concepts, memberships, links, judgments, distinctions, current extractions, suggestion confirmations | rows; digest; foreign keys |
| idempotency receipts | `annotation_operations` | rows; digest |

**Gate.** With `--expect` and the source's inventory, a family with fewer rows than the baseline is
a blocking problem ("missing data family"), exit 1. Equal rows with another digest is a problem.
More rows is a warning (written later).

**Baseline of the synthetic backup** (R4-WB-042): verdict READY, logical digest `9db043ce5ee3…`.
- Rows: 475 entries and captures; 6 notebook sources and 6 marks; 2 listening materials, 3
  transcripts and 3 exercises; 1 reading lesson; 2 Speaking exercises, 3 takes and 4 transcripts;
  1 writing task with 2 drafts; ledger 21.
- 475 entries is the profile plus the captures written during the snapshot-under-writes comparison.

**Auxiliary files** (R4-WB-043): a backup directory holds `SHA256SUMS` (recognised as such); any
other file is listed with its size and SHA-256 as a warning.
- The profile's data directory had `profile.json` and `server.log` beside the database: listed, and
  not needed by any restore.
- The restored target holds `app.db` only.
- No learner data lives outside the database: no audio, packs embedded in the binary, external links
  stored as text and never fetched.

## 9. Backup transfer, post-restore learning and outside dependencies (R4-WB-046 to R4-WB-055)

- **Rehearsal** (`scripts/validation/review_today_r4/restore_learning.py`, 33 checks):
  - a stopped snapshot with SHA256SUMS (backup_tool: COMPLETE), packed, transferred to a scratch
    copy, SHA-256 equal on arrival;
  - a truncated archive and a mismatched checksum both refused, leaving nothing;
  - unpacked into a fresh target: integrity ok, first write possible, inventory READY with the
    baseline's logical digest;
  - the source files byte-identical before and after.
- **Snapshot while writes arrive** (R4-WB-048):
  - a copy of `app.db` alone held 101 of 127 committed records in an earlier run. In the final
    rehearsal it held fewer than were committed again, by the same mechanism (the WAL).
  - a copy with its sidecars is only as new as its moment.
  - Only the stopped snapshot is restored.
- **Learning on the restored data:**
  - Review Today, the notebook, the Speaking exercise, the lesson and the full history export all
    equal the source's (API).
  - The grouped question is one row. Its archived correction resolves on revision 1 (authored
    reference). Done, then marked again: it returns; a repeated mark changes nothing.
  - The listening lesson reaches its authored quiz on revision 2, and a mock exam starts with 9
    frozen questions.
  - The browser journey on a restored copy: 49/49.
- **Release sequence** (R4-WB-050): `bash scripts/validation/migration/verify_restore.sh BACKUP_DIR WORK`.
  It ends VERIFIED on the synthetic backup and stops at step 1 on an altered one.
- **Outside the database** (R4-WB-055): nothing learner-specific.
  - No audio is ever stored.
  - Content packs are embedded in the binary: a lesson's `script_revision.pack_status` says whether
    the running binary's pack matches.
  - External links are text and never fetched (inventory `attachments.external_links_not_fetched`).
  - Providers are optional and disabled by default.
  - The optional Qdrant semantic index is rebuildable from SQLite.
  - Off-host backups are Release's.
  - Before cutover, check:
    - the inventory `auxiliary` list is empty or only `SHA256SUMS`;
    - `pack_status` is `current` on a lesson;
    - `/readyz` answers;
    - provider settings are as intended.

## 10. Performance: what was measured and its limits (R4-WB-056 to R4-WB-060)

**Environment:** one Linux laptop (kernel 7.2, Intel i7-1165G7, 8 threads, 15 GB RAM), Go 1.27.3, the
server built with `-trimpath`, SQLite (modernc), Chromium from Playwright 1.49.1 in
`node:22-bookworm-slim`. Load average was 3–10 during runs: other sessions shared the machine.

| Measure | Runs | Start tree | R4 |
|---|---|---|---|
| Review Today median at 40 / 600 / 2,400 saved records (33-item queue) | 20 sequential reads per size | 11.9 / 16.8 / 14.0 ms | 11.3 / 15.3 / 16.2 ms |
| Review Today payload (33 items) | — | 34.6 KB | 45.5 KB (+31 %, the `schedule` field, about 330 B per item) |
| 8 readers + 1 writer at 2,400 records, median / p95 | 5 requests per reader | 264.2 / 371.0 ms, all answered | 239.2 / 365.2 ms, all answered |

**Restore, measured apart from the first session** (R4-WB-057), one run each:
- snapshot, pack and transfer: 170 ms;
- unpack, verify, integrity and write check: 105 ms;
- server start to ready: 52 ms;
- first Review Today: 5 ms.

**The slow path** (R4-WB-058):
- Review Today still resolves only marked records (R3 test).
- The schedule and the grouping are pure functions over the items already read: no extra
  notebook, evidence or provider lookup.
- The page makes one Review Today request per visit. A grouped "Done for today" makes one save per
  record, then one read.

**Stale data** (R4-WB-059): a slow response from a visit the learner left is ignored, and quickly
opening two items leads back to the last one (jsdom test).

**Limits:**
- Single runs for the restore timings; small synthetic data; a shared machine.
- Latency differences under about 3 ms are noise.
- No measurement on the NAS or AWS hosts.

## 11. A short synthetic walkthrough from restore to completed practice (R4-WB-071)

1. `profile.py` seeds a fresh scratch server through the API; stop it.
2. `verify_restore.sh BACKUP WORK` ends VERIFIED.
3. Start the server on `WORK/data` and open `#/today`. Seven items: two Speaking steps, five workbook
   rows, one standing for two records ("You also saved this question once…").
4. Open "When to review it next" on the grouped row: completed +3 days, missed +1 day, with the
   rules.
5. With the keyboard, open the lesson (Enter), read the item, then "← Back to Review Today" (Enter).
   Focus is back on the same item; a step hidden earlier stays hidden.
6. "Done for today" on the grouped row clears both records. Focus moves to the next item, and the
   change is announced once.
7. Finish the rest: an empty queue puts focus on the heading. The Mistake Notebook still lists every
   record.

Screenshots: `evidence/walk-r4/shots/<combo>/01…07`.

## 12. Migration call (R4-WB-072)

- **GO** for the restore procedure on synthetic data. Evidence:
  - the backup's identity (SHA256SUMS, archive SHA-256 `19808480…` in the sequence run);
  - integrity ok;
  - inventory READY on the source and the target with the same logical digest (`9db043ce…`);
  - first write possible;
  - learner reads equal;
  - an altered or truncated archive refused.
- **HOLD** for:
  - any practice storage migration (no migration approved; proposal only);
  - a restore of real learner data and any live cutover. These are owner decisions, with the
    sequence above as the check to run.

## 13. Decisions reserved for the owner (R4-WB-074)

1. **Practice storage** (`R4-PRACTICE-STORAGE-PROPOSAL.md`):
   - whether Review Today outcomes are stored (`review_outcomes`);
   - whether defers persist across visits;
   - the migration number;
   - its release with a demo artifact rebuild.
2. **Retention:** whether any answer text may ever be kept (R3 optional part A), and the
   learner-facing erase path. Today: never stored, and records are append-only.
3. **Whether the next-review recommendation may ever drive the queue.** Today it is advisory only.
4. **Real learner data:** a backup restore or cutover with real data, with `verify_restore.sh` as
   the gate.
5. **Live work and publication:** AWS, DNS and any live host; commits, pushes and the pull request.
6. **Grouping scope:** whether writing and speaking corrections saved from several versions should
   also be grouped. Today only listening and reading items are grouped, by lesson and item
   position.
