# FLH-032 annotation recovery browser probes

Real-browser checks of the FLH-032 fixes for FLH-030 defects F1–F3, against
the Vite development server (React StrictMode) and the production build served
by `cmd/server -web-dir`. The report is
`docs/validation/FLH-032-annotation-recovery.md`.

The FLH-030 environment and fixtures are reused **read-only**:
`scripts/validation/flh030/up.sh`, `down.sh`, `stub.py` and `seed.py`. They
use synthetic data, a local stub provider, isolated temporary databases and
loopback ports 18930–18932 and 5330. The prerequisites (temporary
`playwright-core`, a built temporary copy of `web/`, Chrome) are the same as in
`scripts/validation/flh030/README.md`.

| File | Purpose |
| --- | --- |
| `probes.mjs` | G1–G7: F1 two tabs; F2 rejection, newer operation and unknown outcome while away; F3 save failure, cleanup failure, unreadable value with recheck |
| `adapt030.py` | Writes a copy of the FLH-030 acceptance harness to a temporary path with only S1/S2 rewritten for the FLH-032 storage behavior (the FLH-030 file is only read) |

## Run

Each block needs freshly seeded databases, because both suites consume units 1–12.

```sh
WORK=$(mktemp -d); WEB=$(mktemp -d); PW=$(mktemp -d)
cp -R web/. "$WEB" && npm --prefix "$WEB" ci && npm --prefix "$WEB" run build
npm install --prefix "$PW" playwright-core
go build -o "$WORK/server" ./cmd/server
mkdir -p "$WORK/shots"
cp scripts/validation/flh032/probes.mjs "$PW/probes032.mjs"
cp scripts/validation/flh030/probes.mjs "$PW/probes030.mjs"
python3 -B scripts/validation/flh032/adapt030.py scripts/validation/flh030/acceptance.mjs "$PW/acceptance030-032.mjs"

# FLH-032 probes
sh scripts/validation/flh030/up.sh "$WORK" "$WEB"
python3 -B scripts/validation/flh030/seed.py http://127.0.0.1:18931
python3 -B scripts/validation/flh030/seed.py http://127.0.0.1:18932
node "$PW/probes032.mjs" http://localhost:5330  http://127.0.0.1:18931 "$WORK/shots" dev
node "$PW/probes032.mjs" http://localhost:18932 http://127.0.0.1:18932 "$WORK/shots" prod
sh scripts/validation/flh030/down.sh

# FLH-030 regression (adapted S1/S2) + FLH-030 probes; up.sh recreates the databases
sh scripts/validation/flh030/up.sh "$WORK" "$WEB"
python3 -B scripts/validation/flh030/seed.py http://127.0.0.1:18931
python3 -B scripts/validation/flh030/seed.py http://127.0.0.1:18932
node "$PW/acceptance030-032.mjs" http://localhost:5330  http://127.0.0.1:18931 "$WORK/shots" dev
node "$PW/acceptance030-032.mjs" http://localhost:18932 http://127.0.0.1:18932 "$WORK/shots" prod
SHOTS="$WORK/shots" LABEL=dev  node "$PW/probes030.mjs" http://localhost:5330  http://127.0.0.1:18931 6 5
SHOTS="$WORK/shots" LABEL=prod node "$PW/probes030.mjs" http://localhost:18932 http://127.0.0.1:18932 6 5
sh scripts/validation/flh030/down.sh
```

Faults are injected at the browser level:

- A held request is released either with a synthetic 422 (`route.fulfill`; the server never sees it) or with a connection reset.
- Storage failure overrides `Storage.prototype.setItem` for the operation key only.
- G3 stands in for another tab by writing a newer operation directly to `localStorage`.
