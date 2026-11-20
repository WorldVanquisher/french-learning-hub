#!/usr/bin/env python3
"""Owner preflight for the private staging run. Offline: no AWS call, no Terraform run.

  preflight.py [--tfvars FILE] [--inputs [--params FILE]] [--policies DIR]
               [--bundle FLH-STAGING-X.tar [--sha256 HEX]] [--plan PLAN.json [--plan-mode MODE]]
               [--tools] [--after-init] [--render-compose] [--card FILE]

Always (repository): every file the Terraform reads exists (file()/templatefile());
the cloud-config template uses exactly the variables main.tf passes; the rendered,
gzipped user data stays under EC2's 16 KB limit; host tools parse (Python 3.9
syntax, bash -n); the provider pin equals the demo's locked version; Git ignore
rules cover state, local variables and plans; the IAM templates equal what
make_policies.py derives from deploy/aws/iam today.
Always (public binding): no inbound path in main.tf, no ingress, egress 443 only; the
  rendered staging.conf PORT, compose.yaml's ports (127.0.0.1 only), the bundle's
  override (adds no port) and the SSM port forward all agree on app_port.
Always (publication): Git ignores every kind of local state, plan and setting; any
  such file present here is ignored; the image allowlist and the bundle's copied
  files cannot carry them.
--tfvars: the owner's terraform.tfvars is filled in (no REPLACE placeholder), its
  values are well formed, the region and instance type match the IAM templates,
  expires_at is in the future and within 24 h, and the host's bounded runtime
  (max_runtime_hours from now) ends before expires_at.
--inputs: the checklist of every input: each Terraform variable SET, DEFAULT,
  MISSING, PLACEHOLDER or INVALID (against variables.tf); the 16 host parameters of
  RUNBOOK §4 (with --params, the owner's saved get-parameters-by-path JSON: missing,
  empty or different; values are never printed); and the owner's decisions (OPEN
  unless another option checks them in this run). OPEN items do not block.
--policies: the administrator's filled policies (render_policies.py) contain no
  placeholder, one account ID, the tfvars AMI, and fit the size limit.
--bundle: the transfer file verifies with host/flh-staging-bundle (SHA-256 from
  --sha256 or the .sha256 file beside it) and its names are consistent.
--plan: plan_check.py's verdict for --plan-mode (default create), the blast radius
  (data-loss blocks), and with --tfvars the plan's freshness (plan_review.py).
--tools: terraform >= 1.6, aws CLI v2, session-manager-plugin, docker, git
  (presence only), python3 >= 3.9, sha256sum, GNU tar >= 1.28, sqlite3 are on PATH
  (version commands only; terraform with CHECKPOINT_DISABLE=1).
--after-init: .terraform.lock.hcl exists and locks hashicorp/aws 6.69.1 with the
  same zh: checksums as the reviewed demo lock.
--render-compose: also `docker compose config` of compose.yaml + the staging
  override in a scratch directory (no daemon, no .env, not the daily project).
--card FILE: a private launch card (0600, refused inside the repository) with the
  run's values, `<PLACEHOLDER>`s, the key commands and what blocks or is open.
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
    main_tf = rd(os.path.join(TF, "main.tf"))
    for f in ("versions.tf", "variables.tf", "main.tf", "outputs.tf", "terraform.tfvars.example"):
        ok(os.path.isfile(os.path.join(TF, f)), f"terraform/{f} present", "", "missing")
    refs = re.findall(r'file\("\$\{path\.module\}/([^"]+)"\)', main_tf)
    missing = [r for r in refs if not os.path.isfile(os.path.normpath(os.path.join(TF, r)))]
    ok(refs and not missing, "files read by main.tf exist", f"{len(refs)} file() references", f"missing {missing}")
    tpl_name, keys = templatefile_vars(main_tf)
    if not tpl_name:
        rec("FAIL", "templatefile() call found in main.tf")
        return
    tpl = rd(os.path.join(TF, tpl_name))
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
            sample[k] = rd(os.path.normpath(os.path.join(TF, fm.group(1))))
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
        ast.parse(rd(os.path.join(host, "flh-staging-bundle")), feature_version=(3, 9))
        rec("PASS", "host/flh-staging-bundle parses as Python 3.9 (AL2023)")
    except SyntaxError as e:
        rec("FAIL", "host/flh-staging-bundle parses as Python 3.9 (AL2023)", str(e))
    r = subprocess.run(["bash", "-n", os.path.join(host, "flh-staging-env")], capture_output=True, text=True)
    ok(r.returncode == 0, "host/flh-staging-env passes bash -n", "", r.stderr.strip())
    vers = rd(os.path.join(TF, "versions.tf"))
    pin = re.search(r'version\s*=\s*"([0-9.]+)"', vers)
    lock = rd(os.path.join(REPO, "deploy", "aws", "terraform", ".terraform.lock.hcl"))
    locked = re.search(r'version\s*=\s*"([0-9.]+)"', lock)
    ok(pin and locked and pin.group(1) == locked.group(1), "provider pin == the demo's locked hashicorp/aws",
       pin.group(1) if pin else "", f"versions.tf {pin and pin.group(1)} vs lock {locked and locked.group(1)}")
    gi = rd(os.path.join(PRIVATE, ".gitignore")).split()
    need = [".terraform/", "*.tfstate", "*.tfstate.*", "terraform.tfvars", "*.tfplan", "*.plan.json"]
    ok(all(n in gi for n in need), "ignore rules for state, local variables and plans", ", ".join(need),
       f"missing {[n for n in need if n not in gi]}")
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([sys.executable, "-I", os.path.join(STAGING, "iam", "make_policies.py"),
                            os.path.join(REPO, "deploy", "aws", "iam"), td], capture_output=True, text=True)
        diffs = [f for f in sorted(os.listdir(td))
                 if rd(os.path.join(td, f), "rb") != rd(os.path.join(STAGING, "iam", "out", f), "rb")] \
            if r.returncode == 0 and all(os.path.isfile(os.path.join(STAGING, "iam", "out", f)) for f in os.listdir(td)) else None
        ok(r.returncode == 0 and diffs == [], "IAM templates == make_policies.py output from deploy/aws/iam",
           "5 files identical", f"generator exit {r.returncode}, differing {diffs}")


# --- owner inputs -----------------------------------------------------------------------------
def parse_tfvars(path):
    vals = {}
    for line in rd(path).splitlines():
        m = re.match(r'\s*([a-z_][a-z0-9_]*)\s*=\s*(".*?"|[0-9.]+|true|false)\s*(#.*)?$', line)
        if m:
            v = m.group(2)
            vals[m.group(1)] = v[1:-1] if v.startswith('"') else v
    return vals


def iam_constraints():
    ec2 = json.loads(rd(os.path.join(STAGING, "iam", "out", "flh-stg-deploy-ec2-policy.json")))
    text = json.dumps(ec2)
    types = set(re.findall(r'"ec2:InstanceType":\s*"([^"]+)"', text))
    regions = set(re.findall(r"arn:aws:ec2:([a-z0-9-]+):", text))
    return types, regions


def check_tfvars(path):
    if not os.path.isfile(path):
        rec("FAIL", "terraform.tfvars present", f"{path} missing: cp terraform.tfvars.example terraform.tfvars and fill it")
        return {}
    v = parse_tfvars(path)
    raw = rd(path)
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
        hours = float(v.get("max_runtime_hours", "4"))
        left = (exp - now).total_seconds() / 3600
        ok(hours <= left, "the host powers off before expires_at (max_runtime_hours from now)",
           f"{hours:g} h <= {left:.1f} h left",
           f"max_runtime_hours {hours:g} would keep the host (and its billing) running {hours - left:.1f} h past "
           f"expires_at {v['expires_at']}: lower max_runtime_hours or move expires_at")
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
        text = rd(os.path.join(d, f))
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
        parts = rd(side).split()
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
    env = dict(os.environ, CHECKPOINT_DISABLE="1")   # terraform: no update check over the network
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)


# Operator tools: (name, version command or None, version regex, minimum, basis, used in).
# Version commands only: nothing contacts AWS, a Docker daemon or a repository. Git is checked
# for presence only, because the preflight runs no Git command.
TOOLS = [
    ("terraform", ["terraform", "version", "-json"], r'"terraform_version":\s*"(\d+(?:\.\d+)+)', (1, 6),
     "versions.tf required_version >= 1.6", "§3"),
    ("aws", ["aws", "--version"], r"aws-cli/(\d+(?:\.\d+)+)", (2, 0), "RUNBOOK §0: AWS CLI v2", "§2-§9"),
    ("session-manager-plugin", ["session-manager-plugin", "--version"], r"(\d+(?:\.\d+)+)", None,
     "any version; SSM sessions and the port forward need it", "§5-§7"),
    ("docker", ["docker", "--version"], r"version (\d+(?:\.\d+)+)", None,
     "any version (the build records it in BUILD.json); client only, no daemon contact", "§1"),
    ("git", None, None, None, "presence only (the preflight runs no Git command); build_bundle.sh --git", "§1"),
    ("python3", ["python3", "--version"], r"Python (\d+(?:\.\d+)+)", (3, 9), "RUNBOOK §0; the host runs 3.9", "§1-§6"),
    ("sha256sum", ["sha256sum", "--version"], r"(\d+(?:\.\d+)+)", None, "any version", "§1, §5"),
    ("tar", ["tar", "--version"], r"GNU tar\)? (\d+(?:\.\d+)+)", (1, 28),
     "GNU tar 1.28+: build_bundle.sh uses --sort=name", "§1"),
    ("sqlite3", ["sqlite3", "--version"], r"^(\d+(?:\.\d+)+)", None, "any 3.x (flh-daily.sh backup/restore)", "§6"),
]


def check_tools():
    for name, cmd, rx, minimum, basis, used in TOOLS:
        path = shutil.which(name)
        if not path:
            rec("FAIL", f"tool {name} on PATH", f"not found; needed in RUNBOOK {used} ({basis})")
            continue
        if cmd is None:
            rec("PASS", f"tool {name} present", f"{path}; {basis}")
            continue
        rc, text = tool_version(cmd)
        m = re.search(rx, text or "", re.M)
        ver = m.group(1) if m else None
        if rc != 0 or not ver:
            rec("FAIL", f"tool {name} reports its version", f"exit {rc}: {(text or '')[:80]!r}")
            continue
        parts = tuple(int(x) for x in ver.split("."))
        if minimum and parts < minimum:
            rec("FAIL", f"tool {name} {ver} supported", f"needs >= {'.'.join(map(str, minimum))} ({basis})")
        else:
            rec("PASS", f"tool {name} {ver} supported", basis)


def check_lock():
    path = os.path.join(TF, ".terraform.lock.hcl")
    if not os.path.isfile(path):
        rec("FAIL", "terraform/.terraform.lock.hcl present", "run terraform init first")
        return
    text = rd(path)
    demo = rd(os.path.join(REPO, "deploy", "aws", "terraform", ".terraform.lock.hcl"))
    ver = re.search(r'version\s*=\s*"([0-9.]+)"', text)
    ok(ver and ver.group(1) == "6.69.1", "lock pins hashicorp/aws 6.69.1", ver.group(1) if ver else "")
    zh = set(re.findall(r'"zh:([0-9a-f]{64})"', text))
    zh_demo = set(re.findall(r'"zh:([0-9a-f]{64})"', demo))
    ok(zh and zh <= zh_demo, "provider zh: checksums == the reviewed demo lock", f"{len(zh)} checksums",
       f"{len(zh - zh_demo)} checksum(s) not in the demo lock")


# --- staging inputs checklist (--inputs) --------------------------------------------------------
def rd(path, mode="r"):
    with open(path, mode) as fh:
        return fh.read()


def hcl_blocks(text, head):
    """(groups, body) of every top-level block whose header matches the regex `head` and ends in '{'.
    Braces inside quoted strings are skipped."""
    out = []
    for m in re.finditer(r"^" + head + r"\s*\{", text, re.M):
        depth, i = 1, m.end()
        while depth and i < len(text):
            c = text[i]
            if c == '"':
                i += 1
                while i < len(text) and text[i] != '"':
                    i += 2 if text[i] == "\\" else 1
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        out.append((m.groups(), text[m.end():i - 1]))
    return out


def tf_variables():
    """variables.tf: description, default and the offline-checkable part of each validation."""
    out = {}
    for (name,), body in hcl_blocks(rd(os.path.join(TF, "variables.tf")), r'variable\s+"([^"]+)"'):
        d = re.search(r'^\s*default\s*=\s*("(?:[^"\\]|\\.)*"|[0-9.]+|true|false)\s*$', body, re.M)
        rx = re.search(r'can\(regex\("((?:[^"\\]|\\.)*)",\s*var\.%s\)\)' % name, body)
        lo = re.search(r"var\.%s\s*>=\s*([0-9.]+)" % name, body)
        hi = re.search(r"var\.%s\s*<=\s*([0-9.]+)" % name, body)
        default = d.group(1) if d else None
        if default is not None and default.startswith('"'):
            default = default[1:-1]
        out[name] = {"default": default, "regex": rx.group(1).replace("\\\\", "\\") if rx else None,
                     "min": float(lo.group(1)) if lo else None, "max": float(hi.group(1)) if hi else None}
    return out


def input_problem(spec, value):
    """None when the value would pass variables.tf, else (state, detail)."""
    if value is None:
        return "MISSING", "required: no default in variables.tf and not set in terraform.tfvars"
    if "REPLACE" in value:
        return "PLACEHOLDER", f"{value} is the example's placeholder"
    if spec["regex"] and not re.search(spec["regex"], value):
        return "INVALID", f"{value!r} fails the variable's validation /{spec['regex']}/"
    if spec["min"] is not None or spec["max"] is not None:
        try:
            n = float(value)
        except ValueError:
            return "INVALID", f"{value!r} is not a number"
        if (spec["min"] is not None and n < spec["min"]) or (spec["max"] is not None and n > spec["max"]):
            return "INVALID", f"{value} is outside the variable's range [{spec['min']:g}, {spec['max']:g}]"
    return None


def runbook_parameters():
    """The host parameters RUNBOOK §4 writes (name -> proposed value) and the count its own check expects."""
    text = rd(os.path.join(PRIVATE, "RUNBOOK.md"))
    m = re.search(r"^for kv in (.*?); do$", text, re.S | re.M)
    pairs = re.findall(r"\b([A-Z][A-Z0-9_]*)=(\S+)", m.group(1)) if m else []
    expect = re.search(r"length\(Parameters\)'\s+#\s*expect\s+(\d+)", text)
    return dict(pairs), (int(expect.group(1)) if expect else None)


def required_parameters():
    m = re.search(r"for need in \(([^)]*)\)", rd(os.path.join(STAGING, "host", "flh-staging-env")))
    return re.findall(r'"([A-Z][A-Z0-9_]*)"', m.group(1)) if m else []


# Inputs the repository cannot hold. `flag` names the option that checks the input in this run.
OWNER_INPUTS = [
    ("authorization", "budget cap, region and runtime window (proposed: $5, us-east-1, 4 h)", "RUNBOOK §0; without it, stop", None),
    ("account_id", "AWS account ID (12 digits), for render_policies.py only; never committed", "RUNBOOK §2", "policies"),
    ("revision", "the one commit on main to deploy", "RUNBOOK §1, build_bundle.sh --git", "bundle"),
    ("bundle", "the transfer tar and its SHA-256", "RUNBOOK §1, --bundle", "bundle"),
    ("synthetic_backup", "a synthetic NAS-shaped backup, never the daily data", "RUNBOOK §6", None),
    ("plan", "`terraform show -json` of the plan to apply", "RUNBOOK §3.2, --plan", "plan"),
]


def bundle_commit(tar):
    """The commit a bundle's MANIFEST pins, or None (tree-only rehearsal or unreadable)."""
    import tarfile
    try:
        with tarfile.open(tar) as tf:
            name = os.path.basename(tar)[:-4] if tar.endswith(".tar") else tf.getmembers()[0].name.split("/")[0]
            with tf.extractfile(f"{name}/MANIFEST.json") as fh:
                commit = (json.load(fh).get("revision") or {}).get("commit")
    except (OSError, KeyError, ValueError, tarfile.TarError, AttributeError):
        return None
    return commit if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit) else None


def check_inputs(tfvars_path, params_path, supplied):
    """Every input of a staging run: Terraform variables (value, default or missing), the host
    parameters (names and set/empty only: values are never printed) and the owner's decisions."""
    specs = tf_variables()
    vals = parse_tfvars(tfvars_path) if tfvars_path and os.path.isfile(tfvars_path) else {}
    print(f"-- Terraform variables: {len(specs)} declared in variables.tf; values from "
          + ("terraform.tfvars, else the default" if tfvars_path else "defaults only (no --tfvars)"))
    resolved = {}
    for name, spec in specs.items():
        value, origin = (vals[name], "SET") if name in vals else (spec["default"], "DEFAULT")
        resolved[name] = value
        bad = input_problem(spec, value)
        if bad:
            rec("FAIL", f"input var.{name} {bad[0]}", bad[1])
        else:
            rec("PASS", f"input var.{name} {origin}", value)
    for name in sorted(set(vals) - set(specs)):
        rec("WARN", f"input var.{name} not declared", "terraform.tfvars sets a variable variables.tf does not declare")
    params, expect = runbook_parameters()
    need = required_parameters()
    print(f"-- host parameters under /flh/staging: {len(params)} written by RUNBOOK §4; required by flh-staging-env: "
          + ", ".join(need))
    ok(len(params) > 0 and expect == len(params), "RUNBOOK §4 writes as many parameters as its check expects",
       f"{len(params)}", f"the loop writes {len(params)}, the check expects {expect}")
    ok(set(need) <= set(params), "RUNBOOK §4 writes every parameter flh-staging-env requires", "",
       f"missing {sorted(set(need) - set(params))}")
    got = None
    if params_path:
        try:
            doc = json.loads(rd(params_path))
            got = {p["Name"].rsplit("/", 1)[-1]: p.get("Value", "") for p in doc.get("Parameters", [])}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            rec("FAIL", "parameters file readable", f"{params_path}: {e}")
    if got is not None:
        for name in sorted(params):          # values are never printed, only set/empty/differs
            if name not in got:
                rec("FAIL", f"parameter {name} MISSING", "RUNBOOK §4")
            elif got[name] == "" and name in need:
                rec("FAIL", f"parameter {name} EMPTY", "required by flh-staging-env")
            elif got[name] != params[name]:
                rec("FAIL", f"parameter {name} differs from RUNBOOK §4", "value not shown; change the runbook first if intended")
            else:
                rec("PASS", f"parameter {name} set", "equals RUNBOOK §4")
        for name in sorted(set(got) - set(params)):
            rec("WARN", f"parameter {name} not in RUNBOOK §4", "every parameter becomes a setting on the host")
    else:
        for name in sorted(params):
            rec("OPEN", f"parameter {name}", f"owner writes it in RUNBOOK §4 (proposed value {params[name]})")
    print("-- owner inputs outside the repository")
    for key, what, where, flag in OWNER_INPUTS:
        if key == "revision" and "bundle" in supplied:
            commit = bundle_commit(supplied["bundle"])
            if commit:
                rec("PASS", "owner input revision supplied", f"the bundle pins commit {commit[:12]}")
            else:
                rec("OPEN", "owner input revision", "the bundle is tree-only (no commit): the owner's "
                    "build_bundle.sh --git pins the commit on main (RUNBOOK §1)")
        elif flag and flag in supplied:
            rec("PASS", f"owner input {key} supplied", f"checked by --{flag} in this run")
        else:
            rec("OPEN", f"owner input {key}", f"{what} ({where})")
    return resolved, (got if got is not None else params)


# --- public binding (always) -------------------------------------------------------------------
def staging_override_text():
    """The override build_bundle.sh writes into every bundle (its heredoc), with $TAG left in."""
    m = re.search(r'cat > "\$OUT/staging\.override\.yaml" <<YAML\n(.*?)\nYAML\n', rd(os.path.join(STAGING, "build_bundle.sh")), re.S)
    return m.group(1) if m else None


def compose_ports(text):
    """Every published port entry in a compose file (static: the items of each `ports:` list)."""
    out, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)ports:\s*$", line)
        if not m:
            continue
        for nxt in lines[i + 1:]:
            if not nxt.strip() or nxt.lstrip().startswith("#"):
                continue
            item = re.match(r"^(\s*)-\s*(.+?)\s*$", nxt)
            if not item or len(item.group(1)) < len(m.group(1)):
                break
            out.append(item.group(2).strip("'\""))
    return out


def render_compose(app_port):
    """`docker compose config` of compose.yaml + the staging override, in a scratch project directory
    (no .env is read; the project name is not the daily one). Returns [(service, host_ip, published)]."""
    with tempfile.TemporaryDirectory() as td:
        shutil.copy(os.path.join(REPO, "compose.yaml"), os.path.join(td, "compose.yaml"))
        with open(os.path.join(td, "staging.override.yaml"), "w") as fh:
            fh.write(staging_override_text().replace("$TAG", "flh-staging-000000000000:render") + "\n")
        with open(os.path.join(td, "staging.env"), "w") as fh:
            fh.write(f"FLH_HOST_PORT={app_port}\nFLH_DATA_DIR={td}/data\nFLH_QDRANT_DIR={td}/qdrant\n")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", td)}
        r = subprocess.run(["docker", "compose", "--project-directory", td, "-p", "flh-preflight-render",
                            "--env-file", os.path.join(td, "staging.env"), "--profile", "semantic",
                            "-f", os.path.join(td, "compose.yaml"), "-f", os.path.join(td, "staging.override.yaml"),
                            "config", "--format", "json"], capture_output=True, text=True, timeout=60, env=env, cwd=td)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip()[-300:])
        cfg = json.loads(r.stdout)
    return [(svc, p.get("host_ip"), p.get("published")) for svc, s in sorted(cfg.get("services", {}).items())
            for p in s.get("ports") or []]


def check_binding(app_port, params, rendered_compose=False):
    """The workbench has no authentication: no inbound path may exist, and every published port
    stays on the host's loopback, reached only through an SSM port forward."""
    main_tf = rd(os.path.join(TF, "main.tf"))
    expected = json.loads(rd(os.path.join(STAGING, "expected_resources.json")))
    res = hcl_blocks(main_tf, r'resource\s+"([^"]+)"\s+"([^"]+)"')
    public = [f"{t}.{n}" for (t, n), _ in res if t in expected["public_path_types"]]
    ok(not public, "main.tf declares no inbound path (EIP, LB, DNS, ingress rule, ...)", f"{len(res)} resources", f"found {public}")
    sgs = [(n, b) for (t, n), b in res if t == "aws_security_group"]
    ok(sgs and not any(re.search(r"^\s*ingress\b", b, re.M) for _, b in sgs), "security groups have no ingress block",
       f"{len(sgs)} group(s)", "an ingress block exists")
    egress = [b for (t, _), b in res if t == "aws_vpc_security_group_egress_rule"]
    ok(egress and all(re.search(r"from_port\s*=\s*443\b", b) and re.search(r"to_port\s*=\s*443\b", b) for b in egress),
       "egress is TCP 443 only", "", "an egress rule other than 443")
    sample = {"root": "/srv/flh-staging", "region": "us-east-1", "bucket": "flh-stg-x", "param_dir": "/flh/staging",
              "port": str(app_port), "max_runtime_hours": "4", "compose_version": "v2.29.7", "compose_sha256": "0" * 64,
              "render_env": "", "bundle_tool": "", "expire_unit": ""}
    rendered = render_template(rd(os.path.join(TF, "cloud-config.yaml.tftpl")), sample)
    conf = re.search(r"^\s*PORT=(\S+)\s*$", rendered, re.M)
    ok(conf and conf.group(1) == str(app_port), "rendered /etc/flh/staging.conf PORT == app_port", str(app_port),
       f"PORT={conf and conf.group(1)}")
    ok(not re.search(r"0\.0\.0\.0|LISTEN_HOST|HTTP_ALLOWED_HOSTS", rendered), "rendered user data sets no listen address", "",
       "user data names 0.0.0.0, LISTEN_HOST or HTTP_ALLOWED_HOSTS")
    compose = rd(os.path.join(REPO, "compose.yaml"))
    ports = compose_ports(compose)
    ok(ports and all(p.startswith("127.0.0.1:") for p in ports), "compose.yaml publishes on 127.0.0.1 only",
       ", ".join(ports), f"ports {ports}")
    ok(not re.search(r"^\s*network_mode:\s*\"?host", compose, re.M), "compose.yaml uses no host networking")
    ov = staging_override_text()
    ok(ov is not None and not re.search(r"^\s*(ports|network_mode|expose):", ov, re.M),
       "the bundle's staging.override.yaml adds no port or network mode", "", "override missing or publishes")
    demo = [n for n, t in (("compose.yaml", compose), ("staging.override.yaml", ov or ""), ("main.tf", main_tf))
            if re.search(r"public-demo|public_demo", t)]
    ok(not demo and "../../terraform" not in main_tf, "staging never runs the public demo mode or uses the demo's root",
       "the private workbench is not behind the public demo boundary here, and not reachable through it",
       f"public-demo named in {demo}" if demo else "main.tf references the demo root")
    outs = rd(os.path.join(TF, "outputs.tf"))
    ok("AWS-StartPortForwardingSession" in outs and "portNumber=${var.app_port}" in outs,
       "the only access is the SSM port forward to app_port", "", "outputs.tf port_forward_command changed")
    pv = (params or {}).get("FLH_HOST_PORT")
    ok(pv == str(app_port), "host parameter FLH_HOST_PORT == app_port", "", "differs (value not shown)")
    ok(not ({"LISTEN_HOST", "HTTP_ALLOWED_HOSTS"} & set(params or {})), "no parameter widens the listener or allowed hosts",
       "", "LISTEN_HOST or HTTP_ALLOWED_HOSTS is set")
    if rendered_compose:
        try:
            got = render_compose(app_port)
            bad = [g for g in got if g[1] != "127.0.0.1"]
            ok(got and not bad, "docker compose config (staging override, semantic profile): every port on 127.0.0.1",
               ", ".join(f"{s} {ip}:{pub}" for s, ip, pub in got), f"not loopback: {bad}")
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
            rec("FAIL", "docker compose config renders", str(e))


# --- publication exclusion (always) ------------------------------------------------------------
def gitignored(rules, path, is_dir=False):
    """Git's matching for the pattern forms private-staging/.gitignore uses (no negation, no '**')."""
    import fnmatch
    parts = path.split("/")
    ignored = False
    for raw in rules:
        pat = raw.strip()
        if not pat or pat.startswith("#"):
            continue
        dir_only = pat.endswith("/")
        p = pat.rstrip("/")
        hit = False
        if "/" in p:
            anchored = p.lstrip("/")
            for i in range(1, len(parts) + 1):
                if fnmatch.fnmatchcase("/".join(parts[:i]), anchored) and (i < len(parts) or is_dir or not dir_only):
                    hit = True
        else:
            for i, comp in enumerate(parts):
                if fnmatch.fnmatchcase(comp, p) and (not dir_only or i < len(parts) - 1 or is_dir):
                    hit = True
        if hit:
            ignored = True
    return ignored


# One sample of every kind of local operator state (relative to deploy/aws/private-staging).
LOCAL_SAMPLES = ["staging/terraform/terraform.tfstate", "staging/terraform/terraform.tfstate.backup",
                 "staging/terraform/terraform.tfstate.1700000000.backup", "staging/terraform/.terraform.tfstate.lock.info",
                 "staging/terraform/.terraform/providers/registry.terraform.io/hashicorp/aws/6.69.1/linux_amd64/p",
                 "staging/terraform/terraform.tfvars", "staging/terraform/owner.auto.tfvars",
                 "staging/terraform/stg.tfplan", "staging/terraform/stg.plan.json", "staging/terraform/stg-destroy.plan.json",
                 "staging/terraform/crash.log", "staging/terraform/override.tf",
                 "staging/iam/local/flh-stg-deploy-policy.json", "flh-staging-0123456789ab.tar",
                 "flh-staging-0123456789ab.tar.sha256", "staging/terraform/stg.plan-stamp.json"]
LOCAL_GLOBS = ("terraform.tfvars", "*.auto.tfvars", "*.auto.tfvars.json", "*.tfstate", "*.tfstate.*",
               ".terraform.tfstate.lock.info", "*.tfplan", "*.tfplan.json", "*.plan.json", "crash*.log",
               "override.tf", "override.tf.json", "*_override.tf", "*_override.tf.json", "flh-staging-*.tar",
               "flh-staging-*.tar.sha256", "*.plan-stamp.json", "*.env", ".env")


def check_publication():
    """Local state, plans and settings stay out of every published form: Git (ignore rules), the image
    (.dockerignore allowlist) and the bundle (its fixed file list). Files present here are listed by name."""
    import fnmatch
    rules = rd(os.path.join(PRIVATE, ".gitignore")).splitlines()
    missed = [s for s in LOCAL_SAMPLES if not gitignored(rules, s)]
    ok(not missed, "Git ignores every kind of local state, plan and setting", f"{len(LOCAL_SAMPLES)} sample kinds",
       f"not ignored: {missed}")
    present = []
    for dp, dns, fns in os.walk(PRIVATE):
        for f in fns + [d + "/" for d in dns if d == ".terraform"]:
            if f.endswith("/") or any(fnmatch.fnmatchcase(f, g) for g in LOCAL_GLOBS):
                present.append(os.path.relpath(os.path.join(dp, f.rstrip("/")), PRIVATE) + ("/" if f.endswith("/") else ""))
        dns[:] = [d for d in dns if d != ".terraform"]
    exposed = [p for p in present if not gitignored(rules, p.rstrip("/"), is_dir=p.endswith("/"))]
    ok(not exposed, "local state present here is ignored by Git",
       f"{len(present)} present: {', '.join(sorted(present))}" if present else "none present", f"NOT ignored: {exposed}")
    di = [l.strip() for l in rd(os.path.join(REPO, ".dockerignore")).splitlines() if l.strip() and not l.startswith("#")]
    allowed = [l[1:].rstrip("/") for l in di if l.startswith("!")]
    ok(di[:1] == ["*"] and not any(a == "deploy" or a.startswith("deploy/") for a in allowed),
       "the image build context (.dockerignore allowlist) excludes deploy/", f"{len(allowed)} allowed paths",
       "the allowlist does not start with * or allows deploy/")
    ok({"**/.env", "**/*.db"} <= set(di), ".dockerignore refuses .env and databases under allowed paths")
    m = re.search(r"^for f in (.*?); do$", rd(os.path.join(STAGING, "build_bundle.sh")), re.S | re.M)
    files = m.group(1).replace("\\\n", " ").split() if m else []
    bad = [f for f in files if f.startswith("deploy/") or any(fnmatch.fnmatchcase(os.path.basename(f), g) for g in LOCAL_GLOBS)]
    ok(files and not bad, "the bundle's copied repository files hold no local state", f"{len(files)} files", f"{bad}")


# --- private launch card (--card) --------------------------------------------------------------
def write_card(path, tfvars, a):
    """A private, filled-in copy of the run's key commands. Placeholders mark what the owner fills;
    no credential, account ID or URL is ever written. Refused inside the repository."""
    real = os.path.realpath(path)
    if real == REPO or real.startswith(REPO + os.sep):
        rec("FAIL", "launch card written outside the repository", f"{path} is inside the repository")
        return
    v = lambda k, ph: tfvars.get(k) if tfvars.get(k) and "REPLACE" not in tfvars.get(k) else f"<{ph}>"
    bundle = os.path.basename(a.bundle) if a.bundle else "<flh-staging-TREE12>.tar"
    sha = a.sha256
    if not sha and a.bundle and os.path.isfile(a.bundle + ".sha256"):
        sha = (rd(a.bundle + ".sha256").split() or [None])[0]
    a = argparse.Namespace(**dict(vars(a), sha256=sha))
    failed = [r for r in results if r[0] == "FAIL"]
    opened = [r for r in results if r[0] == "OPEN"]
    verdict = "BLOCKED" if failed else "READY"
    lines = [
        "# FLH private staging launch card",
        "",
        "PRIVATE: keep this file outside Git and delete it after the run. It holds no credential;",
        "`<...>` marks a value the owner fills in. The commands are RUNBOOK.md's, in order.",
        "",
        f"Preflight when written: **{verdict}**, {len(results) - len(failed) - len(opened)} passed, {len(failed)} failed, "
        f"{len(opened)} open (generated {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}).",
        "",
        "| Input | Value |",
        "| --- | --- |",
        f"| region | {v('aws_region', 'REGION')} |",
        f"| run_id | {v('run_id', 'RUN_ID')} |",
        f"| expires_at (destroy by) | {v('expires_at', 'EXPIRES_AT')} |",
        f"| instance_type | {v('instance_type', 'INSTANCE_TYPE') if tfvars.get('instance_type') else 't3.small (default)'} |",
        f"| ami_id | {v('ami_id', 'AMI_ID')} |",
        "| account ID | <ACCOUNT_ID> (render_policies.py only; never on this card) |",
        "| budget cap / window | <BUDGET_CAP> / until the expiry above |",
        f"| bundle | {bundle}, SHA-256 {a.sha256 or '<BUNDLE_SHA256>'} |",
        "",
        "## Commands",
        "",
        "```bash",
        "S=deploy/aws/private-staging/staging; OUT=<OUT_DIR>; REGION=" + v("aws_region", "REGION"),
        f"python3 -I $S/tools/preflight.py --tools --inputs --tfvars $S/terraform/terraform.tfvars --policies <POLICY_DIR> "
        f"--bundle \"$OUT/{bundle}\" --sha256 {a.sha256 or '<BUNDLE_SHA256>'}   # RUNBOOK §3: READY",
        "cd $S/terraform && terraform fmt -check && terraform init && terraform validate && cd -   # §3.1",
        "python3 -I $S/tools/preflight.py --after-init",
        "cd $S/terraform && terraform plan -out stg.tfplan && terraform show -json stg.tfplan > stg.plan.json   # §3.2",
        "python3 -I ../tools/plan_check.py --mode create stg.plan.json      # SAFE, 21 to add",
        "python3 -I ../tools/plan_review.py stamp stg.plan.json --tfvars terraform.tfvars   # records the reviewed inputs",
        "python3 -I ../tools/plan_review.py freshness stg.plan.json --tfvars terraform.tfvars   # right before apply: FRESH",
        "terraform apply stg.tfplan                                       # §3.3: billing starts",
        "# §4 parameters, §5 upload and install, §6 restore, §7 checks: RUNBOOK.md",
        "# §9 teardown the same day, before " + v("expires_at", "EXPIRES_AT") + ": terraform plan -destroy, plan_check --mode destroy, apply",
        "```",
        "",
        "## Blocking now",
        "",
    ] + ([f"- {n}: {d}" for _, n, d in failed] or ["- none"]) + ["", "## Open (owner)", ""] + \
        ([f"- {n}: {d}" for _, n, d in opened] or ["- none"]) + [""]
    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    os.chmod(path, 0o600)
    print(f"wrote launch card {path} (0600)")


def load_tool(name):
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    loader.exec_module(mod)
    return mod


def check_plan(path, mode, tfvars_path):
    """plan_check.py's verdict, the plan's freshness against its inputs, and its blast radius."""
    pc, pr = load_tool("plan_check"), load_tool("plan_review")
    expected = json.loads(rd(os.path.join(STAGING, "expected_resources.json")))
    try:
        plan = json.loads(rd(path))
    except (OSError, ValueError) as e:
        rec("FAIL", "plan JSON readable", f"{path}: {e}")
        return
    if not isinstance(plan, dict) or "resource_changes" not in plan or "format_version" not in plan:
        rec("FAIL", "plan JSON is `terraform show -json` output", path)
        return
    findings, counts = pc.check(plan, expected, mode, set())
    stops = [f for f in findings if f[0] == "STOP"]
    ok(not stops, f"plan_check --mode {mode} says SAFE",
       f"{counts.get('create', 0)} to add, {counts.get('update', 0)} to change, {counts.get('delete', 0)} to destroy",
       f"STOP x{len(stops)}: " + "; ".join(f"{a}: {m}" for _, a, m in stops[:4]) + (" ..." if len(stops) > 4 else ""))
    rows = pr.summarize(plan, expected)
    worst = next((r for r in pr.RADII if any(x["radius"] == r for x in rows)), "none")
    rec("PASS" if worst not in ("data-loss",) else "FAIL", "plan blast radius", f"most severe: {worst} "
        + "(" + ", ".join(f"{sum(1 for x in rows if x['radius'] == r)} {r}" for r in pr.RADII if any(x['radius'] == r for x in rows)) + ")")
    if tfvars_path and os.path.isfile(tfvars_path):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = pr.cmd_freshness(argparse.Namespace(plan=path, tfvars=tfvars_path))
        lines = [l for l in buf.getvalue().splitlines() if l.startswith("STALE ")]
        ok(rc == 0, "plan made from the current inputs (plan_review.py freshness)", buf.getvalue().strip().splitlines()[0],
           "; ".join(l[6:] for l in lines[:4]))
    else:
        rec("OPEN", "plan freshness", "give --tfvars to compare the plan with its inputs")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tfvars", default=None)
    ap.add_argument("--policies")
    ap.add_argument("--bundle")
    ap.add_argument("--sha256")
    ap.add_argument("--tools", action="store_true")
    ap.add_argument("--after-init", action="store_true")
    ap.add_argument("--inputs", action="store_true", help="the staging inputs checklist")
    ap.add_argument("--params", help="`aws ssm get-parameters-by-path --output json` saved by the owner (values never printed)")
    ap.add_argument("--plan", help="`terraform show -json` of the plan to apply")
    ap.add_argument("--plan-mode", default="create", choices=["create", "update", "destroy"])
    ap.add_argument("--render-compose", action="store_true", help="also check `docker compose config` (local, no daemon)")
    ap.add_argument("--card", help="write a private launch card here (outside the repository)")
    a = ap.parse_args()
    print("== repository")
    check_repo()
    tfvars = {}
    if a.tfvars:
        print("== terraform.tfvars")
        tfvars = check_tfvars(a.tfvars)
    resolved, params = None, runbook_parameters()[0]
    if a.inputs:
        print("== staging inputs checklist")
        supplied = {k: getattr(a, k) for k in ("policies", "bundle", "plan") if getattr(a, k)}
        resolved, params = check_inputs(a.tfvars, a.params, supplied)
    port = (resolved or {}).get("app_port") or tfvars.get("app_port") or tf_variables()["app_port"]["default"]
    print("== public binding")
    check_binding(port, params, a.render_compose)
    print("== publication")
    check_publication()
    if a.policies:
        print("== filled IAM policies")
        check_policies(a.policies, tfvars)
    if a.bundle:
        print("== bundle")
        check_bundle(a.bundle, a.sha256)
    if a.plan:
        print("== plan")
        check_plan(a.plan, a.plan_mode, a.tfvars)
    if a.tools:
        print("== operator tools")
        check_tools()
    if a.after_init:
        print("== after terraform init")
        check_lock()
    if a.card:
        write_card(a.card, parse_tfvars(a.tfvars) if a.tfvars and os.path.isfile(a.tfvars) else {}, a)
    failed = [r for r in results if r[0] == "FAIL"]
    opened = [r for r in results if r[0] == "OPEN"]
    warned = [r for r in results if r[0] == "WARN"]
    extra = (f", {len(warned)} warnings" if warned else "") + (f", {len(opened)} open owner inputs" if opened else "")
    print(f"{'BLOCKED' if failed else 'READY'}: {len(results) - len(failed) - len(opened) - len(warned)} passed, "
          f"{len(failed)} failed{extra}")
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
