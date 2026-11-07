"""Daily-workflow v1.0 RC acceptance journey against a disposable database.

Usage: python3 -I -B journey.py BASE_URL DB_PATH CALL_LOG CASES_JSON EVIDENCE_JSON

Drives the real server over its public HTTP API, exactly as the workbench does,
with three authored cases and one failure boundary:
  1. an "en" question -> analysis -> accepted -> extraction -> explicit NEW CONCEPT;
  2. a second "en" question -> a suggestion recommends the existing Concept;
     generating changes nothing; an explicit confirmation records a human SAME;
     both units stay traceable to their own records;
  3. a related but distinct "y" question receives an unsuitable recommendation
     that is left unused: no membership, no label is recorded;
  4. stale boundary: a fourth question's suggestion becomes stale through an
     explicit re-extraction; confirmation is refused (409) and changes nothing.
Read-only SQLite counts (mode=ro) back the "nothing changed" claims. The fake
provider proves mechanics only, never language quality. Prints PASS/FAIL lines
and exits 1 on any failure.
"""
import json
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE, DB, LOG, CASES, EVIDENCE = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
if urllib.parse.urlparse(BASE).hostname not in ("127.0.0.1", "localhost", "::1"):
    sys.exit(f"refusing non-loopback backend {BASE}")
with open(CASES, encoding="utf-8") as f:
    cases = json.load(f)
failures = 0
evidence = {"checks": [], "ids": {}}


def call(method, path, body=None, headers=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read()
            return r.status, (json.loads(text) if text else None), dict(r.headers)
    except urllib.error.HTTPError as e:
        text = e.read()
        try:
            return e.code, json.loads(text), dict(e.headers)
        except ValueError:
            return e.code, text.decode(errors="replace"), dict(e.headers)


def get(path):
    s, body, _ = call("GET", path)
    if s != 200:
        raise SystemExit(f"GET {path} -> {s}: {body}")
    return body


def check(name, ok, detail=""):
    global failures
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" :: {detail}"))
    evidence["checks"].append({"check": name, "pass": bool(ok)})
    if not ok:
        failures += 1


def provider_calls(schema=None):
    with open(LOG, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [r for r in rows if schema is None or r["schema"] == schema]


# Tables whose rows are human decisions or current authority. Generation and
# "leave unused" must not change any of them.
AUTHORITY = ["unit_concept_memberships", "unit_concept_links", "unit_resolution_judgments",
             "unit_concept_distinctions", "knowledge_concepts", "knowledge_admission_overrides",
             "annotation_operations", "concept_suggestion_confirmations", "entry_current_extractions"]


def authority():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        out = {}
        for table in AUTHORITY:
            out[table] = con.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        return out
    finally:
        con.close()


def rows_for_unit(unit_id):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t} WHERE unit_id = ?", (unit_id,)).fetchone()[0]
                for t in ["unit_concept_memberships", "unit_concept_links", "unit_resolution_judgments",
                          "unit_concept_distinctions"]}
    finally:
        con.close()


def membership(unit_id):
    return get(f"/knowledge-units/{unit_id}/concept-membership")["current_membership"]


def reviewable_ids():
    return {u["unit_id"] for u in get("/reviewable-units")["reviewable_units"]}


def prepare(key):
    """Save the question, request analysis, accept it, request extraction."""
    case = cases["records"][key]
    before = len(provider_calls())
    s, saved, _ = call("POST", "/captures", {"schema_version": "learning_capture_v1", "capture_id": f"question-{uuid.uuid4()}",
                                             "source": "manual", "original_input": case["original_input"],
                                             "original_context": case["original_context"]})
    entry = saved["entry_id"]
    check(f"[{key}] saving the question stores record #{entry} and calls no provider",
          s == 201 and len(provider_calls()) == before, (s, saved))
    s, analysis, _ = call("POST", f"/entries/{entry}/analysis")
    check(f"[{key}] explicit analysis: one provider call, stored unreviewed",
          s == 201 and len(provider_calls()) == before + 1 and analysis["analyzer"].startswith("openai:"), (s, analysis))
    s, fb, _ = call("POST", f"/analyses/{analysis['id']}/feedback",
                    {"status": "accepted", "reviewed_explanation_languages": ["en", "zh"]})
    check(f"[{key}] human Accept is stored and calls no provider", s == 201 and len(provider_calls()) == before + 1, (s, fb))
    s, ex, _ = call("POST", f"/entries/{entry}/extractions")
    units = ex["units"] if s == 201 else []
    check(f"[{key}] explicit extraction: one provider call, {len(case['units'])} unit(s), distinct from the analysis",
          s == 201 and len(units) == len(case["units"]) and len(provider_calls()) == before + 2
          and units[0]["canonical"] == case["units"][0]["canonical"], (s, ex))
    evidence["ids"][key] = {"entry_id": entry, "analysis_id": analysis["id"], "extraction_id": ex.get("id"),
                            "unit_id": units[0]["id"] if units else None}
    return entry, units[0]["id"]


if get("/entries?limit=1")["entries"]:
    sys.exit("refusing: the database is not empty")
overview = get("/concept-suggestion-runs")
check("suggestions are enabled on this fixture server", overview["enabled"], overview)

# ---- Case 1: the first "en" question creates the Concept by explicit human decision.
entry_a, unit_a = prepare("en_first")
check("[case 1] the extracted unit awaits Concept Review and has no membership",
      unit_a in reviewable_ids() and membership(unit_a) is None)
s, created, _ = call("POST", "/concepts", {"identity": cases["en_concept_identity"], "seed_unit_id": unit_a, "link_seed_as_same": True})
concept = created["concept"]["id"] if s == 201 else None
evidence["ids"]["en_concept_id"] = concept
check("[case 1] explicit NEW CONCEPT creates the Concept and seeds a human SAME",
      s == 201 and created["link"]["decision_source"] == "human" and membership(unit_a)["concept_id"] == concept, (s, created))

# ---- Prepare the other three records (case 2, case 3, stale boundary).
entry_b, unit_b = prepare("en_second")
entry_y, unit_y = prepare("y_related")
entry_d, unit_d = prepare("en_stale")

# ---- Generation is advisory: it changes no authority table.
before = authority()
calls_before = len(provider_calls("concept_suggestions"))
key = str(uuid.uuid4())
s, run, headers = call("POST", "/concept-suggestion-runs", {"unit_ids": [unit_b, unit_y, unit_d]}, {"Idempotency-Key": key})
check("generating suggestions makes exactly one provider call and stores a completed run",
      s == 201 and run["status"] == "completed" and len(provider_calls("concept_suggestions")) == calls_before + 1, (s, run))
items = {i["unit_id"]: i for i in run.get("items", [])}
evidence["ids"]["suggestion_run_id"] = run.get("id")
evidence["ids"]["suggestion_items"] = {str(u): i["id"] for u, i in items.items()}
evidence["suggestion_candidates"] = provider_calls("concept_suggestions")[-1].get("candidates")
for unit, label in [(unit_b, "case 2"), (unit_y, "case 3"), (unit_d, "stale")]:
    item = items.get(unit, {})
    check(f"[{label}] the run recommends Concept #{concept} for unit #{unit} (state open)",
          item.get("outcome") == "suggested" and item.get("suggested_concept_id") == concept and item.get("state") == "open", item)
check("generation changed no membership, link, judgment, distinction, Concept, override or receipt",
      authority() == before)
check("after generation the suggested units are still unfiled and awaiting review",
      all(membership(u) is None for u in (unit_b, unit_y, unit_d)) and {unit_b, unit_y, unit_d} <= reviewable_ids())
s, replay, headers = call("POST", "/concept-suggestion-runs", {"unit_ids": [unit_b, unit_y, unit_d]}, {"Idempotency-Key": key})
check("a same-key resend replays the stored run without another provider call",
      s == 201 and replay["id"] == run["id"] and headers.get("Idempotency-Replayed") == "true"
      and len(provider_calls("concept_suggestions")) == calls_before + 1, (s, headers))

# ---- Case 2: explicit confirmation records one human SAME.
item_b = items[unit_b]
s, confirmed, _ = call("POST", f"/concept-suggestion-items/{item_b['id']}/confirm", {"concept_id": concept})
check("[case 2] Confirm SAME records a human SAME with suggestion provenance and calls no provider",
      s == 201 and confirmed["link"]["decision_source"] == "human" and "human_same_ai_suggestion" in confirmed["link"]["evidence"]
      and len(provider_calls("concept_suggestions")) == calls_before + 1, (s, confirmed))
check("[case 2] CURRENT SAME of the second unit is the existing Concept",
      membership(unit_b) and membership(unit_b)["concept_id"] == concept)
ann = get(f"/knowledge-units/{unit_b}/effective-annotation")
check("[case 2] the effective annotation is resolved by that human decision (what the record page shows)",
      ann["snapshot"]["status"] == "resolved" and ann["snapshot"]["current_same"]["decision"]["id"] == confirmed["link"]["id"], ann)
item_read = [i for i in get(f"/concept-suggestion-runs/{run['id']}")["items"] if i["unit_id"] == unit_b][0]
check("[case 2] the item reads back as confirmed and still current",
      item_read["state"] == "confirmed" and item_read["confirmation"]["still_current"] is True
      and item_read["current_concept_id"] == concept, item_read)
s, again, headers = call("POST", f"/concept-suggestion-items/{item_b['id']}/confirm", {"concept_id": concept})
check("[case 2] confirming again replays the same event and records nothing new",
      s == 201 and again["link"]["id"] == confirmed["link"]["id"] and headers.get("Idempotency-Replayed") == "true", (s, headers))
lib = get(f"/knowledge-library/concepts/{concept}")
supporting = {u["unit_id"]: u["entry_id"] for u in lib["supporting_units"]}
check("[case 2] the Concept is supported by both units, each with its own record",
      supporting == {unit_a: entry_a, unit_b: entry_b}, supporting)
for unit, entry, key_ in [(unit_a, entry_a, "en_first"), (unit_b, entry_b, "en_second")]:
    src = get(f"/knowledge-library/units/{unit}/source")
    original = cases["records"][key_]["original_input"]
    check(f"[case 2] unit #{unit} traces to record #{entry} with its original question unchanged",
          src["entry"]["id"] == entry and src["entry"]["original_input"] == original
          and get(f"/entries/{entry}")["original_input"] == original and src["annotation"]["current_concept_id"] == concept, src["entry"])

# ---- Case 3: the unsuitable recommendation is left unused (the workbench sends nothing).
check("[case 3] the y unit has no membership, link, judgment or distinction row",
      rows_for_unit(unit_y) == {"unit_concept_memberships": 0, "unit_concept_links": 0,
                                "unit_resolution_judgments": 0, "unit_concept_distinctions": 0}, rows_for_unit(unit_y))
y_item = [i for i in get(f"/concept-suggestion-runs/{run['id']}")["items"] if i["unit_id"] == unit_y][0]
y_ann = get(f"/knowledge-units/{unit_y}/effective-annotation")["snapshot"]
check("[case 3] the y item stays open, the unit unresolved and still awaiting review",
      y_item["state"] == "open" and y_item["confirmation"] is None and y_ann["status"] == "unresolved"
      and not y_ann["distinctions"] and not y_ann["relations"] and unit_y in reviewable_ids(), (y_item["state"], y_ann))
check("[case 3] the en Concept still has exactly the two confirmed members",
      {u["unit_id"] for u in get(f"/knowledge-library/concepts/{concept}")["supporting_units"]} == {unit_a, unit_b})

# ---- Failure boundary: the suggestion becomes stale before confirmation.
s, re_ex, _ = call("POST", f"/entries/{entry_d}/extractions")
new_unit_d = re_ex["units"][0]["id"] if s == 201 else None
evidence["ids"]["en_stale"]["new_extraction_id"] = re_ex.get("id")
evidence["ids"]["en_stale"]["new_unit_id"] = new_unit_d
check("[stale] an explicit re-extraction stores version 2 and makes it current",
      s == 201 and re_ex["version"] == 2 and get(f"/entries/{entry_d}/current-extraction")["current_extraction_id"] == re_ex["id"], (s, re_ex))
d_item = [i for i in get(f"/concept-suggestion-runs/{run['id']}")["items"] if i["unit_id"] == unit_d][0]
check("[stale] the run now reports the item stale: unit no longer in the current extraction",
      d_item["state"] == "stale" and "unit_not_in_current_extraction" in d_item["stale_reasons"], d_item)
before = authority()
s, refused, _ = call("POST", f"/concept-suggestion-items/{d_item['id']}/confirm", {"concept_id": concept})
evidence["stale_refusal"] = {"status": s, "body": refused}
check("[stale] confirmation is refused with 409 naming the reason", s == 409 and "unit_not_in_current_extraction" in json.dumps(refused), (s, refused))
check("[stale] the refusal changed no authority table", authority() == before)
check("[stale] neither the old nor the new unit gained a membership",
      membership(unit_d) is None and membership(new_unit_d) is None and new_unit_d in reviewable_ids())

# ---- Totals and evidence.
by_schema = {}
for c in provider_calls():
    by_schema[c["schema"]] = by_schema.get(c["schema"], 0) + 1
evidence["provider_calls"] = by_schema
check("provider calls: 4 analyses, 5 extractions, 1 suggestion run; all with the configured model and a bearer token",
      by_schema == {"analysis_result": 4, "knowledge_units": 5, "concept_suggestions": 1}
      and all(c["bearer"] and c["model"] == "fixture-model-placeholder" for c in provider_calls()), by_schema)
evidence["failures"] = failures
with open(EVIDENCE, "w", encoding="utf-8") as f:
    json.dump(evidence, f, ensure_ascii=False, indent=2)
print(f"{len(evidence['checks']) - failures} passed, {failures} failed")
sys.exit(1 if failures else 0)
