#!/usr/bin/env python3
"""Source identity for the staging bundle (no Git needed, standard library only).

  bundle_identity.py tree-id TREE_DIR [--allow-worktree]
      JSON: the Git tree SHA-1 of TREE_DIR computed without Git, the file
      count, a SHA-256 over (path, mode, content SHA-256) of every file, and the
      migration ledger the tree ships (count and last file).
  bundle_identity.py write-manifest BUNDLE_DIR --identity FILE --commit SHA|-
          --image-tag TAG --server-sha256 HEX --web-sha256 HEX
      Writes BUNDLE_DIR/MANIFEST.json: the stable identity of one bundle. It is
      byte-identical for every build of the same revision whose server binary
      and web files are reproducible (staging/README "Reproducibility").

The tree ID equals `git rev-parse <rev>^{tree}` for a `git archive` export of
<rev> (every file tracked, modes 100644/100755/120000). For a working copy the
same exclusions as the release lane's manifests apply (build outputs, caches,
local data, Terraform state), so a dirty worktree never reports a clean ID by
accident: tree-id refuses a directory holding .git unless --allow-worktree.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import sys

EX_DIRS = {".git", "web/node_modules", "web/dist", "web/dist-ssr", "web/.vite", "web/coverage", "bin",
           "deploy/aws/terraform/.terraform", "deploy/aws/private-staging/staging/terraform/.terraform"}
EX_FILES = {".git", ".env", "server", "capture", "PROJECT_REPORT.md", "coverage.out"}
EX_GLOB = ["*.db", "*.db-shm", "*.db-wal", "*.log", "*.tsbuildinfo", "*.tfstate", "*.tfstate.*", "*.tfplan"]
EX_DIRNAMES = {"node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
FORMAT = "flh-staging-bundle/v2"
LABEL_REVISION = "org.opencontainers.image.revision"
LABEL_TREE = "org.flh.staging.tree-id"


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _mode(full):
    if os.path.islink(full):
        return "120000"
    return "100755" if os.stat(full).st_mode & 0o111 else "100644"


def scan(root):
    """{relative path: (git mode, sha256)} for every file that belongs to the tree."""
    rows = {}
    for dp, dns, fns in os.walk(root):
        rel = os.path.relpath(dp, root)
        rel = "" if rel == "." else rel
        dns[:] = sorted(d for d in dns if os.path.join(rel, d) not in EX_DIRS and d not in EX_DIRNAMES)
        for f in sorted(fns):
            p = os.path.join(rel, f)
            if p in EX_FILES or any(fnmatch.fnmatch(f, g) for g in EX_GLOB):
                continue
            if p.startswith("data/") and p != "data/.gitkeep":
                continue
            full = os.path.join(root, p)
            digest = (hashlib.sha256(os.readlink(full).encode()).hexdigest() if os.path.islink(full)
                      else _sha256_file(full))
            rows[p] = (_mode(full), digest)
    return rows


def _obj(kind, data):
    return hashlib.sha1(b"%s %d\0" % (kind, len(data)) + data).digest()


def tree_id(root, rows):
    tree = {}
    for p in rows:
        node = tree
        parts = p.split("/")
        for d in parts[:-1]:
            node = node.setdefault(d, {})
        node[parts[-1]] = p

    def build(node):
        ents = []
        for name, v in node.items():
            b = os.fsencode(name)
            if isinstance(v, dict):
                ents.append((b + b"/", b, b"40000", build(v)))
                continue
            full = os.path.join(root, v)
            if os.path.islink(full):
                ents.append((b, b, b"120000", _obj(b"blob", os.fsencode(os.readlink(full)))))
            else:
                with open(full, "rb") as fh:
                    ents.append((b, b, rows[v][0].encode(), _obj(b"blob", fh.read())))
        ents.sort(key=lambda e: e[0])
        return _obj(b"tree", b"".join(m + b" " + n + b"\0" + h for _, n, m, h in ents))
    return build(tree).hex()


def content_digest(rows):
    h = hashlib.sha256()
    for p in sorted(rows):
        h.update(f"{p}\t{rows[p][0]}\t{rows[p][1]}\n".encode())
    return h.hexdigest()


def identity(root):
    rows = scan(root)
    migs = sorted(p.split("/", 1)[1] for p in rows if p.startswith("migrations/") and p.endswith(".sql")
                  and p.count("/") == 1)
    return {"tree_id": tree_id(root, rows), "files": len(rows), "content_sha256": content_digest(rows),
            "migrations": {"count": len(migs), "last": migs[-1] if migs else None}}


def bundle_files(bundle_dir):
    """Every file of a bundle that MANIFEST.json pins (the deployable scripts, docs and override)."""
    out = {}
    for dp, dns, fns in os.walk(bundle_dir):
        dns.sort()
        for f in sorted(fns):
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, bundle_dir)
            if rel == "staging.override.yaml" or rel.startswith("repo/"):
                out[rel] = _sha256_file(full)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tree-id")
    t.add_argument("tree")
    t.add_argument("--allow-worktree", action="store_true")
    m = sub.add_parser("write-manifest")
    m.add_argument("bundle")
    m.add_argument("--identity", required=True)
    m.add_argument("--commit", required=True)
    m.add_argument("--image-tag", required=True)
    m.add_argument("--server-sha256", required=True)
    m.add_argument("--web-sha256", required=True)
    a = ap.parse_args()
    if a.cmd == "tree-id":
        root = os.path.realpath(a.tree)
        if not os.path.isfile(os.path.join(root, "Dockerfile")) or not os.path.isfile(os.path.join(root, "compose.yaml")):
            sys.exit(f"refused: {root} is not a repository tree (no Dockerfile/compose.yaml)")
        if os.path.exists(os.path.join(root, ".git")) and not a.allow_worktree:
            sys.exit(f"refused: {root} is a Git checkout; build from an export (git archive), not a worktree")
        print(json.dumps(identity(root), sort_keys=True))
        return
    ident = json.load(open(a.identity))
    commit = None if a.commit == "-" else a.commit
    if commit is not None and (len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit)):
        sys.exit("refused: --commit must be a full 40-character commit SHA (or - for a tree-only rehearsal)")
    tid = ident["tree_id"]
    manifest = {
        "format": FORMAT,
        "name": f"flh-staging-{tid[:12]}",
        "revision": {"commit": commit, "tree_id": tid, "files": ident["files"],
                     "content_sha256": ident["content_sha256"]},
        "image": {"tag": a.image_tag, "platform": "linux/amd64",
                  "labels": {LABEL_REVISION: commit or "", LABEL_TREE: tid}},
        "server_sha256": a.server_sha256,
        "web_files_sha256": a.web_sha256,
        "migrations": ident["migrations"],
        "files": bundle_files(a.bundle),
    }
    if os.path.basename(os.path.normpath(a.bundle)) != manifest["name"]:
        sys.exit(f"refused: bundle directory must be named {manifest['name']}")
    with open(os.path.join(a.bundle, "MANIFEST.json"), "w") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
        fh.write("\n")


if __name__ == "__main__":
    main()
