# Local Speaking Lab v1 (items 001–100)

Local transcription, extraction evaluation and Speaking tools; CPU only.

This batch kept the serving defaults:
- `SPEAKING_TRANSCRIPTION_PROVIDER` stays `disabled` in Compose and the daily env;
- `RUNBOOK.md` still names pretrained whisper-small for the opt-in local provider.

No paid call, AWS command or learner data was used.

Large artifacts stay out of Git:
- audio, weights and evaluation outputs live in the owner's work directory (`$W`);
- only hashes, sizes and summary numbers are recorded here.

Handoffs, with commands and actual outcomes for each step, are at items 010,
025, 050, 075 and 100. They sit outside the repository.

Labels used in §7:
- **implemented** means code and tests in this tree, run in this batch;
- **experimented** means a bounded run with real models, whose numbers are below;
- **owner-review** means a proposal the owner applies, or a decision that is the owner's;
- **prototype** means a research harness, not a product feature.

## 1. What a reviewer can run

```sh
cd tools/speaking
python3 -B -m flh_speaking lab demo --check            # one case: accent and omitted word; text and JSON from one computation
python3 -B scripts/run_tests.py                        # offline: standard library only
cd ../extraction
python3 -B -m flh_extraction evidence-review --refs fixtures/evidence_review_v1/refs.jsonl \
    --a fixtures/evidence_review_v1/result-a.jsonl --b fixtures/evidence_review_v1/result-b.jsonl
```

The full strict command, its cache identity and the expected report are in
`SPEAKING-TEST-ENTRY.md`, increment 3. The tool reference is in
`tools/speaking/README.md`, under Speaking Lab and Runtime diagnostics.

## 2. Integration handoff (081–090)

The service was the lock-built image with pinned whisper-base, under
`--cpus 2 --memory 2g` on 127.0.0.1. FLH was the binary built from this tree.
The audio was synthetic tones, so there was no speech.

| Item | Evidence |
|---|---|
| 081 response schema vs a synthetic client | `flh_speaking/client.py` checks each 200 answer the way FLH's Go client reads it. The live answer passed: `ok`, no problems, no optional field omitted, status `no_speech` for a tone. All six error bodies seen passed `check_error`. `tests/test_client.py` checks the response printed in `CONTRACT.md` §3 |
| 082 omitted optional fields | an answer with only `text` and `flh.deployment_id` passes the client (`omitted_optional` lists all nine) and FLH's Go client (`TestLocalTranscriberAcceptsAMinimalAnswerFromAnOlderService`). A missing `flh` block or another deployment is refused by both |
| 083 Compose forwarding | **owner-review.** `compose.yaml` today forwards `SPEAKING_TRANSCRIPTION_PROVIDER` and `_MODEL` only. `SPEAKING-LOCAL-PROVIDER/release-lane-handoff.patch` (sha256 `37f11f9c…ee954da`) adds `_BASE_URL` and `_TIMEOUT` and the daily-wrapper checks. It was applied to a scratch copy of this tree: `docker compose config` showed all four variables, and `scripts/validation/flh094/test_wrapper.sh` reported `{"failures": 0}`. Not applied here: those files belong to the release lane |
| 084 release proposal | **owner-review.** See §3 |
| 085 loopback health | `/healthz` 200 and `/readyz` 200 on 127.0.0.1, before and after each rejected request (`client_check` in this batch's second `runtime-diagnostics.json`, copied to the item-100 handoff evidence) |
| 086 Go behaviour, exercised vs proposed | see the table below |
| 087 no machine paths | `lab privacy-check` finds home paths, claude.ai links and UUID-shaped IDs. It ran on every file this batch adds or changes, and on the diagnostics and experiment reports: 0 findings. The test inputs build those strings by concatenation, so the diff holds none |
| 088 readiness checklist | §4 |
| 089 revert to the previous provider | FLH was restarted with `SPEAKING_TRANSCRIPTION_PROVIDER=disabled`, the setting before the local provider. `/speaking/prompts` then reported `transcription: enabled false`. The same click answered 503 with the message quoted under 090. The earlier failed transcription was still stored (1 listed), and the OpenAI sentinel got 0 requests |
| 090 a visible failure example | with the service stopped, FLH answers 502 and stores `failed` / `provider_unavailable`. The learner sees "the transcription provider is unavailable; your take and transcripts are kept". After the rollback the learner sees "speaking transcription is not enabled (SPEAKING_TRANSCRIPTION_PROVIDER); type the transcript instead". Both rows are in the README's troubleshooting table |

**Go behaviour exercised in this batch vs only proposed (086).**

| Behaviour | Exercised (how) | Proposed only |
|---|---|---|
| local transcriber: request shape, deployment check, minimal answer, error mapping | `go test ./internal/speaking/...` (includes the new minimal-answer test) | — |
| FLH with `SPEAKING_TRANSCRIPTION_PROVIDER=local`, service down | binary from this tree: 502 `provider_unavailable`, sentinel 0 requests | — |
| rollback to `disabled` | same binary restarted: 503, history kept | — |
| Compose forwarding of `_BASE_URL` / `_TIMEOUT` | scratch copy only (`docker compose config`) | the patch (§3) |
| daily wrapper accepting `local` | scratch copy only (`test_wrapper.sh`) | the patch (§3) |
| FLH inside the release container talking to a host service | not run: needs the owner's daily stack | `RUNBOOK.md` §4–§6 |

## 3. Release proposal (084, owner-review)

The owner reviews and runs this. Nothing here was applied to the release-lane
files.

```sh
patch -p1 --dry-run < docs/validation/SPEAKING-LOCAL-PROVIDER/release-lane-handoff.patch   # must print only "checking file …"
patch -p1 < docs/validation/SPEAKING-LOCAL-PROVIDER/release-lane-handoff.patch
TMPDIR=<disk tmp> bash scripts/validation/flh094/test_wrapper.sh <empty work dir>          # expect {"failures": 0}
```

Defaults after the patch: `SPEAKING_TRANSCRIPTION_PROVIDER` still `disabled`;
the new variables empty. Enabling the local provider is a separate owner step
(§4).

## 4. Readiness checklist before enabling the local provider (088)

1. The service image is built from `requirements-cpu.lock` (the lock hash inside the image equals the tree's).
2. The model directory passes `lab candidate check` (no problem), and `GET /manifest` names the expected `deployment_id`.
3. `/healthz` and `/readyz` are 200 on the address FLH will use, and the service is not reachable from the LAN (`--host` rules, README).
4. `SPEAKING_TRANSCRIPTION_MODEL` equals that `deployment_id`.
5. `SPEAKING_TRANSCRIPTION_TIMEOUT` is below `HTTP_WRITE_TIMEOUT`; the wrapper refuses otherwise.
6. One explicit transcription through FLH returns 200, and the synthetic client check passes on the service's answer.
7. Rollback is known and tested: set `SPEAKING_TRANSCRIPTION_PROVIDER=disabled` and restart. Takes and transcripts stay.
8. `lab privacy-check` passes on anything shared about the run.

## 5. Bounded CPU experiment (091, 094, 095, 097)

**Status: experimented. Harness: prototype** (`tools/speaking/scripts/lab_experiment.py`).

**Question.** On a small slice of the frozen MLS-fr test split, how do the two
pinned public models differ? And does seeded white noise change that
difference?

**Slice and conditions.**
- the first 5 clips per test speaker in id order: 8 speakers, 40 clips, 644.3 s of audio;
- clean, and 20 dB SNR white noise with seed 7.

**Bounds.** Four `evaluate` calls in the lock-built image (the image's lock
equals the tree's), each with:
- `--network none`, `--cpus 2`, 2 GB memory and swap;
- batch 1, 2 threads;
- the CPU lock held, and this tree's code mounted read-only.

Wall time: base 64 s and 62 s, small 187 s and 178 s; 491 s in all.

**Identity (094).**
- `experiment_id` `lab-exp-3e998448c4e6ea64`, a hash over every defining input:
  - source manifest `4b1c067e…`, slice ids `0efa6710…`, prepared manifest `ab6bd032…`;
  - candidates `whisper-base@e37978b90ca9/cpu-float32/617eb205053eecc5` and
    `whisper-small@973afd24965f/cpu-float32/6253650582951d8a`;
  - image `sha256:e7d42c0e7dfd…` (lock `2eed2ed2…`);
  - code hashes, limits, bootstrap settings and normalization fingerprint.
- No candidate was invalidated.
- Each comparison carries the same sample-order hash, `0efa6710177a…`.

**Results.** WER is under `flh_fr_asr_norm_v1`. Speakers are the groups. The
interval is a 95% speaker bootstrap (2,000 resamples, seed 20261119).

| Comparison (A → B) | WER A | WER B | B − A [95% interval] | B fewer / more errors: clips (of 40) | speakers (of 8) | standing |
|---|---|---|---|---|---|---|
| base → small, clean | 0.2571 | 0.1431 | −0.1140 [−0.1338, −0.0952] | 33 / 2 | 8 / 0 | observation |
| base → small, noise 20 dB | 0.3031 | 0.1536 | −0.1495 [−0.1631, −0.1329] | 38 / 2 | 8 / 0 | observation |
| base: clean → noise | 0.2571 | 0.3031 | +0.0460 [+0.0234, +0.0652] | 9 / 25 | 1 / 7 | observation |
| small: clean → noise | 0.1431 | 0.1536 | +0.0105 [+0.0006, +0.0208] | 8 / 17 | 2 / 6 | observation |

Per self-reported gender (4 speakers each, so observations): base → small is
−0.115 (F) and −0.113 (M) clean, and −0.141 (F) and −0.158 (M) with noise. There
were no abstentions.

Tradeoffs, reported side by side and not folded into one score:

| | RTF (2 threads) | peak RSS | load |
|---|---|---|---|
| whisper-base | 0.088–0.092 | 756 MB | 3.4 s |
| whisper-small | 0.268–0.282 | 1,511 MB | 3.4–3.5 s |

**Reading.** On these 8 native audiobook speakers, small makes about 44% fewer
word errors than base (about 49% with noise), for about 3× the compute and 2×
the memory. Seeded 20 dB white noise hurts base more than small: +4.6 against
+1.1 points.

This agrees with the stored v1 evaluation of the full 240-clip test split (27.1%
vs 14.9%). It does not change the serving default, which already is small.

Every row is an observation: 8 groups are below the 30-group ranking minimum,
and the intervals are marked unstable. They describe these speakers redrawn,
not learners (§6).

**Differing sample set refused (095).**
- In a scratch copy, one result row was dropped from small's file.
  `lab batch` exited 4, `not_ranked` ("the sample sets differ"), and named the
  missing id.
- `lab_experiment.py report` refuses two evaluations that do not share one
  reference set; `tests/test_lab_experiment.py` pins this.

**Smallest slice re-run (097).**
- `rerun` picked the speaker with the least audio in the slice (2085) and ran
  whisper-base on the noise copies again: 5 of 5 served texts and statuses were
  identical to the first run, in 12.1 s.
- Output `rerun/whisper-base-noise20-2085.json`: 12,337 bytes, sha256 `4134fc8e…`.

**Output sizes, all outside Git (098).**
- evaluations and reports: 12 files, 361,349 bytes, each with its SHA-256 in `experiment-result.json`;
- prepared audio: 41,238,268 bytes;
- re-run: about 24 KB.

The privacy check found 0 findings in every report.

## 6. Provenance, separation and gaps (092, 093, 096, 098, 099)

**Fixtures, licences and provenance (092).**

| Input | Provenance | Licence | In Git |
|---|---|---|---|
| `tools/speaking/fixtures/lab/*` | hand-written synthetic transcripts and references; reviewer records written for the fixture | project | yes |
| synthetic tone (`lab.synthetic_audio`) | generated in code: 0.6 s, 220 Hz, 16 kHz | project | code only |
| `tools/extraction/fixtures/evidence_review_v1/*` | hand-written synthetic records, no provider call; `meta.label_status` `machine_authored_unreviewed` | project | yes |
| whisper-tiny tokenizer fixture (no weights) | `openai/whisper-tiny` @169d4a43, 10 files pinned in `pins.py`, contract `55f3d55e…` | Apache-2.0 card, MIT repository | no (fetched) |
| whisper-base / whisper-small weights | @e37978b9 / @973afd24, every file pinned by size and digest | same | no |
| MLS-fr test split (experiment slice) | `facebook/multilingual_librispeech` @2e83e618, prepared v1 data, manifest hashed in `prepare.json` | CC-BY-4.0 | no |

**Data, weights, results and source kept apart (093).**
- Source (code, synthetic fixtures, docs) is in Git.
- Data (prepared audio) is in `$W/data-v1` and `$W/v3/exp091/data`.
- Weights are in `$W/sources`, read-only in every container.
- Results are in `$W/v3/exp091/{evals,report}` and the handoff evidence.

Each container mounts weights and data read-only, and results are written to
one mount only. The experiment result names each input by hash.

**Confidence and fairness gaps (096).**
- No calibrated confidence. The lab never invents one:
  - measured diagnostics are `measured`;
  - rules are `rule`;
  - guesses are `heuristic`;
  - absent values are `not_supplied`.
- Whisper's no-speech probability is used only inside the service's
  abstention rule. It is not a probability that a transcript is right.
- Speaker fairness: 8 MLS speakers, native audiobook readers, with
  self-reported gender as a slice tag. Per-gender cells are observations, with
  fewer than 5 groups each. Nothing measures accent, age, learner (L2) speech,
  phone microphones or children.
- Learner speech was never collected. Collecting it needs owner approval and
  consent (SPEAKING-MODEL-V1 §12).
- Pronunciation is never graded. The lab compares text only.
- The interval covers redrawing these 8 speakers, not other populations.

**Output sizes outside Git (098)** and **logs, risks and staging paths
(099)**: in §5 and in the item-100 handoff.

## 7. Status of every item (100)

| Items | Status | Where |
|---|---|---|
| 001–010 Speaking Lab: two transcripts vs one reference, synthetic French case, views, edits, low-evidence states, identities, demo, text + JSON, CPU-only command | implemented | `flh_speaking/lab.py`, `lab demo --check`, `fixtures/lab/` |
| 011–020 evaluation contract: policy fingerprint, punctuation and case apart, French forms, empty reference vs prediction, deterministic alignment, counts, paired results, missing IDs before ranking, three-row hand check | implemented | `lab.py`, `textnorm.py`, `tests/test_lab.py` |
| 021–030 quality slices: tags, volume without clipping, silence, seeded noise, groups, ranked regressions with minimum sizes, low support as observations, fixture capabilities | implemented | `variants.py`, `lab batch`, README table |
| 031–040 confidence and review: measured vs heuristic, silence rule, wrong language, invalid, actionable abstention, no invented confidence, correction source, reviewer validation, abstention before/after, walkthrough | implemented | `review.py`, `fixtures/lab/review/` |
| 041–050 candidates: manifest, device and precision, file checks before loading, serving default kept, order and seed, tradeoffs, promotion checklist, reproducibility, dry run, invalidation | implemented; 047 promotion is **owner-review** | `candidates.py`, README |
| 051–060 runtime: readiness, load / first / warm, RTF, limits, oversized and timed-out requests, ready after a rejection, no paid request, error classes, bounded concurrency, troubleshooting | implemented and measured with whisper-base | `scripts/runtime_diagnostics.py`, README |
| 061–070 strict CPU: offline entry kept, strict failures, fixture-only download, lock-built image, network blocked, separate timings, corrupt fixture, counts check, environment vs test failure, release command | implemented | `scripts/run_tests.py`, `SPEAKING-TEST-ENTRY.md` increment 3 |
| 071–080 extraction review: error beside evidence, unsupported / missing / malformed apart, coverage per kind, FLH-154 known failure apart, deterministic A-vs-B, excerpts only, conflict and missing-span fixtures, pagination, accepted and rejected results, pinned hashes | implemented | `tools/extraction/flh_extraction/evidence_review.py` |
| 081, 082, 085, 087, 089, 090 | implemented and exercised | §2 |
| 083 Compose forwarding, 084 release proposal | **owner-review** (patch verified in a scratch copy, not applied) | §2, §3 |
| 086 exercised vs proposed, 088 readiness checklist | implemented (docs) | §2, §4; enabling the provider is **owner-only** |
| 091, 094, 097 | **experimented** (harness: **prototype**) | §5 |
| 092, 093, 095, 096, 098 | implemented | §5, §6 |
| 099 logs, risks and staging paths | in the item-100 handoff | outside the repository |
| 100 | this table | — |

**Owner-only steps.**
- Apply the release-lane patch (§3).
- Enable `SPEAKING_TRANSCRIPTION_PROVIDER=local` on the daily instance (§4).
- Decide any model promotion (README checklist).
- Collect learner speech with consent.
- Do anything on AWS.
