#!/bin/bash
# FLH-094 private daily use: run the existing Compose release with ONE owner
# settings file, every time. See docs/DAILY_USE.md.
#
#   bash scripts/daily/flh-daily.sh check | up | stop | start | restart | status | logs
#   bash scripts/daily/flh-daily.sh backup
#   bash scripts/daily/flh-daily.sh restore BACKUP_DIR
#   bash scripts/daily/flh-daily.sh listening-pull [--scheduled]
#   bash scripts/daily/flh-daily.sh listening-status
#
# Settings file: $FLH_DAILY_ENV, default ~/.config/flh/daily.env (template:
# scripts/daily/daily.env.example). It must be outside the repository, owned by
# you and not readable by others. Every command passes it to
# `docker compose --env-file` and drops inherited shell variables that compose.yaml
# interpolates, so neither a stray shell export nor a forgotten file can silently
# fall back to the rule-based analyzer, disabled extraction or another database.
# This is the same configuration the release already uses (compose.yaml), not a
# second one. Values are never printed: checks report only set/empty and
# non-secret choices.
#
# Nothing here calls a provider, except listening-pull: it runs the Daily
# Listening pull inside the running container (/app/listening-pull), the same
# operation as the workbench's "Pull now" button. A systemd timer may run it
# (scripts/daily/systemd/); this script never installs or enables one.
#
# Isolated rehearsal mode (v1.0 release rehearsal; never needed for daily use):
# set BOTH FLH_COMPOSE_PROJECT (a project name other than french-learning-hub)
# and FLH_COMPOSE_OVERRIDE (a Compose file layered over compose.yaml that gives
# the app another image name). Every command then runs
# `docker compose -p <project> -f compose.yaml -f <override> --env-file ...`.
# The resolved configuration must use that project and must not use a
# french-learning-hub image, so a rehearsal can never rebuild, restart or
# restore the daily instance. With neither set, nothing changes.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd -P)
ENV_FILE=${FLH_DAILY_ENV:-$HOME/.config/flh/daily.env}
die() { echo "flh-daily: $*" >&2; exit 2; }

usage() {
  echo "usage: flh-daily.sh check|up|stop|start|restart|status|logs|backup|restore BACKUP_DIR|listening-pull [--scheduled]|listening-status" >&2
  exit 2
}
CMD=${1:-}
[ -n "$CMD" ] || usage

# ---- Settings file: present, private, outside the repository. ----
[ -f "$ENV_FILE" ] || die "settings file not found: $ENV_FILE (copy scripts/daily/daily.env.example there, chmod 600, then edit it; or set FLH_DAILY_ENV)"
ENV_FILE=$(realpath "$ENV_FILE")
case "$ENV_FILE/" in "$REPO"/*) die "the settings file must be outside the repository: $ENV_FILE" ;; esac
[ "$(stat -c %u "$ENV_FILE")" = "$(id -u)" ] || die "the settings file must be owned by you: $ENV_FILE"
perm=$(stat -c %a "$ENV_FILE")
[ $((8#$perm & 077)) -eq 0 ] || die "the settings file is readable by others (mode $perm); run: chmod 600 $ENV_FILE"
command -v docker > /dev/null || die "missing prerequisite: docker"
command -v python3 > /dev/null || die "missing prerequisite: python3"

# Every variable compose.yaml interpolates, plus Compose's own selectors, is
# removed from the inherited environment, so the settings file is the only source.
DAILY_PROJECT=french-learning-hub
ISOLATED=${FLH_COMPOSE_PROJECT:-}
OVERRIDE=${FLH_COMPOSE_OVERRIDE:-}
PROJECT_ARGS=()
COMPOSE_FILES=("$REPO/compose.yaml")
if [ -n "$ISOLATED" ] || [ -n "$OVERRIDE" ]; then
  [ -n "$ISOLATED" ] && [ -n "$OVERRIDE" ] || die "isolated mode needs both FLH_COMPOSE_PROJECT and FLH_COMPOSE_OVERRIDE"
  [[ "$ISOLATED" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "FLH_COMPOSE_PROJECT must be a Compose project name (lowercase letters, digits, - and _)"
  [ "$ISOLATED" != "$DAILY_PROJECT" ] || die "FLH_COMPOSE_PROJECT must not be the daily project ($DAILY_PROJECT)"
  [ -f "$OVERRIDE" ] || die "FLH_COMPOSE_OVERRIDE not found: $OVERRIDE"
  OVERRIDE=$(realpath "$OVERRIDE")
  COMPOSE_FILES+=("$OVERRIDE")
  PROJECT_ARGS=(-p "$ISOLATED" -f "$REPO/compose.yaml" -f "$OVERRIDE")
fi
mapfile -t COMPOSE_VARS < <(cat "${COMPOSE_FILES[@]}" | grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*' | cut -c3- | sort -u)
UNSET=()
for v in "${COMPOSE_VARS[@]}" COMPOSE_PROJECT_NAME COMPOSE_FILE COMPOSE_ENV_FILES COMPOSE_PROFILES; do UNSET+=(-u "$v"); done
compose() { (cd "$REPO" && env "${UNSET[@]}" docker compose "${PROJECT_ARGS[@]}" --env-file "$ENV_FILE" "$@"); }

# validate checks the configuration Compose will actually run, reading the
# resolved config and interpolation environment through a pipe (never a file,
# never printed). On success it prints a value-free summary and the data path.
VALIDATE_PY='
import json, os, stat, sys
repo, uid, mode, isolated = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
cfg_raw, env_raw = sys.stdin.read().split("\n=====FLH094=====\n", 1)
cfg = json.loads(cfg_raw)
app = cfg["services"]["app"]
envr = app.get("environment") or {}
given = set()
for line in env_raw.splitlines():
    key = line.split("=", 1)[0]
    if key: given.add(key)
problems = []
image = app.get("image") or ""
if isolated:
    project = cfg.get("name")
    if project != isolated:
        problems.append(f"isolated mode: the resolved project is {project!r}, not {isolated!r}")
    if not image or image.split(":")[0] == "french-learning-hub":
        problems.append("isolated mode: the override must give the app an image name other than french-learning-hub")
for key in ("AI_PROVIDER", "EXTRACTOR_PROVIDER"):
    if key not in given:
        problems.append(f"{key} must be stated explicitly in the settings file (no implicit default)")
ai, ex = envr.get("AI_PROVIDER", ""), envr.get("EXTRACTOR_PROVIDER", "")
if ai not in ("openai", "rule-based"): problems.append("AI_PROVIDER must be openai or rule-based")
if ex not in ("openai", "disabled"): problems.append("EXTRACTOR_PROVIDER must be openai or disabled")
sg = envr.get("SUGGESTION_PROVIDER", "") or "disabled"
if sg not in ("openai", "disabled"): problems.append("SUGGESTION_PROVIDER must be openai or disabled")
ls = envr.get("LISTENING_PROVIDER", "") or "disabled"
if ls not in ("openai", "disabled"): problems.append("LISTENING_PROVIDER must be openai or disabled")
rd = envr.get("READING_PROVIDER", "") or "disabled"
if rd not in ("openai", "disabled"): problems.append("READING_PROVIDER must be openai or disabled")
real = "openai" in (ai, ex, sg, ls, rd)
if real:
    if not envr.get("OPENAI_API_KEY"): problems.append("OPENAI_API_KEY must be set (the value is never shown)")
    if not envr.get("OPENAI_MODEL"): problems.append("OPENAI_MODEL must be set to the model you chose")
def secs(key, default):
    v = envr.get(key) or ""
    try:
        n = int(v) if v else default
        return n if n > 0 else default
    except ValueError:
        return default
pt, wt = secs("OPENAI_TIMEOUT", 8), secs("HTTP_WRITE_TIMEOUT", 10)
if real and pt >= wt:
    problems.append(f"OPENAI_TIMEOUT ({pt}s) must be below HTTP_WRITE_TIMEOUT ({wt}s), or a stored result can look like a lost response")
# Daily Listening: every part off unless stated; the server re-checks all of it.
src = envr.get("LISTENING_PLAYLIST_SOURCE", "") or "disabled"
auto = envr.get("LISTENING_AUTO_PREPARE", "") or "disabled"
notify = envr.get("LISTENING_NOTIFY", "") or "disabled"
tz = envr.get("LISTENING_TIMEZONE", "") or "UTC"
if src not in ("youtube", "disabled"): problems.append("LISTENING_PLAYLIST_SOURCE must be youtube or disabled")
if src == "youtube":
    if not envr.get("YOUTUBE_API_KEY"): problems.append("LISTENING_PLAYLIST_SOURCE=youtube needs YOUTUBE_API_KEY (the value is never shown)")
    if not envr.get("LISTENING_PLAYLIST_ID"): problems.append("LISTENING_PLAYLIST_SOURCE=youtube needs LISTENING_PLAYLIST_ID")
if auto not in ("daily", "disabled"): problems.append("LISTENING_AUTO_PREPARE must be daily or disabled")
if auto == "daily" and ls != "openai": problems.append("LISTENING_AUTO_PREPARE=daily needs LISTENING_PROVIDER=openai")
if notify not in ("telegram", "disabled"): problems.append("LISTENING_NOTIFY must be telegram or disabled")
if notify == "telegram":
    if auto != "daily": problems.append("LISTENING_NOTIFY=telegram needs LISTENING_AUTO_PREPARE=daily (only a lesson a pull prepared is announced)")
    if not envr.get("TELEGRAM_BOT_TOKEN"): problems.append("LISTENING_NOTIFY=telegram needs TELEGRAM_BOT_TOKEN (the value is never shown)")
    if not envr.get("TELEGRAM_CHAT_ID"): problems.append("LISTENING_NOTIFY=telegram needs TELEGRAM_CHAT_ID")
import re
if not re.fullmatch(r"[A-Za-z_]+(/[A-Za-z0-9_+-]+)*", tz) or tz == "Local":
    problems.append("LISTENING_TIMEZONE must be an IANA time zone name such as Europe/Paris")
if "FLH_DATA_DIR" not in given:
    problems.append("FLH_DATA_DIR must be set in the settings file (the default ./data/release is not used for daily data)")
mounts = [v for v in app.get("volumes", []) if v.get("target") == "/data"]
data = mounts[0]["source"] if mounts else ""
if "FLH_DATA_DIR" in given:
    if not os.path.isabs(data): problems.append("FLH_DATA_DIR must be an absolute path")
    elif not os.path.isdir(data): problems.append(f"FLH_DATA_DIR does not exist or is not a directory: {data}")
    else:
        real_data = os.path.realpath(data)
        if (real_data + "/").startswith(repo.rstrip("/") + "/"):
            problems.append("FLH_DATA_DIR must be outside the repository")
        st = os.stat(real_data)
        if stat.S_IMODE(st.st_mode) & 0o077: problems.append(f"FLH_DATA_DIR must be private (chmod 700 {data})")
        user = (app.get("user") or "1000:1000").split(":")[0]
        if user.isdigit() and st.st_uid != int(user):
            problems.append(f"FLH_DATA_DIR must be owned by FLH_UID {user}")
        for marker in ("flh092-session", "flh092-session.seeding", "fixture.db", "seed.json"):
            if os.path.exists(os.path.join(real_data, marker)):
                problems.append(f"FLH_DATA_DIR looks like a disposable acceptance/fixture directory ({marker}); use a separate daily directory")
if problems:
    for p in problems: print("flh-daily: " + p, file=sys.stderr)
    sys.exit(3)
ports = app.get("ports") or [{}]
host_port = ports[0].get("published", "8080")
base = "custom" if envr.get("OPENAI_BASE_URL") else "default (public OpenAI API)"
if mode == "summary":
    if isolated:
        print(f"project:    {isolated} (isolated rehearsal; image {image})")
    print(f"analysis:   {ai}" + (" — explicit requests call the provider and may be billed" if ai == "openai" else " — local, no provider call"))
    print(f"extraction: {ex}" + (" — explicit requests call the provider and may be billed" if ex == "openai" else " — off"))
    print(f"suggestions: {sg}" + (" — explicit requests call the provider and may be billed" if sg == "openai" else " — off"))
    print(f"listening:  {ls}" + (" — explicit requests call the provider and may be billed" if ls == "openai" else " — off"))
    print(f"reading:    {rd}" + (" — explicit requests call the provider and may be billed" if rd == "openai" else " — off (authored examples still work)"))
    if src == "disabled" and auto == "disabled":
        print("daily listening: off")
    else:
        print(f"daily pull: playlist {src}" + (" (LISTENING_PLAYLIST_ID set · YOUTUBE_API_KEY set) — reads official metadata only, when you press Pull now or run listening-pull" if src == "youtube" else ""))
        print(f"daily preparation: {auto}" + (f" — at most 1 lesson per day ({tz}); a pull calls the provider and may be billed" if auto == "daily" else " — off"))
        print(f"daily notify: {notify}" + (" (TELEGRAM_BOT_TOKEN set · TELEGRAM_CHAT_ID set) — only for a lesson a pull prepared" if notify == "telegram" else " — off"))
        budget = (pt if auto == "daily" else 0) + (secs("TELEGRAM_TIMEOUT", 10) if notify == "telegram" else 0)
        if src == "youtube":
            pages = -(-max(1, min(200, secs("LISTENING_PLAYLIST_MAX_ITEMS", 50))) // 50)
            budget += pages * secs("YOUTUBE_TIMEOUT", 10)
        if budget >= wt:
            print(f"note:       a Pull now can take up to {budget}s, beyond HTTP_WRITE_TIMEOUT ({wt}s); the workbench then checks the stored run by its key")
    if real:
        print(f"OPENAI_MODEL: set · OPENAI_API_KEY: set · OPENAI_BASE_URL: {base} · timeouts: provider {pt}s < write {wt}s")
    print(f"database:   {data}/app.db")
    print(f"browser:    http://127.0.0.1:{host_port}/  (loopback only)")
else:
    print(data if mode == "data" else host_port)
'
validate() {
  local mode=$1 cfg envs
  cfg=$(compose config --format json) || die "docker compose could not read the configuration (see the message above)"
  envs=$(compose config --environment) || die "docker compose could not read the settings file"
  printf '%s\n=====FLH094=====\n%s' "$cfg" "$envs" | python3 -I -c "$VALIDATE_PY" "$REPO" "$(id -u)" "$mode" "$ISOLATED" \
    || die "configuration refused; nothing was started or changed"
}

running() { [ -n "$(compose ps --status running -q app 2> /dev/null)" ]; }

wait_healthy() {
  local id state
  id=$(compose ps -q app)
  for _ in $(seq 60); do
    state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2> /dev/null || echo unknown)
    [ "$state" = healthy ] && return 0
    sleep 1
  done
  echo "flh-daily: the service did not become healthy within 60 s (state: $state). See: bash scripts/daily/flh-daily.sh logs" >&2
  return 1
}

copy_db() { # copy_db FROM_DIR TO_DIR: app.db and present WAL/SHM sidecars only
  cp -a "$1/app.db" "$2/app.db"
  for suffix in -wal -shm; do
    if [ -e "$1/app.db$suffix" ]; then cp -a "$1/app.db$suffix" "$2/"; fi
  done
}
integrity_ok() { [ "$(sqlite3 -readonly "$1/app.db" 'PRAGMA integrity_check;')" = ok ]; }

case "$CMD" in
  check)
    validate summary
    ;;
  up)
    validate summary
    compose up -d --build
    wait_healthy
    port=$(validate port)
    echo "flh-daily: ready at http://127.0.0.1:$port/ — from another machine: ssh -N -L $port:127.0.0.1:$port <NAS_SSH_HOST>"
    ;;
  stop) compose stop ;;
  start) validate summary > /dev/null; compose start; wait_healthy ;;
  restart) validate summary > /dev/null; compose restart; wait_healthy ;;
  status) validate summary; compose ps ;;
  logs) shift; compose logs "$@" app ;;
  backup)
    command -v sqlite3 > /dev/null || die "missing prerequisite: sqlite3"
    command -v sha256sum > /dev/null || die "missing prerequisite: sha256sum"
    active=$(validate data)
    [ -f "$active/app.db" ] || die "no database yet at $active/app.db"
    umask 077
    backups="$active.backups"
    backup="$backups/flh-$(date -u +%Y%m%dT%H%M%SZ)"
    was_running=0
    if running; then was_running=1; fi
    compose stop
    mkdir -p "$backups"
    chmod 700 "$backups"
    mkdir -m 700 "$backup"
    copy_db "$active" "$backup"
    integrity_ok "$backup" || die "backup integrity check failed; the service is left stopped. Inspect $backup"
    (cd "$backup" && sha256sum app.db* > SHA256SUMS)
    echo "flh-daily: backup written to $backup (copy it off this machine too)"
    if [ "$was_running" = 1 ]; then compose start; wait_healthy; fi
    ;;
  restore)
    backup=${2:-}
    [ -n "$backup" ] || usage
    command -v sqlite3 > /dev/null || die "missing prerequisite: sqlite3"
    command -v sha256sum > /dev/null || die "missing prerequisite: sha256sum"
    backup=$(realpath "$backup")
    [ -f "$backup/app.db" ] && [ -f "$backup/SHA256SUMS" ] || die "not a backup made by this script: $backup"
    active=$(validate data)
    umask 077
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    stage="$active.restore-$stamp"
    old="$active.before-restore-$stamp"
    [ ! -e "$stage" ] && [ ! -e "$old" ] || die "restore staging paths already exist"
    compose stop
    (cd "$backup" && sha256sum --quiet -c SHA256SUMS) || die "backup checksums do not match; nothing was changed (the service is stopped)"
    mkdir -m 700 "$stage"
    copy_db "$backup" "$stage"
    integrity_ok "$stage" || die "restored copy failed the integrity check; nothing was changed. Inspect $stage"
    mv "$active" "$old"
    mv "$stage" "$active" || { mv "$old" "$active"; die "could not move the restored copy into place; the original was put back"; }
    echo "flh-daily: restored $backup into $active; the previous data is kept at $old"
    compose up -d --force-recreate
    wait_healthy
    ;;
  listening-pull)
    trigger=manual
    case "${2:-}" in
      "") ;;
      --scheduled) trigger=scheduled ;;
      *) usage ;;
    esac
    validate summary > /dev/null
    running || die "the service is not running; start it with: bash scripts/daily/flh-daily.sh up"
    # Exit status is the command's: 0 ok, 3 a step needs attention, 4 another
    # pull is running, 5 not configured, 1 error.
    compose exec -T app /app/listening-pull -trigger "$trigger"
    ;;
  listening-status)
    validate summary > /dev/null
    running || die "the service is not running; start it with: bash scripts/daily/flh-daily.sh up"
    compose exec -T app /app/listening-pull status
    ;;
  *) usage ;;
esac
