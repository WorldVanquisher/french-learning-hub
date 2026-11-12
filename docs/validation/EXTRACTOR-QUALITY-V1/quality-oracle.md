# Oracle (references through the production validator)

Each section names its basis: **exact** (production validator and counts), **heuristic** (automatic matcher and string checks, PROVISIONAL) or **human** (judgments). Heuristic and human numbers are never added together. FALSE_CLAIM is not measured automatically.

| Headline | Value | Basis |
|---|---|---|
| structural_validity | 1.000 | exact |
| exact_unit_count_rate | 1.000 | exact |
| abstention_rate | 1.000 | exact |
| false_extraction_on_zero_refs | 0 | exact |
| unit_refs_answered_empty | 0 | exact |
| over_split+merged+duplicate | 0 | heuristic |
| not_anchored_units | 1 | heuristic |
| unsupported_units | 0 | heuristic |
| bilingual_flagged_units | 0 | heuristic |
| unit_f1 | 1.000 | heuristic |

## Structural validity (exact)

200/200 valid (1.000); invalid by class `{}`; parse diagnostics `"not run (pass --outputs)"`.

## Unit-count errors (exact, valid outputs)

Exact count 200/200 (1.000); over-count 0, under-count 0; mean absolute error 0.000.

| Reference → prediction | Examples |
|---|---|
| ref 0 → pred 0 | 20 |
| ref 1 → pred 1 | 155 |
| ref 2 → pred 2 | 25 |

## Abstention errors (exact)

Zero-unit references answered empty: 20/20 (1.000); false extraction 0 `{}`; unit references answered empty 0/180.

## Split / merge / duplicate

| Basis | Examples | OVER_SPLIT | MERGED | DUPLICATE |
|---|---|---|---|---|
| heuristic | 200 | 0 | 0 | 0 |
| human | 0 | 0 | 0 | 0 |

## Grounding

- heuristic: 205 predicted units; anchored in the learner's text 194, only in the explanation 10, not anchored 1; matcher UNSUPPORTED 0; examples taken from the interaction 11/205.
- human: 0 judged, 0 unsupported.
- FALSE_CLAIM: not measured automatically: needs human claim judgments.

## Bilingual fidelity

- heuristic: `{"basis": "heuristic", "pred_units": 205, "units_flagged": 0}`
- human: 0 judged, 0 mismatches.

## Semantic summary

| Basis | Examples | Precision | Recall | F1 | Errors |
|---|---|---|---|---|---|
| heuristic | 200 | 1.000 | 1.000 | 1.000 | {} |
| human | 0 | — | — | — | {} |
