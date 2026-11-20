# From a French question to reviewed practice: one page (prototype, synthetic data)

Everything here runs on the extraction lane's sealed synthetic fixtures. Nothing is stored. The
practice visit lives in the page and disappears on reload, until the owner decides the storage
(`docs/plans/PRACTICE-STORAGE-DECISION-SHEET.md`).

## Steps

1. **The French question (extraction lane).**
   - The learner said « Oui, j'en vais. » to "Tu vas à la boulangerie ?" and was corrected.
   - The extraction prototype grounds the claims in the learner's own words (`ev-…` IDs).
   - The learner approves the supported items in one batch and rejects the claim that is not in
     their text.
   - Practice is built from the approved items only, and `practice feed` writes
     `flh_practice_review_feed_v1`. That lane's sealed handoff is `extraction2-20261119/handoff-2.1`.
2. **Checked before use (Workbooks).**
   - `build_fixture.py --handoff H` takes the feeds byte for byte. It derives the grading keys with
     the sealed code, which first has to reproduce the sealed bundle.
   - The page re-hashes all 21 documents. A changed byte stops it
     (`docs/validation/PRACTICE-FIXTURE-SOURCES.md`).
3. **Review Today.**
   - Show the practice prototype. Today's practice lists three items:
     - « Tu reviens du marché ? » (missed last time);
     - « Tu sais nager ? » (missed);
     - a choice last answered outside the options.
   - Below them come the two approved concepts as `practice` rows, with reason
     `practice_outcome`.
4. **Practice.**
   - Start the first item: the answer field has focus.
   - Answer « Oui, j'y reviens. »: "Not yet", a known confusion. Save it as a mistake to practise
     later.
   - The next useful exercise is recalling the rule. The source stays closed until the recall
     is done.
   - Self-check "I had it". The learner's quoted words appear, marked.
   - Leave a new sentence to inspect its evidence, come back with the draft kept, and answer it:
     "Correct". Repeating the check does not count twice.
5. **Share.**
   - "What you are about to share" names the study packet `pk-afdb387f3af6`, its source revision
     (`fd55a3600f1c`) and what it holds.
   - Copy it. It has no answer key and none of the visit's answers.
6. **The source changes.**
   - Revision 2 arrives while a check is in flight. It waits, and is then applied.
   - The five exercises are withdrawn and explained, the drafts are kept, and the late check is
     refused.
   - Once the learner re-approves in the extraction tool, revision 2 offers the same five IDs
     again ("restored").
7. **Another tutor.**
   - Session 1 (Codex): its return is classed c1 candidate (accepted in the tool), c2 duplicate,
     c3 exercise (preview only).
   - Session 2 (Claude Code) continues it: q1 conflict, q2 candidate, q3 duplicate, q4 unknown
     reference.
   - Accept q2 for this visit only, after a confirmation that shows the change and the real
     `practice accept` command.
8. **Review.**
   - This visit's log groups practice by skill and by local day.
   - Every entry says whether it was an exact match, your judgment, a reveal or an agent
     suggestion.
   - Export it as JSON, without answer texts unless you ask.
   - Reload: everything is gone, as every part of the page said.

## Run it

```bash
python3 -I scripts/validation/practice_feed/walkthrough.py "$(mktemp -d)" --handoff ~/flh-handoff/extraction2-20261119/handoff-2.1
# by hand: build the server and the workbench, start it on an empty database,
# open #/today -> "Show the practice prototype (synthetic data)…"
```

## Limits

- The extraction steps (1) are that lane's, read from its seal. The agents' returns are
  hand-written fixtures; no agent was run.
- The French is synthetic A1/A2 and needs a native-speaker check.
- The revision steps use a prototype control ("Simulate the next feed"), not a live feed.
- Interaction counts and timings come from scripted runs on one machine, not from learners.
