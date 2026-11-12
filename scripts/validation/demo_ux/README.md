# Public demo UX matrix

`accept_matrix.mjs` checks the public demo in a real browser. It runs against
a demo that is already up, normally the packaged release binary.

It covers three sizes in English and 简体中文:
- a 320 px phone and a 390 px phone, both with true phone emulation
  (`isMobile`, touch, DPR 2);
- a 1280 px desktop.

## What it checks

**Start screen**
- Labels, the three examples, and the Development build label in a
  mechanical build only.
- The first example is whole on the first screen from 390 px up. On a
  320 px phone its title line is.

**Walkthrough**
For each example: question → four steps → Concept ("Step 3 of 4") →
evidence ("Step 4 of 4"). Then the navigation contract:
- an in-page back adds no history entry;
- browser Back next goes to the example, not to the evidence just left;
- Forward walks to the Concept and then the evidence;
- a reload stays on the evidence;
- back to the example, then the start, with focus on the example's card.

**Search**
- The address names the search.
- A reload on a Concept keeps that Concept and the way back to the search.
- Going back shows the results with the query, and focus returns to the
  Concept that was opened.
- Browser Back undoes the search.

**Shared links** (each opened as a new document, as a pasted link is)
- A malformed link (`#concept=abc`) opens the start with a notice, and the
  address becomes the start's.
- A link to an ID the build lacks (`#concept=999`, `#concept=12&unit=999`)
  says so, offers no retry, and its button opens a working example without a
  reload (one history entry added; Back returns to the link's screen). Their
  404s are the only console errors allowed.
- Coming back focuses the control that left a screen: the source button used,
  after the in-page back from the evidence; “Open the Concept”, after the
  browser's Back to the example.
- A language change keeps the screen, the address and the history length.

**Keyboard only**
- Start → example → Concept → evidence → example → start.
- Back on the example, focus is on “Open the Concept”, the control used.
- At every stop, focus is visible and not under the sticky return bar.
- Key presses are counted.

**Layout**
- Every Concept and every supporting unit's evidence screen, opened by
  direct link.
- The semantic preset results, whose preset list is the widest control.

**Long and bilingual text**
- Long identifiers, a long Concept title and scope, English + 中文 + French
  explanations, a long French question and a nanosecond timestamp.
- They are injected in the browser; the server never changes.
- They are checked through the walkthrough, with the return bar kept in view.

**States**
- Unavailable demo: the status and a retry that recovers without a reload.
- Example loading.
- A search with no match: the explanation and suggestions, and one suggestion
  finds Concepts.
- An empty catalog.

**Overflow**, measured against the device width in two separate checks per
screen:
- **document:** the root `scrollWidth` (the page scrolls sideways);
- **elements:** every rendered leaf element whose right edge is past the
  device edge, named, even when an ancestor clips it (text cut off with no
  sideways scroll). Content inside a horizontal scroll container is left to
  that container.
- Under phone emulation `innerWidth` grows with the content, so
  `scrollWidth <= innerWidth` can never fail. The D1 check had that problem:
  it passed 421 px on a 390 px phone.
- **Self-test:** the run injects the old evidence-row layout on the
  "être en train de" evidence screen, at 320 and 390 px in both languages.
  The document check must catch it with the `dd` named. With
  `html, body { overflow-x: hidden }` added, the document fits again, and the
  element check must still name the `dd`. Otherwise the run fails.

**Read-only**
- Every request is a same-origin GET on the demo allowlist.
- No console or page errors.
- Private routes answer `404` and writes `405`, at the root and under `/api`.

## Running it

Needs Node, `playwright-core` (no browser download) and Chromium or Chrome.

```sh
PKG=/abs/flh-public-demo-<label>[-BLOCKED]
# add -public-demo-allow-mechanical only for a -BLOCKED (mechanical) package
env -i PATH=/usr/bin:/bin HOME=/tmp LISTEN_HOST=127.0.0.1 PORT=18990 \
  "$PKG/bin/linux-amd64/flh-server" -public-demo-artifact "$PKG/artifact" -web-dir "$PKG/web" &
CHROME=/usr/bin/chromium node accept_matrix.mjs http://127.0.0.1:18990/ /abs/out mechanical   # or: model
```

It complements `../demo_refresh/accept_paths.mjs` and
`../demo_first_visit/*.mjs`, which must still pass.

## Evidence

- `OUT/results.json`: checks and metrics (first-card position, key presses,
  screens measured, the old layout's width).
- `OUT/overflow.json`: every measured screen.
- Screenshots of each step and state, and of the injected regression.
