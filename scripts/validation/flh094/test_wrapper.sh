#!/bin/bash
# FLH-094 checks for scripts/daily/flh-daily.sh, without starting any container.
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
if grep -q "^docker compose .* \(up\|start\|stop\|restart\)" "$WORK/shim.log" 2> /dev/null; then fail "refusals started or stopped nothing"; else pass "refusals started or stopped nothing"; fi

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

# ---- Secrets ----
if grep -rq "$SECRET" "$WORK/outputs.log" "$WORK/shim.log"; then fail "the key never appears in output"; else pass "the key never appears in output or in docker command lines"; fi

echo "{\"failures\": $failures}"
exit $((failures > 0))
