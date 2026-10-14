#!/usr/bin/env bash
# FLH-073 local smoke test of the read-only public demo, on loopback only.
#
#   bash scripts/demo/flh073/smoke.sh /abs/new/work/dir [port]
#
# Builds the server and prepare binaries, a MECHANICAL artifact and the demo
# web build into WORK, starts the demo with an explicit, empty environment
# (cwd WORK, so no repository .env is read), sends real requests to allowed and
# denied routes at the root and under /api, checks that the database bytes,
# fingerprint and preset-vector counters are unchanged by denied requests, then
# stops the server it started. No model, provider, Docker or network beyond
# 127.0.0.1 is used. Exit 0 only if every check passed.
set -euo pipefail

WORK=${1:?usage: smoke.sh /abs/new/work/dir [port]}
PORT=${2:-18973}
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
case "$WORK" in /*) ;; *) echo "refused: WORK must be an absolute path" >&2; exit 2 ;; esac
case "$WORK/" in "$REPO"/*) echo "refused: WORK must be outside the repository" >&2; exit 2 ;; esac
[ ! -e "$WORK" ] || { echo "refused: $WORK already exists" >&2; exit 2; }
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then echo "refused: port $PORT is in use" >&2; exit 2; fi

mkdir -p "$WORK/bin"
RESULTS="$WORK/smoke-results.txt"
: > "$RESULTS"
FAILED=0
note() { echo "$*" | tee -a "$RESULTS"; }

(cd "$REPO" && go build -o "$WORK/bin/server" ./cmd/server && go build -o "$WORK/bin/prepare" ./scripts/demo/flh073/prepare)
(cd "$REPO" && "$WORK/bin/prepare" build -out "$WORK/artifact" -fixtures scripts/demo/flh073/fixtures/catalog.json > "$WORK/prepare-build.json")
set +e
"$WORK/bin/prepare" validate -artifact "$WORK/artifact" > "$WORK/validate.json" 2>&1; VALIDATE=$?
"$WORK/bin/prepare" validate -artifact "$WORK/artifact" -release > "$WORK/validate-release.json" 2> "$WORK/validate-release.err"; RELEASE=$?
set -e
note "artifact validate exit $VALIDATE (want 0); release validate exit $RELEASE (want 3 = BLOCKED, mechanical vectors)"
[ "$VALIDATE" = 0 ] && [ "$RELEASE" = 3 ] || FAILED=1
(cd "$REPO/web" && VITE_FLH_PUBLIC_DEMO=1 npx vite build --outDir "$WORK/web" --emptyOutDir > "$WORK/web-build.log" 2>&1)

run_server() { # extra env assignments as arguments
  (cd "$WORK" && exec env -i PATH=/usr/bin:/bin HOME="$WORK" LISTEN_HOST=127.0.0.1 PORT="$PORT" "$@" \
    "$WORK/bin/server" -public-demo-artifact "$WORK/artifact" -public-demo-allow-mechanical -web-dir "$WORK/web")
}

# A configuration enabling a provider must refuse to start.
set +e
run_server EMBEDDING_PROVIDER=http EMBEDDING_BASE_URL=http://127.0.0.1:9/v1 EMBEDDING_MODEL=m EMBEDDING_MODEL_ID=m EMBEDDING_DIMENSIONS=8 > "$WORK/refused-provider.log" 2>&1
RC=$?
set -e
if [ "$RC" != 0 ] && grep -q "refuses live providers" "$WORK/refused-provider.log"; then note "PASS provider-enabled config refused at startup (exit $RC)"; else note "FAIL provider-enabled config (exit $RC)"; FAILED=1; fi

chmod -R a-w "$WORK/artifact"
DB_SHA_BEFORE=$(shasum -a 256 "$WORK/artifact/demo.db" | cut -d' ' -f1)
# Started without a wrapper function so that $! is the server process itself
# (the subshell execs env, which execs the server).
(cd "$WORK" && exec env -i PATH=/usr/bin:/bin HOME="$WORK" LISTEN_HOST=127.0.0.1 PORT="$PORT" \
  "$WORK/bin/server" -public-demo-artifact "$WORK/artifact" -public-demo-allow-mechanical -web-dir "$WORK/web") > "$WORK/server.log" 2>&1 &
PID=$!
echo "$PID" > "$WORK/server.pid"
stop_server() { # signals only the process this script started, after checking its command line
  if kill -0 "$PID" 2>/dev/null; then
    if ps -p "$PID" -o command= | grep -q "^$WORK/bin/server -public-demo-artifact"; then
      kill "$PID"; wait "$PID" 2>/dev/null || true
    else
      note "FAIL: PID $PID is not the server this script started; not signalled"; FAILED=1
    fi
  fi
  chmod -R u+w "$WORK/artifact" 2>/dev/null || true
}
trap stop_server EXIT
for _ in $(seq 1 50); do curl -fsS "http://127.0.0.1:$PORT/readyz" >/dev/null 2>&1 && break; sleep 0.2; done

BASE="http://127.0.0.1:$PORT"
expect() { # method path want
  local got # exactly one request per check
  case "$1" in
    GET) got=$(curl -s -o /dev/null -w '%{http_code}' "$BASE$2" 2>/dev/null || true) ;;
    HEAD) got=$(curl -s -o /dev/null -I -w '%{http_code}' "$BASE$2" 2>/dev/null || true) ;;
    *) got=$(curl -s -o /dev/null -w '%{http_code}' -X "$1" -H 'Content-Type: application/json' --data-binary '{}' "$BASE$2" 2>/dev/null || true) ;;
  esac
  if [ "$got" = "$3" ]; then note "PASS $1 $2 -> $got"; else note "FAIL $1 $2 -> $got (want $3)"; FAILED=1; fi
}
counters() { curl -fsS "$BASE/knowledge-library/demo" | python3 -c 'import json,sys; c=json.load(sys.stdin)["counters"]; print(c["preset_vector_lookups"], c["refused_vector_lookups"])'; }

C0=$(counters)
for prefix in "" "/api"; do
  for p in /healthz /readyz /knowledge-library/concepts "/knowledge-library/concepts?q=subj" /knowledge-library/concepts/1 \
           /knowledge-library/units/1/source /knowledge-library/demo; do expect GET "$prefix$p" 200; done
  for p in "/knowledge-library/semantic-search?q=anything" "/knowledge-library/hybrid-search?q=anything" /entries /concepts \
           /reviewable-units /retrieval-evaluation/v1 /retrieval-comparison/v1 /annotation-dataset/v1/export /inventory /unknown; do
    expect GET "$prefix$p" 404
  done
  for m in POST PUT PATCH DELETE; do
    for p in /entries /captures /concepts /knowledge-library/concepts "/knowledge-library/demo/hybrid-search?preset=subjunctive"; do expect "$m" "$prefix$p" 405; done
  done
  expect GET "$prefix/knowledge-library/demo/semantic-search?q=free+text" 400
  expect GET "$prefix/knowledge-library/demo/hybrid-search?preset=miss-someone&q=free+text" 400
  expect GET "$prefix/knowledge-library/demo/hybrid-search?preset=unknown" 404
done
expect GET / 200
expect HEAD /knowledge-library/demo 200
C1=$(counters)
if [ "$C0" = "$C1" ] && [ "$C1" = "0 0" ]; then note "PASS preset-vector counters unchanged by denied requests ($C1)"; else note "FAIL counters $C0 -> $C1"; FAILED=1; fi

for prefix in "" "/api"; do
  expect GET "$prefix/knowledge-library/demo/semantic-search?preset=miss-someone" 200
  expect GET "$prefix/knowledge-library/demo/hybrid-search?preset=subjunctive&state=active" 200
done
C2=$(counters)
if [ "$C2" = "4 0" ]; then note "PASS four preset searches used four cached vectors, none refused ($C2)"; else note "FAIL counters after preset searches: $C2"; FAILED=1; fi
SAME=$(python3 - "$BASE" <<'PY'
import json, sys, urllib.request
b = sys.argv[1]
r = json.load(urllib.request.urlopen(b + "/knowledge-library/demo/hybrid-search?preset=miss-someone"))
a = json.load(urllib.request.urlopen(b + "/api/knowledge-library/demo/hybrid-search?preset=miss-someone"))
print("same" if r == a and r["query"] == "how to tell a friend I miss them" and r["policy"]["version"] == "concept_hybrid_rrf_v1" else "different")
PY
)
if [ "$SAME" = same ]; then note "PASS hybrid preset: root == /api, exact preset text, policy concept_hybrid_rrf_v1"; else note "FAIL hybrid preset comparison"; FAILED=1; fi
curl -fsS "$BASE/knowledge-library/demo/hybrid-search?preset=miss-someone" > "$WORK/sample-hybrid.json"

stop_server
trap - EXIT
if kill -0 "$PID" 2>/dev/null; then note "FAIL server still running"; FAILED=1; else note "PASS server stopped"; fi
DB_SHA_AFTER=$(shasum -a 256 "$WORK/artifact/demo.db" | cut -d' ' -f1)
if [ "$DB_SHA_BEFORE" = "$DB_SHA_AFTER" ] && [ ! -e "$WORK/artifact/demo.db-wal" ]; then note "PASS demo.db unchanged ($DB_SHA_AFTER), no -wal file"; else note "FAIL demo.db changed"; FAILED=1; fi
"$WORK/bin/prepare" validate -artifact "$WORK/artifact" > "$WORK/validate-after.json" 2>&1 && note "PASS artifact still validates after the run" || { note "FAIL artifact no longer validates"; FAILED=1; }
note "results: $RESULTS; server log: $WORK/server.log"
[ "$FAILED" = 0 ] && note "SMOKE PASSED" || note "SMOKE FAILED"
exit "$FAILED"
