"""Extraction 2.2 demo (PROTOTYPE, offline, synthetic): reliable knowledge, practice and agent exchange.

``demo3`` runs, on three French contrasts (y/en, savoir/connaître and the public-domain à/en
fixture), every 2.2 path and writes fixed outputs (``fixtures/practice_v1/expected3``):

  00  interactions from capture to first practice and first unaided practice, 2.1 vs 2.2
  01  y/en revision 1 review; 02 revision 3 review (moved quotes, restored items, material
      and non-material changes, a rejection reason kept with its revision)
  03  à/en review (paraphrase, two word cues, a conflict); 04 the learner's decisions on the
      conflicting drafts (accept, edit, reject) and the attested paraphrase
  05  packet 1 (v3) for Codex; 06 Codex's return previewed; one exercise accepted with edits
  07  after revision 2 the accepted exercise is withdrawn; the Codex return previewed again
  08  packet 2 for Claude Code, continued from the kept packet after the first session's
      directory was deleted; 09 Claude Code's return: a duplicate, a rejection, an agent
      assertion that cannot make a changed item supported, a malformed proposal
  10  revision 3 restores the evidence: nothing reactivates until the learner confirms
  11  the minimal packet and the share preview with an omitted field
  12  failed imports and their recovery; 13 older packet versions still previewed
  14  adapters: one packet, three prompts (the probe and its dry run are ``recall.trial``)
  16  the storage round trip; 17 the acceptance matrix
  workbooks2/  the sealed feed bundle (five feeds, replay cases, compatibility check)

No agent, provider or network is called: both agent returns are hand-written fixtures.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import tempfile

from . import exercises as ex
from . import feed2
from . import feed_compat as fc
from . import packet as pk
from . import portable as pt
from . import practice as pr
from . import practice22 as p22
from . import review2 as rv
from . import storage_rt as st
from .practice_flow import _bytes, _same_dir, seal
from .practice_workflow import FIX, Work, _read, _write

EXP3 = os.path.join(FIX, "expected3")
BUNDLE2 = os.path.join(FIX, "workbooks2")
SWITCH2 = os.path.join(FIX, "switch2")
SOURCES = {"y-en-demo": "y_en.r1.json", "savoir-connaitre-demo": "savoir_connaitre.json", "a-en-lieux-demo": "a_en_lieux.json"}


def _text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _ids(w) -> dict:
    return {i["proposal_ref"]: i["item_id"] for i in w.draft()["items"]}


# ---- 00: interactions, 2.1 vs 2.2, two intents ----

def _risky(res21: dict, res22: dict) -> list[str]:
    """Items approved without an individual decision although 2.2 would have asked for one."""
    flagged = {i["item_id"] for i in res22["items"] if i["cues"] or i["conflicts"] or i["paraphrases"]}
    return sorted(i["item_id"] for i in res21["items"] if i["item_id"] in flagged and i.get("batch_id"))


def _scripted(work, flow: str, intent: str, src_path: str, script: dict) -> dict:
    """One flow, executed; every learner interaction is recorded."""
    steps = []
    W = Work if flow == "2.1" else p22.Work2
    w = W(work)
    if flow == "2.1":
        w.init(src_path, with_review=True)
        rv1 = w.review()
        shown = len(rv1["members"]) + len(rv1["left_for_you"])
    else:
        w.init(src_path)
        pl = w.plan()
        shown = len(pl["members"]) + len(pl["left_for_you"])
    steps.append({"kind": "command", "text": "init (shows the draft beside its evidence and the review)", "items_shown": shown})
    if intent == "decide_flagged" and flow == "2.2":
        for ref, action, text, attest in script.get("before_batch", []):
            w.decide(_ids(w)[ref], action, text, reason="decided one by one", attest=attest)
            steps.append({"kind": "decision", "text": f"decide --item {ref} --{action}" + (" --attest-paraphrase" if attest else "")})
    bid = w.review()["batch_id"] if flow == "2.1" else w.plan()["batch_id"]
    w.approve_batch(bid)
    steps.append({"kind": "decision", "text": f"decide --approve-batch {bid}"})
    if intent == "decide_flagged" and flow == "2.1":
        for ref, action, text, _ in script.get("after_batch_21", []):
            w.decide(_ids(w)[ref], action, text, reason="decided one by one")
            steps.append({"kind": "decision", "text": f"decide --item {ref} --{action}"})
    prac = w.practice(rebuild=True)
    steps.append({"kind": "command", "text": "build"})
    first = len(steps)
    explain = next(p["practice_id"] for p in prac["items"] if p["kind"] == "explain")
    w.answer(explain, "from memory")
    steps.append({"kind": "command", "text": f"answer --item {explain} (unaided recall)"})
    res = w.resolved()
    return {"flow": flow, "intent": intent, "steps": steps, "commands_to_first_practice": first, "commands_to_first_unaided_practice": len(steps),
            "decision_commands": sum(1 for s in steps if s["kind"] == "decision"), "decision_records": len(w.decisions()),
            "items_shown_for_reading": shown, "approved": sorted(i["item_id"] for i in pr.approved(res)),
            "practice_ids": sorted(p["practice_id"] for p in prac["items"]),
            "evidence_links": {p["practice_id"]: p["evidence_ids"] for p in prac["items"]}, "res": res}


SCRIPTS = {
    "y-en-demo": {"before_batch": [("en-mouvement", "reject", None, False)], "after_batch_21": [("en-mouvement", "reject", None, False)]},
    "savoir-connaitre-demo": {"before_batch": [("savoir-personnes", "reject", None, False)], "after_batch_21": [("savoir-personnes", "reject", None, False)]},
    "a-en-lieux-demo": {"before_batch": [("en-tous-pays", "reject", None, False), ("en-japon", "approve", None, False),
                                         ("en-gerondif", "edit", "In « en débarquant en Égypte », the first « en » makes a gerund (« en » + -ant: "
                                          "while landing); only « en Égypte » is the place preposition.", False),
                                         ("aux-pluriel", "approve", None, True)],
                        "after_batch_21": []},
}


def measure2(root: str) -> dict:
    if os.path.exists(root) and os.listdir(root):
        raise ValueError("the measure directory must be new or empty")
    rows = []
    for sid, f in SOURCES.items():
        src = os.path.join(FIX, f)
        runs = {}
        for flow in ("2.1", "2.2"):
            for intent in ("leave_flagged", "decide_flagged"):
                runs[(flow, intent)] = _scripted(os.path.join(root, sid, f"{flow}-{intent}"), flow, intent, src, SCRIPTS[sid])
        r22 = runs[("2.2", "decide_flagged")]["res"]
        drf = pr.draft(_read(src))
        row = {"source_id": sid, "knowledge_items": len(drf["items"]), "contrasts": sum(1 for i in drf["items"] if i["type"] == "contrast"),
               "missing_evidence": {"unsupported": drf["counts"]["unsupported"], "no_evidence": drf["counts"]["no_evidence"],
                                    "uncertain": drf["counts"]["uncertain"]},
               "flagged_in_2_2": sorted(i["item_id"] for i in r22["items"] if i["cues"] or i["conflicts"] or i["paraphrases"]), "runs": []}
        for (flow, intent), r in runs.items():
            res21 = r["res"] if flow == "2.1" else None
            row["runs"].append({k: v for k, v in r.items() if k not in ("res", "evidence_links")} | {
                "approved_count": len(r["approved"]), "practice_count": len(r["practice_ids"]),
                "exercises_with_evidence": sum(1 for v in r["evidence_links"].values() if v),
                "approved_without_individual_look": _risky(res21, r22) if res21 else []})
        rows.append(row)
    return {"schema": "flh_practice_interactions_v1", "rows": rows,
            "basis": ["every count is an executed command or a written record, not timed use",
                      "intents: leave_flagged approves only what the review batches and leaves the rest pending (the 2.1 measure's intent); "
                      "decide_flagged also decides every flagged item one by one",
                      "first unaided practice = the first answer to the explain item (no options, no source sentence)",
                      "items_shown_for_reading = items the review lists for the learner to read before the first decision"]}


def render_measure2(rep: dict) -> str:
    L = ["Interactions from capture to first practice and to first unaided practice (executed; 2.1 vs 2.2)", ""]
    for r in rep["rows"]:
        me = r["missing_evidence"]
        L.append(f"{r['source_id']}: {r['knowledge_items']} knowledge items ({r['contrasts']} contrast); missing evidence: unsupported "
                 f"{me['unsupported']}, no evidence {me['no_evidence']}, uncertain {me['uncertain']}; flagged by 2.2: {len(r['flagged_in_2_2'])}")
        L.append("  flow intent           to first practice  to first unaided  decision cmds  records  items shown  approved  practice  "
                 "approved without an individual look")
        for x in r["runs"]:
            L.append(f"  {x['flow']:4} {x['intent']:16} {x['commands_to_first_practice']:18} {x['commands_to_first_unaided_practice']:17} "
                     f"{x['decision_commands']:14} {x['decision_records']:8} {x['items_shown_for_reading']:12} {x['approved_count']:9} "
                     f"{x['practice_count']:9} {', '.join(x['approved_without_individual_look']) or '-'}")
        L.append("")
    L += [f"basis: {b}" for b in rep["basis"]]
    return "\n".join(L) + "\n"


# ---- the worked example ----

def _try(fn) -> str:
    try:
        fn()
        return "ACCEPTED (unexpected)"
    except (ValueError, PermissionError) as e:
        return f"refused: {e}"


def pipeline(out: str) -> tuple[dict, list[str], dict]:
    """Run the 2.2 worked example into ``out`` (new or empty). Returns (files, log, bundle documents)."""
    if os.path.exists(out) and os.listdir(out):
        raise ValueError("--out must be a new or empty directory")
    files, log, b = {}, [], {}
    F = lambda n: os.path.join(FIX, n)
    # A. y/en across three revisions
    y = p22.Work2(os.path.join(out, "work-y-en"))
    files["01-y-en-r1-review.txt"] = y.init(F("y_en.r1.json"))
    yi = _ids(y)
    y.decide(yi["en-mouvement"], "reject", reason="my friend corrected exactly this: « j'en vais » is wrong")
    pl = y.plan()
    y.approve_batch(pl["batch_id"])
    y.practice(rebuild=True)
    log.append(f"1 y/en r1       conflict {yi['en-vais']} vs {yi['en-mouvement']} kept out of the batch until the learner rejected "
               f"{yi['en-mouvement']}; batch {pl['batch_id']} ({len(pl['selected'])} items)")
    y.revise(F("y_en.r2.json"))
    s2 = y.resolved()["states"]
    files["02-y-en-r3-review.txt"] = y.revise(F("y_en.r3.json"))
    r3 = y.resolved()
    kinds = {i["proposal_ref"]: (i["state"], i.get("review_kind"), bool(i.get("normalized_only"))) for i in r3["items"]}
    log.append(f"2 y/en r2, r3   r2: needs_review {s2['needs_review']} (left undecided); r3: restored "
               f"{sorted(k for k, v in kinds.items() if v[1] == 'restored')}, changed {sorted(k for k, v in kinds.items() if v[1] == 'changed')}, "
               f"spacing only {sorted(k for k, v in kinds.items() if v[2])}, quotes moved {len(r3['moves'])}, rejection of en-mouvement still "
               f"from revision {next(i for i in r3['items'] if i['proposal_ref'] == 'en-mouvement')['rejected_on']['revision']}")
    for ref in ("en-de", "y-vs-en", "en-vais", "ex-marche"):
        y.decide(yi[ref], "approve", reason="re-read in revision 3")
    log.append(f"3 y/en r3       confirmed 2 restored and re-approved 2 changed items, one by one: {y.resolved()['states']}")
    # B. à/en: conflicting drafts, a paraphrase, word cues
    w = p22.Work2(os.path.join(out, "work-a-en"))
    files["03-a-en-r1-review.txt"] = w.init(F("a_en_lieux.json"))
    ai = _ids(w)
    no_attest = _try(lambda: w.decide(ai["aux-pluriel"], "approve"))
    for ref, action, text, attest in SCRIPTS["a-en-lieux-demo"]["before_batch"]:
        w.decide(ai[ref], action, text, reason={"en-tous-pays": "« au Japon »: Japon is masculine", "en-japon": "matches what I learnt",
                                                "en-gerondif": "the first « en » is a gerund", "aux-pluriel": "checked against the quote"}[ref], attest=attest)
    pl = w.plan()
    w.approve_batch(pl["batch_id"])
    files["04-a-en-decided.txt"] = rv.render_items(w.resolved()) + f"\napproving {ai['aux-pluriel']} without attestation: {no_attest}\n"
    prac = w.practice(rebuild=True)
    log.append(f"4 à/en r1       conflict and cues decided one by one: rejected {ai['en-tous-pays']}, accepted {ai['en-japon']}, edited "
               f"{ai['en-gerondif']}, paraphrase {ai['aux-pluriel']} approved with attestation (without: refused); batch {pl['batch_id']} "
               f"({len(pl['selected'])}); practice {len(prac['items'])}")
    fe = []
    fe.append(feed2.feed(w.resolved(), prac, w.attempts(), 1))
    # C. session 1: Codex
    p1 = w.export3()
    s1 = os.path.join(out, "session-1-codex")
    pt.write_packet3(p1, s1, "codex")
    files["05-packet-1-codex.json"], files["05-packet-1-codex.md"] = pr.dumps(p1), pt.markdown3(p1)
    ret1 = _read(os.path.join(SWITCH2, "codex-a-en.json"))
    rep1 = pt.import_any(p1, ret1, w.resolved(), w.exercise_decisions())
    files["06-codex-preview.txt"] = pt.render_import_any(rep1)
    d1, new1 = w.exercise(p1, ret1, "e1", "approve", edits={"prompt": "Mon oncle travaille __ Marseille depuis deux ans."})
    d1b, new1b = w.exercise(p1, ret1, "e1", "approve", edits={"prompt": "Mon oncle travaille __ Marseille depuis deux ans."})
    other = _try(lambda: w.exercise(p1, ret1, "e1", "reject"))
    prac = w.practice(rebuild=True)
    w.answer(d1["practice_id"], "à")
    w.answer(next(p["practice_id"] for p in prac["items"] if p["kind"] == "produce"), "Je vais à Espagne.")
    fe.append(feed2.feed(w.resolved(), w.practice(), w.attempts(), 2, previous=fe[-1]))
    log.append(f"5 session 1     packet {p1['packet_id']} (v3) -> Codex return (fixture): "
               + ", ".join(f"{k} {v}" for k, v in rep1["exercises"]["counts"].items() if v)
               + f"; learner accepted e1 with an edited prompt as {d1['practice_id']} (decision {d1['seq']}); the same again wrote "
               f"{'nothing' if not new1b else 'A SECOND RECORD'}; a different decision on e1: {other.split(':')[0]}")
    # D. revision 2: the learner removed an excerpt; the exercise's rule changes
    w.revise(F("a_en_lieux.r2.json"))
    prac = w.practice(rebuild=True)
    fe.append(feed2.feed(w.resolved(), prac, w.attempts(), 3, previous=fe[-1]))
    rep1b = ex.preview(p1, ret1, w.resolved(), w.exercise_decisions())
    files["07-codex-preview-after-r2.txt"] = ex.render_preview(rep1b)
    wd = fe[-1]["withdrawn"]
    log.append(f"6 à/en r2       {ai['a-ville']} changed (quote removed): exercise {', '.join(x['practice_id'] + ' ' + x['reason_code'] for x in wd)}; "
               "Codex's return previewed again: " + ", ".join(f"{r['proposal_id']} {r['class']}" for r in rep1b["rows"]))
    # E. the first session's directory is lost; session 2 continues from the kept packet
    shutil.rmtree(s1)
    awaiting = pt.awaiting_from(None, rep1b)
    p2 = w.export3(previous="latest", awaiting=awaiting)
    s2d = os.path.join(out, "session-2-claude-code")
    pt.write_packet3(p2, s2d, "claude-code")
    files["08-packet-2-claude-code.json"], files["08-packet-2-claude-code.md"] = pr.dumps(p2), pt.markdown3(p2)
    log.append(f"7 session 2     session 1's directory deleted; packet {p2['packet_id']} continues {p2['continuity']['previous_packet_id']} "
               f"(kept in the work directory): {p2['continuity']['knowledge_ids_kept']} knowledge IDs kept, dropped "
               f"{', '.join(p2['continuity']['knowledge_ids_dropped']) or 'none'}; not offered {', '.join(x['practice_id'] for x in p2['exercises_not_offered'])}; "
               f"awaiting the learner {', '.join(a['proposal_id'] for a in p2['awaiting_learner'])}")
    ret2 = _read(os.path.join(SWITCH2, "claude-code-a-en.json"))
    rep2 = pt.import_any(p2, ret2, w.resolved(), w.exercise_decisions())
    d2, _ = w.exercise(p2, ret2, "q2", "reject", reason="too close to Codex's e2, which I want to try first")
    assertion = _try(lambda: w.accept(p1, {**ret2, "schema": pk.PROPOSALS_SCHEMA, "packet_id": p1["packet_id"],
                                           "proposals": [x for x in ret2["proposals"] if x.get("proposal_id") == "q3"]}, "q3"))
    files["09-claude-code-preview.txt"] = pt.render_import_any(rep2) + (
        f"\nlearner rejected q2 (decision {d2['seq']}): {d2['reason']}\n"
        f"q3 replayed against packet 1, where {ai['a-ville']} was still approved: {assertion}\n")
    log.append("8 Claude Code   return (fixture): " + ", ".join(f"{r['proposal_id']} {r['class']}" for r in rep2["exercises"]["rows"])
               + "; " + ", ".join(f"{r['proposal_id']} {r['class']}" for r in rep2["corrections"]["rows"])
               + f"; warnings {len(rep2['warnings'])}; learner rejected q2; q3's assertion cannot make {ai['a-ville']} supported: "
               + assertion.split(":")[0])
    # F. revision 3: the excerpt is back; nothing reactivates by itself
    w.revise(F("a_en_lieux.r3.json"))
    fe.append(feed2.feed(w.resolved(), w.practice(rebuild=True), w.attempts(), 4, previous=fe[-1]))
    waiting = [x["reason_code"] for x in fe[-1]["withdrawn"]]
    files["10-a-en-r3-review.txt"] = w.show()
    before = next(i for i in w.resolved()["items"] if i["item_id"] == ai["a-ville"])
    w.decide(ai["a-ville"], "approve", reason="the excerpt is back in my notes; checked")
    fe.append(feed2.feed(w.resolved(), w.practice(rebuild=True), w.attempts(), 5, previous=fe[-1]))
    log.append(f"9 à/en r3       evidence back: {ai['a-ville']} {before['state']} ({before.get('review_kind')}) until "
               f"confirmed; feed 4 still withdraws ({', '.join(waiting)}); after the learner's confirmation feed 5 restores "
               f"{', '.join(fe[-1]['restored'])}")
    # G. minimal packet and the share preview with an omitted field
    pm = w.export3(variant="minimal", omit=("learner_goal",), keep=False)
    files["11-packet-minimal.md"] = pt.markdown3(pm)
    files["11-share-preview.txt"] = pt.preview3(w.export3(omit=("learner_goal", "evidence_text"), keep=False)) + pt.preview3(pm)
    log.append(f"10 minimal      packet {pm['packet_id']}: {len(pt.markdown3(pm))} characters of Markdown vs {len(pt.markdown3(p2))} for the full packet; "
               "goal omitted by the learner")
    # H. failed imports and recovery
    bad_version = _try(lambda: pt.import_any(p2, {**ret2, "schema": "flh_agent_proposals_v9"}))
    wrong_packet = ex.preview(p2, ret1, w.resolved(), w.exercise_decisions())
    wrong_accept = _try(lambda: w.exercise(p2, ret1, "e2", "approve"))
    right = ex.preview(_read(os.path.join(w.path, "packets", p1["packet_id"] + ".json")), ret1, w.resolved(), w.exercise_decisions())
    files["12-failed-import.txt"] = (
        "1. A return in an unsupported format version\n" + f"   {bad_version}\n"
        "   Recovery: nothing was read or changed. Ask the agent to answer again in the format packet.md describes.\n\n"
        "2. Codex's return previewed against packet 2 (it names packet 1)\n"
        + "".join(f"   {line}\n" for line in ex.render_preview(wrong_packet).splitlines()[:2])
        + f"   accepting e2 anyway: {wrong_accept}\n"
        f"   Recovery: preview it against the packet it names, kept in the work directory (packets/{p1['packet_id']}.json):\n"
        + "".join(f"   {line}\n" for line in ex.render_preview(right).splitlines()[:2]))
    log.append(f"11 failed import unsupported version refused; a return for another packet: warning, accept refused; recovery = the kept packet")
    # I. older packet versions
    older = []
    for name, pfile, rfile in (("v1 (HANDOFF-136)", os.path.join(FIX, "expected", "packet-study__packet.json"), os.path.join(FIX, "agent_return.json")),
                               ("v2 (2.1)", os.path.join(FIX, "expected2", "06-packet-1-codex.json"), os.path.join(FIX, "switch", "codex-return.json"))):
        rep = pt.import_any(_read(pfile), _read(rfile))
        older.append(f"## packet {name}\n" + pt.render_import_any(rep))
    files["13-older-packets.txt"] = "\n".join(older)
    log.append(f"12 older packets v1 (HANDOFF-136) and v2 (2.1) previewed with their original returns, read as 2.1 read them")
    # J. adapters: one packet, three prompts
    ad = os.path.join(out, "adapters")
    for agent in pt.ADAPTERS:
        pt.write_packet3(p2, os.path.join(ad, agent), agent)
    same = all(_bytes(os.path.join(ad, a, "packet.json")) == _bytes(os.path.join(ad, "codex", "packet.json"))
               and _bytes(os.path.join(ad, a, "packet.md")) == _bytes(os.path.join(ad, "codex", "packet.md")) for a in pt.ADAPTERS)
    prompts = {a: _text(os.path.join(ad, a, n)).splitlines() for a, n in pt.ADAPTERS.items()}
    diffs = [f"{a}: line {i + 1} differs from Codex's" for a in ("claude-code", "any-agent") for i, (x, y2) in enumerate(zip(prompts["codex"], prompts[a])) if x != y2]
    priv = sum(len(pk.privacy_findings(_text(f))) for f in glob.glob(os.path.join(ad, "*", "*")))
    files["14-adapters.txt"] = (f"packet.json and packet.md identical for {', '.join(pt.ADAPTERS)}: {same}\n"
                                f"normal form problems in packet.json / packet.md: {pt.normalized(pr.dumps(p2)) + pt.normalized(pt.markdown3(p2)) or 'none'}\n"
                                f"privacy findings in the three adapter directories: {priv}\n" + "\n".join(diffs) + "\n")
    log.append(f"13 adapters     one packet for codex, claude-code and any-agent: identical bytes {same}; prompts differ in {len(diffs)} lines; "
               f"privacy findings {priv}")
    # L. storage round trip
    rts = [st.round_trip(w, amended=False), st.round_trip(w, amended=True), st.round_trip(w, amended=True, keep_answer_text=False)]
    files["16-storage-round-trip.json"] = pr.dumps({"runs": rts, "events": st.EVENTS, "id_map": st.ID_MAP,
                                                    "export_attempts_default": st.export_attempts(w.attempts())})
    as_rows, _ = st.rows(w, amended=False)
    am_rows, _ = st.rows(w, amended=True)
    b["storage-rows.json"] = {"schema": "flh_practice_storage_rows_v1", "synthetic": True,
                              "from": "the à/en work directory of this demo (decisions, exercise decisions, attempts with the answer text stored)",
                              "amendment": [list(x) for x in st.AMENDMENT], "rows": {"as_proposed": as_rows, "amended": am_rows},
                              "expect": {"as_proposed": {"refused": len(rts[0]["refused_by_constraints"])}, "amended": {"refused": 0}}}
    log.append("15 storage       " + "; ".join(f"{r['variant']}{'' if r['answer_text_stored'] else ' (no answer text)'}: refused "
                                                f"{len(r['refused_by_constraints'])}, not representable {len(r['not_representable'])}, learner-visible "
                                                f"differences {len(r['learner_visible_differences'])}" for r in rts))
    # M. acceptance matrix
    with tempfile.TemporaryDirectory() as tmp:
        m = p22.acceptance_matrix(tmp)
    files["17-acceptance-matrix.json"], files["17-acceptance-matrix.md"] = pr.dumps(m), p22.render_matrix(m)
    log.append(f"16 matrix       {sum(r['ok'] for r in m['rows'])} of {len(m['rows'])} transitions as expected")
    # N. Workbooks bundle 2
    names = ["feed-1-r1.json", "feed-2-r1-newly-approved.json", "feed-3-r2-withdrawn.json", "feed-4-r3-awaiting-confirmation.json", "feed-5-r3-restored.json"]
    for n, f in zip(names, fe):
        b[n] = f
    b["replay-cases.json"] = {"schema": "flh_practice_feed_replay_cases_v1", "cases": {
        "in-order": {"deliver": names, "expect": None},
        "replay-every-feed": {"deliver": [x for n in names for x in (n, n)], "expect": None},
        "repeat-restore": {"deliver": names + [names[-1], names[-1]], "expect": None},
        "late-old-feed": {"deliver": names[:2] + [names[4], names[2]], "expect": None},
        "missed-awaiting-feed": {"deliver": names[:3] + [names[4]], "expect": None}}}
    for c in b["replay-cases.json"]["cases"].values():
        state: dict = {}
        acts = [fc.client_apply(state, b[n]) for n in c["deliver"]]
        c["expect"] = {"actions": acts, "items": {pid: {"offered": v["offered"], "history": len(v["history"]),
                                                       **({"reason": v["withdrawn_reason"]} if "withdrawn_reason" in v else {})}
                                                 for pid, v in sorted(state["items"].items())}}
    compat = {n: {"contract": fc.contract_issues(b[n]), "consumer_increment_4": fc.consumer_issues(b[n])} for n in names}
    old21 = {n: {"contract": fc.contract_issues(_read(os.path.join(FIX, "workbooks", n))), "consumer_increment_4": fc.consumer_issues(_read(os.path.join(FIX, "workbooks", n)))}
             for n in sorted(os.listdir(os.path.join(FIX, "workbooks"))) if n.startswith("feed-")}
    b["compat-report.json"] = {"bundle_2_2": compat, "bundle_2_1_unchanged": old21}
    log.append(f"17 workbooks2   {len(names)} feeds; contract issues {sum(len(v['contract']) for v in compat.values())}; refused by the increment-4 "
               f"consumer: {sorted(n for n, v in {**compat, **old21}.items() if v['consumer_increment_4'])}")
    return files, log, b


def write_bundle(b: dict, d: str) -> None:
    os.makedirs(d, exist_ok=True)
    for n, obj in b.items():
        _write(os.path.join(d, n), pr.dumps(obj))
    shutil.copyfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed_compat.py"), os.path.join(d, "check_feed_compat.py"))
    shutil.copyfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage_check.py"), os.path.join(d, "check_storage_rows.py"))
    shutil.copyfile(st.SQL, os.path.join(d, "storage-proposed-0NN.sql"))
    for n in ("README.md", "STORAGE-DECISION-RECORD.md"):
        shutil.copyfile(os.path.join(BUNDLE2, n), os.path.join(d, n))
    _write(os.path.join(d, "SHA256SUMS"), seal(d))


def demo3(out: str, check: bool = False) -> tuple[int, str]:
    if os.path.exists(out) and os.listdir(out):
        raise ValueError("--out must be a new or empty directory")
    rep = measure2(os.path.join(out, "measure"))
    files = {"00-interactions.json": pr.dumps(rep), "00-interactions.txt": render_measure2(rep)}
    more, log, b = pipeline(os.path.join(out, "run"))
    files.update(more)
    head = "0 interactions  " + "; ".join(
        f"{r['source_id']}: 2.1 {x21['commands_to_first_unaided_practice']} -> 2.2 {x22['commands_to_first_unaided_practice']} commands to first unaided "
        f"practice, approved without a look {len(x21['approved_without_individual_look'])} -> {len(x22['approved_without_individual_look'])}"
        for r in rep["rows"] for x21 in [next(x for x in r["runs"] if x["flow"] == "2.1" and x["intent"] == "decide_flagged")]
        for x22 in [next(x for x in r["runs"] if x["flow"] == "2.2" and x["intent"] == "decide_flagged")])
    files["demo3.txt"] = "Extraction 2.2 demo (synthetic y/en, savoir/connaître; à/en quoting public-domain Verne; PROTOTYPE)\n" + "\n".join([head] + log) + "\n"
    for name, body in files.items():
        _write(os.path.join(out, name), body)
    bdir = os.path.join(out, "workbooks2")
    write_bundle(b, bdir)
    import subprocess
    import sys
    feeds = sorted(n for n in os.listdir(bdir) if n.startswith("feed-"))
    pr_ = subprocess.run([sys.executable, "-I", "-B", os.path.join(bdir, "check_feed_compat.py"), *[os.path.join(bdir, n) for n in feeds],
                          "--replay", os.path.join(bdir, "replay-cases.json")], capture_output=True, text=True, timeout=60)
    ps = subprocess.run([sys.executable, "-I", "-B", os.path.join(bdir, "check_storage_rows.py"), bdir], capture_output=True, text=True, timeout=60)
    text = files["demo3.txt"] + f"workbooks2 check_feed_compat.py: exit {pr_.returncode}; check_storage_rows.py: exit {ps.returncode}\n"
    if not check:
        return pr_.returncode or ps.returncode, text
    bad = [n for n in sorted(files) if not os.path.exists(os.path.join(EXP3, n)) or _bytes(os.path.join(out, n)) != _bytes(os.path.join(EXP3, n))]
    bad += ["workbooks2/" + n for n in _same_dir(bdir, BUNDLE2)]
    if pr_.returncode:
        bad.append("check_feed_compat: " + pr_.stdout.strip().splitlines()[-1])
    if ps.returncode:
        bad.append("check_storage_rows: " + ps.stdout.strip().splitlines()[-1])
    if bad:
        return 1, text + f"CHECK FAILED: {', '.join(bad)}\n"
    return 0, text + f"check: every output equals the shipped expected file ({len(files)} files and the {len(os.listdir(BUNDLE2))}-file workbooks2 bundle)\n"
