"""Offline candidate review: is a transcription model ready for the owner to consider? (standard library only)

  python3 -B -m flh_speaking lab candidate-review --baseline EVAL.json --candidate EVAL.json
        [--thresholds FILE] [--data-manifest MANIFEST.jsonl] [--experiment experiment-result.json]
        [--json OUT] [--text OUT]
  python3 -B -m flh_speaking lab candidate-review-demo --out NEW_DIR [--check]

The inputs are saved ``evaluate`` outputs (``flh_speaking_eval_v1``). The review
reads their stored texts and timing only: no model, audio or network is used to
render it. The paired comparison is ``lab.batch``, the same one ``lab batch``
prints, with each speaker as one group. The review adds:
- both model identities and the SHA-256 of every input;
- WER, CER, real-time factor and peak memory side by side, each value marked
  ``measured`` or ``not_measured``;
- support, quality and resource checks against explicit, configurable limits
  (``flh_speaking_candidate_thresholds_v1``; every limit is inclusive);
- one outcome with concrete reasons.

Outcomes, first applicable wins:
  mismatched_inputs       exit 5  the two evaluations cannot be compared as they are
  insufficient_support    exit 4  too few paired samples or independent groups
  thresholds_not_met      exit 3  a quality or resource check failed or was not measured
  ready_for_owner_review  exit 0  every check passed

No outcome promotes anything. ``ready_for_owner_review`` says only that this
evidence is complete under these limits. The decision and any serving change
(RUNBOOK.md, ``SPEAKING_TRANSCRIPTION_*``) stay with the owner, and this command
has no option that makes them.
"""

from __future__ import annotations

import hashlib
import json
import math
import os

from . import candidates, lab, pins, textnorm

SCHEMA = "flh_speaking_candidate_review_v1"
THRESHOLDS_SCHEMA = "flh_speaking_candidate_thresholds_v1"
EVAL_SCHEMA = "flh_speaking_eval_v1"
EXIT = {"ready_for_owner_review": 0, "thresholds_not_met": 3, "insufficient_support": 4, "mismatched_inputs": 5}
DEFAULT_THRESHOLDS = {
    "support": {"min_paired_samples": 30, "min_groups": lab.MIN_RANK_GROUPS},
    "quality": {"max_wer_difference": -0.02, "max_interval_upper": 0.0, "max_cer_difference": 0.0, "max_group_wer_increase": 0.05},
    "resources": {"max_real_time_factor": 0.5, "max_peak_rss_mb": 2048.0},
}
MEANING = {
    "support.min_paired_samples": "samples compared in pairs (same id, same reference, both results present)",
    "support.min_groups": "independent groups (speakers) among the compared samples",
    "quality.max_wer_difference": "candidate WER minus baseline WER (negative: fewer word errors)",
    "quality.max_interval_upper": "upper end of the 95% speaker-bootstrap interval of that difference",
    "quality.max_cer_difference": "candidate CER minus baseline CER",
    "quality.max_group_wer_increase": "largest WER rise for any one speaker, candidate minus baseline",
    "resources.max_real_time_factor": "candidate compute seconds per audio second, as recorded by evaluate",
    "resources.max_peak_rss_mb": "candidate peak resident memory of the evaluate process (MB), as recorded",
}
TIMING = (("real_time_factor", "compute seconds per audio second, recorded by evaluate"),
          ("peak_rss_mb", "peak resident memory of the evaluate process in MB, recorded by evaluate"),
          ("compute_s", "transcription seconds, recorded by evaluate"),
          ("model_load_s", "model load seconds, recorded by evaluate"),
          ("audio_s", "audio seconds transcribed, recorded by evaluate"))
DEMO = os.path.join(lab.FIXTURES, "candidate_review")
SCENARIOS = (("ready", "baseline.json", "candidate.json"), ("insufficient", "baseline-8.json", "candidate-8.json"),
             ("mismatched", "baseline.json", "candidate-mismatched.json"))


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def load_thresholds(doc: dict | None) -> dict:
    """Defaults, overridden by a (partial) thresholds document. Unknown keys refuse the file."""
    values = json.loads(json.dumps(DEFAULT_THRESHOLDS))
    if doc is None:
        return values
    if not isinstance(doc, dict) or doc.get("schema") != THRESHOLDS_SCHEMA:
        raise ValueError(f"thresholds schema must be {THRESHOLDS_SCHEMA}")
    for section, items in doc.items():
        if section == "schema":
            continue
        if section not in values or not isinstance(items, dict):
            raise ValueError(f"unknown thresholds section {section!r}")
        for k, v in items.items():
            if k not in values[section]:
                raise ValueError(f"unknown threshold {section}.{k}")
            if not _num(v) or (section == "support" and (not isinstance(v, int) or v < 1)):
                raise ValueError(f"threshold {section}.{k} must be a number" + (" (an integer >= 1)" if section == "support" else ""))
            values[section][k] = v
    return values


def read_input(path: str) -> tuple[dict, dict]:
    """(parsed JSON, {"file": basename, "bytes", "sha256"}); only the basename is reported."""
    with open(path, "rb") as fh:
        raw = fh.read()
    return json.loads(raw.decode("utf-8")), {"file": os.path.basename(path), "bytes": len(raw), "sha256": _sha(raw)}


def check_eval(doc: dict, role: str) -> None:
    if not isinstance(doc, dict) or doc.get("schema") != EVAL_SCHEMA:
        raise ValueError(f"{role}: not a saved evaluation ({EVAL_SCHEMA})")
    if not isinstance(doc.get("summary"), dict) or not isinstance(doc.get("items"), list) or not isinstance(doc.get("model_dir_name"), str):
        raise ValueError(f"{role}: an evaluation needs summary, items and model_dir_name")
    ids = [i.get("id") for i in doc["items"]]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{role}: duplicate item ids")
    for i in doc["items"]:
        if not isinstance(i.get("ref"), str) or not isinstance((i.get("served") or {}).get("text"), str):
            raise ValueError(f"{role}: item {i.get('id')!r} needs a reference and a served text")


def identity(doc: dict, role: str) -> dict:
    name = next((n for n, m in sorted(pins.MODELS.items()) if m["revision"] == doc["model_dir_name"]), None)
    out = {"role": role, "stored_label": doc["summary"].get("label", ""), "model_dir_name": doc["model_dir_name"],
           "decoding": doc.get("decoding"), "normalization": doc.get("normalization"), "split": doc["summary"].get("split"),
           "runtime": doc.get("runtime") or {}, "pinned_name": name, "speakers": len({i.get("cluster") or i["id"] for i in doc["items"]}),
           "samples": len(doc["items"])}
    if name:
        out["candidate_id"] = candidates.manifest(name)["candidate_id"]
        out["candidate_id_basis"] = "manifest of the pinned revision under this tree's lock (the evaluation records the model directory, not the ID)"
    else:
        out["candidate_id"] = None
        out["candidate_id_basis"] = "not pinned: the model directory name matches no revision in pins.py, so no candidate ID exists"
    return out


def measures(agg: dict, doc: dict) -> dict:
    out = {}
    for k, basis in (("wer", "word errors / reference words, recomputed from the stored served texts (flh_fr_asr_norm_v1)"),
                     ("cer", "character errors / reference characters, recomputed from the stored served texts")):
        out[k] = {"value": agg[k], "status": "measured", "basis": basis} if agg[k] is not None else \
            {"value": None, "status": "not_measured", "reason": "no reference words were compared"}
    timing = doc["summary"].get("timing") or {}
    for k, basis in TIMING:
        v = timing.get(k)
        out[k] = {"value": v, "status": "measured", "basis": basis} if _num(v) else \
            {"value": None, "status": "not_measured", "reason": "the evaluation recorded no timing" if not timing else f"the evaluation's timing has no {k}"}
    out["conditions"] = {"threads": timing.get("threads"), "batch": timing.get("batch"), **(doc.get("runtime") or {})}
    return out


def stored_totals_check(doc: dict, role: str) -> dict:
    """The stored summary must count what the stored texts give (an edited or mixed file fails)."""
    s = (doc["summary"].get("served") or {})
    if not all(_num(s.get(k)) for k in ("sub", "del", "ins", "ref_words")):
        return {"code": f"{role}_stored_summary", "status": "not_recorded", "detail": f"the {role} evaluation stores no served totals to check against"}
    errors = words = 0
    for i in doc["items"]:
        sc = textnorm.score(i["ref"], i["served"]["text"])
        errors, words = errors + sc["sub"] + sc["del"] + sc["ins"], words + sc["ref_words"]
    stored = (s["sub"] + s["del"] + s["ins"], s["ref_words"])
    if stored == (errors, words):
        return {"code": f"{role}_stored_summary", "status": "ok", "detail": f"stored totals ({stored[0]} errors / {stored[1]} words) equal the recomputation"}
    return {"code": f"{role}_stored_summary", "status": "mismatch",
            "detail": f"the {role} summary stores {stored[0]} errors / {stored[1]} words but its texts give {errors} / {words}: the file was edited or mixed"}


def _check(cid: str, value, limit, op: str, fmt: str, evaluated: bool = True, why: str = "") -> dict:
    c = {"id": cid, "value": value, "limit": limit, "comparison": op, "meaning": MEANING[cid]}
    if not evaluated:
        c["status"], c["reason"] = "not_evaluated", why
    elif value is None:
        c["status"], c["reason"] = "not_measured", why or "not measured"
    else:
        ok = value <= limit if op == "<=" else value >= limit
        c["status"] = "pass" if ok else "fail"
        c["reason"] = f"{value:{fmt}} {op} {limit:{fmt}}" + ("" if ok else " does not hold")
    return c


def review(base_doc: dict, cand_doc: dict, inputs: dict, thresholds: dict | None = None,
           data_manifest: list[dict] | None = None, experiment: dict | None = None) -> dict:
    """The review computation. ``inputs`` holds the input records ({"file", "bytes", "sha256"} per role and
    for any optional input); ``data_manifest`` the prepared manifest rows; ``experiment`` an experiment result."""
    th = thresholds or load_thresholds(None)
    check_eval(base_doc, "baseline")
    check_eval(cand_doc, "candidate")
    ra, rows_a = candidates.from_eval(base_doc, "baseline", group="speaker")
    rb, rows_b = candidates.from_eval(cand_doc, "candidate", group="speaker")
    refs = {r["id"]: r for r in rb} | {r["id"]: r for r in ra}
    ref_b = {r["id"]: r["reference"] for r in rb}
    differing = sorted(r["id"] for r in ra if r["id"] in ref_b and ref_b[r["id"]] != r["reference"])
    res = lambda rows: {r["id"]: {"text": r["text"], "status": r["status"]} for r in rows[1:]}  # noqa: E731
    cmp = lab.batch(refs, rows_a[0]["header"], res(rows_a), rows_b[0]["header"], res(rows_b))
    ida, idb = identity(base_doc, "baseline"), identity(cand_doc, "candidate")

    checks_in = []  # input checks: ok | mismatch | not_recorded | not_supplied
    add = lambda code, ok, detail: checks_in.append({"code": code, "status": "ok" if ok else "mismatch", "detail": detail})  # noqa: E731
    add("same_split", ida["split"] == idb["split"], f"both evaluated on split {ida['split']}" if ida["split"] == idb["split"]
        else f"baseline split {ida['split']!r} but candidate split {idb['split']!r}: the audio differs")
    norms = {ida["normalization"], idb["normalization"]}
    add("same_normalization", norms == {textnorm.NORM_VERSION}, f"both scored under {textnorm.NORM_VERSION}" if norms == {textnorm.NORM_VERSION}
        else f"scored under {sorted(str(n) for n in norms)}; this review recomputes under {textnorm.NORM_VERSION}")
    miss = cmp["missing"]
    add("same_ids", not miss, "every id is in both evaluations" if not miss else
        f"{len(miss)} id(s) not in both: " + "; ".join(f"{m['id']} ({', '.join(m['reasons'])})" for m in miss[:5]) + (" …" if len(miss) > 5 else ""))
    add("same_references", not differing, "every shared id has the same reference" if not differing else
        f"{len(differing)} id(s) have another reference in the candidate: {', '.join(differing[:5])}" + (" …" if len(differing) > 5 else ""))
    checks_in += [stored_totals_check(base_doc, "baseline"), stored_totals_check(cand_doc, "candidate")]
    same = (ida["model_dir_name"], ida["decoding"]) == (idb["model_dir_name"], idb["decoding"])
    add("distinct_models", not same, "baseline and candidate are different models" if not same
        else "both sides are the same model and decoding: that is a rerun, not a candidate")
    if experiment is not None:
        cands = (experiment.get("defining") or {}).get("candidates") or {}
        for ident in (ida, idb):
            n = ident["pinned_name"]
            ok = n is not None and cands.get(n) == ident["candidate_id"]
            add(f"{ident['role']}_in_experiment", ok, f"{n} ran in the experiment as {ident['candidate_id']}" if ok else
                (f"{ident['model_dir_name'][:12]} is not a candidate of the experiment" if n not in cands
                 else f"the experiment ran {cands[n]} but this tree's manifest is {ident['candidate_id']}: the lock or pins changed"))
    else:
        checks_in.append({"code": "experiment", "status": "not_supplied", "detail": "no experiment result given: image, limits and run identity are not reported"})
    if data_manifest is not None:
        rows = {(r.get("split"), r.get("id")): r for r in data_manifest}
        compared = [p["id"] for p in cmp["paired"]["per_sample"]]
        lacking = [i for i in compared if len(str((rows.get((ida["split"], i)) or {}).get("pcm_sha256", ""))) != 64]
        add("audio_in_data_manifest", not lacking, f"{len(compared)} compared ids have a PCM SHA-256 in split {ida['split']}" if not lacking
            else f"{len(lacking)} compared id(s) have no PCM SHA-256 in split {ida['split']}: {', '.join(lacking[:5])}")
        want = ((experiment or {}).get("defining") or {}).get("prepare", {}).get("prepared_manifest_sha256")
        if want:
            got = inputs["data_manifest"]["sha256"]
            add("data_manifest_is_the_experiments", got == want, "the data manifest is the one the experiment prepared" if got == want
                else f"the experiment prepared manifest {want[:12]}… but {got[:12]}… was given")
    else:
        checks_in.append({"code": "data_manifest", "status": "not_supplied", "detail": "no data manifest given: the audio behind the texts is identified by the split name only"})
    if cmp["ranking"]["status"] != "ranked" and not miss:
        add("comparable", False, cmp["ranking"]["reason"])
    mismatched = [c for c in checks_in if c["status"] == "mismatch"]

    ma, mb = cmp["models"]["baseline"], cmp["models"]["candidate"]
    words, chars = ma["ref_words"], ma["ref_chars"]
    wer_d = round((mb["errors"] - ma["errors"]) / words, 4) if words else None
    cer_d = round((mb["char_errors"] - ma["char_errors"]) / chars, 4) if chars else None
    by_group: dict = {}
    for p in cmp["paired"]["per_sample"]:
        g = by_group.setdefault(p["group_id"], [0, 0, 0])
        g[0], g[1], g[2] = g[0] + p["errors"][0], g[1] + p["errors"][1], g[2] + p["ref_words"]
    rises = sorted(((round((g[1] - g[0]) / g[2], 4), k) for k, g in by_group.items() if g[2]), key=lambda t: (-t[0], t[1]))
    sens = None
    if len(by_group) >= 2:
        loo = []
        for k in sorted(by_group):
            rest = [g for kk, g in by_group.items() if kk != k]
            w = sum(g[2] for g in rest)
            loo.append((round((sum(g[1] for g in rest) - sum(g[0] for g in rest)) / w, 4), k))
        sens = {"method": "leave one group out", "groups": len(loo), "min": min(loo)[0], "max": max(loo)[0],
                "most_influential_group": max(loo, key=lambda t: (abs(t[0] - (wer_d or 0)), t[1]))[1]}
    u = cmp["uncertainty"]
    upper = u["interval_95"][1] if u.get("interval_95") else None
    sp, qu, rs = th["support"], th["quality"], th["resources"]
    groups, paired = cmp["paired"]["groups"], cmp["paired"]["samples"]
    checks = [
        _check("support.min_paired_samples", paired, sp["min_paired_samples"], ">=", "d"),
        _check("support.min_groups", groups, sp["min_groups"], ">=", "d"),
    ]
    ev, why = not mismatched, "the inputs are mismatched: no quality or resource check is evaluated"
    meas_b = measures(mb, cand_doc)
    checks += [
        _check("quality.max_wer_difference", wer_d, qu["max_wer_difference"], "<=", "+.4f", ev, why if not ev else "no reference words"),
        _check("quality.max_interval_upper", upper, qu["max_interval_upper"], "<=", "+.4f", ev, why if not ev else u.get("reason", "")),
        _check("quality.max_cer_difference", cer_d, qu["max_cer_difference"], "<=", "+.4f", ev, why if not ev else "no reference characters"),
        _check("quality.max_group_wer_increase", rises[0][0] if rises else None, qu["max_group_wer_increase"], "<=", "+.4f", ev,
               why if not ev else "no group with reference words"),
        _check("resources.max_real_time_factor", meas_b["real_time_factor"]["value"], rs["max_real_time_factor"], "<=", ".4f", ev,
               why if not ev else meas_b["real_time_factor"].get("reason", "")),
        _check("resources.max_peak_rss_mb", meas_b["peak_rss_mb"]["value"], rs["max_peak_rss_mb"], "<=", ".1f", ev,
               why if not ev else meas_b["peak_rss_mb"].get("reason", "")),
    ]
    if rises:
        checks[5]["group"] = rises[0][1]
    short = [c for c in checks[:2] if c["status"] != "pass"]
    unmet = [c for c in checks[2:] if c["status"] != "pass"]
    if mismatched:
        outcome, reasons = "mismatched_inputs", [{"code": c["code"], "detail": c["detail"]} for c in mismatched]
    elif short:
        outcome = "insufficient_support"
        reasons = [{"code": c["id"], "detail": f"{c['value']} {'groups (speakers)' if c['id'].endswith('groups') else 'paired samples'} compared; "
                                              f"at least {c['limit']} are required"} for c in short]
        passed = sum(1 for c in checks[2:] if c["status"] == "pass")
        reasons.append({"code": "other_checks_decide_nothing", "detail": f"{passed} of {len(checks) - 2} quality and resource checks pass, "
                                                                          "but with this support they are observations and decide nothing"})
    elif unmet:
        outcome = "thresholds_not_met"
        reasons = [{"code": c["id"], "detail": (c["reason"] if c["status"] == "fail" else f"not measured: {c['reason']}")} for c in unmet]
    else:
        outcome = "ready_for_owner_review"
        reasons = [{"code": "all_checks_pass", "detail": f"{paired} paired samples over {groups} groups; every support, quality and "
                                                         "resource check passes: the evidence is ready for the owner to decide"}]
    return {
        "schema": SCHEMA, "outcome": outcome, "exit_code": EXIT[outcome], "reasons": reasons,
        "promotion": {"performed": False, "decided_by": "owner",
                      "note": "No outcome promotes a model or changes a serving setting; ready_for_owner_review means only that this "
                              "evidence is complete under these limits.",
                      "owner_steps": ["check the candidate's files: lab candidate check --name NAME --model-dir DIR",
                                      "run the acceptance rule flh_speaking_acceptance_v1 (accept) on the frozen holdout, ood and probes",
                                      "decide, then change RUNBOOK.md or SPEAKING_TRANSCRIPTION_* yourself"]},
        "serving_default": "unchanged (RUNBOOK.md decides what is served)",
        "models": {"baseline": ida, "candidate": idb},
        "inputs": {**inputs, "references_sha256": _sha("".join(f"{i}\t{refs[i]['reference']}\n" for i in sorted(refs)).encode()),
                   "sample_order_sha256": cmp["sample_order_sha256"], "experiment_id": (experiment or {}).get("experiment_id"),
                   "experiment_image_id": ((experiment or {}).get("defining") or {}).get("image_id"),
                   "experiment_limits": ((experiment or {}).get("defining") or {}).get("limits")},
        "input_checks": checks_in,
        "samples": {"baseline": ida["samples"], "candidate": idb["samples"], "matched": cmp["samples"]["matched"], "paired": paired,
                    "missing": [m["id"] for m in miss], "empty_reference": cmp["empty_reference_ids"],
                    "speakers": {"baseline": ida["speakers"], "candidate": idb["speakers"], "paired": cmp["samples"]["speakers"]},
                    "groups": groups, "group_unit": "speaker"},
        "measures": {"baseline": measures(ma, base_doc), "candidate": meas_b, "difference": {"wer": wer_d, "cer": cer_d}},
        "uncertainty": u, "sensitivity": sens, "checks": checks, "thresholds": th,
        "standing": cmp["ranking"].get("standing"), "comparison": cmp, "disclaimer": lab.DISCLAIMER,
    }


def _v(m: dict, fmt: str) -> str:
    return "not measured" if m["status"] != "measured" else f"{m['value']:{fmt}}"


def render_text(rv: dict) -> str:
    """Compact text, rendered only from the review JSON."""
    L = [f"Speaking candidate review {rv['schema']}", f"OUTCOME: {rv['outcome']} (exit {rv['exit_code']})"]
    L += [f"  - {r['code']}: {r['detail']}" for r in rv["reasons"]]
    L.append("promotion: not performed. The owner decides; this review changes no serving setting.")
    L.append("models:")
    for role, m in rv["models"].items():
        name = f"{m['pinned_name']} ({m['model_dir_name'][:12]})" if m["pinned_name"] else f"unpinned {m['model_dir_name']}"
        L.append(f"  {role:9} {name}  decoding {m['decoding']}  split {m['split']}  "
                 f"candidate_id {m['candidate_id'] or 'none (' + m['candidate_id_basis'].split(':')[0] + ')'}")
        L.append(f"            stored label: {m['stored_label']}")
    i = rv["inputs"]
    L.append("inputs (sha256):")
    for k in ("baseline", "candidate", "data_manifest", "experiment", "thresholds"):
        if k in i:
            L.append(f"  {k:13} {i[k]['file']}  {i[k]['bytes']} bytes  {i[k]['sha256']}")
        elif k == "thresholds":
            L.append(f"  {k:13} defaults ({THRESHOLDS_SCHEMA})")
    L.append(f"  references    {i['references_sha256']}  sample order {i['sample_order_sha256']}")
    if i.get("experiment_id"):
        lim = i.get("experiment_limits") or {}
        L.append(f"  experiment    {i['experiment_id']}  image {str(i['experiment_image_id'])[:19]}  limits "
                 + ", ".join(f"{k} {lim[k]}" for k in sorted(lim)))
    L.append("input checks:")
    L += [f"  {c['status']:12} {c['code']}: {c['detail']}" for c in rv["input_checks"]]
    s = rv["samples"]
    L.append(f"samples: baseline {s['baseline']}, candidate {s['candidate']}, matched {s['matched']}, paired {s['paired']}, "
             f"missing {len(s['missing'])}{' ' + str(s['missing']) if s['missing'] else ''}; speakers baseline {s['speakers']['baseline']}, "
             f"candidate {s['speakers']['candidate']}, paired {s['speakers']['paired']}; groups {s['groups']} (one per {s['group_unit']})")
    mb, mc, d = rv["measures"]["baseline"], rv["measures"]["candidate"], rv["measures"]["difference"]
    L.append(f"  {'measure':22} {'baseline':>14} {'candidate':>14} {'candidate-baseline':>19}")
    for k, name, fmt in (("wer", "WER", ".4f"), ("cer", "CER", ".4f"), ("real_time_factor", "real-time factor", ".4f"),
                         ("peak_rss_mb", "peak RSS (MB)", ".1f"), ("compute_s", "compute (s)", ".1f"), ("model_load_s", "model load (s)", ".2f")):
        diff = f"{d[k]:+.4f}" if k in d and d[k] is not None else ""
        L.append(f"  {name:22} {_v(mb[k], fmt):>14} {_v(mc[k], fmt):>14} {diff:>19}")
    for role, m in (("baseline", mb), ("candidate", mc)):
        c = m["conditions"]
        L.append(f"  measured under ({role}): " + ", ".join(f"{k} {c[k]}" for k in sorted(c) if c[k] is not None) if any(v is not None for v in c.values())
                 else f"  measured under ({role}): not recorded")
    u = rv["uncertainty"]
    L.append(f"standing of the paired comparison: {rv['standing']}")
    if u.get("interval_95"):
        L.append(f"uncertainty: candidate - baseline = {u['wer_difference_b_minus_a']:+.4f} WER, 95% speaker-bootstrap interval "
                 f"[{u['interval_95'][0]:+.4f}, {u['interval_95'][1]:+.4f}] over {u['groups']} groups ({u['reliability']})")
    else:
        L.append(f"uncertainty: not computed ({u.get('reason')})")
    if rv["sensitivity"]:
        x = rv["sensitivity"]
        L.append(f"sensitivity: leaving one speaker out moves the WER difference between {x['min']:+.4f} and {x['max']:+.4f} "
                 f"({x['groups']} groups; speaker {x['most_influential_group']} moves it most)")
    L.append("checks (limits are inclusive: a value equal to its limit passes):")
    for c in rv["checks"]:
        L.append(f"  {c['status']:13} {c['id']:34} {c['reason']}")
    if rv["outcome"] == "insufficient_support":
        L.append("  with insufficient support the quality and resource checks are shown for information only")
    L.append(f"Note: {rv['disclaimer']}")
    return "\n".join(L) + "\n"


def _per_group(rv: dict) -> dict:
    """{group: [baseline errors, candidate errors, reference words, clips]} from the review's paired samples."""
    out: dict = {}
    for p in rv["comparison"]["paired"]["per_sample"]:
        g = out.setdefault(str(p["group_id"]), [0, 0, 0, 0])
        g[0], g[1], g[2], g[3] = g[0] + p["errors"][0], g[1] + p["errors"][1], g[2] + p["ref_words"], g[3] + 1
    return out


def _speakers_by_split(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(r.get("split", "?"), set()).add(r.get("speaker"))
    return {k: len(v) for k, v in sorted(out.items())}


def walkthrough(rv: dict, data_manifest: list[dict] | None = None) -> str:
    """A step-by-step account of the support rule for one saved review: why its speakers are, or are not,
    enough for the owner to decide. It reads only the review (and, optionally, the data manifest the
    evaluations came from to count the speakers each split can offer). Deterministic; no inference."""
    if rv.get("schema") != SCHEMA:
        raise ValueError(f"not a {SCHEMA} document")
    th = rv["thresholds"]["support"]
    need, need_n = th["min_groups"], th["min_paired_samples"]
    by = _per_group(rv)
    keys = sorted(by)
    n, paired = len(keys), rv["samples"]["paired"]
    L = [f"Support walkthrough for a {SCHEMA} review", f"outcome: {rv['outcome']} (exit {rv['exit_code']}); standing of the comparison: {rv['standing']}", ""]
    came = f"but they come from only {n} speakers" if paired > n else f"one from each of {n} speakers"
    L.append(f"1. What is counted. {paired} clips were compared in pairs, {came}. Clips of one speaker "
             "share a voice, a microphone and a text, so they are not independent: the review counts SPEAKERS as the unit of "
             f"evidence (groups). The rule asks for at least {need} speakers and at least {need_n} paired clips; limits are inclusive.")
    L.append(f"   clips: {paired} {'>=' if paired >= need_n else '<'} {need_n} -> {'pass' if paired >= need_n else 'fail'}; "
             f"speakers: {n} {'>=' if n >= need else '<'} {need} -> {'pass' if n >= need else 'fail'}"
             + (f"; {need - n} more distinct speakers are needed" if n < need else ""))
    L.append("")
    L.append("2. Every speaker separately (WER = errors / reference words; difference = candidate - baseline):")
    L.append(f"   {'speaker':>10} {'clips':>5} {'words':>6} {'baseline':>9} {'candidate':>9} {'difference':>10}")
    better = worse = 0
    for k in keys:
        ea, eb, w, c = by[k]
        d = (eb - ea) / w if w else 0.0
        better, worse = better + (eb < ea), worse + (eb > ea)
        L.append(f"   {k:>10} {c:>5} {w:>6} {ea / w if w else 0:>9.4f} {eb / w if w else 0:>9.4f} {d:>+10.4f}")
    same = n - better - worse
    L.append(f"   the candidate makes fewer errors for {better} of {n} speakers, more for {worse}, the same for {same}.")
    if n and (better == n or worse == n):
        L.append(f"   If the two models were equally good, all {n} speakers pointing the same way would happen with probability "
                 f"{2 * 0.5 ** n:.4f} (two-sided sign test). So the direction is unlikely to be chance FOR THESE SPEAKERS. "
                 "That is a real observation; it is not yet evidence about speakers unlike them.")
    L.append("")
    L.append("3. How stable the size of the difference is.")
    u = rv["uncertainty"]
    if u.get("interval_95"):
        L.append(f"   point estimate {u['wer_difference_b_minus_a']:+.4f}; 95% speaker-bootstrap interval "
                 f"[{u['interval_95'][0]:+.4f}, {u['interval_95'][1]:+.4f}] (seed {u['seed']}, {u['resamples']} resamples).")
        groups = {k: by[k][:3] for k in keys}
        rows = []
        for seed in range(u["seed"], u["seed"] + 5):
            b = lab.group_bootstrap(groups, resamples=u["resamples"], seed=seed)
            rows.append(b["interval_95"])
        lo, hi = [r[0] for r in rows], [r[1] for r in rows]
        move = max(max(lo) - min(lo), max(hi) - min(hi))
        L.append(f"   five consecutive seeds give lower ends {min(lo):+.4f}..{max(lo):+.4f} and upper ends {min(hi):+.4f}..{max(hi):+.4f}: "
                 f"the random draw moves an end by at most {move:.4f}. The weakness is not the draw: every resample can only "
                 f"reuse these {n} speakers.")
        L.append(f"   with {n} speakers there are {math.comb(2 * n - 1, n):,} distinct resamples; with {need} there would be "
                 f"{math.comb(2 * need - 1, need):.1e}. With few groups a percentile bootstrap tends to cover less often than "
                 "its stated 95% (a known property of the method, not measured here).")
        clips = {f"{p['id']}": (p["errors"][0], p["errors"][1], p["ref_words"]) for p in rv["comparison"]["paired"]["per_sample"]}
        cb = lab.group_bootstrap(clips, resamples=u["resamples"], seed=u["seed"])
        if cb["interval_95"] and len(clips) > n:
            wc, ws = cb["interval_95"][1] - cb["interval_95"][0], u["interval_95"][1] - u["interval_95"][0]
            rel = "wider than" if wc > ws else "narrower than" if wc < ws else "the same as"
            L.append(f"   resampling the {len(clips)} clips as if independent gives [{cb['interval_95'][0]:+.4f}, {cb['interval_95'][1]:+.4f}] "
                     f"(width {wc:.4f}, {rel} the speaker interval's {ws:.4f}). "
                     "Either way it answers the wrong question: clips of one speaker are not independent draws, so "
                     f"{paired} clips are still {n} speakers' worth of evidence, and clips alone never satisfy the rule.")
    else:
        L.append(f"   no interval: {u.get('reason')}. With fewer than two speakers there is no spread to measure at all.")
    x = rv.get("sensitivity")
    if x:
        L.append(f"   leaving one speaker out moves the difference between {x['min']:+.4f} and {x['max']:+.4f}; speaker "
                 f"{x['most_influential_group']} moves it most. With {x['groups']} speakers each is roughly "
                 f"{100 / x['groups']:.1f}% of the evidence (weighted by its words); with {need}, roughly {100 / need:.1f}%.")
    L.append("")
    L.append("4. Who the speakers are. The review cannot see it; the data manifest and the experiment's own limits say it.")
    if data_manifest is not None:
        per = _speakers_by_split(data_manifest)
        total = len({r.get("speaker") for r in data_manifest})
        L.append("   speakers per split in the data manifest: " + ", ".join(f"{k} {v}" for k, v in per.items())
                 + f"; {total} distinct speakers overall")
        used = {m.get("split") for m in rv["models"].values()} & set(per)
        for split in sorted(used):
            if per[split] < need:
                L.append(f"   split '{split}' has {per[split]} speakers in total, so no selection from it can reach {need}.")
        below = [k for k, v in per.items() if v < need]
        if below and len(below) == len(per):
            L.append(f"   every split has fewer than {need} speakers: more speakers must come from new data, never from "
                     "splitting one speaker's clips.")
        corpora = sorted({str(r.get("corpus")) for r in data_manifest if r.get("corpus")})
        if corpora:
            L.append("   corpora named in the manifest: " + ", ".join(corpora))
    else:
        L.append("   (no data manifest given: the speakers each split can offer are not counted)")
    L.append("   Whatever the count, the rule is a minimum, not a sufficiency: thirty speakers of read speech still say "
             "little about learners, accents or phone microphones. The experiment's limits of evidence name its population.")
    L.append("")
    L.append("5. What the other checks say.")
    others = [c for c in rv["checks"] if not c["id"].startswith("support.")]
    status = {}
    for c in others:
        status.setdefault(c["status"], []).append(c["id"])
    L.append("   " + "; ".join(f"{k}: {len(v)} ({', '.join(v)})" for k, v in sorted(status.items())))
    would = ("ready_for_owner_review" if all(c["status"] == "pass" for c in others) else "thresholds_not_met")
    if rv["outcome"] == "insufficient_support":
        L.append(f"   If these same values came with enough support, the outcome would be '{would}'. That is not a forecast: "
                 "with more speakers the values themselves change. The limit is not lowered to fit the data; a threshold "
                 "change is an owner decision in a thresholds file, and the review names the file it used.")
    L.append("")
    L.append("6. Decision.")
    if rv["outcome"] == "insufficient_support":
        L.append(f"   {rv['outcome']}: the comparison stays an observation. The candidate is not ready for the owner's promotion "
                 "decision on this evidence.")
    else:
        L.append(f"   {rv['outcome']}: " + "; ".join(r["detail"] for r in rv["reasons"]))
    L.append(f"   promotion performed: {str(rv['promotion']['performed']).lower()}; serving default: {rv['serving_default']}.")
    return "\n".join(L) + "\n"


def from_files(baseline: str, candidate: str, thresholds: str | None = None, data_manifest: str | None = None,
               experiment: str | None = None) -> dict:
    base, rec_a = read_input(baseline)
    cand, rec_b = read_input(candidate)
    inputs = {"baseline": rec_a, "candidate": rec_b}
    th = None
    if thresholds:
        doc, inputs["thresholds"] = read_input(thresholds)
        th = load_thresholds(doc)
    exp = None
    if experiment:
        exp, inputs["experiment"] = read_input(experiment)
    rows = None
    if data_manifest:
        with open(data_manifest, "rb") as fh:
            raw = fh.read()
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        inputs["data_manifest"] = {"file": os.path.basename(data_manifest), "bytes": len(raw), "sha256": _sha(raw)}
    return review(base, cand, inputs, th, rows, exp)


def demo(out: str, check: bool = False) -> tuple[int, str]:
    """Render the three shipped synthetic scenarios into a new or empty directory, plus the support
    walkthrough of the insufficient one; with ``check``, compare each output with the shipped expected
    files byte for byte (exit 1 on any difference)."""
    if os.path.exists(out) and (not os.path.isdir(out) or os.listdir(out)):
        raise ValueError("--out must be a new or empty directory")
    os.makedirs(out, exist_ok=True)
    lines, bad = [], []
    for name, a, b in SCENARIOS:
        rv = from_files(os.path.join(DEMO, a), os.path.join(DEMO, b))
        for suffix, body in ((".json", lab.to_json(rv)), (".txt", render_text(rv))):
            with open(os.path.join(out, name + suffix), "w", encoding="utf-8") as fh:
                fh.write(body)
            if check:
                with open(os.path.join(DEMO, "expected", name + suffix), encoding="utf-8") as fh:
                    if fh.read() != body:
                        bad.append(name + suffix)
        if rv["outcome"] == "insufficient_support":
            body = walkthrough(rv)
            with open(os.path.join(out, name + ".walkthrough.txt"), "w", encoding="utf-8") as fh:
                fh.write(body)
            if check:
                with open(os.path.join(DEMO, "expected", name + ".walkthrough.txt"), encoding="utf-8") as fh:
                    if fh.read() != body:
                        bad.append(name + ".walkthrough.txt")
        lines.append(f"{name:13} {a} vs {b}: {rv['outcome']} (exit {rv['exit_code']})")
    text = "\n".join(lines) + "\n"
    if check:
        return (1, text + f"CHECK FAILED: differs from expected {', '.join(bad)}\n") if bad else (0, text + "check: every output equals the shipped expected JSON and text\n")
    return 0, text
