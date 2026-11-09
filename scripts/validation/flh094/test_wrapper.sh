#!/bin/bash
# FLH-094 checks for scripts/daily/flh-daily.sh, without starting any container
# (plus the v1.0 rehearsal's opt-in isolated-project mode).
#
#   bash scripts/validation/flh094/test_wrapper.sh WORK_DIR
#
# A `docker` shim first on PATH passes only `docker compose ... config` to the
# real Docker CLI (read-only interpolation, no daemon state change) and records
# every other invocation instead of running it. Settings files, data and
# backups live in WORK_DIR (new/empty, outside the repository). The key is a
# placeholder; the check fails if it ever appears in any output.
set -uo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd -P)
WORK=${1:?usage: test_wrapper.sh WORK_DIR}
WORK=$(realpath -m "$WORK")
case "$WORK/" in "$REPO"/*) echo "refused: WORK_DIR must be outside the repository" >&2; exit 2 ;; esac
mkdir -p "$WORK"
[ -z "$(ls -A "$WORK")" ] || { echo "refused: WORK_DIR must be empty" >&2; exit 2; }
REAL_DOCKER=$(command -v docker) || { echo "refused: docker CLI required for compose config" >&2; exit 2; }
W="$REPO/scripts/daily/flh-daily.sh"
SECRET=placeholder-flh094-not-a-real-key
YT_SECRET=placeholder-youtube-not-a-real-key
TG_SECRET=123456:placeholder-telegram-not-a-real-token
failures=0
pass() { echo "PASS $1"; }
fail() { echo "FAIL $1"; failures=$((failures + 1)); }

mkdir -p "$WORK/bin" "$WORK/state"
cat > "$WORK/bin/docker" <<EOF
#!/bin/bash
echo "docker \$*" >> "$WORK/shim.log"
echo "  inherited AI_PROVIDER=\${AI_PROVIDER-<unset>} FLH_DATA_DIR=\${FLH_DATA_DIR-<unset>}" >> "$WORK/shim.log"
case " \$* " in
  *" config "*) exec "$REAL_DOCKER" "\$@" ;;
  *" ps --status running -q app "*) [ -f "$WORK/state/running" ] && echo fakeid; exit 0 ;;
  *" ps -q app "*) echo fakeid; exit 0 ;;
  " inspect "*) echo healthy; exit 0 ;;
  *" stop "*) rm -f "$WORK/state/running"; exit 0 ;;
  *" up "*|*" start "*|*" restart "*) touch "$WORK/state/running"; exit 0 ;;
  *" exec "*) exit "\$(cat "$WORK/state/pull_rc" 2> /dev/null || echo 0)" ;;
  *) exit 0 ;;
esac
EOF
chmod 755 "$WORK/bin/docker"
export PATH="$WORK/bin:$PATH"

DATA="$WORK/daily-data"
mkdir -m 700 "$DATA"
good() { # good FILE [extra lines]: a complete, valid settings file
  {
    echo "FLH_DATA_DIR=$DATA"
    echo "FLH_UID=$(id -u)"
    echo "FLH_GID=$(id -g)"
    echo "FLH_HOST_PORT=18094"
    echo "AI_PROVIDER=openai"
    echo "EXTRACTOR_PROVIDER=openai"
    echo "OPENAI_MODEL=owner-chosen-model-placeholder"
    echo "OPENAI_API_KEY='$SECRET'"
    echo "OPENAI_TIMEOUT=60"
    echo "HTTP_WRITE_TIMEOUT=75"
  } > "$1"
  chmod 600 "$1"
}
run() { # run NAME EXPECT_RC PATTERN SETTINGS [args...]
  local name=$1 want=$2 pattern=$3 env=$4; shift 4
  local out rc
  out=$(FLH_DAILY_ENV="$env" bash "$W" "$@" 2>&1); rc=$?
  echo "$out" >> "$WORK/outputs.log"
  if [ "$rc" = "$want" ] && grep -qE -- "$pattern" <<< "$out"; then pass "$name"; else fail "$name (rc=$rc) :: $(head -c 400 <<< "$out")"; fi
}

# ---- Refusals: nothing is started. ----
run "missing settings file is refused" 2 "settings file not found" "$WORK/none.env" check
good "$WORK/open.env"; chmod 644 "$WORK/open.env"
run "a settings file readable by others is refused" 2 "readable by others" "$WORK/open.env" check
good "$WORK/implicit.env"; sed -i '/^AI_PROVIDER=/d' "$WORK/implicit.env"
run "an implicit (unset) analyzer provider is refused" 2 "AI_PROVIDER must be stated explicitly" "$WORK/implicit.env" check
good "$WORK/nokey.env"; sed -i '/^OPENAI_API_KEY=/d' "$WORK/nokey.env"
run "a real provider without a key is refused" 2 "OPENAI_API_KEY must be set" "$WORK/nokey.env" check
good "$WORK/nomodel.env"; sed -i '/^OPENAI_MODEL=/d' "$WORK/nomodel.env"
run "a real provider without a model is refused" 2 "OPENAI_MODEL must be set" "$WORK/nomodel.env" check
good "$WORK/nodata.env"; sed -i '/^FLH_DATA_DIR=/d' "$WORK/nodata.env"
run "a missing FLH_DATA_DIR is refused (no ./data/release default)" 2 "FLH_DATA_DIR must be set" "$WORK/nodata.env" check
good "$WORK/absent.env"; sed -i "s|^FLH_DATA_DIR=.*|FLH_DATA_DIR=$WORK/absent-dir|" "$WORK/absent.env"
run "a non-existent data directory is refused" 2 "does not exist" "$WORK/absent.env" check
mkdir -m 755 "$WORK/open-data"
good "$WORK/opendata.env"; sed -i "s|^FLH_DATA_DIR=.*|FLH_DATA_DIR=$WORK/open-data|" "$WORK/opendata.env"
run "a data directory readable by others is refused" 2 "must be private" "$WORK/opendata.env" check
mkdir -m 700 "$WORK/acceptance"; touch "$WORK/acceptance/flh092-session" "$WORK/acceptance/fixture.db"
good "$WORK/accept.env"; sed -i "s|^FLH_DATA_DIR=.*|FLH_DATA_DIR=$WORK/acceptance|" "$WORK/accept.env"
run "an acceptance-session directory is refused as daily data" 2 "disposable acceptance" "$WORK/accept.env" check
good "$WORK/timeouts.env"; sed -i 's/^OPENAI_TIMEOUT=.*/OPENAI_TIMEOUT=80/' "$WORK/timeouts.env"
run "a provider timeout not below the write timeout is refused" 2 "must be below HTTP_WRITE_TIMEOUT" "$WORK/timeouts.env" check
good "$WORK/defaults.env"; sed -i '/^OPENAI_TIMEOUT=/d; /^HTTP_WRITE_TIMEOUT=/d' "$WORK/defaults.env"
run "the default timeouts (8 s < 10 s) are accepted" 0 "provider 8s < write 10s" "$WORK/defaults.env" check
good "$WORK/local.env"; sed -i 's/^AI_PROVIDER=.*/AI_PROVIDER=rule-based/; s/^EXTRACTOR_PROVIDER=.*/EXTRACTOR_PROVIDER=disabled/; /^OPENAI_/d' "$WORK/local.env"
run "explicitly local providers are accepted and labelled" 0 "analysis:   rule-based — local" "$WORK/local.env" check
# FLH-097: SUGGESTION_PROVIDER accepts only disabled or openai, and openai needs
# the same key and model as the other providers.
good "$WORK/badsuggest.env"; echo "SUGGESTION_PROVIDER=anthropic" >> "$WORK/badsuggest.env"
run "an unknown suggestion provider is refused" 2 "SUGGESTION_PROVIDER must be openai or disabled" "$WORK/badsuggest.env" check
good "$WORK/badsuggest-up.env"; echo "SUGGESTION_PROVIDER=anthropic" >> "$WORK/badsuggest-up.env"
run "up with an unknown suggestion provider is refused" 2 "SUGGESTION_PROVIDER must be openai or disabled" "$WORK/badsuggest-up.env" up
good "$WORK/suggestnokey.env"
sed -i 's/^AI_PROVIDER=.*/AI_PROVIDER=rule-based/; s/^EXTRACTOR_PROVIDER=.*/EXTRACTOR_PROVIDER=disabled/; /^OPENAI_API_KEY=/d' "$WORK/suggestnokey.env"
echo "SUGGESTION_PROVIDER=openai" >> "$WORK/suggestnokey.env"
run "openai suggestions alone still require the key" 2 "OPENAI_API_KEY must be set" "$WORK/suggestnokey.env" check
if grep -q "^docker compose .* \(up\|start\|stop\|restart\)" "$WORK/shim.log" 2> /dev/null; then fail "refusals started or stopped nothing"; else pass "refusals started or stopped nothing"; fi
run "suggestions default to disabled when unset" 0 "suggestions: disabled — off" "$WORK/defaults.env" check
good "$WORK/suggestoff.env"; echo "SUGGESTION_PROVIDER=disabled" >> "$WORK/suggestoff.env"
run "explicitly disabled suggestions are accepted" 0 "suggestions: disabled — off" "$WORK/suggestoff.env" check
good "$WORK/suggeston.env"; echo "SUGGESTION_PROVIDER=openai" >> "$WORK/suggeston.env"
run "openai suggestions are accepted and labelled as billable" 0 "suggestions: openai — explicit requests call the provider" "$WORK/suggeston.env" check
# Listening v1: LISTENING_PROVIDER follows the same rules as SUGGESTION_PROVIDER.
good "$WORK/badlisten.env"; echo "LISTENING_PROVIDER=anthropic" >> "$WORK/badlisten.env"
run "an unknown listening provider is refused" 2 "LISTENING_PROVIDER must be openai or disabled" "$WORK/badlisten.env" check
good "$WORK/listennokey.env"
sed -i 's/^AI_PROVIDER=.*/AI_PROVIDER=rule-based/; s/^EXTRACTOR_PROVIDER=.*/EXTRACTOR_PROVIDER=disabled/; /^OPENAI_API_KEY=/d' "$WORK/listennokey.env"
echo "LISTENING_PROVIDER=openai" >> "$WORK/listennokey.env"
run "openai listening alone still requires the key" 2 "OPENAI_API_KEY must be set" "$WORK/listennokey.env" check
run "listening defaults to disabled when unset" 0 "listening:  disabled — off" "$WORK/defaults.env" check
good "$WORK/listenon.env"; echo "LISTENING_PROVIDER=openai" >> "$WORK/listenon.env"
run "openai listening is accepted and labelled as billable" 0 "listening:  openai — explicit requests call the provider" "$WORK/listenon.env" check
# Reading v1: READING_PROVIDER follows the same rules as LISTENING_PROVIDER.
good "$WORK/badread.env"; echo "READING_PROVIDER=anthropic" >> "$WORK/badread.env"
run "an unknown reading provider is refused" 2 "READING_PROVIDER must be openai or disabled" "$WORK/badread.env" check
good "$WORK/readnokey.env"
sed -i 's/^AI_PROVIDER=.*/AI_PROVIDER=rule-based/; s/^EXTRACTOR_PROVIDER=.*/EXTRACTOR_PROVIDER=disabled/; /^OPENAI_API_KEY=/d' "$WORK/readnokey.env"
echo "READING_PROVIDER=openai" >> "$WORK/readnokey.env"
run "openai reading alone still requires the key" 2 "OPENAI_API_KEY must be set" "$WORK/readnokey.env" check
run "reading defaults to disabled when unset" 0 "reading:    disabled — off \\(authored examples still work\\)" "$WORK/defaults.env" check
good "$WORK/readon.env"; echo "READING_PROVIDER=openai" >> "$WORK/readon.env"
run "openai reading is accepted and labelled as billable" 0 "reading:    openai — explicit requests call the provider" "$WORK/readon.env" check
# Daily Listening: every part off by default; each enabled part needs its settings.
daily() { # daily FILE: a valid settings file with every Daily Listening part on
  good "$1"
  {
    echo "LISTENING_PROVIDER=openai"
    echo "LISTENING_PLAYLIST_SOURCE=youtube"
    echo "LISTENING_PLAYLIST_ID=PLflh094WrapperTest"
    echo "YOUTUBE_API_KEY='$YT_SECRET'"
    echo "LISTENING_AUTO_PREPARE=daily"
    echo "LISTENING_TIMEZONE=Europe/Paris"
    echo "LISTENING_NOTIFY=telegram"
    echo "TELEGRAM_BOT_TOKEN='$TG_SECRET'"
    echo "TELEGRAM_CHAT_ID=-1001234567890"
  } >> "$1"
}
run "daily listening is off by default" 0 "daily listening: off" "$WORK/defaults.env" check
daily "$WORK/dailyon.env"
run "a full daily listening configuration is accepted and labelled" 0 "daily preparation: daily — at most 1 lesson per day \(Europe/Paris\); a pull calls the provider and may be billed" "$WORK/dailyon.env" check
run "the daily notifier is labelled without values" 0 "daily notify: telegram \(TELEGRAM_BOT_TOKEN set · TELEGRAM_CHAT_ID set\)" "$WORK/dailyon.env" check
daily "$WORK/badsource.env"; sed -i 's/^LISTENING_PLAYLIST_SOURCE=.*/LISTENING_PLAYLIST_SOURCE=rss/' "$WORK/badsource.env"
run "an unknown playlist source is refused" 2 "LISTENING_PLAYLIST_SOURCE must be youtube or disabled" "$WORK/badsource.env" check
daily "$WORK/noytkey.env"; sed -i '/^YOUTUBE_API_KEY=/d' "$WORK/noytkey.env"
run "a playlist source without its key is refused" 2 "needs YOUTUBE_API_KEY" "$WORK/noytkey.env" check
daily "$WORK/noplaylist.env"; sed -i '/^LISTENING_PLAYLIST_ID=/d' "$WORK/noplaylist.env"
run "a playlist source without a playlist is refused" 2 "needs LISTENING_PLAYLIST_ID" "$WORK/noplaylist.env" check
daily "$WORK/autonogen.env"; sed -i 's/^LISTENING_PROVIDER=.*/LISTENING_PROVIDER=disabled/' "$WORK/autonogen.env"
run "automatic preparation without the generator is refused" 2 "LISTENING_AUTO_PREPARE=daily needs LISTENING_PROVIDER=openai" "$WORK/autonogen.env" check
daily "$WORK/notifyonly.env"; sed -i 's/^LISTENING_AUTO_PREPARE=.*/LISTENING_AUTO_PREPARE=disabled/' "$WORK/notifyonly.env"
run "a notifier without automatic preparation is refused" 2 "LISTENING_NOTIFY=telegram needs LISTENING_AUTO_PREPARE=daily" "$WORK/notifyonly.env" check
daily "$WORK/notoken.env"; sed -i '/^TELEGRAM_BOT_TOKEN=/d' "$WORK/notoken.env"
run "a notifier without its token is refused" 2 "needs TELEGRAM_BOT_TOKEN" "$WORK/notoken.env" check
daily "$WORK/badtz.env"; sed -i 's/^LISTENING_TIMEZONE=.*/LISTENING_TIMEZONE=Paris time/' "$WORK/badtz.env"
run "a malformed timezone is refused" 2 "LISTENING_TIMEZONE must be an IANA time zone name" "$WORK/badtz.env" check

# ---- A valid configuration; inherited shell variables must not override it. ----
good "$WORK/daily.env"
out=$(AI_PROVIDER=rule-based EXTRACTOR_PROVIDER=disabled FLH_DATA_DIR=/tmp/elsewhere OPENAI_MODEL=wrong \
  FLH_DAILY_ENV="$WORK/daily.env" bash "$W" check 2>&1); rc=$?
echo "$out" >> "$WORK/outputs.log"
if [ $rc = 0 ] && grep -q "analysis:   openai" <<< "$out" && grep -q "extraction: openai" <<< "$out" && grep -q "database:   $DATA/app.db" <<< "$out"; then
  pass "shell exports cannot override the settings file (providers and database)"
else fail "shell exports cannot override the settings file :: $out"; fi
grep -q "inherited AI_PROVIDER=<unset> FLH_DATA_DIR=<unset>" "$WORK/shim.log" && pass "docker never sees the inherited provider or data variables" || fail "docker saw inherited variables"
echo "$out" | sed 's/^/    /'

: > "$WORK/shim.log"
run "up builds and starts with the settings file, then prints the loopback URL and tunnel" 0 "ssh -N -L 18094:127.0.0.1:18094" "$WORK/daily.env" up
grep -q "^docker compose --env-file $WORK/daily.env up -d --build" "$WORK/shim.log" && pass "up runs 'docker compose --env-file <settings> up -d --build'" || fail "up command line"

# ---- Backup and restore on a real SQLite file. ----
sqlite3 "$DATA/app.db" "CREATE TABLE t(v TEXT); INSERT INTO t VALUES ('avant');"
: > "$WORK/shim.log"
run "backup writes a verified copy" 0 "backup written to" "$WORK/daily.env" backup
backup=$(ls -d "$DATA.backups"/flh-* 2> /dev/null | head -1)
if [ -n "$backup" ] && (cd "$backup" && sha256sum --quiet -c SHA256SUMS) && [ "$(sqlite3 -readonly "$backup/app.db" 'SELECT v FROM t')" = avant ] \
  && [ "$(stat -c %a "$backup")" = 700 ]; then pass "the backup has the data, a valid SHA256SUMS and mode 700"; else fail "backup contents"; fi
grep -qE "compose --env-file .* stop" "$WORK/shim.log" && grep -qE "compose --env-file .* start" "$WORK/shim.log" \
  && pass "backup stops the running service and starts it again" || fail "backup stop/start"
sqlite3 "$DATA/app.db" "UPDATE t SET v = 'après';"
cp -a "$backup" "$WORK/tampered"; echo x >> "$WORK/tampered/app.db"
run "a backup whose checksum does not match is refused" 2 "checksums do not match" "$WORK/daily.env" restore "$WORK/tampered"
[ "$(sqlite3 -readonly "$DATA/app.db" 'SELECT v FROM t')" = après ] && pass "a refused restore leaves the active data untouched" || fail "active data changed by a refused restore"
: > "$WORK/shim.log"
run "restore puts the backup in place" 0 "previous data is kept" "$WORK/daily.env" restore "$backup"
old=$(ls -d "$DATA".before-restore-* 2> /dev/null | head -1)
[ "$(sqlite3 -readonly "$DATA/app.db" 'SELECT v FROM t')" = avant ] && [ -n "$old" ] && [ "$(sqlite3 -readonly "$old/app.db" 'SELECT v FROM t')" = après ] \
  && pass "restored data is active and the previous data is preserved" || fail "restore result"
grep -q "^docker compose --env-file $WORK/daily.env up -d --force-recreate" "$WORK/shim.log" \
  && pass "restore recreates the container with the same settings file" || fail "restore recreate command"

# ---- v1.0 rehearsal: opt-in isolated project (FLH_COMPOSE_PROJECT + FLH_COMPOSE_OVERRIDE). ----
grep -q "^docker compose -p\|^docker compose -f" "$WORK/shim.log" && fail "normal mode passes no -p/-f" || pass "normal mode passes no -p/-f (invocation unchanged)"
printf 'services:\n  app:\n    image: flh-rehearsal-test:app\n' > "$WORK/iso.yaml"
printf 'services:\n  app:\n    user: "1000:1000"\n' > "$WORK/noimage.yaml"
iso() { # iso NAME EXPECT_RC PATTERN PROJECT OVERRIDE args...
  local name=$1 want=$2 pattern=$3 project=$4 override=$5; shift 5
  local out rc
  out=$(FLH_COMPOSE_PROJECT="$project" FLH_COMPOSE_OVERRIDE="$override" FLH_DAILY_ENV="$WORK/daily.env" bash "$W" "$@" 2>&1); rc=$?
  echo "$out" >> "$WORK/outputs.log"
  if [ "$rc" = "$want" ] && grep -qE -- "$pattern" <<< "$out"; then pass "$name"; else fail "$name (rc=$rc) :: $(head -c 400 <<< "$out")"; fi
}
: > "$WORK/shim.log"
iso "isolated mode needs both variables (project only)" 2 "needs both" flh-rehearsal-test "" check
iso "isolated mode needs both variables (override only)" 2 "needs both" "" "$WORK/iso.yaml" check
iso "isolated mode refuses the daily project name" 2 "must not be the daily project" french-learning-hub "$WORK/iso.yaml" check
iso "isolated mode refuses an invalid project name" 2 "Compose project name" "Bad Name" "$WORK/iso.yaml" check
iso "isolated mode refuses an override that keeps the daily image" 2 "image name other than french-learning-hub" flh-rehearsal-test "$WORK/noimage.yaml" up
if grep -q " up \| stop \| start " "$WORK/shim.log" 2> /dev/null; then fail "isolated refusals started or stopped nothing"; else pass "isolated refusals started or stopped nothing"; fi
iso "isolated mode reports its project and image" 0 "project:    flh-rehearsal-test \(isolated rehearsal; image flh-rehearsal-test:app\)" flh-rehearsal-test "$WORK/iso.yaml" up
grep -q "^docker compose -p flh-rehearsal-test -f $REPO/compose.yaml -f $WORK/iso.yaml --env-file $WORK/daily.env up -d --build" "$WORK/shim.log" \
  && pass "isolated up runs 'docker compose -p <project> -f compose.yaml -f <override> --env-file <settings> up -d --build'" || fail "isolated up command line"
: > "$WORK/shim.log"
run "normal up after isolated runs is unchanged" 0 "ready at" "$WORK/daily.env" up
grep -q "^docker compose --env-file $WORK/daily.env up -d --build" "$WORK/shim.log" && ! grep -q -- " -p " "$WORK/shim.log" \
  && pass "normal up still runs 'docker compose --env-file <settings> up -d --build'" || fail "normal up changed"

# ---- Daily Listening pull: only inside the running container, never started here. ----
rm -f "$WORK/state/running"; : > "$WORK/shim.log"
run "listening-pull refuses when the service is not running" 2 "the service is not running" "$WORK/dailyon.env" listening-pull
grep -q " exec " "$WORK/shim.log" && fail "a refused listening-pull ran nothing" || pass "a refused listening-pull ran nothing"
touch "$WORK/state/running"
run "listening-pull refuses an unknown argument" 2 "usage" "$WORK/dailyon.env" listening-pull --hourly
echo 3 > "$WORK/state/pull_rc"
run "listening-pull --scheduled passes the command's exit status through" 3 "" "$WORK/dailyon.env" listening-pull --scheduled
grep -q "^docker compose --env-file $WORK/dailyon.env exec -T app /app/listening-pull -trigger scheduled" "$WORK/shim.log" \
  && pass "listening-pull runs 'docker compose --env-file <settings> exec -T app /app/listening-pull -trigger scheduled'" || fail "listening-pull command line"
echo 0 > "$WORK/state/pull_rc"; : > "$WORK/shim.log"
run "listening-pull without --scheduled is a manual pull" 0 "" "$WORK/dailyon.env" listening-pull
grep -q "exec -T app /app/listening-pull -trigger manual" "$WORK/shim.log" && pass "a manual pull is labelled manual" || fail "manual trigger"
run "listening-status reads the last pull" 0 "" "$WORK/dailyon.env" listening-status
grep -q "exec -T app /app/listening-pull status" "$WORK/shim.log" && pass "listening-status runs the read-only status" || fail "listening-status command line"
grep -qE " (up|start|stop|restart|enable|systemctl)( |$)" "$WORK/shim.log" && fail "listening-pull starts, stops or enables nothing" || pass "listening-pull starts, stops or enables nothing"

# ---- Secrets ----
if grep -rq -e "$SECRET" -e "$YT_SECRET" -e "$TG_SECRET" "$WORK/outputs.log" "$WORK/shim.log"; then fail "the keys never appear in output"; else pass "the keys and the bot token never appear in output or in docker command lines"; fi

echo "{\"failures\": $failures}"
exit $((failures > 0))
