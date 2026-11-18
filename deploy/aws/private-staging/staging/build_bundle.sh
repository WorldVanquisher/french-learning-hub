#!/bin/bash
# Build the deployable staging bundle for ONE pinned application revision.
#
#   build_bundle.sh --git REPO_DIR REV OUT_PARENT [--repro] [--no-cache]
#       Owner path: exports REV with `git archive` into a disposable tree, pins
#       the commit (git rev-parse REV^{commit}) and checks that the exported
#       tree hashes to REV^{tree}.
#   build_bundle.sh --tree TREE_DIR OUT_PARENT [--expect-tree TREE_SHA] [--commit SHA] [--repro] [--no-cache]
#       Rehearsal path: an already exported tree (never a Git checkout). With
#       --expect-tree the build stops unless TREE_DIR hashes to that Git tree.
#
# Writes, under OUT_PARENT (which must exist):
#   flh-staging-<tree12>/            the bundle
#     image.tar                      docker save of flh-staging:<tree12> (linux/amd64),
#                                    labelled with the commit and the tree ID
#     repo/compose.yaml, repo/scripts/daily/*, repo/scripts/release/restore_write_check.py,
#     repo/scripts/validation/v1_rehearsal/snapshot.py, repo/docs/RELEASE.md, repo/docs/DAILY_USE.md
#     staging.override.yaml          isolated-mode override: the bundle's image, never a build
#     MANIFEST.json                  STABLE identity: revision (commit, tree, content digest),
#                                    image tag and labels, server and web digests,
#                                    migration ledger, every file above
#     BUILD.json                     this build only: image ID, image.tar SHA-256, time, tools
#     SHA256SUMS                     every file above
#   flh-staging-<tree12>.tar         the transfer file (deterministic tar of the directory)
#   flh-staging-<tree12>.tar.sha256  its SHA-256 (sha256sum format)
# Then verifies the result with the host tool (host/flh-staging-bundle verify).
#
# --repro additionally rebuilds without cache and records whether the server
# binary and the web files are byte-identical (BUILD.json "reproducibility").
# --no-cache builds the bundle's image itself without cache.
# No push, no registry, no AWS call. Image and project names are flh-staging*;
# the daily image french-learning-hub:local and its project are never touched.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd -P)
die() { echo "build_bundle: $*" >&2; exit 2; }
MODE=${1:-}
case "$MODE" in
  --git) [ $# -ge 4 ] || die "usage: build_bundle.sh --git REPO_DIR REV OUT_PARENT [--repro] [--no-cache]"
         GIT_REPO=$2; REV=$3; OUT_PARENT=$4; shift 4 ;;
  --tree) [ $# -ge 3 ] || die "usage: build_bundle.sh --tree TREE_DIR OUT_PARENT [--expect-tree SHA] [--commit SHA] [--repro] [--no-cache]"
          TREE=$2; OUT_PARENT=$3; shift 3 ;;
  *) die "usage: build_bundle.sh --git REPO_DIR REV OUT_PARENT | --tree TREE_DIR OUT_PARENT [options]" ;;
esac
EXPECT_TREE=; COMMIT=-; REPRO=0; NOCACHE=()
while [ $# -gt 0 ]; do
  case "$1" in
    --expect-tree) EXPECT_TREE=${2:?}; shift 2 ;;
    --commit) COMMIT=${2:?}; shift 2 ;;
    --repro) REPRO=1; shift ;;
    --no-cache) NOCACHE=(--no-cache); shift ;;
    *) die "unknown option: $1" ;;
  esac
done
[ -d "$OUT_PARENT" ] || die "OUT_PARENT does not exist: $OUT_PARENT"
OUT_PARENT=$(realpath "$OUT_PARENT")
for t in docker python3 sha256sum tar; do command -v "$t" > /dev/null || die "missing prerequisite: $t"; done
WORK=$(mktemp -d "${TMPDIR:-/tmp}/flh-bundle.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

if [ "$MODE" = --git ]; then
  command -v git > /dev/null || die "missing prerequisite: git"
  COMMIT=$(git -C "$GIT_REPO" rev-parse --verify "$REV^{commit}") || die "not a commit: $REV"
  EXPECT_TREE=$(git -C "$GIT_REPO" rev-parse --verify "$REV^{tree}")
  TREE="$WORK/tree"
  mkdir "$TREE"
  git -C "$GIT_REPO" archive --format=tar "$COMMIT" | tar -x -C "$TREE"
  echo "exported $REV = commit $COMMIT (tree $EXPECT_TREE)"
fi
TREE=$(realpath "$TREE")
python3 -I "$HERE/bundle_identity.py" tree-id "$TREE" > "$WORK/identity.json"
TID=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["tree_id"])' "$WORK/identity.json")
if [ -n "$EXPECT_TREE" ] && [ "$TID" != "$EXPECT_TREE" ]; then
  die "the tree hashes to $TID, not the expected $EXPECT_TREE: refusing to build an unpinned revision"
fi
NAME=flh-staging-${TID:0:12}
TAG=flh-staging:${TID:0:12}
OUT="$OUT_PARENT/$NAME"
for p in "$OUT" "$OUT.tar" "$OUT.tar.sha256"; do [ ! -e "$p" ] || die "refused: $p exists"; done
LABEL_REV=$([ "$COMMIT" = - ] && echo "" || echo "$COMMIT")
echo "tree $TID -> image $TAG (commit ${LABEL_REV:-none: tree-only rehearsal})"

build() { # build TAG [extra docker build args]
  local tag=$1; shift
  docker build -q --platform linux/amd64 "$@" \
    --label "org.opencontainers.image.revision=$LABEL_REV" \
    --label "org.flh.staging.tree-id=$TID" -t "$tag" "$TREE" > /dev/null
}
digest_image() { # TAG PREFIX -> line 1: server sha256, line 2: web files digest
  local c; c=$(docker create "$1")
  docker cp -q "$c:/app/server" "$2-server" && docker cp -q "$c:/app/web" "$2-web"
  docker rm -f "$c" > /dev/null
  sha256sum "$2-server" | cut -d' ' -f1
  (cd "$2-web" && find . -type f | LC_ALL=C sort | xargs sha256sum) | sha256sum | cut -d' ' -f1
}
t0=$SECONDS
build "$TAG" ${NOCACHE[@]+"${NOCACHE[@]}"}
echo "built in $((SECONDS - t0)) s"
IMAGE_ID=$(docker image inspect -f '{{.Id}}' "$TAG")
mapfile -t D1 < <(digest_image "$TAG" "$WORK/a")
mkdir -p "$OUT/repo"
docker save "$TAG" -o "$OUT/image.tar"
for f in compose.yaml scripts/daily/flh-daily.sh scripts/daily/daily.env.example scripts/release/restore_write_check.py \
         scripts/validation/v1_rehearsal/snapshot.py docs/RELEASE.md docs/DAILY_USE.md; do
  install -D -m "$(stat -c %a "$TREE/$f")" "$TREE/$f" "$OUT/repo/$f"
done
cat > "$OUT/staging.override.yaml" <<YAML
# Staging bundle override: run the bundle's image, never build on the host.
services:
  app:
    image: $TAG
    build: !reset null
YAML
REPRO_JSON=null
if [ "$REPRO" = 1 ]; then
  build "flh-staging-repro:${TID:0:12}" --no-cache
  mapfile -t D2 < <(digest_image "flh-staging-repro:${TID:0:12}" "$WORK/b")
  RID=$(docker image inspect -f '{{.Id}}' "flh-staging-repro:${TID:0:12}")
  docker image rm -f "flh-staging-repro:${TID:0:12}" > /dev/null
  same=false; [ "${D1[0]}" = "${D2[0]}" ] && [ "${D1[1]}" = "${D2[1]}" ] && same=true
  REPRO_JSON="{\"no_cache_rebuild_image_id\": \"$RID\", \"server_sha256\": \"${D2[0]}\", \"web_files_sha256\": \"${D2[1]}\", \"identical_server_and_web\": $same}"
  echo "reproducible server and web: $same"
fi
python3 -I "$HERE/bundle_identity.py" write-manifest "$OUT" --identity "$WORK/identity.json" --commit "$COMMIT" \
  --image-tag "$TAG" --server-sha256 "${D1[0]}" --web-sha256 "${D1[1]}"
cat > "$OUT/BUILD.json" <<JSON
{
 "manifest_sha256": "$(sha256sum "$OUT/MANIFEST.json" | cut -d' ' -f1)",
 "image_id": "$IMAGE_ID",
 "image_tar_sha256": "$(sha256sum "$OUT/image.tar" | cut -d' ' -f1)",
 "built_at": "$(date -u +%FT%TZ)",
 "docker_server": "$(docker version -f '{{.Server.Version}}' 2> /dev/null || echo unknown)",
 "no_cache": $([ ${#NOCACHE[@]} -gt 0 ] && echo true || echo false),
 "reproducibility": $REPRO_JSON
}
JSON
(cd "$OUT" && find . -type f ! -name SHA256SUMS | sed 's#^\./##' | LC_ALL=C sort | xargs sha256sum > SHA256SUMS)
chmod -R a-w "$OUT"
# Deterministic transfer tar: sorted names, numeric root ownership, fixed mtime.
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime=@0 --format=posix \
  --pax-option=exthdr.name=%d/PaxHeaders/%f,delete=atime,delete=ctime \
  -C "$OUT_PARENT" -cf "$OUT.tar" "$NAME"
(cd "$OUT_PARENT" && sha256sum "$NAME.tar" > "$NAME.tar.sha256")
python3 -I "$HERE/host/flh-staging-bundle" verify --dir "$OUT"
python3 -I "$HERE/host/flh-staging-bundle" verify "$OUT.tar" --sha256 "$(cut -d' ' -f1 "$OUT.tar.sha256")" --scratch "$WORK"
echo "bundle:   $OUT"
echo "transfer: $OUT.tar"
echo "sha256:   $(cut -d' ' -f1 "$OUT.tar.sha256")"
