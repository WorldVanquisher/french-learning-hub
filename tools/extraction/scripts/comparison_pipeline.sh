#!/usr/bin/env bash
# Offline, deterministic regeneration of everything the extractor comparison
# needs, up to (not including) any real model or provider run.
#
#   bash scripts/comparison_pipeline.sh OUT_DIR [VALUES.json]
#
# Builds extraction-render, regenerates the datasets, the production-input
# probes and the paired cue challenge slice, runs every offline check, pins the
# comparison matrix, reproduces the category shortcut, demonstrates the paired
# metric and the parsing accounting, builds the readiness package (placeholder
# account values unless VALUES.json is given) and writes OUT_DIR/experiment-manifest.json.
# No network, no provider call, no AWS call, no training. Logs stay in OUT_DIR.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${1:?usage: comparison_pipeline.sh OUT_DIR [VALUES.json]}
VALUES=${2:-}
mkdir -p "$OUT/bin" "$OUT/rd" "$OUT/evidence"
OUT=$(cd "$OUT" && pwd)
B="$OUT/bin/extraction-render"
log() { printf '== %s\n' "$*"; }
run() { "$@" > "$OUT/last.log" 2>&1 || { tail -20 "$OUT/last.log"; exit 1; }; tail -c 600 "$OUT/last.log"; echo; }

log "build extraction-render"
(cd ../.. && go build -o "$B" ./cmd/extraction-render)
log "datasets"
run python3 -I -B authoring/generate_train.py "$OUT/train"
run python3 -I -B authoring/generate_eval.py "$OUT/eval"
run python3 -I -B authoring/generate_increment.py "$OUT/inc"
run python3 -I -B authoring/build_boundary.py "$OUT/boundary"
run python3 -I -B authoring/generate_challenge.py "$OUT/chl"
log "render, analyze, probes"
for f in train/candidates inc/increment_candidates eval/eval_candidates chl/challenge_candidates; do
  "$B" render -in "$OUT/$f.jsonl" -out "$OUT/$(basename "$f")-rendered.jsonl"
done
"$B" analyze -in "$OUT/eval/eval_candidates.jsonl" -out "$OUT/eval-analyses.jsonl"
run python3 -B -m flh_extraction probe --eval "$OUT/eval/eval_candidates.jsonl" --analyses "$OUT/eval-analyses.jsonl" --variant rb --out "$OUT/probe-rb.jsonl"
run python3 -B -m flh_extraction probe --eval "$OUT/eval/eval_candidates.jsonl" --analyses "$OUT/eval-analyses.jsonl" --variant swap --out "$OUT/probe-swap.jsonl"
"$B" render -in "$OUT/probe-rb.jsonl" -out "$OUT/probe-rb-rendered.jsonl"
log "SFT files"
run python3 -B -m flh_extraction sft --candidates "$OUT/train/candidates.jsonl" "$OUT/inc/increment_candidates.jsonl" \
  --rendered "$OUT/candidates-rendered.jsonl" "$OUT/increment_candidates-rendered.jsonl" \
  --out "$OUT/sft-v2-all.jsonl" --out-train "$OUT/rd/sft-train.jsonl" --out-dev "$OUT/rd/sft-dev.jsonl"
log "1 shortcut reproduction"
run python3 -B -m flh_extraction shortcut-repro --eval "$OUT/eval/eval_candidates.jsonl" --probe-rb "$OUT/probe-rb.jsonl" \
  --probe-swap "$OUT/probe-swap.jsonl" --render "$B" --out "$OUT/evidence/shortcut"
log "3 challenge check"
"$B" expected -in "$OUT/chl/challenge_candidates.jsonl" -out "$OUT/chl-validated.jsonl"
run python3 -B -m flh_extraction challenge-check --challenge "$OUT/chl/challenge_candidates.jsonl" \
  --train "$OUT/train/candidates.jsonl" "$OUT/inc/increment_candidates.jsonl" --eval "$OUT/eval/eval_candidates.jsonl" \
  --boundary "$OUT/boundary/boundary_cases_v1.jsonl" --validated "$OUT/chl-validated.jsonl" --out "$OUT/evidence/challenge-check.json"
log "4 review packets"
run python3 -B -m flh_extraction review-packet --base "$OUT/train/candidates.jsonl" --increment "$OUT/inc/increment_candidates.jsonl" \
  --probe "$OUT/probe-rb.jsonl" --out "$OUT/evidence/review-packet-v2" --challenge "$OUT/chl/challenge_candidates.jsonl" \
  --v3-out "$OUT/evidence/review-packet-v3"
log "5 paired consistency"
run python3 -B -m flh_extraction paired-demo --challenge "$OUT/chl/challenge_candidates.jsonl" --render "$B" --out "$OUT/evidence/paired"
log "6 comparison slice and matrix"
run python3 -B -m flh_extraction comparison-slice --eval "$OUT/eval/eval_candidates.jsonl" --probe-rb "$OUT/probe-rb.jsonl" \
  --challenge "$OUT/chl/challenge_candidates.jsonl" --rendered "$OUT/eval_candidates-rendered.jsonl" "$OUT/probe-rb-rendered.jsonl" \
  "$OUT/challenge_candidates-rendered.jsonl" --out "$OUT/slice"
run python3 -B -m flh_extraction comparison-matrix --slice-dir "$OUT/slice" --rendered "$OUT/eval_candidates-rendered.jsonl" \
  --repo ../.. --out "$OUT/slice/comparison-matrix.json"
log "8 parsing fixture through compare"
run python3 -B -m flh_extraction parsing-fixture --slice "$OUT/slice/comparison-slice.jsonl" --out "$OUT/fixture-untuned.jsonl" \
  --expect "$OUT/evidence/parsing-fixture-expect.json"
run python3 -B -m flh_extraction compare --matrix "$OUT/slice/comparison-matrix.json" --slice "$OUT/slice/comparison-slice.jsonl" \
  --render "$B" --predictions "qwen3.5-4b-untuned=$OUT/fixture-untuned.jsonl" --out "$OUT/evidence/parsing-fixture-compare"
python3 -B - "$OUT" <<'EOF'
import json, sys
o = sys.argv[1]
got = json.load(open(f"{o}/evidence/parsing-fixture-compare.json"))["systems"]["qwen3.5-4b-untuned"]["rows"]
want = json.load(open(f"{o}/evidence/parsing-fixture-expect.json"))
assert got["status_counts"] == want["status_counts"] and got["unknown_id_rows"] == want["unknown_id_rows"], (got, want)
assert sum(got["status_counts"].values()) == got["references"]
print("parsing fixture: every status equals the injected count;", got["references"], "rows")
EOF
log "11 decision report (one fixture system measured: must be PENDING)"
set +e
python3 -B -m flh_extraction decision-report --comparison "$OUT/evidence/parsing-fixture-compare.json" \
  --review review/review-packet-v2.jsonl review/review-packet-v3.jsonl --out "$OUT/evidence/decision-fixture" > "$OUT/last.log" 2>&1
code=$?
set -e
cat "$OUT/last.log"
[ "$code" = 3 ] || { echo "expected PENDING (exit 3), got $code"; exit 1; }
log "10 readiness package (placeholders unless VALUES.json)"
cp "$OUT/slice/comparison-prompts.jsonl" "$OUT/rd/"
run python3 -B ../../deploy/aws/sagemaker-extractor/build_readiness.py "$OUT/rd" "$OUT/readiness" ${VALUES:+"$VALUES"}
log "7 model assets (exit 3 = tokenizer files missing; never substituted)"
set +e
python3 -B scripts/check_model_assets.py --sums configs/qwen3.5-4b-851bf6e8.sha256 ${ASSET_DIRS:-} --out "$OUT/evidence/asset-check.json"
set -e
log "experiment manifest"
run python3 -B -m flh_extraction manifest --file \
  "train=$OUT/train/candidates.jsonl" "increment_v2=$OUT/inc/increment_candidates.jsonl" "eval_frozen=$OUT/eval/eval_candidates.jsonl" \
  "boundary=$OUT/boundary/boundary_cases_v1.jsonl" "challenge_v1=$OUT/chl/challenge_candidates.jsonl" "probe_rb=$OUT/probe-rb.jsonl" \
  "probe_swap=$OUT/probe-swap.jsonl" "sft_train=$OUT/rd/sft-train.jsonl" "sft_dev=$OUT/rd/sft-dev.jsonl" \
  "comparison_slice=$OUT/slice/comparison-slice.jsonl" "comparison_inputs=$OUT/slice/comparison-inputs.jsonl" \
  "comparison_prompts=$OUT/slice/comparison-prompts.jsonl" "prompts_shard_a=$OUT/readiness/prompts/a/eval-prompts.jsonl" \
  "prompts_shard_b=$OUT/readiness/prompts/b/eval-prompts.jsonl" \
  --generator authoring/generate_train.py authoring/generate_eval.py authoring/generate_increment.py authoring/generate_challenge.py \
  authoring/bank_challenge_v1.py authoring/challenge_v1_rule_based.json authoring/increment_v2_rule_based.json \
  configs/sft-qwen3.5-4b-lora.json configs/sft-qwen3.5-4b-lora-smoke.json configs/qwen3.5-4b-851bf6e8.sha256 requirements-train.txt \
  --out "$OUT/experiment-manifest.json"
python3 -B - "$OUT" <<'EOF'
import json, sys
o = sys.argv[1]
m = json.load(open(f"{o}/experiment-manifest.json"))
mx = json.load(open(f"{o}/slice/comparison-matrix.json"))
im = json.load(open(f"{o}/readiness/input-manifest.json"))
m["comparison_matrix_sha256"] = mx["matrix_sha256"]
m["scoring_version_sha256"] = mx["scoring_version"]["sha256"]
m["output_schema_sha256"] = mx["output_schema"]["sha256"]
m["readiness_input_manifest_sha256"] = im["manifest_sha256"]
m["real_runs_performed"] = 0
json.dump(m, open(f"{o}/experiment-manifest.json", "w"), indent=2, sort_keys=True)
print(json.dumps({k: m[k] for k in ("manifest_sha256", "comparison_matrix_sha256", "scoring_version_sha256", "readiness_input_manifest_sha256")}))
EOF
log "done: $OUT"
