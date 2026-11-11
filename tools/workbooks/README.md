# tools/workbooks

Build, check and render the synthetic workbooks in `content/workbooks/`. It uses
the Python 3 standard library only. Run every command from this directory.

```bash
python3 -m flh_workbooks build            # authoring modules -> content/workbooks/*.json and adapters/
python3 -m flh_workbooks check            # quality gates; generated files must equal a fresh build
python3 -m flh_workbooks render --out DIR # student/teacher Markdown + printable HTML, listening script, checklist
python3 -m flh_workbooks report --out DIR # inventory and machine-critique flags (reading/listening)
python3 -m flh_workbooks scan --workbook rl|pw --html STUDENT.html [--pdf-text T] [--pdf-info I]
python3 -m flh_workbooks capture --question u05-r05 --text "the learner's own question"
python3 -m unittest discover -s tests     # 20 stdlib tests
```

The Go side is `internal/reading/workbook_adapter_test.go`. It validates the
reading-pack, learner-lesson and writing adapters with the server's own parsers.

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
