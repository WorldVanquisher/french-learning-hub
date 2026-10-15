#!/bin/sh
# Manual start/status/stop for the FLH read-only public demo, without systemd.
#
#   deploy/ctl.sh start|status|stop RUNTIME_DIR
#
# Environment: PORT (default 18970), ALLOWED_HOST (public host name, optional
# for loopback-only use), SERVER_BIN (default bin/linux-<arch>/flh-server),
# ALLOW_MECHANICAL=1 (local smoke of a BLOCKED package only).
# RUNTIME_DIR holds the pid file and log; the release directory stays read-only.
# stop signals only the pid it recorded, after checking that pid's command line.
set -eu
CMD=${1:?usage: ctl.sh start|status|stop RUNTIME_DIR}
RUN=${2:?usage: ctl.sh start|status|stop RUNTIME_DIR}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PORT=${PORT:-18970}
case "$(uname -m)" in x86_64|amd64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) ARCH=unknown ;; esac
SERVER_BIN=${SERVER_BIN:-$ROOT/bin/linux-$ARCH/flh-server}
PIDFILE=$RUN/flh-public-demo.pid
mkdir -p "$RUN"
ours() { [ -f "$PIDFILE" ] && pid=$(cat "$PIDFILE") && kill -0 "$pid" 2>/dev/null && ps -p "$pid" -o command= | grep -q -- "-public-demo-artifact $ROOT/artifact"; }
case "$CMD" in
start)
  if ours; then echo "already running (pid $(cat "$PIDFILE"))"; exit 0; fi
  extra=""
  [ "${ALLOW_MECHANICAL:-}" = 1 ] && extra=-public-demo-allow-mechanical
  (cd "$ROOT" && exec env -i PATH=/usr/bin:/bin LISTEN_HOST=127.0.0.1 PORT="$PORT" AI_PROVIDER=rule-based \
     EXTRACTOR_PROVIDER=disabled EMBEDDING_PROVIDER=disabled SEMANTIC_SEARCH=disabled HTTP_ALLOWED_HOSTS="${ALLOWED_HOST:-}" \
     "$SERVER_BIN" -public-demo-artifact "$ROOT/artifact" -web-dir "$ROOT/web" $extra) >> "$RUN/flh-public-demo.log" 2>&1 &
  echo $! > "$PIDFILE"
  i=0; while [ $i -lt 50 ]; do curl -fsS "http://127.0.0.1:$PORT/readyz" >/dev/null 2>&1 && break; sleep 0.2; i=$((i+1)); done
  if ours && curl -fsS "http://127.0.0.1:$PORT/readyz" >/dev/null 2>&1; then echo "started (pid $(cat "$PIDFILE"), 127.0.0.1:$PORT)"; else echo "start failed; see $RUN/flh-public-demo.log" >&2; exit 1; fi ;;
status)
  if ours; then
    echo "running (pid $(cat "$PIDFILE"))"
    curl -fsS "http://127.0.0.1:$PORT/knowledge-library/demo" | python3 -c 'import json,sys; a=json.load(sys.stdin)["artifact"]; print("artifact", a["version"], a["vector_source"], "real_model=%s" % a["real_model"], a["release_status"])'
  else echo "stopped"; exit 3; fi ;;
stop)
  if ours; then kill "$(cat "$PIDFILE")"; i=0; while ours && [ $i -lt 50 ]; do sleep 0.2; i=$((i+1)); done; fi
  if ours; then echo "did not stop" >&2; exit 1; fi
  rm -f "$PIDFILE"; echo "stopped" ;;
*) echo "usage: ctl.sh start|status|stop RUNTIME_DIR" >&2; exit 2 ;;
esac
