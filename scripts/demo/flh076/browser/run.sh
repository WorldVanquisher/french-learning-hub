#!/usr/bin/env bash
# FLH-076 real-browser acceptance wrapper (macOS or Linux with Chrome installed).
#
#   bash scripts/demo/flh076/browser/run.sh /abs/new/work/dir [artifact-dir] [port]
#
# Builds the server and the demo web build into WORK, builds a mechanical
# artifact unless one is given, installs playwright-core (no browser download)
# into WORK/tools, starts the demo on 127.0.0.1, runs accept.mjs against it
# with the installed Chrome, and stops the server it started. Evidence:
# WORK/browser/ (results.json, screenshots).
set -euo pipefail
WORK=${1:?usage: run.sh /abs/new/work/dir [artifact-dir] [port]}
ARTIFACT=${2:-}
PORT=${3:-18976}
REPO=$(cd "$(dirname "$0")/../../../.." && pwd)
CHROME=${CHROME:-"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"}
case "$WORK" in /*) ;; *) echo "refused: WORK must be absolute" >&2; exit 2 ;; esac
case "$WORK/" in "$REPO"/*) echo "refused: WORK must be outside the repository" >&2; exit 2 ;; esac
[ ! -e "$WORK" ] || { echo "refused: $WORK exists" >&2; exit 2; }
[ -x "$CHROME" ] || { echo "NOT RUN: no Chrome at $CHROME (set CHROME=...)" >&2; exit 4; }
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then echo "refused: port $PORT in use" >&2; exit 2; fi
mkdir -p "$WORK/bin" "$WORK/tools"
(cd "$REPO" && go build -o "$WORK/bin/server" ./cmd/server && go build -o "$WORK/bin/prepare" ./scripts/demo/flh073/prepare)
EXPECT=mechanical
if [ -z "$ARTIFACT" ]; then
  ARTIFACT="$WORK/artifact"
  (cd "$REPO" && "$WORK/bin/prepare" build -out "$ARTIFACT" -fixtures scripts/demo/flh073/fixtures/catalog.json > "$WORK/build.json")
else
  "$WORK/bin/prepare" validate -artifact "$ARTIFACT" -release > /dev/null 2>&1 && EXPECT=model
fi
(cd "$REPO/web" && VITE_FLH_PUBLIC_DEMO=1 ./node_modules/.bin/vite build --outDir "$WORK/web" --emptyOutDir > "$WORK/web-build.log" 2>&1)
(cd "$WORK/tools" && npm init -y > /dev/null && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --no-audit --no-fund playwright-core@1.49.1 > "$WORK/tools/install.log" 2>&1)
FLAGS=(-public-demo-artifact "$ARTIFACT" -web-dir "$WORK/web")
[ "$EXPECT" = mechanical ] && FLAGS+=(-public-demo-allow-mechanical)
(cd "$WORK" && exec env -i PATH=/usr/bin:/bin HOME="$WORK" LISTEN_HOST=127.0.0.1 PORT="$PORT" "$WORK/bin/server" "${FLAGS[@]}") > "$WORK/server.log" 2>&1 &
PID=$!
stop() { if kill -0 "$PID" 2>/dev/null && ps -p "$PID" -o command= | grep -q "^$WORK/bin/server"; then kill "$PID"; wait "$PID" 2>/dev/null || true; fi; }
trap stop EXIT
for _ in $(seq 1 50); do curl -fsS "http://127.0.0.1:$PORT/readyz" > /dev/null 2>&1 && break; sleep 0.2; done
set +e
PLAYWRIGHT_CORE_DIR="$WORK/tools/node_modules/playwright-core" node "$REPO/scripts/demo/flh076/browser/accept.mjs" \
  --url "http://127.0.0.1:$PORT" --out "$WORK/browser" --chrome "$CHROME" --expect-vectors "$EXPECT"
RC=$?
set -e
curl -fsS "http://127.0.0.1:$PORT/knowledge-library/demo" > "$WORK/demo-info-after.json"
stop
trap - EXIT
kill -0 "$PID" 2>/dev/null && { echo "FAIL: server still running" >&2; exit 1; }
echo "browser acceptance exit $RC; evidence $WORK/browser"
exit "$RC"
