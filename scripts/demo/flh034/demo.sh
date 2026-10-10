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
# Ports: DEMO_PORT (default 18934) and STUB_PORT (default 18933). Both must be
# free; the server is bound to 127.0.0.1 (LISTEN_HOST) and the stub to 127.0.0.1.
# The server runs with WORK_DIR as its working directory, so no repository .env
# is read. Its database is WORK_DIR/demo.db. No paid provider, secret or daily
# database is used: AI_PROVIDER is the local rule-based analyzer and extraction
# goes to the local stub_extractor.py.
# Processes are signalled only after proc_guard.py verifies their PID, start
# time and command line (Linux or macOS). Any failure stops what this run
# started and exits non-zero.
set -eu
cmd=${1:-}; work=${2:-}
[ -n "$cmd" ] && [ -n "$work" ] || { sed -n '2,19p' "$0"; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
DEMO_PORT=${DEMO_PORT:-18934}
STUB_PORT=${STUB_PORT:-18933}
MARK=.flh034-demo
guard() { python3 -B "$HERE/proc_guard.py" "$@"; }
fail() { echo "demo.sh: $*" >&2; exit 1; }

# on_exit runs for every exit once a run may have started processes: on failure
# it stops only the processes this directory's records prove are ours.
on_exit() {
  status=$?
  trap - EXIT
  if [ "$status" -ne 0 ]; then
    guard stop "$work" >&2 || true
    echo "demo.sh: $cmd FAILED (exit $status). Owned processes were stopped; logs are in $work." >&2
    [ "$cmd" != setup ] || echo "demo.sh: remove the failed directory with: sh $0 cleanup $work" >&2
  fi
  exit "$status"
}

start() {
  web=${1:-}
  # Refuse before launching anything, so no request can reach another listener.
  guard port-free "$DEMO_PORT" || fail "DEMO_PORT $DEMO_PORT is in use; stop that process or set DEMO_PORT"
  guard port-free "$STUB_PORT" || fail "STUB_PORT $STUB_PORT is in use; stop that process or set STUB_PORT"
  python3 -B "$HERE/stub_extractor.py" "$STUB_PORT" "$work" > "$work/stub.log" 2>&1 &
  echo $! > "$work/stub.pid"
  guard record stub "$work"
  guard wait-listener stub "$work" "$STUB_PORT" 10
  set -- -web-dir "$web"
  [ -n "$web" ] || set --
  (cd "$work" && exec env LISTEN_HOST=127.0.0.1 PORT="$DEMO_PORT" DB_PATH="$work/demo.db" \
    AI_PROVIDER=rule-based EXTRACTOR_PROVIDER=openai EMBEDDING_PROVIDER=disabled \
    OPENAI_API_KEY=sk-local-demo-not-a-secret OPENAI_BASE_URL="http://127.0.0.1:$STUB_PORT" OPENAI_MODEL=stub-model \
    "$work/server" "$@") > "$work/server.log" 2>&1 &
  echo $! > "$work/server.pid"
  guard record server "$work"
  # Readiness counts only once the started server itself owns the listener.
  guard wait-listener server "$work" "$DEMO_PORT" 20
  curl -fsS "http://127.0.0.1:$DEMO_PORT/readyz" > /dev/null || fail "server is not ready; see $work/server.log"
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
  trap on_exit EXIT
  trap 'exit 130' INT TERM
  # Fail fast; start() checks the ports again immediately before launching.
  guard port-free "$DEMO_PORT" || fail "DEMO_PORT $DEMO_PORT is in use; stop that process or set DEMO_PORT"
  guard port-free "$STUB_PORT" || fail "STUB_PORT $STUB_PORT is in use; stop that process or set STUB_PORT"
  (cd "$REPO" && go build -o "$work/server" ./cmd/server) || fail "server build failed"
  start "${3:-}"
  # Re-check ownership immediately before the only fixture writes.
  guard wait-listener server "$work" "$DEMO_PORT" 0 > /dev/null
  python3 -B "$HERE/seed.py" "http://127.0.0.1:$DEMO_PORT" > "$work/seed.partial.json" || fail "seed failed; partial output in $work/seed.partial.json"
  mv "$work/seed.partial.json" "$work/seed.json"
  cat "$work/seed.json"
  echo "setup complete"
  ;;
start)
  [ -f "$work/$MARK" ] && [ -f "$work/demo.db" ] || { echo "refusing: $work is not a FLH-034 demo directory"; exit 2; }
  work=$(cd "$work" && pwd)
  guard stop "$work"
  trap on_exit EXIT
  trap 'exit 130' INT TERM
  start "${3:-}"
  ;;
stop)
  [ -f "$work/$MARK" ] || { echo "refusing: $work is not a FLH-034 demo directory"; exit 2; }
  work=$(cd "$work" && pwd)
  guard stop "$work"; echo stopped
  ;;
cleanup)
  [ -f "$work/$MARK" ] || { echo "refusing: $work is not a FLH-034 demo directory"; exit 2; }
  work=$(cd "$work" && pwd)
  guard stop "$work" || { echo "refusing to delete $work while its demo processes may still run"; exit 1; }
  rm -rf "$work"; echo "removed $work"
  ;;
*) sed -n '2,19p' "$0"; exit 2 ;;
esac
