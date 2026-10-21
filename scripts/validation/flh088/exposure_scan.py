#!/usr/bin/env python3
"""FLH-088 browser-exposure scan of a running read-only public demo.

Crawls every browser-reachable response (demo identity, every preset's
semantic and hybrid search, keyword search, every listed Concept and unit
source record, / and its assets, error, non-demo and write routes) with the
given Host header, and reports any match of private IPv4 ranges, base_url,
provenance, host paths or tailnet names in headers or bodies. Matches are
printed without the matched address. Read-only: GET/HEAD plus refused writes.

    python3 -I -B scripts/validation/flh088/exposure_scan.py http://127.0.0.1:PORT HOST

Run it against a package started with its deploy/ctl.sh (ALLOWED_HOST=HOST),
for example inside `unshare -rn` with loopback up.
"""
import urllib.parse
import json, re, sys, urllib.request, urllib.error
base, host = sys.argv[1], sys.argv[2]
pat = re.compile(rb'(?<![0-9.])(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})(?![0-9])|base_url|provenance|/home/|/srv/|\.tailscale|ts\.net|:\d{2,5}/v1\b')
seen, hits, n = set(), [], 0
def get(path, method="GET"):
    global n
    req = urllib.request.Request(base + path, method=method, headers={"Host": host})
    try:
        with urllib.request.urlopen(req, timeout=5) as r: code, body, hdr = r.status, r.read(), str(r.headers)
    except urllib.error.HTTPError as e: code, body, hdr = e.code, e.read(), str(e.headers)
    n += 1
    for m in pat.finditer(body + hdr.encode()): hits.append((path, method, m.group(0)[:40].decode("latin-1")))
    return code, body
c, b = get("/knowledge-library/demo"); assert c == 200, c
info = json.loads(b)
for p in info["presets"]:
    get("/knowledge-library/demo/semantic-search?preset=" + p["id"])
    get("/knowledge-library/demo/hybrid-search?preset=" + p["id"])
c, b = get("/knowledge-library/concepts?limit=50")
for q in ["le", "de", "a", "en", "passé", "subjonctif"]:
    get("/knowledge-library/concepts?limit=50&q=" + urllib.parse.quote(q))
ids = set(re.findall(rb'"concept_id":\s*(\d+)', b)) | set(re.findall(rb'"id":\s*(\d+)', b))
units = set()
for i in sorted(ids)[:200]:
    c, cb = get("/knowledge-library/concepts/" + i.decode())
    units |= set(re.findall(rb'"unit_id":\s*(\d+)', cb))
for u in sorted(units)[:400]: get("/knowledge-library/units/%s/source" % u.decode())
c, idx = get("/")
for a in set(re.findall(rb'/assets/[A-Za-z0-9._-]+', idx)): get(a.decode())
for p in ["/RELEASE.json", "/artifact/provenance.json", "/artifact/manifest.json", "/assets/../RELEASE.json",
          "/api/knowledge-library/demo", "/readyz", "/healthz", "/entries", "/concepts", "/nope", "/assets/", "/knowledge-library/concepts/abc",
          "/knowledge-library/demo/semantic-search?q=x", "/knowledge-library/demo/semantic-search?preset=bogus", "/knowledge-library/concepts?limit=9999"]:
    get(p)
for m in ["POST", "PUT", "PATCH", "DELETE"]:
    for p in ["/knowledge-library/demo", "/knowledge-library/concepts", "/entries", "/captures"]: get(p, m)
print(json.dumps({"requests": n, "concepts": len(ids), "units": len(units), "presets": len(info["presets"]), "hit_count": len(hits), "hits": [(p, m, "<address>" if v[:1].isdigit() else v) for p, m, v in hits[:20]]}))
