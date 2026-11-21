# Unit quality against gold v1

Sample: 4 documents, 13 gold claims, subjects diary, intervals, keys, states of water.

| System | Coverage | Evidence-supported | Duplicates | Missing claims | Bad-span claims | correct / wrong_claim / bad_span / extra |
|---|---|---|---|---|---|---|
| `authored` | 8/13 (62%) | 7/8 (88%) | 0/8 (0%) | 4/13 (31%) | 1/13 (8%) | 7 / 1 / 0 / 0 |
| `sentence_baseline` | 7/13 (54%) | 6/10 (60%) | 0/10 (0%) | 6/13 (46%) | 0/13 (0%) | 6 / 0 / 0 / 4 |

Per document:

- `authored` music-thirds: accepted 3; semitone missing, major-third matched, minor-third matched, major-triad matched, minor-triad matched, octave missing
- `authored` chem-water-states: accepted 4; freeze-0 matched, boil-100 matched, altitude missing, plateau matched, vapour missing; wrong_claim: Lower air pressure at high altitude lowers the boiling point
- `authored` music-relative-keys: accepted 1; c-major-signature matched, relative-minor bad_span_only
- `authored` music-practice-diary: accepted 0; no gold claim
- `sentence_baseline` music-thirds: accepted 4; semitone matched, major-third matched, minor-third matched, major-triad missing, minor-triad missing, octave matched
- `sentence_baseline` chem-water-states: accepted 3; freeze-0 matched, boil-100 matched, altitude matched, plateau missing, vapour missing; extra: Lab notebook, week 3.
- `sentence_baseline` music-relative-keys: accepted 2; c-major-signature missing, relative-minor missing; extra: Key signatures, part one.; extra: Part two, a week later.
- `sentence_baseline` music-practice-diary: accepted 1; no gold claim; extra: Practised for twenty minutes today.

Known biases:

- the same author wrote the sources, the gold claims and the authored proposals: authored scores are an upper bound, not an estimate
- 4 short synthetic English documents (2 subjects); no learner data; the French control is not in the gold set
- the sentence baseline favours numeric facts by design; descriptive claims are its blind spot
- matching is lexical (span overlap >= 50% and the gold value as words): a correct paraphrase of the value counts as wrong_claim
