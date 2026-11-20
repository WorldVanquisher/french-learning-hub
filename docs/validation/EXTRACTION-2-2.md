# Extraction 2.2: reliable knowledge, practice and agent exchange (2026-11-19)

PROTOTYPE on synthetic data, plus six short public-domain excerpts. It follows
`EXTRACTION-2-1.md` and starts from HANDOFF-2.1 and Speaking Lab HANDOFF-110.
- **Start.** Both seals were checked, and the tree's snapshot equalled HANDOFF-2.1's (115 paths,
  tar `857040c5…`) before any edit.
- **Contract and commands.** `tools/extraction/PRACTICE.md` §9–§14. Workbooks bundle:
  `tools/extraction/fixtures/practice_v1/workbooks2/`.
- **Raw outputs.** In the owner's sealed handoff `extraction2-20261119/handoff-2.2`, outside Git.

```sh
cd tools/extraction && python3 -B -m flh_extraction practice2 demo3 --out "$(mktemp -d)/demo" --check
```

## Totals

| Status | Items |
|---|---|
| implemented | 81 |
| verified prototype | 19 |
| blocked | 0 |
| owner-only | 0 |

**Not run: two live agent sessions.** The smoke in R2-039 and R2-099 is real-agent work, so it
is the owner's step, but no item is owner-only. Each item's deliverable (a checklist, a decision
packet, a proposal) is in the tree; the owner decisions are listed at the end.

## Per item

| ID | Status | Evidence (paths in `tools/extraction` unless stated; `handoff:` = sealed handoff) |
|---|---|---|
| R2-001 | verified prototype | handoff: `evidence/001-start-snapshot.json`; both `sha256sum -c` OK |
| R2-002 | verified prototype | handoff: `evidence/002-demo2.txt`, `002-demo136.txt`, `002-repro/` (packaged review reproduced; one timing check flipped, finding F1) |
| R2-003 | implemented | `practice2 measure`; `fixtures/practice_v1/expected3/00-interactions.json` (each interaction recorded) |
| R2-004 | verified prototype | handoff: `evidence/004-french-check.md`; fixes in `y_en.r3.json`; finding F2 |
| R2-005 | implemented | `fixtures/practice_v1/a_en_lieux.json` (à / en / aux before place names) |
| R2-006 | implemented | its `provenance` block (author, dates, Wikisource revids and text hashes, synthetic parts, usage boundaries); `test_public_excerpts_are_quoted_exactly_with_their_revision` |
| R2-007 | implemented | `review2.render_items` (QUOTE / PARAPHRASE lines); `test_quote_and_paraphrase_are_labelled_apart` |
| R2-008 | implemented | items `en-tous-pays` and `en-gerondif` in `a_en_lieux.json` |
| R2-009 | implemented | `review2.cues` (`flh_quote_scope_cues_v1`); `test_word_cues_…`, `test_a_non_entailing_claim_without_a_cue_word_is_not_caught` |
| R2-010 | implemented | `expected3/04-a-en-decided.txt` (accept `en-japon`, edit `en-gerondif`, reject `en-tous-pays`) |
| R2-011 | implemented | `review2.plan` effects; `expected3/03-a-en-r1-review.txt` |
| R2-012 | implemented | `[x]` list, `--select`, `batch.selected` per decision; `test_plan_lists_the_selection_and_its_effects` |
| R2-013 | implemented | `test_revised_or_uncertain_evidence_is_never_batched` |
| R2-014 | implemented | matrix rows "revision, item unchanged" and "absent from one revision, back unchanged" |
| R2-015 | implemented | MOVED lines; `expected3/02-y-en-r3-review.txt`; `test_revision_3_…` |
| R2-016 | implemented | `material_hash`; matrix rows "spacing only" (kept) and "material change" (refused) |
| R2-017 | implemented | `--attest-paraphrase`; `test_paraphrase_needs_attestation_and_records_it` |
| R2-018 | implemented | `repair`, resumable batch; `test_interrupted_batch_is_refused_until_repaired_then_completes_once` |
| R2-019 | implemented | `rejected_on`, `earlier_decision`; `test_reject_reason_stays_with_the_revision_that_caused_it` |
| R2-020 | implemented | `expected3/17-acceptance-matrix.md` (24 of 24) |
| R2-021 | implemented | `flh_exercise_proposal_v1` in `flh_agent_proposals_v2` (`exercises.py`) |
| R2-022 | implemented | kinds explanation / discrimination / production |
| R2-023 | implemented | `rule_id` + `source` required; `test_rule_and_revision_are_required` |
| R2-024 | implemented | `expected3/06-codex-preview.txt`; `test_preview_shows_variants_rubric_and_ambiguity` |
| R2-025 | implemented | class `withdrawn` with the fixing decision; `expected3/07-codex-preview-after-r2.txt` |
| R2-026 | implemented | `practice2 exercise --prompt/--accepted/--answer`; `test_edited_variants_are_checked_again` |
| R2-027 | implemented | `flh_practice_exercise_decision_v1`; `Work2.practice` |
| R2-028 | implemented | keyed decisions; `test_edit_approve_is_idempotent_and_never_evidence`; `test_same_exercise_from_another_agent_is_a_duplicate` |
| R2-029 | implemented | `support: agent_proposed`, provenance only; same test |
| R2-030 | implemented | `expected3/demo3.txt` lines 5 and 8 (Codex e1 accepted, Claude Code q2 rejected) |
| R2-031 | implemented | `portable.export3`; `test_one_packet_for_every_agent` |
| R2-032 | implemented | `practice_prompts/PROMPT-any-agent.md` |
| R2-033 | implemented | `test_study_v3_has_no_answers_and_no_attempt_text` |
| R2-034 | implemented | `awaiting_learner`; `test_proposed_and_accepted_facts_stay_apart` |
| R2-035 | implemented | `--variant minimal`; `expected3/11-packet-minimal.md` |
| R2-036 | verified prototype | `expected3/13-older-packets.txt`; `test_older_versions_unknown_fields_and_bad_versions` |
| R2-037 | implemented | `exercises.check_return`; same test; `expected3/09-claude-code-preview.txt` |
| R2-038 | verified prototype | `expected3/14-adapters.txt` (identical packet bytes; prompts differ in 4 lines; 0 privacy findings) |
| R2-039 | implemented | `PRACTICE.md` §11 owner smoke checklist (offline part run, packet `pk-0e06b9c6b9c4`) |
| R2-040 | implemented | `--omit`; `expected3/11-share-preview.txt` |
| R2-041 | implemented | `recall.DEFINITIONS`; `PRACTICE.md` §12 |
| R2-042 | implemented | `fixtures/practice_v1/probe/y_en_probe_v1.json` (L1–L3); `probe/expected/probe-checks.json`; `test_probe_is_novel_and_absent_from_study_packets` |
| R2-043 | implemented | t8 and t9 ambiguity notes; `test_statuses_are_kept_apart_and_checked` |
| R2-044 | implemented | `recall.answers_in_packets` (0 found) |
| R2-045 | implemented | `recall.order`; `test_order_is_deterministic_and_refuses_repeats` |
| R2-046 | implemented | completed / revealed / skipped / unsupported / missing |
| R2-047 | implemented | `recall.summary`; `fixtures/practice_v1/probe/expected/dry-run-summary.md` |
| R2-048 | verified prototype | `probe/expected-totals.json` equals the summary (0 differences) |
| R2-049 | implemented | `cannot_support`; this record, "What the trial cannot show" |
| R2-050 | implemented | `practice2 trial --out DIR --check` (`recall.trial`; `probe/expected/`; `tests/test_recall.py`) |
| R2-051 | verified prototype | this record, "Feed against the Workbooks consumer"; `workbooks2/compat-report.json` |
| R2-052 | verified prototype | `fixtures/practice_v1/workbooks/` byte-identical (`sha256sum -c`, `verify.py`); `test_v1_bundle_unchanged_and_still_verifies` |
| R2-053 | implemented | per-item `source_revision`; `feed2.py` |
| R2-054 | implemented | `workbooks2/feed-1…feed-5` |
| R2-055 | implemented | `feed-4-r3-awaiting-confirmation.json`; `test_feed_sequence_withdraws_and_restores_without_silent_reactivation` |
| R2-056 | implemented | `workbooks2/replay-cases.json`; `test_replay_and_repeat_restore_change_nothing` |
| R2-057 | implemented | `recall_type`, no schedule field (contract check) |
| R2-058 | implemented | `test_study_v3_has_no_answers_and_no_attempt_text` |
| R2-059 | implemented | `workbooks2/check_feed_compat.py` (`--json`, `--strict-consumer`, exit codes) |
| R2-060 | implemented | `workbooks2/` (14 files, `SHA256SUMS`, sample commands in `README.md`) |
| R2-061 | implemented | `workbooks2/STORAGE-DECISION-RECORD.md` §1 |
| R2-062 | implemented | same, §2 |
| R2-063 | implemented | same, §3 |
| R2-064 | implemented | same, §4; matrix rows on stale batches |
| R2-065 | implemented | same, §2 (idempotent column) |
| R2-066 | implemented | `storage_rt.export_attempts`; same, §5 |
| R2-067 | verified prototype | `expected3/16-storage-round-trip.json`; `test_round_trip_through_the_proposed_tables` |
| R2-068 | implemented | `storage_rt.history`; `test_history_keeps_withdrawn_outcomes` |
| R2-069 | implemented | same record, §5 (proposal) |
| R2-070 | implemented | `workbooks2/check_storage_rows.py` (exit 0) and the record |
| R2-071 | implemented | `tools/speaking/flh_speaking/prepare.py`, `tests/test_robustness.py`; 0 ResourceWarnings under `-X dev` in the image |
| R2-072 | verified prototype | handoff: `evidence/072c/` (124 run, 0 skipped, 0 errors) |
| R2-073 | implemented | `tools/speaking/flh_speaking/intake.py` (`flh_speaking_intake_checklist_v1`); `lab intake --proposal` |
| R2-074 | verified prototype | handoff: `evidence/074/speaker-needs.txt` |
| R2-075 | implemented | `intake.merge_check`; `tools/speaking/tests/test_intake.py` |
| R2-076 | implemented | `intake.pair_check`; same tests |
| R2-077 | implemented | `test_intake.Standing` (outcome, exit 4, observation, no promotion, serving default unchanged) |
| R2-078 | implemented | this record, "Compute" |
| R2-079 | verified prototype | this record, "Default model"; handoff snapshot (no serving file changed) |
| R2-080 | implemented | this record, "Owner decision packet: evaluation data" |
| R2-081 | verified prototype | `expected3/00-interactions.txt` (2.1 and 2.2 flows on y/en and savoir/connaître) |
| R2-082 | verified prototype | same, "to first unaided" column |
| R2-083 | verified prototype | same, per-fixture header lines |
| R2-084 | implemented | `expected3/demo3.txt` lines 5–9 |
| R2-085 | implemented | `--previous latest`; `test_previous_latest_survives_losing_the_first_session`; demo3 line 7 |
| R2-086 | implemented | `expected3/09-claude-code-preview.txt` (q3 `unknown_reference`; replay against packet 1 refused) |
| R2-087 | verified prototype | handoff: `evidence/087-*` |
| R2-088 | implemented | `expected3/12-failed-import.txt` |
| R2-089 | implemented | this record, "What carries forward between agents" |
| R2-090 | implemented | this record, "Decisions and research" |
| R2-091 | verified prototype | this record, "Validation" |
| R2-092 | verified prototype | 136 demo, demo2, candidate-review demo, lab demo: all exit 0 |
| R2-093 | implemented | `practice2 demo3` |
| R2-094 | implemented | this record, "Demos and expected results" |
| R2-095 | verified prototype | this record, "Validation" |
| R2-096 | implemented | handoff: `REVIEW-2.2.md` |
| R2-097 | implemented | `workbooks2/`; this record, "What Workbooks can consume" |
| R2-098 | implemented | handoff: `COMMIT-SPLIT.md` and `snapshot/GIT-ADD-*.txt` |
| R2-099 | implemented | this record, "Owner decisions" |
| R2-100 | implemented | handoff: `HANDOFF-2.2.md`, `SHA256SUMS` |

## Findings

- **F1. A timing check is not stable** (R2-002). The packaged review was reproduced: texts 5/5
  for both models, outcome `insufficient_support`, exit 4. But the small model's measured
  real-time factor on the same five clips moved from 0.4481 (HANDOFF-110) to 0.6072 here, so
  `resources.max_real_time_factor` flipped from pass to fail (5 → 4 of 6 checks). The host was
  shared with other workers. A single timing run should not gate anything; see "Compute".
- **F2. Synthetic French** (R2-004). Checked against OQLF Vitrine linguistique and the
  Académie française dictionary:
  - « Non, je n'en reviens pas. » (an accepted variant) also means "I can't believe it"
    (Académie, *revenir* II.A.3). Removed in `y_en.r3.json`.
  - « j'en vais » is wrong, but « je m'en vais » (*s'en aller*) is right. The why now says so (r3).
  - « y » also replaces places after « dans », « chez », « en » (Académie, *y* II.1); the y/en
    claim names only « à ». Recorded; not changed.
  - After the future of « aller », « y » is usually dropped (« j'irai »). Used in probe item t9.
  - « savoir » + noun exists for things learnt by heart (OQLF: « sait sa table de
    multiplication »), so the savoir/connaître claim is an A1/A2 simplification. Recorded.
- **F3. The 2.1 batch would have approved claims that their quotes do not support** (R2-008).
  On the à/en fixture, 2.1 batches all 9 items, including:
  - `en-tous-pays` (located quote, false generalisation);
  - `en-gerondif` (a gerund read as a place preposition);
  - `en-japon` (in conflict with it);
  - a paraphrase.

  2.2 leaves those 4 to the learner.
- **F4. The 2.1 resolution reactivates silently.** On y/en revision 3, the 2.1 `resolve` marks
  `en-de` approved again, after revision 2 had withdrawn its evidence. 2.2 asks for confirmation
  (`test_revision_3_…`).
- **F5. An all-withdrawn feed is refused by the Workbooks consumer** (R2-051). The
  increment-4 `parseFeed` refuses an empty `items` list, so the 2.1 bundle's
  `feed-y-en-demo-r2.json` cannot be consumed there. Owner decision.
- **F6. A moved quote gets a new evidence ID.** Evidence IDs hash the position, so inserting a
  sentence renames every later evidence ID. The review maps old to new IDs; feeds carry the
  current ones.
- **F7. Attempts did not record their revision** (2.1). The Workbooks table requires one. 2.2
  attempts record `source_revision`; for 2.1 attempts the round trip reports the gap.

## Measured interactions (R2-003, R2-081–R2-083; executed)

Two intents:
- **leave_flagged** (the 2.1 measure): approve what the review batches, leave the rest pending;
- **decide_flagged**: also decide every flagged item one by one.

"First unaided practice" is the first answer to the explain item.

| Source (items; contrast; missing evidence) | Flow | Commands to first practice / first unaided | Approved | Approved without an individual look |
|---|---|---|---|---|
| y/en (7; 1; 1 unsupported) | 2.1 decide_flagged | 4 / 5 | 6 | 1 (`en-vais`, in conflict with a pending item) |
| | 2.2 decide_flagged | 4 / 5 | 6 | 0 |
| savoir/connaître (7; 1; 1 unsupported) | 2.1 / 2.2 decide_flagged | 4 / 5 each | 6 | 0 |
| à/en (9; 1; 0) | 2.1 decide_flagged | 3 / 4 | 9 | 4 |
| | 2.2 decide_flagged | 7 / 8 | 8 | 0 |

**What these numbers say.**
- 2.2 costs nothing more on y/en and savoir/connaître.
- On à/en it costs 4 more commands: the four flagged items are decided one by one instead of
  being approved unread.
- With intent leave_flagged, 2.2 approves 5 items on à/en and 2.1 approves 9.

Full table, items shown and decision records: `expected3/00-interactions.txt`.

## Feed against the Workbooks consumer (R2-051)

Read from the sealed `workbooks-increment-4/handoff-practice-feed/changes.patch`
(`web/src/prototype/practiceFeed.ts`); nothing of theirs was edited.

| Field or rule | Producer (2.1 / 2.2) | Consumer `parseFeed` | Compatible |
|---|---|---|---|
| `schema` | `flh_practice_review_feed_v1` | must equal | yes |
| `source.capture_id`, `proposer` | present | required non-empty | yes |
| `items` | may be empty (all withdrawn) | must be non-empty | **no** (F5) |
| item `answer`, `accepted`, `hidden`, `rubric`, `due*`, `interval`, `text` | never | refused | yes |
| item `measures`, `prompt`, `grading`, `kind`, `options` | present | required | yes |
| outcomes `seq` / `action` / `outcome` | five outcomes | the same five; a reveal must be `revealed` | yes; `skipped` stays out of feeds |
| 2.2 additions (`source_revision`, `recall_type`, `origin`, `provenance`, `feed_id`, `feed_seq`, `withdrawn`, `restored`, `added`) | optional | ignored (fields mapped explicitly) | yes |
| packets | v2 / v3 | `parsePacket` accepts `flh_practice_packet_v1` only | their prototype pins v1; v3 needs their change |

Every 2.2 feed passes both the contract and the consumer rules (`compat-report.json`).

## What Workbooks can consume (R2-097)

`fixtures/practice_v1/workbooks2/`, sealed:
- five feeds;
- replay cases with a reference client;
- `check_feed_compat.py` and `check_storage_rows.py` (stdlib; `--json` for a runner);
- the pinned storage SQL and rows;
- the storage decision record.

The 2.1 bundle `workbooks/` is unchanged.

**Proposed client rules** (their decision):
- **withdrawn:** stop offering, keep history;
- **restored:** offer again;
- **replay:** no change;
- **older feed:** ignore.

## What carries forward between agents (R2-089)

**Carries forward, in the packet:**
- knowledge IDs and the approved wording, with `accepted_from` for an agent correction the
  learner accepted;
- evidence IDs with excerpts (unless omitted);
- accepted exercises with their origin;
- exercises not offered now and why;
- the last confusion (forms and exercise only);
- the next exercise (never its answer);
- continuity against the previous packet;
- proposals awaiting the learner, labelled as not knowledge.

**Stays local:**
- attempt texts and answer keys (a tutor packet carries keys only by explicit choice);
- every decision record;
- the drafts of earlier revisions;
- the conversation with any agent.

**Continuing without the previous agent.** The next session needs no earlier conversation or
directory: `--previous latest` reads the packet kept in the work directory (R2-085).

## Decisions and research (R2-090)

| Decision | Basis |
|---|---|
| D14: never batch an item with a word cue, an open conflict, a paraphrase or a revision | **Hypothesis H8:** one command over many items invites approval without reading (automation bias / complacency, R14). H6 (2.1, unmeasured) still holds; F3 shows the failure on a fixture |
| D15: cues are word checks, labelled "not a proof" | Observed: one non-entailing claim without a cue word is not caught (tested). No semantic model is used |
| D16: no reuse of an approval across a material change; re-confirm after a restore | A design rule from the append-only principle; F4 shows what happens otherwise |
| D17: agent output is provenance, never evidence | A design decision (CLAUDE.md: AI output is metadata; learner input is the source of truth) |
| D18: measure unassisted recall, assisted recall and transfer separately, on a delayed probe | R13: testing beat restudy on delayed tests (2 days, 1 week), while restudy did better at 5 minutes. So an immediate check can mislead. **Hypothesis H9:** transfer to new sentences tracks the goal better than recognition; untested |
| D19: a production with neither form is `unsupported`, not wrong | A design decision: the probe measures the contrast, not French in general |

| ID | Source | What was read | Used for |
|---|---|---|---|
| R13 | Roediger & Karpicke (2006), *Psychological Science* 17(3):249–255, [10.1111/j.1467-9280.2006.01693.x](https://doi.org/10.1111/j.1467-9280.2006.01693.x) ([PubMed 16507066](https://pubmed.ncbi.nlm.nih.gov/16507066/)) | abstract and index record: prose passages; immediate tests without feedback vs restudy; tested after 5 min, 2 days, 1 week | D18 and the trial's limits; not about L2 grammar (an assumption to transfer it) |
| R14 | Parasuraman & Manzey (2010), *Human Factors* 52(3):381–410, [10.1177/0018720810376055](https://doi.org/10.1177/0018720810376055) ([PubMed 21077562](https://pubmed.ncbi.nlm.nih.gov/21077562/)) | abstract and index record: a review integrating complacency and automation bias, attention-based | H8 as a risk to design against; not a learner study |
| R11, R12 | unchanged from 2.1 | — | — |

French references for F2: [OQLF, prépositions devant un nom de pays](https://vitrinelinguistique.oqlf.gouv.qc.ca/23897/la-syntaxe/les-prepositions/preposition-devant-un-nom/les-prepositions-devant-un-nom-de-pays),
[OQLF, savoir et connaître](https://vitrinelinguistique.oqlf.gouv.qc.ca/22416/le-vocabulaire/nuances-semantiques/difference-entre-savoir-et-connaitre),
[Académie, *y*](https://dictionnaire-academie.fr/article/A9Y0002), [Académie, *revenir*](https://dictionnaire-academie.fr/article/A9R2376).
Public evidence: Jules Verne, *Le Tour du monde en quatre-vingts jours*, French Wikisource,
chapters 1, 3, 8 and 9 (revisions 12868439, 3362598, 12528556 and 11144120).

## What the trial cannot show (R2-049)

The dry run uses synthetic responses for one probe in one sitting. It checks that the
summary's arithmetic equals hand-computed totals. It cannot support any claim about long-term
retention, for three reasons:
- there is no spacing schedule and no second delay;
- there is no control condition;
- there are no real learners.

R13 also shows that an immediate check can rank conditions the other way round from a delayed
one. A real trial needs at least two delays, the same probe items at each, and the owner's
approval to record learner answers.

## Compute (R2-078)

**Measured on this host** (2 CPUs, shared):

| Step | Cold | Warm |
|---|---|---|
| Image build | about 165 s (no cache; recorded in the speaking test-entry handoff), 1.41 GB | 7.5–9.0 s (dependency layer cached) |
| Strict suite in the image | — | 22.8 s wall (19.8 s of tests), peak 527 MiB; under `-X dev` 26.6 s, 567 MiB |
| Evaluate 5 clips (speaker 2085, about 77 s of audio) | model load 4–7 s per model | base: compute 9.0–10.7 s (RTF 0.117–0.140), 740 MB; small: compute 34.3–46.5 s (RTF 0.448–0.607), 1.5 GB |

**Estimate for a broadened experiment (not measured).** 30 test speakers × 5 clips (about
2,300 s of audio) per condition, extrapolated linearly from that one slice:
- base: about 5 minutes;
- small: about 17–23 minutes;
- clean plus one noise condition: twice that.

Memory: small needs the 2 GB container limit in `lab_experiment.LIMITS`. Data fetch size and
time are unknown until a source is chosen.

Timing checks should be measured on an idle host, or repeated with the median used: F1 shows a
single run crossing the 0.5 RTF limit.

## Default model (R2-079)

No serving file changed:
- the handoff snapshot lists no change to `tools/speaking/RUNBOOK.md`, `pins.py`, `service.py`,
  `deployment.py` or `configs/`;
- every review still reports `promotion.performed: false` and "serving default unchanged"
  (`test_intake.Standing`).

Only pinned, approved data was read (`data-v1`; its manifest hash equals its dataset manifest).

## Owner decision packet: evaluation data (R2-080)

**The gap.** The review needs 30 independent speakers.

| Pinned v1 manifest | Speakers | More needed |
|---|---|---|
| test | 8 | 22 |
| dev | 4 | 26 |
| dev and test pooled | 12 | 18 |

The 289 FLEURS clips carry no speaker ID, so they add no group.

**Options:**
1. **Keep the current data.** Every comparison stays an observation.
2. **Pool dev and test.** Still 18 short, and the development split is lost.
3. **Add a source.** It must pass `lab intake --proposal` (licence, pinned revision,
   attribution, speaker IDs and provenance, no audio in Git, no personal metadata, condition
   labels, speaker-disjoint splits) and `--source` (no colliding or duplicate speakers). For
   compute see "Compute". Fetching is the owner's step.
4. **Lower `min_groups`.** Not recommended: the interval would rest on fewer independent
   speakers.

## Demos and expected results (R2-094)

| Demo | Command (in its tool directory) | Expected |
|---|---|---|
| Extraction 2.2 | `python3 -B -m flh_extraction practice2 demo3 --out NEW --check` | exit 0; 23 files and the 14-file bundle equal `expected3/`, `workbooks2/` |
| Trial materials | `python3 -B -m flh_extraction practice2 trial --out NEW --check` | exit 0; 5 files equal `probe/expected/` (novelty, no answers in study packets, dry-run totals) |
| Acceptance matrix | `python3 -B -m flh_extraction practice2 matrix --out NEW` | exit 0; 24 of 24 |
| Extraction 2.1 | `python3 -B -m flh_extraction practice demo2 --out NEW --check` | exit 0 (unchanged) |
| Extraction 2.0 | `python3 -B -m flh_extraction practice demo --out NEW --check` | exit 0 (unchanged) |
| Workbooks checks | `python3 -I -B check_feed_compat.py feed-*.json --replay replay-cases.json`; `python3 -I -B check_storage_rows.py` (in `workbooks2/`) | exit 0 each |
| Speaking review | `python3 -B -m flh_speaking lab candidate-review-demo --out NEW --check` | exit 0 (7 files) |
| Speaking lab | `python3 -B -m flh_speaking lab demo --check` | exit 0 |
| Speaking intake | `python3 -B -m flh_speaking lab intake --data-manifest DATA_V1/manifest.jsonl` | exit 0; test 8, 22 more needed |

## Validation (R2-091, R2-095; this run)

| Suite | Command | Outcome |
|---|---|---|
| Extraction | `python3 -B -X dev -W error::ResourceWarning -m unittest discover -s tests -t tests` | 185 run, OK: 7 skipped (optional TINY_SFT/torch), 1 expected failure (FLH-154 F1); 143 before + 37 in `tests/test_practice22.py` + 5 in `tests/test_recall.py` |
| Speaking, host | `python3 -B scripts/run_tests.py` | 124 run, 28 skipped (missing optional dependencies), exit 0 (118 before + 6 in `tests/test_intake.py`) |
| Speaking, strict, packaged code | the `README.md` command "Strict suite on the packaged code" | 124 run, 0 skipped, 0 errors, no network; under `-X dev` the same, 0 ResourceWarnings |
| Older demos | the four commands above | exit 0 each |
| Privacy | the packet privacy gate over 59 shared and fixture files; `export-check` on `expected3` | 0 findings; exit 0. `lab privacy-check` flags 28 UUID-like strings, all synthetic `operation_key` values in `workbooks2/storage-rows.json` (hashes formatted as UUIDs, as the Workbooks proposal asks; not session IDs) |

A first strict attempt mounted only tests and scripts (7 errors, then 5). The errors were from
fixture, contract and lock files the tests read, not code defects; the run above mounts them.

## Owner decisions

- **Batch rules.** Keep cue, conflict and paraphrase items out of batches (D14), or accept the
  extra commands only for some.
- **Workbooks.** F5 (empty feeds); packet v3 in `parsePacket`; client rules for
  withdrawn / restored / replay; the storage amendment; storing `answer_text` at all.
- **Live agent smoke** in both directions, and with one other agent (`PRACTICE.md` §11).
- **French.**
  - A native-speaker check of all synthetic sentences (the y/en, savoir/connaître and à/en
    fixtures, and the probe).
  - Whether to widen the y/en claim (F2).
- **Public excerpts.** Whether the Wikisource attribution recorded in the fixture is enough for
  its six excerpts.
- **Evaluation data.** The option chosen in the decision packet above.
- **Images.** Keep or remove `flh-speaking:cpu-x22-20261119` (new) and the older lab images.
- **Unchanged from 2.1.** Persistence (migration) and a quote-emitting extractor (paid).
