"""Local work directory, end-to-end demo and comparison for the practice prototype (PROTOTYPE, offline).

A work directory holds one learner's local records for one source. Nothing leaves it
unless an export writes a packet, after a preview and a privacy check:

  source.json  draft.json  drafts/rN.json   the source and its draft per revision (rebuildable)
  decisions.jsonl                            the learner's approve / reject / edit decisions (append-only)
  practice.json                              practice built from approved items (rebuildable)
  attempts.jsonl                             attempts and reveals (append-only)

``demo`` runs the documented sequence on the synthetic y/en source:
capture -> inspect evidence -> approve / reject / correct -> build practice -> answer ->
reveal -> export (study, tutor with rubrics) -> preview an agent's proposed corrections.
"""

from __future__ import annotations

import json
import os
import shutil

from . import packet as pk
from . import practice as pr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(HERE, "fixtures", "practice_v1")
PROMPTS = os.path.join(HERE, "practice_prompts")
FIXTURES = {
    "grammar_contrast": "y_en.r1.json", "revised_source": "y_en.r2.json",
    "ambiguous_evidence": "en_quantite.json", "valid_alternate_answer": "en_quantite.json",
}


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


def _append(path, rec):
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")


class Work:
    def __init__(self, path: str):
        self.path = path

    def p(self, name):
        return os.path.join(self.path, name)

    def init(self, source_path: str, with_review: bool = False) -> str:
        if os.path.exists(self.path) and os.listdir(self.path):
            raise ValueError("the work directory must be new or empty")
        src = _read(source_path)
        drf = pr.draft(src)
        _write(self.p("source.json"), pr.dumps(src))
        _write(self.p("draft.json"), pr.dumps(drf))
        _write(self.p(f"drafts/r{src['revision']}.json"), pr.dumps(drf))
        return pr.render_preview(self.resolved()) + (self.review_text() if with_review else "")

    def drafts(self) -> dict:
        d = self.p("drafts")
        return {int(f[1:-5]): _read(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.startswith("r") and f.endswith(".json")} \
            if os.path.isdir(d) else {}

    def review(self) -> dict:
        return pr.batch_review(self.resolved(), self.drafts())

    def review_text(self) -> str:
        return "\n" + pr.render_review(self.review())

    def approve_batch(self, batch_id: str, except_ids=(), reason: str = "") -> list[dict]:
        seq = max([d["seq"] for d in self.decisions()] + [0]) + 1
        ds = pr.batch_decisions(self.draft(), self.resolved(), batch_id, seq, except_ids, reason)
        for d in ds:
            _append(self.p("decisions.jsonl"), d)
        return ds

    def accept(self, packet: dict, ret: dict, proposal_id: str, reason: str = "") -> dict:
        target, text, via = pk.accept_correction(packet, ret, proposal_id, self.resolved())
        return self.decide(target, "edit", text, reason or f"accepted {via['agent']} proposal {proposal_id}", via=via)

    def revise(self, source_path: str, with_review: bool = False) -> str:
        old, src = _read(self.p("source.json")), _read(source_path)
        if src.get("source_id") != old["source_id"] or not isinstance(src.get("revision"), int) or src["revision"] <= old["revision"]:
            raise ValueError("a revision must keep the source_id and raise the revision number")
        drf = pr.draft(src)
        _write(self.p("source.json"), pr.dumps(src))
        _write(self.p("draft.json"), pr.dumps(drf))
        _write(self.p(f"drafts/r{src['revision']}.json"), pr.dumps(drf))
        if os.path.exists(self.p("practice.json")):
            os.remove(self.p("practice.json"))  # rebuilt from the new resolution on demand
        return pr.render_preview(self.resolved()) + (self.review_text() if with_review else "")

    def draft(self):
        return _read(self.p("draft.json"))

    def decisions(self):
        with open(self.p("decisions.jsonl"), encoding="utf-8") if os.path.exists(self.p("decisions.jsonl")) else open(os.devnull) as fh:
            return pr.read_decisions(fh)

    def resolved(self):
        return pr.resolve(self.draft(), self.decisions())

    def decide(self, item_id, action, text=None, reason="", via=None):
        seq = max([d["seq"] for d in self.decisions()] + [0]) + 1
        d = pr.decision(self.draft(), item_id, action, seq, text, reason, via=via)
        _append(self.p("decisions.jsonl"), d)
        return d

    def practice(self, rebuild=False):
        if rebuild or not os.path.exists(self.p("practice.json")):
            prac = pr.build_practice(self.resolved())
            _write(self.p("practice.json"), pr.dumps(prac))
        return _read(self.p("practice.json"))

    def attempts(self):
        return _jsonl(self.p("attempts.jsonl"))

    def answer(self, practice_id, text=None, reveal=False):
        seq = max([a["seq"] for a in self.attempts()] + [0]) + 1
        rec, fb = pr.attempt(self.practice(), practice_id, seq, text, reveal)
        _append(self.p("attempts.jsonl"), rec)
        return pr.render_feedback(fb)

    def export(self, mode="study", include_rubrics=False, version=2, previous=None):
        return pk.export(self.resolved(), self.practice(), self.attempts(), mode, include_rubrics, version=version, previous=previous)


def write_packet(packet: dict, out: str) -> list[str]:
    """packet.json, packet.md and the two documented prompts, into a new or empty directory."""
    if os.path.exists(out) and os.listdir(out):
        raise ValueError("the packet directory must be new or empty")
    _write(os.path.join(out, "packet.json"), pr.dumps(packet))
    _write(os.path.join(out, "packet.md"), pk.markdown(packet))
    for f in ("PROMPT-codex.md", "PROMPT-claude-code.md"):
        shutil.copyfile(os.path.join(PROMPTS, f), os.path.join(out, f))
    return sorted(os.listdir(out))


DEMO_SCRIPT = [  # the synthetic learner's actions on y_en.r1.json, by proposal ref
    ("en-mouvement", "reject", None, "my friend corrected exactly this: « j'en vais » is wrong"),
    ("y-a", "edit", "« y » replaces where you go or where you are (à la boulangerie, chez Paul, dans le parc): « Oui, j'y vais. »",
     "the rule is wider than « à »"),
    ("en-de", "approve", None, ""), ("y-vs-en", "approve", None, ""), ("en-vais", "approve", None, ""),
    ("ex-piscine", "approve", None, ""), ("ex-marche", "approve", None, ""),
]
DEMO_ANSWERS = [  # (kind, proposal ref of the worked example or contrast, answer or None for reveal)
    ("explain", "y-vs-en", "y for à + a place, en for de + a place"),
    ("choose", "ex-piscine", "y"), ("produce", "ex-piscine", "Oui, on y va !"),
    ("produce", "ex-marche", "Oui, j'y reviens."), ("choose", "ex-marche", None),
]


def _ids_by_ref(drf):
    return {i["proposal_ref"]: i["item_id"] for i in drf["items"]}


def _practice_id(prac, kind, item_id):
    return next(p["practice_id"] for p in prac["items"] if p["kind"] == kind and p["knowledge_ids"][0] == item_id)


def demo(out: str, check: bool = False) -> tuple[int, str]:
    if os.path.exists(out) and os.listdir(out):
        raise ValueError("--out must be a new or empty directory")
    w = Work(os.path.join(out, "work"))
    files, log = {}, []
    src = _read(os.path.join(FIX, "y_en.r1.json"))
    files["00-capture.json"] = pr.dumps(src["capture"])
    log.append(f"1 capture      {src['capture']['capture_id']} ({src['capture']['source']}): {src['capture']['original_input']}")
    files["01-draft-preview.txt"] = w.init(os.path.join(FIX, "y_en.r1.json"))
    drf = w.draft()
    log.append(f"2 inspect      draft {drf['draft_id']}: " + ", ".join(f"{k} {v}" for k, v in drf["counts"].items() if v))
    ids = _ids_by_ref(drf)
    for ref, action, text, reason in DEMO_SCRIPT:
        w.decide(ids[ref], action, text, reason)
    res = w.resolved()
    files["02-decided-preview.txt"] = pr.render_preview(res)
    rej = next(i for i in res["items"] if i["proposal_ref"] == "en-mouvement")
    log.append(f"3 decide       rejected {rej['item_id']} (support {rej['support']}); corrected {ids['y-a']}; "
               + ", ".join(f"{k} {v}" for k, v in res["states"].items() if v))
    prac = w.practice(rebuild=True)
    files["03-practice.txt"] = pr.render_practice(prac)
    log.append("4 practice     " + ", ".join(f"{k} {v}" for k, v in prac["counts"].items())
               + f"; new-sentence items {sum(1 for p in prac['items'] if p['new_sentence'])}")
    fb = []
    for kind, ref, ans in DEMO_ANSWERS:
        pid = _practice_id(prac, kind, ids[ref])
        fb.append(w.answer(pid, ans, reveal=ans is None))
    files["04-attempts.txt"] = "\n".join(fb)
    log.append("5 answer       " + ", ".join(f"{a['practice_id']} {a['outcome']}" for a in w.attempts()))
    study = w.export("study", version=1)  # this demo pins packet v1 so its outputs stay those of HANDOFF-136
    tutor = w.export("tutor", include_rubrics=True, version=1)
    files["05-export-preview-study.txt"] = pk.preview(study)
    files["05-export-preview-tutor.txt"] = pk.preview(tutor)
    write_packet(study, os.path.join(out, "packet-study"))
    write_packet(tutor, os.path.join(out, "packet-tutor"))
    log.append(f"6 export       study {study['packet_id']} ({len(study['next_exercises'])} exercises, no answer keys); "
               f"tutor {tutor['packet_id']} (rubrics by explicit choice)")
    ret = _read(os.path.join(FIX, "agent_return.json"))
    rep = pk.import_preview(study, ret)
    files["06-agent-return-preview.txt"] = pk.render_import(rep)
    log.append("7 agent return " + ", ".join(f"{k} {v}" for k, v in rep["counts"].items()) + " (read-only)")
    files["07-workbooks-feed.json"] = pr.dumps(pk.workbooks_feed(prac, w.attempts()))
    files["demo.txt"] = "Extraction 2.0 practice demo (synthetic y/en source; PROTOTYPE)\n" + "\n".join(log) + "\n"
    for name, body in files.items():
        _write(os.path.join(out, name), body)
    text = files["demo.txt"]
    if not check:
        return 0, text
    bad = []
    exp = os.path.join(FIX, "expected")
    for name in sorted(files) + ["packet-study/packet.json", "packet-study/packet.md", "packet-tutor/packet.json", "packet-tutor/packet.md"]:
        with open(os.path.join(out, name), encoding="utf-8") as a, open(os.path.join(exp, name.replace("/", "__")), encoding="utf-8") as b:
            if a.read() != b.read():
                bad.append(name)
    return (1, text + f"CHECK FAILED: {', '.join(bad)}\n") if bad else (0, text + "check: every output equals the shipped expected file\n")


EXISTING_STEPS = [  # documented user actions in the current FLH path, capture -> first recall question (docs/ARCHITECTURE.md)
    "import the capture (POST /captures)", "enable and run an extraction (POST /entries/{id}/extractions; provider call)",
    "review admission (active / suppressed)", "resolve the unit to a Concept (SAME or NEW CONCEPT)",
    "open the Concept in the Knowledge Library", "start Recall Practice and pick questions",
]


def compare() -> dict:
    """The prototype next to the existing extraction review, on every shipped fixture."""
    rows = []
    for name in ("y_en.r1.json", "y_en.r2.json", "en_quantite.json"):
        src = _read(os.path.join(FIX, name))
        drf = pr.draft(src)
        claims = [i for i in drf["items"] if i["type"] == "claim"]
        script = [(i["item_id"], "approve") for i in drf["items"] if i["support"] in ("supported", "generated")]
        res = pr.resolve(drf, [pr.decision(drf, iid, a, k + 1) for k, (iid, a) in enumerate(script)])
        prac = pr.build_practice(res)
        heur = {}
        for c in claims:
            heur[c["heuristic_class"]] = heur.get(c["heuristic_class"], 0) + 1
        rows.append({
            "fixture": name, "claims": len(claims),
            "new_flow": {"supported": sum(c["support"] == "supported" for c in claims), "uncertain": sum(c["support"] in ("uncertain", "no_evidence") for c in claims),
                         "unsupported": sum(c["support"] == "unsupported" for c in claims),
                         "exercises": len(prac["items"]), "exercises_tied_to_evidence": sum(1 for p in prac["items"] if p["evidence_ids"]),
                         "new_sentence_exercises": sum(1 for p in prac["items"] if p["new_sentence"]),
                         "steps_capture_to_first_practice": 2 + len(script) + 1,
                         "steps_basis": "init (capture + draft), preview, one decision per approved item, build practice"},
            "existing_extraction": {"evidence_review_classes": dict(sorted(heur.items())), "exercises": 0, "exercises_tied_to_evidence": 0,
                                    "steps_capture_to_first_practice": len(EXISTING_STEPS),
                                    "steps_basis": "documented path: " + "; ".join(EXISTING_STEPS)},
        })
    return {"schema": "flh_practice_comparison_v1", "rows": rows,
            "notes": ["claims are compared on the same proposal: exact quote grounding (new) vs lexical anchoring (evidence_review)",
                      "existing exercises are 0 because Recall Practice questions are built in the browser from unit statements and stored nowhere",
                      "step counts are documented user actions, not timed use; the approvals here approve every supported or generated item"]}


def render_compare(rep: dict) -> str:
    L = ["Prototype vs existing extraction review (synthetic fixtures; counts, not quality judgments)"]
    for r in rep["rows"]:
        n, e = r["new_flow"], r["existing_extraction"]
        L += [f"{r['fixture']}: {r['claims']} proposed claims",
              f"  new flow   supported {n['supported']}, uncertain {n['uncertain']}, unsupported {n['unsupported']}; exercises {n['exercises']} "
              f"({n['exercises_tied_to_evidence']} tied to evidence, {n['new_sentence_exercises']} in a new sentence); steps to first practice {n['steps_capture_to_first_practice']}",
              f"  existing   evidence-review classes {e['evidence_review_classes']}; exercises {e['exercises']}; steps to first practice {e['steps_capture_to_first_practice']}"]
    L += [f"note: {x}" for x in rep["notes"]]
    return "\n".join(L) + "\n"
