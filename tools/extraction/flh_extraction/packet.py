"""Portable context packets and agent returns (PROTOTYPE, offline, standard library only).

* ``export`` turns resolved knowledge, its practice and (optionally) attempt outcomes into
  one ``flh_practice_packet_v1`` document. The Markdown is rendered from that JSON only.
  - ``study``: the learner's goal, approved knowledge with its origin, evidence excerpts with
    stable IDs, known confusions and the next exercises. No answer keys, no rubrics.
  - ``tutor``: the same plus tutoring instructions. Answer keys and rubrics are added only
    when the learner explicitly passes ``include_rubrics``; otherwise the packet says they
    were withheld.
  By default it excludes rejected, pending and needs-review items, attempt texts, the full
  question and any chat. A privacy gate refuses a packet that contains machine-local paths,
  session links, e-mail addresses or credential-like strings.
* ``preview`` lists exactly what would be shared, before anything is written.
* ``import_preview`` reads an agent's ``flh_agent_proposals_v1`` return against the packet
  and classifies each proposal as an accepted candidate, a duplicate, a conflict, an unknown
  reference or invalid. It is read-only: it changes no knowledge, decision or practice.
* ``accept_correction`` (Extraction 2.1) is the learner's explicit acceptance of one
  correction that the preview classed as an accepted candidate. It returns the edit to
  record as an ordinary learner decision, with the agent, packet and proposal it came from.
* Packet v2 (``flh_practice_packet_v2``, the default since 2.1) adds where the learner left
  off: the last confusion (forms and exercise, never the attempt text or the answer), the
  next exercise under ``flh_next_exercise_rule_v1``, and, when a previous packet is given,
  what changed since it. v1 is still produced on request and is otherwise unchanged.
"""

from __future__ import annotations

import re

from . import practice as pr

PACKET_SCHEMA = "flh_practice_packet_v1"
PACKET_SCHEMA_V2 = "flh_practice_packet_v2"
VERSIONS = {1: PACKET_SCHEMA, 2: PACKET_SCHEMA_V2}
NEXT_RULE = "flh_next_exercise_rule_v1"
PROPOSALS_SCHEMA = "flh_agent_proposals_v1"
MODES = ("study", "tutor")
CLASSES = ("accepted_candidate", "duplicate", "conflict", "unknown_reference", "invalid")
EXCLUDED = ["rejected, pending and needs-review drafts", "the texts of your attempts (only counts of missed items)",
            "the full question, its context and any chat (only the cited excerpts)", "other sources and unrelated history",
            "credentials, machine-local paths, session links and e-mail addresses (checked)"]
PRIVATE = {
    # concatenated so this file does not match its own patterns
    "home_path": re.compile("/" + "home" + r"/[^/\s\"']+/"),
    "macos_home_path": re.compile("/" + "Users" + r"/[^/\s\"']+/"),
    "windows_user_path": re.compile(r"[A-Za-z]:\\" + "Users" + r"\\"),
    "session_link": re.compile(r"https?://(?:[a-z0-9-]+\.)?" + "claude" + r"\.ai/\S+"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "secret_like": re.compile(r"\b(?:" + "sk" + r"-[A-Za-z0-9_-]{16,}|" + "AKIA" + r"[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,})"),
    "private_key": re.compile("-----BEGIN " + r"[A-Z ]*PRIVATE KEY-----"),
}
TUTOR_RULES = ["Cite the evidence ID (ev-…) or knowledge ID (k-…) for every claim you make about the learner's material.",
               "Ask one question at a time and wait for the answer.",
               "Say clearly when something is NOT supported by the packet's evidence; never present it as the learner's material.",
               "Propose corrections and new exercises only in the flh_agent_proposals_v1 format; the learner decides."]


def privacy_findings(text: str) -> list[dict]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for name, rx in PRIVATE.items():
            for m in rx.finditer(line):
                out.append({"line": n, "kind": name, "match": m.group(0)[:24]})
    return out


def last_confusion(res: dict, prac: dict, attempts: list[dict]) -> dict | None:
    """The learner's latest incorrect attempt on an exercise of approved knowledge: which forms were
    confused and on which exercise. The attempt text and the expected answer are never included."""
    ok = {i["item_id"]: i for i in pr.approved(res)}
    items = {p["practice_id"]: p for p in prac["items"]}
    att = sorted(attempts or [], key=lambda a: a["seq"])
    for a in reversed([a for a in att if a.get("outcome") == "incorrect"]):
        p = items.get(a["practice_id"])
        if not p or not set(p["knowledge_ids"]) <= set(ok):
            continue
        contrast = next((k for k in p["knowledge_ids"] if ok[k]["type"] == "contrast"), None)
        forms = [ok[contrast]["effective"]["a"]["form"], ok[contrast]["effective"]["b"]["form"]] if contrast else []
        known = next((i["item_id"] for i in ok.values() if i["type"] == "common_error" and a.get("known_error")
                      and pr.fr_norm(i["effective"]["wrong"]) in pr.fr_norm(a["known_error"])), None)
        return {"practice_id": p["practice_id"], "kind": p["kind"], "prompt": p["prompt"], "knowledge_ids": p["knowledge_ids"],
                "contrast_id": contrast, "forms": forms, "attempt_seq": a["seq"], "known_confusion_id": known,
                "resolved_later": any(b["seq"] > a["seq"] and b["practice_id"] == p["practice_id"] and b.get("outcome") == "correct" for b in att),
                "shared": "which forms were confused, on which exercise; not the attempt text and not the expected answer"}
    return None


def next_exercise(exercises: list[dict], attempts: list[dict], last: dict | None) -> dict | None:
    """flh_next_exercise_rule_v1 over the packet's exercises (already limited to approved knowledge).
    After an unresolved miss: the same contrast in a different worked example, production before
    recognition, not yet answered correctly; else that contrast's explain item; else the missed one.
    Without a miss: the first exercise, in the packet's order, not yet answered correctly."""
    correct = {a["practice_id"] for a in attempts or [] if a.get("outcome") == "correct"}
    by_id = {x["id"]: x for x in exercises}
    pick, why = None, ""
    if last and not last["resolved_later"] and last["practice_id"] in by_id:
        missed = by_id[last["practice_id"]]
        cands = [x for x in exercises if last["contrast_id"] in x["knowledge_ids"] and x["kind"] != "explain"
                 and x["knowledge_ids"][0] != missed["knowledge_ids"][0] and x["id"] not in correct]
        cands.sort(key=lambda x: ({"produce": 0, "choose": 1}[x["kind"]], x["id"]))
        if cands:
            pick, why = cands[0], f"after the miss on {missed['id']}: the same contrast in a different sentence, production first"
        else:
            expl = [x for x in exercises if x["kind"] == "explain" and last["contrast_id"] in x["knowledge_ids"]]
            pick, why = (expl[0], f"after the miss on {missed['id']}: recall the rule itself") if expl else (missed, "retry the missed exercise")
    else:
        rest = [x for x in exercises if x["id"] not in correct]
        if rest:
            pick, why = rest[0], "the first exercise not yet answered correctly"
    if not pick:
        return None
    out = {k: pick[k] for k in ("id", "kind", "measures", "prompt", "knowledge_ids", "evidence_ids", "new_sentence") if k in pick}
    if pick.get("options"):
        out["options"] = pick["options"]
    return {**out, "why": why, "rule": NEXT_RULE}


def continuity(previous: dict, body: dict) -> dict:
    """What changed since the packet a previous session used (same source required)."""
    if previous.get("schema") not in VERSIONS.values():
        raise ValueError("--previous must be a practice packet")
    if previous["source"]["source_id"] != body["source"]["source_id"]:
        raise ValueError("the previous packet is about another source")
    old = {k["id"]: k for k in previous["knowledge"]}
    new = {k["id"]: k for k in body["knowledge"]}
    changed = []
    for i in sorted(set(old) & set(new)):
        if old[i]["text"] != new[i]["text"]:
            src = new[i].get("accepted_from")
            what = (f"corrected by the learner, who accepted proposal {src['proposal_id']} from {src['agent']} (packet {src['packet_id']})"
                    if src else "corrected by the learner" if new[i].get("learner_corrected") else "wording changed")
            changed.append({"id": i, "what": what})
    om = {o["practice_id"]: o["missed"] for o in previous.get("observed_in_practice", [])}
    new_misses = [{"practice_id": o["practice_id"], "missed_since": o["missed"] - om.get(o["practice_id"], 0)}
                  for o in body["observed_in_practice"] if o["missed"] > om.get(o["practice_id"], 0)]
    return {"previous_packet_id": previous["packet_id"], "same_source_revision": previous["source"]["revision_sha256"] == body["source"]["revision_sha256"],
            "knowledge_ids_kept": len(set(old) & set(new)), "knowledge_ids_added": sorted(set(new) - set(old)),
            "knowledge_ids_dropped": sorted(set(old) - set(new)), "changed": changed, "new_misses": new_misses}


def export(res: dict, prac: dict, attempts: list[dict] | None = None, mode: str = "study", include_rubrics: bool = False,
           concept: str | None = None, version: int = 2, previous: dict | None = None) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if version not in VERSIONS:
        raise ValueError(f"packet version must be one of {sorted(VERSIONS)}")
    if previous is not None and version < 2:
        raise ValueError("--previous needs a version 2 packet")
    if include_rubrics and mode != "tutor":
        raise ValueError("rubrics can only be included in a tutor packet")
    ok = pr.approved(res)
    ids = {i["item_id"] for i in ok}
    used_ev = sorted({e for i in ok for e in i["evidence_ids"]})
    ev = {e["evidence_id"]: e for e in res["evidence"]}
    missed: dict = {}
    for a in attempts or []:
        if a.get("outcome") == "incorrect":
            missed[a["practice_id"]] = missed.get(a["practice_id"], 0) + 1
    keyed = {}  # worked examples whose answer is the key to a listed exercise
    for p in prac["items"]:
        if set(p["knowledge_ids"]) <= ids and p["kind"] in ("choose", "produce"):
            keyed.setdefault(p["knowledge_ids"][0], []).append(p["practice_id"])
    knowledge = []
    for i in ok:
        f = pr.MAIN_TEXT[i["type"]]
        k = {"id": i["item_id"], "type": i["type"], "text": i["effective"][f], "origin": i["origin_effective"],
             "support": i["support"], "evidence_ids": i["evidence_ids"]}
        if i["type"] == "contrast":
            k["forms"] = [i["effective"]["a"], i["effective"]["b"]]
        if i["type"] == "worked_example":
            k["new_sentence"] = i["new_sentence"]
            if i["item_id"] in keyed and not include_rubrics:
                k["text"] = f"(answer and explanation withheld: they are the key to {', '.join(sorted(keyed[i['item_id']]))})"
                k["example"] = f"{i['effective']['question']} — …"
            else:
                k["example"] = f"{i['effective']['question']} — {i['effective']['answer']}"
        if i["state"] == "corrected":
            k["learner_corrected"] = True
            if mode == "tutor":
                k["proposed_text"] = i["proposed_text"]
        if version >= 2 and i.get("accepted_from"):
            k["accepted_from"] = i["accepted_from"]
        if i["support"] in ("unsupported", "uncertain", "no_evidence"):
            k["note"] = f"approved by the learner although the source support is {i['support']}"
        knowledge.append(k)
    confusions = []
    for i in (x for x in ok if x["type"] == "common_error"):
        related = {p["practice_id"] for p in prac["items"] if i["item_id"] in p["knowledge_ids"] or set(p["knowledge_ids"]) & set(i["applies"])}
        confusions.append({"id": i["item_id"], "wrong": i["effective"]["wrong"], "right": i["effective"]["right"],
                           "why": i["effective"]["why"], "evidence_ids": i["evidence_ids"],
                           "missed_in_practice": sum(n for pid, n in missed.items() if pid in related)})
    observed = [{"practice_id": p["practice_id"], "kind": p["kind"], "prompt": p["prompt"], "missed": missed[p["practice_id"]],
                 "knowledge_ids": p["knowledge_ids"]} for p in prac["items"] if p["practice_id"] in missed]
    exercises = []
    for p in prac["items"]:
        if not set(p["knowledge_ids"]) <= ids:
            continue
        x = {"id": p["practice_id"], "kind": p["kind"], "measures": p["measures"], "prompt": p["prompt"],
             "knowledge_ids": p["knowledge_ids"], "evidence_ids": p["evidence_ids"], "new_sentence": p["new_sentence"],
             "missed_in_practice": missed.get(p["practice_id"], 0)}
        if p.get("options"):
            x["options"] = p["options"]
        if include_rubrics:
            h = p["hidden"]
            x["rubric"] = {k: h[k] for k in ("answer", "accepted", "reference", "known_errors", "explanation") if k in h}
            x["rubric"]["grading"] = p["grading"]
        exercises.append(x)
    exercises.sort(key=lambda x: (-x["missed_in_practice"], {"explain": 0, "choose": 1, "produce": 2}[x["kind"]], x["id"]))
    s = res["source"]
    body = {
        "schema": VERSIONS[version], "mode": mode, "rubrics_included": include_rubrics,
        "rubrics_note": None if include_rubrics or mode == "study" else "answer keys and rubrics were withheld: the learner did not choose to share them",
        "concept": concept or ", ".join(sorted({f"{i['effective']['a']['form']} vs {i['effective']['b']['form']}" for i in ok if i["type"] == "contrast"})),
        "learner_goal": res["learner_goal"], "language_level": "A1/A2 (learner-stated target)",
        "source": {"source_id": s["source_id"], "revision": s["revision"], "revision_sha256": s["revision_sha256"]},
        "knowledge": knowledge, "evidence": [{k: ev[e][k] for k in ("evidence_id", "source_revision", "field", "quote", "excerpt", "status") if k in ev[e]}
                                             for e in used_ev],
        "known_confusions": confusions, "observed_in_practice": observed, "next_exercises": exercises, "excluded_by_default": EXCLUDED,
        "agent_rules": TUTOR_RULES if mode == "tutor" else TUTOR_RULES[:3],
        "return_format": {"schema": PROPOSALS_SCHEMA, "proposal_types": ["correction", "exercise"],
                          "each_needs": ["proposal_id", "type", "rationale", "evidence_ids"],
                          "correction": {"target_id": "a k-… id from this packet", "text": "the corrected wording"},
                          "exercise": {"knowledge_ids": "k-… ids", "kind": "explain | choose | produce", "prompt": "…",
                                       "options": "choose only", "answer": "choose only", "accepted": "produce only: valid variants"}},
    }
    if version >= 2:
        last = last_confusion(res, prac, attempts or [])
        body["last_confusion"] = last
        body["next_exercise"] = next_exercise(exercises, attempts or [], last)
        body["continuity"] = continuity(previous, body) if previous is not None else None
    body["packet_id"] = "pk-" + pr.sha(pr.canon(body))[:12]
    found = privacy_findings(pr.dumps(body) + markdown(body))
    if found:
        raise PermissionError("the packet would share private data: " + "; ".join(f"line {f['line']}: {f['kind']}" for f in found))
    return body


def markdown(pk: dict) -> str:
    L = [f"# FLH practice packet {pk.get('packet_id', '(unsealed)')} — {pk['concept']}", "",
         f"Mode: **{pk['mode']}**" + (" (answer keys and rubrics included by the learner's choice)" if pk["rubrics_included"] else ""),
         f"Source: `{pk['source']['source_id']}` revision {pk['source']['revision']}. Level: {pk['language_level']}.", "",
         "## Learner goal", "", pk["learner_goal"] or "(none given)", ""]
    L += _left_off(pk)
    L += ["## Rules for an agent using this packet", ""]
    L += [f"{k}. {r}" for k, r in enumerate(pk["agent_rules"], 1)]
    L += ["", "## Approved knowledge", ""]
    for k in pk["knowledge"]:
        tag = {"source": "from the learner's question", "learner": "corrected by the learner", "generated": "generated practice example"}[k["origin"]]
        L.append(f"- `{k['id']}` ({k['type']}, {tag}; evidence {', '.join(k['evidence_ids']) or 'none'}): {k['text']}")
        if k.get("example"):
            L.append(f"  - example: {k['example']}" + (" (a sentence not in the source)" if k.get("new_sentence") else ""))
        if k.get("accepted_from"):
            a = k["accepted_from"]
            L.append(f"  - accepted by the learner from {a['agent']} proposal `{a['proposal_id']}` (packet `{a['packet_id']}`)")
        if k.get("proposed_text"):
            L.append(f"  - originally proposed: {k['proposed_text']}")
        if k.get("note"):
            L.append(f"  - note: {k['note']}")
    L += ["", "## Evidence excerpts", ""]
    L += [f"- `{e['evidence_id']}` (revision {e['source_revision']}, {e.get('field', 'several places')}, {e['status']}): {e['excerpt']}" for e in pk["evidence"]]
    L += ["", "## Known confusions", ""]
    L += [f"- `{c['id']}`: not « {c['wrong']} » but « {c['right']} » — {c['why']} (evidence {', '.join(c['evidence_ids'])}; "
          f"missed in practice: {c['missed_in_practice']})" for c in pk["known_confusions"]] or ["- none recorded"]
    L += [f"- missed in practice ({o['missed']}×, answer text not shared): `{o['practice_id']}` {o['kind']}: {o['prompt']}"
          for o in pk["observed_in_practice"]]
    L += ["", "## Suggested next exercises", ""]
    for x in pk["next_exercises"]:
        L.append(f"- `{x['id']}` {x['kind']} ({x['measures']}): {x['prompt']}" + (f" Options: {' / '.join(x['options'])}." if x.get("options") else ""))
        if x.get("rubric"):
            r = x["rubric"]
            L.append("  - rubric: " + "; ".join(f"{k}: {' | '.join(v) if isinstance(v, list) else v}" for k, v in sorted(r.items())))
    if pk.get("rubrics_note"):
        L += ["", f"_{pk['rubrics_note']}._"]
    L += ["", "## Not included", ""] + [f"- {x}" for x in pk["excluded_by_default"]]
    L += ["", "## Use it in a fresh agent session", "",
          "1. Make an empty directory and copy `packet.md`, `packet.json`, `PROMPT-codex.md` and `PROMPT-claude-code.md` into it.",
          "2. Codex: `codex --sandbox workspace-write \"$(cat PROMPT-codex.md)\"`",
          "3. Claude Code: `claude \"$(cat PROMPT-claude-code.md)\"`",
          "4. Back in FLH, preview what the agent returned (read-only): "
          "`python3 -B -m flh_extraction practice import-preview --packet packet.json --proposals proposals.json`"]
    L += ["", "## How to return proposals", "", f"Return one JSON object with `\"schema\": \"{PROPOSALS_SCHEMA}\"`, "
          f"`\"packet_id\": \"{pk.get('packet_id', '')}\"` and a `proposals` list. Each proposal has `proposal_id`, `type` "
          "(`correction` or `exercise`), `rationale` and `evidence_ids`. A correction names `target_id` and `text`; an exercise "
          "names `knowledge_ids`, `kind`, `prompt` and, for choose, `options` and `answer`, or for produce, `accepted`. Mark a "
          "proposal with no supporting evidence by leaving `evidence_ids` empty and saying so in the rationale.", ""]
    return "\n".join(L)


def _left_off(pk: dict) -> list[str]:
    """The v2 section: what changed since the previous packet, the last confusion and the next exercise."""
    c, last, nx = pk.get("continuity"), pk.get("last_confusion"), pk.get("next_exercise")
    if not (c or last or nx):
        return []
    L = ["## Where we left off", ""]
    if c:
        L.append(f"- Continues packet `{c['previous_packet_id']}`: {c['knowledge_ids_kept']} knowledge IDs kept, "
                 f"{len(c['knowledge_ids_added'])} added, {len(c['knowledge_ids_dropped'])} dropped"
                 + ("" if c["same_source_revision"] else "; the source was revised since") + ".")
        L += [f"- Changed: `{x['id']}` — {x['what']}." for x in c["changed"]]
        L += [f"- New miss since then: `{x['practice_id']}` ({x['missed_since']}×)." for x in c["new_misses"]]
    if last:
        forms = " vs ".join(f"« {f} »" for f in last["forms"]) or "the forms of this item"
        L.append(f"- Last confusion: {forms} on `{last['practice_id']}` ({last['kind']}): {last['prompt']}")
        L.append("  - not shared: the learner's answer and the expected answer"
                 + (f"; it matches the known confusion `{last['known_confusion_id']}`" if last.get("known_confusion_id") else "")
                 + ("; answered correctly later" if last["resolved_later"] else ""))
    if nx:
        L.append(f"- Next exercise: `{nx['id']}` {nx['kind']}: {nx['prompt']}" + (f" Options: {' / '.join(nx['options'])}." if nx.get("options") else ""))
        L.append(f"  - why: {nx['why']} ({nx['rule']})")
    return L + [""]


def preview(pk: dict) -> str:
    """What will be shared, before any file is written."""
    L = [f"Packet preview ({pk['mode']} mode) {pk['packet_id']}: nothing has been written yet.",
         f"  goal               {pk['learner_goal'][:80]}",
         f"  knowledge          {len(pk['knowledge'])}: " + ", ".join(f"{k['id']} ({k['origin']})" for k in pk["knowledge"]),
         f"  evidence excerpts  {len(pk['evidence'])}: " + ", ".join(e["evidence_id"] for e in pk["evidence"]),
         f"  known confusions   {len(pk['known_confusions'])}",
         f"  next exercises     {len(pk['next_exercises'])}: " + ", ".join(f"{x['id']} {x['kind']}" for x in pk["next_exercises"]),
         f"  answer keys        {'included (your explicit choice)' if pk['rubrics_included'] else 'not included'}",
         "  not included       " + "; ".join(pk["excluded_by_default"]),
         "  privacy check      0 findings (a finding would have refused the export)"]
    if pk["schema"] != PACKET_SCHEMA:
        c, last, nx = pk.get("continuity"), pk.get("last_confusion"), pk.get("next_exercise")
        L.insert(1, f"  schema             {pk['schema']}")
        L.append(f"  continues          {c['previous_packet_id']} ({c['knowledge_ids_kept']} knowledge IDs kept; {len(c['changed'])} changed)" if c
                 else "  continues          (no previous packet given)")
        L.append(f"  last confusion     {' vs '.join(last['forms'])} on {last['practice_id']} (no attempt text, no answer)" if last
                 else "  last confusion     none recorded")
        L.append(f"  next exercise      {nx['id']} {nx['kind']}" if nx else "  next exercise      none")
    return "\n".join(L) + "\n"


def _known_ids(pk: dict) -> tuple[set, set, set]:
    return ({k["id"] for k in pk["knowledge"]}, {e["evidence_id"] for e in pk["evidence"]}, {x["id"] for x in pk["next_exercises"]})


def import_preview(pk: dict, ret: dict, rubric_answers: dict | None = None) -> dict:
    """Classify an agent's proposals against the packet. Read-only."""
    if not isinstance(ret, dict) or ret.get("schema") != PROPOSALS_SCHEMA or not isinstance(ret.get("proposals"), list):
        raise ValueError(f"an agent return must be {PROPOSALS_SCHEMA} with a proposals list")
    kids, eids, _ = _known_ids(pk)
    know = {k["id"]: k for k in pk["knowledge"]}
    wrong = {pr.fr_norm(c["wrong"]) for c in pk["known_confusions"]}
    prompts = {pr.fr_norm(x["prompt"]) for x in pk["next_exercises"]}
    seen_text, seen_prompt, rows = {}, {}, []
    for k, p in enumerate(ret["proposals"]):
        pid = p.get("proposal_id") if isinstance(p, dict) else None
        row = {"proposal_id": pid or f"#{k + 1}", "type": p.get("type") if isinstance(p, dict) else None}
        need = ["proposal_id", "type", "rationale", "evidence_ids"]
        if not isinstance(p, dict) or any(not p.get(f) and f != "evidence_ids" for f in need) or not isinstance(p.get("evidence_ids"), list) \
                or p["type"] not in ("correction", "exercise"):
            rows.append({**row, "class": "invalid", "why": "needs proposal_id, type (correction | exercise), rationale and an evidence_ids list"})
            continue
        unknown = sorted(set(p["evidence_ids"]) - eids)
        flags = [] if p["evidence_ids"] else ["cites no evidence: unsupported until the learner decides"]
        if p["type"] == "correction":
            t = p.get("target_id")
            if not p.get("text"):
                rows.append({**row, "class": "invalid", "why": "a correction needs text"})
                continue
            if t not in kids or unknown:
                rows.append({**row, "class": "unknown_reference", "why": "unknown " + ", ".join(
                    ([f"target {t}"] if t not in kids else []) + [f"evidence {e}" for e in unknown])})
                continue
            key = (t, pr.fr_norm(p["text"]))
            if pr.fr_norm(p["text"]) == pr.fr_norm(know[t]["text"]) or key in seen_text:
                rows.append({**row, "class": "duplicate", "why": "same wording as " + (f"the current {t}" if key not in seen_text else seen_text[key])})
                continue
            seen_text[key] = row["proposal_id"]
            if know[t].get("learner_corrected"):
                rows.append({**row, "class": "conflict", "target_id": t,
                             "why": f"the learner already corrected {t}; replacing a learner correction needs the learner's own decision"})
                continue
            rows.append({**row, "class": "accepted_candidate", "target_id": t, "text": p["text"], "rationale": p["rationale"], "flags": flags})
            continue
        x = p
        miss = sorted(set(x.get("knowledge_ids") or []) - kids)
        if not x.get("knowledge_ids") or x.get("kind") not in ("explain", "choose", "produce") or not x.get("prompt"):
            rows.append({**row, "class": "invalid", "why": "an exercise needs knowledge_ids, kind (explain | choose | produce) and prompt"})
            continue
        if miss or unknown:
            rows.append({**row, "class": "unknown_reference", "why": "unknown " + ", ".join([f"knowledge {m}" for m in miss] + [f"evidence {e}" for e in unknown])})
            continue
        np = pr.fr_norm(x["prompt"])
        if np in prompts or np in seen_prompt:
            rows.append({**row, "class": "duplicate", "why": "the same prompt is already " + ("in the packet" if np in prompts else f"proposed by {seen_prompt[np]}")})
            continue
        seen_prompt[np] = row["proposal_id"]
        answers = [x.get("answer", "")] + list(x.get("accepted") or [])
        bad = [a for a in answers if a and any(f" {w} " in f" {pr.fr_norm(a)} " for w in wrong)]
        if x["kind"] == "choose" and x.get("answer") not in (x.get("options") or []):
            rows.append({**row, "class": "conflict", "why": "the answer is not one of the options"})
        elif bad:
            rows.append({**row, "class": "conflict", "why": f"an expected answer uses a known confusion: {bad[0]!r}"})
        else:
            rows.append({**row, "class": "accepted_candidate", "kind": x["kind"], "prompt": x["prompt"], "rationale": x["rationale"], "flags": flags})
    return {"schema": "flh_agent_import_preview_v1", "packet_id": pk["packet_id"], "agent": ret.get("agent", "unknown"),
            "packet_matches": ret.get("packet_id") == pk["packet_id"], "read_only": True,
            "counts": {c: sum(1 for r in rows if r["class"] == c) for c in CLASSES}, "rows": rows,
            "note": "nothing was applied: an accepted candidate still needs the learner's explicit approval"}


def accept_correction(pk: dict, ret: dict, proposal_id: str, res: dict) -> tuple[str, str, dict]:
    """The learner accepts one agent correction: (target item, text, provenance) for an edit decision.
    Refused unless the read-only preview classes it an accepted candidate, the return names this
    packet, the packet is about the current source revision, and the learner's current knowledge
    neither already says the same nor holds the learner's own correction."""
    rep = import_preview(pk, ret)
    if not rep["packet_matches"]:
        raise ValueError(f"the return names packet {ret.get('packet_id')!r}, not {pk['packet_id']}")
    row = next((r for r in rep["rows"] if r["proposal_id"] == proposal_id), None)
    if row is None:
        raise ValueError(f"no proposal {proposal_id!r} in the return")
    if row["type"] != "correction":
        raise ValueError("only corrections can be accepted here; an exercise proposal stays in the preview")
    if row["class"] != "accepted_candidate":
        raise ValueError(f"proposal {proposal_id} is {row['class']}: {row.get('why', '')}")
    if pk["source"]["revision_sha256"] != res["source"]["revision_sha256"]:
        raise ValueError("the packet was made from another revision of the source; export a new packet first")
    cur = next((i for i in res["items"] if i["item_id"] == row["target_id"]), None)
    if cur is None or cur["state"] not in ("approved", "corrected"):
        raise ValueError(f"{row['target_id']} is no longer approved knowledge")
    prop = next(p for p in ret["proposals"] if isinstance(p, dict) and p.get("proposal_id") == proposal_id)
    if pr.fr_norm(cur["effective"][pr.MAIN_TEXT[cur["type"]]]) == pr.fr_norm(prop["text"]):
        raise ValueError(f"duplicate: {row['target_id']} already says this")
    if cur["state"] == "corrected":
        raise ValueError(f"conflict: you already corrected {row['target_id']}; decide on it directly with --edit")
    via = {"kind": "agent_proposal", "agent": str(ret.get("agent", "unknown")), "packet_id": pk["packet_id"], "proposal_id": proposal_id,
           "rationale": prop["rationale"], "evidence_ids": prop["evidence_ids"], "flags": row["flags"]}
    return row["target_id"], prop["text"], via


def render_import(rep: dict) -> str:
    L = [f"Agent return preview (read-only) for packet {rep['packet_id']} from {rep['agent']}"
         + ("" if rep["packet_matches"] else "  WARNING: the return names another packet_id"),
         "counts: " + ", ".join(f"{k} {v}" for k, v in rep["counts"].items())]
    for r in rep["rows"]:
        L.append(f"  {r['class']:18} {r['proposal_id']:6} {r['type'] or '?':10} " + (r.get("why") or (r.get("text") or r.get("prompt", ""))))
        for f in r.get("flags", []):
            L.append(f"  {'':18} {'':6} {'':10} flag: {f}")
    L.append(rep["note"])
    return "\n".join(L) + "\n"


# ---- Workbooks feed (read-only integration proposal, item 134) ----

FEED_SCHEMA = "flh_practice_review_feed_v1"


def workbooks_feed(prac: dict, attempts: list[dict], previous: dict | None = None) -> dict:
    """Approved practice items and attempt outcomes, for Review Today to read. No scheduling field:
    when an item is due is Workbooks' decision. With ``previous`` (an earlier feed of the same
    source), practice IDs that are no longer offered are listed as ``withdrawn``."""
    outcomes = {}
    for a in sorted(attempts, key=lambda a: a["seq"]):
        outcomes.setdefault(a["practice_id"], []).append({"seq": a["seq"], "action": a["action"], "outcome": a["outcome"]})
    extra = {}
    if previous is not None:
        if previous.get("schema") != FEED_SCHEMA or previous["source"]["source_id"] != prac["source"]["source_id"]:
            raise ValueError("--previous must be an earlier feed of the same source")
        now = {p["practice_id"] for p in prac["items"]}
        extra = {"previous": {k: previous["source"][k] for k in ("revision", "revision_sha256")},
                 "withdrawn": [{"practice_id": p["practice_id"], "kind": p["kind"],
                                "reason": f"not offered from revision {prac['source']['revision']}: its knowledge needs the learner's review or was rejected"}
                               for p in previous["items"] if p["practice_id"] not in now]}
    return {**extra, "schema": FEED_SCHEMA, "producer": "extraction lane prototype (owner of the practice-content contract)",
            "consumer": "workbooks lane: Review Today and scheduling", "source": prac["source"],
            "items": [{**pr.public(p), "outcomes": outcomes.get(p["practice_id"], [])} for p in prac["items"]],
            "not_included": ["due dates, intervals or any schedule (Workbooks owns them)", "answer keys (read them from the practice file when revealing)",
                             "attempt texts"]}
