#!/usr/bin/env bash
# FLH-078: real-browser checks of a release package served OFFLINE on Linux.
#
#   bash scripts/validation/flh078/browser_offline.sh /abs/new/local/work SSH_TARGET /abs/remote/package /abs/new/remote/run \
#        EXPECTED_DEPLOYMENT EXPECTED_ARTIFACT_VERSION [server-port] [bridge-port] [local-port] [encoder-readyz-url]
#
# Run from the repository root on the machine with Chrome (macOS here). On the
# Linux host it starts the PACKAGED server with the package's deploy/ctl.sh
# inside `unshare -rn` (loopback only: no route to the encoder or anywhere
# else; offline_serve.sh records the proof), bridges that loopback port out
# through a Unix socket to a loopback port on the host (netns_bridge.py), and
# forwards it here with `ssh -N -L` (loopback on both ends). It then runs the
# existing FLH-076 accept.mjs (--expect-vectors model) and candidate_browser.mjs
# with the installed Chrome, and finally stops everything it started. The
# encoder probe in offline_serve.sh runs inside the namespace, where it has no
# route: it proves unreachability and sends nothing off the host.
# Evidence: WORK/accept/, WORK/candidate/ (results.json, screenshots), WORK/remote/.
set -euo pipefail
WORK=${1:?usage}; SSH=${2:?usage}; PKG=${3:?usage}; RRUN=${4:?usage}; MODEL=${5:?usage}; ART=${6:?usage}
SPORT=${7:-19981}; BPORT=${8:-19982}; LPORT=${9:-19983}; ENC=${10:-http://100.118.109.6:8765/readyz}
REPO=$(pwd)
CHROME=${CHROME:-"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"}
[ -f "$REPO/scripts/validation/flh078/offline_serve.sh" ] || { echo "run from the repository root" >&2; exit 2; }
case "$WORK" in /*) ;; *) echo "WORK must be absolute" >&2; exit 2 ;; esac
[ ! -e "$WORK" ] || { echo "refused: $WORK exists" >&2; exit 2; }
[ -x "$CHROME" ] || { echo "NOT RUN: no Chrome at $CHROME" >&2; exit 4; }
if (exec 3<>"/dev/tcp/127.0.0.1/$LPORT") 2>/dev/null; then echo "refused: local port $LPORT in use" >&2; exit 2; fi
mkdir -p "$WORK/tools" "$WORK/remote"
r() { ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH" "$@"; }
RT=$RRUN.tools SOCK=$RRUN.sock
r "[ ! -e '$RRUN' ] && [ ! -e '$RT' ] && [ ! -e '$SOCK' ] && mkdir '$RT'"
scp -q -o BatchMode=yes scripts/validation/flh078/offline_serve.sh scripts/validation/flh078/netns_bridge.py "$SSH:$RT/"
(cd "$WORK/tools" && npm init -y > /dev/null && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --no-audit --no-fund playwright-core@1.49.1 > install.log 2>&1)

TUN=
teardown() {
  set +e
  [ -z "$TUN" ] || kill "$TUN" 2>/dev/null
  r "for f in '$RT/outer.pid' '$RRUN/offline_serve.pid'; do [ -f \"\$f\" ] || continue; p=\$(cat \"\$f\"); \
     if ps -p \"\$p\" -o command= | grep -q -e 'netns_bridge.py outer $BPORT' -e 'offline_serve.sh $PKG'; then kill \"\$p\"; \
       for i in \$(seq 1 100); do kill -0 \"\$p\" 2>/dev/null || break; sleep 0.2; done; fi; done; \
     [ -e '$RRUN/flh-public-demo.pid' ] && echo 'server pid file still present' || echo 'server stopped (pid file removed)'; ss -ltn | grep -E ':($SPORT|$BPORT) ' || echo 'remote ports $SPORT/$BPORT closed'" \
    > "$WORK/remote/teardown.txt" 2>&1
  set -e
}
trap teardown EXIT
r "(cd '$RT' && exec nohup unshare -rn sh offline_serve.sh '$PKG' '$RRUN' $SPORT '$SOCK' '$ENC') > '$RT/serve.log' 2>&1 < /dev/null & \
   for i in \$(seq 1 100); do [ -f '$RRUN/ready' ] && break; sleep 0.3; done; [ -f '$RRUN/ready' ] || { cat '$RT/serve.log' '$RRUN/ctl.txt' 2>/dev/null; exit 1; }; \
   (exec nohup python3 '$RT/netns_bridge.py' outer $BPORT '$SOCK') > '$RT/outer.log' 2>&1 < /dev/null & echo \$! > '$RT/outer.pid'"
ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -N -L "127.0.0.1:$LPORT:127.0.0.1:$BPORT" "$SSH" &
TUN=$!
for _ in $(seq 1 50); do curl -fsS --max-time 2 "http://127.0.0.1:$LPORT/readyz" > /dev/null 2>&1 && break; sleep 0.2; done
curl -fsS --max-time 5 "http://127.0.0.1:$LPORT/knowledge-library/demo" > "$WORK/demo-info-before.json"
set +e
PLAYWRIGHT_CORE_DIR="$WORK/tools/node_modules/playwright-core" node "$REPO/scripts/demo/flh076/browser/accept.mjs" \
  --url "http://127.0.0.1:$LPORT" --out "$WORK/accept" --chrome "$CHROME" --expect-vectors model > "$WORK/accept.out" 2>&1
A=$?
PLAYWRIGHT_CORE_DIR="$WORK/tools/node_modules/playwright-core" node "$REPO/scripts/validation/flh078/candidate_browser.mjs" \
  --url "http://127.0.0.1:$LPORT" --out "$WORK/candidate" --chrome "$CHROME" --expect-model "$MODEL" --expect-artifact "$ART" > "$WORK/candidate.out" 2>&1
C=$?
set -e
curl -fsS --max-time 5 "http://127.0.0.1:$LPORT/knowledge-library/demo" > "$WORK/demo-info-after.json"
r "cat '$RRUN/netns.txt'; echo '# ctl start'; cat '$RRUN/ctl.txt'; echo '# server log'; cat '$RRUN/flh-public-demo.log'" > "$WORK/remote/namespace-and-server.txt" 2>&1 || true
teardown; trap - EXIT
echo "accept.mjs exit $A: $(tail -1 "$WORK/accept.out")"
echo "candidate_browser.mjs exit $C: $(tail -1 "$WORK/candidate.out")"
cat "$WORK/remote/teardown.txt"
[ "$A" = 0 ] && [ "$C" = 0 ]
