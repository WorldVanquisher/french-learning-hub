#!/usr/bin/env bash
# FLH-076 local smoke of a release package, on loopback.
#
#   bash scripts/demo/flh076/smoke_package.sh /abs/package/dir /abs/new/runtime/dir [port]
#
# On Linux it uses the package's own binaries; elsewhere it builds host
# binaries from this source tree (SERVER_BIN/PREPARE) and says so. It runs
# validate-release.sh, starts the demo with deploy/ctl.sh, checks allowed and
# denied requests, preset-vector counters and unchanged package files, and
# stops the server. Exit 0 only if every check passed.
set -euo pipefail
PKG=${1:?usage}; RUN=${2:?usage}; PORT=${3:-18978}
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
[ ! -e "$RUN" ] || { echo "refused: $RUN exists" >&2; exit 2; }
mkdir -p "$RUN"
FAILED=0; note() { echo "$*" | tee -a "$RUN/smoke.txt"; }
if [ "$(uname -s)" != Linux ]; then
  (cd "$REPO" && go build -o "$RUN/host-server" ./cmd/server && go build -o "$RUN/host-prepare" ./scripts/demo/flh073/prepare)
  export SERVER_BIN="$RUN/host-server" PREPARE="$RUN/host-prepare"
  note "NOTE: non-Linux host: using host builds of this source instead of the package's linux binaries"
fi
if command -v sha256sum >/dev/null 2>&1; then sha256() { sha256sum "$@"; }; else sha256() { shasum -a 256 "$@"; }; fi
tree_sha() { (cd "$PKG" && find . -type f | LC_ALL=C sort | while IFS= read -r f; do sha256 "$f"; done | sha256); }
before=$(tree_sha)
set +e; "$PKG/validate-release.sh" > "$RUN/validate.out" 2>&1; V=$?; set -e
STATUS=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["release_status"])' "$PKG/RELEASE.json")
note "validate-release.sh exit $V ($(tail -1 "$RUN/validate.out")); RELEASE.json status $STATUS"
if { [ "$STATUS" = BLOCKED ] && [ "$V" = 3 ]; } || { [ "$STATUS" = CANDIDATE ] && [ "$V" = 0 ]; }; then note "PASS release validation matches status"; else note "FAIL release validation"; FAILED=1; fi
[ "$STATUS" = BLOCKED ] && export ALLOW_MECHANICAL=1
PORT=$PORT "$PKG/deploy/ctl.sh" start "$RUN" | tee -a "$RUN/smoke.txt"
trap 'PORT=$PORT "$PKG/deploy/ctl.sh" stop "$RUN" >/dev/null 2>&1 || true' EXIT
PORT=$PORT "$PKG/deploy/ctl.sh" status "$RUN" | tee -a "$RUN/smoke.txt"
B="http://127.0.0.1:$PORT"
expect() { local got; got=$(curl -s -o /dev/null -w '%{http_code}' -X "$1" "$B$2"); if [ "$got" = "$3" ]; then note "PASS $1 $2 -> $got"; else note "FAIL $1 $2 -> $got (want $3)"; FAILED=1; fi; }
counters() { curl -fsS "$B/knowledge-library/demo" | python3 -c 'import json,sys; c=json.load(sys.stdin)["counters"]; print(c["preset_vector_lookups"], c["refused_vector_lookups"])'; }
C0=$(counters)
for p in / /healthz /readyz /knowledge-library/concepts /api/knowledge-library/concepts/1 /api/knowledge-library/units/1/source; do expect GET "$p" 200; done
for p in /favicon.ico /knowledge-library/semantic-search?q=x /api/entries /concepts /annotation-dataset/v1/export /artifact/demo.db /RELEASE.json /assets/; do expect GET "$p" 404; done
for m in POST PUT DELETE; do expect "$m" /api/knowledge-library/concepts 405; done
expect GET "/api/knowledge-library/demo/hybrid-search?q=free" 400
C1=$(counters)
[ "$C0" = "$C1" ] && note "PASS counters unchanged by denied requests ($C1)" || { note "FAIL counters $C0 -> $C1"; FAILED=1; }
expect GET "/api/knowledge-library/demo/semantic-search?preset=no-longer" 200
expect GET "/api/knowledge-library/demo/hybrid-search?preset=subjunctive" 200
C2=$(counters)
[ "$C2" = "2 0" ] && note "PASS two preset searches, two cached lookups ($C2)" || { note "FAIL counters $C2"; FAILED=1; }
PORT=$PORT "$PKG/deploy/ctl.sh" stop "$RUN" | tee -a "$RUN/smoke.txt"
trap - EXIT
after=$(tree_sha)
[ "$before" = "$after" ] && note "PASS package files unchanged by the run" || { note "FAIL package files changed"; FAILED=1; }
[ "$FAILED" = 0 ] && note "PACKAGE SMOKE PASSED" || note "PACKAGE SMOKE FAILED"
exit "$FAILED"
