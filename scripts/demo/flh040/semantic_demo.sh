#!/bin/sh
# FLH-040 semantic search demo on synthetic data (Linux or macOS).
#
#   semantic_demo.sh up    WORK_DIR QDRANT_BIN [WEB_DIST]
#   semantic_demo.sh index WORK_DIR build|sync|rebuild|status
#   semantic_demo.sh down  WORK_DIR
#   semantic_demo.sh clean WORK_DIR
#
# up: seeds the FLH-034 synthetic library in WORK_DIR/demo (through its own
# demo.sh), stops that keyword-only server, then starts task-owned processes:
#   - the deterministic fake embedding service (fake_embeddings.py),
#   - a Qdrant binary you downloaded (QDRANT_BIN), storing under WORK_DIR/qdrant,
#   - the demo server with SEMANTIC_SEARCH=qdrant,
# builds the semantic-index CLI into WORK_DIR and runs "semantic-index build".
# Everything binds 127.0.0.1. Fake vectors prove mechanics, not semantic quality.
# No API key, paid provider, daily database or Docker resource is used.
#
# Ports: DEMO_PORT 18934 (server), STUB_PORT 18933 (FLH-034 seed stub),
# EMBED_PORT 18940, QDRANT_PORT 18941 (+1 for gRPC). Every port must be free.
# down signals only processes whose command line names WORK_DIR.
set -eu
cmd=${1:-}; work=${2:-}
[ -n "$cmd" ] && [ -n "$work" ] || { sed -n '2,21p' "$0"; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
DEMO_PORT=${DEMO_PORT:-18934}
EMBED_PORT=${EMBED_PORT:-18940}
QDRANT_PORT=${QDRANT_PORT:-18941}
QDRANT_GRPC=$((QDRANT_PORT + 1))
DIMS=64
MODEL_ID="fake/bag-of-words-${DIMS}@flh040"
MARK=.flh040-semantic-demo
fail() { echo "semantic_demo.sh: $*" >&2; exit 1; }
port_free() { python3 -B "$REPO/scripts/demo/flh034/proc_guard.py" port-free "$1"; }

# env_line prints the server/CLI environment for this demo directory.
env_line() {
  echo "LISTEN_HOST=127.0.0.1 PORT=$DEMO_PORT DB_PATH=$work/demo/demo.db AI_PROVIDER=rule-based" \
    "EXTRACTOR_PROVIDER=disabled EMBEDDING_PROVIDER=http EMBEDDING_MODEL=fake-bag-of-words" \
    "EMBEDDING_BASE_URL=http://127.0.0.1:$EMBED_PORT/v1 EMBEDDING_MODEL_ID=$MODEL_ID" \
    "EMBEDDING_DIMENSIONS=$DIMS SEMANTIC_SEARCH=qdrant QDRANT_URL=http://127.0.0.1:$QDRANT_PORT" \
    "SEMANTIC_BATCH_SIZE=4"
}

# stop_owned NAME: signal the recorded PID only if its command names $work.
stop_owned() {
  f="$work/$1.pid"
  [ -f "$f" ] || return 0
  pid=$(cat "$f")
  cmdline=$(ps -p "$pid" -o command= 2>/dev/null || true)
  case "$cmdline" in
    *"$work"*) kill "$pid"; i=0
      while ps -p "$pid" >/dev/null 2>&1 && [ $i -lt 50 ]; do i=$((i + 1)); sleep 0.2; done
      ps -p "$pid" >/dev/null 2>&1 && fail "$1 (pid $pid) did not exit"
      echo "$1: stopped pid $pid" ;;
    "") echo "$1: recorded pid $pid is not running" ;;
    *) echo "$1: pid $pid is not this demo's process; NOT signalled" ;;
  esac
  rm -f "$f"
}

wait_http() {
  i=0
  until curl -fsS "$1" >/dev/null 2>&1; do
    i=$((i + 1)); [ $i -lt 100 ] || fail "$2 did not become ready; see $work/$3.log"
    sleep 0.2
  done
}

case "$cmd" in
up)
  qbin=${3:-}; web=${4:-}
  case "$work" in /*) ;; *) fail "WORK_DIR must be an absolute path" ;; esac
  case "$work" in "$REPO"|"$REPO"/*) fail "refusing a WORK_DIR inside the repository" ;; esac
  [ -x "$qbin" ] || fail "QDRANT_BIN must be an executable Qdrant binary (see scripts/demo/flh040/README.md)"
  if [ -e "$work" ] && [ -n "$(ls -A "$work")" ]; then fail "$work is not empty"; fi
  for p in "$EMBED_PORT" "$QDRANT_PORT" "$QDRANT_GRPC"; do port_free "$p" || fail "port $p is in use"; done
  mkdir -p "$work"; work=$(cd "$work" && pwd); touch "$work/$MARK"
  trap 'status=$?; [ $status -eq 0 ] || { sh "$0" down "$work" >&2 || true; echo "up FAILED; inspect $work, then: sh $0 clean $work" >&2; }' EXIT

  sh "$REPO/scripts/demo/flh034/demo.sh" setup "$work/demo" ${web:+"$web"} > "$work/seed.log" 2>&1 || fail "seeding failed; see $work/seed.log"
  sh "$REPO/scripts/demo/flh034/demo.sh" stop "$work/demo" >> "$work/seed.log" 2>&1
  port_free "$DEMO_PORT" || fail "port $DEMO_PORT is still in use"
  (cd "$REPO" && go build -o "$work/semantic-index" ./cmd/semantic-index) || fail "CLI build failed"

  python3 -B "$HERE/fake_embeddings.py" "$EMBED_PORT" "$DIMS" "$work" > "$work/embeddings.log" 2>&1 &
  echo $! > "$work/embeddings.pid"
  mkdir -p "$work/qdrant"
  cat > "$work/qdrant.yaml" <<EOF
service:
  host: 127.0.0.1
  http_port: $QDRANT_PORT
  grpc_port: $QDRANT_GRPC
storage:
  storage_path: $work/qdrant/storage
  snapshots_path: $work/qdrant/snapshots
telemetry_disabled: true
EOF
  (cd "$work/qdrant" && exec "$qbin" --config-path "$work/qdrant.yaml") > "$work/qdrant.log" 2>&1 &
  echo $! > "$work/qdrant.pid"
  wait_http "http://127.0.0.1:$EMBED_PORT/stats" "fake embeddings" embeddings
  wait_http "http://127.0.0.1:$QDRANT_PORT/readyz" "qdrant" qdrant

  set -- -web-dir "$web"; [ -n "$web" ] || set --
  (cd "$work" && exec env $(env_line) "$work/demo/server" "$@") > "$work/server.log" 2>&1 &
  echo $! > "$work/server.pid"
  wait_http "http://127.0.0.1:$DEMO_PORT/readyz" "server" server
  (cd "$work" && env $(env_line) "$work/semantic-index" build) || fail "semantic-index build failed"
  trap - EXIT
  echo "semantic demo ready: http://127.0.0.1:$DEMO_PORT/ (Knowledge Library, Search mode: Semantic)"
  echo "embedding calls so far: $(curl -fsS http://127.0.0.1:$EMBED_PORT/stats)"
  ;;
index)
  [ -f "$work/$MARK" ] || fail "$work is not a semantic demo directory"
  work=$(cd "$work" && pwd)
  (cd "$work" && env $(env_line) "$work/semantic-index" "${3:-status}")
  ;;
down)
  [ -f "$work/$MARK" ] || fail "$work is not a semantic demo directory"
  work=$(cd "$work" && pwd)
  for p in server qdrant embeddings; do stop_owned "$p"; done
  [ ! -f "$work/demo/.flh034-demo" ] || sh "$REPO/scripts/demo/flh034/demo.sh" stop "$work/demo" >/dev/null
  echo stopped
  ;;
clean)
  [ -f "$work/$MARK" ] || fail "$work is not a semantic demo directory"
  sh "$0" down "$work"
  rm -rf "$work"; echo "removed $work"
  ;;
*) sed -n '2,21p' "$0"; exit 2 ;;
esac
