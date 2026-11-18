#!/usr/bin/env python3
"""Derive the staging IAM policies from the reviewed demo policies (FLH-086/088).

  make_policies.py REPO_DEPLOY_AWS_IAM_DIR OUT_DIR

Reads deploy/aws/iam/*.json (read-only) and writes four flh-stg-* policies:
the same structure and guards, renamed to the staging stack, with these
changes, each listed in OUT_DIR/CHANGES.txt:
  - tags Component=public-demo -> workbench-staging; RunInstances also
    requires an ExpiresAt and a Run tag (bounded lifecycle);
  - instance shape t4g.micro -> t3.small; AMI pinned to __STAGING_AMI_ID__;
  - no Elastic IP and no inbound rule (the staging host has no public path);
  - the separate encrypted gp3 data volume: create (tagged, encrypted, gp3),
    attach, detach, delete (tagged);
  - host boundary: S3 backups/ read+write, SSM parameters under /flh/staging,
    kms:Decrypt only through SSM;
  - operator: upload releases/ and backups/, read backups/, manage the
    /flh/staging parameters.
Account ID stays the placeholder __AWS_ACCOUNT_ID__ (substituted locally, never
committed). Checks each output: valid JSON, unique Sids, and the 6,144
non-whitespace character limit of a customer managed policy.
"""
import copy
import json
import os
import re
import sys

src, out = sys.argv[1:3]
os.makedirs(out, exist_ok=True)
changes = []


def load(name):
    return json.load(open(os.path.join(src, name)))


def sub(obj, pairs):
    s = json.dumps(obj)
    for a, b in pairs:
        s = s.replace(a, b)
    return json.loads(s)


RENAME = [
    ("flh-demo-host-boundary", "flh-stg-host-boundary"),
    ("flh-demo-deploy-ec2", "flh-stg-deploy-ec2"),
    ("flh-demo-deploy", "flh-stg-deploy"),
    ("flh-demo-operate", "flh-stg-operate"),
    ("flh-demo-host-", "flh-stg-host-"),
    ("flh-demo-artifacts-", "flh-stg-"),
    ("flh-demo-root", "flh-stg-root"),
    ('"public-demo"', '"workbench-staging"'),
    ("t4g.micro", "t3.small"),
]

# --- deploy (EC2 part) ---------------------------------------------------------------
ec2 = sub(load("flh-experiment-demo-deploy-ec2-policy.json"), RENAME)
ec2["Statement"] = [s for s in ec2["Statement"]
                    if s.get("Sid") not in ("Ec2AllocateTaggedElasticIp", "Ec2CreateIngressRuleTagged",
                                            "Ec2AssociateAddressWithInstanceInterface")]
changes.append("deploy-ec2: removed Ec2AllocateTaggedElasticIp, Ec2CreateIngressRuleTagged, "
               "Ec2AssociateAddressWithInstanceInterface (no public path)")
for s in ec2["Statement"]:
    acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
    kept = [a for a in acts if a not in ("ec2:AllocateAddress", "ec2:ReleaseAddress", "ec2:AssociateAddress",
                                         "ec2:DisassociateAddress", "ec2:AuthorizeSecurityGroupIngress")]
    if len(kept) != len(acts):
        changes.append(f"deploy-ec2: {s.get('Sid')}: dropped {sorted(set(acts) - set(kept))}")
        s["Action"] = kept
    res = s.get("Resource")
    if isinstance(res, list):
        new = []
        for r in res:
            if "elastic-ip/" in r:
                changes.append(f"deploy-ec2: {s.get('Sid')}: dropped resource {r}")
                continue
            new.append(re.sub(r"image/ami-[0-9a-f]+", "image/__STAGING_AMI_ID__", r))
        s["Resource"] = new
    elif isinstance(res, str):
        s["Resource"] = re.sub(r"image/ami-[0-9a-f]+", "image/__STAGING_AMI_ID__", res)
    if s.get("Sid") == "Ec2RunOnlyTheReviewedInstanceShape":
        cond = s.setdefault("Condition", {})
        cond.setdefault("Null", {}).update({"aws:RequestTag/ExpiresAt": "false", "aws:RequestTag/Run": "false"})
        changes.append("deploy-ec2: Ec2RunOnlyTheReviewedInstanceShape: also requires ExpiresAt and Run tags")
changes.append("deploy-ec2: AMI resource -> image/__STAGING_AMI_ID__ (reviewed AL2023 x86_64)")
region_arn = "arn:aws:ec2:us-east-1:__AWS_ACCOUNT_ID__"
ec2["Statement"] += [
    {"Sid": "Ec2CreateEncryptedTaggedDataVolume", "Effect": "Allow", "Action": ["ec2:CreateVolume"],
     "Resource": f"{region_arn}:volume/*",
     "Condition": {"StringEquals": {"aws:RequestTag/Project": "flh", "aws:RequestTag/Component": "workbench-staging",
                                    "ec2:VolumeType": "gp3"},
                   "Bool": {"ec2:Encrypted": "true"}}},
    {"Sid": "Ec2AttachDetachDeleteStackVolume", "Effect": "Allow",
     "Action": ["ec2:AttachVolume", "ec2:DetachVolume", "ec2:DeleteVolume"],
     "Resource": [f"{region_arn}:volume/*", f"{region_arn}:instance/*"],
     "Condition": {"StringEquals": {"aws:ResourceTag/Project": "flh", "aws:ResourceTag/Component": "workbench-staging"}}},
]
changes.append("deploy-ec2: added Ec2CreateEncryptedTaggedDataVolume, Ec2AttachDetachDeleteStackVolume")

# --- deploy (IAM + S3 part) -----------------------------------------------------------
dep = sub(load("flh-experiment-demo-deploy-policy.json"), RENAME)
for s in dep["Statement"]:
    if s.get("Sid") == "S3ManageArtifactBucket":
        for a in ("s3:PutLifecycleConfiguration", "s3:PutBucketVersioning", "s3:PutBucketTagging"):
            acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
            if a not in acts:
                acts.append(a)
                changes.append(f"deploy: S3ManageArtifactBucket: added {a}")
            s["Action"] = acts
changes.append("deploy: names flh-demo-* -> flh-stg-* (role, profile, bucket prefix, guarded policy names)")

# --- host boundary --------------------------------------------------------------------
hb = sub(load("flh-demo-host-boundary-policy.json"), RENAME)
hb["Statement"] += [
    {"Sid": "ReadWriteStagingBackups", "Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
     "Resource": "arn:aws:s3:::flh-stg-*/backups/*"},
    {"Sid": "ReadStagingParameters", "Effect": "Allow", "Action": ["ssm:GetParameter", "ssm:GetParametersByPath"],
     "Resource": ["arn:aws:ssm:us-east-1:*:parameter/flh/staging", "arn:aws:ssm:us-east-1:*:parameter/flh/staging/*"]},
    {"Sid": "DecryptOnlyThroughSsm", "Effect": "Allow", "Action": "kms:Decrypt", "Resource": "*",
     "Condition": {"StringEquals": {"kms:ViaService": "ssm.us-east-1.amazonaws.com"}}},
]
changes.append("host-boundary: added ReadWriteStagingBackups, ReadStagingParameters, DecryptOnlyThroughSsm")

# --- operate --------------------------------------------------------------------------
op = sub(load("flh-experiment-demo-operate-policy.json"), RENAME)
for s in op["Statement"]:
    if s.get("Sid") == "S3UploadReleases":
        res = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
        s["Resource"] = res + [r.replace("/releases/*", "/backups/*") for r in res]
        s["Sid"] = "S3UploadReleasesAndBackups"
        changes.append("operate: S3UploadReleases -> S3UploadReleasesAndBackups (final NAS backup upload)")
op["Statement"] += [
    {"Sid": "S3ReadBackups", "Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::flh-stg-*/backups/*"},
    {"Sid": "ManageStagingParameters", "Effect": "Allow",
     "Action": ["ssm:PutParameter", "ssm:GetParameter", "ssm:GetParametersByPath", "ssm:DeleteParameter",
                "ssm:DeleteParameters"],
     "Resource": ["arn:aws:ssm:us-east-1:__AWS_ACCOUNT_ID__:parameter/flh/staging",
                  "arn:aws:ssm:us-east-1:__AWS_ACCOUNT_ID__:parameter/flh/staging/*"]},
]
changes.append("operate: added S3ReadBackups, ManageStagingParameters")

docs = {"flh-stg-deploy-ec2-policy.json": ec2, "flh-stg-deploy-policy.json": dep,
        "flh-stg-host-boundary-policy.json": hb, "flh-stg-operate-policy.json": op}
bad = 0
for name, d in docs.items():
    text = json.dumps(d, indent=2) + "\n"
    open(os.path.join(out, name), "w").write(text)
    sids = [s.get("Sid") for s in d["Statement"]]
    size = len(re.sub(r"\s", "", json.dumps(d)))
    leftovers = [w for w in ("flh-demo", "public-demo", "t4g.micro", "elastic-ip") if w in text]
    ok = len(sids) == len(set(sids)) and size <= 6144 and not leftovers
    bad += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {len(sids)} statements, {size} non-whitespace chars"
          + (f", leftovers {leftovers}" if leftovers else ""))
open(os.path.join(out, "CHANGES.txt"), "w").write("\n".join(changes) + "\n")
sys.exit(1 if bad else 0)
