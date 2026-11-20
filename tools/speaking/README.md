# Speaking model: local French transcription (research, training, service)

Turns a learner's recorded French answer into a **draft transcript** that the
learner checks and corrects before FLH gives feedback. Runs on CPU, offline,
on the same machine as FLH; audio never leaves it.

What it is **not**: a pronunciation or fluency scorer, a grader, a public
service or an autostarted daemon. The transcript is a draft: Whisper tends to
smooth over learner mistakes, so the learner's confirmation stays required.

Evidence and decisions:
- [`docs/validation/SPEAKING-MODEL-V1.md`](../../docs/validation/SPEAKING-MODEL-V1.md): research, baseline and pilot.
- [`docs/validation/SPEAKING-LOCAL-PROVIDER.md`](../../docs/validation/SPEAKING-LOCAL-PROVIDER.md): the FLH provider, real inference, robustness and the punctuated experiment.

Contract (service API, statuses, errors, retention): [`CONTRACT.md`](CONTRACT.md).
Operations (build, deploy, check, roll back): [`RUNBOOK.md`](RUNBOOK.md).

## Layout

| Path | What |
|---|---|
| `flh_speaking/pins.py` | pinned model revisions and dataset files (size + SHA-256 or git blob) |
| `flh_speaking/fetch.py` | downloads and verifies pinned files (public, ungated, no credentials) |
| `flh_speaking/mls.py`, `prepare.py` | speaker- and book-disjoint MLS French subset + FLEURS fr_fr dev; decoded once to 16 kHz mono PCM16; sealed manifest with leakage checks; FLEURS fr_fr train with punctuation (`prepare-punctuated`) |
| `flh_speaking/audio.py` | the one audio convention (PyAV/FFmpeg, in memory) and signal statistics |
| `flh_speaking/model.py` | Whisper decoding policy `flh_speaking_transcribe_v1` with abstention rules |
| `flh_speaking/textnorm.py`, `evaluate.py`, `compare.py`, `probes.py` | WER/CER, cluster bootstrap, breakdowns, paired comparison, acceptance rule, robustness probes |
| `flh_speaking/robustness.py` | short-clip, language-policy and noise sets: model outputs under the current and the warning-only language policy |
| `flh_speaking/train.py`, `sagemaker_entry.py` | resumable fine-tuning; SageMaker wrapper |
| `flh_speaking/service.py`, `deployment.py` | local HTTP service and its deployment identity |
| `configs/` | training configs (`smoke-tiny`, `pilot-base-encoder`, `ablation-base-full`, `punct-base-encoder` and its local smoke) |
| `requirements*.txt`, `requirements-*.lock` | direct dependencies; full hash-locked sets for the CPU and GPU images |
| `aws/` | SageMaker pilot template, IAM policy, bounded renderer, cost and launch commands (not launched) |
| `fixtures/frontend/` | real backend responses from the local end-to-end run |
| `scripts/` | end-to-end runs through FLH (`e2e_flh.py`, `verify_local_provider.py`) and the service benchmark |
| `tests/` | standard-library tests (host) and image tests (audio, rules, service, training); `scripts/run_tests.py` runs them offline or with `--require-deps` |

## Build and run (offline)

```sh
cd tools/speaking
docker build --build-arg TORCH_INDEX=cpu -t flh-speaking:cpu .     # needs network once (pip)
W=$HOME/flh-speaking-work                                          # outside the repository
python3 -m flh_speaking fetch --dest $W/sources --what whisper-base mls fleurs   # network once; verified
# Every later step runs with no network, 2 GB, 4 CPUs:
RUN="docker run --rm --oom-score-adj 1000 --network none --memory 1536m --memory-swap 1536m --cpus 4 --user $(id -u):$(id -g) -e HOME=/tmp -v $W/sources:/sources:ro"
$RUN -v $W/data:/data flh-speaking:cpu prepare --sources /sources --out /data
$RUN -v $W/data:/data:ro -v $W/out:/out flh-speaking:cpu evaluate \
    --model /sources/openai/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb --data /data --split test --out /out/base-test.json
```

Training (resumable: rerun the same command after an interruption):

```sh
$RUN -v $W/data:/data:ro -v $PWD/configs:/configs:ro -v $W/train:/out flh-speaking:cpu train \
    --config /configs/pilot-base-encoder.json --data /data \
    --base /sources/openai/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb --out /out
```

Service (loopback only; publish the port on 127.0.0.1):

```sh
docker run --rm --oom-score-adj 1000 -p 127.0.0.1:8765:8765 --memory 1536m --cpus 4 -v $W/sources:/sources:ro \
    flh-speaking:cpu serve --model /sources/openai/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb --host 0.0.0.0 --port 8765
```

`--host` accepts loopback and private addresses. The unspecified address
(`0.0.0.0`, all interfaces) is accepted only inside a container, where the
host's `-p 127.0.0.1:8765:8765` mapping is what keeps the service off the LAN;
outside a container it is refused. `GET /manifest` gives
the `deployment_id` to set as `SPEAKING_TRANSCRIPTION_MODEL` with
`SPEAKING_TRANSCRIPTION_PROVIDER=local`; `CONTRACT.md` §6 has the FLH settings
and `RUNBOOK.md` the deployment, check and rollback steps.

## Speaking Lab (compare two transcripts against one reference)

Standard library only, CPU, offline. The whole demo, checked against its shipped
expected output, is one command:

```sh
cd tools/speaking && python3 -B -m flh_speaking lab demo --check
```

`lab compare CASE.json [--audio FILE] [--json OUT] [--text OUT]` runs any case.

**Inputs.** A case (`flh_speaking_lab_case_v1`) holds:
- one reference;
- the audio fixture's `sha256` (with `--audio`, the file must match it);
- exactly two results, each with `label`, `model_id`, `config_id`, `text` and an optional `provenance`.

**Outputs.** One computation gives:
- the versioned JSON (`flh_speaking_lab_result_v1`);
- the compact text, which is rendered from that JSON.

For each result they show:
- the raw text and the `flh_fr_asr_norm_v1` normalized text;
- a side-by-side token alignment, deterministic and with the same tie-breaking
  as the WER scoring;
- substitution, deletion and insertion counts, with accent-only substitutions
  marked `S~`;
- WER and CER.

Every result also carries the model, configuration and audio identity. A
paired line gives the error difference.

| `status` / reason | Meaning | CLI exit |
|---|---|---|
| `compared` | both results aligned against the reference | 0 |
| `insufficient_evidence` + `empty_reference` | the reference has no word after normalization: no lexical comparison is possible | 3 |
| reason `short_reference` | fewer than 3 reference words: reported, `paired.evidence` = `low` | 0 |
| reason `empty_prediction` | a result has no text: every reference word counts as deleted | 0 |
| (error) | invalid case, or `--audio` does not match the case's hash | 2 |

It is word agreement, **not** a pronunciation, fluency or accent grade. A
difference can come from the speaker, the recording or the model, and the lab
cannot tell which. One case is one observation; model decisions use the paired
evaluation (`compare`, `accept`).

The shipped case is `fixtures/lab/synthetic_fr_case.json`, a hand-written
French sentence and two hand-written transcripts: A changes one accent, B omits
one word. Its expected output is `*.expected.json` and `*.expected.txt`. Its
audio is a generated 0.6 s tone (`lab.synthetic_audio()`): a placeholder
identity, not speech. No model was run on it.

**Three views per result** (`views`), so a gain can be attributed:
- `cased_punct`: as written, with case and punctuation as tokens;
- `uncased_punct`: case ignored;
- `normalized`: `flh_fr_asr_norm_v1`.

Two counts make the source of an error visible:
- `case_attributable_errors`: the extra errors of the cased view over the uncased one;
- `punctuation_edits`: edits that involve a punctuation token.

The policy is versioned by `textnorm.NORM_VERSION`. Every result also carries a
behaviour fingerprint (`normalization_fingerprint`), and a test pins it, so a
silent rule change fails the tests.

**Paired batch.**

```sh
python3 -B -m flh_speaking lab batch --refs fixtures/lab/three_rows/refs.jsonl \
    --a fixtures/lab/three_rows/a.jsonl --b fixtures/lab/three_rows/b.jsonl [--json OUT]
```

The inputs:
- references: JSONL `{"id", "reference", "speaker"?}`;
- each result file: a first `{"header": {"label", "model_id", "config_id"}}`
  line, then `{"id", "text"}` rows.

What it reports:
- matched and missing IDs, with reasons, before anything else;
- empty references (excluded) apart from empty predictions (counted as deletions);
- sample counts on every aggregate;
- a ranking only when both results cover exactly the same samples. Otherwise
  the run exits 4, `not_ranked`.

The three-row fixture is hand-computed in `tests/test_lab.py`:
- WER: A 3/11, B 2/11;
- CER: A 9/57, B 10/57. CER ranks them the other way, which is why one score is not enough.

**Quality-slice variants.**

```sh
python3 -B -m flh_speaking lab variants --case fixtures/lab/synthetic_fr_case.json --out DIR
```

This writes WAV variants and `variants.json` (`flh_speaking_lab_variants_v1`)
outside the repository:
- volume: a gain that would clip is refused and recorded, never clipped;
- boundary silence;
- white noise at a fixed seed and SNR;
- a speed resample.

Each variant has:
- its own SHA-256;
- the source's ID as `group_id`, so counts can use groups rather than variants;
- reproducible tags (`TAG_RULES`).

The source bytes are verified unchanged. Without speaker metadata the counts
say `no speaker metadata`. On the shipped tone the variants test mechanics
only; they say nothing about speech recognition.

**Groups and slices.**
- Reference rows may carry `group_id` (from `variants.json`) and `tags`. The
  batch reports samples and groups, a group-level paired count, and a note when
  variants make samples outnumber groups.
- Per tag value it reports both WERs and B − A. A missing tag counts as
  `(unlabelled)`, and each sample sits in exactly one cell per key.
- Only slices with at least `MIN_SLICE_GROUPS` (5) groups are ranked, as
  regressions or improvements. Smaller ones are listed as observations.
- `uncertainty` gives B − A in WER with a 95% percentile interval. It comes
  from resampling groups with replacement: 2,000 resamples, seed 20261119,
  deterministic. With fewer than 30 groups the interval is marked unstable. It
  describes these groups redrawn, not other speakers, learners or microphones.

**Review.** `lab batch --review FILE` reads reviewer records
(`flh_speaking_lab_review_v1` JSONL; an invalid line refuses the file):
- `accept` records a pass;
- `invalid` and `retry` take a sample out of the aggregates, with its reason;
- `correct` records a corrected text and its source beside the original
  hypothesis, which stays the one scored.

Every diagnostic says what kind it is:
- `measured`;
- `rule`;
- `heuristic`;
- `supplied` by the runtime, or `not_supplied`. Confidence is never invented.

Three more behaviours:
- A result the runtime reports as another language keeps its text, with a
  `possibly_wrong_language` note.
- An abstention gets a retry suggestion.
- Aggregates are given with and without abstentions, on the same samples.

`lab silence WAV` applies the explicit local rule: 30 ms frames above
−70 dBFS, at least 0.3 s, the service's defaults; both values are configurable.
Walkthrough: `fixtures/lab/review/` (one pass, one retry, one abstention) and
its `expected.txt`.

**Candidates.**
- `lab candidate manifest --name whisper-small` prints the candidate ID. It
  covers the pinned files, the CPU lock's SHA-256, device and precision, and
  the normalization fingerprint.
- `lab candidate check --name … --model-dir DIR` finds absent or mismatched
  files before anything loads (exit 2).
- `lab candidate dry-run --refs R --out F` writes a weights-free result file
  for wiring checks.
- `lab from-eval EVAL --label L --refs-out R --out F [--group speaker]` turns a
  stored evaluation into lab files. The stored v1 outputs reproduce the v1
  comparison exactly. `--group speaker` makes each speaker one group, because
  one speaker's clips are not independent.
- `lab batch --manifest-a/--manifest-b` invalidates a result whose recorded
  `candidate_id` no longer matches the manifest. The batch also refuses to rank
  runs with different seeds. Quality and resources are reported side by side,
  never folded into one score.
- `lab batch` JSON adds `ranking.standing` (`ranked`, `observation` below 30
  groups, `not_ranked`) and `ranking.min_groups`. The text adds a `standing:`
  line under `samples:`. Existing fields, the `ranking:` line and the exit
  codes are unchanged.

**Candidate review (offline, never promotes).**

```sh
python3 -B -m flh_speaking lab candidate-review --baseline BASE_EVAL.json --candidate CAND_EVAL.json \
    [--thresholds T.json] [--data-manifest DATA/manifest.jsonl] [--experiment experiment-result.json] [--json OUT] [--text OUT]
python3 -B -m flh_speaking lab candidate-review-walkthrough --review REVIEW.json [--data-manifest DATA/manifest.jsonl] [--text OUT]
python3 -B -m flh_speaking lab candidate-review-demo --out NEW_DIR --check     # the three synthetic scenarios and one walkthrough
```

It reads two saved `evaluate` outputs and loads no model, audio or network.
The paired comparison is `lab.batch`, with speakers as groups. The review
(`flh_speaking_candidate_review_v1`, text rendered from the JSON) reports:
- both model identities: the pinned name and candidate ID, or `unpinned`;
- the SHA-256 of every input, the reference set and the sample order;
- paired sample and speaker counts, with missing IDs;
- WER, CER, real-time factor, peak RSS, compute and load time side by side,
  each `measured` or `not_measured` with a reason;
- input checks, the speaker-bootstrap interval and a leave-one-speaker-out range.

`candidate-review-walkthrough` reads a saved review (and optionally the data
manifest) and explains, step by step, whether its speakers are enough. It covers:
- clips against speakers;
- each speaker's WER difference;
- how stable the interval is, with the bootstrap rerun on five seeds;
- the speakers each split can offer;
- what the other checks would say;
- the decision.

It changes no outcome.

Checks use `flh_speaking_candidate_thresholds_v1`. A file may set any subset;
every limit is inclusive.

| Limit | Default |
|---|---|
| `support.min_paired_samples` | 30 |
| `support.min_groups` | 30 |
| `quality.max_wer_difference` (candidate − baseline) | −0.02 |
| `quality.max_interval_upper` | 0.0 |
| `quality.max_cer_difference` | 0.0 |
| `quality.max_group_wer_increase` | 0.05 |
| `resources.max_real_time_factor` | 0.5 |
| `resources.max_peak_rss_mb` | 2048 |

Outcome, first applicable wins, each with concrete reasons:

| Outcome | Exit | When |
|---|---|---|
| `mismatched_inputs` | 5 | split, normalization, IDs or references differ; a stored summary disagrees with its texts; both sides are the same model; or the experiment or data manifest does not match |
| `insufficient_support` | 4 | too few paired samples or speakers; the other checks are shown but decide nothing |
| `thresholds_not_met` | 3 | a quality or resource check failed or was not measured |
| `ready_for_owner_review` | 0 | every check passes |

None of these promotes anything. The command has no option that changes a
serving setting. The shipped fixtures (`fixtures/lab/candidate_review/`) have
invented texts and timing, and their labels say so. They test the review's
mechanics, not any model.

The lab changes no serving setting. The default stays what `RUNBOOK.md`
deploys: pretrained whisper-small with `SPEAKING_TRANSCRIPTION_PROVIDER=local`.

Minimum evidence before promoting a candidate:
1. Its manifest verifies (`candidate check`: no problem). Its `candidate_id` is
   the one in every result file.
2. Baseline and candidate cover exactly the same samples (no `missing`), in the
   same order, with the same seed.
3. There are at least 30 groups overall. A slice is ranked only with at least 5
   groups; smaller slices are observations.
4. `flh_speaking_acceptance_v1` (`accept`) passes A1–A7 on the frozen holdout.
5. Resources are within `RUNBOOK.md` §3, and the regressions list is empty or explained.
6. Reviewer exclusions and abstentions are reported with their counts.

**What the shipped fixtures can and cannot measure**

| Fixture | Measures | Does not measure |
|---|---|---|
| `synthetic_fr_case.json` (hand-written transcripts) | the lab's alignment, edit classes (accent-only, deletion), the text/JSON contract, the evidence states | any model's accuracy: no model produced these texts |
| `three_rows/` (hand-written, hand-computed) | aggregation: WER/CER sums, views, paired counts, ranking rules | variability: three rows have no uncertainty to speak of |
| `lab variants` on the synthetic tone | variant mechanics: tags, group IDs, clipping refusal, SNR and seeds, unchanged source | recognition under noise: the tone is not speech. For that, use the public speech sets with `robustness --set noise` (v2 memo §5) |
| none of them | — | learner speech, pronunciation, speaker fairness: there is no speaker metadata and no learner data |

**Bounded CPU experiment (`scripts/lab_experiment.py`).** whisper-base vs
whisper-small on a slice of the frozen MLS-fr test split: the first 5 clips per
speaker, 8 speakers, 40 clips. The slice runs clean and with seeded 20 dB white
noise:

```sh
X=$W/v3/exp091    # outside the repository
python3 -I -B scripts/lab_experiment.py prepare --data $W/data-v1 --work $X
python3 -I -B scripts/lab_experiment.py run --work $X --sources $W/sources --image flh-speaking:cpu --lock $W/cpu.lock
python3 -I -B scripts/lab_experiment.py report --work $X     # -> $X/experiment-result.json, $X/report/*.txt
```

How it runs:
- **Bounds:** four `evaluate` calls, each with `--network none`, `--cpus 2`, 2 GB, batch 1 and 2 threads.
- **Code:** this tree's `flh_speaking` is mounted read-only.
- **Lock:** the image's lock must equal this tree's.

What the result holds:
- the experiment identity, a hash over every defining input;
- per comparison: the sample-order hash, both WERs, B − A with its speaker-bootstrap interval, and paired counts;
- tradeoffs: RTF, peak RSS and load time;
- output sizes and SHA-256;
- the limits of the evidence.

Eight speakers are below the 30-group minimum, so every comparison is an
observation. A report over two evaluations whose sample sets differ is refused.

**Evaluation-data intake** (no audio read, nothing fetched):

```sh
python3 -B -m flh_speaking lab intake --data-manifest DATA/manifest.jsonl [--min-groups 30]   # speakers per split, how many more are needed
python3 -B -m flh_speaking lab intake --proposal P.json            # licence, revision, attribution, speaker IDs and provenance, no audio in Git,
                                                                   # no personal metadata, condition labels, speaker-disjoint splits
python3 -B -m flh_speaking lab intake --source a=A.jsonl --source b=B.jsonl   # speaker-ID collisions kept apart; duplicate audio refused
python3 -B -m flh_speaking lab intake --pairs PAIRS.jsonl          # noise conditions compared only on clips present in every condition
```

On the pinned v1 manifest: test 8 speakers (22 more needed), dev 4 (26 more), dev and test
pooled 12 (18 more); the 289 FLEURS clips carry no speaker ID. Below 30 speakers a comparison
stays an observation whatever these checks say. Fixtures: `fixtures/lab/intake/` (synthetic).

Further intake flags: `--require-speakers` refuses a speaker-group claim over rows without a
speaker ID; `--balance` reports rows, speakers, gender, hours and missing labels per split;
`--overlap train=M[:split] --overlap name=M2[:split] …` counts shared speakers, normalised texts
and audio between a training set and each evaluation set.

**Training-data intake (R4)**, with no audio read and nothing fetched:

```sh
python3 -B -m flh_speaking lab training-intake --manifest M.json [--json OUT]   # exit 0 eligible, 1 refused, 2 not a manifest
```

A `flh_speaking_training_intake_v1` manifest declares its sources and rows. Each source gives
its kind (public dataset, or synthetic with generator terms and voice consent), pinned revision,
licence, attribution, speaker provenance and consent, and locales. Each row gives `id`,
`source_id`, `split`, `speaker`, `locale`, `variety`, `seconds` and `pcm_sha256`.

The report:
- licence and consent per source;
- clips, distinct speaker groups (`source:speaker`), hours, locales and varieties per split;
- speaker, text and audio leakage between train and evaluation, where rows without a speaker ID
  are counted and never assumed disjoint;
- one actionable refusal per fault: repeated IDs or audio, missing or undeclared metadata.

It never includes a transcript. Fixtures: `fixtures/intake_r4/` (synthetic).

**R4 training pilot (prepared, owner-run).**
- `aws/r4-pilot.prereg.json`: candidate, baseline, held-out split and thresholds, frozen before
  any run.
- `aws/pilot_r4.py render VALUES OUT_DIR`: the bounded job, checked against the pre-registration.
- `aws/pilot_r4.py teardown-check aws/r4-teardown-plan.json`: the order of evidence copy and
  deletions.

Owner commands and cost: `deploy/aws/model-runtime/SPEAKING-PILOT-R4.md`.

**Candidate bundles and identities.**

```sh
python3 -I -B scripts/export_candidate.py --checkpoint CKPT --out NEW_DIR --name NAME [--deployment-manifest M.json]
python3 -I -B scripts/export_candidate.py --verify NEW_DIR      # every file against its seal and the manifest
python3 -I -B scripts/identity_diff.py --a BASE_MANIFEST.json --b CAND_MANIFEST.json [--prompts-a DIR --prompts-b DIR]
```

A bundle holds the inference files only (no trainer state), `candidate_manifest.json`
(`flh_speaking_candidate_bundle_v1`, status `candidate`, `promotion.performed: false`), a model
card and `SHA256SUMS`. `identity_diff.py` says whether two deployments differ by weights,
decoding policy, audio convention, code, runtime or FLH's feedback prompts.

**Strict suite on the packaged code.** Rebuild the image, copy its own package out, and
mount only tests and data:

```sh
IMG=flh-speaking:cpu; docker build --build-arg TORCH_INDEX=cpu -t $IMG .
P=$(mktemp -d); C=$(docker create $IMG); docker cp $C:/opt/program/flh_speaking $P/flh_speaking; docker rm $C
M="-v $P/flh_speaking:/t/tools/speaking/flh_speaking:ro"; for d in tests scripts fixtures configs aws CONTRACT.md Dockerfile README.md RUNBOOK.md requirements.txt requirements-cpu.lock requirements-gpu.lock; do M="$M -v $PWD/$d:/t/tools/speaking/$d:ro"; done
docker run --rm --oom-score-adj 1000 --network none --memory 1g --cpus 2 --user $(id -u):$(id -g) -e HOME=/tmp -e FLH_SPEAKING_TOKENIZER_DIR=/tok \
    $M -v $PWD/../../docs/validation/SPEAKING-MODEL-V1:/t/docs/validation/SPEAKING-MODEL-V1:ro -v TOKENIZER_DIR:/tok:ro \
    -w /t/tools/speaking --entrypoint python3 $IMG -B -X dev scripts/run_tests.py --require-deps --expect-offline
```

**Reproduce with packaged code.** After rebuilding the image from this tree:

```sh
python3 -I -B scripts/lab_experiment.py reproduce --work $X --sources $W/sources --image flh-speaking:cpu --lock $W/cpu.lock
```

- It mounts nothing from this tree. It first compares every file of the image's
  `/opt/program/flh_speaking` with this tree's and refuses (exit 1) on any
  difference, naming the files.
- It re-evaluates the smallest slice (the speaker with the least audio) with
  both models and compares every text and status with the first run.
- It rebuilds the paired comparison and checks it equals the one from the first
  run's outputs for the same IDs (measured resources excluded).
- It renders the candidate review inside the image and checks it is byte-identical
  to this tree's rendering. Results: `$X/reproduce.json` and `$X/reproduce/`.

**Shared-report hygiene.** `lab privacy-check FILE…` lists machine-local home
paths, claude.ai links and UUID-shaped IDs, such as take or request keys
(exit 1 on any). Run it on anything that leaves the machine.

## Runtime diagnostics and troubleshooting

This runs the service with a pinned local model, CPU-bound, in a 2-CPU, 2 GB
container on 127.0.0.1:

```sh
python3 -I -B tools/speaking/scripts/runtime_diagnostics.py --sources $W/sources --work DIR \
    --image flh-speaking:cpu [--model whisper-base] [--flh-bin BIN]
```

It writes `DIR/runtime-diagnostics.json`, with no machine path. The states
below were reproduced by that script with whisper-base:

| What you see | State | Cause and action |
|---|---|---|
| `/readyz` refuses, then 503 `loading` → `warming` → 200 `ready` | startup (about 5 s: load about 1.8 s, warm-up about 0.7 s) | wait for 200; FLH answers `provider_unavailable` until then |
| HTTP 413 `request_too_large` | refused before the body is read | the take is over 8 MiB (with the multipart, the request limit is 8,454,144 bytes); the service stays ready |
| HTTP 422 `audio_too_long` / `undecodable_audio` | refused while decoding | over 120 s, or not audio; FLH stores `invalid_output` |
| HTTP 400 `unknown_model` | wrong `SPEAKING_TRANSCRIPTION_MODEL` | set it to `GET /manifest`'s `deployment_id` and restart FLH |
| HTTP 429 `busy` | one inference running and the waiting slots full | wait; FLH stores `provider_unavailable`, and the next click is sent |
| HTTP 504 `timeout` | the deadline passed, counted from arrival | a long take on a loaded CPU; the service stays ready for the next request |
| FLH 502 `provider_unavailable`, `failed` | the service is not running (connection refused) | start it (`RUNBOOK.md` §4); no OpenAI call is made, even when OpenAI feedback is configured (verified with a sentinel: 0 requests) |
| container exits within a second | startup failed | the script reports the exit code, whether it was OOM-killed and the log tail; check the model path and the memory limit |
| FLH 503 "speaking transcription is not enabled (SPEAKING_TRANSCRIPTION_PROVIDER); type the transcript instead" | rolled back to `SPEAKING_TRANSCRIPTION_PROVIDER=disabled` (the previous setting) | expected after a rollback: the take and the stored transcriptions stay; typing still works. Verified: the earlier failed transcription was still listed, and the sentinel got 0 requests |

The script also checks every 200 answer with the synthetic client
(`flh_speaking/client.py`): `text` and `flh.deployment_id` are required, as
FLH's Go client reads them, and every other `flh` field is optional but typed.
It checks every error body for `{"error": {"type", "message"}}`, and checks
`/healthz` and `/readyz` on loopback. Go's
`TestLocalTranscriberAcceptsAMinimalAnswerFromAnOlderService` pins the
minimal answer on the FLH side.

Measured with whisper-base, 2 threads, on a 5 s synthetic tone:
- RTF about 0.13;
- first and warm inference about 0.66 s (warm-up happens at startup);
- peak 453 MiB idle, 682 MiB with two queued 60 s requests.

## Tests

`scripts/run_tests.py` runs the same discovery as `python3 -B -m unittest
discover -s tests -t tests`, from any working directory, in two modes.

**Offline (default).** Standard library only, any Python ≥ 3.12, under a second.
The 28 tests that need NumPy and PyAV (23) or torch and transformers plus the
tokenizer fixture (5) skip with that reason, and the run exits 0. No test skips
for a platform reason.

```sh
cd tools/speaking && python3 -B scripts/run_tests.py            # or: python3 -B -m unittest discover -s tests -t tests
```

**Full (`--require-deps`).** Every test must run.
- A missing module (`numpy`, `av`, `torch`, `transformers`) fails with exit 2
  before any test runs.
- So does a fixture that does not match its pins. Each of the 10 pinned
  whisper-tiny config and tokenizer files is checked by size and hash, so a
  missing, edited or truncated cached file is named. The fixture's identity is
  `fixture.contract_sha256` in the JSON (`55f3d55e…`).
- `flh_speaking check` verifies the whole model, weights included, so it
  reports a weights-free fixture as incomplete; use the runner's check instead.
- Any skip fails with exit 1.
- `--json FILE` records the totals (failures, errors and skips apart), skips
  by reason, tests per class, module versions, the fixture contract, test time
  and peak memory. It is written on every exit path, and the exit status is the
  suite's.
- The exact CI contract (invocation, Python, CPU and memory, fixture hash) is in
  `docs/validation/SPEAKING-TEST-ENTRY.md` § Release contract.

The fixture is the pinned whisper-tiny config and tokenizer files: about
4.3 MB, fetched once and hash-verified. The weights are never read; the tests
build a tiny random model.

```sh
W=$HOME/flh-speaking-work                                           # outside the repository
python3 -B -m flh_speaking fetch --dest $W/fixture --what whisper-tiny --no-weights       # once, network
docker build --build-arg TORCH_INDEX=cpu -t flh-speaking:cpu .      # once; from requirements-cpu.lock
docker run --rm --network none --memory 1g --cpus 2 --user $(id -u):$(id -g) -e HOME=/tmp -e PYTHONPATH=/src \
    -e FLH_SPEAKING_TOKENIZER_DIR=/tok -v $W/fixture/openai/whisper-tiny/169d4a4341b33bc18d8881c4b69c2e104e1cc0af:/tok:ro \
    -v $PWD:/src:ro -w /src --entrypoint python3 flh-speaking:cpu -B scripts/run_tests.py --require-deps
```

Measured on the NAS host (2 CPUs, 1 GB container, no network). These numbers
are what the release lane needs for CI:

| Step | Time | Resources |
|---|---|---|
| Fixture fetch (`--no-weights`) | about 2.4 s | 4.3 MB download (network) |
| Image build, `--no-cache` | about 165 s | about 250 MB of wheels; image 1.41 GB |
| Full test run | 12–15 s of tests, about 15 s wall | peak 530 MiB; no network, GPU or credentials |

**Without Docker,** the same pins work in a Python 3.12 virtual environment.
The lock's torch and NumPy wheels are built for CPython 3.12. Verified in a bare
`python:3.12-slim` container standing in for a runner: install 124 s,
`pip check` clean, 47 tests, 0 skipped. This host itself has only Python 3.14.

```sh
python3.12 -m venv .venv && .venv/bin/pip install --require-hashes --no-deps \
    --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple -r requirements-cpu.lock
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 FLH_SPEAKING_TOKENIZER_DIR=<fixture dir> .venv/bin/python -B scripts/run_tests.py --require-deps
```

Code CI and an inference smoke check different things:
- **Code CI** runs both modes above. It needs no model weights, no audio
  dataset, no GPU and no credentials.
- **The inference smoke** checks the deployed service. It needs the pinned
  weights (whisper-base 290 MB or whisper-small 967 MB), the frozen MLS test
  data and about 2 GB of memory, and takes about 10 minutes. Run it before a
  deployment, not on every commit:
  - `scripts/verify_local_provider.py` against a disposable FLH;
  - `RUNBOOK.md` §5 for a check against the deployed service.

## Retention

- The service keeps nothing: audio is decoded in memory, released after the
  response, and never written, cached or logged; transcripts are not logged.
- FLH stores audio **metadata** only (type, size, SHA-256, duration) and the
  transcripts the learner confirms (Speaking v1, migration 018).
- Training data here is public (MLS, FLEURS; CC-BY-4.0) and lives outside the
  repository. Learner recordings are never used for training: FLH does not
  store them, and collecting them would need an explicit owner decision with
  consent and a retention limit (see the validation memo).
