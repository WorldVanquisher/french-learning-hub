#!/usr/bin/env python3
"""Audit release outputs, and make a small shareable evidence subset, without echoing what was found.

  evidence_share.py audit PATH... [--json]                # directories and tar files; exit 1 on a finding
  evidence_share.py share SRC_DIR --out DIR --include GLOB... [--seal-of SEAL_DIR]
  evidence_share.py verify-seal DIR                        # sha256sum -c SHA256SUMS, refused for a redacted copy

audit reads every file (tar members too, gzip included) and reports, per file, the classes it holds:
  private-address  RFC 1918, CGNAT 100.64.0.0/10 (tailnet) addresses, *.ts.net names, *.internal hosts
  session-link     claude.ai links and presigned URLs
  home-path        /home/<user> or /Users/<user> paths
  email            e-mail addresses
  aws-identity     12-digit account IDs inside ARNs, access key IDs (AKIA/ASIA)
  private-key      PEM private keys
  env-file         a file named .env or *.env with KEY=VALUE lines
  database         an SQLite database (can hold learner records)
Values are never printed: each finding is a class, a count and the first 12 hex digits of the SHA-256
of the matched value (to tell repeats apart).

share copies only the files matching --include from SRC_DIR into DIR (text files are passed through
redact.py; a database, key or env file is refused), and writes beside them:
  REDACTIONS.json      per file: the original and redacted SHA-256 and replacements per class, no values
  SHA256SUMS.redacted  the digests of the shared files
  REDACTED-COPY.json   {"format": "flh-redacted-evidence/v1", "original_seal": ...}: this is NOT the seal
It never writes a file named SHA256SUMS, so a shared subset cannot pass as the original seal, and
verify-seal refuses any directory holding REDACTED-COPY.json or SHA256SUMS.redacted.
Standard library only; nothing leaves the machine.
"""
import argparse
import fnmatch
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import redact as R  # noqa: E402

CLASSES = {
    "private-address": [re.compile(rb"\b(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
                                   rb"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})\b"),
                        re.compile(rb"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.ts\.net\b", re.I),
                        re.compile(rb"\b[a-z0-9-]+\.(?:ec2|compute)\.internal\b", re.I)],
    "session-link": [re.compile(rb"https://claude\.ai/\S+"), re.compile(rb"https://\S*X-Amz-(?:Signature|Credential)\S*")],
    "home-path": [re.compile(rb"/(?:home|Users)/[A-Za-z0-9._-]+(?=/|\s|$)")],
    "email": [re.compile(rb"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")],
    "aws-identity": [re.compile(rb"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:[0-9]{12}:"), re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")],
    "private-key": [re.compile(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")],
}
EXAMPLE_EMAIL = re.compile(rb"@(?:example\.(?:com|org|net)|users\.noreply\.github\.com)\b")


def classify(name, data):
    found = {}
    if data[:16] == b"SQLite format 3\x00":
        return {"database": [("sqlite", 1)]}
    base = os.path.basename(name)
    if (base == ".env" or base.endswith(".env")) and re.search(rb"(?m)^[A-Z_][A-Z0-9_]*=", data):
        found["env-file"] = [("env", 1)]
    for cls, rxs in CLASSES.items():
        vals = {}
        for rx in rxs:
            for m in rx.finditer(data):
                v = m.group(0)
                if cls == "email" and EXAMPLE_EMAIL.search(v):
                    continue
                h = hashlib.sha256(v).hexdigest()[:12]
                vals[h] = vals.get(h, 0) + 1
        if vals:
            found[cls] = sorted(vals.items())
    return found


def walk(path):
    """(display name, bytes) for every file under a directory or inside a tar (members of gzip tars too)."""
    if os.path.isdir(path):
        for dp, dns, fns in os.walk(path):
            dns.sort()
            for f in sorted(fns):
                full = os.path.join(dp, f)
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                if f.endswith((".tar", ".tar.gz", ".tgz")):
                    yield from walk(full)
                    continue
                with open(full, "rb") as fh:
                    yield os.path.relpath(full, path), fh.read()
    elif tarfile.is_tarfile(path):
        with tarfile.open(path) as tf:
            for m in tf.getmembers():
                if m.isfile():
                    data = tf.extractfile(m).read()
                    if m.name.endswith(".tar") and tarfile.is_tarfile(io.BytesIO(data)):
                        continue                                    # an image layer tar: scanned by its own audit
                    yield f"{os.path.basename(path)}:{m.name}", data
    else:
        with open(path, "rb") as fh:
            data = fh.read()
        if path.endswith(".gz"):
            data = gzip.decompress(data)
        yield os.path.basename(path), data


def audit(paths):
    rows = []
    for p in paths:
        for name, data in walk(p):
            f = classify(name, data)
            if f:
                rows.append({"file": name, "root": os.path.basename(os.path.normpath(p)),
                             "classes": {c: {"count": sum(n for _, n in v), "values": [h for h, _ in v]} for c, v in f.items()}})
    totals = {}
    for r in rows:
        for c, v in r["classes"].items():
            totals[c] = totals.get(c, 0) + v["count"]
    return {"files_with_findings": len(rows), "totals": totals, "rows": rows}


def share(src, out, includes, seal_of=None):
    if os.path.exists(out):
        raise SystemExit(f"refused: {out} exists")
    picked = []
    for dp, _, fns in os.walk(src):
        for f in sorted(fns):
            rel = os.path.relpath(os.path.join(dp, f), src)
            if any(fnmatch.fnmatch(rel, g) for g in includes):
                picked.append(rel)
    if not picked:
        raise SystemExit("refused: --include matched nothing")
    os.makedirs(out)
    manifest, sums = [], []
    for rel in sorted(picked):
        with open(os.path.join(src, rel), "rb") as fh:
            data = fh.read()
        f = classify(rel, data)
        if {"database", "private-key", "env-file"} & set(f):
            raise SystemExit(f"refused: {rel} is a {', '.join(sorted({'database', 'private-key', 'env-file'} & set(f)))}; never shared")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise SystemExit(f"refused: {rel} is not text; share only text evidence")
        per = {}
        for cls, rxs in CLASSES.items():
            n = sum(len(rx.findall(data)) for rx in rxs)
            if n:
                per[cls] = n
        red, count = R.redact(text)
        left = classify(rel, red.encode())
        if set(left) & {"private-address", "session-link", "home-path", "aws-identity"}:
            raise SystemExit(f"refused: {rel} still holds {sorted(left)} after redaction; remove it from --include")
        dst = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(red)
        rs = hashlib.sha256(red.encode()).hexdigest()
        manifest.append({"file": rel, "original_sha256": hashlib.sha256(data).hexdigest(), "shared_sha256": rs,
                         "replacements": count, "classes_found": per})
        sums.append(f"{rs}  {rel}")
    with open(os.path.join(out, "REDACTIONS.json"), "w") as fh:
        json.dump({"format": "flh-redaction-manifest/v1", "files": manifest,
                   "note": "counts and digests only; no removed value is recorded"}, fh, indent=1, sort_keys=True)
    with open(os.path.join(out, "SHA256SUMS.redacted"), "w") as fh:
        fh.write("\n".join(sums) + "\n")
    orig = None
    if seal_of and os.path.isfile(os.path.join(seal_of, "SHA256SUMS")):
        with open(os.path.join(seal_of, "SHA256SUMS"), "rb") as fh:
            orig = {"name": os.path.basename(os.path.normpath(seal_of)), "sha256sums_digest": hashlib.sha256(fh.read()).hexdigest()}
    with open(os.path.join(out, "REDACTED-COPY.json"), "w") as fh:
        json.dump({"format": "flh-redacted-evidence/v1", "original_seal": orig, "files": len(manifest),
                   "statement": "a redacted subset for sharing; it is not, and cannot verify as, the original seal"},
                  fh, indent=1, sort_keys=True)
    return manifest


def verify_seal(d):
    for marker in ("REDACTED-COPY.json", "SHA256SUMS.redacted"):
        if os.path.exists(os.path.join(d, marker)):
            raise SystemExit(f"refused: {d} is a redacted copy ({marker}); verify the original seal instead")
    sums = os.path.join(d, "SHA256SUMS")
    if not os.path.isfile(sums):
        raise SystemExit(f"refused: {d} has no SHA256SUMS")
    bad = 0
    with open(sums) as fh:
        for line in fh:
            if not line.strip():
                continue
            h, rel = line.rstrip("\n").split("  ", 1)
            p = os.path.join(d, rel)
            with open(p, "rb") as g:
                if hashlib.sha256(g.read()).hexdigest() != h:
                    bad += 1
                    print(f"FAILED {rel}")
    print(f"{'OK' if not bad else 'FAILED'}: {sums}")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit")
    a.add_argument("paths", nargs="+")
    a.add_argument("--json", action="store_true")
    s = sub.add_parser("share")
    s.add_argument("src")
    s.add_argument("--out", required=True)
    s.add_argument("--include", action="append", required=True)
    s.add_argument("--seal-of")
    v = sub.add_parser("verify-seal")
    v.add_argument("dir")
    o = ap.parse_args()
    if o.cmd == "audit":
        r = audit(o.paths)
        if o.json:
            print(json.dumps(r, indent=1, sort_keys=True))
        else:
            for row in r["rows"]:
                print(f"{row['file']}: " + "; ".join(f"{c} x{v['count']} [{', '.join(v['values'][:3])}]" for c, v in sorted(row["classes"].items())))
            print(f"{r['files_with_findings']} file(s) with findings; totals: {json.dumps(r['totals'], sort_keys=True)}")
        return 1 if r["rows"] else 0
    if o.cmd == "share":
        m = share(o.src, o.out, o.include, o.seal_of)
        print(f"shared {len(m)} file(s) into {o.out}: {sum(x['replacements'] for x in m)} replacement(s); see REDACTIONS.json")
        return 0
    return verify_seal(o.dir)


if __name__ == "__main__":
    sys.exit(main())
