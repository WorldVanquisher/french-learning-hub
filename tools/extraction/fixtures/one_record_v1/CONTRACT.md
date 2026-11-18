# One-record fixture and reviewer-evidence contract (v1)

> **OFFLINE ONLY.** Synthetic, machine-authored, unreviewed. It is not a training, evaluation
> or comparison record. It is never part of the frozen evaluation, the review sample or the
> pinned comparison slice, and it measures no model. It contains no provider output, no
> learner data and no local paths.

| Identifier | Value |
|---|---|
| Fixture | `fixture.json`, schema `flh154_one_record_fixture_v1` |
| Expectations | `expected.json`, schema `flh154_one_record_fixture_expected_v1` (hand-written) |
| Reviewer queue | `flh_extraction_reviewer_queue_v1` (`flh_extraction/reviewer_evidence.py`) |
| Reviewer evidence | `flh_extraction_reviewer_evidence_v1` (one JSONL row per unit) |
| Experimental report | `flh_extractor_experimental_report_v1` (DRAFT; `production_go` is always false) |
| Unchanged | the scoring sources (`comparison.SCORING_SOURCES`), `decision.py`, the pinned matrix and its digests |

## 1. The fixture

The fixture holds **one learning record** (`p4-depuis`): the learner asks why their corrector
replaced « J'habite à Lyon pendant trois ans » with « J'habite à Lyon depuis trois ans ». The
reference is one unit, « depuis + présent » (an action still going on). It also holds that
learner's **next message** in the same thread (`p4-depuis-thanks`), « Merci beaucoup pour ta
réponse ! ». Its context quotes the earlier sentence, and its reference is zero units
(ANNOTATION_POLICY rule 3). The rule-based analyzer labels it `grammar`, so the abstention
holds against a misleading cue.

`one-record-fixture` builds 10 rows from these two inputs, in the parts `compare` scores:

- **frozen:** the record and its follow-up;
- **rb:** their `rb` probes, using the recorded rule-based analyses;
- **challenge_test:** two paired cue groups (aligned, conflicting, rb). `p4-g-record` has intent extract and `p4-g-follow-up` has intent abstain.

| Case | Linked to | What is wrong | Existing automatic reports | Reviewer answer that rejects it |
|---|---|---|---|---|
| `correct` | the record | nothing (a paraphrase of the reference) | all accept | — |
| `wrong_source` | the follow-up | the record's plausible, true unit is linked to a message that raised nothing; the wording comes from the earlier record quoted in the context | rejected by the exact abstention gates. The heuristic grounding check still calls it anchored, because the context quotes the sentence | `source_raised: no` |
| `unsupported_claim` | the record | "only the present tense is possible after « depuis »", which neither the source nor standard French supports | **all accept** (validator, exact gates, matcher, grounding, bilingual checks, paired consistency) | `claim_true: no` |
| `bilingual_drift` | the record | the Chinese says the action has ended; every quoted French form is kept | **all accept** | `zh_same: no` |
| `legitimate_abstention` | the follow-up | nothing (zero units on a thank-you) | all accept | — |
| `control_abstain_on_question` (control) | the record | the same empty answer on a real question | rejected (over-abstention) | — |

Five synthetic systems answer every row from the record with one case and every row from the
follow-up with another (`fixture.json` → `systems`). These are `correct`, `wrong_source`,
`unsupported_claim`, `bilingual_drift` and `abstain_everywhere`.

## 2. Reviewer evidence

**The queue (`reviewer-queue`).** The queue lists, for every system and every record in the
review scope, each unit of a scorable `valid_units` row. Each item is bound to its output by:

- `system`
- `id`
- `unit` (the 0-based index in the validated output)
- `unit_sha256`: the SHA-256 of the validated unit as canonical JSON (sorted keys, separators `,` and `:`, UTF-8, no ASCII escaping)

The queue also lists the following, which need no unit review:

- **Scorable empty rows:** the exact metrics judge them against the reference, and the reference review judges the reference.
- **Rows that are not scorable:** the strict count already fails them.

The queue records the matrix hash, the slice hash and each system's row accounting, so it
cannot be used with another comparison. Each unit also shows what the automatic checks said
(matcher, grounding, bilingual flags). This is for information only: **every in-scope unit
needs a review**, whatever the checks say.

**Evidence rows.** There is one row per queue item, and a template is written with the queue:

```json
{"schema": "flh_extraction_reviewer_evidence_v1", "system": "...", "id": "...", "unit": 0,
 "unit_sha256": "...", "source_raised": "yes", "claim_true": "yes", "zh_same": "yes",
 "reviewer": "...", "date": "YYYY-MM-DD", "note": ""}
```

| Question | Asks | Rubric code when `no` |
|---|---|---|
| `source_raised` | Did **this record's** learner text raise the objective? A unit raised only by the explanation, or only by an earlier message quoted in the context, does not count. | `UNSUPPORTED` |
| `claim_true` | Is the statement true of standard French and not over-general? | `FALSE_CLAIM` |
| `zh_same` | Does `statement_zh` say the same as `statement` (scope, claim, quoted forms)? | `BILINGUAL_MISMATCH` |

Answers are `"yes"`, `"no"`, `null` or `""`. Any other value refuses the whole file (the
CLI exits 1), and is never read as a guess.

**Per-system criterion** ("reviewer evidence: every in-scope unit reviewed, no explicit failure"):

| Status | When |
|---|---|
| **FAIL**, so the system is excluded | Any bound row answers `no`. This applies whatever the other answers, the sample rates or the F1, and a `no` in a duplicated row counts too. An excluded system is never the preference. |
| **PENDING**, so the verdict is PENDING | Any of these holds: no queue was given; the queue was built for another matrix, lacks the system or reports different row counts; an in-scope unit has no row, a blank answer or no reviewer; the only rows for a unit carry another hash (stale); or a unit has two rows (the report never chooses between reviews). |
| **PASS** | Every in-scope unit has exactly one bound row with three `yes` answers and a reviewer. A system with no unit in scope passes with nothing to review, and is still judged by the exact gates. |

The experimental report v1 needs this criterion for every measured system, besides:

- the exact gates (shared with `decision.py`);
- the aggregate human evidence (sample rates over at least 100 judged units);
- a finished reference review.

A failed reference review still blocks everything.

## 3. Reuse

```sh
cd tools/extraction
# Library path: no Go, no network. Writes DIR/inputs/ and DIR/actual.json, then compares with expected.json.
python3 -B -m flh_extraction one-record-fixture --out DIR --check
# CLI path through the production validator (offline; see docs/validation/FLH-154/part4_checks.py):
#   extraction-render render (the slice parts) -> comparison-slice -> comparison-matrix -> compare
#   reviewer-queue -> experimental-report --reviewer-queue Q.json --reviewer-evidence E.jsonl
#   decision-report (unchanged)
```

For a real comparison, build the queue with the same matrix, slice and prediction files as
`compare`, and choose the scope explicitly (owner decision D2):

- `--scope-packet review/review-sample-v1.jsonl` takes the review-sample ids that are in the slice;
- `--scope-ids FILE` takes any list of ids.

A release may copy this directory. It must keep these stable so recorded evidence stays bound
to outputs:

- the ids;
- the hash rule;
- the three questions;
- the schema names.

A change to any of them is a new contract version (`…_v2`) and a new fixture directory.

## 4. Not covered

- Real model output, real reviewers and inter-reviewer agreement.
- A unit-bearing wrong source. On a record whose own reference has units, a unit taken from
  another record is caught only by the heuristic matcher (part 3, G6 `unsupported_swap`), and
  by `source_raised`.
- The pre-registered `decision-report` is unchanged. With the fixture's assumed human numbers,
  scenario A gives `WINNER_FOR_OWNER_DECISION` for `unsupported_claim`: it has no source,
  claim or Chinese gate. Changing that needs a new pre-registration (owner decision D1).
