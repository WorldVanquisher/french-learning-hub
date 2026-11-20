#!/usr/bin/env python3
"""Offline audit of a tree's pins and lock metadata (reads files only; no network, no Git, no Docker).

  pin_audit.py TREE [--json]

  workflows       every `uses:` in .github/workflows/*.yml: pinned to a commit SHA, a tag, or a branch
  dockerfile      every FROM in Dockerfile and tools/**/Dockerfile: pinned by @sha256 digest or not
  go              go.mod's go/toolchain lines; go.sum present and non-empty
  npm             web/package-lock.json: lockfileVersion; packages without `integrity` or `resolved`
  python-locks    *.lock / requirements*.txt under tools/: requirement lines without --hash
  terraform       every .terraform.lock.hcl: providers, versions and hash counts
Rules that fail (exit 1): an unpinned FROM, an npm package without integrity, a Python lock line
without a hash, a Terraform lock provider without hashes, a missing go.sum. Workflow actions pinned
to a tag rather than a SHA are reported as a warning (a policy choice for the owner).
"""
import glob
import json
import os
import re
import sys


def rd(p):
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def audit(tree):
    out = {"workflows": [], "dockerfile": [], "go": {}, "npm": {}, "python_locks": [], "terraform": [], "fail": [], "warn": []}
    for wf in sorted(glob.glob(os.path.join(tree, ".github", "workflows", "*.y*ml"))):
        for m in re.finditer(r"^\s*-?\s*uses:\s*([^\s#]+)", rd(wf), re.M):
            ref = m.group(1)
            name, _, ver = ref.partition("@")
            kind = "sha" if re.fullmatch(r"[0-9a-f]{40}", ver) else "tag" if re.fullmatch(r"v?\d+(\.\d+)*", ver) else "branch-or-other"
            out["workflows"].append({"file": os.path.relpath(wf, tree), "action": name, "ref": ver, "pin": kind})
    tags = sorted({f"{w['action']}@{w['ref']}" for w in out["workflows"] if w["pin"] != "sha"})
    if tags:
        out["warn"].append(f"{len(tags)} workflow action reference(s) pinned to a tag or branch, not a commit SHA: {', '.join(tags)}")
    for df in [os.path.join(tree, "Dockerfile")] + sorted(glob.glob(os.path.join(tree, "tools", "**", "Dockerfile"), recursive=True)):
        if not os.path.isfile(df):
            continue
        stages = set()
        for m in re.finditer(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", rd(df), re.M | re.I):
            img = m.group(1)
            pinned = "@sha256:" in img or img.lower() == "scratch" or img in stages
            if m.group(2):
                stages.add(m.group(2))
            out["dockerfile"].append({"file": os.path.relpath(df, tree), "from": img.split("@")[0], "digest_pinned": pinned})
            if not pinned:
                out["fail"].append(f"{os.path.relpath(df, tree)}: FROM {img.split('@')[0]} is not pinned by digest")
    gm, gs = os.path.join(tree, "go.mod"), os.path.join(tree, "go.sum")
    if os.path.isfile(gm):
        t = rd(gm)
        out["go"] = {"go": (re.search(r"^go\s+(\S+)", t, re.M) or [None, None])[1],
                     "toolchain": (re.search(r"^toolchain\s+(\S+)", t, re.M) or [None, None])[1],
                     "go_sum_lines": len(rd(gs).splitlines()) if os.path.isfile(gs) else 0}
        if not out["go"]["go_sum_lines"]:
            out["fail"].append("go.sum missing or empty")
    pl = os.path.join(tree, "web", "package-lock.json")
    if os.path.isfile(pl):
        lock = json.loads(rd(pl))
        pk = {k: v for k, v in (lock.get("packages") or {}).items() if k}
        noint = sorted(k for k, v in pk.items() if not v.get("link") and not v.get("integrity"))
        nores = sorted(k for k, v in pk.items() if not v.get("link") and not v.get("resolved"))
        out["npm"] = {"lockfileVersion": lock.get("lockfileVersion"), "packages": len(pk), "without_integrity": noint,
                      "without_resolved": nores}
        if noint:
            out["fail"].append(f"web/package-lock.json: {len(noint)} package(s) without integrity: {noint[:5]}")
    for lk in sorted(glob.glob(os.path.join(tree, "tools", "**", "*.lock"), recursive=True)
                     + glob.glob(os.path.join(tree, "tools", "**", "requirements*.txt"), recursive=True)):
        text = rd(lk).replace("\\\n", " ")
        reqs = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith(("#", "-"))]
        nohash = [l.split()[0] for l in reqs if "--hash=" not in l]
        out["python_locks"].append({"file": os.path.relpath(lk, tree), "requirements": len(reqs), "without_hash": nohash})
        if nohash and lk.endswith(".lock"):
            out["fail"].append(f"{os.path.relpath(lk, tree)}: {len(nohash)} requirement(s) without --hash")
    for tl in sorted(glob.glob(os.path.join(tree, "**", ".terraform.lock.hcl"), recursive=True)):
        for m in re.finditer(r'provider\s+"([^"]+)"\s*\{(.*?)\n\}', rd(tl), re.S):
            body = m.group(2)
            ver = (re.search(r'version\s*=\s*"([^"]+)"', body) or [None, None])[1]
            hashes = len(re.findall(r'"(?:h1|zh):[^"]+"', body))
            out["terraform"].append({"file": os.path.relpath(tl, tree), "provider": m.group(1), "version": ver, "hashes": hashes})
            if not hashes:
                out["fail"].append(f"{os.path.relpath(tl, tree)}: provider {m.group(1)} has no hashes")
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    r = audit(sys.argv[1])
    if "--json" in sys.argv:
        print(json.dumps(r, indent=1, sort_keys=True))
    else:
        kinds = {}
        for w in r["workflows"]:
            kinds[w["pin"]] = kinds.get(w["pin"], 0) + 1
        print(f"workflows: {len(r['workflows'])} action reference(s): {kinds}")
        for d in r["dockerfile"]:
            print(f"dockerfile: {d['file']}: FROM {d['from']}: {'digest-pinned' if d['digest_pinned'] else 'NOT pinned'}")
        print(f"go: {r['go']}")
        n = r["npm"]
        if n:
            print(f"npm: lockfileVersion {n['lockfileVersion']}, {n['packages']} packages, {len(n['without_integrity'])} without integrity, "
                  f"{len(n['without_resolved'])} without resolved")
        for p in r["python_locks"]:
            print(f"python: {p['file']}: {p['requirements']} requirement(s), {len(p['without_hash'])} without --hash")
        for t in r["terraform"]:
            print(f"terraform: {t['file']}: {t['provider']} {t['version']}, {t['hashes']} hash(es)")
        for w in r["warn"]:
            print(f"WARN {w}")
        for f in r["fail"]:
            print(f"FAIL {f}")
        print("PIN AUDIT " + ("FAILED" if r["fail"] else "PASSED") + f" ({len(r['warn'])} warning(s))")
    return 1 if r["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
