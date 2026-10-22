#!/bin/bash
# FLH-094 provider wiring check: the real server binary, configured the way the
# daily settings configure it (AI_PROVIDER=openai, EXTRACTOR_PROVIDER=openai,
# an explicit model and key), but pointed at a local fake OpenAI-compatible
# provider inside `unshare -rn` (loopback only). No real provider is reachable
# and no key is real.
#
#   bash scripts/validation/flh094/run_wiring.sh WORK_DIR
#
# WORK_DIR must be new/empty and outside the repository. Outputs: wiring.txt,
# server-1.log, server-2.log, provider-calls.log, config-refusal.log.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd -P)
WORK=${1:?usage: run_wiring.sh WORK_DIR}
WORK=$(realpath -m "$WORK")
case "$WORK/" in "$REPO"/*) echo "refused: WORK_DIR must be outside the repository" >&2; exit 2 ;; esac
mkdir -p "$WORK"
[ -z "$(ls -A "$WORK")" ] || { echo "refused: WORK_DIR must be empty" >&2; exit 2; }
(cd "$REPO" && GOPROXY=off GOFLAGS=-mod=readonly go build -o "$WORK/server" ./cmd/server)

cat > "$WORK/session.sh" <<'INNER'
#!/bin/bash
set -u
W=$1 REPO=$2
V="$REPO/scripts/validation/flh094"
MODEL=owner-chosen-model-placeholder
ip link set lo up
: > "$W/provider-calls.log"
python3 -B "$V/fake_openai.py" 19095 "$W/provider-calls.log" > "$W/provider.log" 2>&1 &
PROV=$!
start_server() { # start_server LOGNAME
  (cd "$W" && exec env -i PATH="$PATH" LISTEN_HOST=127.0.0.1 PORT=19096 DB_PATH="$W/daily/app.db" \
    AI_PROVIDER=openai EXTRACTOR_PROVIDER=openai OPENAI_MODEL="$MODEL" \
    OPENAI_API_KEY=placeholder-not-a-real-key OPENAI_BASE_URL=http://127.0.0.1:19095/v1 \
    OPENAI_TIMEOUT=60 HTTP_WRITE_TIMEOUT=75 EMBEDDING_PROVIDER=disabled SEMANTIC_SEARCH=disabled \
    ./server) >> "$W/$1" 2>&1 &
  SRV=$!
  for _ in $(seq 100); do curl -fsS -o /dev/null http://127.0.0.1:19096/readyz 2>/dev/null && return 0; sleep 0.1; done
  echo "server not ready; see $W/$1" >&2; return 1
}
mkdir -m 700 "$W/daily"
rc=0
start_server server-1.log || exit 1
python3 -B "$V/wiring.py" http://127.0.0.1:19096 "$W/provider-calls.log" "$MODEL" first "$W/state.json" || rc=1
kill -TERM $SRV; wait $SRV; echo "server stop status: $?"
start_server server-2.log || exit 1
python3 -B "$V/wiring.py" http://127.0.0.1:19096 "$W/provider-calls.log" "$MODEL" restart "$W/state.json" || rc=1
kill -TERM $SRV; wait $SRV; echo "server stop status: $?"
# A requested real provider without a key must stop startup, never fall back.
(cd "$W" && env -i PATH="$PATH" LISTEN_HOST=127.0.0.1 PORT=19097 DB_PATH="$W/refusal.db" \
  AI_PROVIDER=openai OPENAI_MODEL="$MODEL" EXTRACTOR_PROVIDER=openai timeout 10 ./server) > "$W/config-refusal.log" 2>&1
echo "missing-key startup status: $? ($(tail -n 1 "$W/config-refusal.log"))"
[ ! -e "$W/refusal.db" ] && echo "missing-key startup created no database" || { echo "missing-key startup created a database"; rc=1; }
kill $PROV 2>/dev/null; wait 2>/dev/null
exit $rc
INNER
chmod 0755 "$WORK/session.sh"
set +e
unshare -rn "$WORK/session.sh" "$WORK" "$REPO" > "$WORK/wiring.txt" 2>&1
rc=$?
set -e
cat "$WORK/wiring.txt"
grep -l 'placeholder-not-a-real-key' "$WORK"/*.log > /dev/null 2>&1 && { echo "FAIL the placeholder key appears in a log"; rc=1; } || echo "PASS no log contains the key"
echo "outputs in $WORK"
exit $rc
