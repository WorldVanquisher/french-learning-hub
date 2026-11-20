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
  evidence-review --refs R --a A [--b B] [--limit N --page P] [--json OUT] [--md OUT]
  practice  init|revise|preview|review|decide|build|answer|export|import-preview|accept|feed|demo|compare
            measure|workbooks-bundle|demo2   (PROTOTYPE; PRACTICE.md)
  practice2 init|revise|review|decide|repair|build|answer|export|import-preview|accept|exercise|feed|storage|matrix|measure|trial|demo3
            (Extraction 2.2: reliable approval, exercise proposals, packet v3, feed additions; PRACTICE.md §9-§14)
            (each unit beside its source evidence; malformed / missing evidence / unsupported / conflicting; A vs B; HEURISTIC)
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
  review-sample --slice S --challenge C --out PREFIX   (frozen reviewer sample of held-out references; offline only)
  review-agreement --packet P.jsonl [--second P2.jsonl] --out PREFIX   (intent and wording agreement, disputes unresolved)
  export-check FILE …   (exit 1 when a reviewer export carries a local path, address, private link or identifier)
  review-sheet export|import --packet P [--sheet S.csv] --out F   (spreadsheet: intent, evidence, wording apart; offline only)
  experimental-report --comparison C [--human-evidence H] [--review P …] [--reviewer-queue Q --reviewer-evidence E]
            --out PREFIX   (DRAFT; never a production GO; per-unit reviewer evidence required for a preference)
  reviewer-queue --matrix M --slice S --render BIN --predictions SYSTEM=FILE … [--scope-ids F | --scope-packet P]
            --out PREFIX   (units to review per system, bound by hash; blank evidence template; offline only)
  one-record-fixture --out DIR [--fixture DIR] [--check]   (FLH-154 part-4 fixture through every library report)
  decision-report --comparison R [--human H] [--review V …] [--losses L] [--run-manifest M] [--input-manifest M] --out PREFIX
            (WINNER_FOR_OWNER_DECISION / PENDING / NO_WINNER / REFUSED across the three systems)
"""

import argparse
import json
import sys
from pathlib import Path

from . import (audit, categories, challenge, comparison, controls, decision, evaluate, increment, manifest, matrix, paired, probe,
               experimental_report, fixture_one_record, promotion, quality, records, review_packet, review_sample, review_sheet,
               reviewer_evidence, sft, splits)


def practice_cli(a) -> int:
    from . import packet as pk
    from . import practice as pr
    from . import practice_flow as pf
    from . import practice_workflow as pw
    try:
        if a.pcmd == "demo":
            rc, text = pw.demo(a.out, check=a.check)
            sys.stdout.write(text)
            return rc
        if a.pcmd == "demo2":
            rc, text = pf.demo2(a.out, check=a.check)
            sys.stdout.write(text)
            return rc
        if a.pcmd == "workbooks-bundle":
            rc, text = pf.workbooks_bundle(a.out, check=a.check)
            sys.stdout.write(text)
            return rc
        if a.pcmd == "measure":
            rep, _ = pf.measure(a.out)
            if a.json:
                dump(a.json, rep)
            sys.stdout.write(pf.render_measure(rep))
            return 0
        if a.pcmd == "compare":
            rep = pw.compare()
            if a.json:
                dump(a.json, rep)
            sys.stdout.write(pw.render_compare(rep))
            return 0
        if a.pcmd == "import-preview":
            rep = pk.import_preview(json.loads(Path(a.packet).read_text(encoding="utf-8")), json.loads(Path(a.proposals).read_text(encoding="utf-8")))
            if a.json:
                dump(a.json, rep)
            sys.stdout.write(pk.render_import(rep))
            return 0
        w = pw.Work(a.work)
        if a.pcmd == "init":
            sys.stdout.write(w.init(a.source, with_review=True))
        elif a.pcmd == "revise":
            sys.stdout.write(w.revise(a.source, with_review=True))
        elif a.pcmd == "preview":
            sys.stdout.write(pr.render_preview(w.resolved()))
        elif a.pcmd == "review":
            rv = w.review()
            if a.json:
                dump(a.json, rv)
            sys.stdout.write(pr.render_preview(w.resolved()) + w.review_text())
        elif a.pcmd == "decide":
            if a.approve_batch:
                if a.item:
                    raise ValueError("--approve-batch approves the batch shown by review; it takes no --item")
                ds = w.approve_batch(a.approve_batch, a.except_ids or (), a.reason)
                print(f"recorded decisions {ds[0]['seq']}-{ds[-1]['seq']}: approve {len(ds)} items of batch {a.approve_batch}"
                      + (f" (left out: {', '.join(ds[0]['batch']['excepted'])})" if ds[0]["batch"]["excepted"] else ""))
                left = w.review()["left_for_you"]
                if left:
                    print(f"still yours to decide one by one: {', '.join(r['item_id'] + ' (' + r['why'].split(':')[0] + ')' for r in left)}")
            else:
                if not a.item or not (a.approve or a.reject or a.edit):
                    raise ValueError("decide needs --item with --approve, --reject or --edit TEXT, or --approve-batch B")
                if a.except_ids:
                    raise ValueError("--except only applies to --approve-batch")
                d = w.decide(a.item, "approve" if a.approve else "reject" if a.reject else "edit", a.edit, a.reason)
                print(f"recorded decision {d['seq']}: {d['action']} {d['item_id']} (on revision {d['based_on']['source_revision']})")
        elif a.pcmd == "accept":
            d = w.accept(json.loads(Path(a.packet).read_text(encoding="utf-8")), json.loads(Path(a.proposals).read_text(encoding="utf-8")),
                         a.proposal, a.reason)
            print(f"recorded decision {d['seq']}: edit {d['item_id']} from {d['via']['agent']} proposal {d['via']['proposal_id']} "
                  f"(packet {d['via']['packet_id']}); rebuild practice with: practice build --work W")
        elif a.pcmd == "build":
            sys.stdout.write(pr.render_practice(w.practice(rebuild=True)))
        elif a.pcmd == "answer":
            sys.stdout.write(w.answer(a.item, a.text, reveal=a.reveal))
        elif a.pcmd == "export":
            prev = json.loads(Path(a.previous).read_text(encoding="utf-8")) if a.previous else None
            packet = w.export(a.mode, a.include_rubrics, version=a.packet_version, previous=prev)
            sys.stdout.write(pk.preview(packet))
            if a.out:
                print("wrote " + ", ".join(pw.write_packet(packet, a.out)))
        elif a.pcmd == "feed":
            prev = json.loads(Path(a.previous).read_text(encoding="utf-8")) if a.previous else None
            dump(a.out, pk.workbooks_feed(w.practice(), w.attempts(), previous=prev))
            print(f"wrote {a.out}")
    except PermissionError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


def practice2_cli(a) -> int:
    from . import exercises as ex
    from . import feed2
    from . import portable as pt
    from . import practice as pr
    from . import practice22 as p22
    from . import practice_flow22 as f22
    from . import review2 as rv
    from . import storage_rt as st

    def load(p):
        return json.loads(Path(p).read_text(encoding="utf-8"))
    try:
        if a.pcmd == "demo3":
            rc, text = f22.demo3(a.out, check=a.check)
            sys.stdout.write(text)
            return rc
        if a.pcmd == "trial":
            from . import recall
            rc, text = recall.trial(a.out, check=a.check)
            sys.stdout.write(text)
            return rc
        if a.pcmd == "measure":
            rep = f22.measure2(a.out)
            if a.json:
                dump(a.json, rep)
            sys.stdout.write(f22.render_measure2(rep))
            return 0
        if a.pcmd == "matrix":
            m = p22.acceptance_matrix(a.out)
            sys.stdout.write(p22.render_matrix(m))
            return 0 if m["all_ok"] else 1
        if a.pcmd == "import-preview":
            w = p22.Work2(a.work) if a.work else None
            rep = pt.import_any(load(a.packet), load(a.proposals), w.resolved() if w else None, w.exercise_decisions() if w else None)
            if a.json:
                dump(a.json, rep)
            sys.stdout.write(pt.render_import_any(rep))
            return 0
        w = p22.Work2(a.work)
        if a.pcmd == "init":
            sys.stdout.write(w.init(a.source))
        elif a.pcmd == "revise":
            sys.stdout.write(w.revise(a.source))
        elif a.pcmd == "review":
            pl = w.plan(a.select.split(",") if a.select else None, a.except_ids or ())
            if a.json:
                dump(a.json, pl)
            sys.stdout.write(w.show(with_review=False) + "\n" + rv.render_plan(pl))
        elif a.pcmd == "decide":
            if a.approve_batch:
                if a.item or a.attest_paraphrase:
                    raise ValueError("--approve-batch takes no --item or --attest-paraphrase")
                ds = w.approve_batch(a.approve_batch, a.select.split(",") if a.select else None, a.except_ids or (), a.reason)
                print(f"recorded {len(ds)} decisions for batch {a.approve_batch}" + (f" ({ds[0]['seq']}-{ds[-1]['seq']})" if ds else
                                                                                    ": nothing new (the batch was already applied)"))
                left = w.plan()["left_for_you"]
                if left:
                    print("still yours to decide one by one: " + ", ".join(r["item_id"] for r in left))
            else:
                if not a.item or not (a.approve or a.reject or a.edit):
                    raise ValueError("decide needs --item with --approve, --reject or --edit TEXT, or --approve-batch B")
                if a.select or a.except_ids:
                    raise ValueError("--select and --except only apply to --approve-batch")
                d = w.decide(a.item, "approve" if a.approve else "reject" if a.reject else "edit", a.edit, a.reason, attest=a.attest_paraphrase)
                print(f"recorded decision {d['seq']}: {d['action']} {d['item_id']} (revision {d['based_on']['source_revision']}"
                      + (", paraphrase attested by you" if d.get("attest") else "") + ")")
        elif a.pcmd == "repair":
            print(w.repair())
        elif a.pcmd == "build":
            sys.stdout.write(pr.render_practice(w.practice(rebuild=True)))
        elif a.pcmd == "answer":
            sys.stdout.write(w.answer(a.item, a.text, reveal=a.reveal))
        elif a.pcmd == "accept":
            d = w.accept(load(a.packet), load(a.proposals), a.proposal, a.reason)
            print(f"recorded decision {d['seq']}: edit {d['item_id']} from {d['via']['agent']} proposal {d['via']['proposal_id']}")
        elif a.pcmd == "exercise":
            edits = {"prompt": a.prompt, "answer": a.answer, "accepted": a.accepted or None, "options": a.options.split("|") if a.options else None}
            rec, new = w.exercise(load(a.packet), load(a.proposals), a.proposal, "approve" if a.approve else "reject", edits, a.reason)
            print((f"recorded exercise decision {rec['seq']}: {rec['action']} {rec['proposal']['agent']} {rec['proposal']['proposal_id']}"
                   + (f" -> {rec['practice_id']}" if rec["action"] == "approve" else "") + (f" (edited: {', '.join(rec['edited'])})" if rec["edited"] else ""))
                  if new else f"nothing written: the same decision is already recorded (decision {rec['seq']})")
        elif a.pcmd == "export":
            prev = "latest" if a.previous == "latest" else load(a.previous) if a.previous else None
            awaiting = None
            if a.awaiting:
                packet, ret = load(a.awaiting[0]), load(a.awaiting[1])
                rep = pt.import_any(packet, ret, w.resolved(), w.exercise_decisions())
                awaiting = pt.awaiting_from(rep["corrections"], rep["exercises"])
            p = w.export3(a.mode, a.include_rubrics, prev, a.variant, tuple(a.omit or ()), awaiting, keep=bool(a.out))
            sys.stdout.write(pt.preview3(p))
            if a.out:
                print("wrote " + ", ".join(pt.write_packet3(p, a.out, a.agent)) + f"; kept as packets/{p['packet_id']}.json in the work directory")
        elif a.pcmd == "feed":
            prev = load(a.previous) if a.previous else None
            dump(a.out, feed2.feed(w.resolved(), w.practice(rebuild=True), w.attempts(), a.seq, prev))
            print(f"wrote {a.out}")
        elif a.pcmd == "storage":
            rep = [st.round_trip(w, amended=x) for x in (False, True)]
            if a.json:
                dump(a.json, rep)
            for r in rep:
                print(f"{r['variant']}: rows {r['rows']}; refused {len(r['refused_by_constraints'])}; not representable {len(r['not_representable'])}; "
                      f"learner-visible differences {len(r['learner_visible_differences'])}")
    except PermissionError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_results(path, refs=None, what="--results"):
    """A results file for a standalone report: duplicated ids are refused (the
    report would keep only the last row; `compare` counts them as
    duplicate_prediction), ids absent from the references are noted."""
    from collections import Counter
    rows = records.load_jsonl(path)
    dup = sorted(k for k, n in Counter(r["id"] for r in rows).items() if n > 1)
    if dup:
        raise SystemExit(f"{what}: {len(dup)} duplicated id(s), e.g. {dup[:3]}; refusing to keep only the last row")
    if refs is not None:
        extra = len({r["id"] for r in rows} - {r["id"] for r in refs})
        if extra:
            print(f"note: {extra} result id(s) are not in the references and are not scored", file=sys.stderr)
    return rows


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
    rs_ = sub.add_parser("review-sample"); rs_.add_argument("--slice", required=True); rs_.add_argument("--challenge", required=True)
    rs_.add_argument("--out", required=True)
    ra = sub.add_parser("review-agreement"); ra.add_argument("--packet", required=True); ra.add_argument("--second")
    ra.add_argument("--out", required=True)
    ec = sub.add_parser("export-check"); ec.add_argument("files", nargs="+")
    rsh = sub.add_parser("review-sheet"); rsh.add_argument("action", choices=("export", "import"))
    rsh.add_argument("--packet", required=True); rsh.add_argument("--sheet"); rsh.add_argument("--out", required=True)
    xr = sub.add_parser("experimental-report"); xr.add_argument("--comparison", required=True); xr.add_argument("--human-evidence")
    xr.add_argument("--review", nargs="*", default=[]); xr.add_argument("--reviewer-queue"); xr.add_argument("--reviewer-evidence")
    xr.add_argument("--out", required=True)
    rq = sub.add_parser("reviewer-queue")
    for k in ("--matrix", "--slice", "--render", "--out"):
        rq.add_argument(k, required=True)
    rq.add_argument("--predictions", nargs="+", required=True); rq.add_argument("--scope-ids"); rq.add_argument("--scope-packet")
    orf = sub.add_parser("one-record-fixture"); orf.add_argument("--out", required=True); orf.add_argument("--fixture")
    orf.add_argument("--check", action="store_true")
    dr = sub.add_parser("decision-report"); dr.add_argument("--comparison", required=True); dr.add_argument("--human")
    dr.add_argument("--review", nargs="*", default=[]); dr.add_argument("--losses"); dr.add_argument("--run-manifest")
    dr.add_argument("--input-manifest"); dr.add_argument("--out", required=True)
    evr = sub.add_parser("evidence-review", help="units beside their source evidence; A vs B regressions (HEURISTIC evidence location)")
    evr.add_argument("--refs", required=True); evr.add_argument("--a", required=True); evr.add_argument("--b")
    evr.add_argument("--limit", type=int, default=50); evr.add_argument("--page", type=int, default=1)
    evr.add_argument("--json"); evr.add_argument("--md")
    pra = sub.add_parser("practice", help="PROTOTYPE: question + evidence -> approved knowledge -> practice -> portable packet (offline)")
    psub = pra.add_subparsers(dest="pcmd", required=True)
    q = psub.add_parser("init"); q.add_argument("--source", required=True); q.add_argument("--work", required=True)
    q = psub.add_parser("revise"); q.add_argument("--source", required=True); q.add_argument("--work", required=True)
    q = psub.add_parser("preview"); q.add_argument("--work", required=True)
    q = psub.add_parser("review", help="the draft beside its evidence, the batch you may approve together, and what stays yours")
    q.add_argument("--work", required=True); q.add_argument("--json")
    q = psub.add_parser("decide"); q.add_argument("--work", required=True); q.add_argument("--item")
    g = q.add_mutually_exclusive_group(required=True)
    g.add_argument("--approve", action="store_true"); g.add_argument("--reject", action="store_true"); g.add_argument("--edit", metavar="TEXT")
    g.add_argument("--approve-batch", metavar="BATCH_ID", help="approve the batch shown by init / review (supported items and new practice examples)")
    q.add_argument("--except", dest="except_ids", action="append", metavar="ITEM_ID", help="with --approve-batch: leave this item out (repeatable)")
    q.add_argument("--reason", default="")
    q = psub.add_parser("accept", help="accept one agent correction that import-preview classed accepted_candidate (your decision)")
    q.add_argument("--work", required=True); q.add_argument("--packet", required=True); q.add_argument("--proposals", required=True)
    q.add_argument("--proposal", required=True); q.add_argument("--reason", default="")
    q = psub.add_parser("build"); q.add_argument("--work", required=True)
    q = psub.add_parser("answer"); q.add_argument("--work", required=True); q.add_argument("--item", required=True)
    g = q.add_mutually_exclusive_group(required=True); g.add_argument("--text"); g.add_argument("--reveal", action="store_true")
    q = psub.add_parser("export"); q.add_argument("--work", required=True); q.add_argument("--mode", choices=("study", "tutor"), default="study")
    q.add_argument("--include-rubrics", action="store_true", help="tutor only: share answer keys and rubrics (an explicit choice)")
    q.add_argument("--packet-version", type=int, choices=(1, 2), default=2)
    q.add_argument("--previous", help="the packet a previous agent session used: adds what changed since (version 2)")
    g = q.add_mutually_exclusive_group(required=True); g.add_argument("--preview", action="store_true"); g.add_argument("--out")
    q = psub.add_parser("import-preview"); q.add_argument("--packet", required=True); q.add_argument("--proposals", required=True)
    q.add_argument("--json")
    q = psub.add_parser("feed"); q.add_argument("--work", required=True); q.add_argument("--out", required=True)
    q.add_argument("--previous", help="an earlier feed of the same source: lists practice IDs no longer offered as withdrawn")
    q = psub.add_parser("demo"); q.add_argument("--out", required=True); q.add_argument("--check", action="store_true")
    q = psub.add_parser("demo2", help="Extraction 2.1: shorter path, second contrast, agent switching, Workbooks bundle")
    q.add_argument("--out", required=True); q.add_argument("--check", action="store_true")
    q = psub.add_parser("measure", help="steps from capture to first practice, HANDOFF-136 flow vs 2.1 flow, executed")
    q.add_argument("--out", required=True, help="a new or empty scratch directory for the work directories"); q.add_argument("--json")
    q = psub.add_parser("workbooks-bundle", help="regenerate the sealed synthetic Workbooks bundle")
    q.add_argument("--out", required=True); q.add_argument("--check", action="store_true")
    q = psub.add_parser("compare"); q.add_argument("--json")
    p2 = sub.add_parser("practice2", help="PROTOTYPE (Extraction 2.2): reliable approval, agent exercises, packet v3, feed additions (offline)")
    s2 = p2.add_subparsers(dest="pcmd", required=True)
    q = s2.add_parser("init"); q.add_argument("--source", required=True); q.add_argument("--work", required=True)
    q = s2.add_parser("revise"); q.add_argument("--source", required=True); q.add_argument("--work", required=True)
    q = s2.add_parser("review", help="the draft beside its evidence (QUOTE / PARAPHRASE / CUE lines) and the batch plan with its effects")
    q.add_argument("--work", required=True); q.add_argument("--json"); q.add_argument("--select", help="k-…,k-…: preview a smaller selection")
    q.add_argument("--except", dest="except_ids", action="append", metavar="ITEM_ID")
    q = s2.add_parser("decide"); q.add_argument("--work", required=True); q.add_argument("--item")
    g = q.add_mutually_exclusive_group(required=True)
    g.add_argument("--approve", action="store_true"); g.add_argument("--reject", action="store_true"); g.add_argument("--edit", metavar="TEXT")
    g.add_argument("--approve-batch", metavar="BATCH_ID")
    q.add_argument("--select", help="with --approve-batch: approve only these members (k-…,k-…)")
    q.add_argument("--except", dest="except_ids", action="append", metavar="ITEM_ID")
    q.add_argument("--attest-paraphrase", action="store_true", help="with --approve: you checked that the paraphrase says what the quote says")
    q.add_argument("--reason", default="")
    q = s2.add_parser("repair", help="set aside an incomplete last decision line after an interrupted write"); q.add_argument("--work", required=True)
    q = s2.add_parser("build"); q.add_argument("--work", required=True)
    q = s2.add_parser("answer"); q.add_argument("--work", required=True); q.add_argument("--item", required=True)
    g = q.add_mutually_exclusive_group(required=True); g.add_argument("--text"); g.add_argument("--reveal", action="store_true")
    q = s2.add_parser("export", help="packet v3: full or minimal, with optional omissions; kept in the work directory when written")
    q.add_argument("--work", required=True); q.add_argument("--mode", choices=("study", "tutor"), default="study")
    q.add_argument("--include-rubrics", action="store_true"); q.add_argument("--variant", choices=("full", "minimal"), default="full")
    q.add_argument("--omit", action="append", choices=sorted(("learner_goal", "evidence_text", "practice_history", "last_confusion")))
    q.add_argument("--previous", help="a packet file, or 'latest' for the last full packet kept in the work directory")
    q.add_argument("--awaiting", nargs=2, metavar=("PACKET", "RETURN"), help="list this return's unaccepted proposals as 'awaiting the learner'")
    q.add_argument("--agent", choices=("codex", "claude-code", "any-agent"), help="with --out: copy only this agent's prompt")
    g = q.add_mutually_exclusive_group(required=True); g.add_argument("--preview", action="store_true"); g.add_argument("--out")
    q = s2.add_parser("import-preview", help="read-only preview of any return (v1 or v2) against any packet (v1, v2, v3)")
    q.add_argument("--packet", required=True); q.add_argument("--proposals", required=True); q.add_argument("--work"); q.add_argument("--json")
    q = s2.add_parser("accept", help="accept one agent correction (as practice accept)")
    q.add_argument("--work", required=True); q.add_argument("--packet", required=True); q.add_argument("--proposals", required=True)
    q.add_argument("--proposal", required=True); q.add_argument("--reason", default="")
    q = s2.add_parser("exercise", help="your decision on one agent exercise proposal (approve, optionally edited, or reject)")
    q.add_argument("--work", required=True); q.add_argument("--packet", required=True); q.add_argument("--proposals", required=True)
    q.add_argument("--proposal", required=True)
    g = q.add_mutually_exclusive_group(required=True); g.add_argument("--approve", action="store_true"); g.add_argument("--reject", action="store_true")
    q.add_argument("--prompt"); q.add_argument("--answer"); q.add_argument("--accepted", action="append", help="repeatable: replaces the accepted variants")
    q.add_argument("--options", help="a|b: replaces the options"); q.add_argument("--reason", default="")
    q = s2.add_parser("feed", help="the v1 feed with the 2.2 additions"); q.add_argument("--work", required=True); q.add_argument("--out", required=True)
    q.add_argument("--seq", type=int, required=True); q.add_argument("--previous")
    q = s2.add_parser("storage", help="fixture-only round trip through the Workbooks storage proposal (in memory)")
    q.add_argument("--work", required=True); q.add_argument("--json")
    q = s2.add_parser("matrix", help="the acceptance matrix, executed"); q.add_argument("--out", required=True)
    q = s2.add_parser("measure", help="interactions to first practice and first unaided practice, 2.1 vs 2.2, executed")
    q.add_argument("--out", required=True); q.add_argument("--json")
    q = s2.add_parser("trial", help="render the delayed-probe materials and the dry-run summary")
    q.add_argument("--out", required=True); q.add_argument("--check", action="store_true")
    q = s2.add_parser("demo3", help="Extraction 2.2 demo with fixed expected outputs and the sealed workbooks2 bundle")
    q.add_argument("--out", required=True); q.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "practice":
        return practice_cli(a)
    if a.cmd == "practice2":
        return practice2_cli(a)
    if a.cmd == "evidence-review":
        from . import evidence_review
        rep = evidence_review.build(a.refs, a.a, a.b, a.limit, a.page)
        if a.json:
            dump(a.json, rep)
        md = evidence_review.markdown(rep)
        if a.md:
            Path(a.md).write_text(md, encoding="utf-8")
        else:
            sys.stdout.write(md)
        return 0
    if a.cmd == "review-sample":
        rows = review_sample.packet(review_sample.select(records.load_jsonl(a.slice), records.load_jsonl(a.challenge)))
        sel = review_sample.selection_doc(rows, comparison.sha256_file(a.slice), comparison.sha256_file(a.challenge))
        write_jsonl(a.out + ".jsonl", rows)
        dump(a.out + "-selection.json", sel)
        Path(a.out + ".md").write_text(review_sample.markdown(rows, sel) + "\n", encoding="utf-8")
        print(json.dumps({k: sel[k] for k in ("items", "records", "by_stratum", "disputed", "objective_points_covered")},
                         ensure_ascii=False))
        return 0
    if a.cmd == "review-agreement":
        rep = review_sample.agreement(records.load_jsonl(a.packet), records.load_jsonl(a.second) if a.second else None)
        dump(a.out + ".json", rep)
        print(json.dumps({k: rep[k] for k in ("intent_agreement_with_reference", "disputed_unresolved")}, ensure_ascii=False))
        return 0
    if a.cmd == "review-sheet":
        packet = records.load_jsonl(a.packet)
        if a.action == "export":
            Path(a.out).write_text(review_sheet.export(packet), encoding="utf-8")
            print(json.dumps({"items": len(packet), "rows": sum(max(1, len(i["reference"]["units"])) for i in packet)}))
            return 0
        if not a.sheet:
            raise SystemExit("review-sheet import needs --sheet")
        try:
            filled, rep = review_sheet.load(packet, Path(a.sheet).read_text(encoding="utf-8-sig"))
        except ValueError as e:
            print(json.dumps({"refused": str(e)}, ensure_ascii=False))
            return 1
        write_jsonl(a.out, filled)
        print(json.dumps(rep, ensure_ascii=False))
        return 0
    if a.cmd == "experimental-report":
        rd = lambda x: json.loads(Path(x).read_text(encoding="utf-8")) if x else None  # noqa: E731
        try:
            rows = reviewer_evidence.load_evidence(records.load_jsonl(a.reviewer_evidence)) if a.reviewer_evidence else None
        except ValueError as e:
            print(json.dumps({"refused": f"reviewer evidence: {e}"}, ensure_ascii=False))
            return 1
        rep = experimental_report.report(rd(a.comparison), rd(a.human_evidence),
                                         [r for f in a.review for r in records.load_jsonl(f)] or None,
                                         rd(a.reviewer_queue), rows)
        dump(a.out + ".json", rep)
        Path(a.out + ".md").write_text(experimental_report.markdown(rep), encoding="utf-8")
        print(json.dumps({"verdict": rep["verdict"], "preference": rep["preference"], "production_go": rep["production_go"]}))
        return experimental_report.EXIT[rep["verdict"]]
    if a.cmd == "reviewer-queue":
        m = json.loads(Path(a.matrix).read_text(encoding="utf-8"))
        refs = records.load_jsonl(a.slice)
        if comparison.sha256_file(a.slice) != m["slice"]["files"]["comparison-slice.jsonl"]["sha256"]:
            raise SystemExit("slice hash differs from the matrix")
        if a.scope_ids and a.scope_packet:
            raise SystemExit("give --scope-ids or --scope-packet, not both")
        if a.scope_ids:
            scope = [x.strip() for x in Path(a.scope_ids).read_text(encoding="utf-8").splitlines() if x.strip()]
            source = f"ids file {Path(a.scope_ids).name} ({comparison.sha256_file(a.scope_ids)[:12]})"
        elif a.scope_packet:
            ids = {r["id"] for r in refs}
            scope = [i["id"] for i in records.load_jsonl(a.scope_packet) if i["id"] in ids]
            source = f"review packet {Path(a.scope_packet).name} ({comparison.sha256_file(a.scope_packet)[:12]}), ids in the slice"
        else:
            scope, source = [r["id"] for r in refs], "every slice record"
        validate = controls.render_validator(a.render, Path(a.out + ".work"))
        ids, inputs, accounts = [r["id"] for r in refs], {r["id"]: r["input"] for r in refs}, {}
        for x in a.predictions:
            k, f = x.split("=", 1)
            if k not in {s["system"] for s in m["systems"]}:
                raise SystemExit(f"unknown system {k}")
            rows = records.load_jsonl(f)
            raw = [r for r in rows if "output_text" in r]
            if raw and len(raw) != len(rows):
                raise SystemExit(f"{k}: a prediction file mixes raw outputs and production results")
            accounts[k] = comparison.account_with_validator(ids, inputs, raw, validate) if raw else matrix.account_results(ids, rows)
        try:
            q = reviewer_evidence.queue(refs, accounts, scope, m["matrix_sha256"], comparison.sha256_file(a.slice), source)
        except ValueError as e:
            raise SystemExit(str(e))
        dump(a.out + ".json", q)
        write_jsonl(a.out + ".evidence-template.jsonl", reviewer_evidence.template(q))
        Path(a.out + ".md").write_text(reviewer_evidence.markdown(q), encoding="utf-8")
        print(json.dumps({"scope_records": q["scope"]["records"], **{s: v["units_in_scope"] for s, v in q["systems"].items()}}))
        return 0
    if a.cmd == "one-record-fixture":
        fx = fixture_one_record.load(a.fixture or fixture_one_record.FIXTURE_DIR)
        doc = fixture_one_record.run(fx, a.out)
        if not a.check:
            print(json.dumps({"cases": len(doc["cases"]), "out": "actual.json"}))
            return 0
        exp = json.loads((Path(a.fixture or fixture_one_record.FIXTURE_DIR) / "expected.json").read_text(encoding="utf-8"))
        problems = fixture_one_record.diff(exp["expect"], fixture_one_record.project(doc))
        print(json.dumps({"matches_expected": not problems, "differences": problems}, ensure_ascii=False))
        return 1 if problems else 0
    if a.cmd == "export-check":
        bad = {f: review_sample.export_findings(Path(f).read_text(encoding="utf-8")) for f in a.files}
        bad = {f: v for f, v in bad.items() if v}
        print(json.dumps({"files": len(a.files), "findings": bad}, ensure_ascii=False))
        return 1 if bad else 0
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
        chl_refs = records.load_jsonl(a.challenge)
        rep = paired.report(chl_refs, load_results(a.results, chl_refs),
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
        refs = records.load_jsonl(a.refs)
        rep = quality.report(refs, load_results(a.results, refs), judg,
                             records.load_jsonl(a.outputs) if a.outputs else None)
        dump(a.out + ".json", rep)
        Path(a.out + ".md").write_text(quality.markdown(rep, a.title), encoding="utf-8")
        print(json.dumps({k: v[0] for k, v in rep["headline"].items()}, ensure_ascii=False))
        return 0
    if a.cmd == "quality-compare":
        A, B = (json.loads(Path(x).read_text(encoding="utf-8")) for x in (a.a, a.b))
        cmp_ = quality.compare(A, B)
        dump(a.out + ".json", cmp_)
        lines = []
        if A.get("examples") != B.get("examples"):
            note = (f"WARNING: A covers {A.get('examples')} examples and B {B.get('examples')}: different populations, "
                    "so the deltas are not like for like")
            print(note, file=sys.stderr)
            lines += [note, ""]
        lines += ["| Metric | A | B | Δ | Basis |", "|---|---|---|---|---|"]
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
        results = load_results(a.results, refs)
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
        refs = records.load_jsonl(a.refs)
        s = categories.summarize(refs, load_results(a.results, refs),
                                 json.loads(Path(a.report).read_text(encoding="utf-8")))
        dump(a.out + ".json", s)
        Path(a.out + ".md").write_text(categories.markdown(s, a.title), encoding="utf-8")
        print(json.dumps({k: s[k] for k in ("schema_validity", "unsupported", "abstention", "splitting")}, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
