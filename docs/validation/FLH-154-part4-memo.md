# FLH-154 part 4: one-record fixture and reviewer evidence (OFFLINE ONLY, 2026-11-17)

> **OFFLINE ONLY.** One synthetic learning record and synthetic system outputs. No model,
> provider or AWS call, no paid run and no production data. Untouched by this part:
> the pinned scorer (`e5b4e012…`), `decision.py` (`flh_extractor_decision_v1`), the
> frozen evaluation, the comparison matrix (`b3f66eda…`) and the 35-item reviewer sample.
> All 27 files pinned before part 3 were re-checked unchanged.

This part follows `FLH-154-part3-memo.md` (items 41–60). Evidence comes from:

- `FLH-154/part4/actual.json` (the library path);
- `FLH-154/part4/part4-checks.json` and `.md` (the CLI path through the production validator), produced by `FLH-154/part4_checks.py`;
- the tests `tests/test_reviewer_evidence.py` and `tests/test_experimental.py`.

The fixture and its contract live in `tools/extraction/fixtures/one_record_v1/`
(`fixture.json`, `expected.json`, `CONTRACT.md`). They were published early, before
this seal, as the handoff checkpoint `part4-contract`.

## Owner decisions (smallest useful list)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | The pre-registered `decision-report` stays unchanged. With the fixture's assumed human numbers it proposes the **false-claim** system as `WINNER_FOR_OWNER_DECISION` (scenario A), because it has no gate on source, claim or Chinese (G6). | (a) A procedural rule: act on a winner only when `experimental-report` v1 on the same comparison prefers the same system. (b) Re-register the decision as v2 with the reviewer criterion. | (a) now, written into the runbook; (b) only if the decision report itself must be self-sufficient. |
| D2 | Which records the per-unit reviewer evidence covers in a real run. | The review sample's ids that are in the slice (about 27 units per unit-producing system; the oracle control has 27), or another list (`--scope-ids`). | The review sample: the reviewer then sees the reference and every system's output on the same items. |
| D3 | One explicit `no` in scope excludes a system outright, even when its sample rate is under the draft limit (for example false claims ≤ 0.02). | Keep this, or turn the in-scope answers into a rate. | Keep: the report only names what to study next. |

Still open from part 3, and unchanged:

- apply the re-pin patch before any paid run;
- confirm the draft thresholds;
- G7 (the abstention sample size).

Paid runs stay **NO-GO**.

## 1. The fixture (one learning record)

**The record** `p4-depuis`: the learner asks why « J'habite à Lyon pendant trois ans »
became « J'habite à Lyon depuis trois ans ». Its reference is one unit, « depuis + présent »
(an action still going on).

**Its follow-up** `p4-depuis-thanks`: « Merci beaucoup pour ta réponse ! ». Its context
quotes the earlier sentence and its reference is zero units (rule 3). The production
rule-based analyzer labels it `grammar`.

From these two inputs, `one-record-fixture` builds 10 rows:

- **frozen:** both inputs;
- **rb:** their `rb` probes, using the analyses recorded in the fixture (equal to a fresh analyzer run, and the probe bytes are equal too);
- **challenge_test:** one cue group per input, each with the variants aligned, conflicting and rb.

| Case | Linked to | Defect |
|---|---|---|
| `correct` | the record | none (a paraphrase of the reference) |
| `wrong_source` | the follow-up | the same plausible, true unit, but the follow-up raised nothing: the wording comes from the earlier record its context quotes |
| `unsupported_claim` | the record | "only the present tense is possible after « depuis »", which is false (« Je ne l'ai pas vu depuis trois ans ») and not in the source |
| `bilingual_drift` | the record | the Chinese says the action has ended; every quoted French form is kept |
| `legitimate_abstention` | the follow-up | none (zero units on a thank-you, against a `grammar` cue) |
| `control_abstain_on_question` | the record | control: the same empty answer on a real question |

## 2. Which report accepts which case, and why

Each row-level report ran on the case's five rows. The system-level reports ran on the
synthetic system that carries the case. All of it is in `FLH-154/part4/actual.json`.

| Case | evaluate (heur.) | quality exact | quality heuristic | paired (exact) | decision.gates | experimental, no reviewer evidence | experimental, with reviewer evidence |
|---|---|---|---|---|---|---|---|
| correct | accept | accept | accept | accept | accept | eligible | eligible |
| wrong_source | reject | reject | reject | reject | reject | excluded | excluded |
| **unsupported_claim** | **accept** | **accept** | **accept** | **accept** | **accept** | **eligible** | excluded (`claim_true: no`) |
| **bilingual_drift** | **accept** | **accept** | **accept** | **accept** | **accept** | **eligible** | excluded (`zh_same: no`) |
| legitimate_abstention | accept | accept | accept | accept | accept | eligible | eligible |
| control_abstain_on_question | reject | reject | reject | reject | reject | excluded | excluded |

Why each report says what it says:

- **unsupported_claim.** All five rows pass the production validator. The matcher pairs the unit
  with the reference (similarity 0.795 ≥ 0.34, same quoted forms), so evaluate has no
  error and F1 is 1.0. Grounding finds its terms in the learner's text, the bilingual
  checks find every French form in the Chinese, and the abstention and unit counts are exact.
  Nothing automatic can tell that the claim is false.
- **bilingual_drift.** The same holds. The bilingual checks only test that Chinese text exists,
  that the quoted French forms, IPA and numbers reappear, and the length ratio (0.53).
  They cannot read that the meaning has reversed.
- **wrong_source.** The exact abstention catches it, because its target (the follow-up)
  has a zero-unit reference: false extraction 5/5, frozen and rb abstention 0.0, and
  abstain-group paired accuracy 0. Paired *consistency* is 1/1 (consistently wrong).
  The heuristic grounding still calls the unit anchored, because `learner_text` includes the
  context, which quotes the sentence. On a record whose own reference has units, the same
  linkage error would pass every exact gate (part 3, G6 `unsupported_swap`), and only
  `source_raised` would catch it.
- **The abstentions.** The exact metrics separate the legitimate abstention from the control:
  5/5 correct empty, against 5 unit references answered empty, which fails the over-abstention gates.

## 3. Reviewer evidence in the experimental report (v1)

The contract is in `fixtures/one_record_v1/CONTRACT.md`.

**The queue.** `reviewer-queue` lists every unit of a scorable `valid_units` row in the
scope. Each unit is bound by `(system, id, unit, unit_sha256)`, the SHA-256 of the
validated unit as canonical JSON. The queue carries the matrix, the slice and each
system's row accounting, so it cannot vouch for another comparison.

**The evidence.** One row per unit answers three questions with `yes` or `no`:

- `source_raised`: did this record's learner text raise the objective;
- `claim_true`: is the statement true of standard French and not over-general;
- `zh_same`: does the Chinese say the same.

**The criterion.** The experimental report (schema `…_v1`) adds one criterion per system:

| Status | When |
|---|---|
| FAIL | any explicit `no` (the system is excluded and is never the preference) |
| PENDING | no queue; a queue for another comparison; any in-scope unit without exactly one complete, bound review (missing, blank answer, no reviewer, stale hash, duplicate) |
| PASS | every in-scope unit has three `yes` answers and a reviewer |

An answer other than yes, no or blank refuses the whole file (exit 1).

Library scenarios (five systems; the aggregate human evidence is ASSUMED and synthetic, clean samples):

| Scenario | Verdict | Preference |
|---|---|---|
| E0 no human evidence, no queue | PENDING | — |
| E1 assumed aggregates, no queue | PENDING | — |
| E2 queue, no evidence file | PENDING | — |
| E3 blank template | PENDING | — |
| E4 only the correct system reviewed | PENDING | — |
| E5 every unit reviewed | **EXPERIMENTAL_PREFERENCE** | **correct** |
| E6 one review bound to another output (stale hash) | PENDING | — |
| E7 the reviewer fails the correct system's unit | NO_PREFERENCE | — |
| E8 one explicit failure, everything else blank | PENDING (bilingual_drift already excluded) | — |
| E9 one unit reviewed twice | PENDING | — |
| E10 queue built for another comparison | PENDING | — |
| E11 failed reference review (6 of 30 rejected) | BLOCKED | — |
| E12 an answer "maybe" | refused | — |

Before and after, with the same assumed aggregates:

- the sealed part-3 draft (v0) prefers **`unsupported_claim`** (F1 0.90 against 0.82, lead 0.08);
- v1 is PENDING without reviewer evidence, and with it prefers `correct`.

`production_go` is false in every run.

**CLI path (`part4_checks.py`).** Every fixture output went through the production
validator and became `valid_units` or `valid_empty`. The unit hashes of the CLI queue
equal the library ones. The `compare`, `reviewer-queue`, `experimental-report` and
`decision-report` CLIs ran for scenarios A and B on a fixture-only matrix (`92b6a086…`;
its scoring version equals the pinned one):

| Scenario | decision-report (unchanged) | experimental: no evidence / blank / full / reviewer fails correct / invalid |
|---|---|---|
| A: current=correct, untuned=unsupported_claim, tuned=bilingual_drift | WINNER `unsupported_claim` | PENDING / PENDING / PREFERENCE `current_extractor` / NO_PREFERENCE / exit 1 |
| B: current=wrong_source, untuned=abstain_everywhere, tuned=correct | WINNER `correct` | PENDING / PENDING / PREFERENCE `qwen3.5-4b-tuned` / NO_PREFERENCE / exit 1 |

## 4. Release scoring intact

- The scoring version is `e5b4e012…`, equal to the pinned matrix (`b3f66eda…`).
- `decision.py` and the 27 pinned files are unchanged.
- The new modules (`reviewer_evidence.py`, `fixture_one_record.py`) are not scoring sources, and neither is `experimental_report.py`.
- `comparison_pipeline.sh` was rerun offline (exit 0). Of its 80 output files, 73 are byte-equal to part 3's run. The other 7 (the rendered readiness jobs and `readiness-checks.json`) differ only in the per-run timestamp of the job names, and are equal once it is normalized. The experiment manifest (`27a14f8b…`), the matrix (`b3f66eda…`), the scoring version (`e5b4e012…`) and the input manifest (`0c18fb8b…`) are unchanged.
- `part3_checks.py` item 57 was updated for report v1 and regenerated. Only `p57` changed in `part3-checks.json`:
  - without reviewer evidence it is now PENDING;
  - with synthetic reviewer evidence over the review-sample ids in the slice it still prefers the oracle, and the unrelated output is also excluded on `source_raised`;
  - every other check and the G5 fixtures are byte-identical.

## 5. Rerun

```sh
cd tools/extraction
python3 -B -m unittest discover -s tests -t tests                       # 98 OK (7 skipped, 1 expected failure)
python3 -B -m flh_extraction one-record-fixture --out DIR --check       # exit 0; DIR/actual.json = FLH-154/part4/actual.json
cd ../..   # network namespace with loopback only; BIN = go build ./cmd/extraction-render
python3 -I -B docs/validation/FLH-154/part4_checks.py --repo . --render BIN --work DIR2 --out docs/validation/FLH-154/part4 \
  [--pins PINS.sha256] [--xr-before PART3/experimental_report.py]       # exit 0
```

**Not done.** No real reviewer, model output or inter-reviewer agreement. The fixture is
a single record and measures no model.
