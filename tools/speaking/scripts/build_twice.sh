#!/bin/bash
# Reproducible-build check: build the CPU image twice from requirements-cpu.lock
# (the second time without cache) and compare what matters for transcripts: the
# installed packages and the deployment_id of each pinned model.
#
#   bash tools/speaking/scripts/build_twice.sh SOURCES_DIR OUT_DIR
#
# SOURCES_DIR holds the fetched, verified models (python -m flh_speaking fetch).
# Image IDs differ between builds (layer timestamps); they are recorded, not compared.
set -euo pipefail
R=$(cd "$(dirname "$0")/.." && pwd -P)
SRC=${1:?usage: build_twice.sh SOURCES_DIR OUT_DIR}; OUT=${2:?usage: build_twice.sh SOURCES_DIR OUT_DIR}
mkdir -p "$OUT"
MODELS="whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb whisper-small/973afd24965f72e36ca33b3055d56a652f456b4d"
for t in a b; do
  extra=""; [ $t = b ] && extra="--no-cache"
  docker build $extra --build-arg TORCH_INDEX=cpu -t flh-speaking:cpu-check$t "$R" > "$OUT/build-$t.log" 2>&1
  docker run --rm --network none --memory 512m --entrypoint pip flh-speaking:cpu-check$t freeze --all > "$OUT/freeze-$t.txt"
  : > "$OUT/ids-$t.txt"
  for m in $MODELS; do
    docker run --rm --network none --memory 1g -v "$SRC":/sources:ro flh-speaking:cpu-check$t manifest --model /sources/openai/$m \
      | python3 -I -c "import json,sys; print(json.load(sys.stdin)['deployment_id'])" >> "$OUT/ids-$t.txt"
  done
  docker image inspect -f '{{.Id}}' flh-speaking:cpu-check$t > "$OUT/image-$t.txt"
done
diff "$OUT/freeze-a.txt" "$OUT/freeze-b.txt" && diff "$OUT/ids-a.txt" "$OUT/ids-b.txt" && echo "same packages and deployment_ids:" && cat "$OUT/ids-a.txt"
