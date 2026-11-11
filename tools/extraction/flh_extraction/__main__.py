"""python3 -m flh_extraction COMMAND …

  check     --train T --eval E --boundary B [--workbook-text FILE…] --out REPORT.json
  manifest  --file NAME=PATH … [--generator PATH …] --out MANIFEST.json
  evaluate  --refs R.jsonl --results V.jsonl [--judgments J.jsonl] --title T --out PREFIX
  baselines --refs R.jsonl --out DIR        (oracle, empty and perturbed outputs for harness checks)
  sft       --candidates C.jsonl --rendered P.jsonl --out SFT.jsonl
  eval-prompts --candidates E.jsonl --rendered P.jsonl --out PROMPTS.jsonl
  attach-inputs --predictions P.jsonl --candidates E.jsonl --out O.jsonl   (for extraction-render validate)
  categories --refs R.jsonl --results V.jsonl --report REPORT.json --title T --out PREFIX
            (schema validity, unsupported claims, abstention and splitting, reported separately)
"""

import argparse
import json
import sys
from pathlib import Path

from . import categories, evaluate, manifest, records, sft, splits


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv):
    ap = argparse.ArgumentParser(prog="flh_extraction")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--train"); c.add_argument("--eval"); c.add_argument("--boundary")
    c.add_argument("--workbook-text", nargs="*", default=[]); c.add_argument("--out")
    m = sub.add_parser("manifest"); m.add_argument("--file", nargs="+"); m.add_argument("--generator", nargs="*", default=[]); m.add_argument("--out")
    e = sub.add_parser("evaluate"); e.add_argument("--refs"); e.add_argument("--results"); e.add_argument("--judgments")
    e.add_argument("--title", default="Extraction evaluation"); e.add_argument("--out")
    b = sub.add_parser("baselines"); b.add_argument("--refs"); b.add_argument("--out")
    s = sub.add_parser("sft"); s.add_argument("--candidates"); s.add_argument("--rendered"); s.add_argument("--out")
    p = sub.add_parser("eval-prompts"); p.add_argument("--candidates"); p.add_argument("--rendered"); p.add_argument("--out")
    j = sub.add_parser("attach-inputs"); j.add_argument("--predictions"); j.add_argument("--candidates"); j.add_argument("--out")
    k = sub.add_parser("categories"); k.add_argument("--refs"); k.add_argument("--results"); k.add_argument("--report")
    k.add_argument("--title", default="Failure categories"); k.add_argument("--out")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        train, evals = records.load_jsonl(a.train), records.load_jsonl(a.eval)
        boundary = records.load_jsonl(a.boundary) if a.boundary else []
        texts = []
        for f in a.workbook_text:
            texts += [t for t in Path(f).read_text(encoding="utf-8").split("\n\n") if t.strip()]
        rep = splits.check(train, evals, boundary, texts)
        rep["structural_errors"] = {r["id"]: errs for r in train + evals + boundary for errs in [records.structural_errors(r)] if errs}
        rep["pass"] = rep["pass"] and not rep["structural_errors"]
        dump(a.out, rep)
        print(json.dumps({"pass": rep["pass"], "counts": rep["counts"], "structural_errors": len(rep["structural_errors"]),
                          "canonical_overlap_train_eval": len(rep["canonical_overlap_train_eval"]),
                          "headword_overlap_train_eval": rep["headword_overlap_train_eval"],
                          "near_pairs_eval_train": rep["near_pairs_eval_train"]["jaccard_ge_0.5"]}, ensure_ascii=False))
        return 0 if rep["pass"] else 1
    if a.cmd == "manifest":
        files = dict(x.split("=", 1) for x in a.file)
        out = manifest.build(files, a.generator)
        dump(a.out, out)
        print(out["manifest_sha256"])
        return 0
    if a.cmd == "evaluate":
        refs = records.load_jsonl(a.refs)
        results = records.load_jsonl(a.results)
        judg = {}
        if a.judgments:
            for j in records.load_jsonl(a.judgments):
                judg.setdefault(j["id"], []).append(j)
        rep = evaluate.evaluate(refs, results, judg)
        dump(a.out + ".json", rep)
        Path(a.out + ".md").write_text(evaluate.markdown(rep, a.title), encoding="utf-8")
        print(json.dumps({k: rep[k] for k in ("examples", "structural_validity", "unit_precision", "unit_recall", "unit_f1",
                                              "example_perfect_rate", "provisional", "errors")}, ensure_ascii=False))
        return 0
    if a.cmd == "baselines":
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        refs = records.load_jsonl(a.refs)
        oracle, empty, perturbed = [], [], []
        for k, r in enumerate(refs):
            units = r["expected"]["units"]
            oracle.append({"id": r["id"], "input": r["input"], "output_text": json.dumps(r["expected"], ensure_ascii=False)})
            empty.append({"id": r["id"], "input": r["input"], "output_text": '{"units":[]}'})
            # Perturbations a model could make: drop a unit, duplicate one, drop
            # the Chinese quotes, invent a unit on zero-unit cases, break JSON.
            mode = k % 5
            pu = [dict(u) for u in units]
            if mode == 0 and pu:
                pu = pu[1:]
            elif mode == 1 and pu:
                pu.append({**pu[0], "canonical": pu[0]["canonical"] + " (bis)", "statement": pu[0]["statement"] + " Again."})
            elif mode == 2 and pu:
                pu[0]["statement_zh"] = "这个用法需要注意。"  # drops the claim and the French forms
            elif mode == 3 and not pu:
                pu = [{"kind": "vocabulary", "canonical": "salutations", "statement": "Greetings are polite.",
                       "statement_zh": "问候语很礼貌。", "example": None, "confidence": 0.9}]
            text = json.dumps({"units": pu}, ensure_ascii=False) if mode != 4 else "Voici les unités :"
            perturbed.append({"id": r["id"], "input": r["input"], "output_text": text})
        for name, rows in (("oracle", oracle), ("empty", empty), ("perturbed", perturbed)):
            write_jsonl(out / f"{name}-outputs.jsonl", rows)
        print(json.dumps({"written": ["oracle", "empty", "perturbed"], "examples": len(refs)}))
        return 0
    if a.cmd == "sft":
        rows, refused = sft.build(records.load_jsonl(a.candidates), records.load_jsonl(a.rendered))
        write_jsonl(a.out, rows)
        print(json.dumps({"sft_records": len(rows), "refused": len(refused),
                          "by_split": {s: sum(1 for r in rows if r["split"] == s) for s in ("train", "dev")}}))
        return 0
    if a.cmd == "eval-prompts":
        rows = sft.eval_prompts(records.load_jsonl(a.candidates), records.load_jsonl(a.rendered))
        write_jsonl(a.out, rows)
        print(json.dumps({"eval_prompts": len(rows)}))
        return 0
    if a.cmd == "attach-inputs":
        inputs = {c["id"]: c["input"] for c in records.load_jsonl(a.candidates)}
        preds = records.load_jsonl(a.predictions)
        missing = [p["id"] for p in preds if p["id"] not in inputs]
        if missing:
            raise SystemExit(f"predictions for unknown ids: {missing[:5]}")
        write_jsonl(a.out, [{"id": p["id"], "input": inputs[p["id"]], "output_text": p["output_text"]} for p in preds])
        print(json.dumps({"attached": len(preds)}))
        return 0
    if a.cmd == "categories":
        s = categories.summarize(records.load_jsonl(a.refs), records.load_jsonl(a.results),
                                 json.loads(Path(a.report).read_text(encoding="utf-8")))
        dump(a.out + ".json", s)
        Path(a.out + ".md").write_text(categories.markdown(s, a.title), encoding="utf-8")
        print(json.dumps({k: s[k] for k in ("schema_validity", "unsupported", "abstention", "splitting")}, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
