"""Select a deterministic 50-item subset of the frozen evaluation set for a
first untuned run. The evaluation file itself is never modified.

  python3 -B select_eval_subset.py EVAL_CANDIDATES.jsonl EVAL_PROMPTS.jsonl OUT_DIR

The subset makes each reported category measurable:
  - every zero-unit reference (abstention), 20 in eval v1;
  - every fragmentation, duplicate and mixed edge case (splitting, over-extraction);
  - the first 10 two-unit references by id (merging and splitting);
  - singles evenly spaced over the id order to fill 50.
Writes candidates.jsonl, prompts.jsonl (inputs only, in the same order),
ids.txt and subset.json (counts and input hashes).
"""

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

SIZE = 50


def load(p):
    return [json.loads(line) for line in Path(p).read_text(encoding="utf-8").splitlines() if line.strip()]


def select(cands, size=SIZE):
    by_id = sorted(cands, key=lambda r: r["id"])
    zero = [r for r in by_id if not r["expected"]["units"]]
    split = [r for r in by_id if r["meta"].get("case_type") in ("fragmentation", "duplicate", "mixed") and r["expected"]["units"]]
    multi = [r for r in by_id if len(r["expected"]["units"]) == 2 and r["meta"].get("case_type") == "multi_2"][:10]
    chosen = {r["id"] for r in zero + split + multi}
    singles = [r for r in by_id if r["meta"].get("case_type") == "single" and r["id"] not in chosen]
    need = size - len(chosen)
    if need < 0 or need > len(singles):
        raise ValueError(f"cannot fill {size} items (need {need} singles of {len(singles)})")
    step = len(singles) / need if need else 1
    chosen |= {singles[int(k * step)]["id"] for k in range(need)}
    return [r for r in by_id if r["id"] in chosen]


def main(eval_path, prompts_path, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cands = load(eval_path)
    prompts = {p["id"]: p for p in load(prompts_path)}
    subset = select(cands)
    missing = [r["id"] for r in subset if r["id"] not in prompts]
    if missing:
        raise SystemExit(f"prompts missing for {missing[:5]}")
    for name, rows in (("candidates.jsonl", subset), ("prompts.jsonl", [prompts[r["id"]] for r in subset])):
        with open(out / name, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    (out / "ids.txt").write_text("".join(r["id"] + "\n" for r in subset), encoding="utf-8")
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
    info = {"size": len(subset), "eval_sha256": sha(eval_path), "prompts_sha256": sha(prompts_path),
            "by_case": dict(sorted(Counter(r["meta"].get("case_type") for r in subset).items())),
            "zero_unit_refs": sum(1 for r in subset if not r["expected"]["units"]),
            "units_hist": dict(sorted(Counter(len(r["expected"]["units"]) for r in subset).items())),
            "candidates_sha256": sha(out / "candidates.jsonl"), "subset_prompts_sha256": sha(out / "prompts.jsonl")}
    (out / "subset.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(info))


if __name__ == "__main__":
    main(*sys.argv[1:4])
