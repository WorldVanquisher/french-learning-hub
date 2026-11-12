# Demo refresh: path acceptance

`accept_paths.mjs` walks the authored French examples of the public demo,
question → units → Concept → evidence. It runs in English and 简体中文, at desktop
(1280×900) and phone (390×844) widths. It also checks that:
- every request is a same-origin GET on the demo allowlist;
- the console shows no errors;
- there is no horizontal scroll on phones, measured against the device width
  (390 px) with the overflowing element named, because under phone emulation
  `innerWidth` grows with the content and cannot reveal an overflow;
- private routes stay closed (unknown paths 404, non-GET methods 405).

Run it against a demo that is already running, normally the packaged release
binary. It needs Node, `playwright-core` (no browser download) and Chromium or Chrome.

```sh
PKG=/abs/flh-public-demo-<label>[-BLOCKED]
# add -public-demo-allow-mechanical only for a -BLOCKED (mechanical) package
env -i PATH=/usr/bin:/bin HOME=/tmp LISTEN_HOST=127.0.0.1 PORT=18990 \
  "$PKG/bin/linux-amd64/flh-server" -public-demo-artifact "$PKG/artifact" -web-dir "$PKG/web" &
CHROME=/usr/bin/chromium node accept_paths.mjs http://127.0.0.1:18990/ /abs/out mechanical   # or: model
```

Evidence: `OUT/results.json` and one screenshot per step.
