#!/usr/bin/env python3
"""Offline review of owner-supplied staging plans (`terraform show -json`). Never runs Terraform.

  plan_review.py summary PLAN [--json]
      Every change grouped by service and blast radius.
  plan_review.py diff A B [--json]
      Normalized structural diff of two plans: addresses only in one, action changes, and attribute
      changes by path, grouped by service and blast radius. Ignored because they do not change what
      apply does: the order of resource_changes, prior_state, configuration, planned_values, and
      values known only after apply (shown as "(known after apply)"). terraform_version and
      timestamp are reported apart. Exit 0 same changes, 1 different, 2 unreadable.
  plan_review.py cost PLAN [--assumptions FILE] [--hours N]
      Counts come from the plan only; rates come from the assumptions file only
      (staging/cost_assumptions.json). Prints both, the estimate for N hours (default 4) and
      for 30 days, every resource type with no assumption, and every unused assumption.
  plan_review.py checklist PLAN [--json]
      The settings the owner confirms before applying (RUNBOOK §3.2), each read from the plan as one of:
      SET (a value, checked against what staging needs), KNOWN AFTER APPLY (the plan marks it unknown:
      confirm it on the created resource), OMITTED (null in the plan: the configuration leaves it
      unset on purpose, for example no SSH key) or ABSENT (the resource is not in the plan). Exit 0
      when nothing is wrong (unknowns are listed to confirm), 1 when a SET value is wrong or a
      required resource is absent, 2 when the plan is unreadable.
  plan_review.py stamp PLAN --tfvars FILE
      Writes PLAN-stem.plan-stamp.json beside the plan (ignored by Git): the SHA-256 of the plan
      and of every input it was made from (*.tf, the files main.tf reads, the tfvars, the lock).
  plan_review.py freshness PLAN --tfvars FILE
      STALE (exit 1) when the reviewed plan predates its inputs: with a stamp, any input or the
      plan itself changed since; without one, an input file is newer than the plan (its
      `timestamp`, else the file's modification time; a weaker signal, said so). Either way, a
      variable recorded in the plan that differs from tfvars (or the default) is STALE.

Blast radius, most severe first:
  data-loss  delete or replace of a resource that holds data (bucket, data volume)
  access     IAM, security groups and rules, bucket policy, public access block, ownership, and
             every public path type in expected_resources.json (EIP, load balancer, DNS, ...)
  service    the host and its volume attachment (replace = restart on a new instance)
  data       any other change to a resource that holds data, or to the bucket's settings
  network    VPC, subnet, routes, gateway, endpoint
  metadata   only tags differ
  other      anything else
  none       no-op and data-source reads
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STAGING = os.path.dirname(HERE)
TF = os.path.join(STAGING, "terraform")
EXPECTED = os.path.join(STAGING, "expected_resources.json")
ASSUMPTIONS = os.path.join(STAGING, "cost_assumptions.json")
# Stable verdicts (docs/RELEASE.md "Reason codes"; scripts/release/test_reason_codes.py pins them).
VERDICTS = ("SAME", "DIFFERENT", "FRESH", "STALE", "NOT COSTED")
RADII = ["data-loss", "access", "service", "data", "network", "metadata", "other", "none"]
SERVICES = [("aws_vpc_security_group_", "VPC security"), ("aws_security_group", "VPC security"),
            ("aws_s3_", "S3"), ("aws_iam_", "IAM"), ("aws_instance", "EC2"), ("aws_ebs_", "EC2"),
            ("aws_volume_attachment", "EC2"), ("aws_ec2_", "EC2"), ("aws_vpc", "VPC network"),
            ("aws_subnet", "VPC network"), ("aws_route", "VPC network"), ("aws_internet_gateway", "VPC network"),
            ("aws_eip", "EC2"), ("aws_lb", "ELB"), ("aws_alb", "ELB"), ("aws_route53_", "Route 53"),
            ("aws_cloudfront_", "CloudFront"), ("aws_api", "API Gateway"), ("aws_caller_identity", "STS")]
ACCESS = {"aws_s3_bucket_policy", "aws_s3_bucket_public_access_block", "aws_s3_bucket_ownership_controls",
          "aws_s3_bucket_acl", "aws_security_group", "aws_security_group_rule"}
SERVICE = {"aws_instance", "aws_volume_attachment"}
NETWORK = ("aws_vpc", "aws_subnet", "aws_route", "aws_internet_gateway", "aws_eip", "aws_lb", "aws_route53")
UNKNOWN = "(known after apply)"


def die(msg):
    print(f"plan_review: {msg}", file=sys.stderr)
    sys.exit(2)


def load(path):
    try:
        with open(path) as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        die(f"cannot read {path}: {e}")
    if not isinstance(doc, dict) or "format_version" not in doc or "resource_changes" not in doc:
        die(f"{path} is not a `terraform show -json` plan (no format_version/resource_changes)")
    return doc


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def action_kind(actions):
    a = list(actions or [])
    if sorted(a) == ["create", "delete"]:
        return "replace"
    return "+".join(a) or "?"


def service_of(rtype):
    for prefix, name in SERVICES:
        if rtype.startswith(prefix):
            return name
    return rtype.split("_")[1].upper() if rtype.startswith("aws_") and "_" in rtype[4:] else "other"


def holds_data(expected):
    return {a for a, m in expected.get("managed", {}).items() if m.get("holds_data")}


def radius(address, rtype, mode, kind, data_addrs, paths=None, public=()):
    if mode == "data" or kind in ("no-op", "read"):
        return "none"
    if address in data_addrs and kind in ("delete", "replace"):
        return "data-loss"
    if paths and all(re.match(r"(tags|tags_all)(\.|\[|$)", p) for p in paths):
        return "metadata"
    if rtype.startswith("aws_iam_") or rtype in ACCESS or rtype.startswith("aws_vpc_security_group_") or rtype in public:
        return "access"
    if rtype in SERVICE:
        return "service"
    if address in data_addrs or rtype.startswith("aws_s3_bucket_"):
        return "data"           # the bucket's encryption, versioning and lifecycle govern its objects
    if rtype.startswith(NETWORK):
        return "network"
    return "other"


def mask_unknown(after, unknown):
    """Values Terraform knows only after apply become one marker, so two plans compare equal there."""
    if unknown is True:
        return UNKNOWN
    if isinstance(after, dict) or isinstance(unknown, dict):
        a, u = after if isinstance(after, dict) else {}, unknown if isinstance(unknown, dict) else {}
        return {k: mask_unknown(a.get(k), u.get(k)) for k in sorted(set(a) | {k for k, v in u.items() if v})}
    if isinstance(after, list) and isinstance(unknown, list):
        return [mask_unknown(x, unknown[i] if i < len(unknown) else None) for i, x in enumerate(after)]
    return after


def normalize(plan):
    out = {}
    for rc in plan.get("resource_changes") or []:
        ch = rc.get("change") or {}
        out[rc.get("address", "?")] = {
            "mode": rc.get("mode", "managed"), "type": rc.get("type", ""),
            "action": action_kind(ch.get("actions")), "action_reason": rc.get("action_reason"),
            "after": mask_unknown(ch.get("after"), ch.get("after_unknown")),
            "replace_paths": ch.get("replace_paths")}
    return out


def flatten(obj, prefix=""):
    if isinstance(obj, dict):
        if not obj:
            return {prefix: {}} if prefix else {}
        out = {}
        for k in sorted(obj):
            out.update(flatten(obj[k], f"{prefix}.{k}" if prefix else k))
        return out
    if isinstance(obj, list):
        if not obj:
            return {prefix: []}
        out = {}
        for i, x in enumerate(obj):
            out.update(flatten(x, f"{prefix}[{i}]"))
        return out
    return {prefix: obj}


def short(v, n=48):
    s = json.dumps(v, sort_keys=True) if not isinstance(v, str) else v
    return s if len(s) <= n else s[:n - 3] + "..."


# --- summary ---------------------------------------------------------------------------------------
def summarize(plan, expected):
    data_addrs = holds_data(expected)
    rows = []
    for addr, r in sorted(normalize(plan).items()):
        rows.append({"address": addr, "service": service_of(r["type"]), "action": r["action"],
                     "radius": radius(addr, r["type"], r["mode"], r["action"], data_addrs,
                                      public=set(expected.get("public_path_types", [])))})
    return rows


def print_groups(rows, detail):
    for rad in RADII:
        sel = [r for r in rows if r["radius"] == rad]
        if not sel:
            continue
        print(f"[{rad}] {len(sel)}")
        for svc in sorted({r["service"] for r in sel}):
            group = [r for r in sel if r["service"] == svc]
            acts = {}
            for r in group:
                acts[r["action"]] = acts.get(r["action"], 0) + 1
            print(f"  {svc}: " + ", ".join(f"{n} {a}" for a, n in sorted(acts.items())))
            for r in group:
                for line in detail(r):
                    print(f"    {line}")


def cmd_summary(a):
    plan, expected = load(a.plan), json.load(open(EXPECTED))
    rows = summarize(plan, expected)
    if a.json:
        print(json.dumps({"plan": os.path.basename(a.plan), "changes": rows}, indent=1))
        return 0
    counts = {}
    for r in rows:
        counts[r["radius"]] = counts.get(r["radius"], 0) + 1
    print(f"plan {os.path.basename(a.plan)}: {len(rows)} entries; " + ", ".join(f"{counts[k]} {k}" for k in RADII if k in counts))
    print_groups(rows, lambda r: [f"{r['action']:<8} {r['address']}"] if r["radius"] != "none" else [])
    return 0


# --- diff ------------------------------------------------------------------------------------------
def diff(pa, pb, expected):
    na, nb = normalize(pa), normalize(pb)
    data_addrs, public = holds_data(expected), set(expected.get("public_path_types", []))
    rows = []
    for addr in sorted(set(na) | set(nb)):
        a, b = na.get(addr), nb.get(addr)
        ref = b or a
        if a is None or b is None:
            rows.append({"address": addr, "service": service_of(ref["type"]), "change": "only in B" if a is None else "only in A",
                         "action": ref["action"], "paths": [],
                         "radius": radius(addr, ref["type"], ref["mode"], ref["action"], data_addrs, public=public)})
            continue
        fa, fb = flatten(a["after"] or {}), flatten(b["after"] or {})
        paths = [{"path": p, "a": fa.get(p), "b": fb.get(p)} for p in sorted(set(fa) | set(fb)) if fa.get(p) != fb.get(p)
                 or (p in fa) != (p in fb)]
        meta = [k for k in ("action", "action_reason", "replace_paths") if a[k] != b[k]]
        if not paths and not meta:
            continue
        kind = b["action"] if b["action"] not in ("no-op", "read") or a["action"] in ("no-op", "read") else a["action"]
        rows.append({"address": addr, "service": service_of(ref["type"]),
                     "change": f"action {a['action']} -> {b['action']}" if "action" in meta else "attributes",
                     "action": b["action"], "meta": {k: [a[k], b[k]] for k in meta}, "paths": paths,
                     "radius": radius(addr, ref["type"], ref["mode"], kind, data_addrs,
                                      [p["path"] for p in paths] if not meta else None, public=public)})
    header = {k: [pa.get(k), pb.get(k)] for k in ("terraform_version", "timestamp", "format_version") if pa.get(k) != pb.get(k)}
    return rows, header


def cmd_diff(a):
    pa, pb, expected = load(a.a), load(a.b), json.load(open(EXPECTED))
    rows, header = diff(pa, pb, expected)
    if a.json:
        print(json.dumps({"a": os.path.basename(a.a), "b": os.path.basename(a.b), "same": not rows,
                          "header": header, "differences": rows}, indent=1, sort_keys=True))
        return 0 if not rows else 1
    print(f"A {os.path.basename(a.a)}\nB {os.path.basename(a.b)}")
    for k, (x, y) in header.items():
        print(f"  (not compared) {k}: {x} -> {y}")
    if not rows:
        print("SAME: the two plans make the same changes")
        return 0
    counts = {}
    for r in rows:
        counts[r["radius"]] = counts.get(r["radius"], 0) + 1
    print(f"DIFFERENT: {len(rows)} address(es); " + ", ".join(f"{counts[k]} {k}" for k in RADII if k in counts))

    def detail(r):
        lines = [f"{r['address']}: {r['change']}"]
        for p in r["paths"][:12]:
            lines.append(f"  {p['path']}: {short(p['a'])} -> {short(p['b'])}")
        if len(r["paths"]) > 12:
            lines.append(f"  ... {len(r['paths']) - 12} more path(s) (--json shows all)")
        return lines
    print_groups(rows, detail)
    return 1


# --- cost ------------------------------------------------------------------------------------------
def counts_from_plan(plan):
    """What will exist after apply (create, update, replace, no-op): types, instance types, sizes."""
    out = {"types": {}, "instances": {}, "public_ipv4": 0, "gp3_gib": 0, "unknown_sizes": []}
    for rc in plan.get("resource_changes") or []:
        if rc.get("mode") == "data":
            continue
        kind = action_kind((rc.get("change") or {}).get("actions"))
        if kind == "delete":
            continue
        after = (rc.get("change") or {}).get("after") or {}
        t = rc.get("type", "")
        out["types"][t] = out["types"].get(t, 0) + 1
        if t == "aws_instance":
            it = after.get("instance_type") or "?"
            out["instances"][it] = out["instances"].get(it, 0) + 1
            if after.get("associate_public_ip_address"):
                out["public_ipv4"] += 1
            for rb in after.get("root_block_device") or []:
                if isinstance(rb.get("volume_size"), (int, float)):
                    out["gp3_gib"] += rb["volume_size"]
                else:
                    out["unknown_sizes"].append(f"{rc['address']} root volume")
        if t == "aws_ebs_volume":
            if isinstance(after.get("size"), (int, float)):
                out["gp3_gib"] += after["size"]
            else:
                out["unknown_sizes"].append(rc["address"])
    return out


def cmd_cost(a):
    plan = load(a.plan)
    try:
        with open(a.assumptions) as fh:
            asm = json.load(fh)
    except (OSError, ValueError) as e:
        die(f"cannot read {a.assumptions}: {e}")
    c = counts_from_plan(plan)
    r = asm["rates"]
    month = 730.0
    print(f"counts (from the plan {os.path.basename(a.plan)}; what exists after apply):")
    for t, n in sorted(c["types"].items()):
        print(f"  {n} {t}")
    print(f"  instance types {c['instances'] or '{}'}; public IPv4 {c['public_ipv4']}; gp3 {c['gp3_gib']} GiB")
    print(f"assumptions (from {os.path.basename(a.assumptions)}; {asm['region']}, {asm['currency']}, as of {asm['as_of']}):")
    print(f"  source: {asm['source']}")
    try:
        age = (datetime.date.today() - datetime.date.fromisoformat(asm["as_of"])).days
    except ValueError:
        age = None
    lines, used, uncosted = [], set(), []
    for it, n in sorted(c["instances"].items()):
        rate = r["instance_hour"]["by_type"].get(it)
        if rate is None:
            uncosted.append(f"aws_instance {it} (no hourly rate)")
            continue
        used.add("instance_hour")
        lines.append((f"{n} x {it} instance", n * rate, f"{rate}/h"))
    if c["public_ipv4"]:
        used.add("public_ipv4_hour")
        lines.append((f"{c['public_ipv4']} public IPv4", c["public_ipv4"] * r["public_ipv4_hour"]["rate"], f"{r['public_ipv4_hour']['rate']}/h"))
    if c["gp3_gib"]:
        used.add("gp3_gb_month")
        g = r["gp3_gb_month"]["rate"]
        lines.append((f"{c['gp3_gib']} GiB gp3", c["gp3_gib"] * g / month, f"{g}/GB-month"))
    for t, spec in sorted(r.get("per_resource_month", {}).items()):
        if t in c["types"]:
            used.add(f"per_resource_month:{t}")
            lines.append((f"{c['types'][t]} {t}", c["types"][t] * spec["rate"] / month, f"{spec['rate']}/month (bound)"))
    free = set(r.get("free", []))
    for t in sorted(c["types"]):
        if t in free:
            used.add(f"free:{t}")
        elif t not in ("aws_instance", "aws_ebs_volume") and t not in r.get("per_resource_month", {}):
            uncosted.append(t)
    uncosted += [f"{u} (size unknown in the plan)" for u in c["unknown_sizes"]]
    print(f"estimate ({a.hours:g} h | 30 days):")
    tot = 0.0
    for label, hourly, rate in lines:
        tot += hourly
        print(f"  {label:<34} {rate:<34} ${hourly * a.hours:7.2f} | ${hourly * month:7.2f}")
    print(f"  {'total':<34} {'':<34} ${tot * a.hours:7.2f} | ${tot * month:7.2f}")
    print(f"  free by assumption: {', '.join(sorted(t for t in c['types'] if t in free)) or 'none'}")
    declared = {"instance_hour", "public_ipv4_hour", "gp3_gb_month"} | {f"per_resource_month:{t}" for t in r.get("per_resource_month", {})}
    unused = sorted(k for k in declared if k not in used) + sorted(f"free:{t}" for t in free if t not in c["types"])
    if unused:
        print(f"  assumptions with nothing to apply to: {', '.join(unused)}")
    if age is not None and age > 90:
        print(f"WARN assumptions are {age} days old: confirm the rates in the AWS Pricing Calculator")
    if uncosted:
        print(f"NOT COSTED: {', '.join(uncosted)}: add an assumption (or mark it free) before trusting the total")
        return 1
    print("every planned resource type is costed or free by assumption")
    return 0


# --- stamp and freshness -----------------------------------------------------------------------------
def config_inputs(tfvars):
    """Every file the plan was made from: the root's *.tf, what main.tf reads, the tfvars, the lock."""
    files = sorted(os.path.join(TF, f) for f in os.listdir(TF) if f.endswith(".tf"))
    with open(os.path.join(TF, "main.tf")) as fh:
        main_tf = fh.read()
    for ref in re.findall(r'(?:file|templatefile)\("\$\{path\.module\}/([^"]+)"', main_tf):
        files.append(os.path.normpath(os.path.join(TF, ref)))
    lock = os.path.join(TF, ".terraform.lock.hcl")
    if os.path.isfile(lock):
        files.append(lock)
    out = {os.path.relpath(f, STAGING): f for f in sorted(set(files))}
    out["tfvars:" + os.path.basename(tfvars)] = tfvars
    return out


def stamp_path(plan):
    base = plan[:-len(".plan.json")] if plan.endswith(".plan.json") else os.path.splitext(plan)[0]
    return base + ".plan-stamp.json"


def cmd_stamp(a):
    load(a.plan)
    if not os.path.isfile(a.tfvars):
        die(f"{a.tfvars} missing")
    ins = config_inputs(a.tfvars)
    doc = {"format": "flh-plan-stamp/v1", "plan": os.path.basename(a.plan), "plan_sha256": sha_file(a.plan),
           "stamped_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "inputs": {k: sha_file(p) for k, p in ins.items()}}
    out = stamp_path(a.plan)
    with open(out, "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"stamped {len(doc['inputs'])} inputs of {doc['plan']} -> {os.path.basename(out)}")
    return 0


def parse_tfvars(path):
    vals = {}
    with open(path) as fh:
        for line in fh:
            m = re.match(r'\s*([a-z_][a-z0-9_]*)\s*=\s*(".*?"|[0-9.]+|true|false)\s*(#.*)?$', line)
            if m:
                v = m.group(2)
                vals[m.group(1)] = v[1:-1] if v.startswith('"') else v
    return vals


def defaults():
    with open(os.path.join(TF, "variables.tf")) as fh:
        text = fh.read()
    out = {}
    for m in re.finditer(r'variable\s+"([^"]+)"\s*\{(.*?)\n\}', text, re.S):
        d = re.search(r'^\s*default\s*=\s*("(?:[^"\\]|\\.)*"|[0-9.]+|true|false)\s*$', m.group(2), re.M)
        if d:
            out[m.group(1)] = d.group(1).strip('"')
    return out


def parse_time(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def cmd_freshness(a):
    plan = load(a.plan)
    if not os.path.isfile(a.tfvars):
        die(f"{a.tfvars} missing")
    stale = []
    ins = config_inputs(a.tfvars)
    sp = stamp_path(a.plan)
    if os.path.isfile(sp):
        with open(sp) as fh:
            st = json.load(fh)
        print(f"stamp {os.path.basename(sp)} ({st['stamped_at']}): exact comparison by SHA-256")
        if st.get("plan_sha256") != sha_file(a.plan):
            stale.append("the plan file changed after it was stamped")
        for k in sorted(set(st["inputs"]) | set(ins)):
            if k not in ins:
                stale.append(f"{k}: recorded in the stamp, no longer an input")
            elif k not in st["inputs"]:
                stale.append(f"{k}: a new input since the stamp")
            elif sha_file(ins[k]) != st["inputs"][k]:
                stale.append(f"{k}: changed since the plan was stamped")
    else:
        ref = parse_time(plan.get("timestamp"))
        basis = "the plan's timestamp" if ref else "the plan file's modification time"
        ref = ref or os.path.getmtime(a.plan)
        print(f"no stamp: comparing modification times with {basis} "
              f"({datetime.datetime.fromtimestamp(ref, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}); "
              "a checkout or copy also changes them, so stamp the next plan")
        for k, p in sorted(ins.items()):
            if os.path.getmtime(p) > ref + 1:
                stale.append(f"{k}: modified after the plan")
    pv = plan.get("variables")
    if isinstance(pv, dict):
        cur = dict(defaults(), **parse_tfvars(a.tfvars))
        for name in sorted(set(pv) | set(cur)):
            planned = (pv.get(name) or {}).get("value")
            planned = None if planned is None else str(planned).lower() if isinstance(planned, bool) else \
                (f"{planned:g}" if isinstance(planned, float) else str(planned))
            now = cur.get(name)
            if name in pv and now is not None and planned != now:
                stale.append(f"var.{name}: the plan used {short(planned, 32)}, the inputs now say {short(now, 32)}")
            elif name not in pv and name in cur:
                stale.append(f"var.{name}: set now but not recorded in the plan")
        print(f"plan variables: {len(pv)} compared with tfvars and defaults")
    else:
        print("plan variables: not recorded in this plan JSON (only the stamp or times can tell)")
    if stale:
        for s in stale:
            print(f"STALE {s}")
        print(f"STALE: the reviewed plan predates its inputs ({len(stale)} reason(s)). Plan again, review, then apply.")
        return 1
    print("FRESH: the plan was made from the current inputs")
    return 0


# (address, attribute path, label, expectation): the expectation is a value, a callable, or "omitted"
CHECKLIST = [
    ("aws_instance.host", "instance_type", "host instance type", lambda v: isinstance(v, str) and v.startswith(("t3.", "t4g.", "t3a."))),
    ("aws_instance.host", "ami", "host AMI (the owner's pinned image)", lambda v: isinstance(v, str) and v.startswith("ami-")),
    ("aws_instance.host", "metadata_options.0.http_tokens", "IMDSv2 required", "required"),
    ("aws_instance.host", "root_block_device.0.encrypted", "root disk encrypted", True),
    ("aws_instance.host", "root_block_device.0.volume_type", "root disk gp3", "gp3"),
    ("aws_instance.host", "instance_initiated_shutdown_behavior", "power-off at expiry terminates", "terminate"),
    ("aws_instance.host", "key_name", "no SSH key (Session Manager only)", "omitted"),
    ("aws_ebs_volume.data", "encrypted", "data volume encrypted", True),
    ("aws_ebs_volume.data", "type", "data volume gp3", "gp3"),
    ("aws_ebs_volume.data", "size", "data volume size (GiB)", lambda v: isinstance(v, int) and v >= 1),
    ("aws_security_group.host", "ingress", "security group: no inbound rule", lambda v: v == []),
    ("aws_vpc_security_group_egress_rule.https", "from_port", "egress: HTTPS only (from 443)", 443),
    ("aws_vpc_security_group_egress_rule.https", "to_port", "egress: HTTPS only (to 443)", 443),
    ("aws_s3_bucket_public_access_block.staging", "block_public_acls", "bucket blocks public ACLs", True),
    ("aws_s3_bucket_public_access_block.staging", "restrict_public_buckets", "bucket restricts public policies", True),
    ("aws_s3_bucket.staging", "bucket_prefix", "bucket name prefix", "flh-stg-"),
]


def dig(obj, path):
    """(found, value) for a dotted path through dicts and lists; found is False when a step is missing."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def checklist(plan):
    by = {rc["address"]: rc for rc in plan.get("resource_changes", [])}
    rows = []
    for addr, path, label, want in CHECKLIST:
        rc = by.get(addr)
        if rc is None:
            rows.append({"item": label, "address": addr, "attribute": path, "state": "ABSENT", "ok": False, "value": None})
            continue
        ch = rc.get("change") or {}
        unk_found, unk = dig(ch.get("after_unknown") or {}, path)
        found, val = dig(ch.get("after") or {}, path)
        if unk_found and unk is True:
            state, ok = "KNOWN AFTER APPLY", None
        elif not found or val is None:
            state, ok = "OMITTED", want == "omitted"
        else:
            state = "SET"
            ok = want(val) if callable(want) else (val == want and want != "omitted")
        rows.append({"item": label, "address": addr, "attribute": path, "state": state, "ok": ok, "value": val if state == "SET" else None})
    return rows


def cmd_checklist(a):
    try:
        plan = load(a.plan)
    except (OSError, ValueError) as e:
        print(f"plan_review: unreadable plan: {e}", file=sys.stderr)
        return 2
    rows = checklist(plan)
    bad = [r for r in rows if r["ok"] is False]
    later = [r for r in rows if r["ok"] is None]
    if a.json:
        print(json.dumps({"rows": rows, "wrong": len(bad), "confirm_after_apply": len(later)}, indent=1, sort_keys=True))
    else:
        mark = {True: "ok ", False: "NO ", None: "?  "}
        for r in rows:
            shown = json.dumps(r["value"]) if r["state"] == "SET" else ""
            print(f"{mark[r['ok']]} {r['item']:<42} {r['state']:<17} {shown}")
        print(f"{len(rows)} items: {len(rows) - len(bad) - len(later)} ok, {len(bad)} wrong or absent, "
              f"{len(later)} known only after apply (confirm on the created resource)")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary")
    s.add_argument("plan")
    s.add_argument("--json", action="store_true")
    d = sub.add_parser("diff")
    d.add_argument("a")
    d.add_argument("b")
    d.add_argument("--json", action="store_true")
    c = sub.add_parser("cost")
    c.add_argument("plan")
    c.add_argument("--assumptions", default=ASSUMPTIONS)
    c.add_argument("--hours", type=float, default=4.0)
    k = sub.add_parser("checklist")
    k.add_argument("plan")
    k.add_argument("--json", action="store_true")
    for name in ("stamp", "freshness"):
        f = sub.add_parser(name)
        f.add_argument("plan")
        f.add_argument("--tfvars", required=True)
    a = ap.parse_args()
    return {"summary": cmd_summary, "diff": cmd_diff, "cost": cmd_cost, "stamp": cmd_stamp, "freshness": cmd_freshness,
            "checklist": cmd_checklist}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
