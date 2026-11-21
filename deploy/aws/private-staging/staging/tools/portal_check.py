#!/usr/bin/env python3
"""Offline check and simulation of the proposed portal routing (no DNS lookup, no network).

  portal_check.py validate [PLAN.json]                 structure, separation and the pre-launch rules
  portal_check.py simulate [PLAN.json] [--json]        run the synthetic requests below through the plan

The public-demo boundary is mirrored from internal/transport/http/public_demo.go (NewPublicDemoBoundary):
GET/HEAD only (405 otherwise), canonical paths only, the API allowlist at the root or under /api, and / and
/assets/... for the web build. A test reads that Go file and fails if the two drift apart.
Exit codes: 0 every check or expectation holds, 1 a finding, 2 unreadable plan.
"""
import argparse
import json
import os
import posixpath
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PLAN = os.path.join(HERE, "..", "portal", "routing_plan.json")
DEMO_API = [r"^/healthz$", r"^/readyz$", r"^/knowledge-library/concepts$", r"^/knowledge-library/concepts/[0-9]{1,18}$",
            r"^/knowledge-library/units/[0-9]{1,18}/source$", r"^/knowledge-library/demo$",
            r"^/knowledge-library/demo/semantic-search$", r"^/knowledge-library/demo/hybrid-search$"]
# Synthetic requests: (host, method, path, expected outcome). Private workbench routes appear on every host.
REQUESTS = [
    ("flh.vanquisher.world", "GET", "/", 200),
    ("flh.vanquisher.world", "HEAD", "/assets/portal.css", 200),
    ("flh.vanquisher.world", "GET", "/knowledge-library/concepts", 404),
    ("flh.vanquisher.world", "POST", "/captures", 404),
    ("flh.vanquisher.world", "GET", "/api/entries", 404),
    ("demo.flh.vanquisher.world", "GET", "/", 200),
    ("demo.flh.vanquisher.world", "GET", "/readyz", 200),
    ("demo.flh.vanquisher.world", "GET", "/api/knowledge-library/concepts/42", 200),
    ("demo.flh.vanquisher.world", "GET", "/knowledge-library/units/7/source", 200),
    ("demo.flh.vanquisher.world", "GET", "/knowledge-library/demo/semantic-search", 200),
    ("demo.flh.vanquisher.world", "POST", "/captures", 405),
    ("demo.flh.vanquisher.world", "PUT", "/knowledge-units/1/concept-membership", 405),
    ("demo.flh.vanquisher.world", "GET", "/entries", 404),
    ("demo.flh.vanquisher.world", "GET", "/api/entries", 404),
    ("demo.flh.vanquisher.world", "GET", "/listening/materials", 404),
    ("demo.flh.vanquisher.world", "GET", "/annotation-dataset/v1", 404),
    ("demo.flh.vanquisher.world", "GET", "/knowledge-library/../entries", 404),
    ("demo.flh.vanquisher.world", "GET", "/assets/", 404),
    ("app.flh.vanquisher.world", "GET", "/", "no-record"),
    ("app.flh.vanquisher.world", "POST", "/captures", "no-record"),
    ("staging.flh.vanquisher.world", "GET", "/", "refused"),
    ("203.0.113.10", "GET", "/entries", "refused"),
]


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        print(f"portal_check: unreadable {path}: {e}", file=sys.stderr)
        raise SystemExit(2)


def demo_boundary(method, p):
    if method not in ("GET", "HEAD"):
        return 405
    if p == "" or posixpath.normpath(p) != p or "%" in p:
        return 404
    if p == "/" or (p.startswith("/assets/") and len(p) > len("/assets/")):
        return 200
    api = p[len("/api"):] if p.startswith("/api/") else p
    return 200 if any(re.match(rx, api) for rx in DEMO_API) else 404


def route(plan, host, method, path):
    h = plan["hosts"].get(host)
    if h is None:
        return plan["unknown_host"]["outcome"]
    if plan["state"] == "pre-launch" and h.get("prelaunch_outcome"):
        return h["prelaunch_outcome"]
    if h.get("boundary") == "public-demo":
        return demo_boundary(method, path)
    for rule in h.get("rules", []):
        if method in rule["methods"] and any(path == q or (q.endswith("/*") and path.startswith(q[:-1]) and len(path) > len(q) - 1)
                                             for q in rule["paths"]):
            return rule["outcome"]
    return h.get("otherwise", 404)


def validate(plan):
    problems = []
    if plan.get("format") != "flh-portal-routing-plan/v1":
        problems.append("format must be flh-portal-routing-plan/v1")
    hosts = plan.get("hosts", {})
    roles = {v.get("role"): k for k, v in hosts.items()}
    for need in ("portal", "public-demo", "private-pilot"):
        if need not in roles:
            problems.append(f"no host has role {need}")
    if roles.get("portal") == roles.get("public-demo"):
        problems.append("the portal and the public demo must be different host names")
    portal = hosts.get(roles.get("portal"), {})
    if "proxy" in portal.get("target", "").lower() and "never" not in portal.get("target", "").lower():
        problems.append("the portal must not proxy to an FLH server")
    if any(m not in ("GET", "HEAD") for r in portal.get("rules", []) for m in r["methods"]):
        problems.append("the portal serves GET/HEAD only")
    pilot = hosts.get(roles.get("private-pilot"), {})
    if plan.get("state") == "pre-launch" and (pilot.get("dns") is not None or pilot.get("prelaunch_outcome") != "no-record"):
        problems.append("pre-launch: the pilot host must have no DNS record")
    if not pilot.get("open_requires"):
        problems.append("the pilot host must list its opening conditions")
    for c in plan.get("changes", []):
        for k in ("id", "what", "owner", "verify", "rollback"):
            if not c.get(k):
                problems.append(f"change {c.get('id', '?')} lacks {k}")
    if "staging" not in plan or "no host name" not in plan["staging"]:
        problems.append("staging must have no host name")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "simulate"):
        s = sub.add_parser(name); s.add_argument("plan", nargs="?", default=DEFAULT_PLAN); s.add_argument("--json", action="store_true")
    a = ap.parse_args()
    plan = load(a.plan)
    if a.cmd == "validate":
        problems = validate(plan)
        for p in problems:
            print(f"FINDING  {p}")
        print("VALID: portal, demo and pilot are separate; pre-launch pilot has no record; every change has a rollback"
              if not problems else f"INVALID: {len(problems)} finding(s)")
        return 1 if problems else 0
    rows = [{"host": h, "method": m, "path": p, "expected": e, "got": route(plan, h, m, p)} for h, m, p, e in REQUESTS]
    bad = [r for r in rows if r["got"] != r["expected"]]
    if a.json:
        print(json.dumps({"requests": rows, "mismatches": len(bad)}, indent=1))
    else:
        for r in rows:
            print(f"{'ok ' if r['got'] == r['expected'] else 'BAD'} {r['host']:30} {r['method']:5} {r['path']:45} -> {r['got']}")
        print(f"SIMULATION: {len(rows) - len(bad)} of {len(rows)} synthetic requests as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
