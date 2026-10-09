# FLH-030 idempotency browser acceptance harness

Real-browser acceptance of FLH-029 keyed DISTINCT / BROADER / NARROWER / RELATED
in the Concept Review workbench, against both the Vite development server
(React StrictMode) and the production build served by `cmd/server -web-dir`.
The report is `docs/validation/FLH-030-idempotency-browser-acceptance.md`.

Everything runs in new temporary directories with synthetic data, a local stub
extraction provider and fixed loopback ports (18930-18932, 5330). No `.env`,
secret, daily database, paid provider or permanent dependency is used.

## Prerequisites (temporary, outside the repository)

* Go toolchain for `go.mod`; Python 3; Node.js; `sqlite3` CLI (optional checks).
* Google Chrome (override its path with `CHROME=/path/to/chrome`).
* `playwright-core` installed in a **temporary** directory, e.g.
  `npm install --prefix "$PW" playwright-core`. It is not a project dependency.
* A temporary copy of `web/` with `npm ci` and `npm run build` run in the copy.

## Run

```sh
WORK=$(mktemp -d); WEB=$(mktemp -d); PW=$(mktemp -d)
cp -R web/. "$WEB" && npm --prefix "$WEB" ci && npm --prefix "$WEB" run build
npm install --prefix "$PW" playwright-core
go build -o "$WORK/server" ./cmd/server
mkdir -p "$WORK/shots"
cp scripts/validation/flh030/acceptance.mjs scripts/validation/flh030/probes.mjs "$PW"/

sh scripts/validation/flh030/up.sh "$WORK" "$WEB"
python3 -B scripts/validation/flh030/seed.py http://127.0.0.1:18931
python3 -B scripts/validation/flh030/seed.py http://127.0.0.1:18932

node "$PW/acceptance.mjs" http://localhost:5330  http://127.0.0.1:18931 "$WORK/shots" dev
node "$PW/acceptance.mjs" http://localhost:18932 http://127.0.0.1:18932 "$WORK/shots" prod
SHOTS="$WORK/shots" LABEL=dev  node "$PW/probes.mjs" http://localhost:5330  http://127.0.0.1:18931 6 5
SHOTS="$WORK/shots" LABEL=prod node "$PW/probes.mjs" http://localhost:18932 http://127.0.0.1:18932 6 5

sh scripts/validation/flh030/down.sh
```

`acceptance.mjs` must run once per freshly seeded database (it consumes units
1-12). `probes.mjs` runs after it on the same database (units 6 and 5).

## Files

| File | Purpose |
| --- | --- |
| `up.sh` / `down.sh` | Start/stop stub provider, DEV backend + Vite, PROD backend `-web-dir` |
| `stub.py` | Local extraction provider: three synthetic units per call |
| `seed.py` | Four synthetic records, rule-based analyses, one extraction each (12 units), three concepts |
| `acceptance.mjs` | 22 browser steps + 2 global checks (PASS/FAIL/INFO lines) |
| `probes.mjs` | P1 historical receipt vs later INVALID; P2 two tabs on one unit |

Fault injection is browser-level (Playwright routing): *lost response* forwards
the request, lets it commit, then resets the browser connection; *never arrives*
resets before forwarding; *delay-drop* resets the browser connection and later
delivers the identical captured request (same URL, Origin, `Idempotency-Key`,
body) from the harness; *hold* keeps the request inside the browser until the
step releases it. Storage failure overrides `Storage.prototype.setItem` for the
operation key only. Persisted state is read from the backend HTTP API, never
inferred from the UI.
