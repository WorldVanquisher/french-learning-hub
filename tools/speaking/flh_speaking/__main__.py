"""Command line: python -m flh_speaking <command> ...

  fetch      --dest DIR --what whisper-base mls fleurs ...   download and verify pinned files
  check      --dest DIR --what ...                           re-verify pinned files (exit 1 on mismatch)
  prepare    --sources DIR --out DIR                         decode, split and seal the dataset
  prepare-non-french --sources DIR --out DIR                 English + Mandarin FLEURS clips for the not_french probe
  prepare-accent --sources DIR --out DIR                     SLR57 African-accented French test split (CA16)
  prepare-punctuated --sources DIR --base-data DIR --out DIR FLEURS French train with case and punctuation (v2 experiment)
  evaluate   --model DIR --data DIR --split test --out FILE  transcribe a split and score it
  rescore    --eval FILE --data DIR [--out FILE]             re-apply abstention rules to stored raw outputs
  compare    --a FILE --b FILE --out FILE                    paired comparison of one split
  accept     --base DIR --cand DIR --data DIR --out FILE     acceptance rule (DIRs hold test.json, ood.json, probes.json)
  train      --config FILE --data DIR --base DIR --out DIR   fine-tune (resumable)
  probes     --model DIR --out FILE                          short, silent, noisy, invalid, non-French audio
  robustness --set short|language|noise --model DIR --data DIR --out FILE   model outputs for policy analysis (v2)
  serve      --model DIR [--host 127.0.0.1 --port 8765 --inference-timeout S]   local transcription service
  lab demo [--check] | lab compare CASE [--audio F] [--json OUT] [--text OUT]   Speaking Lab (standard library only)
  lab candidate-review --baseline EVAL --candidate EVAL [--thresholds F]   offline candidate review (never promotes)
  lab candidate-review-walkthrough --review REVIEW.json [--data-manifest M]  why the support is or is not enough
  lab intake [--proposal P] [--data-manifest M] [--source NAME=M …] [--pairs P]  data intake checks (no audio read)
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
    f.add_argument("--no-weights", action="store_true", help="skip *.safetensors (config and tokenizer files only: the test fixture)")
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
    pp = sub.add_parser("prepare-punctuated")
    pp.add_argument("--sources", required=True)
    pp.add_argument("--base-data", required=True, help="the frozen v1 dataset (its held-out sentences and texts are excluded)")
    pp.add_argument("--out", required=True)
    pp.add_argument("--n", type=int, default=1440)
    pp.add_argument("--n-dev", type=int, default=100)
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
    rb = sub.add_parser("robustness", help="short/language/noise sets: model outputs for later policy analysis")
    rb.add_argument("--set", required=True, choices=("short", "language", "noise"))
    rb.add_argument("--model", required=True)
    rb.add_argument("--data", required=True)
    rb.add_argument("--sources", help="pinned sources (the language set reads SLR57 and FLEURS archives)")
    rb.add_argument("--out", required=True)
    rb.add_argument("--batch", type=int, default=4)
    rb.add_argument("--threads", type=int, default=4)
    lb = sub.add_parser("lab", help="compare two transcript results against one reference (standard library only)")
    lsub = lb.add_subparsers(dest="lab_cmd", required=True)
    ld = lsub.add_parser("demo", help="the shipped synthetic French case")
    ld.add_argument("--check", action="store_true", help="exit 1 unless the output equals the shipped expected JSON and text")
    lbt = lsub.add_parser("batch", help="paired comparison of two result files on one reference set")
    lbt.add_argument("--refs", required=True)
    lbt.add_argument("--a", required=True)
    lbt.add_argument("--b", required=True)
    lbt.add_argument("--review", help="reviewer records (flh_speaking_lab_review_v1 JSONL)")
    lbt.add_argument("--manifest-a", help="current candidate manifest for --a: a result from another candidate_id is invalidated")
    lbt.add_argument("--manifest-b", help="the same for --b")
    lbt.add_argument("--json")
    lbt.add_argument("--text")
    lca = lsub.add_parser("candidate", help="candidate manifests, local file checks, the weights-free dry run")
    lca.add_argument("what", choices=("manifest", "check", "dry-run"))
    lca.add_argument("--name", help="pinned model name (manifest, check)")
    lca.add_argument("--model-dir", help="local model directory (check)")
    lca.add_argument("--refs", help="references JSONL (dry-run)")
    lca.add_argument("--out", help="write here (manifest, dry-run)")
    lfe = lsub.add_parser("from-eval", help="turn a stored evaluation into lab references and a result file")
    lfe.add_argument("eval")
    lfe.add_argument("--label", required=True)
    lfe.add_argument("--refs-out", required=True)
    lfe.add_argument("--out", required=True)
    lfe.add_argument("--group", choices=("item", "speaker"), default="item", help="independent unit for paired counts and intervals")
    lcr = lsub.add_parser("candidate-review", help="offline review of a candidate from two saved evaluations (no inference; never promotes)")
    lcr.add_argument("--baseline", required=True, help="saved evaluation of the current model (flh_speaking_eval_v1)")
    lcr.add_argument("--candidate", required=True, help="saved evaluation of the candidate, same split and ids")
    lcr.add_argument("--thresholds", help="flh_speaking_candidate_thresholds_v1 JSON (partial: missing limits keep their defaults)")
    lcr.add_argument("--data-manifest", help="the prepared data manifest.jsonl behind both evaluations (audio PCM SHA-256)")
    lcr.add_argument("--experiment", help="experiment-result.json of the run that produced both evaluations")
    lcr.add_argument("--json")
    lcr.add_argument("--text")
    lcw = lsub.add_parser("candidate-review-walkthrough", help="step-by-step account of the support rule for one saved review")
    lcw.add_argument("--review", required=True, help="a saved flh_speaking_candidate_review_v1 JSON (lab candidate-review --json)")
    lcw.add_argument("--data-manifest", help="the prepared data manifest.jsonl: counts the speakers each split can offer")
    lcw.add_argument("--text", help="write the walkthrough here instead of standard output")
    lcd = lsub.add_parser("candidate-review-demo", help="the three shipped synthetic review scenarios")
    lcd.add_argument("--out", required=True, help="a new or empty directory")
    lcd.add_argument("--check", action="store_true", help="exit 1 unless every output equals the shipped expected files")
    lin = lsub.add_parser("intake", help="evaluation-data intake: checklist, speakers per split, merge and noise-pair checks (no audio read)")
    lin.add_argument("--proposal", help="a proposed source (flh_speaking_source_proposal_v1 JSON): the intake checklist")
    lin.add_argument("--data-manifest", help="a pinned data manifest.jsonl: distinct speakers per split and how many more are needed")
    lin.add_argument("--min-groups", type=int, default=30)
    lin.add_argument("--source", action="append", metavar="NAME=MANIFEST.jsonl", help="repeatable: check several evaluation sources together")
    lin.add_argument("--pairs", help="a JSONL of {speaker, clip, condition} rows: keep noise conditions paired")
    lin.add_argument("--json")
    lpc = lsub.add_parser("privacy-check", help="machine paths, session links and UUID-like IDs in shared reports (exit 1 on any)")
    lpc.add_argument("files", nargs="+")
    lsl = lsub.add_parser("silence", help="the explicit local silence rule on a PCM16 WAV")
    lsl.add_argument("wav")
    lsl.add_argument("--threshold-dbfs", type=float, default=-70.0)
    lsl.add_argument("--min-sound-seconds", type=float, default=0.3)
    lv = lsub.add_parser("variants", help="labelled volume/silence/noise/speed variants of a case's audio")
    lv.add_argument("--case", required=True)
    lv.add_argument("--audio", help="mono PCM16 WAV whose sha256 equals the case's (default: the synthetic fixture)")
    lv.add_argument("--out", required=True)
    lc = lsub.add_parser("compare")
    lc.add_argument("case")
    lc.add_argument("--audio", help="the audio file: its sha256 must equal the case's")
    lc.add_argument("--json", help="write the versioned JSON result here")
    lc.add_argument("--text", help="write the compact text result here (default: stdout)")
    s = sub.add_parser("serve")
    s.add_argument("--model", required=True)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--threads", type=int, default=4)
    s.add_argument("--max-waiting", type=int, default=2)
    s.add_argument("--inference-timeout", type=float, default=None,
                   help="seconds from a request's arrival (queue wait included) before 504; default 50; keep it below FLH's SPEAKING_TRANSCRIPTION_TIMEOUT")
    m = sub.add_parser("manifest")
    m.add_argument("--model", required=True)
    a = ap.parse_args(argv)

    if a.cmd in ("fetch", "check"):
        from . import fetch
        if a.cmd == "fetch":
            print(json.dumps(fetch.fetch(a.dest, a.what, weights=not a.no_weights), indent=1))
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
    if a.cmd == "prepare-punctuated":
        from . import prepare
        print(json.dumps(prepare.prepare_punctuated(a.sources, a.base_data, a.out, n=a.n, n_dev=a.n_dev), indent=1, ensure_ascii=False))
        return 0
    if a.cmd == "robustness":
        from . import robustness
        print(json.dumps(robustness.run(a.set, a.model, a.data, a.out, sources=a.sources, batch=a.batch, threads=a.threads), indent=1))
        return 0
    if a.cmd == "lab":
        from . import lab
        if a.lab_cmd == "demo":
            rc, text = lab.demo(check=a.check)
            sys.stdout.write(text)
            return rc
        if a.lab_cmd == "candidate":
            from . import candidates as cd
            if a.what == "dry-run":
                cd.write_jsonl(cd.dry_run(lab.read_refs(a.refs)), a.out)
                print(f"wrote {a.out} ({cd.DRY_RUN_ID}: no model, no weights)")
                return 0
            man = cd.manifest(a.name)
            if a.what == "manifest":
                text = json.dumps(man, indent=1, sort_keys=True) + "\n"
                if a.out:
                    with open(a.out, "w", encoding="utf-8") as fh:
                        fh.write(text)
                print(man["candidate_id"])
                return 0
            bad = cd.check_files(man, a.model_dir or "")
            print(json.dumps({"candidate_id": man["candidate_id"], "problems": bad}, indent=1))
            return 2 if bad else 0
        if a.lab_cmd == "from-eval":
            from . import candidates as cd
            with open(a.eval, encoding="utf-8") as fh:
                refs, rows = cd.from_eval(json.load(fh), a.label, group=a.group)
            cd.write_jsonl(refs, a.refs_out)
            cd.write_jsonl(rows, a.out)
            print(f"wrote {len(refs)} references and {len(rows) - 1} results ({rows[0]['header']['model_id']})")
            return 0
        if a.lab_cmd == "intake":
            from . import intake

            def rows(path):
                with open(path, encoding="utf-8") as fh:
                    return [json.loads(line) for line in fh if line.strip()]
            rep = {}
            try:
                if a.proposal:
                    with open(a.proposal, encoding="utf-8") as fh:
                        rep["proposal"] = intake.check_proposal(json.load(fh))
                if a.data_manifest:
                    rep["needs"] = intake.speaker_needs(rows(a.data_manifest), a.min_groups)
                if a.source:
                    rep["merge"] = intake.merge_check({n: rows(f) for n, f in (x.split("=", 1) for x in a.source)})
                if a.pairs:
                    rep["pairs"] = intake.pair_check(rows(a.pairs))
            except (OSError, ValueError, KeyError) as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
            if not rep:
                print("error: give --proposal, --data-manifest, --source or --pairs", file=sys.stderr)
                return 2
            if a.json:
                with open(a.json, "w", encoding="utf-8") as fh:
                    fh.write(lab.to_json(rep))
            sys.stdout.write(intake.render(rep))
            bad = (rep.get("proposal", {}).get("decision", "").startswith("not")) or not rep.get("merge", {"ok": True})["ok"]
            return 1 if bad else 0
        if a.lab_cmd in ("candidate-review", "candidate-review-demo", "candidate-review-walkthrough"):
            from . import candidate_review as cr
            try:
                if a.lab_cmd == "candidate-review-walkthrough":
                    with open(a.review, encoding="utf-8") as fh:
                        rv = json.load(fh)
                    rows = None
                    if a.data_manifest:
                        with open(a.data_manifest, encoding="utf-8") as fh:
                            rows = [json.loads(line) for line in fh if line.strip()]
                    text = cr.walkthrough(rv, rows)
                    if a.text:
                        with open(a.text, "w", encoding="utf-8") as fh:
                            fh.write(text)
                    else:
                        sys.stdout.write(text)
                    return 0
                if a.lab_cmd == "candidate-review-demo":
                    rc, text = cr.demo(a.out, check=a.check)
                    sys.stdout.write(text)
                    return rc
                rv = cr.from_files(a.baseline, a.candidate, a.thresholds, a.data_manifest, a.experiment)
            except (OSError, ValueError, KeyError) as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
            if a.json:
                with open(a.json, "w", encoding="utf-8") as fh:
                    fh.write(lab.to_json(rv))
            text = cr.render_text(rv)
            if a.text:
                with open(a.text, "w", encoding="utf-8") as fh:
                    fh.write(text)
            else:
                sys.stdout.write(text)
            return rv["exit_code"]
        if a.lab_cmd == "privacy-check":
            total = 0
            for f in a.files:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    found = lab.privacy_findings(fh.read())
                total += len(found)
                for x in found:
                    print(f"{f.rsplit('/', 1)[-1]}:{x['line']}: {x['kind']}: {x['match']}")
            print(f"privacy-check: {len(a.files)} files, {total} findings")
            return 1 if total else 0
        if a.lab_cmd == "silence":
            from . import review as rv
            with open(a.wav, "rb") as fh:
                res = rv.silence(fh.read(), a.threshold_dbfs, a.min_sound_seconds)
            print(json.dumps(res, sort_keys=True))
            return 0
        if a.lab_cmd == "variants":
            import hashlib
            from . import variants
            with open(a.case, encoding="utf-8") as fh:
                case = json.load(fh)
            if a.audio:
                with open(a.audio, "rb") as fh:
                    data = fh.read()
            elif case["audio"].get("fixture") == "synthetic_tone_v1":
                data = lab.synthetic_audio()
            else:
                print("error: --audio is required for this case", file=sys.stderr)
                return 2
            if hashlib.sha256(data).hexdigest() != case["audio"]["sha256"]:
                print("error: the audio does not match the case's sha256", file=sys.stderr)
                return 2
            manifest, files = variants.make(case["id"], data, case["reference"], speaker=case.get("speaker"))
            variants.write(manifest, files, a.out)
            print(json.dumps(manifest["counts"], sort_keys=True))
            for i in manifest["items"]:
                print(f"{i['status']:8} {i['id']:42} " + (i.get("sha256", "")[:12] if i["status"] == "made" else f"{i['reason']}: {i['detail']}"))
            return 0
        if a.lab_cmd == "batch":
            try:
                from . import review as rv
                ha, ra = lab.read_results(a.a)
                hb, rb = lab.read_results(a.b)
                mans = {}
                for head, mpath in ((ha, a.manifest_a), (hb, a.manifest_b)):
                    if mpath:
                        with open(mpath, encoding="utf-8") as fh:
                            mans[head["label"]] = json.load(fh)
                res = lab.batch(lab.read_refs(a.refs), ha, ra, hb, rb, review=rv.read_review(a.review) if a.review else None, manifests=mans)
            except (OSError, ValueError, KeyError) as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
            if a.json:
                with open(a.json, "w", encoding="utf-8") as fh:
                    fh.write(lab.to_json(res))
            text = lab.render_batch_text(res)
            if a.text:
                with open(a.text, "w", encoding="utf-8") as fh:
                    fh.write(text)
            else:
                sys.stdout.write(text)
            return 0 if res["ranking"]["status"] == "ranked" else 4
        try:
            with open(a.case, encoding="utf-8") as fh:
                res = lab.compare(json.load(fh), lab.file_sha256(a.audio) if a.audio else None)
        except (OSError, ValueError) as e:  # unreadable or invalid case, or another audio file
            print(f"error: {e}", file=sys.stderr)
            return 2
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                fh.write(lab.to_json(res))
        text = lab.render_text(res)
        if a.text:
            with open(a.text, "w", encoding="utf-8") as fh:
                fh.write(text)
        else:
            sys.stdout.write(text)
        return 0 if res["status"] == lab.STATUS_OK else 3
    if a.cmd == "serve":
        from . import service
        return service.serve(a.model, a.host, a.port, threads=a.threads, max_waiting=a.max_waiting, inference_timeout=a.inference_timeout)
    if a.cmd == "manifest":
        from . import deployment
        print(json.dumps(deployment.manifest(a.model), indent=1, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
