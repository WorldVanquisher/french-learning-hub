"""Exact prerequisite check for the pinned Qwen3.5-4B tokenizer and weights
(standard library only; no network, no download, no substitution).

  python3 -B scripts/check_model_assets.py --sums configs/qwen3.5-4b-851bf6e8.sha256 \
      --dir DIR [--dir DIR2 …] [--index model.safetensors.index.json] --out REPORT.json

For each purpose it lists the files it needs, where each was found and whether
its SHA-256 equals the pinned value. A file with another hash is reported as
HASH_MISMATCH and never used: a different tokenizer would measure different
token lengths. Weight shards are listed from the pinned index; their hashes
are not pinned (size and presence only).

  purpose "token_lengths"   tokenizer.json, tokenizer_config.json, chat_template.jinja,
                            config.json (vocab.json and merges.txt: pinned, optional)
  purpose "weights"         model.safetensors.index.json and every shard it names

Exit 0 when the token-length files are all present with pinned hashes, 3 when
anything they need is missing or mismatched. The report always ends with the
owner command that fetches exactly the missing files at the pinned revision.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO, REVISION = "Qwen/Qwen3.5-4B", "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
TOKEN_REQUIRED = ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja", "config.json")
TOKEN_OPTIONAL = ("vocab.json", "merges.txt")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_sums(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            h, name = line.split(None, 1)
            out[name.strip()] = h
    return out


def find(name, dirs):
    return [str(Path(d) / name) for d in dirs if (Path(d) / name).is_file()]


def status(name, dirs, pinned):
    found = find(name, dirs)
    if not found:
        return {"file": name, "status": "MISSING", "pinned_sha256": pinned, "found": []}
    rows = [{"path_name": Path(f).parent.name + "/" + name, "sha256": sha(f)} for f in found]
    ok = pinned is None or any(r["sha256"] == pinned for r in rows)
    st = "PRESENT_UNPINNED" if pinned is None else "PRESENT_OK" if ok else "HASH_MISMATCH"
    return {"file": name, "status": st, "pinned_sha256": pinned, "found": rows}


def check(sums, dirs, index=None):
    rep = {"schema": "flh_model_asset_check_v1", "repo": REPO, "revision": REVISION, "searched_dirs": len(dirs),
           "token_lengths": [status(n, dirs, sums.get(n)) for n in TOKEN_REQUIRED + TOKEN_OPTIONAL]}
    shards = []
    idx = index or next(iter(find("model.safetensors.index.json", dirs)), None)
    if idx and sha(idx) == sums.get("model.safetensors.index.json"):
        shards = sorted(set(json.loads(Path(idx).read_text())["weight_map"].values()))
    rep["weights"] = [status("model.safetensors.index.json", dirs, sums.get("model.safetensors.index.json"))]
    rep["weights"] += [status(s, dirs, None) for s in shards]
    rep["weight_shards_named_by_pinned_index"] = shards
    need = [r for r in rep["token_lengths"] if r["file"] in TOKEN_REQUIRED and r["status"] != "PRESENT_OK"]
    rep["token_lengths_ready"] = not need
    rep["weights_ready"] = bool(shards) and all(r["status"] in ("PRESENT_OK", "PRESENT_UNPINNED") for r in rep["weights"])
    missing = [r["file"] for r in rep["token_lengths"] if r["status"] != "PRESENT_OK"]
    rep["missing_for_token_lengths"] = missing
    # verify_profile.py reads every small file from ONE directory: fetch the whole small set there.
    small = list(TOKEN_REQUIRED + TOKEN_OPTIONAL) + ["model.safetensors.index.json"]
    rep["owner_command"] = None if not missing else (
        f"REPO=$(pwd); D=~/models/qwen3.5-4b-851bf6e8-meta; "
        f"hf download {REPO} {' '.join(small)} --revision {REVISION} --local-dir \"$D\" && "
        "(cd \"$D\" && sha256sum --ignore-missing -c \"$REPO/tools/extraction/configs/qwen3.5-4b-851bf6e8.sha256\")"
        "  # from the repository root; tokenizer files only, no weights")
    rep["then"] = ("python3 -B tools/extraction/scripts/verify_profile.py --profile qwen3.5-4b --meta \"$D\" --sums "
                   "tools/extraction/configs/qwen3.5-4b-851bf6e8.sha256 --tokenizer \"$D\" --sft OUT/rd/sft-train.jsonl "
                   "OUT/rd/sft-dev.jsonl --max-length 1280 --max-new-tokens 512 --out OUT/qwen3.5-4b-verification-tokens.json")
    rep["substitution"] = "refused: no other tokenizer is used for token lengths or masking"
    return rep


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sums", required=True)
    ap.add_argument("--dir", action="append", default=[])
    ap.add_argument("--index")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rep = check(load_sums(a.sums), [d for d in a.dir if Path(d).is_dir()], a.index)
    Path(a.out).write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"token_lengths_ready": rep["token_lengths_ready"], "weights_ready": rep["weights_ready"],
                      "token_files": {r["file"]: r["status"] for r in rep["token_lengths"]},
                      "weights": {r["file"]: r["status"] for r in rep["weights"]}}))
    return 0 if rep["token_lengths_ready"] else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
