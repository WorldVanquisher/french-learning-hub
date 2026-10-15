#!/usr/bin/env bash
# FLH-076 portable release package for the read-only public demo.
#
#   bash scripts/demo/flh076/package.sh --artifact DIR --revision LABEL --label NAME --out PARENT_DIR \
#        [--expected-deployment DEPLOYMENT_ID]
#
# --revision is the source-revision label the human owner supplies (no Git is
# run). A model artifact becomes a CANDIDATE only with --expected-deployment
# equal to its model id, which must look like a pinned E5 deployment; a
# mechanical artifact becomes a package named ...-BLOCKED. Output:
# PARENT/flh-public-demo-NAME[-BLOCKED]/ and a .tar.gz with its .sha256.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
ARTIFACT= REVISION= LABEL= OUT= EXPECTED=
while [ $# -gt 0 ]; do
  case "$1" in
    --artifact) ARTIFACT=$2 ;; --revision) REVISION=$2 ;; --label) LABEL=$2 ;; --out) OUT=$2 ;;
    --expected-deployment) EXPECTED=$2 ;; *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
  shift 2
done
[ -n "$ARTIFACT" ] && [ -n "$REVISION" ] && [ -n "$LABEL" ] && [ -n "$OUT" ] || { echo "usage: see header" >&2; exit 2; }
[[ "$LABEL" =~ ^[A-Za-z0-9._-]{1,40}$ ]] || { echo "refused: label must be [A-Za-z0-9._-]{1,40}" >&2; exit 2; }
[[ "$REVISION" =~ ^[A-Za-z0-9._/+-]{1,80}$ ]] || { echo "refused: revision label must be [A-Za-z0-9._/+-]{1,80}" >&2; exit 2; }
case "$OUT" in /*) ;; *) echo "refused: --out must be absolute" >&2; exit 2 ;; esac
case "$OUT/" in "$REPO"/*) echo "refused: --out must be outside the repository" >&2; exit 2 ;; esac
# SHA-256 lines ("HASH  PATH"): sha256sum (GNU coreutils, usual on Linux), else
# shasum -a 256 (macOS, Perl). Both write the format validate-release.sh checks.
if command -v sha256sum >/dev/null 2>&1; then sha256() { sha256sum "$@"; }
elif command -v shasum >/dev/null 2>&1; then sha256() { shasum -a 256 "$@"; }
else echo "refused: no SHA-256 tool (need sha256sum or shasum)" >&2; exit 2; fi
ARTIFACT=$(cd "$ARTIFACT" && pwd)
[ -z "$(find "$ARTIFACT" -type l)" ] || { echo "refused: the artifact contains symbolic links" >&2; exit 2; }

TOOLS=$(mktemp -d)
trap 'rm -rf "$TOOLS"' EXIT
(cd "$REPO" && go build -o "$TOOLS/prepare" ./scripts/demo/flh073/prepare)
"$TOOLS/prepare" validate -artifact "$ARTIFACT" > "$TOOLS/validate.json" || { echo "refused: the artifact does not validate" >&2; exit 1; }
set +e; "$TOOLS/prepare" validate -artifact "$ARTIFACT" -release > /dev/null 2>&1; RC=$?; set -e
read -r MODEL SOURCE <<<"$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["model_id"], d["vector_source"])' "$TOOLS/validate.json")"
if [ "$RC" = 3 ]; then
  STATUS=BLOCKED; NAME="flh-public-demo-$LABEL-BLOCKED"
elif [ "$RC" = 0 ]; then
  [[ "$MODEL" =~ ^multilingual-e5-base@[0-9a-f]{40}/flh_e5_role_prefix_v1/[a-z0-9]+/ ]] || { echo "refused: model id $MODEL is not a pinned E5 deployment" >&2; exit 1; }
  [ "$EXPECTED" = "$MODEL" ] || { echo "refused: --expected-deployment must equal the artifact's model id ($MODEL)" >&2; exit 1; }
  STATUS=CANDIDATE; NAME="flh-public-demo-$LABEL"
else
  echo "refused: release validation exit $RC" >&2; exit 1
fi
FINAL="$OUT/$NAME"
[ ! -e "$FINAL" ] && [ ! -e "$FINAL.tar.gz" ] || { echo "refused: $FINAL already exists" >&2; exit 2; }
mkdir -p "$OUT"
STAGE=$(mktemp -d "$OUT/.$NAME.partial-XXXXXX")
trap 'rm -rf "$TOOLS" "$STAGE"' EXIT
chmod 755 "$STAGE"

for arch in amd64 arm64; do
  mkdir -p "$STAGE/bin/linux-$arch"
  (cd "$REPO" && CGO_ENABLED=0 GOOS=linux GOARCH=$arch go build -trimpath -o "$STAGE/bin/linux-$arch/flh-server" ./cmd/server)
  (cd "$REPO" && CGO_ENABLED=0 GOOS=linux GOARCH=$arch go build -trimpath -o "$STAGE/bin/linux-$arch/flh-prepare" ./scripts/demo/flh073/prepare)
done
mkdir -p "$STAGE/artifact" "$STAGE/deploy"
for f in manifest.json demo.db vectors.json fixtures.json provenance.json; do
  [ -f "$ARTIFACT/$f" ] && cp "$ARTIFACT/$f" "$STAGE/artifact/$f"
done
extra=$(cd "$ARTIFACT" && ls -A | grep -v -E '^(manifest|vectors|fixtures|provenance)\.json$|^demo\.db$' || true)
[ -z "$extra" ] || { echo "refused: unexpected artifact files: $extra" >&2; exit 1; }
(cd "$REPO/web" && VITE_FLH_PUBLIC_DEMO=1 ./node_modules/.bin/vite build --outDir "$STAGE/web" --emptyOutDir > "$TOOLS/web-build.log" 2>&1)
cp "$REPO/scripts/demo/flh076/deploy/flh-public-demo.service.example" "$REPO/scripts/demo/flh076/deploy/nginx-flh-public-demo.conf.example" \
   "$REPO/scripts/demo/flh076/deploy/ctl.sh" "$STAGE/deploy/"
cp "$REPO/scripts/demo/flh076/validate-release.sh" "$STAGE/validate-release.sh"
cp "$REPO/scripts/demo/flh076/PACKAGE_README.md" "$STAGE/README.md"
chmod 755 "$STAGE/validate-release.sh" "$STAGE/deploy/ctl.sh" "$STAGE"/bin/*/*

python3 - "$STAGE" "$ARTIFACT" "$STATUS" "$LABEL" "$REVISION" "$(go version)" <<'PY'
import datetime, hashlib, json, os, sys
stage, artifact, status, label, revision, gover = sys.argv[1:]
m = json.load(open(os.path.join(stage, "artifact/manifest.json")))
prov_path = os.path.join(stage, "artifact/provenance.json")
prov = json.load(open(prov_path)) if os.path.exists(prov_path) else None
release = {
  "schema": "flh076_public_demo_release_v1", "label": label, "source_revision": revision,
  "source_revision_note": "supplied by the human owner; the packaging tool runs no Git",
  "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "go": gover,
  "targets": ["linux/amd64", "linux/arm64"], "release_status": status,
  "artifact": {"version": m["artifact_version"], "manifest_sha256": hashlib.sha256(open(os.path.join(stage, "artifact/manifest.json"), "rb").read()).hexdigest(),
               "vector_source": m["vectors"]["source"], "real_model": m["vectors"]["real_model"], "model_id": m["vectors"]["model_id"],
               "dimensions": m["vectors"]["dimensions"], "release_status": m["release_status"], "domain_fingerprint": m["domain_fingerprint"]["sha256"],
               "fingerprint_version": m["domain_fingerprint"]["version"]},
  "model_provenance": None if prov is None else {"deployment_id": prov["deployment_id"], "base_url": prov["base_url"],
               "plan_sha256": prov["plan_sha256"], "positions": len(prov["positions"]), "posts": prov["accounting"]["used_posts"],
               "probes": prov["accounting"]["used_probes"], "readiness": prov["probes"]},
  "runtime_requirements": {"os": "Linux (amd64 or arm64)", "needs": ["this directory", "a loopback port", "a TLS reverse proxy for public use"],
               "does_not_need": ["an embedding encoder or GPU", "Windows", "Qdrant", "cloud credentials", "any API key", "network egress"]},
  "not_included": ["personal data", "secrets or .env", "model weights", "temporary evidence", "symbolic links"],
}
json.dump(release, open(os.path.join(stage, "RELEASE.json"), "w"), indent=2)
open(os.path.join(stage, "RELEASE.json"), "a").write("\n")
PY

# Content rules, checked on the staged tree before publication.
[ -z "$(find "$STAGE" -type l)" ] || { echo "refused: symbolic links in the package" >&2; exit 1; }
[ -z "$(find "$STAGE" \( -name '.env*' -o -name '*.pem' -o -name '*.key' -o -name '.git' -o -name '*.log' -o -name '.DS_Store' \))" ] || { echo "refused: forbidden file in the package" >&2; exit 1; }
[ "$(find "$STAGE" -name '*.db' | wc -l | tr -d ' ')" = 1 ] || { echo "refused: unexpected database files" >&2; exit 1; }
top=$(cd "$STAGE" && ls -A | LC_ALL=C sort | tr '\n' ' ')
[ "$top" = "README.md RELEASE.json artifact bin deploy validate-release.sh web " ] || { echo "refused: unexpected top-level entries: $top" >&2; exit 1; }
# Written outside the package first, so the list never includes itself.
(cd "$STAGE" && find . -type f | sed 's|^\./||' | LC_ALL=C sort | while IFS= read -r f; do sha256 "$f"; done) > "$TOOLS/SHA256SUMS"
mv "$TOOLS/SHA256SUMS" "$STAGE/SHA256SUMS"
grep -q '  SHA256SUMS$' "$STAGE/SHA256SUMS" && { echo "refused: SHA256SUMS lists itself" >&2; exit 1; }

mv "$STAGE" "$FINAL"
(cd "$OUT" && COPYFILE_DISABLE=1 tar -czf "$NAME.tar.gz" "$NAME" && sha256 "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
trap 'rm -rf "$TOOLS"' EXIT
echo "$STATUS package: $FINAL"
echo "tarball: $OUT/$NAME.tar.gz ($(cut -d' ' -f1 "$OUT/$NAME.tar.gz.sha256"))"
