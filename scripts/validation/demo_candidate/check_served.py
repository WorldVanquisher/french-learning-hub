#!/usr/bin/env python3
"""check_served.py BASE_URL PKG_DIR: is the demo served at BASE_URL this package?

Read-only (GET only, no cookies, no credentials). For a loopback package, a
staging host or the published address behind a proxy, it compares what is
served with the package directory the operator holds:

  page      GET /: the flh-build meta, the entry script and the stylesheet it
            names, and its SHA-256, against RELEASE.json `web`
  assets    the entry script and the stylesheet as served (asked without
            compression, so the bytes are the file), against the package's
            SHA256SUMS: a proxy serving another or a stale copy fails here
  artifact  GET /api/knowledge-library/demo (or /knowledge-library/demo):
            version, manifest SHA-256, real_model and domain fingerprint,
            against RELEASE.json `artifact`; read-only and synthetic
  headers   the page is no-cache and the hashed assets immutable

Use it for the staged smoke, after a deployment, and after a rollback (with
the package rolled back to). Prints one PASS or FAIL line per check and
exits 0 only when all pass, 1 otherwise, 2 on usage. Never prints a response
body. Linux, macOS; Python 3 only.
"""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request


def main():
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 2
    base, pkg = sys.argv[1].rstrip("/"), sys.argv[2]
    try:
        release = json.load(open(os.path.join(pkg, "RELEASE.json"), encoding="utf-8"))
        sums = {}
        for line in open(os.path.join(pkg, "SHA256SUMS"), encoding="utf-8"):
            h, f = line.rstrip("\n").split("  ", 1)
            sums[f] = h
    except (OSError, ValueError) as e:
        print(f"refused: {pkg} is not a public-demo package ({e})", file=sys.stderr)
        return 2

    def get(path):
        req = urllib.request.Request(base + path, headers={"Accept-Encoding": "identity", "User-Agent": "flh-check-served"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
        except urllib.error.HTTPError as e:
            return e.code, b"", {}
        except (urllib.error.URLError, OSError) as e:
            return None, str(e).encode(), {}

    results = []

    def check(name, ok, detail):
        results.append(ok)
        print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail else ""))

    status, html, headers = get("/")
    if status != 200:
        check("page", False, f"GET / answered {status}")
        return 1
    web = release.get("web") or {}
    meta = re.search(rb'<meta name="flh-build" content="([^"]*)"', html)
    entry = re.search(rb'<script\b[^>]*type="module"[^>]*src="(/assets/[^"]+\.js)"', html)
    css = re.search(rb'<link\b[^>]*rel="stylesheet"[^>]*href="(/assets/[^"]+\.css)"', html)
    served = {"build_id": meta.group(1).decode() if meta else None, "entry": entry.group(1).decode() if entry else None,
              "index_sha256": hashlib.sha256(html).hexdigest()}
    if not web:
        check("page", False, "RELEASE.json records no `web` identity (an older package): nothing to compare the page with")
    else:
        bad = [f"{k} served {served[k]} != package {web.get(k)}" for k in ("build_id", "entry", "index_sha256") if served[k] != web.get(k)]
        check("page", not bad, "; ".join(bad) or f"build {served['build_id']}, entry {served['entry']}")
    check("page is no-cache", "no-cache" in headers.get("cache-control", ""), headers.get("cache-control", "no Cache-Control"))

    for label, m in (("entry script", entry), ("stylesheet", css)):
        if not m:
            check(label, False, "the page names none")
            continue
        path = m.group(1).decode()
        st, body, hd = get(path)
        want = sums.get("web" + path)
        got = hashlib.sha256(body).hexdigest() if st == 200 else None
        check(f"{label} {path}", st == 200 and want is not None and got == want,
              f"HTTP {st}" if st != 200 else ("not in this package" if want is None else ("" if got == want else f"served bytes {got[:16]}… != package {want[:16]}…")))
        if st == 200:
            check(f"{label} is immutable", "immutable" in hd.get("cache-control", ""), hd.get("cache-control", "no Cache-Control"))

    info = None
    for path in ("/api/knowledge-library/demo", "/knowledge-library/demo"):
        st, body, _ = get(path)
        if st == 200:
            try:
                info = json.loads(body)
                break
            except ValueError:
                pass
    if info is None:
        check("artifact", False, "no demo description at /api/knowledge-library/demo or /knowledge-library/demo")
    else:
        a, r = info.get("artifact", {}), release.get("artifact", {})
        pairs = {"version": (a.get("version"), r.get("version")), "manifest_sha256": (a.get("manifest_sha256"), r.get("manifest_sha256")),
                 "real_model": (a.get("real_model"), r.get("real_model")), "domain_fingerprint": (a.get("domain_fingerprint_sha256"), r.get("domain_fingerprint"))}
        bad = [f"{k} served {s} != package {p}" for k, (s, p) in pairs.items() if s != p]
        if info.get("read_only") is not True or info.get("data") != "synthetic":
            bad.append("the demo is not read-only synthetic")
        check("artifact", not bad, "; ".join(bad) or f"{a.get('version')} manifest {str(a.get('manifest_sha256'))[:16]}… real_model={a.get('real_model')}")

    ok = all(results)
    print(f"{'SERVED = PACKAGE' if ok else 'SERVED != PACKAGE'}: {release.get('label')} ({sum(results)}/{len(results)} checks)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
