# Extraction 2026-11-21: cross-subject source → evidence → recall (EXT-001 to EXT-150)

**Lane.**
- Worktree `~/workspace/overnight/20261120-r4/extraction`.
- Branch `worker/20261121-extraction`, owner-confirmed.
- Lane files: `tools/extraction`, `deploy/aws/model-runtime/`, this record and the interface
  notes `docs/plans/EXT-20261121-interface-notes.md`.

**Operations.** No AWS call, no model download, no paid job and no Git command. Data is
synthetic. The other lanes were reached by cross-session messages only.

Evidence paths written `evidence/…` are in the local handoff, outside Git. Checkpoints were
written every ten items.

## 1. Revisions (EXT-091)

The repository forbids agents any Git command, including read-only, so **the initial and final
commits are unverified**. The content manifests stand in for them:

| | Record |
|---|---|
| Initial | owner-confirmed branch; content manifest `baseline/start-manifest.tsv` (1,923 paths, SHA-256 `4b0b3ffa…`, 2026-11-21T00:48:33-05:00); every R4 file present and identical |
| At EXT-100 | `snapshot-100/`: 74 changed paths (73 added, 1 modified) |
| Final (EXT-150) | `snapshot-150/` in the handoff (§8) |

## 2. What was delivered (EXT-001 to EXT-100)

**A runnable first slice, done by item 010.** `python3 -I -B tools/extraction/scripts/xsubject.py --check`
replays this from an empty directory and compares with `fixtures/xsubject_v1/expected/`:
- a synthetic music-theory source (English);
- three evidence-bearing units;
- the normal `practice2` CLI loop, attempt first;
- exact spans;
- span-supported recall;
- the French y/en workflow as an unchanged control.

Since then the slice has grown to:
- **sources:** music theory and chemistry, the chemistry source in contract v2;
- **review inbox** with reasons;
- **rerun and revision cases:** identical rerun, prose edit, changed claim, moved evidence,
  kept rejection, duplicate, and source disappearance against extractor failure;
- **recall and review:** a correction path, source links through the practice feed, a
  revisit after a revision, and a contradictory source pair;
- **portable handoffs** for Claude Code and Codex;
- **privacy cases.**

It had 27 parity checks at EXT-100; it has 31 at EXT-150.

| Area | Items | Main artifacts |
|---|---|---|
| First slice | 001–010 | `flh_extraction/units.py`, `scripts/xsubject.py`, `fixtures/xsubject_v1/sources/music_thirds.r1.json` |
| Inbox and decisions | 011–020 | `units.review_reasons`, `inbox`, `check_span`, `overlaps`; `UNITS.md` §1–5 |
| Contract | 021–030 | `units.read_source` / `to_v2` / `validate_units`; `chem_water_states.v2.json`; `UNITS.md` §6–9 |
| Reruns and revisions | 031–040 | `evidence_key`, `compare`, `rerun_status`; `music_thirds.r2/r3.json`; `UNITS.md` §10 |
| Recall and review | 041–050 | `recall_items`, `correction_path`, `contradictions`, `vocabulary_reference`; `UNITS.md` §11 |
| Quality evaluation | 051–060 | `flh_extraction/unit_eval.py`, `fixtures/xsubject_v1/gold/gold_v1.json`, `eval/`; `UNITS.md` §12 |
| Portable handoff | 061–070 | `flh_extraction/unit_handoff.py`; `expected/handoff/`; `UNITS.md` §13 |
| Model readiness | 071–080 | `scripts/model_readiness.py`; `deploy/aws/model-runtime/MODEL-READINESS-20261121.md` |
| Privacy and validation | 081–090 | `music_quoted_instructions.r1.json`; `expected/privacy/`; tests |

The per-item status and evidence are in the checkpoints:
- 001–010 done;
- 011–048 done;
- 049 done: delivered to the Workbooks Vocabulary lane, integration pending;
- 050–072 done;
- 073 done for the model-free baselines; the extraction model baseline is **blocked**: the
  Qwen weights are absent;
- 074–090 done;
- 091–100 done (this section, §3–7).

## 3. Verified experiments with raw denominators (EXT-093)

| Experiment | Result |
|---|---|
| Slice parity (`expected/parity.json`) | 27/27 checks pass. The French draft ID is `d-22ff0c49f9d7`, unchanged |
| Unit quality (`eval/scorecard.json`) | authored: coverage 8/13, evidence-supported 7/8, duplicates 0/8, missing 4/13, bad-span 1/13. Sentence baseline: 7/13, 6/10, 0/10, 6/13, 0/13; extra 4 |
| Revision comparison | r2 → r3: kept 4, moved 4, added 1, removed 0 evidence keys. The diff is order-independent, after a fix (it depended on order when two units shared a claim key) |
| Rerun status | 5 of 5 cases classified as expected (`identical_rerun`, `extractor_failed` ×2, `source_disappeared` ×2) |
| Recall | music: 4 prompts, 0 refused. Chemistry: 4 prompts, 1 claim refused for 2 reasons |
| Fixture workflow | warm median 0.29 / 0.31 / 0.24 ms (preprocessing / review / export), 20 runs. Cold process 76 ms, 5 runs. Peak RSS 35.4 MiB |
| Test suites | `test_xsubject` 48 OK. Hermetic suites all pass: extraction 271 run, 7 optional skips, 1 known expected failure (§7) |

## 4. Claims that need human evidence review (EXT-094)

- **Music theory and chemistry facts in the synthetic sources and the gold set:** semitone,
  thirds, triads, octave frequency, relative keys, boiling and freezing points, altitude.
  They were written by one author and checked by no subject expert.
- **The gold set.** It was written by the same author as the sources and the authored
  proposals, so the authored scores are an upper bound.
- **Lexical matching.** The chemistry altitude claim ("lowers the boiling point") is scored
  `wrong_claim` only because the gold value is "below". A person should rule on it.
- **Contradictions are left to the learner.** The minor-third conflict (lesson notes against
  forum copy) is unresolved on purpose.
- **Stand-in agents are scripted functions.** No Claude Code or Codex session read these
  handoffs.

## 5. Consumer-facing contract changes (EXT-095)

All are new and additive. **No existing contract changed:**
- the service identity stays `flh-extraction-rules@e978b6c2bdb6/flh_extraction_service_v1/flh_practice_drafter_v1`;
- no service code file changed;
- the feed, packet, loop and agent-context contracts are untouched.

New schemas, all experimental:
- `flh_practice_source_v2`;
- `flh_learning_units_v1`;
- `flh_review_inbox_v1`;
- `flh_learning_units_compare_v1`;
- `flh_rerun_status_v1`;
- `flh_unit_contradictions_v1`;
- `flh_vocabulary_reference_v1`;
- `flh_units_eval_v1` and its `.scorecard`;
- `flh_unit_handoff_v1`;
- `flh_unit_followup_v1`;
- `flh_model_readiness_v1`.

One test fixture changed: `fixtures/r4_v1/SMOKE.expected.txt`. The feed interop now walks 25
samples instead of 24, because of the new music feed; every check still passes.

## 6. Owner replay (EXT-096)

```sh
cd tools/extraction
python3 -I -B scripts/xsubject.py --check              # the slice from a fresh directory
python3 -B -m unittest tests.test_xsubject             # 48 focused tests
python3 -B -m flh_extraction.unit_eval                 # the quality table
python3 -I -B scripts/r4_smoke.py --expect             # R4 compatibility
cd ../.. && python3 -B scripts/ci/python_suites.py --hermetic
```

## 7. Hand-offs, recommendation and blockers (EXT-097 to EXT-100)

**Release (EXT-097).**
- Six runtime assumptions were confirmed, one corrected (the smoke costs $0.704).
- Model prerequisites and stop conditions were sent (`MODEL-READINESS-20261121.md` §6).
- Release asked to be told before any change to the envelope, health and readiness routes,
  manifest or deployment ID.

**Workbooks (EXT-098).**
- Sent: the inbox example, the vocabulary reference, and the music practice feed
  (`expected/recall/feed.json`, `flh_practice_review_feed_v1` with additions; units
  `flh_learning_units_v1`).
- Workbooks found no blocking field. Integration on their side is pending.

**Next measurable milestone (EXT-099).**
- An independent gold set: someone other than the proposal author writes 20 documents across 4
  subjects.
- Targets: authored coverage ≥ 0.8 and evidence-supported ≥ 0.9, with the sentence baseline as
  the floor.
- One owner session timed end to end (inbox, batch, recall, loop).

**Blockers.**
- HEAD is unverified (no Git).
- The Qwen3.5-4B files are absent locally, so there is no extraction-model baseline; the owner
  fetches them with the `check_model_assets` command.
- No learner study: H2 and time on task are estimates.
- Consumers have not integrated: UI, Workbooks, Vocabulary.
- Publishing, AWS and promotion are the owner's.

**Next queue ID: EXT-101.**

**Expected failures and skips.**
- **Extraction suite:** 1 known expected failure, FLH-154 F1, listed apart since R2. 7 optional
  skips need `TINY_SFT` and torch.
- **Speaking on the host:** 29 skips need numpy, av or torch.
- **Private-staging suite:** 2 skips, not this lane's.

## 8. EXT-101 to EXT-150 (appended queue)

| Area | Items | Main artifacts | Result |
|---|---|---|---|
| Generalisation corpus | 101–110 | `sources/hw_basics.v2.json`, `history_messages.v2.json`; `gold/gold_v2.json` (frozen 01:22:50, SHA-256 `099cc62f…`); `CATALOG.json`, `COVERAGE.md`; `scripts/xsubject_catalog.py` | 9 sources in 12 files, 22 gold claims in 6 documents; dev and eval split; 6 coverage gaps recorded. Fixed: instruction-like headings rendered as real Markdown headings in an opted-in handoff, now fenced |
| Failure analysis | 111–120 | `unit_eval --analyze`, `eval/analysis-{dev,eval}.json`, `regression/section-label-false-accept.json` | Separate counts for missed claims and unsupported accepts, and for boundary and selection errors. Per document and per topic. Top false accepts: section labels and diary narrative. False rejects: 0. Targeted change on frozen eval: extra 2 → 1, supported 6/8 → 6/7, coverage 6/9 → 6/9. **118 blocked:** no model assets or outputs |
| Evidence lifecycle | 121–130 | `units.write_atomic`; `UNITS.md` §15; `CONSUMERS.json` version 2026-11-21.2 | CRLF, moved, unrelated-edit and corrected evidence each behave as specified. A torn decision line is repaired with identical units. Metadata survives export and reimport |
| Practice | 131–140 | `flh_extraction/unit_practice.py`, `practice/music_thirds.sheet.json`, `expected/practice/` | 4 intended recall types, answer bases, a multi-answer span flag, tolerant grading (12 graded examples), drops with reasons. Two agent formats cite the same evidence. Sent to Workbooks |
| Reproducibility | 141–150 | handoff `evidence/141-150/`; `INPUTS.json`; `eval/SCORECARD-v2.json` | Fresh replay equal. PATH-only runs pass. Repeated runs equal once timing fields are excluded. The real merged Workbooks parser accepts 25/25 feeds. Identity and path scan: 0 hits |

**Downstream JSON and real parsers (EXT-147).**
- The feed examples were run through Workbooks' merged `parseFeed` and `applyFeed`: 25/25 agree
  with the mirror and the replay cases are equal. This was a scratch copy of `web/` at the base,
  outside every worktree.
- Every other new schema has no consumer parser yet. Each is checked by this lane's own
  validators (`validate_units`, `check_span`, `read_source`), which is not a cross-lane
  verification.
- No TypeScript was changed, so `npm run typecheck` does not apply.

**Final verification (EXT-148):**

| Check | Result |
|---|---|
| `tests.test_xsubject` + `test_r4` + `test_service` (`-X dev`, ResourceWarning as error) | 106 run, OK |
| `r4_smoke --expect` | equal |
| Sealed 2.2 demos (3) | equal |
| `python_suites --hermetic` | all 6 pass; extraction 291 run (7 skips, 1 known expected failure); trapped calls 0 |

## 9. Owner replay: one success and one known limitation (EXT-150)

```sh
cd tools/extraction
# success: the whole cross-subject slice from a fresh directory, compared byte for byte (31 parity checks)
python3 -I -B scripts/xsubject.py --check
# known limitation: lexical matching scores a correct paraphrase as wrong. "Lower air pressure at high altitude
# lowers the boiling point" is wrong_claim because the gold value is "below"
python3 -B -m flh_extraction.unit_eval | grep -A1 "chem-water-states" | head -2
```

**Status of the appended queue:**
- 101–117 done;
- 118 blocked (no model assets or model output);
- 119–150 done.

Blockers carried forward:
- no Git (HEAD unverified);
- the Qwen files are absent;
- no learner study;
- consumers have not integrated;
- publishing and cloud are the owner's.

**Next queue ID:** none in this batch (EXT-150 was the last).
