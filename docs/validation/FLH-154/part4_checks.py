"""FLH-154 part 4: the one-record fixture through the production validator and the CLI (OFFLINE ONLY).

  python3 -I -B docs/validation/FLH-154/part4_checks.py --repo . --render BIN --work DIR --out docs/validation/FLH-154/part4
         [--pins PINS.sha256] [--xr-before PART3/experimental_report.py]

Run inside a network namespace with loopback only (extraction-render render uses
an in-process fake analyzer server). BIN is `go build ./cmd/extraction-render`;
DIR is scratch outside the repository. Writes OUT/actual.json (library path, full),
OUT/part4-checks.json and .md (CLI results, file digests, pins). No provider, AWS,
model, download or Git; the pinned scorer, decision.py and the published
comparison digests are only read.
"""

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

A = argparse.ArgumentParser()
A.add_argument("--repo", required=True)
A.add_argument("--render", required=True)
A.add_argument("--work", required=True)
A.add_argument("--out", required=True)
A.add_argument("--pins")
A.add_argument("--xr-before")
ARGS = A.parse_args()
REPO = Path(ARGS.repo).resolve()
TOOLS = REPO / "tools" / "extraction"
BIN, WORK, OUT = Path(ARGS.render).resolve(), Path(ARGS.work).resolve(), Path(ARGS.out).resolve()
sys.path.insert(0, str(TOOLS))

from flh_extraction import comparison, decision, experimental_report as xr  # noqa: E402
from flh_extraction import fixture_one_record as fx1, reviewer_evidence as rev  # noqa: E402

R = {}
FX = fx1.load()
EXPECTED = json.loads((fx1.FIXTURE_DIR / "expected.json").read_text(encoding="utf-8"))
CLI = WORK / "cli"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def write_jsonl(p, rows):
    Path(p).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def cli(*args, ok=(0,)):
    p = subprocess.run([sys.executable, "-B", "-m", "flh_extraction", *map(str, args)], cwd=TOOLS, capture_output=True, text=True)
    if p.returncode not in ok:
        raise SystemExit(f"flh_extraction {args[0]} exit {p.returncode}: {p.stderr[-800:]}{p.stdout[-400:]}")
    return p.returncode, p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""


def render(*args):
    subprocess.run([str(BIN), *map(str, args)], check=True, capture_output=True)


def library():
    doc = fx1.run(FX, WORK / "lib")
    diff = fx1.diff(EXPECTED["expect"], fx1.project(doc))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "actual.json").write_bytes((WORK / "lib" / "actual.json").read_bytes())
    R["c1_library_expected_vs_actual"] = {"status": "PASS" if not diff else "FAIL", "differences": diff,
                                          "actual_sha256": sha(OUT / "actual.json"), "expected_sha256": sha(fx1.FIXTURE_DIR / "expected.json")}
    return doc


def slice_and_matrix():
    I = WORK / "lib" / "inputs"
    CLI.mkdir(parents=True, exist_ok=True)
    for p in ("frozen", "rb", "challenge"):
        render("render", "-in", I / f"{p}.jsonl", "-out", CLI / f"{p}-rendered.jsonl")
    render("analyze", "-in", I / "frozen.jsonl", "-out", CLI / "analyses.jsonl")
    fresh = {a["id"]: {k: a[k] for k in ("analyzer", "effective_category", "effective_explanation")} for a in jl(CLI / "analyses.jsonl")}
    recorded = {k: v for k, v in FX["rule_based_analyses"].items() if k != "note"}
    cli("probe", "--eval", I / "frozen.jsonl", "--analyses", CLI / "analyses.jsonl", "--variant", "rb", "--out", CLI / "probe-rb.jsonl")
    cli("comparison-slice", "--eval", I / "frozen.jsonl", "--probe-rb", I / "rb.jsonl", "--challenge", I / "challenge.jsonl",
        "--rendered", CLI / "frozen-rendered.jsonl", CLI / "rb-rendered.jsonl", CLI / "challenge-rendered.jsonl", "--out", CLI / "slice")
    cli("comparison-matrix", "--slice-dir", CLI / "slice", "--rendered", CLI / "frozen-rendered.jsonl", "--repo", REPO, "--out", CLI / "matrix.json")
    m = json.loads((CLI / "matrix.json").read_text(encoding="utf-8"))
    pinned = json.loads((REPO / "deploy/aws/sagemaker-extractor/readiness/comparison-matrix.json").read_text(encoding="utf-8"))
    ok = fresh == recorded and (CLI / "probe-rb.jsonl").read_bytes() == (I / "rb.jsonl").read_bytes() and m["slice"]["records"] == 10
    R["c2_fixture_slice"] = {"status": "PASS" if ok else "FAIL", "recorded_analyses_equal_fresh_analyzer_run": fresh == recorded,
                             "rb_probe_byte_equal": (CLI / "probe-rb.jsonl").read_bytes() == (I / "rb.jsonl").read_bytes(),
                             "parts": m["slice"]["parts"], "fixture_matrix_sha256": m["matrix_sha256"],
                             "fixture_scoring_version_equals_pinned_matrix": m["scoring_version"]["sha256"] == pinned["scoring_version"]["sha256"],
                             "note": "a fixture-only matrix; the pinned comparison matrix is only read"}
    return m


def slot_rows(rows, slots):
    back = {s: slot for slot, s in slots.items()}
    return [dict(r, system=back[r["system"]]) for r in (rows or []) if r["system"] in back]


def scenario(name, slots, lib_q, ev):
    I = WORK / "lib" / "inputs"
    d = CLI / f"scenario-{name}"
    d.mkdir(parents=True, exist_ok=True)
    preds = [f"{slot}={I / f'predictions-{s}.jsonl'}" for slot, s in slots.items()]
    sl, mx = CLI / "slice" / "comparison-slice.jsonl", CLI / "matrix.json"
    cli("compare", "--matrix", mx, "--slice", sl, "--render", BIN, "--predictions", *preds, "--out", d / "compare")
    cli("reviewer-queue", "--matrix", mx, "--slice", sl, "--render", BIN, "--predictions", *preds, "--out", d / "queue")
    comp = json.loads((d / "compare.json").read_text(encoding="utf-8"))
    q = json.loads((d / "queue.json").read_text(encoding="utf-8"))
    same_items = all([(i["id"], i["unit"], i["unit_sha256"]) for i in q["systems"][slot]["items"]] ==
                     [(i["id"], i["unit"], i["unit_sha256"]) for i in lib_q["systems"][s]["items"]] for slot, s in slots.items())
    statuses = {slot: v["rows"]["status_counts"] for slot, v in comp["systems"].items()}
    human = {slot: FX["assumed_human_evidence"]["experimental"][s] for slot, s in slots.items()}
    dhuman = {slot: FX["assumed_human_evidence"]["decision"][s] for slot, s in slots.items()}
    for k, v in (("human.json", human), ("decision-human.json", dhuman), ("input-manifest.json", fx1.INPUT_MANIFEST),
                 ("run-manifest.json", fx1.RUN_MANIFEST)):
        (d / k).write_text(json.dumps(v, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    write_jsonl(d / "review-ok.jsonl", fx1.REVIEW_OK)
    write_jsonl(d / "losses.jsonl", fx1.LOSSES)
    runs = {}
    base = ["experimental-report", "--comparison", d / "compare.json", "--human-evidence", d / "human.json", "--review", d / "review-ok.jsonl"]
    for k in ("none", "blank", "full", "fails_correct", "invalid"):
        args = list(base)
        if k != "none":
            rows = slot_rows(ev["full" if k == "invalid" else k], slots)
            if k == "invalid":                       # one answer that is not yes, no or blank, in this scenario's systems
                rows[0] = dict(rows[0], claim_true="maybe")
            write_jsonl(d / f"evidence-{k}.jsonl", rows)
            args += ["--reviewer-queue", d / "queue.json", "--reviewer-evidence", d / f"evidence-{k}.jsonl"]
        code, line = cli(*args, "--out", d / f"xr-{k}", ok=(0, 1, 3))
        runs[k] = {"exit": code, "stdout": json.loads(line)}
        if (d / f"xr-{k}.json").exists():
            rep = json.loads((d / f"xr-{k}.json").read_text(encoding="utf-8"))
            runs[k]["eligible"] = {slots[s]: v["eligible"] for s, v in rep["systems"].items()}
            runs[k]["reviewer"] = {slots[s]: v["reviewer"]["status"] for s, v in rep["systems"].items()}
    code, line = cli("decision-report", "--comparison", d / "compare.json", "--human", d / "decision-human.json", "--review", d / "review-ok.jsonl",
                     "--losses", d / "losses.jsonl", "--run-manifest", d / "run-manifest.json", "--input-manifest", d / "input-manifest.json",
                     "--out", d / "decision", ok=(0, 1, 3))
    dec = json.loads((d / "decision.json").read_text(encoding="utf-8"))
    return {"slots": slots, "validator_status_counts": statuses, "queue_items_equal_library_hashes": same_items,
            "units_in_scope": {slot: q["systems"][slot]["units_in_scope"] for slot in slots},
            "experimental_report": runs,
            "decision_report": {"exit": code, "verdict": dec["verdict"], "winner": dec["winner"],
                                "winner_system": slots.get(dec["winner"]) if dec["winner"] else None,
                                "eligible": {slots[s]: v["eligible"] for s, v in dec["systems"].items()}}}


def scenarios(doc):
    lib_parts = fx1.build(FX)
    refs = fx1.slice_refs(lib_parts)
    raw, res = fx1.outputs(FX, refs)
    comp, accounts = fx1.comparison_report(refs, res)
    lib_q = rev.queue(refs, accounts, [r["id"] for r in refs], fx1.LIBRARY_MATRIX, "library", fx1.SCOPE)
    ev = fx1.evidence_sets(FX, lib_q)
    out = {k: scenario(k, v, lib_q, ev) for k, v in FX["cli_scenarios"].items() if k != "note"}
    exp = EXPECTED["expect"]["decision_scenarios"]
    a, b = out["A"]["experimental_report"], out["B"]["experimental_report"]
    valid = all(set(c) <= {"valid_units", "valid_empty"} for s in out.values() for c in s["validator_status_counts"].values())
    ok = (valid and all(s["queue_items_equal_library_hashes"] for s in out.values())
          and all(out[k]["decision_report"]["verdict"] == exp[k]["verdict"] and out[k]["decision_report"]["winner_system"] == exp[k]["winner_system"]
                  for k in exp)
          and a["none"]["stdout"]["verdict"] == "PENDING" and a["blank"]["stdout"]["verdict"] == "PENDING"
          and a["full"]["stdout"] == {"verdict": "EXPERIMENTAL_PREFERENCE", "preference": "current_extractor", "production_go": False}
          and a["fails_correct"]["stdout"]["verdict"] == "NO_PREFERENCE" and a["invalid"]["exit"] == 1 and "refused" in a["invalid"]["stdout"]
          and b["full"]["stdout"] == {"verdict": "EXPERIMENTAL_PREFERENCE", "preference": "qwen3.5-4b-tuned", "production_go": False}
          and b["none"]["stdout"]["verdict"] == "PENDING" and b["invalid"]["exit"] == 1 and "refused" in b["invalid"]["stdout"])
    R["c3_cli_scenarios"] = {"status": "PASS" if ok else "FAIL", "every_fixture_output_accepted_by_the_production_validator": valid,
                             "scenarios": out}
    return comp, lib_q, ev


def before_after(comp, lib_q, ev):
    human = FX["assumed_human_evidence"]["experimental"]
    v1 = {"no reviewer evidence": xr.report(comp, human, fx1.REVIEW_OK),
          "with reviewer evidence": xr.report(comp, human, fx1.REVIEW_OK, lib_q, ev["full"])}
    out = {k: {"schema": v["schema"], "verdict": v["verdict"], "preference": v["preference"]} for k, v in v1.items()}
    if ARGS.xr_before:
        spec = importlib.util.spec_from_file_location("flh_extraction._xr_part3", ARGS.xr_before)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        v0 = mod.report(comp, human, fx1.REVIEW_OK)
        out["part-3 draft (v0), same aggregates"] = {"schema": v0["schema"], "verdict": v0["verdict"], "preference": v0["preference"],
                                                     "source_sha256": sha(ARGS.xr_before)}
    ok = (out["no reviewer evidence"]["verdict"] == "PENDING" and out["with reviewer evidence"]["preference"] == "correct"
          and (not ARGS.xr_before or out["part-3 draft (v0), same aggregates"]["preference"] == "unsupported_claim"))
    R["c4_before_after"] = {"status": "PASS" if ok else "FAIL", "runs": out,
                            "reading": "With the same assumed aggregate evidence (clean samples), the part-3 draft prefers the "
                                       "false-claim system; v1 waits for per-unit reviewer evidence and, with it, excludes the "
                                       "false-claim and drifted systems and prefers the correct one."}


def pins():
    pinned = json.loads((REPO / "deploy/aws/sagemaker-extractor/readiness/comparison-matrix.json").read_text(encoding="utf-8"))
    sv = comparison.scoring_version()
    out = {"scoring_version": sv["sha256"], "pinned_matrix_scoring_version": pinned["scoring_version"]["sha256"],
           "pinned_matrix_sha256": pinned["matrix_sha256"], "decision_py_sha256": sha(TOOLS / "flh_extraction" / "decision.py"),
           "decision_version": decision.VERSION,
           "new_modules_not_scoring_sources": [m for m in ("reviewer_evidence.py", "fixture_one_record.py", "experimental_report.py")
                                               if m not in comparison.SCORING_SOURCES]}
    ok = sv["sha256"] == pinned["scoring_version"]["sha256"] and len(out["new_modules_not_scoring_sources"]) == 3
    if ARGS.pins:
        bad = []
        lines = [x.split(None, 1) for x in Path(ARGS.pins).read_text(encoding="utf-8").splitlines() if x.strip()]
        for h, p in lines:
            if sha(REPO / p.strip()) != h:
                bad.append(p.strip())
        out["pinned_files"] = {"checked": len(lines), "changed": bad}
        ok = ok and not bad
    R["c5_release_scoring_intact"] = {"status": "PASS" if ok else "FAIL", **out}


def digests():
    files = sorted(p for p in CLI.rglob("*") if p.is_file())
    R["c6_cli_output_digests"] = {"status": "DONE", "files": len(files),
                                  "sha256": {p.relative_to(CLI).as_posix(): sha(p) for p in files}}


def md():
    L = ["# FLH-154 part 4 checks (OFFLINE ONLY)", "",
         "Generated by `part4_checks.py`: the one-record fixture through the library reports and through the CLI with the "
         "production validator. Synthetic only; no provider, model, AWS or Git.", "",
         "| Check | Status |", "|---|---|"]
    L += [f"| {k} | {v['status']} |" for k, v in R.items()]
    c3 = R["c3_cli_scenarios"]["scenarios"]
    L += ["", "## CLI scenarios", "", "| Scenario | Slots | decision-report (unchanged) | experimental: no evidence | blank template | "
          "full evidence | reviewer fails the correct unit | invalid answer |", "|---|---|---|---|---|---|---|---|"]
    for k, s in c3.items():
        x = s["experimental_report"]
        cell = lambda r: r["stdout"].get("verdict", "refused") + (f" `{r['stdout']['preference']}`" if r["stdout"].get("preference") else "")  # noqa: E731
        L.append(f"| {k} | {', '.join(f'{a}={b}' for a, b in s['slots'].items())} | {s['decision_report']['verdict']}"
                 f"{' `' + s['decision_report']['winner_system'] + '`' if s['decision_report']['winner_system'] else ''} | "
                 f"{cell(x['none'])} | {cell(x['blank'])} | {cell(x['full'])} | {cell(x['fails_correct'])} | exit {x['invalid']['exit']} |")
    L += ["", "## Before / after (same assumed aggregate evidence)", "", "| Report | Verdict | Preference |", "|---|---|---|"]
    for k, v in R["c4_before_after"]["runs"].items():
        L.append(f"| {k} ({v['schema']}) | {v['verdict']} | {v['preference'] or '—'} |")
    c5 = R["c5_release_scoring_intact"]
    L += ["", "## Release scoring", "", f"- scoring version `{c5['scoring_version'][:16]}…` = pinned matrix "
          f"`{c5['pinned_matrix_scoring_version'][:16]}…` (matrix `{c5['pinned_matrix_sha256'][:16]}…`)",
          f"- decision.py `{c5['decision_py_sha256'][:16]}…` ({c5['decision_version']})"]
    if "pinned_files" in c5:
        L.append(f"- pinned files: {c5['pinned_files']['checked']} checked, changed: {c5['pinned_files']['changed'] or 'none'}")
    return "\n".join(L) + "\n"


def main():
    doc = library()
    slice_and_matrix()
    comp, lib_q, ev = scenarios(doc)
    before_after(comp, lib_q, ev)
    pins()
    digests()
    full = {"schema": "flh154_part4_checks_v1", "offline_only": True, "synthetic_only": True, "real_runs_performed": 0, **R}
    (OUT / "part4-checks.json").write_text(json.dumps(full, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "part4-checks.md").write_text(md(), encoding="utf-8")
    print(json.dumps({k: v["status"] for k, v in R.items()}, indent=1))
    return 0 if all(v["status"] in ("PASS", "DONE") for v in R.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
