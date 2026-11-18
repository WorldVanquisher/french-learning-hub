# Speaking model v1: local French transcription (research, data, baseline, training, service)

> **Offline and local only.** Public data (MLS French, FLEURS; CC-BY-4.0;
> African Accented French SLR57; Apache-2.0) and pinned public weights (Whisper).
> No learner recording, no provider call, no AWS command, no paid run. Every
> model run was inside a container with no network, capped at 1.5–2 GB of
> memory and 4 CPUs, beside the running NAS services.
> Evidence: `docs/validation/SPEAKING-MODEL-V1/` (JSON) and the handoff
> `~/flh-handoff/speaking-extraction-20261117T042813Z/`.

## Summary

| | Result |
|---|---|
| Task | Local French **transcription** of a learner's recorded take: a draft that the learner confirms before FLH's existing feedback. Pronunciation and fluency scoring are deferred: no cleared labels, and the product refuses them |
| Model | Whisper, forced French, greedy, CPU float32; policy `flh_speaking_transcribe_v1` with abstention (`no_speech`, `not_french`). **Serve `whisper-small` @973afd24 where about 1.8 GB can be reserved, otherwise `whisper-base` @e37978b9** (the base model is the one fine-tuned locally) |
| Data | MLS French subset (24 / 4 / 8 speakers, speaker- and book-disjoint, manifest `4b1c067e…`, reproduced byte for byte), FLEURS fr_fr dev (out of domain), SLR57 African-accented French (12 speakers), FLEURS English/Mandarin (non-French probe). All public; no learner data |
| Baseline | WER **27.1%** on MLS test (95% CI 25.4–28.9), **27.5%** on FLEURS, 35.2% on accented French; whisper-tiny 38.6% / 46.4%. **whisper-small: 14.9% / 13.3% / 16.6%** (about half the errors; 17 s for a 120 s take; 1.3 GB). Most errors are homophones (ces/ses, a/à, leur/leurs) that speech cannot decide |
| Robustness | silence, hum, tones, clicks, noise and 20 English/Mandarin sentences abstain; invalid input is refused with stable codes; Opus/AAC/MP3/stereo re-encodings change nothing. **Weak spots:** noise (WER 43% at 20 dB SNR, 94% at 0 dB); `not_french` falsely abstains on 4.7% of accented French |
| Training | resumable fine-tuning with pinned inputs. Real whisper-tiny smoke; a SIGKILL-interrupted run resumes to **byte-identical** weights. Pilot: whisper-base encoder-only, 180 steps on CPU |
| Verdict | **KEEP_BASELINE** (`flh_speaking_acceptance_v1`, written before training): −0.48 pts on MLS test (not significant), +0.98 on FLEURS, and punctuation fell from 100% to 6.6% of outputs, because MLS's unpunctuated text leaked through the encoder although the decoder was frozen |
| Service | loopback HTTP service answering FLH's existing client unchanged. whisper-base: ready after 5.2 s, 120 s of audio in 5.6 s, 0.64 GB peak. whisper-small: ready after 7.3 s, 120 s in 17.3 s, 1.30 GB peak. Keeps no audio or text. Verified end to end through FLH's API (whisper-base), including idempotent replay, the silent take and the service-down path |
| AWS | template, IAM policy, bounded renderer, cost (≤ $1.41 per pilot) and exact commands prepared. **Not launched**: no budget is established and agents may not run AWS commands |
| Owner decisions | D1 opt in to the local service (whisper-small if about 1.8 GB can be reserved); D2 apply the Go patch (provenance, separate URL and timeout, deadline); D3 make `not_french` a warning; D5 consented learner evaluation set; D6 budget for the next (punctuated, noise-augmented, GPU) experiment (§12) |

## 1. Inventory (item 1)

| Area | What exists | Speaking/audio relevance |
|---|---|---|
| `internal/domain/speaking.go` | takes (audio **metadata** only), transcripts, feedback; accepted audio webm, mp4/m4a, mpeg/mp3, wav; ≤ 8 MiB, ≤ 120 s; transcript ≤ 2,000 runes | the limits the model must meet |
| `internal/speaking/transcribe.go`, `openai.go`, `factory.go` | OpenAI-style multipart transcription client (`file`, `model`, `response_format=json`; no language, no prompt); `send()` maps non-200 to "unavailable" | the integration point: a local service can answer it unchanged |
| `internal/config/speaking.go` | `SPEAKING_TRANSCRIPTION_PROVIDER` (`disabled`/`openai`), reuses `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_TIMEOUT` (default **8 s**) | shared settings, so local transcription cannot run beside OpenAI feedback today |
| `internal/application/speaking_service.go`, `storage/sqlite/speaking_repository.go`, migration 018 | attempt-first request rows, Idempotency-Key replay, failure codes `invalid_output` / `unavailable` / `timeout` | duplicate and retry semantics already exist at the FLH level |
| `web/src/pages` (Speaking) | MediaRecorder in the browser; audio leaves only on an explicit Transcribe click | the frontend contract stays unchanged |
| `internal/listening` | YouTube links and learner transcripts; **no ASR by rule** | not touched |
| `tools/embedding/e5/` | local model service pattern: pinned revision, manifest-derived `deployment_id`, loopback only | reused for the Speaking service design |
| `tools/extraction/`, `deploy/aws/sagemaker-extractor/` | SFT image (torch 2.15.0, transformers 5.21.1), SageMaker templates, renderer with bounds, price extract | reused versions, patterns and prices |
| Speech data | **none**: FLH stores no audio by design; confirmed transcripts are private learning records | public data is needed (§4) |

No speech model, audio dataset, pronunciation or fluency code existed before this batch.

## 2. Task choice (items 2, 3, 6, 7)

| Candidate task | Product fit | Labels available | Measurable | Verdict |
|---|---|---|---|---|
| **Transcription (ASR)** | replaces the only paid call in the Speaking flow with a private local one; the learner already confirms the draft before feedback | plenty of public French speech with transcripts (MLS, FLEURS, Common Voice) | WER/CER against references; abstention on silence and noise | **chosen** |
| Pronunciation assessment | contradicts the current contract: feedback refuses pronunciation comments and scores | needs phone-level L2-French annotations; none cleared | GOP-style scores need native references and human calibration | deferred |
| Fluency feedback | speech rate and pauses are computable without training, but "fluent" is a human judgment and the product refuses scores | no labelled learner fluency data | only raw measurements | deferred (no training needed for measurements) |

**What the model can measure:** the words it recognizes (a draft transcript);
per-window confidence (mean token log-probability); P(no speech); language
identification probabilities; duration and sound duration; a repetition
signal.

**What needs human judgment:**
- whether the draft is what the learner actually said;
- pronunciation, fluency, grammar and accent;
- any score.

Whisper's language model tends to regularize speech, so a learner's mistake
can disappear from the draft. That is why the confirmation step stays.

**Choice (item 6): Whisper, initially `whisper-base` @e37978b9, French forced, served on CPU.**

- **Fits the machine.** About 1 GB resident and real-time factor ≈ 0.05–0.12 on four shared cores: a 120 s take transcribes in seconds. It is also the largest Whisper that can be *fine-tuned* locally within about 1.5 GB (encoder-only).
- **Accuracy.** 27.1% WER on MLS test and 27.5% on FLEURS, against 38.6% / 46.4% for tiny. whisper-small, measured last (its first download was truncated and refused), is far better: 14.9% / 13.3% / 16.6% (MLS / FLEURS / accented), −12.2 points against base on MLS test (95% CI −12.8 to −11.6, 8 of 8 speakers). It is also more robust to noise and abstains wrongly on accented French less often (1.6% vs 4.7%), but it needs about 1.3 GB (service) to 1.7 GB (batch) and runs at about 17 s for a 120 s take.
- **Revised recommendation (D1):** serve **whisper-small** when the host can reserve about 1.8 GB for it, and whisper-base otherwise. Same code and contract; only the `deployment_id` differs. whisper-base remains the model that can be fine-tuned locally.
- **Integration and licence.** Multilingual Whisper has French, punctuation and casing, a no-speech probability and language identification, which this design uses for abstention. It is permissively licensed and already supported by the pinned `transformers`.
- **Rejected alternatives:**
  - wav2vec2/XLS-R CTC: no punctuation or case, though more literal.
  - Parakeet/Canary, Voxtral, large-v3-turbo, distil-French: GPU-sized for this host.
  - Pronunciation and fluency models: no cleared labels, and against the product contract.


## 3. Models considered (items 4, 5)

Facts from the Hugging Face API and model cards, read 2026-11-17 (`research/`
in the handoff):

| Model | Params | Licence (card) | French | Runtime needs | Notes |
|---|---:|---|---|---|---|
| `openai/whisper-tiny` @169d4a43 | 37.8 M | Apache-2.0 on the HF card (OpenAI's repository: MIT) | yes (99 languages) | CPU fine | measured |
| `openai/whisper-base` @e37978b9 | 72.6 M | same | yes | CPU fine | measured; trained |
| `openai/whisper-small` @973afd24 | 241.7 M | same | yes | CPU usable (RTF 0.11–0.25), 1.3–1.7 GB | measured; recommended for serving |
| `openai/whisper-large-v3-turbo` | 808.9 M | MIT | yes | GPU for practical latency | not run (CPU too slow beside the NAS) |
| `bofenghuang/whisper-large-v3-french-distil-dec16` | 1,124 M | MIT | French only | GPU | not run |
| `jonatasgrosman/wav2vec2-large-xlsr-53-french` | ≈ 315 M | Apache-2.0 | French only | CPU possible | CTC: no punctuation or case; more literal (less LM smoothing) |
| `nvidia/parakeet-tdt-0.6b-v3` | 627 M | CC-BY-4.0 | yes (25 languages) | GPU recommended | TDT transducer |
| `nvidia/canary-1b-flash` | ≈ 1 B | CC-BY-4.0 | en/de/es/fr | GPU | NeMo |
| `mistralai/Voxtral-Mini-3B-2507` | 4.7 B | Apache-2.0 | yes (8 languages) | GPU (≈ 10 GB) | audio LLM |

Hardware here: Intel i7-1165G7 (4 cores / 8 threads, AVX-512 VNNI, no GPU),
15 GiB RAM with **about 1–2.5 GB available** beside the NAS services. The owner's
RTX 4070 laptop (FLH-054) and AWS GPUs are owner-operated and were not used.

Papers: Radford et al. 2022, *Robust Speech Recognition via Large-Scale Weak
Supervision* (arXiv:2212.04356); Pratap et al. 2020, *MLS* (arXiv:2012.03411);
Conneau et al. 2022, *FLEURS* (arXiv:2205.12446); Babu et al. 2021, *XLS-R*
(arXiv:2111.09296).

## 4. Data (items 9–16)

**Available data (items 9, 10):**
- FLH keeps no audio (Speaking v1 stores metadata only). Confirmed transcripts are private learning records and were not used.
- Public sources, cleared for local use and for upload to the owner's own AWS account (no learner data):

| Source | Revision / pin | Licence | Use |
|---|---|---|---|
| Multilingual LibriSpeech, French | `facebook/multilingual_librispeech` @2e83e618 (36 speaker/book archives + metadata, each pinned by size and SHA-256 or git blob) | CC-BY-4.0 | train / dev / test |
| FLEURS fr_fr dev | `google/fleurs` @70bb2e84 | CC-BY-4.0 | out-of-domain test (`ood`): other speakers, Wikipedia sentences, cased and punctuated references with digits |
| FLEURS en_us and cmn_hans_cn dev (first 10 each) | same revision | CC-BY-4.0 | `not_french` probe (English and Mandarin speech) |
| African Accented French (OpenSLR SLR57) | tarball 1,869,299,860 bytes, SHA-256 `3d9edcd8…` **trust-on-first-use** (OpenSLR publishes no checksum; ETag and Last-Modified recorded) | Apache-2.0 | accent check (`accent`): 12 speakers from Cameroon, Chad, Congo, Gabon |

**Pinning and download (item 12):**
- `flh_speaking/pins.py` pins the exact files. Download with `python -m flh_speaking fetch --dest DIR --what whisper-base mls fleurs slr57`.
- Every file is re-verified before use, and nothing is gated or needs credentials.
- Attribution is in `dataset_manifest.json`. Audio stays out of Git.

**Decoding (item 13):**
- One function, `audio.decode` (PyAV/FFmpeg, in memory), produces 16 kHz mono float32 for preparation, training, evaluation and the service.
- Every MLS and FLEURS source file was checked: rate 16,000 Hz, 1 channel (FLAC, float WAV). Resampling and down-mixing are exercised by the probes (44.1 kHz stereo, 48 kHz Opus).
- FFmpeg's mono down-mix weights each channel by 1/√2 (identical channels gain 3 dB); a test pins this.

**Splits (item 14).** Rule `flh_mls_fr_subset_v1` (`mls.py`), computed from pinned metadata only:

| Split | Utterances | Hours | Speakers | Notes |
|---|---:|---:|---:|---|
| train | 1,440 | 6.07 | 24 (12 F, 12 M) | 60 per speaker; no book that occurs anywhere in MLS dev or test |
| dev | 100 | 0.41 | 4 | training monitoring only |
| test | 240 | 1.01 | 8 (4 F, 4 M) | frozen; each speaker on a different book |
| ood | 289 | 0.80 | n/a (137 sentence groups) | FLEURS publishes no speaker ids |
| accent | 515 | 0.31 | 12 | SLR57 test, CA16 role-play prompts; verbatim transcripts |

**Leakage checks (item 15)** (`dataset_manifest.json` → `checks`): every check that can fail does fail loudly.

| Check | Result |
|---|---|
| speaker overlap between any two of train, dev, test | 0 |
| book overlap between any two of train, dev, test | 0 |
| LibriVox source-recording overlap | 0 |
| duplicate audio (PCM SHA-256) | 0 |
| identical normalized transcript across splits | 0 |
| dev, test or ood utterances sharing any 8-gram with a training reference | 0 / 0 / 0 |
| ood transcripts repeated within ood | 152 (FLEURS reads each sentence with up to 3 speakers; grouped by sentence for uncertainty) |

**Sealed manifest and tiny fixture (item 16):**
- `manifest_jsonl_sha256` is `4b1c067e76ab1e097af4c08ae5e08aebcf32e169bcf6ceb0e14b1bb4221dc9eb`. The 2,069 rows are in the handoff; the summary is `SPEAKING-MODEL-V1/dataset_manifest.json`.
- A second, independent `prepare` reproduced all 2,071 files byte-identical (2,069 WAV files and both manifests).
- The tiny fixture is 16 training utterances (2 from each of 8 speakers) and 8 dev utterances. `configs/smoke-tiny.json` trains on it with the real whisper-tiny (§6).

## 5. Baseline (items 17–24)

**Metrics (item 18):**
- **WER** and **CER** after `flh_fr_asr_norm_v1`: NFKC, lower case, apostrophe and quote variants, œ/æ, punctuation and hyphens removed; accents and elision kept; numbers **not** spelled out, so digit-bearing utterances are also reported separately.
- **Uncertainty** from a cluster bootstrap over speakers (sentence groups for FLEURS; 2,000 resamples, seed 20261117), because one speaker's utterances are not independent.
- **Served WER** scores the transcript after the abstention rules; an abstention counts as all deletions.
- **Abstention rates**, **output style** (share of outputs with punctuation and with an upper-case letter), real-time factor, peak memory and load time.

**Pretrained inference on the frozen splits (items 17, 19, 20).** Greedy French decoding, policy `flh_speaking_transcribe_v1`, CPU, 4 threads, offline container (2 GB for tiny; 1.5 GB for base; 1.8 GB for small):

| Model | Split | WER | 95% CI | CER | Abstained | RTF | Peak RSS | Load |
|---|---|---:|---|---:|---:|---:|---:|---:|
| whisper-tiny | test (MLS) | 38.6% | 36.8–40.7 | 17.2% | 0 / 240 | 0.033 | 856 MB | 4–11 s |
| whisper-tiny | ood (FLEURS) | 46.4% | 43.0–50.0 | 21.7% | 0 / 289 | 0.049 | 870 MB | |
| whisper-tiny | dev | 32.2% | 30.3–35.9 | 12.9% | 0 / 100 | 0.026 | 849 MB | |
| **whisper-base** | test (MLS) | **27.1%** | 25.4–28.9 | 11.5% | 0 / 240 | 0.115 | 948 MB | 4.5–7.8 s |
| whisper-base | ood (FLEURS) | 27.5% | 25.0–30.2 | 12.4% | 0 / 289 | 0.084 | 968 MB | |
| whisper-base | dev | 22.0% | 20.5–23.8 | 8.5% | 0 / 100 | 0.054 | 1,222 MB (batch 8) | |
| whisper-base | accent (SLR57) | 35.2% (served 37.7%) | 29.9–40.0 | 18.3% | 24 / 515 `not_french` | | | |
| **whisper-small** | test (MLS) | **14.9%** | 13.2–16.5 | 6.2% | 0 / 240 | 0.175 | 1,703 MB | 3.4 s |
| whisper-small | ood (FLEURS) | **13.3%** | 11.3–15.3 | 6.1% | 0 / 289 | 0.225 | | |
| whisper-small | accent (SLR57) | **16.6%** (served 17.8%) | 13.6–19.4 | 9.2% | 8 / 515 `not_french` | 0.76 (2 s clips padded to 30 s) | 1,741 MB | |

RTF is compute time over audio time with batches of 4–8 clips; the CPU was shared with the NAS services and other sessions, so latencies are upper-side estimates (§9 has the per-request service numbers). Base against tiny on test, paired by speaker: −11.5 points (95% CI −13.4 to −9.4), better for all 8 speakers (sign test p = 0.008).

**Error analysis (whisper-base, test):**
- The most frequent substitutions are French **homophones**: ces→ses (14), ils→il (9), à→a (9), aux→au (9), l'→la/les, où→ou (6), conte→compte (5), elles→elle (5), prit→pris (4), leurs→leur (4), put→pu (3).
- Speech cannot decide these, and they are the agreement and spelling points learners are taught. A transcript is therefore never evidence of what the learner *knows* about them; the confirmation step stays.
- Digits ("cinq"→"5") are a normalization artifact: WER without digit-bearing utterances is reported per split.
- WER does not differ by duration bucket or by gender on MLS (27.4% vs 27.0%; F 27.0% vs M 27.2%).

**Probes (item 21)** (`probes.json`, whisper-base; the abstention rules are part of the policy):

| Probe | Result |
|---|---|
| silence 1 s and 10 s, hiss −50 dBFS, 440 Hz tone, 50 Hz hum, clicks | abstained (`no_speech`) |
| white noise −20 and −10 dBFS | abstained, labelled `not_french` (language identification picked "nn"); the outcome is right, the label is imprecise |
| empty, random bytes, truncated WAV, FLAC (not accepted by the service), 125 s | refused before the model: `empty_audio`, `unsupported_audio`, `undecodable_audio`, `unsupported_audio`, `audio_too_long` |
| clean speech; clipped ×8; −30 dB quiet | WER 21.3%; 21.3%; 19.1% |
| speech with white noise at 20 / 10 / 5 / 0 dB SNR | WER 42.6% / 57.4% / 78.7% / 93.6%. **Noise robustness is poor**, and `low_confidence` fires only at 0 dB |
| 20 s of silence on each side (long-form windows) | 23.4%, no text added in silent windows |
| 100 s+ concatenation (windows cut at quiet frames) | 21.8% |
| re-encoded webm/Opus 48 kHz, mp4/AAC, mp3 44.1 kHz, WAV 44.1 kHz stereo | 21.3% each, the same as the original: preprocessing and inference share one convention (item 31) |
| 0.5 s / 1.5 s fragments | recorded only (abstained / a few low-confidence words) |
| 10 English + 10 Mandarin FLEURS sentences (`FLH_SPEAKING_NON_FRENCH`) | all 20 abstained as `not_french` (P(fr) ≤ 0.0009); forced French never turned them into a fake French transcript |

**Accents and learner speech (item 22):**
- Accented French was checked on SLR57 (§8).
- **Learner (L2) speech was not checked**: no cleared L2-French recording exists in FLH or in an openly licensed corpus found here. This needs owner-approved collection (§12).

**Structured errors and bounded input (item 23):**
- `AudioError` codes come from the decoder.
- The duration bound is enforced *while* decoding, so 8 MiB of Opus cannot expand into hours.
- The service maps every case to an HTTP status (`tools/speaking/CONTRACT.md` §4); `tests/test_audio_service.py` covers them.

**Two rule defects found while measuring, fixed before any candidate existed (reported for transparency):**
1. The first silence gate counted only frames 12 dB above the clip's own noise floor. It abstained on **every** utterance of one noisy MLS test speaker (29/240) although Whisper heard them clearly (P(no speech) ≈ 0.003).
2. The second gate (−50 dBFS absolute) abstained on 4 very quiet FLEURS recordings (−63 dBFS RMS) that Whisper transcribed perfectly.

The final gate catches only near-digital silence (< 0.3 s above −70 dBFS) and leaves noise to the model. Both defects were seen on test and ood, so the final gate was confirmed on dev (0 / 100 abstained) and on the probes. A deterministic **loop cut-off** was added at the same time, after tiny produced "très très très…" and "os-os-os…": it ends a window when an n-gram (n ≤ 10) repeats 4 times in a row. All baselines above were re-run with the final policy. The draft runs are kept in the handoff (`baseline-draft-gate-v0`).

**Reproducible commands (item 24)** are in §13; outputs are in `SPEAKING-MODEL-V1/evals/`.

## 6. Training (items 25–32)

| Item | Evidence |
|---|---|
| 25 entry point | `python -m flh_speaking train --config C --data D --base B --out O` (`train.py`), plus `sagemaker_entry.py` for SageMaker |
| 26 pins | base revision and file SHA-256 (`pins.py`); config SHA-256, data manifest SHA-256 and library versions in every `run_manifest.json`; seed 20261117; deterministic epoch permutations; `torch.use_deterministic_algorithms` |
| 27 real local smoke | `smoke-tiny.json`: real whisper-tiny weights, real audio (tiny fixture), full fine-tune, gradient checkpointing, 6 steps of 4 utterances. Loss 1.60 → 1.04, dev loss 0.742, about 4 s per step |
| 28 loss and parameters | before any update the library loss equals an independent log-softmax NLL over the same 209 target tokens (whisper-base pilot 0.668397 = 0.668397 over 209 tokens; tiny smoke 1.703331 = 1.703331 over 208; a uniform model would score ln|V| = 10.86). Only text and EOT are scored (the forced `<\|fr\|><\|transcribe\|><\|notimestamps\|>` prompt is masked). Trainable parameters: tiny full 37,760,640 / 37,760,640; base with decoder frozen 20,590,592 / 72,593,920 (encoder only) |
| 29 checkpoint + configuration | each `step-N/` holds `model.safetensors`, byte copies of the base's tokenizer/config files (so the tokenizer identity cannot drift), `trainer_state.pt` (optimizer, scheduler, step, every RNG state), `train_config.json`, `run_manifest.json` (file SHA-256, inputs, versions, `suitable_for_production: false`); written to a temporary directory, renamed, then `LATEST` replaced atomically |
| 30 resume after interruption | real whisper-tiny run **killed with SIGKILL** during step 3, resumed from `step-000002`; final weights **byte-identical** to the uninterrupted run (`model.safetensors` SHA-256 `89e7a298…` in both), with the same loss at every step. A changed config or data refuses to resume (test). SIGTERM finishes the step and saves. The pilot's first four attempts were killed by the memory watchdog before their first checkpoint (§14); after checkpointing every 5 steps and making the kernel prefer this batch's containers, it completed in one attempt |
| 31 audio conventions | one decoder and one feature extractor for preparation, training, evaluation and service; lossy re-encodings and resampling give identical WER (§5 probes) |
| 32 smoke checkpoint inspected | `verify_checkpoint` re-hashes every file (an altered weight file is caught: test); the checkpoint loads in the evaluator and the service (`deployment.identify` → `fine_tuned`, with base, step, config and data hashes) |

Not run: `configs/ablation-base-full.json` (full fine-tune of whisper-base) was prepared but not trained. CPU time went to the pilot and to the whisper-small baselines, and the pilot's result (A5) already predicts its style collapse.

Tests: `tests/test_train.py` (tiny random-weight Whisper with the real pinned tokenizer) checks the loss identity, checkpoint contents, byte copies, bit-identical resume, refusal of a changed config, frozen-parameter counts and refusal of test ids in training.

## 7. AWS (items 33–40)

`tools/speaking/aws/README.md` holds the template, IAM policy, bounded renderer, cost and exact commands.

| Item | Status | Detail |
|---|---|---|
| 33 inspect infrastructure | done | SageMaker training on `ml.g5.xlarge`, network isolation, image by digest, renderer with bounds; the execution role is scoped to `extractor/*` and `flh-extractor-sft` |
| 34 smallest suitable option | done | 1 × `ml.g5.xlarge`, Spot with S3 checkpoints (the trainer resumes exactly), 1 h runtime cap, 2 h wait cap, one retry |
| 35 cost | done | ≤ $1.41 compute (1 h × $1.408, us-east-1) + ≈ $0.80/month storage (S3 ≈ 1.6 GB, ECR ≈ 7 GB) until cleanup |
| 36 budget and limits | **blocked** | no monetary budget is established in the repository or handoffs (paid runs NO-GO since FLH-154), and `AGENTS.md` forbids agents from running AWS commands |
| 37 packaging | done | image `tools/speaking/Dockerfile` (GPU variant = default PyPI torch); dataset and base model addressed by SHA-256 prefixes; `sagemaker_entry.py` verifies both before training |
| 38 runtime, logs, outputs | done | `MaxRuntimeInSeconds` 3600, CloudWatch `/aws/sagemaker/TrainingJobs`, `CheckpointConfig`, `OutputDataConfig`, a one-line `/opt/ml/output/failure` |
| 39 submit pilot | **blocked** (same reason as 36) | the renderer produced a valid job file offline; `aws sagemaker create-training-job` is the owner's step |
| 40 monitor | **blocked** for AWS; done locally | the local pilot was monitored to completion (step log, dev loss, checkpoints every 5 steps); its earlier attempts were killed by the memory watchdog and are kept as evidence |

## 8. Evaluation and promotion (items 41–48)

**Candidate:**
- `whisper-base` encoder-only fine-tune, step 180 of 180 (`configs/pilot-base-encoder.json`): 1,440 MLS training utterances, 16 per step (2 epochs), lr 1e-5, seed 20261117, decoder frozen, 20,590,592 trainable parameters. The final step is the candidate, with no checkpoint selection on test.
- 1 h 39 min on 4 shared CPU cores (about 30 s per step). Dev loss 0.494 (step 60) → 0.483 (120) → 0.480 (180).
- `model.safetensors` `43cf1f2c…`; deployment identity `whisper-base-ft@step180-43cf1f2c4565/flh_speaking_transcribe_v1/cpu-fp32/9831ae6532cba509`.

**Same frozen items, same decoding policy, same batch size (items 41, 42):**

| Split | Pretrained base | Candidate | Δ (candidate − base) | 95% CI (paired cluster bootstrap) | Clusters better / worse (sign test) |
|---|---:|---:|---:|---|---|
| test (MLS, 8 speakers) | 27.12% | 26.64% | −0.48 pts | −1.77 to +0.84 | 5 / 3 (p = 0.73) |
| ood (FLEURS, 137 sentences) | 27.52% | 28.50% | +0.98 pts | −0.28 to +2.31 | 49 / 61 (p = 0.29) |
| dev (MLS, 4 speakers) | 21.97% | 21.74% | −0.23 pts | (training monitor only) | |
| accent (SLR57, 12 speakers), served | 37.69% | 36.09% | −1.60 pts | −3.19 to −0.59 | 9 / 1 (p = 0.021) |
| accent, raw model text | 35.18% | 33.89% | | | |

**Output style** (share of outputs with punctuation / an upper-case letter):

| Split | Base | Candidate |
|---|---|---|
| ood | 100% / 99.6% | **6.6% / 15.9%** |
| test | 100% / 98.8% | 6.7% / 8.8% |
| dev | 100% / 99% | 2% / 14% |

Freezing the decoder did **not** protect the style. The encoder learned to steer the frozen decoder into MLS's lower-case, unpunctuated orthography:

```text
REF   Il y a de nombreuses répercussions sociales et politiques telles que l'utilisation du système métrique, le pas…
BASE  Il y a de nombreuses répercussions sociales et politiques, dès que l'utilisation du système métrique, le passa…
CAND  il y a de nombreuses répercussions sociales et politiques dès que l'utilisation du système métrique le passage…
```

**Regressions by speaker, length and quality (item 43)** (served WER, base → candidate):

| Split | Group | Base → candidate |
|---|---|---|
| test | worst speaker (296) | 31.2% → 34.9% (+3.7) |
| test | best speaker (1406) | 27.7% → 24.4% (−3.3) |
| test | 8–14 s | 27.4 → 27.0 |
| test | ≥ 14 s | 27.0 → 26.5 |
| test | SNR < 25 dB | 24.8 → 25.4 |
| test | SNR 25–35 dB | 26.1 → 24.7 |
| test | SNR ≥ 35 dB | 28.7 → 28.2 |
| test | F | 27.0 → 26.2 |
| test | M | 27.2 → 27.1 |
| ood | 8–14 s | 25.9 → 27.7 (+1.8) |
| ood | SNR 25–35 dB | 29.7 → 32.0 (+2.3) |
| ood | F | 30.7 → 32.1 |
| ood | M | 26.6 → 27.5 |

No length, quality or gender group gains more than 1.5 points. Individual speakers move by up to ±3.7 points in both directions. FLEURS gets slightly worse in most groups.

**Leakage or overfitting (item 44):**
- Not leakage: no test, dev or ood reference shares any 8-gram with the training references, and the test delta on those 240 items is the whole test (A6).
- No train/dev divergence: dev loss falls monotonically.
- The pattern fits adaptation to MLS's *text conventions* rather than to its acoustics: style collapse, no in-domain gain, and slightly worse on another domain. The one gain is on accented French (−1.6 points, 9 of 12 speakers), but it does not offset the readability loss.

**Uncertainty (item 45):**
- Every interval is a paired cluster bootstrap over speakers (sentence groups for FLEURS), with an exact sign test over clusters.
- With 8 test speakers, the smallest attainable sign-test p is 0.0078 and the percentile interval is coarse. A difference under about 1.5 points on test cannot be resolved with this set.

**Abstention and unsupported feedback (item 46):**
- **Base and candidate behave the same on every probe:** 46 of 46 as expected (silence, hum, tone, clicks, noise, 20 English and Mandarin sentences abstain; invalid inputs refused; speech transcribed). A4 passes: no abstention lost, none added on French.
- **The model outputs only a transcript** with per-window confidence. It produces no pronunciation, fluency or grammar statement and no score, so no unsupported feedback exists to suppress; feedback stays with FLH's existing grounded feedback step.
- **The weakness found is the opposite error, false abstention on accented French.** `not_french` abstained on 24 of 515 SLR57 utterances (4.7%, short ones, median 2.8 s; for example "Mon camarade est malade." transcribed perfectly but P(fr) = 0.017), and `possibly_not_french` was raised on 127.
  - Accented French reaches P(fr) 0.0005 while real English and Mandarin peak at 0.0009, so no threshold separates them on this data.
  - This rule matters most for learners, who are accented by definition (decision D3).
- **Verbatim fidelity:** the SLR57 references keep speakers' own forms, and both models standardize them:
  - "S'il vous **plaire** monsieur l'agent." → base "Si le vous **plaît**, M. l'argent." / candidate "s'il vous **plaît** monsieur la j'en";
  - "Oui, qu'est-ce, qu'est-ce que vous voulez?" → "Oui, qu'est-ce que vous voulez ?" (repetition removed).

**Acceptance rule (item 47)** `flh_speaking_acceptance_v1`: written in `compare.py` and covered by tests before the pilot was trained (criteria in the module docstring).

**Verdict (item 48):** **KEEP_BASELINE** (`SPEAKING-MODEL-V1/acceptance.json`; `production_go: false`).

| Criterion | Result |
|---|---|
| A1 in-domain gain ≥ 2 pts with CI < 0 | **fail** (−0.48, CI −1.77 to +0.84) |
| A2 ood CI upper bound ≤ +1 pt | **fail** (+2.31) |
| A3 no speaker worse by > 5 pts | pass (worst +3.7) |
| A4 abstention | pass |
| A5 readable output ≥ 0.8 × base | **fail** (punctuation 6.6% vs 100%) |
| A6 gain not from text overlap | pass: no test item shares an 8-gram with training, so all 240 count, and the delta there is negative (−0.48) |
| A7 CPU RTF ≤ 0.5 | pass (0.048) |

**Recommendation:**
- Keep the pretrained model: whisper-small where memory allows, else whisper-base (D1).
- Do not promote this checkpoint.
- Do not repeat this experiment with unpunctuated targets.

## 9. Inference service (items 49–56)

`python -m flh_speaking serve` (`service.py`). Contract: `tools/speaking/CONTRACT.md`.

| Item | Evidence |
|---|---|
| 49 contract | `POST /v1/audio/transcriptions` answers FLH's existing Go client unchanged (`{"text"}` plus an `flh` block: status, warnings, language, durations, `audio_sha256`, `deployment_id`, timings). 13 HTTP tests with a fake model |
| 50 readiness | `/readyz` is 503 `loading` → 503 `warming` → 200 `ready`, and turns ready only after a warm-up inference through the real encoder and decoder. Observed: connection refused → 503 `loading` (0.5 s) → 503 `warming` (≈ 4.6 s) → 200 `ready` (≈ 5.1–5.6 s); in the benchmark, load 1.7 s, warm-up 0.4 s, ready after 5.2 s |
| 51 limits | request bytes (8 MiB + 64 KiB, refused before reading), audio ≤ 8 MiB and ≤ 120 s (enforced while decoding), accepted containers checked by magic bytes and by the decoder, one inference at a time plus a wait queue of 2 (429 `busy`), 30 s read timeout, 90 s inference deadline checked between decoding steps (504 `timeout`); loopback or private bind only (all interfaces only inside a container published on 127.0.0.1) |
| 52 temporary audio | decoding is in memory; no file is written. Tests run the service with `TMPDIR` pointing at an empty directory and find it still empty after success, a decode failure and a refused model. The end-to-end and benchmark containers had one entry each: an empty `torchinductor_uid_1000` directory that torch creates at import; no audio and no text entries in `/tmp` afterwards. Logs hold status, sizes and timings only; tests check that neither transcript text, audio bytes nor the Authorization header reaches them |
| 53 retries and duplicates | the service never retries and keeps no state; identical bytes give identical text (the benchmark sent each of four requests three times and got identical text every time; dev evaluated at batch 8 and batch 4 gives 100/100 identical texts). FLH's `Idempotency-Key` replays a finished request without a second model call (end-to-end: the replay returned 200 with `Idempotency-Replayed: true` and the same text, and the service counter stayed at 1 request) |
| 54 isolated pilot deployment | **local, not AWS**: the service container is published on 127.0.0.1 only, with no access to the NAS's daily instance, database or ports. An AWS deployment is not prepared: a GPU endpoint is unnecessary for this CPU-sized model, and AWS is blocked (§7) |
| 55 FLH end-to-end | verified with today's code and with the Go patch: §9.1 |
| 56 record | model revisions, `deployment_id`, response schema `flh_speaking_transcription_v1`, latency and memory: §9.2 |

### 9.1 End-to-end through FLH (`scripts/e2e_flh.py`, `SPEAKING-MODEL-V1/service/e2e-*.json`)

The real FLH server ran with a scrubbed environment and a fresh database, and used the whisper-base service on loopback. It was driven through FLH's own API:

| Step | Result |
|---|---|
| start a prompt; add a take | 201; 201 |
| transcribe a 16.5 s webm/Opus take | **201 `completed` in 1.58 s**, WER 21.3% against its MLS reference |
| the same request and `Idempotency-Key` again | 200, `Idempotency-Replayed: true`, same text; service request counter unchanged (no second model call) |
| request lookup; confirm the transcript | `completed`; 201 (version 1, origin `transcription`) |
| 3 s silent take | 502, stored `failure_code: invalid_output` (the service abstained; model not run) |
| service stopped | 502, stored `failure_code: provider_unavailable` |

Two runs:
- **Today's code** (`SPEAKING_TRANSCRIPTION_PROVIDER=openai` pointed at the service): provenance `openai:<deployment_id>:speaking_transcription_v1`.
- **With the proposed Go patch** (`local` provider): provenance `local:<deployment_id>:speaking_transcription_v1`, no API key sent.

The first patched run showed the request deadline still came from `OPENAI_TIMEOUT` (8 + 30 = 38 s). The fixed patch takes it from `SPEAKING_TRANSCRIPTION_TIMEOUT`; the re-run shows 150 s.

### 9.2 Service latency and resources (`scripts/service_bench.py`, `SPEAKING-MODEL-V1/service/bench-*.json`)

One request at a time, median of 3, container capped at 4 CPUs on the shared NAS host. All three runs of each request gave identical text.

| Audio | whisper-base: wall time | RTF | whisper-small: wall time | RTF | Windows |
|---|---:|---:|---:|---:|---:|
| 10 s | 0.80 s | 0.080 | 2.53 s | 0.253 | 1 |
| 30 s | 1.89 s | 0.063 | 3.43 s | 0.114 | 1 |
| 60 s | 3.40 s | 0.057 | 10.09 s | 0.168 | 3 |
| 120 s | 5.59 s | 0.047 | 17.27 s | 0.144 | 5 |

| | whisper-base | whisper-small |
|---|---|---|
| deployment_id | `whisper-base@e37978b90ca9/flh_speaking_transcribe_v1/cpu-fp32/3cb0fbf137cef809` | `whisper-small@973afd24965f/flh_speaking_transcribe_v1/cpu-fp32/6307099ec4850176` |
| ready after (load + warm-up) | 5.2 s (1.7 + 0.4 s) | 7.3 s (1.8 + 1.5 s) |
| memory after load / peak | 377 / 644 MiB (cap 1.5 GB) | 379 / 1,304 MiB (cap 1.8 GB) |

## 10. Handoff and continuation (items 57–64)

| Item | Evidence |
|---|---|
| 57 frontend fixtures | `tools/speaking/fixtures/frontend/`: real FLH responses from the end-to-end run (created, idempotent replay, request lookup, confirmed transcript, silent take, service down) |
| 58 retention | `tools/speaking/README.md` §Retention and `CONTRACT.md` §5: the service keeps nothing; FLH keeps audio metadata and confirmed transcripts only; learner recordings are never used for training without an owner decision |
| 59 extraction compatibility | no file under `tools/extraction/` or `deploy/` changed in this batch; the 27 FLH-154 pinned files verify; `tools/extraction` unittest: 98 OK (7 skipped, 1 expected failure), as at FLH-154 part 4 |
| 60 regression checks | listed below the table |
| 61 commands | §13 |
| 62 checksums and reload | the final pilot checkpoint re-hashes clean (`verify_checkpoint` → no problems), reloads in the transcriber, and identifies as `fine_tuned` (base whisper-base, step 180, config and data hashes) (`training/candidate-checkpoint-verify.json`); the smoke checkpoints of the interrupted and uninterrupted runs carry the same `model.safetensors` SHA-256 (`training/smoke-*-run_manifest.json`) |
| 63 compute and billable resources | no AWS resource exists: no command was run. Local: every container was `--rm` and capped; the end-to-end and benchmark containers were removed; nothing keeps running. Retained on disk outside Git (`~/flh-speaking-work`, about 11 GB: pinned sources 4.6 GB, prepared data 0.9 GB plus a 0.9 GB reproducibility copy (deletable), runs and checkpoints 3.5 GB): sources, prepared audio, checkpoints, run outputs |
| 64 results, blockers, next experiment | Summary, §8 and §12 |

Regression checks (item 60):

- `tools/speaking`: 36 tests OK in the image (none skipped); 36 on the host (13 run, 23 skipped there for lack of NumPy/torch).
- `verify_evidence.py`: 22 evidence files recomputed, 0 problems.
- The Go patch in a disposable tree: `go vet` and `go test` of `cmd/server`, `internal/config`, `internal/speaking`, `internal/transport/http`, `internal/application` OK.
- Unpatched worktree: no Go file changed.
- `tools/extraction`: 98 OK (7 skipped, 1 expected failure).

## 11. Item status

| # | Item | Status | Where / why |
|---:|---|---|---|
| 1 | Inventory Speaking/audio/transcription/model code | implemented | §1 |
| 2 | Most useful trainable task | implemented | §2: transcription |
| 3 | Compare transcription, pronunciation, fluency | implemented | §2 table |
| 4 | Research models (cards, papers) | implemented | §3 |
| 5 | Licences, languages, hardware | implemented | §3 |
| 6 | Choose task and model with rationale | implemented | §2–3: transcription with Whisper; whisper-base trained, whisper-small recommended for serving where memory allows |
| 7 | What the model measures vs human judgment | implemented | §2 |
| 8 | Minimal request/response contract | implemented | `tools/speaking/CONTRACT.md` |
| 9 | Inventory audio and labels with provenance | implemented | §4: FLH stores none; public sources pinned |
| 10 | Cleared for local use and AWS upload | implemented | §4: public CC-BY/Apache data only; no learner data |
| 11 | Public dataset | implemented | MLS French, FLEURS, SLR57 |
| 12 | Pin version, licence, download | implemented | `pins.py`, `fetch` |
| 13 | Decoding, sample rate, channels | implemented, verified | §4, probes |
| 14 | Speaker/source splits | implemented, verified | §4 |
| 15 | Duplicates and leakage | implemented, verified | §4 checks |
| 16 | Dataset manifest + tiny fixture | implemented, verified | manifest `4b1c067e…`; smoke trains on the fixture |
| 17 | Pretrained inference on the frozen sample | verified | §5 (tiny, base, small) |
| 18 | Task metrics | implemented | §5 |
| 19 | Baseline on held-out examples | verified | §5 table |
| 20 | Latency, peak memory, load time | verified | §5 (batch), §9 (service) |
| 21 | Short, silent, noisy, invalid audio | verified | §5 probes |
| 22 | French accents; learner speech | accents verified; **learner speech blocked** | §8 (SLR57); no cleared L2 recordings exist |
| 23 | Structured errors, bounded input | implemented, verified | `AudioError`, `CONTRACT.md` §4, tests |
| 24 | Seal baseline outputs, metrics, commands | verified | `SPEAKING-MODEL-V1/evals/`, §13, `verify_evidence.py` |
| 25 | Fine-tuning entry point | implemented | `train.py` |
| 26 | Pin revision, dependencies, seeds, config | implemented | `run_manifest.json` |
| 27 | Tiny local smoke with real model operations | verified | §6 |
| 28 | Loss and trainable parameters | verified | §6 |
| 29 | Checkpoints with configuration | verified | §6 |
| 30 | Resume; interruption recovery | verified | SIGKILL → byte-identical weights; pilot resumed after watchdog kills |
| 31 | Compatible audio conventions | verified | §5 probes, §6 |
| 32 | Completed smoke; checkpoint inspected | verified | §6 |
| 33 | Inspect AWS infrastructure and permissions | implemented | §7 (files only; no AWS call) |
| 34 | Smallest execution option | implemented | `ml.g5.xlarge` Spot, 1 h cap |
| 35 | Cost estimate | implemented | ≤ $1.41 + ≈ $0.80/month |
| 36 | Verify budget and runtime limits | **blocked** | no budget established; AGENTS.md forbids agent AWS commands |
| 37 | Package code and data references | implemented | Dockerfile, hashes, `sagemaker_entry.py` |
| 38 | Runtime, logs, output locations | implemented | template + renderer (refuses out-of-bounds jobs) |
| 39 | Submit a training pilot | **blocked** (AWS); pilot run locally | as 36 |
| 40 | Monitor to completion | **blocked** (AWS); done locally | §6, §7 |
| 41 | Evaluate checkpoint on frozen held-out set | verified | §8 |
| 42 | Trained vs pretrained on identical examples | verified | §8 |
| 43 | Regressions by speaker, length, quality | verified | §8 |
| 44 | Leakage or overfitting check | verified: not leakage; adaptation to MLS text conventions | §8 |
| 45 | Uncertainty for sample size | implemented | speaker bootstrap + exact sign test (8 speakers) |
| 46 | Abstention and unsupported feedback | verified (finding: false `not_french` on 4.7% of accented French) | §5 probes, §8 |
| 47 | Explicit acceptance rule | implemented (written before the pilot) | `compare.py` `flh_speaking_acceptance_v1`, tests |
| 48 | Seal comparison + recommendation | verified: **KEEP_BASELINE** | `acceptance.json`, §8 |
| 49 | Expose the model through the contract | implemented, verified | `service.py` |
| 50 | Readiness: loading vs usable | verified | §9 |
| 51 | Size, duration, timeout, concurrency limits | verified | §9, tests |
| 52 | Temporary audio cleanup | verified | none is created (tests, containers) |
| 53 | Retries and duplicates explicit | verified | §9 |
| 54 | Isolated inference pilot | verified locally; AWS **blocked** | §9 |
| 55 | One end-to-end request through FLH | verified (today's code and the patched Go tree) | §9 |
| 56 | Record revision, schema, latency, resources | verified | §9 |
| 57 | Fixture responses for the frontend | implemented | `fixtures/frontend/` |
| 58 | Transcript and recording retention | implemented | README, CONTRACT |
| 59 | Extraction evaluation compatibility | verified | §10 |
| 60 | Model/service regression checks | verified | §10 |
| 61 | Retraining, evaluation, deployment commands | implemented | §13, `aws/README.md` |
| 62 | Checksums; reload the saved model | verified | §10 |
| 63 | Stop compute; inventory billable resources | verified | §10: no AWS resource; no container left running |
| 64 | Training results, blockers, next experiment | implemented | Summary, §8, §12 |

## 12. Owner decisions and next experiment

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Use the local service for Speaking transcription, and which model | (a) keep OpenAI or typing; (b) local whisper-small (WER ≈ 13–17%, 2.5–17 s per take, about 1.3–1.8 GB); (c) local whisper-base (WER ≈ 27–35%, 0.8–5.6 s, about 0.4–0.65 GB) | (b) if the NAS can reserve about 1.8 GB beside its services (today it often has about 1 GB free), otherwise (c); opt-in, **with the Go patch applied** |
| D2 | Apply `SPEAKING-MODEL-V1/go-local-provider.patch` (shared files `internal/config`, `internal/speaking`, `cmd/server`) | apply / not | Apply. Without it, the local model is recorded as `openai:…`, shares `OPENAI_BASE_URL` (so OpenAI feedback cannot run beside it) and the default 8 s `OPENAI_TIMEOUT` is too short. The patch adds `SPEAKING_TRANSCRIPTION_PROVIDER=local`, its own base URL and timeout (default 60 s), `local:` provenance and a matching request deadline. Tested in a disposable tree (§9) |
| D3 | The `not_french` abstention on accented speech | (a) keep (blocks 4.7% of accented French, mostly short takes); (b) warning only (a non-French take yields a forced-French draft the learner sees and rejects); (c) abstain only on long takes | (b) for learners, as policy `flh_speaking_transcribe_v2`, validated on new data before use (not tuned on this test) |
| D4 | The pilot checkpoint | promote / keep baseline | Keep the baseline (KEEP_BASELINE; §8) |
| D5 | Learner (L2) evaluation data | (a) none; (b) an owner-approved, consented collection: explicit opt-in per take, verbatim transcripts by the learner, a retention limit and a deletion path | (b), small: about 30 speakers × 10 takes. Nothing in this batch can say how the model treats learner errors beyond the SLR57 evidence that it standardizes them |
| D6 | AWS budget | set one (≈ $5/month alert; one pilot ≤ $1.41 + storage) / keep local | Only together with D5 or punctuated targets (next experiment); another MLS run would repeat the negative result |
| D7 | Shared docs | adopt `SPEAKING-MODEL-V1/agents-md-proposal.md` into `AGENTS.md` | after D1 |
| D8 | Recording guidance | noise robustness is poor (43% WER at 20 dB SNR) | a one-line UI hint ("record in a quiet place") is cheap; owner/UI lane |

Still open and outside this lane: integrating the FLH-154 and Speaking handoffs.

**Next justified experiment.** Fine-tune only on **cased, punctuated** targets, with **noise augmentation**, and evaluate on a held-out **learner** set:

- The pilot showed that MLS's normalized text teaches the model to drop case and punctuation even through a frozen decoder.
- Noise is the largest measured weakness.
- Learner speech is the product's real domain.

Data: FLEURS fr_fr train (CC-BY-4.0, `raw_transcription`), plus Common Voice French if its terms are accepted by the owner. Training: GPU via the prepared SageMaker job (D6), which also makes whisper-small trainable.

Acceptance stays `flh_speaking_acceptance_v1`, plus an L2 criterion once D5 exists.

## 13. Rerun

```sh
cd tools/speaking
python3 -B -m unittest discover -s tests -t tests                                   # host tests
docker build --build-arg TORCH_INDEX=cpu -t flh-speaking:cpu .
W=$HOME/flh-speaking-work
python3 -m flh_speaking fetch --dest $W/sources --what whisper-tiny whisper-base whisper-small mls fleurs slr57
RUN="docker run --rm --oom-score-adj 1000 --network none --memory 1536m --memory-swap 1536m --cpus 4 --user $(id -u):$(id -g) -e HOME=/tmp -v $W/sources:/sources:ro"
BASE=/sources/openai/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb
$RUN -v $W/data-v1:/data flh-speaking:cpu prepare --sources /sources --out /data          # manifest 4b1c067e…
$RUN -v $W/data-accent:/data flh-speaking:cpu prepare-accent --sources /sources --out /data
$RUN -v $W/data-nonfr:/data flh-speaking:cpu prepare-non-french --sources /sources --out /data
for s in test ood dev; do $RUN -v $W/data-v1:/data:ro -v $W/out:/out flh-speaking:cpu evaluate --model $BASE --data /data --split $s --out /out/base-$s.json --batch 4; done
$RUN -e FLH_SPEAKING_NON_FRENCH=/nonfr -v $W/data-nonfr:/nonfr:ro -v $W/data-v1:/data:ro -v $W/out:/out flh-speaking:cpu probes --model $BASE --data /data --out /out/probes.json
$RUN -v $PWD/configs:/configs:ro -v $W/data-v1:/data:ro -v $W/pilot:/out flh-speaking:cpu train --config /configs/pilot-base-encoder.json --data /data --base $BASE --out /out   # rerun = resume
$RUN -v $W:/w flh-speaking:cpu accept --base /w/accept/base --cand /w/accept/cand --data /w/data-v1 --out /w/acceptance.json
python3 -I scripts/e2e_flh.py --repo ../.. --work $W/e2e --sources $W/sources --data $W/data-v1 --model-subdir openai/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb --server-bin BIN --provider openai
python3 -I scripts/service_bench.py --sources $W/sources --data $W/data-v1 --model-subdir openai/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb --out $W/bench.json
cd ../.. && python3 -I -B docs/validation/SPEAKING-MODEL-V1/verify_evidence.py                       # recomputes every number here
```

## 14. Incidents and deviations

1. **Abstention gate fixed twice, before any candidate.**
   - The relative-energy gate abstained on a whole noisy test speaker.
   - The −50 dBFS gate abstained on 4 quiet FLEURS clips.

   Both were found on test/ood, the final gate was confirmed on dev, and all baselines were re-run. The loop cut-off was added at the same time. Draft runs are kept (`baseline-draft-gate-v0` in the handoff).
2. **Memory pressure on the shared host.** Other sessions and the host's `/tmp` (tmpfs) leave about 0.8–1.7 GB available. A watchdog stops only this batch's containers below a threshold (400 → 300 → 150 MB). It stopped 11 of them in 10 events: 4 whisper-base evaluations, 4 pilot attempts and 3 others (draft-run and test containers), some early on while I ran a test container and a `go build` beside an evaluation. **No other process was touched.**

   Mitigations:
   - one-at-a-time lock;
   - batch 4 and 1.5 GB caps for whisper-base;
   - `--oom-score-adj 1000` so the kernel would pick these containers first;
   - checkpoints every 5 steps;
   - automatic resume.

   The pilot config changed only `save_every` (20 → 5), before any candidate result; the killed attempts' log is kept.
3. **Own files moved.** I moved this session's own 159 MB scratchpad from 2026-11-11/12 from the RAM-backed `/tmp` to the home disk (`~/flh-speaking-work/archived-scratchpad-e3c2e1db`). Nothing else in `/tmp` was touched.
4. **Self-matching patterns.** Twice a `pkill -f`/`kill` pattern matched my own shell, and the commands in it did not run. Once a `pgrep -f` wait loop matched itself and was stopped. In both cases the runner and watchdog were restarted and checked; nothing else was affected.
5. **Truncated download.** The first whisper-small weights download ended early (669 of 967 MB). The fetcher's size check refused and deleted it; re-fetched and verified.
6. **Library changes.** PyAV 19 removed `metadata_errors=`, and `transformers` 5.21's Whisper `generate()` refuses precomputed encoder outputs. Both were replaced with explicit code (an in-memory decoder and a greedy KV-cache loop).
7. **Temporary-file locations.** The Go linker failed on the shared `/tmp` quota; builds used a home-disk `TMPDIR`. A host helper wrote a `__pycache__` into `tools/speaking/flh_speaking/`; it was removed and the helper now writes no bytecode.
8. **Go patch fix.** The first version of the Go patch kept the 38 s request deadline (found by the end-to-end run); fixed in v2.


