# Workbook listening: real-browser study walkthrough

`walkthrough.mjs` drives Chromium (Playwright 1.49.1) through the private
Listening workbench at phone (390×844, DPR 2, touch) and desktop (1280×900)
widths:

- choose a workbook script and import it (`ls-wb1-u05` on the phone,
  `ls-wb1-u02` on desktop);
- attempt every question, one deliberately wrong;
- reveal: the answer overview (focus, one row per question, "Same" /
  "Different" / "compare it yourself", no total), **Go to question N**;
- save the missed point (`POST /captures`, `source: manual`,
  `listening_item` source) and **Back to the answer overview**;
- Mistake Notebook → **Open source** (the lesson still mounted), then a page
  reload → **Show reference** → **Open source** again (question at the top);
- no horizontal scroll, no key before reveal, no console error;
- the preparation boundary through the real API: `POST
  /listening/materials/{script}/exercises` must be `409 authored_script`,
  store nothing and leave the authored questions on screen; a YouTube lesson
  with a timed transcript must still prepare (local fake provider), reveal and
  link `0:00` to `&t=0s`;
- the overview heading in 简体中文.

`run.py` starts everything it needs and stops it afterwards: the local fake
provider (`fake_openai.py`, loopback, no key, no billing; it logs what it was
sent), the server binary with `-web-dir` on a random loopback port with a fresh
scratch database, an empty working directory (no `.env`) and a clean
environment, and a disposable `node:22-bookworm-slim` container (`--rm`, host
network) that runs the browser. npm and Chromium live in the Docker volume
`flh-listening-workbook-pw`. Nothing touches the daily instance or its data.

## Reproduce

Needs Go, Node with `web/node_modules` (`npm ci`), Python 3, Docker, and
network access for the first npm/Chromium download into the volume.

```sh
R=$PWD                       # repository root
OUT=/abs/scratch/listening-walkthrough
mkdir -p "$OUT/build"
go build -o "$OUT/build/server" ./cmd/server
(cd web && npx vite build --outDir "$OUT/build/web-dist" --emptyOutDir)
python3 -I scripts/validation/listening_workbook/run.py \
  "$OUT/build/server" "$OUT/build/web-dist" "$OUT" mytag
# -> $OUT/results-mytag.json, $OUT/shots-mytag/*.png, $OUT/run-mytag/{server.log,fake.log}
# prints PASS/FAIL per check and the fake provider's calls; exit 0 only if all pass
docker volume rm flh-listening-workbook-pw   # remove the browser cache afterwards
```

If `/tmp` is a small tmpfs, point Go's temporary directory elsewhere
(`GOTMPDIR=/abs/dir TMPDIR=/abs/dir`).

To compare with an earlier tree, build that tree's server and web bundle the
same way and run with another tag. On the tree before this change the
overview, reload-reopen, script-preparation and zh-CN checks fail (the
recorded baseline: 51 of 61 checks).

## Script revisions: old import -> update -> reopen the old mistake

`revisions.py` + `revisions.mjs` walk the revision contract (ARCHITECTURE.md
§4.3) in real Chromium, on four fresh scratch databases: phone and desktop,
English and Simplified Chinese.

1. An OLD server (a binary whose embedded pack predates a correction, e.g.
   built from commit `c53b42c`, before the 2026-11-11 evidence audit) imports
   `ls-wb1-u05` in its own UI, answers question 4 wrongly, reveals and saves
   it (always in English: it is the setup).
2. The NEW server opens the same database: the list tags the script
   **Update available** / **Revision 1**; the lesson shows a notice and no
   update button, with its old wording; the old mistake opens its question;
   **Review the changes** (focus, the one-sentence note on earlier practice,
   question 4 listed, key behind a closed disclosure, nothing written);
   **Update this lesson to revision 2** (201); the same confirmation again
   replays (200) and a re-import replays (200); the old mistake keeps its
   explanation and opens **Revision 1: the version you saved from** with the
   question at the top; a typed answer is self-assessed in its overview row;
   a new mistake on revision 2 is a separate record; only two writes; no
   console error; no horizontal scroll.

```sh
OLD=/abs/old-build   # server + web-dist from a tree whose pack predates a correction
NEW=/abs/new-build   # this tree: go build -o $NEW/server ./cmd/server; (cd web && npx vite build --outDir $NEW/web-dist --emptyOutDir)
python3 -I scripts/validation/listening_workbook/revisions.py \
  $OLD/server $OLD/web-dist $NEW/server $NEW/web-dist /abs/scratch/out mytag
# -> out/results-mytag.json, out/shots-mytag/<combo>-A1…B07.png, out/run-mytag/<combo>/{old,new}-server.log
```

Recorded on 2026-11-12 (Chromium 131.0.6778.33, Playwright 1.49.1): this tree
120/120; the tree before the revision path (`521279a`) 16/32 (no tag, no
notice, re-import `409 script_conflict`, the old wording after reveal). Not
covered: Safari, Firefox, a real phone (Chromium phone emulation only), and
the old part in Chinese.
