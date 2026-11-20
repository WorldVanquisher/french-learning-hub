"""Agent exercise proposals (Extraction 2.2; PROTOTYPE, offline, standard library only).

An agent that used a study packet may propose a new exercise. The round trip:

  agent return (``flh_agent_proposals_v2``; each exercise is ``flh_exercise_proposal_v1``)
    -> ``preview`` (read-only): one class per proposal, the expected answer, accepted
       variants, rubric and every ambiguity (declared by the agent or found by a check)
    -> the learner's ``decide`` (approve, optionally editing the wording and the variants,
       or reject), recorded as ``flh_practice_exercise_decision_v1`` (append-only)
    -> ``practice_items``: approved exercises join practice while their rule is approved.

Rules:
* An exercise cites one **rule**: an approved claim or contrast (``rule_id``) of the packet,
  and the packet's **source revision**. A rule that is no longer approved (changed,
  rejected) makes the proposal ``withdrawn``, with the command that fixes it.
* Kinds: ``explanation`` (unaided recall), ``discrimination`` (choose between forms) and
  ``production`` (a sentence). They map to the practice kinds explain, choose and produce.
* **Agent output is never evidence.** An exercise keeps only the packet's own evidence IDs it
  cites; its rationale and the agent's identity are provenance. Its support is
  ``agent_proposed``, never ``supported``.
* **Idempotent.** A decision is keyed by (agent, packet, proposal); repeating the same
  decision writes nothing, a different one is refused. The practice ID hashes the rule, the
  kind and the proposed prompt, so the same exercise proposed twice (by one agent or two)
  is a duplicate, never a second exercise.
"""

from __future__ import annotations

import re

from . import practice as pr

RETURN_V1 = "flh_agent_proposals_v1"
RETURN_V2 = "flh_agent_proposals_v2"
RETURNS = (RETURN_V1, RETURN_V2)
PROPOSAL = "flh_exercise_proposal_v1"
DECISION = "flh_practice_exercise_decision_v1"
KINDS = {"explanation": "explain", "discrimination": "choose", "production": "produce"}
MEASURES = {"explain": "unaided recall of the rule", "choose": "recognition between confusable forms", "produce": "production in a new sentence"}
GRADING = {"explain": "self_check", "choose": "exact", "produce": "accepted_variants_else_self_check"}
CLASSES = ("candidate", "decided", "duplicate", "withdrawn", "wrong_revision", "unknown_reference", "conflict", "invalid", "unsupported_version")
KID, EID = re.compile(r"k-[0-9a-f]{12}"), re.compile(r"ev-[0-9a-f]{10}")
PROP_ID = re.compile(r"[A-Za-z0-9_.-]{1,32}")
TOP_FIELDS = {"schema", "packet_id", "agent", "proposals", "fixture_note"}
EX_FIELDS = {"proposal_id", "type", "exercise_schema", "kind", "rule_id", "knowledge_ids", "source", "prompt", "options", "answer", "accepted",
             "rubric", "reference", "ambiguity", "rationale", "evidence_ids"}
CORR_FIELDS = {"proposal_id", "type", "target_id", "text", "rationale", "evidence_ids"}


def check_return(ret) -> dict:
    """Format checks before any classification: version, unknown fields, malformed IDs."""
    if not isinstance(ret, dict):
        raise ValueError("an agent return must be one JSON object")
    v = ret.get("schema")
    if v not in RETURNS:
        raise ValueError(f"unsupported return format {v!r}: this FLH reads {', '.join(RETURNS)}. Ask the agent to answer in the format that "
                         "packet.md describes under 'How to return proposals' (the packet names its version)")
    if not isinstance(ret.get("proposals"), list):
        raise ValueError("an agent return needs a proposals list")
    warnings = [f"unknown top-level field {k!r} ignored" for k in sorted(set(ret) - TOP_FIELDS)]
    for k, p in enumerate(ret["proposals"]):
        if isinstance(p, dict):
            known = EX_FIELDS if p.get("type") == "exercise" else CORR_FIELDS
            warnings += [f"proposal {p.get('proposal_id', '#' + str(k + 1))}: unknown field {f!r} ignored" for f in sorted(set(p) - known)]
    return {"version": v, "warnings": warnings}


def _rule_forms(pk: dict, rule_id: str) -> list[str]:
    k = next((x for x in pk["knowledge"] if x["id"] == rule_id), None)
    return [f["form"] for f in (k or {}).get("forms", [])]


def ambiguities(pk: dict, x: dict, kind: str) -> list[str]:
    """Checks that find a possibly ambiguous answer rule (word checks only)."""
    out = [f"declared by the agent: {a}" for a in (x.get("ambiguity") or []) if isinstance(a, str) and a.strip()]
    ans = x.get("answer") or ""
    if ans and pr.fr_norm(ans) and f" {pr.fr_norm(ans)} " in f" {pr.fr_norm(x.get('prompt', ''))} " and kind == "produce":
        out.append("the prompt already contains the expected answer")
    if kind == "choose":
        opts = [pr.fr_norm(o) for o in x.get("options") or []]
        if len(set(opts)) != len(opts):
            out.append("two options are the same after normalisation")
    if kind == "produce":
        acc = list(x.get("accepted") or [])
        norms = [pr.fr_norm(a) for a in acc]
        if len(set(norms)) != len(norms):
            out.append("some accepted variants are the same after normalisation")
        if len(set(norms)) <= 1:
            out.append("only one accepted answer: any other correct sentence will be graded 'check it yourself'")
        forms = _rule_forms(pk, x.get("rule_id", ""))
        used = {f for f in forms for a in norms if f" {pr.fr_norm(f)} " in f" {a.replace(chr(39), ' ')} "}
        if len(forms) == 2 and used == set(forms):
            out.append(f"the accepted variants use both « {forms[0]} » and « {forms[1]} »: check that the rule allows both here")
    return out


def practice_id(rule_id: str, kind: str, prompt: str) -> str:
    return "p-" + pr.sha("\x1f".join(["agent_exercise", rule_id, kind, pr.fr_norm(prompt)]))[:12]


def preview(pk: dict, ret: dict, res: dict | None = None, decided: list[dict] | None = None) -> dict:
    """Classify every exercise proposal of a return against the packet (and, when given, the
    learner's current resolution and earlier exercise decisions). Read-only."""
    fmt = check_return(ret)
    know = {k["id"]: k for k in pk["knowledge"]}
    eids = {e["evidence_id"] for e in pk["evidence"]}
    wrong = {pr.fr_norm(c["wrong"]) for c in pk.get("known_confusions", [])}
    states = {i["item_id"]: i["state"] for i in (res or {}).get("items", [])}
    taken = {pr.fr_norm(x["prompt"]): f"exercise {x['id']} of the packet" for x in pk["next_exercises"]}
    for d in decided or []:
        if d["action"] == "approve":
            taken.setdefault(pr.fr_norm(d["proposal"]["prompt"]), f"exercise {d['practice_id']} you accepted from {d['proposal']['agent']}")
            taken.setdefault(pr.fr_norm(d["final"]["prompt"]), f"exercise {d['practice_id']} you accepted from {d['proposal']['agent']}")
    rows = []
    for k, x in enumerate(ret["proposals"]):
        if not isinstance(x, dict) or x.get("type") != "exercise":
            continue
        pid = x.get("proposal_id")
        row = {"proposal_id": pid if isinstance(pid, str) else f"#{k + 1}", "type": "exercise"}
        if fmt["version"] != RETURN_V2 or x.get("exercise_schema") != PROPOSAL:
            rows.append({**row, "class": "unsupported_version",
                         "why": f"an exercise needs return {RETURN_V2} and exercise_schema {PROPOSAL} (got {fmt['version']}, {x.get('exercise_schema')!r})"})
            continue
        prev = next((d for d in decided or [] if (d["proposal"]["agent"], d["proposal"]["packet_id"], d["proposal"]["proposal_id"])
                     == (str(ret.get("agent", "unknown")), pk["packet_id"], pid)), None)
        if prev:
            rows.append({**row, "class": "decided", "why": (f"you accepted it as {prev['practice_id']} (decision {prev['seq']})" if prev["action"] == "approve"
                                                            else f"you rejected it (decision {prev['seq']}): {prev['reason'] or 'no reason given'}")})
            continue
        kind = KINDS.get(x.get("kind"))
        need = ["proposal_id", "kind", "rule_id", "source", "prompt", "rationale"]
        bad = [f for f in need if not x.get(f)] + ([] if isinstance(x.get("evidence_ids"), list) else ["evidence_ids"])
        if kind is None or bad or not PROP_ID.fullmatch(str(pid)):
            rows.append({**row, "class": "invalid", "why": "needs proposal_id (letters, digits, . _ -), kind (explanation | discrimination | production), "
                                                            "rule_id, source, prompt, rationale and an evidence_ids list" + (f"; missing {', '.join(bad)}" if bad else "")})
            continue
        if kind == "choose" and not (isinstance(x.get("options"), list) and len(x["options"]) >= 2 and x.get("answer")):
            rows.append({**row, "class": "invalid", "why": "a discrimination needs at least two options and the answer"})
            continue
        if kind == "produce" and not (x.get("answer") and isinstance(x.get("accepted"), list) and x["accepted"] and x.get("rubric")):
            rows.append({**row, "class": "invalid", "why": "a production needs the answer, a non-empty accepted list and a rubric"})
            continue
        if kind == "explain" and not x.get("reference"):
            rows.append({**row, "class": "invalid", "why": "an explanation needs a reference (what a complete answer says)"})
            continue
        ids = [x["rule_id"]] + list(x.get("knowledge_ids") or [])
        malformed = [i for i in ids if not KID.fullmatch(str(i))] + [e for e in x["evidence_ids"] if not EID.fullmatch(str(e))]
        if malformed:
            rows.append({**row, "class": "invalid", "why": f"malformed IDs: {', '.join(map(str, malformed))}"})
            continue
        s = x["source"] if isinstance(x["source"], dict) else {}
        if (s.get("source_id"), s.get("revision"), s.get("revision_sha256")) != (pk["source"]["source_id"], pk["source"]["revision"], pk["source"]["revision_sha256"]):
            rows.append({**row, "class": "wrong_revision", "why": f"the proposal names source {s.get('source_id')} revision {s.get('revision')}; this packet is "
                                                                   f"{pk['source']['source_id']} revision {pk['source']['revision']}. Ask the agent to use the packet it was given"})
            continue
        unknown = [i for i in ids if i not in know] + [e for e in x["evidence_ids"] if e not in eids]
        if unknown:
            rows.append({**row, "class": "unknown_reference", "why": "not in the packet: " + ", ".join(unknown)})
            continue
        if know[x["rule_id"]]["type"] not in ("claim", "contrast"):
            rows.append({**row, "class": "invalid", "why": f"rule_id {x['rule_id']} is a {know[x['rule_id']]['type']}; cite an approved claim or contrast"})
            continue
        gone = [i for i in ids if res is not None and states.get(i) not in ("approved", "corrected")]
        if gone:
            rows.append({**row, "class": "withdrawn", "why": f"{', '.join(gone)} is no longer approved knowledge in revision {res['source']['revision']} "
                                                              f"({', '.join(states.get(i, 'absent') for i in gone)}). To use this exercise: decide on "
                                                              f"{gone[0]} in practice2 review, export a new packet, and ask for the exercise again"})
            continue
        np = pr.fr_norm(x["prompt"])
        if np in taken:
            rows.append({**row, "class": "duplicate", "why": f"the same prompt is already {taken[np]}"})
            continue
        taken[np] = f"proposed as {row['proposal_id']} in this return"
        answers = [x.get("answer", "")] + list(x.get("accepted") or [])
        badans = [a for a in answers if a and any(w and f" {w} " in f" {pr.fr_norm(a)} " for w in wrong)]
        if kind == "choose" and x["answer"] not in x["options"]:
            rows.append({**row, "class": "conflict", "why": "the answer is not one of the options"})
            continue
        if badans:
            rows.append({**row, "class": "conflict", "why": f"an expected answer uses a known confusion of the packet: {badans[0]!r}"})
            continue
        rows.append({**row, "class": "candidate", "kind": x["kind"], "practice_kind": kind, "rule_id": x["rule_id"], "prompt": x["prompt"],
                     "answer": x.get("answer"), "options": x.get("options"), "accepted": x.get("accepted"), "rubric": x.get("rubric"),
                     "reference": x.get("reference"), "ambiguity": ambiguities(pk, x, kind), "evidence_ids": x["evidence_ids"],
                     "rationale": x["rationale"], "practice_id": practice_id(x["rule_id"], kind, x["prompt"]),
                     "provenance_only": "the agent's rationale and identity are provenance; only the packet's evidence IDs it cites are evidence"})
    return {"schema": "flh_agent_exercise_preview_v1", "packet_id": pk["packet_id"], "agent": str(ret.get("agent", "unknown")),
            "packet_matches": ret.get("packet_id") == pk["packet_id"], "read_only": True, "warnings": fmt["warnings"],
            "counts": {c: sum(1 for r in rows if r["class"] == c) for c in CLASSES}, "rows": rows,
            "note": "nothing was applied: a candidate becomes practice only by your explicit decision (practice2 exercise --approve)"}


def decide(pk: dict, ret: dict, proposal_id: str, action: str, seq: int, res: dict, decided: list[dict],
           edits: dict | None = None, reason: str = "") -> tuple[dict, bool]:
    """(decision record, written?) for one exercise proposal. Repeating an identical decision is a no-op."""
    if action not in ("approve", "reject"):
        raise ValueError("an exercise decision is approve or reject")
    prop = next((p for p in ret.get("proposals", []) if isinstance(p, dict) and p.get("proposal_id") == proposal_id and p.get("type") == "exercise"), None)
    if prop is None:
        raise ValueError(f"no exercise proposal {proposal_id!r} in the return")
    if ret.get("packet_id") != pk["packet_id"]:
        raise ValueError(f"the return names packet {ret.get('packet_id')!r}, not {pk['packet_id']}")
    agent = str(ret.get("agent", "unknown"))
    key = (agent, pk["packet_id"], proposal_id)
    earlier = next((d for d in decided if (d["proposal"]["agent"], d["proposal"]["packet_id"], d["proposal"]["proposal_id"]) == key), None)
    edits = {k: v for k, v in (edits or {}).items() if v not in (None, [], "")}
    if earlier:
        same = earlier["action"] == action and (action == "reject" or earlier["edited"] == sorted(edits) and all(earlier["final"].get(k) == v for k, v in edits.items()))
        if same:
            return earlier, False
        raise ValueError(f"proposal {proposal_id} from {agent} was already decided (decision {earlier['seq']}: {earlier['action']}); "
                         "a different decision on the same proposal is refused")
    rep = preview(pk, ret, res, decided)
    row = next(r for r in rep["rows"] if r["proposal_id"] == proposal_id)
    if action == "approve" and row["class"] != "candidate":
        raise ValueError(f"proposal {proposal_id} is {row['class']}: {row.get('why', '')}")
    kind = KINDS.get(prop.get("kind"), "explain")
    final = {k: prop[k] for k in ("prompt", "options", "answer", "accepted", "rubric", "reference") if prop.get(k) is not None}
    final.update(edits)
    if action == "approve":
        if kind == "choose" and final.get("answer") not in (final.get("options") or []):
            raise ValueError("after your edit the answer is not one of the options")
        if kind == "produce":
            if not final.get("accepted"):
                raise ValueError("a production needs at least one accepted variant")
            if final["answer"] not in final["accepted"]:
                final["accepted"] = [final["answer"]] + list(final["accepted"])
            wrong = {pr.fr_norm(c["wrong"]) for c in pk.get("known_confusions", [])}
            bad = [a for a in final["accepted"] if any(w and f" {w} " in f" {pr.fr_norm(a)} " for w in wrong)]
            if bad:
                raise ValueError(f"after your edit an accepted variant uses a known confusion: {bad[0]!r}")
    rec = {"schema": DECISION, "seq": seq, "action": action, "reason": reason,
           "proposal": {"agent": agent, "packet_id": pk["packet_id"], "proposal_id": proposal_id, "prompt": prop.get("prompt", ""),
                        "content_sha256": pr.sha(pr.canon(prop)), "rationale": prop.get("rationale", ""), "class_at_decision": row["class"]},
           "rule_id": prop.get("rule_id"), "knowledge_ids": [prop.get("rule_id")] + list(prop.get("knowledge_ids") or []), "kind": kind,
           "source": {k: pk["source"][k] for k in ("source_id", "revision", "revision_sha256")},
           "evidence_ids": [e for e in prop.get("evidence_ids") or [] if e in {x["evidence_id"] for x in pk["evidence"]}],
           "edited": sorted(edits), "final": final, "practice_id": practice_id(prop.get("rule_id", ""), kind, prop.get("prompt", ""))}
    return rec, True


def practice_items(res: dict, decided: list[dict], source_text: str = "") -> tuple[list[dict], list[dict]]:
    """(practice items, suspended) from approved exercise decisions. An exercise is offered only while
    every knowledge ID it cites is approved now; it never carries evidence the learner's source lacks."""
    ok = {i["item_id"] for i in pr.approved(res)}
    ev = {e["evidence_id"]: e for e in res["evidence"]}
    items, suspended = [], []
    for d in sorted((d for d in decided if d["action"] == "approve"), key=lambda d: d["seq"]):
        missing = [k for k in d["knowledge_ids"] if k not in ok]
        if missing:
            suspended.append({"practice_id": d["practice_id"], "proposal_id": d["proposal"]["proposal_id"], "agent": d["proposal"]["agent"],
                              "why": f"{', '.join(missing)} is not approved in revision {res['source']['revision']}: not offered until it is"})
            continue
        f, kind = d["final"], d["kind"]
        refs = [e for e in d["evidence_ids"] if e in ev]
        hidden = {"explanation": f.get("rubric") or f.get("reference") or "", "excerpts": [{"evidence_id": e, "excerpt": ev[e]["excerpt"]} for e in refs]}
        if kind == "choose":
            hidden["answer"] = f["answer"]
        elif kind == "produce":
            hidden.update({"answer": f["answer"], "accepted": f["accepted"], "known_errors": []})
        else:
            hidden["reference"] = [f.get("reference", "")]
        p = {"practice_id": d["practice_id"], "kind": kind, "measures": MEASURES[kind], "prompt": f["prompt"], "knowledge_ids": d["knowledge_ids"],
             "evidence_ids": refs, "new_sentence": (pr.fr_norm(f["prompt"]) not in pr.fr_norm(source_text)) if kind != "explain" else None,
             "grading": GRADING[kind], "origin": "agent_proposal",
             "provenance": {"agent": d["proposal"]["agent"], "packet_id": d["proposal"]["packet_id"], "proposal_id": d["proposal"]["proposal_id"],
                            "decision_seq": d["seq"], "accepted_by": "learner", "edited_by_learner": d["edited"]},
             "support": "agent_proposed", "hidden": hidden}
        if kind == "choose":
            p["options"] = f["options"]
        items.append(p)
    return items, suspended


def render_preview(rep: dict) -> str:
    L = [f"Exercise proposals (read-only) for packet {rep['packet_id']} from {rep['agent']}"
         + ("" if rep["packet_matches"] else "  WARNING: the return names another packet_id"),
         "counts: " + ", ".join(f"{k} {v}" for k, v in rep["counts"].items() if v)]
    L += [f"  warning: {w}" for w in rep["warnings"]]
    for r in rep["rows"]:
        if r["class"] != "candidate":
            L.append(f"  {r['class']:17} {r['proposal_id']:6} {r.get('why', '')}")
            continue
        L.append(f"  candidate         {r['proposal_id']:6} {r['kind']} for rule {r['rule_id']} -> would be {r['practice_id']}")
        L.append(f"      prompt    {r['prompt']}" + (f"   options: {' / '.join(r['options'])}" if r.get("options") else ""))
        if r.get("answer"):
            L.append(f"      answer    {r['answer']}")
        if r.get("accepted"):
            L.append(f"      accepted  {' | '.join(r['accepted'])}")
        if r.get("rubric") or r.get("reference"):
            L.append(f"      rubric    {r.get('rubric') or r.get('reference')}")
        L += [f"      ambiguity {a}" for a in r["ambiguity"]] or ["      ambiguity none found (word checks only)"]
        L.append(f"      evidence  {', '.join(r['evidence_ids']) or 'none cited'}; rationale (provenance, not evidence): {r['rationale']}")
    L.append(rep["note"])
    return "\n".join(L) + "\n"
