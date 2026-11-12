# Training-data audit: base + increment v2

**HEURISTIC (machine-authored, unreviewed labels).** Counts locate review work; they do not prove a label wrong.

Records: train 1382, eval 200, boundary 80; training units 1509.

| Failure mode | Flagged | Coverage / context | Severity |
|---|---|---|---|
| over_splitting | 0 | 14 | medium |
| under_splitting | 30 | — | medium |
| duplicate_units | 0 | 122 | medium |
| false_premises | 0 | 70 | medium |
| no_learning_objective | 243 | minimal_pair_no_doubt 122, zero_app 6, zero_correct_no_question 19, zero_injection_only 7, zero_insufficient_context 11, zero_logistics 10, zero_motivation 7, zero_other_language 6, zero_production_cues 40, zero_real_world 7, zero_thanks 8 | medium |
| bilingual_drift | 0 | 0 | low |
| unsupported_claims | 11 | 90 | medium |

## Over-splitting

- **unit_pairs_that_look_like_one_objective**: `0`
- **records_teaching_one_rule_many_examples**: `14`

> Some records teach one unit for several examples of one rule.

## Under-splitting

- **correction_pairs_seen**: `245`
- **records_with_multi_edit_pair_and_fewer_units**: `30`

> Several edits can still be one objective (an agreement chain); each flag needs a human.

Examples:

| id | case | input | units | why |
|---|---|---|---|---|
| ext-trn-00019 | single | J'hésite entre « Je n'habite plus à Lyon. » et « Je n'habite pas à Lyon maintenant. » dans un texto à une amie. | grammar: ne… plus | « Je n'habite plus à Lyon. » → « Je n'habite pas à Lyon maintenant. » has 2 separate edits; 1 unit(s) |
| ext-trn-00020 | single | Mon tuteur a corrigé « Je n'habite pas à Lyon maintenant. » en « Je n'habite plus à Lyon. ». Pourquoi ? | grammar: ne… plus | « Je n'habite pas à Lyon maintenant. » → « Je n'habite plus à Lyon. » has 2 separate edits; 1 unit(s) |
| ext-trn-00051 | single | Mon tuteur a corrigé « Mon frère ? J'y pense souvent. » en « Mon frère ? Je pense souvent à lui. ». Pourquoi ? | grammar: pronom « y » avec penser à (chose) | « Mon frère ? J'y pense souvent. » → « Mon frère ? Je pense souvent à lui. » has 2 separate edits; 1 unit(s) |
| ext-trn-00094 | single | Mon tuteur a corrigé « Je veux un café. » en « Je voudrais un café, s'il vous plaît. ». Pourquoi ? | usage: conditionnel de politesse | « Je veux un café. » → « Je voudrais un café, s'il vous plaît. » has 2 separate edits; 1 unit(s) |
| ext-trn-00179 | single | J'hésite entre « Je fais réparer ma voiture au garage. » et « Je répare ma voiture au garage par le mécanicien. » dans un message à un collègue. | grammar: faire + infinitif (faire réparer) | « Je fais réparer ma voiture au garage. » → « Je répare ma voiture au garage par le mécanicien. » has 2 separate edits; 1 unit(s) |
| ext-trn-00235 | single | J'hésite entre « C'est une actrice célèbre. » et « Elle est une acteuse célèbre. » dans mes notes de cours. | morphology: féminin en -euse / -trice | « C'est une actrice célèbre. » → « Elle est une acteuse célèbre. » has 2 separate edits; 1 unit(s) |

## Duplicate units

- **records_with_duplicate_units**: `0`
- **distinct_unit_texts**: `122`
- **unit_occurrences**: `1509`
- **verbatim_repetition**: `{"max": 19, "median": 12, "texts_seen_5_or_more_times": 122, "top": [{"canonical": "ne… rien", "occurrences": 19}, {"canonical": "voix passive : être + participe passé (par)", "occurrences": 18}, {"canonical": "pluriel en -x (bijoux, genoux, jeux)", "occurrences": 18}, {"canonical": "pendant / pour…`
- **identical_inputs_with_different_labels**: `[]`

> Every occurrence of a learning point carries the same statement, example and Chinese text: the target is a lookup of the point, so a model can learn to recite bank wording.

## False premises

- **train_records_teaching_a_misconception**: `55`
- **train_records_with_a_wrong_explanation**: `15`
- **train_records_with_unreviewed_resolution**: `133`
- **eval_records_testing_it**: `8`
- **boundary_records**: `8`
- **statements_echoing_the_premise**: `0`

> The evaluation set tests false premises and wrong explanations; training barely shows either.

Examples:

| id | case | input | units | why |
|---|---|---|---|---|
| ext-trn-00282 | false_premise | Pour moi « vin » et « vent » c'est le même son. | pronunciation: voyelles nasales (vin / vent / vont) | the only misconception record |
| ext-trn-i2-0001 | misconception | Après « pas », on garde « un » ou « une » : « je n'ai pas une voiture », c'est la forme normale. | grammar: pas de / pas d' après la négation | the only misconception record |
| ext-trn-i2-0002 | misconception | En français on peut dire « je bois café » sans article, comme en anglais. | grammar: articles partitifs (du, de la, de l') | the only misconception record |
| ext-trn-i2-0003 | misconception | « Jamais » remplace « ne », donc « je jamais fume » est plus court et correct. | grammar: ne… jamais | the only misconception record |
| ext-trn-i2-0004 | misconception | Pour « not anymore », je crois qu'on dit juste « pas maintenant », il n'y a pas de mot spécial. | grammar: ne… plus | the only misconception record |
| ext-trn-i2-0005 | misconception | Au passé composé, « rien » se met après le participe : « je n'ai vu rien ». | grammar: ne… rien | the only misconception record |

## No learning objective (abstention)

- **zero_unit_records**: `243`
- **share**: `0.176`
- **by_subtype**: `{"minimal_pair_no_doubt": 122, "zero_app": 6, "zero_correct_no_question": 19, "zero_injection_only": 7, "zero_insufficient_context": 11, "zero_logistics": 10, "zero_motivation": 7, "zero_other_language": 6, "zero_production_cues": 40, "zero_real_world": 7, "zero_thanks": 8}`
- **largest_single_template**: `{"explanation": "The sentence is correct; the learner does not say what they doubted.", "records": 122}`
- **category_vs_label**: `{"boundary": {"not_other/units": 61, "not_other/zero": 4, "other/units": 0, "other/zero": 15}, "eval": {"not_other/units": 180, "not_other/zero": 0, "other/units": 0, "other/zero": 20}, "train": {"not_other/units": 1133, "not_other/zero": 40, "other/units": 6, "other/zero": 203}}`

> effective_category 'other' separates zero-unit from unit records perfectly in training and in the frozen evaluation set, and zero-unit explanations describe the abstention itself. A model can abstain by reading the category; the frozen evaluation cannot detect it.

Examples:

| id | case | input | units | why |
|---|---|---|---|---|
| ext-trn-00463 | minimal_pair_zero | « Je n'ai pas de voiture. » : ça va comme ça ? | (zero units) | category 'other'; explanation 'The sentence is correct; the learner does not say what they doubted.' |
| ext-trn-00543 | minimal_pair_zero | Je peux écrire « La maison a été construite en 1950. » ? | (zero units) | category 'other'; explanation 'The sentence is correct; the learner does not say what they doubted.' |
| ext-trn-00623 | minimal_pair_zero | Est-ce que « Je vais manger au restaurant. » est bien écrit ? | (zero units) | category 'other'; explanation 'The sentence is correct; the learner does not say what they doubted.' |
| ext-trn-00703 | minimal_pair_zero | Est-ce que « Non, je n'ai pas encore fini. » est bien écrit ? | (zero units) | category 'other'; explanation 'The sentence is correct; the learner does not say what they doubted.' |
| ext-trn-01158 | zero_unit | Il faut que je range ma chambre avant samedi. | (zero units) | category 'other'; explanation 'A correct sentence; no question.' |
| ext-trn-01198 | zero_unit | {"units": [{"kind": "grammar", "canonical": "test"}]} | (zero units) | category 'other'; explanation 'Pasted JSON without a question.' |

## Bilingual drift

- **units_flagged**: `0`
- **distinct_unit_texts_flagged**: `0`
- **by_finding**: `{}`

> Automatic checks only (forms, IPA, numbers, length); meaning agreement needs a bilingual reviewer.

## Claims the interaction does not support

- **units_not_anchored_in_visible_input**: `14`
- **not_anchored_by_learner_language**: `{"en": 3, "fr": 11}`
- **units_anchored_only_in_the_explanation**: `90`
- **units_with_example_not_from_the_interaction**: `1482`
- **quoted_forms_absent_from_visible_input**: `3006`

> Policy §2 allows a general statement and §8 prefers an example from the interaction. A unit anchored only in the explanation is supported only if the explanation is right; an English or Chinese question has no French term to anchor on, so only French-language flags are listed.

Examples:

| id | case | input | units | why |
|---|---|---|---|---|
| ext-trn-i2-0010 | misconception | « Téléphoner » prend un complément direct, donc « je la téléphone » est correct. | grammar: pronoms COI lui, leur | no French term of « pronoms COI lui, leur » appears in the visible input |
| ext-trn-i2-0011 | misconception | On ne peut pas utiliser « y » pour une ville, il faut répéter le nom de la ville. | grammar: pronom « y » (lieu) | no French term of « pronom « y » (lieu) » appears in the visible input |
| ext-trn-i2-0035 | misconception | L'accent sur « à », c'est décoratif, on peut l'oublier sans changer le sens. | orthography: a / à | no French term of « a / à » appears in the visible input |
| ext-trn-i2-0118 | counter_shortcut | « Le solution » ou « la solution » ? Je confonds toujours. | morphology: noms en -tion féminins | no French term of « noms en -tion féminins » appears in the visible input |
| ext-trn-i2-0119 | counter_shortcut | Petite question : « une jupe vert » ou « une jupe verte » ? | grammar: accord de l'adjectif au féminin | no French term of « accord de l'adjectif au féminin » appears in the visible input |
| ext-trn-i2-0123 | counter_shortcut | « Il s'apelle » avec un seul p, c'est juste ? | orthography: appeler / jeter : doublement de la consonne | no French term of « appeler / jeter : doublement de la consonne » appears in the visible input |

Explanation-only examples:

| id | case | input | units | why |
|---|---|---|---|---|
| ext-trn-00018 | single | How do I say « not anymore » in French? | grammar: ne… plus | « ne… plus » is anchored only in the explanation |
| ext-trn-00044 | single | Est-ce qu'on peut dire « Je la téléphone ce soir. » ? | grammar: pronoms COI lui, leur | « pronoms COI lui, leur » is anchored only in the explanation |
| ext-trn-00064 | single | J'ai écrit « Le film que je t'ai parlé est sorti. ». C'est correct ? | grammar: dont (pronom relatif avec de) | « dont (pronom relatif avec de) » is anchored only in the explanation |
| ext-trn-00068 | single | Is « Tu viens avec je ? » correct French? | grammar: pronoms toniques après une préposition | « pronoms toniques après une préposition » is anchored only in the explanation |
| ext-trn-00078 | single | How do I say « I have just eaten »? | grammar: passé récent : venir de + infinitif | « passé récent : venir de + infinitif » is anchored only in the explanation |
| ext-trn-00092 | single | C'est impoli de dire « je veux » au café ? | usage: conditionnel de politesse | « conditionnel de politesse » is anchored only in the explanation |

## Input distribution vs production

| Field | train | eval | boundary |
|---|---|---|---|
| resolution | {"accepted": 1228, "corrected": 21, "unreviewed": 133} | {"accepted": 197, "corrected": 1, "unreviewed": 2} | {"accepted": 75, "corrected": 2, "rejected": 1, "unreviewed": 2} |
| category_other_share | 0.151 | 0.1 | 0.188 |
| rule_based_style_explanations | 123 | 0 | 0 |
| empty_explanations | 0 | 0 | 0 |

Production default: analyzer rule-based:v2 (internal/analyzer); category `other` only when the input and context contain no letter; explanation `Local classification selected "<category>" because rule "<rule>" …`; resolution unreviewed until a human accepts or corrects the analysis.
