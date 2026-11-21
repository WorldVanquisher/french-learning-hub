#!/usr/bin/env python3
"""Invite-only pilot acceptance: validate the isolation case and probe a LOCAL server for anonymous access.

  pilot_check.py validate [CASE.json]
  pilot_check.py probe URL [--routes-from GO_DIR] [--json]
        GET every private GET route anonymously (path parameters replaced by 1). READY only if all answer 401.
        URL must be loopback (127.0.0.1, ::1 or localhost): live hosts are probed by the owner, never here.
        Only GET is sent, so a server without authentication is never written to.
  pilot_check.py run URL --case CASE.json
        BLOCKED until the server has accounts, sessions and invitations (the pilot API does not exist).

Exit codes: 0 valid / ready, 1 finding / not ready / blocked, 2 usage or unreadable.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CASE = os.path.join(HERE, "..", "pilot", "isolation_case_v1.json")
DEFAULT_GO = os.path.realpath(os.path.join(HERE, "..", "..", "..", "..", "..", "internal", "transport", "http"))
PUBLIC = {"/healthz", "/readyz"}
NEEDED_KINDS = {"enroll", "invite-reuse", "invite-expiry", "write", "read", "cross-read", "cross-write", "export", "anonymous",
                "revoke", "backup", "restore-isolation", "restore-revocation"}
EXPORTS = {"/learning-history/export", "/learning-records/export", "/speaking/export", "/annotation-dataset/v1/export"}


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        print(f"pilot_check: unreadable {path}: {e}", file=sys.stderr)
        raise SystemExit(2)


def validate(case):
    problems = []
    if case.get("format") != "flh-pilot-isolation-case/v1":
        problems.append("format must be flh-pilot-isolation-case/v1")
    if sorted(case.get("accounts", {})) != ["A", "B"]:
        problems.append("exactly two synthetic accounts, A and B")
    steps = case.get("steps", [])
    kinds = {s.get("kind") for s in steps}
    for k in sorted(NEEDED_KINDS - kinds):
        problems.append(f"no step of kind {k}")
    for s in steps:
        for f in ("id", "kind", "actor", "request", "expect"):
            if not s.get(f):
                problems.append(f"step {s.get('id', '?')} lacks {f}")
    covered = {e for e in EXPORTS if any(e in s.get("request", "") for s in steps if s.get("kind") == "export")}
    for e in sorted(EXPORTS - covered):
        problems.append(f"export {e} is not covered")
    for s in steps:
        if s.get("kind") in ("cross-read", "cross-write") and "404" not in s.get("expect", ""):
            problems.append(f"{s['id']}: a cross-account request must answer 404 (no existence leak)")
    if re.search(r"@[A-Za-z0-9-]+\.|\b\d{12}\b", json.dumps(case)):
        problems.append("the case contains an e-mail address or a 12-digit number: synthetic labels only")
    return problems


def private_get_routes(go_dir):
    routes = set()
    for f in sorted(os.listdir(go_dir)):
        if f.endswith(".go") and not f.endswith("_test.go"):
            with open(os.path.join(go_dir, f), encoding="utf-8") as fh:
                routes |= set(re.findall(r'HandleFunc\("GET (/[^" ]*)"', fh.read()))
    return sorted(r for r in routes if r not in PUBLIC)


def probe(url, go_dir):
    u = urllib.parse.urlparse(url)
    if u.scheme != "http" or u.hostname not in ("127.0.0.1", "::1", "localhost"):
        raise SystemExit("pilot_check: refused: probe only a loopback http URL (a local stand-in); the owner probes live hosts")
    rows = []
    for r in private_get_routes(go_dir):
        p = re.sub(r"\{[^}]+\}", "1", r)
        req = urllib.request.Request(url.rstrip("/") + p, method="GET", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                code = resp.status
        except urllib.error.HTTPError as e:
            code = e.code
        except (urllib.error.URLError, OSError) as e:
            code = f"error: {type(e).__name__}"
        rows.append({"route": r, "path": p, "status": code})
    open_ = [x for x in rows if isinstance(x["status"], int) and 200 <= x["status"] < 300]
    other = [x for x in rows if x["status"] != 401 and x not in open_]
    return {"routes": len(rows), "anonymous_2xx": len(open_), "not_401": len(other) + len(open_),
            "ready": not open_ and not other, "open_examples": [x["route"] for x in open_[:8]], "rows": rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("validate"); s.add_argument("case", nargs="?", default=DEFAULT_CASE)
    s = sub.add_parser("probe"); s.add_argument("url"); s.add_argument("--routes-from", default=DEFAULT_GO); s.add_argument("--json", action="store_true")
    s = sub.add_parser("run"); s.add_argument("url"); s.add_argument("--case", default=DEFAULT_CASE)
    a = ap.parse_args()
    if a.cmd == "validate":
        problems = validate(load(a.case))
        for p in problems:
            print(f"FINDING  {p}")
        print(f"VALID: {len(load(a.case)['steps'])} steps cover enrollment, reuse, expiry, writes, reads, cross-account, exports, "
              "anonymous, revocation and restore" if not problems else f"INVALID: {len(problems)} finding(s)")
        return 1 if problems else 0
    if a.cmd == "run":
        print("BLOCKED: the server has no accounts, sessions or invitations; the isolation case cannot run until the pilot "
              "authentication is implemented and `pilot_check.py probe` is READY")
        return 1
    res = probe(a.url, a.routes_from)
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"{res['routes']} private GET routes probed anonymously: {res['anonymous_2xx']} answered 2xx, "
              f"{res['not_401']} did not answer 401")
        print("READY: every private route rejects anonymous requests" if res["ready"] else
              "NOT READY: private routes answer anonymous requests, e.g. " + ", ".join(res["open_examples"]))
    return 0 if res["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
