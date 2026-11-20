# Extraction R4: grounded extraction → learning loop, agent exchange, bounded Speaking experiment

Date 2026-11-20.

**Lane.** Worktree `worker/20261120-r4/extraction` on the owner-confirmed merged base
`58c0ba8bb36777ccd445c0f95be09e752a6459ab`.

**Owned files.**
- `tools/extraction`, `tools/speaking`;
- the private model-runtime handoff (`deploy/aws/model-runtime/`);
- this record.

**Operations.**
- **AWS:** none. R4 carries no AWS authorization; every cloud action below is the owner's.
- **Git:** none.
- **Data:** synthetic, plus public licensed metadata.
- **Coordination:** Workbooks and Release lanes by cross-session messages (§6).

Evidence paths written `evidence/…` are in the local R4 handoff, outside Git. Its manifest is
sealed, and the base manifest lists 1,762 paths.

## 1. Results

- **Corpus and baseline.** A 12-request synthetic corpus covers evidence, pending review,
  revision, withdrawal and restoration. Its untouched baseline (`fixtures/r4_v1/baseline`) was
  frozen before any change.
- **Service defect found by the corpus.** After a feed that withdrew every item, the next
  `/v1/feed` refused the learner's earlier attempts (422), although the CLI built the same feed.
  - **Fixed:** attempts may name practice IDs withdrawn by `previous`.
  - **Identity:** the deployment ID moved from `b0bd175f5d97` to `e978b6c2bdb6`; Release adopted
    the new pin.
  - **Baseline comparison:** it lists exactly that change (scenarios 10 and 12, and the
    identity).
- **Private runtime.** It was built from a clean tree: cached image `f7b28efb…`, equal to R3's;
  uncached `e8ec777b…`; R4 image `b00773bf…`. Rehearsed on loopback:
  - identity, and the smoke 15/15 from a separate client;
  - 409/400 contract errors;
  - 413 at 256 KiB + 2 B, and 504 under a 1 ms deadline;
  - JSON-only logs without learner text;
  - restart without state: no mount and an empty `docker diff`;
  - FLH ready while the service is down, with a 5-step recovery;
  - teardown with no container left.

  Container peak memory: 24.3 MiB.
- **French grounding.** Four deterministic systems ran on 18 annotated cases. The annotations
  were frozen by hash before any candidate existed.
  - The shipped rules get 11/18. They support 3 contradicted claims (negation, substitution) and
    2 unrelated quotes, and miss 2 spelling variants.
  - Case- and accent-folding alone gets 9/18 and accepts contradictions silently.
  - The proposed checks (`negated_quote`, `spelling_variant`) get 15/18 and only ever add a
    review. They are not wired in.
  - Unrelated evidence that shares words (n6, p3, p5) still needs a human.
- **Revision and provenance.**
  - Every corpus request replays byte-identically over HTTP.
  - A learner edit keeps source, item and evidence identity.
  - Withdrawn items return with their outcome history.
  - The learner's CLI session produces feeds byte-identical to the service (4/4).
  - The reference consumer converges when it misses a feed, sees a replay or receives a stale
    feed.
- **Learning loop** (`flh_learning_loop_v1`, `tools/extraction/LOOP.md`):
  - read, recall, reveal, retry and learner-started revisit;
  - a pointer back to the reviewed units and the learner's own words, verified by slicing the
    source revision;
  - answer retention `keep` | `discard`, with a later opt-out that removes kept answers.
- **Agent exchange** (`flh_agent_context_v1` / `flh_agent_corrections_v1`):
  - the packet is exercise-scoped;
  - the Markdown is byte-identical for Claude Code and Codex apart from the first line;
  - an import classifies and never applies;
  - outdated and malformed documents get recovery commands.

  A round trip with two scripted local stand-ins keeps the same provenance fields.
- **Research and experiment.** Three primary sources led to two hypotheses, and one offline
  experiment was pre-registered and run once:
  - no prompt leaks its answer (M1 = 0);
  - the loop's read-before-recall shows the full reference for all 4 explain items (M2 = 0.20);
  - the registered rule therefore selected **branch A, attempt first**, which is implemented.
- **Feed interoperability.** All feed samples parse with the merged Workbooks parser, run in a
  scratch copy of base `58c0ba8b`; the mirror agrees, and the replay cases are equal in
  TypeScript and Python.
  - **Reason codes:** an open-set rule for `reason_code` is recorded.
  - **New examples:** `service_v1` 08/09, requested by Workbooks; with `workbooks2` feed 3, real
    producer output covers all five codes.
- **Speaking.**
  - **Training intake:** licence, consent, speaker groups, locales and leakage, with actionable
    refusals and counts only.
  - **Pre-registered pilot:** 180 steps against the unchanged base; its declared outcome is an
    observation, because 20 speaker groups is less than 30.
  - **Bounded owner-run job:** rendered offline with no credentials.
  - **Cancellation:** SIGTERM finishes the step, saves, and the resume is identical; tested in
    the CPU image.
  - **Inference dry-run:** the base model transcribes a French test clip; silence and tone
    abstain; an empty file gets 422; an unpinned model name gets 400.
  - **Recommendation:** keep the baseline.

## 2. Per item

**Statuses.**
- **done:** implemented and checked locally.
- **prototype:** implemented and checked, but not wired into the product path.
- **owner-only:** not done.

| ID | Status | Evidence |
|---|---|---|
| R4-EXT-001 | done | `evidence/001-005/001-route-inventory.md`: 7 routes. HTTP consumers are scripts and tests; Workbooks reads feed documents; no Go consumer |
| 002 | done | `evidence/001-005/002-service-manifest.json` (`b0bd175f5d97`), examples `SHA256SUMS` `ecd9ed44…`, `--check` equal |
| 003 | done | `evidence/001-005/003-python-suites.*`: 6 suites pass; skips: extraction 7 (TINY_SFT/torch), speaking 28 (numpy/av/torch) |
| 004 | done | `tools/extraction/fixtures/r4_v1/corpus` (12 requests) and `flh_extraction/r4corpus.py` |
| 005 | done | `fixtures/r4_v1/baseline` (frozen; `--freeze-baseline` refuses to rewrite), `scripts/r4_corpus.py --compare` |
| 006 | done | `evidence/006-015/rehearsal-base.json`, `006-nocache-build.txt`: both builds give deployment `b0bd175f5d97` |
| 007 | done | the same: ready 0.31 s, manifest equals the host, smoke 15/15 |
| 008 | done | v0 client 409 `contract_mismatch` with `service_contract`; no header 400 |
| 009 | done | 262,146 B → 413; largest legal 254,156 B → 200 in ≈ 160 ms; `--timeout 0.001` → 504, ready after |
| 010 | done | 28 log lines: JSON with documented keys, no synthetic learner marker |
| 011 | done | `deploy/aws/model-runtime/EXTRACTION-SERVICE-RUNTIME.md` §2 (no env, no secret; FLH-side settings a proposal) |
| 012 | done | the same §3: flags and ceilings (256 MiB, 1 CPU, 64 pids, read-only, no caps) with measured peaks |
| 013 | done | restart: same identity, counters reset, same `feed_id`, no mount, empty `docker diff` |
| 014 | done | outage: call → status 0 `unavailable`, no retry; FLH `/readyz` 200; recovery sequence verified |
| 015 | done | `EXTRACTION-SERVICE-RUNTIME.md` §6; the rehearsal leaves no container |
| 016 | done | `fixtures/r4_v1/quality/q_*.json`: 18 items (paraphrase, negation, accent/case, lexical overlap, controls) |
| 017 | done | `fixtures/r4_v1/quality/REPORT.md`, exact_v1 column, classified |
| 018 | done | `annotations.json` (location × relation; contradicts ≠ unrelated), hash `448426d8…` frozen before the candidate |
| 019 | done | `REPORT.md`: exact_v1 11/18, folded_v1 9/18, lexical_v1 6/17; 7 error categories |
| 020 | prototype | `flh_extraction/grounding_quality.py` checks v2: 15/18, review-only, window sensitivity reported; baseline unchanged |
| 021 | done | `fixtures/r4_v1/lifecycle/report.json` `replay`: 12 requests twice, byte-identical; stable IDs listed |
| 022 | done | `correction`: pending → corrected, IDs kept, decision based on the proposed item hash |
| 023 | done | `restore`: 5 withdrawn, 5 restored, 3 outcomes kept, `since_revision` kept |
| 024 | done | `cli_http`: 4/4 feeds byte-identical (CLI `practice2` vs HTTP), draft and plan equal |
| 025 | done | `fixtures/r4_v1/lifecycle/` (4 feeds + `replay-cases.json`); run by Workbooks' `applyFeed` |
| 026 | done | `tools/extraction/LOOP.md` §1 |
| 027 | done | `loop.pointer` / `resolve`; `fixtures/r4_v1/loop/checks.json` (evidence verified at read, reveal, revisit) |
| 028 | done | `loop-discard.json`, `loop-opt-out-later.json`; `validate` refuses a kept answer under `discard` |
| 029 | done | `scripts/r4_loop.py`: attempt first → revisit r2 (withdrawn, original evidence verified) → revisit r3 (current, moved) |
| 030 | done | `LOOP.md` limits + fixtures, sent to Workbooks (accepted on read; `session` = their UUID) |
| 031 | done | `flh_extraction/exchange.py` `export` (no answer, verified evidence, privacy gate) |
| 032 | done | `fixtures/r4_v1/exchange/context.{claude-code,codex}.md` (identical bodies) |
| 033 | done | `import_preview` classes; `applied: false`; `accept` → edit decision with `via` |
| 034 | done | 5 refusals with recovery commands; CLI exit 2 (`evidence/031-035/cli-session.txt`) |
| 035 | done | `scripts/r4_exchange.py`: two stand-ins, the same provenance fields, outdated against r2 |
| 036 | done | §5 and `evidence/036-040/research.md` |
| 037 | done | §5 table (population, task, limit) |
| 038 | done | H1 answer exposure before retrieval; H2 prompt before reveal (needs learners, not run) |
| 039 | done | `tools/extraction/experiments/r4-retrieval-leakage.prereg.json` frozen 13:30:57 (SHA-256 `90955c73…`) |
| 040 | done | `r4-retrieval-leakage.result.json`: M1 0, M2 0.20 → branch A (attempt first) in `loop.py` |
| 041 | done | `evidence/066-070/workbooks-parser-results.json`: merged TypeScript `parseFeed` / `applyFeed` over all 24 samples; the mirror agrees 24/24 |
| 042 | done | empty feeds with withdrawals (lifecycle 2, 3; corpus 08, 10; `service_v1` 09) parse and apply |
| 043 | done | `flh_extraction/feed_interop.py` `REASON_RULE`; an unknown code is kept verbatim, a missing one becomes `unspecified` (TypeScript and Python) |
| 044 | done | replay cases in order, missed, replay-and-stale, late (stale): equal in TypeScript and Python |
| 045 | done | `fixtures/service_v1/08-09`, `fixtures/r4_v1/lifecycle`, omissions in `feed_interop.OMISSIONS` |
| 046 | done | `tools/speaking/flh_speaking/intake.py` `training_intake`; `fixtures/intake_r4/` |
| 047 | done | speaker groups `source:speaker`, locales, varieties per split |
| 048 | done | leakage on the fixture: speaker 1 and audio 1 found in the refused manifest; rows without speaker ID counted, never assumed disjoint |
| 049 | done | 13 actionable refusals (repeated ID or audio, missing or undeclared metadata, licence, synthetic terms) |
| 050 | done | clips, distinct speakers, hours per split; no transcript (asserted) |
| 051 | done | `deploy/aws/model-runtime/SPEAKING-PILOT-R4.md` §1 |
| 052 | done | `tools/speaking/aws/r4-pilot.prereg.json` (SHA-256 `77a63007…`, frozen 13:44:26) |
| 053 | done | `tools/speaking/aws/pilot_r4.py render` → `deploy/aws/model-runtime/speaking-r4/flh-speaking-r4pilot-20261120-000000.json` |
| 054 | done | §3; `tests/test_train.py` SIGTERM test (CPU image) |
| 055 | done | offline render, placeholder values, refusals (`tests/test_aws_render.py` `PilotR4`) |
| 056 | done | `evidence/051-060/056-bundle-verify.txt` (seal verified; model identity changed; pin enforced) |
| 057 | done | `evidence/051-060/057-058-dryrun.json` (MLS clip transcribed; host gaps numpy, av, torch, transformers) |
| 058 | done | silence and tone `no_speech`, empty 422, low support exit 4 (`058-candidate-review-demo.txt`) |
| 059 | done | `evidence/051-060/059-per-slice.md` and §4 |
| 060 | done | `SPEAKING-PILOT-R4.md` §9 |
| 061 | done | `SPEAKING-PILOT-R4.md` §4 (dated envelopes; prices to verify) |
| 062 | done | §5 offline checklist (quota values unknown: owner query) |
| 063 | done | §6 commands with a parameter contract and no credentials; **running them is owner-only** |
| 064 | done | `tools/speaking/aws/r4-teardown-plan.json` + `pilot_r4.py teardown-check` (6 refused orders tested) |
| 065 | done | `SPEAKING-PILOT-R4.md` §8 |
| 066 | done | `evidence/066-067/bench-{host,container}.json` |
| 067 | done | cold (5 starts) and warm (200 passes × 6 kinds) apart; CPU, cores, kernel and load recorded |
| 068 | done | `tests/test_service.py` `test_concurrent_requests_at_the_worker_limit` (barrier proves 4 in flight; the 5th is busy) |
| 069 | done | every fixture directory regenerates byte-identically (`tests/test_r4.py` `Fixtures`); render file name fixed by `--now`; bench and rehearsal reports carry timings by design |
| 070 | done | §3 |
| 071 | done | `python3 -I -B scripts/r4_smoke.py --expect` (14 checks; `fixtures/r4_v1/SMOKE.expected.txt`) |
| 072 | done | `fixtures/service_v1/01–09` sealed; `SERVICE.md` §7a stable vs experimental |
| 073 | done | §6 |
| 074 | done | §7 |
| 075 | done | the R4 handoff (`SHA256SUMS`, read-only); §8 |

**Owner-only actions, not done:**
- every AWS read or write;
- the pilot job;
- image push;
- quota queries;
- staging deployment;
- enabling FLH → extraction service;
- accepting `restart: unless-stopped`;
- choosing an extra evaluation source;
- any promotion;
- Git.

## 3. Tests and checks run

Commands run from the tree: the suites, the runtime rehearsal, the strict Speaking run and the
Go checks.

| Command | Result |
|---|---|
| `python3 -B scripts/ci/python_suites.py --hermetic` (the CI `python-tools` job, host Python 3.14) | 6 suites pass: extraction 223 (7 optional skips, 1 known expected failure), speaking 138 (29 skipped: numpy/av/torch absent), release 126, private-staging 76, ci-runner 18, workbooks 35; trapped AWS/Terraform/Docker calls 0 |
| strict Speaking suite in `flh-speaking:cpu-final-20261120`, tree package read-only (`run_tests.py --require-deps --expect-offline`) | 138 run, 0 skipped, 0 failures (torch 2.15.0+cpu, transformers 5.21.1, numpy 2.5.4, av 19.0.2); includes the SIGTERM, training-intake and pilot tests |
| `python3 -B -X dev -W error::ResourceWarning -m unittest discover -s tests -t tests` (extraction) | 223 run, OK (7 optional skips, 1 known expected failure), no ResourceWarning |
| `scripts/runtime_rehearsal.py` on the R4 image with the FLH server | PASS: image `b00773bf…`, deployment `e978b6c2bdb6` equal to the host; contract, limits (largest legal 208 ms), logs, restart, outage and teardown ok; no container left |
| merged Workbooks parser and client (vitest, scratch copy of `web/` at the base, never in a worktree) + `feed_interop` | 24/24 samples agree with the merged-parser mirror; 4/4 replay cases equal; unknown code kept, missing code `unspecified` |
| `scripts/r4_smoke.py --expect` | 14/14 PASS; output equal to `SMOKE.expected.txt` |
| sealed 2.2 demos (`practice2 demo3`, `practice demo2`, `practice demo` with `--check`) | all three: every output equals the shipped expected files (2.2: 23 files + the 14-file `workbooks2` bundle) |
| `gofmt -l .`, `go vet ./...`, `go test ./...` (no Go file changed) | no unformatted file; vet clean; 25 packages ok |

**Expected failures and skips.**
- **Extraction:** 1 known expected failure (FLH-154 F1, listed apart since R2). 7 optional skips
  need `TINY_SFT` and torch.
- **Speaking on the host:** 29 skips need numpy, av or torch. The strict run in the image runs
  them all.

## 4. Speaking comparison per slice (R3 24-step candidate; R4-EXT-059)

| Slice | Utterances | Clusters | WER base → cand | CER base → cand | Punctuated | Standing |
|---|---|---|---|---|---|---|
| MLS test | 240 | 8 speakers | 27.12% → 27.32% (+0.21; paired 95% −0.58 to +0.94) | 11.48% → 11.54% | 1.0 / 1.0 | observation |
| SLR57 accented | 515 | 12 speakers | 37.69% → 36.48% (−1.21) | 22.00% → 20.82% | 0.95 / 0.98 | observation |
| FLEURS ood | 289 | 137 sentence groups | 27.52% → 26.94% | 12.44% → 12.18% | 1.0 / 1.0 | diagnostic only (training corpus) |

**Unsuitable as promotion evidence:**
- 20 speaker groups, against the 30 required;
- one seed;
- a 24-step smoke;
- FLEURS speaker overlap unknown;
- the same author designed and evaluated it.

## 5. Research (R4-EXT-036–038)

| Source | Population | Task | Observation | Limit for French practice in FLH |
|---|---|---|---|---|
| Karpicke & Roediger 2008, *Science* 319:966 (supporting material read) | 40 Washington University undergraduates | 40 Swahili–English pairs, 4 study/test schedules, typed recall one week later | repeated retrieval, not restudy, drove delayed recall | vocabulary pairs, not grammar contrasts; one week |
| Cepeda et al. 2008, *Psychological Science* 19:1095 (full text read) | >1,350 adults from an online pool (mean age 34) | 32 obscure trivia facts, 26 gap × delay conditions up to one year | the optimal gap is a falling share of the delay (20–40% at 1 week, 5–10% at 1 year) | trivia, not a second language. Scheduling is out of scope in this phase: no hypothesis |
| Lyster & Ranta 1997, *SSLA* 19:37 (figures from Tedick & de Gortari 1998, which reproduces their Table 1) | 4 Grade 4/5 French immersion classes, ≈ 18 h | teacher feedback types and learner uptake | recasts were 55% of feedback but led to no student-generated repair (66 repairs, all repetitions, from 375 recasts); elicitation 43/94 and metalinguistic feedback 26/58 led to repair | children, spoken, teacher-led; the primary text was not fetched (figures second-hand) |

## 6. Decisions and unresolved differences

**Decisions** (each with what was chosen, why, and how to reverse it):
- **Grounding checks as a separate module.** Chosen: not wired into `review2`. Why: it keeps the
  service identity, the batch semantics and the sealed 2.2 outputs. Reverse: call
  `grounding_quality.negated_quote` / `spelling_variant` from `review2.cues`; that is a new
  identity and needs Workbooks' review of the new cues.
- **Exercise-scoped agent packet as a new schema** (not a v3 variant). Why: no identity change,
  and smaller and stricter (corrections must cite evidence). Reverse: a `variant: "exercise"`
  in `portable.py`.
- **Increment-4 consumer mirror kept byte-identical.** It is embedded in sealed bundles; the
  merged-parser mirror is new (`feed_interop.py`). Reverse: replace `consumer_issues` and
  re-seal the bundles.
- **Service feed fix** (attempts on IDs withdrawn by `previous`). Why: a real 422 in the R4
  lifecycle, and the CLI accepted the same input. Reverse: restore the older `known` set; the
  baseline shows the difference.
- **Attempt first in the loop.** This is the pre-registered branch A. Reverse: only by a new
  experiment ID.
- **Retention default `keep`.** Why: it matches today's practice attempts. `discard` is one
  argument away. Reverse: default `discard` once the owner decides Workbooks'
  `practice_text_retention`.
- **Pilot candidate.** Chosen: the R3 config at 180 steps, not a new model. Why: the smallest
  credible step, with the same held-out split and the thresholds unchanged.

**Unresolved with Workbooks** (R4-EXT-073):
- The service feed builds source practice only. A `previous` with an accepted agent exercise is
  withdrawn as `knowledge_changed`, which is misleading; the CLI path is correct. Workbooks does
  not need the extension in R4. The request extension (exercise decisions) waits for the
  owner's storage decision (Workbooks part B).
- `flh_learning_loop_v1` and `flh_agent_*` are not integrated by Workbooks. They were read and
  accepted; nothing blocks.
- Workbooks' merged parser explains 2 of the 5 reason codes at base `58c0ba8b`. Their R4 branch
  explains all 5; this is pending the owner's merge.

**Unresolved with Release:**
- `restart: unless-stopped` in Release's staging override, against the rehearsal's `no`: the
  owner should accept one.
- Owned by Release under A11, unchanged in R4:
  - `flh-daily.sh` refuses `SPEAKING_TRANSCRIPTION_PROVIDER=local`;
  - Compose does not forward its `BASE_URL`/`TIMEOUT`;
  - staging IAM allows t3.small only.
- FLH has no provider for the extraction service: the URL and timeout settings remain a proposal.

## 7. Proceed? (R4-EXT-074)

- **Live staging of the extraction service.** Ready for an owner-run synthetic pass: Release's
  override pins `e978b6c2bdb6`, and §5–6 of the runtime contract give the checks. It needs the
  owner's approval of the staging host change and of `unless-stopped`. It is not needed for any
  learner-facing feature yet.
- **Training pilot.** Do not proceed unless the owner wants the measurement for itself. The
  pre-declared result is an observation (20 < 30 speaker groups).
  - **Cost** ≤ $1.41 compute, recommended ceiling $5.
  - **Evidence needed first:**
    - an approved budget, account, region and profile;
    - the quota (§5 of the pilot plan);
    - the pinned inputs unchanged;
    - the local gates green.
  - **For promotion:** an approved evaluation source adding ≥ 10 speaker groups.
- **Production promotion.** No. Keep the baseline.

## 8. Changed paths and seal

The changed paths are listed in the R4 handoff `snapshot/paths.txt`, with the owner's
`git add` command (`snapshot/GIT-ADD.txt`). The handoff is sealed with `SHA256SUMS` and made
read-only.
