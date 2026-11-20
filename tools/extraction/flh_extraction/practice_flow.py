"""Extraction 2.1 (PROTOTYPE, offline, standard library only): a shorter path to the first
practice, a second contrast, switching agents with one packet, and a sealed Workbooks feed.

* ``measure`` runs the HANDOFF-136 flow (one decision per item) and the 2.1 flow (the
  review shown by ``init`` and one batch approval) on the same source, and counts the
  commands each needs from capture to the first practice. It checks that both approve
  the same items, build the same practice, and keep the same evidence links. It also checks
  that every flagged item is left to the learner and is named in the review.
* ``pipeline`` is the worked example:
  - session 1 with Codex on a study packet;
  - the learner reviews and accepts one correction (a duplicate is refused);
  - a later miss;
  - session 2 with Claude Code on an updated packet: the same knowledge IDs, the accepted
    correction, the last confusion and the next exercise.
  It also writes the Workbooks bundle: feeds for two sources, a revised source, attempt
  examples and three test cases, sealed with SHA256SUMS.
* ``demo2`` runs it all and, with ``check``, compares every output with the shipped files.

No agent, provider or network is called: the two agent returns are hand-written fixtures.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

from . import packet as pk
from . import practice as pr
from .practice_workflow import FIX, Work, _read, _write, write_packet

EXP2 = os.path.join(FIX, "expected2")
BUNDLE = os.path.join(FIX, "workbooks")
SWITCH = os.path.join(FIX, "switch")
STEPS_SCHEMA = "flh_practice_steps_v1"
BUNDLE_SCHEMA = "flh_practice_workbooks_bundle_v1"
SOURCES = {"y-en-demo": "y_en.r1.json", "savoir-connaitre-demo": "savoir_connaitre.json"}


def _ids(drf: dict) -> dict:
    return {i["proposal_ref"]: i["item_id"] for i in drf["items"]}


def _pid(prac: dict, kind: str, item_id: str) -> str:
    return next(p["practice_id"] for p in prac["items"] if p["kind"] == kind and p["knowledge_ids"][0] == item_id)


def _bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _same_dir(a: str, b: str) -> list[str]:
    """Names that differ between two flat directories (missing on one side or different bytes)."""
    return [n for n in sorted(set(os.listdir(a)) | set(os.listdir(b)))
            if not (os.path.isfile(os.path.join(a, n)) and os.path.isfile(os.path.join(b, n))) or _bytes(os.path.join(a, n)) != _bytes(os.path.join(b, n))]


def _sha_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


# ---- before / after (same learner intent: approve every supported item and practice example) ----

def flow_before(src_path: str, work: str) -> tuple[list[str], Work]:
    """The HANDOFF-136 path: init, preview, one decision per approved item, build."""
    w, steps = Work(work), []
    w.init(src_path)
    steps.append("practice init --source S --work W")
    pr.render_preview(w.resolved())
    steps.append("practice preview --work W")
    for i in w.draft()["items"]:
        if i["support"] in pr.BATCH_SUPPORT:
            w.decide(i["item_id"], "approve")
            steps.append(f"practice decide --work W --item {i['item_id']} --approve")
    w.practice(rebuild=True)
    steps.append("practice build --work W")
    return steps, w


def flow_after(src_path: str, work: str) -> tuple[list[str], Work, str]:
    """The 2.1 path: init shows the draft beside its evidence and the review; one batch approval; build."""
    w, steps = Work(work), []
    shown = w.init(src_path, with_review=True)
    steps.append("practice init --source S --work W   (draft beside its evidence, then the review)")
    bid = w.review()["batch_id"]
    w.approve_batch(bid)
    steps.append(f"practice decide --work W --approve-batch {bid}")
    w.practice(rebuild=True)
    steps.append("practice build --work W")
    return steps, w, shown


def _links(w: Work) -> dict:
    return {p["practice_id"]: p["evidence_ids"] for p in w.practice()["items"]}


def _left_section(text: str) -> str:
    return text.split("Decide yourself, one by one", 1)[1].split("Already decided", 1)[0] if "Decide yourself, one by one" in text else ""


def measure_one(src_path: str, root: str) -> tuple[dict, str]:
    sb, wb = flow_before(src_path, os.path.join(root, "before"))
    sa, wa, shown = flow_after(src_path, os.path.join(root, "after"))
    rb, ra = wb.resolved(), wa.resolved()
    appr_b = sorted(i["item_id"] for i in pr.approved(rb))
    appr_a = sorted(i["item_id"] for i in pr.approved(ra))
    left = [r["item_id"] for r in wa.review()["left_for_you"]]
    section = _left_section(shown)
    da, db = wa.decisions(), wb.decisions()
    row = {
        "source_id": rb["source"]["source_id"], "revision": rb["source"]["revision"],
        "before": {"steps": len(sb), "commands": sb, "decision_records": len(db)},
        "after": {"steps": len(sa), "commands": sa, "decision_records": len(da),
                  "batch_ids": sorted({d["batch"]["batch_id"] for d in da if d.get("batch")})},
        "same_approved_items": appr_b == appr_a, "approved_items": len(appr_a),
        "same_practice_ids": sorted(_links(wb)) == sorted(_links(wa)), "practice_items": len(_links(wa)),
        "same_evidence_links": _links(wb) == _links(wa),
        "exercises_tied_to_evidence": sum(1 for v in _links(wa).values() if v),
        "one_learner_decision_per_approved_item": len(da) == len(appr_a) and len(db) == len(appr_b),
        "left_for_learner": left, "left_named_in_review": all(i in section for i in left),
        "left_still_pending": all(next(x for x in ra["items"] if x["item_id"] == i)["state"] == "pending" for i in left),
    }
    return row, shown


def measure_revision(root: str, r2_path: str) -> tuple[dict, str]:
    """After both flows reached their first practice on revision 1: the steps to practise again on revision 2."""
    out, shown = {}, ""
    for name in ("before", "after"):
        w, steps = Work(os.path.join(root, name)), []
        text = w.revise(r2_path, with_review=name == "after")
        steps.append("practice revise --source S2 --work W" + ("   (draft beside its evidence, then the review)" if name == "after" else ""))
        if name == "before":
            pr.render_preview(w.resolved())
            steps.append("practice preview --work W")
        else:
            shown = text
        rv = w.review()
        if name == "after" and rv["batch_id"]:
            w.approve_batch(rv["batch_id"])
            steps.append(f"practice decide --work W --approve-batch {rv['batch_id']}")
        for r in rv["left_for_you"]:
            if r["state"] == "needs_review":  # the learner re-reads the changed evidence and approves again
                w.decide(r["item_id"], "approve", reason="re-read after the revision")
                steps.append(f"practice decide --work W --item {r['item_id']} --approve")
        w.practice(rebuild=True)
        steps.append("practice build --work W")
        out[name] = {"steps": len(steps), "commands": steps, "practice_ids": sorted(_links(w))}
    changed = [r["item_id"] for r in Work(os.path.join(root, "after")).review()["left_for_you"] if r["state"] == "needs_review"]
    return {"source_id": "y-en-demo", "revision": 2, "before": {k: out["before"][k] for k in ("steps", "commands")},
            "after": {k: out["after"][k] for k in ("steps", "commands")},
            "changed_items_decided_one_by_one": len([c for c in out["after"]["commands"] if "--item" in c]),
            "still_needing_review_after": changed,
            "same_practice_ids_as_revision_1": out["after"]["practice_ids"] == out["before"]["practice_ids"],
            "note": "changed items are never batched: each needs the learner's own decision, so only the preview step is saved"}, shown


def measure(root: str) -> tuple[dict, dict]:
    """(report, texts shown to the learner). ``root`` must be new or empty."""
    if os.path.exists(root) and os.listdir(root):
        raise ValueError("the measure directory must be new or empty")
    rows, shown = [], {}
    for sid, f in SOURCES.items():
        row, text = measure_one(os.path.join(FIX, f), os.path.join(root, sid))
        rows.append(row)
        shown[sid] = text
    rev, shown["y-en-demo-r2"] = measure_revision(os.path.join(root, "y-en-demo"), os.path.join(FIX, "y_en.r2.json"))
    rows.append(rev)
    return {"schema": STEPS_SCHEMA, "rows": rows,
            "basis": "commands the learner runs from capture to the first practice, executed here, not timed use; the same "
                     "intent in both flows (approve every supported item and new practice example, leave the rest)"}, shown


def render_measure(rep: dict) -> str:
    L = ["Steps from capture to first practice: before (HANDOFF-136) vs after (Extraction 2.1)", ""]
    for r in rep["rows"]:
        L.append(f"{r['source_id']} revision {r['revision']}: before {r['before']['steps']} steps, after {r['after']['steps']} steps")
        for k in ("before", "after"):
            L += [f"  {k:6} {i}. {c}" for i, c in enumerate(r[k]["commands"], 1)]
        if "same_approved_items" in r:
            L.append(f"  same approved items {r['same_approved_items']} ({r['approved_items']}); same practice IDs {r['same_practice_ids']} "
                     f"({r['practice_items']}); same evidence links {r['same_evidence_links']}; exercises tied to evidence {r['exercises_tied_to_evidence']}")
            L.append(f"  one learner decision per approved item {r['one_learner_decision_per_approved_item']}; batch {', '.join(r['after']['batch_ids'])}")
            L.append(f"  left for the learner {', '.join(r['left_for_learner']) or 'none'}: named in the review {r['left_named_in_review']}, "
                     f"still pending {r['left_still_pending']}")
        else:
            L.append(f"  changed items decided one by one {r['changed_items_decided_one_by_one']}; same practice IDs as revision 1 "
                     f"{r['same_practice_ids_as_revision_1']}; {r['note']}")
        L.append("")
    L.append(f"basis: {rep['basis']}")
    return "\n".join(L) + "\n"


# ---- the worked example: two agents, one packet, a learner in between; plus the Workbooks bundle ----

def answer_keys(prac: dict, shared: str) -> tuple[list[str], list[str]]:
    """(forbidden, allowed) strings for a packet without answers: produce answers and accepted variants,
    and the choose/produce explanations; a key that is also shared knowledge text is allowed, and listed."""
    keys = set()
    for p in prac["items"]:
        h = p["hidden"]
        if p["kind"] == "produce":
            keys |= {h["answer"], *h["accepted"]}
        if p["kind"] in ("choose", "produce"):
            keys.add(h["explanation"])
    allowed = sorted(k for k in keys if k in shared)
    return sorted(keys - set(allowed)), allowed


def pipeline(out: str) -> tuple[dict, list[str]]:
    """Run the 2.1 worked example into ``out`` (new or empty). Returns (files to compare, log lines)."""
    if os.path.exists(out) and os.listdir(out):
        raise ValueError("--out must be a new or empty directory")
    files, log, b = {}, [], {}
    # 1. y/en: the short path, then the learner rejects the flagged claim
    w = Work(os.path.join(out, "work-y-en"))
    files["02-init-review-y-en-r1.txt"] = w.init(os.path.join(FIX, "y_en.r1.json"), with_review=True)
    ids = _ids(w.draft())
    rv = w.review()
    w.approve_batch(rv["batch_id"])
    w.decide(ids["en-mouvement"], "reject", reason="spotted in the review: that quote is not in my text")
    log.append(f"1 y/en          init + review; batch {rv['batch_id']} approved ({len(rv['members'])} items); "
               f"flagged {ids['en-mouvement']} rejected; {', '.join(f'{k} {v}' for k, v in w.resolved()['states'].items() if v)}")
    prac = w.practice(rebuild=True)
    w.answer(_pid(prac, "choose", ids["ex-piscine"]), "y")
    feed_before_accept = pr.dumps(pk.workbooks_feed(w.practice(), w.attempts()))
    # 2. session 1 with Codex
    p1 = w.export("study")
    write_packet(p1, os.path.join(out, "session-1-codex"))
    files["06-packet-1-codex.json"], files["06-packet-1-codex.md"] = pr.dumps(p1), pk.markdown(p1)
    ret1 = _read(os.path.join(SWITCH, "codex-return.json"))
    rep1 = pk.import_preview(p1, ret1)
    files["05-codex-return-preview.txt"] = pk.render_import(rep1)
    log.append(f"2 session 1     packet {p1['packet_id']} ({p1['schema']}, study) -> Codex return (fixture): "
               + ", ".join(f"{k} {v}" for k, v in rep1["counts"].items() if v))
    d = w.accept(p1, ret1, "c1")
    refusals = []
    for pid in ("c2", "c1"):
        try:
            w.accept(p1, ret1, pid)
            refusals.append(f"{pid}: ACCEPTED (unexpected)")
        except ValueError as e:
            refusals.append(f"{pid}: refused ({e})")
    prac = w.practice(rebuild=True)
    feed_after_accept = pr.dumps(pk.workbooks_feed(prac, w.attempts()))
    log.append(f"3 learner       accepted c1 -> decision {d['seq']} edit {d['item_id']} via {d['via']['agent']} {d['via']['proposal_id']}; "
               + "; ".join(refusals))
    # 3. a later miss
    w.answer(_pid(prac, "produce", ids["ex-marche"]), "Oui, j'y reviens.")
    last_a = w.attempts()[-1]
    log.append(f"4 practice      {last_a['practice_id']} {last_a['outcome']} (known error matched; the text stays local)")
    # 4. session 2 with Claude Code
    p2 = w.export("study", previous=p1)
    write_packet(p2, os.path.join(out, "session-2-claude-code"))
    files["07-packet-2-claude-code.json"], files["07-packet-2-claude-code.md"] = pr.dumps(p2), pk.markdown(p2)
    ret2 = _read(os.path.join(SWITCH, "claude-code-return.json"))
    rep2 = pk.import_preview(p2, ret2)
    files["08-claude-code-return-preview.txt"] = pk.render_import(rep2)
    k1, k2 = {k["id"] for k in p1["knowledge"]}, {k["id"] for k in p2["knowledge"]}
    target = next(k for k in p2["knowledge"] if k["id"] == d["item_id"])
    keys, allowed = answer_keys(prac, pr.dumps(p2) + pk.markdown(p2))
    leaked = [k for k in keys if k in pr.dumps(p2) or k in pk.markdown(p2)]
    checks = {
        "same_knowledge_ids": k1 == k2, "knowledge_ids": len(k2),
        "accepted_correction_in_packet": target["text"] == d["text"] and target.get("accepted_from", {}).get("proposal_id") == "c1",
        "continuity_names_the_change": [c["id"] for c in p2["continuity"]["changed"]] == [d["item_id"]],
        "last_confusion": f"{' vs '.join(p2['last_confusion']['forms'])} on {p2['last_confusion']['practice_id']}",
        "next_exercise": f"{p2['next_exercise']['id']} {p2['next_exercise']['kind']}",
        "answer_keys_in_study_packet": len(leaked), "answer_keys_checked": len(keys),
        "claude_code_conflicts_with_the_accepted_correction": any(r["class"] == "conflict" and r.get("target_id") == d["item_id"] for r in rep2["rows"]),
    }
    log.append(f"5 session 2     packet {p2['packet_id']} continues {p1['packet_id']}: same knowledge IDs {checks['same_knowledge_ids']} "
               f"({checks['knowledge_ids']}); accepted correction present {checks['accepted_correction_in_packet']}; "
               f"last confusion {checks['last_confusion']}; next exercise {checks['next_exercise']}; "
               f"answer keys in the study packet {checks['answer_keys_in_study_packet']} of {checks['answer_keys_checked']} checked")
    log.append("6 Claude Code   return (fixture), read-only: " + ", ".join(f"{k} {v}" for k, v in rep2["counts"].items() if v)
               + f"; it cannot silently replace the accepted correction: {checks['claude_code_conflicts_with_the_accepted_correction']}")
    files["05-switch.json"] = pr.dumps({"schema": "flh_practice_switch_v1", "packet_1": p1["packet_id"], "packet_2": p2["packet_id"],
                                        "accepted": {"proposal_id": "c1", "decision_seq": d["seq"], "item_id": d["item_id"]},
                                        "refused": refusals, "checks": checks})
    # 5. Workbooks bundle: feeds, a revised source, attempt examples and three cases
    bdir = os.path.join(out, "workbooks")
    w.answer(_pid(prac, "explain", ids["y-vs-en"]), "y with à, en with de")
    w.answer(_pid(prac, "produce", ids["ex-piscine"]), "Oui, on y va !")
    w.answer(_pid(prac, "choose", ids["ex-marche"]), None, reveal=True)
    b["feed-y-en-demo-r1.json"] = feed1 = pk.workbooks_feed(w.practice(), w.attempts())
    files["04-revise-review-y-en-r2.txt"] = w.revise(os.path.join(FIX, "y_en.r2.json"), with_review=True)
    b["feed-y-en-demo-r2.json"] = feed2 = pk.workbooks_feed(w.practice(rebuild=True), w.attempts(), previous=feed1)
    for r in w.review()["left_for_you"]:
        if r["state"] == "needs_review":
            w.decide(r["item_id"], "approve", reason="re-read after the revision")
    b["feed-y-en-demo-r2-reapproved.json"] = feed3 = pk.workbooks_feed(w.practice(rebuild=True), w.attempts(), previous=feed2)
    log.append(f"7 revision 2    feed r1 {len(feed1['items'])} items -> r2 {len(feed2['items'])} items, {len(feed2['withdrawn'])} withdrawn -> "
               f"re-approved {len(feed3['items'])} items, same practice IDs as r1 "
               f"{sorted(p['practice_id'] for p in feed3['items']) == sorted(p['practice_id'] for p in feed1['items'])}")
    w2 = Work(os.path.join(out, "work-savoir-connaitre"))
    files["03-init-review-savoir-connaitre-r1.txt"] = w2.init(os.path.join(FIX, "savoir_connaitre.json"), with_review=True)
    ids2 = _ids(w2.draft())
    w2.approve_batch(w2.review()["batch_id"])
    w2.decide(ids2["savoir-personnes"], "reject", reason="spotted in the review: not in my text")
    prac2 = w2.practice(rebuild=True)
    for kind, ref, ans in (("choose", "ex-frere", "connais"), ("choose", "ex-nager", "conait"), ("produce", "ex-nager", "Oui, je connais nager."),
                           ("produce", "ex-frere", "Oui, je le connais bien."), ("explain", "savoir-vs-connaitre", None)):
        w2.answer(_pid(prac2, kind, ids2[ref]), ans, reveal=ans is None)
    b["feed-savoir-connaitre-demo-r1.json"] = feed4 = pk.workbooks_feed(prac2, w2.attempts())
    outs = sorted({o["outcome"] for f in (feed1, feed4) for p in f["items"] for o in p["outcomes"]})
    log.append(f"8 savoir/conn.  {len(feed4['items'])} items; attempt outcomes across both feeds: {', '.join(outs)}")
    cases = {
        "changed-source": {"case": "changed_source", "feeds": ["feed-y-en-demo-r1.json", "feed-y-en-demo-r2.json", "feed-y-en-demo-r2-reapproved.json"],
                           "expect": {"source_id": "y-en-demo", "revisions": [1, 2, 2], "revision_sha256_changes_between": ["feed-y-en-demo-r1.json", "feed-y-en-demo-r2.json"],
                                      "r2_items": 0, "r2_withdrawn": sorted(p["practice_id"] for p in feed1["items"]),
                                      "reapproved_practice_ids_equal_r1": True,
                                      "workbooks_should": ["stop offering a withdrawn practice_id; keep its history",
                                                           "offer it again when a later feed lists the same practice_id",
                                                           "never infer a schedule from the feed"]}},
        "duplicate-correction": {"case": "duplicate_correction", "packet": "duplicate-correction-packet.json", "proposals": "duplicate-correction-proposals.json",
                                 "preview": "duplicate-correction-preview.json",
                                 "expect": {"classes": {r["proposal_id"]: r["class"] for r in rep1["rows"]}, "learner_accepts": "c1",
                                            "refused": refusals, "feed_sha256_before_accept": _sha_text(feed_before_accept),
                                            "feed_sha256_after_accept": _sha_text(feed_after_accept),
                                            "feed_unchanged_by_the_correction": feed_before_accept == feed_after_accept,
                                            "workbooks_should": ["see no new or changed practice_id because of a correction: practice IDs hash the knowledge ID and the kind"]}},
        "study-packet-without-answers": {"case": "study_packet_without_answers", "packet": "study-packet.json", "markdown": "study-packet.md",
                                         "expect": {"mode": "study", "rubrics_included": False, "forbidden_strings": keys,
                                                    "allowed_overlaps": allowed, "forbidden_found": leaked}},
    }
    b["cases.json"] = {"schema": BUNDLE_SCHEMA + "/cases", "cases": cases}
    b["duplicate-correction-packet.json"] = p1
    b["duplicate-correction-proposals.json"] = ret1
    b["duplicate-correction-preview.json"] = rep1
    b["study-packet.json"] = p2
    feeds = [n for n in sorted(b) if n.startswith("feed-")]
    b["MANIFEST.json"] = {
        "schema": BUNDLE_SCHEMA, "synthetic": True,
        "producer": "extraction lane prototype (owner of the practice-content contract)", "consumer": "workbooks lane (read-only)",
        "feed_schema": pk.FEED_SCHEMA, "packet_schema": pk.PACKET_SCHEMA_V2,
        "feeds": [{"file": n, "source_id": b[n]["source"]["source_id"], "revision": b[n]["source"]["revision"],
                   "revision_sha256": b[n]["source"]["revision_sha256"],
                   "practice_ids": {p["practice_id"]: p["kind"] for p in b[n]["items"]},
                   "withdrawn": [x["practice_id"] for x in b[n].get("withdrawn", [])]} for n in feeds],
        "exercise_kinds": ["explain", "choose", "produce"], "attempt_outcomes": ["correct", "incorrect", "self_check", "revealed", "invalid"],
        "outcomes_present": outs,
        "id_rules": {"practice_id": "p- + 12 hex of SHA-256(knowledge ID, kind): stable across revisions and corrections",
                     "knowledge_id": "k- + 12 hex of SHA-256(source ID, type, content key): never hashes the revision",
                     "evidence_id": "ev- + 10 hex of SHA-256(source ID, field, quote, occurrence)"},
        "never_in_a_feed": ["due dates, intervals or schedules", "answer keys", "attempt texts"],
        "verify": "python3 verify.py   (standard library only; exit 0 when the seal and every case hold)"}
    os.makedirs(bdir, exist_ok=True)
    for n, obj in b.items():
        _write(os.path.join(bdir, n), pr.dumps(obj))
    _write(os.path.join(bdir, "study-packet.md"), pk.markdown(p2))
    for n in ("README.md", "verify.py"):
        shutil.copyfile(os.path.join(BUNDLE, n), os.path.join(bdir, n))
    _write(os.path.join(bdir, "SHA256SUMS"), seal(bdir))
    return files, log


def seal(d: str) -> str:
    rows = []
    for n in sorted(os.listdir(d)):
        if n != "SHA256SUMS":
            with open(os.path.join(d, n), "rb") as fh:
                rows.append(f"{hashlib.sha256(fh.read()).hexdigest()}  {n}\n")
    return "".join(rows)


def run_verify(d: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-I", "-B", os.path.join(d, "verify.py"), d], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


def workbooks_bundle(out: str, check: bool = False) -> tuple[int, str]:
    """Regenerate the sealed Workbooks bundle into ``out`` (new or empty); with ``check``, compare it with the shipped one."""
    if os.path.exists(out) and os.listdir(out):
        raise ValueError("--out must be a new or empty directory")
    with tempfile.TemporaryDirectory() as tmp:
        pipeline(os.path.join(tmp, "run"))
        shutil.copytree(os.path.join(tmp, "run", "workbooks"), out, dirs_exist_ok=True)
    rc, text = run_verify(out)
    if check:
        bad = _same_dir(out, BUNDLE)
        if bad:
            return 1, text + f"CHECK FAILED: differs from the shipped bundle: {', '.join(bad)}\n"
        text += "check: the regenerated bundle equals the shipped one byte for byte\n"
    return rc, text


def demo2(out: str, check: bool = False) -> tuple[int, str]:
    if os.path.exists(out) and os.listdir(out):
        raise ValueError("--out must be a new or empty directory")
    rep, shown = measure(os.path.join(out, "measure"))
    files = {"01-steps.json": pr.dumps(rep), "01-steps.txt": render_measure(rep)}
    more, log = pipeline(os.path.join(out, "run"))
    files.update(more)
    head = [f"0 measure       " + "; ".join(f"{r['source_id']} r{r['revision']}: {r['before']['steps']} -> {r['after']['steps']} steps" for r in rep["rows"])]
    files["demo2.txt"] = "Extraction 2.1 demo (synthetic y/en and savoir/connaître; PROTOTYPE)\n" + "\n".join(head + log) + "\n"
    for name, body in files.items():
        _write(os.path.join(out, name), body)
    rc, vtext = run_verify(os.path.join(out, "run", "workbooks"))
    text = files["demo2.txt"] + f"workbooks bundle verify: exit {rc}\n"
    if not check:
        return rc, text
    bad = []
    for name in sorted(files):
        with open(os.path.join(out, name), encoding="utf-8") as a, open(os.path.join(EXP2, name), encoding="utf-8") as e:
            if a.read() != e.read():
                bad.append(name)
    bad += ["workbooks/" + n for n in _same_dir(os.path.join(out, "run", "workbooks"), BUNDLE)]
    if rc:
        bad.append("workbooks verify: " + vtext.strip().splitlines()[-1])
    if bad:
        return 1, text + f"CHECK FAILED: {', '.join(bad)}\n"
    return 0, text + f"check: every output equals the shipped expected file ({len(files)} files and the {len(os.listdir(BUNDLE))}-file Workbooks bundle)\n"
