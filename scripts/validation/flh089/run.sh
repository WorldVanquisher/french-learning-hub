#!/bin/bash
# FLH-089 synthetic daily-workflow fixture: build, seed, measure, walk through.
#
#   bash scripts/validation/flh089/run.sh WORK_DIR [RECORDS] [CONCEPTS]
#
# WORK_DIR must be a new or empty directory outside the repository. Everything
# runs inside `unshare -rn` (Linux): a private network namespace with loopback
# only, so neither the server nor the local stub extractor can reach a real
# provider. The server listens on 127.0.0.1:18989 and the stub on 18988 inside
# that namespace. The fixture database is WORK_DIR/fixture.db; the seeded copy
# is kept as WORK_DIR/fixture-seeded.db before the workflow writes to it.
# Outputs: seed.json, measure.json, workflow.txt, server.log, stub.log.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
WORK=${1:?usage: run.sh WORK_DIR [RECORDS] [CONCEPTS]}
RECORDS=${2:-1000}
CONCEPTS=${3:-500}
WORK=$(realpath -m "$WORK")
case "$WORK/" in "$REPO"/*) echo "refused: WORK_DIR must be outside the repository" >&2; exit 2 ;; esac
mkdir -p "$WORK"
[ -z "$(ls -A "$WORK")" ] || { echo "refused: WORK_DIR must be empty" >&2; exit 2; }
command -v unshare > /dev/null || { echo "refused: unshare (util-linux) is required for network isolation" >&2; exit 2; }

(cd "$REPO" && GOPROXY=off GOFLAGS=-mod=readonly go build -o "$WORK/server" ./cmd/server)

cat > "$WORK/session.sh" <<'EOF'
#!/bin/bash
# session.sh WORK REPO CMD...: stub + server on loopback, run CMD, stop both.
set -u
W=$1 REPO=$2; shift 2
ip link set lo up
python3 -B "$REPO/scripts/validation/flh089/stub_extractor.py" 18988 > "$W/stub.log" 2>&1 &
STUB=$!
(cd "$W" && exec env LISTEN_HOST=127.0.0.1 PORT=18989 DB_PATH="$W/fixture.db" AI_PROVIDER=rule-based \
  EXTRACTOR_PROVIDER=openai EMBEDDING_PROVIDER=disabled SEMANTIC_SEARCH=disabled \
  OPENAI_API_KEY=sk-local-fixture-not-a-secret OPENAI_BASE_URL=http://127.0.0.1:18988 OPENAI_MODEL=stub-model \
  ./server) >> "$W/server.log" 2>&1 &
SRV=$!
ready=0
for _ in $(seq 100); do curl -fsS -o /dev/null http://127.0.0.1:18989/readyz 2>/dev/null && { ready=1; break; }; sleep 0.1; done
[ "$ready" = 1 ] || { echo "server not ready; see $W/server.log" >&2; kill $SRV $STUB 2>/dev/null; exit 1; }
"$@"; rc=$?
kill $SRV $STUB 2>/dev/null; wait 2>/dev/null
exit $rc
EOF
chmod 0755 "$WORK/session.sh"

V="$REPO/scripts/validation/flh089"
unshare -rn "$WORK/session.sh" "$WORK" "$REPO" python3 -B "$V/seed.py" http://127.0.0.1:18989 \
  --records "$RECORDS" --concepts "$CONCEPTS" > "$WORK/seed.json"
cp "$WORK/fixture.db" "$WORK/fixture-seeded.db"
unshare -rn "$WORK/session.sh" "$WORK" "$REPO" python3 -B "$V/measure.py" http://127.0.0.1:18989 > "$WORK/measure.json"
unshare -rn "$WORK/session.sh" "$WORK" "$REPO" python3 -B "$V/workflow.py" http://127.0.0.1:18989 > "$WORK/workflow.txt"
cat "$WORK/seed.json"
tail -n 1 "$WORK/workflow.txt"
echo "outputs in $WORK"
