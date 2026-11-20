"""Extraction 2.2 review (PROTOTYPE, offline, standard library only): reliable approval.

It reads the unchanged 2.1 draft (``practice.draft``) and adds what a learner needs to
approve safely. The 2.1 functions and their outputs are untouched; this module is used by
the 2.2 work directory (``practice22.Work2``) and the ``practice2`` commands.

* **Quote or paraphrase.** A proposal item may carry ``paraphrases``: a pedagogical
  restatement of one of its quotes. Previews label every line as an exact quote (with its
  grounding) or a paraphrase (never evidence). Approving an item with a paraphrase needs
  the learner's explicit attestation, which the decision records.
* **Word cues, not proof** (``flh_quote_scope_cues_v1``). A quote can be located and still
  not support the claim. Two cues look for that with word matching only: a claim that
  generalises ("every", "always", "toujours"…) and a claim about « en » whose quote has
  « en » + a word in -ant (often a gerund). A flagged item is never batched; the review
  says that the check compares words and proves nothing either way.
* **Conflicts.** A common error whose wrong form another item presents as correct makes a
  conflict pair. Both sides are decided one by one until one side is rejected.
* **Material changes** (``flh_material_hash_v1``). A decision records the item's material
  hash: its content, paraphrases and quote statuses after Unicode NFC, apostrophe and
  whitespace normalisation. Only a change that survives that normalisation is material.
* **No silent reactivation.** An approval is reused only across revisions in which the item
  never changed materially. An item that changed (for example its quote disappeared) and
  later returns to the decided state is ``needs_review`` (restored) until the learner
  confirms it. An item absent from a revision and back unchanged keeps its decision.
* **Moved quotes.** A quote located at another position is still located: the review shows
  where it moved and maps the old evidence ID to the new one.
* **Batch v2** (``flh_practice_batch_plan_v1``). The plan lists the selected items
  explicitly, what approving them changes (knowledge and practice), and why every other
  item is left out. Its ID hashes every member's item and material hashes. Applying it is
  resumable: a retry after an interruption writes only the members still missing.
"""

from __future__ import annotations

import re

from . import practice as pr

REVIEW_SCHEMA = "flh_practice_review_v2"
PLAN_SCHEMA = "flh_practice_batch_plan_v1"
CUES = "flh_quote_scope_cues_v1"
MATERIAL = "flh_material_hash_v1"
UNIVERSAL = re.compile(r"\b(every|all|always|never|only|any|each|toujours|jamais|seulement|uniquement|chaque|tous|toutes)\b", re.I)
GERUND = re.compile(r"\ben (\w+ant)\b", re.I)
NOT_GERUND = {"avant", "tant", "devant", "dedans"}
QUOTED = re.compile(r"«[^»]*»")


def ws(s: str) -> str:
    """NFC, apostrophes unified, every Unicode space run collapsed: what is not material."""
    return " ".join(pr.fold(s).split())


def _deep(v):
    if isinstance(v, str):
        return ws(v)
    if isinstance(v, list):
        return [_deep(x) for x in v]
    if isinstance(v, dict):
        return {k: _deep(x) for k, x in v.items()}
    return v


def paraphrases_of(src: dict | None, ref: str) -> list[dict]:
    if not src:
        return []
    it = next((i for i in src["proposal"]["items"] if i["ref"] == ref), None)
    return [p for p in (it or {}).get("paraphrases", []) if isinstance(p, dict) and p.get("text")]


def material_hash(it: dict, src: dict | None = None) -> str:
    body = {"type": it["type"], "content": _deep(it["content"]), "grounding": [(ws(g["quote"]), g["status"]) for g in it["groundings"]],
            "paraphrases": [(ws(p["text"]), ws(p.get("of", ""))) for p in paraphrases_of(src, it["proposal_ref"])]}
    return pr.sha(pr.canon(body))


# ---- cues, paraphrases, conflicts ----

def cues(it: dict) -> list[dict]:
    """Word cues that a located quote may not support the claim. Never a semantic judgement."""
    if it["origin"] == "generated" or not any(g["status"] == "located" for g in it["groundings"]):
        return []
    text = it["content"][pr.MAIN_TEXT[it["type"]]]
    out = []
    m = UNIVERSAL.search(QUOTED.sub(" ", text))
    if m:
        n = sum(1 for g in it["groundings"] if g["status"] == "located")
        out.append({"cue": "generalises", "word": m.group(1),
                    "detail": f"the claim says « {m.group(1)} »; its {n} located quote{'s' if n != 1 else ''} show{'' if n != 1 else 's'} "
                              f"{'examples' if n != 1 else 'one example'}, not a rule for every case"})
    if "« en" in text or " en " in f" {pr.fr_norm(QUOTED.sub(' ', text))} ":
        for g in it["groundings"]:
            for w in GERUND.findall(g["quote"]):
                if w.lower() not in NOT_GERUND:
                    out.append({"cue": "en_plus_ant", "word": w,
                                "detail": f"in « {g['quote']} », « en {w} » is « en » + a word in -ant: it may be a gerund, not the place preposition"})
    return out


def paraphrase_rows(it: dict, src: dict | None) -> list[dict]:
    by_quote = {g["quote"]: g for g in it["groundings"]}
    rows = []
    for p in paraphrases_of(src, it["proposal_ref"]):
        g = by_quote.get(pr.fold(p.get("of", "")))
        rows.append({"text": p["text"], "of": p.get("of", ""), "of_evidence_id": (g or {}).get("evidence_id"),
                     "of_status": (g or {}).get("status", "not_cited"),
                     "note": "a paraphrase, not a quotation: it is never evidence; only the quote it restates is"})
    return rows


def _assertions(it: dict) -> list[str]:
    c = it["content"]
    out = [c.get(pr.MAIN_TEXT[it["type"]], "")]
    if it["type"] == "worked_example":
        out += [c.get("answer", "")] + list(c.get("accepted") or [])
    return [x for x in out if x]


def conflicts(items: list[dict]) -> list[dict]:
    """Pairs where one item presents as correct what a common error lists as wrong (word match)."""
    out = []
    for e in (i for i in items if i["type"] == "common_error"):
        w = pr.fr_norm(e["content"]["wrong"])
        for o in items:
            if o["item_id"] == e["item_id"] or not w:
                continue
            if any(f" {w} " in f" {pr.fr_norm(t)} " for t in _assertions(o)):
                out.append({"error_id": e["item_id"], "other_id": o["item_id"], "form": e["content"]["wrong"],
                            "detail": f"{o['item_id']} presents « {e['content']['wrong']} » as correct; {e['item_id']} lists it as an error"})
    return out


# ---- resolution across revisions ----

def changes2(old: dict, new: dict, old_rev: int) -> list[str]:
    """What changed materially in one item, with the values (lists as removed / added entries)."""
    out = []
    for k in sorted(set(old["content"]) | set(new["content"])):
        a, b = _deep(old["content"].get(k)), _deep(new["content"].get(k))
        if a == b:
            continue
        if isinstance(a, list) and isinstance(b, list):
            out += [f"{k}: removed « {x} »" for x in a if x not in b] + [f"{k}: added « {x} »" for x in b if x not in a]
        elif isinstance(a, str) and isinstance(b, str):
            out.append(f"{k}: « {_short(a, 70)} » -> « {_short(b, 70)} »")
        else:
            out.append(f"{k} changed")
    og = {ws(g["quote"]): g["status"] for g in old["groundings"]}
    ng = {ws(g["quote"]): g["status"] for g in new["groundings"]}
    out += [f"quote « {q} »: {og.get(q, 'absent')} in revision {old_rev} -> {ng.get(q, 'absent')} now"
            for q in sorted(set(og) | set(ng)) if og.get(q) != ng.get(q)]
    return out or ["paraphrases changed"]


def _by_id(drf: dict) -> dict:
    return {i["item_id"]: i for i in drf["items"]}


def evidence_moves(old: dict, new: dict) -> dict:
    """quote -> move, for quotes located in both drafts at a different position."""
    o = {e["quote"]: e for e in old["evidence"] if e["status"] == "located"}
    out = {}
    for e in new["evidence"]:
        p = o.get(e["quote"])
        if e["status"] == "located" and p and (p["field"], p["start"]) != (e["field"], e["start"]):
            out[e["quote"]] = {"quote": e["quote"], "from": f"{p['field']}@{p['start']}", "to": f"{e['field']}@{e['start']}",
                               "from_revision": old["source"]["revision"], "old_evidence_id": p["evidence_id"], "new_evidence_id": e["evidence_id"]}
    return out


def resolve2(drafts: dict, decisions: list[dict], sources: dict | None = None) -> dict:
    """The 2.1 resolution plus: material comparison, restored items, moved quotes, reasons kept with
    the revision that caused them. ``drafts`` and ``sources`` map revision -> document."""
    sources = sources or {}
    cur_rev = max(drafts)
    drf, src = drafts[cur_rev], sources.get(cur_rev)
    last, first_by_item = {}, {}
    for d in sorted(decisions, key=lambda d: d["seq"]):
        last[d["item_id"]] = d
    base = pr.resolve(drf, decisions)
    mat = {i["item_id"]: material_hash(i, src) for i in drf["items"]}
    conf = conflicts(drf["items"])
    items = []
    for r in base["items"]:
        iid, d = r["item_id"], last.get(r["item_id"])
        r = {**r, "material_hash": mat[iid], "cues": cues(r), "paraphrases": paraphrase_rows(r, src),
             "conflicts": [c for c in conf if iid in (c["error_id"], c["other_id"])]}
        if d:
            dr = d["based_on"]["source_revision"]
            dm = d["based_on"].get("material_hash")
            same_material = (dm == mat[iid]) if dm else d["based_on"]["item_hash"] == r["item_hash"]
            earlier = {"action": d["action"], "revision": dr, "draft_id": d["based_on"].get("draft_id"), "reason": d.get("reason", ""), "seq": d["seq"]}
            if d["action"] == "reject":
                r["rejected_on"] = earlier
            if not same_material:
                r["state"] = "needs_review"
                r["review_kind"] = "changed"
                old = _by_id(drafts[dr]).get(iid) if dr in drafts else None
                r["changes"] = changes2(old, r, dr) if old else ["the draft of that revision is not in this work directory"]
                r["review_reason"] = f"you decided '{d['action']}' on revision {dr}; it changed materially since, so that decision is not reused"
                r["earlier_decision"] = earlier
            else:
                between = [v for v in sorted(drafts) if dr < v < cur_rev]
                changed_in = [v for v in between if iid in _by_id(drafts[v]) and material_hash(_by_id(drafts[v])[iid], sources.get(v)) != (dm or mat[iid])]
                absent_in = [v for v in between if iid not in _by_id(drafts[v])]
                if changed_in:
                    r["state"] = "needs_review"
                    r["review_kind"] = "restored"
                    r["review_reason"] = (f"you decided '{d['action']}' on revision {dr}; it changed in revision {changed_in[0]} and is now back to what "
                                          f"you decided. A decision is not reused across a change: confirm it again")
                    r["earlier_decision"] = earlier
                    r.pop("carried_from_revision", None)
                else:
                    r.pop("review_reason", None)
                    r["state"] = {"approve": "approved", "reject": "rejected", "edit": "corrected"}[d["action"]]
                    if d.get("via") and r["state"] in ("approved", "corrected"):
                        r["accepted_from"] = {k: d["via"][k] for k in ("agent", "packet_id", "proposal_id") if k in d["via"]}
                    if d.get("batch") and r["state"] == "approved":
                        r["batch_id"] = d["batch"]["batch_id"]
                    if d["action"] == "edit":
                        f = pr.MAIN_TEXT[r["type"]]
                        r["effective"] = {**r["content"], f: d["text"]}
                        r["proposed_text"] = r["content"][f]
                    if dr != cur_rev:
                        r["carried_from_revision"] = dr
                    if d["based_on"]["item_hash"] != r["item_hash"]:
                        r["normalized_only"] = "the wording differs only in spacing, apostrophes or Unicode form"
                    if absent_in:
                        r["reappeared_after"] = absent_in
            if d.get("attest") and r["state"] == "approved":
                r["attested"] = d["attest"]
        r["origin_effective"] = "learner" if r["state"] == "corrected" else r["origin"]
        if r["state"] not in ("approved", "corrected"):
            r.pop("accepted_from", None)
            r.pop("batch_id", None)
        items.append(r)
    out = {k: v for k, v in base.items() if k != "items"}
    out["items"] = items
    out["states"] = {s: sum(1 for i in items if i["state"] == s) for s in ("pending", "approved", "corrected", "rejected", "needs_review")}
    prev = max([v for v in drafts if v < cur_rev], default=None)
    out["moves"] = evidence_moves(drafts[prev], drf) if prev is not None else {}
    out["conflicts"] = conf
    return out


# ---- batch plan v2 ----

def _blocked(it: dict, res: dict) -> str | None:
    """Why an item cannot be approved together with others (None: it can)."""
    if it["state"] == "needs_review":
        return ("RESTORED: back to what you decided earlier after a change; confirm it" if it.get("review_kind") == "restored"
                else "CHANGED: decided on an earlier revision; it changed materially")
    if it["state"] != "pending":
        return "decided"
    if it["support"] not in pr.BATCH_SUPPORT:
        return pr._why(it)
    if it["cues"]:
        return "QUOTE FOUND, CLAIM MAY SAY MORE (a word check, not a proof): " + "; ".join(c["detail"] for c in it["cues"])
    open_conf = []
    states = {i["item_id"]: i["state"] for i in res["items"]}
    for c in it["conflicts"]:
        other = c["other_id"] if c["error_id"] == it["item_id"] else c["error_id"]
        if states.get(other) != "rejected":
            open_conf.append(f"CONFLICTS WITH {other}: {c['detail']}")
    if open_conf:
        return "; ".join(open_conf)
    if it["paraphrases"]:
        return "PARAPHRASE: approving it needs your attestation that the paraphrase says what the quote says (--attest-paraphrase)"
    return None


def plan(res: dict, select=None, except_ids=()) -> dict:
    """The batch the learner may approve together, its explicit selection and its effects."""
    members, left, done = [], [], []
    for it in res["items"]:
        why = _blocked(it, res)
        if why is None:
            members.append(it)
        elif why == "decided":
            done.append(it)
        else:
            left.append({"item_id": it["item_id"], "type": it["type"], "state": it["state"], "support": it["support"], "why": why,
                         "text": it["content"][pr.MAIN_TEXT[it["type"]]], "changes": it.get("changes", []),
                         "earlier_decision": it.get("earlier_decision")})
    ids = [m["item_id"] for m in members]
    bid = "b2-" + pr.sha(pr.canon([res["draft_id"], [(m["item_id"], m["item_hash"], m["material_hash"]) for m in members]]))[:12] if members else None
    sel = list(ids if select is None else select)
    bad = sorted(set(sel) - set(ids)) + sorted(set(except_ids) - set(ids))
    if bad:
        raise ValueError(f"not in this batch (each must be decided by itself, or is unknown): {', '.join(bad)}")
    sel = [i for i in ids if i in set(sel) and i not in set(except_ids)]
    eff = effects(res, sel)
    return {"schema": PLAN_SCHEMA, "draft_id": res["draft_id"], "source": res["source"], "batch_id": bid,
            "members": [{"item_id": m["item_id"], "type": m["type"], "support": m["support"], "text": m["content"][pr.MAIN_TEXT[m["type"]]],
                         "evidence_ids": m["evidence_ids"], "new_sentence": m["new_sentence"], "selected": m["item_id"] in sel} for m in members],
            "selected": sel, "left_for_you": left, "already_decided": [{"item_id": i["item_id"], "state": i["state"]} for i in done],
            "effects": eff,
            "rule": "batched: pending, every quote located once (or a new practice example), no word cue, no open conflict, no paraphrase"}


def effects(res: dict, selected: list[str]) -> dict:
    now = pr.build_practice(res)
    hyp = {**res, "items": [{**i, "state": "approved"} if i["item_id"] in set(selected) else i for i in res["items"]]}
    after = pr.build_practice(hyp)
    old = {p["practice_id"] for p in now["items"]}
    new = [p for p in after["items"] if p["practice_id"] not in old]
    return {"knowledge_approved": len(selected), "decision_records": len(selected),
            "practice_before": len(now["items"]), "practice_after": len(after["items"]),
            "new_practice": [{"practice_id": p["practice_id"], "kind": p["kind"]} for p in new],
            "evidence_links_added": sorted({e for p in new for e in p["evidence_ids"]})}


def batch_meta(pl: dict) -> dict:
    return {"batch_id": pl["batch_id"], "members": [m["item_id"] for m in pl["members"]], "selected": pl["selected"],
            "excepted": sorted(set(m["item_id"] for m in pl["members"]) - set(pl["selected"])), "size": len(pl["selected"])}


def resume_check(res: dict, batch_id: str, decisions: list[dict]) -> tuple[list[str], dict] | None:
    """For a retry after an interrupted batch: (members still to write, batch meta) when the
    decisions already written for ``batch_id`` and the current items still hash to it."""
    written = [d for d in decisions if (d.get("batch") or {}).get("batch_id") == batch_id]
    if not written:
        return None
    meta = written[0]["batch"]
    byid = {i["item_id"]: i for i in res["items"]}
    if any(m not in byid for m in meta.get("members", [])):
        raise ValueError(f"batch {batch_id} names items that are no longer in the draft: review again")
    if any(d["based_on"].get("draft_id") != res["draft_id"] for d in written):
        raise ValueError(f"batch {batch_id} was shown on another revision of the source: review again")
    check = "b2-" + pr.sha(pr.canon([res["draft_id"], [(m, byid[m]["item_hash"], byid[m]["material_hash"]) for m in meta["members"]]]))[:12]
    if check != batch_id:
        raise ValueError(f"batch {batch_id}: its items changed since it was shown; review again")
    done = {d["item_id"] for d in written}
    todo = [m for m in meta["selected"] if m not in done]
    blocked = [m for m in todo if byid[m]["state"] != "pending"]
    if blocked:
        raise ValueError(f"batch {batch_id}: {', '.join(blocked)} were decided otherwise since; review again")
    return todo, meta


# ---- rendering ----

def _short(t: str, n: int = 96) -> str:
    return t if len(t) <= n else t[: n - 1] + "…"


def render_items(res: dict) -> str:
    """The draft beside its evidence, every line labelled exact quote or paraphrase."""
    s = res["source"]
    L = [f"Draft {res['draft_id']}  source {s['source_id']} revision {s['revision']} ({s['revision_sha256'][:12]})",
         "lines: QUOTE = your exact words, located in your text (evidence); PARAPHRASE = a restatement (never evidence); "
         "CUE = a word check that the quote may not support the claim (not a proof)", ""]
    ev = {e["evidence_id"]: e for e in res["evidence"]}
    moved = res.get("moves", {})
    for it in res["items"]:
        c = it.get("effective", it["content"])
        L.append(f"[{it['item_id']}] {it['type']}  support {it['support']}  state {it['state']}"
                 + (f" (carried from revision {it['carried_from_revision']})" if it.get("carried_from_revision") else "")
                 + (f" ({it['review_kind']})" if it.get("review_kind") else ""))
        if it["type"] == "contrast":
            L.append(f"  says        « {c['a']['form']} » {c['a'].get('use', '')} / « {c['b']['form']} » {c['b'].get('use', '')}")
        elif it["type"] == "worked_example":
            L.append(f"  says        {c['question']} — {c['answer']}" + ("  (a sentence not in your source)" if it["new_sentence"] else ""))
        elif it["type"] == "common_error":
            L.append(f"  says        not « {c['wrong']} » but « {c['right']} »")
        L.append(f"  {'says' if it['type'] == 'claim' else pr.MAIN_TEXT[it['type']]:11} {_short(c[pr.MAIN_TEXT[it['type']]], 140)}")
        if it.get("proposed_text"):
            L.append(f"  proposed    {_short(it['proposed_text'], 140)}  (your correction replaces it; kept)")
        for g in it["groundings"]:
            L.append(f"  QUOTE       {g.get('evidence_id', '-'):13} {g['status']:9} « {g['quote']} »")
            e = ev.get(g.get("evidence_id"))
            if e and e["status"] == "located":
                L.append(f"              {e['excerpt']}")
            mv = moved.get(g["quote"])
            if mv:
                L.append(f"              MOVED since revision {mv['from_revision']}: {mv['from']} -> {mv['to']} (still located once; "
                         f"{mv['old_evidence_id']} is now {mv['new_evidence_id']}; a move does not change your decision)")
        if not it["groundings"]:
            L.append("  QUOTE       none" + (" (a new practice example: the source never said it)" if it["origin"] == "generated" else ""))
        for p in it["paraphrases"]:
            L.append(f"  PARAPHRASE  restates {p['of_evidence_id'] or '(a quote it does not cite)'}: {_short(p['text'], 140)}")
        for k in it["cues"]:
            L.append(f"  CUE         {k['cue']}: {k['detail']}")
        for k in it["conflicts"]:
            L.append(f"  CONFLICT    {k['detail']}")
        if it.get("normalized_only"):
            L.append(f"  note        {it['normalized_only']}; your decision is kept")
        if it.get("reappeared_after"):
            L.append(f"  note        absent from revision {', '.join(map(str, it['reappeared_after']))}, back unchanged; your decision is kept")
        if it.get("rejected_on") and it["state"] == "rejected":
            r = it["rejected_on"]
            L.append(f"  rejected    on revision {r['revision']}" + (f": {r['reason']}" if r["reason"] else ""))
        if it.get("review_reason"):
            L.append(f"  review      {it['review_reason']}")
            e = it.get("earlier_decision") or {}
            if e.get("reason"):
                L.append(f"              your reason then (revision {e['revision']}): {e['reason']}")
            L += [f"              what changed: {x}" for x in it.get("changes", [])]
        if it.get("attested"):
            L.append(f"  attested    {it['attested']['what']} (by the learner, decision {it.get('decision_seq')})")
        L.append("")
    L.append("states: " + ", ".join(f"{k} {v}" for k, v in res["states"].items()))
    return "\n".join(L) + "\n"


def render_plan(pl: dict) -> str:
    s = pl["source"]
    L = [f"Review v2 of draft {pl['draft_id']} (source {s['source_id']} revision {s['revision']})", ""]
    e = pl["effects"]
    if pl["batch_id"]:
        L.append(f"Batch {pl['batch_id']}: approve {len(pl['selected'])} of {len(pl['members'])} batchable items together. Selected, explicitly:")
        for m in pl["members"]:
            ref = f"evidence {', '.join(m['evidence_ids'])}" if m["evidence_ids"] else "new practice example" + (", sentence not in your source" if m["new_sentence"] else "")
            L.append(f"  [{'x' if m['selected'] else ' '}] {m['item_id']} {m['type']:14} {ref}")
            L.append(f"      {_short(m['text'])}")
        np = ", ".join(f"{p['practice_id']} {p['kind']}" for p in e["new_practice"]) or "none"
        L.append(f"  Effect: {e['knowledge_approved']} items become approved knowledge ({e['decision_records']} decision records, one each); "
                 f"practice {e['practice_before']} -> {e['practice_after']} exercises (new: {np}); nothing else changes.")
        L.append(f"  -> practice2 decide --work W --approve-batch {pl['batch_id']}   (--select k-…,k-… to approve fewer; --except k-…)")
    else:
        L.append("Batch: none (no pending item can be approved together with others)")
    L += ["", f"Decide yourself, one by one ({len(pl['left_for_you'])}):"]
    for r in pl["left_for_you"]:
        L.append(f"  [{r['item_id']}] {r['type']:14} {r['why']}")
        L.append(f"      {_short(r['text'])}")
        if r.get("earlier_decision") and r["earlier_decision"].get("reason"):
            L.append(f"      your earlier '{r['earlier_decision']['action']}' on revision {r['earlier_decision']['revision']}: {r['earlier_decision']['reason']}")
        L += [f"      what changed: {c}" for c in r.get("changes", [])]
    if not pl["left_for_you"]:
        L.append("  (none)")
    st: dict = {}
    for d in pl["already_decided"]:
        st[d["state"]] = st.get(d["state"], 0) + 1
    L += ["", "Already decided: " + (", ".join(f"{k} {v}" for k, v in sorted(st.items())) or "none")]
    return "\n".join(L) + "\n"
