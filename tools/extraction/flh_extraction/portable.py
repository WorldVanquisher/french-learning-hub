"""Portable packets v3 and agent-neutral adapters (Extraction 2.2; PROTOTYPE, offline).

``flh_practice_packet_v3`` is packet v2 (``packet.export``) plus:
* ``variant``: ``full`` or ``minimal``. The minimal packet fits a short tutoring
  conversation: the goal, the rules of the contrast, the last confusion, the next exercise
  (never its answer) and the return format.
* ``omitted_by_learner``: fields the learner chose not to share in the share preview
  (``learner_goal``, ``evidence_text``, ``practice_history``, ``last_confusion``). The
  packet says what was omitted; it never fills the gap.
* ``exercise origins``: each exercise says whether it was built from the learner's source
  or proposed by an agent and accepted by the learner (with the agent and proposal).
* ``awaiting_learner``: proposals an agent made that the learner has previewed but not
  accepted. They are listed apart, labelled "proposed, not accepted", and are never
  knowledge.
* ``return_format`` names both return versions (corrections v1; exercises v2).

The packet is the same bytes for every agent: an adapter is only a prompt file. Packets v1
and v2 stay readable by the import previews.
"""

from __future__ import annotations

import os
import shutil

from . import exercises as ex
from . import packet as pk
from . import practice as pr

PACKET_SCHEMA_V3 = "flh_practice_packet_v3"
READABLE = (pk.PACKET_SCHEMA, pk.PACKET_SCHEMA_V2, PACKET_SCHEMA_V3)
VARIANTS = ("full", "minimal")
OMITTABLE = {"learner_goal": "the learner's goal", "evidence_text": "the quoted words and excerpts (evidence IDs stay)",
             "practice_history": "which exercises were missed", "last_confusion": "the last confusion"}
PROMPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "practice_prompts")
ADAPTERS = {"codex": "PROMPT-codex.md", "claude-code": "PROMPT-claude-code.md", "any-agent": "PROMPT-any-agent.md"}


def export3(res: dict, prac: dict, attempts: list[dict] | None = None, mode: str = "study", include_rubrics: bool = False,
            previous: dict | None = None, variant: str = "full", omit=(), awaiting: list[dict] | None = None) -> dict:
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}")
    bad = sorted(set(omit) - set(OMITTABLE))
    if bad:
        raise ValueError(f"cannot omit {', '.join(bad)}; omittable: {', '.join(sorted(OMITTABLE))}")
    if variant == "minimal" and include_rubrics:
        raise ValueError("a minimal packet never carries rubrics")
    prev = None
    if previous is not None:
        if previous.get("schema") not in READABLE:
            raise ValueError("--previous must be a practice packet")
        prev = {**previous, "schema": pk.PACKET_SCHEMA_V2}
    body = pk.export(res, prac, attempts, mode, include_rubrics, version=2, previous=prev)
    body.pop("packet_id")
    body["schema"] = PACKET_SCHEMA_V3
    origin = {p["practice_id"]: p for p in prac["items"]}
    for x in body["next_exercises"] + ([body["next_exercise"]] if body.get("next_exercise") else []):
        p = origin.get(x["id"], {})
        x["origin"] = p.get("origin", "source")
        if p.get("provenance"):
            x["accepted_from"] = {k: p["provenance"][k] for k in ("agent", "packet_id", "proposal_id")}
    body["exercises_not_offered"] = [{k: x[k] for k in ("practice_id", "proposal_id", "agent", "why")}
                                     for x in prac.get("from_agents", {}).get("suspended", [])]
    body["awaiting_learner"] = [{**a, "status": "proposed by an agent, not accepted by the learner: not knowledge"} for a in (awaiting or [])]
    body["return_format"]["schemas"] = {"corrections": ex.RETURN_V1, "exercises": ex.RETURN_V2}
    body["return_format"]["exercise"] = {"exercise_schema": ex.PROPOSAL, "kind": "explanation | discrimination | production",
                                         "rule_id": "an approved claim or contrast k-… of this packet",
                                         "source": "this packet's source object, unchanged",
                                         "discrimination": "options and answer", "production": "answer, accepted (all valid variants) and rubric",
                                         "explanation": "reference", "ambiguity": "optional: any case where the rule allows more than one answer"}
    if "learner_goal" in omit:
        body["learner_goal"] = None
    if "evidence_text" in omit:
        body["evidence"] = [{k: e[k] for k in ("evidence_id", "source_revision", "status")} for e in body["evidence"]]
    if "practice_history" in omit:
        body["observed_in_practice"] = []
        for x in body["next_exercises"]:
            x.pop("missed_in_practice", None)
        for c in body["known_confusions"]:
            c.pop("missed_in_practice", None)
        if body.get("continuity"):
            body["continuity"]["new_misses"] = []
    if "last_confusion" in omit:
        body["last_confusion"] = None
    body["omitted_by_learner"] = sorted(omit)
    body["variant"] = variant
    if variant == "minimal":
        body = _minimal(body)
    body["packet_id"] = "pk-" + pr.sha(pr.canon(body))[:12]
    found = pk.privacy_findings(pr.dumps(body) + markdown3(body))
    if found:
        raise PermissionError("the packet would share private data: " + "; ".join(f"line {f['line']}: {f['kind']}" for f in found))
    return body


def _minimal(b: dict) -> dict:
    rules = [k for k in b["knowledge"] if k["type"] in ("contrast", "claim")]
    contrast = next((k for k in rules if k["type"] == "contrast"), None)
    keep = [contrast] if contrast else []
    keep += [k for k in rules if k["type"] == "claim" and (not contrast or k["id"] in _applies(b, contrast))][:2]
    keep = [k for k in keep if k] or rules[:3]
    nx = b.get("next_exercise")
    return {"schema": b["schema"], "variant": "minimal", "mode": b["mode"], "rubrics_included": False, "concept": b["concept"],
            "learner_goal": b["learner_goal"], "language_level": b["language_level"], "source": b["source"],
            "knowledge": [{k2: v for k2, v in k.items() if k2 in ("id", "type", "text", "forms", "origin", "evidence_ids", "accepted_from")} for k in keep],
            "last_confusion": b.get("last_confusion"), "next_exercise": nx,
            "agent_rules": b["agent_rules"], "return_format": {"schemas": b["return_format"]["schemas"], "proposal_types": b["return_format"]["proposal_types"]},
            "omitted_by_learner": b["omitted_by_learner"],
            "not_in_minimal": ["evidence excerpts (IDs only)", "worked examples and known confusions", "other exercises", "continuity details"],
            "excluded_by_default": b["excluded_by_default"]}


def _applies(b: dict, contrast: dict) -> set:
    return set(k["id"] for k in b["knowledge"] if k["type"] == "claim")


def markdown3(p: dict) -> str:
    if p.get("variant") == "minimal":
        goal = "(omitted by the learner)" if "learner_goal" in p["omitted_by_learner"] else (p["learner_goal"] or "(none given)")
        L = [f"# FLH practice packet {p.get('packet_id', '(unsealed)')} (minimal) — {p['concept']}", "",
             f"Source `{p['source']['source_id']}` revision {p['source']['revision']}. Level: {p['language_level']}. Mode: {p['mode']}. "
             "A short version for a quick tutoring conversation.", "", "## Learner goal", "", goal, "", "## Where we left off", ""]
        lc, nx = p.get("last_confusion"), p.get("next_exercise")
        if lc:
            L.append(f"- Last confusion: {' vs '.join(f'« {f} »' for f in lc['forms'])} on `{lc['practice_id']}` (the answers are not shared).")
        L.append(f"- Next exercise: `{nx['id']}` {nx['kind']}: {nx['prompt']}" + (f" Options: {' / '.join(nx['options'])}." if nx.get("options") else "")
                 if nx else "- Next exercise: none (ask the learner what to practise)")
        L += ["", "## Approved knowledge", ""]
        L += [f"- `{k['id']}` ({k['type']}): {k['text']}" + (f" (accepted from {k['accepted_from']['agent']})" if k.get("accepted_from") else "")
              for k in p["knowledge"]]
        L += ["", "## Rules for an agent using this packet", ""] + [f"{n}. {r}" for n, r in enumerate(p["agent_rules"], 1)]
        L += ["", "## How to return proposals", "", f"One JSON object with `\"packet_id\": \"{p.get('packet_id', '')}\"`: corrections in "
              f"`{p['return_format']['schemas']['corrections']}`, new exercises in `{p['return_format']['schemas']['exercises']}` "
              "(the full packet describes both formats)."]
        if p["omitted_by_learner"]:
            L += ["", "Omitted by the learner: " + ", ".join(OMITTABLE[o] for o in p["omitted_by_learner"]) + "."]
        L += ["", "Not in this minimal packet: " + "; ".join(p["not_in_minimal"]) + "."]
        return "\n".join(L) + "\n"
    v2 = {**p, "schema": pk.PACKET_SCHEMA_V2, "learner_goal": p["learner_goal"] or ("(omitted by the learner)" if "learner_goal" in p["omitted_by_learner"] else "")}
    v2["evidence"] = [{**e, "excerpt": e.get("excerpt", "(text omitted by the learner)")} for e in p["evidence"]]
    v2["observed_in_practice"] = [{**o} for o in p["observed_in_practice"]]
    v2["known_confusions"] = [{**c, "missed_in_practice": c.get("missed_in_practice", "not shared")} for c in p["known_confusions"]]
    text = pk.markdown(v2)
    text = text.replace("# FLH practice packet", "# FLH practice packet (v3)", 1)
    extra = ["## Origin of each exercise", ""]
    for x in p["next_exercises"]:
        extra.append(f"- `{x['id']}`: " + (f"proposed by {x['accepted_from']['agent']} (`{x['accepted_from']['proposal_id']}`), accepted by the learner"
                                           if x["origin"] == "agent_proposal" else "built from the learner's approved knowledge"))
    if p.get("exercises_not_offered"):
        extra += ["", "## Accepted exercises not offered now", ""]
        extra += [f"- `{x['practice_id']}` ({x['agent']} `{x['proposal_id']}`): {x['why']}" for x in p["exercises_not_offered"]]
    extra += ["", "## Proposed by an agent, NOT accepted by the learner (not knowledge)", ""]
    extra += [f"- {a['agent']} `{a['proposal_id']}` ({a['type']}): {a['summary']} — {a['status']}" for a in p["awaiting_learner"]] or ["- none"]
    if p["omitted_by_learner"]:
        extra += ["", "## Omitted by the learner", ""] + [f"- {OMITTABLE[o]}" for o in p["omitted_by_learner"]]
    head = text.split("## Use it in a fresh agent session", 1)[0]
    extra += ["", "## Use it in a fresh agent session", "",
              "1. Make an empty directory and copy `packet.md`, `packet.json` and the prompt for your agent into it: `PROMPT-codex.md`, "
              "`PROMPT-claude-code.md`, or `PROMPT-any-agent.md` for any other agent that reads Markdown.",
              "2. Codex: `codex --sandbox workspace-write \"$(cat PROMPT-codex.md)\"`",
              "3. Claude Code: `claude \"$(cat PROMPT-claude-code.md)\"`",
              "4. Back in FLH, preview what the agent returned (read-only): "
              "`python3 -B -m flh_extraction practice2 import-preview --packet packet.json --proposals proposals.json`",
              "", "## How to return proposals", "",
              f"Return one JSON object with `\"packet_id\": \"{p.get('packet_id', '')}\"`, `\"agent\"` (your tool's short name) and a `proposals` "
              f"list. With corrections only, use `\"schema\": \"{ex.RETURN_V1}\"`; with any exercise, use `\"schema\": \"{ex.RETURN_V2}\"`. "
              "Every proposal has `proposal_id`, `type` (`correction` or `exercise`), `rationale` and `evidence_ids` (packet IDs only; leave "
              "it empty and say so in the rationale when the packet does not support the proposal). A correction names `target_id` and `text`.",
              "",
              f"An exercise has `\"exercise_schema\": \"{ex.PROPOSAL}\"`, `kind` (explanation, discrimination or production), `rule_id` "
              "(an approved claim or contrast above), `source` (copy this packet's source object), `prompt`; a discrimination adds `options` and "
              "`answer`, a production `answer`, `accepted` (every valid variant) and `rubric`, an explanation `reference`. List any case where "
              "the rule allows more than one answer under `ambiguity`.", ""]
    return head + "\n".join(extra)


def preview3(p: dict) -> str:
    L = [f"Share preview ({p['schema']}, {p['variant']}, {p['mode']} mode) {p['packet_id']}: nothing has been written yet."]
    if p["variant"] == "minimal":
        L.append(f"  rules              {len(p['knowledge'])}: " + ", ".join(k["id"] for k in p["knowledge"]))
        L.append(f"  next exercise      {p['next_exercise']['id']} {p['next_exercise']['kind']} (no answer)" if p.get("next_exercise") else "  next exercise      none")
        L.append("  not in minimal     " + "; ".join(p["not_in_minimal"]))
    else:
        L.append(f"  knowledge          {len(p['knowledge'])}: " + ", ".join(f"{k['id']} ({k['origin']})" for k in p["knowledge"]))
        L.append(f"  evidence           {len(p['evidence'])}" + (" IDs only (text omitted by you)" if "evidence_text" in p["omitted_by_learner"] else " with excerpts"))
        L.append(f"  exercises          {len(p['next_exercises'])}: " + ", ".join(f"{x['id']} {x['kind']} ({x['origin']})" for x in p["next_exercises"]))
        L.append(f"  awaiting learner   {len(p['awaiting_learner'])} (proposed, not accepted; never knowledge)")
        L.append(f"  answer keys        {'included (your explicit choice)' if p['rubrics_included'] else 'not included'}")
    L.append(f"  goal               {'omitted by you' if 'learner_goal' in p['omitted_by_learner'] else (p['learner_goal'] or '')[:70]}")
    L.append(f"  last confusion     {'omitted by you' if 'last_confusion' in p['omitted_by_learner'] else ('shared (forms and exercise only)' if p.get('last_confusion') else 'none')}")
    more = [f"--omit {k}" for k in sorted(OMITTABLE) if k not in p["omitted_by_learner"]]
    L.append("  you may omit       " + (", ".join(more) if more else "nothing more"))
    L.append("  privacy check      0 findings (a finding would have refused the export)")
    return "\n".join(L) + "\n"


def write_packet3(p: dict, out: str, agent: str | None = None) -> list[str]:
    """packet.json, packet.md and the adapter prompts (one agent's, or all three) into a new or empty directory."""
    if os.path.exists(out) and os.listdir(out):
        raise ValueError("the packet directory must be new or empty")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "packet.json"), "w", encoding="utf-8") as fh:
        fh.write(pr.dumps(p))
    with open(os.path.join(out, "packet.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown3(p))
    names = [ADAPTERS[agent]] if agent else sorted(ADAPTERS.values())
    for n in names:
        shutil.copyfile(os.path.join(PROMPTS, n), os.path.join(out, n))
    return sorted(os.listdir(out))


def normalized(text: str) -> list[str]:
    """Why a text is not in the packet's normal form (NFC, LF only, no trailing spaces, final newline)."""
    import unicodedata
    out = []
    if unicodedata.normalize("NFC", text) != text:
        out.append("not NFC")
    if "\r" in text:
        out.append("CR line ends")
    if any(line != line.rstrip(" \t") for line in text.split("\n")):
        out.append("trailing spaces")
    if not text.endswith("\n"):
        out.append("no final newline")
    return out


def awaiting_from(rep_corrections: dict | None, rep_exercises: dict | None) -> list[dict]:
    """Proposals a learner previewed but did not accept, for ``awaiting_learner``."""
    out = []
    for r in (rep_corrections or {}).get("rows", []):
        if r["class"] == "accepted_candidate":
            out.append({"agent": rep_corrections["agent"], "proposal_id": r["proposal_id"], "type": "correction",
                        "summary": f"rewording of {r['target_id']}: {r['text']}"})
    for r in (rep_exercises or {}).get("rows", []):
        if r["class"] == "candidate":
            out.append({"agent": rep_exercises["agent"], "proposal_id": r["proposal_id"], "type": "exercise",
                        "summary": f"{r['kind']} for {r['rule_id']}: {r['prompt']}"})
    return out


def import_any(p: dict, ret: dict, res: dict | None = None, decided: list[dict] | None = None) -> dict:
    """Corrections (read by ``packet.import_preview``) and exercises (``exercises.preview``) of any
    readable packet version. Unknown fields are warnings; an unsupported return version is refused."""
    if p.get("schema") not in READABLE:
        raise ValueError(f"not a practice packet this FLH reads ({', '.join(READABLE)})")
    fmt = ex.check_return(ret)
    if fmt["version"] == ex.RETURN_V1:  # a 2.1 return: read exactly as 2.1 did
        return {"packet_schema": p["schema"], "return_version": fmt["version"], "warnings": fmt["warnings"],
                "corrections": pk.import_preview(p, ret), "exercises": None}
    corr = {**ret, "schema": pk.PROPOSALS_SCHEMA, "proposals": [x for x in ret["proposals"] if not (isinstance(x, dict) and x.get("type") == "exercise")]}
    out = {"packet_schema": p["schema"], "return_version": fmt["version"], "warnings": fmt["warnings"],
           "corrections": pk.import_preview(p, corr) if corr["proposals"] else None,
           "exercises": ex.preview(p, ret, res, decided) if any(isinstance(x, dict) and x.get("type") == "exercise" for x in ret["proposals"]) else None}
    return out


def render_import_any(rep: dict) -> str:
    L = [f"Import preview (read-only): packet {rep['packet_schema']}, return {rep['return_version']}"]
    L += [f"  warning: {w}" for w in rep["warnings"]]
    if rep["corrections"]:
        L.append(pk.render_import(rep["corrections"]).rstrip("\n"))
    if rep["exercises"]:
        L.append(ex.render_preview(rep["exercises"]).rstrip("\n"))
    if not (rep["corrections"] or rep["exercises"]):
        L.append("  no proposals")
    return "\n".join(L) + "\n"
