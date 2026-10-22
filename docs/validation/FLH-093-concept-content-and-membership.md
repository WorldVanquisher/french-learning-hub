# FLH-093 — Make Concept membership understandable

Owner: NAS Claude Code. Continues in the same working tree as FLH-092; the
FLH-092 launcher and manual (`scripts/validation/flh092/`,
`docs/validation/FLH-092-workbench-browser-acceptance.md`) are unchanged.

**Status: implemented. Validated with jsdom component tests and an isolated
loopback API fixture only.**
- **No browser:** no browser was run, so browser behaviour is unverified.
- **No acceptance claimed:** this is not browser acceptance and not
  semantic-quality acceptance.
- **Owner evidence:** the owner reported no failure on the frontend paths
  exercised so far. That is recorded here as reported, not as acceptance.

## 1. Problem

During owner browser use, Concept Review showed identity fields and the
fixture's synthetic Unit text. It did not show what a destination Concept
contains, so a SAME decision could not be judged on content.

Each card showed:
- target, intent and scope;
- the signature;
- the preferred unit as a bare ID.

It showed none of the Concept's current supporting statements, examples or
original questions.

The three Units per record came from the FLH-089 fixture stub. Real extraction
already produces zero or more Units, and nothing here assumes a count.

## 2. Contract choice: no backend change

The existing read-only Knowledge Library endpoints already carry the
authoritative content:

| Need | Endpoint | Authority |
|---|---|---|
| A Concept's content | `GET /knowledge-library/concepts/{id}` | Fields: `preferred_unit`, `supporting_units` (derived current support: current extraction + active admission + CURRENT SAME), `non_supporting_members`, `historical_units` |
| A unit's original question | `GET /knowledge-library/units/{id}/source` | Any unit: the entry's original input and context, its extraction version, `in_current_extraction` |

What did not change:
- no endpoint, DTO, schema, migration or dependency;
- no API client change: `getLibraryConcept` and `getLibraryUnitSource`
  already existed for the Knowledge Library;
- no change to Concept identity, SAME, NEW CONCEPT, reassignment, eligibility
  or the unknown-outcome rules.

## 3. Behaviour

**Reads only.** Every view below is a GET, and starts only when the reviewer
asks for it by expanding, selecting or opening a source. The views create no
annotation and call no provider.

| Area | Behaviour |
|---|---|
| Unit card | Leads with the canonical name, the knowledge **statement**, the **example** and the **kind**, then "From learning record #N" (paged queue) |
| Unit source | **Show the original question for unit #N** opens the original input (line breaks kept) and context inline, with whether the extraction is current. Inline, so the queue position, search text, selection and identity draft are untouched |
| Technical details | Unit ID, confidence, identity features and signature are under a collapsed **Technical details** section (also on candidate cards and Concept content) |
| Candidate card | Leads with target, type and scope, then the support tag and **concept #N**. **select this concept** is unchanged; **Show what concept #N contains** expands the content (on-demand read) |
| Concept content | Target, type, scope and a support sentence. Then the **Preferred explanation**, only when a person chose one, labelled with whether it also currently supports the Concept. Then current supporting units, three first, with **Show all N** / "Showing 3 of N." Each shows its statement, example, provenance (unit, kind, record, extraction version, admission) and its own original question |
| Not support | Filed-but-not-supporting members (older extraction, suppressed admission, waiting) and historical units (INVALID, moved away, older) are only **counted**, with a pointer to the Knowledge Library. They are never shown as evidence |
| States | Loading (`status`); no current support ("No unit currently supports this concept…"); Concept not found (404, `status`); failed read (`alert` with the server detail and **Retry**); unexpected response shape, reported as a failed read rather than breaking the page |
| Stale answers | A response for a Concept or unit that is no longer requested (selection changed, panel closed, unmounted) is discarded |
| Compare before deciding | Top of the right column, beside the unit card, so the unit text is not repeated. With a selection: the selected Concept's content, plus what SAME does ("files this unit … as one more piece of evidence. The unit, its statement and its original record stay unchanged; nothing is merged or deleted"). When the unit already has CURRENT SAME elsewhere, the move it would make. Always: what NEW CONCEPT does |
| Reassignment | In a unit's **Corrections**, selecting a target shows "What concept #N currently contains" with the same component. Confirmation, eligibility, re-read and unknown-outcome handling are unchanged |
| Languages | All new text is in the English and 简体中文 catalogs (placeholder parity tested). Learner content, IDs and decision words are not translated |

## 4. Files

| File | Change |
|---|---|
| `web/src/components/ConceptContent.tsx` | New: `ConceptContent`, `UnitSourceDisclosure`, `MembershipComparison`, a stale-safe on-demand read hook, and response-shape checks |
| `web/src/components/CandidateConceptCard.tsx` | Readable layout, content toggle, technical details collapsed |
| `web/src/components/UnitCard.tsx` | Statement first, inline source, technical details collapsed |
| `web/src/pages/ReviewQueue.tsx` | Renders `MembershipComparison` at the top of the right column |
| `web/src/pages/UnitCorrections.tsx` | Shows the selected reassignment target's content |
| `web/src/i18n/en.ts`, `web/src/i18n/zh-CN.ts` | `content.*`, `compare.*`, `unitCard.fromRecord`, `correction.targetContent` |
| `web/src/styles.css` | Small appended block for the new views |
| `web/src/ConceptMembership.test.tsx` | New: 11 tests (§5.1) |
| `web/src/UnitCorrections.test.tsx` | One added reassignment test |
| `scripts/validation/flh093/{run.sh,check.py,stub_extractor.py}` | New isolated API fixture (§5.2) |
| `README.md`, `README.zh-CN.md` | One clause each in the Concept Review feature bullet |
| `web/README.md`, `docs/LOCAL_LEARNING_WORKFLOW.zh-CN.md`, `docs/ARCHITECTURE.md` §7.1 | Short descriptions of the new reads |
| This report | — |

## 5. Validation

### 5.1 Frontend (jsdom; synthetic French content authored for the tests)

`web/src/ConceptMembership.test.tsx` (11 tests, all passing):
- **Support only:**
  - the preferred unit is shown once;
  - three of the other four supporting units are shown, then **Show all 4**;
  - an older-extraction member and an INVALID historical unit are never
    rendered, only counted;
  - technical details are collapsed;
  - every request is a GET.
- **No support:** an orphaned Concept states that it has no current support.
- **Read states:** loading, 404 not found, and 500 failure, then **Retry** and
  success.
- **Malformed response:** an unexpected response shape is reported as a failed
  read.
- **Late answer:** a late answer for Concept 40 after the selection moved to 41
  is discarded.
- **Reassignment wording:** shown when the unit already has CURRENT SAME
  elsewhere.
- **Source:**
  - nothing is read before opening;
  - opening reads the source with one GET;
  - line breaks are kept;
  - an extraction that is not current is labelled;
  - closing removes the view;
  - a failed source read is retried only when asked.
- **Concept Review integration:**
  - the reviewer types a search text and edits the identity draft;
  - opens and closes the unit's source;
  - expands a candidate and opens a supporting unit's source;
  - selects the candidate and sees the comparison;
  - the position ("unit 1 of 2"), search text and identity draft are all kept;
  - every call so far is a GET;
  - **SAME → selected** then sends exactly
    `POST /api/knowledge-units/9/concept-links/same {"concept_id":40}`, the only
    write.
- **Selection change while pending:** selecting 40 (slow), then 41, shows 41,
  and the late 40 answer is discarded.
- **Failed detail read in the queue:** an error alert, and SAME stays available,
  since the decision remains the reviewer's.

`web/src/UnitCorrections.test.tsx`, one added test:
- selecting a reassignment target shows its supporting statement and that
  unit's original question, with no write;
- the confirmed reassignment still sends exactly
  `PUT /api/knowledge-units/201/concept-membership {"concept_id":8}`.

The existing NEW CONCEPT, SAME, reassignment, INVALID, outcome and recovery
tests pass unchanged.

### 5.2 Isolated API fixture (authored French content, synthetic)

`bash scripts/validation/flh093/run.sh <empty dir outside repo>`:
- **Isolation:** runs the server and a local stub inside `unshare -rn`
  (loopback only), with a fresh database and `env -i`.
- **Content:** five questions about *ne … plus*, *ne … jamais* and
  *ne … guère*. One has a line break.
- **Decisions, all explicit:**
  - NEW CONCEPT A, then SAME for three more units;
  - a preferred unit is chosen;
  - Concept B is created and a unit is reassigned from A to B;
  - INVALID on one A member;
  - a second extraction of one A member's record;
  - NEW CONCEPT C, then INVALID on its only unit.

Result: **17 PASS, 0 FAIL**:
- **Multiple Units join one Concept:** four units support A, and each unit's
  source is still its own original question.
- **Current support only:**
  - A's current support is only the current, admitted, filed unit;
  - the preferred unit is the one chosen;
  - the older-extraction member is filed but not support;
  - the INVALID unit and the reassigned unit are history only, and the
    reassigned one names B;
  - none of them appears as support.
- **B and C:** B's support is the reassigned unit. C is orphaned, not deleted,
  with its target kept.
- **Sources intact:**
  - every original question and context is unchanged after SAME, reassignment
    and INVALID;
  - the line break is kept;
  - the old unit's source is labelled non-current, the new one current;
  - no unit statement was merged or rewritten.
- **Inspection is read-only:** the reads the workbench makes (Concept details,
  all sources, catalog, queue, resolution, membership) changed **no database
  row** (per-table counts) and made **no provider call** (stub call log).

### 5.3 Commands

| Command | Result |
|---|---|
| `cd web && npx tsc -b --noEmit` | passed |
| `cd web && NODE_OPTIONS=--no-experimental-webstorage npx vitest run` | 22 files, **292 tests passed** (280 before + 12 new) |
| `bash scripts/validation/flh093/run.sh <scratchpad>/flh093/run1` | 17 PASS, 0 FAIL |
| `NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0: gofmt, `go test ./...`, `go vet ./...`, server and capture builds, frontend typecheck, tests and production build |

`make verify` rebuilt `web/dist`, which is git-ignored, so the FLH-092 launcher
now serves this UI.

## 6. Remaining gaps

- **Browser:** layout of expanded content inside the scrollable discovery list
  (520 px), keyboard flow through the new toggles, and long-text wrapping are
  unverified.
- **Unpaginated detail:** `GET /knowledge-library/concepts/{id}` is complete
  but unpaginated. A Concept with very many members returns them all in one
  response; the view renders three and states the count. Server-side bounding
  would be a contract change.
- **Duplicate reads:** expanding a card and selecting the same Concept reads it
  twice. There is no client cache, by choice, so a decision never leaves a
  stale view behind.
- **Not shown inline:** filed-but-not-supporting and historical units are
  counted, not listed. The Knowledge Library lists them with reasons, but there
  is no direct link from Concept Review to that Concept's library page.
- **Language quality:** none of this judges the quality of extracted
  statements. The fixture content is authored and synthetic.

## 7. Short walkthrough (when the owner next uses the workbench)

1. Start a session, for example with the FLH-092 launcher.
2. Open **Concept Review**:
   - read the unit's statement and example;
   - choose **Show the original question for unit #N**, then hide it: the
     position and search text are unchanged.
3. On a candidate, choose **Show what concept #N contains**:
   - check the preferred explanation, if any, and the current supporting
     statements;
   - open one supporting unit's original question.
4. Choose **select this concept**: **Compare before deciding** shows the
   Concept beside the unit and explains SAME. Decide SAME or NEW CONCEPT
   explicitly.
5. From a record's resolved unit, open **Corrections** and select a
   reassignment target. Check "What concept #N currently contains" before
   confirming.
