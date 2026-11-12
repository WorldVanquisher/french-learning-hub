"""python3 -m flh_extraction COMMAND …

  check     --train T [T2 …] --eval E --boundary B [--workbook-text FILE…] --out REPORT.json
  manifest  --file NAME=PATH … [--generator PATH …] --out MANIFEST.json
  evaluate  --refs R.jsonl --results V.jsonl [--judgments J.jsonl] --title T --out PREFIX
  baselines --refs R.jsonl --out DIR        (oracle, empty and perturbed outputs for harness checks)
  sft       --candidates C.jsonl [C2 …] --rendered P.jsonl [P2 …] --out SFT.jsonl [--out-train T --out-dev D]
  eval-prompts --candidates E.jsonl --rendered P.jsonl --out PROMPTS.jsonl
  attach-inputs --predictions P.jsonl --candidates E.jsonl --out O.jsonl   (for extraction-render validate)
  categories --refs R.jsonl --results V.jsonl --report REPORT.json --title T --out PREFIX
            (schema validity, unsupported claims, abstention and splitting, reported separately)
  audit     --train T [T2 …] [--eval E] [--boundary B] --out PREFIX   (training data by failure mode; HEURISTIC)
  increment-check --base T --increment I --eval E [--boundary B] [--validated V] --out REPORT.json
  quality   --refs R --results V [--outputs O] [--judgments J] --title T --out PREFIX
            (structure, unit counts, split/merge, abstention, grounding, bilingual; exact vs heuristic vs human)
  quality-compare --a A.json --b B.json --out PREFIX   (headline deltas, e.g. frozen eval vs probe)
  probe     --eval E --analyses A --variant rb|swap --out P.jsonl   (production-input probe; eval only)
  control-matrix --refs R --render BIN --out DIR [--probe P.jsonl]  (controlled failures vs metrics)
  review-packet --base T --increment I --probe P --out PREFIX   (25 prioritized items; verdicts left empty)
            [--challenge C --v3-out PREFIX]   (v3 expansion: one sample per error family, rubric, one example per label)
  promotion-check --candidate-frozen Q --candidate-probe Q --baseline-frozen Q [--baseline-probe Q] [--losses L]
            [--run-manifest M] [--input-manifest M] [--review V] --out PREFIX   (PASS / FAIL / PENDING per criterion)
  shortcut-repro --eval E --probe-rb P --probe-swap S --render BIN --out DIR
            (oracle, category-only and constant-empty systems; manifests and abstention confusion counts)
  account   --slice R --predictions P --render BIN --out PREFIX   (one status per reference row; nothing dropped)
  challenge-check --challenge C --train T [T2 …] --eval E [--boundary B] [--validated V] --out REPORT.json
            (paired cue challenge slice: groups, splits, production validation, leakage)
  paired-consistency --challenge C --results V [--outputs O] --out PREFIX   (paired consistency + components + aggregate)
  paired-demo --challenge C --render BIN --out DIR   (oracle, category-only, constant-empty through the validator)
  comparison-slice --eval E --probe-rb P --challenge C --rendered R [R2 …] --out DIR   (refs, inputs, prompts)
  comparison-matrix --slice-dir DIR --rendered R --repo ROOT --out MATRIX.json   (pinned; every run NOT_PERFORMED)
  compare   --matrix M --slice S --render BIN [--predictions SYSTEM=FILE …] --out PREFIX   (missing systems stay NOT_PERFORMED)
  parsing-fixture --slice S --out P.jsonl --expect E.json   (raw outputs with known faults, for compare)
  decision-report --comparison R [--human H] [--review V …] [--losses L] [--run-manifest M] [--input-manifest M] --out PREFIX
            (WINNER_FOR_OWNER_DECISION / PENDING / NO_WINNER / REFUSED across the three systems)
"""

import argparse
import json
import sys
from pathlib import Path

from . import (audit, categories, challenge, comparison, controls, decision, evaluate, increment, manifest, matrix, paired, probe,
               promotion, quality, records, review_packet, sft, splits)


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv):
    ap = argparse.ArgumentParser(prog="flh_extraction")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--train", nargs="+"); c.add_argument("--eval"); c.add_argument("--boundary")
    c.add_argument("--workbook-text", nargs="*", default=[]); c.add_argument("--out")
    m = sub.add_parser("manifest"); m.add_argument("--file", nargs="+"); m.add_argument("--generator", nargs="*", default=[]); m.add_argument("--out")
    e = sub.add_parser("evaluate"); e.add_argument("--refs"); e.add_argument("--results"); e.add_argument("--judgments")
    e.add_argument("--title", default="Extraction evaluation"); e.add_argument("--out")
    b = sub.add_parser("baselines"); b.add_argument("--refs"); b.add_argument("--out")
    s = sub.add_parser("sft"); s.add_argument("--candidates", nargs="+"); s.add_argument("--rendered", nargs="+"); s.add_argument("--out")
    s.add_argument("--out-train"); s.add_argument("--out-dev")
    p = sub.add_parser("eval-prompts"); p.add_argument("--candidates"); p.add_argument("--rendered"); p.add_argument("--out")
    p.add_argument("--split-groups", nargs="+", default=["eval"])
    j = sub.add_parser("attach-inputs"); j.add_argument("--predictions"); j.add_argument("--candidates"); j.add_argument("--out")
    k = sub.add_parser("categories"); k.add_argument("--refs"); k.add_argument("--results"); k.add_argument("--report")
    k.add_argument("--title", default="Failure categories"); k.add_argument("--out")
    u = sub.add_parser("audit"); u.add_argument("--train", nargs="+", required=True); u.add_argument("--eval"); u.add_argument("--boundary")
    u.add_argument("--title", default="Training-data audit"); u.add_argument("--out", required=True)
    n = sub.add_parser("increment-check"); n.add_argument("--base", required=True); n.add_argument("--increment", required=True)
    n.add_argument("--eval", required=True); n.add_argument("--boundary"); n.add_argument("--validated"); n.add_argument("--out", required=True)
    q = sub.add_parser("quality"); q.add_argument("--refs", required=True); q.add_argument("--results", required=True)
    q.add_argument("--outputs"); q.add_argument("--judgments"); q.add_argument("--title", default="Extraction quality")
    q.add_argument("--out", required=True)
    qc = sub.add_parser("quality-compare"); qc.add_argument("--a", required=True); qc.add_argument("--b", required=True)
    qc.add_argument("--out", required=True)
    pr = sub.add_parser("probe"); pr.add_argument("--eval", required=True); pr.add_argument("--analyses", required=True)
    pr.add_argument("--variant", choices=("rb", "swap"), required=True); pr.add_argument("--out", required=True)
    cm = sub.add_parser("control-matrix"); cm.add_argument("--refs", required=True); cm.add_argument("--render", required=True)
    cm.add_argument("--probe"); cm.add_argument("--out", required=True)
    rp = sub.add_parser("review-packet"); rp.add_argument("--base", required=True); rp.add_argument("--increment", required=True)
    rp.add_argument("--probe", required=True); rp.add_argument("--out", required=True)
    rp.add_argument("--challenge"); rp.add_argument("--v3-out")
    pc = sub.add_parser("promotion-check")
    for k in ("--candidate-frozen", "--candidate-probe", "--baseline-frozen", "--out"):
        pc.add_argument(k, required=True)
    for k in ("--baseline-probe", "--losses", "--run-manifest", "--input-manifest", "--review"):
        pc.add_argument(k)
    sr = sub.add_parser("shortcut-repro")
    for k in ("--eval", "--probe-rb", "--probe-swap", "--render", "--out"):
        sr.add_argument(k, required=True)
    ac = sub.add_parser("account")
    for k in ("--slice", "--predictions", "--render", "--out"):
        ac.add_argument(k, required=True)
    ch = sub.add_parser("challenge-check"); ch.add_argument("--challenge", required=True)
    ch.add_argument("--train", nargs="+", required=True); ch.add_argument("--eval", required=True)
    ch.add_argument("--boundary"); ch.add_argument("--validated"); ch.add_argument("--out", required=True)
    pcs = sub.add_parser("paired-consistency"); pcs.add_argument("--challenge", required=True)
    pcs.add_argument("--results", required=True); pcs.add_argument("--outputs"); pcs.add_argument("--out", required=True)
    pd = sub.add_parser("paired-demo")
    for k in ("--challenge", "--render", "--out"):
        pd.add_argument(k, required=True)
    cs = sub.add_parser("comparison-slice")
    for k in ("--eval", "--probe-rb", "--challenge", "--out"):
        cs.add_argument(k, required=True)
    cs.add_argument("--rendered", nargs="+", required=True)
    cmx = sub.add_parser("comparison-matrix")
    for k in ("--slice-dir", "--rendered", "--repo", "--out"):
        cmx.add_argument(k, required=True)
    cp = sub.add_parser("compare")
    for k in ("--matrix", "--slice", "--render", "--out"):
        cp.add_argument(k, required=True)
    cp.add_argument("--predictions", nargs="*", default=[])
    pf = sub.add_parser("parsing-fixture")
    for k in ("--slice", "--out", "--expect"):
        pf.add_argument(k, required=True)
    dr = sub.add_parser("decision-report"); dr.add_argument("--comparison", required=True); dr.add_argument("--human")
    dr.add_argument("--review", nargs="*", default=[]); dr.add_argument("--losses"); dr.add_argument("--run-manifest")
    dr.add_argument("--input-manifest"); dr.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "decision-report":
        rd = lambda x: json.loads(Path(x).read_text(encoding="utf-8")) if x else None  # noqa: E731
        rep = decision.decide(rd(a.comparison), rd(a.human), [r for f in a.review for r in records.load_jsonl(f)] or None,
                              records.load_jsonl(a.losses) if a.losses else None, rd(a.run_manifest), rd(a.input_manifest))
        dump(a.out + ".json", rep)
        Path(a.out + ".md").write_text(decision.markdown(rep), encoding="utf-8")
        print(json.dumps({"verdict": rep["verdict"], "winner": rep["winner"], "reasons": rep["reasons"]}, ensure_ascii=False))
        return {"WINNER_FOR_OWNER_DECISION": 0, "PENDING": 3}.get(rep["verdict"], 1)
    if a.cmd == "parsing-fixture":
        rows, expect = comparison.parsing_fixture(records.load_jsonl(a.slice))
        write_jsonl(a.out, rows)
        dump(a.expect, {"status_counts": expect, "unknown_id_rows": 1, "prediction_rows": len(rows)})
        print(json.dumps({"rows": len(rows), "expect": expect}))
        return 0
    if a.cmd == "comparison-slice":
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        refs, inputs, prompts = matrix.build_slice(records.load_jsonl(a.eval), records.load_jsonl(a.probe_rb),
                                                   records.load_jsonl(a.challenge),
                                                   [r for f in a.rendered for r in records.load_jsonl(f)])
        for name, rows in (("comparison-slice.jsonl", refs), ("comparison-inputs.jsonl", inputs), ("comparison-prompts.jsonl", prompts)):
            matrix.write_jsonl(out / name, rows)
        from collections import Counter
        print(json.dumps({"records": len(refs), "parts": dict(Counter(matrix.part_of(r) for r in refs))}))
        return 0
    if a.cmd == "comparison-matrix":
        m = matrix.build_matrix(a.slice_dir, records.load_jsonl(a.rendered)[0], a.repo)
        dump(a.out, m)
        Path(a.out).with_suffix(".md").write_text(matrix.markdown(m), encoding="utf-8")
        print(json.dumps({"matrix_sha256": m["matrix_sha256"], "statuses": [s["status"] for s in m["systems"]]}))
        return 0
    if a.cmd == "compare":
        m = json.loads(Path(a.matrix).read_text(encoding="utf-8"))
        preds = {}
        for x in a.predictions:
            k, f = x.split("=", 1)
            preds[k] = records.load_jsonl(f)
        unknown = sorted(set(preds) - {s["system"] for s in m["systems"]})
        if unknown:
            raise SystemExit(f"unknown systems {unknown}")
        rep = matrix.compare(m, a.slice, preds, controls.render_validator(a.render, Path(a.out + ".work")))
        dump(a.out + ".json", rep)
        Path(a.out + ".md").write_text(matrix.markdown(m, rep), encoding="utf-8")
        print(json.dumps({"refused": rep["refused"], **{k: v["status"] for k, v in rep["systems"].items()}}))
        return 1 if rep["refused"] else 0
    if a.cmd == "paired-consistency":
        rep = paired.report(records.load_jsonl(a.challenge), records.load_jsonl(a.results),
                            records.load_jsonl(a.outputs) if a.outputs else None)
        dump(a.out + ".json", rep)
        Path(a.out + ".md").write_text(paired.markdown({"system": rep}), encoding="utf-8")
        print(json.dumps(rep["headline"]))
        return 0
    if a.cmd == "paired-demo":
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        reps = paired.demo(records.load_jsonl(a.challenge), controls.render_validator(a.render, out / "work"))
        dump(out / "paired-demo.json", {"challenge": comparison.file_entry(a.challenge), "systems": reps})
        (out / "paired-demo.md").write_text(paired.markdown(reps), encoding="utf-8")
        print(json.dumps({k: v["headline"] for k, v in reps.items()}))
        return 0
    if a.cmd == "challenge-check":
        rep = challenge.check(records.load_jsonl(a.challenge), [r for t in a.train for r in records.load_jsonl(t)],
                              records.load_jsonl(a.eval), records.load_jsonl(a.boundary) if a.boundary else [],
                              records.load_jsonl(a.validated) if a.validated else None)
        dump(a.out, rep)
        pv = rep["production_validation"]
        print(json.dumps({"pass": rep["pass"], "records": rep["records"], "groups": rep["groups"]["count"],
                          "production_valid": pv if isinstance(pv, str) else f"{pv['valid']}/{pv['of']}",
                          "splits": rep["splits"], "between_groups_ge_0.5": rep["between_groups"]["near_pairs_ge_0.5"],
                          "near_ge_0.5": {k: v["near_pairs_ge_0.5"] for k, v in rep["against"].items() if isinstance(v, dict)},
                          "objectives": rep["objectives"]}, ensure_ascii=False))
        return 0 if rep["pass"] else 1
    if a.cmd == "shortcut-repro":
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        val = controls.render_validator(a.render, out / "work")
        slices = {n: (f, records.load_jsonl(f)) for n, f in (("frozen", a.eval), ("rb", a.probe_rb), ("swap", a.probe_swap))}
        rep = comparison.shortcut_repro(slices, val, out / "runs")
        dump(out / "shortcut-repro.json", rep)
        (out / "shortcut-repro.md").write_text(comparison.shortcut_markdown(rep), encoding="utf-8")
        print(json.dumps({k: v["confusion"]["abstention"] for k, v in rep["runs"].items()}))
        return 0
    if a.cmd == "account":
        refs = records.load_jsonl(a.slice)
        preds = records.load_jsonl(a.predictions)
        acc = comparison.account_with_validator([r["id"] for r in refs], {r["id"]: r["input"] for r in refs}, preds,
                                                controls.render_validator(a.render, Path(a.out + ".work")))
        dump(a.out + ".json", acc)
        print(json.dumps({k: acc[k] for k in ("references", "scorable", "status_counts", "unknown_id_rows")}))
        return 0
    if a.cmd == "promotion-check":
        rd = lambda x: json.loads(Path(x).read_text(encoding="utf-8")) if x else None  # noqa: E731
        rep = promotion.check(rd(a.candidate_frozen), rd(a.candidate_probe), rd(a.baseline_frozen), rd(a.baseline_probe),
                              records.load_jsonl(a.losses) if a.losses else None, rd(a.run_manifest), rd(a.input_manifest),
                              records.load_jsonl(a.review) if a.review else None)
        dump(a.out + ".json", rep)
        Path(a.out + ".md").write_text(promotion.markdown(rep), encoding="utf-8")
        print(json.dumps({"verdict": rep["verdict"], "statuses": [c["status"] for c in rep["criteria"]]}))
        return {"ELIGIBLE_FOR_OWNER_DECISION": 0, "PENDING": 3}.get(rep["verdict"], 1)
    if a.cmd == "review-packet":
        items = review_packet.build(records.load_jsonl(a.base), records.load_jsonl(a.increment), records.load_jsonl(a.probe))
        Path(a.out + ".md").write_text(review_packet.markdown(items), encoding="utf-8")
        Path(a.out + ".jsonl").write_text(review_packet.jsonl(items), encoding="utf-8")
        from collections import Counter
        print(json.dumps({"items": len(items), "by_priority": dict(sorted(Counter(i["priority"] for i in items).items()))}))
        if a.challenge and a.v3_out:
            x = review_packet.build_v3(records.load_jsonl(a.base), records.load_jsonl(a.increment),
                                       records.load_jsonl(a.challenge), exclude={i["id"] for i in items})
            Path(a.v3_out + ".md").write_text(review_packet.markdown_v3(x), encoding="utf-8")
            Path(a.v3_out + ".jsonl").write_text(review_packet.jsonl(x), encoding="utf-8")
            print(json.dumps({"v3_items": len(x), "by_family": dict(sorted(Counter(i["family"] for i in x).items()))}))
        return 0
    if a.cmd == "quality":
        judg = {}
        for j in (records.load_jsonl(a.judgments) if a.judgments else []):
            judg.setdefault(j["id"], []).append(j)
        rep = quality.report(records.load_jsonl(a.refs), records.load_jsonl(a.results), judg,
                             records.load_jsonl(a.outputs) if a.outputs else None)
        dump(a.out + ".json", rep)
        Path(a.out + ".md").write_text(quality.markdown(rep, a.title), encoding="utf-8")
        print(json.dumps({k: v[0] for k, v in rep["headline"].items()}, ensure_ascii=False))
        return 0
    if a.cmd == "quality-compare":
        A, B = (json.loads(Path(x).read_text(encoding="utf-8")) for x in (a.a, a.b))
        cmp_ = quality.compare(A, B)
        dump(a.out + ".json", cmp_)
        lines = ["| Metric | A | B | Δ | Basis |", "|---|---|---|---|---|"]
        lines += [f"| {k} | {v['a']} | {v['b']} | {v['delta']} | {v['basis']} |" for k, v in cmp_.items()]
        Path(a.out + ".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(json.dumps({k: v["delta"] for k, v in cmp_.items()}))
        return 0
    if a.cmd == "probe":
        rows = probe.build(records.load_jsonl(a.eval), records.load_jsonl(a.analyses), a.variant)
        write_jsonl(a.out, rows)
        print(json.dumps(probe.summary(rows), ensure_ascii=False))
        return 0
    if a.cmd == "control-matrix":
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        val = controls.render_validator(a.render, out / "work")
        m = controls.matrix(records.load_jsonl(a.refs), val)
        pm = None
        if a.probe:
            pt = {"oracle": [], **controls.PROBE_TARGETS}
            pm = controls.matrix(records.load_jsonl(a.probe), val, pt)
        dump(out / "control-matrix.json", {"frozen_eval": m, "swap_probe": pm})
        (out / "control-matrix.md").write_text(controls.markdown(m, "Controlled failures vs metrics", pm), encoding="utf-8")
        print(json.dumps({c: r["caught"] for c, r in m.items()}))
        return 0
    if a.cmd == "increment-check":
        rep = increment.check(records.load_jsonl(a.base), records.load_jsonl(a.increment), records.load_jsonl(a.eval),
                              records.load_jsonl(a.boundary) if a.boundary else [],
                              records.load_jsonl(a.validated) if a.validated else None)
        dump(a.out, rep)
        pv = rep["production_validation"]
        print(json.dumps({"pass": rep["pass"], "increment": len(records.load_jsonl(a.increment)),
                          "production_valid": pv if isinstance(pv, str) else f"{pv['valid']}/{pv['of']}",
                          "near_pairs_eval_ge_0.5": rep["near_pairs_eval"]["jaccard_ge_0.5"],
                          "headword_overlap_eval": rep["headword_overlap_eval"],
                          "near_duplicates_of_base": rep["near_duplicates_of_base"]["jaccard_ge_0.8"]}, ensure_ascii=False))
        return 0 if rep["pass"] else 1
    if a.cmd == "audit":
        rep = audit.audit([r for t in a.train for r in records.load_jsonl(t)], records.load_jsonl(a.eval) if a.eval else [],
                          records.load_jsonl(a.boundary) if a.boundary else [])
        dump(a.out + ".json", rep)
        Path(a.out + ".md").write_text(audit.markdown(rep, a.title), encoding="utf-8")
        print(json.dumps({r["mode"]: r["count"] for r in rep["summary"]}, ensure_ascii=False))
        return 0
    if a.cmd == "check":
        train, evals = [r for t in a.train for r in records.load_jsonl(t)], records.load_jsonl(a.eval)
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
        rows, refused = sft.build([r for c in a.candidates for r in records.load_jsonl(c)],
                                  [r for p in a.rendered for r in records.load_jsonl(p)])
        write_jsonl(a.out, rows)
        if a.out_train:
            write_jsonl(a.out_train, [r for r in rows if r["split"] == "train"])
        if a.out_dev:
            write_jsonl(a.out_dev, [r for r in rows if r["split"] == "dev"])
        print(json.dumps({"sft_records": len(rows), "refused": len(refused),
                          "by_split": {s: sum(1 for r in rows if r["split"] == s) for s in ("train", "dev")}}))
        return 0
    if a.cmd == "eval-prompts":
        rows = sft.eval_prompts(records.load_jsonl(a.candidates), records.load_jsonl(a.rendered), tuple(a.split_groups))
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
