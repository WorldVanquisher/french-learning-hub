# Synthetic FLH-030 fixtures through the public API only.
import json, sys, urllib.request
BASE = sys.argv[1]
def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)
for i in range(1, 5):
    call("POST", "/entries", {"original_input": f"FLH-030 synthetic question {i}", "original_context": f"Contexte synthétique {i}"})
    call("POST", f"/entries/{i}/analysis")
    call("POST", f"/entries/{i}/extractions")
for name in ("alpha", "beta", "gamma"):
    identity = {"target": f"concept {name}", "pedagogical_intent": "synthetic", "scope": "flh030", "identity_features": {}}
    c = call("POST", "/concepts", {"identity": identity, "seed_unit_id": None, "link_seed_as_same": False})
    print("concept", c["concept"]["id"], c["concept"]["target"])
print("reviewable", [u["unit_id"] for u in call("GET", "/reviewable-units")["reviewable_units"]])
