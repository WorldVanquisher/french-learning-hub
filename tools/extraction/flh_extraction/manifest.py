"""Reproducible dataset manifests: file hashes, record counts and record hashes."""

import hashlib
import json
from pathlib import Path


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def record_hash(rec):
    return hashlib.sha256(json.dumps(rec, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def build(files, generator_files=()):
    out = {"schema": "flh_extraction_manifest_v1", "files": {}, "generators": {}}
    for name, path in files.items():
        p = Path(path)
        n = None
        if p.suffix == ".jsonl":
            with open(p, encoding="utf-8") as f:
                n = sum(1 for line in f if line.strip())
        out["files"][name] = {"sha256": sha256_file(p), "bytes": p.stat().st_size, "records": n}
    for path in generator_files:
        out["generators"][Path(path).name] = sha256_file(path)
    out["manifest_sha256"] = hashlib.sha256(json.dumps(out["files"], sort_keys=True).encode()).hexdigest()
    return out
