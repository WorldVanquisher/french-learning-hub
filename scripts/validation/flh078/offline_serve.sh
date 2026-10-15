#!/bin/sh
# FLH-078: serve a release package from a network namespace with loopback only.
#
#   unshare -rn sh offline_serve.sh /abs/package /abs/new/run-dir PORT /abs/bridge.sock ENCODER_READYZ_URL
#
# Run on Linux through `unshare -rn` (an unprivileged user + network namespace).
# Inside, only `lo` exists, so the server cannot reach the encoder or any other
# host. It records the namespace's interfaces and routes, proves the encoder is
# unreachable, starts the package with its own deploy/ctl.sh on 127.0.0.1:PORT,
# and exposes that port through a Unix socket (netns_bridge.py inner) until it
# receives TERM/INT. It then stops the bridge and the server it started.
set -eu
PKG=$1 RUN=$2 PORT=$3 SOCK=$4 ENC=$5
HERE=$(cd "$(dirname "$0")" && pwd)
[ ! -e "$RUN" ] || { echo "refused: $RUN exists" >&2; exit 2; }
mkdir -p "$RUN"
echo $$ > "$RUN/offline_serve.pid"
ip link set lo up
{ echo "# ip -brief addr"; ip -brief addr; echo "# ip route"; ip route; echo "# ip -6 route"; ip -6 route; } > "$RUN/netns.txt"
set +e
code=$(curl -s --max-time 3 -o /dev/null -w '%{http_code}' "$ENC"); rc=$?
set -e
echo "encoder probe from inside the namespace: http_code=$code curl_exit=$rc" >> "$RUN/netns.txt"
[ "$rc" != 0 ] || { echo "refused: the encoder is reachable from the namespace" >&2; exit 1; }
BR=
cleanup() {
  trap - EXIT TERM INT
  [ -z "$BR" ] || kill "$BR" 2>/dev/null || true
  rm -f "$SOCK"
  PORT=$PORT "$PKG/deploy/ctl.sh" stop "$RUN" >> "$RUN/ctl.txt" 2>&1 || true
}
trap cleanup EXIT
trap 'cleanup; exit 0' TERM INT
PORT=$PORT "$PKG/deploy/ctl.sh" start "$RUN" > "$RUN/ctl.txt" 2>&1
python3 "$HERE/netns_bridge.py" inner "$SOCK" "$PORT" &
BR=$!
echo ready > "$RUN/ready"
wait "$BR"
