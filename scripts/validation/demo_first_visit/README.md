# Public demo first visit: guided path acceptance

`accept_guided.mjs` walks the public demo's guided examples in English and
简体中文 at desktop (1280×900) and phone (390×844) widths:

- the starting screen: one-sentence lead, three example entry points, the
  *Read-only* / *Synthetic data* labels, the mechanical-build warning (or its
  absence for a model build) and direct search;
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
