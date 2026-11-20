#!/usr/bin/env python3
"""Release-candidate gates for the private staging root (R4). Offline: no AWS, Terraform or Docker call.

  candidate.py identity BUNDLE [--json]
      BUNDLE is flh-staging-<tree12>.tar (its .sha256 beside it) or the unpacked directory. Prints
      the candidate identity: bundle, transfer SHA-256, commit, tree, content digest, image ID and
      platform (from image.tar's config), server and web digests, migration ledger, and the runtime
      contract read from the bundle's own compose.yaml (user, published port binding, forwarded
      settings, health check, restart policy).
  candidate.py provenance BUNDLE --commit SHA --out FILE
      On the build machine, right after build_bundle.sh: writes the provenance record
      (flh-candidate-provenance/v1) of what was built from which commit. Refuses a bundle whose
      MANIFEST names another commit.
  candidate.py promote-check BUNDLE --provenance FILE [--sha256 SHA]
      PROMOTE (exit 0) only when every field of the provenance record equals the bundle's own
      identity, and the SHA-256 the operator typed (when given) equals both; else REFUSED (exit 1)
      naming each disagreeing field.
  candidate.py gate --caller-identity FILE --allowed-account-sha256 HEX --region R --env E [--workspace W]
      FILE holds `aws sts get-caller-identity --output json` (the owner runs it). PASS (exit 0)
      only for the allowed account (compared by SHA-256, so no account ID is stored or printed),
      region us-east-1, an environment staging|production and, when given, the matching Terraform
      workspace (production only in `production`). Prints field names and PASS/FAIL, never the ID.
  candidate.py vars --tfvars FILE [--root DIR] [--json]
      The effective value of every variable in variables.tf with its source: -var-file (FILE),
      an auto-loaded file in the root (terraform.tfvars, *.auto.tfvars), a TF_VAR_ environment
      variable, the declared default, or the environment's local default (null defaults). Values
      that look like an account ID, ARN or key are redacted. Exit 1 when a value would arrive
      silently: from a TF_VAR_ variable or an auto-loaded file that is not FILE.
  candidate.py authorize --tfvars FILE --bundle TAR [--sha256 SHA] [--provenance FILE] [--hours N]
      DRY RUN: prints the material the owner authorizes (environment, region, workspace, run and
      expiry, runtime bound, shape, data volume, estimated cost, candidate identity, IAM policies,
      the approvals it needs and the exact commands), and runs nothing. Exit 1 when vars or
      promote-check refuse.
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
STAGING = os.path.dirname(HERE)
TF = os.path.join(STAGING, "terraform")
FORMAT_IDENTITY = "flh-candidate-identity/v1"
FORMAT_PROVENANCE = "flh-candidate-provenance/v1"
NAME_RE = re.compile(r"^flh-staging-[0-9a-f]{12}$")
ENV_DEFAULTS = {  # the null-default variables resolved by main.tf locals (keep in step with main.tf)
    "staging": {"vpc_cidr": "10.85.0.0/24", "data_volume_size_gib": "8",
                "host_role_permissions_boundary_name": "flh-stg-host-boundary"},
    "production": {"vpc_cidr": "10.86.0.0/24", "data_volume_size_gib": "20",
                   "host_role_permissions_boundary_name": "flh-prd-host-boundary"},
}
IDENTITY_FIELDS = ("bundle", "tar_sha256", "commit", "tree", "content_sha256", "image_id", "image_platform",
                   "server_sha256", "web_files_sha256", "migrations")
SENSITIVE = [(re.compile(r"\b\d{12}\b"), "<account-id>"), (re.compile(r"arn:aws[^\s\"']*"), "<arn>"),
             (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "<access-key>"), (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "<key>")]


class Refused(Exception):
    pass


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def redact(text):
    for rx, rep in SENSITIVE:
        text = rx.sub(rep, text)
    return text


# --- bundle reading ---------------------------------------------------------------------------------
class Bundle:
    """Read-only access to a bundle tar or directory: named members as bytes."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.is_tar = os.path.isfile(self.path) and self.path.endswith(".tar")
        if self.is_tar:
            self.name = os.path.basename(self.path)[:-4]
            self.tf = tarfile.open(self.path)
        elif os.path.isdir(self.path):
            self.name = os.path.basename(self.path.rstrip("/"))
            self.tf = None
        else:
            raise Refused(f"{path} is neither a bundle .tar nor a bundle directory")
        if not NAME_RE.match(self.name):
            raise Refused(f"{self.name} is not a bundle name (flh-staging-<tree12>)")

    def read(self, rel):
        if self.tf:
            try:
                m = self.tf.getmember(f"{self.name}/{rel}")
            except KeyError:
                raise Refused(f"the bundle has no {rel}")
            return self.tf.extractfile(m).read()
        p = os.path.join(self.path, rel)
        if not os.path.isfile(p):
            raise Refused(f"the bundle has no {rel}")
        with open(p, "rb") as fh:
            return fh.read()

    def tar_sha256(self):
        if not self.tf:
            side = self.path.rstrip("/") + ".tar"
            return sha256_file(side) if os.path.isfile(side) else None
        return sha256_file(self.path)

    def recorded_sha256(self):
        side = (self.path if self.tf else self.path.rstrip("/") + ".tar") + ".sha256"
        if os.path.isfile(side):
            with open(side) as fh:
                parts = fh.read().split()
            return parts[0] if parts else None
        return None


def image_platform(image_tar_bytes):
    with tarfile.open(fileobj=io.BytesIO(image_tar_bytes)) as it:
        man = json.loads(it.extractfile("manifest.json").read())
        cfg = json.loads(it.extractfile(man[0]["Config"]).read())
    return f"{cfg.get('os')}/{cfg.get('architecture')}"


def runtime_contract(compose_text, daily_text):
    """What the bundle needs from its host, read from its own compose.yaml and wrapper."""
    app = re.search(r"^  app:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)", compose_text, re.S | re.M)
    body = app.group(1) if app else ""
    env = re.search(r"^    environment:\n((?:^      .*\n)+)", body, re.M)
    env_names = sorted(re.findall(r"^      ([A-Z][A-Z0-9_]+):", env.group(1), re.M)) if env else []
    ports = re.findall(r'^\s+- "([^"]+)"', body.split("environment:")[0], re.M)
    health = re.search(r"healthcheck:\n\s+test: (.+)", body)
    user = re.search(r'^    user: "?([^"\n]+)"?', body, re.M)
    restart = re.search(r"^    restart: (\S+)", body, re.M)
    # always-required settings: the explicit `for key in (...)` list and FLH_DATA_DIR ("must be set in the
    # settings file"); conditional ones (a model or key once a provider is enabled) are not listed
    required = set()
    for group in re.findall(r'^for key in \(([^)]*)\):', daily_text, re.M):
        required |= set(re.findall(r'"([A-Z][A-Z0-9_]+)"', group))
    required |= set(re.findall(r'problems\.append\("([A-Z][A-Z0-9_]+) must be set in the settings file', daily_text))
    required = sorted(required)
    return {"user": user.group(1) if user else None, "published": ports, "forwarded_settings": env_names,
            "healthcheck": health.group(1).strip() if health else None, "restart": restart.group(1) if restart else None,
            "settings_required_by_wrapper": required, "endpoints": {"liveness": "/healthz", "readiness": "/readyz"}}


def identity(path):
    b = Bundle(path)
    m = json.loads(b.read("MANIFEST.json"))
    build = json.loads(b.read("BUILD.json"))
    if m.get("name") != b.name:
        raise Refused(f"MANIFEST names {m.get('name')!r}, the bundle is {b.name}")
    plat = image_platform(b.read("image.tar"))
    try:
        compose = b.read("repo/compose.yaml").decode()
        daily = b.read("repo/scripts/daily/flh-daily.sh").decode()
    except Refused:
        compose, daily = "", ""
    return {"format": FORMAT_IDENTITY, "bundle": b.name, "tar_sha256": b.tar_sha256(),
            "recorded_sha256": b.recorded_sha256(), "commit": m["revision"].get("commit"),
            "tree": m["revision"]["tree_id"], "content_sha256": m["revision"].get("content_sha256"),
            "image_id": build.get("image_id"), "image_platform": plat,
            "manifest_platform": (m.get("image") or {}).get("platform"),
            "server_sha256": m.get("server_sha256"), "web_files_sha256": m.get("web_files_sha256"),
            "migrations": m.get("migrations"), "runtime": runtime_contract(compose, daily)}


# --- commands ---------------------------------------------------------------------------------------
def cmd_identity(a):
    ident = identity(a.bundle)
    if a.json:
        print(json.dumps(ident, indent=1, sort_keys=True))
        return 0
    for k in IDENTITY_FIELDS:
        print(f"{k:18} {ident[k] if k != 'migrations' else json.dumps(ident[k], sort_keys=True)}")
    print(f"{'manifest_platform':18} {ident['manifest_platform']}")
    rt = ident["runtime"]
    print(f"{'runtime':18} user {rt['user']}; published {rt['published']}; restart {rt['restart']}; "
          f"{len(rt['forwarded_settings'])} forwarded settings; wrapper requires {rt['settings_required_by_wrapper']}")
    if ident["recorded_sha256"] and ident["tar_sha256"] and ident["recorded_sha256"] != ident["tar_sha256"]:
        print("WARN: the .sha256 beside the bundle does not match the tar")
        return 1
    return 0


def cmd_provenance(a):
    ident = identity(a.bundle)
    if not re.fullmatch(r"[0-9a-f]{40}", a.commit or ""):
        raise Refused("--commit must be the 40-hex commit the bundle was built from")
    if ident["commit"] != a.commit:
        raise Refused(f"the bundle's MANIFEST names commit {ident['commit']}, not {a.commit}")
    rec = {"format": FORMAT_PROVENANCE, **{k: ident[k] for k in IDENTITY_FIELDS}}
    if os.path.exists(a.out):
        raise Refused(f"{a.out} exists; a provenance record is written once")
    with open(a.out, "w") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"wrote {a.out}: {ident['bundle']} commit {ident['commit'][:12]} tree {ident['tree'][:12]} "
          f"tar {ident['tar_sha256'][:16]}")
    return 0


def promote_problems(ident, prov, typed_sha=None):
    probs = []
    if prov.get("format") != FORMAT_PROVENANCE:
        probs.append(f"provenance format {prov.get('format')!r} is not {FORMAT_PROVENANCE}")
    for k in IDENTITY_FIELDS:
        if prov.get(k) != ident.get(k):
            probs.append(f"{k}: bundle {short(ident.get(k))} != provenance {short(prov.get(k))}")
    if ident.get("manifest_platform") != ident.get("image_platform"):
        probs.append(f"MANIFEST platform {ident.get('manifest_platform')} != image {ident.get('image_platform')}")
    if typed_sha is not None and typed_sha != ident.get("tar_sha256"):
        probs.append(f"the typed SHA-256 {short(typed_sha)} is not the bundle's {short(ident.get('tar_sha256'))}")
    return probs


def short(v):
    if isinstance(v, dict):
        return json.dumps(v, sort_keys=True)
    return (v[:16] + "…") if isinstance(v, str) and len(v) > 20 else repr(v)


def cmd_promote_check(a):
    ident = identity(a.bundle)
    with open(a.provenance) as fh:
        prov = json.load(fh)
    probs = promote_problems(ident, prov, a.sha256)
    for p in probs:
        print(f"MISMATCH {p}")
    if probs:
        print(f"REFUSED: {ident['bundle']} disagrees with its provenance record in {len(probs)} field(s); do not promote")
        return 1
    print(f"PROMOTE: {ident['bundle']} equals its provenance record (commit {ident['commit'][:12]}, "
          f"tree {ident['tree'][:12]}, image {ident['image_id'][:19]}, {ident['image_platform']})")
    return 0


def gate_results(caller, allowed_sha, region, env, workspace=None):
    res = []
    acct = str(caller.get("Account", ""))
    res.append(("account", bool(acct) and hashlib.sha256(acct.encode()).hexdigest() == allowed_sha.lower(),
                "the caller's account is the allowed one (compared by SHA-256)"))
    res.append(("region", region == "us-east-1", "region us-east-1 (the IAM templates and AMI pin name it)"))
    res.append(("environment", env in ("staging", "production"), "environment is staging or production"))
    if workspace is not None:
        ok = (env == "production") == (workspace == "production")
        res.append(("workspace", ok, "production only in the workspace production, staging never there"))
    arn = str(caller.get("Arn", ""))
    res.append(("principal", ":assumed-role/" in arn or ":user/" in arn, "the caller is a user or an assumed role"))
    return res


def cmd_gate(a):
    with open(a.caller_identity) as fh:
        caller = json.load(fh)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", a.allowed_account_sha256):
        raise Refused("--allowed-account-sha256 must be 64 hex characters (sha256 of the 12-digit account ID)")
    res = gate_results(caller, a.allowed_account_sha256, a.region, a.env, a.workspace)
    for name, ok, what in res:
        print(f"{'PASS' if ok else 'FAIL'} {name:12} {what}")
    bad = [n for n, ok, _ in res if not ok]
    print("GATE PASSED: live commands may be prepared" if not bad else
          f"GATE FAILED ({', '.join(bad)}): prepare no live command")
    return 0 if not bad else 1


def tf_variables():
    with open(os.path.join(TF, "variables.tf")) as fh:
        text = fh.read()
    out = {}
    for m in re.finditer(r'variable\s+"([^"]+)"\s*\{(.*?)\n\}', text, re.S):
        d = re.search(r'^\s*default\s*=\s*("(?:[^"\\]|\\.)*"|[0-9.]+|true|false|null)\s*$', m.group(2), re.M)
        out[m.group(1)] = None if d is None else d.group(1).strip('"')
    return out


def parse_tfvars(path):
    vals = {}
    with open(path) as fh:
        for line in fh:
            m = re.match(r'\s*([a-z_][a-z0-9_]*)\s*=\s*(".*?"|[0-9.]+|true|false)\s*(#.*)?$', line)
            if m:
                vals[m.group(1)] = m.group(2).strip('"')
    return vals


def effective_vars(tfvars, root=TF, environ=None):
    """[(name, value, source)] in Terraform's order: defaults < terraform.tfvars < *.auto.tfvars < -var-file < TF_VAR_."""
    environ = os.environ if environ is None else environ
    decl = tf_variables()
    layers = []
    auto = sorted(f for f in (os.listdir(root) if os.path.isdir(root) else [])
                  if f == "terraform.tfvars" or f.endswith(".auto.tfvars"))
    given = os.path.realpath(tfvars) if tfvars else None
    for f in auto:
        p = os.path.realpath(os.path.join(root, f))
        if p != given:
            layers.append((f"auto-loaded {f}", parse_tfvars(p)))
    if tfvars:
        layers.append((f"-var-file {os.path.basename(tfvars)}", parse_tfvars(tfvars)))
    env_layer = {k[len("TF_VAR_"):]: v for k, v in environ.items() if k.startswith("TF_VAR_")}
    rows, silent = [], []
    env_name = "staging"
    for name in decl:
        value, source = decl[name], "default"
        for label, vals in layers:
            if name in vals:
                value, source = vals[name], label
        if name in env_layer:
            value, source = env_layer[name], f"environment TF_VAR_{name}"
        if name == "environment" and value:
            env_name = value
        rows.append([name, value, source])
        if source.startswith(("auto-loaded", "environment")):
            silent.append(f"{name} from {source}")
    for row in rows:
        if row[1] in (None, "null") and row[0] in ENV_DEFAULTS.get(env_name, {}):
            row[1], row[2] = ENV_DEFAULTS[env_name][row[0]], f"environment default ({env_name}, main.tf locals)"
    unknown = sorted(set(env_layer) - set(decl))
    return rows, silent, env_name, unknown


def cmd_vars(a):
    rows, silent, env_name, unknown = effective_vars(a.tfvars, a.root)
    if a.json:
        print(json.dumps({"environment": env_name, "variables": [{"name": n, "value": redact(str(v)) if v is not None else None,
                                                                    "source": s} for n, v, s in rows],
                          "silent": silent, "unknown_tf_var": unknown}, indent=1, sort_keys=True))
    else:
        for n, v, s in rows:
            shown = "(unset: required)" if v is None else redact(str(v))
            print(f"{n:38} {shown[:44]:44} {s}")
    for s in silent:
        print(f"REFUSE silent input: {s} (pass every value in the one -var-file you reviewed)")
    for u in unknown:
        print(f"REFUSE unknown TF_VAR_{u}: not a variable of this root")
    return 1 if silent or unknown else 0


def cmd_authorize(a):
    rows, silent, env_name, unknown = effective_vars(a.tfvars, a.root)
    v = {n: val for n, val, _ in rows}
    ident = identity(a.bundle)
    probs = list(silent) + [f"unknown TF_VAR_{u}" for u in unknown]
    if a.provenance:
        with open(a.provenance) as fh:
            probs += promote_problems(ident, json.load(fh), a.sha256)
    elif a.sha256 and a.sha256 != ident["tar_sha256"]:
        probs.append("the typed SHA-256 is not the bundle's")
    missing = [n for n, val, _ in rows if val is None]
    probs += [f"variable {n} unset" for n in missing]
    with open(os.path.join(STAGING, "cost_assumptions.json")) as fh:
        rates = json.load(fh)
    hours = a.hours if env_name == "staging" else 24 * 30
    itype = v.get("instance_type") or "t3.small"
    inst = rates["rates"]["instance_hour"]["by_type"].get(itype)
    gib = 16 + float(v.get("data_volume_size_gib") or 8)
    cost = None if inst is None else round(hours * (inst + rates["rates"]["public_ipv4_hour"]["rate"])
                                           + gib * rates["rates"]["gp3_gb_month"]["rate"] * hours / 730
                                           + rates["rates"]["per_resource_month"]["aws_s3_bucket"]["rate"], 2)
    prefix = "flh-stg" if env_name == "staging" else "flh-prd"
    out_dir = "out" if env_name == "staging" else "out-production"
    pol_dir = os.path.join(STAGING, "iam", out_dir)
    pols = sorted(f for f in os.listdir(pol_dir) if f.endswith("-policy.json")) if os.path.isdir(pol_dir) else []
    ws = "production" if env_name == "production" else "default"
    plan = "prd" if env_name == "production" else "stg"
    print("DRY RUN: nothing below was executed. Authorization material for the owner:")
    print(f"  environment      {env_name} (Terraform workspace: {ws}); region {redact(str(v.get('aws_region')))}")
    print(f"  run / expiry     {v.get('run_id')} / {v.get('expires_at')}; runtime bound "
          f"{v.get('max_runtime_hours') if env_name == 'staging' else 'none (production)'} h")
    print(f"  shape            {itype}, data volume {v.get('data_volume_size_gib')} GiB, VPC {v.get('vpc_cidr')}")
    print(f"  estimate         {'unknown for ' + itype if cost is None else f'about ${cost:.2f}'} for "
          f"{hours:g} h at the {rates.get('as_of')} list prices (confirm in the AWS calculator)")
    print(f"  candidate        {ident['bundle']} commit {ident['commit']} tree {ident['tree'][:12]} "
          f"{ident['image_platform']} migrations {ident['migrations']['count']}")
    print(f"  transfer sha256  {ident['tar_sha256']}")
    print(f"  IAM (admin)      {', '.join(p[:-len('-policy.json')] for p in pols)} from iam/{out_dir} (render_policies.py)")
    print(f"  approvals        {'A2 (budget, runtime, account, synthetic scope) + A3 (IAM)' if env_name == 'staging' else 'A7 (design) + A8 (budget, apply)'}")
    print("  commands (after approval; from deploy/aws/private-staging/staging/terraform):")
    for c in (f"terraform workspace select {ws}" + (" || terraform workspace new production" if ws == "production" else ""),
              f"terraform plan -var-file={os.path.basename(a.tfvars)} -out {plan}.tfplan",
              f"terraform show -json {plan}.tfplan > {plan}.plan.json",
              f"python3 -I ../tools/plan_check.py --env {env_name} --mode create {plan}.plan.json",
              f"python3 -I ../tools/plan_review.py checklist {plan}.plan.json",
              f"python3 -I ../tools/plan_review.py freshness {plan}.plan.json --tfvars {os.path.basename(a.tfvars)}",
              f"terraform apply {plan}.tfplan"):
        print(f"    {c}")
    for p in probs:
        print(f"REFUSE {p}")
    print("AUTHORIZATION MATERIAL READY (dry run)" if not probs else
          f"NOT READY: {len(probs)} problem(s) above; fix them before asking for approval")
    return 0 if not probs else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("identity"); s.add_argument("bundle"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("provenance"); s.add_argument("bundle"); s.add_argument("--commit", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("promote-check"); s.add_argument("bundle"); s.add_argument("--provenance", required=True)
    s.add_argument("--sha256")
    s = sub.add_parser("gate"); s.add_argument("--caller-identity", required=True)
    s.add_argument("--allowed-account-sha256", required=True); s.add_argument("--region", required=True)
    s.add_argument("--env", required=True); s.add_argument("--workspace")
    s = sub.add_parser("vars"); s.add_argument("--tfvars"); s.add_argument("--root", default=TF)
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("authorize"); s.add_argument("--tfvars", required=True); s.add_argument("--bundle", required=True)
    s.add_argument("--sha256"); s.add_argument("--provenance"); s.add_argument("--hours", type=float, default=4)
    s.add_argument("--root", default=TF)
    a = ap.parse_args()
    try:
        return {"identity": cmd_identity, "provenance": cmd_provenance, "promote-check": cmd_promote_check,
                "gate": cmd_gate, "vars": cmd_vars, "authorize": cmd_authorize}[a.cmd](a)
    except Refused as e:
        print(f"candidate: REFUSED: {e}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError) as e:
        print(f"candidate: cannot read input: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
