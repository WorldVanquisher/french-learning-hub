#!/bin/sh
# FLH-034 Knowledge Library demo environment.
#
#   demo.sh setup   WORK_DIR [WEB_DIST]  new empty WORK_DIR: build, start, seed
#   demo.sh start   WORK_DIR [WEB_DIST]  restart against the existing demo database
#   demo.sh stop    WORK_DIR             stop the demo server and stub
#   demo.sh cleanup WORK_DIR             stop, then delete WORK_DIR (demo dirs only)
#
# WEB_DIST is an already built web/dist; with it the server also serves the
# workbench (production mode). Without it the API is served alone (use Vite).
# Ports: DEMO_PORT (default 18934) and STUB_PORT (default 18933), loopback only.
# The server runs with WORK_DIR as its working directory, so no repository .env
# is read. Its database is WORK_DIR/demo.db. No paid provider, secret or daily
# database is used: AI_PROVIDER is the local rule-based analyzer and extraction
# goes to the local stub_extractor.py.
set -eu
cmd=${1:-}; work=${2:-}
[ -n "$cmd" ] && [ -n "$work" ] || { sed -n '2,15p' "$0"; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
DEMO_PORT=${DEMO_PORT:-18934}
STUB_PORT=${STUB_PORT:-18933}
MARK=.flh034-demo

stop() {
  for f in "$work/server.pid" "$work/stub.pid"; do
    if [ -f "$f" ]; then kill "$(cat "$f")" 2>/dev/null || true; rm -f "$f"; fi
  done
}

start() {
  web=${1:-}
  python3 -B "$HERE/stub_extractor.py" "$STUB_PORT" > "$work/stub.log" 2>&1 &
  echo $! > "$work/stub.pid"
  set -- -web-dir "$web"
  [ -n "$web" ] || set --
  (cd "$work" && exec env AI_PROVIDER=rule-based EXTRACTOR_PROVIDER=openai \
    OPENAI_API_KEY=sk-local-demo-not-a-secret OPENAI_BASE_URL="http://127.0.0.1:$STUB_PORT" \
    OPENAI_MODEL=stub-model EMBEDDING_PROVIDER=disabled PORT="$DEMO_PORT" DB_PATH="$work/demo.db" \
    "$work/server" "$@") > "$work/server.log" 2>&1 &
  echo $! > "$work/server.pid"
  i=0
  until curl -fsS "http://127.0.0.1:$DEMO_PORT/readyz" > /dev/null 2>&1; do
    i=$((i + 1)); [ $i -lt 50 ] || { echo "server did not become ready; see $work/server.log"; exit 1; }
    sleep 0.2
  done
  echo "Knowledge Library demo ready: http://127.0.0.1:$DEMO_PORT/${web:+ (workbench)}"
  [ -n "$web" ] || echo "API only; for the workbench run: FRENCH_HUB_URL=http://127.0.0.1:$DEMO_PORT npm --prefix web run dev"
}

case "$cmd" in
setup)
  case "$work" in /*) ;; *) echo "WORK_DIR must be an absolute path"; exit 2 ;; esac
  case "$work" in "$REPO"|"$REPO"/*) echo "refusing a WORK_DIR inside the repository (protects data/)"; exit 2 ;; esac
  if [ -e "$work" ] && [ -n "$(ls -A "$work")" ]; then echo "refusing: $work is not empty; setup never reuses or resets a database"; exit 2; fi
  mkdir -p "$work"
  work=$(cd "$work" && pwd)
  touch "$work/$MARK"
  (cd "$REPO" && go build -o "$work/server" ./cmd/server)
  start "${3:-}"
  python3 -B "$HERE/seed.py" "http://127.0.0.1:$DEMO_PORT" | tee "$work/seed.json"
  ;;
start)
  [ -f "$work/$MARK" ] && [ -f "$work/demo.db" ] || { echo "refusing: $work is not a FLH-034 demo directory"; exit 2; }
  work=$(cd "$work" && pwd)
  stop
  start "${3:-}"
  ;;
stop)
  [ -f "$work/$MARK" ] || { echo "refusing: $work is not a FLH-034 demo directory"; exit 2; }
  stop; echo stopped
  ;;
cleanup)
  [ -f "$work/$MARK" ] || { echo "refusing: $work is not a FLH-034 demo directory"; exit 2; }
  stop; rm -rf "$work"; echo "removed $work"
  ;;
*) sed -n '2,15p' "$0"; exit 2 ;;
esac
