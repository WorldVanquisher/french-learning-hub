#!/bin/bash
# Daily-workflow v1.0 RC acceptance fixture. Builds the real server, then inside
# `unshare -rn` (a network namespace with loopback only) starts a fake
# OpenAI-compatible provider and the server on a fresh SQLite database, with
# the daily-use provider settings: AI_PROVIDER, EXTRACTOR_PROVIDER and
# SUGGESTION_PROVIDER all `openai`, pointed at the fake. journey.py then drives
# the three authored cases and the stale-confirmation boundary over HTTP.
# No real provider is reachable, the key is a placeholder, and the owner's
# daily database is never opened.
#
#   bash scripts/validation/daily_v1_rc/run.sh WORK_DIR
#
# WORK_DIR must be new or empty and outside the repository. Outputs in WORK_DIR:
# journey.txt (PASS/FAIL lines), evidence.json, provider-calls.log, server.log,
# fixture.db (kept for inspection; disposable).
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd -P)
WORK=${1:?usage: run.sh WORK_DIR}
WORK=$(realpath -m "$WORK")
case "$WORK/" in "$REPO"/*) echo "refused: WORK_DIR must be outside the repository" >&2; exit 2 ;; esac
mkdir -p "$WORK"
[ -z "$(ls -A "$WORK")" ] || { echo "refused: WORK_DIR must be empty" >&2; exit 2; }
command -v unshare > /dev/null || { echo "refused: unshare is required for the loopback-only namespace" >&2; exit 2; }
(cd "$REPO" && GOPROXY=off GOFLAGS=-mod=readonly go build -o "$WORK/server" ./cmd/server)

cat > "$WORK/session.sh" <<'INNER'
#!/bin/bash
set -u
W=$1 REPO=$2
V="$REPO/scripts/validation/daily_v1_rc"
ip link set lo up
: > "$W/provider-calls.log"
python3 -I -B "$V/fake_openai.py" 19195 "$W/provider-calls.log" "$V/cases.json" > "$W/provider.log" 2>&1 &
PROV=$!
(cd "$W" && exec env -i PATH="$PATH" LISTEN_HOST=127.0.0.1 PORT=19196 DB_PATH="$W/fixture.db" \
  AI_PROVIDER=openai EXTRACTOR_PROVIDER=openai SUGGESTION_PROVIDER=openai OPENAI_MODEL=fixture-model-placeholder \
  OPENAI_API_KEY=placeholder-not-a-real-key OPENAI_BASE_URL=http://127.0.0.1:19195/v1 \
  OPENAI_TIMEOUT=60 HTTP_WRITE_TIMEOUT=75 EMBEDDING_PROVIDER=disabled SEMANTIC_SEARCH=disabled \
  ./server) > "$W/server.log" 2>&1 &
SRV=$!
ready=0
for _ in $(seq 100); do
  if curl -fsS -o /dev/null http://127.0.0.1:19196/readyz 2> /dev/null; then ready=1; break; fi
  sleep 0.1
done
rc=0
if [ "$ready" = 1 ]; then
  echo "healthz: $(curl -fsS http://127.0.0.1:19196/healthz)"
  echo "readyz:  $(curl -fsS http://127.0.0.1:19196/readyz)"
  python3 -I -B "$V/journey.py" http://127.0.0.1:19196 "$W/fixture.db" "$W/provider-calls.log" "$V/cases.json" "$W/evidence.json" || rc=1
else
  echo "server not ready; see $W/server.log"; rc=1
fi
kill -TERM $SRV; wait $SRV; echo "server stop status: $?"
kill $PROV 2> /dev/null; wait 2> /dev/null
echo "integrity_check: $(sqlite3 -readonly "$W/fixture.db" 'PRAGMA integrity_check;' 2>&1)"
exit $rc
INNER
chmod 0755 "$WORK/session.sh"
set +e
unshare -rn "$WORK/session.sh" "$WORK" "$REPO" > "$WORK/journey.txt" 2>&1
rc=$?
set -e
cat "$WORK/journey.txt"
if grep -l 'placeholder-not-a-real-key' "$WORK"/*.log "$WORK/journey.txt" "$WORK/evidence.json" > /dev/null 2>&1; then
  echo "FAIL the placeholder key appears in an output"; rc=1
else
  echo "PASS no output contains the key"
fi
echo "outputs in $WORK"
exit $rc
