#!/usr/bin/env python3
"""Offline review: do the staging IAM templates allow what the staging root and runbook need?

  review_permissions.py [--json] [--env staging|production]

Maps every resource type in terraform/main.tf to the write calls Terraform
makes for create, update and destroy (reads come from the operator's
ReadOnlyAccess, as for the demo), adds the operator's runbook calls (operate
policy) and the host's calls (inline policy in main.tf, capped by the
boundary), and checks each against the Allow statements of iam/out/*.json.
Tag-on-create is checked per create action (ec2:CreateTags with
ec2:CreateAction). Conditions are listed, not evaluated: a tag or shape
condition the request does not meet still ends in AccessDenied on AWS.
Prints MISSING (exit 1), then broad statements and allowed actions no step
needs. This is a static review; it proves nothing about live AWS behaviour.
--env production (R3) reviews iam/out-production: the deletes production withholds
(data volume, bucket, objects, parameters) are listed as ADMIN-ONLY, not MISSING.
Both environments: the <prefix>-verify-readonly policy must allow only
describe/list/get/view actions, never a parameter value, KMS decrypt or a backup object.
"""
import fnmatch
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = "production" if "--env" in sys.argv and sys.argv[sys.argv.index("--env") + 1:][:1] == ["production"] else "staging"
OUT = os.path.join(HERE, "out" if ENV == "staging" else "out-production")
PREFIX = "flh-stg" if ENV == "staging" else "flh-prd"
WITHHELD = {"ec2:DeleteVolume", "s3:DeleteBucket", "s3:DeleteObject", "s3:DeleteObjectVersion",
            "ssm:DeleteParameter", "ssm:DeleteParameters"} if ENV == "production" else set()
READ_ONLY = re.compile(r"^[a-z0-9-]+:(Describe|Get|List|View)[A-Za-z]*$")
NEVER_IN_VERIFY = {"ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath", "kms:Decrypt"}
MAIN = os.path.join(os.path.dirname(HERE), "terraform", "main.tf")

# Terraform resource type -> (deploy write actions, tag-on-create action or None)
TF = {
    "aws_vpc": (["ec2:CreateVpc", "ec2:ModifyVpcAttribute", "ec2:DeleteVpc"], "CreateVpc"),
    "aws_internet_gateway": (["ec2:CreateInternetGateway", "ec2:AttachInternetGateway", "ec2:DetachInternetGateway",
                              "ec2:DeleteInternetGateway"], "CreateInternetGateway"),
    "aws_subnet": (["ec2:CreateSubnet", "ec2:DeleteSubnet"], "CreateSubnet"),
    "aws_route_table": (["ec2:CreateRouteTable", "ec2:CreateRoute", "ec2:DeleteRoute", "ec2:DeleteRouteTable"], "CreateRouteTable"),
    "aws_route_table_association": (["ec2:AssociateRouteTable", "ec2:DisassociateRouteTable"], None),
    "aws_vpc_endpoint": (["ec2:CreateVpcEndpoint", "ec2:ModifyVpcEndpoint", "ec2:DeleteVpcEndpoints"], "CreateVpcEndpoint"),
    "aws_security_group": (["ec2:CreateSecurityGroup", "ec2:RevokeSecurityGroupEgress", "ec2:DeleteSecurityGroup"], "CreateSecurityGroup"),
    "aws_vpc_security_group_egress_rule": (["ec2:AuthorizeSecurityGroupEgress", "ec2:RevokeSecurityGroupEgress"],
                                           "AuthorizeSecurityGroupEgress"),
    "aws_s3_bucket": (["s3:CreateBucket", "s3:PutBucketTagging", "s3:DeleteBucket", "s3:DeleteObject",
                       "s3:DeleteObjectVersion"], None),
    "aws_s3_bucket_public_access_block": (["s3:PutBucketPublicAccessBlock"], None),
    "aws_s3_bucket_ownership_controls": (["s3:PutBucketOwnershipControls"], None),
    "aws_s3_bucket_server_side_encryption_configuration": (["s3:PutEncryptionConfiguration"], None),
    "aws_s3_bucket_versioning": (["s3:PutBucketVersioning"], None),
    "aws_s3_bucket_lifecycle_configuration": (["s3:PutLifecycleConfiguration"], None),
    "aws_s3_bucket_policy": (["s3:PutBucketPolicy", "s3:DeleteBucketPolicy"], None),
    "aws_iam_role": (["iam:CreateRole", "iam:TagRole", "iam:DeleteRole"], None),
    "aws_iam_role_policy": (["iam:PutRolePolicy", "iam:DeleteRolePolicy"], None),
    "aws_iam_instance_profile": (["iam:CreateInstanceProfile", "iam:TagInstanceProfile", "iam:AddRoleToInstanceProfile",
                                  "iam:RemoveRoleFromInstanceProfile", "iam:DeleteInstanceProfile"], None),
    "aws_instance": (["ec2:RunInstances", "ec2:TerminateInstances", "ec2:ModifyInstanceAttribute", "iam:PassRole"], "RunInstances"),
    "aws_ebs_volume": (["ec2:CreateVolume", "ec2:DeleteVolume"], "CreateVolume"),
    "aws_volume_attachment": (["ec2:AttachVolume", "ec2:DetachVolume"], None),
}
OPERATOR = {  # RUNBOOK steps -> operate policy
    "§5 upload the bundle to releases/": ["s3:PutObject"],
    "§6 upload the backup to backups/": ["s3:PutObject"],
    "§6/E13 download a backup": ["s3:GetObject"],
    "§4/§9 parameters": ["ssm:PutParameter", "ssm:GetParametersByPath", "ssm:DeleteParameters"],
    "§5/E10 sessions and port forwarding": ["ssm:StartSession", "ssm:TerminateSession"],
}
HOST = {  # host steps -> inline policy (main.tf) and boundary
    "Session Manager agent": ["ssm:UpdateInstanceInformation", "ssmmessages:CreateControlChannel",
                              "ssmmessages:CreateDataChannel", "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel"],
    "§5 download the bundle (releases/)": ["s3:GetObject"],
    "§6 download a backup / E13 upload a backup (backups/)": ["s3:GetObject", "s3:PutObject"],
    "§5 flh-staging-env": ["ssm:GetParametersByPath", "kms:Decrypt"],
}


def statements(path):
    d = json.load(open(path))
    for s in d["Statement"]:
        acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
        res = s.get("Resource", [])
        res = res if isinstance(res, list) else [res]
        yield s.get("Sid", "?"), s["Effect"], acts, res, s.get("Condition", {})


def allows(stmts, action, create_action=None):
    hits = []
    for sid, eff, acts, res, cond in stmts:
        if eff != "Allow" or not any(fnmatch.fnmatchcase(action, a) for a in acts):
            continue
        if create_action:
            # A resource being created has no tags yet, so a statement scoped by
            # aws:ResourceTag cannot authorise tag-on-create: only an ec2:CreateAction
            # condition naming this create call (or no condition at all) does.
            ca = (cond.get("StringEquals") or {}).get("ec2:CreateAction")
            if cond and (ca is None or create_action not in (ca if isinstance(ca, list) else [ca])):
                continue
        hits.append(sid)
    return hits


def host_inline_actions():
    text = open(MAIN).read()
    block = text[text.index('data "aws_iam_policy_document" "host"'):text.index('resource "aws_iam_role_policy" "host"')]
    acts = set()
    for m in re.finditer(r"actions\s*=\s*\[(.*?)\]", block, re.S):
        acts |= set(re.findall(r'"([a-z0-9]+:[A-Za-z*]+)"', m.group(1)))
    return acts


def review():
    deploy = list(statements(os.path.join(OUT, f"{PREFIX}-deploy-policy.json"))) + \
        list(statements(os.path.join(OUT, f"{PREFIX}-deploy-ec2-policy.json")))
    operate = list(statements(os.path.join(OUT, f"{PREFIX}-operate-policy.json")))
    boundary = list(statements(os.path.join(OUT, f"{PREFIX}-host-boundary-policy.json")))
    inline = host_inline_actions()
    types = sorted(set(re.findall(r'^resource "([a-z0-9_]+)"', open(MAIN).read(), re.M)))
    rows, missing, needed, admin_only = [], [], set(), []
    for t in types:
        if t not in TF:
            missing.append((t, "?", "resource type not mapped in review_permissions.py"))
            continue
        acts, create = TF[t]
        for a in acts:
            needed.add(a)
            hits = allows(deploy, a)
            rows.append(("deploy", t, a, hits))
            if not hits and a in WITHHELD:
                admin_only.append(("deploy", t, a))
            elif not hits:
                missing.append(("deploy", t, a))
        if create:
            hits = allows(deploy, "ec2:CreateTags", create)
            rows.append(("deploy", t, f"ec2:CreateTags [CreateAction={create}]", hits))
            if not hits:
                missing.append(("deploy", t, f"ec2:CreateTags with ec2:CreateAction={create}"))
    for step, acts in OPERATOR.items():
        for a in acts:
            hits = allows(operate, a)
            rows.append(("operate", step, a, hits))
            if not hits and a in WITHHELD:
                admin_only.append(("operate", step, a))
            elif not hits:
                missing.append(("operate", step, a))
    for step, acts in HOST.items():
        for a in acts:
            in_inline = any(fnmatch.fnmatchcase(a, x) for x in inline)
            hits = allows(boundary, a)
            rows.append(("host", step, a, hits if in_inline else []))
            if not (hits and in_inline):
                missing.append(("host", step, f"{a} (inline {in_inline}, boundary {bool(hits)})"))
    broad, unused = [], []
    for name, stmts in (("deploy", deploy), ("operate", operate), ("host-boundary", boundary)):
        for sid, eff, acts, res, cond in stmts:
            if eff != "Allow":
                continue
            if any(r == "*" or r.endswith(":*") for r in res):
                broad.append((name, sid, ", ".join(res), "conditions: " + (", ".join(sorted(cond)) or "none")))
            if name == "deploy":
                for a in acts:
                    if a not in needed and a != "ec2:CreateTags":
                        unused.append((sid, a))
    return rows, missing, broad, unused, admin_only, verify_problems()


def verify_problems():
    """The verify-readonly policy: read-only Allow actions only, and never a value, a decrypt or a backup object."""
    path = os.path.join(OUT, f"{PREFIX}-verify-readonly-policy.json")
    if not os.path.isfile(path):
        return [f"{os.path.basename(path)} missing"]
    probs, denied = [], set()
    for sid, eff, acts, res, cond in statements(path):
        if eff == "Deny":
            denied |= set(acts)
            continue
        for a in acts:
            if not READ_ONLY.match(a):
                probs.append(f"{sid}: {a} is not a read-only action")
            if a in NEVER_IN_VERIFY:
                probs.append(f"{sid}: {a} would read a parameter value or decrypt")
            if a.startswith("s3:GetObject") and any("backups/" in r or r.endswith("/*") and "releases/" not in r for r in res):
                probs.append(f"{sid}: {a} on {res} could read backup objects")
    for a in NEVER_IN_VERIFY:
        if a not in denied:
            probs.append(f"{a} is not explicitly denied")
    return probs


def main():
    rows, missing, broad, unused, admin_only, vprobs = review()
    missing = missing + [("verify", p) for p in vprobs]
    if "--json" in sys.argv:
        print(json.dumps({"env": ENV, "rows": rows, "missing": missing, "broad": broad, "unused": unused,
                          "admin_only": admin_only}, indent=1))
        return 1 if missing else 0
    print(f"environment {ENV} ({os.path.relpath(OUT, HERE)}): checked {len(rows)} required actions "
          "(deploy per Terraform resource type, operator, host)")
    for m in admin_only:
        print("ADMIN-ONLY " + " | ".join(m) + " (withheld from production; an administrator deletes)")
    print(f"verify-readonly: {'read-only' if not vprobs else 'PROBLEMS'}")
    for m in missing:
        print("MISSING " + " | ".join(m))
    print("== broad statements (Resource * or account-wide; scoped by the listed conditions)")
    for b in broad:
        print("BROAD   " + " | ".join(b))
    print("== deploy actions allowed but used by no create/destroy step (updates, start/stop; tag-scoped)")
    for sid, a in sorted(set(unused)):
        print(f"UNUSED  {sid} | {a}")
    print("RESULT: " + ("MISSING permissions" if missing else "every required action is allowed (conditions not evaluated)"))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
