"""Seed the FLH-034 Knowledge Library demo through the public HTTP API only.

Usage: python3 -B seed.py http://127.0.0.1:18934

Refuses a non-loopback backend and any backend that already holds entries or
concepts, so it can only fill a fresh, isolated demo database. Every write goes
through the normal endpoints, so all domain invariants apply. All content is
synthetic. Concept titles, explanations and the learner's questions are in
English; French examples and grammar terms are kept.
"""
import json
import sys
import urllib.parse
import urllib.request

BASE = sys.argv[1].rstrip("/")
host = urllib.parse.urlparse(BASE).hostname
if host not in ("127.0.0.1", "localhost", "::1"):
    sys.exit(f"refusing non-loopback backend {BASE}")


def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        text = r.read()
        return json.loads(text) if text else None


if call("GET", "/entries?limit=1")["entries"] or call("GET", "/concepts")["concepts"]:
    sys.exit("refusing to seed: this backend already has entries or concepts (use a fresh demo database)")

ids = {}


def record(key, text, context):
    entry = call("POST", "/entries", {"original_input": text, "original_context": context})
    ids[key] = entry["id"]
    call("POST", f"/entries/{entry['id']}/analysis")  # local rule-based analyzer
    return entry["id"]


def extract(entry_id):
    return [u["id"] for u in call("POST", f"/entries/{entry_id}/extractions")["units"]]


def concept(target, intent, features=None, seed=None, scope=""):
    identity = {"target": target, "pedagogical_intent": intent, "scope": scope, "identity_features": features or {}}
    c = call("POST", "/concepts", {"identity": identity, "seed_unit_id": seed, "link_seed_as_same": seed is not None})
    return c["concept"]["id"]


same = lambda unit, cid: call("POST", f"/knowledge-units/{unit}/concept-links/same", {"concept_id": cid})
relation = lambda unit, cid, rel: call("POST", f"/knowledge-units/{unit}/concept-links/relation", {"concept_id": cid, "relation": rel})

# Four synthetic learning records.
e1 = record("faut", "Why do we say « il faut que je fasse » and not « il faut que je fais »?", "Tuesday class, exercise on expressing necessity.")
e2 = record("bien", "Bien que + subjunctive or indicative? I wrote « bien qu'il pleut ».", "Essay corrected by my teacher.")
e3 = record("aller", "I wrote « je suis allé au cinéma hier ». Is that correct?", "Personal journal.")
e4 = record("miss", "How do I say « I miss you » in French?", "Message to a friend.")

# A human correction on record 2's analysis, in force when it is extracted.
a2 = call("GET", f"/entries/{e2}/analyses")["analyses"][0]
call("POST", f"/analyses/{a2['id']}/feedback", {"status": "corrected", "corrected_explanation": "Concession: « bien que » (although) always takes the subjunctive, so « bien qu'il pleuve », not « bien qu'il pleut »."})

u_faut1, u_faire1 = extract(e1)
u_bien, u_malgre = extract(e2)
u_aller, u_accord = extract(e3)
u_manques, u_manquer = extract(e4)

# English titles, stored lower-case because concept identity is normalized.
# French terms stay in the identity (mood, trigger, scope), so "subjonctif",
# "déclencheur" and "vue d'ensemble" still find the same Concepts, and the
# titles sort as the earlier French ones did (browse and tie order unchanged).
subj = {"mood": "subjunctive (subjonctif)"}
c_faut = concept("subjunctive after « il faut que »", "grammar", {**subj, "trigger (déclencheur)": "il faut que (it is necessary that)"}, seed=u_faut1)
c_faire = concept("subjunctive forms of faire", "morphology", {**subj, "verb": "faire (to do)"}, seed=u_faire1)
c_bien = concept("subjunctive after « bien que »", "grammar", {**subj, "trigger (déclencheur)": "bien que (although)"}, seed=u_bien)
c_mode = concept("overview of the subjunctive mood", "grammar", subj, scope="overview (vue d'ensemble)")
c_pc = concept("passé composé with être", "grammar", {"auxiliary": "être (to be)"}, seed=u_aller)
c_accord = concept("agreement of the past participle with être", "orthography", {"auxiliary": "être (to be)"})
c_manque = concept("tu me manques: saying you miss someone", "expression", seed=u_manques)
call("POST", f"/concepts/{c_bien}/preferred-unit", {"unit_id": u_bien})

# Record 2's "malgré" note is a member, but suppressed by the learner (mastered).
same(u_malgre, c_bien)
call("POST", f"/knowledge-units/{u_malgre}/admission-overrides", {"decision": "suppressed", "reason": "mastered", "note": "already mastered"})
# Relations are not membership and give no support.
relation(u_bien, c_faut, "related")
# Record 3: the agreement unit was first linked to the wrong concept, then corrected.
same(u_accord, c_pc)
call("PUT", f"/knowledge-units/{u_accord}/concept-membership", {"concept_id": c_accord})
# Record 4: "manquer = to miss" was linked, then judged an invalid unit.
same(u_manquer, c_manque)
call("POST", f"/knowledge-units/{u_manquer}/invalid", {})

# Record 1 is re-analyzed and re-extracted: v1 units become historical evidence.
call("POST", f"/entries/{e1}/analysis")
u_faut2, _u_faire2 = extract(e1)
same(u_faut2, c_faut)
call("POST", f"/concepts/{c_faut}/preferred-unit", {"unit_id": u_faut2})
relation(u_faut2, c_mode, "narrower")
# "subjonctif de faire" is not re-linked: it becomes orphaned but stays inspectable.

print(json.dumps({"entries": [e1, e2, e3, e4], "concepts": {
    "il faut que": c_faut, "faire": c_faire, "bien que": c_bien, "mode subjonctif": c_mode,
    "passé composé": c_pc, "accord": c_accord, "tu me manques": c_manque}}, ensure_ascii=False))
