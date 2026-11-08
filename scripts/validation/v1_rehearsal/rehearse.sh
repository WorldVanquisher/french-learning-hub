#!/bin/bash
# v1.0 release rehearsal: real Docker Compose upgrade and recovery of the
# packaged application, through the daily wrapper, in an isolated project.
#
#   bash scripts/validation/v1_rehearsal/rehearse.sh run   WORK_DIR BASELINE_IMAGE [--inject-failure after-seed] [--keep]
#   bash scripts/validation/v1_rehearsal/rehearse.sh serve WORK_DIR    # RC package + fake provider, empty DB (browser smoke)
#   bash scripts/validation/v1_rehearsal/rehearse.sh verify WORK_DIR   # read-only: does the URL belong to that `serve`?
#   bash scripts/validation/v1_rehearsal/rehearse.sh down  WORK_DIR    # remove what `serve` started
#
# BASELINE_IMAGE is the known-good image to upgrade from, given by its
# immutable ID (sha256:...). The harness never rebuilds, retags or removes it;
# it only adds rehearsal tags. The release candidate (RC) is built from this
# working tree by the wrapper's own `up`.
#
# Isolation: project flh-rehearsal-<run>, images flh-rehearsal-<run>:*,
# 127.0.0.1:${REHEARSAL_PORT:-18995}, settings/data/evidence under WORK_DIR
# (new or empty, outside the repository). The fake OpenAI-compatible provider
# runs as a second service of the same project (python:3.12-slim pinned by digest,
# never pulled by the harness, no published port); the key is a placeholder, so no paid call is possible.
# Before the first mutating command every resolved Compose configuration is
# checked against the daily instance (project, images, port, /data mount),
# whose container and image fingerprints must be unchanged at the end.
# Cleanup removes only this run's containers, network and tags. Evidence:
# WORK_DIR/evidence/ (results.tsv, logs, snapshots, compose state on exit).
set -uo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd -P)
H="$REPO/scripts/validation/v1_rehearsal"
FIX="$REPO/scripts/validation/daily_v1_rc"
WRAPPER="$REPO/scripts/daily/flh-daily.sh"
DAILY_PROJECT=french-learning-hub
DAILY_IMAGE=french-learning-hub:local
PORT=${REHEARSAL_PORT:-18995}
MODE=${1:-}; WORK=${2:-}
[ -n "$MODE" ] && [ -n "$WORK" ] || { sed -n '4,8p' "$0" >&2; exit 2; }
WORK=$(realpath -m "$WORK")
case "$WORK/" in "$REPO"/*) echo "refused: WORK_DIR must be outside the repository" >&2; exit 2 ;; esac
TOOLS="docker curl python3"; [ "$MODE" = run ] && TOOLS="$TOOLS sqlite3 sha256sum"
for tool in $TOOLS; do command -v $tool > /dev/null || { echo "refused: $tool is required" >&2; exit 2; }; done
# The fake provider's image. Pinned so CI and the NAS run the same one; the
# harness never pulls it (CI pulls it beforehand).
FAKE_IMAGE=${REHEARSAL_FAKE_IMAGE:-python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e}

E="$WORK/evidence"; RES="$E/results.tsv"
FAILED=0
rec() { printf '%s\t%s\t%s\n' "$1" "$2" "${3:-}" | tee -a "$RES"; }
pass() { rec PASS "$1" "${2:-}"; }
fail() { rec FAIL "$1" "${2:-}"; FAILED=1; }
ok() { if [ "$2" = "$3" ]; then pass "$1" "$2"; else fail "$1" "got [$2] want [$3]"; fi; }
note() { rec NOTE "$1" "${2:-}"; }
abort() { fail "$1" "${2:-}"; note "aborted" "remaining steps not run"; exit 1; }

# ---------------------------------------------------------------- setup
if [ "$MODE" = run ] || [ "$MODE" = serve ]; then
  mkdir -p "$WORK"
  [ -z "$(ls -A "$WORK")" ] || { echo "refused: WORK_DIR must be empty" >&2; exit 2; }
  umask 077
  mkdir -p "$E" "$WORK/config" "$WORK/compose"
  mkdir -m 700 "$WORK/data"
  chmod 755 "$E"   # the fake provider (uid $(id -u)) writes its call log here
  : > "$E/provider-calls.log"   # journey.py reads it before the first provider call
  RUN=$(date -u +%Y%m%d%H%M%S)
  PROJECT="flh-rehearsal-$RUN"
  echo "$PROJECT" > "$WORK/project"
else
  [ -f "$WORK/project" ] || { echo "refused: $WORK has no rehearsal project" >&2; exit 2; }
  PROJECT=$(cat "$WORK/project")
fi
IMG="$PROJECT"            # image repository: $IMG:app, $IMG:before-upgrade
SETTINGS="$WORK/config/rehearsal.env"
export FLH_DAILY_ENV="$SETTINGS" FLH_COMPOSE_PROJECT="$PROJECT"
B="http://127.0.0.1:$PORT"

compose_files() { echo -f "$REPO/compose.yaml" -f "$WORK/compose/$1.yaml"; }
dc() { # dc OVERRIDE args...: plain Compose on the rehearsal project (inspection and cleanup only)
  local o=$1; shift
  (cd "$REPO" && docker compose -p "$PROJECT" $(compose_files "$o") --env-file "$SETTINGS" "$@")
}
wrap() { # wrap OVERRIDE LOGNAME args...: the operator path, isolated
  local o=$1 log=$2; shift 2
  FLH_COMPOSE_OVERRIDE="$WORK/compose/$o.yaml" bash "$WRAPPER" "$@" > "$E/$log.log" 2>&1
}
ready() { curl -fsS --max-time 2 "$B/readyz" 2> /dev/null; }
wait_ready() { for _ in $(seq 60); do ready > /dev/null && return 0; sleep 1; done; return 1; }
app_image() { docker inspect -f '{{.Image}}' "$(dc upgrade ps -aq app 2> /dev/null | head -1)" 2> /dev/null || echo none; }
migrations() { sqlite3 -readonly "$WORK/data/app.db" "SELECT name FROM schema_migrations ORDER BY name" | tr '\n' ' '; }
bundle_has_stage() { # 1 if the served workbench bundle contains the #123 stage summary
  local js; js=$(curl -fsS "$B/" | grep -oE '/assets/[^"]+\.js' | head -1)
  curl -fsS "$B$js" | grep -c "Where this record stands" | sed 's/^[1-9][0-9]*$/1/'
}
daily_fingerprint() {
  local c img
  c=$(docker ps -a --filter "label=com.docker.compose.project=$DAILY_PROJECT" --format '{{.ID}}' | sort | while read -r id; do
    docker inspect -f '{{.Id}} {{.State.Status}} {{.State.StartedAt}} {{.Image}}' "$id"; done)
  img=$(docker image inspect -f '{{.Id}}' "$DAILY_IMAGE" 2> /dev/null || echo absent)
  printf '%s\nimage %s\n' "$c" "$img"
}

write_overrides() { # BASELINE_ID may be empty (serve)
  local fake
  fake=$(cat <<EOF
  fake-provider:
    image: $FAKE_IMAGE
    pull_policy: never
    user: "$(id -u):$(id -g)"
    restart: "no"
    command: ["python3", "-I", "-B", "/fixture/fake_openai.py", "19195", "/evidence/provider-calls.log", "/fixture/cases.json", "0.0.0.0"]
    volumes:
      - type: bind
        source: $FIX
        target: /fixture
        read_only: true
      - type: bind
        source: $E
        target: /evidence
EOF
)
  # baseline: start the given image as is (no build from this tree).
  printf 'services:\n  app:\n    image: %s:app\n    build: !reset null\n    pull_policy: never\n%s\n' "$IMG" "$fake" > "$WORK/compose/baseline.yaml"
  # upgrade: the wrapper's `up` builds this tree into the same tag, like daily `up` builds :local.
  printf 'services:\n  app:\n    image: %s:app\n%s\n' "$IMG" "$fake" > "$WORK/compose/upgrade.yaml"
  # broken: the upgraded image with a startup that fails (unknown server flag).
  printf 'services:\n  app:\n    image: %s:app\n    build: !reset null\n    pull_policy: never\n    entrypoint: ["/app/server", "-rehearsal-induced-startup-failure"]\n%s\n' "$IMG" "$fake" > "$WORK/compose/broken.yaml"
}

write_settings() {
  cat > "$SETTINGS" <<EOF
FLH_DATA_DIR=$WORK/data
FLH_UID=$(id -u)
FLH_GID=$(id -g)
FLH_HOST_PORT=$PORT
AI_PROVIDER=openai
EXTRACTOR_PROVIDER=openai
SUGGESTION_PROVIDER=openai
OPENAI_MODEL=fixture-model-placeholder
OPENAI_API_KEY='placeholder-not-a-real-key'
OPENAI_BASE_URL=http://fake-provider:19195/v1
OPENAI_TIMEOUT=60
HTTP_WRITE_TIMEOUT=75
EOF
  chmod 600 "$SETTINGS"
}

# preflight OVERRIDE...: read-only checks that nothing can target the daily instance.
preflight() {
  local daily_mount used o
  daily_mount=$(docker ps -a --filter "label=com.docker.compose.project=$DAILY_PROJECT" --format '{{.ID}}' | head -1 | xargs -r docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')
  used=$(docker ps --format '{{.Ports}}' | grep -oE ':[0-9]+->' | tr -d ':>-' | sort -u | tr '\n' ' ')
  for o in "$@"; do
    dc "$o" config --format json > "$E/config-$o.json" 2> "$E/config-$o.err" || abort "preflight: compose config ($o)" "$(head -c 300 "$E/config-$o.err")"
    local verdict
    verdict=$(python3 -I - "$E/config-$o.json" "$PROJECT" "$IMG" "$PORT" "$WORK/data" "$DAILY_PROJECT" "${daily_mount:-none}" "$used" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1])); project, img, port, data, daily, daily_mount, used = sys.argv[2:9]
bad = []
if cfg.get("name") != project or project == daily: bad.append(f"project {cfg.get('name')}")
for name, svc in cfg["services"].items():
    image = svc.get("image", "")
    if image.split(":")[0] == "french-learning-hub": bad.append(f"{name} uses a daily image name {image}")
    if "container_name" in svc: bad.append(f"{name} sets container_name")
    for v in svc.get("volumes", []):
        if v.get("source") and daily_mount != "none" and v["source"].rstrip("/") == daily_mount.rstrip("/"): bad.append(f"{name} mounts the daily data")
app = cfg["services"]["app"]
if not app.get("image", "").startswith(img + ":"): bad.append(f"app image {app.get('image')}")
ports = app.get("ports", [])
if len(ports) != 1 or ports[0].get("host_ip") != "127.0.0.1" or str(ports[0].get("published")) != port: bad.append(f"app ports {ports}")
if port in used.split(): bad.append(f"port {port} is already published by a container")
mounts = [v["source"] for v in app.get("volumes", []) if v.get("target") == "/data"]
if mounts != [data]: bad.append(f"/data mount {mounts}")
if cfg["services"].get("fake-provider", {}).get("ports"): bad.append("fake-provider publishes a port")
print("; ".join(bad) or "ok")
PY
)
    [ "$verdict" = ok ] && pass "preflight: $o resolves to project $PROJECT, image $IMG:app, 127.0.0.1:$PORT, data in WORK_DIR; daily untouched" || abort "preflight: $o" "$verdict"
  done
  [ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ] && pass "preflight: project $PROJECT has no containers yet" || abort "preflight: project already has containers"
  ss -ltn 2> /dev/null | grep -q ":$PORT " && abort "preflight: port $PORT is in use" || pass "preflight: port $PORT is free"
}

collect() { # evidence of the project's state, whatever happened
  dc upgrade ps -a > "$E/compose-ps.txt" 2>&1
  dc upgrade logs --no-color --timestamps > "$E/compose-logs.txt" 2>&1
  docker ps -a --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}} {{.Image}} {{.Status}}' > "$E/containers-at-exit.txt" 2>&1
}

cleanup() {
  local rc=$?
  trap - EXIT
  [ -f "$SETTINGS" ] || exit $rc
  collect
  if [ "${KEEP:-0}" = 1 ]; then note "cleanup" "--keep: project $PROJECT left running"; exit $rc; fi
  dc upgrade down --remove-orphans > "$E/down.log" 2>&1
  local tags; tags=$(docker image ls --format '{{.Repository}}:{{.Tag}}' "$IMG" 2> /dev/null)
  for t in $tags; do docker image rm "$t" >> "$E/down.log" 2>&1; done
  if [ -n "${RC_ID:-}" ] && docker image inspect "$RC_ID" > /dev/null 2>&1 && [ -z "$(docker image inspect -f '{{join .RepoTags " "}}' "$RC_ID")" ]; then
    docker image rm "$RC_ID" >> "$E/down.log" 2>&1
  fi
  ok "cleanup: no container of $PROJECT remains" "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" | wc -l)" 0
  ok "cleanup: no $IMG image tag remains" "$(docker image ls -q "$IMG" | wc -l)" 0
  ok "cleanup: the project network is gone" "$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT" | wc -l)" 0
  if [ -n "${DAILY_BEFORE:-}" ]; then
    daily_fingerprint > "$E/daily-after.txt"
    if diff -q "$E/daily-before.txt" "$E/daily-after.txt" > /dev/null; then pass "daily instance unchanged (container id, state, start time, image; $DAILY_IMAGE id)"; else fail "daily instance changed" "$(diff "$E/daily-before.txt" "$E/daily-after.txt" | head -c 300)"; fi
  fi
  [ -n "${BASELINE:-}" ] && { docker image inspect "$BASELINE" > /dev/null 2>&1 && pass "baseline image $BASELINE still present" || fail "baseline image missing"; }
  echo "evidence: $E"
  [ $FAILED = 0 ] && [ $rc = 0 ] && exit 0
  exit 1
}

# ---------------------------------------------------------------- down
if [ "$MODE" = down ]; then
  KEEP=0
  [ -f "$E/daily-before.txt" ] && DAILY_BEFORE=1   # recorded by `serve`
  cleanup
fi

# ---------------------------------------------------------------- verify
# Read-only proof that 127.0.0.1:PORT is the instance `serve` started in this
# WORK_DIR (ownership.py lists every check). Writes evidence/ownership.json,
# which browser_smoke.mjs requires before it seeds anything. Fails closed.
if [ "$MODE" = verify ]; then
  python3 -I -B "$H/ownership.py" --work "$WORK" --project "$PROJECT" --port "$PORT" --repo "$REPO" \
    --image "$IMG:app" --fake-image "$FAKE_IMAGE" --out "$E/ownership.json" > "$E/ownership.txt" 2>&1
  rc=$?
  grep -E '^FAIL|^ownership verdict' "$E/ownership.txt" | tee -a "$RES"
  exit $rc
fi

# ---------------------------------------------------------------- serve
if [ "$MODE" = serve ]; then
  KEEP=1
  write_settings; write_overrides
  DAILY_BEFORE=1; daily_fingerprint > "$E/daily-before.txt"
  trap cleanup EXIT
  preflight upgrade
  wrap upgrade serve-up up && pass "RC package started through the wrapper" || abort "RC up" "$(tail -3 "$E/serve-up.log")"
  ok "readyz" "$(ready)" '{"status":"ready"}'
  ok "served bundle has the record stage summary" "$(bundle_has_stage)" 1
  note "browser" "next: rehearse.sh verify $WORK, then browser_smoke.mjs --ownership $E/ownership.json (see README.md); afterwards: rehearse.sh down $WORK"
  exit 0
fi

[ "$MODE" = run ] || { echo "unknown mode $MODE" >&2; exit 2; }
BASELINE=${3:-}
[ -n "$BASELINE" ] || { echo "refused: BASELINE_IMAGE (sha256:...) is required; the owner supplies it" >&2; exit 2; }
shift 3
INJECT=""; KEEP=0
while [ $# -gt 0 ]; do
  case $1 in --inject-failure) INJECT=$2; shift 2 ;; --keep) KEEP=1; shift ;; *) echo "unknown option $1" >&2; exit 2 ;; esac
done
BASELINE=$(docker image inspect -f '{{.Id}}' "$BASELINE" 2> /dev/null) || { echo "refused: baseline image not present locally (it is never pulled)" >&2; exit 2; }
note "run" "project $PROJECT · baseline $BASELINE · port $PORT · work $WORK"
write_settings; write_overrides
DAILY_BEFORE=1; daily_fingerprint > "$E/daily-before.txt"
note "daily fingerprint" "$(tr '\n' ' ' < "$E/daily-before.txt" | head -c 250)"
trap cleanup EXIT

# 0. Preflight (read-only), then the first mutating command.
preflight baseline upgrade broken
wrap baseline check check && pass "wrapper check accepts the isolated settings" || abort "wrapper check" "$(tail -3 "$E/check.log")"
docker image tag "$BASELINE" "$IMG:app" && pass "tagged the baseline as $IMG:app (new tag only)"

# 1. Baseline package.
wrap baseline 1-baseline-up up && pass "1. baseline package started through the wrapper (up, healthy)" || abort "1. baseline up" "$(tail -3 "$E/1-baseline-up.log")"
ok "1. baseline readyz" "$(ready)" '{"status":"ready"}'
ok "1. baseline healthz" "$(curl -fsS "$B/healthz")" '{"status":"ok"}'
ok "1. the running app is the baseline image" "$(app_image)" "$BASELINE"
ok "1. baseline bundle predates #123 (no record stage summary)" "$(bundle_has_stage)" 0
MIG_BASE=$(migrations); note "1. baseline migrations" "$MIG_BASE"

# Seed: the PR #123 acceptance fixture, against the baseline.
python3 -I -B "$FIX/journey.py" "$B" "$WORK/data/app.db" "$E/provider-calls.log" "$FIX/cases.json" "$E/seed-evidence.json" > "$E/seed-journey.txt" 2>&1 \
  && pass "1. seeded with the RC fixture on the baseline" "$(tail -1 "$E/seed-journey.txt")" \
  || abort "1. RC fixture on the baseline" "$(grep -E '^FAIL|passed|Error' "$E/seed-journey.txt" | head -5 | tr '\n' ' ')"
python3 -I -B "$H/snapshot.py" "$B" "$E/snapshot-1-baseline.json" > "$E/snapshot-1.txt" 2>&1 || abort "1. baseline snapshot" "$(tail -2 "$E/snapshot-1.txt")"
note "1. baseline recorded" "$(cat "$E/snapshot-1.txt")"
# A comparison of empty snapshots would prove nothing.
ok "1. the baseline holds the seeded data" "$(python3 -I -c 'import json,sys; s=json.load(open(sys.argv[1]))["summary"]; print(s["entries"] >= 4 and s["memberships"] >= 2 and s["concepts"] >= 1 and s["suggestion_runs"] >= 1)' "$E/snapshot-1-baseline.json")" True
[ "$INJECT" = after-seed ] && abort "injected failure after seeding (--inject-failure after-seed)"

# 2. Verified backup through the documented operator path.
wrap upgrade 2-backup backup && pass "2. wrapper backup succeeded" || abort "2. backup" "$(tail -3 "$E/2-backup.log")"
BACKUP=$(ls -d "$WORK/data.backups"/flh-* | tail -1)
(cd "$BACKUP" && sha256sum --quiet -c SHA256SUMS) && pass "2. backup checksums verify" "$BACKUP" || fail "2. backup checksums"
ok "2. backup integrity_check" "$(sqlite3 -readonly "$BACKUP/app.db" 'PRAGMA integrity_check;')" ok
ok "2. service is ready again after the backup" "$(wait_ready && ready)" '{"status":"ready"}'
docker image tag "$IMG:app" "$IMG:before-upgrade" && pass "2. kept the known-good image as $IMG:before-upgrade"

# 3. Upgrade: the wrapper builds this tree (RC) and recreates the service.
wrap upgrade 3-upgrade-up up && pass "3. RC package built and started through the wrapper (up, healthy)" || abort "3. RC up" "$(tail -5 "$E/3-upgrade-up.log")"
RC_ID=$(docker image inspect -f '{{.Id}}' "$IMG:app")
note "3. RC image" "$RC_ID"
[ "$RC_ID" != "$BASELINE" ] && pass "3. the RC image differs from the baseline" || fail "3. RC image equals the baseline"
ok "3. the running app is the RC image" "$(app_image)" "$RC_ID"
ok "3. RC readyz" "$(ready)" '{"status":"ready"}'
ok "3. RC bundle has the record stage summary" "$(bundle_has_stage)" 1
MIG_RC=$(migrations); note "3. RC migrations" "$MIG_RC"
if [ "$MIG_BASE" = "$MIG_RC" ]; then
  note "3. migrations" "identical in both images: this proves an image upgrade and recovery, not a database migration"
else
  note "3. migrations" "the RC applied: $(comm -13 <(tr ' ' '\n' <<< "$MIG_BASE" | sort) <(tr ' ' '\n' <<< "$MIG_RC" | sort) | tr '\n' ' ')"
fi
python3 -I -B "$H/snapshot.py" "$B" "$E/snapshot-3-rc.json" > "$E/snapshot-3.txt" 2>&1
cmp -s "$E/snapshot-1-baseline.json" "$E/snapshot-3-rc.json" && pass "3. the recorded baseline is unchanged under the RC" || fail "3. baseline differs under the RC" "diff $E/snapshot-1-baseline.json $E/snapshot-3-rc.json"
AFTER=$(curl -fsS -H 'Content-Type: application/json' -d "{\"schema_version\":\"learning_capture_v1\",\"capture_id\":\"rehearsal-after-backup-$RUN\",\"source\":\"manual\",\"original_input\":\"Question écrite après la sauvegarde (répétition).\",\"original_context\":\"\"}" "$B/captures" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["entry_id"])')
note "3. wrote record #$AFTER after the backup (must not survive the recovery)"

# 4. A failed upgrade, then recovery in the documented order.
if wrap broken 4-broken-up up; then fail "4. the induced startup failure was not detected"; else pass "4. induced startup failure: wrapper up reports not healthy" "$(tail -1 "$E/4-broken-up.log")"; fi
ready > /dev/null && fail "4. service answered although startup failed" || pass "4. readyz unreachable while the startup fails"
dc broken logs --no-color app > "$E/4-broken-app.log" 2>&1
grep -q "rehearsal-induced-startup-failure" "$E/4-broken-app.log" && pass "4. the app log names the failure (unknown flag)" || fail "4. failure cause not in the log"
wrap broken 4-stop stop && pass "4. recovery step 1: stop the failed service" || fail "4. stop"
docker image tag "$IMG:before-upgrade" "$IMG:app" && pass "4. recovery step 2: restore the known-good image tag"
wrap upgrade 4-restore restore "$BACKUP" && pass "4. recovery step 3: wrapper restore of the verified backup (healthy)" || abort "4. restore" "$(tail -3 "$E/4-restore.log")"
ok "4. readyz after recovery" "$(ready)" '{"status":"ready"}'
ok "4. the running app is the baseline image again" "$(app_image)" "$BASELINE"
ok "4. integrity_check of the live database" "$(sqlite3 -readonly "$WORK/data/app.db" 'PRAGMA integrity_check;')" ok
ok "4. migrations after recovery equal the baseline" "$(migrations)" "$MIG_BASE"
python3 -I -B "$H/snapshot.py" "$B" "$E/snapshot-4-recovered.json" > "$E/snapshot-4.txt" 2>&1
cmp -s "$E/snapshot-1-baseline.json" "$E/snapshot-4-recovered.json" && pass "4. original questions, versions, CURRENT SAME and sources match the baseline" || fail "4. recovered state differs" "diff $E/snapshot-1-baseline.json $E/snapshot-4-recovered.json"
ok "4. the record written after the backup is gone" "$(curl -s -o /dev/null -w '%{http_code}' "$B/entries/$AFTER")" 404
OLD=$(ls -d "$WORK/data.before-restore-"* | tail -1)
ok "4. it is kept in the replaced data directory" "$(sqlite3 -readonly "$OLD/app.db" "SELECT COUNT(*) FROM learning_entries WHERE id = $AFTER")" 1
python3 -I -c 'import json,sys; s=json.load(open(sys.argv[1])); print(json.dumps(s["summary"]))' "$E/snapshot-4-recovered.json" > "$E/summary.txt"
note "done" "$(cat "$E/summary.txt")"
exit $FAILED
