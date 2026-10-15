#!/usr/bin/env bash
# FLH-077 Linux acceptance of the FLH-076 public-demo package.
#
#   bash scripts/validation/flh077/accept.sh "/abs/new/work dir" [port-base]
#
# Run from the repository root ON THE LINUX HOST. It packages the integrated
# source with the existing tooling (mechanical artifact, so the package is
# ...-BLOCKED), unpacks the tarball into a directory whose path contains spaces,
# and exercises the PACKAGED native binary through the package's own
# deploy/ctl.sh. Loopback ports only; installs, enables and reloads nothing.
# Results: WORK/results.tsv (PASS/FAIL/BLOCKED per check) and WORK/summary.txt.
# Exit 0 only if no check FAILED (BLOCKED checks are reported, not hidden).
#
# FLH077_HOST_SUBSTITUTE=1 allows a non-Linux dry run of the harness logic with
# host builds; such a run is labelled and is NOT Linux package evidence.
set -uo pipefail
WORK=${1:?usage: accept.sh "/abs/new/work dir" [port-base]}
PB=${2:-19770}
REVISION=${FLH077_REVISION:-1dc491141de7ae2aab5d5b2c941b8f37cd38d408}
REPO=$(pwd)
[ -f "$REPO/scripts/demo/flh076/package.sh" ] || { echo "run from the repository root (FLH-076 tooling missing)" >&2; exit 2; }
case "$WORK" in /*) ;; *) echo "WORK must be absolute" >&2; exit 2 ;; esac
case "$WORK/" in "$REPO"/*) echo "WORK must be outside the repository" >&2; exit 2 ;; esac
[ ! -e "$WORK" ] || { echo "refused: $WORK exists" >&2; exit 2; }
mkdir -p "$WORK"
RES="$WORK/results.tsv"; : > "$RES"
rec() { printf '%s\t%s\t%s\n' "$1" "$2" "${3:-}" | tee -a "$RES"; }   # status name detail
pass() { rec PASS "$1" "${2:-}"; }
fail() { rec FAIL "$1" "${2:-}"; }
blocked() { rec BLOCKED "$1" "${2:-}"; }
expect_eq() { if [ "$2" = "$3" ]; then pass "$1" "$2"; else fail "$1" "got [$2] want [$3]"; fi; }
SUB=0
if [ "$(uname -s)" != Linux ]; then
  [ "${FLH077_HOST_SUBSTITUTE:-}" = 1 ] || { echo "not Linux: this is Linux acceptance (FLH077_HOST_SUBSTITUTE=1 for a labelled dry run)" >&2; exit 2; }
  SUB=1; rec NOTE "host-substitute dry run" "$(uname -sm): NOT Linux package evidence"
fi
# bounded SECS cmd...: runs cmd in its own session and kills the whole session
# after SECS (exit 124), so a hanging controller is a reported FAIL, not a stall.
bounded() {
  python3 - "$@" <<'PY'
import os, signal, subprocess, sys
secs, cmd = float(sys.argv[1]), sys.argv[2:]
p = subprocess.Popen(cmd, start_new_session=True)
try:
    sys.exit(p.wait(timeout=secs))
except subprocess.TimeoutExpired:
    os.killpg(p.pid, signal.SIGKILL)
    p.wait()
    sys.exit(124)
PY
}
sha() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }
treehash() { (cd "$1" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 cat | sha | cut -d' ' -f1); }

# 0. Prerequisites (reported, never installed).
for tool in go python3 curl tar; do command -v $tool >/dev/null && pass "prerequisite $tool" "$(command -v $tool)" || { blocked "prerequisite $tool" "missing"; }; done
[ -x "$REPO/web/node_modules/.bin/vite" ] && pass "prerequisite web/node_modules (vite)" || blocked "prerequisite web/node_modules (vite)" "run npm ci in web/ first"
if grep -q BLOCKED "$RES"; then echo "BLOCKED prerequisites; stopping" >&2; exit 4; fi

# 1. Build and package from the integrated source.
mkdir -p "$WORK/build"
(go build -o "$WORK/build/prepare" ./scripts/demo/flh073/prepare) || { fail "build prepare"; exit 1; }
"$WORK/build/prepare" build -out "$WORK/build/artifact" -fixtures scripts/demo/flh073/fixtures/catalog.json > "$WORK/build/artifact.json" 2>&1 \
  && pass "mechanical artifact built" || { fail "mechanical artifact built"; exit 1; }
bash scripts/demo/flh076/package.sh --artifact "$WORK/build/artifact" --revision "$REVISION" --label flh077 --out "$WORK/packages" > "$WORK/package.log" 2>&1
expect_eq "package.sh exit (mechanical => BLOCKED package)" "$?" 0
TARBALL="$WORK/packages/flh-public-demo-flh077-BLOCKED.tar.gz"
[ -f "$TARBALL" ] && pass "BLOCKED tarball produced" "$(basename "$TARBALL")" || { fail "BLOCKED tarball produced"; exit 1; }
(cd "$WORK/packages" && sha -c "$(basename "$TARBALL").sha256" >/dev/null 2>&1) && pass "tarball checksum" || fail "tarball checksum"

# 2. Unpack into a path with spaces; verify layout, checksums, architecture.
INST="$WORK/install root with spaces"
mkdir -p "$INST" && tar -xzf "$TARBALL" -C "$INST"
PKG="$INST/flh-public-demo-flh077-BLOCKED"
expect_eq "top-level layout" "$(cd "$PKG" && ls -A | LC_ALL=C sort | tr '\n' ' ')" "README.md RELEASE.json SHA256SUMS artifact bin deploy validate-release.sh web "
expect_eq "no symlinks" "$(find "$PKG" -type l | wc -l | tr -d ' ')" 0
(cd "$PKG" && sha -c SHA256SUMS >/dev/null 2>&1) && pass "SHA256SUMS verifies" || fail "SHA256SUMS verifies"
expect_eq "RELEASE.json source_revision" "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["source_revision"])' "$PKG/RELEASE.json")" "$REVISION"
expect_eq "RELEASE.json release_status" "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["release_status"])' "$PKG/RELEASE.json")" BLOCKED
case "$(uname -m)" in x86_64|amd64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) ARCH=unknown ;; esac
SERVER="$PKG/bin/linux-$ARCH/flh-server"; PREPARE="$PKG/bin/linux-$ARCH/flh-prepare"
elfarch() { python3 - "$1" <<'PY'
import struct, sys
b = open(sys.argv[1], "rb").read(20)
if b[:4] != b"\x7fELF": print("not-ELF"); sys.exit()
m = struct.unpack("<H", b[18:20])[0]
print({62: "x86_64", 183: "aarch64"}.get(m, "machine-%d" % m))
PY
}
for a in amd64 arm64; do
  want=$([ $a = amd64 ] && echo x86_64 || echo aarch64)
  expect_eq "bin/linux-$a ELF machine" "$(elfarch "$PKG/bin/linux-$a/flh-server")" "$want"
done
if [ $SUB = 1 ]; then
  mkdir -p "$WORK/host"; go build -o "$WORK/host/flh-server" ./cmd/server && go build -o "$WORK/host/flh-prepare" ./scripts/demo/flh073/prepare
  SERVER="$WORK/host/flh-server"; PREPARE="$WORK/host/flh-prepare"; export SERVER_BIN="$SERVER" PREPARE
  rec NOTE "binaries" "host builds substituted (dry run)"
else
  expect_eq "host machine matches a packaged binary" "$(elfarch "$SERVER")" "$(uname -m | sed 's/arm64/aarch64/;s/amd64/x86_64/')"
  "$SERVER" -h >/dev/null 2>&1; rc=$?; [ $rc = 0 ] || [ $rc = 2 ] && pass "packaged native flh-server executes" "exit $rc" || fail "packaged native flh-server executes" "exit $rc"
fi
PKGHASH0=$(treehash "$PKG")

# 3. Release validation and controller lifecycle.
set +e; (cd "$WORK" && PREPARE="$PREPARE" "$PKG/validate-release.sh") > "$WORK/validate.out" 2>&1; rc=$?; set -e; set +e
expect_eq "validate-release.sh on BLOCKED package (mechanical refusal)" "$rc" 3
RUN="$WORK/runtime with spaces"
CTL="$PKG/deploy/ctl.sh"
P1=$((PB + 1))
ctl() { bounded 60 env PORT="$P1" ${ALLOW:+ALLOW_MECHANICAL=1} ${SERVER_BIN:+SERVER_BIN="$SERVER_BIN"} "$CTL" "$@"; }
ALLOW= ; ctl start "$RUN" > "$WORK/start-no-flag.out" 2>&1; rc=$?
expect_eq "start BLOCKED package without ALLOW_MECHANICAL refused" "$rc" 1
grep -q "mechanical test fixtures" "$RUN/flh-public-demo.log" && pass "refusal reason logged (mechanical)" || fail "refusal reason logged (mechanical)"
ALLOW=1
ctl start "$RUN" > "$WORK/start1.out" 2>&1; expect_eq "start" "$?" 0
PID1=$(cat "$RUN/flh-public-demo.pid")
case "$(ps -p "$PID1" -o args=)" in "$SERVER "*) pass "server process is the packaged binary" "$SERVER" ;; *) fail "server process is the packaged binary" "$(ps -p "$PID1" -o args=)" ;; esac
ctl start "$RUN" > "$WORK/start2.out" 2>&1; expect_eq "repeated start is idempotent" "$?:$(cat "$RUN/flh-public-demo.pid")" "0:$PID1"
ctl status "$RUN" > "$WORK/status1.out" 2>&1; expect_eq "status running" "$?" 0
grep -q "mechanical-test real_model=False blocked_mechanical_vectors" "$WORK/status1.out" && pass "status shows artifact identity" || fail "status shows artifact identity" "$(cat "$WORK/status1.out")"

# 4. HTTP behaviour against the packaged binary.
B="http://127.0.0.1:$P1"
code() { curl -s -o /dev/null -w '%{http_code}' -X "$1" "$B$2"; }
hc() { expect_eq "$1 $2" "$(code "$1" "$2")" "$3"; }
INDEX_SHA=$(curl -fsS "$B/" | sha | cut -d' ' -f1); expect_eq "static index bytes" "$INDEX_SHA" "$(sha "$PKG/web/index.html" | cut -d' ' -f1)"
ASSET=$(curl -fsS "$B/" | grep -o '/assets/[^"]*\.js' | head -1)
expect_eq "static JS bytes" "$(curl -fsS "$B$ASSET" | sha | cut -d' ' -f1)" "$(sha "$PKG/web$ASSET" | cut -d' ' -f1)"
for p in /healthz /readyz /api/knowledge-library/demo "/api/knowledge-library/concepts?q=subj" /api/knowledge-library/concepts/1 /api/knowledge-library/units/1/source; do hc GET "$p" 200; done
for p in /favicon.ico /artifact/demo.db /RELEASE.json /assets/ /api/entries /concepts /retrieval-comparison/v1 "/knowledge-library/semantic-search?q=x" "/knowledge-library/hybrid-search?q=x"; do hc GET "$p" 404; done
for m in POST PUT PATCH DELETE; do hc "$m" /api/knowledge-library/concepts 405; hc "$m" /entries 405; done
hc GET "/api/knowledge-library/demo/hybrid-search?q=free+text" 400
hc GET "/api/knowledge-library/demo/semantic-search?preset=unknown" 404
SRC=$(curl -fsS "$B/api/knowledge-library/units/1/source")
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["entry"]["original_input"].endswith("?"); assert d["extraction"]["extractor"].startswith("fixture:flh073")' "$SRC" \
  && pass "provenance: original question and fixture extractor" || fail "provenance"
results() { for q in "concepts?q=subjunctive" "demo/semantic-search?preset=no-longer" "demo/hybrid-search?preset=subjunctive&state=active" "demo/hybrid-search?preset=miss-someone"; do curl -fsS "$B/api/knowledge-library/$q"; echo; done; }
results > "$WORK/results-run1.json"
python3 - "$WORK/results-run1.json" <<'PY' && pass "keyword/semantic/hybrid responses well-formed" || fail "keyword/semantic/hybrid responses well-formed"
import json, sys
lines = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
assert lines[0]["schema_version"] == "knowledge_library_search_v1" and lines[0]["results"]
assert lines[1]["query"] == "no longer doing something" and lines[1]["results"]
assert lines[2]["policy"]["version"] == "concept_hybrid_rrf_v1" and lines[2]["state"] == "active"
assert lines[3]["query"] == "how to tell a friend I miss them"
PY
ID1=$(curl -fsS "$B/api/knowledge-library/demo" | python3 -c 'import json,sys;d=json.load(sys.stdin);a=d["artifact"];print(a["version"],a["manifest_sha256"],d["counters"]["refused_vector_lookups"])')

# Unrelated process and occupied port.
# Long-lived (1 h) so they cannot expire during the run; killed explicitly at the end.
sleep 3600 & UNREL=$!
# A non-HTTP occupant: accepts connections and never answers.
python3 -c 'import socket,time,sys; s=socket.socket(); s.bind(("127.0.0.1",int(sys.argv[1]))); s.listen(); time.sleep(3600)' $((PB + 2)) & BUSY=$!
sleep 0.5
RUN2="$WORK/runtime occupied"
bounded 30 env PORT=$((PB + 2)) ALLOW_MECHANICAL=1 ${SERVER_BIN:+SERVER_BIN="$SERVER_BIN"} "$CTL" start "$RUN2" > "$WORK/start-occupied.out" 2>&1; rc=$?
if [ "$rc" = 124 ]; then fail "start on an occupied port fails promptly" "ctl.sh start hung >30 s polling a non-HTTP occupant (readiness curl has no timeout)"
else expect_eq "start on an occupied port fails promptly" "$rc" 1; fi
grep -q "address already in use" "$RUN2/flh-public-demo.log" && pass "server refused the occupied port (bind error logged)" || fail "server refused the occupied port"
kill -0 $BUSY 2>/dev/null && pass "occupying listener untouched" || fail "occupying listener untouched"
# Stale pid file naming an unrelated live process: stop and status must not touch it.
RUN3="$WORK/runtime stale"; mkdir -p "$RUN3"; echo $UNREL > "$RUN3/flh-public-demo.pid"
bounded 30 env PORT=$((PB + 3)) "$CTL" status "$RUN3" > "$WORK/status-stale.out" 2>&1; expect_eq "status with a pid file naming an unrelated process" "$?" 3
bounded 30 env PORT=$((PB + 3)) "$CTL" stop "$RUN3" > "$WORK/stop-stale.out" 2>&1; expect_eq "stop with a pid file naming an unrelated process" "$?" 0
kill -0 $UNREL 2>/dev/null && pass "unrelated process not signalled" || fail "unrelated process not signalled"
# Stale pid file naming a dead process.
RUN4="$WORK/runtime dead"; mkdir -p "$RUN4"; (sleep 0 & echo $! > "$RUN4/flh-public-demo.pid"; wait)
bounded 30 env PORT=$((PB + 4)) "$CTL" status "$RUN4" >/dev/null 2>&1; expect_eq "status with a dead pid" "$?" 3
# Startup failure: corrupted artifact copy (in a separate package copy).
BAD="$WORK/bad package"; cp -R "$PKG" "$BAD"; chmod -R u+w "$BAD"; printf x >> "$BAD/artifact/vectors.json"
bounded 60 env PORT=$((PB + 5)) ALLOW_MECHANICAL=1 ${SERVER_BIN:+SERVER_BIN="$SERVER_BIN"} "$BAD/deploy/ctl.sh" start "$WORK/runtime bad" > "$WORK/start-bad.out" 2>&1; rc=$?
expect_eq "start with a corrupted artifact fails" "$rc" 1
grep -q "artifact rejected" "$WORK/runtime bad/flh-public-demo.log" && pass "corruption reason logged" || fail "corruption reason logged"

# Stop, repeated stop, restart, identical results.
ctl stop "$RUN" > "$WORK/stop1.out" 2>&1; expect_eq "stop" "$?" 0
kill -0 "$PID1" 2>/dev/null && fail "server exited after stop" || pass "server exited after stop"
ctl stop "$RUN" > "$WORK/stop2.out" 2>&1; expect_eq "repeated stop is idempotent" "$?" 0
ctl status "$RUN" > /dev/null 2>&1; expect_eq "status after stop" "$?" 3
ctl start "$RUN" > "$WORK/start3.out" 2>&1; expect_eq "restart" "$?" 0
results > "$WORK/results-run2.json"
expect_eq "identical results after restart" "$(sha "$WORK/results-run2.json" | cut -d' ' -f1)" "$(sha "$WORK/results-run1.json" | cut -d' ' -f1)"
ID2=$(curl -fsS "$B/api/knowledge-library/demo" | python3 -c 'import json,sys;d=json.load(sys.stdin);a=d["artifact"];print(a["version"],a["manifest_sha256"],d["counters"]["refused_vector_lookups"])')
expect_eq "artifact identity persists across restart" "$ID2" "$ID1"
ctl stop "$RUN" > /dev/null 2>&1; expect_eq "final stop" "$?" 0
kill -0 $UNREL 2>/dev/null && pass "unrelated process still alive at end" || fail "unrelated process still alive at end"
kill -0 $BUSY 2>/dev/null && pass "occupying listener still alive at end" || fail "occupying listener still alive at end"
kill $UNREL $BUSY 2>/dev/null; wait $UNREL $BUSY 2>/dev/null
expect_eq "package bytes unchanged by every run" "$(treehash "$PKG")" "$PKGHASH0"

# 5. Tampering refusals (copies).
for t in edit symlink extra relabel; do
  T="$WORK/tamper $t"; cp -R "$PKG" "$T"; chmod -R u+w "$T"
  case $t in edit) printf x >> "$T/web/index.html" ;; symlink) ln -s /etc/hostname "$T/web/assets/x" ;; extra) echo x > "$T/extra.txt" ;;
    relabel) python3 -c 'import json,sys;p=sys.argv[1];d=json.load(open(p));d["release_status"]="CANDIDATE";json.dump(d,open(p,"w"))' "$T/RELEASE.json" ;; esac
  (cd "$WORK" && PREPARE="$PREPARE" "$T/validate-release.sh") > "$WORK/tamper-$t.out" 2>&1; expect_eq "tamper $t refused" "$?" 1
done

# 6. Template syntax (installed tools only; nothing installed, enabled or reloaded).
TPL="$WORK/templates"; mkdir -p "$TPL"
if command -v systemd-analyze >/dev/null; then
  # The unit is verified as written, with only its site paths and user substituted. Unit files
  # split ExecStart on spaces, so the test copy uses a space-free task-local directory.
  UNITDIR=$(mktemp -d /tmp/flh077-unit-XXXXXX); cp "$SERVER" "$UNITDIR/flh-server"
  sed -e "s|/srv/flh-demo/current/bin/linux-amd64/flh-server|$UNITDIR/flh-server|" -e "s|/srv/flh-demo/current|$UNITDIR|g" -e "s|/srv/flh-demo|$UNITDIR|g" \
      -e "s|^User=.*|User=$(id -un)|" -e "s|^Group=.*|Group=$(id -gn)|" \
    "$PKG/deploy/flh-public-demo.service.example" > "$UNITDIR/flh-public-demo-test.service"
  cp "$UNITDIR/flh-public-demo-test.service" "$TPL/"
  systemd-analyze verify "$UNITDIR/flh-public-demo-test.service" > "$TPL/systemd-verify.out" 2>&1; rc=$?
  if [ $rc = 0 ] && ! grep -qiE "unknown|invalid|failed|ignoring" "$TPL/systemd-verify.out"; then pass "systemd-analyze verify (unit template)"
  else fail "systemd-analyze verify (unit template)" "exit $rc: $(head -c 300 "$TPL/systemd-verify.out" | tr '\n' ' ')"; fi
else blocked "systemd-analyze verify" "systemd-analyze not installed"; fi
if command -v nginx >/dev/null; then
  if command -v openssl >/dev/null; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=demo.example.org -keyout "$TPL/key.pem" -out "$TPL/cert.pem" >/dev/null 2>&1
    sed -e "s|/etc/ssl/demo.example.org/fullchain.pem|\"$TPL/cert.pem\"|" -e "s|/etc/ssl/demo.example.org/privkey.pem|\"$TPL/key.pem\"|" -e "s|listen 443 ssl|listen 127.0.0.1:$((PB + 8)) ssl|" -e "s|listen 80;|listen 127.0.0.1:$((PB + 9));|" \
      "$PKG/deploy/nginx-flh-public-demo.conf.example" > "$TPL/site.conf"
    printf 'pid "%s/nginx.pid";\nerror_log "%s/error.log";\nevents {}\nhttp {\n  access_log off;\n  include "%s/site.conf";\n}\n' "$TPL" "$TPL" "$TPL" > "$TPL/nginx.conf"
    nginx -t -p "$TPL" -c "$TPL/nginx.conf" > "$TPL/nginx-t.out" 2>&1 && pass "nginx -t (server block in a task-local main config)" || fail "nginx -t" "$(tail -c 400 "$TPL/nginx-t.out" | tr '\n' ' ')"
  else blocked "nginx -t" "openssl missing for a test certificate"; fi
else blocked "nginx -t" "nginx not installed (not installed by this harness)"; fi
sh -n "$PKG/deploy/ctl.sh" && pass "ctl.sh shell syntax" || fail "ctl.sh shell syntax"

# Listener cleanup.
for p in $((PB + 1)) $((PB + 2)) $((PB + 5)); do
  (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null && fail "loopback port $p closed at end" || pass "loopback port $p closed at end"
done
{ echo "PASS $(grep -c '^PASS' "$RES")"; echo "FAIL $(grep -c '^FAIL' "$RES")"; echo "BLOCKED $(grep -c '^BLOCKED' "$RES")"; } | tee "$WORK/summary.txt"
grep -q '^FAIL' "$RES" && exit 1 || exit 0
