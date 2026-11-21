"""Cross-subject slice: source → evidence → recall, replayed from an empty directory (offline, synthetic).

  python3 -I -B scripts/xsubject.py --out EMPTY_DIR     # run it; EMPTY_DIR/result/ holds the outputs
  python3 -I -B scripts/xsubject.py --check             # run in a fresh temporary directory, compare with fixtures/xsubject_v1/expected/
  python3 -I -B scripts/xsubject.py --write             # (re)write fixtures/xsubject_v1/expected/

The slice runs each pinned source through the normal learner workflow:
1. the ``practice2`` CLI, as a learner's session would run it (init, review, approve the proposed
   batch, build) in its own work directory;
2. the attempt-first learning loop on one choose item (recall, reveal, read, retry);
3. the unit export (``units export``) and the independent span check (``units inspect``).

The music-theory source (English) is the subject under test. The y/en source (French) is the
compatibility control: same commands, same approval rule. Its draft must keep the ID it has
had since Extraction 2.2.

``result/parity.json`` compares the two runs. ``SHA256SUMS`` seals ``result/``. Nothing in
``result/`` holds a path, a time or a random value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from flh_extraction import loop as lp  # noqa: E402
from flh_extraction import practice as pr  # noqa: E402
from flh_extraction import practice22 as p22  # noqa: E402
from flh_extraction import unit_handoff as uh  # noqa: E402
from flh_extraction import units as un  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "xsubject_v1")
EXPECTED = os.path.join(FIX, "expected")
SOURCES = {
    "music": {"path": os.path.join(FIX, "sources", "music_thirds.r1.json"),
              "sha256": "508b5e30be0c40db6100e1cf27ce05cbaf57786868c477173acb483b702d0ec0",
              "loop": {"wrong": "minor triad", "right": "major triad"}},
    "french": {"path": os.path.join(HERE, "fixtures", "practice_v1", "y_en.r1.json"),
               "sha256": None, "draft_id": "d-22ff0c49f9d7", "loop": {"wrong": "y", "right": "en"}},
    "chemistry": {"path": os.path.join(FIX, "sources", "chem_water_states.v2.json"), "v2": True,
                  "sha256": "93dfe7ae904b13c13ef22f40369eaa8b4fea67f0e6ccbcbb4c0c5c5ab753698f", "loop": None},
}


def _bytes(p: str) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()


def cli(work_parent: str, *args) -> str:
    r = subprocess.run([sys.executable, "-B", "-m", "flh_extraction", *args], cwd=HERE, capture_output=True, text=True,
                       env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    if r.returncode:
        raise SystemExit(f"{args[0]} {args[1] if len(args) > 1 else ''} failed: {r.stderr.strip()[-400:]}")
    return r.stdout


def run_one(name: str, spec: dict, out: str) -> dict:
    src_path = spec["path"]
    if spec.get("sha256") and hashlib.sha256(_bytes(src_path)).hexdigest() != spec["sha256"]:
        raise SystemExit(f"{name}: the pinned source changed (it is frozen; a change is a new fixture)")
    w = os.path.join(out, f"work-{name}")
    res_dir = os.path.join(out, "result", name)
    os.makedirs(res_dir)
    declared = None
    if spec.get("v2"):
        with open(src_path, encoding="utf-8") as fh:
            declared = {it["ref"]: it.get("evidence", []) for it in json.load(fh)["proposal"]["items"]}
        v1_path = os.path.join(out, f"{name}.v1.json")
        r = subprocess.run([sys.executable, "-B", "-m", "flh_extraction.units", "convert", "--source", src_path, "--out", v1_path, "--strict"],
                           cwd=HERE, capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        if r.returncode:
            raise SystemExit(f"units convert failed: {r.stderr[-300:]}")
        src_path = v1_path
    cli(out, "practice2", "init", "--source", src_path, "--work", w)
    plan_path = os.path.join(out, f"plan-{name}.json")
    cli(out, "practice2", "review", "--work", w, "--json", plan_path)
    with open(plan_path, encoding="utf-8") as fh:
        plan = json.load(fh)
    cli(out, "practice2", "decide", "--work", w, "--approve-batch", plan["batch_id"])
    practice_text = cli(out, "practice2", "build", "--work", w)
    work = p22.Work2(w)
    res, prac, srcs = work.resolved(), work.practice(), work.sources()
    loop, steps = None, []
    if spec["loop"]:
        pid = next(p["practice_id"] for p in prac["items"] if p["kind"] == "choose")
        loop = lp.start(res, prac, pid, session=f"xsubject-{name}")
        steps = [lp.next_step(loop)]
        loop = lp.recall(loop, prac, spec["loop"]["wrong"])
        loop = lp.reveal(loop, prac, srcs)
        loop = lp.read(loop, res, srcs)
        loop = lp.retry(loop, prac, spec["loop"]["right"])
    units_path = os.path.join(res_dir, "units.json")
    r = subprocess.run([sys.executable, "-B", "-m", "flh_extraction.units", "export", "--work", w, "--out", units_path], cwd=HERE,
                       capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    if r.returncode:
        raise SystemExit(f"units export failed: {r.stderr[-300:]}")
    r = subprocess.run([sys.executable, "-B", "-m", "flh_extraction.units", "inspect", "--units", units_path, "--source", src_path,
                        "--md", os.path.join(res_dir, "inspect.md")], cwd=HERE, capture_output=True, text=True,
                       env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    inspect_ok = r.returncode == 0
    with open(units_path, encoding="utf-8") as fh:
        units = json.load(fh)
    with open(src_path, encoding="utf-8") as fh:
        src = json.load(fh)
    if loop is not None:
        with open(os.path.join(res_dir, "loop.json"), "w", encoding="utf-8") as fh:
            fh.write(pr.dumps(loop))
    with open(os.path.join(res_dir, "practice.txt"), "w", encoding="utf-8") as fh:
        fh.write(practice_text)
    with open(os.path.join(res_dir, "batch-plan.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps({k: plan[k] for k in ("batch_id", "selected", "left_for_you")}))
    authored = {i["ref"]: i for i in src["proposal"]["items"]}
    same_as_authored = all(u["proposed_text"] == authored[u["proposal_ref"]][pr.MAIN_TEXT[u["type"]]] for u in units["units"])
    original_kept = all(pr.fold(src["capture"][e["field"]])[e["start"]:e["end"]] == e["quote"]
                        for u in units["units"] for e in u["evidence"] if "start" in e)
    return {"name": name, "subject": units["source"]["subject"], "language": units["source"]["language"],
            "draft_id": units["source"]["draft_id"], "fingerprint": units["source"]["fingerprint"], "run_key": units["source"]["run_key"],
            "units": units["counts"]["units"], "usable": units["counts"]["usable"], "needs_review": units["counts"]["needs_review"],
            "recall": units["counts"]["recall"], "recall_refused": len(units["recall_refused"]), "practice": prac["counts"],
            "loop_order": steps + [e["event"] for e in loop["events"]] if loop else ["none: no contrast, so no practice item"],
            "loop_retrieval": [e.get("retrieval") for e in loop["events"] if "retrieval" in e] if loop else [],
            "loop_valid": (lp.validate(loop) == []) if loop else None, "spans_verified": inspect_ok, "units_equal_authored_text": same_as_authored,
            "original_text_spans_exact": original_kept, "unit_keys": sorted(set.intersection(*(set(u) for u in units["units"])) - set(un.OPTIONAL_UNIT_KEYS)), "doc_keys": sorted(units),
            "declared_spans_kept": None if declared is None else all(
                sorted((e["field"], e["start"], e["end"]) for e in u["evidence"] if "start" in e) == sorted((d["field"], d["start"], d["end"]) for d in declared[u["proposal_ref"]])
                for u in units["units"]),
            "extensions_kept": units["source"]["extensions"] == (src.get("extensions") or {}), "validate": un.validate_units(units)}


INBOX_SOURCES = [os.path.join(FIX, "sources", f"music_intervals_inbox.r{r}.json") for r in (1, 2)]


def units_cli(*args) -> None:
    r = subprocess.run([sys.executable, "-B", "-m", "flh_extraction.units", *args], cwd=HERE, capture_output=True, text=True,
                       env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    if r.returncode:
        raise SystemExit(f"units {args[0]} failed: {r.stderr[-300:]}")


def run_inbox(out: str) -> dict:
    """Review states and reasons through the CLI: approve the batch, reject the self-contradicting claim, revise,
    rerun identically (revision 3 = revision 2's content) and compare."""
    w = os.path.join(out, "work-inbox")
    res_dir = os.path.join(out, "result", "inbox")
    os.makedirs(res_dir)
    cli(out, "practice2", "init", "--source", INBOX_SOURCES[0], "--work", w)
    plan_path = os.path.join(out, "plan-inbox.json")
    cli(out, "practice2", "review", "--work", w, "--json", plan_path)
    with open(plan_path, encoding="utf-8") as fh:
        plan = json.load(fh)
    cli(out, "practice2", "decide", "--work", w, "--approve-batch", plan["batch_id"])
    ids = {i["proposal_ref"]: i["item_id"] for i in p22.Work2(w).resolved()["items"]}
    cli(out, "practice2", "decide", "--work", w, "--item", ids["tritone-wrong"], "--reject", "--reason", "seven semitones is a fifth, not a tritone")
    units_cli("export", "--work", w, "--out", os.path.join(res_dir, "units-r1.json"))
    units_cli("inbox", "--units", os.path.join(res_dir, "units-r1.json"), "--out", os.path.join(res_dir, "inbox-r1.json"))
    cli(out, "practice2", "revise", "--source", INBOX_SOURCES[1], "--work", w)
    units_cli("export", "--work", w, "--out", os.path.join(res_dir, "units-r2.json"))
    units_cli("inbox", "--units", os.path.join(res_dir, "units-r2.json"), "--out", os.path.join(res_dir, "inbox-r2.json"))
    with open(INBOX_SOURCES[1], encoding="utf-8") as fh:
        r3 = json.load(fh)
    r3["revision"] = 3
    r3_path = os.path.join(out, "music_intervals_inbox.r3-rerun.json")
    with open(r3_path, "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(r3))
    cli(out, "practice2", "revise", "--source", r3_path, "--work", w)
    units_cli("export", "--work", w, "--out", os.path.join(res_dir, "units-r3-rerun.json"))
    units_cli("compare", "--old", os.path.join(res_dir, "units-r1.json"), "--new", os.path.join(res_dir, "units-r2.json"),
              "--json", os.path.join(res_dir, "compare-r1-r2.json"))
    units_cli("compare", "--old", os.path.join(res_dir, "units-r2.json"), "--new", os.path.join(res_dir, "units-r3-rerun.json"),
              "--json", os.path.join(res_dir, "compare-r2-r3-rerun.json"))
    def load(n):
        with open(os.path.join(res_dir, n), encoding="utf-8") as fh:
            return json.load(fh)
    u2, u3, c23 = load("units-r2.json"), load("units-r3-rerun.json"), load("compare-r2-r3-rerun.json")
    i1, i2 = load("inbox-r1.json"), load("inbox-r2.json")
    st = lambda d: {u["proposal_ref"]: u["state"] for u in d["units"]}  # noqa: E731
    return {"reason_codes_r1": sorted(i1["reason_counts"]), "reason_codes_r2": sorted(i2["reason_counts"]),
            "rejected_listed_apart": [r["unit_id"] for r in i1["rejected"]] == [ids["tritone-wrong"]],
            "changed_after_revision": [u["proposal_ref"] for u in u2["units"] if any(r["code"] == "changed_since_decision" for r in u["review_reasons"])],
            "identical_rerun": c23["identical_rerun"], "rerun_states_equal": st(u2) == st(u3),
            "rerun_unit_ids_equal": [u["unit_id"] for u in u2["units"]] == [u["unit_id"] for u in u3["units"]],
            "inbox_privacy_findings": i1["privacy_findings"] + i2["privacy_findings"],
            "multi_span_units": sorted(u["proposal_ref"] for u in u2["units"] if len(u["evidence"]) > 1),
            "overlaps": [o["relation"] for o in u2["span_overlaps"]]}


REVISIONS = [os.path.join(FIX, "sources", f"music_thirds.r{r}.json") for r in (1, 2, 3)]


def run_revisions(out: str) -> dict:
    """EXT-031 to 040: identical rerun, prose edit, changed claim, moved, added and removed evidence, a kept rejection,
    an ambiguous duplicate, a deterministic diff, and a vanished source told apart from a failed extraction."""
    w = os.path.join(out, "work-revisions")
    res_dir = os.path.join(out, "result", "revisions")
    os.makedirs(res_dir)
    exp = lambda n: units_cli("export", "--work", w, "--out", os.path.join(res_dir, n))  # noqa: E731
    cli(out, "practice2", "init", "--source", REVISIONS[0], "--work", w)
    plan_path = os.path.join(out, "plan-revisions.json")
    cli(out, "practice2", "review", "--work", w, "--json", plan_path)
    with open(plan_path, encoding="utf-8") as fh:
        cli(out, "practice2", "decide", "--work", w, "--approve-batch", json.load(fh)["batch_id"])
    exp("units-r1.json")
    cli(out, "practice2", "revise", "--source", REVISIONS[1], "--work", w)
    exp("units-r2-before-decisions.json")
    ids = {i["proposal_ref"]: i["item_id"] for i in p22.Work2(w).resolved()["items"]}
    cli(out, "practice2", "decide", "--work", w, "--item", ids["major-third"], "--approve", "--reason", "same rule, clearer words")
    cli(out, "practice2", "decide", "--work", w, "--item", ids["minor-third"], "--reject", "--reason", "my notes say three semitones")
    exp("units-r2.json")
    cli(out, "practice2", "revise", "--source", REVISIONS[2], "--work", w)
    exp("units-r3.json")
    for a, b in (("r1", "r2-before-decisions"), ("r2", "r3")):
        units_cli("compare", "--old", os.path.join(res_dir, f"units-{a}.json"), "--new", os.path.join(res_dir, f"units-{b}.json"),
                  "--json", os.path.join(res_dir, f"compare-{a}-to-{b}.json"))

    def load(n):
        with open(os.path.join(res_dir, n), encoding="utf-8") as fh:
            return json.load(fh)
    u3 = load("units-r3.json")
    with open(REVISIONS[2], encoding="utf-8") as fh:
        r3 = json.load(fh)
    gone = json.loads(json.dumps(r3))
    gone["capture"]["original_context"] = "Lesson four, Tuesday evening. The notes from this lesson were lost."
    shuffled = json.loads(json.dumps(u3))
    shuffled["units"].reverse()
    for u in shuffled["units"]:
        u["evidence"].reverse()
    statuses = {"identical_rerun": un.rerun_status(u3, r3, u3), "extractor_failed_empty": un.rerun_status(u3, r3, {"units": []}),
                "extractor_failed_error": un.rerun_status(u3, r3, None, "provider timeout"),
                "source_missing": un.rerun_status(u3, None), "source_text_replaced": un.rerun_status(u3, gone, None)}
    with open(os.path.join(res_dir, "rerun-statuses.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(statuses))
    c12, c23 = load("compare-r1-to-r2-before-decisions.json"), load("compare-r2-to-r3.json")
    st3 = {u["proposal_ref"]: u["state"] for u in u3["units"]}
    return {"r1_r2_same_text": c12["same_text"], "r1_r2_changes": c12["counts"],
            "prose_edit_keeps_claim_key": any(r["change"] == "prose_edit" for r in c12["claims"]),
            "changed_claim_same_source": c12["same_text"] and c12["counts"]["added"] >= 1 and c12["counts"]["removed"] >= 1,
            "r2_r3_evidence": {k: len(v) for k, v in c23["evidence"].items()}, "moved_keep_keys": len(c23["evidence"]["moved"]) > 0,
            "rejected_kept_in_r3": st3.get("minor-third") == "rejected" and bool(c23["rejected_kept"]),
            "ambiguous_duplicates_r3": len(u3["ambiguous_duplicates"]), "diff_deterministic": un.compare(load("units-r2.json"), u3) == c23
            and un.compare(load("units-r2.json"), shuffled)["counts"] == c23["counts"],
            "rerun_statuses": {k: v["status"] for k, v in statuses.items()}}


FORUM = os.path.join(FIX, "sources", "music_thirds_forum.r1.json")


def run_recall_review(out: str) -> dict:
    """EXT-043 to 048: a correction path from a prompt to its source, source links through the feed, review after a
    revision, and a contradictory source pair with both evidence trails."""
    res_dir = os.path.join(out, "result", "recall")
    os.makedirs(res_dir)
    w = os.path.join(out, "work-music")

    def load(p):
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    u = load(os.path.join(out, "result", "music", "units.json"))
    rid = next(r["recall_id"] for r in u["recall"] if r["kind"] == "free_recall" and "major" in r["prompt"])
    path = un.correction_path(u, rid)
    cli(out, "practice2", "decide", "--work", w, "--item", path["unit_id"], "--edit",
        "A major third spans four semitones (two whole tones), for example C to E.", "--reason", "my teacher added the whole tones")
    units_cli("export", "--work", w, "--out", os.path.join(res_dir, "units-after-correction.json"))
    after = load(os.path.join(res_dir, "units-after-correction.json"))
    fixed = next(x for x in after["units"] if x["unit_id"] == path["unit_id"])
    cli(out, "practice2", "feed", "--work", w, "--out", os.path.join(res_dir, "feed.json"), "--seq", "1")
    feed = load(os.path.join(res_dir, "feed.json"))
    ev = {e["evidence_id"]: e for x in after["units"] for e in x["evidence"]}
    links = [{"practice_id": i["practice_id"], "recall_type": i.get("recall_type"), "evidence": [[e, ev[e]["field"], ev[e]["start"], ev[e]["end"]] for e in i["evidence_ids"]]}
             for i in feed["items"]]
    # review after a source revision: a loop started on revision 1, revisited after revision 3
    wr = p22.Work2(os.path.join(out, "work-revisions"))
    rv3, pr3, s3 = wr.resolved(), wr.practice(rebuild=True), wr.sources()
    with tempfile.TemporaryDirectory() as t:
        w1 = p22.Work2(os.path.join(t, "w1"))
        w1.init(REVISIONS[0], with_review=False)
        w1.approve_batch(w1.plan()["batch_id"])
        rv1, pr1, s1 = w1.resolved(), w1.practice(rebuild=True), w1.sources()
    pid = next(p["practice_id"] for p in pr1["items"] if p["kind"] == "choose")
    loop = lp.reveal(lp.recall(lp.start(rv1, pr1, pid, session="xsubject-revisit"), pr1, "minor triad"), pr1, s1)
    loop = lp.revisit(loop, rv3, pr3, {**s1, **s3})
    with open(os.path.join(res_dir, "loop-revisit-r3.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(loop))
    with open(os.path.join(res_dir, "correction-path.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(path))
    cw = os.path.join(out, "work-forum")
    cli(out, "practice2", "init", "--source", FORUM, "--work", cw)
    cli(out, "practice2", "review", "--work", cw, "--json", os.path.join(out, "plan-forum.json"))
    cli(out, "practice2", "decide", "--work", cw, "--approve-batch", load(os.path.join(out, "plan-forum.json"))["batch_id"])
    units_cli("export", "--work", cw, "--out", os.path.join(res_dir, "units-forum.json"))
    con = un.contradictions([u, load(os.path.join(res_dir, "units-forum.json"))])
    with open(os.path.join(res_dir, "contradictions.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps({"schema": "flh_unit_contradictions_v1", "contradictions": con}))
    os.makedirs(os.path.join(out, "result", "vocabulary"))
    with open(os.path.join(out, "result", "vocabulary", "terms-music-thirds.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(un.vocabulary_reference(u)))
    rv = loop["events"][-1]
    return {"correction": {"state": fixed["state"], "evidence_unchanged": fixed["evidence"] == next(x for x in u["units"] if x["unit_id"] == path["unit_id"])["evidence"],
                           "recall_prompt_after": next((r["prompt"] for r in after["recall"] if r["unit_id"] == path["unit_id"] and r["kind"] == "free_recall"), None)},
            "feed_items": len(links), "feed_links_resolve": all(e[2] is not None for x in links for e in x["evidence"]),
            "recall_links": all(r["source_link"]["fingerprint"] == u["source"]["fingerprint"] for r in u["recall"]),
            "revisit_r3": {"units": [x["status"] for x in rv["units"]], "evidence": [x["status"] for x in rv["evidence_status"]], "can_practise": rv["can_practise"]},
            "contradictions": [{"topic": c["topic"], "values": c["values"], "sources": [x["source_id"] for x in c["sides"]]} for c in con]}


def standin_agent(md: str, h: dict, src: dict) -> dict:
    """A scripted local stand-in (no model, no credentials): it reads only the Markdown and answers two questions.
    It pins the first occurrence of an ambiguous quote, and offers a span for the unsupported claim that does not
    hold (so the follow-up refuses it)."""
    import re as _re
    qs = _re.findall(r"^- (q-[0-9a-f]{10}) \(([a-z_:]+)\) about « (.*?) »", md, _re.M)
    text = pr.fold(src["capture"]["original_context"])
    ans = []
    for qid, reason, about in qs:
        if reason == "uncertain_evidence":
            q = "A perfect fifth is stable."
            i = text.index(q)
            ans.append({"question_id": qid, "span": {"field": "original_context", "start": i, "end": i + len(q), "quote": q},
                        "rationale": "the first sentence about stability, in your interval notes"})
        elif reason == "unsupported_claim":
            ans.append({"question_id": qid, "span": {"field": "original_context", "start": 0, "end": 15, "quote": "A major sixth s"},
                        "rationale": "stand-in: a span that does not hold"})
    return {"schema": uh.FOLLOWUP, "handoff_id": h["handoff_id"], "agent": "codex", "answers": ans}


def run_handoff(out: str) -> dict:
    """EXT-061 to 070: handoff of the inbox units (revision 2), both agent formats, citations, a follow-up revision."""
    res_dir = os.path.join(out, "result", "handoff")
    os.makedirs(res_dir)
    with open(os.path.join(out, "result", "inbox", "units-r2.json"), encoding="utf-8") as fh:
        u2 = json.load(fh)
    with open(INBOX_SOURCES[1], encoding="utf-8") as fh:
        src2 = json.load(fh)
    h = uh.export(u2, src2)
    with open(os.path.join(res_dir, "handoff.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(h))
    md = {a: uh.markdown(h, a) for a in ("claude-code", "codex")}
    for a, t in md.items():
        with open(os.path.join(res_dir, f"handoff.{a}.md"), "w", encoding="utf-8") as fh:
            fh.write(t)
    ret = standin_agent(md["codex"], h, src2)
    new, refused = uh.followup(h, src2, ret)
    with open(os.path.join(res_dir, "followup-codex.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(ret))
    r3_path = os.path.join(out, "inbox.r3-followup.json")
    with open(r3_path, "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(new))
    w = os.path.join(out, "work-handoff")
    cli(out, "practice2", "init", "--source", INBOX_SOURCES[0], "--work", w)
    cli(out, "practice2", "review", "--work", w, "--json", os.path.join(out, "plan-handoff.json"))
    with open(os.path.join(out, "plan-handoff.json"), encoding="utf-8") as fh:
        cli(out, "practice2", "decide", "--work", w, "--approve-batch", json.load(fh)["batch_id"])
    cli(out, "practice2", "revise", "--source", INBOX_SOURCES[1], "--work", w)
    units_cli("export", "--work", w, "--out", os.path.join(res_dir, "units-r2.json"))
    cli(out, "practice2", "revise", "--source", r3_path, "--work", w)
    units_cli("export", "--work", w, "--out", os.path.join(res_dir, "units-r3-followup.json"))
    units_cli("compare", "--old", os.path.join(res_dir, "units-r2.json"), "--new", os.path.join(res_dir, "units-r3-followup.json"),
              "--json", os.path.join(res_dir, "compare-r2-r3-followup.json"))
    with open(os.path.join(res_dir, "units-r3-followup.json"), encoding="utf-8") as fh:
        u3 = json.load(fh)
    ev_id = h["reviewed_claims"][0]["evidence"][0]["evidence_id"]
    ek = h["reviewed_claims"][0]["evidence"][0]["evidence_key"]
    citations = [uh.cite(h, src2, ev_id), uh.cite(h, src2, ek)]
    with open(os.path.join(res_dir, "citations.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps({"citations": citations, "refused_followup_answers": refused}))
    stable = {x["proposal_ref"]: x for x in u3["units"]}
    try:
        uh.export(u2, src2, include_source_text=True)
        private_refused = None
    except un.UnitError as e:
        private_refused = str(e)
    priv = json.loads(json.dumps(src2))
    priv_units = json.loads(json.dumps(u2))
    priv_units["source"]["data_scope"] = "private"
    try:
        uh.export(priv_units, priv, include_source_text=True)
        private_text = "EXPORTED"
    except un.UnitError:
        private_text = "refused"
    return {"handoff_id": h["handoff_id"], "reviewed_claims": len(h["reviewed_claims"]), "questions": len(h["unresolved"]),
            "questions_have_next_action": all(q["next_action"]["command"] for q in h["unresolved"]),
            "markdown_bodies_identical": md["claude-code"].split("\n", 1)[1] == md["codex"].split("\n", 1)[1],
            "source_text_by_default": h["source_text_included"], "synthetic_with_text_opt_in": private_refused is None,
            "private_text_refused": private_text == "refused",
            "citations_verified": all(c["verified"] for c in citations),
            "followup": {"answers": len(ret["answers"]), "refused": [r["code"] for r in refused],
                         "fifth_stable_after": stable["fifth-stable"]["support"], "revision": u3["source"]["revision"]}}


INJECTION = os.path.join(FIX, "sources", "music_quoted_instructions.r1.json")


def run_privacy(out: str) -> dict:
    """EXT-081 to 086: instructions in the source stay data, contact details never leave, private scope stays local,
    and a failed optional step leaves the local output intact."""
    res_dir = os.path.join(out, "result", "privacy")
    os.makedirs(res_dir)
    w = os.path.join(out, "work-injection")
    cli(out, "practice2", "init", "--source", INJECTION, "--work", w)
    cli(out, "practice2", "review", "--work", w, "--json", os.path.join(out, "plan-injection.json"))
    with open(os.path.join(out, "plan-injection.json"), encoding="utf-8") as fh:
        cli(out, "practice2", "decide", "--work", w, "--approve-batch", json.load(fh)["batch_id"])
    up = os.path.join(res_dir, "units.json")
    units_cli("export", "--work", w, "--out", up)
    units_cli("inbox", "--units", up, "--out", os.path.join(res_dir, "inbox.json"))
    with open(up, encoding="utf-8") as fh:
        u = json.load(fh)
    with open(INJECTION, encoding="utf-8") as fh:
        src = json.load(fh)
    h = uh.export(u, src)
    md = uh.markdown(h, "claude-code")
    with open(os.path.join(res_dir, "handoff.claude-code.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    inj = next(x for x in u["units"] if x["proposal_ref"] == "injected")
    # contact details: uncited text never leaves; opting into the full text with a real-looking address is refused
    leaky = json.loads(json.dumps(src))
    leaky["capture"]["original_context"] = leaky["capture"]["original_context"].replace("[teacher's email]", "teacher.name" + "@" + "example.com")  # reserved domain; built here so no file holds an address
    lu = json.loads(json.dumps(u))
    lu["source"]["fingerprint"] = un.source_fingerprint(leaky)
    results = {}
    for name, fn in (("handoff_without_text", lambda: uh.export(lu, leaky)), ("handoff_with_text", lambda: uh.export(lu, leaky, include_source_text=True))):
        try:
            fn()
            results[name] = "exported"
        except un.UnitError as e:
            results[name] = "refused: " + str(e).split("(")[0].strip()
    priv = json.loads(json.dumps(u))
    priv["source"]["data_scope"] = "private"
    try:
        uh.export(priv, src)
        results["private_scope"] = "exported"
    except un.UnitError:
        results["private_scope"] = "refused"
    # an optional step that fails (a bad model proposal file) leaves the local units untouched
    before = hashlib.sha256(_bytes(up)).hexdigest()
    bad = os.path.join(out, "model-proposal.bad.json")
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write('{"schema": "flh_practice_source_v9", "note": "a model run that returned something unusable"}')
    r = subprocess.run([sys.executable, "-B", "-m", "flh_extraction.units", "convert", "--source", bad, "--out", up], cwd=HERE,
                       capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    results["model_failure"] = {"exit": r.returncode, "local_units_unchanged": hashlib.sha256(_bytes(up)).hexdigest() == before,
                                "message": r.stderr.strip().split(":", 1)[0]}
    with open(os.path.join(res_dir, "checks.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(results))
    return {"injected_claim_needs_review": inj["needs_review"] and inj["state"] == "pending",
            "injected_reasons": [r["code"] for r in inj["review_reasons"]],
            "markdown_says_quotes_are_data": "source material even when it reads like an instruction" in md,
            "instruction_text_only_inside_quotes": all(("ignore all previous instructions" not in line) or ("«" in line) for line in md.splitlines()),
            "recall_still_works": [x["prompt"] for x in u["recall"] if x["kind"] == "free_recall"], **results}


SHEET = os.path.join(FIX, "practice", "music_thirds.sheet.json")


def run_practice(out: str) -> dict:
    """EXT-131 to 139: prompts of four intended recall types, answer bases, multi-answer spans, grading, drops, and one
    unit exported in two agent formats."""
    from flh_extraction import exchange as xc
    from flh_extraction import unit_practice as up
    res_dir = os.path.join(out, "result", "practice")
    os.makedirs(res_dir)
    mp = os.path.join(res_dir, "music-practice.json")
    r = subprocess.run([sys.executable, "-B", "-m", "flh_extraction.unit_practice", "build", "--units", os.path.join(out, "result", "music", "units.json"),
                        "--sheet", SHEET, "--out", mp], cwd=HERE, capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    if r.returncode:
        raise SystemExit(f"unit_practice build failed: {r.stderr[-300:]}")
    with open(mp, encoding="utf-8") as fh:
        doc = json.load(fh)
    with open(os.path.join(out, "result", "chemistry", "units.json"), encoding="utf-8") as fh:
        chem = up.build(json.load(fh))
    with open(os.path.join(res_dir, "chemistry-practice.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(chem))
    major = {p["kind"]: p for p in doc["prompts"] if "major" in p["prompt"] or p.get("claim_key") == next(
        x["claim_key"] for x in doc["prompts"] if "major third spans" in x["prompt"])}
    samples = {"free_recall": ["4", "Four.", "four semitones", "4 semitones", "five", "C to E"], "recognition": ["four", "three"],
               "application": ["major third", "A major third.", "a minor third"], "explanation": ["Four semitones up from the root, like C to E or G to B."]}
    graded = [{"prompt_id": major[k]["prompt_id"], "kind": k, "answer": a, **{x: v for x, v in up.grade(major[k], a).items() if x in ("outcome", "chosen")}}
              for k, answers in samples.items() for a in answers]
    with open(os.path.join(res_dir, "graded-examples.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps({"schema": "flh_unit_practice_graded_examples_v1", "practice": "music-practice.json", "examples": graded}))
    wm = p22.Work2(os.path.join(out, "work-music"))
    rv1, pr1, s1 = wm.resolved(), wm.practice(), wm.sources()
    pid = next(p["practice_id"] for p in pr1["items"] if p["kind"] == "choose")
    ctx = xc.export(rv1, pr1, s1, pid)
    with open(os.path.join(out, "result", "music", "units.json"), encoding="utf-8") as fh:
        mu = json.load(fh)
    with open(SOURCES["music"]["path"], encoding="utf-8") as fh:
        msrc = json.load(fh)
    h = uh.export(mu, msrc)
    ctx_ev = {u["unit_id"]: sorted(e["evidence_id"] for e in ctx["evidence"] if e["evidence_id"] in
                                   {x["evidence_id"] for x in next(z for z in mu["units"] if z["unit_id"] == u["unit_id"])["evidence"]})
              for u in ctx["units"]}
    h_ev = {c["unit_id"]: sorted(e["evidence_id"] for e in c["evidence"]) for c in h["reviewed_claims"] if c["unit_id"] in ctx_ev}
    two = {"unit_ids": sorted(ctx_ev), "agent_context_v1": ctx["context_id"], "unit_handoff_v1": h["handoff_id"], "evidence_in_context": ctx_ev,
           "evidence_in_handoff": h_ev, "same_evidence": all(set(ctx_ev[k]) <= set(h_ev.get(k, [])) for k in ctx_ev)}
    with open(os.path.join(res_dir, "two-formats.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(two))
    out_g = {(g["kind"], g["answer"]): g["outcome"] for g in graded}
    return {"counts": doc["counts"], "refused_exercises": [x["exercise_id"] for x in doc["refused"]],
            "answer_bases": sorted({a["basis"] for p in doc["prompts"] for a in p.get("accepted", [])}),
            "chem_multi_answer_spans": len(chem["multi_answer_spans"]), "chem_drops": [d["why"].split(":")[0] for d in chem["drops"]],
            "short_answers_correct": all(out_g[("free_recall", a)] == "correct" for a in ("4", "Four.", "four semitones", "4 semitones")),
            "other_option_incorrect": out_g[("recognition", "three")] == "incorrect", "unknown_is_self_check": out_g[("free_recall", "C to E")] == "self_check",
            "two_formats_same_evidence": two["same_evidence"]}


def run(out: str) -> dict:
    if os.path.exists(out) and os.listdir(out):
        raise SystemExit("--out must be a new or empty directory")
    os.makedirs(os.path.join(out, "result"), exist_ok=True)
    rows = {n: run_one(n, s, out) for n, s in SOURCES.items()}
    ib = run_inbox(out)
    rv = run_revisions(out)
    rr = run_recall_review(out)
    ho = run_handoff(out)
    pv = run_privacy(out)
    pp = run_practice(out)
    m, f, c = rows["music"], rows["french"], rows["chemistry"]
    parity = {"schema": "flh_xsubject_parity_v1", "runs": rows, "inbox": ib, "revisions": rv, "recall_review": rr, "handoff": ho, "privacy": pv, "practice": pp,
              "checks": {"same_unit_contract": m["unit_keys"] == f["unit_keys"] and m["doc_keys"] == f["doc_keys"],
                         "both_spans_verified": m["spans_verified"] and f["spans_verified"],
                         "both_loops_valid_attempt_first": m["loop_valid"] and f["loop_valid"] and m["loop_order"][0] == f["loop_order"][0] == "recall",
                         "french_draft_unchanged": f["draft_id"] == SOURCES["french"]["draft_id"],
                         "music_recall_supported": m["recall"] > 0 and m["recall_refused"] == 0,
                         "french_recall_optional": f["recall"] == 0,
                         "units_equal_authored_text": m["units_equal_authored_text"] and f["units_equal_authored_text"],
                         "original_text_spans_exact": m["original_text_spans_exact"] and f["original_text_spans_exact"],
                         "inbox_reasons_distinct": {"unsupported_claim", "uncertain_evidence", "word_cue", "conflict"} <= set(ib["reason_codes_r1"]),
                         "decision_kept_on_identical_rerun": ib["identical_rerun"] and ib["rerun_states_equal"] and ib["rerun_unit_ids_equal"],
                         "inbox_sanitized": ib["inbox_privacy_findings"] == 0,
                         "v2_source_through_normal_loop": c["spans_verified"] and c["declared_spans_kept"] and c["recall"] > 0,
                         "v2_extensions_kept": c["extensions_kept"] and c["subject"] == "chemistry" and c["language"] == "en",
                         "exports_have_stable_ids": not m["validate"] and not f["validate"] and not c["validate"],
                         "same_unit_contract_v2": c["unit_keys"] == m["unit_keys"] and c["doc_keys"] == m["doc_keys"],
                         "revisions_classified": rv["prose_edit_keeps_claim_key"] and rv["changed_claim_same_source"] and rv["moved_keep_keys"]
                         and rv["rejected_kept_in_r3"] and rv["ambiguous_duplicates_r3"] >= 1 and rv["diff_deterministic"],
                         "rerun_statuses_distinct": rv["rerun_statuses"] == {"identical_rerun": "identical_rerun", "extractor_failed_empty": "extractor_failed",
                                                                              "extractor_failed_error": "extractor_failed", "source_missing": "source_disappeared",
                                                                              "source_text_replaced": "source_disappeared"},
                         "correction_keeps_evidence": rr["correction"]["state"] == "corrected" and rr["correction"]["evidence_unchanged"],
                         "source_links_carried": rr["feed_links_resolve"] and rr["recall_links"] and rr["feed_items"] > 0,
                         "review_after_revision": rr["revisit_r3"]["can_practise"] and "moved" in rr["revisit_r3"]["evidence"],
                         "contradiction_both_trails": [c["topic"] for c in rr["contradictions"]] == ["minor third"],
                         "handoff_portable": ho["markdown_bodies_identical"] and ho["questions_have_next_action"] and ho["citations_verified"]
                         and not ho["source_text_by_default"] and ho["private_text_refused"],
                         "followup_adds_a_revision": ho["followup"]["fifth_stable_after"] == "supported" and ho["followup"]["refused"] == ["invalid_span"],
                         "quoted_instructions_inert": pv["injected_claim_needs_review"] and pv["markdown_says_quotes_are_data"] and pv["instruction_text_only_inside_quotes"],
                         "contact_details_stay_local": pv["handoff_without_text"] == "exported" and pv["handoff_with_text"].startswith("refused"),
                         "private_scope_stays_local": pv["private_scope"] == "refused",
                         "model_failure_keeps_local_output": pv["model_failure"]["exit"] == 2 and pv["model_failure"]["local_units_unchanged"],
                         "practice_four_kinds": all(pp["counts"][k] > 0 for k in ("free_recall", "recognition", "application", "explanation"))
                         and pp["refused_exercises"] == ["leaky"],
                         "grading_tolerant_not_lenient": pp["short_answers_correct"] and pp["other_option_incorrect"] and pp["unknown_is_self_check"],
                         "multi_answer_span_flagged": pp["chem_multi_answer_spans"] == 1,
                         "two_agent_formats_same_evidence": pp["two_formats_same_evidence"]}}
    parity["ok"] = all(parity["checks"].values())
    with open(os.path.join(out, "result", "parity.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(parity))
    L = ["# Cross-subject slice", "", "| Check | Result |", "|---|---|"] + [f"| {k} | {v} |" for k, v in parity["checks"].items()]
    L += ["", "| Run | Subject | Language | Units | Usable | Recall | Loop |", "|---|---|---|---|---|---|---|"]
    L += [f"| {r['name']} | {r['subject']} | {r['language']} | {r['units']} | {r['usable']} | {r['recall']} | {' → '.join(r['loop_order'][1:]) or r['loop_order'][0]} |"
          for r in rows.values()]
    L += ["", "The chemistry source is a `flh_practice_source_v2` document with explicit spans, converted with `units convert` and run",
          "through the same CLI; it has no contrast, so the practice builder makes no exercise and recall comes from the units layer."]
    with open(os.path.join(out, "result", "SUMMARY.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    seal(os.path.join(out, "result"))
    return parity


def seal(d: str) -> None:
    rows = []
    for dp, _, fs in os.walk(d):
        for n in fs:
            if n != "SHA256SUMS":
                p = os.path.join(dp, n)
                rows.append(f"{hashlib.sha256(_bytes(p)).hexdigest()}  {os.path.relpath(p, d)}\n")
    with open(os.path.join(d, "SHA256SUMS"), "w", encoding="utf-8") as fh:
        fh.write("".join(sorted(rows, key=lambda r: r.split("  ", 1)[1])))


def tree(d: str) -> dict:
    out = {}
    for dp, _, fs in os.walk(d):
        for n in fs:
            p = os.path.join(dp, n)
            out[os.path.relpath(p, d)] = _bytes(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--out")
    g.add_argument("--check", action="store_true")
    g.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if a.out:
        p = run(a.out)
        print(f"xsubject: {'PASS' if p['ok'] else 'FAIL'} ({a.out}/result)")
        return 0 if p["ok"] else 1
    with tempfile.TemporaryDirectory() as t:
        p = run(os.path.join(t, "run"))
        got = tree(os.path.join(t, "run", "result"))
        if a.write:
            shutil.rmtree(EXPECTED, ignore_errors=True)
            shutil.copytree(os.path.join(t, "run", "result"), EXPECTED)
            print(f"wrote fixtures/xsubject_v1/expected/ ({len(got)} files); parity {'PASS' if p['ok'] else 'FAIL'}")
            return 0 if p["ok"] else 1
    want = tree(EXPECTED)
    bad = sorted(n for n in set(got) | set(want) if got.get(n) != want.get(n))
    print("check: result equals fixtures/xsubject_v1/expected/" if not bad else "CHECK FAILED: " + ", ".join(bad))
    print(f"parity: {'PASS' if p['ok'] else 'FAIL'}")
    return 0 if not bad and p["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
