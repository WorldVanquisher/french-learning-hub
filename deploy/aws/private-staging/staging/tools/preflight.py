#!/usr/bin/env python3
"""Owner preflight for the private staging run. Offline: no AWS call, no Terraform run.

  preflight.py [--tfvars FILE] [--policies DIR] [--bundle FLH-STAGING-X.tar [--sha256 HEX]]
               [--tools] [--after-init]

Always (repository): every file the Terraform reads exists (file()/templatefile());
the cloud-config template uses exactly the variables main.tf passes; the rendered,
gzipped user data stays under EC2's 16 KB limit; host tools parse (Python 3.9
syntax, bash -n); the provider pin equals the demo's locked version; Git ignore
rules cover state, local variables and plans; the IAM templates equal what
make_policies.py derives from deploy/aws/iam today.
--tfvars: the owner's terraform.tfvars is filled in (no REPLACE placeholder), its
  values are well formed, the region and instance type match the IAM templates,
  expires_at is in the future and within 24 h.
--policies: the administrator's filled policies (render_policies.py) contain no
  placeholder, one account ID, the tfvars AMI, and fit the size limit.
--bundle: the transfer file verifies with host/flh-staging-bundle (SHA-256 from
  --sha256 or the .sha256 file beside it) and its names are consistent.
--tools: terraform >= 1.6, aws CLI v2, session-manager-plugin, docker, git,
  python3 >= 3.9, sha256sum, tar, sqlite3 are on PATH (version commands only).
--after-init: .terraform.lock.hcl exists and locks hashicorp/aws 6.69.1 with the
  same zh: checksums as the reviewed demo lock.
Exit 0 READY, 3 BLOCKED (every failed check is listed), 2 usage.
"""
import argparse
import ast
import datetime
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STAGING = os.path.dirname(HERE)
PRIVATE = os.path.dirname(STAGING)
REPO = os.path.realpath(os.path.join(PRIVATE, "..", "..", ".."))
TF = os.path.join(STAGING, "terraform")
results = []


def rec(status, name, detail=""):
    results.append((status, name, detail))
    print(f"{status:4} {name}" + (f": {detail}" if detail else ""), flush=True)


def ok(cond, name, detail_ok="", detail_fail=""):
    rec("PASS" if cond else "FAIL", name, detail_ok if cond else detail_fail)
    return cond


# --- repository checks -----------------------------------------------------------------------
def templatefile_vars(main_tf):
    m = re.search(r'templatefile\("\$\{path\.module\}/([^"]+)",\s*\{(.*?)\n\s*\}\)', main_tf, re.S)
    if not m:
        return None, {}
    keys = {}
    for line in m.group(2).splitlines():
        km = re.match(r"\s*([a-z_][a-z0-9_]*)\s*=\s*(.+?)\s*$", line)
        if km:
            keys[km.group(1)] = km.group(2)
    return m.group(1), keys


def render_template(text, values):
    """Enough of Terraform's template syntax for this file: ${name} and ${indent(n, name)}."""
    def rep(m):
        expr = m.group(1).strip()
        im = re.fullmatch(r"indent\((\d+),\s*([a-z_][a-z0-9_]*)\)", expr)
        if im:
            n, var = int(im.group(1)), im.group(2)
            lines = values[var].split("\n")
            return "\n".join([lines[0]] + [(" " * n + l) if l else l for l in lines[1:]])
        if re.fullmatch(r"[a-z_][a-z0-9_]*", expr):
            return str(values[expr])
        raise KeyError(expr)
    return re.sub(r"(?<!\$)\$\{([^}]*)\}", rep, text)


def check_repo():
    main_tf = open(os.path.join(TF, "main.tf")).read()
    for f in ("versions.tf", "variables.tf", "main.tf", "outputs.tf", "terraform.tfvars.example"):
        ok(os.path.isfile(os.path.join(TF, f)), f"terraform/{f} present", "", "missing")
    refs = re.findall(r'file\("\$\{path\.module\}/([^"]+)"\)', main_tf)
    missing = [r for r in refs if not os.path.isfile(os.path.normpath(os.path.join(TF, r)))]
    ok(refs and not missing, "files read by main.tf exist", f"{len(refs)} file() references", f"missing {missing}")
    tpl_name, keys = templatefile_vars(main_tf)
    if not tpl_name:
        rec("FAIL", "templatefile() call found in main.tf")
        return
    tpl = open(os.path.join(TF, tpl_name)).read()
    used = (set(re.findall(r"(?<!\$)\$\{\s*([a-z_][a-z0-9_]*)\s*\}", tpl))
            | set(re.findall(r"indent\(\d+,\s*([a-z_][a-z0-9_]*)\)", tpl)))
    ok(used == set(keys), "cloud-config variables == templatefile() map",
       f"{len(used)} variables", f"template uses {sorted(used - set(keys))} not passed; passed {sorted(set(keys) - used)} unused")
    sample = {"root": "/srv/flh-staging", "region": "us-east-1", "bucket": "flh-stg-20261118000000000000000000",
              "param_dir": "/flh/staging", "port": "8080", "max_runtime_hours": "4", "compose_version": "v2.29.7",
              "compose_sha256": "0" * 64}
    for k, expr in keys.items():
        fm = re.match(r'file\("\$\{path\.module\}/([^"]+)"\)', expr)
        if fm:
            sample[k] = open(os.path.normpath(os.path.join(TF, fm.group(1)))).read()
    try:
        rendered = render_template(tpl, sample)
        size = len(gzip.compress(rendered.encode(), 9))
        ok(size < 16384, "gzipped user data under 16 KB", f"{size} bytes ({len(rendered)} rendered)",
           f"{size} bytes: EC2 refuses user data over 16384")
        ok("%{" not in tpl, "no template directives the preflight cannot render", "", "found %{ directive")
    except KeyError as e:
        rec("FAIL", "cloud-config renders", f"unknown expression {e}")
    host = os.path.join(STAGING, "host")
    try:
        ast.parse(open(os.path.join(host, "flh-staging-bundle")).read(), feature_version=(3, 9))
        rec("PASS", "host/flh-staging-bundle parses as Python 3.9 (AL2023)")
    except SyntaxError as e:
        rec("FAIL", "host/flh-staging-bundle parses as Python 3.9 (AL2023)", str(e))
    r = subprocess.run(["bash", "-n", os.path.join(host, "flh-staging-env")], capture_output=True, text=True)
    ok(r.returncode == 0, "host/flh-staging-env passes bash -n", "", r.stderr.strip())
    vers = open(os.path.join(TF, "versions.tf")).read()
    pin = re.search(r'version\s*=\s*"([0-9.]+)"', vers)
    lock = open(os.path.join(REPO, "deploy", "aws", "terraform", ".terraform.lock.hcl")).read()
    locked = re.search(r'version\s*=\s*"([0-9.]+)"', lock)
    ok(pin and locked and pin.group(1) == locked.group(1), "provider pin == the demo's locked hashicorp/aws",
       pin.group(1) if pin else "", f"versions.tf {pin and pin.group(1)} vs lock {locked and locked.group(1)}")
    gi = open(os.path.join(PRIVATE, ".gitignore")).read().split()
    need = [".terraform/", "*.tfstate", "*.tfstate.*", "terraform.tfvars", "*.tfplan", "*.plan.json"]
    ok(all(n in gi for n in need), "ignore rules for state, local variables and plans", ", ".join(need),
       f"missing {[n for n in need if n not in gi]}")
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([sys.executable, "-I", os.path.join(STAGING, "iam", "make_policies.py"),
                            os.path.join(REPO, "deploy", "aws", "iam"), td], capture_output=True, text=True)
        diffs = [f for f in sorted(os.listdir(td))
                 if open(os.path.join(td, f), "rb").read() != open(os.path.join(STAGING, "iam", "out", f), "rb").read()] \
            if r.returncode == 0 and all(os.path.isfile(os.path.join(STAGING, "iam", "out", f)) for f in os.listdir(td)) else None
        ok(r.returncode == 0 and diffs == [], "IAM templates == make_policies.py output from deploy/aws/iam",
           "5 files identical", f"generator exit {r.returncode}, differing {diffs}")


# --- owner inputs -----------------------------------------------------------------------------
def parse_tfvars(path):
    vals = {}
    for line in open(path):
        m = re.match(r'\s*([a-z_][a-z0-9_]*)\s*=\s*(".*?"|[0-9.]+|true|false)\s*(#.*)?$', line)
        if m:
            v = m.group(2)
            vals[m.group(1)] = v[1:-1] if v.startswith('"') else v
    return vals


def iam_constraints():
    ec2 = json.load(open(os.path.join(STAGING, "iam", "out", "flh-stg-deploy-ec2-policy.json")))
    text = json.dumps(ec2)
    types = set(re.findall(r'"ec2:InstanceType":\s*"([^"]+)"', text))
    regions = set(re.findall(r"arn:aws:ec2:([a-z0-9-]+):", text))
    return types, regions


def check_tfvars(path):
    if not os.path.isfile(path):
        rec("FAIL", "terraform.tfvars present", f"{path} missing: cp terraform.tfvars.example terraform.tfvars and fill it")
        return {}
    v = parse_tfvars(path)
    raw = open(path).read()
    ok("REPLACE" not in raw, "terraform.tfvars has no REPLACE placeholder", "", "fill ami_id and compose_plugin_sha256")
    for key in ("aws_region", "run_id", "expires_at", "ami_id", "compose_plugin_sha256"):
        ok(key in v, f"tfvars {key} set", "", "missing")
    ok(re.fullmatch(r"ami-[0-9a-f]{8,17}", v.get("ami_id", "")) is not None, "tfvars ami_id is an AMI ID")
    ok(re.fullmatch(r"[0-9a-f]{64}", v.get("compose_plugin_sha256", "")) is not None,
       "tfvars compose_plugin_sha256 is 64 hex")
    ok(re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", v.get("run_id", "")) is not None, "tfvars run_id format")
    try:
        exp = datetime.datetime.strptime(v.get("expires_at", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        ok(now < exp <= now + datetime.timedelta(hours=24), "tfvars expires_at in the next 24 h",
           v["expires_at"], f"{v['expires_at']} is in the past or more than 24 h ahead")
    except ValueError:
        rec("FAIL", "tfvars expires_at is RFC 3339 UTC", v.get("expires_at", ""))
    types, regions = iam_constraints()
    itype = v.get("instance_type", "t3.small")
    ok(itype in types, "instance_type allowed by the IAM template", itype, f"{itype} not in {sorted(types)}")
    ok(v.get("aws_region") in regions, "aws_region named by the IAM templates", v.get("aws_region", ""),
       f"{v.get('aws_region')} not in {sorted(regions)}")
    return v


def check_policies(d, tfvars):
    files = sorted(f for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []
    ok(len(files) == 4, "four filled policies present", ", ".join(files), f"found {files}")
    accounts, amis = set(), set()
    for f in files:
        text = open(os.path.join(d, f)).read()
        left = re.findall(r"__[A-Z0-9_]+__", text)
        size = len(re.sub(r"\s", "", text))
        ok(not left and size <= 6144, f"{f} filled and within 6,144", f"{size} characters",
           f"placeholders {sorted(set(left))}, {size} characters")
        accounts |= set(re.findall(r"arn:aws:[a-z0-9-]+:[a-z0-9-]*:([0-9]{12}):", text))
        amis |= set(re.findall(r"image/(ami-[0-9a-f]+)", text))
    ok(len(accounts) == 1, "one account ID across the policies", "", f"{len(accounts)} distinct")
    if tfvars.get("ami_id"):
        ok(amis == {tfvars["ami_id"]}, "deploy-ec2 AMI == tfvars ami_id", "", f"policy {sorted(amis)} vs tfvars {tfvars['ami_id']}")


def check_bundle(tar, sha):
    base = os.path.basename(tar)
    ok(re.fullmatch(r"flh-staging-[0-9a-f]{12}\.tar", base) is not None, "bundle file name flh-staging-<tree12>.tar", base)
    side = tar + ".sha256"
    if not sha and os.path.isfile(side):
        parts = open(side).read().split()
        ok(len(parts) == 2 and parts[1].lstrip("*") == base, f"{base}.sha256 names {base}", "", f"content {parts}")
        sha = parts[0] if parts else None
    if not sha:
        rec("FAIL", "bundle SHA-256 known", "give --sha256 or keep the .sha256 file beside the tar")
        return
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.realpath(tar))) as td:
        r = subprocess.run([sys.executable, "-I", os.path.join(STAGING, "host", "flh-staging-bundle"), "verify", tar,
                            "--sha256", sha, "--scratch", td], capture_output=True, text=True)
    ok(r.returncode == 0, "bundle verifies (flh-staging-bundle verify)", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "",
       (r.stderr or r.stdout).strip()[-400:])


def tool_version(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)


def check_tools():
    for t in ("docker", "git", "sha256sum", "tar", "sqlite3"):
        ok(shutil.which(t) is not None, f"tool {t} on PATH", shutil.which(t) or "", "not found")
    ok(sys.version_info >= (3, 9), "python3 >= 3.9", sys.version.split()[0])
    if not shutil.which("terraform"):
        rec("FAIL", "tool terraform on PATH", "not found")
    else:
        rc, text = tool_version(["terraform", "version", "-json"])
        try:
            ver = json.loads(text)["terraform_version"]
        except (ValueError, KeyError, TypeError):
            ver = ""
        parts = tuple(int(x) for x in re.findall(r"\d+", ver)[:2]) if ver else ()
        ok(parts >= (1, 6), "terraform >= 1.6", ver, f"version {ver or text[:80]!r}")
    if not shutil.which("aws"):
        rec("FAIL", "tool aws (CLI v2) on PATH", "not found")
    else:
        rc, text = tool_version(["aws", "--version"])
        ok(rc == 0 and text.startswith("aws-cli/2."), "aws CLI v2", text.split()[0] if text else "", text[:80])
    if not shutil.which("session-manager-plugin"):
        rec("FAIL", "tool session-manager-plugin on PATH", "not found (needed for SSM sessions and port forwarding)")
    else:
        rc, text = tool_version(["session-manager-plugin", "--version"])
        ok(rc == 0, "session-manager-plugin runs", text.splitlines()[0] if text else "", text[:80])


def check_lock():
    path = os.path.join(TF, ".terraform.lock.hcl")
    if not os.path.isfile(path):
        rec("FAIL", "terraform/.terraform.lock.hcl present", "run terraform init first")
        return
    text = open(path).read()
    demo = open(os.path.join(REPO, "deploy", "aws", "terraform", ".terraform.lock.hcl")).read()
    ver = re.search(r'version\s*=\s*"([0-9.]+)"', text)
    ok(ver and ver.group(1) == "6.69.1", "lock pins hashicorp/aws 6.69.1", ver.group(1) if ver else "")
    zh = set(re.findall(r'"zh:([0-9a-f]{64})"', text))
    zh_demo = set(re.findall(r'"zh:([0-9a-f]{64})"', demo))
    ok(zh and zh <= zh_demo, "provider zh: checksums == the reviewed demo lock", f"{len(zh)} checksums",
       f"{len(zh - zh_demo)} checksum(s) not in the demo lock")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tfvars", default=None)
    ap.add_argument("--policies")
    ap.add_argument("--bundle")
    ap.add_argument("--sha256")
    ap.add_argument("--tools", action="store_true")
    ap.add_argument("--after-init", action="store_true")
    a = ap.parse_args()
    print("== repository")
    check_repo()
    tfvars = {}
    if a.tfvars:
        print("== terraform.tfvars")
        tfvars = check_tfvars(a.tfvars)
    if a.policies:
        print("== filled IAM policies")
        check_policies(a.policies, tfvars)
    if a.bundle:
        print("== bundle")
        check_bundle(a.bundle, a.sha256)
    if a.tools:
        print("== operator tools")
        check_tools()
    if a.after_init:
        print("== after terraform init")
        check_lock()
    failed = [r for r in results if r[0] == "FAIL"]
    print(f"{'BLOCKED' if failed else 'READY'}: {len(results) - len(failed)} passed, {len(failed)} failed")
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
