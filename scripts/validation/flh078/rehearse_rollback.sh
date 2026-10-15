#!/usr/bin/env bash
# FLH-078 local deployment/rollback rehearsal of the documented procedure
# (PACKAGE_README.md "Install and roll back"), on Linux, loopback only.
#
#   bash scripts/validation/flh078/rehearse_rollback.sh "/abs/new/root" PREVIOUS.tar.gz CANDIDATE.tar.gz [port]
#
# PREVIOUS is the release in service before the change (here a mechanical
# BLOCKED package, so it is started with ALLOW_MECHANICAL=1 and labelled as
# such); CANDIDATE is the release being introduced. Under ROOT it creates
# releases/<package>/ (read-only after validation), the `current` symlink
# outside them, and a runtime dir. Steps: install and serve PREVIOUS; install,
# validate and switch to CANDIDATE; roll back to PREVIOUS; return to CANDIDATE;
# then an invalid candidate (one artifact byte changed) is refused by
# validation, and, if selected anyway, refused at startup; recovery is a switch
# back plus restart. Every step checks the identity the running server
# reports, and release files are hashed before and after. Nothing is installed
# system-wide; no systemd, proxy or public listener. Results: ROOT/results.tsv.
set -uo pipefail
ROOT=${1:?usage}; PREV=${2:?usage}; CAND=${3:?usage}; PORT=${4:-19990}
case "$ROOT" in /*) ;; *) echo "ROOT must be absolute" >&2; exit 2 ;; esac
[ ! -e "$ROOT" ] || { echo "refused: $ROOT exists" >&2; exit 2; }
[ "$(uname -s)" = Linux ] || { echo "Linux only (packaged native binary)" >&2; exit 2; }
mkdir -p "$ROOT/releases" "$ROOT/run"
RES="$ROOT/results.tsv"; : > "$RES"
FAILED=0
rec() { printf '%s\t%s\t%s\n' "$1" "$2" "${3:-}" | tee -a "$RES"; }
ok() { if [ "$2" = "$3" ]; then rec PASS "$1" "$2"; else rec FAIL "$1" "got [$2] want [$3]"; FAILED=1; fi; }
B="http://127.0.0.1:$PORT"
ctl() { (cd "$ROOT" && PORT=$PORT "$ROOT/current/deploy/ctl.sh" "$@" "$ROOT/run"); }
identity() { curl -fsS --max-time 2 "$B/knowledge-library/demo" | python3 -c 'import json,sys; a=json.load(sys.stdin)["artifact"]; print(a["version"], a["real_model"], a["manifest_sha256"][:16])' 2>/dev/null || echo unreachable; }
want_identity() { python3 -c 'import json,sys; m=json.load(open(sys.argv[1]+"/artifact/manifest.json")); r=json.load(open(sys.argv[1]+"/RELEASE.json"))["artifact"]; print(m["artifact_version"], m["vectors"]["real_model"], r["manifest_sha256"][:16])' "$1"; }
tree_sha() { (cd "$1" && find . -type f | LC_ALL=C sort | while IFS= read -r f; do sha256sum "$f"; done | sha256sum | cut -d' ' -f1); }
select_release() { ln -sfn "releases/$1" "$ROOT/current.new" && mv -T "$ROOT/current.new" "$ROOT/current"; rec NOTE "current -> releases/$1"; }

install() { # tarball -> INAME, IRC; unpack into releases/, validate, make read-only
  local tgz=$1 name; name=$(basename "$tgz" .tar.gz)
  (cd "$(dirname "$tgz")" && sha256sum -c "$name.tar.gz.sha256" > /dev/null) && rec PASS "tarball checksum $name" || { rec FAIL "tarball checksum $name"; FAILED=1; }
  tar -C "$ROOT/releases" -xzf "$tgz"
  set +e; (cd "$ROOT/releases/$name" && ./validate-release.sh > "$ROOT/validate-$name.out" 2>&1); local rc=$?; set -e
  rec NOTE "validate-release $name exit $rc" "$(tail -1 "$ROOT/validate-$name.out")"
  chmod -R a-w "$ROOT/releases/$name"
  INAME=$name IRC=$rc
}
set -e
install "$PREV"; PNAME=$INAME PRC=$IRC
install "$CAND"; CNAME=$INAME CRC=$IRC
ok "previous release validates as BLOCKED (mechanical)" "$PRC" 3
ok "candidate release validates as CANDIDATE" "$CRC" 0
PSHA=$(tree_sha "$ROOT/releases/$PNAME"); CSHA=$(tree_sha "$ROOT/releases/$CNAME")
PID_WANT=$(want_identity "$ROOT/releases/$PNAME"); CID_WANT=$(want_identity "$ROOT/releases/$CNAME")
set +e

# 1. Previous release in service (mechanical, so ALLOW_MECHANICAL=1; labelled).
select_release "$PNAME"
ALLOW_MECHANICAL=1 ctl start > "$ROOT/1-start.out" 2>&1; ok "1 start previous" "$?" 0
ok "1 serving previous identity" "$(identity)" "$PID_WANT"
# 2. Switch to the candidate and restart.
select_release "$CNAME"
ctl stop > "$ROOT/2-stop.out" 2>&1; ok "2 stop (through the switched symlink) stops the running previous server" "$?" 0
ok "2 port closed after stop" "$(identity)" unreachable
ctl start > "$ROOT/2-start.out" 2>&1; ok "2 start candidate" "$?" 0
ok "2 serving candidate identity" "$(identity)" "$CID_WANT"
ctl status > "$ROOT/2-status.out" 2>&1; ok "2 status" "$?" 0
ok "2 status names the real-model artifact" "$(grep -c "real_model=True model_vectors" "$ROOT/2-status.out")" 1
# 3. Roll back.
select_release "$PNAME"
ctl stop > "$ROOT/3-stop.out" 2>&1; ok "3 stop candidate" "$?" 0
ALLOW_MECHANICAL=1 ctl start > "$ROOT/3-start.out" 2>&1; ok "3 rollback start previous" "$?" 0
ok "3 serving previous identity after rollback" "$(identity)" "$PID_WANT"
# 4. Forward again.
select_release "$CNAME"
ctl stop > "$ROOT/4-stop.out" 2>&1; ok "4 stop previous" "$?" 0
ctl start > "$ROOT/4-start.out" 2>&1; ok "4 start candidate again" "$?" 0
ok "4 serving candidate identity" "$(identity)" "$CID_WANT"

# 5. Invalid candidate: a copy of the candidate with one artifact byte changed.
BAD="${CNAME}-invalid"
cp -R "$ROOT/releases/$CNAME" "$ROOT/releases/$BAD"; chmod -R u+w "$ROOT/releases/$BAD"
python3 - "$ROOT/releases/$BAD/artifact/fixtures.json" <<'PY'
import sys
p = sys.argv[1]; b = bytearray(open(p, "rb").read()); i = b.index(b"synthetic"); b[i] = ord("S"); open(p, "wb").write(bytes(b))
PY
chmod -R a-w "$ROOT/releases/$BAD"
(cd "$ROOT/releases/$BAD" && ./validate-release.sh > "$ROOT/5-validate.out" 2>&1); ok "5 invalid candidate refused by validate-release (do not switch)" "$?" 1
rec NOTE "5 validate output" "$(tail -1 "$ROOT/5-validate.out")"
ok "5 the service is still the candidate" "$(identity)" "$CID_WANT"
# Operator error: switched and restarted anyway.
select_release "$BAD"
ctl stop > "$ROOT/5-stop.out" 2>&1; ok "5 stop" "$?" 0
ctl start > "$ROOT/5-start.out" 2>&1; rc=$?
[ "$rc" != 0 ] && rec PASS "5 invalid release refused at startup" "exit $rc: $(grep -m1 -i -E 'refus|mismatch|fail|error' "$ROOT/run/flh-public-demo.log" "$ROOT/5-start.out" | head -1 | cut -c1-200)" || { rec FAIL "5 invalid release started"; FAILED=1; }
ok "5 nothing serving after the refused start" "$(identity)" unreachable
# Recovery: switch back to the last good release and restart.
select_release "$CNAME"
ctl start > "$ROOT/5-recover.out" 2>&1; ok "5 recovery start candidate" "$?" 0
ok "5 serving candidate identity after recovery" "$(identity)" "$CID_WANT"
ctl stop > "$ROOT/6-stop.out" 2>&1; ok "6 final stop" "$?" 0
ok "6 port closed" "$(identity)" unreachable

ok "release files unchanged: previous" "$(tree_sha "$ROOT/releases/$PNAME")" "$PSHA"
ok "release files unchanged: candidate" "$(tree_sha "$ROOT/releases/$CNAME")" "$CSHA"
ok "releases are read-only" "$(find "$ROOT/releases" -mindepth 1 \( -perm -u+w -o -perm -g+w -o -perm -o+w \) | wc -l | tr -d ' ')" 0
ok "no server left running from ROOT" "$(pgrep -f -- "-public-demo-artifact $ROOT/" | wc -l | tr -d ' ')" 0
{ printf 'PASS %s\n' "$(grep -c '^PASS' "$RES")"; printf 'FAIL %s\n' "$(grep -c '^FAIL' "$RES")"; } | tee "$ROOT/summary.txt"
exit "$FAILED"
