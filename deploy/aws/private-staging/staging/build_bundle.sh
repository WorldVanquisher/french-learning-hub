#!/bin/bash
# Build the deployable staging bundle from one integrated candidate tree.
#
#   build_bundle.sh TREE OUT_DIR [--repro]
#
# TREE is a disposable integration tree (never a live worktree). The bundle is
# what the staging host installs, and what the local stand-in rehearsal runs:
#   image.tar                   docker save of flh-staging:<tree12> (linux/amd64)
#   repo/compose.yaml, repo/scripts/daily/*, repo/scripts/release/restore_write_check.py,
#   repo/scripts/validation/v1_rehearsal/snapshot.py, repo/docs/RELEASE.md, repo/docs/DAILY_USE.md
#   staging.override.yaml       isolated-mode override: the bundle's image, no build
#   VERSION.json                tree id, manifest digest, image id, server/web digests
#   SHA256SUMS                  every file above
# --repro builds the image a second time without cache and compares the server
# binary and the web files byte for byte (image IDs differ by design: layer
# timestamps). No push, no registry, no AWS call; the daily image and project
# are never touched (names are flh-staging*).
set -euo pipefail
TREE=$(realpath "${1:?tree}")
OUT=$(realpath -m "${2:?out dir}")
REPRO=${3:-}
R=~/flh-handoff/release-20261117T042813Z
[ ! -e "$OUT" ] || { echo "refused: $OUT exists" >&2; exit 2; }
[ -f "$TREE/Dockerfile" ] && [ -f "$TREE/compose.yaml" ] || { echo "refused: $TREE is not a repository tree" >&2; exit 2; }
case "$TREE" in "$HOME"/workspace/*) echo "refused: build from a disposable integration tree, not a worktree" >&2; exit 2 ;; esac
export TMPDIR=${TMPDIR:-$R/tmp}
TID=$(python3 -I "$R/integration/candidates.py" tree-id "$TREE")
TAG=flh-staging:${TID:0:12}
mkdir -p "$OUT/repo"
echo "tree $TID -> image $TAG"
t0=$SECONDS
docker build -q -t "$TAG" "$TREE" > "$OUT/.build-id"
echo "built in $((SECONDS - t0)) s"
IMAGE_ID=$(docker image inspect -f '{{.Id}}' "$TAG")
digest_image() { # TAG OUTPREFIX -> server sha256, web tree sha256
  local c; c=$(docker create "$1")
  docker cp -q "$c:/app/server" "$2-server" && docker cp -q "$c:/app/web" "$2-web"
  docker rm -f "$c" > /dev/null
  sha256sum "$2-server" | cut -d' ' -f1
  (cd "$2-web" && find . -type f | LC_ALL=C sort | xargs sha256sum) | sha256sum | cut -d' ' -f1
}
mapfile -t D1 < <(digest_image "$TAG" "$TMPDIR/bundle-a")
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
if [ "$REPRO" = --repro ]; then
  docker build -q --no-cache -t "flh-staging-repro:${TID:0:12}" "$TREE" > /dev/null
  mapfile -t D2 < <(digest_image "flh-staging-repro:${TID:0:12}" "$TMPDIR/bundle-b")
  RID=$(docker image inspect -f '{{.Id}}' "flh-staging-repro:${TID:0:12}")
  docker image rm -f "flh-staging-repro:${TID:0:12}" > /dev/null
  same=false; [ "${D1[0]}" = "${D2[0]}" ] && [ "${D1[1]}" = "${D2[1]}" ] && same=true
  REPRO_JSON="{\"no_cache_rebuild_image_id\": \"$RID\", \"server_sha256\": \"${D2[0]}\", \"web_files_sha256\": \"${D2[1]}\", \"identical_server_and_web\": $same}"
  echo "reproducible server and web: $same"
fi
rm -rf "$TMPDIR/bundle-a-"* "$TMPDIR/bundle-b-"*
MAN=$(python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import candidates, lanes; print(candidates.manifest_digest(lanes.scan(sys.argv[2])))' "$R/integration" "$TREE" 2>/dev/null || true)
cat > "$OUT/VERSION.json" <<JSON
{
 "bundle": "flh-staging",
 "tree_id": "$TID",
 "manifest_sha256": "$MAN",
 "image_tag": "$TAG",
 "image_id": "$IMAGE_ID",
 "image_tar_sha256": "$(sha256sum "$OUT/image.tar" | cut -d' ' -f1)",
 "platform": "linux/amd64",
 "server_sha256": "${D1[0]}",
 "web_files_sha256": "${D1[1]}",
 "reproducibility": $REPRO_JSON,
 "built_at": "$(date -u +%FT%TZ)"
}
JSON
rm -f "$OUT/.build-id"
(cd "$OUT" && find . -type f ! -name SHA256SUMS | LC_ALL=C sort | xargs sha256sum > SHA256SUMS)
find "$R/integration" -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
cat "$OUT/VERSION.json"
