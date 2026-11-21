#!/usr/bin/env python3
"""Refuse Terraform state, plans, filled-in variables, databases, keys and env files before they are shared.

  state_guard.py scan DIR...                    every file under DIR (handoff folders, evidence archives)
  state_guard.py --stdin                        one path per line, e.g. `git diff --cached --name-only | state_guard.py --stdin`
                                                (the owner runs Git; agents never do)
  state_guard.py ignore-check [REPO]            each Terraform root's .gitignore still names the required patterns

.gitignore is a convenience, not a guard: `git add -f` and copied folders bypass it. Exit 0 clean, 1 finding, 2 usage.
Allowed on purpose: *.tfvars.example, .terraform.lock.hcl (provider pins).
"""
import fnmatch
import os
import sys

RULES = [
    ("terraform-state", ["*.tfstate", "*.tfstate.*", ".terraform.tfstate.lock.info"]),
    ("terraform-plan", ["*.tfplan", "*.tfplan.json", "*.plan.json", "plan.out"]),
    ("terraform-vars", ["terraform.tfvars", "*.auto.tfvars", "*.auto.tfvars.json", "production.tfvars", "staging.tfvars"]),
    ("terraform-workdir", [".terraform/*"]),
    ("database", ["*.db", "*.db-wal", "*.db-shm", "*.sqlite", "*.sqlite3"]),
    ("env-file", [".env", "*.env", "staging.env"]),
    ("private-key", ["*.pem", "*.key", "id_rsa", "id_ed25519"]),
    ("crash-log", ["crash.log", "crash.*.log"]),
]
ALLOWED = ["*.tfvars.example", ".terraform.lock.hcl"]
ROOT_PATTERNS = [".terraform/", "*.tfstate", "*.tfplan"]          # required
TFVARS_ANY = ("*.tfvars", "terraform.tfvars")                       # at least one; the broad form is preferred
TERRAFORM_ROOTS = ["deploy/aws/private-staging", "deploy/aws/terraform"]


def classify(path):
    p = path.replace(os.sep, "/")
    while p.startswith("./"):
        p = p[2:]
    name = p.rsplit("/", 1)[-1]
    if any(fnmatch.fnmatch(name, a) for a in ALLOWED):
        return None
    for cls, pats in RULES:
        for pat in pats:
            if "/" in pat:
                if f"/{pat.split('/')[0]}/" in f"/{p}":
                    return cls
            elif fnmatch.fnmatch(name, pat):
                return cls
    return None


def scan(paths):
    found = []
    for root in paths:
        if os.path.isfile(root):
            c = classify(root)
            if c:
                found.append((c, root))
            continue
        for d, ds, fs in os.walk(root):
            ds[:] = [x for x in ds if x != "node_modules"]
            for f in fs:
                rel = os.path.relpath(os.path.join(d, f), root)
                c = classify(rel)
                if c:
                    found.append((c, os.path.join(os.path.basename(os.path.abspath(root)), rel)))
    return found


def ignore_check(repo):
    problems = []
    for r in TERRAFORM_ROOTS:
        gi = os.path.join(repo, r, ".gitignore")
        if not os.path.isfile(gi):
            problems.append(f"{r}: no .gitignore")
            continue
        with open(gi, encoding="utf-8") as fh:
            lines = {l.strip() for l in fh if l.strip() and not l.startswith("#")}
        for pat in ROOT_PATTERNS:
            if pat not in lines:
                problems.append(f"{r}/.gitignore lacks {pat}")
        if not any(t in lines for t in TFVARS_ANY):
            problems.append(f"{r}/.gitignore ignores no tfvars file")
        elif "*.tfvars" not in lines:
            print(f"NOTE     {r}/.gitignore ignores terraform.tfvars only; *.auto.tfvars or other.tfvars would not be ignored")
    return problems


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    if argv[0] == "ignore-check":
        repo = argv[1] if len(argv) > 1 else os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
        problems = ignore_check(repo)
        for p in problems:
            print(f"FINDING  {p}")
        print("IGNORE-CHECK OK" if not problems else f"IGNORE-CHECK: {len(problems)} finding(s)")
        return 1 if problems else 0
    if argv[0] == "--stdin":
        found = [(c, l.strip()) for l in sys.stdin if l.strip() for c in [classify(l.strip())] if c]
    elif argv[0] == "scan" and len(argv) > 1:
        found = scan(argv[1:])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    for c, p in found:
        print(f"REFUSED  {c:18} {p}")
    print("CLEAN: no state, plan, filled-in variables, database, key or env file" if not found else
          f"REFUSED: {len(found)} file(s) must not be committed or shared")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
