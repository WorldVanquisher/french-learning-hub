# Public demo example data and discovery (2026-11-19, items 031–040)

**Scope.** The examples the public demo offers, how they are chosen, and how
a package is checked against them. Artifact `97dbe0f215af37e7` (real-model
E5 vectors, synthetic data), served by a package built from this tree.
Nothing here needs an embedding call; every suggested search is a keyword
search.

## Inventory of the pinned artifact (031)

The package serves:
- 14 Concepts (13 active, 1 orphaned);
- 16 current member units, all currently supporting;
- 11 source records, all synthetic (`scripts/demo/flh073/fixtures/catalog.json`,
  `data_classification: synthetic`);
- 9 semantic presets.

The lane tool `inventory.py` lists them all, with the demo feature that uses
each unit.

## Selection (032)

Each example and comparison illustrates a different learner intent:

| Entry | Learner intent | Units |
|---|---|---|
| example `y-en` | what two pronouns replace (a question in French) | #12, #13 |
| example `il-faut-venir` | why a verb form is subjunctive | #14 |
| example `en-train-de` | how to say "right now" (a false translation) | #15, #16 |
| comparison `imparfait-passe-compose` | choosing between two past tenses | #6, #7 |
| comparison `depuis-pendant` | a duration still going on vs a finished one | #9, #10 |

Each suggested search (033) shows one search behaviour:

| Query | Behaviour shown | Result on this artifact |
|---|---|---|
| `remplace` | found only in a unit's wording (`unit_evidence`) | Concept #12 |
| `subjonctif` | found in identity details | Concepts #2 and #1 |
| `tu me manques` | every word must match (3 words) | Concept #4 |
| `marché` | accents and case ignored (token `marche`) | Concepts #7 and #12, through their examples |
| `pass` | a word matches longer words it begins | Concepts #6 and #7 |
| `pronoms` | finds nothing; follow-up (034): search "pronouns" or open example `y-en` | 0, then 1 |

## One data file, checked at the package gate (035–038)

`web/src/demo/discovery.json` holds the example, comparison and query data.
The page reads it (`examples.ts`, `comparisons.ts`, `queries.ts`); titles and
labels stay in the i18n catalogs.

`scripts/validation/demo_candidate/check_examples.py BASE SPEC OUT` resolves
every entry the way the page does. It uses only GETs and writes
`examples.json` plus a support matrix. It runs as the package gate's new
`examples` stage.

**This run, against the package (036):**

| Feature | Entry | Supported | Resolves to |
|---|---|---|---|
| example | `y-en` | yes | unit #12 → Concept #12, record #9 |
| example | `il-faut-venir` | yes | unit #14 → Concept #1, record #10 |
| example | `en-train-de` | yes | unit #16 → Concept #14, record #11 |
| comparison | `imparfait-passe-compose` | yes | unit #6 → Concept #5, record #5 · unit #7 → Concept #6, record #5 |
| comparison | `depuis-pendant` | yes | unit #9 → Concept #8, record #7 · unit #10 → Concept #9, record #7 |
| query | `remplace` | yes | 1 result [12] |
| query | `subjonctif` | yes | 2 results [2, 1] |
| query | `tu me manques` | yes | 1 result [4] |
| query | `marché` | yes | 2 results [7, 12] |
| query | `pass` | yes | 2 results [6, 7] |
| query | `pronoms` | yes | 0 results; follow-up "pronouns": 1 |

**Negative control (037, 038).** A copy of the data file with five deliberate
faults exits 1, with one readable line for each:

```
FAIL example y-en: “pronouns” matches Concepts [12], whose supporting units include 0 with “y remplacé” in their wording (the page needs exactly 1)
FAIL example il-faut-venir: unit #14's question (record #10) differs from the one the start page quotes
FAIL comparison depuis-pendant: no unit with “pendant pour une durée finie” in its wording among the Concepts “pendent” matches (none)
FAIL query remplace: no result of tier identity
FAIL query pronoms: its follow-up search “pronominal” finds nothing
6/11 example entries resolve against artifact 97dbe0f215af37e7
```

## Provenance of the phrases the bundle keeps (039)

The bundle keeps only these French phrases from the catalog: the three
example questions (quoted verbatim on the start page), the seed wording, and
the suggested searches. `web/src/demo/DiscoverySpec.test.ts` checks the
following against `catalog.json`:
- each question is one record's `original_input`, verbatim;
- each seed is in exactly one unit;
- each suggested search's words occur in the catalog, except `pronoms`, which
  shows finding nothing.

| Phrase | Catalog source |
|---|---|
| question of `y-en` | entry `e-y-en`; seed `y remplace` → unit `u-y-lieu` |
| question of `il-faut-venir` | entry `e-il-faut-venir`; seed → unit `u-il-faut-venir` |
| question of `en-train-de` | entry `e-en-train-de`; seed → unit `u-en-train-de` |
| `imparfait pour le contexte`, `passé composé pour un événement` | entry `e-imparfait`, units `u-imparfait`, `u-pc-evenement` |
| `depuis avec le présent`, `pendant pour une durée finie` | entry `e-depuis`, units `u-depuis`, `u-pendant` |

## A data-only update against the existing build (040, prototype)

Done in a scratch copy of `web/`; the repository was not changed.
1. **The change:** one line added to `discovery.json`, a suggested search
   `en train` ("every word must match", 2 words).
2. **Checked first, against the existing package** (unchanged):
   `check_examples.py` gives 12/12.
3. **Rebuilt:** the web bundle, before and after the change. Only the entry
   script and `index.html` differ.
4. **Served:** the rebuilt page with the existing package's server binary and
   artifact, which are byte-identical.

**Result:** a fresh browser shows "Suggested searches (7)", and `en train`
finds Concept #14, with no write request. An edit that breaks an entry is
caught by step 2, before any rebuild.
