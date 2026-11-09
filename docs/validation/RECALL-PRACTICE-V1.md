# Recall Practice v1 — validation

Owner: Claude Code (sole implementation owner). Date: 2026-11-08 (UTC).
Branch: `feat/concept-recall-practice` (prepared by the owner).

**Status: implemented and tested in jsdom.** It has not yet been seen in a real
browser or used with real daily data; the owner walkthrough is in
[DAILY_USE.md](../DAILY_USE.md) §8.

## 1. Gap and scope

The Knowledge Library was browse-only. A Concept's detail shows its title, every
statement and example, and the source links at once, so nothing supported trying
a question first and checking afterwards.

What was added: a private recall practice that starts from Concept detail.
- **Choosing:** the learner chooses up to 5 of their own original questions from
  the Concept's current support.
- **Answering:** each question is shown with the answer hidden.
- **Reveal:** shows the unit's stored statement (following the Explanation-language
  preference), its example and its original source.
- **Self-check:** Recalled / Try again / Skip, with one second pass over the
  Try-again items.

Behaviour: [web/README.md](../../web/README.md) (*Recall practice*); design note:
[ARCHITECTURE.md §9.2](../ARCHITECTURE.md#92-concept-detail-and-source-view).

**Contract impact: none.** There is no route, DTO, schema, migration, provider,
dependency, scheduler or public-demo change. The view uses only
`GET /knowledge-library/concepts/{id}` and
`GET /knowledge-library/units/{id}/source`.

## 2. Authority and privacy

| Rule | How it is enforced | Test |
|---|---|---|
| Only current support is offered | Candidates are the backend's `supporting_units` (first 10); each source read must still show current extraction, `active` admission, not INVALID and `current_concept_id` = this Concept | first and fourth tests |
| Excluded evidence is never read | Older-extraction members, relations and historical or reassigned units are not candidates, so their sources are not requested | first and second tests |
| A failed read is never a card | 500 → alert with **Retry**, 404 → "not found", blank question → "no question text", moved / INVALID → reason; none has a checkbox | fourth test |
| The learner chooses | Nothing is preselected; Start stays disabled until one is chosen; at most 5 | first test |
| The answer stays hidden | The card shows only the question: no title, statement (either language), example or context | second test |
| The reveal is a reference, not a grade | Labelled "Stored reference explanation … not a grading rubric"; nothing compares the attempt | second test |
| Explanation-language preference | The reveal uses `StoredText`; switching to 中文 or English re-renders in place | third test |
| Attempt text stays on the page | Component state only; the test spies on `Storage.prototype.setItem` and every console method and inspects every request | second test |
| Reads only | Every request in the session is a GET, including the source opened from practice and a new selection | second and fourth tests |
| Not in the public demo | `KnowledgeLibrary` passes no practice entry when `demo` is set | seventh test |

## 3. Authored fixture

`web/src/test/recallPracticeFixture.ts` is typed against the wire types. It
holds Concept #21 "pronom « en »", currently supported by two different
original questions:
- record #31 « J'en ai deux » (its context gives the answer away);
- record #32 « Tu veux du café ? — Oui, j'en veux ».

Around them:
- an older-extraction member of record #31 (unit #204);
- a unit first filed here and then reassigned to Concept #22 "pronom « y »"
  (unit #205);
- a RELATED unit (#206);
- the unrelated Concept #22.

All text is synthetic.

## 4. Commands and results

Run in `~/workspace/flh-nas-claude` with Node v26.13.0 (hence the documented
`NODE_OPTIONS=--no-experimental-webstorage`) and Go 1.27.3.

| Command | Result |
|---|---|
| `cd web && npx tsc -b --noEmit` | exit 0 |
| `cd web && NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/pages/RecallPractice.test.tsx` | **7 passed**. The first run had 1 failure, a test-scoping error: the question text appears both on the source screen and in the hidden practice card. The assertion was scoped to the source's record section |
| Mutation checks, each restored afterwards: drop the "moved" re-check; offer practice in the demo; write the attempt to `sessionStorage`; show the statement with the question | each made exactly **1 test fail**; 7/7 again after restoring |
| `set -o pipefail; NODE_OPTIONS=--no-experimental-webstorage make verify` | first run **exit 0**. It was rerun after three review fixes: a single read sequence for stale-answer discarding, a fresh re-read on **Choose questions again**, and focus moving to the revealed material. Final run **exit 0**: gofmt, Go tests (all 18 packages cached; no Go file changed), vet, builds, typecheck, **26 files / 329 tests passed** (322 before + 7), production build |

## 5. Limitations

- **The reveal is the unit's stored statement.** Reusing it does not establish
  its linguistic quality, and practising does not demonstrate learning gains.
  Nothing judges the attempt.
- **Nothing is remembered.** There is no score, schedule, history or mastery
  state. Leaving practice, opening another Concept or reloading discards the
  session.
- **Bounded and unshuffled.** At most the first 10 supporting units, in Library
  order, and 5 per session.
- **The question is the record as written.** It may give its own answer away.
  The learner decides whether to use it, and the context is shown only on the
  source screen.
- **jsdom only.** The flow has not been driven in a real browser. The packaged
  browser smoke does not cover practice.
