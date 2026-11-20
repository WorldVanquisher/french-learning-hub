#!/usr/bin/env bash
# integration_battery.sh TREE RECEIPT_DIR WORK_DIR [STAGE...]
#
# Runs the release checks on one assembled candidate tree and records each in its integration
# receipt (scripts/release/integration_receipt.py). TREE stays untouched: every stage runs on
# WORK_DIR/test, a copy whose tree id must equal the receipt's candidate before and after each
# command (integration_receipt.py run --tree refuses or fails otherwise). Stages, in order:
#
#   go        gofmt, go vet, go test, and every command build
#   web       npm run typecheck (tsc -b), the full vitest suite, npm run build
#   python    scripts/ci/python_suites.py --hermetic --require speaking
#   speaking  strict Speaking suite in a local image, offline (needs FLH_SPEAKING_IMAGE and
#             FLH_SPEAKING_FIXTURE; recorded UNAVAILABLE when either is missing)
#   learning  scripts/validation/learning_day/verify.py
#   practice  scripts/validation/practice_feed/walkthrough.py
#   demo      public-demo package from this tree, its gate with the pinned SHA256SUMS digest,
#             then the six browser suites (needs FLH_DEMO_E5_WORK, FLH_DEMO_DEPLOYMENT and
#             FLH_DEMO_SUITE; UNAVAILABLE otherwise)
#   bundle    private-staging bundle (build_bundle.sh --tree), Docker builds without network
#   report    release_report.py collect for local-rehearsal (needs FLH_ROLLBACK_BUNDLE and
#             FLH_ROLLBACK_SHA256)
#
# Environment: RESUME=1 keeps any check already PASS on this tree with intact evidence (a rerun
# after an interrupted stage starts where it stopped). Builds are offline: GOPROXY=off,
# GOFLAGS=-mod=readonly, `npm ci --offline`, `docker build --network none` (a PATH shim).
# No Git, no AWS, no deployment. Machine-specific locations come only from the environment.
set -uo pipefail
TREE=$(realpath "$1"); RD=$(realpath -m "$2"); WORK=$(realpath -m "$3"); shift 3
STAGES=${*:-go web python speaking learning practice demo bundle report}
HERE=$(cd "$(dirname "$0")" && pwd)
RT="python3 -I -B $HERE/integration_receipt.py"
export GOPROXY=off GOFLAGS=-mod=readonly TMPDIR="${TMPDIR:-$WORK/tmp}"
mkdir -p "$WORK" "$TMPDIR"
T=$WORK/test
RES=${RESUME:+--resume}
BOTH="--required-for local-rehearsal --required-for staging"

note() { printf '\n== %s ==\n' "$*"; }
unavail() {   # id title reason next
  local f=$WORK/$1.unavailable.txt
  printf '%s\n' "$3" > "$f"
  $RT record "$RD" --id "$1" --title "$2" --status unavailable --evidence "$f" $BOTH --next-action "$4"
}

if [ ! -d "$T" ]; then
  note "test copy"
  cp -a "$TREE" "$T" || exit 2
  (cd "$T/web" && npm ci --offline --no-audit --no-fund --ignore-scripts > "$WORK/npm-ci.log" 2>&1) || { echo "npm ci --offline failed: $WORK/npm-ci.log"; exit 2; }
fi

for s in $STAGES; do case $s in
go)
  note go
  $RT run "$RD" $RES --id go --title "Go: gofmt, vet, test, command builds" $BOTH --tree "$T" --parse go -- bash -c \
    'set -e; test -z "$(gofmt -l ./cmd ./internal)"; echo gofmt clean; go vet ./...; echo vet ok; go test -count=1 ./...; for c in server capture semantic-index listening-pull history-export; do go build -o /dev/null ./cmd/$c && echo "build $c ok"; done'
  ;;
web)
  note web
  $RT run "$RD" $RES --id web-typecheck --title "Web typecheck: npm run typecheck (tsc -b --noEmit)" $BOTH --tree "$T" --cwd "$T/web" -- npm run typecheck
  $RT run "$RD" $RES --id web-test --title "Web tests: vitest, all files" $BOTH --tree "$T" --cwd "$T/web" --parse vitest -- \
    env NODE_OPTIONS=--no-experimental-webstorage npx vitest run
  $RT run "$RD" $RES --id web-build --title "Web production build: npm run build" $BOTH --tree "$T" --cwd "$T/web" -- npm run build
  ;;
python)
  note python
  $RT run "$RD" $RES --id python-suites --title "Python CI suites, hermetic, Speaking required" $BOTH --tree "$T" --parse python-suites \
    --json "$WORK/python-suites.json" -- python3 -B scripts/ci/python_suites.py --hermetic --require speaking --json "$WORK/python-suites.json"
  ;;
speaking)
  note speaking
  if [ -z "${FLH_SPEAKING_IMAGE:-}" ] || [ -z "${FLH_SPEAKING_FIXTURE:-}" ] || ! docker image inspect "$FLH_SPEAKING_IMAGE" >/dev/null 2>&1; then
    unavail speaking-strict "Strict Speaking suite (local image, offline)" "FLH_SPEAKING_IMAGE or FLH_SPEAKING_FIXTURE missing" \
      "build the image (docs/validation/SPEAKING-TEST-ENTRY.md) and set FLH_SPEAKING_IMAGE and FLH_SPEAKING_FIXTURE"
  else
    mkdir -p "$WORK/speaking-out"
    $RT run "$RD" $RES --id speaking-strict --title "Strict Speaking suite: --require-deps, --network none, repository mounted read-only" $BOTH \
      --tree "$T" --parse unittest --json "$WORK/speaking-out/strict.json" -- docker run --rm --network none --cpus 2 --memory 1g \
      -u "$(id -u):$(id -g)" -e HOME=/tmp -e PYTHONPATH=/repo/tools/speaking -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
      -e FLH_SPEAKING_TOKENIZER_DIR=/fixture/openai/whisper-tiny/169d4a4341b33bc18d8881c4b69c2e104e1cc0af \
      -v "$T:/repo:ro" -v "$FLH_SPEAKING_FIXTURE:/fixture:ro" -v "$WORK/speaking-out:/out" -w /repo/tools/speaking \
      --entrypoint python "$FLH_SPEAKING_IMAGE" -B scripts/run_tests.py --require-deps --expect-offline --json /out/strict.json
  fi
  ;;
learning)
  note learning
  rm -rf "$WORK/learning-day"
  $RT run "$RD" $RES --id learning-day --title "Private learning-day walkthrough (verify.py: gofmt, go, web, browser)" $BOTH --tree "$T" \
    --parse results --json "$WORK/learning-day/browser/results.json" -- python3 -I scripts/validation/learning_day/verify.py "$WORK/learning-day"
  ;;
practice)
  note practice
  rm -rf "$WORK/practice-feed"
  $RT run "$RD" $RES --id practice-feed --title "Practice-feed browser walkthrough (desktop en, 320 px en and zh)" $BOTH --tree "$T" \
    --parse results --json "$WORK/practice-feed/results.json" -- python3 -I scripts/validation/practice_feed/walkthrough.py "$WORK/practice-feed"
  ;;
demo)
  note demo
  if [ -z "${FLH_DEMO_E5_WORK:-}" ] || [ -z "${FLH_DEMO_DEPLOYMENT:-}" ] || [ -z "${FLH_DEMO_SUITE:-}" ]; then
    unavail demo-package-gate "Public-demo package gate" "FLH_DEMO_E5_WORK, FLH_DEMO_DEPLOYMENT or FLH_DEMO_SUITE missing" \
      "set them (demo-refresh DEPLOY-HANDOFF §083) and rerun the demo stage"
    unavail demo-browser "Public-demo browser suites" "the package was not built" "rerun the demo stage"
  else
    TID=$(python3 -I -B "$HERE/integration_candidate.py" tree-id "$T" | python3 -c 'import json,sys; print(json.load(sys.stdin)["tree_id"])')
    D=$WORK/demo; rm -rf "$D"; mkdir -p "$D"
    LABEL=rc-${TID:0:12}
    $RT run "$RD" $RES --id demo-package --title "Public-demo package built from this tree (prepare, import, validate, package.sh)" \
      --scope package --tree "$T" -- bash -c '
        set -e; D='"$D"'; go build -buildvcs=false -o "$D/flh-prepare" ./scripts/demo/flh073/prepare; echo "build prepare ok"
        "$D/flh-prepare" plan | grep -o "\"plan_sha256\": \"[0-9a-f]*\""
        cp -a "'"$FLH_DEMO_E5_WORK"'" "$D/e5-work"
        "$D/flh-prepare" import -work "$D/e5-work" -out "$D/artifact" > "$D/import.log" 2>&1; echo "import exit $?"
        "$D/flh-prepare" validate -artifact "$D/artifact" -release > "$D/validate.log" 2>&1; echo "validate exit $?"
        bash scripts/demo/flh076/package.sh --artifact "$D/artifact" --revision tree-'"${TID:0:12}"' --label '"$LABEL"' \
          --out "$D/packages" --expected-deployment "'"$FLH_DEMO_DEPLOYMENT"'" > "$D/package.log" 2>&1; echo "package exit $?"
        tail -3 "$D/package.log"'
    PKG=$D/packages/flh-public-demo-$LABEL
    if [ -f "$PKG/SHA256SUMS" ]; then
      SUMS=$(sha256sum "$PKG/SHA256SUMS" | cut -c1-64); echo "$SUMS" > "$D/pinned-sums-digest.txt"
      MAN=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact"]["manifest_sha256"])' "$PKG/RELEASE.json")
      VER=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact"]["version"])' "$PKG/RELEASE.json")
      $RT run "$RD" $RES --id demo-package-gate --title "Package gate with the pinned SHA256SUMS digest (--skip-browser; browser suites below)" $BOTH \
        --scope package --tree "$T" --artifact "$PKG/SHA256SUMS" --artifact "$PKG.tar.gz" -- bash scripts/validation/demo_candidate/check_package.sh \
        "$PKG" "$D/check" --expect-status CANDIDATE --expect-version "$VER" --expect-manifest "$MAN" --expect-sums "$SUMS" --skip-browser
      PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
      mkdir -p "$D/run" "$D/browser"
      PORT=$PORT bash "$PKG/deploy/ctl.sh" start "$D/run" > "$D/browser/ctl-start.txt" 2>&1
      B="http://127.0.0.1:$PORT"
      cat > "$D/browser.sh" <<EOF
set -u; rc=0
r() { n=\$1; shift; bash "$FLH_DEMO_SUITE" "$T" "$D/browser/\$n" "\$@" > "$D/browser/\$n.log" 2>&1; e=\$?; echo "\$n exit \$e: \$(tail -1 "$D/browser/\$n.log")"; [ \$e = 0 ] || rc=1; }
sha256sum -c --quiet "$D/pinned-sums.check" && echo "package bytes = pinned SHA256SUMS"
r accept_matrix scripts/validation/demo_ux/accept_matrix.mjs "$B/" /out/matrix model
r accept_paths scripts/validation/demo_refresh/accept_paths.mjs "$B/" /out/paths model
r accept_guided scripts/validation/demo_first_visit/accept_guided.mjs "$B/" /out/guided model
r accept_resilience scripts/validation/demo_first_visit/accept_resilience.mjs "$B/" /out/resilience
r accept_a11y scripts/validation/demo_first_visit/accept_a11y.mjs "$B/" /out/a11y
r flh076_accept scripts/demo/flh076/browser/accept.mjs --url "$B" --out /out/flh076 --chrome /usr/bin/chromium --expect-vectors model
exit \$rc
EOF
      echo "$SUMS  $PKG/SHA256SUMS" > "$D/pinned-sums.check"
      $RT run "$RD" $RES --id demo-browser --title "Public-demo browser suites against the packaged server (six suites)" $BOTH \
        --scope package --tree "$T" --artifact "$PKG/SHA256SUMS" --parse results -- bash "$D/browser.sh"
      PORT=$PORT bash "$PKG/deploy/ctl.sh" stop "$D/run" > "$D/browser/ctl-stop.txt" 2>&1
    else
      unavail demo-package-gate "Public-demo package gate" "packaging failed: see the demo-package check" "fix packaging and rerun the demo stage"
    fi
  fi
  ;;
bundle)
  note bundle
  mkdir -p "$WORK/shim" "$WORK/bundles"
  printf '#!/bin/sh\nif [ "$1" = build ]; then shift; exec /usr/bin/docker build --network none "$@"; fi\nexec /usr/bin/docker "$@"\n' > "$WORK/shim/docker"
  chmod +x "$WORK/shim/docker"
  $RT run "$RD" $RES --id staging-bundle --title "Private-staging bundle from this tree (the tree's own build_bundle.sh --tree, offline Docker build)" $BOTH \
    --scope bundle --tree "$T" -- env PATH="$WORK/shim:$PATH" bash deploy/aws/private-staging/staging/build_bundle.sh --tree "$TREE" "$WORK/bundles" \
    --timings "$WORK/bundle-timings.jsonl"
  ;;
report)
  note report
  B=$(ls "$WORK"/bundles/flh-staging-*.tar 2>/dev/null | head -1)
  if [ -z "$B" ] || [ -z "${FLH_ROLLBACK_BUNDLE:-}" ]; then
    unavail release-report "Release report for local-rehearsal" "no candidate bundle or FLH_ROLLBACK_BUNDLE unset" "build the bundle and set FLH_ROLLBACK_BUNDLE/FLH_ROLLBACK_SHA256"
  else
    rm -rf "$WORK/report"
    $RT run "$RD" $RES --id release-report --title "release_report.py collect --target local-rehearsal (bundle, rollback, suites, preflight)" $BOTH \
      --scope bundle --tree "$T" --artifact "$B" -- python3 -I scripts/release/release_report.py collect --candidate "$B" \
      --candidate-sha256 "$(sha256sum "$B" | cut -c1-64)" --rollback "$FLH_ROLLBACK_BUNDLE" --rollback-sha256 "$FLH_ROLLBACK_SHA256" \
      --source "$T" --target local-rehearsal --out "$WORK/report"
  fi
  ;;
*) echo "unknown stage $s"; exit 2;;
esac; done
note summary
$RT summary "$RD" --width 100
