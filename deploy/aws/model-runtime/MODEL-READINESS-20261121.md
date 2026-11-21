# Model readiness for the cross-subject workflow (2026-11-21; local checks only)

**Out of scope.** No AWS call was made, no model was downloaded and no paid job was run.

**How the numbers were produced.**

```sh
python3 -I -B tools/extraction/scripts/model_readiness.py --qwen-dir DIR … --whisper-dir DIR --runs 20 --json OUT
```

The script writes file names and statuses only, never machine paths.

## 1. Artifacts and expected digests (EXT-071)

| Artifact | Pin | Expected | Used by |
|---|---|---|---|
| `Qwen/Qwen3.5-4B` | revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`, Apache-2.0 | 9 small files by SHA-256 (`tools/extraction/configs/qwen3.5-4b-851bf6e8.sha256`); 2 weight shards named by the pinned index, size only (9,319,737,856 bytes) | optional SFT candidate (SageMaker only) |
| `Qwen/Qwen3-1.7B` | revision `70d244cc86cc…` | no digest file (superseded, never trained) | none |
| `openai/whisper-tiny` / `-base` / `-small` | `tools/speaking/flh_speaking/pins.py` (size + SHA-256 or git blob per file) | 155,434,424 / 294,776,748 / 971,367,937 bytes | Speaking (`whisper-base` is the approved default) |
| extraction service | `flh-extraction-rules@e978b6c2bdb6/flh_extraction_service_v1/flh_practice_drafter_v1` | SHA-256 of its 15 code files (`GET /manifest`) | rules only, no model |

## 2. Runtime contracts in place (EXT-072)

| Runtime | Contract | Where |
|---|---|---|
| extraction service | `flh_extraction_service_v1`; 256 MiB; 1 CPU; read-only; 5 s deadline; no model | `tools/extraction/SERVICE.md`, `EXTRACTION-SERVICE-RUNTIME.md` |
| cross-subject workflow (`units`, `unit_eval`, `unit_handoff`) | offline CLI, standard library, no model, no network; `flh_learning_units_v1` and companions | `tools/extraction/UNITS.md` |
| Speaking transcription (local provider) | `flh_speaking_transcription_v1`; `model` must equal the deployment ID; abstains with `no_speech` / `not_french` | `tools/speaking/CONTRACT.md` |
| Qwen SFT and predict | SageMaker job templates with readiness bounds (smoke 0.5 h ≈ $0.704 on `ml.g5.xlarge`) | `deploy/aws/sagemaker-extractor/readiness/README.md` |

## 3. Availability on this machine (EXT-073, EXT-074)

| Artifact | Status | Evidence |
|---|---|---|
| Qwen3.5-4B | **UNAVAILABLE**: `tokenizer.json`, `vocab.json`, `merges.txt` and both weight shards missing; 4 small files present and verified | `check_model_assets.py` exit 3; R4 handoff `evidence/071-080/` |
| Qwen3-1.7B | **UNAVAILABLE** (no digest file, no files) | the same |
| whisper-tiny, -base, -small | usable: every pinned file present with its digest | the same |

**Consequences.**
- No extraction-model baseline can be measured locally.
- The measured extraction baselines are model-free: the rules workflow, and the sentence
  baseline in `fixtures/xsubject_v1/eval` (coverage 7/13 against 8/13 for authored proposals).
- The Speaking base was measured on 2026-11-20 in the R4 inference dry-run: a 16.5 s French
  clip took 8.7 s (`model_s` 8.59), the service was ready in 13 s, and silence and a tone were
  answered `no_speech`.

## 4. Measurements of the fixture workflow (EXT-075 to EXT-077)

Music source, 20 warm runs and 5 cold processes, on an i7-1165G7 (8 cores, shared load).

| Stage | Warm median | Cold median (fresh process) |
|---|---|---|
| preprocessing (read and check the source, ground every quote) | 0.29 ms | 0.48 ms |
| review and batch approval | 0.31 ms | 0.60 ms |
| units export with recall | 0.24 ms | 0.40 ms |
| inference | 0: rules only, no model | 0 |
| whole process (interpreter start and imports included) | — | 76 ms (wall time 100 ms) |
| peak RSS | — | 35.4 MiB |

**Inference against preprocessing.**
- Fixture workflow: all time is preprocessing and bookkeeping.
- Speaking: inference dominates (8.59 of 8.70 s; audio decoding about 0.1 s).

**Memory.**

| Runtime | Peak |
|---|---|
| fixture workflow | about 36 MiB |
| extraction service container | 24.3 MiB (R4) |
| Speaking base | about 0.6 to 1.2 GB (R3) |
| Qwen3.5-4B | not measurable here; its weights alone are 9.3 GB |

## 5. CPU fallback (EXT-078)

**The fixture workflow is the CPU path.** It runs on the standard library with no model.

**Model-free extractor.** `unit_eval.sentence_baseline` is deterministic and language-agnostic,
and measured.

**Rule: never fall back silently.** If an optional model step is missing or fails:
- the local rules output stays as it was (`units.rerun_status`: `extractor_failed` keeps the
  last good units);
- the model step reports its own failure.

## 6. Daytime acceptance checklist for a model deployment (EXT-080)

Run in daylight, by the owner, after explicit approval. Stop at the first failed line.

1. **Approval recorded:** account, region, profile and budget ceiling, plus the artifact's pin
   (revision and digests above).
2. **Assets:**
   - `check_model_assets.py` exits 0 for the pinned files;
   - every weight shard is present at its indexed size;
   - nothing is substituted.
3. **Image:** built from the reviewed Dockerfile; its digest is recorded; the deployment ID is
   pinned, not the image ID.
4. **Readiness:**
   - `/readyz` stays 503 until a warm-up inference succeeds;
   - `/manifest`'s deployment ID equals the pin.
5. **Contract:**
   - the service smoke passes;
   - a request with another model ID is refused;
   - silence or empty input abstains or is refused, never answered with invented text.
6. **Quality on frozen held-out data:**
   - the pre-registered thresholds are met with their denominators (Speaking:
     `tools/speaking/aws/r4-pilot.prereg.json`; extraction: `fixtures/xsubject_v1/eval` scorecard);
   - below the support threshold the result is an observation, not a promotion.
7. **Resources:** peak memory and latency are measured at the configured concurrency, within
   the container limits.
8. **Privacy:** logs and exported files carry no learner text and no machine path.
9. **Failure behaviour:** stop the model. The app stays ready; the local output stays usable;
   the caller sees `unavailable` once and nothing retries.
10. **Teardown and rollback:**
    - the teardown plan check passes;
    - rollback to the previous pin is rehearsed;
    - evidence is copied before anything is deleted.

**Stop conditions:** any failed line; an unexpected cost; a quota or permission denial; any
substitution of a pinned file.
