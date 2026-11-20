#!/usr/bin/env bash
# One copyable verification sequence for a backup transfer and restore (R4-WB-050).
#
#   bash scripts/validation/migration/verify_restore.sh BACKUP_DIR WORK
#
# BACKUP_DIR is a COMPLETE `flh-daily.sh backup` directory (app.db, sidecars, SHA256SUMS), taken
# from a STOPPED service. WORK is a new, empty scratch directory. Every step reads copies only and
# stops at the first failure with its exit status. The data directory it restores into is
# WORK/data; in a real cutover, the RELEASE.md restore block puts the files in place instead,
# and steps 6 and 7 run on that directory before the service starts.
set -euo pipefail
[ $# -eq 2 ] || { echo "usage: verify_restore.sh BACKUP_DIR WORK" >&2; exit 2; }
BACKUP=$(realpath "$1"); WORK=$2
mkdir -p "$WORK"; [ -z "$(ls -A "$WORK")" ] || { echo "WORK must be empty" >&2; exit 2; }
WORK=$(realpath "$WORK"); REPO=$(cd "$(dirname "$0")/../../.." && pwd)
step() { echo "== $*"; }

step "1. the source backup is COMPLETE and its inventory READY (the baseline)"
python3 -I -B "$REPO/scripts/release/backup_tool.py" inspect "$BACKUP" --json | python3 -c 'import json,sys; s=json.load(sys.stdin)["state"]; print(s); sys.exit(0 if s=="COMPLETE" else 1)'
python3 -I -B "$REPO/scripts/validation/migration/inventory.py" "$BACKUP" --out "$WORK/inv-source"

step "2. pack (writes the archive's SHA-256 beside it)"
mkdir -p "$WORK/sent"
python3 -I -B "$REPO/scripts/release/backup_tool.py" pack "$BACKUP" "$WORK/sent/flh-backup.tar.gz"

step "3. transfer (here: a scratch copy) and compare the SHA-256 on arrival"
mkdir -p "$WORK/arrived"; cp "$WORK/sent/flh-backup.tar.gz" "$WORK/sent/flh-backup.tar.gz.sha256" "$WORK/arrived/"
SENT=$(cut -d' ' -f1 "$WORK/arrived/flh-backup.tar.gz.sha256")
GOT=$(sha256sum "$WORK/arrived/flh-backup.tar.gz" | cut -d' ' -f1)
[ "$SENT" = "$GOT" ] && echo "sha256 ok $GOT" || { echo "sha256 MISMATCH: sent $SENT, arrived $GOT" >&2; exit 1; }

step "4. unpack (verifies the SHA-256 first; a truncated or altered archive leaves nothing)"
mkdir -p "$WORK/unpacked"
python3 -I -B "$REPO/scripts/release/backup_tool.py" unpack "$WORK/arrived/flh-backup.tar.gz" --sha256 "$SENT" "$WORK/unpacked"
RESTORED=$(ls -d "$WORK"/unpacked/*/ | head -1)
python3 -I -B "$REPO/scripts/release/backup_tool.py" inspect "$RESTORED" --json | python3 -c 'import json,sys; s=json.load(sys.stdin)["state"]; print(s); sys.exit(0 if s=="COMPLETE" else 1)'

step "5. into a fresh data directory"
mkdir -p "$WORK/data"; cp -p "$RESTORED"/app.db* "$WORK/data/"

step "6. the first write is possible (before the service starts)"
python3 -I "$REPO/scripts/release/restore_write_check.py" "$WORK/data"

step "7. the restored data equals the baseline: READY, the same logical digest, no family missing"
python3 -I -B "$REPO/scripts/validation/migration/inventory.py" "$WORK/data" --out "$WORK/inv-target" --expect "$WORK/inv-source/inventory.json"
python3 -c 'import json,sys; e=json.load(open(sys.argv[1]))["expect"]; print("same logical digest:", e["same_logical_digest"]); sys.exit(0 if e["same_logical_digest"] and not e["missing"] else 1)' "$WORK/inv-target/inventory.json"
echo "VERIFIED: $BACKUP restores with the same learner data"
