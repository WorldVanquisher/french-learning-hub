"""Speaking Lab: compare two transcript results against one reference (standard library only).

  python3 -B -m flh_speaking lab demo [--check]          # the shipped synthetic French case
  python3 -B -m flh_speaking lab compare CASE.json [--audio FILE] [--json OUT] [--text OUT]

A case (``flh_speaking_lab_case_v1``) holds one reference, the audio fixture's
identity and exactly two results, each with a model ID and a configuration ID.
The lab normalizes with ``flh_fr_asr_norm_v1`` (``textnorm``), aligns tokens
deterministically and reports, per result, the raw text, the normalized text
and every edit. The versioned JSON result (``flh_speaking_lab_result_v1``) is
the computation; the compact text is rendered from that JSON, never recomputed.

What it measures: agreement of words between a transcript and a reference.
What it does not: pronunciation, fluency or accent. A transcript can differ
from the reference because of the speaker, the recording or the model, and
this lab cannot tell which; it never grades the speaker.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import random
import re
import struct
import unicodedata
import wave

from . import review as rv
from . import textnorm

CASE_SCHEMA = "flh_speaking_lab_case_v1"
RESULT_SCHEMA = "flh_speaking_lab_result_v1"
MIN_REFERENCE_WORDS = 3  # fewer reference words: the comparison is reported as low evidence
DISCLAIMER = ("Word agreement between each transcript and the reference, after flh_fr_asr_norm_v1. "
              "Not a pronunciation, fluency or accent grade: a difference can come from the speaker, "
              "the recording or the model, and this comparison cannot tell which.")
FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "lab")
DEMO_CASE = os.path.join(FIXTURES, "synthetic_fr_case.json")

# Documented states (also in tools/speaking/README.md, Speaking Lab).
STATUS_OK = "compared"
STATUS_INSUFFICIENT = "insufficient_evidence"
REASONS = {
    "empty_reference": "the reference has no word after normalization, so no lexical comparison is possible",
    "short_reference": f"the reference has fewer than {MIN_REFERENCE_WORDS} words: one edit moves the error rate a lot",
    "empty_prediction": "this result has no text (abstention, silence or failure): every reference word counts as deleted",
    "possibly_wrong_language": "the runtime reported another language; the text is kept and compared as it is",
}


_TOKEN = re.compile(r"\w+|[^\w\s]")


def surface_tokens(text: str, cased: bool) -> list[str]:
    """Punctuation-sensitive tokens: NFC, words and single punctuation marks
    (apostrophe variants unified), with or without case. "L'élève," ->
    ["L", "'", "élève", ","]."""
    t = unicodedata.normalize("NFC", text).translate(str.maketrans({"’": "'", "‘": "'", "ʼ": "'"}))
    return _TOKEN.findall(t if cased else t.lower())


def is_punct(token: str | None) -> bool:
    return bool(token) and not any(ch.isalnum() for ch in token)


def views(reference: str, text: str) -> dict:
    """Three measures of the same pair, so a gain can be attributed:
    cased_punct (as written), uncased_punct (case ignored), normalized
    (flh_fr_asr_norm_v1: case, punctuation and the rest ignored). Case is
    counted as the extra errors of the cased view over the uncased one (it does
    not depend on which equal-cost alignment is chosen); punctuation as the
    uncased edits that involve a punctuation token."""
    out = {}
    for name, rt, ht in (("cased_punct", surface_tokens(reference, True), surface_tokens(text, True)),
                         ("uncased_punct", surface_tokens(reference, False), surface_tokens(text, False)),
                         ("normalized", textnorm.words(reference), textnorm.words(text))):
        ops = edits(rt, ht)
        errors = sum(1 for e in ops if e["op"] != "equal")
        v = {"ref_tokens": len(rt), "errors": errors, "error_rate": round(errors / len(rt), 4) if rt else None}
        if name == "uncased_punct":
            v["punctuation_edits"] = sum(1 for e in ops if e["op"] != "equal" and (is_punct(e["ref"]) or is_punct(e["hyp"])))
        out[name] = v
    out["cased_punct"]["case_attributable_errors"] = out["cased_punct"]["errors"] - out["uncased_punct"]["errors"]
    return out

VIEW_ORDER = ("cased_punct", "uncased_punct", "normalized")


def strip_accents(token: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", token) if not unicodedata.combining(c))


def edits(ref: list[str], hyp: list[str]) -> list[dict]:
    """Minimum-edit alignment as a list of operations, with the same
    deterministic tie-breaking as ``textnorm.align``: on equal cost a
    diagonal step (match or substitution) wins, then a deletion, then an
    insertion. Each op: equal | sub | del | ins, with the tokens and positions."""
    n, m = len(ref), len(hyp)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    for j in range(1, m + 1):
        cost[0][j], back[0][j] = j, 3
    for i in range(1, n + 1):
        cost[i][0], back[i][0] = i, 2
        for j in range(1, m + 1):
            best, op = cost[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]), (0 if ref[i - 1] == hyp[j - 1] else 1)
            if cost[i - 1][j] + 1 < best:
                best, op = cost[i - 1][j] + 1, 2
            if cost[i][j - 1] + 1 < best:
                best, op = cost[i][j - 1] + 1, 3
            cost[i][j], back[i][j] = best, op
    out, i, j = [], n, m
    while i > 0 or j > 0:
        op = back[i][j]
        if op in (0, 1):
            r, h = ref[i - 1], hyp[j - 1]
            e = {"op": "equal" if op == 0 else "sub", "ref": r, "hyp": h, "ref_index": i - 1, "hyp_index": j - 1}
            if op == 1 and strip_accents(r) == strip_accents(h):
                e["accent_only"] = True  # the same letters with other diacritics
            out.append(e)
            i, j = i - 1, j - 1
        elif op == 2:
            out.append({"op": "del", "ref": ref[i - 1], "hyp": None, "ref_index": i - 1, "hyp_index": None})
            i -= 1
        else:
            out.append({"op": "ins", "ref": None, "hyp": hyp[j - 1], "ref_index": None, "hyp_index": j - 1})
            j -= 1
    return out[::-1]


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def synthetic_audio() -> bytes:
    """The demo's audio fixture: 0.6 s of a 220 Hz tone with a soft envelope,
    16 kHz mono PCM16, generated byte-identically on every platform. It is a
    placeholder that gives the case a hashable audio identity; it is not speech
    and no model was run on it."""
    sr, n = 16000, 9600
    frames = b"".join(struct.pack("<h", int(round(9000 * math.sin(2 * math.pi * 220 * k / sr) * math.sin(math.pi * k / n)))) for k in range(n))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(frames)
    return buf.getvalue()


def validate_case(case: dict) -> None:
    if case.get("schema") != CASE_SCHEMA:
        raise ValueError(f"case schema must be {CASE_SCHEMA}")
    for k in ("id", "reference", "audio", "results"):
        if k not in case:
            raise ValueError(f"case is missing {k!r}")
    if not isinstance(case["audio"], dict) or len(str(case["audio"].get("sha256", ""))) != 64:
        raise ValueError("case audio must carry a 64-hex sha256")
    if not isinstance(case["results"], list) or len(case["results"]) != 2:
        raise ValueError("a case compares exactly two results")
    labels = set()
    for r in case["results"]:
        for k in ("label", "model_id", "config_id", "text"):
            if not isinstance(r.get(k), str):
                raise ValueError(f"each result needs a string {k!r}")
        labels.add(r["label"])
    if len(labels) != 2:
        raise ValueError("the two results need distinct labels")


def compare_one(ref_words: list[str], reference: str, r: dict) -> dict:
    hyp_words = textnorm.words(r["text"])
    ops = edits(ref_words, hyp_words)
    counts = {k: sum(1 for e in ops if e["op"] == k) for k in ("equal", "sub", "del", "ins")}
    sc = textnorm.score(reference, r["text"])
    n = len(ref_words)
    notes = []
    if not hyp_words:
        notes.append("empty_prediction")
    lang = r.get("language")
    if isinstance(lang, dict) and lang.get("top") not in (None, "fr"):
        notes.append("possibly_wrong_language")
    wer_v = round((counts["sub"] + counts["del"] + counts["ins"]) / n, 4) if n else None
    conf = r.get("confidence")
    diagnostics = [
        {"name": "wer", "value": wer_v, "kind": "measured", "basis": "token alignment after flh_fr_asr_norm_v1"},
        {"name": "accent_only_substitutions", "value": sum(1 for e in ops if e.get("accent_only")), "kind": "rule",
         "basis": "substitutions whose tokens are equal once diacritics are removed"},
        {"name": "low_evidence", "value": n < MIN_REFERENCE_WORDS, "kind": "heuristic", "basis": f"fewer than {MIN_REFERENCE_WORDS} reference words"},
        {"name": "confidence", "value": conf if conf is not None else None, "kind": "supplied" if conf is not None else "not_supplied",
         "basis": "as reported by the runtime" if conf is not None else "the runtime supplied no comparable confidence; none is computed here"},
    ]
    if isinstance(lang, dict):
        diagnostics.append({"name": "language", "value": lang, "kind": "supplied", "basis": "as reported by the runtime"})
    out_extra = {"diagnostics": diagnostics, "runtime_status": r.get("status")}
    if not hyp_words:
        out_extra["suggested_retry"] = rv.suggest_retry(r.get("status"))
    return {**out_extra,
        "label": r["label"], "model_id": r["model_id"], "config_id": r["config_id"],
        "provenance": r.get("provenance", ""),
        "raw": r["text"], "normalized": " ".join(hyp_words),
        "edits": ops, "counts": counts,
        "accent_only_substitutions": sum(1 for e in ops if e.get("accent_only")),
        "wer": round((counts["sub"] + counts["del"] + counts["ins"]) / n, 4) if n else None,
        "cer": round(sc["char_errors"] / sc["ref_chars"], 4) if sc["ref_chars"] else None,
        "ref_words": n, "ref_chars": sc["ref_chars"], "char_errors": sc["char_errors"], "notes": notes,
        "views": views(reference, r["text"]),
    }


def compare(case: dict, audio_sha256: str | None = None) -> dict:
    """The lab computation. ``audio_sha256``, when given, must equal the case's."""
    validate_case(case)
    if audio_sha256 is not None and audio_sha256 != case["audio"]["sha256"]:
        raise ValueError(f"audio sha256 {audio_sha256[:12]}… does not match the case ({case['audio']['sha256'][:12]}…)")
    ref_words = textnorm.words(case["reference"])
    out = {
        "schema": RESULT_SCHEMA, "case_id": case["id"], "normalization": textnorm.NORM_VERSION,
        "normalization_fingerprint": textnorm.policy_fingerprint(),
        "audio": dict(case["audio"]), "reference": {"raw": case["reference"], "normalized": " ".join(ref_words), "words": len(ref_words)},
        "disclaimer": DISCLAIMER, "reasons": {},
    }
    if not ref_words:
        out.update(status=STATUS_INSUFFICIENT, results=[], paired=None)
        out["reasons"]["empty_reference"] = REASONS["empty_reference"]
        return out
    results = [compare_one(ref_words, case["reference"], r) for r in case["results"]]
    a, b = results
    if len(ref_words) < MIN_REFERENCE_WORDS:
        out["reasons"]["short_reference"] = REASONS["short_reference"]
    for r in results:
        for note in r["notes"]:
            out["reasons"][note] = REASONS[note]
    err = lambda r: r["counts"]["sub"] + r["counts"]["del"] + r["counts"]["ins"]  # noqa: E731
    differing = sorted({e["ref_index"] for r in results for e in r["edits"] if e["op"] in ("sub", "del") and e["ref_index"] is not None})
    out["status"] = STATUS_OK
    out["results"] = results
    out["paired"] = {
        "labels": [a["label"], b["label"]], "errors": [err(a), err(b)], "difference_b_minus_a": err(b) - err(a),
        "reference_positions_with_an_edit": differing,
        "evidence": "low" if out["reasons"] else "single_case",
        "note": "One case is one observation: use the paired evaluation (compare/accept) for a model decision.",
    }
    return out


def _side_by_side(ops: list[dict]) -> tuple[str, str, str]:
    top, bottom, marks = [], [], []
    for e in ops:
        r, h = e["ref"] or "*", e["hyp"] or "*"
        w = max(len(r), len(h))
        mark = {"equal": "", "sub": "S~" if e.get("accent_only") else "S", "del": "D", "ins": "I"}[e["op"]]
        w = max(w, len(mark))
        top.append(r.ljust(w))
        bottom.append(h.ljust(w))
        marks.append(mark.ljust(w))
    return " ".join(top).rstrip(), " ".join(bottom).rstrip(), " ".join(marks).rstrip()


def render_text(res: dict) -> str:
    """Compact text, rendered only from the JSON result."""
    lines = [f"Speaking Lab {res['schema']}  case {res['case_id']}  status {res['status']}",
             f"Note: {res['disclaimer']}",
             f"audio sha256 {res['audio']['sha256']}  ({res['audio'].get('fixture', '')}: {res['audio'].get('description', '')})",
             f"reference   {res['reference']['raw']}",
             f"normalized  {res['reference']['normalized']}  ({res['reference']['words']} words, {res['normalization']})"]
    for code, why in sorted(res["reasons"].items()):
        lines.append(f"evidence: {code}: {why}")
    for r in res["results"]:
        c = r["counts"]
        top, bottom, marks = _side_by_side(r["edits"])
        lines += ["", f"[{r['label']}] model {r['model_id']}  config {r['config_id']}" + (f"  ({r['provenance']})" if r["provenance"] else ""),
                  f"  raw         {r['raw']}", f"  normalized  {r['normalized']}",
                  f"  ref         {top}", f"  hyp         {bottom}", f"  edit        {marks}",
                  f"  WER {r['wer']:.1%} ({c['sub']} sub, {c['del']} del, {c['ins']} ins over {r['ref_words']} reference words; "
                  f"{r['accent_only_substitutions']} accent-only)  CER {r['cer']:.1%}",
                  "  views       " + "  ".join(f"{k} {r['views'][k]['errors']}/{r['views'][k]['ref_tokens']}" for k in VIEW_ORDER)
                  + f"  (case {r['views']['cased_punct']['case_attributable_errors']}, punctuation {r['views']['uncased_punct']['punctuation_edits']})",
                  "  signals     " + "  ".join(f"{d['name']}={d['value'] if d['kind'] != 'not_supplied' else 'not supplied'} [{d['kind']}]" for d in r["diagnostics"])]
        if r.get("suggested_retry"):
            lines.append(f"  retry       {r['suggested_retry']['suggestion']} (cause {r['suggested_retry']['cause']})")
    if res["paired"]:
        p = res["paired"]
        lines += ["", f"paired: errors {p['labels'][0]} {p['errors'][0]}, {p['labels'][1]} {p['errors'][1]}; "
                      f"{p['labels'][1]} - {p['labels'][0]} = {p['difference_b_minus_a']:+d}; evidence {p['evidence']}. {p['note']}"]
    lines.append("edit marks: S substitution, S~ accent-only substitution, D deletion (* in hyp), I insertion (* in ref)")
    return "\n".join(lines) + "\n"


def to_json(res: dict) -> str:
    return json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def demo(check: bool = False) -> tuple[int, str]:
    """Run the shipped case. With ``check``, compare the JSON and text with the
    shipped expected files byte for byte (exit status 1 on any difference)."""
    with open(DEMO_CASE, encoding="utf-8") as fh:
        case = json.load(fh)
    audio = synthetic_audio()
    res = compare(case, hashlib.sha256(audio).hexdigest())
    text, js = render_text(res), to_json(res)
    if not check:
        return 0, text
    problems = []
    for suffix, got in ((".expected.json", js), (".expected.txt", text)):
        with open(DEMO_CASE.replace(".json", suffix), encoding="utf-8") as fh:
            if fh.read() != got:
                problems.append(os.path.basename(DEMO_CASE.replace(".json", suffix)))
    return (1, text + f"CHECK FAILED: output differs from {', '.join(problems)}\n") if problems else (0, text + "check: output equals the shipped expected JSON and text\n")


# ---- paired batch comparison (evaluation contract) ----
BATCH_SCHEMA = "flh_speaking_lab_batch_v1"
MIN_SLICE_GROUPS = 5  # a slice with fewer independent groups is an observation, never ranked
MIN_RANK_GROUPS = 30  # an overall ranking on fewer groups is labelled an observation


def _jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def read_refs(path: str) -> dict:
    """References: JSONL rows {"id", "reference", optional "speaker", "group_id", "tags"}.
    ``group_id`` ties variants to their source (default: the row's own id);
    ``tags`` is a {key: value} map used for slices."""
    out = {}
    for r in _jsonl(path):
        if r["id"] in out:
            raise ValueError(f"duplicate reference id {r['id']!r}")
        out[r["id"]] = r
    return out


def read_results(path: str) -> tuple[dict, dict]:
    """One model's results: a first line {"header": {"label", "model_id", "config_id", ...}}
    and rows {"id", "text"}. Duplicate ids are refused."""
    rows = _jsonl(path)
    if not rows or "header" not in rows[0]:
        raise ValueError(f"{os.path.basename(path)}: the first line must be {{\"header\": {{...}}}}")
    head = rows[0]["header"]
    for k in ("label", "model_id", "config_id"):
        if not isinstance(head.get(k), str):
            raise ValueError(f"{os.path.basename(path)}: header needs a string {k!r}")
    out = {}
    for r in rows[1:]:
        if r["id"] in out:
            raise ValueError(f"{os.path.basename(path)}: duplicate id {r['id']!r}")
        out[r["id"]] = {k: r[k] for k in ("text", "status", "language", "confidence") if k in r}
    return head, out


def _row(v) -> dict:
    """A result value: plain text, or {"text", optional runtime "status", "language", "confidence"}."""
    return {"text": v} if isinstance(v, str) else dict(v)


def _aggregate(rows: list[dict]) -> dict:
    agg = {"samples": len(rows), "ref_words": sum(r["ref_words"] for r in rows)}
    for k in ("sub", "del", "ins"):
        agg[k] = sum(r["counts"][k] for r in rows)
    agg["errors"] = agg["sub"] + agg["del"] + agg["ins"]
    agg["wer"] = round(agg["errors"] / agg["ref_words"], 4) if agg["ref_words"] else None
    agg["ref_chars"] = sum(r["ref_chars"] for r in rows)
    agg["char_errors"] = sum(r["char_errors"] for r in rows)
    agg["cer"] = round(agg["char_errors"] / agg["ref_chars"], 4) if agg["ref_chars"] else None
    agg["views"] = {}
    for v in ("cased_punct", "uncased_punct", "normalized"):
        n, e = sum(r["views"][v]["ref_tokens"] for r in rows), sum(r["views"][v]["errors"] for r in rows)
        agg["views"][v] = {"ref_tokens": n, "errors": e, "error_rate": round(e / n, 4) if n else None, "samples": len(rows)}
    agg["views"]["cased_punct"]["case_attributable_errors"] = sum(r["views"]["cased_punct"]["case_attributable_errors"] for r in rows)
    agg["views"]["uncased_punct"]["punctuation_edits"] = sum(r["views"]["uncased_punct"]["punctuation_edits"] for r in rows)
    empty = [r["id"] for r in rows if "empty_prediction" in r["notes"]]
    agg["empty_predictions"] = {"samples": len(empty), "ids": empty, "counted_as": "deletions of every reference word"}
    return agg


def batch(refs: dict, head_a: dict, res_a: dict, head_b: dict, res_b: dict, review: dict | None = None, manifests: dict | None = None) -> dict:
    """Paired comparison: both results are scored on exactly the same samples.
    Matched and missing ids (with reasons) are reported before any ranking;
    a ranking is given only when every id is matched and compared."""
    if head_a["label"] == head_b["label"]:
        raise ValueError("the two results need distinct labels")
    every = sorted(set(refs) | set(res_a) | set(res_b))
    missing = []
    for i in every:
        why = [w for w, ok in (("no reference", i in refs), (f"missing in {head_a['label']}", i in res_a),
                               (f"missing in {head_b['label']}", i in res_b)) if not ok]
        if why:
            missing.append({"id": i, "reasons": why})
    matched = [i for i in every if i in refs and i in res_a and i in res_b]
    review = review or {}
    reviewed_out, accepted, corrections = [], [], []
    for i, recs in sorted(review.items()):
        for r in recs:
            if r["action"] in ("invalid", "retry"):
                reviewed_out.append({"id": i, "action": r["action"], "reason": r["reason"], "reviewer": r["reviewer"]})
            elif r["action"] == "accept":
                accepted.append({"id": i, "reason": r["reason"], "reviewer": r["reviewer"]})
            else:
                original = {head_a["label"]: res_a, head_b["label"]: res_b}.get(r["label"], {}).get(i)
                original = _row(original)["text"] if original is not None else None
                corrections.append({"id": i, "label": r["label"], "original": original, "correction": r["correction"],
                                    "source": r["source"], "reviewer": r["reviewer"], "reason": r["reason"],
                                    "note": "the original hypothesis is kept and scored; the correction is recorded beside it"})
    out_ids = {e["id"] for e in reviewed_out}
    empty_ref, rows_a, rows_b, pairs = [], [], [], []
    for i in [x for x in matched if x not in out_ids]:
        ref = refs[i]["reference"]
        ref_words = textnorm.words(ref)
        if not ref_words:
            empty_ref.append(i)
            continue
        ra = compare_one(ref_words, ref, {"label": head_a["label"], "model_id": head_a["model_id"], "config_id": head_a["config_id"], **_row(res_a[i])})
        rb = compare_one(ref_words, ref, {"label": head_b["label"], "model_id": head_b["model_id"], "config_id": head_b["config_id"], **_row(res_b[i])})
        ra["id"] = rb["id"] = i
        rows_a.append(ra)
        rows_b.append(rb)
        ea, eb = (sum(r["counts"][k] for k in ("sub", "del", "ins")) for r in (ra, rb))
        pairs.append({"id": i, "ref_words": len(ref_words), "errors": [ea, eb], "speaker": refs[i].get("speaker"),
                      "group_id": refs[i].get("group_id") or i, "tags": refs[i].get("tags") or {}})
    better = sum(1 for p in pairs if p["errors"][1] < p["errors"][0])
    worse = sum(1 for p in pairs if p["errors"][1] > p["errors"][0])
    speakers = sorted({p["speaker"] for p in pairs if p["speaker"]})
    groups = sorted({p["group_id"] for p in pairs})
    by_group: dict = {}
    for p in pairs:
        g = by_group.setdefault(p["group_id"], [0, 0, 0])
        g[0] += p["errors"][0]
        g[1] += p["errors"][1]
        g[2] += p["ref_words"]
    out = {
        "schema": BATCH_SCHEMA, "normalization": textnorm.NORM_VERSION, "normalization_fingerprint": textnorm.policy_fingerprint(),
        "disclaimer": DISCLAIMER,
        "samples": {"in_references": len(refs), f"in_{head_a['label']}": len(res_a), f"in_{head_b['label']}": len(res_b),
                    "matched": len(matched), "compared": len(pairs), "groups": len(groups), "empty_reference": len(empty_ref),
                    "speakers": len(speakers) if speakers else "no speaker metadata"},
        "missing": missing, "empty_reference_ids": empty_ref,
        "review": {"excluded": reviewed_out, "accepted": accepted, "corrections": corrections, "actions": rv.ACTIONS} if review else None,
        "models": {h["label"]: {"model_id": h["model_id"], "config_id": h["config_id"],
                                "candidate_id": h.get("candidate_id"), "runtime": {"device": h.get("device"), "dtype": h.get("dtype")},
                                "resources": h.get("resources"), "seed": h.get("seed"), **_aggregate(rows)}
                   for h, rows in ((head_a, rows_a), (head_b, rows_b))},
        "sample_order_sha256": hashlib.sha256("\n".join(p["id"] for p in pairs).encode()).hexdigest(),
        "paired": {"labels": [head_a["label"], head_b["label"]], "samples": len(pairs),
                   f"{head_b['label']}_fewer_errors": better, f"{head_b['label']}_more_errors": worse, "same": len(pairs) - better - worse,
                   "difference_b_minus_a": sum(p["errors"][1] - p["errors"][0] for p in pairs), "per_sample": pairs,
                   "groups": len(groups), f"{head_b['label']}_fewer_errors_groups": sum(1 for a_, b_, _w in by_group.values() if b_ < a_),
                   f"{head_b['label']}_more_errors_groups": sum(1 for a_, b_, _w in by_group.values() if b_ > a_)},
        "slices": slices(pairs, head_a["label"], head_b["label"]),
        "uncertainty": group_bootstrap(by_group),
    }
    abst = sorted({r["id"] for r in rows_a + rows_b if "empty_prediction" in r["notes"]})
    keep_a = [r for r in rows_a if r["id"] not in abst]
    keep_b = [r for r in rows_b if r["id"] not in abst]
    out["abstentions"] = {"samples": len(abst), "ids": abst,
                          "including": {h["label"]: {k: out["models"][h["label"]][k] for k in ("samples", "errors", "ref_words", "wer")} for h in (head_a, head_b)},
                          "excluding": {h["label"]: {k: agg[k] for k in ("samples", "errors", "ref_words", "wer")}
                                        for h, agg in ((head_a, _aggregate(keep_a)), (head_b, _aggregate(keep_b)))},
                          "suggestions": [{"id": r["id"], "label": r["label"], **r["suggested_retry"]} for r in rows_a + rows_b if r.get("suggested_retry")],
                          "note": "excluding drops every sample where either result abstained, so both still see the same samples"}
    if reviewed_out:
        out["samples"]["reviewed_out"] = len(reviewed_out)
    if len(groups) < len(pairs):
        out["samples"]["note"] = f"{len(pairs)} samples come from {len(groups)} groups (variants share their source's group): count groups as independent evidence"
    invalid = []
    for h in (head_a, head_b):
        m = (manifests or {}).get(h["label"])
        if m is not None and h.get("candidate_id") != m["candidate_id"]:
            invalid.append(f"{h['label']} was produced by {h.get('candidate_id')!r} but the manifest now names {m['candidate_id']!r}")
    out["validity"] = {"checked": sorted((manifests or {}).keys()), "invalidated": invalid}
    seeds = {h.get("seed") for h in (head_a, head_b)}
    if invalid:
        out["ranking"] = {"status": "not_ranked", "reason": "invalidated: " + "; ".join(invalid)}
    elif None not in seeds and len(seeds) > 1:
        out["ranking"] = {"status": "not_ranked", "reason": f"the two runs used different seeds {sorted(seeds)}"}
    elif missing or not pairs:
        out["ranking"] = {"status": "not_ranked", "reason": "the sample sets differ: rank only on identical samples" if missing else "no comparable sample"}
    else:
        ea, eb = out["models"][head_a["label"]]["errors"], out["models"][head_b["label"]]["errors"]
        out["ranking"] = {"status": "ranked", "fewer_errors": head_a["label"] if ea < eb else head_b["label"] if eb < ea else "tie",
                          "samples": len(pairs), "groups": len(groups),
                          "note": (f"observation only: fewer than {MIN_RANK_GROUPS} groups" if len(groups) < MIN_RANK_GROUPS
                                   else f"on {len(groups)} groups; promotion still needs the acceptance rule (accept)")}
    # additive (item 103): status, fewer_errors, note and the exit codes are unchanged for existing consumers
    rk = out["ranking"]
    rk["standing"] = "not_ranked" if rk["status"] != "ranked" else ("observation" if len(groups) < MIN_RANK_GROUPS else "ranked")
    rk["min_groups"] = MIN_RANK_GROUPS
    return out


def standing_line(rk: dict, groups: int) -> str:
    if rk.get("standing") == "observation":
        return (f"standing: OBSERVATION ONLY: {groups} groups, fewer than {rk['min_groups']}; "
                "this comparison ranks nothing and supports no promotion")
    if rk.get("standing") == "not_ranked":
        return f"standing: NOT RANKED: {rk['reason']}"
    return f"standing: ranked on {groups} groups (at least {rk['min_groups']}); promotion still needs the acceptance rule"


BOOTSTRAP = {"resamples": 2000, "seed": 20261119, "level": 0.95}


def group_bootstrap(by_group: dict, resamples: int = BOOTSTRAP["resamples"], seed: int = BOOTSTRAP["seed"]) -> dict:
    """WER difference B - A with a percentile interval from resampling GROUPS
    with replacement (samples in a group are not independent). Deterministic:
    groups are sorted and the generator is seeded. It describes how much the
    difference moves when the same groups are redrawn; it does not cover groups
    unlike these (other speakers, learners, microphones)."""
    keys = sorted(by_group)
    base = {"method": "percentile bootstrap over groups", "resamples": resamples, "seed": seed, "level": BOOTSTRAP["level"],
            "groups": len(keys), "kind": "measured under resampling"}
    words = sum(by_group[k][2] for k in keys)
    if len(keys) < 2 or not words:
        return {**base, "wer_difference_b_minus_a": None, "interval_95": None, "reason": "fewer than 2 groups with reference words"}
    point = (sum(by_group[k][1] for k in keys) - sum(by_group[k][0] for k in keys)) / words
    rng, diffs = random.Random(seed), []
    for _ in range(resamples):
        ea = eb = w = 0
        for _k in range(len(keys)):
            g = by_group[keys[rng.randrange(len(keys))]]
            ea, eb, w = ea + g[0], eb + g[1], w + g[2]
        diffs.append((eb - ea) / w if w else 0.0)
    diffs.sort()
    lo, hi = diffs[int(0.025 * resamples)], diffs[min(resamples - 1, int(0.975 * resamples))]
    return {**base, "wer_difference_b_minus_a": round(point, 4), "interval_95": [round(lo, 4), round(hi, 4)],
            "excludes_zero": lo > 0 or hi < 0,
            "reliability": (f"few groups (< {MIN_RANK_GROUPS}): the interval is unstable" if len(keys) < MIN_RANK_GROUPS else "enough groups for a rough interval")}


def slices(pairs: list[dict], la: str, lb: str) -> dict:
    """Per tag key and value: samples, groups, WER of each result and the
    difference (b - a). A sample without the key counts in "(unlabelled)"; a
    sample with several keys belongs to one slice per key (slices overlap
    across keys, never within one). Slices with at least MIN_SLICE_GROUPS
    groups are ranked by the difference; the others are observations."""
    keys = sorted({k for p in pairs for k in p["tags"]})
    out = {"min_groups": MIN_SLICE_GROUPS, "keys": {}, "regressions": [], "improvements": [], "observations": []}
    for k in keys:
        cells: dict = {}
        for p in pairs:
            cells.setdefault(str(p["tags"].get(k, "(unlabelled)")), []).append(p)
        out["keys"][k] = {}
        for v, ps in sorted(cells.items()):
            n = sum(p["ref_words"] for p in ps)
            ea, eb = sum(p["errors"][0] for p in ps), sum(p["errors"][1] for p in ps)
            g = len({p["group_id"] for p in ps})
            cell = {"samples": len(ps), "groups": g, "ref_words": n, f"wer_{la}": round(ea / n, 4), f"wer_{lb}": round(eb / n, 4),
                    "difference_b_minus_a": round((eb - ea) / n, 4), "support": "ranked" if g >= MIN_SLICE_GROUPS else "observation"}
            out["keys"][k][v] = cell
            entry = {"slice": f"{k}={v}", **cell}
            if cell["support"] == "observation":
                out["observations"].append(entry)
            elif cell["difference_b_minus_a"] > 0:
                out["regressions"].append(entry)
            elif cell["difference_b_minus_a"] < 0:
                out["improvements"].append(entry)
    out["regressions"].sort(key=lambda e: (-e["difference_b_minus_a"], e["slice"]))
    out["improvements"].sort(key=lambda e: (e["difference_b_minus_a"], e["slice"]))
    out["observations"].sort(key=lambda e: e["slice"])
    return out


def render_batch_text(res: dict) -> str:
    s = res["samples"]
    lines = [f"Speaking Lab {res['schema']}  ({res['normalization']})", f"Note: {res['disclaimer']}",
             "samples: " + ", ".join(f"{k} {v}" for k, v in s.items())]
    if res["ranking"].get("standing"):
        lines.append(standing_line(res["ranking"], res["paired"]["groups"]))
    for m in res["missing"]:
        lines.append(f"missing: {m['id']}: {'; '.join(m['reasons'])}")
    for i in res["empty_reference_ids"]:
        lines.append(f"excluded: {i}: empty reference (no lexical comparison possible)")
    if res.get("review"):
        for e in res["review"]["excluded"]:
            lines.append(f"reviewed out: {e['id']}: {e['action']} ({e['reason']}; {e['reviewer']})")
        for e in res["review"]["accepted"]:
            lines.append(f"accepted: {e['id']} ({e['reason']}; {e['reviewer']})")
        for e in res["review"]["corrections"]:
            lines.append(f"correction: {e['id']} [{e['label']}] {e['original']!r} -> {e['correction']!r} (source: {e['source']}; original kept)")
    for label, m in res["models"].items():
        v = m["views"]
        lines.append(f"[{label}] model {m['model_id']}  config {m['config_id']}  samples {m['samples']}  WER {m['wer']}  "
                     f"({m['sub']} sub, {m['del']} del, {m['ins']} ins / {m['ref_words']} words)  CER {m['cer']}  "
                     f"cased+punct {v['cased_punct']['error_rate']}  uncased+punct {v['uncased_punct']['error_rate']}  "
                     f"empty predictions {m['empty_predictions']['samples']}")
        if m.get("resources") or m["runtime"]["device"]:
            lines.append(f"    runtime {m['runtime']['device']}/{m['runtime']['dtype']}  resources {json.dumps(m.get('resources'), sort_keys=True)}"
                         + (f"  candidate {m['candidate_id']}" if m.get("candidate_id") else ""))
    ab = res["abstentions"]
    if ab["samples"]:
        lines.append(f"abstentions: {ab['samples']} sample(s) {ab['ids']}; WER including / excluding: " + "; ".join(
            f"{k} {ab['including'][k]['wer']} ({ab['including'][k]['samples']}) / {ab['excluding'][k]['wer']} ({ab['excluding'][k]['samples']})" for k in ab["including"]))
        for sg in ab["suggestions"]:
            lines.append(f"retry suggestion: {sg['id']} [{sg['label']}] {sg['suggestion']} (cause {sg['cause']}, {sg['kind']})")
    p, rk = res["paired"], res["ranking"]
    lines.append(f"paired over {p['samples']} samples: {p['labels'][1]} fewer errors on {p[p['labels'][1] + '_fewer_errors']}, "
                 f"more on {p[p['labels'][1] + '_more_errors']}, same on {p['same']}; {p['labels'][1]} - {p['labels'][0]} = {p['difference_b_minus_a']:+d}")
    lines.append(f"ranking: {rk['status']}" + (f": fewer errors {rk['fewer_errors']} ({rk['note']})" if rk["status"] == "ranked" else f": {rk['reason']}"))
    u = res.get("uncertainty") or {}
    if u.get("interval_95"):
        lines.append(f"uncertainty: B - A = {u['wer_difference_b_minus_a']:+.4f} WER, 95% group-bootstrap interval "
                     f"[{u['interval_95'][0]:+.4f}, {u['interval_95'][1]:+.4f}] over {u['groups']} groups ({u['reliability']})")
    elif u:
        lines.append(f"uncertainty: not computed ({u['reason']})")
    sl = res["slices"]
    for title, key in (("regression", "regressions"), ("improvement", "improvements")):
        for e in sl[key]:
            lines.append(f"{title}: {e['slice']}  {e['groups']} groups / {e['samples']} samples  B - A = {e['difference_b_minus_a']:+.4f} WER")
    for e in sl["observations"]:
        lines.append(f"observation (fewer than {sl['min_groups']} groups, not ranked): {e['slice']}  {e['groups']} groups / {e['samples']} samples  "
                     f"B - A = {e['difference_b_minus_a']:+.4f} WER")
    return "\n".join(lines) + "\n"


# ---- shared-report hygiene ----
PRIVATE_PATTERNS = {
    # built by concatenation so this source file does not match its own patterns
    "home_path": re.compile("/" + "home" + r"/[^/\s\"']+/"),
    "macos_home_path": re.compile("/" + "Users" + r"/[^/\s\"']+/"),
    "windows_user_path": re.compile(r"[A-Za-z]:\\Users\\"),
    "session_link": re.compile(r"https?://(?:[a-z0-9-]+\.)?claude\.ai/\S+"),
    "uuid": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
}


def privacy_findings(text: str) -> list[dict]:
    """Machine-local paths, session links and UUID-like IDs (take or request keys) in a shared report."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for name, rx in PRIVATE_PATTERNS.items():
            for m in rx.finditer(line):
                out.append({"line": n, "kind": name, "match": m.group(0)[:40]})
    return out
