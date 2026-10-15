#!/bin/sh
# Manual start/status/stop for the FLH read-only public demo, without systemd.
#
#   deploy/ctl.sh start|status|stop RUNTIME_DIR
#
# Environment: PORT (default 18970), ALLOWED_HOST (public host name, optional
# for loopback-only use), SERVER_BIN (default bin/linux-<arch>/flh-server),
# ALLOW_MECHANICAL=1 (local smoke of a BLOCKED package only), READY_TIMEOUT
# (seconds to wait for readiness, default 30).
# RUNTIME_DIR holds the pid file and log; the release directory stays read-only.
#
# start reports ready only when the process it launched is alive, owns the
# listening socket (lsof/ss when available, else its own startup log), and the
# answer on the port carries this package's artifact manifest SHA-256. Every
# readiness request is bounded (2 s) and so is the total wait. It stops waiting
# as soon as the launched process exits, and on timeout it stops only that
# process. stop signals only the pid it recorded, after checking that pid's
# command line. Nothing here ever signals a process occupying the port.
#
# start prepares its pid bookkeeping before launching: the pid path must be a
# regular file or absent and a temporary file next to it must be writable, or
# nothing is launched. After launching, the pid is written to that temporary
# file, renamed into place and read back. If that fails, or start exits early
# for any other reason (an error, or SIGHUP/SIGINT/SIGTERM), the launched
# process is stopped before start exits. It is identified as this shell's own
# unreaped child, so its pid cannot have been reused. Only SIGKILL of ctl.sh in
# the moment between launch and the pid rename can leave it untracked.
set -eu
CMD=${1:?usage: ctl.sh start|status|stop RUNTIME_DIR}
RUN=${2:?usage: ctl.sh start|status|stop RUNTIME_DIR}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PORT=${PORT:-18970}
READY_TIMEOUT=${READY_TIMEOUT:-30}
case "$(uname -m)" in x86_64|amd64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) ARCH=unknown ;; esac
SERVER_BIN=${SERVER_BIN:-$ROOT/bin/linux-$ARCH/flh-server}
PIDFILE=$RUN/flh-public-demo.pid
LOG=$RUN/flh-public-demo.log
mkdir -p "$RUN"
is_ours() { kill -0 "$1" 2>/dev/null && ps -p "$1" -o command= | grep -q -- "-public-demo-artifact $ROOT/artifact"; }
ours() { [ -f "$PIDFILE" ] && pid=$(cat "$PIDFILE") && is_ours "$pid"; }
sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
# Prints the pids listening on PORT, or returns 1 when no tool can tell.
listener_pids() {
  if command -v lsof >/dev/null 2>&1; then lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true; return 0; fi
  if command -v ss >/dev/null 2>&1; then ss -ltnpH "sport = :$PORT" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 || true; return 0; fi
  return 1
}
# The answer on PORT names this package's artifact (bounded request).
answers_as_us() {
  body=$(curl -fsS --max-time 2 "http://127.0.0.1:$PORT/knowledge-library/demo" 2>/dev/null) || return 1
  printf '%s' "$body" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin)["artifact"]["manifest_sha256"] == sys.argv[1] else 1)' "$EXPECTED" 2>/dev/null
}
# The launched process owns the listener (or, without lsof/ss, logged its own listen line and no error since launch).
owns_listener() {
  if pids=$(listener_pids); then
    printf '%s\n' $pids | grep -qx "$1"
    return
  fi
  new=$(tail -c +"$((OFFSET + 1))" "$LOG" 2>/dev/null || true)
  printf '%s' "$new" | grep -q "listening on 127.0.0.1:$PORT " || return 1
  sleep 0.5
  new=$(tail -c +"$((OFFSET + 1))" "$LOG" 2>/dev/null || true)
  ! printf '%s' "$new" | grep -q "server error" && kill -0 "$1" 2>/dev/null
}
# The launched process is still this shell's own child (not yet reaped, not a zombie).
live_child() { ps -o ppid= -o stat= -p "$1" 2>/dev/null | awk -v me="$$" '$1 == me && $2 !~ /^Z/ { ok = 1 } END { exit !ok }'; }
# Stops this shell's own launched child, before or after its exec; true once it is gone.
stop_child() {
  live_child "$1" || return 0
  kill "$1" 2>/dev/null || true
  i=0; while live_child "$1" && [ $i -lt 25 ]; do sleep 0.2; i=$((i+1)); done
  if live_child "$1"; then kill -9 "$1" 2>/dev/null || true; sleep 0.2; fi
  if live_child "$1"; then return 1; fi
  wait "$1" 2>/dev/null || true
}
# Stops a process this script launched (re-checked by command line), never another.
stop_launched() {
  is_ours "$1" || return 0
  kill "$1" 2>/dev/null || true
  i=0; while is_ours "$1" && [ $i -lt 25 ]; do sleep 0.2; i=$((i+1)); done
  if is_ours "$1"; then kill -9 "$1" 2>/dev/null || true; fi
}
case "$CMD" in
start)
  if ours; then echo "already running (pid $(cat "$PIDFILE"))"; exit 0; fi
  case "$READY_TIMEOUT" in ''|*[!0-9]*) echo "READY_TIMEOUT must be whole seconds" >&2; exit 2 ;; esac
  command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 2; }
  EXPECTED=$(sha256 "$ROOT/artifact/manifest.json")
  extra=""
  [ "${ALLOW_MECHANICAL:-}" = 1 ] && extra=-public-demo-allow-mechanical
  # Pid bookkeeping is prepared before anything is launched.
  if [ -L "$PIDFILE" ] || { [ -e "$PIDFILE" ] && [ ! -f "$PIDFILE" ]; }; then
    echo "start refused: $PIDFILE exists and is not a regular file; nothing launched" >&2; exit 1
  fi
  PIDTMP=$RUN/.flh-public-demo.pid.$$
  if ! { printf 'starting\n' > "$PIDTMP"; } 2>/dev/null; then
    rm -f "$PIDTMP" 2>/dev/null || true
    echo "start refused: cannot write pid bookkeeping in $RUN; nothing launched" >&2; exit 1
  fi
  launched=""; started=0
  # Any exit before "started" stops the launched process and removes only this start's bookkeeping.
  start_cleanup() {
    [ "$started" = 1 ] && return 0
    rm -f "$PIDTMP" 2>/dev/null || true
    [ -n "$launched" ] || return 0
    if ! stop_child "$launched"; then echo "start cleanup: launched pid $launched did not stop" >&2; fi
    if [ -f "$PIDFILE" ] && [ "$(cat "$PIDFILE" 2>/dev/null)" = "$launched" ]; then rm -f "$PIDFILE"; fi
    if [ -d "$PIDFILE" ]; then rm -f "$PIDFILE/${PIDTMP##*/}" 2>/dev/null || true; fi
  }
  trap start_cleanup EXIT
  trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM
  touch "$LOG"
  OFFSET=$(wc -c < "$LOG" | tr -d ' ')
  (cd "$ROOT" && exec env -i PATH=/usr/bin:/bin LISTEN_HOST=127.0.0.1 PORT="$PORT" AI_PROVIDER=rule-based \
     EXTRACTOR_PROVIDER=disabled EMBEDDING_PROVIDER=disabled SEMANTIC_SEARCH=disabled HTTP_ALLOWED_HOSTS="${ALLOWED_HOST:-}" \
     "$SERVER_BIN" -public-demo-artifact "$ROOT/artifact" -web-dir "$ROOT/web" $extra) >> "$LOG" 2>&1 &
  launched=$!
  # Record the pid: write the prepared file, rename it into place, read it back.
  if ! { printf '%s\n' "$launched" > "$PIDTMP" && mv -f "$PIDTMP" "$PIDFILE" && [ -f "$PIDFILE" ] && [ ! -L "$PIDFILE" ] \
         && [ "$(cat "$PIDFILE")" = "$launched" ]; } 2>/dev/null; then
    if stop_child "$launched"; then
      echo "start failed: could not record pid $launched in $PIDFILE; stopped the launched process" >&2
    else
      echo "start failed: could not record pid $launched in $PIDFILE, and it did not stop" >&2
    fi
    exit 1
  fi
  deadline=$(( $(date +%s) + READY_TIMEOUT ))
  while :; do
    if ! kill -0 "$launched" 2>/dev/null; then
      rm -f "$PIDFILE"
      echo "start failed: the server exited during startup; see $LOG" >&2; exit 1
    fi
    if answers_as_us && owns_listener "$launched" && is_ours "$launched"; then
      started=1; trap - EXIT HUP INT TERM
      echo "started (pid $launched, 127.0.0.1:$PORT)"; exit 0
    fi
    if [ "$(date +%s)" -gt "$deadline" ]; then
      stop_launched "$launched"
      rm -f "$PIDFILE"
      echo "start failed: not ready within ${READY_TIMEOUT}s; stopped the launched process only; see $LOG" >&2; exit 1
    fi
    sleep 0.2
  done ;;
status)
  if ours; then
    echo "running (pid $(cat "$PIDFILE"))"
    curl -fsS --max-time 5 "http://127.0.0.1:$PORT/knowledge-library/demo" | python3 -c 'import json,sys; a=json.load(sys.stdin)["artifact"]; print("artifact", a["version"], a["vector_source"], "real_model=%s" % a["real_model"], a["release_status"])'
  else echo "stopped"; exit 3; fi ;;
stop)
  if ours; then kill "$(cat "$PIDFILE")"; i=0; while ours && [ $i -lt 50 ]; do sleep 0.2; i=$((i+1)); done; fi
  if ours; then echo "did not stop" >&2; exit 1; fi
  rm -f "$PIDFILE"; echo "stopped" ;;
*) echo "usage: ctl.sh start|status|stop RUNTIME_DIR" >&2; exit 2 ;;
esac
