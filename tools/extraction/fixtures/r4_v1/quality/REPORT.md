# French grounding quality (R4)

Reference `flh_grounding_reference_v1` (frozen before the candidate). Candidate checks `flh_grounding_checks_v2`, window 3.
same author for cases and checks: reproducible behaviour on this fixture, not an accuracy estimate.

| System | Correct | Errors |
|---|---|---|
| `exact_v1` | 11/18 | false_support_contradiction 3, false_support_unrelated 2, missed_variant 2 |
| `folded_v1` | 9/18 | false_support_contradiction 4, false_support_unrelated 2, variant_accepted_silently 2, over_flag 1 |
| `lexical_v1` | 6/17 | false_support_contradiction 5, false_support_unrelated 2, false_support_paraphrase 2, variant_accepted_silently 1, false_rejection 1 |
| `exact_v1+checks_v2` | 15/18 | false_support_contradiction 1, false_support_unrelated 2 |

| Item | Phenomenon | Location | Relation | Acceptable | `exact_v1` | `folded_v1` | `lexical_v1` | `exact_v1+checks_v2` |
|---|---|---|---|---|---|---|---|---|
| n1 | control | verbatim | supports | supported | supported | supported | supported | supported |
| n2 | negation | verbatim | contradicts | review, unsupported | supported **false_support_contradiction** | supported **false_support_contradiction** | supported **false_support_contradiction** | review |
| n3 | negation | verbatim | supports | supported | supported | supported | supported | supported |
| n4 | negation | verbatim | supports | supported | supported | supported | supported | supported |
| n5 | negation | verbatim | contradicts | review, unsupported | supported **false_support_contradiction** | supported **false_support_contradiction** | supported **false_support_contradiction** | review |
| n6 | lexical_overlap | verbatim | unrelated | review, unsupported | supported **false_support_unrelated** | supported **false_support_unrelated** | supported **false_support_unrelated** | supported **false_support_unrelated** |
| a1 | accent_error | verbatim | supports | supported | supported | review **over_flag** | unsupported **false_rejection** | supported |
| a2 | accent_error | accent_variant | supports | review | unsupported **missed_variant** | supported **variant_accepted_silently** | n/a | review |
| a3 | accent_error | case_variant | supports | review | unsupported **missed_variant** | supported **variant_accepted_silently** | supported **variant_accepted_silently** | review |
| a4 | accent_error | accent_variant | contradicts | review, unsupported | unsupported | supported **false_support_contradiction** | supported **false_support_contradiction** | review |
| p1 | paraphrase | paraphrase | supports | unsupported, review | unsupported | unsupported | supported **false_support_paraphrase** | unsupported |
| p2 | control | verbatim | supports | supported | supported | supported | supported | supported |
| p3 | lexical_overlap | verbatim | unrelated | review, unsupported | supported **false_support_unrelated** | supported **false_support_unrelated** | supported **false_support_unrelated** | supported **false_support_unrelated** |
| p4 | control | verbatim | supports | supported | supported | supported | supported | supported |
| p5 | lexical_overlap | verbatim | contradicts | review, unsupported | supported **false_support_contradiction** | supported **false_support_contradiction** | supported **false_support_contradiction** | supported **false_support_contradiction** |
| p6 | negation | verbatim | supports | supported | supported | supported | supported | supported |
| p7 | paraphrase | paraphrase | supports | unsupported, review | unsupported | unsupported | supported **false_support_paraphrase** | unsupported |
| p8 | paraphrase | paraphrase | contradicts | review, unsupported | unsupported | unsupported | supported **false_support_contradiction** | unsupported |

Checks raised by the candidate:

- n2 `negated_quote`: in « On ne dit pas en Japon », « en Japon » follows « ne dit pas »: the quoted words may deny what the claim asserts (a word check, not proof)
- n5 `negated_quote`: in « ce n'est jamais « en » devant un pays masculin », « en » follows « n' est jamais »: the quoted words may deny what the claim asserts (a word check, not proof)
- a2 `spelling_variant`: not the learner's exact words: the learner wrote « Hier j'ai ecrit « je vais a Lyon » » (accents differ); review before using it
- a3 `spelling_variant`: not the learner's exact words: the learner wrote « Sans accent, a est le verbe avoir » (case differ); review before using it
- a4 `spelling_variant`: not the learner's exact words: the learner wrote « il a un chat » (accents differ); review before using it

Window sensitivity (candidate only):

- window 2: correct 15/18; false_support_contradiction 1, false_support_unrelated 2
- window 3: correct 15/18; false_support_contradiction 1, false_support_unrelated 2
- window 4: correct 14/18; false_support_contradiction 1, false_support_unrelated 2, over_flag 1
- window 6: correct 14/18; false_support_contradiction 1, false_support_unrelated 2, over_flag 1
