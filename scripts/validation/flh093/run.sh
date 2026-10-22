#!/bin/bash
# FLH-093 isolated Concept-content fixture: authored French-learning content,
# built and checked through the public HTTP API only.
#
#   bash scripts/validation/flh093/run.sh WORK_DIR
#
# WORK_DIR must be a new or empty directory outside the repository. Everything
# runs inside `unshare -rn` (Linux): a loopback-only network namespace, so
# neither the server nor the local stub extractor can reach a real provider.
# The server listens on 127.0.0.1:19093 and the stub on 19094 inside that
# namespace; the database is WORK_DIR/fixture.db. Outputs: check.txt,
# server.log, stub.log, stub-calls.log. The content is synthetic.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
WORK=${1:?usage: run.sh WORK_DIR}
WORK=$(realpath -m "$WORK")
case "$WORK/" in "$REPO"/*) echo "refused: WORK_DIR must be outside the repository" >&2; exit 2 ;; esac
mkdir -p "$WORK"
[ -z "$(ls -A "$WORK")" ] || { echo "refused: WORK_DIR must be empty" >&2; exit 2; }
command -v unshare > /dev/null || { echo "refused: unshare (util-linux) is required for network isolation" >&2; exit 2; }

(cd "$REPO" && GOPROXY=off GOFLAGS=-mod=readonly go build -o "$WORK/server" ./cmd/server)

cat > "$WORK/session.sh" <<'INNER'
#!/bin/bash
set -u
W=$1 REPO=$2; shift 2
ip link set lo up
: > "$W/stub-calls.log"
python3 -B "$REPO/scripts/validation/flh093/stub_extractor.py" 19094 "$W/stub-calls.log" > "$W/stub.log" 2>&1 &
STUB=$!
(cd "$W" && exec env -i PATH="$PATH" LISTEN_HOST=127.0.0.1 PORT=19093 DB_PATH="$W/fixture.db" AI_PROVIDER=rule-based \
  EXTRACTOR_PROVIDER=openai EMBEDDING_PROVIDER=disabled SEMANTIC_SEARCH=disabled \
  OPENAI_API_KEY=sk-local-fixture-not-a-secret OPENAI_BASE_URL=http://127.0.0.1:19094 OPENAI_MODEL=stub-model \
  ./server) >> "$W/server.log" 2>&1 &
SRV=$!
ready=0
for _ in $(seq 100); do curl -fsS -o /dev/null http://127.0.0.1:19093/readyz 2>/dev/null && { ready=1; break; }; sleep 0.1; done
[ "$ready" = 1 ] || { echo "server not ready; see $W/server.log" >&2; kill $SRV $STUB 2>/dev/null; exit 1; }
"$@"; rc=$?
kill $SRV $STUB 2>/dev/null; wait 2>/dev/null
exit $rc
INNER
chmod 0755 "$WORK/session.sh"

set +e
unshare -rn "$WORK/session.sh" "$WORK" "$REPO" python3 -B "$REPO/scripts/validation/flh093/check.py" \
  http://127.0.0.1:19093 "$WORK/fixture.db" "$WORK/stub-calls.log" > "$WORK/check.txt"
rc=$?
set -e
cat "$WORK/check.txt"
echo "outputs in $WORK"
exit $rc
