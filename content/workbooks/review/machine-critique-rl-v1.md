# Machine critique: reading/listening workbook v1

**What this is:** a machine review by the same model that wrote the material
(Claude Code, claude-opus-5-5, 2026-11-10). It is a self-review, not independent
expert validation, and no French teacher or native speaker has read the workbook.
The workbook stays labelled synthetic and unreviewed.

## Method

1. **Structural gates** (`python3 -m flh_workbooks check`). Every question has
   evidence that occurs exactly once in its paragraph or line. Distractors carry
   bilingual reasons, and Chinese text is present. No option is duplicated. The
   correct option is the longest in at most 40% of single-choice items. Answer
   letters are balanced, with no run longer than 3.
2. **Heuristic flags** (`python3 -m flh_workbooks report`):
   - negative stems;
   - distractors that overlap the evidence more than the key does;
   - distractors that appear verbatim in the text;
   - keys that share no content word with their evidence.
3. **Reading pass:**
   - every text and every item of units 1–6 (written in an earlier part of the session);
   - every non-detail item of units 7–12;
   - the texts of units 7–12 as they were written.

## Defects found and fixed

| Item | Problem | Fix |
|---|---|---|
| u02-l07 | Key said the 7:00 coach would arrive « trop tard »: 7:00 + 1 h 15 = 8:15, before the 8:30 appointment | Key now « Il arriverait trop juste pour son rendez-vous » (matches the explanation) |
| u05-r05 | Distractor « 145 euros, livre compris » was defensible (120 € + 25 € book) | Replaced with « 100 euros, avec la carte d'étudiant » |
| u02-r01 | Ungrammatical stem « Que annonce… » | « Qu'annonce ce texte ? » |
| u01 p5 | « le week-end du 23 et 24 août » | « des 23 et 24 août » |
| u02 p4 | A free-phone number that could belong to a real line | « au numéro gratuit affiché en gare » |
| u08-l | Resident voiced as 70, but the service she gets is for over-75s | Voice direction « 75–80 ans » |
| u04-r08, u03-l05, u08-r02, u08-r03, u09-l01 | Evidence did not show the whole key | Longer or additional excerpts |
| u09-l06, u10-l01 | Distractor reasons referred to facts outside the dialogue | Reasons rewritten from the dialogue only |
| u12-r08 | Chinese explanation had no Chinese | Fixed |
| units 1–3 | Correct option was the longest in 27/42 items (length clue) | Options rebalanced: 12/42 |

## Flags kept, with reasons

- **Distractor appears verbatim** (u02-l05, u02-l10, u03-l05, u04-l10, u05-l03,
  u07-r05, u09-r03): deliberate "heard but wrong" traps. Each is wrong in
  context, and its reason cites the line.
- **Distractor overlaps the evidence more than the key** (u01-r07, u01-r10,
  u05-l05): lexical traps such as « courses… ensemble ». The key is a paraphrase.
- **Negative stems** (18): all are "why not…" or selection questions (« Quel
  article ne peut pas être retourné ? »). None is a "which is NOT true" trick.
- **Key shares no content word with evidence** (paraphrase): checked one by one.
  Each key follows from its excerpt.

## Known limits

- French naturalness, level fit and distractor plausibility have not been
  measured with learners. Bands are authoring targets.
- The listening scripts have not been read aloud or recorded. Some lines may be
  hard to follow at natural speed.
- One vocabulary-in-context item exists (u01-r05). Kinds are mostly detail.
- Four vocabulary entries are lemma forms of words that appear inflected in the
  text (« contenir » / « contient »). The gate reports this as a note only.
