"""Recall measurement for a later trial (Extraction 2.2; PROTOTYPE, offline, synthetic).

Three outcomes are kept apart (``flh_recall_outcomes_v1``):

* ``unassisted_recall``: the learner states the rule with no options and no source sentence
  (explain). Never graded automatically: a self-check.
* ``assisted_recall``: the learner chooses between the forms; the options are the cue
  (choose). Graded exactly.
* ``transfer``: the learner produces the form in a sentence that is in neither the source,
  the practice items nor any study packet (produce). Accepted variants are correct, a listed
  error is incorrect, anything else is a self-check.

A **probe** (``flh_recall_probe_v1``) is a fixed set of such items for a delayed check. Each
item records its difficulty controls. ``novelty`` proves, by word comparison, that no probe
prompt or answer occurs in the source, the practice or any study packet given, and reports
the longest word sequence each item shares with them. ``order`` is a seeded, deterministic
shuffle; no two items share an example key (verb + place).

Responses (``flh_probe_response_v1``) have one status each: ``completed`` (an answer the
probe can score), ``revealed`` (deliberately shown without answering), ``skipped``
(neither) or ``unsupported`` (an answer the probe cannot score: not one of the options, or
a production with neither form of the contrast). A planned item with no response is
``missing``. ``summary`` reports every count with its denominator and never folds missing
or skipped items into a rate.

What this cannot show: anything about long-term retention. One synthetic dry run checks
the arithmetic of the summary, nothing about learning.
"""

from __future__ import annotations

import glob
import json
import os

from . import practice as pr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(HERE, "fixtures", "practice_v1")
PROBE_DIR = os.path.join(FIX, "probe")
EXPECTED = os.path.join(PROBE_DIR, "expected")

PROBE = "flh_recall_probe_v1"
RESPONSE = "flh_probe_response_v1"
SUMMARY = "flh_probe_summary_v1"
TYPES = {"unassisted_recall": "explain", "assisted_recall": "choose", "transfer": "produce"}
STATUSES = ("completed", "revealed", "skipped", "unsupported")
DEFINITIONS = {
    "unassisted_recall": "state the rule with nothing to choose from and no source sentence; a self-check (never graded automatically)",
    "assisted_recall": "choose between the confusable forms; the options are a cue; graded exactly",
    "transfer": "produce the form in a sentence that is in neither the source, the practice nor any study packet; accepted variants, "
                "listed errors, otherwise a self-check",
}


def words(s: str) -> list[str]:
    return pr.fr_norm(s).replace("'", "' ").split()


def longest_shared(a: str, corpus: list[str]) -> int:
    """Length of the longest word sequence of ``a`` that also occurs in one text of ``corpus``."""
    wa = words(a)
    texts = [" " + " ".join(words(t)) + " " for t in corpus]
    best = 0
    for i in range(len(wa)):
        for j in range(i + best + 1, len(wa) + 1):
            if any(" " + " ".join(wa[i:j]) + " " in t for t in texts):
                best = j - i
            else:
                break
    return best


def keys(it: dict) -> list[str]:
    """The strings that would give an item away: a production's answers, a choice's completed sentence."""
    if it["type"] == "assisted_recall":
        filled = it["prompt"].replace("__", it["answer"]) if "'__" not in it["prompt"] else it["prompt"].replace("'__ ", "'" + it["answer"] + " ")
        return [filled.split("—", 1)[1].strip() if "—" in filled else filled]
    return [a for a in [it.get("answer")] + list(it.get("accepted") or []) if a]


def novelty(probe: dict, corpus: dict) -> dict:
    """``corpus`` maps a name (source, practice, study packets) to its text. An item is novel when
    neither its prompt nor any of its answers occurs in any text (normalised)."""
    rows, texts = [], list(corpus.values())
    for it in probe["items"]:
        answers = keys(it)
        found = [(n, s) for s in [it["prompt"]] + answers for n, t in corpus.items() if pr.fr_norm(s) and pr.fr_norm(s) in pr.fr_norm(t)]
        rows.append({"id": it["id"], "type": it["type"], "difficulty": it.get("difficulty"), "novel": not found,
                     "found_in": [f"{n}: « {s} »" for n, s in found],
                     "longest_shared_words": max([longest_shared(s, texts) for s in [it["prompt"]] + answers] or [0])})
    return {"items": rows, "all_novel": all(r["novel"] for r in rows), "corpus": sorted(corpus)}


def answers_in_packets(probe: dict, packets: dict) -> list[str]:
    """Probe answers found in a study packet's text (JSON or Markdown): must be empty."""
    out = []
    for it in probe["items"]:
        for a in keys(it):
            for n, t in packets.items():
                if pr.fr_norm(a) in pr.fr_norm(t):
                    out.append(f"{it['id']}: « {a} » in {n}")
    return out


def order(probe: dict) -> list[str]:
    """A seeded deterministic shuffle; refuses a probe whose items repeat an example."""
    keys = [it["example_key"] for it in probe["items"]]
    if len(set(keys)) != len(keys):
        raise ValueError("a probe must not repeat an example: " + ", ".join(sorted({k for k in keys if keys.count(k) > 1})))
    prompts = [pr.fr_norm(it["prompt"]) for it in probe["items"]]
    if len(set(prompts)) != len(prompts):
        raise ValueError("a probe must not repeat a prompt")
    return [it["id"] for it in sorted(probe["items"], key=lambda it: pr.sha(probe["seed"] + "\x1f" + it["id"]))]


def _as_practice(it: dict) -> dict:
    kind = TYPES[it["type"]]
    hidden = {"explanation": it.get("rule", ""), "answer": it.get("answer"), "accepted": it.get("accepted", []), "known_errors": it.get("known_errors", [])}
    p = {"kind": kind, "hidden": hidden}
    if kind == "choose":
        p["options"] = it["options"]
    return p


def score(it: dict, r: dict | None) -> dict:
    """The status and, for a completed answer, the outcome of one planned item."""
    if r is None:
        return {"id": it["id"], "type": it["type"], "status": "missing"}
    st = r.get("status")
    if st not in STATUSES:
        raise ValueError(f"{it['id']}: status must be one of {STATUSES}")
    if st in ("revealed", "skipped"):
        if (r.get("text") or "").strip():
            raise ValueError(f"{it['id']}: a {st} item carries no answer")
        return {"id": it["id"], "type": it["type"], "status": st}
    text = (r.get("text") or "").strip()
    if not text:
        raise ValueError(f"{it['id']}: a {st} response needs the answer")
    g = pr.grade(_as_practice(it), text)
    forms = [pr.fr_norm(f) for f in it.get("forms", [])]
    scorable = g["outcome"] != "invalid" and not (it["type"] == "transfer" and g["outcome"] == "self_check" and forms
                                                   and not any(f" {f} " in " " + " ".join(words(text)) + " " for f in forms))
    status = "completed" if scorable else "unsupported"
    if st != status:
        raise ValueError(f"{it['id']}: recorded as {st} but the answer is {status} under the probe's rule")
    out = {"id": it["id"], "type": it["type"], "status": status}
    if status == "completed":
        out["outcome"] = g["outcome"]
        if it.get("ambiguous") and g["outcome"] == "self_check":
            out["note"] = it["ambiguous"]
    return out


def summary(probe: dict, responses: list[dict]) -> dict:
    by = {}
    for r in responses:
        if r.get("schema") != RESPONSE or r.get("probe_id") != probe["probe_id"]:
            raise ValueError("every response must be flh_probe_response_v1 for this probe")
        if r["item"] in by:
            raise ValueError(f"two responses for {r['item']}")
        by[r["item"]] = r
    unknown = sorted(set(by) - {it["id"] for it in probe["items"]})
    if unknown:
        raise ValueError(f"responses for items not in the probe: {', '.join(unknown)}")
    rows = [score(it, by.get(it["id"])) for it in probe["items"]]
    groups = {}
    for t in list(TYPES) + ["all"]:
        rs = [r for r in rows if t == "all" or r["type"] == t]
        c = {k: sum(1 for r in rs if r["status"] == k) for k in ("completed", "revealed", "skipped", "unsupported", "missing")}
        o = {k: sum(1 for r in rs if r.get("outcome") == k) for k in ("correct", "incorrect", "self_check")}
        groups[t] = {"planned": len(rs), "observed": len(rs) - c["missing"], **c, **o,
                     "rates": {"correct_of_completed": f"{o['correct']}/{c['completed']}", "correct_of_planned": f"{o['correct']}/{len(rs)}",
                               "self_check_of_completed": f"{o['self_check']}/{c['completed']}"}}
    return {"schema": SUMMARY, "probe_id": probe["probe_id"], "rows": rows, "groups": groups,
            "definitions": DEFINITIONS,
            "rules": ["missing = planned with no response; it is never counted as wrong or as skipped",
                      "rates name their denominator; skipped, revealed, unsupported and missing are never in 'completed'",
                      "a self-check is not correct until the learner marks it; this summary does not guess"],
            "cannot_support": ["any claim about long-term retention: one session, no spacing schedule, no control condition",
                               "any comparison between learners or with a baseline", "anything about real learners: the responses here are synthetic"]}


def render_summary(s: dict) -> str:
    L = [f"Probe {s['probe_id']} summary (synthetic dry run; counts, not learning)", "",
         "| Outcome type | Planned | Observed | Completed | Correct | Incorrect | Self-check | Revealed | Skipped | Unsupported | Missing | Correct / completed | Correct / planned |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t, g in s["groups"].items():
        L.append(f"| {t} | {g['planned']} | {g['observed']} | {g['completed']} | {g['correct']} | {g['incorrect']} | {g['self_check']} | {g['revealed']} | "
                 f"{g['skipped']} | {g['unsupported']} | {g['missing']} | {g['rates']['correct_of_completed']} | {g['rates']['correct_of_planned']} |")
    L += ["", "Per item:"] + [f"- {r['id']} ({r['type']}): {r['status']}" + (f", {r['outcome']}" if r.get("outcome") else "")
                              + (f" — {r['note']}" if r.get("note") else "") for r in s["rows"]]
    L += ["", "Rules:"] + [f"- {x}" for x in s["rules"]] + ["", "This dry run cannot support:"] + [f"- {x}" for x in s["cannot_support"]]
    return "\n".join(L) + "\n"


def sheet(probe: dict) -> tuple[str, str]:
    """(the learner's sheet: prompts only, in the probe order; the key, to open after the probe)."""
    ids = order(probe)
    by = {it["id"]: it for it in probe["items"]}
    L = [f"# Delayed probe {probe['probe_id']} ({probe['delay']})", "",
         "Answer without your notes. Write « skip » to skip; you may ask to see an answer (it is recorded as revealed).", ""]
    K = [f"# Key for probe {probe['probe_id']} (open only after the probe)", ""]
    for n, i in enumerate(ids, 1):
        it = by[i]
        L.append(f"{n}. [{i}] {it['prompt']}" + (f"  ({' / '.join(it['options'])})" if it.get("options") else ""))
        K.append(f"{n}. [{i}] {it['type']}, difficulty {it.get('difficulty', '-')}: " + (it.get("answer") or "(self-check against the rule)")
                 + (f"; also accepted: {' | '.join(a for a in it.get('accepted', []) if a != it.get('answer'))}" if len(it.get("accepted", [])) > 1 else ""))
        if it.get("ambiguous"):
            K.append(f"   ambiguous: {it['ambiguous']}")
    return "\n".join(L) + "\n", "\n".join(K) + "\n"


def dry_run(probe: dict, responses: list[dict], expected: dict) -> tuple[dict, list[str]]:
    s = summary(probe, responses)
    diffs = [f"{t}.{k}: expected {v}, got {s['groups'][t][k]}" for t, exp in expected["groups"].items() for k, v in exp.items() if s["groups"][t][k] != v]
    return s, diffs




def _text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def default_corpus() -> dict:
    """The y/en sources and the shipped practice outputs: what a probe item must not repeat."""
    out = {}
    for p in sorted(glob.glob(os.path.join(FIX, "y_en.r*.json"))):
        with open(p, encoding="utf-8") as fh:
            out[os.path.basename(p)] = pr.source_text(json.load(fh))
    for p in sorted(glob.glob(os.path.join(FIX, "expected", "0[34]-*.txt"))):
        out["expected/" + os.path.basename(p)] = _text(p)
    return out


def default_study_packets() -> dict:
    """Every shipped study packet (2.0, 2.1, 2.2), JSON and Markdown."""
    pats = [("expected", "packet-study__*"), ("expected2", "0[67]-packet-*"), ("workbooks", "study-packet.*"), ("expected3", "0[58]-packet-*"),
            ("expected3", "11-packet-minimal.md")]
    return {os.path.relpath(p, FIX): _text(p) for d, g in pats for p in sorted(glob.glob(os.path.join(FIX, d, g)))}


def materials() -> tuple[dict, list[str]]:
    """The trial files (sheet, key, response template, dry-run summary, checks) and the dry run's differences."""
    with open(os.path.join(PROBE_DIR, "y_en_probe_v1.json"), encoding="utf-8") as fh:
        probe = json.load(fh)
    with open(os.path.join(PROBE_DIR, "responses-dry-run.json"), encoding="utf-8") as fh:
        responses = json.load(fh)["responses"]
    with open(os.path.join(PROBE_DIR, "expected-totals.json"), encoding="utf-8") as fh:
        expected = json.load(fh)
    sheet_md, key_md = sheet(probe)
    summ, dd = dry_run(probe, responses, expected)
    template = {"schema": "flh_probe_responses_v1", "probe_id": probe["probe_id"], "responses": [
        {"schema": RESPONSE, "probe_id": probe["probe_id"], "item": i, "status": "completed | revealed | skipped | unsupported", "text": ""}
        for i in order(probe)]}
    checks = {"novelty": novelty(probe, default_corpus()), "answers_in_study_packets": answers_in_packets(probe, default_study_packets()),
              "order": order(probe), "dry_run_differences": dd}
    files = {"probe-sheet.md": sheet_md, "probe-key.md": key_md, "responses-template.json": pr.dumps(template),
             "dry-run-summary.md": render_summary(summ), "probe-checks.json": pr.dumps(checks)}
    return files, dd


def trial(out: str, check: bool = False) -> tuple[int, str]:
    """Render the trial materials into ``out`` (new or empty); with ``check``, compare them with ``probe/expected/``."""
    if os.path.exists(out) and os.listdir(out):
        raise ValueError("--out must be a new or empty directory")
    files, dd = materials()
    os.makedirs(out, exist_ok=True)
    for n, t in files.items():
        with open(os.path.join(out, n), "w", encoding="utf-8") as fh:
            fh.write(t)
    checks = json.loads(files["probe-checks.json"])
    text = (f"trial materials: {', '.join(sorted(files))}; novel {checks['novelty']['all_novel']}; answers in study packets "
            f"{len(checks['answers_in_study_packets'])}; dry run vs hand-computed totals: {len(dd)} differences\n")
    if dd or not checks["novelty"]["all_novel"] or checks["answers_in_study_packets"]:
        return 1, text
    if check:
        bad = [n for n in sorted(files) if not os.path.exists(os.path.join(EXPECTED, n)) or _text(os.path.join(EXPECTED, n)) != files[n]]
        return (1, text + f"CHECK FAILED: {', '.join(bad)}\n") if bad else (0, text + "check: every file equals probe/expected/\n")
    return 0, text
