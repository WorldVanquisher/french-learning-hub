"""FLH-093 checks: Concept content and membership, through the public HTTP API.

Usage: python3 -B check.py http://127.0.0.1:PORT DB_PATH STUB_CALL_LOG

Builds an authored, synthetic French-learning fixture on a fresh loopback
backend, records explicit human decisions, then reads back exactly what the
workbench shows (Knowledge Library Concept detail and unit source) and checks
that current support, preferred units, history and sources follow the existing
backend authority. Finally it proves that the inspection reads change no row
and make no provider call. Prints one PASS/FAIL line per check and exits 1 on any
failure. Refuses a non-loopback backend or a database that already has entries.
"""
import json
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE, DB, CALL_LOG = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
if urllib.parse.urlparse(BASE).hostname not in ("127.0.0.1", "localhost", "::1"):
    sys.exit(f"refusing non-loopback backend {BASE}")

failures = 0


def call(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path}: HTTP {e.code}: {e.read(500).decode(errors='replace')}")


def check(name, ok, detail=""):
    global failures
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" :: {detail}"))
    if not ok:
        failures += 1


def snapshot():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        con.close()


def provider_calls():
    with open(CALL_LOG, encoding="utf-8") as f:
        return sum(1 for _ in f)


if call("GET", "/entries?limit=1")["entries"]:
    sys.exit("refusing: the backend already has entries (use a fresh database)")

QUESTIONS = {
    1: ("[flh093:1] Pourquoi dit-on « je ne fume plus » et pas « je ne fume pas » ?\nJe veux dire que j'ai arrêté.",
        "Discussion avec ma tutrice (synthétique, FLH-093)."),
    2: ("[flh093:2] Où se place « plus » dans « je n'ai plus vu Paul » ?", ""),
    3: ("[flh093:3] Est-ce que « j'en veux plus » est correct à l'oral ?", "Entendu dans une série."),
    4: ("[flh093:4] Quelle différence entre « ne … plus » et « ne … jamais » ?", ""),
    5: ("[flh093:5] « Ne … guère » est-il encore utilisé ?", "Lu dans un roman."),
}

entry, unit = {}, {}
for n, (text, ctx) in QUESTIONS.items():
    e = call("POST", "/entries", {"original_input": text, "original_context": ctx})
    entry[n] = e["id"]
    a = call("POST", f"/entries/{e['id']}/analysis")
    call("POST", f"/analyses/{a['id']}/feedback", {"status": "accepted"})
    ext = call("POST", f"/entries/{e['id']}/extractions")
    unit[n] = ext["units"][0]["id"]

identity = lambda target, scope="négation": {"target": target, "pedagogical_intent": "grammar", "scope": scope, "identity_features": {}}

# Concept A "ne … plus": NEW CONCEPT seeded by record 1, then three explicit SAME.
A = call("POST", "/concepts", {"identity": identity("ne … plus"), "seed_unit_id": unit[1], "link_seed_as_same": True})["concept"]["id"]
for n in (2, 3, 4):
    call("POST", f"/knowledge-units/{unit[n]}/concept-links/same", {"concept_id": A})
detail = call("GET", f"/knowledge-library/concepts/{A}")
check("multiple units join one Concept: four current supporting units",
      sorted(u["unit_id"] for u in detail["supporting_units"]) == sorted(unit[n] for n in (1, 2, 3, 4)), detail["supporting_units"])
check("joining keeps each unit's own original record",
      all(call("GET", f"/knowledge-library/units/{unit[n]}/source")["entry"]["original_input"] == QUESTIONS[n][0] for n in (1, 2, 3, 4)))
check("no preferred unit until a person chooses one", detail["preferred_unit"] is None)
call("POST", f"/concepts/{A}/preferred-unit", {"unit_id": unit[1]})

# Concept B "ne … jamais": created without a seed, then record 4's unit is moved
# there by an explicit reassignment (it was wrongly filed under A).
B = call("POST", "/concepts", {"identity": identity("ne … jamais")})["concept"]["id"]
call("PUT", f"/knowledge-units/{unit[4]}/concept-membership", {"concept_id": B})

# Record 3's unit is judged INVALID; record 2 is extracted again (its earlier
# unit stays a member of A but is no longer from the current extraction).
call("POST", f"/knowledge-units/{unit[3]}/invalid", {})
ext2 = call("POST", f"/entries/{entry[2]}/extractions")
unit2_new = ext2["units"][0]["id"]

# Concept C "ne … guère": NEW CONCEPT, then its only unit is judged INVALID.
C = call("POST", "/concepts", {"identity": identity("ne … guère", "registre soutenu"), "seed_unit_id": unit[5], "link_seed_as_same": True})["concept"]["id"]
call("POST", f"/knowledge-units/{unit[5]}/invalid", {})

# ---- Inspection: exactly the reads the workbench makes. Nothing may change. ----
before_rows, before_calls = snapshot(), provider_calls()
a = call("GET", f"/knowledge-library/concepts/{A}")
b = call("GET", f"/knowledge-library/concepts/{B}")
c = call("GET", f"/knowledge-library/concepts/{C}")
sources = {n: call("GET", f"/knowledge-library/units/{unit[n]}/source") for n in QUESTIONS}
new_source = call("GET", f"/knowledge-library/units/{unit2_new}/source")
call("GET", "/concepts")
call("GET", "/reviewable-units?limit=50")
call("GET", f"/knowledge-units/{unit2_new}/concept-resolution")
call("GET", f"/knowledge-units/{unit2_new}/concept-membership")
after_rows, after_calls = snapshot(), provider_calls()

ids = lambda units: sorted(u["unit_id"] for u in units)
hist = {h["unit"]["unit_id"]: h for h in a["historical_units"]}
check("A: only the current, admitted, filed unit is current support", ids(a["supporting_units"]) == [unit[1]], ids(a["supporting_units"]))
check("A: the preferred representative is the chosen unit", (a["preferred_unit"] or {}).get("unit_id") == unit[1], a["preferred_unit"])
check("A: a member from a non-current extraction is filed but not support",
      ids(a["non_supporting_members"]) == [unit[2]] and a["non_supporting_members"][0]["in_current_extraction"] is False, a["non_supporting_members"])
check("A: the INVALID unit is history only", hist.get(unit[3], {}).get("effective_status") == "invalid", a["historical_units"])
check("A: the reassigned unit is history only and names its current Concept", hist.get(unit[4], {}).get("current_concept_id") == B, a["historical_units"])
check("A: no historical, INVALID or reassigned unit appears as support",
      not ({unit[2], unit[3], unit[4]} & set(ids(a["supporting_units"]))))
check("B: the reassigned unit is B's current support", ids(b["supporting_units"]) == [unit[4]] and b["concept"]["state"] == "active", b)
check("C: a Concept without current support is orphaned, not deleted",
      c["supporting_units"] == [] and c["concept"]["state"] == "orphaned" and c["concept"]["target"] == "ne … guère", c["concept"])
check("every unit keeps its original question and context after SAME, reassignment and INVALID",
      all(sources[n]["entry"]["original_input"] == QUESTIONS[n][0] and sources[n]["entry"]["original_context"] == QUESTIONS[n][1] for n in QUESTIONS))
check("the line break in the original question is preserved", "\n" in sources[1]["entry"]["original_input"])
check("source of the old record-2 unit is labelled non-current; the new one current",
      sources[2]["unit"]["in_current_extraction"] is False and new_source["unit"]["in_current_extraction"] is True)
check("no unit text was merged or rewritten",
      sources[1]["unit"]["statement"] == "« Ne … plus » indicates that a habitual action has stopped."
      and sources[2]["unit"]["statement"].startswith("In compound tenses"))
check("each unit keeps its own Chinese statement (FLH-095)",
      sources[1]["unit"]["statements"]["zh"] == "« Ne … plus » 表示一个习惯性的动作已经停止。"
      and sources[2]["unit"]["statements"]["en"] == sources[2]["unit"]["statement"])
check("inspection reads changed no database row", before_rows == after_rows,
      {k: (before_rows[k], after_rows.get(k)) for k in before_rows if before_rows[k] != after_rows.get(k)})
check("inspection reads made no provider call", before_calls == after_calls, (before_calls, after_calls))

print(json.dumps({"concepts": {"A": A, "B": B, "C": C}, "units": unit, "unit2_current": unit2_new,
                  "provider_calls": after_calls, "failures": failures}, ensure_ascii=False))
sys.exit(1 if failures else 0)
