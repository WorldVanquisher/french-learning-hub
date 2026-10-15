#!/bin/sh
# Validates an FLH public-demo release package in place (FLH-076). Run from anywhere:
#   ./validate-release.sh            (uses bin/linux-<arch>/flh-prepare)
#   PREPARE=/path/to/flh-prepare ./validate-release.sh   (e.g. on a non-Linux host)
# Exit 0: release candidate valid. 3: BLOCKED (mechanical vectors). 1: invalid.
set -eu
ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT"
fail() { echo "INVALID: $*" >&2; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then sha256sum --quiet -c SHA256SUMS || fail "checksums differ"
else shasum -a 256 -c SHA256SUMS >/dev/null || fail "checksums differ"; fi
[ -z "$(find . -type l)" ] || fail "symbolic links present"
unlisted=$(find . -type f ! -name SHA256SUMS | sed 's|^\./||' | sort | while read -r f; do grep -q "  $f\$" SHA256SUMS || echo "$f"; done)
[ -z "$unlisted" ] || fail "files not in SHA256SUMS: $unlisted"
case "$(uname -m)" in x86_64|amd64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) ARCH=unknown ;; esac
PREPARE=${PREPARE:-$ROOT/bin/linux-$ARCH/flh-prepare}
[ -x "$PREPARE" ] || fail "no flh-prepare for this host; set PREPARE"
"$PREPARE" validate -artifact "$ROOT/artifact" > /dev/null || fail "artifact does not validate"
status=$(python3 -c 'import json; print(json.load(open("RELEASE.json"))["release_status"])')
set +e
"$PREPARE" validate -artifact "$ROOT/artifact" -release > /dev/null 2>&1
rc=$?
set -e
if [ "$rc" = 3 ]; then
  [ "$status" = BLOCKED ] || fail "RELEASE.json says $status but the artifact is mechanical"
  echo "BLOCKED: checksums and artifact valid, but the vectors are mechanical test fixtures (not releasable)"; exit 3
fi
[ "$rc" = 0 ] || fail "release validation exit $rc"
[ "$status" = CANDIDATE ] || fail "RELEASE.json says $status for a model artifact"
echo "CANDIDATE: checksums, artifact, model provenance and release validation passed"
