"""Paired comparison of two evaluations and the candidate acceptance rule.

``flh_speaking_acceptance_v1`` was written before any candidate was trained or
evaluated (2026-11-17, this batch). A candidate (fine-tuned checkpoint) is
compared with its own pretrained baseline on the same frozen items. Every
criterion must hold for PROMOTE_CANDIDATE; otherwise the verdict is
KEEP_BASELINE and the failed criteria are named. Promotion here only means "the
candidate may replace the baseline in the local service after owner review";
``production_go`` is always false.

  A1 in-domain gain   test served WER improves by >= 0.02 absolute and the 95%
                      paired speaker-cluster bootstrap interval of (B - A) is < 0
  A2 no OOD loss      FLEURS (ood) paired interval upper bound of (B - A) <= +0.01
  A3 no speaker loss  no test speaker's WER rises by more than 0.05
  A4 abstention       every probe the baseline abstains on, the candidate
                      abstains on too, and French speech is not abstained on
                      more often than by the baseline (test + ood)
  A5 readable output  on ood, the share of outputs with punctuation and with an
                      uppercase letter each stay >= 0.8 x the baseline's
  A6 not leakage      the test gain (B - A) is also negative on test utterances
                      that share no 8-gram with the training references
  A7 runtime          candidate CPU real-time factor <= 0.5 on test
"""

from __future__ import annotations

import json
import math
import random

from . import evaluate, textnorm

RULE = "flh_speaking_acceptance_v1"
MIN_GAIN = 0.02
OOD_TOLERANCE = 0.01
SPEAKER_TOLERANCE = 0.05
STYLE_RATIO = 0.8
MAX_RTF = 0.5


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def paired(a: dict, b: dict, which: str = "served", ids=None) -> dict:
    ia = {i["id"]: i for i in a["items"]}
    ib = {i["id"]: i for i in b["items"]}
    if set(ia) != set(ib):
        raise ValueError("the two evaluations do not cover the same items")
    keys = sorted(ia) if ids is None else sorted(set(ids) & set(ia))
    clusters: dict[str, list[int]] = {}
    for k in keys:
        if ia[k]["ref"] != ib[k]["ref"]:
            raise ValueError(f"reference differs for {k}")
        sa, sb = ia[k]["score"][which], ib[k]["score"][which]
        c = clusters.setdefault(ia[k]["cluster"], [0, 0, 0])
        c[0] += sa["sub"] + sa["del"] + sa["ins"]
        c[1] += sb["sub"] + sb["del"] + sb["ins"]
        c[2] += sa["ref_words"]
    names = sorted(clusters)
    ea, eb, w = (sum(clusters[n][j] for n in names) for j in range(3))
    rng = random.Random(evaluate.SEED)
    deltas = []
    for _ in range(evaluate.BOOTSTRAP):
        xa = xb = xw = 0
        for _ in names:
            c = clusters[names[rng.randrange(len(names))]]
            xa, xb, xw = xa + c[0], xb + c[1], xw + c[2]
        deltas.append((xb - xa) / xw if xw else 0.0)
    deltas.sort()
    n = len(deltas)
    per = {k: {"a": round(v[0] / v[2], 5) if v[2] else None, "b": round(v[1] / v[2], 5) if v[2] else None} for k, v in clusters.items()}
    up = sum(1 for v in per.values() if v["b"] is not None and v["b"] < v["a"])
    down = sum(1 for v in per.values() if v["b"] is not None and v["b"] > v["a"])
    better = sum(1 for k in keys if _err(ib[k], which) < _err(ia[k], which))
    worse = sum(1 for k in keys if _err(ib[k], which) > _err(ia[k], which))
    return {
        "items": len(keys), "clusters": len(names), "ref_words": w,
        "wer_a": round(ea / w, 5) if w else None, "wer_b": round(eb / w, 5) if w else None,
        "delta": round((eb - ea) / w, 5) if w else None,
        "delta_ci95": [round(deltas[int(0.025 * n)], 5), round(deltas[int(0.975 * n) - 1], 5)] if len(names) > 1 else None,
        "utterances_better": better, "utterances_worse": worse, "utterances_same": len(keys) - better - worse,
        "clusters_better": up, "clusters_worse": down, "cluster_sign_test_p": sign_test(up, down),
        "per_cluster": per,
    }


def sign_test(k: int, m: int) -> float | None:
    """Exact two-sided binomial sign test over clusters (ties dropped): supplementary
    to the bootstrap, whose percentile interval is coarse with few clusters."""
    n = k + m
    if n == 0:
        return None
    tail = sum(math.comb(n, i) for i in range(0, min(k, m) + 1)) / 2 ** n
    return round(min(1.0, 2 * tail), 5)


def _err(item, which):
    s = item["score"][which]
    return s["sub"] + s["del"] + s["ins"]


def compare_files(a_path: str, b_path: str, out: str) -> dict:
    a, b = _load(a_path), _load(b_path)
    res = {"rule": "paired", "split": a["summary"]["split"], "served": paired(a, b, "served"), "raw": paired(a, b, "raw")}
    res["verdict"] = {k: res["served"][k] for k in ("wer_a", "wer_b", "delta", "delta_ci95", "utterances_better", "utterances_worse")}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return res


def abstained(doc: dict) -> int:
    return sum(1 for i in doc["items"] if i["served"]["status"] != "transcribed")


def acceptance(base: dict, cand: dict, overlap_free_test_ids: list[str]) -> dict:
    """base/cand: {"test": eval doc, "ood": eval doc, "probes": probes doc}."""
    crit = {}
    t = paired(base["test"], cand["test"])
    crit["A1_in_domain_gain"] = {"pass": t["delta"] is not None and t["delta"] <= -MIN_GAIN and t["delta_ci95"] is not None and t["delta_ci95"][1] < 0,
                                 "delta": t["delta"], "ci95": t["delta_ci95"], "wer_base": t["wer_a"], "wer_candidate": t["wer_b"]}
    o = paired(base["ood"], cand["ood"])
    crit["A2_no_ood_loss"] = {"pass": o["delta_ci95"] is not None and o["delta_ci95"][1] <= OOD_TOLERANCE,
                              "delta": o["delta"], "ci95": o["delta_ci95"], "wer_base": o["wer_a"], "wer_candidate": o["wer_b"]}
    worst = max(((v["b"] - v["a"]), k) for k, v in t["per_cluster"].items())
    crit["A3_no_speaker_loss"] = {"pass": worst[0] <= SPEAKER_TOLERANCE, "worst_speaker": worst[1], "worst_delta": round(worst[0], 5)}
    pb = {p["name"]: p for p in base["probes"]["probes"]}
    pc = {p["name"]: p for p in cand["probes"]["probes"]}
    lost = sorted(n for n, p in pb.items() if p["expect"] == "abstain" and p["status"] != "transcribed" and pc[n]["status"] == "transcribed")
    over = (abstained(cand["test"]) + abstained(cand["ood"])) - (abstained(base["test"]) + abstained(base["ood"]))
    crit["A4_abstention"] = {"pass": not lost and over <= 0, "abstentions_lost": lost, "extra_abstentions_on_french": over}
    sb, sc = base["ood"]["summary"]["style"], cand["ood"]["summary"]["style"]
    crit["A5_readable_output"] = {
        "pass": sc.get("with_punctuation", 0) >= STYLE_RATIO * sb.get("with_punctuation", 0) and sc.get("with_uppercase", 0) >= STYLE_RATIO * sb.get("with_uppercase", 0),
        "base": sb, "candidate": sc}
    lf = paired(base["test"], cand["test"], ids=overlap_free_test_ids)
    crit["A6_not_leakage"] = {"pass": lf["delta"] is not None and lf["delta"] < 0, "items": lf["items"], "delta": lf["delta"], "ci95": lf["delta_ci95"]}
    rtf = cand["test"]["summary"]["timing"]["real_time_factor"]
    crit["A7_runtime"] = {"pass": rtf <= MAX_RTF, "real_time_factor": rtf}
    failed = sorted(k for k, v in crit.items() if not v["pass"])
    return {"rule": RULE, "verdict": "PROMOTE_CANDIDATE" if not failed else "KEEP_BASELINE", "failed": failed,
            "criteria": crit, "production_go": False}


def overlap_free(test_doc: dict, train_texts: list[str], n: int = 8) -> list[str]:
    grams = set()
    for t in train_texts:
        w = textnorm.words(t)
        grams |= {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}
    out = []
    for i in test_doc["items"]:
        w = textnorm.words(i["ref"])
        if not ({tuple(w[k:k + n]) for k in range(len(w) - n + 1)} & grams):
            out.append(i["id"])
    return out
