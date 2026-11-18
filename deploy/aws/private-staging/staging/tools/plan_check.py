#!/usr/bin/env python3
"""Offline check of an owner-supplied staging Terraform plan (JSON). Never runs Terraform.

  plan_check.py --mode create|update|destroy PLAN.json [--allow-replace ADDRESS ...]
                [--expected staging/expected_resources.json]

PLAN.json is what the owner produces with
  terraform plan -out stg.tfplan && terraform show -json stg.tfplan > stg.plan.json
(or `terraform plan -destroy -out ...` for --mode destroy). Both files hold the
account ID and ARNs: they are ignored by Git and must stay on the owner's machine.

STOP (exit 1) when any of these holds; otherwise SAFE (exit 0):
  - a resource address that is not in expected_resources.json (for example the
    public demo's stack, an Elastic IP or a DNS record), or a module resource;
  - any public path: an inbound rule, a security group with ingress, an Elastic
    IP, load balancer, DNS record, CloudFront, API gateway, public bucket ACL or
    website, or a public-access block that is not fully on;
  - create mode: an action other than create on a managed resource, or a root
    that already has managed resources in state;
  - update mode: any delete; a replace of anything except the addresses given
    with --allow-replace (only aws_instance.host and aws_volume_attachment.data
    may ever be allowed: the data volume and the bucket are never replaced);
  - destroy mode: anything but delete, or a resource missing from the destroy;
  - weakened settings: IMDSv1, an unencrypted root or data volume, a shutdown
    behaviour other than terminate, an egress rule other than TCP 443, missing
    Project/Component/ExpiresAt/Run/ManagedBy tags, another provider.
Exit 2: the file is not a Terraform plan JSON or the arguments are wrong.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_EXPECTED = os.path.join(os.path.dirname(HERE), "expected_resources.json")
NEVER_REPLACE_OK = {"aws_ebs_volume.data", "aws_s3_bucket.staging"}


def load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        print(f"plan_check: cannot read {path}: {e}", file=sys.stderr)
        sys.exit(2)


def action_kind(actions):
    a = list(actions)
    if a == ["no-op"]:
        return "no-op"
    if a == ["read"]:
        return "read"
    if a == ["create"]:
        return "create"
    if a == ["update"]:
        return "update"
    if a == ["delete"]:
        return "delete"
    if sorted(a) == ["create", "delete"]:
        return "replace"
    return "+".join(a)


def check(plan, expected, mode, allow_replace):
    findings = []  # (severity, address, message)
    stop = lambda addr, msg: findings.append(("STOP", addr, msg))
    info = lambda addr, msg: findings.append(("INFO", addr, msg))
    if not isinstance(plan, dict) or "resource_changes" not in plan or "format_version" not in plan:
        print("plan_check: not a `terraform show -json` plan (no format_version/resource_changes)", file=sys.stderr)
        sys.exit(2)
    managed = expected["managed"]
    data_ok = set(expected["data"])
    public_types = set(expected["public_path_types"])
    counts = {"create": 0, "update": 0, "delete": 0, "replace": 0, "no-op": 0, "read": 0}
    seen = set()
    for rc in plan.get("resource_changes") or []:
        addr = rc.get("address", "?")
        rtype = rc.get("type", "")
        kind = action_kind((rc.get("change") or {}).get("actions") or [])
        counts[kind] = counts.get(kind, 0) + 1
        after = (rc.get("change") or {}).get("after") or {}
        if rc.get("module_address"):
            stop(addr, "resource inside a module: the staging root has none")
        if rc.get("provider_name") and rc["provider_name"] != expected["provider"]:
            stop(addr, f"provider {rc['provider_name']} is not {expected['provider']}")
        if rtype in public_types:
            stop(addr, f"public path: {rtype} must not exist in staging (no inbound access, no address, no DNS)")
        if rc.get("mode") == "data":
            if addr not in data_ok:
                stop(addr, "unexpected data source")
            continue
        seen.add(addr)
        if addr not in managed:
            stop(addr, f"unexpected resource ({kind}): not in expected_resources.json; the demo stack and anything "
                       "else belong to other roots")
            continue
        # --- action rules by mode
        if mode == "create" and kind not in ("create",):
            stop(addr, f"{kind} in a first apply (expected create only)")
        if mode == "update":
            if kind == "delete":
                stop(addr, "delete during an update (stop rule): only `terraform destroy` removes staging resources")
            elif kind == "replace":
                if addr in NEVER_REPLACE_OK:
                    stop(addr, "replace of a resource that holds data (stop rule): never allowed")
                elif addr not in allow_replace:
                    stop(addr, "replace (delete then create) without --allow-replace "
                               f"{addr}: confirm the reason in the plan first (stop rule)")
                elif not managed[addr].get("replace_needs_flag"):
                    stop(addr, "replace is never allowed for this resource")
                else:
                    info(addr, "replace allowed by --allow-replace")
        if mode == "destroy" and kind != "delete":
            stop(addr, f"{kind} in a destroy plan (expected delete only)")
        if kind in ("delete", "no-op"):
            continue
        # --- settings of what will exist
        if rtype == "aws_security_group" and after.get("ingress"):
            stop(addr, f"security group has {len(after['ingress'])} ingress rule(s): staging has no inbound access")
        if rtype == "aws_vpc_security_group_egress_rule":
            if not (after.get("ip_protocol") == "tcp" and after.get("from_port") == 443 and after.get("to_port") == 443):
                stop(addr, "egress rule is not TCP 443 only")
        if rtype == "aws_s3_bucket_public_access_block":
            for k in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
                if after.get(k) is not True:
                    stop(addr, f"public access block {k} is not true")
        if rtype == "aws_instance":
            md = (after.get("metadata_options") or [{}])[0]
            if md.get("http_tokens") != "required":
                stop(addr, "IMDSv2 not required (http_tokens)")
            root = (after.get("root_block_device") or [{}])[0]
            if root.get("encrypted") is not True:
                stop(addr, "root volume not encrypted")
            if after.get("instance_initiated_shutdown_behavior") != "terminate":
                stop(addr, "shutdown behaviour is not terminate (the bounded runtime relies on it)")
            if after.get("associate_public_ip_address"):
                info(addr, "public IPv4 for outbound HTTPS only (no inbound rule); the workbench is reached by SSM")
        if rtype == "aws_ebs_volume" and after.get("encrypted") is not True:
            stop(addr, "data volume not encrypted")
        if "tags_all" in after or "tags" in after:
            tags = after.get("tags_all")
            if tags is None:
                unknown = ((rc.get("change") or {}).get("after_unknown") or {}).get("tags_all")
                if unknown:
                    continue
                tags = after.get("tags") or {}
            for k, v in expected["required_tags"].items():
                if (tags or {}).get(k) != v:
                    stop(addr, f"tag {k} is {(tags or {}).get(k)!r}, expected {v!r}")
            for k in expected["required_tag_keys"]:
                if not (tags or {}).get(k):
                    stop(addr, f"tag {k} missing")
    if mode == "create":
        prior = (((plan.get("prior_state") or {}).get("values") or {}).get("root_module") or {}).get("resources") or []
        if any(r.get("mode") == "managed" for r in prior):
            stop("-", "the root already has managed resources in state: this is not a first apply (use --mode update)")
        missing = sorted(set(managed) - seen)
        if missing:
            stop("-", f"expected resources absent from the plan: {missing}")
    if mode == "destroy":
        missing = sorted(set(managed) - seen)
        if missing:
            info("-", f"not in this destroy (already gone or never created): {missing}")
    return findings, counts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--mode", required=True, choices=["create", "update", "destroy"])
    ap.add_argument("--allow-replace", action="append", default=[])
    ap.add_argument("--expected", default=DEFAULT_EXPECTED)
    a = ap.parse_args()
    expected = load(a.expected)
    for r in a.allow_replace:
        if r in NEVER_REPLACE_OK or r not in expected["managed"]:
            print(f"plan_check: --allow-replace {r} is never permitted", file=sys.stderr)
            return 2
    plan = load(a.plan)
    findings, counts = check(plan, expected, a.mode, set(a.allow_replace))
    print(f"plan ({a.mode}): {counts.get('create', 0)} to add, {counts.get('update', 0)} to change, "
          f"{counts.get('delete', 0)} to destroy, {counts.get('replace', 0)} to replace, "
          f"{counts.get('no-op', 0)} unchanged; terraform {plan.get('terraform_version', '?')}")
    for sev, addr, msg in findings:
        print(f"{sev:4} {addr}: {msg}")
    stops = [f for f in findings if f[0] == "STOP"]
    if stops:
        print(f"STOP: {len(stops)} finding(s). Do not apply this plan; fix the cause and plan again.")
        return 1
    print("SAFE: every change is expected for this mode.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
