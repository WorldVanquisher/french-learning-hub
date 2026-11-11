#!/usr/bin/env bash
# First untuned run of a base model on a fixed 50-item subset of the frozen
# evaluation set: predict, production validation, harness, four categories.
#
#   bash scripts/untuned_baseline.sh MODEL_DIR OUT_DIR [PROFILE]
#
# MODEL_DIR  local weights at the profile's pinned revision (never downloaded here)
# PROFILE    flh_extraction/models.py profile (default qwen3.5-4b)
# Needs: EVAL (eval_candidates.jsonl), PROMPTS (inputs-only eval prompts) and
# RENDER (extraction-render binary), all generated as in TRAINING_RUNBOOK.md §2.
# No network, no provider call, no training; the evaluation file is not modified.
set -euo pipefail
cd "$(dirname "$0")/.."
MODEL=${1:?usage: untuned_baseline.sh MODEL_DIR OUT_DIR [PROFILE]}
OUT=${2:?usage: untuned_baseline.sh MODEL_DIR OUT_DIR [PROFILE]}
PROFILE=${3:-qwen3.5-4b}
: "${EVAL:?set EVAL=path/to/eval_candidates.jsonl}" "${PROMPTS:?set PROMPTS=path/to/eval-prompts-inputs-only.jsonl}" "${RENDER:?set RENDER=path/to/extraction-render}"
mkdir -p "$OUT"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python3 -B scripts/select_eval_subset.py "$EVAL" "$PROMPTS" "$OUT/subset"
python3 -B -m flh_extraction.predict --model "$MODEL" --profile "$PROFILE" --prompts "$OUT/subset/prompts.jsonl" \
  --candidates "$OUT/subset/candidates.jsonl" --out "$OUT/predictions.jsonl" --max-new-tokens "${MAX_NEW_TOKENS:-512}"
"$RENDER" validate -in "$OUT/predictions.jsonl" -out "$OUT/validated.jsonl"
python3 -B -m flh_extraction evaluate --refs "$OUT/subset/candidates.jsonl" --results "$OUT/validated.jsonl" \
  --title "Untuned $PROFILE, frozen eval subset (50)" --out "$OUT/report"
python3 -B -m flh_extraction categories --refs "$OUT/subset/candidates.jsonl" --results "$OUT/validated.jsonl" \
  --report "$OUT/report.json" --title "Untuned $PROFILE, frozen eval subset (50): categories" --out "$OUT/categories"
