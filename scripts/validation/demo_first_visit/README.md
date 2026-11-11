# Public demo first visit: guided path acceptance

`accept_guided.mjs` walks the public demo's guided examples in English and
简体中文 at desktop (1280×900) and phone (390×844) widths:

- the starting screen: one-sentence lead, three example entry points (the
  first one fully on the first screen at both widths), the *Read-only* /
  *Synthetic data* labels, the synthetic notice and artifact identity, the
  mechanical-build warning (or its absence for a model build) and direct
  search;
- each example: its French question unchanged and marked `lang="fr"`, the
  number of extracted units and Concepts, then example → Concept → evidence →
  back to the Concept → back to the example → back to the start with focus on
  the example's card;
- keyboard entry (Tab to the first card, Enter opens it), no horizontal scroll
  on any screen, search query and results kept across an example;
- the browser's Back: Concept → its example → the start, same URL, focus on the
  example card; in a mechanical build, the notice beside semantic scores;
- failure and edge states: a slow source read (loading), a failed Concept read
  (alert with retry, then recovery) and a keyword search with no match;
- every request a same-origin GET on the demo allowlist, and no console errors.

It complements `../demo_refresh/accept_paths.mjs` (search paths and
private-route probes), which must still pass. Run both against a running demo,
normally the packaged release binary. Needs Node, `playwright-core` (no browser
download) and Chromium or Chrome.

```sh
PKG=/abs/flh-public-demo-<label>[-BLOCKED]
# add -public-demo-allow-mechanical only for a -BLOCKED (mechanical) package
env -i PATH=/usr/bin:/bin HOME=/tmp LISTEN_HOST=127.0.0.1 PORT=18990 \
  "$PKG/bin/linux-amd64/flh-server" -public-demo-artifact "$PKG/artifact" -web-dir "$PKG/web" &
CHROME=/usr/bin/chromium node accept_guided.mjs http://127.0.0.1:18990/ /abs/out mechanical   # or: model
```

Evidence: `OUT/results.json` and one screenshot per step.

## Resilience: `accept_resilience.mjs`

Delays, fails or lengthens responses **in the browser** (Playwright routing; the
server and its data are untouched) and checks one failure case per check:

- long text (a long French question with an unbroken word, long Concept,
  unit and identifier text) in both languages at 1280 and 390 px: no
  horizontal scroll, the whole question shown, return actions in view;
- a failed demo description (stated with its status, recovered by *Try
  again* without a reload), a failed search and a failed source read, each
  recovered by retry with the query and back actions kept;
- out-of-order reads: a slower, older search or Concept answer never replaces
  a newer one;
- an empty status filter, a double click on an example (one Back returns),
  rapid example switching;
- browser Back from evidence and Concept to the results, with the query,
  results, focus and scroll position kept.

```sh
CHROME=/usr/bin/chromium node accept_resilience.mjs http://127.0.0.1:18990/ /abs/out/resilience
```

The same failure cases run without a browser in
`web/src/demo/Resilience.test.tsx`.

## Accessibility and direct links: `accept_a11y.mjs`

- The whole guided path with the keyboard only (Tab, Shift+Tab, Enter) in
  English at 1280 px and 简体中文 at 390 px, with visible focus at every stop,
  each screen's heading focused and never under the return bar, focus restored
  to the starting card, and the number of key presses (`METRIC` lines and
  `results.json`).
- Reduced motion: no animation, transition or smooth scrolling on any guided
  screen.
- Direct links: example, Concept and evidence fragments open their screens,
  survive a reload and keep "back to the example"; malformed links open the
  start; a missing Concept states the failed read; fragments never reach the
  server.
- Every button has an accessible name; header, main and the return navigation
  are present.

```sh
CHROME=/usr/bin/chromium node accept_a11y.mjs http://127.0.0.1:18990/ /abs/out/a11y
```
