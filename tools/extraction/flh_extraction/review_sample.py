"""Frozen reviewer sample of the held-out references (OFFLINE ONLY).

  python3 -m flh_extraction review-sample --slice S.jsonl --challenge C.jsonl --out PREFIX
      writes PREFIX.jsonl (the packet to fill), PREFIX.md (rubric + items) and
      PREFIX-selection.json (rule, salt, input hashes, the chosen ids)
  python3 -m flh_extraction review-agreement --packet P.jsonl [--second P2.jsonl] --out PREFIX
      agreement with the references (and between two reviewers), learning intent
      and wording reported separately; disputed items stay unresolved until a
      reviewer resolves them explicitly
  python3 -m flh_extraction export-check FILE …
      exit 1 when a reviewer export carries a local path, an e-mail address, a
      private link, a non-zero entry id or a secret-like value

The sample covers the references that gate the three-system comparison
(frozen evaluation, its `rb` probe, `challenge_test`), which no human has
reviewed. Everything in it is synthetic and machine-authored: no model output
and no learner data. The selection is a pure function of the inputs and SALT.

Selection rule (each stratum skips ids already chosen; "first" = smallest
sha256(SALT + ":" + id)):

  objective      frozen unit references, grouped into objective clusters (records
                 linked by a shared objective point): the first record of each
                 cluster
  zero           frozen zero-unit references: the first of each case type
  false_premise  frozen false-premise and wrong-explanation references: the first
                 of each case type not yet represented
  over_general   frozen references holding a unit that the FLH-154 agent reading
                 found over-general (OVER_GENERAL): the first per unit, if absent
  cue_dispute    every challenge_test abstain group whose conflicting cue quotes a
                 form present in the learner's own text
  challenge      the first two other challenge_test extract groups and the first
                 other abstain group
  rb_anchor      rb rows whose unit is anchored only in the explanation that rb
                 replaced and whose frozen record is not already chosen: the first two

A dispute is recorded, never resolved: `dispute.status` is "disputed" with the
positions of each source (reference, cue, heuristic, agent reading). The
reviewer answers the rubric and writes the position taken; until then the
item counts as unresolved and stays out of every agreement rate.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict

from . import audit, challenge
from .textnorm import norm

SALT = "flh154-review-sample-v1"
PACKET = "review-sample-v1"
OVER_GENERAL = {
    "adjectifs de couleur invariables (marron, orange)":
        "« Colour words that come from nouns do not agree » is over-general: « rose, mauve, fauve, écarlate » come "
        "from nouns and agree. Suggest « most colour words … such as marron, orange ».",
    "lequel / laquelle après une préposition":
        "Reads as if every preposition takes « lequel »; after « de » French uses « dont » (« duquel » in compound "
        "prepositions).",
}
OFFLINE = ("OFFLINE ONLY: synthetic, machine-authored references with no model output and no learner data. "
           "Nothing here measures a model; only a person's verdict below counts as review.")

RUBRIC = {
    "intent": [
        {"id": "I1", "question": "Decision: from the learner's text and context alone, is « units » vs « zero units » right? "
                                 "The category and explanation are evidence, not authority.",
         "yes": "ext-trn-i2-0153 « Correction demandée : Je vais en Lyon en pied. » → units: the learner asks for a "
                "correction. bc-004 « J'ai regardé un film français hier soir, c'était super. » (journal) → zero: correct "
                "French with no question, correction or doubt.",
         "no": "bc-001 « Merci beaucoup, c'est beaucoup plus clair maintenant ! » (after a talk on the subjunctive) with a "
               "unit on the subjunctive: thanks raise no objective in this interaction."},
        {"id": "I2", "question": "Objectives: is the set right — none missing, none extra, each unit one objective?",
         "yes": "ext-trn-i2-0167 « Ma voisine est petit et blond. » → one unit (adjective agreement): two adjectives, "
                "one rule.",
         "no": "ext-trn-00235 « Elle est une acteuse » → « C'est une actrice » labelled with the « -trice » unit only: "
               "the « c'est / il est » objective is missing (UNDER_SPLIT). Splitting « vouloir — je veux » and "
               "« vouloir — nous voulons » into two units is the opposite error (OVER_SPLIT)."},
    ],
    "wording": [
        {"id": "W1", "question": "statement: true, and not over-general for what it claims?",
         "yes": "« Ne… que means only; it is a restriction, not a negation: je n'ai que dix euros ».",
         "no": "« After a negation, the articles un, une, du, de la, des become de » (ext-trn-i2-0001): false after « être » "
               "(« ce n'est pas un problème »). Mark no and write the fix (FALSE_CLAIM)."},
        {"id": "W2", "question": "statement_zh: says the same thing (scope, claim, French forms)? It is a translation of "
                                 "statement, so the two are ONE claim: their agreement never confirms the claim.",
         "yes": "« ne… que » 意为“只、仅”，表示限制而不是否定 for the statement above.",
         "no": "EN « grâce à introduces a positive cause » with ZH « grâce à 表示原因 »: the ZH drops « positive »."},
        {"id": "W3", "question": "canonical: names the objective the learner raised?",
         "yes": "ext-trn-00018 « How do I say not anymore in French? » → « ne… plus ».",
         "no": "ext-trn-00377 « Location, c'est l'endroit où se trouve l'hôtel ? » → « louer (deux sens) »: the question is "
               "the false friend « location » (= rental), not the two senses of « louer »."},
        {"id": "W4", "question": "example: correct French that illustrates this objective (or null)?",
         "yes": "« Il ne mange jamais de viande. » for « ne… jamais ».",
         "no": "ext-trn-00051 (« J'y pense » corrected to « je pense à lui ») with the example « Ton examen ? J'y pense tous "
               "les jours. »: it shows the thing case; the learner's error was the person case."},
    ],
    "dispute": {"question": "When `dispute.status` is disputed: answer I1–W4 as usual, then write which position you take "
                            "and why in `dispute_position`. Never change the reference silently; use verdict "
                            "`quarantine` when reasonable people disagree.",
                "yes": "ext-trn-i2-0070 « Merci pour ton aide avec la conjugaison hier soir ! »: the cue says `morphology` "
                       "(it matched « conjugaison ») while the reference is zero units — two machine sources disagree, so "
                       "the item stays disputed until a person decides.",
                "no": "A scheduling message whose cue is `other` and whose reference is zero: nothing to dispute."},
    "verdict": "accept / edit (write the fix) / reject / quarantine; reviewer and date.",
}


def h(x):
    return hashlib.sha256(f"{SALT}:{x}".encode()).hexdigest()


def first(rs, k=1):
    return sorted(rs, key=lambda r: h(r["id"]))[:k]


def clusters(unit_refs):
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for r in unit_refs:
        ps = r["meta"]["points"] or [r["id"]]
        for p in ps[1:]:
            parent[find(p)] = find(ps[0])
        find(ps[0])
    out = defaultdict(list)
    for r in unit_refs:
        out[find((r["meta"]["points"] or [r["id"]])[0])].append(r)
    return [out[k] for k in sorted(out, key=lambda k: min(p for p in parent if find(p) == k))]


def _quoted_in_text(expl, text):
    lt = " " + " ".join(norm(text).replace("'", " ").split()) + " "
    return [w for w in re.findall(r"«\s*([^»]+?)\s*»", expl) if " " + " ".join(norm(w).replace("'", " ").split()) + " " in lt]


def _rb_anchor_lost(rb, frozen):
    lost = []
    for u in rb["expected"]["units"]:
        t = audit.anchor_terms(u)
        if (not audit.is_anchored(norm(audit.learner_text(rb)), t) and audit.is_anchored(norm(frozen["input"]["effective_explanation"]), t)
                and not audit.is_anchored(norm(rb["input"]["effective_explanation"]), t)):
            lost.append(u["canonical"])
    return lost


def select(slice_refs, chl_all):
    """[(stratum, record or group records, dispute)] in selection order."""
    fz = [r for r in slice_refs if not r["id"].endswith("#rb") and "challenge" not in r["meta"]]
    rb = [r for r in slice_refs if r["id"].endswith("#rb")]
    by_id = {r["id"]: r for r in fz}
    chosen, out = set(), []

    def take(stratum, rs, dispute=None, key=None):
        if not rs:
            return
        k = key or rs[0]["id"]
        if k in chosen:
            return
        chosen.add(k)
        out.append((stratum, rs, dispute or {"status": "none", "raised_by": [], "positions": []}))

    for cl in clusters([r for r in fz if r["expected"]["units"]]):
        take("objective", first(cl))
    zero = [r for r in fz if not r["expected"]["units"]]
    for case in sorted({r["meta"].get("case_type") for r in zero}):
        take("zero", first([r for r in zero if r["meta"].get("case_type") == case]))
    for case in ("false_premise", "wrong_explanation"):
        if not any(by_id[i]["meta"].get("case_type") == case for i in chosen if i in by_id):
            take("false_premise", first([r for r in fz if r["meta"].get("case_type") == case]))
    for canon, note in OVER_GENERAL.items():
        holders = [r for r in fz if any(u["canonical"] == canon for u in r["expected"]["units"])]
        if not holders:
            continue
        present = [i for i in chosen if i in by_id and any(u["canonical"] == canon for u in by_id[i]["expected"]["units"])]
        if not present:
            take("over_general", first(holders))
    # Mark over-general disputes on whatever item holds such a unit.
    groups = {g: rs for g, rs in challenge.groups_of([r for r in chl_all if r["meta"]["split_group"] == "challenge_test"]).items()}
    hard = []
    for g, rs in groups.items():
        if rs[0]["meta"]["challenge"]["intent"] != "abstain":
            continue
        conf = next(r for r in rs if r["meta"]["challenge"]["variant"] == "conflicting")
        seen = _quoted_in_text(conf["input"]["effective_explanation"], audit.learner_text(conf))
        if seen:
            hard.append(g)
            take("cue_dispute", rs, {"status": "disputed", "raised_by": ["conflicting cue (machine analysis)"],
                                     "positions": [f"reference: zero units ({rs[0]['meta']['rationale']})",
                                                   f"cue: {conf['input']['effective_category']} — {conf['input']['effective_explanation']} "
                                                   f"(names {', '.join('« ' + s + ' »' for s in seen)}, present in the learner's text)"]},
                 key=g)
    ext = [rs for g, rs in groups.items() if rs[0]["meta"]["challenge"]["intent"] == "extract"]
    ab = [rs for g, rs in groups.items() if rs[0]["meta"]["challenge"]["intent"] == "abstain" and g not in hard]
    for rs in sorted(ext, key=lambda rs: h(rs[0]["meta"]["challenge"]["group_id"]))[:2]:
        take("challenge", rs, key=rs[0]["meta"]["challenge"]["group_id"])
    for rs in sorted(ab, key=lambda rs: h(rs[0]["meta"]["challenge"]["group_id"]))[:1]:
        take("challenge", rs, key=rs[0]["meta"]["challenge"]["group_id"])
    frozen_of = {r["id"]: r for r in fz}
    lost = [r for r in rb if r["meta"]["probe"]["derived_from"] not in chosen
            and _rb_anchor_lost(r, frozen_of[r["meta"]["probe"]["derived_from"]])]
    for r in first(lost, 2):
        src = frozen_of[r["meta"]["probe"]["derived_from"]]
        units = _rb_anchor_lost(r, src)
        take("rb_anchor", [r], {"status": "disputed", "raised_by": ["heuristic anchoring"],
                                "positions": [f"reference (inherited from {src['id']}): units {units}",
                                              "heuristic: under the rb view no French form of this unit is visible; the "
                                              "explanation that spelled it out was replaced by the production analyzer's"]})
    # over-general disputes on any chosen record holding such a unit
    final = []
    for stratum, rs, d in out:
        canons = [u["canonical"] for u in rs[0]["expected"]["units"] if u["canonical"] in OVER_GENERAL]
        if canons:
            d = {"status": "disputed", "raised_by": d["raised_by"] + ["agent reading (FLH-154 agent-review.json)"],
                 "positions": d["positions"] + [f"reference: {u['statement']}" for u in rs[0]["expected"]["units"]
                                                if u["canonical"] in canons] + [f"agent: {OVER_GENERAL[c]}" for c in canons]}
        final.append((stratum, rs, d))
    return final


def _unit_view(u):
    return {k: u[k] for k in ("kind", "canonical", "statement", "statement_zh", "example", "confidence")}


def packet(selection):
    rows = []
    for n, (stratum, rs, d) in enumerate(selection, 1):
        r = next((x for x in rs if x["meta"].get("challenge", {}).get("variant") == "aligned"), rs[0])
        i = r["input"]
        cues = ([{"variant": x["meta"]["challenge"]["variant"], "category": x["input"]["effective_category"],
                  "resolution": x["input"]["resolution"], "explanation": x["input"]["effective_explanation"]}
                 for x in sorted(rs, key=lambda x: challenge.VARIANTS.index(x["meta"]["challenge"]["variant"]))]
                if "challenge" in r["meta"] else
                [{"variant": "rb" if r["id"].endswith("#rb") else "frozen", "category": i["effective_category"],
                  "resolution": i["resolution"], "explanation": i["effective_explanation"]}])
        units = r["expected"]["units"]
        rows.append({
            "n": n, "id": r["meta"]["challenge"]["group_id"] if "challenge" in r["meta"] else r["id"],
            "record_ids": [x["id"] for x in rs], "packet": PACKET, "stratum": stratum,
            "part": "challenge_test" if "challenge" in r["meta"] else ("rb" if r["id"].endswith("#rb") else "frozen"),
            "case_type": r["meta"].get("case_type"), "points": r["meta"].get("points", []),
            "input": {"original_input": i["original_input"], "original_context": i["original_context"]}, "cues": cues,
            "reference": {"decision": "units" if units else "zero", "units": [_unit_view(u) for u in units],
                          "rationale": r["meta"].get("rationale"), "label_status": r["meta"].get("label_status")},
            "dispute": d,
            "review": {"intent": {"decision_ok": None, "objectives_ok": None, "missing_objective": "", "extra_objective": "",
                                  "note": ""},
                       "wording": [{"canonical": u["canonical"], "statement_true": None, "statement_zh_same": None,
                                    "canonical_ok": None, "example_ok": None, "fix": ""} for u in units],
                       "dispute_position": ""},
            "verdict": None, "reviewer": "", "date": "",
        })
    return rows


def selection_doc(rows, slice_sha, chl_sha):
    return {"schema": "flh_extraction_review_sample_selection_v1", "packet": PACKET, "salt": SALT, "offline_only": OFFLINE,
            "inputs": {"comparison_slice_sha256": slice_sha, "challenge_sha256": chl_sha},
            "rule": __doc__.split("Selection rule")[1].split("A dispute is recorded")[0].strip(),
            "items": len(rows), "records": sum(len(r["record_ids"]) for r in rows),
            "by_stratum": dict(Counter(r["stratum"] for r in rows)), "by_part": dict(Counter(r["part"] for r in rows)),
            "disputed": [r["id"] for r in rows if r["dispute"]["status"] == "disputed"],
            "objective_points_covered": len({p for r in rows for p in r["points"]}),
            "ids": [r["id"] for r in rows]}


def _line(t):
    """One Markdown line; the JSONL keeps the exact text with its line breaks."""
    return " ⏎ ".join(x.strip() for x in t.splitlines())


def markdown(rows, sel):
    L = [f"# Reviewer sample v1 — held-out references ({len(rows)} items)", "", f"> **{OFFLINE}**", "",
         "Fill `review` and `verdict` in `review-sample-v1.jsonl` (one JSON object per line). Answer **learning intent** (I1–I2) first, "
         "then **wording** (W1–W4) for each unit, only when the objective itself is right. A disputed item needs "
         "`dispute_position`. `review-agreement` reports intent and wording separately and never counts an unresolved "
         "dispute.", "",
         f"Selection (frozen; salt `{sel['salt']}`; slice `{sel['inputs']['comparison_slice_sha256'][:16]}…`, challenge "
         f"`{sel['inputs']['challenge_sha256'][:16]}…`): {json.dumps(sel['by_stratum'])}; "
         f"{sel['objective_points_covered']} objective points covered; {len(sel['disputed'])} disputed.", "",
         "## Rubric", "", "| Question | Mark yes, e.g. | Mark no, e.g. |", "|---|---|---|"]
    for q in RUBRIC["intent"] + RUBRIC["wording"]:
        L.append(f"| **{q['id']}** {q['question']} | {q['yes']} | {q['no']} |")
    d = RUBRIC["dispute"]
    L += [f"| **Dispute** {d['question']} | {d['yes']} | {d['no']} |", "", f"Verdict: {RUBRIC['verdict']}", "",
          "Rubric examples come from training, increment and boundary records, never from this sample.", "", "## Items", ""]
    for r in rows:
        L += [f"### {r['n']}. `{r['id']}` · {r['part']} · {r['stratum']}" + (" · **DISPUTED**" if r["dispute"]["status"] == "disputed" else ""), "",
              f"- input: {_line(r['input']['original_input'])}", f"- context: {_line(r['input']['original_context']) or '—'}"]
        for c in r["cues"]:
            L.append(f"- cues `{c['variant']}`: `{c['category']}` / `{c['resolution']}` — {c['explanation']}")
        if r["reference"]["decision"] == "zero":
            L.append("- reference: **zero units**")
        for u in r["reference"]["units"]:
            L += [f"- reference unit ({u['kind']}) **{u['canonical']}**: {u['statement']}", f"  - zh: {u['statement_zh']}",
                  f"  - example: {u['example'] or '—'}"]
        L.append(f"- rationale: {r['reference']['rationale']}")
        if r["dispute"]["status"] == "disputed":
            L.append(f"- dispute (raised by {', '.join(r['dispute']['raised_by'])}):")
            L += [f"  - {p}" for p in r["dispute"]["positions"]]
        L += ["- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- agreement
def _intent(r):
    i = r["review"]["intent"]
    if i["decision_ok"] is None or i["objectives_ok"] is None:
        return None
    return bool(i["decision_ok"] and i["objectives_ok"])


def _resolved(r):
    """A disputed item counts only once a reviewer gave a verdict other than
    quarantine and wrote the position taken (decision.reviewed applies the same
    rule when the packet is passed to decision-report --review)."""
    if (r.get("dispute") or {}).get("status") != "disputed":
        return True
    return r.get("verdict") in ("accept", "edit", "reject") and bool(((r.get("review") or {}).get("dispute_position") or "").strip())


WORD_FIELDS = ("statement_true", "statement_zh_same", "canonical_ok", "example_ok")
EVIDENCE_FIELDS = ("raised_by_learner", "claim_true")


def review_label(r):
    """COUNTED, OPEN DISPUTE or NO VERDICT: the state a person sees for one item."""
    if not r.get("verdict"):
        return "NO VERDICT"
    return "COUNTED" if _resolved(r) else "OPEN DISPUTE"


def _rate(n, d):
    return {"count": n, "of": d, "rate": round(n / d, 3) if d else None}


def _kappa(pairs):
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if pe == 1 else round((po - pe) / (1 - pe), 3)


def agreement(rows, second=None):
    unresolved = [r["id"] for r in rows if not _resolved(r)]
    counted = [r for r in rows if _resolved(r) and _intent(r) is not None]
    intent_ok = [r for r in counted if _intent(r)]
    units = [w for r in intent_ok for w in r["review"]["wording"]]
    judged = [w for w in units if all(w[f] is not None for f in WORD_FIELDS)]
    rep = {"schema": "flh_extraction_review_agreement_v1", "offline_only": OFFLINE, "items": len(rows),
           "unreviewed": sum(1 for r in rows if _intent(r) is None),
           "disputed_unresolved": unresolved,
           "intent_agreement_with_reference": _rate(len(intent_ok), len(counted)),
           "intent_disagreements": [{"id": r["id"], "decision_ok": r["review"]["intent"]["decision_ok"],
                                     "missing": r["review"]["intent"]["missing_objective"],
                                     "extra": r["review"]["intent"]["extra_objective"]} for r in counted if not _intent(r)],
           "wording_agreement_with_reference": {
               "scope": "units of items whose learning intent the reviewer accepted",
               "all_fields": _rate(sum(all(w[f] for f in WORD_FIELDS) for w in judged), len(judged)),
               **{f: _rate(sum(bool(w[f]) for w in judged), len(judged)) for f in WORD_FIELDS},
               "units_not_judged": len(units) - len(judged)},
           "never_combined": "intent, evidence and wording agreement are separate numbers; there is no overall score"}
    ev = [e for r in intent_ok for e in (r["review"].get("evidence") or [])]
    ev_judged = [e for e in ev if all(e[f] is not None for f in EVIDENCE_FIELDS)]
    rep["evidence_agreement_with_reference"] = {
        "scope": "units of items whose learning intent the reviewer accepted (review sheet column group B)",
        **{f: _rate(sum(bool(e[f]) for e in ev_judged), len(ev_judged)) for f in EVIDENCE_FIELDS},
        "units_not_judged": len(ev) - len(ev_judged)}
    labels = {r["id"]: review_label(r) for r in rows}
    rep["labels"] = {k: sorted(i for i, v in labels.items() if v == k) for k in ("COUNTED", "OPEN DISPUTE", "NO VERDICT")}
    if second is not None:
        other = {r["id"]: r for r in second}
        both = [(r, other[r["id"]]) for r in rows if r["id"] in other and _resolved(r) and _resolved(other[r["id"]])
                and _intent(r) is not None and _intent(other[r["id"]]) is not None]
        pairs = [(_intent(a), _intent(b)) for a, b in both]
        word = defaultdict(list)
        for a, b in both:
            if _intent(a) and _intent(b):
                for wa, wb in zip(a["review"]["wording"], b["review"]["wording"]):
                    for f in WORD_FIELDS:
                        if wa[f] is not None and wb[f] is not None:
                            word[f].append(wa[f] == wb[f])
        rep["between_reviewers"] = {"items_both_resolved": len(both),
                                    "intent": {**_rate(sum(a == b for a, b in pairs), len(pairs)), "cohen_kappa": _kappa(pairs)},
                                    "wording": {f: _rate(sum(v), len(v)) for f, v in sorted(word.items())},
                                    "disputed_unresolved_in_second": [r["id"] for r in second if not _resolved(r)]}
    return rep


# ---------------------------------------------------------------- export privacy
PRIVACY = [
    ("local_path", re.compile(r"(?:/home/|/Users/|/srv/|/mnt/|/tmp/|/var/folders/|[A-Za-z]:\\\\Users\\\\)[^\s\"']*")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("private_link", re.compile(r"https?://(?:claude\.ai|[\w.-]*\.internal|localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+)[^\s\"']*")),
    ("entry_id_nonzero", re.compile(r"\"entry_id\"\s*:\s*[1-9]\d*")),
    ("secret_like", re.compile(r"AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|(?i:api[_-]?key|password|secret)\"?\s*[:=]\s*\"?[A-Za-z0-9/+_-]{12,}")),
    ("aws_account", re.compile(r"\b(?!000000000000\b)\d{12}\b")),
]


def export_findings(text):
    return [{"rule": k, "excerpt": m.group(0)[:60]} for k, rx in PRIVACY for m in rx.finditer(text)]
