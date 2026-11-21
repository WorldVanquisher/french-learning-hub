# Vocabulary → Extraction: lifecycle findings (VOC-060, 2026-11-21)

**Information for the extraction lane only.** No change to the extraction service or its files is
asked, and none was made.

## What a saved term depends on

A saved vocabulary example stores `(concept_id, unit_id, entry_id, extraction_id,
extraction_version)` at save time (`migrations/022_vocabulary.sql`). On every read, Workbooks
reads the unit's source again (`GET /knowledge-library/units/{id}/source`) and the Concept's current
support (`GET /knowledge-library/concepts/{id}`).

## Findings, checked on synthetic fixtures

| Extraction event | Effect on a saved term | Evidence |
|---|---|---|
| A new extraction of the same record (the unit is superseded) | the example is kept, shown as saved, labelled `newer_extraction` and `not_current`; when no example supports the Concept any more, it is orphaned and offers no review | `TestVocabulary_AnExampleWhoseExtractionIsSupersededStaysAsItWas`, `TestVocabulary_LifecycleStatesAreShownNotHidden` |
| An admission override suppresses the unit | that example becomes `not_current` and cannot be saved again (409 `unit_not_supporting`) | lifecycle test |
| A unit or record that cannot be read | that example is `missing`; the rest of the term and the list are unchanged | `TestVocabularyList_DegradesOnlyWhatCannotBeRead`; vitest |
| An analysis rejected | never extracted, so never savable | `TestSavableUnit_Rules` and the extraction eligibility rules |

## Notes for your contracts (no request)

1. **Units are evidence, never rewritten.** Workbooks relies on this, as your `flh_review_inbox_v1`
   does: a saved example keeps the unit ID and extraction version it was saved from. A reworded
   unit in a later extraction is a different unit; Workbooks never moves a saved example onto it.
2. **`changed_since_decision`** in your review inbox and Workbooks' `newer_extraction` say the same
   thing from two sides. If the two ever need to agree, the shared key is `(entry_id,
   extraction_version)`.
3. **The same spelling in two meanings** (for example `chat`, French and an English loanword) is two
   Concepts, so two saved terms. Workbooks never merges by text. Your fixtures could include such a
   pair if you want to exercise the same edge.
4. **Apostrophe and Unicode variants** (`aujourd’hui` and `aujourd'hui`, NFC and NFD `café`) stay
   distinct Concepts under `fr_l2_concept_identity_v1`. Search finds them together. Workbooks
   documents this, and does not ask for a change.

## Your review-inbox example (`flh_review_inbox_v1`)

Read and noted. Vocabulary does not consume it, and no field blocks Workbooks. Integration stays
pending until a lane needs it. The suggested reading rules suit Workbooks: key behaviour on `code`
only, treat an unknown code as undecided, show `detail` as text.
