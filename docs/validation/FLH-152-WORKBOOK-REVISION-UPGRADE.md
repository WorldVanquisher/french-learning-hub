# FLH-152: workbook revision upgrade rehearsal (2026-11-17)

Baseline `198b23f14489c26cef6ea1c34f96714c843f00db` (after #151, the workbook
script revisions). No Git command was run; nothing was committed, pushed,
deployed or run against the daily instance or its data; no provider was
called. No earlier FLH-152 handoff existed, so every item starts here.

**Evidence kind.** Everything below is **synthetic-fixture evidence**:
disposable databases written through the real HTTP API by real binaries on
loopback, with a fake key and a loopback fake provider. **No real backup or
production database was read**, so there is no real-backup evidence; the
daily database's own upgrade is still unrehearsed (see "Not verified").
Screenshots, logs, databases and JSON results are in the lane's evidence
directory outside the repository (named in the handoff).

Tools (this change): `scripts/validation/listening_workbook/upgrade_rehearsal.py`
(API and database), `upgrade_walk.py` + `upgrade_walk.mjs` (phone browser);
see the README there.

## 1–2. The flow and the pre-revision build

#151 adds, without a migration: `script_revision` on lesson reads,
`imported_revision`/`pack_status` on `GET /listening/scripts`,
`GET`/`POST /listening/materials/{id}/script-update` and
`GET /listening/materials/{id}/revisions/{n}` (ARCHITECTURE.md §4.3, A.15).
Earlier evidence (`LISTENING-SCRIPT-REVISIONS.md`: Go integration tests, a
real-browser walk from fresh scratch databases) never rehearsed snapshot →
upgrade → restore → re-upgrade.

Pre-revision build: `c53b42c` (its embedded pack predates the 2026-11-11
evidence audit; `go version -m`: `vcs.modified=false`). A fresh database from
it and from `198b23f` gets the same ledger (001–021) and the same schema.

## 3–4. Seed and snapshot

The old server imported all 12 scripts, saved mistakes on `u05` question 4
(the corrected one) and question 2, and prepared a YouTube lesson through the
fake provider with a mistake on it. The RELEASE.md Backup block made the
snapshot (integrity `ok`; 70 rows in 53 tables: 13 materials, 13 transcripts,
13 exercises, 3 entries/captures/sources, 1 preparation, 21 ledger rows),
which was then made read-only and checksummed.

## 5–14 and 19. API rehearsal (67 checks, twice)

| # | Result |
|---|---|
| 5 | Upgrading a copy: ledger, schema, every table and `sqlite_sequence` unchanged by start and a read; equal to a fresh install; `integrity_check` ok, `foreign_key_check` empty. |
| 6 | 10 of 12 scripts `update_available`, u09 and u12 `up_to_date`. u05: lesson still revision 1 with the old wording; preview 1 → 2 lists `u05-l04` (explanation, cited lines, cited words); reads write nothing; confirm 201 adds exactly one transcript version and one exercise. |
| 7 | The old mistake is identical to what the old build showed except `latest_version: 2`; it links exercise/transcript version 1 and keeps "Work ends before the 18:30 class."; revision 1 reads back the old build's lines and question; its evidence is in its cited line. |
| 8 | A new mistake on revision 2 links revision 2 and shows the corrected explanation; saving revision 1's item again is 409 `source_already_saved` naming the old entry. |
| 9 | The same confirmation again: 200, `replayed`, `Idempotency-Replayed: true`; nothing written. |
| 10 | Two simultaneous confirmations of one preview: one 201, one 200, one revision; a third later: 200. |
| 11 | Stale previews (unknown pack fingerprint; a revision the lesson never had; a preview taken before the server's pack changed; a revision-1 preview after the lesson moved to 2): 409 `stale_preview` with a fresh preview, nothing written, histories unchanged. |
| 12 | Re-import of the updated script: 200 replay. Whole catalog: updated and unchanged scripts 200, outdated ones 409 `script_conflict` naming lesson, revision and `update_available`. Up-to-date preview empty; its confirmation 200. Nothing written. |
| 13 | A pack that rotates the options of `u05-l02`: preview lists only that question's options, position 2 → 2; revision 3 keeps every question id and position, the reference answer, why-wrong notes, explanation and evidence; the answer moves from option 3 to 1. The old mistake on question 2 keeps revision 1's question, options and attempt; a new one links revision 3; earlier mistakes keep their revisions. Extra: a line correction appends a revision whose only line difference is that line. |
| 14 | YouTube lesson: `script_revision` null, transcript and exercises unchanged, script-update and revision routes 409 `not_authored_script` with nothing written, its mistake unchanged, explicit preparation still one fake call. No provider call during any script operation. |
| 19 | The RELEASE.md Restore block brought back a byte-identical database; the same flow on it (run B) gave the same 67 results and observations; the snapshot still verified against its SHA256SUMS. |

## 15–16. Phone walk (real Chromium 131.0.6778.33, 390×844, English and Chinese)

List → notice (no update button) → preview → **Not now** → preview → update →
reload → the old mistake opens revision 1; then a stale preview after a real
pack change, and a preview already applied by another client. All revision
copy is matched character for character on the page; the 48 revision keys
have equal placeholders in both catalogs; no English is left in the Chinese
revision UI.

Two defects in #151's update UI were found on the unmodified baseline (55/63)
and fixed in `web/src/pages/Listening.tsx` (63/63 after):

1. After an update (direct, after a stale preview, or "already"), the lesson
   reload put a phone back at the top: the outcome message sat at
   y ≈ 973–993 px on an 844 px screen, off-screen and unfocused. It is now
   focused (`tabIndex=-1`) and scrolled to the centre once the lesson has
   reloaded.
2. **Not now** removed the focused button and focus fell to `<body>`; it now
   returns to **Review the changes**.

`ListeningRevisions.test.tsx` has a test for both; it fails when the two focus
calls are removed.

## 17. The three new study packs (u01, u06, u12)

- Mechanical: `check` builds every pack with no error. An independent scan of
  each pack's sheets with 76–79 secrets per pack (transfer explanations,
  why-wrong notes, short-answer references and alternatives, productive
  model, debrief, the unit's explanations, why-wrong notes and typed answers):
  student checklists 0; reader sheets only answer words that the dialogue they
  carry says aloud (6, 3, 4); teacher debriefs all of them (positive control).
- Read by hand: every transfer answer is stated in the line it cites; the
  debrief facts match the unit scripts (u01 s7; u06 s5–s11; u12 s4, s8, s10,
  s11).
- For a human reviewer (not changed; the packs are unreviewed content):
  in u01, option B of x01 (« À l'arrêt de la pharmacie ») names the landmark
  that answers x02 (« à côté de la pharmacie »); in u12, the stem of x02
  (« Pourquoi vaut-il mieux éviter sa banque… ») rules out option A of x01
  (« Pour se connecter à sa banque »); u12-x01's « Pour quoi » (for what) may
  be read as a typo of « Pourquoi ». The audit's clue check looks for a whole
  answer repeated elsewhere, so it cannot see these.

## 18. Regeneration, twice

`render`, `report`, `studypack --all` and `audit` (each into two new
directories): identical files (12, 2, 49, 2); `check` exit 0 twice; `build`
built twice in memory equals itself and the 8 committed files.

## Extra: the pre-revision binary on an updated database

The `c53b42c` server on a copy of run A's final database (u05 at revision 3,
u01 and u03 at revision 2, six Notebook items over revisions 1–3): ready; no
migration recorded; the u05 lesson reads transcript version 3 with exercises
from all three revisions; all six Notebook items resolve to their own
revisions; re-importing u05 answers **200** and writes nothing, because the
old binary compares with revision 1, which is its own pack (the #151 handoff
had predicted 409); `integrity_check` ok. API only: the old workbench was not
opened.

## Observation not fixed (pre-existing, outside #151)

The RELEASE.md Restore block copies with `cp -a`, so a backup an operator made
read-only is restored read-only. The server then passes `/readyz`, the lesson
read and the preview, but the confirmation answers 500 and the server logs
nothing; after `chmod 600` the same confirmation is 201.

## Commands and results

| Command | Result |
|---|---|
| `python3 -I scripts/validation/listening_workbook/upgrade_rehearsal.py --old-server OLD --new-server NEW WORK` | exit 0; every stage PASS; 67/67 checks in runs A and B; run B equals run A |
| `python3 -I scripts/validation/listening_workbook/upgrade_walk.py SNAPSHOT NEW VARIANT WEB OUT TAG` | 63/63 with this tree's workbench; 55/63 with the baseline's |
| `npx vitest run src/pages/ListeningRevisions.test.tsx` | 6 passed; 1 failed with the fix's focus calls removed |
| `python3 -m flh_workbooks check`, `render`, `report`, `studypack --all`, `audit` (twice) | exit 0; identical outputs |
| `python3 -m unittest discover -s tests` (tools/workbooks) | 35 tests OK |
| `make verify` (private `GOTMPDIR`/`TMPDIR`, `NODE_OPTIONS=--no-experimental-webstorage`) | exit 0: Go fmt, tests (24 packages), vet, builds; 44 frontend files / 492 tests; production build. After items 21–40: exit 0, 44 files / 493 tests |

## Not verified

- A real backup or the daily database (synthetic databases only, by
  instruction). `upgrade_rehearsal.py` always seeds its own database; running
  its upgrade checks on a copy of a real backup would need an option to start
  from a given snapshot instead (not written).
- Safari, Firefox, a real phone (Chromium phone emulation only); desktop
  width was not rerun (the 2026-11-12 walk covered it).
- The old workbench on an updated database (the rollback above is API only).
- A teacher's or native speaker's review of the three packs.

## Items 21–40: what learners see around a revision update

Same evidence kind: **synthetic only** (the snapshot above, a second
variant pack, fault-injected copies). The exploration harnesses (API and a
phone walk in real Chromium 131, English and Chinese) live in the lane's
evidence directory; the regressions they found are in the regular suite
(item 39).

### 21. Before, during, after

| Stage | Where | What the learner sees |
|---|---|---|
| Before | Script list | "Imported", **Revision 1**, **Update available** |
| Before | Lesson | The wording they practised and a notice (**A corrected version… stays as it is (revision 1)…**) with **Review the changes**; no update button |
| Before | Notebook | Their items as saved; source line "Listening exercise #5 (transcript version 1), question 4" |
| During | Preview | Heading **revision 1 → 2**, one sentence on earlier practice, one entry per changed line or question with the changed fields, a closed **Show the exact before and after**, **Update this lesson to revision 2** / **Not now** |
| During | Preview, stale | An alert that the lesson or pack changed and nothing was updated, with the new preview; a preview already applied elsewhere says **already shows revision N** |
| After | Lesson | The outcome message, on screen and focused; **Revision 2**; no notice; new questions |
| After | Notebook | Old items unchanged plus **The source now has version 2. This item is shown as it was saved.**; **Open source** opens **Revision 1: the version you saved from**; new mistakes link revision 2 |
| After | Retry | Each card shows its own saved question, answer and reference |

### 22–24. Preview accuracy

- **22.** For all 10 outdated scripts, the preview listed exactly the lines,
  questions and fields that differ between the two stored revisions
  (compared field by field from `GET …/revisions/1` and `/2`, not from the
  server's diff): 17 changed questions in all, no changed line.
- **23. Defect, fixed.** A pack that deletes u06-l03 renumbered every later
  question, and the list read "Question 3 changed: position" … "Question 9
  changed: position", then "Question 3 of revision 2 is removed.": one number
  for two questions. Now: **Question 4 of revision 2 is now question 3.** …
  and **Question 3 of revision 2 is removed.**; the details label moved and
  removed questions the same way. A replaced question (u07-l05 → u07-l11)
  was already accurate: **Question 5 is new.** + **Question 5 of revision 2 is
  removed.**
- **24. Defect, fixed.** An unchanged pack offered nothing and appended
  nothing (as before). But a stored revision differing from the pack only in
  JSON the workbench never reads (an extra key, as another build might write)
  was listed **Update available** with an **empty** preview, and confirming
  appended revision 2, identical in substance, which every Notebook item from
  revision 1 then called newer. The stored revision is now fingerprinted as
  decoded (`domain.ListeningRevisionFingerprint`; ARCHITECTURE.md §4.3): up to
  date, empty preview, confirmation and re-import replay, nothing appended.

### 25–28. Cancelling, refreshing, two tabs, bookmarks

- **25.** After answering three questions, opening the preview and browsing
  every before/after pair, **Not now** writes nothing, keeps the lesson at
  revision 1, keeps the three answers and returns focus to **Review the
  changes**; the details start closed again. **Defect, fixed:** the details
  showed only the question, reference and explanation, so a change to the
  options, the why-wrong notes or the cited lines and words looked identical
  before and after; every changed field is now shown, as the reveal shows it.
- **26.** Reloading with the preview open returns to Home (the workbench keeps
  no screen in the URL); nothing was written, the lesson is still revision 1
  and shows the notice, not the preview; previewing again and confirming is
  201. Answers picked on the page and not saved are cleared by the update
  (0 of 3 kept), as by any reload (decision 2 below).
- **27.** The same preview in two tabs: the first confirmation 201, the second
  200 with **already shows revision 2**; one revision.
- **28.** The workbench URL never names a lesson or revision (always `/`). The
  API URL `…/revisions/1` reads the same after two more revisions apart from
  `current_revision`; `0`/`abc` 400, `4`/`99` 404, a YouTube lesson 409.

### 29–33. History

- **29.** The learning-records export rows of the old mistakes are identical
  after the updates; the capture lookup is unchanged; the entry's source still
  names revision 1's exercise and transcript version 1. The private workbench
  has no share link (listening is not in the public demo).
- **30.** Empty history (the old build imported every script, nothing else):
  the notice and update work; the Notebook and retry list stay empty; the only
  write is the update.
- **31.** Two mistakes on u05-l04 (revisions 1 and 2) differ in the Notebook
  list by their source line and the newer-version note. **Retry cards look
  identical before reveal** (same title, prompt and, here, answer), in both
  languages (decision 1).
- **32.** After revisions 2 and 3 (the third with a 282-character question),
  the revision-1 mistake still resolves to revision 1's question 4, its
  attempt and its evidence, grounded in revision 1's lines; **Open source**
  shows that question and, after reveal, « Je finis le travail à 17 h 30 ».
- **33.** Evidence stripped from the saved revision: the item still shows its
  own question with no evidence, nothing borrowed. The saved revision's
  exercise row deleted: that item says its source can no longer be read,
  revision 1 is 404, the other items still resolve. The saved item missing
  from its revision: "no longer yields that item". Nothing is ever replaced by
  another revision's content. No change needed.

### 34–36. Copy, keyboard, phone

- **34.** No numeric counts are shown; one entry per changed line or question.
  A deleted question lists every later question as moved (u06: 8 entries for
  one deletion; accurate, long). The new strings read correctly in both
  languages (« 第 2 版的第 4 题现在是第 3 题。»). Terminology differs between
  screens: **Revision N** / « 第 N 版 » in Listening, "transcript version N" /
  « 文字稿版本 N » and "The source now has version N" in the Notebook
  (decision 3). Changed lines keep the workbook's ids ("Line s2").
- **35.** Keyboard only: Enter on **Review the changes** focuses the preview
  heading; Tab reaches the details, then **Update…**, then **Not now**; Space
  opens the details; Enter on **Not now** returns focus to **Review…**; Enter
  on **Update…** answers 201 and focuses the outcome; focused controls show an
  outline.
- **36.** A 282-character question with a 70-character address, a
  253-character option and a 296-character explanation: no horizontal scroll
  in the preview, its details or the lesson, and no element past the screen
  edge, in English and Chinese.

### 37. Worked example (draft for the learner guide)

Question 4 of « À l'accueil de la Maison des langues », saved once before the
correction and once after it:

| | Saved on revision 1 | Saved on revision 2 |
|---|---|---|
| Source line | Listening exercise #5 (transcript version 1), question 4 | Listening exercise #14 (transcript version 2), question 4 |
| Prompt and reference | « Pourquoi l'horaire du soir lui convient-il ? » — « Elle finit le travail à 17 h 30. » | the same |
| Why | Work ends before the 18:30 class. | She finishes work at 17:30 (s5) and is enrolling in an evening course (s1), so the class comes after work. The dialogue gives no class time. |
| Note | The source now has version 2. This item is shown as it was saved. | — |
| Open source | **Revision 1: the version you saved from**, question 4 marked; evidence « Je finis le travail à 17 h 30 » (s5) | The lesson (revision 2), question 4 marked; evidence « cours du soir » (s1) and « Je finis le travail à 17 h 30 » (s5) |

Both stay; neither moves to the other's content. The old explanation is kept
because it is what was saved, even though the correction replaced it.

### 38–39. Regular checks and regressions

The three checks worth keeping in the regular suite (all now in it):

1. `TestListeningScriptRevisions_CorrectedPackExplicitUpdateEndToEnd` (Go,
   existing): nothing changes until the preview is confirmed; one revision is
   appended; old mistakes keep revision 1's words and link; new ones link
   revision 2.
2. `TestListeningScriptRevisions_StoredJSONOnlyDifferenceIsNotAnUpdate` (Go,
   new): an update is offered and appended only for a difference the learner
   can see. It fails on the 198b23f repository code.
3. `ListeningRevisions.test.tsx`, "names a moved question by both numbers…;
   the details show every changed field" (vitest, new): the preview the
   learner consents to is accurate. It fails on the previous `Listening.tsx`.

The phone focus test added earlier in FLH-152 stays too. The rehearsal and
walk scripts need real binaries and Docker, so they stay release-time checks.

### Decisions for the owner (learner-facing)

1. Retry cards of the same question from two revisions are identical before
   reveal. Show the source line (or **Revision N**) on retry cards?
2. An update clears answers picked on the page and not saved; the preview
   speaks only of saved items. Say so in the preview, or leave it?
3. One word for the same thing: **Revision N** (Listening) or "transcript
   version N" / "version N" (Notebook), in both languages.
4. A deleted question lists every later question as moved. Keep, or collapse
   into one line? (It only arises when a correction breaks the "keep
   positions" authoring rule.)
5. No bookmarkable lesson or revision URL in the workbench (a reload returns
   Home). Keep, or add one?
