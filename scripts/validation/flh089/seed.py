"""Seed the FLH-089 daily-workflow fixture through the public HTTP API only.

Usage: python3 -B seed.py http://127.0.0.1:PORT [--records 1000] [--concepts 500]

Refuses a non-loopback backend and any backend that already holds entries or
concepts, so it only fills a fresh, disposable database. Every write goes
through the normal endpoints, so all domain invariants apply. The analyzer is
the local rule-based one; extraction uses stub_extractor.py. All content is
synthetic. The counts are test targets, not learning evidence.

Deterministic plan for record n (1-based):
- n % 10 == 0          unanalyzed (no analysis);
- otherwise analyzed. Feedback by n % 20: 1-3 rejected, 4-8 accepted,
  9-11 corrected, else unreviewed;
- n % 12 == 5          re-analyzed later (analysis history; the latest is unreviewed);
- eligible records (not unanalyzed, not rejected) are extracted once (3 units);
  n % 3 == 0 among them are extracted a second time (extraction history);
- Concepts: the first unit of the current extraction of the first --concepts
  eligible records seeds a NEW CONCEPT (SAME); the second unit of every 4th
  eligible record is linked SAME to an existing Concept; every 40th third unit is
  marked INVALID. Everything else stays reviewable.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("base")
ap.add_argument("--records", type=int, default=1000)
ap.add_argument("--concepts", type=int, default=500)
args = ap.parse_args()
BASE = args.base.rstrip("/")
if urllib.parse.urlparse(BASE).hostname not in ("127.0.0.1", "localhost", "::1"):
    sys.exit(f"refusing non-loopback backend {BASE}")

stats = {"requests": 0}


def call(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    stats["requests"] += 1
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path}: HTTP {e.code}: {e.read(500).decode(errors='replace')}")


if call("GET", "/entries?limit=1")["entries"] or call("GET", "/concepts")["concepts"]:
    sys.exit("refusing to seed: this backend already has entries or concepts (use a fresh database)")

CATS = ["grammar", "vocabulary", "morphology", "orthography", "pragmatics", "translation"]
LONG = ("Je voulais vérifier une phrase que j'ai écrite dans mon journal. " * 40).strip()
start = time.time()
entries = []
counts = {"unanalyzed": 0, "rejected": 0, "accepted": 0, "corrected": 0, "unreviewed": 0,
          "reanalyzed": 0, "extractions": 0, "units": 0, "concepts": 0, "same_links": 0, "invalid": 0}
for n in range(1, args.records + 1):
    text = f"[fx:{n}] Synthetic question {n}: est-ce que « exemple {n % 97} » est correct ici ?"
    if n % 50 == 7:
        text += " " + LONG  # long learner text (~2.6k characters)
    ctx = f"Synthetic context {n} (fixture FLH-089)." if n % 4 else ""
    e = call("POST", "/entries", {"original_input": text, "original_context": ctx})
    entries.append((n, e["id"]))

eligible = []
for n, eid in entries:
    if n % 10 == 0:
        counts["unanalyzed"] += 1
        continue
    a = call("POST", f"/entries/{eid}/analysis")
    r = n % 20
    if 1 <= r <= 3:
        call("POST", f"/analyses/{a['id']}/feedback", {"status": "rejected"})
        counts["rejected"] += 1
        continue
    if 4 <= r <= 8:
        call("POST", f"/analyses/{a['id']}/feedback", {"status": "accepted"})
        counts["accepted"] += 1
    elif 9 <= r <= 11:
        call("POST", f"/analyses/{a['id']}/feedback",
             {"status": "corrected", "corrected_category": CATS[n % len(CATS)],
              "corrected_explanation": f"Synthetic correction for record {n}."})
        counts["corrected"] += 1
    else:
        counts["unreviewed"] += 1
    if n % 12 == 5:
        call("POST", f"/entries/{eid}/analysis")  # analysis history; latest unreviewed
        counts["reanalyzed"] += 1
    eligible.append((n, eid))

current_units = {}
for n, eid in eligible:
    ext = call("POST", f"/entries/{eid}/extractions")
    counts["extractions"] += 1
    counts["units"] += len(ext["units"])
    if n % 3 == 0:
        ext = call("POST", f"/entries/{eid}/extractions")  # extraction history; latest is current
        counts["extractions"] += 1
        counts["units"] += len(ext["units"])
    current_units[eid] = [u["id"] for u in ext["units"]]

concept_ids = []
for i, (n, eid) in enumerate(eligible):
    units = current_units[eid]
    if i < args.concepts:
        identity = {"target": f"synthetic concept {i:04d}", "pedagogical_intent": ["grammar", "vocabulary", "usage"][i % 3],
                    "scope": "" if i % 5 else "overview", "identity_features": {"fixture": "flh089", "group": f"g{i % 25:02d}"}}
        c = call("POST", "/concepts", {"identity": identity, "seed_unit_id": units[0], "link_seed_as_same": True})
        concept_ids.append(c["concept"]["id"])
        counts["concepts"] += 1
    if i % 4 == 0 and concept_ids:
        call("POST", f"/knowledge-units/{units[1]}/concept-links/same", {"concept_id": concept_ids[(i * 7) % len(concept_ids)]})
        counts["same_links"] += 1
    if i % 40 == 0:
        call("POST", f"/knowledge-units/{units[2]}/invalid", {})
        counts["invalid"] += 1

counts["records"] = len(entries)
counts["requests"] = stats["requests"]
counts["seconds"] = round(time.time() - start, 1)
counts["first_entry_id"], counts["last_entry_id"] = entries[0][1], entries[-1][1]
print(json.dumps(counts))
