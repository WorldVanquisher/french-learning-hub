#!/usr/bin/env python3
"""Owner-run preflight before integrating the lanes: does the repository still match the rehearsal?

  python3 -I scripts/release/owner_preflight.py EXPECT.json --ref main=origin/main \
      [--ref LANE=REF]... [--after-merge LANE]...

Run by the OWNER in their checkout, after their own `git fetch` (this script never fetches, pushes or
changes anything; it only runs read-only `git rev-parse`, `git status --porcelain` and
`git merge-base`). EXPECT.json comes from the integration handoff (integration_candidate.py slices +
lane-tree): the base tree, each lane's tree (base + that lane), and the tree after each lane in the
review order. Checks:
  base       main's tree equals the rehearsal's base tree (else main moved: rehearse again on it)
  clean      the working tree has no uncommitted change
  lane LANE  REF's tree equals that lane's sealed tree, and REF descends from main (no other base)
  merged     with --after-merge LANE: HEAD's tree equals the expected state after that lane
Prints one line per check and a verdict: READY (exit 0) or STOP (exit 1); 2 on usage errors.
Agents do not run this against a real repository (no Git for agents); tests use a stub `git`.
"""
import argparse
import json
import subprocess
import sys


def git(*args):
    p = subprocess.run(["git", *args], capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def tree_of(ref):
    rc, out, err = git("rev-parse", f"{ref}^{{tree}}")
    return out if rc == 0 else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("expect")
    ap.add_argument("--ref", action="append", default=[], help="NAME=REF (main=..., or a lane name)")
    ap.add_argument("--after-merge", action="append", default=[])
    a = ap.parse_args(argv)
    with open(a.expect) as fh:
        E = json.load(fh)
    refs = dict(r.split("=", 1) for r in a.ref)
    if "main" not in refs:
        print("owner_preflight: --ref main=REF is required", file=sys.stderr)
        return 2
    rows = []

    def check(name, ok, detail, fix=""):
        rows.append(ok)
        print(f"{'PASS' if ok else 'STOP'}\t{name}\t{detail}" + (f"\n\tnext: {fix}" if not ok and fix else ""))

    t = tree_of(refs["main"])
    check("base", t == E["base_tree"], f"{refs['main']} tree {t or 'unreadable'}; rehearsed on {E['base_tree']}",
          "main moved since the rehearsal: rerun the integration rehearsal on the new base before merging")
    rc, out, _ = git("status", "--porcelain")
    check("clean", rc == 0 and out == "", "no uncommitted change" if rc == 0 and not out else f"{len(out.splitlines())} changed path(s)",
          "commit or stash your own work first")
    for lane, ref in refs.items():
        if lane == "main":
            continue
        want = (E.get("lanes") or {}).get(lane)
        if want is None:
            check(f"lane {lane}", False, "not in EXPECT.json", "use a lane name from the handoff")
            continue
        got = tree_of(ref)
        rc, mb, _ = git("merge-base", "--is-ancestor", refs["main"], ref)
        check(f"lane {lane}", got == want and rc == 0,
              f"{ref} tree {got or 'unreadable'} (sealed {want}); descends from main: {'yes' if rc == 0 else 'no'}",
              "the branch holds other bytes than the sealed handoff, or another base: compare before merging")
    states = {s["after"]: s["tree_id"] for s in E.get("states", [])}
    for lane in a.after_merge:
        got = tree_of("HEAD")
        check(f"merged {lane}", got == states.get(lane), f"HEAD tree {got}; expected after {lane}: {states.get(lane)}",
              "the merge result differs from the rehearsal: run integration_candidate.py verify on this checkout")
    ok = all(rows)
    print(("READY" if ok else "STOP") + f": {sum(rows)}/{len(rows)} checks pass")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
