#!/usr/bin/env python3
"""Cost and lifecycle of the private root, offline (R4). No AWS call: the owner collects read-only JSON.

  lifecycle.py cost [--scenario NAME] [--sheet FILE] [--set KEY=VALUE ...] [--json]
      Costs by category (compute, disk, snapshots, storage, ipv4, logs) for a scenario of
      staging/cost_sheet.json (dated list prices + named assumptions). --set overrides one input.
  lifecycle.py after-shutdown [--env staging|production]
      What keeps billing after the host stops (production) or powers off and terminates (staging),
      derived from the root's settings, and what ends it.
  lifecycle.py teardown-rehearse INVENTORY.json --now UTC
      Rehearses the expiry and the manual teardown on a synthetic inventory (no AWS): which resources
      are past ExpiresAt, what the power-off removes, what stays billable until `terraform destroy`,
      and what would be left after it. Exit 1 if anything would remain billable after destroy.
  lifecycle.py verify-commands --env staging|production --out DIR [--profile P]
      Prints the read-only AWS CLI commands (for the verify-readonly profile) that collect the
      residual-resource evidence into DIR as JSON. Nothing is run.
  lifecycle.py residual DIR --env staging|production [--json]
      The residual-resource checklist from those files: one row per check with its evidence fields
      (source file, collected time, count, masked IDs). PASS only when no resource of the
      environment remains. Exit 1 on any residual, 2 when a file is missing or unreadable.
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STAGING = os.path.dirname(HERE)
SHEET = os.path.join(STAGING, "cost_sheet.json")
ENV = {"staging": {"component": "workbench-staging", "prefix": "flh-stg-"},
       "production": {"component": "workbench-production", "prefix": "flh-prd-"}}
FILES = {  # evidence file -> the read-only command that produces it (verify-readonly policy)
    "ec2-instances.json": "ec2 describe-instances --filters Name=tag:Component,Values={component} Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down",
    "ec2-volumes.json": "ec2 describe-volumes --filters Name=tag:Component,Values={component}",
    "ec2-snapshots.json": "ec2 describe-snapshots --owner-ids self --filters Name=tag:Component,Values={component}",
    "ec2-addresses.json": "ec2 describe-addresses --filters Name=tag:Component,Values={component}",
    "s3-buckets.json": "s3api list-buckets",
    "tagged-resources.json": "resourcegroupstaggingapi get-resources --tag-filters Key=Component,Values={component}",
}


def load_sheet(path):
    with open(path) as fh:
        return json.load(fh)


def cost(sheet, sc):
    p, hpm = sheet["prices"], sheet["hours_per_month"]
    itype = sc["instance_type"]
    if itype not in p["compute"]["by_type"]:
        raise SystemExit(f"lifecycle: no compute price for {itype} in the sheet")
    st = sc["storage_hours"] / hpm
    rows = {
        "compute": sc["compute_hours"] * p["compute"]["by_type"][itype],
        "disk": (sc["root_gib"] * sc["compute_hours"] / hpm + sc["data_gib"] * st) * p["disk"]["price"],
        "snapshots": sc["snapshot_gib"] * st * p["snapshots"]["price"],
        "storage": sc["s3_gib"] * st * p["storage"]["price"] + sc["s3_puts"] / 1000 * p["storage"]["put_per_1000"]
                   + sc["s3_gets"] / 1000 * p["storage"]["get_per_1000"],
        "ipv4": sc["ipv4"] * sc["compute_hours"] * p["ipv4"]["price"],
        "logs": sc["log_ingest_gib"] * p["logs"]["ingest"] + sc["log_store_gib"] * st * p["logs"]["store"]
                + sc["alarms"] * st * p["logs"]["alarm_month"],
    }
    return {k: round(v, 4) for k, v in rows.items()}


def cmd_cost(a):
    sheet = load_sheet(a.sheet)
    sc = dict(sheet["scenarios"][a.scenario])
    for kv in a.set or []:
        k, v = kv.split("=", 1)
        if k not in sc:
            raise SystemExit(f"lifecycle: --set {k}: not an input of {a.scenario}")
        sc[k] = v if k == "instance_type" else float(v)
    rows = cost(sheet, sc)
    total = round(sum(rows.values()), 2)
    if a.json:
        print(json.dumps({"scenario": a.scenario, "as_of": sheet["as_of"], "inputs": sc, "by_category": rows, "total": total},
                         indent=1, sort_keys=True))
        return 0
    print(f"scenario {a.scenario} ({sc.get('note', '')}); prices as of {sheet['as_of']} ({sheet['region']}, list, not fetched)")
    for k, v in rows.items():
        print(f"  {k:10} ${v:9.4f}   {sheet['prices'][k]['unit']}")
    print(f"  {'total':10} ${total:9.2f}")
    for s in sheet["assumptions"]:
        print(f"  assumption: {s}")
    return 0


def after_shutdown(env):
    """(resource, keeps billing?, why, what ends it) from the root's settings (main.tf)."""
    staging = env == "staging"
    return [
        ("aws_instance.host (compute)", False, "the power-off timer (staging) or a stop (production) ends instance-hours",
         "-"),
        ("root volume (16 GiB gp3)", not staging,
         "staging terminates on shutdown and the root has delete_on_termination" if staging
         else "production stops (never terminates): the root volume stays", "terraform destroy" if not staging else "-"),
        ("aws_ebs_volume.data", True, "a separate volume: it survives terminate and stop by design (it holds the data)",
         "terraform destroy (staging); an administrator (production: DeleteVolume is withheld)"),
        ("public IPv4 (auto-assigned)", False, "released when the instance stops or terminates (no Elastic IP exists)", "-"),
        ("aws_s3_bucket.staging objects", True, "releases/ and backups/ stay; lifecycle expiry is 14 d (staging) / 35+7 d (production)",
         "terraform destroy with force_destroy (staging); an administrator (production)"),
        ("EBS snapshots", True, "none are created by this root; any made by hand bill until deleted", "delete them by hand"),
        ("CloudWatch Logs, alarms", True, "none in this root today; alarms proposed for production would bill monthly", "-"),
        ("SSM parameters, IAM policies, VPC, S3 endpoint", False, "free", "RUNBOOK §9 (parameters, policies)"),
    ]


def cmd_after_shutdown(a):
    for res, bills, why, end in after_shutdown(a.env):
        print(f"{'BILLS' if bills else 'free ':6} {res:44} {why}{'; ends with: ' + end if bills and end != '-' else ''}")
    return 0


def parse_utc(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def cmd_teardown_rehearse(a):
    with open(a.inventory) as fh:
        inv = json.load(fh)
    now = parse_utc(a.now)
    res = inv["resources"]
    print(f"synthetic inventory {inv.get('name', '?')}: {len(res)} resources at {a.now}")
    expired = [r for r in res if r.get("tags", {}).get("ExpiresAt") not in (None, "never") and parse_utc(r["tags"]["ExpiresAt"]) <= now]
    print(f"step 1 expiry: {len(expired)} resource(s) past ExpiresAt; the stack must be destroyed")
    after_off = []
    for r in res:
        if r["type"] == "aws_instance":
            continue                                    # powered off, then terminated (staging)
        if r["type"] == "root_volume" and r.get("delete_on_termination"):
            continue
        if r["type"] == "public_ipv4":
            continue
        after_off.append(r)
    billable = [r for r in after_off if r.get("billable")]
    print(f"step 2 power-off and terminate: compute, root disk and public IPv4 end; still billable: "
          f"{', '.join(r['type'] for r in billable) or 'none'}")
    left = [r for r in after_off if not r.get("managed_by_terraform", True)]
    print(f"step 3 terraform destroy (force_destroy bucket): removes {len(after_off) - len(left)} managed resource(s)")
    for r in left:
        print(f"RESIDUAL {r['type']} {r.get('id', '?')}: not managed by this root ({r.get('note', 'created by hand')}); "
              f"{'billable' if r.get('billable') else 'free'}")
    bill_left = [r for r in left if r.get("billable")]
    print("TEARDOWN REHEARSAL: nothing billable would remain" if not bill_left else
          f"TEARDOWN REHEARSAL: {len(bill_left)} billable residual(s) need a manual step (step 4)")
    return 1 if bill_left else 0


def cmd_verify_commands(a):
    comp = ENV[a.env]["component"]
    print(f"# read-only residual evidence for {a.env} (verify-readonly policy); run from an empty directory {a.out}")
    print(f"mkdir -p {a.out} && date -u +%Y-%m-%dT%H:%M:%SZ > {a.out}/collected-at.txt")
    for f, cmd in FILES.items():
        print(f"aws {cmd.format(component=comp)} --profile {a.profile} --region us-east-1 --output json > {a.out}/{f}")
    print(f"python3 -I deploy/aws/private-staging/staging/tools/lifecycle.py residual {a.out} --env {a.env}")
    return 0


def mask(s):
    return re.sub(r"([a-z]+-)?([0-9a-f]{8,17})$", lambda m: (m.group(1) or "") + "…" + m.group(2)[-4:], str(s))


def cmd_residual(a):
    e = ENV[a.env]
    try:
        with open(os.path.join(a.dir, "collected-at.txt")) as fh:
            collected = fh.read().strip()
        docs = {}
        for f in FILES:
            with open(os.path.join(a.dir, f)) as fh:
                docs[f] = json.load(fh)
    except (OSError, ValueError) as ex:
        print(f"lifecycle: incomplete evidence in {a.dir}: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 2
    # A listing without its top-level key (an error envelope, a refused call, the wrong command) proves nothing:
    # reading it as "zero resources" would pass a teardown that was never checked.
    shape = {"ec2-instances.json": "Reservations", "ec2-volumes.json": "Volumes", "ec2-snapshots.json": "Snapshots",
             "ec2-addresses.json": "Addresses", "s3-buckets.json": "Buckets", "tagged-resources.json": "ResourceTagMappingList"}
    wrong = [f for f, key in shape.items() if not isinstance(docs.get(f), dict) or not isinstance(docs[f].get(key), list)]
    if wrong:
        print(f"lifecycle: incomplete evidence in {a.dir}: {', '.join(wrong)} lack(s) the listing's top-level key; "
              "re-run the printed command (verify-commands) into a NEW directory", file=sys.stderr)
        return 2
    insts = [i for r in docs["ec2-instances.json"].get("Reservations", []) for i in r.get("Instances", [])
             if i.get("State", {}).get("Name") != "terminated"]
    checks = [
        ("instances", "ec2-instances.json", [i["InstanceId"] for i in insts]),
        ("volumes", "ec2-volumes.json", [v["VolumeId"] for v in docs["ec2-volumes.json"].get("Volumes", [])]),
        ("snapshots", "ec2-snapshots.json", [s["SnapshotId"] for s in docs["ec2-snapshots.json"].get("Snapshots", [])]),
        ("addresses", "ec2-addresses.json", [x.get("AllocationId", "?") for x in docs["ec2-addresses.json"].get("Addresses", [])]),
        ("buckets", "s3-buckets.json", [b["Name"] for b in docs["s3-buckets.json"].get("Buckets", []) if b["Name"].startswith(e["prefix"])]),
        ("tagged", "tagged-resources.json", [t["ResourceARN"].split(":")[-1] for t in
                                             docs["tagged-resources.json"].get("ResourceTagMappingList", [])]),
    ]
    rows = [{"check": n, "source": f, "collected_at": collected, "count": len(ids), "ids": [mask(i) for i in ids],
             "status": "PASS" if not ids else "RESIDUAL"} for n, f, ids in checks]
    if a.json:
        print(json.dumps({"env": a.env, "rows": rows}, indent=1))
    else:
        for r in rows:
            print(f"{r['status']:8} {r['check']:10} {r['count']} from {r['source']} at {r['collected_at']} {' '.join(r['ids'])}")
    bad = [r for r in rows if r["status"] != "PASS"]
    print(f"RESIDUAL CHECK {'PASSED: nothing of ' + a.env + ' remains' if not bad else 'FAILED: ' + str(len(bad)) + ' check(s) found resources'}")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("cost"); s.add_argument("--scenario", default="staging-pass"); s.add_argument("--sheet", default=SHEET)
    s.add_argument("--set", action="append"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("after-shutdown"); s.add_argument("--env", default="staging", choices=list(ENV))
    s = sub.add_parser("teardown-rehearse"); s.add_argument("inventory"); s.add_argument("--now", required=True)
    s = sub.add_parser("verify-commands"); s.add_argument("--env", required=True, choices=list(ENV)); s.add_argument("--out", required=True)
    s.add_argument("--profile", default="flh-staging-release")
    s = sub.add_parser("residual"); s.add_argument("dir"); s.add_argument("--env", required=True, choices=list(ENV))
    s.add_argument("--json", action="store_true")
    a = ap.parse_args()
    return {"cost": cmd_cost, "after-shutdown": cmd_after_shutdown, "teardown-rehearse": cmd_teardown_rehearse,
            "verify-commands": cmd_verify_commands, "residual": cmd_residual}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
