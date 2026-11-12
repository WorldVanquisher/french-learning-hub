#!/bin/bash
# Controlled-failure proof for browser_check.sh: run it with a deliberately
# failing check and assert that the failure is reported, evidence is retained,
# and only the run's own resources were removed.
#
#   bash scripts/validation/v1_rehearsal/failure_probe.sh WORK_DIR [PHASE] [browser_check options...]
#
# PHASE defaults to "sources" (after the explicit SAME, before the source
# records). Exit 0 only if browser_check.sh exited 1 AND:
# - results.json says failed with the injected check, the earlier phases passed;
# - the error screenshot and sanitized logs are in diagnostics/;
# - teardown passed and no container, tag or network of the project remains.
set -uo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd -P)
WORK=${1:?usage: failure_probe.sh WORK_DIR [PHASE] [browser_check options...]}
PHASE=${2:-sources}
shift; [ $# -gt 0 ] && shift
FAILED=0
ok() { if [ "$2" = "$3" ]; then echo "PASS	probe: $1"; else echo "FAIL	probe: $1 (got [$2] want [$3])"; FAILED=1; fi; }

bash "$REPO/scripts/validation/v1_rehearsal/browser_check.sh" "$WORK" --inject-failure "$PHASE" "$@" > "$WORK.log" 2>&1
RC=$?
tail -n 8 "$WORK.log"
[ "$RC" = 3 ] && { echo "BLOCKED	probe: no browser or no disk room, the probe did not run"; exit 3; }
ok "browser_check exits 1 on the injected failure" "$RC" 1
D="$WORK/diagnostics"
ok "results.json retained in diagnostics" "$([ -f "$D/results.json" ] && echo yes)" yes
ok "results.json reports the injected failure and nothing else failed" "$(python3 -I -c '
import json, sys
r = json.load(open(sys.argv[1])); phase = sys.argv[2]
fails = [c for c in r["checks"] if c["status"] != "PASS"]
before = r["phases"][: r["phases"].index(phase)]
print(r["status"] == "failed" and len(fails) == 1 and "injected failure" in fails[0]["name"]
      and fails[0]["phase"] == phase and all(p in r["phasesRun"] for p in before) and r["passed"] > 0)
' "$D/results.json" "$PHASE" 2> /dev/null)" True
ok "error screenshot retained" "$(ls "$D/screenshots" 2> /dev/null | grep -c -- '-error\.png$')" 1
ok "sanitized Compose logs retained" "$([ -s "$D/compose-logs.txt" ] && echo yes)" yes
ok "no key-like value in diagnostics" "$(grep -rlE 'placeholder-not-a-real-key|sk-[A-Za-z0-9_-]{8,}' "$D" | wc -l)" 0
ok "teardown passed" "$(grep -c '^PASS	teardown' "$WORK/summary.txt")" 1
PROJECT=$(cat "$WORK/instance/project" 2> /dev/null || echo unknown)
ok "no container of $PROJECT remains" "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" | wc -l)" 0
ok "no image tag of $PROJECT remains" "$(docker image ls -q "$PROJECT" | wc -l)" 0
ok "no network of $PROJECT remains" "$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT" | wc -l)" 0
ok "no browser container remains" "$(docker ps -aq --filter label=org.flh.task=v1-browser-smoke | wc -l)" 0
ok "daily instance unchanged (rehearse.sh down)" "$(grep -c '^PASS	daily instance unchanged' "$WORK/instance/evidence/results.tsv")" 1
[ $FAILED = 0 ] && echo "controlled failure: PASS (nonzero exit, evidence kept, own resources removed)" || echo "controlled failure: FAIL"
exit $FAILED
