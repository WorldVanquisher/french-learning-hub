#!/usr/bin/env python3
"""List, then remove, what is stale under a staging ROOT. Shipped inside every staging bundle.

  python3 -I bundle_cleanup.py --root ROOT [--yes] [--keep-transfers N]

Stale: bundles under ROOT/bundles that are neither ROOT/current nor ROOT/previous, interrupted
unpacks (.partial-*, .plan-*), and transfer files ROOT/transfer/flh-staging-*.tar beyond the newest
N (default 2) that no installed bundle uses, with their .sha256. Never the data, backups, settings,
current or previous. Without --yes nothing is removed. Takes the host tool's lock
(ROOT/.flh-staging-bundle.lock), so it never runs beside an install or rollback, and logs each
removal to ROOT/deploy.log in the host tool's format.

This was the host tool's `cleanup` subcommand. It moved into the bundle (repo/scripts/release/) to
keep the instance's user data small: `flh-staging-bundle cleanup` runs this file from the current
bundle (else the previous one) after checking its SHA-256 against that bundle's SHA256SUMS. Before
the first install, run it from a verified bundle directory. Standard library only (Python >= 3.9).
"""
import argparse
import datetime
import fcntl
import os
import re
import stat
import sys

NAME_RE = re.compile(r"^flh-staging-[0-9a-f]{12}$")


def link_target(link):
    return os.path.realpath(link) if os.path.islink(link) else None


def force_rmtree(path):
    """Remove a tree even when bundle files were made read-only (chmod -R a-w)."""
    for dp, dns, fns in os.walk(path, topdown=False):
        for n in fns:
            p = os.path.join(dp, n)
            if not os.path.islink(p):
                os.chmod(p, stat.S_IWUSR | stat.S_IRUSR)
            os.unlink(p)
        for n in dns:
            p = os.path.join(dp, n)
            if os.path.islink(p):
                os.unlink(p)
            else:
                os.chmod(p, stat.S_IRWXU)
                os.rmdir(p)
    os.chmod(path, stat.S_IRWXU)
    os.rmdir(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--keep-transfers", type=int, default=2)
    a = ap.parse_args(argv)
    root = os.path.realpath(a.root)
    bundles, tdir = os.path.join(root, "bundles"), os.path.join(root, "transfer")
    if not os.path.isdir(root):
        print(f"bundle_cleanup: {root} is not a staging root", file=sys.stderr)
        return 2
    say = lambda m: print(f"flh-staging-bundle: {m}", flush=True)
    lock = open(os.path.join(root, ".flh-staging-bundle.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("flh-staging-bundle: refused: another flh-staging-bundle run holds the lock", file=sys.stderr)
        return 1
    try:
        keep = {p for p in (link_target(os.path.join(root, "current")), link_target(os.path.join(root, "previous"))) if p}
        rm = []
        if os.path.isdir(bundles):
            for n in sorted(os.listdir(bundles)):
                p = os.path.join(bundles, n)
                if os.path.realpath(p) in keep:
                    continue
                if n.startswith((".partial-", ".plan-")):
                    rm.append((p, "interrupted unpack"))
                elif NAME_RE.match(n):
                    rm.append((p, "bundle neither current nor previous"))
        if os.path.isdir(tdir):
            inuse = {os.path.basename(k) + ".tar" for k in keep}
            tars = sorted((n for n in os.listdir(tdir) if n.endswith(".tar") and NAME_RE.match(n[:-4]) and n not in inuse),
                          key=lambda n: os.path.getmtime(os.path.join(tdir, n)), reverse=True)
            for n in tars[a.keep_transfers:]:
                rm.append((os.path.join(tdir, n), f"transfer file beyond the newest {a.keep_transfers} not in use"))
                if os.path.exists(os.path.join(tdir, n + ".sha256")):
                    rm.append((os.path.join(tdir, n + ".sha256"), "its .sha256"))
        for p, why in rm:
            say(f"{'removing' if a.yes else 'would remove'} {os.path.relpath(p, root)} ({why})")
            if a.yes:
                if os.path.isdir(p):
                    force_rmtree(p)
                else:
                    os.unlink(p)
                with open(os.path.join(root, "deploy.log"), "a") as fh:
                    fh.write(f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\tcleanup\t"
                             f"{os.path.relpath(p, root)}\n")
        say(f"{len(rm)} stale item(s); " + ("removed" if a.yes else "nothing removed (add --yes)")
            + "; data, backups, settings, current and previous are never touched")
        return 0
    finally:
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
