#!/usr/bin/env bash
# Disk preflight for browser and Compose jobs: is there room where the job
# writes, before it starts?
#
#   bash scripts/release/disk_preflight.sh [--probe-mb N] LABEL=DIR:MIN_MB[:noprobe] ...
#
# For each location it reports the free space `df` shows and, unless
# `noprobe`, writes and deletes one probe file of N MiB (default 32) in DIR.
# The probe catches what `df` misses: a per-user quota on a shared tmpfs (seen
# here as "disk quota exceeded" while `df` still showed free space). The probe
# file is the only thing this script creates or deletes; it never cleans,
# moves or inspects anyone else's files.
#
# Exit 0 when every location passes. Exit 3 (BLOCKED) otherwise, after
# printing, for each failing location: the label, the directory, the space
# available and needed, the probe error, and the effective TMPDIR, so the job
# can say where to free space or which TMPDIR to set. Exit 2 for bad usage.
set -uo pipefail

PROBE_MB=32
LOCS=()
while [ $# -gt 0 ]; do
  case $1 in
    --probe-mb) PROBE_MB=${2:?--probe-mb needs a number}; shift 2 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *=*:*) LOCS+=("$1"); shift ;;
    *) echo "disk preflight: bad argument $1 (want LABEL=DIR:MIN_MB[:noprobe])" >&2; exit 2 ;;
  esac
done
[[ "$PROBE_MB" =~ ^[0-9]+$ ]] || { echo "disk preflight: --probe-mb must be a whole number" >&2; exit 2; }
[ ${#LOCS[@]} -gt 0 ] || { echo "disk preflight: no location given" >&2; exit 2; }

EFFECTIVE_TMP=${TMPDIR:-/tmp}
TMP_NOTE="TMPDIR=${TMPDIR:-<unset, so /tmp>}"
FAILED=0
PROBE=""
cleanup() { [ -n "$PROBE" ] && rm -f -- "$PROBE"; }
trap cleanup EXIT

for loc in "${LOCS[@]}"; do
  label=${loc%%=*}
  rest=${loc#*=}
  opt=""
  case $rest in *:noprobe) opt=noprobe; rest=${rest%:noprobe} ;; esac
  dir=${rest%:*}
  need=${rest##*:}
  [[ "$need" =~ ^[0-9]+$ ]] || { echo "disk preflight: $label: MIN_MB must be a whole number" >&2; exit 2; }
  problems=()
  avail=""
  if [ ! -d "$dir" ]; then
    problems+=("directory does not exist")
  else
    avail=$(df -Pk -- "$dir" 2> /dev/null | awk 'NR == 2 { print int($4 / 1024) }')
    if [ -z "$avail" ]; then
      problems+=("df could not read it")
    elif [ "$avail" -lt "$need" ]; then
      problems+=("only ${avail} MiB available, ${need} MiB needed")
    fi
    if [ "$opt" != noprobe ] && [ "$PROBE_MB" -gt 0 ]; then
      PROBE=$(mktemp -p "$dir" .flh-disk-preflight.XXXXXX 2> /dev/null) || { problems+=("cannot create a file there"); PROBE=""; }
      if [ -n "$PROBE" ]; then
        if ! err=$(head -c "$((PROBE_MB * 1048576))" /dev/zero 2>&1 > "$PROBE") || ! err=$(sync -f "$PROBE" 2>&1); then
          problems+=("probe write of ${PROBE_MB} MiB failed${err:+: $err}")
        elif [ "$(stat -c %s "$PROBE")" != "$((PROBE_MB * 1048576))" ]; then
          problems+=("probe write of ${PROBE_MB} MiB was cut short (quota or full disk)")
        fi
        rm -f -- "$PROBE"
        PROBE=""
      fi
    fi
  fi
  if [ ${#problems[@]} -eq 0 ]; then
    printf 'disk preflight: %s OK: %s (%s MiB available, %s MiB needed)\n' "$label" "$dir" "$avail" "$need"
  else
    FAILED=1
    printf 'disk preflight: %s BLOCKED: %s: %s\n' "$label" "$dir" "$(IFS='; '; echo "${problems[*]}")" >&2
  fi
done

if [ "$FAILED" = 1 ]; then
  {
    echo "disk preflight: $TMP_NOTE (effective: $EFFECTIVE_TMP)"
    echo "disk preflight: nothing was cleaned. Free space yourself, or rerun with TMPDIR and the work directory on a disk with room."
  } >&2
  exit 3
fi
exit 0
