# Controlled failures vs metrics

Each control breaks one thing in the reference outputs; a metric "moves" when it gets worse than the oracle. CAUGHT = every target moved. References are machine-authored and unreviewed.

| Control | Targets | Result | Moved (Δ vs oracle) | Collateral |
|---|---|---|---|---|
| oracle | — | — | nothing | — |
| struct_code_fence | structural_validity | CAUGHT | structural_validity -1, abstention_rate -1 | abstention_rate |
| struct_think_block | structural_validity | CAUGHT | structural_validity -1, abstention_rate -1 | abstention_rate |
| struct_truncated | structural_validity | CAUGHT | structural_validity -1, abstention_rate -1 | abstention_rate |
| count_drop | exact_unit_count_rate | CAUGHT | exact_unit_count_rate -0.125, over_split+merged+duplicate +1, unit_f1 -0.065 | over_split+merged+duplicate, unit_f1 |
| over_split | exact_unit_count_rate, over_split+merged+duplicate | CAUGHT | exact_unit_count_rate -0.9, over_split+merged+duplicate +180, not_anchored_units +3, bilingual_flagged_units +145, unit_f1 -0.305 | bilingual_flagged_units, not_anchored_units, unit_f1 |
| merge | exact_unit_count_rate, over_split+merged+duplicate | CAUGHT | exact_unit_count_rate -0.125, over_split+merged+duplicate +25, unit_f1 -0.065 | unit_f1 |
| duplicate | exact_unit_count_rate, over_split+merged+duplicate | CAUGHT | exact_unit_count_rate -0.9, over_split+merged+duplicate +180, not_anchored_units +1, unit_f1 -0.305 | not_anchored_units, unit_f1 |
| over_abstain | unit_refs_answered_empty | CAUGHT | exact_unit_count_rate -0.9, unit_refs_answered_empty +180 | exact_unit_count_rate |
| hallucinate_on_zero | false_extraction_on_zero_refs, abstention_rate | CAUGHT | exact_unit_count_rate -0.1, abstention_rate -1, false_extraction_on_zero_refs +20, not_anchored_units +20, unsupported_units +20, unit_f1 -0.047 | exact_unit_count_rate, not_anchored_units, unit_f1, unsupported_units |
| unsupported_swap | unsupported_units, not_anchored_units | CAUGHT | over_split+merged+duplicate +1, not_anchored_units +139, unsupported_units +154, unit_f1 -0.756 | over_split+merged+duplicate, unit_f1 |
| bilingual_drift | bilingual_flagged_units | CAUGHT | bilingual_flagged_units +205 | — |
| false_claim | — | NOT CAUGHT (needs human claim judgment) | nothing | — |
| category_shortcut | — | hidden on the frozen eval | nothing | — |

## On the `swap` probe (production-style cues)

| Control | Targets | Result | Moved |
|---|---|---|---|
| category_shortcut | false_extraction_on_zero_refs, unit_refs_answered_empty | CAUGHT | exact_unit_count_rate -1, abstention_rate -1, false_extraction_on_zero_refs +20, unit_refs_answered_empty +180, not_anchored_units +9, unsupported_units +20 |
