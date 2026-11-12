#!/usr/bin/env bash
# Local release-gate check of one public-demo package (demo-candidate lane).
#
#   bash scripts/validation/demo_candidate/check_package.sh PKG_DIR /abs/new/work/dir [options]
#
#   --expect-version V      the artifact version the package must carry and serve
#   --expect-manifest SHA   the artifact manifest SHA-256 (per build: take it from the
#                           package you mean to release, never from another build)
#   --expect-status S       BLOCKED or CANDIDATE (default: whatever RELEASE.json says)
#   --port N                loopback port for the live stages (default 18986; the
#                           package smoke uses N+1)
#   --node-modules DIR      a node_modules holding playwright-core (no browser download);
#                           the browser stage also needs CHROME=/path/to/chromium
#   --suites matrix|all     the UX matrix only (default), or also accept_paths, the
#                           first-visit suites and the FLH-076 browser acceptance
#   --skip-browser          identity, health, boundary and writes only
#
# Each stage runs a maintained tool, unchanged:
#   1 identity    validate-release.sh (exit 0 = CANDIDATE, 3 = BLOCKED, matching
#                 RELEASE.json); RELEASE.json's identity equals artifact/manifest.json
#                 and every --expect-* value
#   2 boundary    scripts/demo/flh076/smoke_package.sh: allowed and denied routes at
#                 the root and under /api, preset counters, package files unchanged
#   3 live        deploy/ctl.sh start; /healthz and /readyz; /knowledge-library/demo
#                 serves RELEASE.json's identity, read-only and synthetic;
#                 write_probe.sh: every write refused (405), the demo unchanged
#   4 browser     scripts/validation/demo_ux/accept_matrix.mjs (and, with --suites all,
#                 the other demo suites) against the live server
#   5 stop        deploy/ctl.sh stop; nothing left running; package files unchanged
#
# Linux only (the package's own binary). Loopback only; nothing is installed,
# uploaded or deployed, and no Git is run. Evidence: WORK/summary.json, WORK/*.txt
# and the suites' own output under WORK/browser/.
# Exit: 0 every stage passed; 1 a check failed; 2 usage or refused; 4 the
# browser stage could not run (no Chromium or playwright-core) and was not skipped.
set -uo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
PKG=${1:-}; WORK=${2:-}
[ -n "$PKG" ] && [ -n "$WORK" ] || { sed -n '2,36p' "$0" >&2; exit 2; }
shift 2
EXPECT_VERSION= EXPECT_MANIFEST= EXPECT_STATUS= PORT=18986 NODE_MODULES= SUITES=matrix SKIP_BROWSER=0
while [ $# -gt 0 ]; do
  case "$1" in
    --expect-version) EXPECT_VERSION=${2:-}; shift 2 ;;
    --expect-manifest) EXPECT_MANIFEST=${2:-}; shift 2 ;;
    --expect-status) EXPECT_STATUS=${2:-}; shift 2 ;;
    --port) PORT=${2:-}; shift 2 ;;
    --node-modules) NODE_MODULES=${2:-}; shift 2 ;;
    --suites) SUITES=${2:-}; shift 2 ;;
    --skip-browser) SKIP_BROWSER=1; shift ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
case "$WORK" in /*) ;; *) echo "refused: WORK must be absolute" >&2; exit 2 ;; esac
case "$WORK/" in "$REPO"/*) echo "refused: WORK must be outside the repository" >&2; exit 2 ;; esac
[ ! -e "$WORK" ] || { echo "refused: $WORK exists" >&2; exit 2; }
[ -f "$PKG/RELEASE.json" ] && [ -x "$PKG/validate-release.sh" ] && [ -x "$PKG/deploy/ctl.sh" ] || { echo "refused: $PKG is not a public-demo package" >&2; exit 2; }
[[ "$PORT" =~ ^[0-9]{4,5}$ ]] || { echo "refused: --port must be a number" >&2; exit 2; }
case "$SUITES" in matrix|all) ;; *) echo "refused: --suites matrix|all" >&2; exit 2 ;; esac
case "$EXPECT_STATUS" in ""|BLOCKED|CANDIDATE) ;; *) echo "refused: --expect-status BLOCKED|CANDIDATE" >&2; exit 2 ;; esac
[ "$(uname -s)" = Linux ] || { echo "refused: Linux only (the package's own binary)" >&2; exit 2; }
for p in "$PORT" "$((PORT + 1))"; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null; then echo "refused: port $p in use" >&2; exit 2; fi
done
PKG=$(cd "$PKG" && pwd)
mkdir -p "$WORK"
SUMMARY=$WORK/summary.json
declare -A STAGE
FAILED=0
note() { echo "$*" | tee -a "$WORK/check.txt"; }
stage() { STAGE[$1]=$2; note "STAGE $1: $2${3:+ ($3)}"; [ "$2" = FAIL ] && FAILED=1; return 0; }
tree_sha() { (cd "$PKG" && find . -type f | LC_ALL=C sort | while IFS= read -r f; do sha256sum "$f"; done | sha256sum | cut -d' ' -f1); }
PKG_TREE_BEFORE=$(tree_sha)

# 1. Identity (offline).
(cd "$PKG" && ./validate-release.sh) > "$WORK/validate-release.txt" 2>&1; VR=$?
python3 -I - "$PKG" "$VR" "$EXPECT_VERSION" "$EXPECT_MANIFEST" "$EXPECT_STATUS" > "$WORK/identity.txt" 2>&1 <<'PY'
import hashlib, json, os, sys
pkg, vr, ev, em, es = sys.argv[1], int(sys.argv[2]), *sys.argv[3:]
rel = json.load(open(os.path.join(pkg, "RELEASE.json")))
raw = open(os.path.join(pkg, "artifact/manifest.json"), "rb").read()
man = json.loads(raw)
a = rel["artifact"]
have = {"version": man["artifact_version"], "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "real_model": man["vectors"]["real_model"], "domain_fingerprint": man["domain_fingerprint"]["sha256"]}
bad = [f"RELEASE.json {k} {a[k]} != artifact {v}" for k, v in have.items() if a[k] != v]
status = rel["release_status"]
want_exit = {"CANDIDATE": 0, "BLOCKED": 3}.get(status)
if vr != want_exit:
    bad.append(f"validate-release.sh exit {vr} for RELEASE.json status {status} (want {want_exit})")
if es and status != es:
    bad.append(f"release status {status} != expected {es}")
if ev and have["version"] != ev:
    bad.append(f"identity mismatch: artifact version {have['version']} != expected {ev}")
if em and have["manifest_sha256"] != em:
    bad.append(f"identity mismatch: manifest {have['manifest_sha256']} != expected {em}")
if status == "CANDIDATE" and not have["real_model"]:
    bad.append("CANDIDATE without real-model vectors")
print(json.dumps({"release_status": status, "validate_release_exit": vr, **have, "vector_source": a["vector_source"], "model_id": a["model_id"]}))
for b in bad:
    print("FAIL", b)
sys.exit(1 if bad else 0)
PY
ID_RC=$?
cat "$WORK/identity.txt" | tee -a "$WORK/check.txt" > /dev/null
if [ "$ID_RC" = 0 ]; then stage identity PASS; else stage identity FAIL "$(grep '^FAIL' "$WORK/identity.txt" | head -3 | tr '\n' ';')"; fi
STATUS=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["release_status"])' "$PKG/RELEASE.json")
VECTORS=model; [ "$STATUS" = BLOCKED ] && VECTORS=mechanical
[ "$STATUS" = BLOCKED ] && export ALLOW_MECHANICAL=1

# 2. Boundary and health through the maintained package smoke (its own server and port).
if bash "$REPO/scripts/demo/flh076/smoke_package.sh" "$PKG" "$WORK/smoke" "$((PORT + 1))" > "$WORK/smoke.txt" 2>&1; then
  stage boundary PASS "$(grep -c '^PASS' "$WORK/smoke.txt") smoke checks"
else
  stage boundary FAIL "$(grep '^FAIL' "$WORK/smoke.txt" | head -3 | tr '\n' ';')"
fi

# 3. Live identity, health and attempted writes on a server started by deploy/ctl.sh.
RUN=$WORK/run
B="http://127.0.0.1:$PORT"
started=0
if PORT=$PORT "$PKG/deploy/ctl.sh" start "$RUN" > "$WORK/ctl-start.txt" 2>&1; then started=1; fi
stop_server() { if [ "$started" = 1 ]; then PORT=$PORT "$PKG/deploy/ctl.sh" stop "$RUN" > "$WORK/ctl-stop.txt" 2>&1 || true; started=0; fi; }
trap stop_server EXIT
if [ "$started" = 1 ]; then
  live=PASS; why=
  for p in /healthz /readyz; do
    c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$B$p"); [ "$c" = 200 ] || { live=FAIL; why="$why $p -> $c;"; }
  done
  curl -s --max-time 5 "$B/knowledge-library/demo" > "$WORK/demo-info.json"
  if ! python3 -I - "$WORK/demo-info.json" "$PKG/RELEASE.json" "$EXPECT_VERSION" "$EXPECT_MANIFEST" > "$WORK/live-identity.txt" 2>&1 <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); r = json.load(open(sys.argv[2]))["artifact"]; ev, em = sys.argv[3], sys.argv[4]
a = d["artifact"]
pairs = {"version": (a["version"], r["version"]), "manifest_sha256": (a["manifest_sha256"], r["manifest_sha256"]),
         "real_model": (a["real_model"], r["real_model"]), "domain_fingerprint": (a["domain_fingerprint_sha256"], r["domain_fingerprint"])}
bad = [f"served {k} {s} != RELEASE.json {w}" for k, (s, w) in pairs.items() if s != w]
if ev and a["version"] != ev: bad.append(f"identity mismatch: served version {a['version']} != expected {ev}")
if em and a["manifest_sha256"] != em: bad.append(f"identity mismatch: served manifest {a['manifest_sha256']} != expected {em}")
if d.get("read_only") is not True or d.get("data") != "synthetic": bad.append("demo is not read-only synthetic")
print("served", a["version"], a["manifest_sha256"], "real_model=%s" % a["real_model"], a["release_status"])
for b in bad: print("FAIL", b)
sys.exit(1 if bad else 0)
PY
  then live=FAIL; why="$why $(grep '^FAIL' "$WORK/live-identity.txt" | head -3 | tr '\n' ';')"; fi
  stage live "$live" "${why:-$(head -1 "$WORK/live-identity.txt")}"
  if bash "$REPO/scripts/validation/demo_candidate/write_probe.sh" "$B" "$WORK/writes.txt" > /dev/null 2>&1; then
    stage writes PASS "$(grep -c '^PASS refused' "$WORK/writes.txt") writes refused"
  else
    stage writes FAIL "$(grep '^FAIL' "$WORK/writes.txt" | head -3 | tr '\n' ';')"
  fi
else
  stage live FAIL "ctl.sh start: $(tail -1 "$WORK/ctl-start.txt")"
  stage writes FAIL "no server"
fi

# 4. Browser suites, from private copies next to the given playwright-core.
if [ "$SKIP_BROWSER" = 1 ]; then
  stage browser "NOT RUN" "--skip-browser"
elif [ -z "${CHROME:-}" ] || [ ! -x "${CHROME:-}" ] || [ -z "$NODE_MODULES" ] || [ ! -d "$NODE_MODULES/playwright-core" ]; then
  stage browser "NOT RUN" "needs CHROME=/path/to/chromium and --node-modules DIR with playwright-core"
elif [ "$started" != 1 ]; then
  stage browser FAIL "no server"
else
  T=$WORK/browser-tools; mkdir -p "$T" "$WORK/browser"
  ln -s "$(cd "$NODE_MODULES" && pwd)" "$T/node_modules"
  export PLAYWRIGHT_CORE_DIR="$T/node_modules/playwright-core"
  cp "$REPO/scripts/validation/demo_ux/accept_matrix.mjs" "$REPO/scripts/validation/demo_refresh/accept_paths.mjs" \
     "$REPO"/scripts/validation/demo_first_visit/*.mjs "$T/"
  results=()
  run_suite() { # NAME ARGS...
    local name=$1; shift
    if (cd "$T" && node "$@") > "$WORK/browser/$name.log" 2>&1; then results+=("$name PASS"); else results+=("$name FAIL"); fi
    note "  $name: $(tail -1 "$WORK/browser/$name.log")"
  }
  run_suite accept_matrix accept_matrix.mjs "$B/" "$WORK/browser/matrix" "$VECTORS"
  if [ "$SUITES" = all ]; then
    run_suite accept_paths accept_paths.mjs "$B/" "$WORK/browser/paths" "$VECTORS"
    run_suite accept_guided accept_guided.mjs "$B/" "$WORK/browser/guided"
    run_suite accept_resilience accept_resilience.mjs "$B/" "$WORK/browser/resilience"
    run_suite accept_a11y accept_a11y.mjs "$B/" "$WORK/browser/a11y"
    run_suite flh076_accept "$REPO/scripts/demo/flh076/browser/accept.mjs" --url "$B" --out "$WORK/browser/flh076" \
      --chrome "$CHROME" --expect-vectors "$VECTORS"
  fi
  if printf '%s\n' "${results[@]}" | grep -q ' FAIL$'; then
    stage browser FAIL "$(printf '%s\n' "${results[@]}" | grep ' FAIL$' | tr '\n' ';')"
  else
    stage browser PASS "$(printf '%s ' "${results[@]}")"
  fi
fi

# 5. Stop, nothing left running, package unchanged.
stop_server
trap - EXIT
left=$(ps -eo pid=,args= | grep -F -- "-public-demo-artifact $PKG/artifact" | grep -v grep || true)
[ -z "$left" ] && after=$(tree_sha) && [ "$after" = "$PKG_TREE_BEFORE" ] && stage stop PASS "stopped; package files unchanged" \
  || stage stop FAIL "left running: [${left}] or package files changed"

python3 -I - "$SUMMARY" "$PKG" "$STATUS" "$FAILED" "${STAGE[identity]}" "${STAGE[boundary]}" "${STAGE[live]}" "${STAGE[writes]}" "${STAGE[browser]}" "${STAGE[stop]}" "$WORK/identity.txt" <<'PY'
import json, sys
out, pkg, status, failed, *stages, ident = sys.argv[1:]
names = ["identity", "boundary", "live", "writes", "browser", "stop"]
first = open(ident).readline()
result = "FAIL" if failed == "1" else ("NOT RUN (browser)" if stages[4] == "NOT RUN" else "PASS")
json.dump({"schema": "demo_candidate_package_check_v1", "package": pkg, "release_status": status,
           "identity": json.loads(first) if first.startswith("{") else None,
           "stages": dict(zip(names, stages)), "result": result,
           "note": "PASS checks this package locally; a BLOCKED package stays not releasable whatever this says."},
          open(out, "w"), indent=1)
print(result)
PY
if [ "$FAILED" = 1 ]; then note "PACKAGE CHECK FAILED ($STATUS package)"; exit 1; fi
if [ "${STAGE[browser]}" = "NOT RUN" ] && [ "$SKIP_BROWSER" != 1 ]; then note "PACKAGE CHECK INCOMPLETE: browser not run"; exit 4; fi
note "PACKAGE CHECK PASSED ($STATUS package)"
exit 0
