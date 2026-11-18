"""Per-unit reviewer evidence for the experimental report (OFFLINE ONLY; not a scoring source).

  python3 -m flh_extraction reviewer-queue --matrix M.json --slice S.jsonl --render BIN
         --predictions SYSTEM=FILE … [--scope-ids IDS.txt | --scope-packet P.jsonl] --out PREFIX
      writes PREFIX.json (the queue), PREFIX.evidence-template.jsonl (one blank row per
      unit to review) and PREFIX.md (what the reviewer reads)

Why: the automatic metrics accept output they cannot judge. A plausible unit
linked to the wrong source, a false or over-general claim and a Chinese
statement that drifts from the English all pass the production validator, the
exact gates and every string heuristic (fixtures/one_record_v1). Only a person
can say whether this record raised the objective, whether the claim is true
and whether the Chinese says the same.

Queue (flh_extraction_reviewer_queue_v1): for every system and every record in
the review scope, each unit of a scorable `valid_units` row is one item, bound
to that row by (system, id, unit index, unit_sha256). `unit_sha256` is the
SHA-256 of the unit as the production validator accepted it (canonical JSON:
sorted keys, no spaces, UTF-8). Scorable empty rows are listed as abstentions
(the exact metrics judge them against the reference; the reference review
judges the reference). Rows that are not scorable are listed and need no unit
review (the strict count already fails them). The queue records the matrix,
the slice and each system's row accounting, so it can only be used with the
comparison it was built from.

Evidence (flh_extraction_reviewer_evidence_v1), one JSONL row per item:

  {"schema": "flh_extraction_reviewer_evidence_v1", "system": "...", "id": "...", "unit": 0,
   "unit_sha256": "...", "source_raised": "yes|no|null", "claim_true": "yes|no|null",
   "zh_same": "yes|no|null", "reviewer": "...", "date": "YYYY-MM-DD", "note": "..."}

  source_raised  did THIS record's learner text raise the objective (not only the
                 explanation, not an earlier message quoted in the context)?  UNSUPPORTED
  claim_true     is the statement true of standard French and not over-general?  FALSE_CLAIM
  zh_same        does statement_zh say the same thing as statement?  BILINGUAL_MISMATCH

Per system (the criterion the experimental report adds):

  FAIL     any bound row answers `no` (an explicit failure blocks the system, whatever
           the other answers, its sample rates or its F1; a `no` in a duplicated row
           counts too)
  PENDING  any in-scope unit has no row, a blank answer, no reviewer, only rows bound
           to another output (stale hash) or two rows (never choose between reviews);
           the queue is missing, lacks the system, or was built for another comparison
  PASS     every in-scope unit has exactly one bound row with three `yes` answers and a
           reviewer (a system with no unit in scope passes with nothing to review)

Answers other than "yes", "no", null or "" are refused (the file is not used),
never read as a guess.
"""

import hashlib
import json
from collections import defaultdict

from . import audit, evaluate
from .textnorm import norm

QUEUE_SCHEMA = "flh_extraction_reviewer_queue_v1"
EVIDENCE_SCHEMA = "flh_extraction_reviewer_evidence_v1"
QUESTIONS = {
    "source_raised": "Did THIS record's learner text raise the objective (not only the explanation, not an earlier message "
                     "quoted in the context)? (UNSUPPORTED when no)",
    "claim_true": "Is the statement true of standard French and not over-general? (FALSE_CLAIM when no)",
    "zh_same": "Does statement_zh say the same thing as statement (scope, claim, quoted forms)? (BILINGUAL_MISMATCH when no)",
}
ANSWERS = ("yes", "no")
KEYS = ("system", "id", "unit", "unit_sha256")
CRITERION = "reviewer evidence: every in-scope unit reviewed, no explicit failure"


def unit_sha256(u):
    return hashlib.sha256(json.dumps(u, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def automatic(rec, units):
    """What the existing automatic checks say about each unit (informative only:
    every in-scope unit needs a review whatever they say)."""
    ref = rec["expected"]["units"]
    pairs = dict(evaluate.best_assignment([[evaluate.similarity(p, r) for r in ref] for p in units])) if ref and units else {}
    lt, vt = norm(audit.learner_text(rec)), norm(audit.visible_text(rec))
    out = []
    for k, u in enumerate(units):
        t = audit.anchor_terms(u)
        grounding = ("learner_text_or_context" if audit.is_anchored(lt, t) else
                     "explanation_only" if audit.is_anchored(vt, t) else "not_anchored")
        flags = audit.bilingual_findings(u)
        matcher = "reference has zero units" if not ref else (f"matched reference unit {pairs[k]}" if k in pairs else "unmatched")
        out.append({"matcher": matcher, "grounding": grounding, "bilingual_flags": flags,
                    "accepted_by_every_automatic_check": bool(ref) and k in pairs and grounding == "learner_text_or_context"
                    and not flags})
    return out


def queue(refs, accounts, scope_ids, matrix_sha256, slice_sha256, scope_source):
    """accounts: {system: comparison.account(...) or matrix.account_results(...)}."""
    by_id = {r["id"]: r for r in refs}
    scope = set(scope_ids)
    if not scope:
        raise ValueError("the review scope is empty")
    unknown = sorted(scope - set(by_id))
    if unknown:
        raise ValueError(f"scope ids not in the slice: {unknown[:5]}")
    order = [r["id"] for r in refs if r["id"] in scope]
    q = {"schema": QUEUE_SCHEMA, "status": "OFFLINE ONLY; reviewer work list, not a score", "matrix_sha256": matrix_sha256,
         "slice_sha256": slice_sha256, "scope": {"source": scope_source, "records": len(order), "ids": order},
         "questions": QUESTIONS, "systems": {}}
    for s, acc in sorted(accounts.items()):
        rows = {r["id"]: r for r in acc["rows"]}
        items, empty, other = [], [], {}
        for rid in order:
            row = rows[rid]
            if row["status"] == "valid_units":
                units = row["result"]["units"]
                for k, (u, a) in enumerate(zip(units, automatic(by_id[rid], units))):
                    items.append({"id": rid, "unit": k, "unit_sha256": unit_sha256(u), "content": u,
                                  "reference_decision": "units" if by_id[rid]["expected"]["units"] else "zero", "automatic": a})
            elif row["status"] == "valid_empty":
                empty.append(rid)
            else:
                other[rid] = row["status"]
        q["systems"][s] = {"rows": {k: acc[k] for k in ("references", "scorable", "status_counts")}, "units_in_scope": len(items),
                           "items": items, "abstentions_in_scope": empty, "not_scorable_in_scope": other}
    return q


def template(q):
    """One blank evidence row per queue item (answers null)."""
    return [{"schema": EVIDENCE_SCHEMA, "system": s, "id": i["id"], "unit": i["unit"], "unit_sha256": i["unit_sha256"],
             **dict.fromkeys(QUESTIONS), "reviewer": "", "date": "", "note": ""}
            for s, v in q["systems"].items() for i in v["items"]]


def load_evidence(rows):
    """Validates evidence rows; raises ValueError naming every problem."""
    problems = []
    for k, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            problems.append(f"row {k}: not an object")
            continue
        if r.get("schema", EVIDENCE_SCHEMA) != EVIDENCE_SCHEMA:
            problems.append(f"row {k}: schema {r.get('schema')!r} is not {EVIDENCE_SCHEMA}")
        miss = [x for x in KEYS if x not in r]
        if miss:
            problems.append(f"row {k}: missing {', '.join(miss)}")
        if "unit" in r and (not isinstance(r["unit"], int) or isinstance(r["unit"], bool)):
            problems.append(f"row {k}: unit must be an integer index")
        for qn in QUESTIONS:
            v = r.get(qn)
            if v not in (None, "") + ANSWERS:
                problems.append(f"row {k}: {qn} {v!r} is not yes, no or blank (never read as a guess)")
    if problems:
        raise ValueError("; ".join(problems))
    return rows


def _blank(v):
    return v is None or v == ""


def criterion(qsys, rows):
    """(status, evidence) for one system's queue entry and its evidence rows."""
    items = {(i["id"], i["unit"]): i for i in qsys["items"]}
    keyed = defaultdict(list)
    for r in rows:
        keyed[(r["id"], r["unit"])].append(r)
    failed, missing, stale, incomplete, duplicate, done = [], [], [], [], [], 0
    for key, it in items.items():
        rs = keyed.get(key, [])
        bound = [r for r in rs if r.get("unit_sha256") == it["unit_sha256"]]
        no = sorted({qn for r in bound for qn in QUESTIONS if r.get(qn) == "no"})
        if no:
            failed.append({"id": key[0], "unit": key[1], "answered_no": no,
                           "reviewer": sorted({r.get("reviewer") or "" for r in bound}), "note": [r.get("note") or "" for r in bound if r.get("note")]})
        if not rs:
            missing.append(f"{key[0]}#{key[1]}")
        elif not bound:
            stale.append(f"{key[0]}#{key[1]}")
        elif len(bound) > 1:
            duplicate.append(f"{key[0]}#{key[1]}")
        elif any(_blank(bound[0].get(qn)) for qn in QUESTIONS) or not (bound[0].get("reviewer") or "").strip():
            incomplete.append(f"{key[0]}#{key[1]}")
        elif not no:
            done += 1
    unbound = sorted(f"{r['id']}#{r['unit']}" for r in rows if (r["id"], r["unit"]) not in items)
    ev = {"units_in_scope": len(items), "reviewed_yes": done, "failed": failed, "missing": missing, "stale_hash": stale,
          "incomplete": incomplete, "duplicate": duplicate, "rows_for_no_queue_item": unbound}
    if failed:
        return "FAIL", ev
    if missing or stale or incomplete or duplicate:
        return "PENDING", ev
    return "PASS", ev


def binding_problems(q, comparison, system):
    """Why this queue cannot vouch for this system in this comparison (empty = it can)."""
    if q.get("schema") != QUEUE_SCHEMA:
        return [f"not a {QUEUE_SCHEMA} file"]
    out = []
    if q.get("matrix_sha256") != comparison.get("matrix_sha256"):
        out.append(f"queue built for matrix {str(q.get('matrix_sha256'))[:12]}, comparison uses {str(comparison.get('matrix_sha256'))[:12]}")
    qs = q["systems"].get(system)
    if qs is None:
        return out + ["system not in the reviewer queue"]
    rows = (comparison["systems"].get(system) or {}).get("rows") or {}
    for k in ("references", "scorable", "status_counts"):
        if qs["rows"].get(k) != rows.get(k):
            out.append(f"queue {k} {json.dumps(qs['rows'].get(k))} differs from the comparison's {json.dumps(rows.get(k))}")
    return out


def system_criterion(q, evidence, comparison, system):
    """The experimental report's per-system criterion."""
    if q is None:
        return {"criterion": CRITERION, "basis": "human (per unit)", "status": "PENDING", "evidence": "no reviewer queue"}
    bad = binding_problems(q, comparison, system)
    if bad:
        return {"criterion": CRITERION, "basis": "human (per unit)", "status": "PENDING", "evidence": {"queue_mismatch": bad}}
    st, ev = criterion(q["systems"][system], [r for r in (evidence or []) if r.get("system") == system])
    if evidence is None and ev["units_in_scope"]:
        ev["note"] = "no evidence file given"
    return {"criterion": CRITERION, "basis": "human (per unit)", "status": st, "evidence": ev}


def markdown(q):
    L = [f"# Reviewer queue (OFFLINE ONLY): {q['scope']['records']} records in scope", "",
         f"Matrix `{str(q['matrix_sha256'])[:16]}…`, slice `{str(q['slice_sha256'])[:16]}…`, scope: {q['scope']['source']}.", "",
         "Answer each question `yes` or `no` in the evidence file (one row per unit; blank = not reviewed):", ""]
    L += [f"- `{k}`: {v}" for k, v in q["questions"].items()] + [""]
    for s, v in q["systems"].items():
        L += [f"## {s}: {v['units_in_scope']} units to review", "",
              f"Abstentions in scope (judged exactly against the reference): {len(v['abstentions_in_scope'])}; "
              f"not scorable in scope (already failed by the strict count): {len(v['not_scorable_in_scope'])}.", ""]
        if v["items"]:
            L += ["| Record | Unit | Reference | Canonical | Statement | 中文 | Automatic checks |", "|---|---|---|---|---|---|---|"]
            for i in v["items"]:
                c, a = i["content"], i["automatic"]
                auto = "all accept" if a["accepted_by_every_automatic_check"] else f"{a['matcher']}; {a['grounding']}; {a['bilingual_flags'] or 'no flags'}"
                L.append(f"| `{i['id']}` | {i['unit']} | {i['reference_decision']} | {_cell(c['canonical'])} | {_cell(c['statement'])} "
                         f"| {_cell(c['statement_zh'])} | {auto} |")
            L.append("")
    return "\n".join(L) + "\n"


def _cell(s):
    return " ".join(str(s).split()).replace("|", "\\|")
