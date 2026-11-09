#!/bin/bash
# Capture batch import acceptance against a real FLH server.
#
#   bash scripts/validation/capture_batch/run.sh WORK_DIR
#
# WORK_DIR must not exist (or be empty) and must be outside the repository.
# Builds cmd/server and cmd/capture from this checkout, starts the server on
# 127.0.0.1 with a disposable SQLite database (rule-based analyzer, every
# provider disabled: no model call), puts lossy_proxy.py in front of it, and
# drives one mixed batch through the real CLI binary:
#   new records, an identical replay, a conflict under an existing capture_id,
#   server-invalid input (wrong schema_version, not JSON), a locally invalid
#   file (missing), and a response lost after commit;
# then reruns the same files and checks that the lost one is a replay and that
# no record was duplicated. It also checks that -preview sends no request, that
# an unreachable server stops the batch with not_attempted files, and that
# SIGINT leaves the in-flight file unconfirmed and the rest not attempted.
# Run it under `unshare -rn` (loopback only) when available. Results:
# WORK_DIR/results.tsv; exit 0 only if every check passed.
set -uo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd -P)
H="$REPO/scripts/validation/capture_batch"
WORK=${1:?usage: run.sh WORK_DIR}
case "$(realpath -m "$WORK")/" in "$REPO"/*) echo "WORK_DIR must be outside the repository" >&2; exit 2 ;; esac
if [ -e "$WORK" ] && [ -n "$(ls -A "$WORK")" ]; then echo "WORK_DIR must be empty" >&2; exit 2; fi
mkdir -p "$WORK"/{bin,captures,out}
WORK=$(cd "$WORK" && pwd -P)
SPORT=${CAPTURE_BATCH_SERVER_PORT:-18997}
PPORT=${CAPTURE_BATCH_PROXY_PORT:-18998}
SERVER="http://127.0.0.1:$SPORT"
PROXY="http://127.0.0.1:$PPORT"
RES="$WORK/results.tsv"; : > "$RES"
FAILED=0
pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2> /dev/null; done; wait 2> /dev/null; }
trap cleanup EXIT
check() { # name got want
  if [ "$2" = "$3" ]; then printf 'PASS\t%s\n' "$1" | tee -a "$RES"
  else printf 'FAIL\t%s (got [%s] want [%s])\n' "$1" "$2" "$3" | tee -a "$RES"; FAILED=1; fi
}
port_free() { ! (exec 3<> "/dev/tcp/127.0.0.1/$1") 2> /dev/null; }
entries() { curl -fsS "$SERVER/learning-records?limit=200" | python3 -I -c 'import json,sys; print(len(json.load(sys.stdin)["records"]))'; }
outcome() { grep -E "^\[[0-9]+/[0-9]+\] [a-z_]+ +[^ ]*/$2 " "$1" | awk '{print $2}'; }

# 1. Build from this checkout, offline.
export GOFLAGS=-mod=readonly GOTOOLCHAIN=local GOPROXY=off
(cd "$REPO" && go build -o "$WORK/bin/server" ./cmd/server && go build -o "$WORK/bin/capture" ./cmd/capture) > "$WORK/out/build.log" 2>&1
check "build server and capture" "$?" 0
port_free "$SPORT" && port_free "$PPORT"; check "ports $SPORT/$PPORT free" "$?" 0
[ "$FAILED" = 0 ] || exit 1

# 2. Real server: disposable DB, loopback only, every provider off, empty cwd (no .env).
(cd "$WORK" && exec env -i PATH=/usr/bin:/bin DB_PATH="$WORK/hub.db" PORT="$SPORT" LISTEN_HOST=127.0.0.1 \
  AI_PROVIDER=rule-based EXTRACTOR_PROVIDER=disabled SUGGESTION_PROVIDER=disabled EMBEDDING_PROVIDER=disabled \
  "$WORK/bin/server") > "$WORK/out/server.log" 2>&1 &
pids+=($!)
for _ in $(seq 50); do curl -fsS "$SERVER/readyz" > /dev/null 2>&1 && break; sleep 0.2; done
check "server ready on 127.0.0.1:$SPORT" "$(curl -fsS "$SERVER/readyz")" '{"status":"ready"}'
python3 -I -B "$H/lossy_proxy.py" --port "$PPORT" --upstream "$SERVER" --drop-id batch-lost --log "$WORK/proxy.log" > "$WORK/out/proxy.err" 2>&1 &
pids+=($!)
for _ in $(seq 50); do port_free "$PPORT" || break; sleep 0.1; done
: > "$WORK/proxy.log"

# 3. Fixtures. Learner text carries a marker that no report may contain.
C="$WORK/captures"
cap() { printf '{"schema_version":"%s","capture_id":"%s","source":"manual","original_input":"%s","original_context":"MARKER-LEARNER-TEXT batch acceptance"}' "$1" "$2" "$3" > "$C/$4"; }
cap learning_capture_v1 batch-pre "J'en veux deux." 00-pre.json
cap learning_capture_v1 batch-new-1 "Pourquoi « en » ici ?" 01-new.json
cp "$C/00-pre.json" "$C/02-replay.json"
cap learning_capture_v1 batch-pre "Different words, same id." 03-conflict.json
cap learning_capture_v1 batch-lost "Où mettre « y » ?" 04-lost.json
cap learning_capture_v9 batch-bad "Mauvais schéma." 05-invalid-schema.json
cap learning_capture_v1 batch-new-2 "Faut-il le subjonctif ?" 07-new.json
printf 'this is not json MARKER-LEARNER-TEXT' > "$C/08-not-json.json"
BATCH=("$C/01-new.json" "$C/02-replay.json" "$C/03-conflict.json" "$C/04-lost.json" "$C/05-invalid-schema.json" "$C/06-missing.json" "$C/07-new.json" "$C/08-not-json.json")

# 4. Existing single-file mode, unchanged, directly to the server.
"$WORK/bin/capture" -url "$SERVER" -file "$C/00-pre.json" > "$WORK/out/single.txt" 2>&1
check "single-file import exit 0" "$?" 0
check "single-file output unchanged" "$(head -1 "$WORK/out/single.txt")" "capture stored (new)"
check "entries after single import" "$(entries)" 1

# 5. Preview through the proxy: no request at all.
"$WORK/bin/capture" -url "$PROXY" -batch -preview "${BATCH[@]}" > "$WORK/out/preview.txt" 2>&1
check "preview exit 1 (one locally invalid file)" "$?" 1
check "preview sent no request (proxy log empty)" "$(wc -l < "$WORK/proxy.log")" 0
check "preview summary" "$(grep '^summary:' "$WORK/out/preview.txt")" "summary: total=8 ready=7 invalid=1"
check "preview wrote nothing" "$(entries)" 1

# 6. The mixed batch through the lossy proxy.
"$WORK/bin/capture" -url "$PROXY" -batch "${BATCH[@]}" > "$WORK/out/batch1.txt" 2>&1
check "batch exit 3 (an unconfirmed file)" "$?" 3
for pair in 01-new.json:created 02-replay.json:replayed 03-conflict.json:conflict 04-lost.json:unconfirmed \
            05-invalid-schema.json:invalid 06-missing.json:invalid 07-new.json:created 08-not-json.json:invalid; do
  f=${pair%%:*}; check "batch $f" "$(outcome "$WORK/out/batch1.txt" "$f")" "${pair#*:}"
done
check "batch summary" "$(grep '^summary:' "$WORK/out/batch1.txt")" \
  "summary: total=8 created=2 replayed=1 conflict=1 invalid=3 unconfirmed=1 not_attempted=0"
check "proxy dropped exactly the lost response after commit" "$(grep -c $'^DROPPED\t/captures\tbatch-lost\tupstream_status=201' "$WORK/proxy.log")" 1
check "requests sent: 7 (missing file never sent)" "$(grep -c $'^POST\t' "$WORK/proxy.log")" 7
check "lost-response capture is committed" "$(curl -s -o /dev/null -w '%{http_code}' "$SERVER/captures/batch-lost")" 200
check "conflict left the stored capture unchanged" "$(curl -fsS "$SERVER/captures/batch-pre" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["entry_id"])')" 1
check "entries after batch (pre + 2 new + lost)" "$(entries)" 4

# 7. Rerun the same files: the lost one settles as replayed, nothing duplicated.
"$WORK/bin/capture" -url "$PROXY" -batch "${BATCH[@]}" > "$WORK/out/batch2.txt" 2>&1
check "rerun exit 1 (conflict and invalid remain)" "$?" 1
check "rerun 04-lost.json" "$(outcome "$WORK/out/batch2.txt" 04-lost.json)" replayed
check "rerun summary" "$(grep '^summary:' "$WORK/out/batch2.txt")" \
  "summary: total=8 created=0 replayed=4 conflict=1 invalid=3 unconfirmed=0 not_attempted=0"
check "entries after rerun (no duplicate)" "$(entries)" 4

# 8. Unreachable server: nothing is delivered (not_attempted), the batch stops
#    after 3 failed connections, exit 3.
DEAD="http://127.0.0.1:$((PPORT + 1))"
port_free "$((PPORT + 1))"; check "dead port is free" "$?" 0
"$WORK/bin/capture" -url "$DEAD" -batch "$C/01-new.json" "$C/02-replay.json" "$C/03-conflict.json" "$C/04-lost.json" "$C/07-new.json" > "$WORK/out/dead.txt" 2>&1
check "unreachable server exit 3" "$?" 3
check "unreachable summary" "$(grep '^summary:' "$WORK/out/dead.txt")" \
  "summary: total=5 created=0 replayed=0 conflict=0 invalid=0 unconfirmed=0 not_attempted=5"
check "unreachable: stopped after 3 failed connections" "$(grep -c '^stopped: the batch stopped after 3 files in a row without a server response' "$WORK/out/dead.txt")" 1
check "entries unchanged" "$(entries)" 4

# 9. Interruption: a listener that accepts but never answers; SIGINT after 1 s.
#    The request in flight is unconfirmed, the rest not attempted, exit 3.
HANG=$((PPORT + 2))
port_free "$HANG"; check "hang port is free" "$?" 0
python3 -I -c 'import socket,sys,time; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("127.0.0.1", int(sys.argv[1]))); s.listen(8); time.sleep(60)' "$HANG" &
pids+=($!)
for _ in $(seq 50); do port_free "$HANG" || break; sleep 0.1; done
"$WORK/bin/capture" -url "http://127.0.0.1:$HANG" -batch "$C/01-new.json" "$C/04-lost.json" "$C/07-new.json" > "$WORK/out/interrupt.txt" 2>&1 &
cpid=$!
sleep 1; kill -INT "$cpid"; wait "$cpid"
check "interrupted batch exit 3" "$?" 3
check "interrupted summary" "$(grep '^summary:' "$WORK/out/interrupt.txt")" \
  "summary: total=3 created=0 replayed=0 conflict=0 invalid=0 unconfirmed=1 not_attempted=2"
check "interrupted: in-flight file unconfirmed" "$(outcome "$WORK/out/interrupt.txt" 01-new.json)" unconfirmed
check "interrupted: report says so" "$(grep -c '^interrupted: files after the last decided one were not sent' "$WORK/out/interrupt.txt")" 1
check "entries unchanged after interruption" "$(entries)" 4

# 10. The documented example: the 16 synthetic captures/*.json, then a rerun.
"$WORK/bin/capture" -url "$SERVER" -batch "$REPO"/captures/*.json > "$WORK/out/demo1.txt" 2>&1
check "captures/*.json exit 0" "$?" 0
check "captures/*.json summary" "$(grep '^summary:' "$WORK/out/demo1.txt")" \
  "summary: total=16 created=16 replayed=0 conflict=0 invalid=0 unconfirmed=0 not_attempted=0"
"$WORK/bin/capture" -url "$SERVER" -batch "$REPO"/captures/*.json > "$WORK/out/demo2.txt" 2>&1
check "captures/*.json rerun exit 0" "$?" 0
check "captures/*.json rerun summary" "$(grep '^summary:' "$WORK/out/demo2.txt")" \
  "summary: total=16 created=0 replayed=16 conflict=0 invalid=0 unconfirmed=0 not_attempted=0"
check "entries: 4 + 16, no duplicate" "$(entries)" 20

# 11. No learner text or request body in any batch report.
check "no learner text in reports" "$(cat "$WORK"/out/{preview,batch1,batch2,dead,interrupt,demo1,demo2}.txt | grep -cE 'MARKER-LEARNER-TEXT|«|original_input|imparfait')" 0

printf '\n%s PASS, %s FAIL\n' "$(grep -c '^PASS' "$RES")" "$(grep -c '^FAIL' "$RES")" | tee -a "$RES"
exit $FAILED
