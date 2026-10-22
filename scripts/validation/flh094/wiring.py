"""FLH-094 wiring checks: the five daily-use steps against a fake provider.

Usage: python3 -B wiring.py BASE_URL CALL_LOG MODEL PHASE STATE_FILE
  PHASE first   - run the workflow on a fresh database, write STATE_FILE
  PHASE restart - after a server restart on the same database, verify it

Proves configuration wiring and explicit-call boundaries only: which actions
reach the provider, with which model and schema, what provenance is stored,
and what is never called. The fake provider's text is not language evidence.
Prints PASS/FAIL lines; exits 1 on any failure.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE, LOG, MODEL, PHASE, STATE = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
if urllib.parse.urlparse(BASE).hostname not in ("127.0.0.1", "localhost", "::1"):
    sys.exit(f"refusing non-loopback backend {BASE}")
failures = 0


def call(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read()
            return r.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        text = e.read()
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, text.decode(errors="replace")


def check(name, ok, detail=""):
    global failures
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" :: {detail}"))
    if not ok:
        failures += 1


def calls():
    with open(LOG, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def record(entry_id):
    s, body = call("GET", f"/learning-records?limit=1&before_entry_id={entry_id + 1}")
    rows = [r for r in body["records"] if r["entry_id"] == entry_id]
    return rows[0] if rows else None


if PHASE == "first":
    s, body = call("GET", "/entries?limit=1")
    if body["entries"]:
        sys.exit("refusing: the database is not empty")

    # 1. Saving a plain question (what the workbench's Question mode sends).
    question = "Pourquoi dit-on « je me souviens de » mais « je me rappelle » sans « de » ?\nC'est pour un courriel."
    s, saved = call("POST", "/captures", {"schema_version": "learning_capture_v1", "capture_id": f"question-{uuid.uuid4()}",
                                           "source": "manual", "original_input": question, "original_context": "Courriel au travail."})
    q = saved["entry_id"]
    check("1. saving a plain question stores a record (201) and calls no provider", s == 201 and len(calls()) == 0, (s, calls()))
    check("1. the saved question is unanalyzed, text unchanged", record(q)["state"] == "unanalyzed" and record(q)["original_input"] == question, record(q))

    # 2. Importing Capture JSON with a candidate Analysis.
    s, imp = call("POST", "/captures", {
        "schema_version": "learning_capture_v1", "capture_id": "flh094-import-1", "source": "chatgpt-web",
        "original_input": "Je parle japonais ou je parle le japonais ?", "original_context": "",
        "analysis": {"category": "grammar", "explanation": "After parler, no article.", "confidence": 0.9, "uncertainty": ""}})
    imported = imp["entry_id"]
    r = record(imported)
    check("2. importing Capture JSON calls no provider", s == 201 and len(calls()) == 0, (s, calls()))
    check("2. the imported Analysis is unreviewed with imported provenance",
          r["state"] == "unreviewed" and r["analyzer"].startswith("imported:chatgpt-web:"), r)

    # Extraction is refused for an unanalyzed record before any provider call.
    s, body = call("POST", f"/entries/{q}/extractions")
    check("4. extraction of an unanalyzed record is refused before any provider call", s >= 400 and len(calls()) == 0, (s, body))

    # 3. Explicit analysis uses the configured analyzer once.
    s, analysis = call("POST", f"/entries/{q}/analysis")
    c = calls()
    check("3. explicit analysis calls the provider exactly once, with the configured model and a bearer token",
          s == 201 and len(c) == 1 and c[0]["schema"] == "analysis_result" and c[0]["model"] == MODEL and c[0]["bearer"], (s, c))
    check("3. the stored analysis records the real-provider provenance",
          analysis["analyzer"] == f"openai:{MODEL}:fr_l2_taxonomy_v1.explanation_en_zh_v1" and record(q)["state"] == "unreviewed", analysis)

    check("3. the same call stored both explanation languages (FLH-095)",
          analysis["explanations"]["en"] == analysis["explanation"] and bool(analysis["explanations"]["zh"]), analysis)

    # A human accepts it (the test's stand-in for a real review).
    s, fb = call("POST", f"/analyses/{analysis['id']}/feedback", {"status": "accepted"})
    check("human feedback is a separate record and calls no provider", s == 201 and len(calls()) == 1, (s, len(calls())))

    # 4. Explicit extraction uses the configured extractor once.
    s, ext = call("POST", f"/entries/{q}/extractions")
    c = calls()
    check("4. explicit extraction calls the provider exactly once, with the configured model",
          s == 201 and len(c) == 2 and c[1]["schema"] == "knowledge_units" and c[1]["model"] == MODEL, (s, c))
    check("4. the extraction records the real-provider provenance and its units",
          ext["extractor"] == f"openai:{MODEL}:knowledge_extraction_v2" and len(ext["units"]) == 2, ext)

    # Zero units is a valid result.
    s, hello = call("POST", "/entries", {"original_input": "Bonjour, comment ça va ?", "original_context": ""})
    h = hello["id"]
    s, a2 = call("POST", f"/entries/{h}/analysis")
    s, ext0 = call("POST", f"/entries/{h}/extractions")
    check("4. an extraction may return zero units and is still stored", s == 201 and ext0["units"] == [] and ext0["version"] == 1, (s, ext0))

    # Provider failure: reported, nothing stored, not retried.
    s, bad = call("POST", "/entries", {"original_input": "Test ERREUR-FOURNISSEUR", "original_context": ""})
    b = bad["id"]
    before = len(calls())
    s, err = call("POST", f"/entries/{b}/analysis")
    after = len(calls())
    s2, versions = call("GET", f"/entries/{b}/analyses")
    secret_leak = isinstance(err, dict) and "sk-" in json.dumps(err)
    check("3. a provider failure is an error response, stores no analysis and is not retried",
          s >= 500 and after - before == 1 and versions["analyses"] == [] and not secret_leak, (s, err, after - before, versions))

    # 5. Concept membership stays an explicit human decision.
    before = len(calls())
    s, page = call("GET", "/reviewable-units?limit=50")
    unit_ids = [u["unit_id"] for u in page["reviewable_units"]]
    memberships = [call("GET", f"/knowledge-units/{u}/concept-membership")[1]["current_membership"] for u in unit_ids]
    for u in unit_ids:
        call("GET", f"/knowledge-units/{u}/concept-resolution")
    check("5. extracted units await review with no automatic SAME membership",
          sorted(unit_ids) == sorted(u["id"] for u in ext["units"]) and all(m is None for m in memberships), (unit_ids, memberships))
    check("5. reading the review queue and resolution calls no provider", len(calls()) == before, len(calls()) - before)
    s, made = call("POST", "/concepts", {"identity": {"target": "se souvenir de / se rappeler", "pedagogical_intent": "grammar",
                                                      "scope": "", "identity_features": {}},
                                         "seed_unit_id": unit_ids[0], "link_seed_as_same": True})
    check("5. an explicit NEW CONCEPT decision is recorded and calls no provider", s == 201 and len(calls()) == before, (s, made))

    json.dump({"question": q, "question_text": question, "imported": imported, "hello": h, "unit": unit_ids[0],
               "concept": made["concept"]["id"], "calls": len(calls())}, open(STATE, "w"))
else:
    st = json.load(open(STATE))
    r = record(st["question"])
    check("restart: the saved question, its analysis and extraction are still there",
          r is not None and r["original_input"] == st["question_text"] and r["state"] == "accepted", r)
    s, ext = call("GET", f"/entries/{st['question']}/extractions")
    check("restart: the stored extraction keeps its provenance",
          ext["extractions"][0]["extractor"] == f"openai:{MODEL}:knowledge_extraction_v2", ext)
    s, m = call("GET", f"/knowledge-units/{st['unit']}/concept-membership")
    check("restart: the explicit membership is still current", (m["current_membership"] or {}).get("concept_id") == st["concept"], m)
    check("restart: starting the server made no provider call", len(calls()) == st["calls"], (len(calls()), st["calls"]))
    s, a = call("POST", f"/entries/{st['hello']}/analysis")
    check("restart: a new explicit analysis still uses the configured provider (version 2)",
          s == 201 and a["version"] == 2 and a["analyzer"] == f"openai:{MODEL}:fr_l2_taxonomy_v1.explanation_en_zh_v1" and len(calls()) == st["calls"] + 1, (s, a))

print(json.dumps({"phase": PHASE, "failures": failures, "provider_calls": len(calls())}))
sys.exit(1 if failures else 0)
