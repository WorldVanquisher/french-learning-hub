"""v1.0 release rehearsal: record the user-visible state of a running server.

Usage: python3 -I -B snapshot.py BASE_URL OUT_JSON

GET requests only. Records, per learning record: the original question and
context exactly as stored, analysis and feedback IDs/versions, extraction
IDs/versions with their unit IDs, the current-extraction selection, each unit's
CURRENT SAME membership and Knowledge Library source link; per Concept: its
identity, signature and supporting units with their records; and the stored
suggestion runs with each item's confirmation. Two snapshots taken before and
after an upgrade or a recovery must be identical.
"""
import json
import sys
import urllib.parse
import urllib.request

BASE, OUT = sys.argv[1].rstrip("/"), sys.argv[2]
if urllib.parse.urlparse(BASE).hostname not in ("127.0.0.1", "localhost", "::1"):
    sys.exit(f"refusing non-loopback backend {BASE}")


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


entries = sorted(get("/entries?limit=100")["entries"], key=lambda e: e["id"])
snap = {"entries": [], "concepts": [], "suggestion_runs": []}
unit_ids = []
for e in entries:
    eid = e["id"]
    analyses = get(f"/entries/{eid}/analyses")["analyses"]
    extractions = get(f"/entries/{eid}/extractions")["extractions"]
    rec = {
        "id": eid, "original_input": e["original_input"], "original_context": e["original_context"], "created_at": e["created_at"],
        "analyses": [{"id": a["id"], "version": a["version"], "analyzer": a["analyzer"],
                      "feedback": [f["id"] for f in get(f"/analyses/{a['id']}/feedback")["feedback"]]} for a in analyses],
        "extractions": [{"id": x["id"], "version": x["version"], "units": [u["id"] for u in x["units"]]} for x in extractions],
        "current_extraction": get(f"/entries/{eid}/current-extraction"),
        "units": {},
    }
    for x in extractions:
        for u in x["units"]:
            m = get(f"/knowledge-units/{u['id']}/concept-membership")["current_membership"]
            src = get(f"/knowledge-library/units/{u['id']}/source")
            rec["units"][str(u["id"])] = {
                "canonical": u["canonical"],
                "membership": None if m is None else {"concept_id": m["concept_id"], "link_id": m["link_id"]},
                "source_entry_id": src["entry"]["id"],
                "source_original_input": src["entry"]["original_input"],
            }
            unit_ids.append(u["id"])
    snap["entries"].append(rec)
for c in sorted(get("/concepts")["concepts"], key=lambda c: c["id"]):
    lib = get(f"/knowledge-library/concepts/{c['id']}")
    snap["concepts"].append({
        "id": c["id"], "target": c["target"], "signature": c["signature"], "lifecycle_state": c["lifecycle_state"],
        "state": c["state"],
        "supporting_units": sorted([[u["unit_id"], u["entry_id"]] for u in lib["supporting_units"]]),
    })
for r in sorted(get("/concept-suggestion-runs")["runs"], key=lambda r: r["id"]):
    full = get(f"/concept-suggestion-runs/{r['id']}")
    snap["suggestion_runs"].append({
        "id": r["id"], "status": r["status"], "unit_ids": r["unit_ids"],
        "items": [{"id": i["id"], "unit_id": i["unit_id"], "suggested_concept_id": i["suggested_concept_id"], "state": i["state"],
                   "confirmation_link": None if i["confirmation"] is None else i["confirmation"]["link_id"]}
                  for i in full.get("items", [])],
    })
snap["summary"] = {"entries": len(entries), "units": len(unit_ids), "concepts": len(snap["concepts"]),
                   "memberships": sum(1 for e in snap["entries"] for u in e["units"].values() if u["membership"]),
                   "suggestion_runs": len(snap["suggestion_runs"])}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(snap, f, ensure_ascii=False, indent=1, sort_keys=True)
print(json.dumps(snap["summary"]))
