# tools/workbooks

Build, check and render the synthetic workbooks in `content/workbooks/`. It uses
the Python 3 standard library only. Run every command from this directory.

```bash
python3 -m flh_workbooks build            # authoring modules -> content/workbooks/*.json, adapters/ and
                                          # internal/listening/pack/listening_scripts_v1.json
python3 -m flh_workbooks check            # quality gates; generated files must equal a fresh build
python3 -m flh_workbooks render --out DIR # student/teacher Markdown + printable HTML, listening script, checklist
python3 -m flh_workbooks report --out DIR # inventory and machine-critique flags (reading/listening)
python3 -m flh_workbooks scan --workbook rl|pw --html STUDENT.html [--pdf-text T] [--pdf-info I]
python3 -m flh_workbooks capture --question u05-r05 --text "the learner's own question"
python3 -m flh_workbooks studypack --all --out DIR      # every ten-minute listening study pack (below)
python3 -m flh_workbooks studypack --unit u05 --out DIR # one pack
python3 -m flh_workbooks audit --out DIR  # evidence audit of the 120 listening questions (below)
python3 -m unittest discover -s tests     # 28 stdlib tests
```

The Go side is `internal/reading/workbook_adapter_test.go`, which validates the
reading-pack, learner-lesson and writing adapters with the server's own parsers,
and `internal/listening/script_pack_test.go`, which checks that the embedded
listening script pack passes `ParseListeningScriptPack` and equals the workbook.

## Ten-minute study packs

`studypack --all --out DIR` builds every pack in `content/workbooks/study_packs/`
(`--unit ID` builds one). Each pack has its own practice goal and the unit
questions it focuses on (marked ★ for the student):

| Pack | Goal |
|---|---|
| u02 | Catch times and durations, and calculate with them |
| u05 | Understand an enrolment: days, price and payment |
| u08 | Follow several voices: who asks what, and which answer each one gets |
| u11 | Understand reasons and what is not said directly |

Per pack it writes:
- a student checklist: the goal, the ten-minute plan, the questions and the
  transfer questions, with no script and no key;
- a reader sheet: reading instructions, the voices and the scripts;
- a teacher debrief: the goal and focus questions, the key, the evidence, every
  wrong-answer reason, the vocabulary, the unit's follow-up, the transfer key
  and the pack's debrief prompts;
- `<unit>-verification.md`.

A pack file (`flh_study_pack_v1`) holds the goal (fr/en/zh), the focus question
IDs, the plan (ten minutes), the debrief prompts, an optional context line
quoted from the unit's reading text, and a short authored transfer exercise.
The output is deterministic (a test builds every pack twice and compares the
bytes).

The command fails when:
- an evidence excerpt does not occur exactly once in its line;
- a wrong-option reason cites no line, or a line that does not exist;
- a number or time in an explanation or reason is found only in the unit's
  reading text (the listener never hears it), unless the pack reads it aloud as
  its context line;
- the student checklist or reader sheet carries the key (the workbook scanner's
  checks; the teacher debrief must fail them, as the positive control);
- the student checklist contains the script, an evidence excerpt that no stem
  or option already shows, a short-answer reference or the transfer key.

A number or time found nowhere (for example 8:15 computed from 7:00 plus an hour
and a quarter) is flagged in the debrief for the teacher, not refused. No audio
is made: a person reads the script aloud. `check` builds every pack.

## Listening evidence audit

`audit --out DIR` writes `listening-evidence-audit.md` and `.json`: per
question, the evidence occurrences, whether every wrong-option reason cites a
script line, values restated or computed from the script, anything that relies
on the reading text, and the basis (`script`, `script, restated or computed
value`, `reading` or `error`). `check` fails on `reading` and `error`, and when
a question's stem or options show another question's short answer. Hand-made
judgements are in `content/workbooks/review/listening-evidence-audit-v1.md`.

## Quality gates

**Reading/listening:**
- Every question cites evidence that occurs exactly once in its paragraph or script line.
- Every wrong option carries a reason in English and Chinese.
- No option is duplicated.
- The correct option is the longest in at most 40% of single-choice items, to avoid a length clue.
- Answer letters are balanced, with no run longer than 3. The position seed is fixed.

**Writing/speaking:**
- Every task fits the API limits.
- Each writing sample fits its word range (Python twin of `domain.CountWritingWords`, cross-checked in Go).
- Each sample covers every content point with an excerpt that occurs exactly once.
- Retry corrections quote non-overlapping spans that occur exactly once and apply cleanly.
- Telephone numbers use ranges reserved for fiction.

## Student editions carry no key

`scan` fails if a student edition contains any of the following:
- explanations, wrong-option reasons, practice answers, retry corrections or samples;
- teacher markers;
- scripts, comments, `data-`/`aria-`/`title` attributes, embedded JSON or hidden content;
- extra `<meta>` tags;
- PDF metadata or attachments that would carry the above.

The teacher edition is the positive control: the scan must find its keys.

## PDFs

The PDFs in the handoff were printed with Chromium in a disposable
`node:22-bookworm-slim` container. Chromium, `fonts-wqy-zenhei`,
`fonts-noto-core` and `poppler-utils` were installed there with apt:

```bash
chromium --headless --no-sandbox --no-pdf-header-footer --print-to-pdf=OUT.pdf file:///work/IN.html
pdftotext OUT.pdf OUT.pdf.txt && pdfinfo OUT.pdf > OUT.pdfinfo.txt   # then: scan --pdf-text/--pdf-info
```
