# FLH-152 part 3: learner-facing revision fixes (2026-11-17)

Follows `FLH-152-WORKBOOK-REVISION-UPGRADE.md` (items 1–40). Items 41–52.
**Synthetic data only:** the FLH-152 snapshot (seeded by the pre-revision
build `c53b42c`) on disposable copies, and a variant pack (VC) built from a
copy of the sources: u01 options rotated, u05 long text, u06 question 3
deleted, u08 questions 2 and 3 swapped, u10 question 2 deleted and question 7
moved ahead of question 5. No Git command, deployment or provider call. The
restore work is recorded separately (`FLH-152-PART3-RESTORE.md`).

Real Chromium 131.0.6778.33 at 390×844 (touch), English and Chinese.

## 41–43. Retry cards, same question, two revisions

Reproduced on the part-2 build in both languages: the two cards for u05-l04
(saved on revisions 1 and 2, same answer) were identical before reveal.

Fix (`MistakeNotebook.tsx`): each retry card shows the item's source line
before reveal. For a workbook script it names the revision: **Workbook
script, revision 1, question 4** / « 练习册脚本第 1 版，第 4 题 ». It names no
answer; reference and explanation still appear only after reveal. Each card
reveals only its own explanation, and **Open source** opens its own revision
(revision 1 → **Revision 1: the version you saved from**; revision 2 → the
current lesson, question marked).

## 44–46. Unsaved answers and the update

The lesson counts the questions answered or self-checked on the page
(`ExerciseView` → `LessonScreen`). When there are any, the preview says
**You have answered 3 questions on this page. Answers are not stored, so
updating clears your answers: save any missed points you want to keep
first.** (Chinese: « 你在这个页面上已回答 3 道题。… »). With none, nothing is
added. **Not now** and a stale-preview refusal (409) keep the answers, and the
fresh preview still warns; the update then clears them. Saved mistakes (with
their saved answers) and the learning-records export are identical before and
after, apart from `latest_version`.

## 47. One name for a script's versions

For a workbook script, the Notebook source line, the newer-version note and
the lesson's "opened from the Mistake Notebook" banner now say revision /
« 第 N 版 », as the lesson does (they said "transcript version", « 文字稿版本 »
and « 转写稿第 N 版 »). YouTube lessons keep "transcript version".

## 49–51. Renumbering after a deletion

A question whose only change is a new number that the removed or added
questions before it explain is an ordinary shift. Shifts collapse into one
entry (**7 other questions are renumbered; nothing else in them changes.**)
whose **Show the new numbers** lists each (**Question 4 of revision 2 is now
question 3.** …) in order of the new number. They are left out of the
before/after details (no content changed). A question moved any other way
keeps its own entry: swapping questions 2 and 3 lists both moves and no
summary; in u10, question 7's move is its own entry while the 5 shifts are
summarised.

## 52. Long previews

u05's long text and u06's deletion, with the details and the summary
expanded: no horizontal scroll and nothing past the screen edge at 390×844
and at 640×450 (a 1280×900 window at 200%), in both languages. A phone at
200% (195 px wide, below the 320 px reflow minimum) also fits.

## Results

| Check | Result |
|---|---|
| Items 41–52 walk, part-2 build | 8/20 before it stopped: 41 reproduced, old labels, no warning, no summary |
| Items 41–52 walk, final build | 36/36 |
| Items 21–40 walk (incl. the two failed retry cases), final build | 45/45 (two expectations updated for the new labels and the summary's extra tab stop) |
| `ListeningRevisions.test.tsx` | 10 passed; the 3 new and 2 updated tests fail on the part-2 sources |
| `make verify` | exit 0: Go 24 packages; 44 frontend files / 496 tests; build |
| FLH-152 rehearsal / upgrade walk | 67/67 twice / 63/63 |

## Not verified

Safari, Firefox, a real phone, a screen reader (keyboard and focus only);
desktop width for the retry cards.
