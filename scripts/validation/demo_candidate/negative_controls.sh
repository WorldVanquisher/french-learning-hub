#!/usr/bin/env bash
# Negative controls for the public-demo package check (demo-candidate lane):
# each feeds check_package.sh or write_probe.sh something the release gate must
# reject, and passes only when that failure is actually detected.
#
#   bash scripts/validation/demo_candidate/negative_controls.sh PKG_DIR /abs/new/work/dir \
#        [--control-package PRE_FIX_PKG_DIR] [--port N] [--node-modules DIR]
#
#   identity   check_package.sh with a wrong --expect-version, then a wrong
#              --expect-manifest: must exit 1 with "identity mismatch" in the
#              identity and live stages.
#   write      the package's own server started WITHOUT -public-demo-artifact (a
#              normal server on a disposable database in WORK, providers off): the
#              write probe must exit 1 naming the accepted writes, and the database
#              must hold the probe's entry (the write really happened).
#   link       check_package.sh on a package built from a tree without the
#              malformed-link handling (--control-package; for example main at
#              521279a): identity, boundary, live and writes must pass, the browser
#              stage must fail, on "a malformed link opens the start with a notice".
#              Needs CHROME and --node-modules; NOT RUN without them or without
#              --control-package.
#
# Ports N..N+4 on loopback (default 18986). Nothing outside WORK is written.
# Exit: 0 every control that ran detected its failure; 1 a control was missed;
# 2 usage or refused.
set -uo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
HERE=$REPO/scripts/validation/demo_candidate
PKG=${1:-}; WORK=${2:-}
[ -n "$PKG" ] && [ -n "$WORK" ] || { sed -n '2,25p' "$0" >&2; exit 2; }
shift 2
CONTROL_PKG= PORT=18986 NODE_MODULES=
while [ $# -gt 0 ]; do
  case "$1" in
    --control-package) CONTROL_PKG=${2:-}; shift 2 ;;
    --port) PORT=${2:-}; shift 2 ;;
    --node-modules) NODE_MODULES=${2:-}; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
case "$WORK" in /*) ;; *) echo "refused: WORK must be absolute" >&2; exit 2 ;; esac
case "$WORK/" in "$REPO"/*) echo "refused: WORK must be outside the repository" >&2; exit 2 ;; esac
[ ! -e "$WORK" ] || { echo "refused: $WORK exists" >&2; exit 2; }
[ -f "$PKG/RELEASE.json" ] || { echo "refused: $PKG is not a public-demo package" >&2; exit 2; }
[[ "$PORT" =~ ^[0-9]{4,5}$ ]] || { echo "refused: --port must be a number" >&2; exit 2; }
PKG=$(cd "$PKG" && pwd)
mkdir -p "$WORK"
MISSED=0
declare -A RESULT
note() { echo "$*" | tee -a "$WORK/controls.txt"; }
count() { local n; n=$(grep -c -- "$1" "$2" 2>/dev/null || true); echo "${n:-0}"; }
verdict() { RESULT[$1]=$2; note "CONTROL $1: $2${3:+ — $3}"; [ "$2" = MISSED ] && MISSED=1; return 0; }

# identity: a wrong expected version, then a wrong expected manifest.
for kind in version manifest; do
  if [ $kind = version ]; then flag=(--expect-version 0000000000000000); else flag=(--expect-manifest "$(printf '0%.0s' $(seq 64))"); fi
  bash "$HERE/check_package.sh" "$PKG" "$WORK/identity-$kind" "${flag[@]}" --port "$PORT" --skip-browser > "$WORK/identity-$kind.out" 2>&1
  rc=$?
  stages=$(python3 -I -c 'import json,sys; s=json.load(open(sys.argv[1]))["stages"]; print(s["identity"], s["live"])' "$WORK/identity-$kind/summary.json" 2>/dev/null)
  if [ "$rc" = 1 ] && [ "$stages" = "FAIL FAIL" ] && grep -q "identity mismatch" "$WORK/identity-$kind/identity.txt" && grep -q "identity mismatch" "$WORK/identity-$kind/live-identity.txt"; then
    verdict "identity-$kind" DETECTED "exit 1; $(grep -h 'identity mismatch' "$WORK/identity-$kind/identity.txt" | head -1)"
  else
    verdict "identity-$kind" MISSED "exit $rc, stages [$stages]"
  fi
done

# write: the same binary without the public-demo boundary, on a throwaway database.
case "$(uname -m)" in x86_64|amd64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) ARCH=unknown ;; esac
BIN=$PKG/bin/linux-$ARCH/flh-server
W=$WORK/write; mkdir -p "$W"
P=$((PORT + 2))
if (exec 3<>"/dev/tcp/127.0.0.1/$P") 2>/dev/null; then
  verdict write MISSED "port $P in use; control not run"
else
  (cd "$W" && exec env -i PATH=/usr/bin:/bin HOME="$W" LISTEN_HOST=127.0.0.1 PORT="$P" DB_PATH="$W/control.db" \
     AI_PROVIDER=rule-based EXTRACTOR_PROVIDER=disabled EMBEDDING_PROVIDER=disabled SEMANTIC_SEARCH=disabled "$BIN") > "$W/server.log" 2>&1 &
  SPID=$!
  for _ in $(seq 100); do curl -fsS --max-time 1 "http://127.0.0.1:$P/readyz" > /dev/null 2>&1 && break; sleep 0.1; done
  bash "$HERE/write_probe.sh" "http://127.0.0.1:$P" "$W/writes.txt" > /dev/null 2>&1
  rc=$?
  kill "$SPID" 2> /dev/null; wait "$SPID" 2> /dev/null
  entries=$(python3 -I -c 'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("select count(*) from learning_entries where original_input = ?", ("Synthetic write probe.",)).fetchone()[0])' "$W/control.db" 2>/dev/null || echo 0)
  accepted=$(count "^FAIL write not refused" "$W/writes.txt")
  if [ "$rc" = 1 ] && [ "$accepted" -gt 0 ] && [ "$entries" -gt 0 ]; then
    verdict write DETECTED "probe exit 1; $accepted writes not refused, e.g. $(grep -m1 'not refused: POST' "$W/writes.txt" | sed 's/^FAIL write not refused: //'); $entries probe entries in the throwaway database"
  else
    verdict write MISSED "probe exit $rc, $accepted accepted, $entries entries"
  fi
fi

# link: a build without the malformed-link handling must fail the browser stage, and only it.
if [ -z "$CONTROL_PKG" ] || [ -z "${CHROME:-}" ] || [ -z "$NODE_MODULES" ]; then
  verdict link "NOT RUN" "needs --control-package, CHROME and --node-modules"
else
  bash "$HERE/check_package.sh" "$CONTROL_PKG" "$WORK/link" --port "$((PORT + 3))" --node-modules "$NODE_MODULES" > "$WORK/link.out" 2>&1
  rc=$?
  stages=$(python3 -I -c 'import json,sys; s=json.load(open(sys.argv[1]))["stages"]; print(" ".join(s[k] for k in ("identity","boundary","live","writes","browser")))' "$WORK/link/summary.json" 2>/dev/null)
  named=$(count "FAIL .*links: a malformed link opens the start with a notice" "$WORK/link/browser/accept_matrix.log")
  if [ "$rc" = 1 ] && [ "$stages" = "PASS PASS PASS PASS FAIL" ] && [ "$named" -gt 0 ]; then
    verdict link DETECTED "exit 1; only the browser stage failed; the malformed-link check failed in $named size/language configurations"
  else
    verdict link MISSED "exit $rc, stages [$stages], malformed-link failures $named"
  fi
fi

python3 -I - "$WORK/controls.json" "${RESULT[identity-version]}" "${RESULT[identity-manifest]}" "${RESULT[write]}" "${RESULT[link]}" <<'PY'
import json, sys
out, *r = sys.argv[1:]
json.dump({"schema": "demo_candidate_negative_controls_v1", "controls": dict(zip(["identity-version", "identity-manifest", "write", "link"], r))}, open(out, "w"), indent=1)
PY
if [ "$MISSED" = 1 ]; then note "NEGATIVE CONTROLS: A FAILURE WAS MISSED"; exit 1; fi
note "NEGATIVE CONTROLS PASSED (every control that ran was detected)"
exit 0
