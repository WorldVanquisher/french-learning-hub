"""FLH-154: offline review of the extraction evaluation before any paid run.

  bash tools/extraction/scripts/comparison_pipeline.sh OUT1
  bash tools/extraction/scripts/comparison_pipeline.sh OUT2        # a second, independent regeneration
  python3 -I -B docs/validation/FLH-154/review_checks.py --repo . --pipeline OUT1 --pipeline2 OUT2 \
      --out docs/validation/FLH-154 [--asset-dir DIR …]

Reads the regenerated datasets, the committed readiness package and the
scoring code; drives the production validator (OUT1/bin/extraction-render
validate, an in-process fake server, no network) for the synthetic systems.
Writes OUT/review-checks.json and OUT/review-checks.md. Changes nothing in the
repository, calls no provider, no AWS, no model; downloads nothing.

Every system here is synthetic (oracle = the machine-authored references).
Results show what the harness does, never how a real model behaves.
"""

import argparse
import copy
import hashlib
import json
import random
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

A = argparse.ArgumentParser()
A.add_argument("--repo", required=True)
A.add_argument("--pipeline", required=True)
A.add_argument("--pipeline2")
A.add_argument("--out", required=True)
A.add_argument("--asset-dir", action="append", default=[])
A.add_argument("--image-packaging", help="saved packaging report of the local training image (JSON)")
ARGS = A.parse_args()

REPO = Path(ARGS.repo).resolve()
OUT = Path(ARGS.pipeline).resolve()
TOOLS = REPO / "tools" / "extraction"
READY = REPO / "deploy" / "aws" / "sagemaker-extractor" / "readiness"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "deploy" / "aws" / "sagemaker-extractor"))

from flh_extraction import audit, challenge, comparison, controls, decision, matrix, paired, quality, sft  # noqa: E402
from flh_extraction.textnorm import norm  # noqa: E402

BIN = OUT / "bin" / "extraction-render"
WORK = Path(tempfile.mkdtemp(prefix="flh154-"))
VALIDATE = controls.render_validator(BIN, WORK / "validate")
TS = re.compile(r"\d{8}-\d{6}")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def jd(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def rel(p):
    return str(Path(p).resolve().relative_to(REPO)) if str(Path(p).resolve()).startswith(str(REPO)) else Path(p).name


D = {
    "eval": jl(OUT / "eval" / "eval_candidates.jsonl"),
    "train": jl(OUT / "train" / "candidates.jsonl"),
    "inc": jl(OUT / "inc" / "increment_candidates.jsonl"),
    "boundary": jl(OUT / "boundary" / "boundary_cases_v1.jsonl"),
    "chl": jl(OUT / "chl" / "challenge_candidates.jsonl"),
    "rb": jl(OUT / "probe-rb.jsonl"),
    "swap": jl(OUT / "probe-swap.jsonl"),
    "slice": jl(OUT / "slice" / "comparison-slice.jsonl"),
    "prompts": jl(OUT / "slice" / "comparison-prompts.jsonl"),
    "inputs": jl(OUT / "slice" / "comparison-inputs.jsonl"),
    "sft_train": jl(OUT / "rd" / "sft-train.jsonl"),
    "sft_dev": jl(OUT / "rd" / "sft-dev.jsonl"),
}
MATRIX = jd(READY / "comparison-matrix.json")
REFS = D["slice"]
IDS = [r["id"] for r in REFS]
INPUTS = {r["id"]: r["input"] for r in REFS}
R = {}


def status(ok, finding=False):
    return "FINDING" if finding else ("PASS" if ok else "FAIL")


# ---------------------------------------------------------------- 1. revisions
def cp01():
    em = jd(READY / "experiment-manifest.json")
    files = {"frozen_eval": OUT / "eval" / "eval_candidates.jsonl", "challenge_slice": OUT / "chl" / "challenge_candidates.jsonl",
             "comparison_slice": OUT / "slice" / "comparison-slice.jsonl"}
    rec = {k: comparison.file_entry(p) for k, p in files.items()}
    sv = comparison.scoring_version()
    val = {p: sha(REPO / p) for p in matrix.VALIDATOR_SOURCES}
    gens = {p.name: sha(p) for p in sorted((TOOLS / "authoring").iterdir()) if p.suffix in (".py", ".json")}
    pins = {
        "frozen_eval = experiment-manifest eval_frozen": rec["frozen_eval"]["sha256"] == em["files"]["eval_frozen"]["sha256"],
        "challenge = experiment-manifest challenge_v1": rec["challenge_slice"]["sha256"] == em["files"]["challenge_v1"]["sha256"],
        "comparison slice = matrix pin": rec["comparison_slice"]["sha256"] == MATRIX["slice"]["files"]["comparison-slice.jsonl"]["sha256"],
        "scoring version = matrix pin": sv["sha256"] == MATRIX["scoring_version"]["sha256"],
        "scoring version = experiment-manifest": sv["sha256"] == em["scoring_version_sha256"],
        "scoring files = matrix pin (per file)": sv["files"] == MATRIX["scoring_version"]["files"],
        "validator sources = matrix pin": val == MATRIX["validator_sources"],
        "matrix sha = experiment-manifest": MATRIX["matrix_sha256"] == em["comparison_matrix_sha256"],
    }
    unpinned = {"flh_extraction/decision.py (decision criteria)": sha(TOOLS / "flh_extraction" / "decision.py"),
                "flh_extraction/predict.py (decoding code)": sha(TOOLS / "flh_extraction" / "predict.py"),
                "flh_extraction/records.py (JSONL loader used by compare)": sha(TOOLS / "flh_extraction" / "records.py")}
    gv = subprocess.run(["go", "version"], capture_output=True, text=True).stdout.strip()
    R["cp01_revisions"] = {
        "status": status(all(pins.values()), finding=all(pins.values())),
        "base_sha_from_task": "198b23f14489c26cef6ea1c34f96714c843f00db (not verified with Git: agents run no Git)",
        "frozen_eval": rec["frozen_eval"], "challenge_slice": rec["challenge_slice"], "comparison_slice": rec["comparison_slice"],
        "comparison_parts": MATRIX["slice"]["parts"],
        "scorer": {"scoring_version": sv["sha256"], "files": sv["files"], "validator_sources": val,
                   "validator_binary_sha256": sha(BIN), "go": gv,
                   "note": "the binary hash depends on the Go toolchain; the matrix pins the validator SOURCES"},
        "authoring_sources": gens, "pins_hold": pins,
        "not_pinned_by_the_matrix": unpinned,
        "finding": "compare checks the slice hash and the scoring-module hash but not validator_sources: a --render binary "
                   "built from changed Go validation code is accepted silently; decision.py (the gates) is outside the "
                   "scoring version, so a gate change does not alter the matrix hash",
    }


# ---------------------------------------------------------------- 2. shortcut
def cue_table(rs):
    t = Counter()
    for r in rs:
        t[("category_other" if r["input"]["effective_category"] == "other" else "category_not_other",
           "ref_zero" if not r["expected"]["units"] else "ref_units")] += 1
    return {f"{a}/{b}": t[(a, b)] for a in ("category_other", "category_not_other") for b in ("ref_zero", "ref_units")}


def category_only_independent(rs):
    """Written from the definition, not from controls.py: abstain iff category is `other`, else answer the
    reference (an invented unit when the reference is empty)."""
    return {r["id"]: "empty" if r["input"]["effective_category"] == "other" else "units" for r in rs}


def cp02():
    parts = {"frozen": D["eval"], "rb": D["rb"], "swap": D["swap"],
             "challenge_test": [r for r in D["chl"] if r["meta"]["split_group"] == "challenge_test"]}
    tables = {k: cue_table(v) for k, v in parts.items()}
    indep = {}
    for k, rs in parts.items():
        dec = category_only_independent(rs)
        want = {r["id"]: "units" if r["expected"]["units"] else "empty" for r in rs}
        wrong = Counter((want[i], d) for i, d in dec.items() if d != want[i])
        indep[k] = {"records": len(rs), "decisions_equal_reference": sum(dec[i] == want[i] for i in dec),
                    "false_extraction": wrong[("empty", "units")], "over_abstention": wrong[("units", "empty")]}
    committed = jd(REPO / "docs" / "validation" / "EXTRACTOR-COMPARISON-V1" / "shortcut-repro.json")
    regen = jd(OUT / "evidence" / "shortcut" / "shortcut-repro.json")
    same = committed == regen
    fz = indep["frozen"]
    R["cp02_shortcut"] = {
        "status": status(same and fz["decisions_equal_reference"] == fz["records"] and indep["rb"]["false_extraction"] > 0),
        "cue_by_reference": tables,
        "independent_category_only": indep,
        "committed_shortcut_repro_equals_regenerated": same,
        "regenerated_runs": {k: v["confusion"]["abstention"] for k, v in regen["runs"].items()},
        "reading": "On the frozen evaluation the category cue separates zero-unit from unit references perfectly "
                   "(every zero reference is `other`, no unit reference is), so a category-only system is "
                   "indistinguishable from the oracle there; rb and the challenge break the cue.",
    }


# ---------------------------------------------------------------- 3. controls on the whole slice
def run_system(rows):
    acc = comparison.account_with_validator(IDS, INPUTS, rows, VALIDATE)
    res = comparison.scored_results(acc)
    raw = [r for r in rows if "output_text" in r]
    return {"rows": {k: acc[k] for k in ("references", "scorable", "status_counts", "unknown_ids", "unknown_id_rows")},
            "metrics": matrix._metrics(REFS, res, raw or None), "status": "MEASURED"}


def summarize(sysrep):
    m = sysrep["metrics"]
    gs = decision.gates(sysrep)
    return {"strict_validity": round(sysrep["rows"]["scorable"] / sysrep["rows"]["references"], 3),
            "frozen_abstention": m["frozen"]["headline"]["abstention_rate"], "frozen_over_abstention": m["frozen"]["over_abstention_rate"],
            "rb_abstention": m["rb"]["headline"]["abstention_rate"], "rb_over_abstention": m["rb"]["over_abstention_rate"],
            "rb_false_extraction": m["rb"]["confusion"]["abstention"]["false_extraction"],
            "paired_consistency": m["challenge_test"]["headline"]["paired_consistency"],
            "paired_accuracy": m["challenge_test"]["headline"]["paired_accuracy"],
            "abstain_group_paired_accuracy": m["challenge_test"]["by_intent"]["abstain"]["paired_correct"],
            "extract_group_paired_accuracy": m["challenge_test"]["by_intent"]["extract"]["paired_correct"],
            "frozen_heuristic_unit_f1": m["frozen"]["headline"]["unit_f1"],
            "gates_failed": [g["criterion"] for g in gs if g["status"] == "FAIL"],
            "eligible_on_exact_gates": not any(g["status"] == "FAIL" for g in gs)}


SYS = {}


def cp03():
    for name, control in comparison.SYSTEMS.items():
        SYS[name] = run_system(controls.outputs(REFS, control))
    s = {k: summarize(v) for k, v in SYS.items()}
    ok = (s["oracle"]["eligible_on_exact_gates"] and not s["category_only"]["eligible_on_exact_gates"]
          and not s["constant_empty"]["eligible_on_exact_gates"])
    R["cp03_controls"] = {
        "status": status(ok), "slice_records": len(REFS), "systems": s,
        "reading": "Through the same compare path as a real run (production validator, row accounting, the decision "
                   "gates): the oracle passes every exact gate; category-only fails rb abstention and paired "
                   "consistency while matching the oracle on the frozen evaluation; constant-empty is perfectly "
                   "consistent but fails over-abstention.",
    }


# ---------------------------------------------------------------- 4. learning intent inside pairs
def cp04():
    rendered = {r["id"]: r for f in ("challenge_candidates-rendered.jsonl",) for r in jl(OUT / f)}
    probs = defaultdict(list)
    for gid, rs in challenge.groups_of(D["chl"]).items():
        users = [json.loads(rendered[r["id"]]["user"]) for r in rs]
        keys = set().union(*users)
        differ = sorted(k for k in keys if len({json.dumps(u.get(k), sort_keys=True, ensure_ascii=False) for u in users}) > 1)
        if not set(differ) <= {"effective_category", "effective_explanation", "resolution"}:
            probs["rendered_payload_differs_beyond_cues"].append((gid, differ))
        if len({rendered[r["id"]]["developer"] for r in rs}) != 1:
            probs["developer_instruction_differs"].append(gid)
        intent = rs[0]["meta"]["challenge"]["intent"]
        for r in rs:
            i = r["input"]
            human = i["resolution"] in ("accepted", "corrected")
            says_nothing = i["effective_category"] == "other"
            if human and ((intent == "extract" and says_nothing) or (intent == "abstain" and not says_nothing)):
                probs["human_confirmed_cue_contradicts_reference"].append(r["id"])
        for u in rs[0]["expected"]["units"]:
            if not audit.is_anchored(norm(audit.learner_text(rs[0])), audit.anchor_terms(u)):
                probs["unit_not_lexically_anchored_in_learner_text (heuristic)"].append((gid, u["canonical"]))
        if intent == "abstain":
            conf = next(r for r in rs if r["meta"]["challenge"]["variant"] == "conflicting")
            words = [w for w in re.findall(r"«\s*([^»]+?)\s*»", conf["input"]["effective_explanation"])]
            lt = " " + " ".join(norm(audit.learner_text(conf)).replace("'", " ").split()) + " "
            seen = [w for w in words if " " + " ".join(norm(w).replace("'", " ").split()) + " " in lt]
            if seen:
                probs["abstain_group_cue_names_words_present_in_learner_text (read these)"].append((gid, seen))
    ev = {r["id"]: r for r in D["eval"]}
    lost = {}
    for name in ("rb", "swap"):
        rows = []
        for p in D[name]:
            src = ev[p["meta"]["probe"]["derived_from"]]
            if p["input"]["original_input"] != src["input"]["original_input"] or p["expected"] != src["expected"]:
                probs[f"{name}_pair_changes_learner_text_or_reference"].append(p["id"])
            for u in p["expected"]["units"]:
                t = audit.anchor_terms(u)
                if (not audit.is_anchored(norm(audit.learner_text(p)), t) and audit.is_anchored(norm(src["input"]["effective_explanation"]), t)
                        and not audit.is_anchored(norm(p["input"]["effective_explanation"]), t)):
                    rows.append({"id": p["id"], "unit": u["canonical"], "learner_text": src["input"]["original_input"][:120]})
        lost[name] = rows
    hard = ("rendered_payload_differs_beyond_cues", "developer_instruction_differs", "human_confirmed_cue_contradicts_reference",
            "rb_pair_changes_learner_text_or_reference", "swap_pair_changes_learner_text_or_reference")
    R["cp04_intent"] = {
        "status": status(not any(probs.get(k) for k in hard)),
        "challenge_groups": len(challenge.groups_of(D["chl"])),
        "problems": {k: v for k, v in sorted(probs.items())},
        "probe_units_whose_only_anchor_was_the_replaced_explanation": {k: len(v) for k, v in lost.items()},
        "probe_units_detail": lost["rb"],
        "agent_reading": "Read all 32 groups (96 records) and the 10 rb/swap pairs listed: in every case the learner's "
                         "text alone still raises (or does not raise) the objective, so the shared reference keeps "
                         "its intent. The 10 probe rows are translation requests, sentences marked [?] in a longer "
                         "text, or direct questions whose French answer only the replaced explanation spelled out: "
                         "the reference stays right, but on rb a model must know the answer rather than copy it.",
    }


# ---------------------------------------------------------------- 5. review packets (agent reading, not human verdicts)
def cp05():
    rv = jd(REPO / "docs" / "validation" / "FLH-154" / "agent-review.json")
    v2, v3 = jl(TOOLS / "review" / "review-packet-v2.jsonl"), jl(TOOLS / "review" / "review-packet-v3.jsonl")
    ids = {r["id"] for r in v2} | {r["id"] for r in v3}
    got = {x["id"] for x in rv["items"]}
    filled = [r["id"] for r in v2 + v3 if r.get("verdict") or r.get("label") or r.get("decision_ok") is not None]
    dis = [x for x in rv["items"] if x["agreement"] != "agree"]
    R["cp05_review"] = {
        "status": status(got == ids and not filled, finding=bool(dis)),
        "packet_items": len(ids), "agent_read": len(got & ids), "missing": sorted(ids - got), "extra": sorted(got - ids),
        "packet_verdict_fields_filled": filled,
        "agreement": dict(Counter(x["agreement"] for x in rv["items"])),
        "disagreements": [{k: x[k] for k in ("id", "packet", "machine_label", "agent_label", "note")} for x in dis],
        "note": "An agent's reading is not a human verdict: the packets' verdict fields stay empty and the decision "
                "report keeps treating review as PENDING.",
    }


# ---------------------------------------------------------------- 6. false premises
FP_KEYS = ("false_premise", "wrong_explanation", "misconception")


def is_fp(r):
    m = r["meta"]
    return any(k in (m.get("case_type") or "") or k in (m.get("category") or "") or k in (m.get("mode") or "") for k in FP_KEYS)


def cp06():
    sets = {"frozen_eval": D["eval"], "boundary": D["boundary"], "train": D["train"], "increment": D["inc"], "challenge": D["chl"]}
    fp = {k: [r for r in v if is_fp(r)] for k, v in sets.items()}
    echo = {}
    for k, rs in fp.items():
        e = []
        for r in rs:
            prem = norm(r["input"]["original_input"])
            for u in r["expected"]["units"]:
                st = norm(u["statement"])
                # a premise sentence copied into a statement (>= 6 consecutive words) is an echo candidate
                w = prem.split()
                grams = {" ".join(w[i:i + 6]) for i in range(max(0, len(w) - 5))}
                if any(g in st for g in grams):
                    e.append({"id": r["id"], "unit": u["canonical"]})
        echo[k] = e
    zero = {k: [r["id"] for r in rs if not r["expected"]["units"]] for k, rs in fp.items()}
    # Sensitivity: oracle everywhere, but abstain on every frozen-eval false-premise / wrong-explanation record.
    fz_fp = {r["id"] for r in fp["frozen_eval"]}
    rows = controls.outputs(REFS, "oracle")
    for x in rows:
        if x["id"] in fz_fp:
            x["output_text"] = '{"units": []}'
    rep = run_system(rows)
    s = summarize(rep)
    R["cp06_false_premise"] = {
        "status": status(not any(zero.values()), finding=s["eligible_on_exact_gates"]),
        "records": {k: len(v) for k, v in fp.items()}, "zero_unit_false_premise_references": zero,
        "echo_candidates_6gram": echo,
        "echo_candidates_agent_reading": "each candidate shares a CORRECT phrase with the learner's text (« en bus, en train »; "
                                         "« ça fait deux ans que j'apprends »); no statement repeats the premise as true",
        "frozen_eval_cases": [{"id": r["id"], "case": r["meta"].get("case_type"), "resolution": r["input"]["resolution"],
                               "unit": [u["canonical"] for u in r["expected"]["units"]]} for r in fp["frozen_eval"]],
        "sensitivity_abstain_on_all_frozen_false_premises": {
            "abstained_records": len(fz_fp), "frozen_over_abstention": s["frozen_over_abstention"],
            "eligible_on_exact_gates": s["eligible_on_exact_gates"], "gates_failed": s["gates_failed"]},
        "agent_reading": "All 16 held-out false-premise / wrong-explanation references (8 frozen, 8 boundary) and all 70 "
                         "training ones (1 train, 69 increment) carry a unit; none states the premise as true. "
                         "Over-generalizations noted in agent-review.json (colour nouns, lequel after any "
                         "preposition, pas de after any negation).",
        "finding": "Unwarranted abstention on false premises is not gated: a system that is perfect except that it "
                   "abstains on every frozen false-premise record stays eligible (over-abstention "
                   f"{s['frozen_over_abstention']} <= 0.10). Report over-abstention by case type before trusting a winner.",
    }


# ---------------------------------------------------------------- 7. bilingual pairs and independence
def cp07():
    held = {"frozen_eval": D["eval"], "challenge": D["chl"], "boundary": D["boundary"]}
    flagged, units, keys = {}, {}, {}
    for k, rs in held.items():
        seen = {}
        for r in rs:
            for u in r["expected"]["units"]:
                seen[(u["canonical"], u["statement"], u["statement_zh"])] = u
        units[k] = len(seen)
        keys[k] = set(seen)
        flagged[k] = [{"canonical": u["canonical"], "findings": f} for u in seen.values() for f in [audit.bilingual_findings(u)] if f]
    units["union"] = len(set().union(*keys.values()))
    units["challenge_units_identical_to_frozen_units"] = len(keys["challenge"] & keys["frozen_eval"])
    ev = D["eval"]
    unit_recs = [r for r in ev if r["expected"]["units"]]
    pts = Counter(p for r in unit_recs for p in r["meta"]["points"])
    langs = defaultdict(set)
    for r in unit_recs:
        for p in r["meta"]["points"]:
            langs[p].add(audit.learner_language(r))
    # connected components of records linked by a shared objective point
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for r in unit_recs:
        ps = r["meta"]["points"]
        for p in ps[1:]:
            parent[find(p)] = find(ps[0])
        find(ps[0])
    comps = len({find(p) for p in pts})
    Q = re.compile(r"«\s*([^»]+?)\s*»")
    span = defaultdict(set)
    for r in ev:
        for s in Q.findall(r["input"]["original_input"] + " " + r["input"]["original_context"]):
            if len(norm(s)) >= 12:
                span[norm(s)].add(r["id"])
    reused = {s: sorted(i) for s, i in span.items() if len(i) > 1}
    R["cp07_bilingual"] = {
        "status": status(not any(flagged.values()), finding=True),
        "distinct_reference_units": units, "heuristic_bilingual_findings": flagged,
        "agent_reading": "Read every distinct held-out unit (EN statement against statement_zh): no meaning drift found. "
                         "statement_zh is a translation of statement, so an EN/ZH pair is one claim: a wrong rule is "
                         "wrong in both languages and their agreement confirms nothing.",
        "frozen_eval_independence": {
            "records": len(ev), "unit_records": len(unit_recs), "distinct_objective_points": len(pts),
            "objective_clusters_linked_by_shared_points": comps, "records_per_point_max": max(pts.values()),
            "points_asked_in_more_than_one_learner_language": sum(1 for v in langs.values() if len(v) > 1),
            "quoted_french_sentences_reused_across_records": len(reused), "reuse_examples": dict(list(reused.items())[:5])},
        "finding": "decision.py counts human-judged EXAMPLES (>= 100), but the frozen evaluation's 180 unit records "
                   f"cover only {len(pts)} objectives; the same corrected sentence recurs in single and two-error records "
                   "and many objectives are asked in French, Chinese and English. Translations and reused sentences "
                   "are not independent evidence: report human F1 by objective (or with a cluster bootstrap) and "
                   "never count the frozen and rb outputs of one learner text as two examples.",
    }


# ---------------------------------------------------------------- 8. duplicates and leakage
def cp08():
    chk = subprocess.run([sys.executable, "-B", "-m", "flh_extraction", "check",
                          "--train", str(OUT / "train" / "candidates.jsonl"), str(OUT / "inc" / "increment_candidates.jsonl"),
                          "--eval", str(OUT / "eval" / "eval_candidates.jsonl"), "--boundary", str(OUT / "boundary" / "boundary_cases_v1.jsonl"),
                          "--out", str(WORK / "check.json")], cwd=TOOLS, capture_output=True, text=True)
    check = jd(WORK / "check.json") if chk.returncode == 0 else {"error": chk.stderr[-400:]}
    no_out = subprocess.run([sys.executable, "-B", "-m", "flh_extraction", "check", "--train", str(OUT / "train" / "candidates.jsonl"),
                             "--eval", str(OUT / "eval" / "eval_candidates.jsonl")], cwd=TOOLS, capture_output=True, text=True)
    cc_regen = jd(OUT / "evidence" / "challenge-check.json")
    cc_committed = jd(REPO / "docs" / "validation" / "EXTRACTOR-COMPARISON-V1" / "challenge-check.json")
    trainish = [r for r in D["train"] + D["inc"] if r["meta"]["split_group"] in ("train", "dev")]
    held = {"frozen_eval": D["eval"], "rb": D["rb"], "swap": D["swap"], "challenge": D["chl"], "boundary": D["boundary"]}
    tid = {r["id"] for r in trainish}
    tin = {norm(r["input"]["original_input"] + " " + r["input"]["original_context"]) for r in trainish}
    Q = re.compile(r"«\s*([^»]+?)\s*»")

    def spans(r):
        return {norm(s) for s in Q.findall(r["input"]["original_input"] + " " + r["input"]["original_context"]) if len(norm(s)) >= 12}
    tsp = set().union(*(spans(r) for r in trainish))
    sft_rows = D["sft_train"] + D["sft_dev"]
    sft_ids = {r["id"] for r in sft_rows}
    sft_user = "\n".join(r["messages"][1]["content"] for r in sft_rows)
    sft_asst = {r["messages"][2]["content"] for r in sft_rows}
    out = {}
    for k, rs in held.items():
        base_ids = {r["meta"].get("probe", {}).get("derived_from", r["id"]) for r in rs}
        out[k] = {"records": len(rs), "ids_in_training": len(base_ids & tid), "ids_in_sft_files": len(base_ids & sft_ids),
                  "exact_learner_text_in_training": sum(norm(r["input"]["original_input"] + " " + r["input"]["original_context"]) in tin for r in rs),
                  "quoted_french_sentences_shared_with_training": sorted(set().union(*(spans(r) for r in rs)) & tsp),
                  "learner_input_inside_an_sft_prompt": sum(r["input"]["original_input"] in sft_user for r in rs if len(r["input"]["original_input"]) >= 20),
                  "reference_target_equals_an_sft_answer": sum(sft.target_text(r["expected"]) in sft_asst for r in rs if r["expected"]["units"])}
    clean = all(v["ids_in_training"] == 0 and v["ids_in_sft_files"] == 0 and v["exact_learner_text_in_training"] == 0
                and v["learner_input_inside_an_sft_prompt"] == 0 and v["reference_target_equals_an_sft_answer"] == 0 for v in out.values())
    boundary_span = out["boundary"]["quoted_french_sentences_shared_with_training"]
    ok = check.get("pass") is True and cc_regen.get("pass") is True and cc_regen == cc_committed and clean
    R["cp08_leakage"] = {
        "status": status(ok), "dataset_check": {k: check.get(k) for k in ("pass", "counts", "near_pairs_eval_train", "points_in_train_and_eval",
                                                                           "canonical_overlap_train_eval", "headword_overlap_train_eval",
                                                                           "exact_duplicate_groups", "families_in_two_splits")},
        "challenge_check": {"pass": cc_regen.get("pass"), "equals_committed": cc_regen == cc_committed,
                            "against": {k: {x: v[x] for x in ("exact_duplicates", "near_pairs_ge_0.5", "near_pairs_ge_0.8")} if isinstance(v, dict) else v
                                        for k, v in cc_regen["against"].items()},
                            "objectives": {k: cc_regen["objectives"][k] for k in ("points_in_training", "canonicals_in_training", "headwords_in_training")}},
        "independent_held_out_vs_training": out,
        "notes": [f"boundary shares the generic quoted phrase {boundary_span} with training; the boundary set is not part "
                  "of the comparison slice" if boundary_span else "no quoted sentence shared",
                  "cross-language duplicates: the lexical near-duplicate check cannot see a translation; the point, "
                  "canonical and headword checks (0 overlap) and the shared-French-sentence check cover it, because a "
                  "translated question keeps its French forms and objective"],
        "minor_defect": {"command": "python3 -m flh_extraction check ... (without --out)", "exit": no_out.returncode,
                         "error": (no_out.stderr.strip().splitlines() or [""])[-1][:160],
                         "impact": "usability only: argparse accepts the call, then dump(None) raises after the checks ran"},
    }


# ---------------------------------------------------------------- 9. regeneration
def _incomplete_run_change(old, new):
    """docs/validation/EXTRACTOR-COMPARISON-V1 keeps the 2026-11-12 decision fixture. FLH-154 item 39 makes an
    incomplete run (the fixture has 6 missing and 6 duplicated predictions) PENDING with its own reason instead
    of reading the absent rows as weak abstention. Accept exactly that change; the verdict must stay PENDING."""
    if old.lstrip().startswith("{"):
        a, b = json.loads(old), json.loads(new)
        u = b["systems"]["qwen3.5-4b-untuned"]
        ok = (a["verdict"] == b["verdict"] == "PENDING" and u.get("incomplete_run") == {"duplicate_prediction": 6, "missing_prediction": 6}
              and u["eligible"] is None and any(r.startswith("incomplete run: qwen3.5-4b-untuned") for r in b["reasons"])
              and u["criteria"] == a["systems"]["qwen3.5-4b-untuned"]["criteria"])
    else:
        ok = "INCOMPLETE RUN" in new and "# Extractor decision: **PENDING**" in new and "# Extractor decision: **PENDING**" in old
    return "changed_as_intended_by_FLH-154_item_39 (incomplete run is PENDING)" if ok else "DIFFERS"


INTENDED = {"docs/validation/EXTRACTOR-COMPARISON-V1/decision-fixture.json": _incomplete_run_change,
            "docs/validation/EXTRACTOR-COMPARISON-V1/decision-fixture.md": _incomplete_run_change}


def cp09():
    pairs = [(READY / "comparison-matrix.json", OUT / "slice" / "comparison-matrix.json"),
             (READY / "comparison-matrix.md", OUT / "slice" / "comparison-matrix.md"),
             (READY / "experiment-manifest.json", OUT / "experiment-manifest.json"),
             (READY / "input-manifest.json", OUT / "readiness" / "input-manifest.json"),
             (READY / "readiness-checks.json", OUT / "readiness" / "readiness-checks.json")]
    pairs += [(READY / "rendered" / f"{j}.json", OUT / "readiness" / "rendered" / f"{j}.json")
              for j in ("sft-smoke", "sft-experiment", "predict-base-a", "predict-base-b", "predict-eval-a", "predict-eval-b")]
    V = REPO / "docs" / "validation" / "EXTRACTOR-COMPARISON-V1"
    pairs += [(V / f, OUT / "evidence" / f) for f in ("challenge-check.json", "decision-fixture.json", "decision-fixture.md",
                                                    "parsing-fixture-compare.json", "parsing-fixture-compare.md", "parsing-fixture-expect.json")]
    pairs += [(V / "shortcut-repro.json", OUT / "evidence" / "shortcut" / "shortcut-repro.json"),
              (V / "shortcut-repro.md", OUT / "evidence" / "shortcut" / "shortcut-repro.md"),
              (V / "paired-demo.json", OUT / "evidence" / "paired" / "paired-demo.json"),
              (V / "paired-demo.md", OUT / "evidence" / "paired" / "paired-demo.md")]
    T = TOOLS / "review"
    pairs += [(T / "review-packet-v2.jsonl", OUT / "evidence" / "review-packet-v2.jsonl"), (T / "REVIEW_PACKET_V2.md", OUT / "evidence" / "review-packet-v2.md"),
              (T / "review-packet-v3.jsonl", OUT / "evidence" / "review-packet-v3.jsonl"), (T / "REVIEW_PACKET_V3.md", OUT / "evidence" / "review-packet-v3.md")]
    if (OUT / "evidence" / "review-sample-v1.jsonl").is_file():
        pairs += [(T / "review-sample-v1.jsonl", OUT / "evidence" / "review-sample-v1.jsonl"), (T / "REVIEW_SAMPLE_V1.md", OUT / "evidence" / "review-sample-v1.md"),
                  (T / "review-sample-v1-selection.json", OUT / "evidence" / "review-sample-v1-selection.json")]
    rows = []
    for a, b in pairs:
        x, y = Path(a).read_bytes(), Path(b).read_bytes()
        res = "identical" if x == y else ("identical_after_job_name_timestamp" if TS.sub("T", x.decode()) == TS.sub("T", y.decode()) else "DIFFERS")
        if res == "DIFFERS" and rel(a) in INTENDED:
            res = INTENDED[rel(a)](x.decode(), y.decode())
        rows.append({"committed": rel(a), "sha256_committed": sha(a), "sha256_regenerated": sha(b), "result": res})
    runs = None
    if ARGS.pipeline2:
        O2 = Path(ARGS.pipeline2).resolve()
        diff, same, norm_same = [], 0, 0
        for p in sorted(x for x in OUT.rglob("*") if x.is_file() and x.name != "last.log"
                        and not {"bin"} & set(x.relative_to(OUT).parts) and not any(q.endswith(".work") for q in x.relative_to(OUT).parts)):
            q = O2 / p.relative_to(OUT)
            if not q.is_file():
                diff.append(str(p.relative_to(OUT)) + " (missing in run 2)")
            elif p.read_bytes() == q.read_bytes():
                same += 1
            elif TS.sub("T", p.read_bytes().decode("utf-8", "replace")) == TS.sub("T", q.read_bytes().decode("utf-8", "replace")):
                norm_same += 1
            else:
                diff.append(str(p.relative_to(OUT)))
        runs = {"files_identical": same, "identical_after_job_name_timestamp": norm_same, "differ": diff}
    ok = all(r["result"] != "DIFFERS" for r in rows) and (runs is None or not runs["differ"])
    changed = [r["committed"] for r in rows if r["result"].startswith("changed_as_intended")]
    R["cp09_regeneration"] = {"status": status(ok), "committed_vs_regenerated": rows, "run1_vs_run2": runs,
                              "intended_changes": changed,
                              "not_compared": {"docs/validation/EXTRACTOR-COMPARISON-V1/asset-check.json":
                                               "depends on which local directories are searched (see cp16), not on regeneration"}}


# ---------------------------------------------------------------- 10. reference isolation
def cp10():
    shards = {"a": jl(OUT / "readiness" / "prompts" / "a" / "eval-prompts.jsonl"), "b": jl(OUT / "readiness" / "prompts" / "b" / "eval-prompts.jsonl")}
    prompts = {p["id"]: p for p in D["prompts"]}
    leaks = defaultdict(list)
    for p in D["prompts"] + shards["a"] + shards["b"]:
        if set(p) != {"id", "messages"} or [m["role"] for m in p["messages"]] != ["system", "user"]:
            leaks["not_inputs_only"].append(p["id"])
    ref_by = {r["id"]: r for r in REFS}
    for rid, p in prompts.items():
        r = ref_by[rid]
        text = p["messages"][0]["content"] + "\n" + p["messages"][1]["content"]
        own = norm(json.dumps(r["input"], ensure_ascii=False))
        if r["expected"]["units"] and sft.target_text(r["expected"]) in text:
            leaks["target_json_in_prompt"].append(rid)
        for u in r["expected"]["units"]:
            for f in ("statement", "statement_zh"):
                if len(u[f]) >= 25 and u[f] in text and norm(u[f]) not in own:
                    leaks[f"reference_{f}_in_prompt_not_from_input"].append(rid)
            if u["example"] and len(u["example"]) >= 15 and u["example"] in text and norm(u["example"]) not in own:
                leaks["reference_example_in_prompt_not_from_input"].append(rid)
        if re.search(r'"(expected|rationale|label_status|review_status|units)"\s*:', p["messages"][1]["content"]):
            leaks["reference_field_name_in_user_payload"].append(rid)
        meta_markers = (r["meta"].get("rationale") or "")
        if len(meta_markers) >= 25 and meta_markers in text:
            leaks["rationale_in_prompt"].append(rid)
    sysmsg = {p["messages"][0]["content"] for p in D["prompts"]}
    im = jd(READY / "input-manifest.json")
    rendered = {j: jd(READY / "rendered" / f"{j}.json") for j in ("sft-smoke", "sft-experiment", "predict-base-a", "predict-base-b", "predict-eval-a", "predict-eval-b")}
    chans = {j: sorted(c["ChannelName"] for c in v["InputDataConfig"]) for j, v in rendered.items()}
    uris = [c["DataSource"]["S3DataSource"]["S3Uri"] for v in rendered.values() for c in v["InputDataConfig"]]
    bad_uri = [u for u in uris if re.search(r"eval_candidates|comparison-slice|reference|expected|challenge_candidates|probe-", u)]
    R["cp10_isolation"] = {
        "status": status(not leaks and not bad_uri and len(sysmsg) == 1),
        "prompts_checked": len(D["prompts"]) + len(shards["a"]) + len(shards["b"]),
        "leaks": {k: v for k, v in leaks.items()}, "distinct_system_messages": len(sysmsg),
        "uploaded_files": sorted(im["files"]), "never_uploaded": im["never_uploaded"],
        "rendered_channels": chans, "suspicious_channel_uris": bad_uri,
        "method": "every reference's target JSON, statements (>= 25 chars) and examples not taken from the input were "
                  "searched for in every prompt; reference field names in the user payload; the uploaded file list "
                  "and the channel URIs of every rendered job",
    }


# ---------------------------------------------------------------- 11. comparator robustness
ADV = [
    ("empty string", "", "unparseable:empty"),
    ("whitespace around valid JSON", '\n  {"units": []}  \n', "valid_empty|valid_units"),
    ("leading prose", 'Sure! {"units": []}', "unparseable:leading_text"),
    ("trailing prose", '{"units": []} Hope this helps.', "unparseable:trailing_text"),
    ("two JSON objects", '{"units": []}{"units": []}', "unparseable:trailing_text"),
    ("markdown fence", '```json\n{"units": []}\n```', "unparseable:code_fence"),
    ("UTF-8 BOM", '﻿{"units": []}', "unparseable:*"),
    ("JSON array", "[]", "unparseable:*"),
    ("JSON string holding JSON", json.dumps('{"units": []}'), "unparseable:*"),
    ("NaN confidence", '{"units": [{"kind": "grammar", "canonical": "x", "statement": "x", "statement_zh": "x", "example": null, "confidence": NaN}]}', "unparseable:*"),
    ("confidence as a string", '{"units": [{"kind": "grammar", "canonical": "x", "statement": "x", "statement_zh": "说明", "example": null, "confidence": "0.9"}]}', "unparseable:*|invalid_output"),
    ("unknown kind", '{"units": [{"kind": "idiom", "canonical": "x", "statement": "x", "statement_zh": "说明", "example": null, "confidence": 0.9}]}', "invalid_output"),
    ("top-level extra key", '{"units": [], "note": "nothing to extract"}', "valid_extra_keys"),
    ("unit extra key", None, "valid_extra_keys"),
    ("unit missing example key", None, "valid_extra_keys"),
    ("unit missing statement_zh", None, "invalid_output"),
    ("literal null", "null", "NOT valid_empty"),
    ("empty object", "{}", "NOT valid_empty"),
    ("units null", '{"units": null}', "NOT valid_empty"),
    ("truncated JSON", '{"units": [{"kind": "grammar", "canon', "unparseable:*"),
]


def cp11():
    unit_ids = [r["id"] for r in REFS if r["expected"]["units"] and matrix.part_of(r) == "frozen"]
    zero_ids = [r["id"] for r in REFS if not r["expected"]["units"] and matrix.part_of(r) == "frozen"]
    rows = controls.outputs(REFS, "oracle")
    by = {x["id"]: x for x in rows}
    plan = {}
    for k, (name, text, want) in enumerate(ADV):
        rid = (unit_ids if text is None else zero_ids + unit_ids)[k]
        ref = next(r for r in REFS if r["id"] == rid)
        if text is None:
            u = dict(ref["expected"]["units"][0])
            if name == "unit extra key":
                u["evidence"] = "quoted from the learner"
            elif name == "unit missing example key":
                u.pop("example")
            else:
                u.pop("statement_zh")
            text = json.dumps({"units": [u] + ref["expected"]["units"][1:]}, ensure_ascii=False)
        by[rid]["output_text"] = text
        plan[rid] = (name, want)
    acc = comparison.account_with_validator(IDS, INPUTS, rows, VALIDATE)
    st = {r["id"]: r["status"] for r in acc["rows"]}
    cases = []
    for rid, (name, want) in plan.items():
        got = st[rid]
        if want.startswith("NOT "):
            ok = got != want[4:]
        else:
            ok = any(got == w or (w.endswith("*") and got.startswith(w[:-1])) for w in want.split("|"))
        cases.append({"case": name, "id": rid, "status": got, "expected": want, "as_expected": ok})
    total_ok = sum(acc["status_counts"].values()) == len(IDS)
    # Whole-file failures: rows the comparator cannot account for one by one.
    crashes = []
    for name, mutate in (("output_text is a JSON object, not a string", lambda r: r.update(output_text={"units": []})),
                         ("output_text is a number", lambda r: r.update(output_text=7))):
        rs = copy.deepcopy(controls.outputs(REFS, "oracle"))
        mutate(rs[0])
        try:
            comparison.account_with_validator(IDS, INPUTS, rs, VALIDATE)
            crashes.append({"case": name, "result": "accounted"})
        except subprocess.CalledProcessError as e:
            crashes.append({"case": name, "result": f"comparison aborted: extraction-render validate exited {e.returncode}"})
    rs = controls.outputs(REFS, "oracle")
    rs[0] = {"id": rs[0]["id"], "error": "generation failed"}
    try:
        matrix.compare(MATRIX, OUT / "slice" / "comparison-slice.jsonl", {"qwen3.5-4b-untuned": rs}, VALIDATE)
        crashes.append({"case": "a raw file with one row lacking output_text", "result": "accounted"})
    except ValueError as e:
        crashes.append({"case": "a raw file with one row lacking output_text", "result": f"comparison aborted: {e}"})
    p = WORK / "truncated.jsonl"
    p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in controls.outputs(REFS, "oracle")[:5]) + '{"id": "ext-evl-0006", "output_te',
                 encoding="utf-8")
    from flh_extraction import records
    try:
        records.load_jsonl(p)
        crashes.append({"case": "prediction file whose last line was cut (job stopped mid-write)", "result": "loaded"})
    except json.JSONDecodeError as e:
        crashes.append({"case": "prediction file whose last line was cut (job stopped mid-write)", "result": f"compare aborts while loading: {e.msg}"})
    lenient = [c for c in cases if c["expected"].startswith("NOT ") and not c["as_expected"]]
    R["cp11_comparator"] = {
        "status": status(all(c["as_expected"] for c in cases) and total_ok, finding=bool(lenient) or any("aborted" in c["result"] for c in crashes)),
        "rows_accounted": sum(acc["status_counts"].values()), "references": len(IDS), "cases": cases, "whole_file_failures": crashes,
        "findings": [
            "Degenerate outputs `null`, `{}` and `{\"units\": null}` are accepted by the production parser as zero units and "
            "counted valid_empty, i.e. as a correct abstention on a zero reference; the strict knowledge_extraction_v2 schema "
            "forbids them, and strict_schema_findings already reports them (top_level_not_object / units_not_list) but "
            "account() only demotes extra/missing-key findings." if any(c["case"] in ("literal null", "empty object", "units null")
                                                                       and c["status"] == "valid_empty" for c in cases) else None,
            "A non-string output_text aborts the whole comparison (the Go validator refuses the line) instead of being one "
            "invalid row; a raw row without output_text and a cut last line also abort it. These fail loudly (no silent "
            "miscount) and predict.py writes neither, but a partial file from a stopped job needs its last line removed by hand.",
        ],
    }


# ---------------------------------------------------------------- 12. denominators
def cp12():
    fx = jl(OUT / "fixture-untuned.jsonl")
    rep = run_system(fx)
    m = rep["metrics"]
    parts = {p: [r for r in REFS if matrix.part_of(r) == p] for p in matrix.PARTS}
    zero = {p: sum(1 for r in parts[p] if not r["expected"]["units"]) for p in ("frozen", "rb")}
    unit = {p: sum(1 for r in parts[p] if r["expected"]["units"]) for p in ("frozen", "rb")}
    conf = {p: m[p]["confusion"]["ref_by_pred"] for p in ("frozen", "rb")}
    den_ok = all(sum(conf[p]["ref_zero"].values()) == zero[p] and sum(conf[p]["ref_units"].values()) == unit[p] for p in conf)
    ab_ok = all(m[p]["headline"]["abstention_rate"] == round(conf[p]["ref_zero"]["empty"] / zero[p], 3) for p in conf)
    oa_ok = all(m[p]["over_abstention_rate"] == round(conf[p]["ref_units"]["empty"] / unit[p], 3) for p in conf)
    groups = m["challenge_test"]["headline"]
    # F1 denominator: truncate the frozen references with the most units (validity stays >= 0.98).
    fz = sorted((r for r in parts["frozen"] if r["expected"]["units"]), key=lambda r: (-len(r["expected"]["units"]), r["id"]))
    cut = {r["id"] for r in fz[:9]}
    rows = controls.outputs(REFS, "oracle")
    for x in rows:
        if x["id"] in cut:
            x["output_text"] = x["output_text"][: len(x["output_text"]) // 2]
            x["stopped"] = "max_new_tokens"
    t = run_system(rows)
    o = SYS.get("oracle") or run_system(controls.outputs(REFS, "oracle"))
    s_t, s_o = summarize(t), summarize(o)
    trunc_units = sum(len(r["expected"]["units"]) for r in fz[:9])
    all_units = sum(len(r["expected"]["units"]) for r in parts["frozen"])
    R["cp12_denominators"] = {
        "status": status(den_ok and ab_ok and oa_ok, finding=s_t["frozen_heuristic_unit_f1"] == s_o["frozen_heuristic_unit_f1"]),
        "parsing_fixture": {"status_counts": rep["rows"]["status_counts"], "scorable": rep["rows"]["scorable"],
                            "references": rep["rows"]["references"]},
        "confusion_rows_sum_to_slice_part": den_ok, "abstention_denominator_is_every_zero_reference": ab_ok,
        "over_abstention_denominator_is_every_unit_reference": oa_ok,
        "frozen": {"zero_refs": zero["frozen"], "unit_refs": unit["frozen"], "confusion": conf["frozen"]},
        "rb": {"zero_refs": zero["rb"], "unit_refs": unit["rb"], "confusion": conf["rb"]},
        "challenge_groups_scored": m["challenge_test"]["headline"], "paired_invalid_never_consistent": "paired.report: invalid or missing -> not consistent, not correct",
        "f1_denominator_probe": {
            "system": "oracle except 9 frozen references with the most units truncated at max_new_tokens",
            "truncated_reference_units": trunc_units, "frozen_reference_units": all_units,
            "strict_validity": s_t["strict_validity"], "eligible_on_exact_gates": s_t["eligible_on_exact_gates"],
            "frozen_heuristic_unit_f1": s_t["frozen_heuristic_unit_f1"], "oracle_frozen_heuristic_unit_f1": s_o["frozen_heuristic_unit_f1"]},
        "finding": "Structural validity, abstention, over-abstention and the paired metrics count every reference row "
                   "(an invalid, truncated, extra-key or missing row counts against the system). Unit F1 does not: "
                   "quality.report computes precision and recall over valid outputs only, so the reference units of "
                   "truncated or malformed rows leave the recall denominator. The same holds for human F1 built with "
                   "`quality --judgments`. The 0.98 validity gate bounds the effect (at most 9 of 472 rows), but those "
                   "rows can be the hardest ones, and the 0.05 win margin is decided on that F1.",
    }


# ---------------------------------------------------------------- 13. shards
def cp13():
    a = jl(OUT / "readiness" / "prompts" / "a" / "eval-prompts.jsonl")
    b = jl(OUT / "readiness" / "prompts" / "b" / "eval-prompts.jsonl")
    ids = [p["id"] for p in D["prompts"]]
    ia, ib = [p["id"] for p in a], [p["id"] for p in b]
    order_a = ia == [i for i in ids if not i.endswith("#rb")]
    order_b = ib == [i for i in ids if i.endswith("#rb")]
    content = {p["id"]: p for p in D["prompts"]}
    same_content = all(content[p["id"]] == p for p in a + b)
    groups_whole = Counter(r["meta"]["challenge"]["group_id"] for r in REFS if "challenge" in r["meta"])
    in_a = {i for i in ia}
    split_groups = [g for g in groups_whole if len({(r["id"] in in_a) for r in REFS if r["meta"].get("challenge", {}).get("group_id") == g}) > 1]
    stable = None
    if ARGS.pipeline2:
        O2 = Path(ARGS.pipeline2).resolve()
        stable = all((OUT / "readiness" / "prompts" / s / "eval-prompts.jsonl").read_bytes() == (O2 / "readiness" / "prompts" / s / "eval-prompts.jsonl").read_bytes()
                     for s in ("a", "b"))
    jobs = {j: jd(READY / "rendered" / f"{j}.json") for j in ("predict-base-a", "predict-base-b", "predict-eval-a", "predict-eval-b")}
    shard_hash = {"a": sha(OUT / "readiness" / "prompts" / "a" / "eval-prompts.jsonl"), "b": sha(OUT / "readiness" / "prompts" / "b" / "eval-prompts.jsonl")}
    bind = {j: v["HyperParameters"].get("prompts_sha256") == shard_hash[j[-1]] for j, v in jobs.items()}
    limit = {j: {k: v for k, v in jobs[j]["HyperParameters"].items() if "limit" in k} for j in jobs}
    # compare is order-free: shuffled and a-then-b concatenation give the same report
    o = controls.outputs(REFS, "oracle")
    shuffled = o[:]
    random.Random(154).shuffle(shuffled)
    ab = [x for x in o if not x["id"].endswith("#rb")] + [x for x in o if x["id"].endswith("#rb")]
    r1 = matrix.compare(MATRIX, OUT / "slice" / "comparison-slice.jsonl", {"qwen3.5-4b-untuned": o}, VALIDATE)
    r2 = matrix.compare(MATRIX, OUT / "slice" / "comparison-slice.jsonl", {"qwen3.5-4b-untuned": shuffled}, VALIDATE)
    r3 = matrix.compare(MATRIX, OUT / "slice" / "comparison-slice.jsonl", {"qwen3.5-4b-untuned": ab}, VALIDATE)
    order_free = r1 == r2 == r3
    ok = (len(ia) + len(ib) == len(ids) and not set(ia) & set(ib) and set(ia) | set(ib) == set(ids) and len(set(ia)) == len(ia)
          and len(set(ib)) == len(ib) and order_a and order_b and same_content and not split_groups and all(bind.values())
          and stable is not False and order_free and not any(limit.values()))
    R["cp13_shards"] = {"status": status(ok), "shard_a": {"records": len(ia), "sha256": shard_hash["a"], "order_equals_slice_order": order_a},
                        "shard_b": {"records": len(ib), "sha256": shard_hash["b"], "order_equals_slice_order": order_b},
                        "overlap": len(set(ia) & set(ib)), "union_equals_slice": set(ia) | set(ib) == set(ids),
                        "prompt_content_unchanged_by_sharding": same_content, "challenge_groups_split_across_shards": split_groups,
                        "identical_in_a_second_regeneration": stable, "jobs_bound_to_their_shard_hash": bind,
                        "limit_parameters_in_prediction_jobs": limit, "compare_independent_of_row_order": order_free}


# ---------------------------------------------------------------- 14/15. decision report
def fake_human(**f1):
    return {s: {"unit_f1": v, "judged_examples": 120, "unsupported_or_false_claim_rate": 0.0} for s, v in f1.items()}


def fake_review():
    return [{"id": f"r{i}", "verdict": "accept"} for i in range(44)]


def comp(systems):
    return {"systems": {s: (systems[s] if s in systems else {"status": "NOT_PERFORMED", "rows": None, "metrics": None}) for s in decision.SYSTEMS},
            "refused": []}


TUNED_OK = {"losses": [{"dev_loss": 1.0}, {"dev_loss": 0.9}, {"dev_loss": 0.8}],
            "run_manifest": None}


def tuned_extras():
    im = jd(READY / "input-manifest.json")
    rm = {"train_sha256": im["files"]["sft-train.jsonl"]["sha256"], "dev_sha256": im["files"]["sft-dev.jsonl"]["sha256"],
          "suitable_for_production": False, "smoke": False}
    return TUNED_OK["losses"], rm, im


def cp14():
    good = SYS["oracle"]
    losses, rm, im = tuned_extras()
    rows = []
    from itertools import combinations
    for k in range(0, 4):
        for present in combinations(decision.SYSTEMS, k):
            c = comp({s: good for s in present})
            rep = decision.decide(c, fake_human(**{s: 0.9 - 0.1 * i for i, s in enumerate(decision.SYSTEMS)}), fake_review(), losses, rm, im)
            rows.append({"measured": list(present), "verdict": rep["verdict"], "winner": rep["winner"]})
    allm = comp({s: good for s in decision.SYSTEMS})
    extra = {
        "all measured, no human F1": decision.decide(allm, None, fake_review(), losses, rm, im)["verdict"],
        "all measured, human F1 from 99 examples": decision.decide(allm, {s: {"unit_f1": 0.9, "judged_examples": 99} for s in decision.SYSTEMS},
                                                                   fake_review(), losses, rm, im)["verdict"],
        "all measured, review verdicts missing": decision.decide(allm, fake_human(**{s: 0.9 - 0.1 * i for i, s in enumerate(decision.SYSTEMS)}),
                                                                 [{"id": "x", "verdict": None}] * 44, losses, rm, im)["verdict"],
        "all measured, tuned losses missing": decision.decide(allm, fake_human(**{"current_extractor": 0.5, "qwen3.5-4b-untuned": 0.5,
                                                                                  "qwen3.5-4b-tuned": 0.9}), fake_review(), None, rm, im)["verdict"],
        "comparison refused": decision.decide({"systems": {}, "refused": ["slice hash differs from the matrix"]})["verdict"],
    }
    pending_when_missing = all(r["verdict"] == "PENDING" for r in rows if len(r["measured"]) < 3)
    full = [r for r in rows if len(r["measured"]) == 3][0]
    ok = (pending_when_missing and full["verdict"] == "WINNER_FOR_OWNER_DECISION" and extra["all measured, no human F1"] == "PENDING"
          and extra["all measured, human F1 from 99 examples"] == "PENDING" and extra["all measured, review verdicts missing"] == "PENDING"
          and extra["all measured, tuned losses missing"] == "PENDING" and extra["comparison refused"] == "REFUSED")
    R["cp14_pending"] = {"status": status(ok), "subsets_of_measured_runs": rows, "other_missing_inputs": extra,
                         "note": "every synthetic system here is the oracle's metrics; only the presence of runs and inputs varies"}


def with_rb_false_extractions(k):
    """Oracle everywhere except k invented units on zero-unit rb references."""
    rows = controls.outputs(REFS, "oracle")
    zero_rb = [r["id"] for r in REFS if matrix.part_of(r) == "rb" and not r["expected"]["units"]][:k]
    for x in rows:
        if x["id"] in zero_rb:
            x["output_text"] = json.dumps({"units": [controls.FAKE]}, ensure_ascii=False)
    return run_system(rows)


def with_cue_flips(k):
    """Oracle everywhere except k challenge_test extract groups answered empty in their `conflicting` variant."""
    rows = controls.outputs(REFS, "oracle")
    gs = sorted({r["meta"]["challenge"]["group_id"] for r in REFS if "challenge" in r["meta"] and r["meta"]["challenge"]["intent"] == "extract"})[:k]
    tgt = {r["id"] for r in REFS if "challenge" in r["meta"] and r["meta"]["challenge"]["group_id"] in gs and r["meta"]["challenge"]["variant"] == "conflicting"}
    for x in rows:
        if x["id"] in tgt:
            x["output_text"] = '{"units": []}'
    return run_system(rows)


def cp15():
    losses, rm, im = tuned_extras()
    out = {}
    for label, rep, f1 in (("rb abstention 0.90 (2 of 20 invented)", with_rb_false_extractions(2), 0.95),
                           ("rb abstention 0.85 (3 of 20 invented)", with_rb_false_extractions(3), 0.99),
                           ("paired consistency 0.875 (3 cue flips of 24 groups)", with_cue_flips(3), 0.99),
                           ("paired consistency 0.917 (2 cue flips)", with_cue_flips(2), 0.99)):
        c = comp({"current_extractor": SYS["oracle"], "qwen3.5-4b-untuned": SYS["oracle"], "qwen3.5-4b-tuned": rep})
        h = fake_human(**{"current_extractor": 0.70, "qwen3.5-4b-untuned": 0.55, "qwen3.5-4b-tuned": f1})
        d = decision.decide(c, h, fake_review(), losses, rm, im)
        s = summarize(rep)
        out[label] = {"tuned": {k: s[k] for k in ("rb_abstention", "paired_consistency", "frozen_heuristic_unit_f1", "gates_failed")},
                      "tuned_human_f1": f1, "others_human_f1": [0.70, 0.55], "verdict": d["verdict"], "winner": d["winner"],
                      "tuned_eligible": d["systems"]["qwen3.5-4b-tuned"]["eligible"]}
    cat = summarize(SYS["category_only"])
    c = comp({"current_extractor": SYS["category_only"], "qwen3.5-4b-untuned": SYS["oracle"], "qwen3.5-4b-tuned": SYS["oracle"]})
    d = decision.decide(c, fake_human(**{"current_extractor": 0.99, "qwen3.5-4b-untuned": 0.50, "qwen3.5-4b-tuned": 0.50}), fake_review(), losses, rm, im)
    out["category-only with the best human F1 by far"] = {"frozen_heuristic_unit_f1": cat["frozen_heuristic_unit_f1"],
                                                          "gates_failed": cat["gates_failed"], "verdict": d["verdict"], "winner": d["winner"]}
    # rounding: gates compare rates rounded to 3 decimals; can rounding flip any gate at the slice's denominators?
    dens = {"frozen zero refs": 20, "rb zero refs": 20, "frozen unit refs": 180, "rb unit refs": 180, "challenge_test groups": 24, "abstain groups": 9}
    flips = []
    for name, dn in dens.items():
        for thr, ge in ((0.90, True), (0.80, True), (0.10, False)):
            for k in range(dn + 1):
                exact, rounded = k / dn, round(k / dn, 3)
                if (exact >= thr) != (rounded >= thr) if ge else (exact <= thr) != (rounded <= thr):
                    flips.append((name, thr, k))
    ok = (out["rb abstention 0.85 (3 of 20 invented)"]["winner"] != "qwen3.5-4b-tuned"
          and out["paired consistency 0.875 (3 cue flips of 24 groups)"]["winner"] != "qwen3.5-4b-tuned"
          and out["rb abstention 0.90 (2 of 20 invented)"]["winner"] == "qwen3.5-4b-tuned"
          and out["category-only with the best human F1 by far"]["winner"] != "current_extractor")
    edge = [(a / 1000, (a - 50) / 1000) for a in range(50, 1001) if a / 1000 - (a - 50) / 1000 < decision.WIN_MARGIN]
    two = comp({s: SYS["oracle"] for s in decision.SYSTEMS})
    d6 = decision.decide(two, fake_human(**{"current_extractor": 0.60, "qwen3.5-4b-untuned": 0.55, "qwen3.5-4b-tuned": 0.30}), fake_review(), losses, rm, im)
    d7 = decision.decide(two, fake_human(**{"current_extractor": 0.65, "qwen3.5-4b-untuned": 0.60, "qwen3.5-4b-tuned": 0.30}), fake_review(), losses, rm, im)
    R["cp15_weak_abstention"] = {"status": status(ok, finding=bool(edge)), "cases": out, "rounding_flips_at_current_denominators": flips,
                                 "win_margin_float_edge": {"exact_0.050_leads_counted_below_the_margin": f"{len(edge)} of 951 (F1 on a 0.001 grid)",
                                                           "0.60 vs 0.55": d6["verdict"], "0.65 vs 0.60": d7["verdict"],
                                                           "finding": "decision.py compares `best - second < 0.05` in binary floating point: "
                                                                      "a lead of exactly 0.05 wins or loses depending on the values. Decide "
                                                                      "on rounded values (e.g. round(best - second, 3) < 0.05) before any real run."},
                                 "note": "the gates compare rates rounded to 3 decimals; at the pinned slice's denominators "
                                         "no gate can flip (listed above if any could). A different slice size needs this re-checked."}


# ---------------------------------------------------------------- 16/17. assets and packaging
def cp16():
    out = WORK / "assets.json"
    cmd = [sys.executable, "-B", str(TOOLS / "scripts" / "check_model_assets.py"), "--sums", str(TOOLS / "configs" / "qwen3.5-4b-851bf6e8.sha256")]
    for d in ARGS.asset_dir:
        cmd += ["--dir", d]
    p = subprocess.run(cmd + ["--out", str(out)], cwd=TOOLS, capture_output=True, text=True)
    rep = jd(out) if out.is_file() else {"error": p.stderr[-300:]}
    files = rep.get("token_lengths", []) + rep.get("weights", [])
    R["cp16_assets"] = {"status": "BLOCKED" if p.returncode == 3 else status(p.returncode == 0),
                        "exit": p.returncode, "searched_dirs": len(ARGS.asset_dir),
                        "pinned_revision": rep.get("revision"),
                        "by_status": {s: sorted(f["file"] for f in files if f["status"] == s) for s in sorted({f["status"] for f in files})},
                        "never_substituted": "no tokenizer or weights from another revision or model were used"}


def cp17():
    pk = subprocess.run([sys.executable, "-B", "-m", "flh_extraction.packaging"], cwd=TOOLS, capture_output=True, text=True)
    try:
        host = json.loads(pk.stdout)
    except json.JSONDecodeError:
        host = {"stdout": pk.stdout[-600:], "stderr": pk.stderr[-300:]}
    img = jd(ARGS.image_packaging) if ARGS.image_packaging else "not given"
    R["cp17_packaging"] = {"status": "BLOCKED", "host_python_exit": pk.returncode, "host_python": host, "local_image": img,
                           "missing_prerequisites": [
                               "GPU image built from requirements-train.txt (the local image is CPU-only and stale: transformers "
                               "4.57.6 cannot load qwen3_5; tokenizers and huggingface-hub are behind)",
                               "tokenizer.json, vocab.json, merges.txt at revision 851bf6e8 (token lengths and masking unmeasured)",
                               "both weight shards (9,319,737,856 bytes) at revision 851bf6e8",
                               "the image digest, execution role, bucket and adapter key (placeholders in values.example.json)",
                               "host Python has no torch/transformers/peft/tokenizers (expected: the stack lives in the image)"]}


# ---------------------------------------------------------------- 18. rendered jobs
def cp18():
    import render_job
    bounds = render_job.BOUNDS
    jobs = {j: jd(READY / "rendered" / f"{j}.json") for j in ("sft-smoke", "sft-experiment", "predict-base-a", "predict-base-b", "predict-eval-a", "predict-eval-b")}
    run_of = {"sft-smoke": "smoke", "sft-experiment": "experiment"}
    rows, probs = {}, []
    name_re = re.compile(r"^flh-extractor-[a-z0-9]+(-[a-z0-9]+)*-\d{8}-\d{6}$")
    blob = json.dumps(jobs)
    for j, v in jobs.items():
        run = run_of.get(j, "predict")
        n = v["TrainingJobName"]
        mx = v["StoppingCondition"]["MaxRuntimeInSeconds"]
        rows[j] = {"name": n, "name_ok": bool(name_re.match(n)) and len(n) <= 63 and f"-{j}-" in n + "-",
                   "max_runtime_s": mx, "bound_s": bounds[run], "within_bound": mx <= bounds[run],
                   "instance": f"{v['ResourceConfig']['InstanceCount']} x {v['ResourceConfig']['InstanceType']}",
                   "network_isolation": v["EnableNetworkIsolation"], "image": v["AlgorithmSpecification"]["TrainingImage"],
                   "role": v["RoleArn"], "output": v["OutputDataConfig"]["S3OutputPath"]}
        if not rows[j]["name_ok"] or not rows[j]["within_bound"] or not v["EnableNetworkIsolation"]:
            probs.append(j)
    acct = sorted(set(re.findall(r"\b\d{12}\b", blob)))
    secrets = [k for k in re.findall(r'"([A-Za-z_]*(?:SECRET|TOKEN|PASSWORD|ACCESS_KEY|API_KEY)[A-Za-z_]*)"', blob)]
    keyish = re.findall(r"AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}", blob)
    env = {j: sorted(v.get("Environment", {})) for j, v in jobs.items()}
    names = [r["name"] for r in rows.values()]
    # The renderer refuses what it must refuse (no AWS call; placeholder values only).
    import io
    import contextlib
    ex = jd(READY / "values.example.json")
    ex.pop("$comment", None)
    refusals = {}
    for label, change in (("tag instead of digest", {"IMAGE_DIGEST": "latest"}), ("missing role", {"EXEC_ROLE_ARN": ""}),
                          ("missing bucket", {"BUCKET": ""})):
        vals = dict(ex, **change, TRAIN_SHA256="0" * 64, DEV_SHA256="0" * 64, PROMPTS_SHA256="0" * 64, CONFIG_JSON="{}")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                render_job.render(REPO / "deploy" / "aws" / "sagemaker-extractor" / "jobs" / "predict-base.json.tmpl", "predict", WORK / "r", vals, role="probe")
            refusals[label] = "rendered (NOT refused)"
        except SystemExit as e:
            refusals[label] = f"refused: {e}"
    R["cp18_render"] = {"status": status(not probs and len(set(names)) == len(names) and acct == ["000000000000"] and not secrets and not keyish
                                         and all(v.startswith("refused") for v in refusals.values())),
                        "jobs": rows, "unique_names": len(set(names)) == len(names), "account_ids_in_rendered_jobs": acct,
                        "secret_like_keys": secrets, "key_like_values": keyish, "environment_keys": env,
                        "renderer_refusals": refusals}


# ---------------------------------------------------------------- 19. cost assumptions (computed, not executed)
def cp19():
    rate = 1.408  # ml.g5.xlarge training, us-east-1, as recorded in TRAINING_RUNBOOK.md §10 (not re-verified offline)
    jobs = {j: jd(READY / "rendered" / f"{j}.json") for j in ("sft-smoke", "predict-base-a", "predict-base-b", "sft-experiment", "predict-eval-a", "predict-eval-b")}
    caps = {j: v["StoppingCondition"]["MaxRuntimeInSeconds"] for j, v in jobs.items()}
    cost = {j: round(s / 3600 * rate, 3) for j, s in caps.items()}
    prompts = D["prompts"]
    chars = [len(p["messages"][0]["content"]) + len(p["messages"][1]["content"]) for p in prompts]
    inp = D["inputs"]
    R["cp19_cost"] = {"status": "INFO", "rate_usd_per_hour_assumed": rate, "rate_source": "tools/extraction/TRAINING_RUNBOOK.md §10 (recorded earlier; not re-checked: no network)",
                      "max_runtime_s": caps, "worst_case_usd": cost, "worst_case_total_usd": round(sum(cost.values()), 2),
                      "storage": "cents (weights 9,319,737,856 bytes + datasets); not priced here",
                      "paid_provider_baseline": {"requests": len(inp), "retries": 0,
                                                 "request_text_chars_total": sum(chars), "request_text_chars_max": max(chars),
                                                 "pricing": "not estimated: the provider model is chosen at run time; the owner prices "
                                                            "472 requests of this size with that model's current rates"}}


def md(rep):
    L = ["# FLH-154 review checks (generated)", "", "| Check | Status |", "|---|---|"]
    for k, v in rep.items():
        if isinstance(v, dict) and "status" in v:
            L.append(f"| {k} | {v['status']} |")
    return "\n".join(L) + "\n"


def main():
    for f in (cp01, cp02, cp03, cp04, cp05, cp06, cp07, cp08, cp09, cp10, cp11, cp12, cp13, cp14, cp15, cp16, cp17, cp18, cp19):
        f()
    out = Path(ARGS.out)
    doc = {"schema": "flh154_review_checks_v1", "synthetic_only": True, "real_runs_performed": 0, **R}
    (out / "review-checks.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    (out / "review-checks.md").write_text(md(R), encoding="utf-8")
    print(json.dumps({k: v["status"] for k, v in R.items()}, indent=1))


if __name__ == "__main__":
    main()
