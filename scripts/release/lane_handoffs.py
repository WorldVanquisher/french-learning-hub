#!/usr/bin/env python3
"""Cross-lane handoff manifests: inventory, overlap, staging preview, dependencies (standard library).

  lane_handoffs.py import --lane L --state FINISHED|PARTIAL|BLOCKED --paths FILE --out RUN_DIR/L.handoff.json
                          [--content TAR|DIR] [--baseline-tree SHA] [--final-tree SHA] [--worktree W] [--branch B]
                          [--doc HANDOFF.md] [--test "COMMAND => RESULT"]... [--depends "LANE: what [resolved|unresolved]"]...
                          [--supersedes ID]... [--commit "SUBJECT => path,path"]... [--id ID]
  lane_handoffs.py scan WORKTREE --baseline-dir DIR --out PATHS.txt   # own lane only: S<TAB>path vs a baseline copy
  lane_handoffs.py inventory RUN_DIR [--json] [--redact]
  lane_handoffs.py overlap RUN_DIR --base-dir DIR --base-tree SHA --out DIR
  lane_handoffs.py stage-preview MANIFEST.json [--worktree DIR --baseline-dir DIR]
  lane_handoffs.py deps RUN_DIR
  lane_handoffs.py requires RUN_DIR --base-dir DIR [--path P]... [--contains "P::TEXT"]... [--adds P]... [--label L]
      Where each path a proposal needs comes from (the baseline copy or a current lane's sealed
      content) and whether it holds the text relied on; --adds checks that no lane claims a path the
      proposal creates. Exit 1 when a requirement is missing or a created path is claimed.

Manifest `flh-handoff-manifest/v1` (one per lane and handoff): id, lane, state (FINISHED: done,
PARTIAL: some items left, BLOCKED: cannot finish without the named input), worktree, branch,
baseline/final tree, paths[] {path, status A|M|D, sha256}, commits[] {subject, paths}, tests[]
{command, result}, dependencies[] {lane, what, resolved}, blockers[], supersedes[], doc, content
(where the lane's sealed bytes are: a tar or a directory; read only for the paths an overlap
needs). `import` accepts the lanes' own path lists: "S<TAB>path", "S path" and "S sha256 path".
Overlaps are computed from manifests alone; a three-way comparison then reads only the
intersecting paths, from each lane's `content` and from a baseline copy whose tree is recorded.
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile

FORMAT = "flh-handoff-manifest/v1"
STATES = ("FINISHED", "PARTIAL", "BLOCKED")


class Invalid(Exception):
    pass


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def parse_paths(path):
    rows, seen, dups = [], set(), []
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            m = (re.match(r"^([AMD])\t(\S.*)$", line) or re.match(r"^([AMD]) ([0-9a-f]{64}) (\S.*)$", line)
                 or re.match(r"^([AMD]) (\S.*)$", line))
            if not m:
                raise Invalid(f"{path}:{n}: not 'S<TAB>path', 'S path' or 'S sha256 path': {line[:80]}")
            st, rest = m.group(1), m.groups()[1:]
            p, h = (rest[1], rest[0]) if len(rest) == 2 else (rest[0], None)
            if p in seen:
                dups.append(p)
            seen.add(p)
            rows.append({"path": p, "status": st, "sha256": h})
    return rows, dups


def read_content(src, path):
    """Bytes of one path from a lane's sealed tar or directory; None when absent."""
    if not src:
        return None
    if os.path.isdir(src):
        f = os.path.join(src, path)
        if os.path.isfile(f):
            with open(f, "rb") as fh:
                return fh.read()
        return None
    with tarfile.open(src) as tf:
        for cand in (path, "./" + path):
            try:
                m = tf.getmember(cand)
            except KeyError:
                continue
            if m.isfile():
                return tf.extractfile(m).read()
        for m in tf.getmembers():   # snapshots that prefix one directory
            if m.isfile() and m.name.split("/", 1)[-1] == path:
                return tf.extractfile(m).read()
    return None


def load(path):
    with open(path) as fh:
        m = json.load(fh)
    if m.get("format") != FORMAT:
        raise Invalid(f"{path}: format {m.get('format')!r}")
    if m.get("state") not in STATES:
        raise Invalid(f"{path}: state {m.get('state')!r}")
    m["_file"] = path
    return m


def manifests(run_dir):
    out = []
    for dp, dns, fns in os.walk(run_dir):
        for f in sorted(fns):
            if f.endswith(".handoff.json"):
                out.append(load(os.path.join(dp, f)))
    ids = [m["id"] for m in out]
    if len(ids) != len(set(ids)):
        raise Invalid("two manifests share an id")
    superseded = {}
    for m in out:
        for s in m.get("supersedes", []):
            superseded[s] = m["id"]
    for m in out:
        m["_superseded_by"] = superseded.get(m["id"])
    return out


def current(ms):
    return [m for m in ms if not m["_superseded_by"]]


# --- commands --------------------------------------------------------------------------------------
def cmd_import(a):
    rows, dups = parse_paths(a.paths)
    if dups:
        raise Invalid(f"duplicate paths in {a.paths}: {dups}")
    for r in rows:
        if r["sha256"] is None and r["status"] != "D":
            b = read_content(a.content, r["path"])
            r["sha256"] = sha_bytes(b) if b is not None else None
    commits = []
    for c in a.commit:
        subj, _, ps = c.partition("=>")
        commits.append({"subject": subj.strip(), "paths": [p.strip() for p in ps.split(",") if p.strip()]})
    deps = []
    for d in a.depends:
        m = re.match(r"^\s*([a-z0-9-]+)\s*:\s*(.*?)\s*\[(resolved|unresolved)\]\s*$", d)
        if not m:
            raise Invalid(f"--depends must be 'LANE: what [resolved|unresolved]': {d}")
        deps.append({"lane": m.group(1), "what": m.group(2), "resolved": m.group(3) == "resolved"})
    tests = []
    for t in a.test:
        cmd, _, res = t.partition("=>")
        tests.append({"command": cmd.strip(), "result": res.strip()})
    man = {"format": FORMAT, "id": a.id or f"{a.lane}@{os.path.basename(os.path.dirname(os.path.realpath(a.paths)))}",
           "lane": a.lane, "state": a.state, "worktree": a.worktree, "branch": a.branch,
           "baseline": {"tree_id": a.baseline_tree}, "final": {"tree_id": a.final_tree},
           "paths": rows, "commits": commits, "tests": tests, "dependencies": deps, "blockers": a.blocker,
           "supersedes": a.supersedes, "doc": a.doc, "content": os.path.realpath(a.content) if a.content else None,
           "paths_source": os.path.realpath(a.paths)}
    os.makedirs(os.path.dirname(os.path.realpath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(man, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"{man['id']}: {a.state}, {len(rows)} paths -> {a.out}")


def cmd_scan(a):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "deploy", "aws", "private-staging", "staging"))
    import bundle_identity as BI
    cur, base = BI.scan(a.worktree), BI.scan(a.baseline_dir)
    lines = []
    for p in sorted(set(cur) | set(base)):
        if p not in cur:
            lines.append(f"D\t{p}")
        elif p not in base:
            lines.append(f"A\t{p}")
        elif cur[p] != base[p]:
            lines.append(f"M\t{p}")
    with open(a.out, "w") as fh:
        fh.write("\n".join(lines) + ("\n" if lines else ""))
    print(f"{len(lines)} changed paths -> {a.out}")


def redactor(on):
    if not on:
        return lambda t: t
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import redact as R
    return lambda t: R.redact(str(t))[0]


def cmd_inventory(a):
    ms = manifests(a.run_dir)
    R = redactor(a.redact)
    if a.json:
        print(R(json.dumps([{k: v for k, v in m.items() if not k.startswith("_") or k == "_superseded_by"} for m in ms], indent=1)))
        return 0
    print(R(f"{len(ms)} handoff manifest(s) in {a.run_dir}"))
    for m in sorted(ms, key=lambda m: (m["lane"], m["id"])):
        st = {s: sum(1 for p in m["paths"] if p["status"] == s) for s in "AMD"}
        sup = f"  SUPERSEDED by {m['_superseded_by']}" if m["_superseded_by"] else ""
        print(R(f"\n{m['id']}  [{m['state']}]{sup}\n  lane {m['lane']}  worktree {m.get('worktree') or '?'}  branch {m.get('branch') or '?'}"
                f"\n  baseline {(m['baseline'].get('tree_id') or '?')[:12]}  final {(m['final'].get('tree_id') or '?')[:12]}"
                f"  paths {len(m['paths'])} ({st['A']} A, {st['M']} M, {st['D']} D)"))
        for p in m["paths"]:
            print(f"    {p['status']} {p['path']}")
        for d in m.get("dependencies", []):
            print(f"  depends on {d['lane']}: {d['what']} [{'resolved' if d['resolved'] else 'UNRESOLVED'}]")
        for t in m.get("tests", []):
            print(R(f"  test: {t['command']} => {t['result']}"))
        for b in m.get("blockers", []):
            print(R(f"  blocker: {b}"))
        if m.get("supersedes"):
            print(f"  supersedes: {', '.join(m['supersedes'])}")
    return 0


def cmd_overlap(a):
    ms = current(manifests(a.run_dir))
    owners = {}
    for m in ms:
        for p in m["paths"]:
            owners.setdefault(p["path"], []).append((m, p))
    shared = {p: o for p, o in owners.items() if len(o) > 1}
    os.makedirs(a.out, exist_ok=True)
    results = []
    for path, o in sorted(shared.items()):
        base_file = os.path.join(a.base_dir, path)
        base = open(base_file, "rb").read() if os.path.isfile(base_file) else None
        for i in range(len(o)):
            for j in range(i + 1, len(o)):
                (ma, pa), (mb, pb) = o[i], o[j]
                r = {"path": path, "lanes": [ma["lane"], mb["lane"]], "kinds": [pa["status"], pb["status"]],
                     "expected_baseline": {"tree_id": a.base_tree, "path_sha256": sha_bytes(base) if base is not None else None}}
                ba, bb = read_content(ma.get("content"), path), read_content(mb.get("content"), path)
                if "D" in r["kinds"]:
                    r["result"] = "DELETE vs CHANGE: manual"
                elif ba is None or bb is None:
                    r["result"] = f"UNVERIFIED: no sealed content for {ma['lane'] if ba is None else mb['lane']}"
                elif ba == bb:
                    r["result"] = "identical (overlap, no conflict)"
                elif base is None:
                    r["result"] = "BOTH ADDED, DIFFERENT: manual"
                else:
                    with tempfile.TemporaryDirectory(dir=a.out) as td:
                        fa, fo, fb = (os.path.join(td, n) for n in ("a", "o", "b"))
                        for f, data in ((fa, ba), (fo, base), (fb, bb)):
                            with open(f, "wb") as fh:
                                fh.write(data)
                        p = subprocess.run(["diff3", "-m", fa, fo, fb], capture_output=True)
                    merged = os.path.join(a.out, path.replace("/", "__") + f".{ma['lane']}+{mb['lane']}")
                    with open(merged, "wb") as fh:
                        fh.write(p.stdout)
                    hunks = p.stdout.count(b"<<<<<<<")
                    r["result"] = "clean merge (overlap, no conflict)" if p.returncode == 0 else f"CONFLICT: {hunks} hunk(s)"
                    r["merged"] = merged
                    r["merged_sha256"] = sha_bytes(p.stdout) if p.returncode == 0 else None
                results.append(r)
    with open(os.path.join(a.out, "overlap.json"), "w") as fh:
        json.dump(results, fh, indent=1, sort_keys=True)
    print(f"{len(ms)} current manifest(s); {len(shared)} path(s) claimed by more than one lane; baseline {a.base_tree}")
    for r in results:
        print(f"  {r['path']}: {' + '.join(r['lanes'])} ({'/'.join(r['kinds'])}): {r['result']}")
    return 1 if any(r["result"].startswith(("CONFLICT", "DELETE", "BOTH", "UNVERIFIED")) for r in results) else 0


def cmd_stage_preview(a):
    m = load(a.manifest)
    problems = []
    declared = [p["path"] for p in m["paths"]]
    dups = sorted({p for p in declared if declared.count(p) > 1})
    if dups:
        problems.append(f"duplicate paths: {dups}")
    groups = m.get("commits") or [{"subject": "(one commit)", "paths": declared}]
    grouped = [p for g in groups for p in g["paths"]]
    gd = sorted({p for p in grouped if grouped.count(p) > 1})
    if gd:
        problems.append(f"paths in more than one commit: {gd}")
    if sorted(set(grouped) - set(declared)):
        problems.append(f"unexpected paths in commits (not in the handoff): {sorted(set(grouped) - set(declared))}")
    if sorted(set(declared) - set(grouped)):
        problems.append(f"missing from every commit: {sorted(set(declared) - set(grouped))}")
    if a.worktree:
        for p in m["paths"]:
            f = os.path.join(a.worktree, p["path"])
            if p["status"] == "D" and os.path.lexists(f):
                problems.append(f"declared deleted but present: {p['path']}")
            elif p["status"] != "D" and not os.path.isfile(f):
                problems.append(f"missing path: {p['path']}")
            elif p["status"] != "D" and p.get("sha256"):
                with open(f, "rb") as fh:
                    if sha_bytes(fh.read()) != p["sha256"]:
                        problems.append(f"content differs from the handoff: {p['path']}")
        if a.baseline_dir:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                            "deploy", "aws", "private-staging", "staging"))
            import bundle_identity as BI
            cur, base = BI.scan(a.worktree), BI.scan(a.baseline_dir)
            actual = {p for p in set(cur) | set(base) if cur.get(p) != base.get(p)}
            extra = sorted(actual - set(declared))
            if extra:
                problems.append(f"unexpected changed paths not in the handoff: {extra}")
    print(f"# staging preview for {m['id']} [{m['state']}] (owner runs these; nothing was staged)")
    print(f"cd {m.get('worktree') or '<worktree>'}")
    for g in groups:
        print(f"# {g['subject']}")
        print("git add -- " + " ".join(g["paths"]))
        print("git diff --cached --check")
    for p in problems:
        print(f"PROBLEM {p}", file=sys.stderr)
    print("PREVIEW " + ("REFUSED" if problems else "OK"), file=sys.stderr)
    return 1 if problems else 0


def cmd_deps(a):
    ms = current(manifests(a.run_dir))
    lanes = {m["lane"]: m for m in ms}
    order, seen, cycle = [], set(), []

    def visit(lane, stack):
        if lane in seen or lane not in lanes:
            return
        if lane in stack:
            cycle.append(" -> ".join(stack + [lane]))
            return
        for d in lanes[lane].get("dependencies", []):
            visit(d["lane"], stack + [lane])
        if lane not in seen:
            seen.add(lane)
            order.append(lane)
    for lane in sorted(lanes):
        visit(lane, [])
    print("review order (dependencies first): " + " -> ".join(order))
    for lane in order:
        for d in lanes[lane].get("dependencies", []):
            known = "" if d["lane"] in lanes else " (no current manifest for that lane)"
            print(f"  {lane} needs {d['lane']}: {d['what']}: {'resolved' if d['resolved'] else 'UNRESOLVED'}{known}")
    for c in cycle:
        print(f"  CYCLE: {c}")
    unresolved = [(l, d) for l in order for d in lanes[l].get("dependencies", []) if not d["resolved"]]
    print(f"{len(unresolved)} unresolved dependenc{'y' if len(unresolved) == 1 else 'ies'}")
    return 1 if unresolved or cycle else 0


def cmd_requires(a):
    cur = current(manifests(a.run_dir))
    reqs = [(p, None) for p in a.path] + [tuple(c.split("::", 1)) for c in a.contains]
    bad, lanes = 0, set()
    print(f"requirements of {a.label or 'the proposal'}: {len(reqs)}, against {len(cur)} current handoff(s) and the baseline")
    for path, text in reqs:
        prov = [(m, r) for m in cur for r in m["paths"] if r["path"] == path]
        if prov and prov[-1][1]["status"] == "D":
            data, src = None, f"deleted by {prov[-1][0]['id']}"
        elif prov:
            m, r = prov[-1]
            data, src = read_content(m.get("content"), path), f"{m['id']} [{m['state']}] ({r['status']})"
            lanes.add(m["lane"])
            if len(prov) > 1:
                src += f"; also claimed by {', '.join(x[0]['id'] for x in prov[:-1])}"
        elif os.path.isfile(os.path.join(a.base_dir, path)):
            with open(os.path.join(a.base_dir, path), "rb") as fh:
                data, src = fh.read(), "baseline"
        else:
            data, src = None, "nowhere"
        ok = data is not None and (text is None or text.encode() in data)
        bad += 0 if ok else 1
        what = f"{path} contains {text!r}" if text else path
        print(f"  {'ok' if ok else 'MISSING':<8} {what}: {src}" + ("" if ok or data is None else " (text not found)"))
    for path in a.adds:
        claim = [m["id"] for m in cur for r in m["paths"] if r["path"] == path]
        exists = os.path.exists(os.path.join(a.base_dir, path))
        ok = not claim and not exists
        bad += 0 if ok else 1
        print(f"  {'ok' if ok else 'CLASH':<8} creates {path}: " + ("no lane claims it, not in the baseline" if ok else
              f"claimed by {claim}" if claim else "already in the baseline"))
    print(f"lands after: {', '.join(sorted(lanes)) or 'nothing (the baseline has everything)'}")
    if bad:
        print(f"BLOCKED: {bad} requirement(s) not met")
        return 1
    print("READY: every requirement is met by the baseline or by the lanes named above")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("import")
    for k in ("--lane", "--state", "--paths", "--out"):
        i.add_argument(k, required=True)
    for k in ("--content", "--baseline-tree", "--final-tree", "--worktree", "--branch", "--doc", "--id"):
        i.add_argument(k)
    for k in ("--test", "--depends", "--supersedes", "--commit", "--blocker"):
        i.add_argument(k, action="append", default=[])
    s = sub.add_parser("scan")
    s.add_argument("worktree")
    s.add_argument("--baseline-dir", required=True)
    s.add_argument("--out", required=True)
    v = sub.add_parser("inventory")
    v.add_argument("run_dir")
    v.add_argument("--json", action="store_true")
    v.add_argument("--redact", action="store_true", help="mask absolute paths, IDs and addresses (redact.py)")
    o = sub.add_parser("overlap")
    o.add_argument("run_dir")
    o.add_argument("--base-dir", required=True)
    o.add_argument("--base-tree", required=True)
    o.add_argument("--out", required=True)
    p = sub.add_parser("stage-preview")
    p.add_argument("manifest")
    p.add_argument("--worktree")
    p.add_argument("--baseline-dir")
    d = sub.add_parser("deps")
    d.add_argument("run_dir")
    q = sub.add_parser("requires")
    q.add_argument("run_dir")
    q.add_argument("--base-dir", required=True)
    for k in ("--path", "--contains", "--adds"):
        q.add_argument(k, action="append", default=[])
    q.add_argument("--label")
    a = ap.parse_args()
    if getattr(a, "state", None) and a.state not in STATES:
        print(f"lane_handoffs: state must be one of {STATES}", file=sys.stderr)
        return 2
    try:
        return {"import": cmd_import, "scan": cmd_scan, "inventory": cmd_inventory, "overlap": cmd_overlap,
                "stage-preview": cmd_stage_preview, "deps": cmd_deps, "requires": cmd_requires}[a.cmd](a) or 0
    except Invalid as e:
        print(f"lane_handoffs: invalid: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
