"""Command line: python -m flh_speaking <command> ...

  fetch      --dest DIR --what whisper-base mls fleurs ...   download and verify pinned files
  check      --dest DIR --what ...                           re-verify pinned files (exit 1 on mismatch)
  prepare    --sources DIR --out DIR                         decode, split and seal the dataset
  prepare-non-french --sources DIR --out DIR                 English + Mandarin FLEURS clips for the not_french probe
  prepare-accent --sources DIR --out DIR                     SLR57 African-accented French test split (CA16)
  evaluate   --model DIR --data DIR --split test --out FILE  transcribe a split and score it
  rescore    --eval FILE --data DIR [--out FILE]             re-apply abstention rules to stored raw outputs
  compare    --a FILE --b FILE --out FILE                    paired comparison of one split
  accept     --base DIR --cand DIR --data DIR --out FILE     acceptance rule (DIRs hold test.json, ood.json, probes.json)
  train      --config FILE --data DIR --base DIR --out DIR   fine-tune (resumable)
  probes     --model DIR --out FILE                          short, silent, noisy, invalid, non-French audio
  serve      --model DIR [--host 127.0.0.1 --port 8765]      local transcription service
  manifest   --model DIR                                     deployment manifest (no model load)
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="flh_speaking")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--dest", required=True)
    f.add_argument("--what", nargs="+", required=True)
    c = sub.add_parser("check")
    c.add_argument("--dest", required=True)
    c.add_argument("--what", nargs="+", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--sources", required=True)
    p.add_argument("--out", required=True)
    pa = sub.add_parser("prepare-accent")
    pa.add_argument("--sources", required=True)
    pa.add_argument("--out", required=True)
    pn = sub.add_parser("prepare-non-french")
    pn.add_argument("--sources", required=True)
    pn.add_argument("--out", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--model", required=True)
    e.add_argument("--data", required=True)
    e.add_argument("--split", required=True)
    e.add_argument("--ids", help="JSON list of ids (default: the whole split)")
    e.add_argument("--out", required=True)
    e.add_argument("--batch", type=int, default=8)
    e.add_argument("--threads", type=int, default=4)
    e.add_argument("--label", default="")
    rs = sub.add_parser("rescore")
    rs.add_argument("--eval", required=True)
    rs.add_argument("--data", required=True)
    rs.add_argument("--out")
    ac = sub.add_parser("accept")
    ac.add_argument("--base", required=True)
    ac.add_argument("--cand", required=True)
    ac.add_argument("--data", required=True)
    ac.add_argument("--out", required=True)
    k = sub.add_parser("compare")
    k.add_argument("--a", required=True, help="baseline evaluation JSON")
    k.add_argument("--b", required=True, help="candidate evaluation JSON")
    k.add_argument("--out", required=True)
    t = sub.add_parser("train")
    t.add_argument("--config", required=True)
    t.add_argument("--data", required=True)
    t.add_argument("--base", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--max-steps-this-run", type=int, default=0, help="stop after N steps (interruption test)")
    pr = sub.add_parser("probes")
    pr.add_argument("--model", required=True)
    pr.add_argument("--data", help="prepared dataset (for noisy/short variants of real speech)")
    pr.add_argument("--out", required=True)
    pr.add_argument("--threads", type=int, default=4)
    s = sub.add_parser("serve")
    s.add_argument("--model", required=True)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--threads", type=int, default=4)
    s.add_argument("--max-waiting", type=int, default=2)
    m = sub.add_parser("manifest")
    m.add_argument("--model", required=True)
    a = ap.parse_args(argv)

    if a.cmd in ("fetch", "check"):
        from . import fetch
        if a.cmd == "fetch":
            print(json.dumps(fetch.fetch(a.dest, a.what), indent=1))
            return 0
        problems = fetch.check(a.dest, a.what)
        print(json.dumps({"ok": not problems, "problems": problems}, indent=1))
        return 0 if not problems else 1
    if a.cmd == "prepare":
        from . import prepare
        m = prepare.prepare(a.sources, a.out)
        print(json.dumps({"splits": m["splits"], "checks": m["checks"], "manifest_jsonl_sha256": m["manifest_jsonl_sha256"]}, indent=1, ensure_ascii=False))
        return 0
    if a.cmd == "prepare-accent":
        from . import prepare
        print(json.dumps(prepare.prepare_accent(a.sources, a.out)["splits"], indent=1))
        return 0
    if a.cmd == "prepare-non-french":
        from . import prepare
        print(json.dumps(prepare.prepare_non_french(a.sources, a.out), indent=1))
        return 0
    if a.cmd == "evaluate":
        from . import evaluate
        ids = json.loads(open(a.ids).read()) if a.ids else None
        res = evaluate.evaluate(a.model, a.data, a.split, a.out, ids=ids, batch=a.batch, threads=a.threads, label=a.label)
        print(json.dumps(res["summary"], indent=1))
        return 0
    if a.cmd == "rescore":
        from . import evaluate
        res = evaluate.rescore(a.eval, a.data, a.out)
        print(json.dumps({k: res["summary"][k] for k in ("label", "split", "served_status", "served_warnings")}, indent=1))
        print(json.dumps({"raw_wer": res["summary"]["raw"]["wer"], "served_wer": res["summary"]["served"]["wer"]}))
        return 0
    if a.cmd == "accept":
        import os
        from . import compare, evaluate
        load = lambda d, f: json.load(open(os.path.join(d, f), encoding="utf-8"))  # noqa: E731
        base = {k: load(a.base, f"{k}.json") for k in ("test", "ood", "probes")}
        cand = {k: load(a.cand, f"{k}.json") for k in ("test", "ood", "probes")}
        train_texts = [r["text"] for r in evaluate.load_rows(a.data, "train")]
        free = compare.overlap_free(base["test"], train_texts)
        res = compare.acceptance(base, cand, free)
        res["overlap_free_test_ids"] = free
        res["inputs"] = {"base": {k: f"{a.base}/{k}.json" for k in ("test", "ood", "probes")},
                         "candidate": {k: f"{a.cand}/{k}.json" for k in ("test", "ood", "probes")}}
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print(json.dumps({k: res[k] for k in ("rule", "verdict", "failed", "production_go")}, indent=1))
        return 0
    if a.cmd == "compare":
        from . import compare
        res = compare.compare_files(a.a, a.b, a.out)
        print(json.dumps(res["verdict"], indent=1))
        return 0
    if a.cmd == "train":
        from . import train
        res = train.train(a.config, a.data, a.base, a.out, stop_after=a.max_steps_this_run)
        print(json.dumps(res, indent=1))
        return 0
    if a.cmd == "probes":
        from . import probes
        res = probes.run(a.model, a.out, data=a.data, threads=a.threads)
        print(json.dumps(res["summary"], indent=1))
        return 0
    if a.cmd == "serve":
        from . import service
        return service.serve(a.model, a.host, a.port, threads=a.threads, max_waiting=a.max_waiting)
    if a.cmd == "manifest":
        from . import deployment
        print(json.dumps(deployment.manifest(a.model), indent=1, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
