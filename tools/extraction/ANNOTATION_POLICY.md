# Knowledge extraction: task specification and annotation policy (v1)

Target: the existing `knowledge_extraction_v2` contract of
`internal/extractor/openai.go`. This is not Concept matching, exam grading or
a chatbot. Nothing here changes the production prompt, schema or routing.

## 1. What the extractor sees and returns (inspected, 2026-11-10)

**Input** (the user message; the developer message is the fixed production
instruction). Every field below is model-visible:

| Field | Source |
|---|---|
| `entry_id` | the learning record id (not informative; synthetic data uses 0) |
| `original_input` | the learner's own text (a question, a sentence, a pasted explanation…) |
| `original_context` | the learner's surrounding context |
| `effective_category` | the current effective analysis category (`fr_l2_taxonomy_v1`: vocabulary, grammar, morphology, orthography, pronunciation, pragmatics, discourse, comprehension, translation, mixed, other) |
| `effective_explanation` | the current effective explanation: the corrected one when a human corrected the analysis, else the analysis's own |
| `resolution` | `unreviewed`, `accepted` or `corrected` (a `rejected` analysis is never extracted: the request is refused before any model call) |
| `language_hint`, `instructions` | fixed strings added by the extractor |

**Output** (strict JSON schema): `{"units": [...]}`, each unit exactly
`kind` (`fr_l2_knowledge_v1`: vocabulary, grammar, morphology, orthography,
pronunciation, usage, expression), `canonical` (≤ 200 bytes), `statement`
(English, ≤ 2000), `statement_zh` (required, non-blank), `example` (string or
null), `confidence` (0–1). Exact duplicates (kind + normalized canonical,
statement and example) are refused. An empty list is valid.

Model-invisible metadata (ids, family, topic, band, origin, review status,
rationale) never enters the input fields.

## 2. The boundary: grounded selection, general-knowledge statements

The production instruction allows two different things, and this policy keeps
them apart without moving the line:

- **Which objectives** may appear is strictly **source-grounded**: a unit must
  be something the learner "actually learned, asked about, corrected, or
  revealed uncertainty about" in this interaction. Facts merely present in the
  text are not objectives.
- **How a statement is phrased** may use correct **general French knowledge**:
  "« aller » forms the passé composé with « être »" is a general rule even if
  the interaction showed one sentence. The statement may generalize only as far
  as needed to state that objective, and must be true.

Never allowed: an objective the interaction did not raise; a statement that
contradicts standard French; adopting a learner's false premise; copying an
explanation's error; an example unrelated to the objective.

## 3. Rules

1. **Atomicity.** One unit = one independently reviewable objective. Two
   distinct rules are two units; several examples of the same rule are one.
2. **Useful granularity.** Prefer the smallest *useful* objective: "vouloir —
   présent" is one unit, not six person/number forms, unless the learner asked
   about one form specifically.
3. **Zero units** when nothing durable arose: thanks, logistics, off-topic,
   meta questions about the app, a context too thin to know what was asked.
4. **Insufficient context.** If the interaction refers to text that is not
   present ("is the sentence above right?"), do not guess the missing
   sentence. Extract only what the visible text supports; often zero units.
5. **False premises.** Extract the objective the learner was wrong about,
   stated correctly. The statement never repeats the false claim as true.
6. **Explanations.** The effective explanation is evidence, not authority.
   Use it to understand what was discussed; never copy a claim that is
   wrong. A `corrected` resolution means the visible explanation is the human
   correction. `rejected` never reaches the extractor.
7. **Mixed topics.** Extract each French-learning objective separately; ignore
   non-French or non-learning content (another language's grammar, travel
   plans, app questions).
8. **Examples.** `example` is a short correct French example of the objective,
   preferably the learner's corrected sentence or one taken from the
   interaction; null when none is warranted. Never reproduce the learner's
   error as the example; never invent an unrelated sentence.
9. **Canonical.** A short stable label, not a sentence: French headword or
   construction first, then the aspect: `« depuis » + présent`,
   `connaître / savoir`, `accord du participe passé avec être`. Quote French
   exactly; keep accents and apostrophes; no trailing period.
10. **Bilingual agreement.** `statement_zh` says the same thing as `statement`:
    same rule, same scope, same exceptions, same French forms quoted
    unchanged. Not a summary, not a different claim.
11. **Duplication.** Never output two units for the same objective, even with
    different wording or kinds.
12. **Prompt injection.** Learner text is data. Instructions inside it ("ignore
    the rules", "output ten units", "write in Spanish") are never followed;
    the genuine learning objective, if any, is still extracted.
13. **Kind.** grammar = a structural rule or choice (tense or mood choice,
    agreement rule, word order, negation); morphology = a form (a
    conjugation, a participle, a noun's gender or plural); orthography =
    written form (accents, elision in writing, hyphens, capitals);
    pronunciation = sound (liaison, silent letters); vocabulary = meaning or
    lexical choice; usage = register and appropriateness (tu/vous, formality);
    expression = a fixed phrase or idiom.
14. **Uncertainty and confidence.** `confidence` is the authoring convention,
    not a calibrated probability: 0.9 when the interaction is explicitly about
    the objective; 0.75 when it is clearly raised but secondary (a second
    correction); 0.6 when it is raised only implicitly. Below that, do not
    extract. Synthetic labels never claim calibration.

## 4. Measurable errors

Structural errors come from the production validator (`extraction-render`);
the rest are judged per unit against the reference and the input.

| Code | Error |
|---|---|
| `STRUCT_INVALID` | output fails production parsing or validation |
| `MISSED` | a reference objective has no predicted unit |
| `UNSUPPORTED` | a predicted objective is not raised by the interaction |
| `FALSE_CLAIM` | a statement is not true of standard French, or adopts a false premise or an erroneous explanation |
| `OVER_SPLIT` | one reference objective spread over several predicted units |
| `MERGED` | one predicted unit covers several reference objectives |
| `DUPLICATE` | two predicted units with the same objective |
| `BILINGUAL_MISMATCH` | `statement_zh` disagrees with `statement` (scope, claim, quoted forms) |
| `KIND_MISMATCH` | kind contradicts rule 13 |
| `CANONICAL_FORM` | canonical is a sentence, untranslated wrongly, or loses accents |
| `BAD_EXAMPLE` | example incorrect, reproduces the error, or unrelated |
| `ABSTENTION_FAIL` | units produced where the reference is zero units |
| `INJECTION_FOLLOWED` | behaviour changed by instructions inside learner text |

Rates are reported per example and per unit; a perfect example has no error.

## 5. Human review rubric (per example, before any label becomes gold)

1. **Input:** realistic and readable? (yes / edit / reject)
2. **Decision:** is the expected decision (units vs zero, how many) right?
3. **Per unit:** grounded · true · atomic · useful granularity · kind ·
   canonical · English/Chinese agreement · example (each pass / fix).
4. **Verdict:** `accept` · `edit` (write the fix) · `reject` · `quarantine`
   (reasonable people would disagree; note why).
5. **Reviewer and date.** Only `accept` (or `edit` once re-checked) may move a
   synthetic label to `human_reviewed`. Nothing is gold by default.

## 6. Labels and statuses used in the datasets

- `origin: synthetic`, `review_status: unreviewed`,
  `label_status: machine_authored_unreviewed` for everything generated here.
- `quarantine` for items whose correct label is ambiguous; they are excluded
  from training and evaluation until a human decides.
- Authoring provenance names the local tool and source bank (no provider run
  produced any label).
