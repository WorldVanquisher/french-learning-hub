#!/usr/bin/env bash
# FLH-077 focused regression tests for scripts/demo/flh076/deploy/ctl.sh (D1).
#
#   bash scripts/validation/flh077/ctl_regression.sh "/abs/new/work dir" [port-base]
#
# Builds a BLOCKED package from this source (so it carries the ctl.sh under
# test), then drives deploy/ctl.sh with the real server (SERVER_BIN: the
# packaged linux binary on Linux, a host build elsewhere) and small fake
# servers for timing cases. Every ctl.sh call runs under an outer hard timeout
# in its own session, so a hang is a FAIL, not a stall. Results in
# WORK/results.tsv; exit 0 only if no check FAILED. Loopback only.
set -uo pipefail
WORK=${1:?usage}; PB=${2:-19840}
REPO=$(pwd)
[ -f scripts/demo/flh076/deploy/ctl.sh ] || { echo "run from the repository root" >&2; exit 2; }
[ ! -e "$WORK" ] || { echo "refused: $WORK exists" >&2; exit 2; }
mkdir -p "$WORK"; RES="$WORK/results.tsv"; : > "$RES"
rec() { printf '%s\t%s\t%s\n' "$1" "$2" "${3:-}" | tee -a "$RES"; }
check() { if [ "$2" = "$3" ]; then rec PASS "$1" "$2"; else rec FAIL "$1" "got [$2] want [$3]"; fi; }
alive() { kill -0 "$1" 2>/dev/null && echo alive || echo gone; }
# timed SECS cmd... -> prints "rc seconds"; kills its own session on timeout (rc 124).
timed() {
  python3 - "$@" <<'PY'
import os, signal, subprocess, sys, time
secs, cmd = float(sys.argv[1]), sys.argv[2:]
t = time.time(); p = subprocess.Popen(cmd, start_new_session=True, stdout=sys.stderr)  # keep our stdout for "rc seconds"
try:
    rc = p.wait(timeout=secs)
except subprocess.TimeoutExpired:
    os.killpg(p.pid, signal.SIGKILL); p.wait(); rc = 124
print(rc, int(time.time() - t))
PY
}
go build -o "$WORK/prepare" ./scripts/demo/flh073/prepare && go build -o "$WORK/host-server" ./cmd/server || { rec FAIL build; exit 1; }
"$WORK/prepare" build -out "$WORK/artifact" > /dev/null
bash scripts/demo/flh076/package.sh --artifact "$WORK/artifact" --revision "${FLH077_REVISION:-1dc491141de7ae2aab5d5b2c941b8f37cd38d408}" --label ctltest --out "$WORK/pkgs" > "$WORK/package.log" 2>&1
PKG="$WORK/pkgs/flh-public-demo-ctltest-BLOCKED"; CTL="$PKG/deploy/ctl.sh"
cmp -s "$CTL" scripts/demo/flh076/deploy/ctl.sh && rec PASS "package carries the ctl.sh under test" || { rec FAIL "package carries the ctl.sh under test"; exit 1; }
case "$(uname -m)" in x86_64|amd64) A=amd64 ;; aarch64|arm64) A=arm64 ;; esac
if [ "$(uname -s)" = Linux ]; then REAL="$PKG/bin/linux-$A/flh-server"; else REAL="$WORK/host-server"; rec NOTE "server" "host build (non-Linux)"; fi
# Fake servers (invoked with the same arguments, so ctl.sh's ownership check recognises them).
mkdir -p "$WORK/fakes"
# Keeps the demo arguments in its command line (as a real server does), so ctl.sh may stop it.
printf '#!/bin/sh\nexec python3 -c "import time; time.sleep(3600)" "$@"\n' > "$WORK/fakes/never-ready"
printf '#!/bin/sh\nsleep 2\nexec "%s" "$@"\n' "$REAL" > "$WORK/fakes/slow-ready"
chmod +x "$WORK/fakes/"*
SHA=$( (command -v sha256sum >/dev/null && sha256sum "$PKG/artifact/manifest.json" || shasum -a 256 "$PKG/artifact/manifest.json") | cut -d' ' -f1)
CHILD_PATH=$PATH
NOLSOF_PATH=/usr/bin:/bin   # no /usr/sbin: exercises the log-based ownership fallback where lsof lives in /usr/sbin
run_ctl() { # port path-mode server-bin timeout-secs outer-secs action rundir
  local port=$1 mode=$2 bin=$3 rt=$4 outer=$5 action=$6 run=$7 p=$CHILD_PATH
  [ "$mode" = nolsof ] && p=$NOLSOF_PATH
  timed "$outer" env PATH="$p" PORT="$port" ALLOW_MECHANICAL=1 SERVER_BIN="$bin" READY_TIMEOUT="$rt" "$CTL" "$action" "$run"
}
command -v lsof >/dev/null && rec NOTE "ownership tool" "lsof available" || { command -v ss >/dev/null && rec NOTE "ownership tool" "ss available" || rec NOTE "ownership tool" "none: log fallback only"; }

for mode in tool nolsof; do
  # 1. Non-HTTP occupant (the D1 reproducer): fails promptly, occupant untouched.
  P=$((PB + 1)); [ $mode = nolsof ] && P=$((PB + 11))
  python3 -c 'import socket,time,sys; s=socket.socket(); s.bind(("127.0.0.1",int(sys.argv[1]))); s.listen(); time.sleep(3600)' $P & OCC=$!; sleep 0.5
  read -r rc secs <<<"$(run_ctl $P $mode "$REAL" 30 60 start "$WORK/run occ-raw $mode" 2>"$WORK/occ-raw-$mode.err")"
  check "[$mode] non-HTTP occupant: start fails" "$rc" 1
  [ "$secs" -le 5 ] && rec PASS "[$mode] non-HTTP occupant: fails within 5 s" "${secs}s" || rec FAIL "[$mode] non-HTTP occupant: fails within 5 s" "${secs}s"
  check "[$mode] non-HTTP occupant untouched" "$(alive $OCC)" alive
  check "[$mode] no pid file left" "$(test -e "$WORK/run occ-raw $mode/flh-public-demo.pid" && echo present || echo absent)" absent
  kill $OCC; wait $OCC 2>/dev/null

  # 2. HTTP occupant that even imitates the demo's identity answer.
  P=$((PB + 2)); [ $mode = nolsof ] && P=$((PB + 12))
  python3 - $P "$SHA" <<'PY' & HTTP=$!
import http.server, json, sys
port, sha = int(sys.argv[1]), sys.argv[2]
body = json.dumps({"artifact": {"manifest_sha256": sha}}).encode()
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
PY
  sleep 0.7
  read -r rc secs <<<"$(run_ctl $P $mode "$REAL" 30 60 start "$WORK/run occ-http $mode" 2>"$WORK/occ-http-$mode.err")"
  check "[$mode] imitating HTTP occupant: not reported ready" "$rc" 1
  [ "$secs" -le 5 ] && rec PASS "[$mode] imitating HTTP occupant: fails within 5 s" "${secs}s" || rec FAIL "[$mode] imitating HTTP occupant: fails within 5 s" "${secs}s"
  check "[$mode] HTTP occupant untouched" "$(alive $HTTP)" alive
  kill $HTTP; wait $HTTP 2>/dev/null
done

# 3. Immediate startup failure (corrupted artifact in a package copy).
BAD="$WORK/bad pkg"; cp -R "$PKG" "$BAD"; printf x >> "$BAD/artifact/vectors.json"
read -r rc secs <<<"$(timed 60 env PORT=$((PB + 3)) ALLOW_MECHANICAL=1 SERVER_BIN="$REAL" "$BAD/deploy/ctl.sh" start "$WORK/run bad" 2>"$WORK/bad.err")"
check "immediate startup failure: start fails" "$rc" 1
[ "$secs" -le 3 ] && rec PASS "immediate startup failure: within 3 s" "${secs}s" || rec FAIL "immediate startup failure: within 3 s" "${secs}s"
grep -q "exited during startup" "$WORK/bad.err" && rec PASS "immediate failure message" || rec FAIL "immediate failure message" "$(cat "$WORK/bad.err")"

# 4. Successful start, repeated start, status, stop (both ownership paths).
for mode in tool nolsof; do
  P=$((PB + 4)); [ $mode = nolsof ] && P=$((PB + 14)); R="$WORK/run ok $mode"
  read -r rc secs <<<"$(run_ctl $P $mode "$REAL" 30 60 start "$R")"; check "[$mode] start succeeds" "$rc" 0
  PID=$(cat "$R/flh-public-demo.pid")
  read -r rc secs <<<"$(run_ctl $P $mode "$REAL" 30 60 start "$R")"; check "[$mode] repeated start keeps the same pid" "$rc:$(cat "$R/flh-public-demo.pid")" "0:$PID"
  read -r rc secs <<<"$(run_ctl $P $mode "$REAL" 30 60 status "$R")"; check "[$mode] status running" "$rc" 0
  read -r rc secs <<<"$(run_ctl $P $mode "$REAL" 30 60 stop "$R")"; check "[$mode] stop" "$rc:$(alive $PID)" "0:gone"
done

# 5. Slow readiness: ready after ~2 s within the timeout.
R="$WORK/run slow"
read -r rc secs <<<"$(run_ctl $((PB + 5)) tool "$WORK/fakes/slow-ready" 15 60 start "$R")"
check "slow readiness within the timeout succeeds" "$rc" 0
[ "$secs" -ge 2 ] && rec PASS "slow readiness waited for the server" "${secs}s" || rec FAIL "slow readiness waited for the server" "${secs}s"
run_ctl $((PB + 5)) tool "$WORK/fakes/slow-ready" 15 60 stop "$R" > /dev/null

# 6. Never ready: bounded total wait, only the launched process is stopped.
sleep 3600 & UNREL=$!
R="$WORK/run never"
read -r rc secs <<<"$(run_ctl $((PB + 6)) tool "$WORK/fakes/never-ready" 3 60 start "$R" 2>"$WORK/never.err")"
check "never ready: start fails" "$rc" 1
[ "$secs" -ge 3 ] && [ "$secs" -le 8 ] && rec PASS "never ready: bounded by READY_TIMEOUT=3" "${secs}s" || rec FAIL "never ready: bounded by READY_TIMEOUT=3" "${secs}s"
grep -q "not ready within 3s; stopped the launched process only" "$WORK/never.err" && rec PASS "timeout message" || rec FAIL "timeout message" "$(cat "$WORK/never.err")"
LEFT=$(ps -axo pid=,command= | grep -F -- "$WORK/fakes/never-ready" | grep -v grep | wc -l | tr -d ' ')
check "never ready: launched process stopped" "$LEFT" 0
check "never ready: unrelated process untouched" "$(alive $UNREL)" alive
check "never ready: pid file removed" "$(test -e "$R/flh-public-demo.pid" && echo present || echo absent)" absent
kill $UNREL; wait $UNREL 2>/dev/null

# 7. Invalid READY_TIMEOUT refused before launching anything.
read -r rc secs <<<"$(timed 30 env PORT=$((PB + 7)) READY_TIMEOUT=abc SERVER_BIN="$REAL" "$CTL" start "$WORK/run bad timeout" 2>/dev/null)"
check "invalid READY_TIMEOUT refused" "$rc" 2

for p in 1 2 4 5 6 11 12 14; do (exec 3<>"/dev/tcp/127.0.0.1/$((PB + p))") 2>/dev/null && rec FAIL "port $((PB + p)) closed" || true; done
{ echo "PASS $(grep -c '^PASS' "$RES")"; echo "FAIL $(grep -c '^FAIL' "$RES")"; } | tee "$WORK/summary.txt"
grep -q '^FAIL' "$RES" && exit 1 || exit 0
