"""The R4 synthetic corpus, its frozen baseline and the current results (offline, synthetic).

  python3 -I -B scripts/r4_corpus.py --freeze-baseline     # once: write fixtures/r4_v1/baseline/ (refuses if present)
  python3 -I -B scripts/r4_corpus.py --write               # (re)write fixtures/r4_v1/corpus/ and current/
  python3 -I -B scripts/r4_corpus.py --check               # regenerate and compare corpus/ and current/ byte for byte
  python3 -I -B scripts/r4_corpus.py --compare [--json]    # what changed between the frozen baseline and current/

``baseline/`` is the untouched result of the merged service on this corpus, frozen before
any R4 change; it is never rewritten. ``current/`` is what the code in this tree returns.
``--compare`` lists, per scenario, the status and summary fields that differ.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from flh_extraction import r4corpus as rc  # noqa: E402
from flh_extraction import service as svc  # noqa: E402

ROOT = os.path.join(HERE, "fixtures", "r4_v1")


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def seal(d: str) -> None:
    rows = []
    for n in sorted(os.listdir(d)):
        if n != "SHA256SUMS":
            with open(os.path.join(d, n), "rb") as fh:
                rows.append(f"{hashlib.sha256(fh.read()).hexdigest()}  {n}\n")
    _write(os.path.join(d, "SHA256SUMS"), "".join(rows))


def write(out: str, results_dir: str) -> None:
    """corpus/ (requests) and RESULTS_DIR/ (responses, summary.json, REPORT.md), each sealed."""
    sc, resp, sm = rc.build()
    dep = svc.manifest(dict(svc.LIMITS))["deployment_id"]
    for s, r in zip(sc, resp):
        _write(os.path.join(out, "corpus", f"{s['name']}.request.json"),
               rc.dumps({"method": "POST", "path": s["route"], "headers": {"Content-Type": "application/json", "X-FLH-Contract": svc.CONTRACT},
                         "body": s["request"]}))
        _write(os.path.join(out, results_dir, f"{s['name']}.response.json"), rc.dumps(r))
    _write(os.path.join(out, results_dir, "summary.json"), rc.dumps({"schema": rc.CORPUS + ".summary", "deployment_id": dep, "scenarios": sm}))
    _write(os.path.join(out, results_dir, "REPORT.md"), rc.report(sm, dep))
    seal(os.path.join(out, "corpus"))
    seal(os.path.join(out, results_dir))


def _same(a: str, b: str) -> list[str]:
    names = sorted(set(os.listdir(a)) | set(os.listdir(b)))
    bad = []
    for n in names:
        pa, pb = os.path.join(a, n), os.path.join(b, n)
        if not (os.path.exists(pa) and os.path.exists(pb)):
            bad.append(n)
            continue
        with open(pa, "rb") as fa, open(pb, "rb") as fb:
            if fa.read() != fb.read():
                bad.append(n)
    return bad


def compare(base: dict, cur: dict) -> list[dict]:
    out = []
    b = {s["name"]: s for s in base["scenarios"]}
    for s in cur["scenarios"]:
        o = b.get(s["name"])
        if o is None:
            out.append({"name": s["name"], "change": "new scenario"})
            continue
        diff = {k: [o.get(k), s.get(k)] for k in sorted(set(o) | set(s)) if o.get(k) != s.get(k) and k != "items"}
        if o.get("items") != s.get("items"):
            diff["items"] = "item list differs"
        if diff:
            out.append({"name": s["name"], "change": diff})
    if base.get("deployment_id") != cur.get("deployment_id"):
        out.insert(0, {"name": "service", "change": {"deployment_id": [base.get("deployment_id"), cur.get("deployment_id")]}})
    return out


def _load(p: str) -> dict:
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--freeze-baseline", action="store_true")
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--compare", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.freeze_baseline:
        if os.path.exists(os.path.join(ROOT, "baseline")):
            raise SystemExit("fixtures/r4_v1/baseline/ exists: the baseline is frozen and is never rewritten")
        write(ROOT, "baseline")
        print("froze fixtures/r4_v1/baseline/")
        return 0
    if a.write:
        for d in ("corpus", "current"):
            shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)
        write(ROOT, "current")
        print("wrote fixtures/r4_v1/corpus/ and current/")
        return 0
    if a.check:
        with tempfile.TemporaryDirectory() as t:
            write(t, "current")
            bad = [f"corpus/{n}" for n in _same(os.path.join(t, "corpus"), os.path.join(ROOT, "corpus"))]
            bad += [f"current/{n}" for n in _same(os.path.join(t, "current"), os.path.join(ROOT, "current"))]
        print("check: corpus/ and current/ equal a fresh run" if not bad else "CHECK FAILED: " + ", ".join(bad))
        return 1 if bad else 0
    ch = compare(_load(os.path.join(ROOT, "baseline", "summary.json")), _load(os.path.join(ROOT, "current", "summary.json")))
    if a.json:
        print(json.dumps(ch, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        print("baseline -> current: " + (f"{len(ch)} change(s)" if ch else "no change"))
        for c in ch:
            print(f"  {c['name']}: {json.dumps(c['change'], ensure_ascii=False, sort_keys=True)[:400]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
