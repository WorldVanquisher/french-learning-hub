#!/bin/bash
# FLH-092 manual browser acceptance session: serve the private workbench over a
# persistent synthetic fixture, in the foreground, until Ctrl-C.
#
#   bash scripts/validation/flh092/serve.sh WORK_DIR [PORT [STUB_PORT]]
#
# WORK_DIR must be outside the repository and either new/empty (first run:
# build, seed through the public API with the FLH-089 seeder, then serve) or a
# directory this script already seeded (restart: serve the same database, no
# reseeding, nothing overwritten). Anything else is refused.
# PORT (default 18990) is the server; STUB_PORT (default 18991) is the local
# FLH-089 stub extractor. FLH092_RECORDS / FLH092_CONCEPTS change the seed size
# on a first run only (defaults 1000 / 500).
#
# NOT network-namespace isolated: unlike flh089/run.sh this cannot use
# `unshare -rn`, because the browser (through an SSH tunnel) must reach the
# server. Isolation rests on configuration only: both processes bind 127.0.0.1;
# they start with an empty environment (env -i) plus explicit settings; the
# analyzer is the local rule-based one; the extractor points at the loopback
# stub with a fake key; embedding and semantic search are disabled; DB_PATH is
# WORK_DIR/fixture.db. The fixture is synthetic: it proves mechanics only, not
# language quality.
#
# Ctrl-C (or TERM) stops only the two processes this invocation started and
# keeps WORK_DIR, so a later run with the same WORK_DIR restarts on the same
# database.
set -euo pipefail

die() { echo "serve.sh: $*" >&2; exit 2; }

REPO=$(cd "$(dirname "$0")/../../.." && pwd)
WORK=${1:-}
[ -n "$WORK" ] || die "usage: serve.sh WORK_DIR [PORT [STUB_PORT]]"
PORT=${2:-18990}
STUB_PORT=${3:-18991}
RECORDS=${FLH092_RECORDS:-1000}
CONCEPTS=${FLH092_CONCEPTS:-500}
MARKER=flh092-session

for p in "$PORT" "$STUB_PORT"; do
  [[ "$p" =~ ^[0-9]+$ ]] && [ "$p" -ge 1024 ] && [ "$p" -le 65535 ] || die "ports must be numbers 1024-65535 (got '$p')"
done
[ "$PORT" != "$STUB_PORT" ] || die "PORT and STUB_PORT must differ"
[[ "$RECORDS" =~ ^[0-9]+$ && "$CONCEPTS" =~ ^[0-9]+$ ]] || die "FLH092_RECORDS and FLH092_CONCEPTS must be whole numbers"

# Prerequisites.
for cmd in go python3 curl; do
  command -v "$cmd" > /dev/null || die "missing prerequisite: $cmd"
done
DIST="$REPO/web/dist"
[ -f "$DIST/index.html" ] && [ -d "$DIST/assets" ] \
  || die "missing frontend build ($DIST). Build it first: cd web && npm ci && npm run build"
if [ -n "$(find "$REPO/web/src" "$REPO/web/index.html" -newer "$DIST/index.html" -type f -print -quit 2> /dev/null)" ]; then
  echo "serve.sh: warning: web/src has files newer than web/dist; the browser will see the older build (rebuild: cd web && npm run build)" >&2
fi

# Work directory: outside the repository; fresh only when empty; restart only
# when it carries this script's completed-seed marker.
WORK=$(realpath -m "$WORK")
case "$WORK/" in "$REPO"/*) die "WORK_DIR must be outside the repository" ;; esac
MODE=
if [ ! -e "$WORK" ] || { [ -d "$WORK" ] && [ -z "$(ls -A "$WORK")" ]; }; then
  MODE=fresh
elif [ -d "$WORK" ] && [ -f "$WORK/$MARKER" ] && [ -f "$WORK/fixture.db" ]; then
  MODE=restart
elif [ -d "$WORK" ] && [ -f "$WORK/$MARKER.seeding" ]; then
  die "WORK_DIR holds an incomplete seed from an earlier run; use a new empty directory"
else
  die "WORK_DIR must be a new/empty directory or one seeded by this script (refusing to touch $WORK)"
fi
[ ! -e "$WORK/.env" ] || die "WORK_DIR contains .env; the server would read it. Remove it or use another directory"

# Ports: refuse anything already listening or bound on loopback.
port_free() {
  python3 -I -c 'import socket,sys
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try: s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError: sys.exit(1)' "$1"
}
port_free "$PORT" || die "port $PORT on 127.0.0.1 is already in use; stop that process or pass another PORT"
port_free "$STUB_PORT" || die "stub port $STUB_PORT on 127.0.0.1 is already in use; stop that process or pass another STUB_PORT"

mkdir -p "$WORK"
echo "serve.sh: building the server ($MODE run)…"
(cd "$REPO" && GOPROXY=off GOFLAGS=-mod=readonly go build -o "$WORK/server" ./cmd/server) || die "go build failed"

SRV= STUB=
cleanup() {
  trap - EXIT INT TERM
  for pid in $SRV $STUB; do kill "$pid" 2> /dev/null || true; done
  for pid in $SRV $STUB; do wait "$pid" 2> /dev/null || true; done
}
on_signal() {
  cleanup
  echo
  echo "serve.sh: stopped the server and stub started by this run. Data kept in $WORK"
  if [ -f "$WORK/$MARKER.seeding" ]; then
    echo "serve.sh: seeding was interrupted, so this WORK_DIR will be refused; use a new empty directory"
    exit 1
  fi
  echo "serve.sh: restart with the same command: bash $0 $WORK $PORT $STUB_PORT"
  exit 0
}
trap cleanup EXIT
trap on_signal INT TERM

BASE_ENV=(env -i "PATH=/usr/local/bin:/usr/bin:/bin" "HOME=$WORK" "LANG=C.UTF-8")
"${BASE_ENV[@]}" python3 -B -I "$REPO/scripts/validation/flh089/stub_extractor.py" "$STUB_PORT" >> "$WORK/stub.log" 2>&1 &
STUB=$!
(cd "$WORK" && exec "${BASE_ENV[@]}" \
  LISTEN_HOST=127.0.0.1 PORT="$PORT" DB_PATH="$WORK/fixture.db" \
  AI_PROVIDER=rule-based \
  EXTRACTOR_PROVIDER=openai OPENAI_API_KEY=sk-local-fixture-not-a-secret \
  OPENAI_BASE_URL="http://127.0.0.1:$STUB_PORT" OPENAI_MODEL=stub-model \
  EMBEDDING_PROVIDER=disabled SEMANTIC_SEARCH=disabled \
  HTTP_TRUSTED_ORIGINS="http://127.0.0.1:$PORT,http://localhost:$PORT" \
  ./server -web-dir "$DIST") >> "$WORK/server.log" 2>&1 &
SRV=$!

ready=0
for _ in $(seq 150); do
  kill -0 "$SRV" 2> /dev/null || break
  if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/readyz" 2> /dev/null; then ready=1; break; fi
  sleep 0.1
done
[ "$ready" = 1 ] || { echo "serve.sh: server did not become ready; see $WORK/server.log" >&2; exit 1; }
kill -0 "$STUB" 2> /dev/null || { echo "serve.sh: stub extractor exited; see $WORK/stub.log" >&2; exit 1; }

if [ "$MODE" = fresh ]; then
  echo "serve.sh: seeding $RECORDS synthetic records and $CONCEPTS Concepts…"
  : > "$WORK/$MARKER.seeding"
  if ! python3 -B -I "$REPO/scripts/validation/flh089/seed.py" "http://127.0.0.1:$PORT" \
      --records "$RECORDS" --concepts "$CONCEPTS" > "$WORK/seed.json"; then
    echo "serve.sh: seeding failed; this WORK_DIR will be refused. Use a new empty directory" >&2
    exit 1
  fi
  printf 'seeded by scripts/validation/flh092/serve.sh: %s records, %s concepts\n' "$RECORDS" "$CONCEPTS" > "$WORK/$MARKER"
  rm -f "$WORK/$MARKER.seeding"
  echo "serve.sh: seed summary: $(cat "$WORK/seed.json")"
fi

cat <<EOF

FLH-092 workbench session ready ($MODE run). Synthetic data only; not network-namespace isolated.
  Server:   http://127.0.0.1:$PORT/   (PID $SRV, log $WORK/server.log)
  Stub:     http://127.0.0.1:$STUB_PORT  (PID $STUB, log $WORK/stub.log)
  Database: $WORK/fixture.db
  From the Mac:  ssh -N -L $PORT:127.0.0.1:$PORT <SSH_HOST>
  Then open:     http://127.0.0.1:$PORT/
Press Ctrl-C to stop. The data stays in $WORK.
EOF

# Foreground until Ctrl-C or until either process exits on its own.
set +e
wait -n "$SRV" "$STUB"
rc=$?
set -e
echo "serve.sh: a process exited unexpectedly (status $rc); stopping. See $WORK/server.log and $WORK/stub.log" >&2
exit 1
