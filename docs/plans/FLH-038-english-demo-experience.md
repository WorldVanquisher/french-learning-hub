# FLH-038 English-first Knowledge Library demo

**Problem.** In human acceptance, the owner completed all six manual demo steps,
but found that the French grammar titles and explanations were hard to follow.
This task makes the existing demo readable for an English-speaking recruiter or
learner. It keeps the French examples and source provenance, and changes no
behaviour.

**Scope limits.**
- English is the only display language.
- There is no language selector, translation API, translation storage,
  migration, or Chinese UI.
- Search, ranking, authority rules and API semantics are unchanged.

## Interface copy (`web/src/pages/KnowledgeLibrary.tsx`)

The data flow is unchanged and the page still makes only GET calls.

| Concept | Old wording | New wording |
| --- | --- | --- |
| Membership | CURRENT SAME member | A unit **filed under** a Concept (CURRENT SAME kept in parentheses) |
| Support | Current support | **Currently supporting this concept** |
| Membership without support | Current members that do not provide support | **Filed here but not supporting** |
| Relation | Current relations | **Linked units**; a link is not filing and gives no support |
| History | Historical evidence — not current | **History: no longer current** |
| Preferred unit | Preferred representation | **Best explanation (preferred unit)** |

Membership versus support is defined once, under the Concept header.

**Results page**
- A two-sentence introduction explains concepts and units.
- Each result reads "N units filed here, M currently supporting". A
  unit-wording match says "Found in the … of a unit filed here, not in the
  concept's title. Being filed here does not mean the unit supports the concept".

**Concept page**
- The Status row explains the state in a full sentence.
- "Not supporting" reasons are plain: older extraction; "The learner hid it
  (admission suppressed)"; "waiting for review".
- History notes say "This unit was moved: it is now filed under concept #6", or
  "later marked INVALID: judged not to be a usable unit". The raw last decision
  follows.

**Source page**
- The heading reads "Where unit #N came from: learning record #M".
- A one-line explanation says what an extraction is.
- Extraction selection reads "selected automatically" or "pinned by a person".
- Review status reads "corrected by a person (feedback #…)". The rows are
  "Explanation used", "Before correction" and "Produced by".

**French examples** render as "French example:" plus a `lang="fr"` span.

**IDs.** Concept, unit, record, extraction, link and event numbers, plus the
lifecycle and support fields, stay in small print.

## Synthetic fixture (`seed.py`, `stub_extractor.py`)

Only freshly seeded demo databases are affected.

**What changed**
- Rule names and explanations are English, with French terms glossed:
  « bien que » (although), subjonctif, passé composé.
- Every example sentence is unchanged French.
- The learner records are English questions quoting French.
- The record 2 correction and the admission note are English.

**What stayed the same**
- The extraction phrases, the v1→v2 rewording and every API step are unchanged.
- The seven cases and every Concept, unit, record and extraction ID are unchanged.

**Concept titles** are English and stored in lower case, because the backend
normalizes identity. The French term stays in the identity:
- `mood: subjunctive (subjonctif)`;
- `trigger (déclencheur): …`;
- scope `overview (vue d'ensemble)`.

**Compatibility with the FLH-035 harness.** The titles were chosen so that
browse order, tie order and every search expectation in
`scripts/validation/flh035/verify_integrated.py` still hold (replayed
read-only; see validation). In particular:
- "subjunctive forms of faire" keeps `irreg` a unit-wording match;
- no unit text uses "subject", so `subj subj` stays the four subjunctive Concepts.

## Walkthrough (`walkthrough.mjs`, `docs/DEMO.md`)

- Assertions follow the new copy and titles.
- W2 also checks that `subjunctive` and `subjonctif` return the same Concepts.
- W3 and W6 check that French examples render, including the `lang="fr"` span.
- `page.setDefaultTimeout(8000)` makes a failing step report quickly.
- `docs/DEMO.md` has the English fixture table and the eight-step English
  walkthrough.

## Files

- `web/src/pages/KnowledgeLibrary.tsx`, `web/src/pages/KnowledgeLibrary.test.tsx`
- `scripts/demo/flh034/seed.py`, `scripts/demo/flh034/stub_extractor.py`, `scripts/demo/flh034/walkthrough.mjs`
- `docs/DEMO.md`, `README.md`, `README.zh-CN.md`
- `docs/plans/FLH-038-english-demo-experience.md`, `docs/validation/FLH-038-english-demo-experience.md`

**Not touched:** the demo lifecycle and process guards (`demo.sh`,
`proc_guard.py`), the backend, migrations, harnesses, manifests, AGENTS.md,
`App.tsx` and `styles.css`.

The "Labels" bullet in `docs/plans/FLH-034-knowledge-library.md` still quotes
the FLH-036 wording ("member unit wording"). That file is outside this task's
ownership.
