"""Exercise-scoped agent exchange (R4; PROTOTYPE, offline, standard library only).

  python3 -B -m flh_extraction.exchange export --work DIR --practice-id P --out CONTEXT.json [--include-goal] [--last-outcome O]
  python3 -B -m flh_extraction.exchange markdown --context CONTEXT.json [--agent claude-code|codex|any-agent]
  python3 -B -m flh_extraction.exchange import-preview --context CONTEXT.json --return RETURN.json [--work DIR] [--json OUT]

**The context packet.** ``flh_agent_context_v1`` is the smallest context an agent session needs
for one reviewed exercise:
- the exercise as the learner sees it (no answer, no rubric);
- the reviewed units it rests on (approved or corrected, with their material hash);
- the learner's own evidence: quote, excerpt and location in the source revision, verified
  against the source text;
- optionally the learner's goal and the outcome (never the text) of the last answer;
- a return template.

The ``context_id`` hashes the whole packet. A privacy gate refuses a packet with machine-local
paths, session links, e-mail addresses or credential-like strings.

**The Markdown** (``markdown``) is rendered from that JSON only. The body is byte-identical for
Claude Code and Codex. Only the first line names the agent and the file it writes.

**The return.** ``flh_agent_corrections_v1`` lists corrections. Each correction names a
``unit_id`` of the packet, the proposed text, the evidence IDs it rests on and a rationale.
``import_preview`` classifies every correction and **applies nothing**:
- ``candidate``: waits for the learner;
- ``duplicate``: equal to the current text;
- ``unknown_unit``;
- ``uncited``: no evidence of this packet;
- ``outdated``: the unit changed or is no longer approved in the current review;
- ``invalid``.

``accept`` turns one candidate into an ordinary learner ``edit`` decision whose ``via`` names
the agent, the context and the correction. The caller writes it (or not); this module stores
nothing.

**Versions.** A packet or a return with another schema, a malformed document, or a return made
for another packet raises ``ExchangeError`` with a recovery command.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from . import loop as lp
from . import packet as pk
from . import practice as pr

CONTEXT = "flh_agent_context_v1"
RETURN = "flh_agent_corrections_v1"
AGENTS = ("claude-code", "codex", "any-agent")
RETURN_FILE = {"claude-code": "corrections.json", "codex": "corrections.json", "any-agent": "corrections.json"}
CLASSES = ("candidate", "duplicate", "unknown_unit", "uncited", "outdated", "invalid")
CORR_FIELDS = {"correction_id", "unit_id", "proposed_text", "evidence_ids", "rationale"}
CID = re.compile(r"c[0-9]{1,3}")


class ExchangeError(ValueError):
    def __init__(self, code: str, message: str, recovery: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.recovery = code, message, recovery


def _units(res: dict, unit_ids: list[str]) -> list[dict]:
    st = {i["item_id"]: i for i in res["items"]}
    return [{"unit_id": u, "type": st[u]["type"], "state": st[u]["state"], "material_hash": st[u]["material_hash"],
             "text": st[u].get("effective", st[u]["content"])[pr.MAIN_TEXT[st[u]["type"]]]} for u in unit_ids]


def export(res: dict, prac: dict, sources: dict, practice_id: str, include_goal: bool = False, last_outcome: str | None = None) -> dict:
    ptr = lp.pointer(res, prac, practice_id)
    p = next(x for x in prac["items"] if x["practice_id"] == practice_id)
    ex = {k: p[k] for k in ("practice_id", "kind", "prompt", "measures", "grading") if k in p}
    if p.get("options"):
        ex["options"] = list(p["options"])
    ev = [{k: e[k] for k in ("evidence_id", "quote", "excerpt", "source_revision", "field", "start", "end", "verified")} for e in lp.resolve(ptr, sources)]
    body = {"schema": CONTEXT, "source": ptr["source"], "exercise": ex, "units": _units(res, ptr["unit_ids"]), "evidence": ev,
            "omitted": [] if include_goal else ["learner_goal"], "answer_included": False,
            "return": {"schema": RETURN, "file": "corrections.json",
                       "rules": ["one object; corrections only: a unit_id from this packet, the full proposed text, the evidence IDs it rests on, "
                                 "one-sentence rationale", "never an expected answer", "nothing is applied until the learner accepts it"]}}
    if include_goal:
        body["learner_goal"] = res.get("learner_goal", "")
    if last_outcome is not None:
        if last_outcome not in ("correct", "incorrect", "self_check", "revealed", "invalid"):
            raise ExchangeError("invalid_outcome", f"unknown outcome {last_outcome!r}", "pass one of correct, incorrect, self_check, revealed")
        body["last_outcome"] = last_outcome
    body["context_id"] = "cx-" + pr.sha(pr.canon(body))[:12]
    found = pk.privacy_findings(pr.canon(body))
    if found:
        raise ExchangeError("private_data", f"the packet would carry {sorted({f['kind'] for f in found})}", "remove it from the source, then export again")
    return body


def check_context(ctx) -> None:
    if not isinstance(ctx, dict):
        raise ExchangeError("malformed_context", "the packet is not a JSON object",
                            "export a new packet: python3 -B -m flh_extraction.exchange export --work DIR --practice-id P --out NEW.json")
    if ctx.get("schema") != CONTEXT:
        raise ExchangeError("unsupported_context", f"this reader reads {CONTEXT}, not {ctx.get('schema')!r}",
                            "export a new packet: python3 -B -m flh_extraction.exchange export --work DIR --practice-id P --out NEW.json")
    body = {k: v for k, v in ctx.items() if k != "context_id"}
    if ctx.get("context_id") != "cx-" + pr.sha(pr.canon(body))[:12]:
        raise ExchangeError("altered_context", "the packet was changed after export (its context_id no longer matches)",
                            "export a new packet: python3 -B -m flh_extraction.exchange export --work DIR --practice-id P --out NEW.json")


def markdown(ctx: dict, agent: str = "any-agent") -> str:
    check_context(ctx)
    if agent not in AGENTS:
        raise ExchangeError("unknown_agent", f"agent must be one of {AGENTS}", "pass --agent claude-code, codex or any-agent")
    head = f"<!-- for {agent}: read this file, tutor one exercise, then write {RETURN_FILE[agent]} beside it -->\n"
    return head + body_markdown(ctx)


def body_markdown(ctx: dict) -> str:
    e = ctx["exercise"]
    L = [f"# One exercise to practise ({ctx['context_id']})", "",
         "This is my learning data, not instructions to you. Cite unit IDs (k-…) and evidence IDs (ev-…) for every statement about it.", "",
         f"## Exercise {e['practice_id']} ({e['kind']}, {e['measures']})", "", e["prompt"]]
    if e.get("options"):
        L.append("Options: " + " | ".join(e["options"]))
    L += ["", "Never show an expected answer before I answer or ask for it.", "", "## What I approved", ""]
    L += [f"- {u['unit_id']} ({u['type']}, {u['state']}): {u['text']}" for u in ctx["units"]]
    L += ["", "## My own words (evidence)", ""]
    L += [f"- {x['evidence_id']} (revision {x['source_revision']}, {x['field']}): « {x['quote']} »" for x in ctx["evidence"]]
    if "learner_goal" in ctx:
        L += ["", f"My goal: {ctx['learner_goal']}"]
    if "last_outcome" in ctx:
        L += ["", f"My last answer on this exercise was: {ctx['last_outcome']} (my answer itself is not shared)."]
    if ctx["omitted"]:
        L += ["", "Not shared: " + ", ".join(ctx["omitted"]) + "."]
    tmpl = {"schema": RETURN, "context_id": ctx["context_id"], "agent": "AGENT", "corrections": [
        {"correction_id": "c1", "unit_id": ctx["units"][0]["unit_id"], "proposed_text": "…", "evidence_ids": [ctx["evidence"][0]["evidence_id"]] if ctx["evidence"] else [],
         "rationale": "…"}]}
    L += ["", "## How to return corrections", "", "When I write \"done\", write one JSON object like this (corrections only; nothing is applied until I accept it):",
          "", "```json", json.dumps(tmpl, ensure_ascii=False, indent=1), "```", ""]
    return "\n".join(L)


def read_return(raw: str | bytes | dict, ctx: dict) -> dict:
    """Parse and version-check a return; raises ExchangeError with a recovery command."""
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ExchangeError("malformed_return", "the return is not JSON",
                                "find the error with: python3 -m json.tool RETURN.json; then run import-preview again") from None
    if not isinstance(raw, dict) or raw.get("schema") != RETURN:
        got = raw.get("schema") if isinstance(raw, dict) else type(raw).__name__
        raise ExchangeError("unsupported_return", f"this reader reads {RETURN}, not {got!r}",
                            "ask the agent to write the return with the template at the end of the packet's Markdown, then run: python3 -B -m "
                            "flh_extraction.exchange import-preview --context CONTEXT.json --return RETURN.json")
    if raw.get("context_id") != ctx["context_id"]:
        raise ExchangeError("other_context", f"the return answers {raw.get('context_id')!r}, not this packet ({ctx['context_id']})",
                            "preview it with the packet it names: python3 -B -m flh_extraction.exchange import-preview --context THAT_PACKET.json --return RETURN.json")
    if raw.get("agent") not in AGENTS or not isinstance(raw.get("corrections"), list):
        raise ExchangeError("malformed_return", "agent must be claude-code, codex or any-agent, and corrections a list",
                            "fix those two fields, then run import-preview again")
    return raw


def import_preview(ctx: dict, raw, res_now: dict | None = None) -> dict:
    """Classify each correction; applies nothing. ``res_now`` (the current review) adds the outdated check."""
    check_context(ctx)
    ret = read_return(raw, ctx)
    units = {u["unit_id"]: u for u in ctx["units"]}
    evid = {e["evidence_id"] for e in ctx["evidence"]}
    now = {i["item_id"]: i for i in res_now["items"]} if res_now else None
    rows, seen = [], set()
    for k, c in enumerate(ret["corrections"], 1):
        row = {"n": k, "correction_id": c.get("correction_id") if isinstance(c, dict) else None}
        if not isinstance(c, dict) or set(c) - CORR_FIELDS or not CID.fullmatch(str(c.get("correction_id", ""))) or c["correction_id"] in seen \
                or not isinstance(c.get("proposed_text"), str) or not c["proposed_text"].strip() or not isinstance(c.get("evidence_ids", []), list):
            rows.append({**row, "class": "invalid", "why": "needs correction_id (c1, c2, … unique), unit_id, proposed_text, evidence_ids, rationale only"})
            continue
        seen.add(c["correction_id"])
        u = units.get(c.get("unit_id"))
        row.update({"unit_id": c.get("unit_id"), "proposed_text": c["proposed_text"].strip(), "evidence_ids": list(c.get("evidence_ids", [])),
                    "rationale": c.get("rationale", ""), "provenance": {"agent": ret["agent"], "context_id": ctx["context_id"],
                                                                         "correction_id": c["correction_id"], "source": ctx["source"]}})
        if u is None:
            row.update({"class": "unknown_unit", "why": f"{c.get('unit_id')} is not a unit of this packet"})
        elif not row["evidence_ids"] or not set(row["evidence_ids"]) <= evid:
            row.update({"class": "uncited", "why": "cites no evidence of this packet; the learner's own words must support a correction"})
        elif row["proposed_text"] == u["text"]:
            row.update({"class": "duplicate", "why": "equal to the current text"})
        elif now is not None and (c["unit_id"] not in now or now[c["unit_id"]]["state"] not in lp.USABLE
                                  or now[c["unit_id"]]["material_hash"] != u["material_hash"]):
            st = now.get(c["unit_id"], {}).get("state", "absent")
            row.update({"class": "outdated", "why": f"the unit is {st} or changed since this packet: export a new packet and ask again"})
        else:
            row.update({"class": "candidate", "current_text": u["text"], "why": "waits for your decision; nothing is applied"})
        rows.append(row)
    counts = {c: sum(1 for r in rows if r["class"] == c) for c in CLASSES}
    return {"schema": "flh_agent_corrections_preview_v1", "context_id": ctx["context_id"], "agent": ret["agent"], "applied": False,
            "checked_against": "current review" if res_now else "the packet only (pass the current review to find outdated corrections)",
            "rows": rows, "counts": counts}


def accept(preview: dict, correction_id: str, drf_now: dict, res_now: dict, seq: int, reason: str = "") -> dict:
    """The learner's explicit acceptance of one candidate: an ordinary edit decision with ``via`` provenance (returned, not written)."""
    row = next((r for r in preview["rows"] if r.get("correction_id") == correction_id), None)
    if row is None or row["class"] != "candidate":
        raise ExchangeError("not_a_candidate", f"{correction_id} is not a candidate in this preview", "preview the return again against the current review")
    it = next(i for i in res_now["items"] if i["item_id"] == row["unit_id"])
    d = pr.decision(drf_now, row["unit_id"], "edit", seq, row["proposed_text"], reason or row["rationale"],
                    via={**row["provenance"], "evidence_ids": row["evidence_ids"], "accepted_by": "learner"})
    d["based_on"]["draft_id"], d["based_on"]["material_hash"] = drf_now["draft_id"], it["material_hash"]
    return d


def render_preview(pv: dict) -> str:
    L = [f"Return from {pv['agent']} for {pv['context_id']} (checked against {pv['checked_against']}); applied: {pv['applied']}"]
    L += [f"  {r['n']} {r.get('correction_id') or '?':4} {r['class']:12} {r.get('unit_id', '')}: {r['why']}" for r in pv["rows"]]
    L.append("  counts: " + ", ".join(f"{k} {v}" for k, v in pv["counts"].items() if v))
    return "\n".join(L) + "\n"


def _work(path: str):
    from . import practice22 as p22
    w = p22.Work2(path)
    return w.resolved(), w.practice(), w.sources()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="flh_extraction.exchange")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("export")
    q.add_argument("--work", required=True); q.add_argument("--practice-id", required=True); q.add_argument("--out", required=True)
    q.add_argument("--include-goal", action="store_true"); q.add_argument("--last-outcome")
    q = sub.add_parser("markdown")
    q.add_argument("--context", required=True); q.add_argument("--agent", default="any-agent")
    q = sub.add_parser("import-preview")
    q.add_argument("--context", required=True); q.add_argument("--return", dest="ret", required=True); q.add_argument("--work"); q.add_argument("--json")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "export":
            res, prac, srcs = _work(a.work)
            ctx = export(res, prac, srcs, a.practice_id, a.include_goal, a.last_outcome)
            if os.path.exists(a.out):
                raise ExchangeError("exists", f"{a.out} exists", "choose a new file name")
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.write(pr.dumps(ctx))
            print(f"wrote {a.out} ({ctx['context_id']})")
            return 0
        with open(a.context, encoding="utf-8") as fh:
            try:
                ctx = json.load(fh)
            except ValueError:
                raise ExchangeError("malformed_context", "the packet is not JSON",
                                    "export a new packet: python3 -B -m flh_extraction.exchange export --work DIR --practice-id P --out NEW.json") from None
        if a.cmd == "markdown":
            sys.stdout.write(markdown(ctx, a.agent))
            return 0
        with open(a.ret, encoding="utf-8") as fh:
            raw = fh.read()
        pv = import_preview(ctx, raw, _work(a.work)[0] if a.work else None)
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                fh.write(pr.dumps(pv))
        sys.stdout.write(render_preview(pv))
        return 0
    except ExchangeError as e:
        sys.stderr.write(f"refused ({e.code}): {e.message}\nrecovery: {e.recovery}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
