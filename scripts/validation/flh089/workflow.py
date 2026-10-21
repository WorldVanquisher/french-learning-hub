"""FLH-089 complete daily workflow against the seeded fixture, through the HTTP API.

Usage: python3 -B workflow.py http://127.0.0.1:PORT

Walks capture -> find record -> review interpretation -> explicit extraction ->
Concept organization -> original-source inspection with the same endpoints the
workbench calls, and checks the record-finding paths the FLH-089 UI uses
(newest page, a direct cursor jump to an old record, filters, the last page).
It writes one capture, one feedback, one extraction and three annotation
decisions to the disposable fixture database.

FLH-090 additions: finding records by text (?q=), and the paged review queue
with a unit decided between page requests and a resume through from_unit_id.

FLH-091 additions: the plain-question intake payload (a manual
learning_capture_v1 without analysis) creates an unanalyzed record with no
analysis or extraction, keeps the text, replays idempotently and conflicts on
changed content. Loopback only. It proves API
mechanics on synthetic data, not learning quality or browser behaviour.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1].rstrip("/")
if urllib.parse.urlparse(BASE).hostname not in ("127.0.0.1", "localhost", "::1"):
    sys.exit("refusing non-loopback backend")
results = []


def call(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read()
            return r.status, json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


# 1. Capture import (a new record, with an imported analysis).
capture = {
    "schema_version": "learning_capture_v1", "capture_id": "flh089-workflow-01", "source": "manual",
    "original_input": "[fx:5001] Workflow check: « bien que » + subjonctif ?",
    "original_context": "FLH-089 synthetic workflow check.",
    "discussion_summary": "Synthetic discussion for the workflow check.",
    "analysis": {"category": "grammar", "explanation": "Concession takes the subjunctive.", "confidence": 0.8,
                 "uncertainty": "Synthetic."},
}
st, cap = call("POST", "/captures", capture)
check("capture import creates a record (201)", st == 201, (st, cap))
eid = cap["entry_id"] if st == 201 else cap.get("entry_id")
st, again = call("POST", "/captures", capture)
check("identical capture replays idempotently (200, same entry)", st == 200 and again.get("entry_id") == eid, (st, again))

# 2. Find the record: newest page, and old records by a direct cursor jump.
st, page = call("GET", "/learning-records?limit=20")
check("new record is first on the newest page", st == 200 and page["records"][0]["entry_id"] == eid)
st, jump = call("GET", "/learning-records?limit=20&before_entry_id=4")
check("jump to record #3 is one request and reaches the last page",
      [r["entry_id"] for r in jump["records"]] == [3, 2, 1] and jump["next_before_entry_id"] is None)
# Corrected fixture records carry a corrected category; "translation" exists among them.
st, jf = call("GET", "/learning-records?state=corrected&category=translation&limit=20&before_entry_id=501")
ids = [r["entry_id"] for r in jf.get("records", [])]
check("jump combined with state and effective-category filters stays filtered and descending",
      st == 200 and ids and ids == sorted(ids, reverse=True) and all(
          r["state"] == "corrected" and r["effective"]["category"] == "translation" and r["entry_id"] <= 500
          for r in jf["records"]), (st, ids[:5]))

# 3. Review the interpretation (explicit human feedback).
st, analyses = call("GET", f"/entries/{eid}/analyses")
aid = analyses["analyses"][0]["id"]
st, eff = call("GET", f"/analyses/{aid}/effective")
check("imported interpretation is unreviewed before review", eff["resolution"] == "unreviewed" and eff["feedback_id"] is None, eff)
st, fb = call("POST", f"/analyses/{aid}/feedback", {"status": "accepted"})
check("explicit acceptance is stored (201)", st == 201, (st, fb))
st, row = call("GET", f"/learning-records?limit=1&before_entry_id={eid + 1}")
check("inventory row now reports accepted", row["records"][0]["state"] == "accepted")

# 4. Explicit extraction.
st, ext = call("POST", f"/entries/{eid}/extractions")
check("explicit extraction succeeds with units", st == 201 and len(ext["units"]) == 3, (st, ext))
units = [u["id"] for u in ext["units"]]
st, cur = call("GET", f"/entries/{eid}/current-extraction")
check("the new extraction is current (automatic selection)", cur["current_extraction_id"] == ext["id"] and cur["selection_mode"] == "automatic")

# 5. Concept organization: the record-scoped queue, SAME to an existing Concept, NEW CONCEPT.
st, rq = call("GET", f"/reviewable-units?entry_id={eid}")
check("record-scoped review queue lists the three new units", sorted(u["unit_id"] for u in rq["reviewable_units"]) == sorted(units))
st, catalog = call("GET", "/concepts")
target = next(c for c in catalog["concepts"] if c["target"] == "synthetic concept 0042")
st, same = call("POST", f"/knowledge-units/{units[0]}/concept-links/same", {"concept_id": target["id"]})
check("SAME to a catalog Concept is recorded", st == 201, (st, same))
identity = {"target": "flh089 workflow concession", "pedagogical_intent": "grammar", "scope": "", "identity_features": {}}
st, new = call("POST", "/concepts", {"identity": identity, "seed_unit_id": units[1], "link_seed_as_same": True})
check("NEW CONCEPT with the seed unit as SAME is recorded", st == 201, (st, new))
st, rq2 = call("GET", f"/reviewable-units?entry_id={eid}")
check("decided units leave the queue; the third remains", [u["unit_id"] for u in rq2["reviewable_units"]] == [units[2]])

# 6. Original-source inspection from the Concept.
st, lib = call("GET", f"/knowledge-library/concepts/{target['id']}")
def ids_in(value, key="unit_id"):
    if isinstance(value, dict):
        return {v for k, v in value.items() if k == key} | {x for v in value.values() for x in ids_in(v, key)}
    if isinstance(value, list):
        return {x for v in value for x in ids_in(v, key)}
    return set()


check("library Concept detail lists the new member", st == 200 and units[0] in ids_in(lib), st)
st, src = call("GET", f"/knowledge-library/units/{units[0]}/source")
check("unit source shows the learner's original input", st == 200 and capture["original_input"] in json.dumps(src, ensure_ascii=False), st)

# 7. FLH-090: find records by text, including one far beyond the first page.
st, found = call("GET", "/learning-records?limit=20&q=" + urllib.parse.quote("workflow check"))
check("text search finds the new record (case-insensitive)", st == 200 and [r["entry_id"] for r in found["records"]] == [eid], found)
st, old = call("GET", "/learning-records?limit=20&q=" + urllib.parse.quote("Synthetic question 7:"))
check("text search reaches an old record (#7) in one request", st == 200 and [r["entry_id"] for r in old["records"]] == [7], old)
st, lit = call("GET", "/learning-records?limit=20&q=" + urllib.parse.quote("% est-ce"))
check("wildcard characters are literal (no record contains '% est-ce')", st == 200 and lit["records"] == [], lit)

# 8. FLH-090: paged queue, a unit decided between page requests.
st, legacy = call("GET", "/reviewable-units")
legacy_ids = [u["unit_id"] for u in legacy["reviewable_units"]]
st, p1 = call("GET", "/reviewable-units?limit=50")
target2 = legacy_ids[60]  # on page 2
st, inv = call("POST", f"/knowledge-units/{target2}/invalid", {})
check("INVALID between page requests is recorded", st in (200, 201), (st, inv))
st, p2 = call("GET", "/reviewable-units?limit=50&after=" + urllib.parse.quote(p1["next_cursor"]))
ids1 = [u["unit_id"] for u in p1["reviewable_units"]]
ids2 = [u["unit_id"] for u in p2["reviewable_units"]]
check("page 2 omits the unit decided after page 1 and repeats no page-1 unit",
      target2 not in ids2 and not set(ids1) & set(ids2) and ids2 == [i for i in legacy_ids[50:101] if i != target2][:50], ids2[:5])

# 9. FLH-090: resume from a unit that is no longer reviewable (bounded locator).
st, resumed = call("GET", f"/reviewable-units?limit=50&from_unit_id={target2}")
check("from_unit_id of a decided unit starts at the next unit in queue order",
      st == 200 and resumed["reviewable_units"][0]["unit_id"] == legacy_ids[61], resumed["reviewable_units"][:1])
st, scoped = call("GET", f"/reviewable-units?entry_id={eid}&limit=200")
check("record-scoped paged queue lists the record's remaining unit", [u["unit_id"] for u in scoped["reviewable_units"]] == [units[2]])

# 10. FLH-091: a plain question, exactly as the workbench's Question mode sends it.
qid = "question-0b6f6f2e-1d4a-4c3e-9a51-0f0e5d1c2b3a"
question = {"schema_version": "learning_capture_v1", "capture_id": qid, "source": "manual",
            "original_input": "  Pourquoi « il faut que je fasse »\n  et pas « fais » ?  ",
            "original_context": "Cours du mardi,  exercice 3"}
st, q = call("POST", "/captures", question)
check("question save creates a record without analysis (201, analysis_id null)", st == 201 and q.get("analysis_id") is None, (st, q))
qe = q.get("entry_id")
st, qe_analyses = call("GET", f"/entries/{qe}/analyses")
st2, qe_ext = call("GET", f"/entries/{qe}/extractions")
check("no analysis and no extraction exist for the saved question",
      qe_analyses.get("analyses") == [] and qe_ext.get("extractions") == [], (qe_analyses, qe_ext))
st, qrow = call("GET", f"/learning-records?limit=1&before_entry_id={qe + 1}")
r0 = qrow["records"][0]
check("the saved question is listed as unanalyzed, with interior whitespace and newline kept (ends trimmed)",
      r0["entry_id"] == qe and r0["state"] == "unanalyzed"
      and r0["original_input"] == "Pourquoi « il faut que je fasse »\n  et pas « fais » ?"
      and r0["original_context"] == "Cours du mardi,  exercice 3", r0)
st, again = call("POST", "/captures", question)
check("resending the identical question replays (200, same record)", st == 200 and again.get("entry_id") == qe, (st, again))
st, conflict = call("POST", "/captures", {**question, "original_input": "changed text"})
check("the same identity with changed text is refused as a conflict (409)", st == 409, (st, conflict))
st, receipt = call("GET", f"/captures/{qid}")
check("the receipt lookup confirms the stored record", st == 200 and receipt.get("entry_id") == qe and receipt.get("source") == "manual", receipt)
st, missing = call("GET", "/captures/question-00000000-0000-4000-8000-000000000000")
check("an unknown identity is reported as not stored (404)", st == 404, st)

failed = [n for n, ok in results if not ok]
print(f"workflow: {len(results) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
