"""Agent exchange round trip with two local role stand-ins (R4; offline, synthetic, no model).

  python3 -I -B scripts/r4_exchange.py --write     # (re)write fixtures/r4_v1/exchange/
  python3 -I -B scripts/r4_exchange.py --check     # regenerate and compare byte for byte

1. **Export.** A ``flh_agent_context_v1`` packet is exported for one reviewed exercise of the
   y/en source (revision 1, after the learner's wrong answer), then rendered as Markdown for
   Claude Code and for Codex. The two bodies are byte-identical.
2. **Return.** Two deterministic stand-ins play the agents. They are scripted functions, not
   models. Each reads only its Markdown (the return template's JSON block) and writes a
   ``flh_agent_corrections_v1`` return:
   - the "claude-code" stand-in sends one rewording and one correction for a unit that is not
     in the packet;
   - the "codex" stand-in sends one rewording, one duplicate and one uncited correction.
3. **Preview.** ``import_preview`` classifies both returns against the current review and
   applies nothing.
4. **Accept.** The learner accepts one candidate from each. ``accept`` gives two ordinary edit
   decisions with ``via`` provenance. With them the units are ``corrected``; a re-export shows
   the corrected texts.
5. **Compare.** The provenance kept for the two agents has the same fields.
6. **Outdated and refused.** Previewed against revision 2, the correction on the changed unit
   is ``outdated``. Malformed, other-version, other-packet and altered documents are refused,
   each with a recovery command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "scripts"))

from flh_extraction import exchange as xc  # noqa: E402
from flh_extraction import practice as pr  # noqa: E402
from flh_extraction import review2 as rv  # noqa: E402

import r4_loop  # noqa: E402

OUT = os.path.join(HERE, "fixtures", "r4_v1", "exchange")


def template(md: str) -> dict:
    """What a stand-in reads: the JSON block of the Markdown's return section (the IDs it may use)."""
    m = re.search(r"```json\n(.*?)\n```", md, re.S)
    return json.loads(m.group(1))


def standin(agent: str, md: str) -> dict:
    t = template(md)
    units = re.findall(r"^- (k-[0-9a-f]{12}) \(([a-z_]+), [a-z_]+\): (.*)$", md, re.M)
    evid = re.findall(r"^- (ev-[0-9a-f]{10}) ", md, re.M)
    c = []
    if agent == "claude-code":
        c.append({"correction_id": "c1", "unit_id": units[0][0], "proposed_text": "In short: " + units[0][2], "evidence_ids": evid[:1],
                  "rationale": "a shorter lead-in for an A2 learner"})
        c.append({"correction_id": "c2", "unit_id": "k-000000000000", "proposed_text": "A rule the packet does not contain.", "evidence_ids": evid[:1],
                  "rationale": "stand-in: a unit outside the packet"})
    else:
        c.append({"correction_id": "c1", "unit_id": units[1][0], "proposed_text": "In short: " + units[1][2], "evidence_ids": evid[1:2],
                  "rationale": "names both forms first"})
        c.append({"correction_id": "c2", "unit_id": units[0][0], "proposed_text": units[0][2], "evidence_ids": evid[:1], "rationale": "stand-in: no change"})
        c.append({"correction_id": "c3", "unit_id": units[0][0], "proposed_text": "Always use « en ».", "evidence_ids": [],
                  "rationale": "stand-in: not supported by the packet"})
    return {"schema": t["schema"], "context_id": t["context_id"], "agent": agent, "corrections": c}


def build() -> dict:
    s = r4_loop.states()
    r1, r2 = s["r1"], s["r2"]
    pid = next(p["practice_id"] for p in r1["prac"]["items"] if p["kind"] == "choose")
    ctx = xc.export(r1["res"], r1["prac"], r1["sources"], pid, last_outcome="incorrect")
    md = {a: xc.markdown(ctx, a) for a in ("claude-code", "codex")}
    rets = {a: standin(a, md[a]) for a in md}
    pvs = {a: xc.import_preview(ctx, rets[a], r1["res"]) for a in rets}
    drafts = {rev: pr.draft(src) for rev, src in r1["sources"].items()}
    cur = drafts[max(drafts)]
    decs = list(_decisions(r1))
    seq = max(d["seq"] for d in decs) + 1
    acc = [xc.accept(pvs["claude-code"], "c1", cur, r1["res"], seq), xc.accept(pvs["codex"], "c1", cur, r1["res"], seq + 1)]
    res_after = rv.resolve2(drafts, decs + acc, r1["sources"])
    prac_after = pr.build_practice(res_after)
    ctx_after = xc.export(res_after, prac_after, r1["sources"], pid)
    prov = {a: sorted(d["via"]) for a, d in zip(("claude-code", "codex"), acc)}
    outdated = {a: xc.import_preview(ctx, rets[a], r2["res"]) for a in rets}
    errors = {}
    other = dict(ctx_after)
    for name, fn in (("malformed_return", lambda: xc.import_preview(ctx, "{not json")),
                     ("return_v2", lambda: xc.import_preview(ctx, {**rets["codex"], "schema": "flh_agent_corrections_v2"})),
                     ("return_for_another_packet", lambda: xc.import_preview(other, rets["codex"])),
                     ("packet_v0", lambda: xc.import_preview({**ctx, "schema": "flh_agent_context_v0"}, rets["codex"])),
                     ("packet_altered", lambda: xc.import_preview({**ctx, "units": ctx["units"][:1]}, rets["codex"]))):
        try:
            fn()
            errors[name] = {"refused": False}
        except xc.ExchangeError as e:
            errors[name] = {"refused": True, "code": e.code, "recovery": e.recovery}
    report = {
        "context_id": ctx["context_id"], "markdown_bodies_identical": md["claude-code"].split("\n", 1)[1] == md["codex"].split("\n", 1)[1],
        "packet_has_no_answer": not any(k in json.dumps(ctx, ensure_ascii=False) for k in ('"answer":', '"accepted":', '"hidden":', '"rubric')),
        "evidence_verified": all(e["verified"] for e in ctx["evidence"]),
        "previews": {a: pvs[a]["counts"] for a in pvs}, "applied": {a: pvs[a]["applied"] for a in pvs},
        "units_before": {u["unit_id"]: u["state"] for u in ctx["units"]},
        "units_after_acceptance": {u["unit_id"]: u["state"] for u in ctx_after["units"]},
        "texts_after_are_the_accepted": [u["text"] for u in ctx_after["units"]] == [r["proposed_text"] for r in
                                                                                     (pvs["claude-code"]["rows"][0], pvs["codex"]["rows"][0])],
        "provenance_fields": prov, "provenance_same_fields": prov["claude-code"] == prov["codex"],
        "outdated_against_r2": {a: outdated[a]["counts"] for a in outdated}, "refusals": errors}
    report["ok"] = (report["markdown_bodies_identical"] and report["packet_has_no_answer"] and report["evidence_verified"]
                    and not any(report["applied"].values()) and report["texts_after_are_the_accepted"] and report["provenance_same_fields"]
                    and set(report["units_after_acceptance"].values()) == {"corrected"}
                    and report["outdated_against_r2"]["codex"]["outdated"] == 1 and all(v["refused"] for v in errors.values()))
    return {"ctx": ctx, "md": md, "rets": rets, "pvs": pvs, "acc": acc, "ctx_after": ctx_after, "outdated": outdated, "report": report}


def _decisions(snap: dict) -> list[dict]:
    """The learner's decisions behind revision 1 of the R4 states (reject en-mouvement, then the batch)."""
    import tempfile as _t

    from flh_extraction import practice22 as p22
    from flh_extraction import r4corpus as rc
    with _t.TemporaryDirectory() as t:
        y = p22.Work2(os.path.join(t, "y"))
        y.init(os.path.join(rc.PRACTICE, "y_en.r1.json"), with_review=False)
        ids = {i["proposal_ref"]: i["item_id"] for i in y.resolved()["items"]}
        y.decide(ids["en-mouvement"], "reject", reason="my friend corrected exactly this: « j'en vais » is wrong")
        y.approve_batch(y.plan()["batch_id"])
        assert y.resolved()["states"] == snap["res"]["states"]
        return y.decisions()


README = """# Agent exchange round trip (`flh_agent_context_v1` / `flh_agent_corrections_v1`, R4; synthetic)

| File | What it is |
|---|---|
| `context.json` | the packet for one reviewed exercise (no answer; units, evidence verified against the learner's text; last outcome only) |
| `context.claude-code.md`, `context.codex.md` | the same Markdown body; only the first line names the agent |
| `return-*.json` | what the two local stand-ins (scripted, no model) wrote |
| `preview-*.txt` | the read-only classification: nothing applied |
| `accepted-decisions.json` | the learner accepted one candidate from each: ordinary edit decisions with `via` provenance |
| `context-after.json` | re-export after acceptance: both units `corrected` with the accepted texts |
| `preview-*-against-r2.txt` | the same returns against revision 2: the correction on the changed unit is `outdated` |
| `report.json` | the checks, the provenance fields of both agents and the refused documents with their recovery commands |

Contract: `tools/extraction/LOOP.md` §2. Regenerate with `scripts/r4_exchange.py --write`.
"""


def files() -> dict:
    b = build()
    fs = {"context.json": pr.dumps(b["ctx"]), "context.claude-code.md": b["md"]["claude-code"], "context.codex.md": b["md"]["codex"],
          "accepted-decisions.json": pr.dumps(b["acc"]), "context-after.json": pr.dumps(b["ctx_after"]), "report.json": pr.dumps(b["report"]),
          "README.md": README}
    for a in ("claude-code", "codex"):
        fs[f"return-{a}.json"] = pr.dumps(b["rets"][a])
        fs[f"preview-{a}.txt"] = xc.render_preview(b["pvs"][a])
        fs[f"preview-{a}-against-r2.txt"] = xc.render_preview(b["outdated"][a])
    return fs


def write(out: str) -> dict:
    fs = files()
    os.makedirs(out, exist_ok=True)
    for n, t in fs.items():
        with open(os.path.join(out, n), "w", encoding="utf-8") as fh:
            fh.write(t)
    with open(os.path.join(out, "SHA256SUMS"), "w", encoding="utf-8") as fh:
        fh.write("".join(f"{hashlib.sha256(fs[n].encode()).hexdigest()}  {n}\n" for n in sorted(fs)))
    return json.loads(fs["report.json"])


def _bytes(p: str) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.write:
        shutil.rmtree(OUT, ignore_errors=True)
        rep = write(OUT)
    else:
        with tempfile.TemporaryDirectory() as t:
            rep = write(t)
            bad = [n for n in sorted(set(os.listdir(t)) | set(os.listdir(OUT)))
                   if not (os.path.exists(os.path.join(t, n)) and os.path.exists(os.path.join(OUT, n)))
                   or _bytes(os.path.join(t, n)) != _bytes(os.path.join(OUT, n))]
        print("check: exchange/ equals a fresh run" if not bad else "CHECK FAILED: " + ", ".join(bad))
        if bad:
            return 1
    print(json.dumps({k: v for k, v in rep.items() if k != "refusals"}, ensure_ascii=False, sort_keys=True))
    print("refusals:", {k: v.get("code") for k, v in rep["refusals"].items()})
    print("exchange:", "PASS" if rep["ok"] else "FAIL")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
