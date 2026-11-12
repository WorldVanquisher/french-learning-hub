# Listening evidence audit (v1, 2026-11-11)

**Self-review by the authoring model (Claude Code, claude-opus-5-5), not
independent validation.** No teacher or native speaker has reviewed it.

## Question

Can each of the 120 listening questions be answered, and its explanation and
wrong-answer reasons checked, from its own script alone? A script-only lesson
in the workbench and a study pack read aloud give the learner the dialogue,
never the unit's reading text.

## Method

1. Automatic, per question, against its own unit's script
   (`python3 -m flh_workbooks audit`): evidence excerpts occur exactly once in
   the cited line; every wrong-option reason cites a script line; no reference to
   the reading text (`p1`, …); numbers and clock times in explanations and
   reasons occur in the script (a value found in the reading text but not in the
   script means the question relies on reading context); no question's stem or
   options show another question's short answer (all choices are on screen
   before reveal).
2. By hand: every question, its answer, evidence, explanation and reasons were
   read against the script (dump of all 12 scripts and 120 questions).

`check` now runs step 1 and fails on any reliance on the reading text, broken
evidence, uncited reason or cross-question clue.

## Findings and changes

17 items in 10 units changed. No item ID, script line, option order or answer
position changed; the canonical workbook, the reading pack adapter and the
embedded listening pack were regenerated with `python3 -m flh_workbooks build`.

**Relied on the reading text (5):**

| Item | Problem | Change |
|---|---|---|
| u05-l04 | Explanation "Work ends before the 18:30 class": the class time is only in the brochure (p1) | Explanation rests on s5 (finishes work at 17:30) and s1 (evening course), and says the dialogue gives no class time; evidence adds s1 |
| u01-l08 | Reason for « Dans la cour » cites "the advert" (p2) | Reason cites the basement bike room (s9) |
| u07-l05 | Reason for « Chloé lui a acheté des billets » says "Entry is free" (only in p1) | Reason: no tickets are mentioned; his reason is his cousin (s6) |
| u08-l10 | Reason "The rules are the same for the city (s11)": not in s11; the reading even gives different collection days by area | Reason rests on s1 and s11; no choice by neighbourhood is mentioned |
| u11-l10 | "13 euros (starter and main)": which menu is hers comes from the reading's menu (p1) | Now an inference from the dialogue: Hugo takes the full menu (s7), Inès no dessert (s6); of the two menus named (s10) the full one is the dearer; evidence adds s6, s7; kind `detail` → `inference` |

**Reasons that cited no line or overreached (4 items):** u01-l03, u01-l06 (absence
claims now cite the line that gives the actual answer), u02-l07 (one reason
cited nothing; the other claimed "all replacement coaches leave from there",
which s2 does not say).

**Evidence that did not cover the answer (3):** u04-l05 (the month comes from
s7: evidence added), u06-l10 (the "quick solution" is s9: evidence added),
u02-l10 (the first coach at 6:00 is s8: evidence added).

**One question gave away another's answer (5 items, before reveal):**

| Clue | Answer given away | Change |
|---|---|---|
| u02-l10 option « Prendre le car de 6 heures. » | u02-l08 « à 6 heures » | « Prendre le premier car du matin. » |
| u03-l10 option « … pas de carte Vitale … » | u03-l08 « sa carte Vitale » | « Il n'a pas de mutuelle et ne peut pas payer. » |
| u06-l08 option « Un livreur la reprendra jeudi. » | u06-l06 « jeudi » | « Un livreur la reprendra en même temps. » |
| u10-l07 option « Le bureau 3 est fermé ce jour-là. » | u10-l08 « bureau 3 » | « Le bureau est fermé ce jour-là. » |
| u11-l03 option « … plus cher que la soupe. » | u11-l04 « la soupe » | « Elle coûte plus cher que les autres entrées. » |

**Wording that matched the script better (3):** u02-l05 and u02-l07 now say
times as the script does (an hour and a quarter, 7 o'clock), u11-l01 says the
dialogue does not name the place.

## Judgement calls kept

- u04-l04 « Il a vécu six mois en Irlande » from « six mois à Dublin »: general
  knowledge (Dublin is in Ireland).
- u11-l10 assumes the full menu costs more than the shorter one.
- u11-l01 « Dans un café »: the dialogue shows a waiter taking an order; of the
  three places offered only a café fits.
- u05-l05 option « 120 euros, le tarif réduit »: the amount comes from the
  reading (p3), but it is a wrong option and its reason rests on the dialogue
  (s6, s7, s8).
- Names in stems (Lina, Mei, Inès, Hugo, M. Leroy…) are not spoken in the
  dialogues; the stem introduces them, as in the printed workbook.
- Five rows read "script, restated or computed value": u01-l02 (11:30 for
  « onze heures et demie »), u02-l07 (8:15 computed), u04-l05 (9 for
  September in Chinese), u06-l02 (48213 for « 48 213 »), u07-l02 (1 p.m. for
  13 heures).

## Effect on lessons already imported

An imported script is immutable. A lesson imported before this audit keeps its
earlier wording and stays listed as imported; importing it again is `409
script_conflict` and writes nothing; Mistake Notebook items saved from it keep
resolving to the words they were saved from. Scripts imported afterwards get the
corrected wording. Pinned by
`TestListeningScripts_EarlierImportKeepsItsContentAfterAPackCorrection`.

## Answer context check (added 2026-11-12)

`audit.answer_context` (run by `audit` and by `check`) looks at the answer
itself: the correct option, or the reference answer and every accepted
alternative. Its anchors are the tokens a listener must have heard to give
that answer: numbers and codes (« 180 », « A2 », « 3e »), clock times, day
and month names, and capitalised words after the first (names, places). Each
anchor must be said by the script: literally (accents and case folded), as
the same number in words or grouped digits (« quatre jours », « troisième
étage », « 48 213 »), or as the same time. An anchor found only in the unit's
reading text, or nowhere, fails the check unless `REVIEWED_ANSWER_CONTEXT`
records a person's judgement; an entry that is no longer needed also fails.

Result on the 120 questions: 83 anchors, 80 in a cited line, 2 in another line
(u10-l01 « M. Martin »), 1 reviewed (u04-l04 « Irlande », general knowledge,
see above), 0 errors. The deliberately bad fixture
`tools/workbooks/tests/fixtures/answer_context_bad.json` must fail with three
errors (a day and a time only in the reading text, a city never said) while
its two controls pass (a number said in words, a name in a cited line):
`python3 -m flh_workbooks audit --doc tests/fixtures/answer_context_bad.json --out DIR`
exits 1.

**Still needs a person** (the check does not claim to detect these):

- answers that paraphrase content words (« Elle travaille la journée » for
  « je finis le travail à 17 h 30 »): whether the paraphrase follows;
- inferences that rest on general or cultural knowledge without a named
  anchor (a price that is "expensive", a place that "must be a café");
- whether a restated or computed value is the one meant (8:15 from 7:00 plus
  an hour and a quarter; « 3e » for « troisième »);
- anything the written script cannot carry: intonation, irony, hesitation;
  these scripts have no audio, so a reader may change what is heard;
- the plausibility of the wrong options, and whether a stem's names (not
  spoken) are enough to follow who is who.

## Update (2026-11-12): earlier imports can be updated explicitly

The section "Effect on lessons already imported" above describes the contract
when this audit was made. Since 2026-11-12 a lesson imported before a
correction still keeps its wording and is never rewritten, but the workbench
says a corrected version exists, shows a preview of what changes, and on an
explicit confirmation adds the corrected text as the lesson's next revision.
Mistake Notebook items stay linked to the revision they were saved from
(ARCHITECTURE.md §4.3, "Pack corrections, revisions and explicit updates").
