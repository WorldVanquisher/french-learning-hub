#!/usr/bin/env bash
# Attempted writes against a running public demo (demo-candidate lane).
#
#   bash scripts/validation/demo_candidate/write_probe.sh BASE_URL OUT_FILE
#
# Sends well-formed writes that a normal server would accept (a capture, an
# entry, a Concept, a pin, a clear), at the root and under /api, and requires
# each to be refused with 405 before any handler runs. When the server is a
# demo, its artifact identity and preset counters must also be unchanged by
# the attempts. Exit 0: every write refused; 1: a write was not refused (named
# in OUT_FILE) or the demo changed; 2: usage. Synthetic payloads only; a server
# that wrongly accepts them writes only to its own database.
set -uo pipefail
BASE=${1:?usage: write_probe.sh BASE_URL OUT_FILE}; OUT=${2:?usage: write_probe.sh BASE_URL OUT_FILE}
BASE=${BASE%/}
case "$BASE" in http://127.0.0.1:*|http://localhost:*|http://\[::1\]:*) ;; *) echo "refused: loopback URLs only" >&2; exit 2 ;; esac
: > "$OUT"
FAILED=0
note() { echo "$*" | tee -a "$OUT"; }
demo() { curl -s --max-time 5 "$BASE/knowledge-library/demo" | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin); a=d["artifact"]; c=d["counters"]
    print(a["version"], a["manifest_sha256"], a["real_model"], c["preset_vector_lookups"], c["refused_vector_lookups"])
except Exception:
    print("no-demo")'; }
CAPTURE='{"schema_version":"learning_capture_v1","capture_id":"write-probe-0001","source":"manual","original_input":"Synthetic write probe.","original_context":"Must be refused by the public demo."}'
BEFORE=$(demo)
attempt() { # METHOD PATH [JSON]
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X "$1" -H 'Content-Type: application/json' \
    -H 'Idempotency-Key: 4b0c7c4e-6d1f-4c0e-9d7a-0000000000a1' ${3:+--data "$3"} "$BASE$2")
  if [ "$code" = 405 ]; then note "PASS refused $1 $2 -> 405"; else note "FAIL write not refused: $1 $2 -> $code"; FAILED=1; fi
}
for prefix in "" /api; do
  attempt POST "$prefix/captures" "$CAPTURE"
  attempt POST "$prefix/entries" '{"original_input":"Synthetic write probe.","original_context":""}'
  attempt POST "$prefix/concepts" '{"target":"write probe","pedagogical_intent":"grammar","scope":"","identity_features":{}}'
  attempt POST "$prefix/knowledge-library/concepts" '{}'
  attempt PUT "$prefix/entries/1/current-extraction" '{"extraction_id":1}'
  attempt DELETE "$prefix/entries/1/current-extraction"
  attempt PATCH "$prefix/knowledge-library/concepts/1" '{}'
done
AFTER=$(demo)
if [ "$BEFORE" = no-demo ] || [ "$AFTER" != "$BEFORE" ]; then
  note "FAIL demo identity/counters before and after the attempts: [$BEFORE] [$AFTER]"; FAILED=1
else
  note "PASS demo identity and counters unchanged: $AFTER"
fi
[ "$FAILED" = 0 ] && note "WRITE PROBE PASSED" || note "WRITE PROBE FAILED"
exit "$FAILED"
