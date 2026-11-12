# Extractor comparison v1: cue shortcut, paired challenge, comparison matrix (2026-11-12)

Lane `extractor-comparison`, worktree `flh-workers/extraction`. Every number
below comes from a command run in this session on deterministically
regenerated data. **No model was trained, run or downloaded; no provider,
network or AWS call was made; every real comparison run is NOT PERFORMED.**
Every label is synthetic, machine-authored and unreviewed.

Inputs regenerated first; all equal the recorded hashes: train `8ec9b172…`,
increment v2 `5a40c6e7…`, frozen evaluation `99602feb…` (unchanged by this
lane), boundary `5960b48a…`.

Status: all twelve checkpoints DONE (7 with its measurement pending the owner's tokenizer download); lane READY_FOR_INTEGRATION.
Everything below regenerates with `bash tools/extraction/scripts/comparison_pipeline.sh OUT`
(run twice: every artifact byte-identical; experiment manifest `manifest_sha256` `27a14f8b…`).

## 1. Category-only abstention shortcut — DONE

`python3 -m flh_extraction shortcut-repro` runs three synthetic systems through
the production validator on the frozen evaluation and the two production-style
probes (`EXTRACTOR-COMPARISON-V1/shortcut-repro.{json,md}`: input and output
SHA-256, scoring version, confusion counts).

| Slice (SHA-256) | System | True abstain | False extraction | Over-abstention | True extraction | Abstention | Heuristic F1 |
|---|---|---|---|---|---|---|---|
| frozen `99602feb…` | oracle | 20 | 0 | 0 | 180 | 1.0 | 1.0 |
| frozen | category-only | 20 | 0 | 0 | 180 | 1.0 | 1.0 |
| frozen | constant empty | 20 | 0 | 180 | 0 | 1.0 | — |
| rb `9e9e0b24…` | category-only | 0 | **20** | 0 | 180 | **0.0** | 0.953 |
| swap `5a3ec4de…` | category-only | 0 | 20 | **180** | 0 | 0.0 | — |

On the frozen evaluation the category-only outputs are **byte-identical** to the
oracle's (outputs SHA-256 `89e157a0…` for both): no metric can separate them.
Under the production analyzer's cues (`rb`), every zero-unit reference gets a
false extraction while heuristic F1 drops only to 0.953.

## 2. Paired cue challenge slice — DONE (96 records, unreviewed, evaluation only)

`authoring/bank_challenge_v1.py` (hand-written) → `generate_challenge.py` →
`challenge_candidates.jsonl` `b004f6ed…` (deterministic). 32 groups fix the
learning intent (learner text, context, reference); each has three variants
that change only category, explanation and resolution:

| Group intent | Groups | aligned | conflicting | rb (production analyzer, frozen in `challenge_v1_rule_based.json`) |
|---|---|---|---|---|
| extract (17 one-unit, 3 two-unit) | 20 | objective's category, correct explanation, accepted | `other`, dismissive (10) or no summary (10), unreviewed | non-`other`, unreviewed |
| abstain | 12 | `other`, why nothing arose, accepted | real category + a rule the learner never raised, unreviewed | non-`other`, unreviewed |

Objectives are evaluation-bank points reused verbatim (23 points; none in
training). Learner texts are new, in French, English and Chinese. Provenance:
`origin synthetic`, `review_status unreviewed`, `label_status
machine_authored_unreviewed`, generator, rationale and `meta.challenge`
(group, variant, intent, cue) per record. Splits are assigned per group,
stratified by intent: `challenge_dev` 8 groups (24 records), `challenge_test`
24 groups (72 records).

## 3. Production validation and leakage — DONE

`challenge-check` (`EXTRACTOR-COMPARISON-V1/challenge-check.json`, exit 0):

- **Production validator:** 96/96 references valid (`extraction-render expected`), units unchanged; 96/96 rendered.
- **Within groups:** identical learner text, context and reference; no two variants with the same model-visible input; the category cue flips between aligned and conflicting in every group; `rb` is never `other`.
- **Between groups:** 0 exact duplicates, 0 near pairs (word 3-gram Jaccard ≥ 0.5).
- **Against train + dev** (base and increment, 1,382 records), the **frozen evaluation** (200) and the **boundary cases** (80): 0 exact duplicates, 0 near pairs ≥ 0.5; 0 points, canonicals or headwords shared with training.
- **Splits:** one split per group, both intents in both splits; `sft` refuses 96/96.

Negative controls in `tests/test_comparison.py`: a variant moved to the other
split, a changed reference, identical variants, a missing variant and a
training input copied into the slice each fail the check.

## 4. Review packet expansion — DONE

`review-packet --challenge … --v3-out` → `tools/extraction/review/REVIEW_PACKET_V3.md`
and `review-packet-v3.jsonl`: 19 new items (the v2 packet is unchanged),
P1 cue invariance (4 challenge groups from `challenge_dev`) and grounding
disagreements (3 units the heuristic finds only in the explanation), P2 false
premises (3, highest premise overlap), P3 under-splits (3), P4 over-splits (3,
most similar unit pairs), P5 bilingual drift (3, highest risk score; the
heuristic flags none). Three-step rubric and one illustrative example for each
label (OK, OVER_SPLIT, UNDER_SPLIT, FALSE_PREMISE, BILINGUAL_DRIFT, UNSUPPORTED,
CUE_DEPENDENT). Verdicts are empty.

## 5. Paired-consistency metric — DONE

`paired-consistency` / `paired-demo` (`EXTRACTOR-COMPARISON-V1/paired-demo.{json,md}`),
all 32 groups, every output through the production validator:

| System | Paired consistency | Paired accuracy | Cue flips | Objective consistent (heur.) | Aggregate F1 (heur.) | Abstention | Over-abstention |
|---|---|---|---|---|---|---|---|
| oracle | 32/32 | 32/32 | 0 | 32 | 1.0 | 1.0 | 0.0 |
| category-only | **0/32** | 0/32 | **32** | 0 | 0.662 | 0.333 | 0.333 |
| constant empty | 32/32 | **12/32** | 0 | 32 | — | 1.0 | 1.0 |

Consistency catches the cue shortcut that aggregate F1 softens (0.662); paired
accuracy catches the constant answer that consistency alone would reward. The
category-only system is perfect on the `aligned` variant (decision accuracy
1.0), the cue set the training data teaches.

## 6. Comparison matrix — DONE (every real run NOT PERFORMED)

`comparison-slice` + `comparison-matrix` pin one 472-record slice (frozen 200,
`rb` 200, `challenge_test` 72 in whole groups), the `knowledge_extraction_v2`
output schema and developer-instruction hashes, the decoding settings of each
system and the scoring version (SHA-256 over the scoring modules, plus the
validator's Go sources). Systems: current extractor (`extraction-render run`,
one paid request per input, owner decision), untuned Qwen3.5-4B
(`rendered/predict-base-a/-b.json`) and tuned Qwen3.5-4B (`rendered/predict-eval-a/-b.json`):
greedy, `max_new_tokens` 512, thinking off, bfloat16. The bfloat16 pin is
now real: `predict.py --dtype` and the prediction templates' `dtype`
hyperparameter (before, the dtype was left to the installed transformers).
`compare` scores only systems with predictions and refuses a slice or scoring
version that differs from the matrix. Pinned matrix: `deploy/aws/sagemaker-extractor/readiness/comparison-matrix.json` `b3f66eda…`
(scoring `e5b4e012…`, schema `8335a158…`, prompts `cb859d8d…`). All three rows: **NOT PERFORMED**.

## 7. Tokenizer and model assets — DONE (measurement PENDING owner download)

`scripts/check_model_assets.py` (`EXTRACTOR-COMPARISON-V1/asset-check.json`,
exit 3): `config.json`, `tokenizer_config.json`, `chat_template.jinja` and
`model.safetensors.index.json` are present with the pinned hashes (earlier
handoff); **`tokenizer.json`, `vocab.json` and `merges.txt` are missing** on
every local filesystem and in the CPU image, as are both weight shards named
by the pinned index. No other tokenizer was substituted. The report carries
the owner command (pinned revision, small files only, checksum-verified) and
the `verify_profile.py --tokenizer` command that then measures token lengths
and masking on the real records.

## 8. Prediction parsing — DONE

`parsing-fixture` writes the slice's references as raw outputs with one
known fault on every seventh row; `compare` scored it with the real Go
validator (`EXTRACTOR-COMPARISON-V1/parsing-fixture-*.{json,md}`). Every status equals
the injected count; 472 references → 472 statuses, plus 1 unknown-id row
counted separately:

| Status | Count | Fault |
|---|---|---|
| valid_units / valid_empty | 348 / 57 | none |
| unparseable:truncated_at_max_new_tokens | 7 | cut at half, `stopped` = max_new_tokens |
| unparseable:leading_text / trailing_text | 9 / 7 | prose before / after the JSON |
| unparseable:code_fence / think_block | 7 / 7 | fenced JSON / a `<think>` block |
| valid_extra_keys | 6 | a per-unit `evidence` key |
| invalid_output | 12 | confidence 1.5 or blank `statement_zh` |
| missing_prediction / duplicate_prediction | 6 / 6 | dropped / doubled rows |

Finding: the production parser (Go `json.Unmarshal`) **accepts** a unit with
an extra `evidence` key and drops it; only the provider's strict schema
forbids it. A local model is not bound by that schema, so `compare` reports
these rows as `valid_extra_keys`, outside the scorable set. Non-scorable rows
count as invalid, never as abstentions: the fixture's frozen abstention is
0.85, not 1.0.

## 9. Packaging against the pinned requirements — DONE

`flh_extraction/packaging.py` compares the installed stack with
`requirements-train.txt`; it follows pip's rule that a local variant such as
`2.15.0+cpu` satisfies `==2.15.0`. Run inside `flh-extractor-sft:smoke-cpu`
with the network off (`EXTRACTOR-COMPARISON-V1/stack-check-smoke-cpu.json`, exit 4):

| Package | Pinned | In the image | Status |
|---|---|---|---|
| transformers | 5.21.1 | 4.57.6 | MISMATCH (does not know `qwen3_5`) |
| tokenizers | 0.23.3 | 0.22.2 | MISMATCH |
| huggingface_hub | 2.4.0 | 0.36.2 | MISMATCH |
| torch / peft | 2.15.0 / 0.21.2 | 2.15.0+cpu / 0.21.2 | OK |

The image was built on 2026-11-10 from the older requirements, and its baked-in
code predates `models.py`. The SageMaker entry point now runs this check before
training or prediction and writes `stack-check.json` beside the outputs. On a
mismatch it fails the job, unless `FLH_ALLOW_STACK_MISMATCH=1` is set; only the
tiny fixtures set it. The Dockerfile build now runs the same check. In the
image (current code mounted read-only, torch on), the tiny offline fixture ran
**57/57 tests OK**: LoRA training on base and increment records, and the
SageMaker-layout train → predict dry run, which logged `stack_mismatch_allowed`
with the exact mismatch (`EXTRACTOR-COMPARISON-V1/image-entry-tests.txt`). That
run proves the code paths only; it says nothing about Qwen3.5. A test proves
that a stale stack is refused when the flag is absent.

## 10. Rendered jobs (not submitted) — DONE

`build_readiness.py` now renders six jobs from the pinned slice:

- `sft-smoke` and `sft-experiment`;
- untuned prediction `predict-base-a` and `-b`;
- adapter prediction `predict-eval-a` and `-b`.

Shard a holds the frozen evaluation and challenge_test (272 prompts), shard b
the `rb` probe (200). `readiness-checks.json` (pass) verifies offline:

- **Input digests:** every hash hyperparameter is a manifest file's hash, every
  channel points at that file's hashed S3 key, and the shards partition
  `comparison-prompts.jsonl`.
- **Held-out reference isolation:** no reference-bearing channel or key, every
  prompt is `{id, messages: [system, user]}` with no reference field in the
  payload, and only the SFT files and the two shards are uploaded.
- **Output naming:** six distinct job names and output prefixes.

**Defect fixed:** the committed package gave the untuned and adapter prediction
jobs the same name (`flh-extractor-predict-20261112-025505`), because the name
held only the run type and the time. The second submission would have
collided. Names now carry the role (`flh-extractor-predict-base-a-…`).

Worst-case compute is $10.56, up from $9.15, because prediction is sharded to
stay inside the reviewed one-hour bound.

## 11. Promotion decision report — DONE

`decision-report` (`flh_extractor_decision_v1`, pre-registered) gives one of
four verdicts:

- WINNER_FOR_OWNER_DECISION, only when all three runs are measured, every human
  criterion is decided, and one eligible system leads on human unit F1 by
  ≥ 0.05;
- PENDING, for a missing run, missing human judgments or an open review item;
- NO_WINNER, when no system is eligible or the lead is too small;
- REFUSED.

Weak abstention or cue dependence makes a system ineligible whatever its F1.
The tests use synthetic result files through the CLI:

- **pass:** the tuned model leads and is proposed;
- **fail:** a tuned model with rb abstention 0.0 is never the winner, all-weak
  systems give NO_WINNER, a constant-empty model fails on over-abstention, and
  a lead of 0.02 gives NO_WINNER;
- **pending:** a missing run, missing human F1 and 14 open review items each
  give PENDING;
- **refused:** a refused comparison gives REFUSED.

On the real parsing fixture, with one system measured, it answers **PENDING**
(`EXTRACTOR-COMPARISON-V1/decision-fixture.md`).

## 12. Hand-off to Release — DONE

- `tools/extraction/scripts/comparison_pipeline.sh` regenerates everything
  offline.
- `deploy/aws/sagemaker-extractor/readiness/experiment-manifest.json`
  (`manifest_sha256` `27a14f8b…`) holds the hashes of every dataset, slice, shard, generator and
  config, plus the matrix, scoring and input-manifest hashes and
  `real_runs_performed: 0`.
- `tools/extraction/COMPARISON_RUNBOOK.md` is the owner runbook. It keeps three
  lists apart: measured mechanics, findings from synthetic controls, and
  conclusions that need a real model or human review.

## The strongest insight

Aggregate scores cannot see the cue shortcut, and the frozen evaluation cannot
show it at all. A system that decides abstention from the category alone
produces output **byte-identical** to the oracle on the frozen evaluation. On
production-style cues it fails every zero-unit case (20/20). On the paired
challenge it is inconsistent in **every** group (0/32), while its aggregate F1
still reads 0.662. Paired consistency catches it. Paired accuracy and the
over-abstention gate catch the opposite failure, a constant empty answer
(32/32 consistent, 12/32 accurate). Both now gate the decision.

Whether a real Qwen3.5-4B, untuned or tuned, learns the shortcut is **not
measured**. That question is exactly what the matrix is pinned to answer.

## Not verified (owner)

- Any real output of the three systems (all NOT PERFORMED; the current
  extractor needs 472 paid requests).
- Token lengths and masking with the real tokenizer (files missing locally).
- Inference rate and memory on `ml.g5.xlarge`, and whether 272 prompts fit in
  one hour.
- A GPU image built from the pinned requirements, including the new build-time
  check.
- Human review of the challenge, increment and probe references (packets v2 and
  v3).
- Human-judged unit F1.
