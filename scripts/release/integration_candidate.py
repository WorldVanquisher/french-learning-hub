#!/usr/bin/env python3
"""Assemble an integration candidate from sealed lane snapshots, without Git.

  integration_candidate.py select   SELECTION.json --out SELECTED.json
  integration_candidate.py assemble SELECTED.json --out TREE_DIR [--work DIR]
  integration_candidate.py catalogs TREE_DIR [--base BASE_DIR] [--lane LABEL=DIR]...
  integration_candidate.py compare  OLD_DIR NEW_DIR [--selected SELECTED.json]
  integration_candidate.py verify   SELECTED.json TREE_DIR       # every lane change holds in TREE_DIR
  integration_candidate.py tree-id  TREE_DIR
  integration_candidate.py lane-tree SELECTED.json LANE           # base + that lane alone
  integration_candidate.py slices SELECTED.json --work DIR        # tree after each lane in order; cross-lane uses
  integration_candidate.py reproduce SELECTION.json --expect TREE_ID   # select + assemble from scratch, one command
  integration_candidate.py rebuild  --manifest START --from SRC... [--patch P] --expect FINAL --out DIR

`select` reads a selection (format `flh-integration-selection/v1`, kept outside Git because
it names local directories) and checks, for every lane:
  - the seal: every line of its SHA256SUMS hashes correctly, the SHA256SUMS digest equals
    the pinned one (a re-sealed or newer handoff is refused, not silently taken), and the
    snapshot it names is covered by that seal;
  - the snapshot's own consistency: a path both deleted and supplied, a duplicate path, a
    tar member that is not a plain file or symlink, a symlink pointing outside the tree;
  - the lane's base equals the shared base (when the lane sealed a base manifest);
  - pending owner proposals stay out: their paths are not in any lane's intended state.
It writes SELECTED.json (`flh-integration-selected/v1`): per lane, the intended state of every
path it changes against the shared base (sha256, mode, symlink target), plus where its bytes
can be read. SELECTED.json carries everything `assemble` needs; it is the reviewable input.

`assemble` builds TREE_DIR = shared base + every lane's changes, in the selected lane order.
Bytes are content-addressed: a path is written only from a source whose bytes hash to the
intended SHA-256 (sealed tars first, then hash-only stores, then a lane worktree, read-only,
when the selection allows it). A source that changes while it is read (tar digest, or a
file's size/mtime/inode moving under the read) stops the assembly. A path changed by two or
more lanes is merged with `diff3 -m` against the base, lane by lane; a conflict stops it.
After merging, every lane's changed lines and, for the UI catalogs, every key it added,
changed or removed must hold in the result: a text merge that drops a key is refused even
when diff3 reports success. Finally every path is re-hashed against the plan, the tree ID is
computed, and TREE_DIR/../assembly.json records the provenance of every byte.

`catalogs` checks web/src/i18n/en.ts and zh-CN.ts: duplicate keys, missing or extra keys,
{placeholder} parity; with --base/--lane, that each lane's key changes survive.
`compare` lists what differs between two trees, attributed to lanes when --selected is given.
`rebuild` recreates a lane that sealed only hash manifests and a patch: START's files by hash
from sealed sources, the patch applied, every file checked against the FINAL manifest. The
result is a hash-only byte source for `assemble`, so the lane's live worktree is not needed.

Exit 0 on success, 1 on a refusal (the reason is printed), 2 on usage errors. Standard
library plus `diff3`; no Git, no network.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.realpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "deploy", "aws", "private-staging", "staging"))
import bundle_identity as BI  # noqa: E402

SELECTION = "flh-integration-selection/v1"
SELECTED = "flh-integration-selected/v1"
ASSEMBLY = "flh-integration-assembly/v1"
CATALOGS = ("web/src/i18n/en.ts", "web/src/i18n/zh-CN.ts")


class Refused(Exception):
    pass


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# --- seals ---------------------------------------------------------------------------------------
def read_sums(path):
    """{relative path: sha256} from a `sha256sum` file; './' prefixes are dropped."""
    out = {}
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            m = re.match(r"^([0-9a-f]{64}) [ *](.+)$", line)
            if not m:
                raise Refused(f"{path}:{n}: not a sha256sum line")
            p = os.path.normpath(m.group(2))
            if p in out and out[p] != m.group(1):
                raise Refused(f"{path}: {p} listed twice with different digests")
            out[p] = m.group(1)
    return out


def verify_seal(seal):
    """Every file the seal lists hashes to its line; the seal file itself has the pinned digest."""
    d, sums = seal["dir"], os.path.join(seal["dir"], seal.get("sums", "SHA256SUMS"))
    if not os.path.isfile(sums):
        raise Refused(f"seal file missing: {sums}")
    digest = sha256_file(sums)
    if seal.get("digest") and digest != seal["digest"]:
        raise Refused(f"seal {sums} has digest {digest[:16]}, the selection pins {seal['digest'][:16]}: "
                      "the handoff was re-sealed or replaced; select the new seal explicitly")
    listed = read_sums(sums)
    bad = [p for p, h in sorted(listed.items())
           if not os.path.isfile(os.path.join(d, p)) or sha256_file(os.path.join(d, p)) != h]
    if bad:
        raise Refused(f"seal {sums}: {len(bad)} file(s) do not match: {bad[:5]}")
    return {"sums": os.path.relpath(sums, d), "digest": digest, "files": len(listed)}, listed


def covered(listed, rel, what):
    rel = os.path.normpath(rel)
    if rel not in listed:
        raise Refused(f"{what} {rel} is not covered by its lane's seal")
    return listed[rel]


# --- states: {path: {"type": "file"|"symlink", "sha256", "mode", "target"?}} ---------------------
def scan_state(root):
    st = {}
    for p, (mode, h) in BI.scan(root).items():
        full = os.path.join(root, p)
        if mode == "120000":
            st[p] = {"type": "symlink", "target": os.readlink(full), "sha256": h, "mode": mode}
        else:
            st[p] = {"type": "file", "sha256": h, "mode": mode}
    return st


def member_path(name):
    """A tar member's tree path: only an exact leading './' is dropped (never the dot of '.github')."""
    while name.startswith("./"):
        name = name[2:]
    name = name.rstrip("/")
    return os.path.normpath(name) if name not in ("", ".") else ""


def check_symlink(p, target):
    if os.path.isabs(target):
        raise Refused(f"symlink {p} -> {target}: absolute target")
    norm = os.path.normpath(os.path.join(os.path.dirname(p), target))
    if norm.startswith("..") or norm == ".":
        raise Refused(f"symlink {p} -> {target}: points outside the tree")


def tar_state(path, only=None):
    """State of a (gz) tar's members, keyed by relative path; refuses unsupported members."""
    st, seen = {}, set()
    with tarfile.open(path) as tf:
        for m in tf.getmembers():
            p = member_path(m.name)
            if not p or m.isdir():
                continue
            if only is not None and p not in only:
                continue
            if p in seen:
                raise Refused(f"{os.path.basename(path)}: member {p} appears twice")
            seen.add(p)
            if p.startswith("..") or os.path.isabs(m.name):
                raise Refused(f"{os.path.basename(path)}: unsafe member {m.name}")
            if m.issym():
                check_symlink(p, m.linkname)
                st[p] = {"type": "symlink", "target": m.linkname, "sha256": sha256_bytes(m.linkname.encode()),
                         "mode": "120000"}
            elif m.isfile():
                data = tf.extractfile(m).read()
                st[p] = {"type": "file", "sha256": sha256_bytes(data),
                         "mode": "100755" if m.mode & 0o111 else "100644"}
            else:
                raise Refused(f"{os.path.basename(path)}: member {p} is not a plain file or symlink")
    return st


def read_paths_list(path):
    """[(status, path)] from 'A path' / 'M path' / 'D path' lines."""
    out = []
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            parts = line.rstrip("\n").split(None, 1)
            if len(parts) != 2 or parts[0] not in ("A", "M", "D"):
                raise Refused(f"{path}:{n}: expected 'A|M|D path'")
            out.append((parts[0], os.path.normpath(parts[1].strip())))
    return out


def read_hash_manifest(path):
    """{path: sha256} from 'sha256  path' lines (no modes, no symlinks)."""
    out = {}
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            if "\t" in line:                        # path<TAB>mode<TAB>sha (lane manifests)
                p, mode, h = line.split("\t")
            else:
                parts = line.split("  ")
                h, p = parts[0], parts[-1]
            if not re.fullmatch(r"[0-9a-f]{64}", h) and not h.startswith("symlink:"):
                raise Refused(f"{path}:{n}: not a manifest line")
            p = os.path.normpath(p)
            if p in out:
                raise Refused(f"{path}: {p} listed twice")
            out[p] = h
    return out


def lane_state(name, cfg, base, listed):
    """The lane's intended state for the paths it changes, plus notes; refuses inconsistent snapshots."""
    snap, d = cfg["snapshot"], cfg["seal"]["dir"]
    notes = []
    kind = snap["kind"]
    if kind == "tree-tar":                                  # the lane's whole final tree
        tar = os.path.join(d, snap["tar"])
        if snap.get("attested_by"):
            # a tar made outside the lane's seal (the seal holds no bytes): accepted only when its tree id
            # equals the id that a sealed record states, and that record's seal verifies
            att = snap["attested_by"]
            _, att_listed = verify_seal({"dir": att["dir"], "sums": att.get("sums", "SHA256SUMS"),
                                         "digest": att.get("digest")})
            covered(att_listed, att["file"], "attesting record")
            with open(os.path.join(att["dir"], att["file"])) as fh:
                if snap.get("tree_id", "-") not in fh.read():
                    raise Refused(f"{name}: {att['file']} does not state tree {snap.get('tree_id')}")
            tar_sha = sha256_file(tar)
            notes.append(f"snapshot outside the lane seal, pinned by tree {snap['tree_id'][:12]} as stated in the sealed "
                         f"{att['file']}")
        else:
            tar_sha = covered(listed, snap["tar"], "snapshot")
        if sha256_file(tar) != tar_sha:
            raise Refused(f"{name}: snapshot tar changed after its seal")
        if snap.get("attested_by") and not snap.get("tree_id"):
            raise Refused(f"{name}: an attested snapshot needs tree_id")
        full = tar_state(tar)
        if snap.get("tree_id"):
            got = tree_id_of_state(full, tar)
            if got != snap["tree_id"]:
                raise Refused(f"{name}: snapshot tree id {got[:12]}, the handoff states {snap['tree_id'][:12]}")
        delta = {p: dict(e, status="A" if p not in base else "M") for p, e in full.items() if base.get(p) != e}
        for p in base:
            if p not in full:
                delta[p] = {"status": "D"}
        sources = [{"kind": "tar", "path": tar, "sha256": tar_sha}]
        final = full
    elif kind == "delta-tar":                               # changed paths only, with an A/M/D list
        tar = os.path.join(d, snap["tar"])
        tar_sha = covered(listed, snap["tar"], "snapshot")
        covered(listed, snap["paths"], "path list")
        if sha256_file(tar) != tar_sha:
            raise Refused(f"{name}: snapshot tar changed after its seal")
        plist = read_paths_list(os.path.join(d, snap["paths"]))
        seen = {}
        for s, p in plist:
            if p in seen:
                raise Refused(f"{name}: {p} is listed twice in {snap['paths']} ({seen[p]} and {s})")
            seen[p] = s
        members = tar_state(tar)
        both = sorted(p for p, s in seen.items() if s == "D" and p in members)
        if both:
            raise Refused(f"{name}: path(s) both deleted and supplied by the snapshot: {both[:5]}")
        missing = sorted(p for p, s in seen.items() if s != "D" and p not in members)
        if missing:
            raise Refused(f"{name}: listed but not in the sealed tar: {missing[:5]}")
        extra = sorted(set(members) - set(seen))
        if extra:
            raise Refused(f"{name}: tar members not in the path list: {extra[:5]}")
        delta = {}
        for p, s in seen.items():
            if s == "D":
                if p not in base:
                    raise Refused(f"{name}: deletes {p}, which the base does not have")
                delta[p] = {"status": "D"}
            else:
                if (s == "M") != (p in base):
                    raise Refused(f"{name}: {p} is listed {s} but the base {'has' if p in base else 'lacks'} it")
                delta[p] = dict(members[p], status=s)
        sources = [{"kind": "tar", "path": tar, "sha256": tar_sha}]
        final = None
    elif kind == "manifest":                                 # a full-tree hash manifest, bytes elsewhere
        man_rel = snap["manifest"]
        covered(listed, man_rel, "manifest")
        man = read_hash_manifest(os.path.join(d, man_rel))
        delta = {}
        for p, h in man.items():
            if h.startswith("symlink:"):
                tgt = h.split(":", 1)[1]
                check_symlink(p, tgt)
                e = {"type": "symlink", "target": tgt, "sha256": sha256_bytes(tgt.encode()), "mode": "120000"}
            else:
                e = {"type": "file", "sha256": h, "mode": None}
            b = base.get(p)
            if b and b["sha256"] == e["sha256"] and b["type"] == e["type"]:
                continue
            delta[p] = dict(e, status="M" if b else "A")
        for p, b in base.items():
            if p in man:
                continue
            if b["type"] == "symlink" and snap.get("omits_symlinks"):
                notes.append(f"{p}: symlink -> {b['target']} kept from the base (the manifest format omits symlinks)")
                continue
            delta[p] = {"status": "D"}
        sources = []
        final = None
    else:
        raise Refused(f"{name}: unknown snapshot kind {kind!r}")
    for p, e in delta.items():
        if e.get("type") == "symlink":
            check_symlink(p, e["target"])
    return delta, sources, notes, final


def tree_id_of_state(state, tar):
    """Tree id of a tar's files without trusting the disk: extract into memory-backed scratch."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="flh-tid-") as tmp:
        with tarfile.open(tar) as tf:
            for m in tf.getmembers():
                p = member_path(m.name)
                if not p or p not in state:
                    continue
                full = os.path.join(tmp, p)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                if m.issym():
                    os.symlink(m.linkname, full)
                else:
                    with open(full, "wb") as fh:
                        fh.write(tf.extractfile(m).read())
                    os.chmod(full, 0o755 if m.mode & 0o111 else 0o644)
        return BI.tree_id(tmp, BI.scan(tmp))


def build_chain(lane, st, base_dir):
    """A hash-only store rebuilt from sealed patches: START (a sealed manifest of the base) and steps of
    {seal: {dir, sums?}, patch, expect}; each patch and manifest must be covered by its step's seal."""
    out = st["path"]
    start = st["start"]
    _, listed = verify_seal({"dir": start["seal"]["dir"], "sums": start["seal"].get("sums", "SHA256SUMS")})
    covered(listed, start["manifest"], "chain start manifest")
    files = [os.path.join(start["seal"]["dir"], start["manifest"])]
    steps = []
    for stp in st["steps"]:
        _, lst = verify_seal({"dir": stp["seal"]["dir"], "sums": stp["seal"].get("sums", "SHA256SUMS")})
        covered(lst, stp["patch"], "chain patch")
        covered(lst, stp["expect"], "chain manifest")
        steps.append((os.path.join(stp["seal"]["dir"], stp["patch"]), os.path.join(stp["seal"]["dir"], stp["expect"])))
    if not os.path.isdir(out):
        prev_dir, prev_man, made = base_dir, files[0], []
        for i, (patch, expect) in enumerate(steps):
            d = out if i == len(steps) - 1 else f"{out}.step{i + 1}"
            rebuild(prev_man, [prev_dir], d, expect, patch, mode_from=prev_dir)
            made.append(d)
            prev_dir, prev_man = d, expect
        for d in made[:-1]:
            shutil.rmtree(d)
    return {"kind": "dir", "label": st.get("label", f"{lane} rebuilt from sealed patches"), "path": out, "modes": True,
            "chain": [{"patch": sha256_file(p), "expect": sha256_file(e)} for p, e in steps]}


def select(selection_path, out_path):
    with open(selection_path) as fh:
        S = json.load(fh)
    if S.get("format") != SELECTION:
        raise Refused(f"selection format {S.get('format')!r}, expected {SELECTION}")
    base_dir = S["base"]["dir"]
    rows = BI.scan(base_dir)
    base_tid = BI.tree_id(base_dir, rows)
    if base_tid != S["base"]["tree_id"]:
        raise Refused(f"base {base_dir} has tree {base_tid[:12]}, the selection pins {S['base']['tree_id'][:12]}")
    base = scan_state(base_dir)
    lanes, order = {}, S["order"]
    if sorted(order) != sorted(S["lanes"]):
        raise Refused("order must name every lane exactly once")
    for name in order:
        cfg = S["lanes"][name]
        seal, listed = verify_seal(cfg["seal"])
        r = {"seal": dict(seal, dir=cfg["seal"]["dir"], id=cfg["seal"].get("id")),
             "supersedes": cfg.get("supersedes", [])}
        if cfg.get("base_manifest"):
            bm = read_hash_manifest(cfg["base_manifest"]["path"])
            if cfg["base_manifest"].get("sha256") and sha256_file(cfg["base_manifest"]["path"]) != cfg["base_manifest"]["sha256"]:
                raise Refused(f"{name}: base manifest changed")
            diffs = []
            for p in sorted(set(bm) | set(base)):
                b = base.get(p)
                h = bm.get(p)
                if b and b["type"] == "symlink" and (h is None or h == f"symlink:{b['target']}"):
                    continue
                if (b or {}).get("sha256") != h:
                    diffs.append(p)
            if diffs:
                raise Refused(f"{name}: its recorded base differs from the shared base on {len(diffs)} path(s): {diffs[:5]}")
            r["base"] = "equal to the shared base (base manifest checked)"
        else:
            r["base"] = cfg.get("base_note", "shared base (stated by the lane, no base manifest)")
        delta, sources, notes, _ = lane_state(name, cfg, base, listed)
        for st in cfg.get("stores", []):
            st = dict(st)
            if st["kind"] == "patch-chain":
                st = build_chain(name, st, base_dir)
            if st["kind"] == "tar":
                if st.get("sealed_by"):
                    sb_dir, sb_sums = st["sealed_by"]
                    sb = read_sums(os.path.join(sb_dir, sb_sums))
                    rel = os.path.normpath(os.path.relpath(st["path"], sb_dir))
                    if sb.get(rel) != sha256_file(st["path"]):
                        raise Refused(f"{name}: store {st['path']} is not covered by {sb_sums}")
                st["sha256"] = sha256_file(st["path"])
            sources.append(st)
        r.update({"delta": delta, "sources": sources, "notes": notes,
                  "counts": {s: sum(1 for e in delta.values() if e["status"] == s) for s in "AMD"}})
        lanes[name] = r
    claims = {}
    for name in order:
        for p in lanes[name]["delta"]:
            claims.setdefault(p, []).append(name)
    pend = []
    for prop in S.get("pending_proposals", []):
        hits = sorted(p for p in prop.get("paths", []) if p in claims)
        created = [p for p in prop.get("creates", []) if p in claims or p in base]
        if hits and prop.get("forbid_paths", False):
            raise Refused(f"pending proposal {prop['id']} touches {hits}, which a selected lane also supplies")
        if created:
            raise Refused(f"pending proposal {prop['id']}: {created} already present; it is not pending")
        if prop.get("patch"):
            prop = dict(prop, patch_sha256=sha256_file(prop["patch"]))
        pend.append(dict(prop, state="excluded from the candidate"))
    out = {"format": SELECTED, "selected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "selection_sha256": sha256_file(selection_path),
           "base": {"dir": base_dir, "tree_id": base_tid, "files": len(base)},
           "order": order, "lanes": lanes, "pending_proposals": pend,
           "shared_paths": {p: ls for p, ls in sorted(claims.items()) if len(ls) > 1},
           "expect": S.get("expect", {})}
    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return out


# --- byte sources ----------------------------------------------------------------------------------
class Sources:
    """Content-addressed reads. Every read is checked against the wanted SHA-256, and every source
    is checked for change while it is read."""

    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.tars = {}
        self.tar_index = {}
        self.dir_index = {}

    def _tar(self, src):
        path = src["path"]
        if path not in self.tars:
            if src.get("sha256") and sha256_file(path) != src["sha256"]:
                raise Refused(f"sealed tar {path} changed before copying")
            st = os.stat(path)
            tf = tarfile.open(path)
            idx = {}
            for m in tf.getmembers():
                if m.isfile():
                    idx[member_path(m.name)] = m
            self.tars[path] = (tf, (st.st_size, st.st_mtime_ns, st.st_ino), src.get("sha256"))
            self.tar_index[path] = idx
        return self.tars[path][0], self.tar_index[path]

    def read(self, lane, rel, want, sources, allow_worktree):
        """(bytes, provenance) for rel with SHA-256 `want`, or Refused."""
        tried = []
        for src in sources:
            k = src["kind"]
            if k == "tar":
                tf, idx = self._tar(src)
                m = idx.get(rel)
                if m is None:
                    tried.append(f"tar {os.path.basename(src['path'])}: absent")
                    continue
                data = tf.extractfile(m).read()
                if sha256_bytes(data) == want:
                    return data, f"tar:{os.path.basename(src['path'])}"
                tried.append(f"tar {os.path.basename(src['path'])}: different bytes")
            elif k in ("dir", "worktree"):
                if k == "worktree" and not allow_worktree:
                    continue
                full = os.path.join(src["path"], rel)
                if not os.path.isfile(full) or os.path.islink(full):
                    tried.append(f"{k} {src.get('label', '')}: absent")
                    continue
                data = read_stable(full)
                if sha256_bytes(data) == want:
                    return data, f"{k}:{src.get('label', os.path.basename(src['path']))}"
                tried.append(f"{k} {src.get('label', '')}: different bytes (now {sha256_bytes(data)[:12]})")
        raise Refused(f"{lane}: no source holds {rel} with sha256 {want[:12]} ({'; '.join(tried) or 'no source'})")

    def recheck(self):
        """A sealed tar must still be the file that was read: same identity and digest."""
        for path, (tf, ident, sha) in self.tars.items():
            st = os.stat(path)
            if (st.st_size, st.st_mtime_ns, st.st_ino) != ident or (sha and sha256_file(path) != sha):
                raise Refused(f"sealed tar {path} changed during copying")

    def close(self):
        for tf, _, _ in self.tars.values():
            tf.close()
        self.tars, self.tar_index = {}, {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_stable(full):
    """The file's bytes, refused if its size, mtime or inode moved during the read."""
    s1 = os.stat(full)
    with open(full, "rb") as fh:
        data = fh.read()
    s2 = os.stat(full)
    if (s1.st_size, s1.st_mtime_ns, s1.st_ino) != (s2.st_size, s2.st_mtime_ns, s2.st_ino) or len(data) != s2.st_size:
        raise Refused(f"{full} changed while it was read")
    return data


# --- catalogs ----------------------------------------------------------------------------------------
CAT_KEY = re.compile(r'^\s*"(?P<k>[A-Za-z0-9_.\-]+)":\s*"(?P<v>(?:[^"\\]|\\.)*)"', re.M | re.S)
CAT_KEYLINE = re.compile(r'^\s*"[A-Za-z0-9_.\-]+":', re.M)
PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_]+)\}")


def parse_catalog(text):
    """([(key, value)] in file order, problems)."""
    pairs = [(m["k"], m["v"]) for m in CAT_KEY.finditer(text)]
    problems = []
    if len(pairs) != len(CAT_KEYLINE.findall(text)):
        problems.append(f"{len(CAT_KEYLINE.findall(text))} key lines but {len(pairs)} parsed messages")
    seen = {}
    for k, _ in pairs:
        seen[k] = seen.get(k, 0) + 1
    dups = sorted(k for k, n in seen.items() if n > 1)
    if dups:
        problems.append(f"duplicate keys: {dups[:5]}{' …' if len(dups) > 5 else ''} ({len(dups)})")
    return pairs, problems


def catalog_report(tree):
    """Duplicates, key parity between en and zh-CN, and {placeholder} parity."""
    res, cats = {"problems": []}, {}
    for rel in CATALOGS:
        full = os.path.join(tree, rel)
        with open(full, encoding="utf-8") as fh:
            pairs, probs = parse_catalog(fh.read())
        cats[rel] = dict(pairs)
        res[rel] = {"keys": len(pairs), "sha256": sha256_file(full)}
        res["problems"] += [f"{rel}: {p}" for p in probs]
    en, zh = cats[CATALOGS[0]], cats[CATALOGS[1]]
    miss, extra = sorted(set(en) - set(zh)), sorted(set(zh) - set(en))
    if miss:
        res["problems"].append(f"zh-CN lacks {len(miss)} key(s): {miss[:5]}")
    if extra:
        res["problems"].append(f"zh-CN has {len(extra)} key(s) en lacks: {extra[:5]}")
    ph = sorted(k for k in set(en) & set(zh)
                if sorted(PLACEHOLDER.findall(en[k])) != sorted(PLACEHOLDER.findall(zh[k])))
    if ph:
        res["problems"].append(f"{len(ph)} key(s) with different placeholders: {ph[:5]}")
    res["ok"] = not res["problems"]
    return res


def key_changes(base_text, lane_text):
    """{key: new value or None (removed)} for every key the lane added, changed or removed."""
    b, _ = parse_catalog(base_text)
    l, _ = parse_catalog(lane_text)
    b, l = dict(b), dict(l)
    ch = {k: v for k, v in l.items() if b.get(k) != v}
    ch.update({k: None for k in b if k not in l})
    return ch


def lost_keys(base_text, lane_text, merged_text):
    m, _ = parse_catalog(merged_text)
    m = dict(m)
    lost = []
    for k, v in key_changes(base_text, lane_text).items():
        if v is None and k in m:
            lost.append(f"{k} (removed by the lane, present after the merge)")
        elif v is not None and m.get(k) != v:
            lost.append(f"{k} ({'missing' if k not in m else 'value differs'} after the merge)")
    return lost


# --- assemble ---------------------------------------------------------------------------------------
def write_entry(root, rel, entry, data):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full) or root, exist_ok=True)
    if os.path.lexists(full):
        os.unlink(full)
    if entry["type"] == "symlink":
        os.symlink(entry["target"], full)
        return
    with open(full, "wb") as fh:
        fh.write(data)
    os.chmod(full, 0o755 if entry["mode"] == "100755" else 0o644)


def resolve_mode(lane, rel, entry, base, sources, notes):
    """Manifest-only lanes carry no modes: the base mode for a modified file, else a mode source."""
    if entry.get("mode"):
        return entry["mode"]
    if rel in base and base[rel]["type"] == "file":
        return base[rel]["mode"]
    for src in sources:
        if src["kind"] in ("dir", "worktree") and src.get("modes"):
            full = os.path.join(src["path"], rel)
            if os.path.isfile(full):
                m = "100755" if os.stat(full).st_mode & 0o111 else "100644"
                notes.append(f"{rel}: mode {m} from {src['kind']} {src.get('label', '')} (the manifest has no modes)")
                return m
    notes.append(f"{rel}: mode 100644 assumed (no mode source)")
    return "100644"


def assemble(selected_path, out, work=None, allow_worktree=None, hook=None):
    with open(selected_path) as fh:
        S = json.load(fh)
    if S.get("format") != SELECTED:
        raise Refused(f"not a {SELECTED} file")
    out = os.path.realpath(out)
    if os.path.exists(out):
        raise Refused(f"{out} exists")
    work = work or out + ".work"
    if os.path.exists(work):
        raise Refused(f"{work} exists")
    base_dir = S["base"]["dir"]
    base = scan_state(base_dir)
    if BI.tree_id(base_dir, BI.scan(base_dir)) != S["base"]["tree_id"]:
        raise Refused("the base changed after selection")
    os.makedirs(work)
    os.makedirs(out)
    for p, e in base.items():                       # exactly the base tree's files, nothing generated
        data = None
        if e["type"] == "file":
            data = read_stable(os.path.join(base_dir, p))
            if sha256_bytes(data) != e["sha256"]:
                raise Refused(f"base file {p} changed while copying")
        write_entry(out, p, e, data)
    with Sources(base_dir) as srcs:
        return _assemble(S, selected_path, out, work, base_dir, base, srcs, allow_worktree, hook)


def _assemble(S, selected_path, out, work, base_dir, base, srcs, allow_worktree, hook):
    order = S["order"]
    claims = {}
    for lane in order:
        for p, e in S["lanes"][lane]["delta"].items():
            claims.setdefault(p, []).append(lane)
    prov, merges, notes, plan = {}, {}, [], {}
    for p in sorted(claims):
        lanes = claims[p]
        ents = [(ln, S["lanes"][ln]["delta"][p]) for ln in lanes]
        if len(lanes) == 1:
            ln, e = ents[0]
            if e["status"] == "D":
                os.unlink(os.path.join(out, p))
                prov[p] = {"lane": ln, "status": "D"}
                plan[p] = None
                continue
            allow = (allow_worktree if allow_worktree is not None
                     else S["lanes"][ln].get("allow_worktree", False))
            if e["type"] == "symlink":
                data, how = None, "symlink"
            else:
                data, how = srcs.read(ln, p, e["sha256"], S["lanes"][ln]["sources"], allow)
            ent = dict(e, mode=resolve_mode(ln, p, e, base, S["lanes"][ln]["sources"], notes))
            write_entry(out, p, ent, data)
            prov[p] = {"lane": ln, "status": e["status"], "sha256": e["sha256"], "mode": ent["mode"], "from": how}
            plan[p] = ent
            if hook:
                hook(p)
            continue
        if any(e["status"] == "D" for _, e in ents):
            raise Refused(f"{p}: deleted by one lane and changed by another: {lanes}")
        if any(e["type"] != "file" for _, e in ents) or p not in base or base[p]["type"] != "file":
            raise Refused(f"{p}: changed by {lanes} but not a text file present in the base; merge by hand")
        tag = p.replace("/", "__")
        base_file = os.path.join(base_dir, p)
        cur = os.path.join(work, tag + ".base")
        shutil.copyfile(base_file, cur)
        steps, texts = [], {}
        for ln, e in ents:
            allow = (allow_worktree if allow_worktree is not None
                     else S["lanes"][ln].get("allow_worktree", False))
            data, how = srcs.read(ln, p, e["sha256"], S["lanes"][ln]["sources"], allow)
            texts[ln] = data
            theirs = os.path.join(work, f"{tag}.{ln}")
            with open(theirs, "wb") as fh:
                fh.write(data)
            r = subprocess.run(["diff3", "-m", theirs, base_file, cur], capture_output=True)
            nxt = os.path.join(work, f"{tag}.after-{ln}")
            with open(nxt, "wb") as fh:
                fh.write(r.stdout)
            steps.append({"lane": ln, "from": how, "diff3_exit": r.returncode,
                          "conflict_blocks": r.stdout.count(b"\n<<<<<<< ") + r.stdout.startswith(b"<<<<<<< ")})
            if r.returncode != 0:
                raise Refused(f"{p}: diff3 conflict while merging {ln} (kept {nxt})")
            cur = nxt
        with open(cur, "rb") as fh:
            merged = fh.read()
        with open(base_file, "rb") as fh:
            base_bytes = fh.read()
        base_lines = set(base_bytes.splitlines())
        mset = set(merged.splitlines())
        lost = {}
        for ln, data in texts.items():
            miss = [x for x in data.splitlines() if x not in base_lines and x not in mset]
            if miss:
                lost[ln] = len(miss)
        keys_lost = {}
        if p in CATALOGS:
            for ln, data in texts.items():
                kl = lost_keys(base_bytes.decode(), data.decode(), merged.decode())
                if kl:
                    keys_lost[ln] = kl
        if lost or keys_lost:
            raise Refused(f"{p}: the merge reports success but drops lane changes: lines {lost}, keys {keys_lost}")
        mode = base[p]["mode"]
        ent = {"type": "file", "sha256": sha256_bytes(merged), "mode": mode}
        write_entry(out, p, ent, merged)
        merges[p] = {"lanes": lanes, "steps": steps, "base_sha256": base[p]["sha256"], "merged_sha256": ent["sha256"],
                     "lost_lines": {}, "lost_keys": {}, "result": "CLEAN"}
        prov[p] = {"lane": "+".join(lanes), "status": "merged", "sha256": ent["sha256"], "mode": mode}
        plan[p] = ent
    srcs.recheck()
    for ln in order:                                # a lane re-sealed during copying is refused as well
        seal = S["lanes"][ln]["seal"]
        if sha256_file(os.path.join(seal["dir"], seal["sums"])) != seal["digest"]:
            raise Refused(f"{ln}: its seal changed during copying")
    # final pass: every planned path, and every untouched base path, holds what the plan says
    final = scan_state(out)
    wrong = []
    for p, ent in plan.items():
        got = final.get(p)
        if ent is None:
            if got is not None:
                wrong.append(f"{p}: should be deleted")
        elif got is None or got["sha256"] != ent["sha256"] or (ent["type"] == "file" and got["mode"] != ent["mode"]):
            wrong.append(f"{p}: differs from the plan")
    for p, b in base.items():
        if p not in plan and final.get(p) != b:
            wrong.append(f"{p}: base file changed during assembly")
    extra = sorted(set(final) - set(base) - set(plan))
    wrong += [f"{p}: unplanned file" for p in extra]
    if wrong:
        raise Refused("final verification failed: " + "; ".join(wrong[:8]))
    rows = BI.scan(out)
    ident = {"tree_id": BI.tree_id(out, rows), "files": len(rows), "content_sha256": BI.content_digest(rows)}
    cat = catalog_report(out) if all(os.path.isfile(os.path.join(out, c)) for c in CATALOGS) else None
    rec = {"format": ASSEMBLY, "assembled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "selected_sha256": sha256_file(selected_path), "base_tree_id": S["base"]["tree_id"],
           "order": order, "tree": ident, "merges": merges, "catalogs": cat,
           "lanes": {ln: {"seal_id": S["lanes"][ln]["seal"].get("id"), "seal_digest": S["lanes"][ln]["seal"]["digest"],
                          "counts": S["lanes"][ln]["counts"],
                          "from": sorted({v.get("from", "") for v in prov.values() if v.get("lane") == ln})}
                     for ln in order},
           "provenance": prov, "notes": notes}
    exp = S.get("expect", {})
    if exp.get("tree_id") and exp["tree_id"] != ident["tree_id"]:
        rec["expect_mismatch"] = f"tree {ident['tree_id']} != expected {exp['tree_id']}"
    with open(os.path.join(os.path.dirname(out), os.path.basename(out) + ".assembly.json"), "w") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")
    shutil.rmtree(work)
    if cat and not cat["ok"]:
        raise Refused("catalog check failed: " + "; ".join(cat["problems"]))
    return rec


# --- rebuild a manifest-only lane from sealed bytes -------------------------------------------------
def index_sources(paths):
    """{sha256: (kind, path, member)} over directories (their tree files) and tars (their files)."""
    idx = {}
    for src in paths:
        if os.path.isdir(src):
            for p, (mode, h) in BI.scan(src).items():
                if mode != "120000":
                    idx.setdefault(h, ("dir", src, p))
        else:
            with tarfile.open(src) as tf:
                for m in tf.getmembers():
                    if m.isfile():
                        idx.setdefault(sha256_bytes(tf.extractfile(m).read()), ("tar", src, m.name))
    return idx


def fetch(idx, h):
    kind, src, member = idx[h]
    if kind == "dir":
        data = read_stable(os.path.join(src, member))
    else:
        with tarfile.open(src) as tf:
            data = tf.extractfile(member).read()
    if sha256_bytes(data) != h:
        raise Refused(f"{src}:{member} changed while it was read")
    return data


def rebuild(start_manifest, sources, out, expect_manifest, patch=None, mode_from=None):
    """OUT = the files of START_MANIFEST taken by hash from SOURCES, then PATCH applied (patch -p1),
    verified path by path against EXPECT_MANIFEST. Modes come from MODE_FROM (a tree) where it has
    the path, else 100644; the result is a hash-only store, never trusted without its manifest."""
    if os.path.exists(out):
        raise Refused(f"{out} exists")
    start = read_hash_manifest(start_manifest)
    expect = read_hash_manifest(expect_manifest)
    idx = index_sources(sources)
    missing = sorted(p for p, h in start.items() if not h.startswith("symlink:") and h not in idx)
    if missing:
        raise Refused(f"no source holds {len(missing)} start file(s): {missing[:5]}")
    os.makedirs(out)
    for p, h in start.items():
        if h.startswith("symlink:"):
            continue
        mode = "100644"
        if mode_from and os.path.isfile(os.path.join(mode_from, p)):
            mode = "100755" if os.stat(os.path.join(mode_from, p)).st_mode & 0o111 else "100644"
        write_entry(out, p, {"type": "file", "mode": mode}, fetch(idx, h))
    applied = None
    if patch:
        r = subprocess.run(["patch", "-p1", "--batch", "--forward", "--no-backup-if-mismatch", "-s", "-d", out, "-i",
                            os.path.realpath(patch)], capture_output=True, text=True)
        if r.returncode != 0:
            raise Refused(f"patch {os.path.basename(patch)} does not apply: {(r.stdout + r.stderr).strip()[:300]}")
        applied = sha256_file(patch)
    got = {p: h for p, (m, h) in BI.scan(out).items()}
    wrong = sorted(p for p, h in expect.items() if not h.startswith("symlink:") and got.get(p) != h)
    extra = sorted(p for p in got if p not in expect)
    if wrong or extra:
        raise Refused(f"rebuilt tree differs from {os.path.basename(expect_manifest)}: {len(wrong)} wrong {wrong[:5]}, "
                      f"{len(extra)} extra {extra[:5]}")
    return {"files": len(got), "start": sha256_file(start_manifest), "expect": sha256_file(expect_manifest),
            "patch": applied, "verified": len([h for h in expect.values() if not h.startswith("symlink:")])}


# --- verify: every lane's intended change holds in a tree (the candidate, or the owner's merge) --------
def verify(selected_path, tree, sources_ok=True):
    """Per lane and path: a path only this lane changes must be byte-identical (and same mode or link);
    a shared path must keep every line and catalog key change of each lane. Lane bytes for shared paths
    are read through the selected sources (hash-checked)."""
    with open(selected_path) as fh:
        S = json.load(fh)
    base_dir = S["base"]["dir"]
    got = scan_state(tree)
    claims = {}
    for ln in S["order"]:
        for p in S["lanes"][ln]["delta"]:
            claims.setdefault(p, []).append(ln)
    srcs = Sources(base_dir)
    try:
        return _verify(S, tree, base_dir, got, claims, srcs)
    finally:
        srcs.close()


def _verify(S, tree, base_dir, got, claims, srcs):
    rows, bad = [], []
    for p in sorted(claims):
        for ln in claims[p]:
            e = S["lanes"][ln]["delta"][p]
            g = got.get(p)
            if e["status"] == "D":
                ok, why = g is None, "deleted" if g is None else "still present"
            elif len(claims[p]) == 1:
                ok = g is not None and g["sha256"] == e["sha256"] and (e.get("mode") is None or g["mode"] == e["mode"]) \
                    and g["type"] == e["type"]
                why = "identical" if ok else ("absent" if g is None else "different bytes, mode or type")
            else:
                data, _ = srcs.read(ln, p, e["sha256"], S["lanes"][ln]["sources"], S["lanes"][ln].get("allow_worktree", False))
                with open(os.path.join(base_dir, p), "rb") as fh:
                    base_bytes = fh.read()
                with open(os.path.join(tree, p), "rb") as fh:
                    merged = fh.read()
                mset, bset = set(merged.splitlines()), set(base_bytes.splitlines())
                lost = [x for x in data.splitlines() if x not in bset and x not in mset]
                kl = lost_keys(base_bytes.decode(), data.decode(), merged.decode()) if p in CATALOGS else []
                ok = not lost and not kl
                why = "every changed line and key kept" if ok else f"{len(lost)} line(s), {len(kl)} key(s) lost"
            rows.append({"lane": ln, "path": p, "ok": ok, "why": why})
            if not ok:
                bad.append(f"{ln}: {p}: {why}")
    srcs.recheck()
    extra = sorted(p for p in got if p not in claims and S["base"].get("dir") and
                   not os.path.lexists(os.path.join(base_dir, p)))
    per_lane = {ln: {"paths": sum(1 for r in rows if r["lane"] == ln), "kept": sum(1 for r in rows if r["lane"] == ln and r["ok"])}
                for ln in S["order"]}
    return {"tree": BI.tree_id(tree, BI.scan(tree)), "per_lane": per_lane, "failures": bad,
            "unclaimed_new_paths": extra, "ok": not bad}


# --- per-lane trees and one-command reproduction ----------------------------------------------------
def lane_tree_id(selected_path, lane):
    """Tree id of the shared base plus one lane's changes alone (bytes from the selected sources)."""
    import tempfile
    with open(selected_path) as fh:
        S = json.load(fh)
    L = S["lanes"][lane]
    base_dir = S["base"]["dir"]
    srcs = Sources(base_dir)
    base = scan_state(base_dir)
    with tempfile.TemporaryDirectory(prefix="flh-lane-") as tmp, srcs:
        for p, e in base.items():
            if p in L["delta"]:
                continue
            write_entry(tmp, p, e, None if e["type"] == "symlink" else read_stable(os.path.join(base_dir, p)))
        notes = []
        for p, e in L["delta"].items():
            if e["status"] == "D":
                continue
            data = None if e["type"] == "symlink" else srcs.read(lane, p, e["sha256"], L["sources"], L.get("allow_worktree", False))[0]
            write_entry(tmp, p, dict(e, mode=resolve_mode(lane, p, e, base, L["sources"], notes)), data)
        srcs.recheck()
        return BI.tree_id(tmp, BI.scan(tmp))


def reproduce(selection_path, expect=None, keep=None):
    """select + assemble in a fresh scratch directory; compare the tree id with EXPECT."""
    import tempfile
    if keep:
        os.makedirs(keep, exist_ok=True)
        if os.listdir(keep):
            raise Refused(f"--keep {keep} must be new or empty")
    work = keep or tempfile.mkdtemp(prefix="flh-repro-")
    sel = os.path.join(work, "selected.json")
    select(selection_path, sel)
    rec = assemble(sel, os.path.join(work, "tree"))
    tid = rec["tree"]["tree_id"]
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    if expect and tid != expect:
        raise Refused(f"reproduced tree {tid}, expected {expect}")
    return {"tree_id": tid, "files": rec["tree"]["files"], "expected": expect, "equal": (tid == expect) if expect else None,
            "kept": work if keep else None}


# --- review slices: the tree after each lane in order, and what each lane adds that others use ---------
def slices(selected_path, work):
    """Assemble base + the first k lanes for every k (in the selected order) and report each state's tree id,
    the migrations and scripts each lane adds, and which other lanes' changed files name them (so omitting
    that lane breaks them)."""
    with open(selected_path) as fh:
        S = json.load(fh)
    os.makedirs(work, exist_ok=False)
    order, out = S["order"], {"states": [], "lanes": {}}
    for k in range(1, len(order) + 1):
        sub = dict(S, order=order[:k], lanes={ln: S["lanes"][ln] for ln in order[:k]},
                   shared_paths={p: [x for x in ls if x in order[:k]] for p, ls in S["shared_paths"].items()})
        sp = os.path.join(work, f"selected-{k}.json")
        with open(sp, "w") as fh:
            json.dump(sub, fh)
        rec = assemble(sp, os.path.join(work, f"state-{k}"))
        out["states"].append({"after": order[k - 1], "lanes": order[:k], "tree_id": rec["tree"]["tree_id"],
                              "files": rec["tree"]["files"], "tree_dir": os.path.join(work, f"state-{k}")})
    for ln in order:
        added = sorted(p for p, e in S["lanes"][ln]["delta"].items() if e["status"] == "A")
        tools = [p for p in added if p.startswith(("migrations/", "scripts/", "tools/", "cmd/", ".github/", "deploy/"))
                 and not p.endswith((".md", ".json", ".txt")) or p.startswith("migrations/")]
        used = {}
        for other in order:
            if other == ln:
                continue
            for q, e in S["lanes"][other]["delta"].items():
                if e["status"] == "D" or e.get("type") != "file":
                    continue
                with Sources(S["base"]["dir"]) as srcs:         # the other lane's OWN bytes, not a merged file
                    text = srcs.read(other, q, e["sha256"], S["lanes"][other]["sources"],
                                     S["lanes"][other].get("allow_worktree", False))[0].decode("utf-8", "replace")
                for t in tools:
                    if t in text:
                        used.setdefault(t, set()).add(f"{other}:{q}")
        out["lanes"][ln] = {"adds": len(added), "migrations": [p for p in added if p.startswith("migrations/")],
                            "scripts_and_tools": len(tools),
                            "used_by_other_lanes": {t: sorted(v) for t, v in sorted(used.items())}}
    return out


# --- compare ----------------------------------------------------------------------------------------
def compare(old, new, selected=None):
    a, b = scan_state(old), scan_state(new)
    owner = {}
    if selected:
        with open(selected) as fh:
            S = json.load(fh)
        for ln in S["order"]:
            for p in S["lanes"][ln]["delta"]:
                owner[p] = owner.get(p, "") + ("+" if p in owner else "") + ln
    rows = []
    for p in sorted(set(a) | set(b)):
        if a.get(p) == b.get(p):
            continue
        st = "added" if p not in a else "removed" if p not in b else "changed"
        if st == "changed" and a[p]["sha256"] == b[p]["sha256"]:
            st = "mode"
        rows.append({"path": p, "change": st, "lane": owner.get(p, "(not in the selection)")})
    return {"old": BI.tree_id(old, BI.scan(old)), "new": BI.tree_id(new, BI.scan(new)), "differences": rows,
            "by_lane": {ln: sum(1 for r in rows if r["lane"] == ln) for ln in sorted({r["lane"] for r in rows})}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("selection")
    s.add_argument("--out", required=True)
    a = sub.add_parser("assemble")
    a.add_argument("selected")
    a.add_argument("--out", required=True)
    a.add_argument("--work")
    c = sub.add_parser("catalogs")
    c.add_argument("tree")
    c.add_argument("--base")
    c.add_argument("--lane", action="append", default=[], help="LABEL=DIR holding web/src/i18n")
    m = sub.add_parser("compare")
    m.add_argument("old")
    m.add_argument("new")
    m.add_argument("--selected")
    v = sub.add_parser("verify")
    v.add_argument("selected")
    v.add_argument("tree")
    sl = sub.add_parser("slices")
    sl.add_argument("selected")
    sl.add_argument("--work", required=True)
    lt = sub.add_parser("lane-tree")
    lt.add_argument("selected")
    lt.add_argument("lane")
    rp = sub.add_parser("reproduce")
    rp.add_argument("selection")
    rp.add_argument("--expect")
    rp.add_argument("--keep", help="keep the scratch directory here (new)")
    t = sub.add_parser("tree-id")
    t.add_argument("tree")
    rb = sub.add_parser("rebuild")
    rb.add_argument("--manifest", required=True, help="the start state (sha256  path)")
    rb.add_argument("--from", dest="sources", action="append", required=True, help="a directory or tar to take bytes from")
    rb.add_argument("--patch")
    rb.add_argument("--modes-from")
    rb.add_argument("--expect", required=True, help="the sealed final manifest")
    rb.add_argument("--out", required=True)
    o = ap.parse_args(argv)
    try:
        if o.cmd == "select":
            S = select(o.selection, o.out)
            for ln in S["order"]:
                L = S["lanes"][ln]
                c_ = L["counts"]
                print(f"{ln:<13} seal {L['seal'].get('id') or ''} OK ({L['seal']['files']} files, {L['seal']['digest'][:16]}); "
                      f"{L['base']}; changes A {c_['A']} M {c_['M']} D {c_['D']}")
                for n in L["notes"]:
                    print(f"    note: {n}")
            print(f"shared paths: {len(S['shared_paths'])}")
            for p, ls in S["shared_paths"].items():
                print(f"    {p}: {' + '.join(ls)}")
            for pp in S["pending_proposals"]:
                print(f"pending proposal {pp['id']}: {pp['state']}")
        elif o.cmd == "assemble":
            r = assemble(o.selected, o.out, o.work)
            for p, mm in r["merges"].items():
                print(f"merge {p}: {' + '.join(mm['lanes'])}: {mm['result']}")
            if r["catalogs"]:
                print(f"catalogs: en {r['catalogs'][CATALOGS[0]]['keys']} keys, zh-CN {r['catalogs'][CATALOGS[1]]['keys']} keys, "
                      f"{'OK' if r['catalogs']['ok'] else 'PROBLEMS'}")
            print(f"tree {r['tree']['tree_id']} ({r['tree']['files']} files, content {r['tree']['content_sha256'][:16]})")
            if r.get("expect_mismatch"):
                print(f"NOTE: {r['expect_mismatch']}")
        elif o.cmd == "catalogs":
            r = catalog_report(o.tree)
            if o.base:
                merged = {c_: open(os.path.join(o.tree, c_), encoding="utf-8").read() for c_ in CATALOGS}
                for spec in o.lane:
                    label, d = spec.split("=", 1)
                    for c_ in CATALOGS:
                        bt = open(os.path.join(o.base, c_), encoding="utf-8").read()
                        lt = open(os.path.join(d, c_), encoding="utf-8").read()
                        kl = lost_keys(bt, lt, merged[c_])
                        n = len(key_changes(bt, lt))
                        r.setdefault("lanes", {}).setdefault(label, {})[c_] = {"changed_keys": n, "lost": kl}
                        if kl:
                            r["problems"].append(f"{label} {c_}: {len(kl)} key change(s) lost: {kl[:3]}")
                r["ok"] = not r["problems"]
            print(json.dumps(r, indent=1, sort_keys=True))
            return 0 if r["ok"] else 1
        elif o.cmd == "compare":
            print(json.dumps(compare(o.old, o.new, o.selected), indent=1, sort_keys=True))
        elif o.cmd == "verify":
            r = verify(o.selected, o.tree)
            print(json.dumps(r, indent=1, sort_keys=True))
            return 0 if r["ok"] else 1
        elif o.cmd == "slices":
            print(json.dumps(slices(o.selected, o.work), indent=1, sort_keys=True))
        elif o.cmd == "lane-tree":
            print(lane_tree_id(o.selected, o.lane))
        elif o.cmd == "reproduce":
            r = reproduce(o.selection, o.expect, o.keep)
            print(json.dumps(r, sort_keys=True))
        elif o.cmd == "rebuild":
            print(json.dumps(rebuild(o.manifest, o.sources, o.out, o.expect, o.patch, o.modes_from), sort_keys=True))
        elif o.cmd == "tree-id":
            rows = BI.scan(o.tree)
            print(json.dumps({"tree_id": BI.tree_id(o.tree, rows), "files": len(rows),
                              "content_sha256": BI.content_digest(rows)}))
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
        print(f"integration_candidate: error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
