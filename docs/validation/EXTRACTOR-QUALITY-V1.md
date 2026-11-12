# Extractor quality v1: audit, increment, harness, Qwen3.5-4B profile, AWS readiness (2026-11-12)

Lane `extractor-quality`, worktree `flh-workers/extraction`. Every number
below was produced by a command run in this session on deterministically
regenerated data. **No model was trained or evaluated, no weights were
downloaded, no network or AWS call was made, and no quality improvement is
claimed.** Every label is synthetic, machine-authored and unreviewed.

Inputs regenerated first; all four hashes equal the recorded values
(`tools/extraction/README.md`): boundary `5960b48a…`, train `8ec9b172…`,
quarantine `98e8e581…`, eval `99602feb…`. Base SFT files reproduce
`2d9e7efe…` / `fd58903c…` and the eval prompts `68a2c499…`.

Detailed outputs: `EXTRACTOR-QUALITY-V1/` (audits, control matrix, oracle
quality report, increment check, profile verification, LoRA comparison).

## Checkpoint 1: training-data audit by failure mode — DONE

`python3 -m flh_extraction audit` (new, `flh_extraction/audit.py`). Counts are
HEURISTIC triage, not verdicts. Base training set: 1,200 records, 1,353 units.

| Failure mode | Count | Concrete example |
|---|---|---|
| Over-splitting | 0 unit pairs that look like one objective; **0 records** teach "several examples of one rule = one unit" (eval tests 2, boundary 8) | — |
| Under-splitting | 30 records whose correction makes ≥ 2 separate edits with fewer units (244 pairs); the session's reading finds one likely genuine: `tr.feminin_eur` | `ext-trn-00235`: « C'est une actrice » vs « Elle est une acteuse » corrects *c'est / elle est* **and** *-trice*, one unit |
| Duplicate units | 0 within a record; 0 identical inputs with different labels; **122 distinct unit texts for 1,353 occurrences** (max 17, median 11) | « ne… rien » appears verbatim 17 times |
| False premises | **1** misconception record, **0** wrong explanations, **0** `unreviewed` analyses (eval tests 8, boundary 8); 0 statements echo a premise | `ext-trn-00282` « Pour moi « vin » et « vent » c'est le même son » is the only one |
| No learning objective | 203 zero-unit records (16.9 %); 122 come from one template with one fixed explanation; **category `other` ⇔ zero units in 203/203 training and 20/20 evaluation records** | `ext-trn-01130` « Je serai en retard… », category `other`, explanation « A practical message. » |
| Bilingual drift | 0 after the checker learned placeholders and glosses (a first version flagged 38 = 3 texts, all false positives such as « à + person » → « à + 人 ») | — |
| Unsupported claims | 0 French-language units without any lexical anchor; 86 anchored only in the explanation; **1,327/1,353 examples are not from the interaction** (policy rule 8 prefers them) | `ext-trn-00044` « Je la téléphone » → « pronoms COI lui, leur »: only the explanation names it |

Input distribution vs production (`internal/analyzer`, the default): training
had 0 rule-based explanations and 0 `unreviewed` analyses; the rule-based
analyzer gives `other` only to input without letters.

## Checkpoint 2: targeted synthetic increment — DONE (182 candidates, unreviewed)

`authoring/bank_increment_v2.py` (hand-written) → `generate_increment.py`
→ `increment_candidates.jsonl` `5a40c6e7…`. Every unit is a training-bank
point reused verbatim, so no new objective and no evaluation objective enters.

| Mode | Records | Targets |
|---|---|---|
| misconception | 54 | false premises (rule 5) |
| wrong_explanation | 15 | an `unreviewed` analysis that is wrong (rule 6) |
| zero_production_cues | 40 | abstention under the real analyzer's category (never `other`) |
| counter_shortcut | 29 | an objective with an uninformative explanation; 6 with category `other` |
| fragmentation / several_edits_one_objective / two_errors | 14 / 6 / 14 | splitting boundaries |
| duplicate_question / explanation_extra | 4 / 6 | duplicates; rules only the explanation raises |

123 inputs carry the production analyzer's exact category and explanation
(`extraction-render analyze`, new offline mode; frozen in
`increment_v2_rule_based.json`); 133 are `unreviewed`. Provenance: `origin
synthetic`, `review_status unreviewed`, `label_status
machine_authored_unreviewed`, `increment extraction_increment_v2`,
`explanation_source`, rationale per record.

Validation (`increment-check`, exit 0): **182/182 valid through the
production validator** with units unchanged; no new point, no point in the
other split, **no evaluation point, canonical or headword**; 0 exact
duplicates and 0 near pairs ≥ 0.5 with evaluation or boundary inputs; 0 near
duplicates of base inputs; combined split check passes (1,245 train / 137 dev).

Audit after (base + increment): misconception records 1 → 55, wrong
explanations 0 → 15, `unreviewed` 0 → 133, rule-based explanations 0 → 123,
fragmentation records 0 → 14, zero-unit records with a non-`other` category
0 → 40, unit records with `other` 0 → 6. The 11 new "not anchored" flags are
error-only inputs (« le solution » → « noms en -tion féminins »), as intended.

## Checkpoint 3: evaluation harness — DONE

`python3 -m flh_extraction quality` reports separately, each with its basis:
structural validity (+ parse diagnostics: `code_fence`, `think_block`,
`truncated_json`, `truncated_at_max_new_tokens`, …) and unit counts and
abstention (**exact**); split/merge/duplicate, grounding and bilingual
fidelity (**heuristic** or **human**, never summed). An invalid output is no
longer counted as an abstention, and the matcher now labels a merged unit
MERGED instead of MISSED (existing test updated accordingly).

Production-input probes of the frozen evaluation (never training data,
`probe`): `rb` = the 200 inputs as the default analyzer presents them (0
`other`, 199 `unreviewed`); `swap` = zero-unit references get the analyzer's
category, unit references get `other`.

Controlled failures (`control-matrix`, real production validator):

| Control | Result |
|---|---|
| code fence / think block / truncated JSON | CAUGHT: validity −1.0; diagnosed as `code_fence` 200, `think_block` 200, `truncated_json` 200 |
| count drop / over-split / merge / duplicate | CAUGHT: exact-count rate −0.125 / −0.9 / −0.125 / −0.9; split+merge+duplicate +1 / +180 / +25 / +180 |
| over-abstain / hallucinate on zero refs | CAUGHT: 180 unit refs answered empty / 20 false extractions |
| unsupported swap / bilingual drift | CAUGHT: 154 unsupported, 139 not anchored / 205 units flagged |
| false claim (wrong statement, same label and forms) | **NOT CAUGHT** by any automatic metric: needs a human claim judgment |
| category shortcut (abstain iff category `other`) | **hidden on the frozen evaluation** (every metric equals the oracle); on `rb`: abstention 1.0 → 0.0, 20/20 false extractions, while heuristic F1 only drops 1.000 → 0.953; on `swap`: 20 false extractions and 180 over-abstentions |

Review packet (`review-packet`, `tools/extraction/review/REVIEW_PACKET_V2.md`
+ `.jsonl`): 25 items, P1 6 (zero units under production categories,
inherited probe references), P2 9 (misconceptions by kind, wrong
explanations), P3 6 (splitting), P4 2 (base under-split flags), P5 2;
verdicts empty.

## Checkpoint 4: Qwen3.5-4B profile — DONE offline; token counts and model comparison PENDING

Local assets: the pinned revision's small files from the earlier handoff
(hashes OK: `config.json`, `tokenizer_config.json`, `chat_template.jinja`,
`model.safetensors.index.json`); **no `tokenizer.json`, vocabulary, merges or
weights; no GPU**; the CPU image `flh-extractor-sft:smoke-cpu` has transformers
4.57.6 (the pinned requirement is 5.21.1). Nothing was downloaded.

`scripts/verify_profile.py` in that image (network off), on all 1,382 v2 SFT records:

| Check | Result |
|---|---|
| Model | `Qwen/Qwen3.5-4B` revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`; `Qwen3_5ForConditionalGeneration`, 32 layers (24 linear, 8 full attention), vocabulary 248,320, tied embeddings |
| Template (transformers' own renderer) | default prompt ends `<think>\n` (thinking on); profile `enable_thinking: false` ends `<think>\n\n</think>\n\n` |
| Masking (text level) | prompt is a prefix of the conversation in 1,382/1,382; continuation equals target + `<|im_end|>\n` in 1,382/1,382 (matches `train.encode`'s cut); 0 think markers in targets |
| LoRA targets on real weight names | 200 modules: linear-attn in_proj_qkv/in_proj_z/out_proj 24 each, self-attn q/k/v/o 8 each, MLP gate/up/down 32 each; 0 outside the text stack (164 vision/MTP modules untouched) |
| Prediction parsing | `<|im_end|>` is special (removed by decoding); `<think>`/`</think>` are not (a generated block reaches the parser, now diagnosed as `think_block`); rows record `generated_tokens` and `stopped` |
| Truncation | PENDING token counts; the increment's variable text is shorter than the base's longest (≤ 1,563 vs 2,245 UTF-8 bytes; same system prompt), base max measured 980 tokens on 2026-11-11 |
| Tests in the image (torch backend on) | 37/37, incl. tiny-fixture LoRA training on base + increment records and the new stop-reason test |

Older profile, measured where both can be: applying the `qwen3-1.7b` target
list to the Qwen3.5 checkpoint would adapt attention in 8/32 layers (0
linear-attention projections) and collide with 7 vision/MTP names; the
`qwen3.5-4b` regex adapts all 32. Quality comparison between the profiles:
**PENDING** (no weights, no GPU). Owner commands:
`deploy/aws/sagemaker-extractor/readiness/README.md` step 1 (tokenizer) and
`TRAINING_RUNBOOK.md` §9a (`untuned_baseline.sh`, now with `PROBE`; ran end
to end in the CPU image on a tiny random fixture: plumbing only).

## Checkpoint 5: AWS training readiness — DONE (prepared, nothing submitted)

`deploy/aws/sagemaker-extractor/readiness/`: `input-manifest.json` (train
`4dab4e7b…` 1,245, dev `31285fe8…` 137, prediction prompts 100 `d63dc7f5…`
and 400 `2974e13e…`, S3 keys, base revision), `output-manifest.json`, four
jobs rendered with placeholder account values (`sft-smoke` 12 steps ≤ 0.5 h,
`predict-base` untuned ≤ 1 h — the template the runbook said was missing,
`sft-experiment` 234 steps ≤ 3 h, `predict-eval` ≤ 1 h), the gated sequence
(worst case $9.15 of compute) and the pre-registered criteria, mechanised by
`promotion-check`. Offline mechanical checks: renderer tests 4/4;
`build_readiness.py` ran; SageMaker-layout train → predict dry run passed in
the CPU image; refusals of an `eval` channel and of mismatched hashes tested;
`promotion-check` returns PENDING for the oracle (human criteria open) and
NOT_ELIGIBLE for the category-shortcut control.

## The strongest insight tonight

The data teach a cue the product never shows. In training and in the frozen
evaluation, "zero units" coincides exactly with `effective_category = other`
and an explanation that states why there is nothing to extract; production's
default analyzer never says `other` for text and explains with
`Local classification selected "grammar" because rule …`. A model can
therefore score perfectly on the frozen evaluation by reading the category,
and the frozen evaluation cannot tell. The control proves the mechanism
(hidden on frozen, 20/20 false extractions under the real analyzer); whether a
trained Qwen3.5-4B actually learns the cue is **not measured**. Consequences
already in place: the increment breaks the correlation in training, every
model comparison runs on the frozen set **and** the `rb` probe, and
promotion requires the probe.

## Not verified (owner)

Token-level lengths with the real tokenizer; any real-model output (untuned
or trained); training time and memory on `ml.g5.xlarge`; the current
extractor's baseline (paid); the increment's French and Chinese by a human
(the review packet); transformers 5.21.1 in a locally built image.
