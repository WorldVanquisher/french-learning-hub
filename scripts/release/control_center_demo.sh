#!/bin/bash
# The release control center in about 90 seconds, from a clean checkout (offline: no Docker, no AWS,
# no network; synthetic data only; writes only under OUT_DIR, which must not exist).
#
#   bash scripts/release/control_center_demo.sh OUT_DIR
#
# 1 the dashboard from the shipped fixture (check, terminal, HTML, Markdown)
# 2 the staging preflight (repository checks) and plan review (summary, diff, cost)
# 3 a synthetic backup: inspect, pack, a truncated copy refused as DAMAGED
# 4 a synthetic cutover rolled back after target writes: ROLLBACK-B with the discard warning
# 5 the startup diagnosis on the synthetic data
# 6 the Python suites, hermetic
# Each step prints its time; the run fails at the first step whose result is not the expected one.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:?usage: control_center_demo.sh OUT_DIR}
[ ! -e "$OUT" ] || { echo "refused: $OUT exists" >&2; exit 2; }
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
export TMPDIR="$OUT/tmp"; mkdir -p "$TMPDIR"
PY="python3 -I -B"; S="$REPO/deploy/aws/private-staging/staging"; T0=$(date +%s%N)
ms() { echo $(( ($(date +%s%N) - $1) / 1000000 )); }
step() { # step NAME EXPECTED_EXIT COMMAND...: run, keep the output, check the exit status
  local name=$1 want=$2 t rc; shift 2; t=$(date +%s%N)
  set +e; "$@" > "$OUT/$name.txt" 2>&1; rc=$?; set -e
  printf '%-28s exit %-2s %6s ms  %s\n' "$name" "$rc" "$(ms "$t")" "$(tail -1 "$OUT/$name.txt" | cut -c1-90)"
  [ "$rc" = "$want" ] || { echo "FAILED: $name exited $rc, expected $want (see $OUT/$name.txt)" >&2; exit 1; }
}
F="$REPO/scripts/release/fixtures/release-report/ready/report.json"
step 1-dashboard-check 0 $PY "$REPO/scripts/release/release_report.py" check "$F"
step 1-dashboard-terminal 0 $PY "$REPO/scripts/release/release_report.py" terminal "$F"
step 1-dashboard-html 0 $PY "$REPO/scripts/release/release_report.py" html "$F" --out "$OUT/dashboard.html"
step 1-dashboard-markdown 0 $PY "$REPO/scripts/release/release_report.py" markdown "$F" --out "$OUT/dashboard.md"
step 2-preflight 0 $PY "$S/tools/preflight.py"
step 2-plan-summary 0 $PY "$S/tools/plan_review.py" summary "$S/tests/fixtures/plan-unsafe-replace-data-volume.json"
step 2-plan-diff 1 $PY "$S/tools/plan_review.py" diff "$S/tests/fixtures/plan-create-safe.json" "$S/tests/fixtures/plan-unsafe-unexpected-resources.json"
step 2-plan-cost 0 $PY "$S/tools/plan_review.py" cost "$S/tests/fixtures/plan-create-safe.json"
# 3: a synthetic backup made the way flh-daily.sh seals one (app.db, sidecars, SHA256SUMS)
python3 -I - "$OUT" "$REPO/migrations" <<'PY'
import hashlib, os, sqlite3, sys
out, mig = sys.argv[1], sys.argv[2]
for name, rows in (("data/app", 3), ("data/app.backups/flh-20261119T000000Z", 3), ("aws/app", 5)):
    d = os.path.join(out, name); os.makedirs(d, mode=0o700)
    con = sqlite3.connect(os.path.join(d, "app.db"))
    con.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY)")
    con.executemany("INSERT INTO schema_migrations VALUES (?)", [(m,) for m in sorted(os.listdir(mig)) if m.endswith(".sql")])
    con.execute("CREATE TABLE learning_entries (id INTEGER PRIMARY KEY, original_input TEXT)")
    con.executemany("INSERT INTO learning_entries (original_input) VALUES (?)", [(f"FIXTURE-SYNTHETIC {i}",) for i in range(rows)])
    con.commit(); con.close(); os.chmod(os.path.join(d, "app.db"), 0o600)
    with open(os.path.join(d, "SHA256SUMS"), "w") as fh:
        fh.write(hashlib.sha256(open(os.path.join(d, "app.db"), "rb").read()).hexdigest() + "  app.db\n")
PY
B="$OUT/data/app.backups/flh-20261119T000000Z"
step 3-backup-inspect 0 $PY "$REPO/scripts/release/backup_tool.py" inspect "$B"
step 3-backup-pack 0 $PY "$REPO/scripts/release/backup_tool.py" pack "$B" "$OUT/backup.tar.gz"
head -c 600 "$OUT/backup.tar.gz" > "$OUT/truncated.tar.gz"; mkdir -p "$OUT/unpack"
step 3-backup-truncated 1 $PY "$REPO/scripts/release/backup_tool.py" unpack "$OUT/truncated.tar.gz" --sha256 "$(sha256sum "$OUT/truncated.tar.gz" | cut -d' ' -f1)" "$OUT/unpack"
grep -q DAMAGED "$OUT/3-backup-truncated.txt"
# 4: the cutover evidence of a switch followed by writes on the target
CC="$REPO/scripts/release/cutover_check.py"; EV="$OUT/cutover.jsonl"; : > "$OUT/sent.tar"
$PY "$CC" record "$EV" --step C1-aws-empty --host aws --db "$OUT/aws-empty/app.db" > /dev/null
$PY "$CC" record "$EV" --step C2-boundary --host nas --db "$OUT/data/app/app.db" > /dev/null
$PY "$CC" record "$EV" --step C3-backup --host nas --db "$B/app.db" > /dev/null
$PY "$CC" record "$EV" --step C4-sent --host nas --file "$OUT/sent.tar" > /dev/null
$PY "$CC" record "$EV" --step C4-received --host aws --file "$OUT/sent.tar" > /dev/null
$PY "$CC" record "$EV" --step C7-switch --host client > /dev/null
$PY "$CC" record "$EV" --step A-check --host aws --db "$OUT/aws/app/app.db" > /dev/null
step 4-cutover-check 1 $PY "$CC" check "$EV"
grep -q "WARNING: restarting the NAS now would discard 2 new row(s)" "$OUT/4-cutover-check.txt"
step 5-diagnose 0 $PY "$REPO/scripts/release/diagnose.py" --data "$OUT/data/app" --port 1 --running --uid "$(id -u)" --gid "$(id -g)"
step 6-python-suites 0 python3 -B "$REPO/scripts/ci/python_suites.py" --hermetic --json "$OUT/python-suites.json"
echo "done in $(( $(ms "$T0") / 1000 )) s. Open $OUT/dashboard.html"
