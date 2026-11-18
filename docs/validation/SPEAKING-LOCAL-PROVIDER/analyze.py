"""Speaking v2 analysis from stored per-clip outputs (standard library only).

  python3 -I -B docs/validation/SPEAKING-LOCAL-PROVIDER/analyze.py models     # item 10
  python3 -I -B docs/validation/SPEAKING-LOCAL-PROVIDER/analyze.py short      # item 11
  python3 -I -B docs/validation/SPEAKING-LOCAL-PROVIDER/analyze.py language   # item 12
  python3 -I -B docs/validation/SPEAKING-LOCAL-PROVIDER/analyze.py thresholds # item 12: P(fr) threshold sweep
  python3 -I -B docs/validation/SPEAKING-LOCAL-PROVIDER/analyze.py noise      # item 13
  python3 -I -B docs/validation/SPEAKING-LOCAL-PROVIDER/analyze.py audit [DATA_DIR ...]   # item 16 (data dirs: target style)
  python3 -I -B docs/validation/SPEAKING-LOCAL-PROVIDER/analyze.py verify     # recompute stored summaries and the acceptance verdict
  python3 -I -B docs/validation/SPEAKING-LOCAL-PROVIDER/analyze.py all        # writes analysis/*.json (audit only with DATA_DIR)

Inputs: the v1 evaluations (``../SPEAKING-MODEL-V1/evals``, ``../SPEAKING-MODEL-V1/service``),
the v2 re-runs (``reeval/``) and the robustness outputs (``robustness/<model>-<set>.json``,
from ``python -m flh_speaking robustness``). Every number is recomputed here from
references and model text with ``flh_fr_asr_norm_v1``; nothing is read from a
stored summary except where named (latency and memory from the v1 service bench).
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
V1 = os.path.join(ROOT, "docs", "validation", "SPEAKING-MODEL-V1")
sys.path.insert(0, os.path.join(ROOT, "tools", "speaking"))

from flh_speaking import compare, textnorm  # noqa: E402

MODELS = ("base", "small")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def scored(doc):
    for i in doc["items"]:
        i["score"] = {"raw": textnorm.score(i["ref"], i["raw"]["text"]), "served": textnorm.score(i["ref"], i["served"]["text"])}
    return doc


def wer(pairs):
    """Corpus WER over (reference, hypothesis) pairs."""
    s = [textnorm.score(r, h or "") for r, h in pairs]
    return round(textnorm.rate(s)["wer"], 4) if s else None


def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


# ---------------------------------------------------------------- item 10
def models():
    out = {"paired_small_minus_base": {}, "service": {}, "reeval_identical_to_v1": {}}
    for split in ("test", "ood", "accent"):
        a, b = scored(load(os.path.join(V1, "evals", f"base-{split}.json"))), scored(load(os.path.join(V1, "evals", f"small-{split}.json")))
        p = compare.paired(a, b, "served")
        out["paired_small_minus_base"][split] = {k: p[k] for k in ("items", "clusters", "wer_a", "wer_b", "delta", "delta_ci95", "utterances_better",
                                                                    "utterances_worse", "clusters_better", "clusters_worse", "cluster_sign_test_p")}
        out["paired_small_minus_base"][split]["rtf"] = {"base": a["summary"]["timing"]["real_time_factor"], "small": b["summary"]["timing"]["real_time_factor"]}
        out["paired_small_minus_base"][split]["peak_rss_mb_batch"] = {"base": a["summary"]["timing"]["peak_rss_mb"], "small": b["summary"]["timing"]["peak_rss_mb"]}
    for m in MODELS:
        bench = load(os.path.join(V1, "service", f"bench-whisper-{m}.json"))
        out["service"][m] = {"latency_median_s": {k: v["median_wall_s"] for k, v in bench["latency"].items()},
                             "rtf": {k: v["rtf"] for k, v in bench["latency"].items()},
                             "peak_mem_mib": bench["peak_mem_mib"], "idle_mem_mib": bench["idle_mem_mib"], "ready_after_s": bench["ready_after_s"]}
        path = os.path.join(HERE, "reeval", f"{m}-test.json")
        if os.path.exists(path):
            new, old = load(path), load(os.path.join(V1, "evals", f"{m}-test.json"))
            o = {i["id"]: i for i in old["items"]}
            same = sum(1 for i in new["items"] if i["id"] in o and i["served"]["text"] == o[i["id"]]["served"]["text"] and i["raw"]["text"] == o[i["id"]]["raw"]["text"])
            out["reeval_identical_to_v1"][m] = {"items": len(new["items"]), "identical_raw_and_served_text": same,
                                                "timing": new["summary"]["timing"]}
    return out


# ---------------------------------------------------------------- shared
def robust(model, set_):
    path = os.path.join(HERE, "robustness", f"{model}-{set_}.json")
    return load(path)["items"] if os.path.exists(path) else None


def status_counts(items, key="served"):
    c = Counter(i[key]["status"] for i in items)
    n = len(items)
    return {"n": n, "transcribed": c["transcribed"], "no_speech": c["no_speech"], "not_french": c["not_french"],
            "not_french_pct": pct(c["not_french"], n), "abstained_pct": pct(n - c["transcribed"], n)}


def example(i):
    r = i["raw"] or {}
    return {"id": i["id"], "seconds": i.get("length") or i["quality"]["seconds"], "p_fr": r.get("p_fr"), "top": r.get("top_language"),
            "p_top": r.get("p_top_language"), "model_text": r.get("text"), "reference": i.get("ref")}


DUR = ((0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 1e9))


def dur_bucket(s):
    for lo, hi in DUR:
        if lo <= s < hi:
            return f"{lo:g}-{hi:g}s" if hi < 1e9 else f">={lo:g}s"
    return "?"


# ---------------------------------------------------------------- item 11
def short():
    out = {}
    for m in MODELS:
        items = robust(m, "short")
        res = {}
        if items:
            groups = defaultdict(list)
            for i in items:
                groups[(i["group"], i["condition"])].append(i)
            res["by_group_and_length"] = {}
            for (g, cond), its in sorted(groups.items()):
                row = status_counts(its)
                row["median_seconds"] = sorted(i["quality"]["seconds"] for i in its)[len(its) // 2]
                refd = [i for i in its if i["ref"]]
                if refd:
                    row["wer_served"] = wer([(i["ref"], i["served"]["text"]) for i in refd])
                    row["wer_raw"] = wer([(i["ref"], (i["raw"] or {}).get("text")) for i in refd])
                res["by_group_and_length"][f"{g}/{cond}"] = row
            res["not_french_examples"] = [example(i) for i in items if i["served"]["status"] == "not_french"][:12]
            res["no_speech_on_speech_examples"] = [example(i) for i in items if i["served"]["status"] == "no_speech" and i["condition"] != "full"][:6]
        acc = load(os.path.join(V1, "evals", f"{m}-accent.json"))["items"]
        by = defaultdict(list)
        for i in acc:
            by[dur_bucket(i["seconds"])].append(i)
        res["accent_v1_by_duration"] = {}
        for b in [dur_bucket(lo) for lo, _ in DUR]:
            its = by.get(b, [])
            if not its:
                continue
            row = status_counts(its)
            row["wer_served"] = wer([(i["ref"], i["served"]["text"]) for i in its])
            row["wer_if_not_refused"] = wer([(i["ref"], i["raw"]["text"]) for i in its])
            res["accent_v1_by_duration"][b] = row
        res["accent_v1_not_french_examples"] = [{"id": i["id"], "seconds": i["seconds"], "p_fr": i["raw"]["p_fr"], "top": i["raw"]["top_language"],
                                                 "model_text": i["raw"]["text"], "reference": i["ref"]}
                                                for i in sorted(acc, key=lambda i: i["seconds"]) if i["served"]["status"] == "not_french"][:12]
        out[m] = res
    return out


# ---------------------------------------------------------------- item 12
def language():
    out = {}
    for m in MODELS:
        items = robust(m, "language")
        if not items:
            continue
        res = {}
        groups = defaultdict(list)
        for i in items:
            groups[(i["group"], i["condition"])].append(i)
        for (g, cond), its in sorted(groups.items()):
            cur, alt = status_counts(its, "served"), status_counts(its, "served_warning_only")
            row = {"n": len(its), "current": cur, "warning_only": alt}
            moved = [i for i in its if i["served"]["status"] == "not_french" and i["served_warning_only"]["status"] == "transcribed"]
            row["refused_now_transcribed_with_warning"] = len(moved)
            row["warning_only_flagged_possibly_not_french"] = sum(1 for i in its if "possibly_not_french" in i["served_warning_only"]["warnings"])
            refd = [i for i in its if i["ref"]]
            if refd:
                row["wer_current"] = wer([(i["ref"], i["served"]["text"]) for i in refd])
                row["wer_warning_only"] = wer([(i["ref"], i["served_warning_only"]["text"]) for i in refd])
                row["wer_of_rescued"] = wer([(i["ref"], i["served_warning_only"]["text"]) for i in moved if i["ref"]])
            row["examples_changed"] = [{**example(i), "warning_only_text": i["served_warning_only"]["text"]} for i in moved[:6]]
            res[f"{g}/{cond}"] = row
        out[m] = res
    return out


THRESHOLDS = (0.2, 0.05, 0.02, 0.01, 0.005, 0.002, 0.001)


def refused_at(p_fr, top, t, p_top=None):
    """The language rule with a P(fr) threshold t (the current rule: t = 0.2).
    Its P(top) > 0.6 condition applies when P(top) is known (the v2 files);
    the v1 files do not store it."""
    return p_fr is not None and p_fr < t and top not in (None, "fr") and (p_top is None or p_top > 0.6)


def threshold_sweep():
    """Refusals per P(fr) threshold: chosen on the v1 sets (development),
    confirmed on the separate v2 language sample."""
    out = {}
    for m in MODELS:
        dev = {"accented_v1_ca16": [(i["raw"]["p_fr"], i["raw"]["top_language"]) for i in load(os.path.join(V1, "evals", f"{m}-accent.json"))["items"]],
               "native_v1_test": [(i["raw"]["p_fr"], i["raw"]["top_language"]) for i in load(os.path.join(V1, "evals", f"{m}-test.json"))["items"]],
               "native_v1_ood": [(i["raw"]["p_fr"], i["raw"]["top_language"]) for i in load(os.path.join(V1, "evals", f"{m}-ood.json"))["items"]]}
        nf = os.path.join(V1, "evals", f"probes-{m}-nonfr.json")
        if os.path.exists(nf):
            dev["other_language_v1"] = [(w["p_fr"], w["top_language"]) for p in load(nf)["probes"] if p["name"].startswith("non_french_")
                                        for w in p["window_detail"][:1]]
        sep = {}
        items = robust(m, "language") or []
        for i in items:
            if i["raw"]:
                sep.setdefault(i["group"] + ("" if i["condition"] == "full" else "/" + i["condition"]), []).append((i["raw"]["p_fr"], i["raw"]["top_language"], i["raw"]["p_top_language"]))
        short = robust(m, "short") or []
        for i in short:
            if i["raw"] and i["condition"].startswith("cut_"):
                sep.setdefault(f"native_short/{i['condition']}", []).append((i["raw"]["p_fr"], i["raw"]["top_language"], i["raw"]["p_top_language"]))
        res = {}
        for name, sample in (("development_v1", dev), ("separate_v2", sep)):
            res[name] = {g: {"n": len(v), **{str(t): sum(1 for x in v if refused_at(*x[:2], t, *x[2:])) for t in THRESHOLDS}} for g, v in sorted(dev.items() if name == "development_v1" else sep.items())}
        out[m] = res
    return out


# ---------------------------------------------------------------- item 13
def noise():
    out = {}
    for m in MODELS:
        items = robust(m, "noise")
        if not items:
            continue
        groups = defaultdict(list)
        for i in items:
            groups[i["condition"]].append(i)
        res = {"by_condition": {}}
        for cond, its in sorted(groups.items()):
            row = status_counts(its)
            refd = [i for i in its if i["ref"]]
            if refd:
                row["wer_served"] = wer([(i["ref"], i["served"]["text"]) for i in refd])
                row["wer_raw"] = wer([(i["ref"], (i["raw"] or {}).get("text")) for i in refd])
                kept = [i for i in refd if i["served"]["status"] == "transcribed"]
                row["wer_of_transcribed"] = wer([(i["ref"], i["served"]["text"]) for i in kept])
            raws = [i["raw"] for i in its if i["raw"]]
            if raws:
                row["median_avg_logprob"] = sorted(r["avg_logprob"] for r in raws)[len(raws) // 2]
                row["median_no_speech_prob"] = sorted(r["no_speech_prob"] for r in raws)[len(raws) // 2]
            row["warnings"] = dict(Counter(w for i in its for w in i["served"]["warnings"]))
            row["median_snr_estimate_db"] = sorted(i["quality"].get("snr_db") or 0 for i in its)[len(its) // 2]
            row["median_rms_dbfs"] = sorted(i["quality"]["rms_dbfs"] for i in its)[len(its) // 2]
            res["by_condition"][cond] = row
        # Candidate rule: abstain when the window's average log-probability is
        # below T. Cost measured on the clean v1 test/ood/accent evaluations.
        res["logprob_rule"] = {}
        clean = {s: load(os.path.join(V1, "evals", f"{m}-{s}.json"))["items"] for s in ("test", "ood", "accent")}
        for t in (-0.6, -0.7, -0.8, -0.9, -1.0):
            noisy = [i for i in items if i["ref"] and i["condition"] != "clean" and i["served"]["status"] == "transcribed"]
            caught = [i for i in noisy if i["raw"]["avg_logprob"] < t]
            row = {"noisy_transcribed": len(noisy), "would_abstain": len(caught),
                   "wer_of_those": wer([(i["ref"], i["served"]["text"]) for i in caught]),
                   "wer_of_the_rest": wer([(i["ref"], i["served"]["text"]) for i in noisy if i not in caught])}
            for s, its in clean.items():
                tr = [i for i in its if i["served"]["status"] == "transcribed"]
                row[f"clean_{s}_would_abstain_pct"] = pct(sum(1 for i in tr if i["raw"]["avg_logprob"] < t), len(tr))
            res["logprob_rule"][str(t)] = row
        out[m] = res
    return out


# ---------------------------------------------------------------- item 16
def style_of(texts):
    import re
    texts = [t for t in texts if t]
    n = len(texts)
    return {"n": n, "with_punctuation": round(sum(1 for t in texts if re.search(r"[.,;:!?]", t)) / n, 4) if n else None,
            "with_uppercase": round(sum(1 for t in texts if any(c.isupper() for c in t)) / n, 4) if n else None}


def audit(data_dirs=()):
    """The v1 pilot: its training targets, its loss curve and what changed in its output."""
    out = {"training_targets": {}, "pilot_log": [], "outputs": {}}
    for d in data_dirs:
        path = os.path.join(d, "manifest.jsonl")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh]
            for split in sorted({r["split"] for r in rows}):
                out["training_targets"][f"{os.path.basename(os.path.normpath(d))}/{split}"] = style_of([r["text"] for r in rows if r["split"] == split])
    with open(os.path.join(V1, "training", "pilot-train-log.txt"), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("{"):
                e = json.loads(line)
                if "dev_loss" in e or e["step"] in (1, 30, 90, 150):
                    out["pilot_log"].append({k: e[k] for k in ("step", "loss", "dev_loss") if k in e})
    for split in ("test", "ood", "accent"):
        for who in ("base", "candidate"):
            doc = load(os.path.join(V1, "evals", f"{who}-{split}.json"))
            row = style_of([i["served"]["text"] for i in doc["items"]])
            row["wer"] = wer([(i["ref"], i["served"]["text"]) for i in doc["items"]])
            out["outputs"][f"{who}/{split}"] = row
    return out


# ---------------------------------------------------------------- checks
def verify():
    """Recompute every stored v2 evaluation summary (as v1's verify_evidence.py
    does) and the smoke candidate's acceptance verdict. Problems listed; none expected."""
    sys.path.insert(0, V1)
    import verify_evidence  # noqa: E402 (v1 checker, standard library only)
    problems, checked = [], []
    for sub in ("evals", "reeval"):
        d = os.path.join(HERE, sub)
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if f.endswith(".json") and not f.startswith("probes"):
                problems += verify_evidence.check_eval(os.path.join(d, f))
                checked.append(f"{sub}/{f}")
    acc_path = os.path.join(HERE, "acceptance-punct-smoke.json")
    if os.path.exists(acc_path):
        acc = load(acc_path)
        side = lambda who: {k: (load(os.path.join(HERE, acc["inputs"][who][k])) if k == "probes" else scored(load(os.path.join(HERE, acc["inputs"][who][k]))))
                            for k in ("test", "ood", "probes")}  # noqa: E731
        got = compare.acceptance(side("base"), side("candidate"), acc["overlap_free_test_ids"])
        if (got["verdict"], got["failed"]) != (acc["verdict"], acc["failed"]) or any(v != acc["criteria"][k] for k, v in got["criteria"].items()):
            problems.append("acceptance-punct-smoke.json differs from its recomputation")
        checked.append("acceptance-punct-smoke.json")
    return {"checked": checked, "problems": problems}


def main() -> int:
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    data_dirs = sys.argv[2:]
    fns = {"models": models, "short": short, "language": language, "thresholds": threshold_sweep, "noise": noise, "audit": lambda: audit(data_dirs), "verify": verify}
    if what == "all":
        todo = {k: v for k, v in fns.items() if k != "audit" or data_dirs}
    else:
        todo = {what: fns[what]}
    os.makedirs(os.path.join(HERE, "analysis"), exist_ok=True)
    for name, fn in todo.items():
        res = fn()
        with open(os.path.join(HERE, "analysis", f"{name}.json"), "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print(f"analysis/{name}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
