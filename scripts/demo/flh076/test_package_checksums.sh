#!/usr/bin/env bash
# FLH-078 focused test of package.sh checksum-tool selection.
#
#   bash scripts/demo/flh076/test_package_checksums.sh /abs/new/work/dir /abs/artifact [expected-deployment]
#
# Runs package.sh with PATH restricted (a task-local farm of symlinks to every
# PATH executable except the hidden names) to:
#   none      neither sha256sum nor shasum: refused (exit 2) before anything is built or written;
#   sha256sum only (shasum hidden), and
#   shasum    only (sha256sum hidden), each when the host has that tool.
# For each package it checks the SHA256SUMS line format and file coverage,
# verification with every available tool, the tarball .sha256, the packaged
# validate-release.sh (under the same restricted PATH) and that a tampered
# file is detected. The work dir may contain spaces; it must not exist.
# Exit 0 only if every check passed. Implementations the host lacks are NOT RUN.
set -euo pipefail
WORK=${1:?usage}; ARTIFACT=${2:?usage}; EXPECTED=${3:-}
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
case "$WORK" in /*) ;; *) echo "refused: work dir must be absolute" >&2; exit 2 ;; esac
[ ! -e "$WORK" ] || { echo "refused: $WORK exists" >&2; exit 2; }
mkdir -p "$WORK"
FAILED=0
note() { echo "$*" | tee -a "$WORK/results.txt"; }
check() { if eval "$2"; then note "PASS $1"; else note "FAIL $1"; FAILED=1; fi; }

# farm NAME HIDDEN...: a directory of symlinks to the first PATH match of every
# executable name, except the hidden ones.
farm() {
  local dir="$WORK/path-$1" d f n hidden; shift
  hidden=" $* "
  mkdir -p "$dir"
  local IFS=:
  for d in $PATH; do
    [ -d "$d" ] || continue
    for f in "$d"/*; do
      n=${f##*/}
      [ -x "$f" ] && [ ! -d "$f" ] && [ ! -e "$dir/$n" ] || continue
      case "$hidden" in *" $n "*) continue ;; esac
      ln -s "$f" "$dir/$n"
    done
  done
  echo "$dir"
}
HAVE_SHA256SUM=0; command -v sha256sum >/dev/null 2>&1 && HAVE_SHA256SUM=1
HAVE_SHASUM=0; command -v shasum >/dev/null 2>&1 && HAVE_SHASUM=1
note "host: $(uname -sm); sha256sum=$HAVE_SHA256SUM shasum=$HAVE_SHASUM"
# validate-release.sh uses the package's Linux flh-prepare; elsewhere a host build.
if [ "$(uname -s)" = Linux ]; then PREP_ENV=(); else
  (cd "$REPO" && go build -o "$WORK/host-prepare" ./scripts/demo/flh073/prepare)
  PREP_ENV=(PREPARE="$WORK/host-prepare"); note "NOTE: non-Linux host: validate-release.sh uses a host build of flh-prepare"
fi
args=(--artifact "$ARTIFACT" --revision flh078-checksum-test --label cks)
[ -z "$EXPECTED" ] || args+=(--expected-deployment "$EXPECTED")

# 1. Neither tool: refused before building, nothing written.
P=$(farm none sha256sum shasum)
set +e; PATH=$P bash "$REPO/scripts/demo/flh076/package.sh" "${args[@]}" --out "$WORK/out none" > "$WORK/none.log" 2>&1; rc=$?; set -e
check "no tool: exit 2 (got $rc)" '[ "$rc" = 2 ]'
check "no tool: clear message" 'grep -q "refused: no SHA-256 tool (need sha256sum or shasum)" "$WORK/none.log"'
check "no tool: nothing written" '[ ! -e "$WORK/out none" ]'

# 2./3. One implementation at a time.
for impl in sha256sum shasum; do
  if [ "$impl" = sha256sum ]; then have=$HAVE_SHA256SUM; hide=shasum; else have=$HAVE_SHASUM; hide=sha256sum; fi
  if [ "$have" != 1 ]; then note "NOT RUN $impl only: the host has no $impl"; continue; fi
  P=$(farm "$impl" "$hide")
  OUT="$WORK/out $impl"
  set +e; PATH=$P bash "$REPO/scripts/demo/flh076/package.sh" "${args[@]}" --out "$OUT" > "$WORK/$impl.log" 2>&1; rc=$?; set -e
  check "$impl only: package.sh exit 0 (got $rc)" '[ "$rc" = 0 ]'
  [ "$rc" = 0 ] || { tail -5 "$WORK/$impl.log" | tee -a "$WORK/results.txt"; continue; }
  PKG=$(find "$OUT" -mindepth 1 -maxdepth 1 -type d -name 'flh-public-demo-cks*')
  NAME=${PKG##*/}
  check "$impl only: every SHA256SUMS line is 'HASH  PATH'" '! grep -v -E "^[0-9a-f]{64}  [^ ].*$" "$PKG/SHA256SUMS"'
  check "$impl only: SHA256SUMS lists exactly the other files" \
    '[ "$(cut -c67- "$PKG/SHA256SUMS")" = "$(cd "$PKG" && find . -type f ! -name SHA256SUMS | sed "s|^\./||" | LC_ALL=C sort)" ]'
  [ "$HAVE_SHA256SUM" = 1 ] && check "$impl only: sha256sum -c verifies" '(cd "$PKG" && sha256sum --quiet -c SHA256SUMS)'
  [ "$HAVE_SHASUM" = 1 ] && check "$impl only: shasum -a 256 -c verifies" '(cd "$PKG" && shasum -a 256 -c SHA256SUMS >/dev/null)'
  if [ "$impl" = sha256sum ]; then want=$(cd "$OUT" && sha256sum "$NAME.tar.gz"); else want=$(cd "$OUT" && shasum -a 256 "$NAME.tar.gz"); fi
  check "$impl only: tarball .sha256 is 'HASH  $NAME.tar.gz' and matches" '[ "$(cat "$OUT/$NAME.tar.gz.sha256")" = "$want" ]'
  want=3; [ -z "$EXPECTED" ] || want=0
  set +e; env "${PREP_ENV[@]}" PATH="$P" "$PKG/validate-release.sh" > "$WORK/$impl.validate" 2>&1; rc=$?; set -e
  check "$impl only: validate-release.sh exit $want (got $rc: $(tail -1 "$WORK/$impl.validate"))" '[ "$rc" = "$want" ]'
  # Tamper with a copy and expect checksum failure (exit 1).
  T="$WORK/tamper $impl"; cp -R "$PKG" "$T"; printf ' ' >> "$T/web/index.html"
  set +e; env "${PREP_ENV[@]}" PATH="$P" "$T/validate-release.sh" > "$WORK/$impl.tamper" 2>&1; rc=$?; set -e
  check "$impl only: tampered web/index.html refused (exit $rc: $(tail -1 "$WORK/$impl.tamper"))" '[ "$rc" = 1 ] && grep -q "checksums differ" "$WORK/$impl.tamper"'
  rm -rf "$T"
  cut -c67- "$PKG/SHA256SUMS" > "$WORK/$impl.paths"
done
if [ -f "$WORK/sha256sum.paths" ] && [ -f "$WORK/shasum.paths" ]; then
  check "both implementations list the same paths" 'cmp -s "$WORK/sha256sum.paths" "$WORK/shasum.paths"'
fi
[ "$FAILED" = 0 ] && note "CHECKSUM TESTS PASSED" || note "CHECKSUM TESTS FAILED"
exit "$FAILED"
