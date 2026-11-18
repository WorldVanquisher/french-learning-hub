# FLH-154: extraction evaluation review before paid runs (2026-11-17)

Review of the three-system extractor comparison (`tools/extraction/COMPARISON_RUNBOOK.md`,
`docs/validation/EXTRACTOR-COMPARISON-V1.md`) before any paid provider request or GPU
job. Baseline `198b23f14489c26cef6ea1c34f96714c843f00db`. That value comes from the task;
agents run no Git.

**Scope and method.** Everything ran offline. Datasets were regenerated twice with
`scripts/comparison_pipeline.sh` inside a network namespace that allowed loopback only.
The renderer's in-process fake server needs loopback; nothing else was reachable.
The synthetic systems were scored through the real comparison path: the production
validator, `compare`'s row accounting, and the `decision.py` gates. No provider call, AWS
command, model run, download or daily-instance action took place. No code, data or
scoring module changed. The pinned matrix (`b3f66eda…`) and scoring version
(`e5b4e012…`) are still valid.

Every "system" below is synthetic: the oracle returns the machine-authored references.
The results show what the harness does, not how any model behaves.

Evidence, all regenerable:

- `FLH-154/review-checks.json` is the per-check results, with summary `.md`.
- `FLH-154/review_checks.py` regenerates them.
- `FLH-154/agent-review.json` holds the agent's reading of the review packets and of every held-out unit.
- `FLH-154/image-packaging-smoke-cpu.json` is the local image's stack check.
- `FLH-154/sigterm-buffer-demo.json` is the buffered-write demonstration.

## Checkpoints

| # | Item | Status | Result |
|---|---|---|---|
| 1 | Revisions of frozen eval, challenge slice, scorer | DONE | Frozen eval `99602feb…` (200), challenge `b004f6ed…` (96), comparison slice `de4c61e5…` (472), scoring version `e5b4e012…`, validator sources as pinned. All 8 pin cross-checks hold. Gaps: `compare` never re-checks the pinned validator sources, and `decision.py` is not pinned at all (F5) |
| 2 | Category-only shortcut | DONE | Frozen eval: the cue is perfect (20 `other` = 20 zero references; 180 non-`other` = 180 unit references). A category-only system, written independently of `controls.py`, matches every frozen decision. On rb it makes 20/20 false extractions, and committed `shortcut-repro.json` equals the regenerated copy |
| 3 | Constant-empty and oracle controls | DONE | Full 472-row slice through `compare` and the gates (table below). Category-only and constant-empty are ineligible; the oracle passes |
| 4 | Learning intent inside pairs | DONE | Challenge variants differ only in category, explanation and resolution in the rendered payload. No human-confirmed cue contradicts a reference. 10 rb units (the same 10 in swap) lose their only lexical anchor with the replaced explanation; all 10 were read and the intent holds (F11) |
| 5 | Prioritized synthetic labels | DONE (agent reading) | 44 packet items read: 38 agree, 5 edits suggested, 1 disagreement. Rubric gap: no label for an inaccurate statement (F9). Packet verdict fields left empty |
| 6 | False premises | DONE | All 86 false-premise or wrong-explanation records carry a unit, and none repeats the premise as true. Unwarranted abstention on them is not gated (F4) |
| 7 | Bilingual pairs; translations not independent | DONE | All 114 distinct held-out units read in EN and ZH (frozen 45, boundary 69; the challenge's 23 are reused frozen units): no drift, and the heuristic flags none. The frozen eval's 180 unit records cover 45 objectives (F3) |
| 8 | Train/eval duplicates and leakage | DONE | `check` and `challenge-check` pass. Independently: 0 ids, 0 learner texts, 0 quoted French sentences and 0 targets shared between held-out sets and training or the SFT files |
| 9 | Manifest digests before/after regeneration | DONE | 25 committed artifacts equal the regenerated ones: 18 byte-identical, and 7 rendered jobs and checks differ only in the job-name timestamp. Run 1 = run 2 over 74 files |
| 10 | Held-out references absent from prediction inputs | DONE | 944 prompt rows (slice and both shards) are inputs-only. No reference target, statement, example or rationale appears; the upload list and channel URIs carry no references |
| 11 | Invalid JSON, extra prose, unsupported keys | DONE | 20 crafted outputs on the real validator; 472/472 rows accounted. `null`, `{}` and `{"units": null}` count as correct abstentions (F2). Four malformed-file shapes abort the comparison (F7) |
| 12 | Malformed evidence and truncation stay in denominators | DONE | Validity, abstention, over-abstention and the paired metrics count every row. Unit F1 does not (F1) |
| 13 | Prediction shards | DONE | a = 272, b = 200; no overlap, union = slice, slice order kept, no challenge group split. Each job is bound to its shard hash and has no `limit` parameter. Regeneration is identical, and `compare` ignores row order |
| 14 | Decision stays pending with a run missing | DONE | All 7 subsets with a run missing give PENDING. No human F1, < 100 judged, missing review verdicts and missing tuned losses all give PENDING; a refused comparison gives REFUSED |
| 15 | Weak abstention blocks promotion | DONE | rb abstention 0.85 or paired consistency 0.875 makes the best-F1 system (0.99 vs 0.70) ineligible, and the other system wins. At 0.90 and 0.917 it passes. Category-only is never chosen. Rounding cannot flip a gate at these denominators; the 0.05 win margin is float-dependent (F6) |
| 16 | Local tokenizer and model assets vs pinned revision | DONE (readiness BLOCKED) | Revision `851bf6e8…`: config.json, tokenizer_config.json, chat_template.jinja and the weight index are PRESENT_OK. tokenizer.json, vocab.json, merges.txt and both weight shards are MISSING anywhere on this machine and in the image. Nothing was substituted |

Item 3, synthetic controls on the full slice (production validator, then the gates of
`decision.py`):

| System | Validity | Frozen abst. / over-abst. | rb abst. / over-abst. | rb false extractions | Paired consistency | Paired accuracy (abstain groups) | Frozen F1 (heur.) | Gates failed |
|---|---|---|---|---|---|---|---|---|
| oracle | 1.0 | 1.0 / 0.0 | 1.0 / 0.0 | 0 | 1.0 | 1.0 (1.0) | 1.0 | none |
| category-only | 1.0 | 1.0 / 0.0 | **0.0** / 0.0 | **20** | **0.0** | 0.0 (**0.0**) | 1.0 | rb abstention, paired consistency, abstain-group accuracy |
| constant-empty | 1.0 | 1.0 / **1.0** | 1.0 / **1.0** | 0 | 1.0 | 0.375 (1.0) | — | over-abstention on frozen and rb |

## Findings

No finding is a regression: each is pre-existing behaviour of the merged comparison
harness. Following the task's rule, none was fixed. Each fix touches the pinned
scoring code or decision rules. It should be decided and re-pinned before any result
exists; re-scoring saved predictions later is free, but changing the rules after
seeing results breaks the pre-registration.

| ID | Severity | Location | Failure scenario | Impact | Suggested fix and verification |
|---|---|---|---|---|---|
| F1 | medium | `quality.report`, semantic section (used by `compare` and `quality --judgments`) | The oracle truncates its 9 frozen answers with the most units (18 of 205 reference units). Strict validity is 0.981 and every gate passes, yet unit F1 stays 1.0, equal to the oracle | Precision and recall use valid rows only, so a system that fails structurally on hard rows loses no F1. Human F1, which decides the 0.05 win margin, is computed the same way | Count the reference units of non-scorable rows as unmatched in recall, or report a strict F1 beside it, then re-pin the matrix. Rerun `review_checks.py`: the cp12 probe F1 must drop below 1.0 |
| F2 | medium | `comparison.account` (`strict_schema_findings` results other than extra or missing keys are ignored) | A model answers `{}`, `null` or `{"units": null}`. The production parser accepts each as zero units, and the row counts `valid_empty`, a correct abstention on a zero reference | The abstention gates (≥ 0.90 on 20 zero references per part) can be met with output the strict schema forbids, and strict validity also counts these rows as valid | Treat `top_level_not_object` and `units_not_list` as non-scorable, then re-pin. Verify with cp11: these three cases must not be `valid_empty` |
| F3 | medium | `decision.py` `HUMAN_EXAMPLES_MIN = 100`; frozen eval composition | The 180 frozen unit records cover 45 objectives in 20 linked clusters, with up to 8 records per objective. 25 objectives are asked in more than one learner language, and 38 French sentences recur across records. Frozen and rb share every learner text, and the challenge's 23 reference units are frozen-eval units | "≥ 100 judged examples" can be met with ~25 objectives; translated or reused items and frozen/rb pairs are not independent evidence | Judge and report human F1 by objective (or with a cluster bootstrap over the 45 points), require all 45 objectives covered, and never pool frozen and rb judgments of one text |
| F4 | medium-low | `decision.gates` | The oracle abstains on all 8 frozen false-premise and wrong-explanation records. Over-abstention is 0.044 and the system stays eligible | A system that refuses exactly the hardest corrective cases is not blocked | Report over-abstention by `case_type`, and decide a pre-registered limit (for example ≤ 1 of 8) before the runs |
| F5 | low-medium | `matrix.compare`; `comparison.scoring_version` | `compare --render BIN` with a binary built from changed Go validation code is accepted, because the matrix pins `validator_sources` but compare never re-checks them. `decision.py` sits outside the scoring version | Statuses or gates can change while the matrix hash stays the same | compare re-hashes `VALIDATOR_SOURCES` and refuses on a mismatch; pin `decision.py` (criteria version) in the matrix or record it in the report |
| F6 | low | `decision.decide` (`best - second < WIN_MARGIN`) | 0.60 vs 0.55 gives NO_WINNER, but 0.65 vs 0.60 gives WINNER. On a 0.001 grid, 494 of 951 exact 0.050 leads count as below the margin | The boundary case depends on binary floating point | Compare `round(best - second, 3)`, and add a test for exact-margin leads |
| F7 | low | `comparison.account_with_validator`; `matrix.compare`; `records.load_jsonl` | An `output_text` that is an object or a number makes `extraction-render validate` exit 1. A raw row without `output_text` raises "mixes raw outputs and production results", and a cut last line raises JSONDecodeError | The whole comparison aborts. It is loud, not a silent miscount, and `predict.py` writes none of these, but hand-made or partial files need cleaning by hand | Account such rows individually (for example `unparseable:not_a_string`), and treat a cut final line as a missing prediction |
| F8 | low | `predict.py` (buffered writes, no flush) | At `MaxRuntimeInSeconds`, SageMaker sends SIGTERM. In the image (Python 3.12, 8 KB buffer), 12–28 finished demo rows were lost per kill and lines were never cut (`sigterm-buffer-demo.json`) | A capped shard under-reports finished rows, which skews the inference rate the runbook uses to re-shard. Whether SageMaker uploads `/opt/ml/model` after a runtime stop is UNVERIFIED | Flush after every row (or handle SIGTERM), then repeat the demo |
| F9 | low | `REVIEW_PACKET_V3.md` rubric; references | The agent read 44 items. `ext-trn-00235` misses a « c'est / il est » unit (UNDER_SPLIT). Edits are suggested for `ext-trn-i2-0001` and `ext-trn-00965`, where « pas de » after any negation ignores « être »; for `ext-trn-i2-0047`, an absolute « visiter »; for `ext-trn-00051`, where the canonical stresses the thing case; and for `ext-trn-00377`, which teaches « louer » instead of the false friend « location ». Held-out units over-generalize twice: colour words from nouns (« rose » agrees) and « lequel » after any preposition (« dont » after « de ») | The rubric has no FALSE_CLAIM label, so an over-general rule can only be marked OK + edit | Add FALSE_CLAIM to the v3 rubric; the owner gives the human verdicts (`agent-review.json` is not one) |
| F10 | info | `python3 -m flh_extraction check` | Without `--out`, the checks run and then `dump(None)` raises TypeError | Usability only | Make `--out` required |
| F11 | info | rb/swap probes | 10 rb units (ext-evl-0004, 0005, 0025, 0046, 0056, 0121, 0127, 0128, 0131, 0195) are spelled out only by the explanation that rb replaces | The intent holds, but on these rows rb measures knowing the answer rather than copying it, and the heuristic `not_anchored_units` will flag correct predictions there | Read rb grounding counts with this list |
| F12 | info | `quality.parse_diagnostic` | A JSON array, a JSON string, NaN or a string confidence get status `unparseable:parses` | Misleading name; the rows are non-scorable anyway | Rename the label to `parses_not_contract` with the next re-pin |
| F13 | info | `tools/extraction/TRAINING_RUNBOOK.md` §3–10 | The sections still describe the pre-comparison flow: one predict-eval job on frozen-only prompts, 200 paid requests, and "an untuned job needs a template variant", although `predict-base` exists. §1c points to `COMPARISON_RUNBOOK.md` | An owner following §3–8 literally would upload the wrong prompt file | Follow `COMPARISON_RUNBOOK.md` and the readiness README; trim §3–10 in a later docs task |

## Item notes

- **4.** Three abstain groups (g21 « tout », g26 « à Lyon », g31 « combien de ») have
  a conflicting cue that names a form present in the learner's correct sentence. Zero
  units is consistent with the policy (bc-004: facts merely present in a correct
  sentence are not objectives). These are the hardest abstentions, and a human should
  confirm them first.
- **6.** The 86 records are 8 frozen eval, 8 boundary, 1 train and 69 increment. The
  6-word-sequence echo heuristic flags `ext-trn-i2-0028` and `ext-trn-i2-0061`. Both
  share a correct phrase with the learner's text; neither repeats the premise.
- **8.** The lexical near-duplicate check cannot see a translation. The point,
  canonical and headword checks (0 overlap) and the shared-French-sentence check (0
  for frozen, rb, swap and challenge) cover cross-language duplicates. The only
  sentence shared with training is the generic « je vais manger » in the boundary
  set, which is not part of the comparison slice.
- **9, after items 21–40.** `FLH-154-decision-memo.md` (G1) makes an incomplete run
  PENDING, so the regenerated decision fixture now names the fixture's 6 missing and
  6 duplicated predictions. The dated copy in `EXTRACTOR-COMPARISON-V1/` is kept;
  `review_checks.py` accepts exactly that change (verdict still PENDING, gates
  unchanged). The reviewer sample's three files are compared too.
- **10.** The provider input file (`comparison-inputs.jsonl`, 472 rows) holds only
  `id` and the six production input fields.
- **13.** The runbook concatenates the shards a then b; that order differs from the
  slice's, which is harmless because `compare` keys by id (shuffled, a+b and slice
  order give identical reports).

## Items 17–20

| # | Item | Status | Result |
|---|---|---|---|
| 17 | Offline runtime and packaging prerequisites | DONE (readiness BLOCKED) | Host Python has no torch, transformers, peft or tokenizers; the stack lives in the image. Local image `flh-extractor-sft:smoke-cpu` (`6f6b1942…`), checked with `--network none`, is STALE (transformers 4.57.6 vs 5.21.1, no `qwen3_5`; tokenizers 0.22.2 vs 0.23.3; huggingface-hub 0.36.2 vs 2.4.0), CPU-only, with no model files. 57/57 tests pass inside it |
| 18 | Rendered job examples | DONE | Six jobs are named `flh-extractor-<role>-<UTC>`, unique, ≤ 63 characters. Caps: smoke 1,800 s, experiment 10,800 s, four predictions at 3,600 s each, all equal to the renderer's bounds. 1 × ml.g5.xlarge, network isolation, image by digest. Credentials are placeholders only (account `000000000000`, placeholder role and bucket, zero digest), with no environment variables and no secret-like keys. The renderer refuses a tag instead of a digest, a missing role and a missing bucket |
| 19 | Cost assumptions and owner steps | DONE (documented, nothing executed) | See below |
| 20 | Go/no-go memo | DONE | See below |

Missing prerequisites (item 17):

1. A GPU image built from `requirements-train.txt`; the build runs `flh_extraction.packaging`.
2. `tokenizer.json`, `vocab.json` and `merges.txt` at revision `851bf6e8`.
3. Both weight shards (9,319,737,856 bytes).
4. Real values for `REGISTRY`, `IMAGE_DIGEST`, `EXEC_ROLE_ARN`, `BUCKET`, and, after the experiment, `ADAPTER_KEY`.
5. The owner's verdicts on the 44 review-packet items.

## Cost assumptions (item 19)

| Step | Cap | Worst case |
|---|---|---|
| sft-smoke | 1,800 s | $0.70 |
| predict-base-a, -b | 3,600 s each | $1.41 each |
| sft-experiment | 10,800 s | $4.22 |
| predict-eval-a, -b | 3,600 s each | $1.41 each |
| **GPU compute total** | | **$10.56** |
| Current extractor baseline | 472 requests, no retries | not priced: depends on the model chosen at run time |

- **Rate.** `ml.g5.xlarge` training at $1.408 per hour in us-east-1, from
  `TRAINING_RUNBOOK.md` §10 (Price List extract of 2026-11-07). It was not
  re-checked: no network.
- **Storage.** Cents per month for ~9.3 GB of weights plus datasets.
- **Provider request size.** The request text totals 1,146,923 characters, with a
  maximum of 2,648 per request. The token count is unknown, because no tokenizer
  of the provider was used.
- **Model fit.** Whether Qwen3.5-4B fits these caps is untested. The smoke job's
  step time decides the experiment, and the first prediction shard's rate
  decides re-sharding.

## Owner steps, in order (none was executed)

0. **Decide F1–F6** (scoring and decision rules) before any result exists.
   Implement the accepted ones in a separate task, then
   `bash tools/extraction/scripts/comparison_pipeline.sh OUT` to re-pin
   `comparison-matrix.json` and `experiment-manifest.json`, and commit them.
1. **Tokenizer files only**, at the pinned revision (the command printed in
   `docs/validation/EXTRACTOR-COMPARISON-V1/asset-check.json`, `owner_command`):
   `hf download Qwen/Qwen3.5-4B tokenizer.json tokenizer_config.json chat_template.jinja config.json vocab.json merges.txt model.safetensors.index.json --revision 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a --local-dir "$D"`,
   then `sha256sum --ignore-missing -c tools/extraction/configs/qwen3.5-4b-851bf6e8.sha256` in `$D`,
   then `python3 -B tools/extraction/scripts/verify_profile.py … --tokenizer "$D" …`
   (`then` in the same file). Gate: 0 prefix errors, 0 prompts over 1,280
   tokens, 0 answers over 512.
2. **Human review.** Fill `verdict`, plus `decision_ok` and `label` for v3, in
   `tools/extraction/review/review-packet-v2.jsonl` and `review-packet-v3.jsonl`;
   `FLH-154/agent-review.json` lists where to look first. If references change,
   regenerate and re-pin. Prompts and provider inputs do not change, so no run is
   wasted.
3. **GPU image.** `docker build -t flh-extractor-sft:gpu tools/extraction`, then
   push it and record the digest (`TRAINING_RUNBOOK.md` §3). The build fails on a
   stale stack.
4. **Real values.** Put them in a `values.json` outside the repository, then
   `bash tools/extraction/scripts/comparison_pipeline.sh OUT values.json`. Check
   that `OUT/experiment-manifest.json` equals the committed one, then upload the
   files listed in `OUT/readiness/input-manifest.json` to their S3 keys
   (readiness README steps 4–5).
5. **GPU jobs.** For each job, in order:
   `aws sagemaker create-training-job --region "$REGION" --cli-input-json file://OUT/readiness/rendered/<job>.json`.
   - `sft-smoke`: projected experiment ≤ 9,000 s.
   - `predict-base-a`, then `predict-base-b`: 272 + 200 rows. If shard a hits the
     cap, stop and re-shard (and see F8).
   - `sft-experiment`: output-manifest checks.
   - Set `ADAPTER_KEY` to the experiment's job name and re-render.
   - `predict-eval-a`, then `predict-eval-b`.
6. **Retrieve predictions.** For each prediction job, copy
   `s3://$BUCKET/extractor/output/<job>/output/model.tar.gz`, extract
   `predictions.jsonl` and check its row count. Concatenate shard a then b per model.
7. **Paid baseline** (owner decision, 472 requests):
   `EXTRACTOR_PROVIDER=openai OPENAI_MODEL=<model> extraction-render run -in OUT/slice/comparison-inputs.jsonl -out OUT/current-results.jsonl -max-requests 472 -confirm-paid-calls`
   (key from the owner's environment, never the repository).
8. **Scoring.** Run `compare`, then `decision-report`, exactly as in
   `COMPARISON_RUNBOOK.md`. Human F1 is per objective if F3 is accepted.

## Go/no-go (item 20)

**Paid runs today: NO-GO.** The hard prerequisites are not met:

- the tokenizer and weights are missing, so token lengths are unmeasured;
- no GPU image exists that was built from the pinned requirements; the local one is stale;
- none of the 44 reference-review verdicts exist.

Four decision-rule defects (F1–F4) should be settled and re-pinned before any
result exists. Otherwise the pre-registered decision would be judged with rules
known to favour structural failure (F1), degenerate output (F2), an inflated
sample (F3) or refusal of corrective cases (F4).

**GO for the no-cost owner steps 0–4**, in that order. Once they pass, the first
paid step is the smoke job (≤ $0.70). Its step time decides the experiment.
The 472-request provider baseline depends only on step 0 and the owner's
payment decision; it does not depend on the GPU steps or the reference review.

**What the synthetic, offline review established** (it shows the harness, never a model):

- The frozen evaluation cannot reveal the category shortcut; rb and the paired
  challenge do. Category-only and constant-empty systems are ineligible under the
  pinned gates; the oracle passes.
- References never reach prompts or training data. Regeneration is
  deterministic, and the six jobs stay inside their caps with placeholder
  credentials only.
- Every slice row gets exactly one status for 20 output shapes. The gaps are F2
  and F7.
- Validity, abstention and paired metrics count every row; F1 does not (F1).
- The decision stays PENDING whenever a run, a human criterion or a review
  verdict is missing, and weak abstention or cue dependence blocks a system
  whatever its F1.

**What still requires a real model or a human** (measured nowhere):

- **Model behaviour.** Whether untuned or tuned Qwen3.5-4B takes the category
  shortcut (rb abstention, paired consistency), and every metric of the three
  systems.
- **Real outputs.** Their strict validity, and how often they are degenerate
  (`{}`, `null`: F2) or truncated at 512 tokens (F1).
- **Hardware.** Token lengths and masking with the real tokenizer; inference rate
  and memory on `ml.g5.xlarge`; whether 272 prompts fit in an hour; smoke step
  time and dev-loss behaviour.
- **Current extractor.** How it behaves on the 472 inputs.
- **Human judgment.** Unit F1 and false-claim rates, per objective; verdicts on
  the 44 packet items; confirmation of the three hardest abstain groups (g21,
  g26, g31).

## Reproduce

All commands run from the repository root, offline:

```sh
X=/path/outside/the/repo   # large outputs stay outside the repository
unshare -rn sh -c 'ip link set lo up && exec bash tools/extraction/scripts/comparison_pipeline.sh "$0"' $X/run1   # loopback only
unshare -rn sh -c 'ip link set lo up && exec bash tools/extraction/scripts/comparison_pipeline.sh "$0"' $X/run2
unshare -rn sh -c 'ip link set lo up && exec "$@"' sh python3 -I -B docs/validation/FLH-154/review_checks.py --repo . \
  --pipeline $X/run1 --pipeline2 $X/run2 --out docs/validation/FLH-154 --asset-dir <dir with the pinned small files> \
  --image-packaging docs/validation/FLH-154/image-packaging-smoke-cpu.json
(cd tools/extraction && python3 -B -m unittest discover -s tests -t tests)          # 57 OK, 7 skipped (need torch)
(cd deploy/aws/sagemaker-extractor && python3 -B -m unittest test_render)           # 5 OK
go vet ./cmd/extraction-render && go test ./cmd/extraction-render                     # ok
docker run --rm --network none --read-only --tmpfs /tmp --entrypoint sh -e TINY_SFT=/work/sft-sample.jsonl -e HOME=/tmp \
  -v "$PWD/tools/extraction:/code:ro" -v <40-record SFT sample>:/work/sft-sample.jsonl:ro -w /code flh-extractor-sft:smoke-cpu \
  -c 'python3 -B -m unittest discover -s tests -t tests'                              # 57/57 OK
```

`review_checks.py` builds no image and downloads nothing. Without `--asset-dir`
every asset reads MISSING. The rendered job names carry the render time, so they
are compared after normalising the timestamp.
