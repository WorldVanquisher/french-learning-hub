#!/bin/bash
# v1.0 packaged browser acceptance: build and start the RC package in an
# isolated Compose project, prove the URL is that project's, run
# browser_smoke.mjs in a real Chrome/Chromium, and always tear down.
#
#   bash scripts/validation/v1_rehearsal/browser_check.sh WORK_DIR [--chrome PATH | --browser-container] \
#        [--inject-failure PHASE] [--npm-cache DIR]
#
# WORK_DIR: absolute, new or empty, outside the repository. Layout:
#   tools/        playwright-core 1.49.1 (no browser download)
#   instance/     rehearse.sh serve: settings, data, evidence (ownership.json)
#   browser/      results.json and screenshots from browser_smoke.mjs
#   diagnostics/  bounded copy for CI: results, screenshots, sanitized logs
#   summary.txt   one line per stage
#
# Browser: --chrome PATH, else $CHROME, else google-chrome, google-chrome-stable,
# chromium, chromium-browser on PATH, else the macOS Google Chrome. For a host
# without a usable browser (the NAS), --browser-container runs the smoke in a
# disposable container from the local node:22-bookworm-slim image (pinned,
# never pulled) with the Debian chromium package installed at run time, on the
# host network so that it reaches 127.0.0.1 only through the given URL.
# The browser profile is always a fresh temporary one.
#
# Exit: 0 PASS; 1 FAIL (harness, ownership, smoke or teardown); 2 refused
# (usage); 3 BLOCKED: no browser, so the smoke did not run. A missing
# browser is never a pass.
set -uo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd -P)
H="$REPO/scripts/validation/v1_rehearsal"
PORT=${REHEARSAL_PORT:-18995}
URL="http://127.0.0.1:$PORT"
BROWSER_IMAGE=${FLH_BROWSER_IMAGE:-node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436}
PLAYWRIGHT_CORE=playwright-core@1.49.1
SMOKE_TIMEOUT=${SMOKE_TIMEOUT:-600}

WORK=${1:-}
[ -n "$WORK" ] || { sed -n '5,6p' "$0" >&2; exit 2; }
shift
CHROME_ARG=""; CONTAINER=0; INJECT=""; NPM_CACHE=""
while [ $# -gt 0 ]; do
  case $1 in
    --chrome) CHROME_ARG=${2:?}; shift 2 ;;
    --browser-container) CONTAINER=1; shift ;;
    --inject-failure) INJECT=${2:?}; shift 2 ;;
    --npm-cache) NPM_CACHE=${2:?}; shift 2 ;;
    *) echo "refused: unknown option $1" >&2; exit 2 ;;
  esac
done
case "$WORK" in /*) ;; *) echo "refused: WORK_DIR must be absolute" >&2; exit 2 ;; esac
WORK=$(realpath -m "$WORK")
case "$WORK/" in "$REPO"/*) echo "refused: WORK_DIR must be outside the repository" >&2; exit 2 ;; esac
[ -n "$CHROME_ARG" ] && [ "$CONTAINER" = 1 ] && { echo "refused: --chrome and --browser-container are exclusive" >&2; exit 2; }
mkdir -p "$WORK"
[ -z "$(ls -A "$WORK")" ] || { echo "refused: WORK_DIR must be empty" >&2; exit 2; }
for tool in docker node npm python3 curl timeout; do command -v $tool > /dev/null || { echo "refused: $tool is required" >&2; exit 2; }; done
mkdir -p "$WORK/tools" "$WORK/browser" "$WORK/diagnostics"
INST="$WORK/instance"
SUM="$WORK/summary.txt"
stage() { printf '%s\t%s\t%s\n' "$1" "$2" "${3:-}" | tee -a "$SUM"; }

# ---------------------------------------------------------------- browser first
# Decided before anything is built or started: a missing browser is BLOCKED.
blocked() {
  stage BLOCKED browser "$1"
  printf '{"status": "browser-missing", "reason": "%s", "checks": []}\n' "$1" > "$WORK/diagnostics/results.json"
  echo "BLOCKED: the browser smoke did not run" >&2
  exit 3
}
if [ "$CONTAINER" = 1 ]; then
  docker image inspect "$BROWSER_IMAGE" > /dev/null 2>&1 || blocked "browser container image not present locally: $BROWSER_IMAGE (it is never pulled)"
  stage PASS browser "container $BROWSER_IMAGE + Debian chromium"
else
  CHROME=${CHROME_ARG:-${CHROME:-}}
  if [ -z "$CHROME" ]; then
    for c in google-chrome google-chrome-stable chromium chromium-browser; do
      p=$(command -v "$c" 2> /dev/null) && { CHROME=$p; break; }
    done
    [ -z "$CHROME" ] && [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ] && CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  fi
  [ -n "$CHROME" ] && [ -x "$CHROME" ] || blocked "no executable Chrome/Chromium (--chrome, \$CHROME, google-chrome, google-chrome-stable, chromium, chromium-browser, macOS Google Chrome)"
  VERSION=$("$CHROME" --version 2> /dev/null) || blocked "$CHROME --version failed"
  stage PASS browser "$CHROME ($VERSION)"
fi

# ---------------------------------------------------------------- driver
NPM_ENV=(PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm_config_update_notifier=false npm_config_cache="${NPM_CACHE:-$WORK/npm-cache}")
if (cd "$WORK/tools" && env "${NPM_ENV[@]}" npm init -y > /dev/null && env "${NPM_ENV[@]}" npm install --no-audit --no-fund --ignore-scripts "$PLAYWRIGHT_CORE") > "$WORK/tools/install.log" 2>&1; then
  stage PASS driver "$PLAYWRIGHT_CORE (no browser download)"
else
  stage FAIL driver "npm install $PLAYWRIGHT_CORE failed (tools/install.log)"; exit 1
fi

# ---------------------------------------------------------------- teardown (always)
SERVE_RC=-1; VERIFY_RC=-1; SMOKE_RC=-1
BROWSER_CONTAINER=""
teardown() {
  local rc=$? down_rc=0
  trap - EXIT INT TERM
  if [ -n "$BROWSER_CONTAINER" ] && [ -n "$(docker ps -aq --filter "name=^${BROWSER_CONTAINER}$" --filter label=org.flh.task=v1-browser-smoke)" ]; then
    docker rm -f "$BROWSER_CONTAINER" > /dev/null 2>&1
  fi
  if [ -f "$INST/project" ]; then
    bash "$H/rehearse.sh" down "$INST" > "$WORK/down.log" 2>&1; down_rc=$?
    if [ $down_rc = 0 ]; then stage PASS teardown "only this run's containers, network and tags removed; daily instance unchanged"
    else stage FAIL teardown "rehearse.sh down exit $down_rc (down.log)"; fi
  fi
  collect_diagnostics
  local verdict=FAIL
  if [ "$SMOKE_RC" = 0 ] && [ $down_rc = 0 ] && python3 -I -c '
import json, sys
r = json.load(open(sys.argv[1]))
sys.exit(0 if r.get("status") == "passed" and r.get("failed") == 0 and r.get("phasesRun") == r.get("phases") and r.get("passed", 0) >= 30 else 1)
' "$WORK/browser/results.json" 2> /dev/null; then verdict=PASS; fi
  stage "$verdict" result "serve $SERVE_RC, verify $VERIFY_RC, smoke $SMOKE_RC, teardown $down_rc; evidence $WORK/browser, diagnostics $WORK/diagnostics"
  [ "$verdict" = PASS ] && exit 0
  [ "$SMOKE_RC" = 3 ] && exit 3
  [ $rc != 0 ] && [ $rc != 1 ] && [ $rc != 3 ] && exit $rc
  exit 1
}
sanitize() { # bounded, with anything key-like redacted
  tail -c 200000 "$1" | sed -E 's/placeholder-not-a-real-key/[placeholder-key]/g; s/sk-[A-Za-z0-9_-]{8,}/[redacted-key]/g; s/(Bearer )[^ "]+/\1[redacted]/g; s/(OPENAI_API_KEY|EMBEDDING_API_KEY|QDRANT_API_KEY)=[^ ]*/\1=[redacted]/g'
}
collect_diagnostics() {
  local d="$WORK/diagnostics" n=0 f
  cp "$SUM" "$d/summary.txt" 2> /dev/null
  [ -f "$WORK/browser/results.json" ] && [ "$(stat -c %s "$WORK/browser/results.json")" -le 2000000 ] && cp "$WORK/browser/results.json" "$d/"
  mkdir -p "$d/screenshots"
  for f in "$WORK/browser"/*.png; do
    [ -f "$f" ] || continue
    [ "$(stat -c %s "$f")" -le 5000000 ] && [ $n -lt 30 ] && { cp "$f" "$d/screenshots/"; n=$((n + 1)); }
  done
  for f in results.tsv ownership.json ownership.txt compose-ps.txt containers-at-exit.txt; do
    [ -f "$INST/evidence/$f" ] && sanitize "$INST/evidence/$f" > "$d/instance-$f"
  done
  for f in "$INST/evidence/compose-logs.txt" "$INST/evidence/serve-up.log" "$WORK/smoke.log" "$WORK/serve.log" "$WORK/down.log"; do
    [ -f "$f" ] && sanitize "$f" > "$d/$(basename "$f")"
  done
  du -sh "$d" | cut -f1 > "$d/size.txt"
}
trap teardown EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ---------------------------------------------------------------- package
bash "$H/rehearse.sh" serve "$INST" > "$WORK/serve.log" 2>&1; SERVE_RC=$?
if [ $SERVE_RC = 0 ]; then stage PASS serve "RC built and started through the wrapper in $(cat "$INST/project")"
else stage FAIL serve "rehearse.sh serve exit $SERVE_RC (serve.log)"; exit 1; fi

bash "$H/rehearse.sh" verify "$INST" > "$WORK/verify.log" 2>&1; VERIFY_RC=$?
if [ $VERIFY_RC = 0 ]; then stage PASS ownership "$URL belongs to $(cat "$INST/project") (instance/evidence/ownership.json)"
else stage FAIL ownership "refused to seed: $(grep -E '^FAIL' "$WORK/verify.log" | head -3 | tr '\n' ' ')"; exit 1; fi

# ---------------------------------------------------------------- smoke
SMOKE_ARGS=(--url "$URL")
[ -n "$INJECT" ] && SMOKE_ARGS+=(--inject-failure "$INJECT")
if [ "$CONTAINER" = 1 ]; then
  BROWSER_CONTAINER="$(cat "$INST/project")-browser"
  timeout "$SMOKE_TIMEOUT" docker run --rm --pull never --name "$BROWSER_CONTAINER" --label org.flh.task=v1-browser-smoke \
    --network host --cap-drop ALL --cap-add SETUID --cap-add SETGID --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
    -v "$REPO/scripts/validation:/smoke:ro" -v "$WORK/tools:/tools:ro" -v "$WORK/browser:/out" \
    -v "$INST/evidence/ownership.json:/ownership.json:ro" \
    "$BROWSER_IMAGE" bash -c '
      set -e
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq > /dev/null && apt-get install -y -qq --no-install-recommends chromium fonts-wqy-zenhei > /dev/null
      chromium --version
      exec setpriv --reuid="$0" --regid="$1" --clear-groups env HOME=/tmp PLAYWRIGHT_CORE_DIR=/tools/node_modules/playwright-core \
        node /smoke/v1_rehearsal/browser_smoke.mjs --out /out --ownership /ownership.json --chrome /usr/bin/chromium "${@:2}"
    ' "$(id -u)" "$(id -g)" "${SMOKE_ARGS[@]}" > "$WORK/smoke.log" 2>&1
  SMOKE_RC=$?
else
  PLAYWRIGHT_CORE_DIR="$WORK/tools/node_modules/playwright-core" timeout "$SMOKE_TIMEOUT" \
    node "$H/browser_smoke.mjs" "${SMOKE_ARGS[@]}" --out "$WORK/browser" --ownership "$INST/evidence/ownership.json" --chrome "$CHROME" > "$WORK/smoke.log" 2>&1
  SMOKE_RC=$?
fi
grep -E '^(PASS|FAIL) ' "$WORK/smoke.log" | tail -n 60
case $SMOKE_RC in
  0) stage PASS smoke "$(tail -1 "$WORK/smoke.log")" ;;
  3) stage BLOCKED smoke "the browser did not start: $(grep -m1 refused "$WORK/smoke.log")" ;;
  124) stage FAIL smoke "timed out after ${SMOKE_TIMEOUT}s" ;;
  *) stage FAIL smoke "exit $SMOKE_RC: $(tail -1 "$WORK/smoke.log")" ;;
esac
[ "$SMOKE_RC" = 0 ] || exit 1
exit 0
