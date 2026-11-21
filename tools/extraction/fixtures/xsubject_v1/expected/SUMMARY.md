# Cross-subject slice

| Check | Result |
|---|---|
| same_unit_contract | True |
| both_spans_verified | True |
| both_loops_valid_attempt_first | True |
| french_draft_unchanged | True |
| music_recall_supported | True |
| french_recall_optional | True |
| units_equal_authored_text | True |
| original_text_spans_exact | True |
| inbox_reasons_distinct | True |
| decision_kept_on_identical_rerun | True |
| inbox_sanitized | True |
| v2_source_through_normal_loop | True |
| v2_extensions_kept | True |
| exports_have_stable_ids | True |
| same_unit_contract_v2 | True |
| revisions_classified | True |
| rerun_statuses_distinct | True |
| correction_keeps_evidence | True |
| source_links_carried | True |
| review_after_revision | True |
| contradiction_both_trails | True |
| handoff_portable | True |
| followup_adds_a_revision | True |
| quoted_instructions_inert | True |
| contact_details_stay_local | True |
| private_scope_stays_local | True |
| model_failure_keeps_local_output | True |
| practice_four_kinds | True |
| grading_tolerant_not_lenient | True |
| multi_answer_span_flagged | True |
| two_agent_formats_same_evidence | True |

| Run | Subject | Language | Units | Usable | Recall | Loop |
|---|---|---|---|---|---|---|
| music | music_theory | en | 5 | 5 | 4 | recall → reveal → read → retry |
| french | french | fr | 7 | 5 | 0 | recall → reveal → read → retry |
| chemistry | chemistry | en | 4 | 4 | 4 | none: no contrast, so no practice item |

The chemistry source is a `flh_practice_source_v2` document with explicit spans, converted with `units convert` and run
through the same CLI; it has no contrast, so the practice builder makes no exercise and recall comes from the units layer.
