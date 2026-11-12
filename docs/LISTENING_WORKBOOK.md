# Studying with the workbook listening scripts

A short guide for the learner. Chinese: [LISTENING_WORKBOOK.zh-CN.md](LISTENING_WORKBOOK.zh-CN.md).
Contract: [ARCHITECTURE.md §4.3](ARCHITECTURE.md#43-listening-lessons-exam-listening-lesson-v1).

## Written scripts, not audio

The 12 workbook "listening" lessons are **written scripts**: dialogues with
speakers and line numbers (`s1`, `s2`…), written for someone to read aloud.
There is **no audio, no video and no timestamp**, and nothing in the app plays
or records sound. "Line 8" means the eighth line of the script, never a time.
The scripts and their questions are **synthetic and unreviewed** (no teacher or
native speaker has checked them), and the levels are targets, not certified
CEFR levels. A YouTube lesson (Listening → **Add a video**) is different: you
watch real audio on YouTube and paste your own transcript.

So that the exercise trains your ear, someone else reads the script to you
(**Show the script to the person reading it aloud** shows it to them, with no
answers), or you record it yourself and listen back without looking.

## One lesson, start to finish (phone or desktop)

1. **Listening → Workbook listening scripts → Import …** Importing calls no
   model and stores the lesson; importing again opens the same lesson.
   Imported scripts move to **Imported (N)** and open with **Open …**.
2. **Listen, then answer.** Choose an option or type a short answer. Nothing is
   sent while you answer, and your answers are not saved.
3. **Reveal answers and evidence.** The page moves to **Your answers and the
   reference**: one row per question with your answer beside the reference.
   A chosen option reads **Same as the reference** or **Different from the
   reference**; a typed answer reads **Short answer: compare it yourself**.
   This is a comparison on the page, not a score or a level.
4. **Go to question N** opens a question: why the reference is right, **Why
   not « … »** for each wrong option, the cited script line and the exact
   words. **I got it / I missed it** stay on the page.
   **Back to the answer overview** returns to the list.
5. **Save as a learning question…** on a point you missed: write what you
   missed or want to ask, optionally attach your answer, then **Save learning
   record**. Only this click sends something: one learning record whose
   context names the authored script ("no audio or video"), the question and
   the cited line.
6. **Reopen it later:** **Mistake Notebook → Show reference** shows the saved
   question, your answer and the reference; **Open source** opens the lesson
   with that question at the top of the screen and marked, also on another day
   or after a reload. The saved item always shows the wording it was saved
   from.

## When the workbook is corrected: revisions

Each imported script is a lesson with **revisions**. Importing creates
revision 1. When a later version of the app ships a corrected script, your
lesson does **not** change by itself: it keeps the words you practised until
you choose to update it, and an update only adds the next revision. Your
saved mistakes stay with the revision you saw.

### Worked example 1: a script imported before a correction

You imported **À l'accueil de la Maison des langues** before the 2026-11-11
correction and saved question 4 (« Pourquoi l'horaire du soir lui
convient-il ? ») as a mistake. Its explanation then read "Work ends before
the 18:30 class.", a class time the dialogue never says.

1. **Listening → Workbook listening scripts** lists it under **Imported**
   with **Revision 1** and **Update available**.
2. Open it. The questions are the ones you practised, with a notice: **A
   corrected version of this script is available. This lesson stays as it is
   (revision 1) until you review the changes and update it.** Nothing has
   changed yet, and nothing updates when the page opens.
3. **Review the changes** lists what differs without showing answers:
   **Question 4 changed:** *explanation*, *cited lines*, *cited words*. **Show
   the exact before and after** shows the old and new wording, including the
   reference answers, so open it after you have practised. One sentence says
   what happens to your earlier practice: it stays with revision 1.
4. **Update this lesson to revision 2**. The page says **This lesson now
   shows revision 2. Items you saved from revision 1 stay in the Mistake
   Notebook exactly as you saved them.** The new explanation rests on the
   dialogue only (« Je finis le travail à 17 h 30 » and « cours du soir »).
5. **Mistake Notebook → Show reference** on your question-4 item still shows
   the explanation and your answer as saved, with **The source now has
   version 2. This item is shown as it was saved.** **Open source** opens **Revision 1: the version you saved from**,
   with question 4 marked at the top; the lesson below it shows revision 2.
6. Saving question 4 again from revision 2 makes a new, separate item.

If the connection drops after you confirm, **Confirm the update again** is
safe: the server never adds a second revision. If the lesson or the app's
scripts changed after you opened the preview, nothing is updated and a fresh
preview replaces the old one. **Not now** leaves the lesson as it is.

### Worked example 2: a fresh import

You have never imported **Au guichet de la gare**. **Import Au guichet de la
gare** stores revision 1 with the current wording; the lesson shows no notice
because there is nothing to update. Importing it again (for example from **Next workbook
script: …** at the end of the previous lesson, or after a lost response)
opens the same lesson and stores nothing twice.

### Where the server still refuses (409)

These refusals change nothing; the workbench avoids them, but another client
calling the API would see them:

- importing a script again while your lesson is on an older revision:
  `409 script_conflict` (use the update above instead);
- asking the model to prepare questions for a script: `409 authored_script`
  (a script's questions are fixed);
- adding your own transcript to a script: `409 authored_script`;
- confirming an update from a preview that went stale: `409 stale_preview`
  (the workbench shows the fresh preview).

## Ten-minute study packs (printable)

For a session with a second person, build the packs (no app or model needed):

```sh
cd tools/workbooks
python3 -m flh_workbooks studypack --all --out /tmp/flh-study-packs
```

Each pack has three sheets: the **student checklist** (goal, plan, questions;
no script, no key), the **reader sheet** (the script to read aloud twice) and
the **teacher debrief** (key, evidence, reasons, debrief prompts). ★ marks the
questions that train the pack's goal.

| Pack | Goal |
|---|---|
| u02 Au guichet de la gare | Times and durations, and calculating with them |
| u05 À l'accueil de la Maison des langues | An enrolment: days, price and payment |
| u08 Réunion d'information à la mairie annexe | Following several speakers |
| u11 Commander avec une allergie | Reasons and what is not said directly |
| u01 Au téléphone : organiser la visite | Directions and an address: line, stop, landmark, number, floor |
| u06 Au service client : un colis abîmé | The problem, the solution offered and what to do next |
| u12 Podcast « Clic Clair » : des mots de passe plus sûrs | Advice: what to do, what to avoid, and why |

The ten minutes: read the questions (1), first listening (3), second listening
(2), check with the app's reveal or the teacher debrief (2), a new short
transfer dialogue and one sentence of your own (2).

## Good to know

- Every question can be answered from its dialogue alone; the 2026-11-11
  evidence audit removed the few that relied on the unit's reading text, and
  the check now also tests each answer (names, numbers, times, days) against
  the dialogue. A few judgements still need a person; they are listed in
  `content/workbooks/review/listening-evidence-audit-v1.md`.
- A correction never rewrites a lesson: you see what changed and choose
  whether to update (see above).
- A script's questions are fixed: the app never replaces them with
  model-generated ones.
- After **Reveal answers and evidence**, a short answer is yours to judge:
  mark **I got it** or **I missed it** right in its row of the answer overview
  (or under the question; both show the same mark). It stays on the page.
