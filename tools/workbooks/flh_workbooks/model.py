"""Load the hand-written authoring modules and build the canonical workbook
JSON: displayed option order (balanced answer positions, no long runs),
status labels and provenance. Deterministic for a given seed."""

import importlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONTENT = ROOT / "content" / "workbooks"
AUTHORING = CONTENT / "authoring"
RL_PATH = CONTENT / "reading_listening_v1.json"
RL_MODULES = ("rl_units_01_03", "rl_units_04_06", "rl_units_07_09", "rl_units_10_12")
SEED = 20261110
MAX_RUN = 3
KEYS = "ABCDE"

STATUS = {
    "synthetic": True,
    "human_reviewed": False,
    "review_state": "unreviewed",
    "machine_review": ("structural quality gates and a machine critique pass by the authoring model "
                       "(self-review); not independent expert validation"),
    "levels": "A1–B1 bands are authoring targets, not certified CEFR levels",
    "official_exam": False,
}
PROVENANCE = {
    "authoring": ("hand-written in local Python authoring modules (content/workbooks/authoring) by "
                  "Claude Code (model claude-opus-5-5) on 2026-11-10; no provider or API generation call"),
    "generated_by_provider": False,
    "source_material": "original texts; places, people and organisations are fictional unless a notice says otherwise",
}


def load_units(modules):
    sys.path.insert(0, str(AUTHORING))
    try:
        units = []
        for name in modules:
            mod = importlib.import_module(name)
            units.extend(mod.UNITS)
        return units
    finally:
        sys.path.remove(str(AUTHORING))


def assign_positions(qs, rng):
    """Correct-answer index per question: balanced counts per option count,
    shuffled, then repaired so no answer letter repeats more than MAX_RUN
    times in a row (swaps stay within the same option count)."""
    pos = {}
    by_n = {}
    for q in qs:
        by_n.setdefault(len(q["distractors"]) + 1, []).append(q["id"])
    for n, ids in sorted(by_n.items()):
        p = [i % n for i in range(len(ids))]
        rng.shuffle(p)
        pos.update(zip(ids, p))
    order = [q["id"] for q in qs]
    nopt = {q["id"]: len(q["distractors"]) + 1 for q in qs}

    def run_at(i):
        k = i
        while k > 0 and pos[order[k - 1]] == pos[order[i]]:
            k -= 1
        return i - k + 1

    for _ in range(10 * len(order)):
        bad = next((i for i in range(len(order)) if run_at(i) > MAX_RUN), None)
        if bad is None:
            break
        cands = [j for j in range(len(order)) if j != bad and nopt[order[j]] == nopt[order[bad]]
                 and pos[order[j]] != pos[order[bad]]]
        rng.shuffle(cands)
        for j in cands:
            a, b = order[bad], order[j]
            pos[a], pos[b] = pos[b], pos[a]
            if all(run_at(i) <= MAX_RUN for i in {bad, j, max(bad - 1, 0), min(j + 1, len(order) - 1)}):
                break
            pos[a], pos[b] = pos[b], pos[a]
    return pos


def position_stats(questions):
    seq = [q["answer"] for q in questions if q["type"] == "single_choice"]
    run = best = 0
    prev = None
    for x in seq:
        run = run + 1 if x == prev else 1
        best = max(best, run)
        prev = x
    succ = sum(1 for a, b in zip(seq, seq[1:]) if KEYS.index(b) == (KEYS.index(a) + 1) % 3)
    return {"counts": dict(sorted(Counter(seq).items())), "max_run": best,
            "cyclic_successor_rate": round(succ / max(len(seq) - 1, 1), 3)}


def _question(q, pos, rng):
    out = {"id": q["id"], "type": q["type"], "kind": q["kind"], "stem": q["stem"]}
    if q["type"] == "single_choice":
        wrong = [dict(d) for d in q["distractors"]]
        rng.shuffle(wrong)
        opts = wrong[:]
        opts.insert(pos[q["id"]], {"text": q["correct"], "correct": True})
        out["options"] = []
        for k, o in zip(KEYS, opts):
            if o.get("correct"):
                out["options"].append({"key": k, "text": o["text"], "correct": True})
            else:
                out["options"].append({"key": k, "text": o["text"], "correct": False,
                                       "why_wrong_en": o["why_en"], "why_wrong_zh": o["why_zh"]})
        out["answer"] = KEYS[pos[q["id"]]]
    else:
        out["reference_answer"] = q["accepted"][0]
        out["accepted_alternatives"] = list(q["accepted"][1:])
    out["evidence"] = q["evidence"]
    out["explanation_en"] = q["explanation_en"]
    out["explanation_zh"] = q["explanation_zh"]
    return out


def build_rl(seed=SEED):
    units = load_units(RL_MODULES)
    rng = random.Random(seed)
    sc = [q for u in units for s in ("reading", "listening") for q in u[s]["questions"] if q["type"] == "single_choice"]
    pos = assign_positions(sc, rng)
    out_units = []
    for u in units:
        r, l = u["reading"], u["listening"]
        out_units.append({
            "id": u["id"], "theme": u["theme"], "band": u["band"], "goal": u["goal"],
            "prerequisites": u["prerequisites"],
            "reading": {"id": r["id"], "title": r["title"], "genre": r["genre"], "segments": r["segments"],
                        "questions": [_question(q, pos, rng) for q in r["questions"]]},
            "listening": {"id": l["id"], "title": l["title"], "genre": l["genre"], "format": "script",
                          "audio": None, "speakers": l["speakers"], "turns": l["turns"],
                          "questions": [_question(q, pos, rng) for q in l["questions"]]},
            "vocabulary": u["vocabulary"], "follow_up": u["follow_up"]})
    return {
        "schema_version": "flh_workbook_reading_listening_v1",
        "workbook_id": "flh-workbook-reading-listening-v1",
        "title": {"fr": "Comprendre : cahier de lecture et d'écoute (12 unités)",
                  "en": "Comprehension workbook: reading and listening (12 units)",
                  "zh": "理解练习册：阅读与听力（12个单元）"},
        "status": dict(STATUS, listening=("written scripts for reading aloud or recording; no audio exists, "
                                          "no timestamps, no listening-quality evidence")),
        "provenance": dict(PROVENANCE, build={"tool": "tools/workbooks (python3 -m flh_workbooks build)",
                                              "position_seed": seed, "max_answer_run": MAX_RUN}),
        "notices": {
            "fictional": ("Villeneuve-sur-Claire, the Café des Halles, the hotels, shops, clinics, schools and "
                          "people are fictional. Procedures and prices illustrate language and are not official guidance."),
            "telephone": "The telephone number in unit 10 uses a range reserved for fiction.",
            "real_reference": "Unit 12 cites 33700, the real French short number for forwarding fraudulent SMS.",
        },
        "units": out_units,
    }


def dumps(doc):
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def all_questions(doc):
    return [q for u in doc["units"] for s in ("reading", "listening") for q in u[s]["questions"]]


# ---- productive workbook (writing and speaking) ----

PW_PATH = CONTENT / "productive_v1.json"
PW_MODULES = ("pw_units_01_04", "pw_units_05_08", "pw_units_09_12")


def build_pw():
    from . import quality
    units = load_units(PW_MODULES)
    sys.path.insert(0, str(AUTHORING))
    try:
        rubric = importlib.import_module("pw_rubric")
    finally:
        sys.path.remove(str(AUTHORING))
    out = []
    for u in units:
        r = u["retry"]
        out.append(dict(u, retry=dict(r, corrected=quality.apply_corrections(r["draft"], r["corrections"]))))
    return {
        "schema_version": "flh_workbook_productive_v1",
        "workbook_id": "flh-workbook-productive-v1",
        "title": {"fr": "S'exprimer : cahier d'écriture et d'oral (12 unités)",
                  "en": "Expression workbook: writing and speaking (12 units)",
                  "zh": "表达练习册：写作与口语（12个单元）"},
        "status": dict(STATUS, samples="each sample is one possible answer, not the only correct answer",
                       scoring="no score, no level and no certified judgment; the rubric is for self-assessment"),
        "provenance": dict(PROVENANCE, build={"tool": "tools/workbooks (python3 -m flh_workbooks build)"}),
        "notices": {
            "fictional": ("People, the town hall, shops and hotels are fictional. Procedures illustrate language "
                          "and are not official guidance."),
            "telephone": "Telephone numbers use ranges reserved for fiction.",
            "real_reference": "Unit 12 cites 33700, the real French short number for forwarding fraudulent SMS.",
            "speaking": "Speaking tasks have no audio. Feedback on a transcript cannot judge pronunciation.",
        },
        "rubric": {"levels": rubric.LEVELS, "criteria": rubric.CRITERIA, "notice": rubric.NOTICE},
        "workflow": rubric.WORKFLOW,
        "units": out,
    }
