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

The ten minutes: read the questions (1), first listening (3), second listening
(2), check with the app's reveal or the teacher debrief (2), a new short
transfer dialogue and one sentence of your own (2).

## Good to know

- Every question can be answered from its dialogue alone; the 2026-11-11
  evidence audit removed the few that relied on the unit's reading text.
- A script imported before a correction keeps its earlier wording; nothing is
  rewritten in your lessons.
- A script's questions are fixed: the app never replaces them with
  model-generated ones.
