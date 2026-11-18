#!/usr/bin/env python3
"""Fill the staging IAM policy templates for the administrator (locally, never committed).

  render_policies.py --account 123456789012 --ami ami-0123456789abcdef0 --out DIR [--region us-east-1]

Reads out/flh-stg-*-policy.json (the generator's reviewed output), substitutes
__AWS_ACCOUNT_ID__ and __STAGING_AMI_ID__, and writes DIR/<policy name>.json
(mode 0600). Refuses: an output directory inside the repository (the files
hold the account ID), an existing non-empty DIR, a malformed account or AMI ID,
a region other than the one the templates name, any placeholder left after
substitution, invalid JSON, duplicate Sids and a policy over IAM's 6,144
non-whitespace character limit. Prints names and sizes only.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.realpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
NAMES = {
    "flh-stg-host-boundary-policy.json": "flh-stg-host-boundary",
    "flh-stg-deploy-policy.json": "flh-stg-deploy",
    "flh-stg-deploy-ec2-policy.json": "flh-stg-deploy-ec2",
    "flh-stg-operate-policy.json": "flh-stg-operate",
}


def render(text, account, ami):
    return text.replace("__AWS_ACCOUNT_ID__", account).replace("__STAGING_AMI_ID__", ami)


def check_doc(name, text):
    problems = []
    left = sorted(set(re.findall(r"__[A-Z0-9_]+__", text)))
    if left:
        problems.append(f"placeholders left: {left}")
    try:
        doc = json.loads(text)
    except ValueError as e:
        return problems + [f"invalid JSON: {e}"]
    sids = [s.get("Sid") for s in doc.get("Statement", [])]
    if len(sids) != len(set(sids)):
        problems.append("duplicate Sid")
    size = len(re.sub(r"\s", "", json.dumps(doc)))
    if size > 6144:
        problems.append(f"{size} non-whitespace characters, over the 6,144 limit")
    return problems, size


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", required=True)
    ap.add_argument("--ami", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--templates", default=os.path.join(HERE, "out"))
    a = ap.parse_args()
    if not re.fullmatch(r"[0-9]{12}", a.account):
        sys.exit("refused: --account must be the 12-digit AWS account ID")
    if not re.fullmatch(r"ami-[0-9a-f]{8,17}", a.ami):
        sys.exit("refused: --ami must be an AMI ID (ami-...)")
    out = os.path.realpath(a.out)
    if (out + "/").startswith(REPO + "/"):
        sys.exit(f"refused: {out} is inside the repository; the filled policies hold the account ID")
    if os.path.isdir(out) and os.listdir(out):
        sys.exit(f"refused: {out} is not empty")
    bad = 0
    rendered = {}
    for fname in NAMES:
        text = open(os.path.join(a.templates, fname)).read()
        regions = set(re.findall(r"arn:aws:[a-z0-9-]+:([a-z]{2}-[a-z]+-[0-9]):", text))
        if regions - {a.region}:
            print(f"FAIL {fname}: the template names region(s) {sorted(regions)}, not {a.region}; "
                  "regenerate the templates for that region first")
            bad += 1
            continue
        filled = render(text, a.account, a.ami)
        res = check_doc(fname, filled)
        problems, size = res if isinstance(res, tuple) else (res, None)
        if problems:
            print(f"FAIL {fname}: {'; '.join(problems)}")
            bad += 1
            continue
        rendered[fname] = (filled, size)
    if bad:
        sys.exit(1)
    os.makedirs(out, mode=0o700, exist_ok=True)
    for fname, (filled, size) in rendered.items():
        path = os.path.join(out, fname)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(filled)
        print(f"OK   {fname} -> create as {NAMES[fname]} ({size} non-whitespace characters)")
    print(f"written to {out} (0600). Do not commit these files.")


if __name__ == "__main__":
    main()
