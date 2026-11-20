# Extraction 3: deploy and test Extraction; train and serve a candidate model (2026-11-20)

**Label.** Local rehearsal on synthetic and pinned public data, plus the owner-authorized
**read-only** AWS checks. No AWS write, training job, upload, deployment, DNS change, data
migration or promotion was made.

**Baseline.**
- Worktree `20261120-postmerge-flh/extraction`, confirmed by the owner. The base SHA was not
  given, and agents run no Git, so the baseline is a content manifest of 1,696 paths
  (SHA-256 `0678a2b3…`, in the sealed handoff).
- The sealed HANDOFF-2.2 is on that base: 189 of its 190 paths byte-identical, and one
  (`SPEAKING-TEST-ENTRY.md`) differs only by a trailing blank line. Extraction 2.2 and
  Speaking Lab 2 are therefore **already integrated**. They were re-tested from the new base
  (R3-002, R3-003).

**Candidate.** **French speech recognition**, not text extraction (R3-010). The objective was
written down and hashed before any candidate result existed
(`evidence/model/OBJECTIVE-preregistered.md`, SHA-256 `7f914577…`).

**Results in one place.**
- **Extraction service:** packaged (stdlib image, 119 MB, ready in 0.47 s), tested without a source
  mount, and driven by FLH's real capture API. Identical draft IDs to the library; review p50
  1.7–3.5 ms.
- **Candidate C2** (whisper-base, punctuated FLEURS, 24 CPU steps): all three pre-registered goals
  pass.
  - **G1:** 100% of outputs punctuated on MLS test and FLEURS, against 6.6% for the earlier pilot.
  - **G2:** MLS test WER +0.21 points, 95% upper bound +0.94 ≤ +1.0.
  - **G3:** RTF ≤ 0.11, peak RSS about 1.2 GB.
- **Acceptance** `flh_speaking_acceptance_v1`: **KEEP_BASELINE**. It fails A1 (no in-domain gain)
  and A6.
- **Candidate review:** `insufficient_support` (exit 4, 8 speakers: an observation).
- **Recommendation:** keep the pretrained model; nothing promoted.
- **Serving:** the candidate bundle and the rollback to the base were both served through FLH's
  Speaking API with the deployment pin enforced. AWS: read-only checks only; every write is
  prepared, not run.

## Per item

| ID | Status | Evidence (§ = this record; STAGING-PLAN = `deploy/aws/model-runtime/STAGING-PLAN.md`; handoff = `extraction3-20261120`) |
|---|---|---|
| R3-001 | verified in a rehearsal | seals reconciled (189/190 identical, 1 whitespace); **real read-only AWS**: identity, 0 jobs, 0 endpoints; IAM actions, runtime, data paths and cleanup in STAGING-PLAN §2–§3; `evidence/001-reconcile.txt`, `evidence/aws/` |
| R3-002 | verified in a rehearsal | demo3 / demo2 / demo / trial `--check` exit 0 on the new base |
| R3-003 | verified in a rehearsal | strict suite in the base image: 124 / 0 skipped; in the final image: 130 / 0 |
| R3-004 | implemented | §1 map |
| R3-005 | implemented | §1 provider modes |
| R3-006 | verified in a rehearsal | §1 inventory; every manifest hash rechecked; `fetch.check` clean |
| R3-007 | implemented | §1 dependencies |
| R3-008 | implemented | §2 |
| R3-009 | implemented | §3, `SERVICE.md`, `CONTRACT.md`; sent to the Release lane, whose findings are in STAGING-PLAN §0 (their acceptance of the sidecar is decision A11) |
| R3-010 | implemented | §4; pre-registered `evidence/model/OBJECTIVE-preregistered.md` |
| R3-011 | implemented | `flh_extraction/service.py` |
| R3-012 | implemented | `Dockerfile.service`; image `f7b28efb…` |
| R3-013 | implemented | §5: code identity in `deployment_id`; container equals host |
| R3-014 | implemented | §5 |
| R3-015 | implemented | §5 |
| R3-016 | implemented | §5; `Bounds` tests |
| R3-017 | implemented | `SERVICE.md` §2 |
| R3-018 | verified in a rehearsal | the container with no mounts: smoke 15/15, workflow passes |
| R3-019 | implemented | 409 / 400 / `deployment_mismatch`; tests |
| R3-020 | implemented | `python3 -B -m flh_extraction.service smoke` |
| R3-021 | verified in a rehearsal | §6 |
| R3-022 | verified in a rehearsal | §6 |
| R3-023 | verified in a rehearsal | §6 |
| R3-024 | verified in a rehearsal | §6 |
| R3-025 | verified in a rehearsal | §6 |
| R3-026 | verified in a rehearsal | §6 |
| R3-027 | verified in a rehearsal | §6 |
| R3-028 | verified in a rehearsal | §6 |
| R3-029 | verified in a rehearsal | §6 |
| R3-030 | implemented | `scripts/app_workflow.py --json`; privacy 0 |
| R3-031 | implemented | §7 |
| R3-032 | implemented | §1, §7 |
| R3-033 | verified in a rehearsal | §7 |
| R3-034 | implemented | `lab intake --require-speakers`; refused data-v1 |
| R3-035 | verified in a rehearsal | §7 |
| R3-036 | verified in a rehearsal | §7 overlap table |
| R3-037 | verified in a rehearsal | §7 |
| R3-038 | verified in a rehearsal | §7 |
| R3-039 | verified in a rehearsal | the strict suite's training tests |
| R3-040 | implemented | §7; `evidence/data/` |
| R3-041 | verified in a rehearsal | §8 |
| R3-042 | implemented | §8 |
| R3-043 | implemented | §8: grounding metrics for the extraction runtime; not used for training (speech) |
| R3-044 | verified in a rehearsal | §8 |
| R3-045 | verified in a rehearsal | §8 |
| R3-046 | verified in a rehearsal | §8 |
| R3-047 | verified in a rehearsal | §8 |
| R3-048 | verified in a rehearsal | §8: exit 5 |
| R3-049 | verified in a rehearsal | §8 |
| R3-050 | implemented | §8 |
| R3-051 | verified in a rehearsal | §9 |
| R3-052 | verified in a rehearsal | §9 |
| R3-053 | verified in a rehearsal | §9: byte-identical |
| R3-054 | verified in a rehearsal | §9 |
| R3-055 | implemented | §9 |
| R3-056 | owner-only | the quota query was denied for the authorized role; the owner command is recorded |
| R3-057 | implemented | STAGING-PLAN §3; rendered offline |
| R3-058 | verified in a rehearsal | the local smoke scale (24 steps); no AWS job authorized |
| R3-059 | verified in a rehearsal | §9 |
| R3-060 | implemented | §9; the bundle verifies |
| R3-061 | implemented | §10, STAGING-PLAN §1 |
| R3-062 | verified in a rehearsal | §10 |
| R3-063 | verified in a rehearsal | §10 |
| R3-064 | implemented | §10 |
| R3-065 | verified in a rehearsal | §10 |
| R3-066 | verified in a rehearsal | §10 |
| R3-067 | verified in a rehearsal | §10 |
| R3-068 | verified in a rehearsal | §10 |
| R3-069 | verified in a rehearsal | §10: rollback run |
| R3-070 | implemented | STAGING-PLAN §5; sent to Release |
| R3-071 | owner-only | account and region verified (read-only); no approved spending envelope for any write |
| R3-072 | owner-only | prepared (STAGING-PLAN §4); writes need approval |
| R3-073 | owner-only | not authorized; prepared |
| R3-074 | owner-only | staging needs approval; local: private binding and no published port verified |
| R3-075 | owner-only | staging needs approval; local: probes ran on synthetic and public inputs |
| R3-076 | owner-only | staging needs approval; local: container health and grounding passed |
| R3-077 | owner-only | staging needs approval; local: the full FLH capture and review against the container passed |
| R3-078 | owner-only | staging needs approval; local: container output equals in-process |
| R3-079 | owner-only | staging needs approval; local per-piece measurements in §6 and §10 |
| R3-080 | verified in a rehearsal | nothing created on AWS, so nothing idle; local containers stopped; teardown commands in STAGING-PLAN §7 |
| R3-081 | verified in a rehearsal | §12 |
| R3-082 | verified in a rehearsal | §12; Go public-demo tests pass |
| R3-083 | implemented | §12 |
| R3-084 | verified in a rehearsal | §12; `tests/test_runtime_ops.py` |
| R3-085 | verified in a rehearsal | §12; rollback run |
| R3-086 | implemented | `scripts/identity_diff.py`; tests; real manifests |
| R3-087 | implemented | §12 |
| R3-088 | implemented | §3 |
| R3-089 | implemented | §12 |
| R3-090 | implemented | §12 |
| R3-091 | verified in a rehearsal | §13 |
| R3-092 | implemented | handoff: extraction-service and model-artifact identities sealed separately |
| R3-093 | implemented | handoff `COMMANDS.md` |
| R3-094 | implemented | handoff `COMMANDS.md` (AWS spend $0; local times) |
| R3-095 | verified in a rehearsal | §8: same held-out sets for base and candidate |
| R3-096 | implemented | §1, §7; no private paths |
| R3-097 | implemented | `fixtures/service_v1/` (sealed) |
| R3-098 | implemented | §14 |
| R3-099 | implemented | §14 |
| R3-100 | implemented | handoff `HANDOFF-3.md`, `SHA256SUMS` |

**Totals:** 43 implemented, 47 verified in a rehearsal, 10 owner-only, 0 blocked (100).

## 1. Runtime map (R3-004–R3-007)

**Boundaries:**

```text
browser ── FLH Go server (one process, SQLite) ──┬─ analyzer: rule-based (default) | openai
                                                  ├─ extractor: disabled (default) | openai          ← no local extractor exists
                                                  ├─ speaking transcription: disabled | openai | local ── flh_speaking service (HTTP, private)
                                                  ├─ speaking feedback: disabled | openai
                                                  └─ embedding / suggestion / listening / reading / writing: disabled | provider
tools/extraction (offline, stdlib) ── NEW: flh_extraction.service (HTTP, private, rules only; FLH does not call it yet)
tools/speaking (torch, pinned lock) ── train / evaluate / serve; the service is FLH's `local` transcription provider
```

**Provider modes (R3-005)**, read from `internal/config`:
- `EXTRACTOR_PROVIDER` is `disabled` (default) or `openai`. There is no fallback: disabled
  answers 503.
- `SPEAKING_TRANSCRIPTION_PROVIDER` is `disabled`, `openai` or `local`. `local` adds
  `SPEAKING_TRANSCRIPTION_BASE_URL`, a `_TIMEOUT` of 60 s, and `_MODEL`, which must equal the
  service's `deployment_id`.
- Every provider is opt-in and independent. None retries automatically or falls back to
  another.

**Approved data and artifacts (R3-006).** Everything lives outside Git in the speaking work area;
every manifest hash was rechecked this run.

| Item | Identity | Licence | Use |
|---|---|---|---|
| `openai/whisper-tiny`, `-base`, `-small` | revisions `169d4a43`, `e37978b9`, `973afd24`; `fetch.check` reports no problem | Apache-2.0 on the HF card (OpenAI code: MIT) | base model, baselines |
| `data-v1` (MLS fr train/dev/test, FLEURS ood) | manifest `4b1c067e…`, matches its dataset manifest | CC BY 4.0 | baseline training (pilot), held-out evaluation |
| `data-punct` (FLEURS fr_fr punctuated train/dev) | manifest `920b74a0…`, matches | CC BY 4.0 | **this candidate's training data** |
| `data-accent` (SLR57) | manifest `53571726…`, matches | Apache-2.0 | accented French evaluation |
| earlier pilot (MLS, unpunctuated) | `model.safetensors` `43cf1f2c…`, step 180 | — | KEEP_BASELINE (`SPEAKING-MODEL-V1.md`); not served |
| extraction datasets | `tools/extraction/README.md` hashes | synthetic / annotated | the extraction runtime here is rules-only and loads none |

**Runtime dependencies (R3-007):**
- **Extraction service:** Python 3.12 standard library only, 15 package files.
- **Speech service:** the pinned `requirements-cpu.lock` (torch CPU, transformers, numpy, av),
  in `python:3.12-slim` pinned by digest.
- **FLH:** the Go module set (`go.sum`); it was built offline with `GOPROXY=off`.
- No runtime fetch: the speech image runs with `HF_HUB_OFFLINE=1`, and the weights are mounted
  read-only.

## 2. Deployment acceptance (R3-008), separately per endpoint

| | Extraction service | Speech model service |
|---|---|---|
| Identity | `/manifest` `deployment_id` equals the release record | `/manifest` `deployment_id` equals `SPEAKING_TRANSCRIPTION_MODEL`; FLH refuses any other |
| Ready | `/readyz` 200 after the self-check | `/readyz` 200 after load and warm-up |
| Function | `smoke --url` 15/15; app workflow passes | a real transcription through FLH's Speaking API; probes as expected |
| Bounds | 413, 503 `busy`, 504 `timeout` as documented | the existing service limits (8 MiB, 120 s, queue 2, 50 s deadline) |
| Privacy | no learner text in logs | no audio kept (container diff empty), no transcript in logs |
| Network | private only | private only |
| Quality gate | none: rules, identical to the library | the candidate review and acceptance below; **promotion is separate** |

## 3. Private runtime contract with Release (R3-009, R3-070, R3-088)

**Service contracts:**
- Extraction service: `tools/extraction/SERVICE.md`.
- Speech service: `tools/speaking/CONTRACT.md` (unchanged).

**Configuration inputs, form and teardown:** `deploy/aws/model-runtime/STAGING-PLAN.md`
(§1 deployment form, §5 configuration inputs, §7 teardown).

**Gap for Release.** `compose.yaml` forwards `SPEAKING_TRANSCRIPTION_PROVIDER` and `_MODEL`, but
not `_BASE_URL` or `_TIMEOUT`. A Compose deployment therefore cannot point FLH at a sidecar. The
two-line hunk is proposed there; this lane did not edit Release's file.

**Monitoring contract (R3-088).**

| Signal | Extraction | Speech | Alert when |
|---|---|---|---|
| Liveness | `GET /healthz` | `GET /healthz` | 3 failures in a row |
| Readiness | `GET /readyz` | `GET /readyz` | not 200 for 2 minutes after start |
| Identity | `GET /manifest` `deployment_id` | the same | differs from the release record (never auto-fix) |
| Counters | `GET /metrics`: ok, client_error, busy, timeout, internal | `GET /metrics` | `internal` > 0; `busy` or `timeout` above 5% of requests in an hour |
| Resources | `docker stats` memory | the same | above 80% of the limit |
| FLH side | — | transcription `failure_code` counts (`provider_unavailable`, `provider_timeout`) | any `provider_timeout` |

No request content, audio or transcript is a signal. Logs carry sizes, codes and durations only.

## 4. The candidate and its objective (R3-010)

**Why speech, not text extraction.**
- Speech has approved, pinned public data with transcripts, and an existing CPU training,
  evaluation and serving path into FLH (the `local` transcription provider).
- A learned text extractor would need a GPU fine-tune with no approved budget, and no learned
  extractor sits in a runtime path today. The extraction service here is rules-only.

**The observed error it answers.** The earlier pilot, trained on unpunctuated MLS text,
collapsed the output style: 6.6% of outputs punctuated vs 100% for the base (A5 failed), with no
significant WER gain. Verdict KEEP_BASELINE.

**Candidate C2.**
- whisper-base `e37978b9`, encoder-only fine-tune on **punctuated, cased** FLEURS fr_fr training
  text (data-punct), seed 20261117.
- Local scale: 24 steps (`configs/punct-base-encoder-smoke.json`). The 180-step config is the
  prepared AWS job.

**Goals** (pre-registered; unchanged after the results):
- **G1 readable output:** share of outputs with punctuation ≥ 0.8 × base, on MLS test and on
  FLEURS ood.
- **G2 non-inferior accuracy:** served-WER difference (candidate − base) on MLS test, 95% upper
  bound ≤ +1.0 point.
- **G3 runtime:** RTF ≤ 0.5 and peak RSS ≤ 2,048 MB.

`flh_speaking_acceptance_v1` (A1–A7) and the candidate review's support rule (30 speakers)
decide any recommendation. The expectation at 24 steps: no in-domain gain (A1 fails).

## 5. Extraction as a deployable service (R3-011–R3-020)

**Entry point (R3-011).** The existing offline practice pipeline is wrapped by
`flh_extraction/service.py`, with no new rules. A learned extractor was not chosen: none sits in
a runtime path, and a GPU fine-tune has no approved budget.

| Item | Result |
|---|---|
| R3-012 artifact | `tools/extraction/Dockerfile.service`: `python:3.12-slim` pinned by digest plus the 15 package files (the existing `.dockerignore` allowlist; the classic builder here has no per-Dockerfile ignore file); user 10002; healthcheck on `/readyz`. Image `flh-extraction-service:postmerge-20261120` `sha256:f7b28efb…`, 119 MB |
| R3-013 identities | `deployment_id` = the code identity (SHA-256 of the 15 files' hashes) + contract + drafter. The container's `/manifest` code hashes and `deployment_id` (`flh-extraction-rules@b0bd175f5d97/…`) equal the host's |
| R3-014 schema | envelope (`flh_extraction_request_v1`, contract field and header), each source validated by `practice.validate_source`, decisions by `read_decisions`, and every decision's item and revision checked against the request |
| R3-015 identity endpoints | `/healthz`, `/readyz` (built-in self-check: pinned draft ID and grounding), `/manifest` (no paths, no environment), `/metrics` |
| R3-016 bounds | 256 KiB, 8 revisions, 64 items, 1,000 decisions, 5,000 attempts, 5 s deadline (504), 4 in flight (503 `busy`). Tested: busy and timeout with a gated slow hook; oversized body 413 |
| R3-017 codes | 14 documented codes (`SERVICE.md` §2); a 500 never carries input text or a traceback |
| R3-018 no source mount | `docker run --read-only --memory 256m --cpus 1 --cap-drop ALL --security-opt no-new-privileges -p 127.0.0.1:PORT:8090`: no mounts (`docker inspect` lists none), ready in 0.47 s, `smoke --url` 15/15, the app workflow passes against it |
| R3-019 versions | the client sends `X-FLH-Contract`. A different contract gets 409 with the service's; a missing header gets 400; a client pinned to a deployment ID refuses a 200 from another (`deployment_mismatch`) |
| R3-020 smoke | `python3 -B -m flh_extraction.service smoke [--url URL]`: 15 checks; in-process 15/15 |

Tests: `tools/extraction/tests/test_service.py` (13 tests: library equality, source revisions kept,
cue flags, feed contract and withdrawal, import preview, envelope and media errors, counters,
log privacy, busy and timeout, not-ready, client unavailable and deployment mismatch, host
rules, manifest hashes).

## 6. Extraction as an application workflow (R3-021–R3-030)

`scripts/app_workflow.py`: the FLH server built from this base (`go build`, offline), a fresh
database, every provider disabled.

| Check | In-process service | Container (no source mount) |
|---|---|---|
| R3-021 capture → evidence: 3 synthetic captures stored (201) and read back; the service grounds FLH's **stored** text | draft IDs equal the library's for all 3 | the same |
| Groundings | y/en 6 located, 1 not found; savoir/connaître 6 / 1; à/en 10 located | the same |
| R3-023 unsupported claim with an exact quote | à/en: 2 items flagged by word cues, none batched (batch 5) | the same |
| R3-028 provider failure keeps learner input | `POST /entries/{id}/extractions` with the extractor disabled → 503; entry byte-identical afterwards | the same |
| R3-027 unavailable upstream | service stopped: one call, `unavailable` in 0.9 ms, **0 automatic retries**; FLH stays ready and the entry readable; an explicit retry after restart → 200 | — |
| R3-029 latency (30 reviews per case) | p50 1.7 / 1.8 / 2.4 ms, p95 1.8 / 2.2 / 2.5 ms | p50 2.3 / 2.4 / 3.5 ms, p95 2.8 / 2.6 / 3.9 ms; memory 15 MiB of 256 |
| R3-030 redacted report | IDs, counts, codes and timings only; privacy findings 0; no learner text | the same |

- **R3-022 source revisions retained.** Every approved item keeps `decided_on_revision` and
  `carried_from_revision`, and every evidence entry keeps its `source_revision`
  (`test_review_equals_the_library_and_keeps_source_revisions`).
- **R3-024 withheld or revised sources.** A revision whose quotes disappear withdraws every
  dependent exercise from the feed (`test_feed_contract_and_withdrawal_after_a_revision`). Items
  restored after a change need confirmation.
- **R3-025 Workbooks feed contract.** Service feeds pass the contract check and the increment-4
  consumer rules. The all-withdrawn feed is still refused by that consumer, as recorded in 2.2.
- **R3-026 packet and agent return.** `/v1/import-preview` classifies the Codex fixture against
  its v3 packet (3 candidates) and a v2 return (1 duplicate). Packet export is `practice2 export`
  (demo3, unchanged).
- **Fault found and fixed while running.** The first workflow run stopped on its own report code:
  FLH's error body is `{"error": "<message>"}`, a string. Fixed; both runs pass.

## 7. Training data (R3-031–R3-040)

**Schema (R3-031).**
- Input: mono 16 kHz float audio decoded by one convention (`pcm_f32le/16000Hz/mono/ffmpeg-swr-v1`),
  keyed by `pcm_sha256`.
- Target: the reference text as published (punctuated and cased for FLEURS, lower-case for MLS).
- Grouping keys: `speaker` (MLS, SLR57) or the FLEURS sentence; `split`; quality (SNR, clipping).

**Datasets (R3-032).** Above (§1), with their licences and pinned revisions. No learner audio.

**Speaker IDs (R3-033).**
- MLS publishes per-utterance speaker IDs: 24 train, 4 dev, 8 test speakers, disjoint.
- SLR57 publishes them too: 12 speakers.
- **FLEURS publishes none.** The 1,440 training and 289 ood rows have no speaker, so FLEURS
  supports only sentence-group claims.

**Unlabeled rows (R3-034).** `lab intake --data-manifest M --require-speakers` refuses a
speaker-group claim over rows without a speaker ID. It refused data-v1 (289 FLEURS rows), as
intended.

**Splits (R3-035).**
- data-v1's speaker-disjoint MLS splits and data-punct's sentence-disjoint FLEURS splits are
  fixed by their manifests (hashes above, rechecked).
- The candidate trains on data-punct `train`, monitors data-punct `dev`, and is evaluated on
  data-v1 `test` and `ood` and on data-accent.

**Overlap (R3-036).** `lab intake --overlap` compared data-punct train with every evaluation set:

| Set | Rows | Shared speakers | Shared normalised texts | Shared audio |
|---|---|---|---|---|
| MLS test | 240 | 0 | 0 | 0 |
| FLEURS ood | 289 | **unknown** (no IDs on either side) | 0 | 0 |
| MLS dev | 100 | 0 | 0 | 0 |
| SLR57 accent | 515 | 0 | 0 | 0 |
| data-punct dev | 100 | unknown | 0 | 0 |

MLS test is the clean held-out set. FLEURS ood is the same corpus as training: sentence-disjoint,
speaker overlap unknown. It is reported, and flagged wherever it appears.

**Manifest (R3-037).** Training reads data-punct by its manifest hash (`920b74a0…`); each
checkpoint's `run_manifest.json` records the config, data manifest and base model hashes.

**Balance (R3-038).**
- data-punct train: 1,440 rows, 4.65 h, gender F 1,030 / M 410 (**imbalanced**), 0 missing text,
  1,440 missing speaker IDs.
- data-v1 test: 240 rows, 8 speakers, F 120 / M 120, 1.01 h.
- No missing reference text anywhere.

**Synthetic smoke (R3-039).** The training tests use a tiny random Whisper. They ran in the strict
suite (`test_train.Training`, 5 tests).

**Sealing (R3-040).** The datasets stay in controlled storage outside Git, referenced by their
manifest hashes. The hashes and the balance and overlap reports are sealed in the handoff
(`evidence/data/`). The audio is never copied into the repository.

## 8. Evaluation and promotion rules (R3-041–R3-050)

| Item | Result |
|---|---|
| R3-041 baseline | The packaged base-vs-small reproduction on the new base image: texts 5/5 for both models, the paired comparison equals the first run's, review `insufficient_support` exit 4, same bytes as the tree's code. Base WER on MLS test re-measured at 27.115%, equal to SPEAKING-MODEL-V1 |
| R3-042 normalisation | `flh_fr_asr_norm_v1` (NFKC, lower case, apostrophe and quote variants, œ/æ, punctuation and hyphens removed; accents and elision kept; digits not spelled out). WER and CER are scored on the served text after the abstention rules |
| R3-043 grounding metrics | the candidate is speech, so they are not used for training. For the extraction runtime: per case, located / ambiguous / not found quotes, cue flags, batch size, items left to the learner (§6) |
| R3-044 runtime and failures | below; served status 0 abstentions on all French sets for both models; probes as expected (A4) |
| R3-045 paired | same items, decoding policy and batch size; paired cluster bootstrap per speaker (sentence groups for FLEURS) |
| R3-046 qualifications | intervals and support kept in every report; 8 test speakers → observation |
| R3-047 thresholds | the candidate-review thresholds and `flh_speaking_acceptance_v1`: they report and never promote (`promotion.performed: false`) |
| R3-048 mismatched splits | base `test` against candidate `ood` → `mismatched_inputs`, exit 5 (`evidence/model/048-mismatched.txt`) |
| R3-049 difficult French | SLR57 accented French (12 speakers, 515 utterances) and the probes (silence, hum, tones, noise, other languages) |
| R3-050 rubric and fixtures | the pre-registered objective (`7f914577…`), `flh_speaking_candidate_review_v1` thresholds and `flh_speaking_acceptance_v1`; inputs by SHA-256 in the review text |

| Held-out set (never trained on) | Utterances / groups | WER base → candidate (Δ) | Punctuated outputs | RTF base / candidate | Peak RSS (MB) |
|---|---|---|---|---|---|
| MLS test | 240 / 8 speakers | 27.115% → 27.324% (+0.21; paired 95% −0.58 to +0.94) | 100% / 100% | 0.081 / 0.080 | 1,224 / 1,223 |
| FLEURS ood (same corpus as training; speaker overlap unknown) | 289 / 137 sentence groups | 27.52% → 26.94% (−0.58; −1.56 to +0.46) | 100% / 100% | 0.110 / 0.110 | 1,248 / 1,202 |
| SLR57 accented | 515 / 12 speakers | 37.69% → 36.48% (−1.21) | 95.0% / 97.7% | 0.383 / 0.269 | 1,225 / 1,218 |

**Acceptance** `flh_speaking_acceptance_v1`: **KEEP_BASELINE**.

| Criterion | Result | Measured |
|---|---|---|
| A1 in-domain gain | **fail** | +0.21, CI −0.59 to +0.92 |
| A2 no ood loss | pass | upper bound +0.46 ≤ +1 |
| A3 no speaker loss | pass | worst +1.85, speaker 5207 |
| A4 abstention | pass | none lost, none added |
| A5 readable output | pass | 100% punctuated, vs the pilot's 6.6% |
| A6 not leakage | **fail** | the test change is not negative |
| A7 runtime | pass | RTF 0.080 |

**Pre-registered goals:** G1 pass, G2 pass, G3 pass
(`evidence/model/objective-check.json`).

**Candidate review** (MLS test): `insufficient_support`, exit 4. 8 of the required 30 speakers;
standing: observation.

## 9. Training (R3-051–R3-060)

| Item | Result |
|---|---|
| R3-051 script | `flh_speaking train` (existing): pinned config, data manifest and base model; a fixed seed and a known sample per step; resumable |
| R3-052 smoke | `configs/punct-base-encoder-smoke.json`: 24 steps on 4 CPU cores in the image (no network, 2 GiB), one loss line per step; the loss check before training is exact (library 0.513549 = manual 0.513549) |
| R3-053 resume | run A stopped after step 12 (`--max-steps-this-run 12`) and resumed; run B uninterrupted. **Final weights byte-identical** (`model.safetensors` `7e6ac180…`), same step losses |
| R3-054 comparable steps | dev loss (FLEURS punctuated dev) 0.750105 at step 12 and 0.743972 at step 24, identical in both runs |
| R3-055 runtime and cost | run A 7 m 18 s + 7 m 38 s, run B 20 m 29 s (28–59 s per step on a shared 8-core host, load about 8–11); CPU, fp32, about 1.5 GB; $0 |
| R3-056 quota | denied for the read-only role; owner command in `evidence/aws/README.md` |
| R3-057 AWS config | `deploy/aws/model-runtime/STAGING-PLAN.md` §3: 180 steps, `ml.g5.xlarge` Spot, 1 h cap, ≤ $1.41; rendered offline |
| R3-058 capped run | the local smoke scale (above); no AWS job (not authorized) |
| R3-059 stop rule | stops at `max_steps` (24) and at `--max-steps-this-run`; on AWS also `MaxRuntimeInSeconds` 3600 and `MaxWaitTimeInSeconds` 7200 |
| R3-060 export | `scripts/export_candidate.py`: 13 inference files, `trainer_state.pt` excluded, `candidate_manifest.json` (status `candidate`, promotion not performed), model card, `SHA256SUMS`; `--verify` passes |

## 10. Serving (R3-061–R3-070)

| Item | Result |
|---|---|
| R3-061 form | the sidecar container on the private host (STAGING-PLAN §1); no SageMaker endpoint |
| R3-062 local image and bundle | `flh-speaking:cpu-final-20261120` (`sha256:777be836…`; its 24 package files equal the tree's) with the base weights pinned by revision and the candidate bundle pinned by hash, both mounted read-only |
| R3-063 loads from the artifact | the service serves the exported bundle (not the checkpoint): ready, and FLH stores transcripts under `local:whisper-base-ft@step24-7e6ac1809b01/…/e112ed7849fd77fe` |
| R3-064 responses | `/healthz`, `/readyz`, `/manifest`, `/metrics` and the transcription route only (`CONTRACT.md`) |
| R3-065 identity mismatch | a service started with the other weights: FLH refuses its answers (`provider_unavailable`, 502); nothing is stored as text |
| R3-066 missing artifact and timeout | missing model directory: listening, `/readyz` 503 `failed` (`FileNotFoundError`), no deployment ID. A 1 s service deadline on a long clip: `provider_unavailable`, recovered with the default deadline. FLH's own timeout shorter than inference: `provider_timeout`, unknown, and the acknowledged retry completes |
| R3-067 cold and warm | ready 4.4–4.5 s after start (503 loading, then warming, then 200); a short clip 1.1 s; a long clip 4.4 s |
| R3-068 concurrency | a second click on another take while one runs: 409 `request_in_progress`; the same key replays; the service saw one request |
| R3-069 rollback | the verifier run with the **base** configured (the rollback target) passes the same scenarios, and the candidate is then refused as other weights. FLH only switches by changing `SPEAKING_TRANSCRIPTION_MODEL` |
| R3-070 configuration for Release | STAGING-PLAN §0 and §5, sent to the Release lane; their findings recorded (the wrapper refuses `local`; staging IAM allows t3.small only) |

**Leftovers.** The verifier's cleanup found no audio fragments in the database, no transcript words
in FLH's or the service's logs, and no authorization header in the logs.

**Finding.** The deployment ID computed on the raw checkpoint (`…239825c3…`) differs from the one
served from the exported bundle (`…e112ed78…`). The bundle's own `candidate_manifest.json` is one
of the identity's files. Use the bundle's served ID (`GET /manifest`). FLH's pin fails closed
either way.

## 11. AWS staging (R3-071–R3-080)

| Item | What happened |
|---|---|
| R3-071 | **real AWS, read-only:** caller identity verified (account masked), region us-east-1, profile `flh-staging-extraction`. No spending envelope is approved for any write. The envelope proposed: training ≤ $1.41 per run plus about $0.80/month storage; staging sidecars about +$0.02/h on the host |
| R3-072–R3-077 | prepared commands only (`deploy/aws/model-runtime/STAGING-PLAN.md` §4–§6). Their local equivalents ran: the container smoke, the app workflow against the container, and the model service through FLH |
| R3-078 | local: the container's output equals the in-process service's (same draft IDs and deployment ID); staged outputs need staging |
| R3-079 | local per-piece time, memory and failures (§5, §10); staging needs staging |
| R3-080 | nothing was created, so nothing is idle. The teardown commands are in the plan (§7). Local containers stopped (`docker ps` evidence) |

## 12. Data and operational gaps (R3-081–R3-090)

| Item | Result |
|---|---|
| R3-081 logs | 69 run logs scanned with the packet privacy patterns: no credential, e-mail or session link, and no learner text (the verifier also checked transcript words and audio). The only finding: FLH's own startup line names its scratch database path (10 local server logs, outside Git) |
| R3-082 public demo | The demo boundary (`internal/transport/http/public_demo.go`) allows only GET/HEAD on health, readiness and the knowledge-library routes. No capture, speaking or extraction route is reachable, and the demo never opens `DB_PATH`. Neither runtime service is part of a demo artifact. Go tests: see §13 |
| R3-083 retention | Approved model artifacts stay outside Git, by identity: the pinned base revisions; the candidate bundle (`SHA256SUMS`, `candidate_manifest.json`, model card), kept until the owner decides, and deleted then. Keep the current and the previous deployed tag only (`RUNBOOK.md` §9). Nothing derived from learner data exists: no learner audio or transcript was used |
| R3-084 downloads | `fetch` writes `*.part`, checks size and SHA-256 (SHA-1 git blob for small files), then renames. Tested against a local server: a dropped connection and a corrupted body each raise and leave **no file**; after damage on disk `verify` reports it and a re-fetch repairs it (`tests/test_runtime_ops.py`). The candidate bundle has its own seal (`export_candidate.py --verify`; one appended byte is detected) |
| R3-085 failed model update | `tools/speaking/RUNBOOK.md` §6–§7: start the new deployment beside the old one, switch FLH's model ID, stop the old one; rollback is the reverse. Rehearsed below (§10, the rollback run) |
| R3-086 model vs prompt change | `scripts/identity_diff.py` compares two deployment manifests and FLH's prompt files: weights, decoding policy, audio convention, code and runtime are told apart from feedback prompts (tests: model, prompt, mixed and no change). On the real manifests: base vs candidate → `model change` (weights and model kind only; decoding, audio, code and runtime equal) |
| R3-087 coverage | Covered: MLS read speech (8 speakers), FLEURS read speech (no speaker IDs), SLR57 accented read speech (12 speakers), probes (silence, noise, other languages). **Not covered:** learners' own spontaneous speech, children, telephone audio, more than 12 accented speakers. **Native-speaker review needed:** the probe and practice French of the extraction fixtures (Extraction 2.2, F2), and any transcript the learner corrects, before it becomes evidence of a model error |
| R3-088 monitoring | §3 |
| R3-089 AWS vs local | §11 and the table below |
| R3-090 next experiment | Justified by what was observed: the punctuated objective works (style kept), but 24 steps give no in-domain gain. The next step is the prepared 180-step run (AWS, owner approval) **only together with** more test speakers (the 30-speaker gap). Without them, any WER change below about 1.5 points stays unresolvable. Not justified: training on MLS text again, or a larger model before the support exists |

| Evidence | Real AWS | Local rehearsal |
|---|---|---|
| Caller identity, training jobs, endpoints | yes (read-only) | — |
| Quotas | denied (owner command recorded) | — |
| Training | no | yes: 2 × 24-step CPU runs |
| Model and extraction services | no | yes: containers on loopback, FLH through its API |
| Staging deploy, upload, teardown | no (prepared) | the containers were started and stopped |

## 13. Validation

| Suite (final packaged source) | Command | Result |
|---|---|---|
| Extraction | `cd tools/extraction && python3 -B -X dev -W error::ResourceWarning -m unittest discover -s tests -t tests` | 200 run, OK: 7 optional skips, 1 expected failure (FLH-154 F1); 185 before + 15 in `tests/test_service.py` |
| Speaking strict, final image (its own package; tests and data mounted read-only; no network) | the `tools/speaking/README.md` command | 130 run, 0 skipped, 0 errors, 0 ResourceWarnings; image and tree: 24 equal files |
| Speaking host | `cd tools/speaking && python3 -B -X dev scripts/run_tests.py` | 130 run, 28 skipped (missing dependencies), 0 errors |
| Go | `go test -count=1 -run 'PublicDemo\|Speaking' ./internal/transport/http/ ./internal/config/ ./internal/speaking/` | ok |
| Demos | `practice2 demo3 --check`, `practice demo2 --check`, `practice demo --check`, `practice2 trial --check` | exit 0 each |
| Service | `flh_extraction.service smoke`; `scripts/service_examples.py --check` | 15/15; equal |
| Workflow | `scripts/app_workflow.py` in-process and against the container | every check passes |
| Model queue | training A and B, 6 evaluations, probes, acceptance, review, bundle, two serving runs | rc 0 each (`evidence/queues/`) |

## 14. Owner decisions

**Model recommendation vs real promotion (R3-098).** These are two separate things.
- **Recommendation (this lane):** **keep the pretrained model** (KEEP_BASELINE). C2 solves the pilot's style failure (G1–G3 pass) but shows no in-domain gain, and it rests on 8 test speakers.
- **Real promotion (owner only):** none was made. `SPEAKING_TRANSCRIPTION_MODEL`, the RUNBOOK
  and every serving default are unchanged. Every review records `promotion.performed: false`.

**Owner decisions.**
1. **Base SHA.** Record the base SHA of `20261120-postmerge-flh/extraction` beside the content
   manifest (`0678a2b3…`).
2. **AWS:**
   - approve one capped training run of the 180-step punctuated config (≤ $1.41 compute plus
     about $0.80/month storage until cleanup), or not;
   - add `servicequotas:ListServiceQuotas`/`GetServiceQuota` to the read-only role, or run the
     quota command yourself;
   - approve staging sidecars on a t3.medium (about +$0.02/h), or keep the speech provider off
     in staging.
3. **Release.**
   - The two-line `compose.yaml` hunk (`SPEAKING_TRANSCRIPTION_BASE_URL`, `_TIMEOUT`).
   - Whether staging carries the sidecars at all.
4. **Wiring the extraction service into FLH.** A new extractor provider or a practice API is a
   shared-contract change. It needs a design decision and the Release lane.
5. **Images.**
   - New, kept for the handoff: `flh-speaking:cpu-postmerge-20261120`,
     `flh-speaking:cpu-final-20261120` and `flh-extraction-service:postmerge-20261120`.
   - Older images to keep or remove: `cpu-x22-20261119`, `cpu-lab2-20261119`,
     `cpu-lab20261119`, `cpu-test20261119`.
6. **French.** A native-speaker review of the synthetic French (Extraction 2.2 F2) and of the
   probe set.
7. **Evaluation data.** The 30-speaker gap (Speaking Lab 2) still decides every comparison's
   standing.

**Preventable deployment failures seen, and their remedies (R3-099).**

| Failure | Cause | Remedy (in place) |
|---|---|---|
| Strict suite errors on the packaged image (2.2: 7, then 5) | the mount left out fixtures, the contract, the locks and the Dockerfile that the tests read | mount every non-package file read-only; the command is in `tools/speaking/README.md` |
| `python3 -I -m flh_speaking` fails outside the package directory | `-I` ignores `PYTHONPATH` and the working directory | set `PYTHONPATH` without `-I`, or run from `tools/speaking` |
| A later CPU queue could take the lock before an earlier one | `flock` does not wake waiters in order | an explicit done-marker wait before taking the lock |
| A per-Dockerfile ignore file is silently unused | this host's `docker build` is the classic builder (no buildx) | the image needs only allowlisted files; the self-check source is built in |
| FLH in Compose cannot reach a speech sidecar | `compose.yaml` does not forward `_BASE_URL` and `_TIMEOUT` | the hunk proposed to Release |
| No quota visibility | the read-only role lacks `servicequotas:*` | the owner command recorded; add the permission |
| A resource gate flips between runs | the real-time factor is measured on a shared, loaded host (small: 0.448 → 0.607 → 0.585 on the same five clips) | measure on an idle host, or take the median of repeats; never gate on one timing run |
| No base SHA in the handoff | agents may not read Git state | the owner records it; a content manifest stands in |
