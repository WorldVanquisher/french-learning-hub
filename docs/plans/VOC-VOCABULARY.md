# VOC: private saved vocabulary (Workbooks, 2026-11-21)

**Branch:** `worker/20261121-vocabulary`, confirmed by the owner. The exact commit is **unverified**:
agents may not run Git here.

**Evidence and status:** in the sealed handoffs
(`flh-handoff/overnight-20261121-flh/workbooks-voc/handoff-0NN`). The living resume file is next to
them.

## 1. What existed (VOC-001 to VOC-004)

### The Vocabulary view (VOC-001)

- **Where it lives:** a mode of the Mistake Notebook, `GET /mistake-notebook/concepts?kind=vocabulary`
  (`ConceptsByKind`, rule `concept_kind_view_v1`).
- **What it lists:** active Concepts whose CURRENT supporting units are all of kind `vocabulary`.
- **What "approved" means:** a supporting unit is in its record's current extraction, has effective
  admission `active` and has CURRENT SAME membership. The view was read-only and saved nothing.

### The canonical identifier (VOC-002)

- **The ID:** the Knowledge Concept ID (`knowledge_concepts.id`), with its durable identity
  `fr_l2_concept_identity_v1` (target, pedagogical intent, scope, features) and its signature.
- **How identity compares text:** lowercased, with whitespace collapsed. It does not normalize
  Unicode or apostrophes. So `aujourd’hui` and `aujourd'hui`, and an NFC `café` and an NFD `café`,
  are separate Concepts when created so. A saved term inherits this rule because it *is* the Concept.

### The source and sentence (VOC-003)

- **The unit:** a Concept's supporting unit is immutable extraction evidence: `canonical` (its
  wording), `statement` with EN/ZH variants (the meaning, generated), and an optional `example`
  sentence (generated).
- **Where it came from:** the unit points to its learner record (`learning_entries`, the learner's
  own `original_input` and `original_context`, immutable) and to its extraction (id and version).
- **How to read it:** `GET /knowledge-library/units/{id}/source` returns that whole chain.

### Storage (VOC-004)

**Nothing existing could hold a saved term that can be removed:**
- the notebook's `learning_capture_sources` has a CHECK on four workbook source types (a new type
  needs a table rebuild);
- captures and records cannot be removed;
- browser storage is not durable learner data (no backup, no restore, one device).

**Chosen:** one additive migration, `022_vocabulary.sql`, with two append-only tables and nothing
else changed (VOC-019). The existing primitives are reused for everything else:
- the Concept identity;
- the Knowledge Library reads (`GetConcept`, `GetUnitSource`);
- the library's search normalization;
- Recall Practice for review;
- the retry-mark pattern (append a row only on a change of state).

## 2. The record (VOC-005, VOC-011, VOC-013 to VOC-017)

`vocabulary_marks` holds `(concept_id, saved 0|1, created_at)`: one row per change of state. The
current state is the latest row.

`vocabulary_examples` holds `(concept_id, unit_id, entry_id, extraction_id, extraction_version,
created_at)`, `UNIQUE(concept_id, unit_id)`:
- each example records its source revision (its extraction and version) when saved;
- a Concept can have several examples, from different records.

| Rule | Decision |
|---|---|
| Stable key | `concept_id`. A repeat save of the same Concept is the same term (VOC-013); two Concepts with the same spelling and another meaning or scope are two terms (VOC-014) |
| What can be saved (VOC-011) | a Concept `concept_kind_view_v1` classifies as vocabulary, not retired, with an example unit among its CURRENT supporting units. Anything else is 409 with a code: `not_vocabulary`, `unit_not_supporting` or `concept_retired`. A rejected analysis is never extracted, and a suppressed or pending unit is not supporting, so neither can be saved (VOC-049) |
| Text (VOC-012) | nothing is copied or normalized for display: the Concept's target, the unit's exact wording (spacing and accents kept), and the learner's words are read live |
| Missing translation (VOC-016) | `meanings.en` / `meanings.zh` are `null` when not recorded. The page says "not recorded" (or "its language was not recorded" when both are null) |

### When what a term rests on changes (VOC-018, VOC-054 to VOC-059)

A saved term never disappears because its source changed. Each state is read live and shown.

| Change | What the learner sees |
|---|---|
| Newer extraction of the example's record | the example is shown as it was saved, labelled "a newer extraction exists" and, when its unit no longer supports the term, "no longer supports this term" |
| Unit suppressed or reassigned | that example: "no longer supports this term"; the others are unchanged |
| Every example superseded (Concept orphaned) | state "no current support"; no review offered, with the reason; the examples stay |
| Concept retired by a human | state "retired"; no new example can be saved (409 `concept_retired`); removing still works |
| Concept or source unreadable | that part says it can no longer be read; the rest of the term and the list stay |

**Older application versions** (VOC-139): a server without migration 022 starts on an upgraded
database. It reads everything it knew, ignores the two new tables, and answers 404 on `/vocabulary`
(`upgrade_check.py`).

## 3. API (private; not on the public demo allowlist)

| Route | Behaviour |
|---|---|
| `GET /vocabulary?q=` | `vocabulary_v1`: `saved` (count before the query), `items` sorted by the target accent- and case-blind, then exact text, then Concept ID (VOC-034). Search: each query token must prefix some token of the item (`concept_lexical_normalization_v1`, as the Knowledge Library) over the target, intent, scope, each example's wording, meanings EN/ZH, sentence, and the learner's question and context |
| `PUT /vocabulary/{concept_id}` `{"unit_id": N}` | save. 200 `{item, changed, saved_now, example_added}`; a repeat is `changed: false` (VOC-022) |
| `DELETE /vocabulary/{concept_id}` | remove. 200 `{concept_id, saved: false, changed}`; a repeat is `changed: false` (VOC-029); 404 when never saved |

**Errors:** 400 bad input; 404 an unknown Concept or unit; 409 not savable, with `code`; 503 not
wired.

## 4. The page and the Frontend contract (VOC-006 to VOC-010, VOC-072)

`web/src/pages/Vocabulary.tsx` (`VocabularyBook`) holds every control. Today it is mounted by the
Mistake Notebook's existing **Vocabulary** mode (Workbooks' own file), so no app-shell change is
needed. The existing Concept list (`ConceptKinds`, moved unchanged to its own file) gets a Save
action and a "saved only" filter. Grammar and Unclassified are unchanged.

**Frontend route contract**, confirmed by the workspace shell lane on 2026-11-21 with their
corrections applied:

```tsx
// workbenchViews.ts (shell lane): view "vocabulary", #/vocabulary, tab "notebook.mode.vocabulary",
// in KEPT_VIEWS, Practice group after Mistake Notebook; title app.vocabulary.title / subtitle app.vocabulary.subtitle
<VocabularyBook onOpenConcept={(conceptId) => openConcept(conceptId, { kind: "vocabulary" })} />
```

- **One mount only:** the shell passes
  `<MistakeNotebook onOpenVocabulary={() => show("vocabulary")} … />`. The notebook then has no
  Vocabulary tab of its own, and a `modeRequest` for `vocabulary` calls `onOpenVocabulary`, so
  `VocabularyBook` exists once and its IDs stay unique. Without the prop (this branch alone), the
  notebook keeps its Vocabulary mode. This came from the shell lane's combined-tree finding
  ("double mount").
- **`onOpenConcept`:** optional. Without it, Concept names are plain text and there is no "Open in
  the Knowledge Library" control.
- **Stable IDs** for returning focus:
  - `vocabulary-word-<conceptId>`: a saved term's "Open in the Knowledge Library" control;
  - `vocabulary-approved-<conceptId>`: the approved list's Concept button.

  IDs on the page never repeat (vitest).
- **Kept mounted and hidden** with the `hidden` attribute: the component does no layout reads.
  Focus restoration only calls `focus()` in an animation frame. Search, filter and an open review
  or source survive.
- **Headings:** the page starts at h2 (the shell's h1 is the section title); terms are h3.
- **Styles:** layout and wrap rules only, under `.vocabulary-*`, with no colours. Type uses the
  shell's tokens with fallbacks (`--headword-size`, `--headword-weight`, `--source-line`).
- **Title wording sent to the shell:**
  - en: "Vocabulary" / "Terms you saved from your approved Concepts, with their examples and their sources."
  - zh: "词汇" / "你从已批准的概念中保存的词语，附有例子和来源。"
- **Public demo:** never mount it there. Its routes are not allowlisted, and
  `TestVocabulary_NeverInThePublicDemo` pins that.

## 5. The persistence gate (VOC-020, VOC-070, VOC-094)

The save is server-backed in this branch, on any database that runs migration 022. Before it
reaches the owner's daily database:
1. **Confirm the migration number 022.** No other worktree claimed 022 at the start; R4's practice
   storage proposal only *proposed* 022 and was never allocated.
2. **Approve activation on real learner data.** Take a backup first (`flh-daily.sh backup`). The
   rollback is restoring that backup, and it loses only vocabulary rows written after it.
3. **Rebuild the public demo artifact** (Demo and Release). The demo checks its ledger against the
   embedded migrations. The two new tables are classified empty for the demo
   (`internal/publicdemo/database.go`).

## 6. Decisions (reversible)

| # | Decision | Why | Reverse |
|---|---|---|---|
| V1 | A new additive migration instead of browser storage | Learner data must survive backup and restore, and be private and durable | Drop the tables (rollback SQL in §5's backup path) |
| V2 | Concept ID as the key; examples by (Concept, unit) | Identity is the Concept, never text; several examples per term | — |
| V3 | Save from the Vocabulary view picks the preferred unit when it supports the Concept, else the first supporting unit; "Add an example" adds others | One click to save; more examples are explicit | Show a chooser on every save |
| V4 | Removal is a mark; examples stay | Removal never loses history; a re-save restores the examples | — |
| V5 | Review is the existing Recall Practice, hosted in the page, with an exit label for Vocabulary | Reuse; nothing is stored; one optional prop on Recall Practice | Remove the prop and use its default label |
| V7 | Focus after a save or a removal waits for the re-read list (numbered re-reads) | A browser run caught focus going to a row about to disappear, after a removal | — |
| V6 | The list re-reads every saved Concept and example source on each read | Truthful states (retired, superseded, missing) without copies; personal scale | Cache, if the list grows large |

## 7. FAQ (VOC-030, VOC-147)

- **What does "Remove from my vocabulary" do?** It takes the term off your saved list, and nothing
  else: its examples, the Concept, the extracted knowledge and any history stay. Saving it again
  brings it back with the same examples.
- **What if I save the same word twice?** If it is the same Concept, nothing changes; you keep one
  row. If the same spelling has another meaning (another Concept), it becomes a second term.
- **What if I save the same Concept from another record?** The record is added as a second example
  of the same term.
- **What if the save times out?** Retry. Saving twice never adds a second copy.
- **What if I remove a term twice, or one already removed?** Nothing changes, and the page says so.

## 8. Acceptance matrix for edge-case identities (VOC-110)

**Rules:** identity is the Concept's (`normalizeField`: lowercase, whitespace collapsed; no
Unicode, apostrophe or accent folding). Search uses `concept_lexical_normalization_v1`:
lowercase, NFD, combining marks removed, non-letters as separators, tokens of two letters or more,
prefix match. Every text round-trips byte for byte.

| Case | Saved as | Search finds | Shown as | Evidence |
|---|---|---|---|---|
| `chat` (French) and `chat` (English loanword) | two terms (two Concepts, scopes differ) | `chat` → both, in Concept-ID order; `loanword` → only the English one | each with its scope | Go identity-edge test; browser |
| `aujourd’hui` and `aujourd'hui` | two terms | either spelling → both | exactly as written | Go identity-edge test |
| `café` (NFC) and `cafe` + U+0301 (NFD) | two terms | `café`, NFD, `cafe`, `CAFÉ` → both (NFD sorts first by exact text) | each in its own form | Go identity-edge test |
| `faire  la grasse matinée` (double space in the wording) | one term, target `faire la grasse matinée` | `matinee`, the full phrase, `睡懒觉` | the wording with its double space | Go identity test; browser |
| A long phrase with punctuation, with a 1,500-character context | one term | any of its words (`cordes vraiment`) | exactly; wraps at 320 px | Go identity-edge test; browser |
| The same Concept from two records | one term, two examples | — | both examples, the first first | Go examples test |
| `apporter` with another meaning | two terms | `apporter` → both | each with its scope | Go identity test |
| A grammar Concept | refused 409 `not_vocabulary` | — | — | Go refusal test; replay |
| A one-letter query (`x`) | — | 400 (no searchable term) | — | Go search test |

## 9. A short review journey with expected states (VOC-130)

| Step | Expected state |
|---|---|
| 1. "Review amener" on a saved term with two supporting units | Recall Practice opens on its selection screen; nothing is preselected; the page names the Concept |
| 2. Choose two questions and start | card 1 shows the learner's own question; the stored answer and the source link are not on the page |
| 3. "Reveal stored explanation" | the answer appears, labelled as a reference; "Open the original source (record #N)" appears |
| 4. Self-check "Recalled", then card 2 "Try again" | a repeated press records nothing twice; the summary reads Recalled 1, Try again 1, Skipped 0 |
| 5. The second pass | only the question marked "Try again" comes back |
| 6. Open a source from a revealed answer, then come back | the review returns to the same card |
| 7. "← End the review and return to my vocabulary" | focus is on that term's Review button; the list and the query are unchanged; nothing was stored |
| 8. Review the same term again | a fresh session: nothing selected, no card |

Tests: vitest (cue and reveal, two answers, restart); browser (open and end).

## 10. Interoperability with Extraction's vocabulary reference (VOC-131 to VOC-133)

**Provisional.** These comparisons use the extraction lane's **unpublished**
`flh_vocabulary_reference_v1` example (`xsubject_v1/expected/vocabulary/terms-music-thirds.json`,
synthetic music theory in English), copied read-only into scratch. **Real integration is pending**
its publication, and nothing here claims cross-lane verification.

| Their field | Workbooks today | Round-trips into a saved item? |
|---|---|---|
| `unit_id` (`k-…`, the extraction lane's own namespace) | `unit_id` is an FLH `knowledge_units` integer, with the Concept as the key | **no**: no mapping exists; their units would first have to be imported as FLH units and Concepts |
| `term` (from "TERM = VALUE") | the unit's `canonical` wording | yes, as the wording |
| `value` | part of the unit `statement` | no separate field |
| `definition` (the reviewed claim) | the unit `statement` (meaning) | yes, as the meaning |
| `evidence[]` {`field`, `start`, `end`, `quote`} | the whole learner record (`original_input` / `original_context`) and its extraction version | partly: the field names match FLH's, but offsets and quotes are not stored or highlighted. Source navigation is preserved at record level |
| `recall[]` {`kind`, `prompt`} (cloze prompts, no answers) | review is Recall Practice over the learner's own questions | no: there is no cloze template (VOC-047's "no eligible review" message would apply) |

**Findings:**
- Workbooks marks terms `lang="fr"`. A non-French subject (their music theory) would be mislabelled;
  the language would have to come from the source.
- Their entries contain no learner answers, as Workbooks requires.

**Fields that round-trip from evidence into a saved item today (VOC-132):**
- the learner's original question and context (exact);
- the unit's wording, its meaning (EN/ZH) and example sentence;
- the extraction id, version and extractor;
- the Concept identity and state.

**Unsupported (VOC-133):** evidence offsets and quote spans, and recall prompt templates. Source
navigation is preserved through the unit source read, which opens the whole record and labels its
extraction version.

## 11. Save and remove wording, reviewed (VOC-145)

| Text | Why it is unambiguous |
|---|---|
| "Save to my vocabulary" / "Save {term} to my vocabulary" | names the destination; never just "Save" next to other notebook saves |
| "In my vocabulary" (tag on an approved row) | a state, not a button |
| "Remove from my vocabulary" / "Remove {term} from my vocabulary" | names what is removed and from where, not "Delete"; the announcement adds "Its examples and history are kept." |
| "{term} was already in your vocabulary; nothing changed." / "{term} was already removed; nothing changed." | a repeat is reported, never silent |
| "The server did not answer, so the save may or may not have been recorded. Retrying is safe…" | says what is unknown, and that retrying cannot duplicate |
| "← End the review and return to my vocabulary" (Recall Practice hosted here) | replaces "return to concept #id", which would have been wrong here |

Chinese: 保存到我的词汇, 已在我的词汇中, 从我的词汇中移除, 结束复习，返回我的词汇. The same
distinctions hold, and every placeholder is filled (vitest).
