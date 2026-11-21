#!/usr/bin/env python3
"""Owner daytime slot for one synthetic staging pass: inputs, go-or-hold, roles and limits. Offline only.

  daytime.py template --out INPUTS.json        the exact owner inputs, as placeholders (never real values in Git)
  daytime.py check INPUTS.json [--now ISO] [--json]
                                               GO only when every input is filled, consistent and approved
  daytime.py roles [--json]                    each daytime operation and the role that performs it
  daytime.py limits [--json]                   proposed runtime and spending limits, each ENFORCED or ALERT-ONLY
  daytime.py page INPUTS.json --out PAGE.md [--now ISO]
                                               the one-page go-or-hold for the morning
  daytime.py cost [--json]                     one-run and steady-state estimates by category, demo apart,
                                               plus the illustrative bounded model smoke (dated rates only)
  daytime.py residual [--json]                 what can still bill after teardown, and how to see it
  daytime.py bill-template --out BILL.json     the redacted billing fields the owner copies from the console
  daytime.py bill BILL.json [--json]           amount due and months covered from those fields
  daytime.py quotas [--running-vcpu N] [--json]
                                               quota checks with their formulas and the headroom they need
  daytime.py model-record [--rendered JOB.json] [--manifest MANIFEST.json --readyz-status N --expect-deployment ID]
                                               one evidence record with SEPARATE render and readiness sections;
                                               a valid render proves nothing about readiness, and the reverse
  daytime.py checklist                         the copyable go-or-hold checklist: who supplies each item, the stop
                                               triggers before any live write, and the rollback entry

No AWS call, no network, no Git, standard library only. The inputs file holds no credential: profiles are
names, the account is a SHA-256 (candidate.py gate compares it), and the operator's sign-in stays in the
AWS CLI's own cache. Exit codes: check/page 0 GO, 1 HOLD, 2 unreadable or malformed.
"""
import argparse
import datetime
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHEET = os.path.join(HERE, "..", "cost_sheet.json")
# A dated rate that is not in the sheet, already approved in a merged runbook (label and date travel with it).
TRAINING_RATE = {"instance": "ml.g5.xlarge", "usd_per_hour": 1.408, "region": "us-east-1",
                 "source": "tools/extraction/TRAINING_RUNBOOK.md §10 (A6 handoff, 2026-11-07)", "as_of": "2026-11-07"}
BASE_WEIGHTS_GB = 9.319737856   # Qwen/Qwen3.5-4B revision 851bf6e8, readiness input manifest

FORMAT = "flh-daytime-inputs/v1"
# The R4 candidate and rollback (docs/plans/FLH-R4-release-candidate.md §2; standin bundles' .sha256 files).
PINNED = {"flh-staging-35da542d0dd4.tar": "d9db57a6edb5dfcc22e3ffc63a1fa2913ca7ad867917588919429ca9f8d88f70",
          "flh-staging-57ec7085dc61.tar": "d53d71b76f1fae8716400c2ddf2adb33197c455b7c9fcc453d65f0be8ab7d988"}
DEMO_VCPU = 2            # the running public demo, t4g.micro (verified in the R5 snapshot)
STAGING_VCPU = 2         # t3.small, fixed by the deploy-ec2 policy
WINDOW_MAX_HOURS = 6     # 4 h of runtime plus 2 h for install, checks and teardown
CAP_CEILING_USD = 10.0   # a first pass needs no more; the pass itself is estimated at about $0.12

TEMPLATE = {
    "format": FORMAT,
    "run": {"run_id": "<YYYYMMDDTHHMMSSZ, the same as terraform.tfvars>", "region": "us-east-1", "environment": "staging",
            "window_start_utc": "<YYYY-MM-DDTHH:MM:SSZ>", "window_end_utc": "<YYYY-MM-DDTHH:MM:SSZ, at most 6 h later>",
            "expires_at": "<YYYY-MM-DDTHH:MM:SSZ, after the window end and at most 24 h after its start>",
            "max_runtime_hours": 4},
    "account": {"allowed_account_sha256": "<sha256 of the 12-digit account ID: printf %s ID | sha256sum>",
                "readonly_profile": "flh-staging-release", "operator_profile": "<operator profile name, not a credential>"},
    "approvals": {"A1_teardown_verification": "<granted (verify-readonly policy) | use-operator-profile>",
                  "A2_staging_pass": False, "A3_iam_policies_created": False, "synthetic_data_only": True},
    "limits": {"budget_cap_usd": 5, "budget_alert_usd": 2, "max_compute_hours": 4},
    "host": {"ami_id": "<ami-… from the public SSM parameter for AL2023 x86_64>", "ami_architecture": "x86_64",
             "instance_type": "t3.small", "compose_plugin_version": "<vX.Y.Z>",
             "compose_plugin_sha256": "<64 hex from the release's checksum file>"},
    "candidate": {"bundle": "flh-staging-35da542d0dd4.tar", "sha256": PINNED["flh-staging-35da542d0dd4.tar"],
                  "rollback_bundle": "flh-staging-57ec7085dc61.tar", "rollback_sha256": PINNED["flh-staging-57ec7085dc61.tar"]},
    "capacity": {"running_standard_vcpu_quota": None},
    "billing": {"baseline_recorded": False},
}

# (operation, role, how the role is obtained, writes?)
ROLES = [
    ("Read-only inventory and residual listing", "read-only SSO profile flh-staging-release", "owner signs in (aws sso login)", "no"),
    ("Teardown verification listings (volumes, addresses, buckets, SSM)", "verify-readonly policy (A1) or the operator profile",
     "IAM administrator attaches flh-stg-verify-readonly, or the owner uses the operator profile", "no"),
    ("Caller identity for candidate.py gate", "operator profile", "owner signs in", "no"),
    ("Render the IAM policies (render_policies.py)", "owner workstation, offline", "no AWS access needed", "no"),
    ("Create the four staging policies and the permissions boundary", "IAM administrator", "console or IAM CLI, A3", "yes (IAM)"),
    ("Budget with a $2 alert", "account owner (billing access)", "Billing console → Budgets, A2", "yes (billing)"),
    ("Quota and billing reads (Service Quotas, Bills, Credits)", "account owner", "console", "no"),
    ("terraform plan / apply / destroy", "operator profile with flh-stg-deploy and flh-stg-deploy-ec2", "owner, A2 + A3", "yes"),
    ("SSM parameters (16 under /flh/staging)", "operator profile with flh-stg-operate", "owner", "yes"),
    ("Upload bundle and synthetic backup to the staging bucket", "operator profile with flh-stg-operate", "owner", "yes"),
    ("SSM session and port forward to the host", "operator profile with flh-stg-operate", "owner", "no (session only)"),
    ("Host-side install, restore, rollback, reboot", "the host role (instance profile under flh-stg-host-boundary)",
     "created by Terraform; used by the host itself", "host bucket only"),
    ("DNS records (vanquisher.world)", "domain owner (registrar console)", "not part of the staging pass", "yes (DNS)"),
]

# (limit, value, kind, enforced by)
LIMITS = [
    ("Compute runtime per pass", "4 h (max_runtime_hours = 4)", "ENFORCED",
     "the host's power-off timer (cloud-config) and instance_initiated_shutdown_behavior = terminate"),
    ("Expiry tag", "ExpiresAt ≤ 24 h after the start", "ENFORCED before apply",
     "preflight.py refuses a later or missing value; IAM requires the tag; nothing in AWS acts on it later"),
    ("Instance type", "t3.small only", "ENFORCED", "flh-stg-deploy-ec2 condition ec2:InstanceType"),
    ("Volume type", "gp3 only", "ENFORCED", "flh-stg-deploy-ec2 condition ec2:VolumeType"),
    ("Volume sizes", "16 GiB root + 8 GiB data", "ENFORCED before apply", "Terraform declaration and plan_check.py (no IAM size condition)"),
    ("Resource set", "21 Terraform addresses, nothing else", "ENFORCED before apply", "plan_check.py STOPs on any other address, ingress, EIP, LB or DNS"),
    ("Data", "synthetic fixture only", "PROCEDURAL", "the owner's A2 approval and the fixture's checksum; no tool can tell real from synthetic"),
    ("Spending cap", "$5 for the pass (estimate ≈ $0.12)", "ALERT-ONLY", "AWS Budgets notifies; it does not stop charges"),
    ("Spending alert", "$2 actual or forecast", "ALERT-ONLY", "AWS Budgets e-mail; arrives hours after the usage"),
    ("Teardown", "same day, destroy plan SAFE, residual check PASSED", "PROCEDURAL", "the owner runs RUNBOOK §9 and lifecycle.py residual"),
]


def lifecycle():
    spec = importlib.util.spec_from_file_location("lifecycle", os.path.join(HERE, "lifecycle.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def demo_scenario(hours, s3_gib):
    """The public demo (Demo lane), estimated for the bill only: t4g.micro, 8 GiB gp3 root (Terraform default; size
    not readable), one public IPv4, a small artifact bucket."""
    return {"instance_type": "t4g.micro", "compute_hours": hours, "storage_hours": hours, "root_gib": 8, "data_gib": 0,
            "snapshot_gib": 0, "s3_gib": s3_gib, "s3_puts": 50, "s3_gets": 500, "ipv4": 1,
            "log_ingest_gib": 0, "log_store_gib": 0, "alarms": 0}


def costs():
    lc = lifecycle()
    sheet = lc.load_sheet(SHEET)
    def row(group, name, sc, note):
        c = lc.cost(sheet, sc)
        return {"group": group, "scenario": name, "note": note, "compute": round(c["compute"], 4),
                "disks": round(c["disk"] + c["snapshots"], 4), "storage": round(c["storage"] + c["logs"], 4),
                "transfer": None, "public_ipv4": round(c["ipv4"], 4), "total": round(sum(c.values()), 4)}
    sc = sheet["scenarios"]
    rows = [row("one run: private staging", "staging-pass", sc["staging-pass"], sc["staging-pass"]["note"]),
            row("one run: private staging", "staging-not-destroyed-7d", sc["staging-not-destroyed-7d"],
                "residual if teardown is forgotten for 7 days"),
            row("steady state: private production (not approved)", "production-month", sc["production-month"], sc["production-month"]["note"]),
            row("steady state: private production (not approved)", "production-peak-month", sc["production-peak-month"],
                sc["production-peak-month"]["note"]),
            row("steady state: public demo (existing, Demo lane)", "demo-month (bucket 0.05 GiB)", demo_scenario(730, 0.05),
                "running now; R5 snapshot 2026-11-20T21:09:14Z"),
            row("steady state: public demo (existing, Demo lane)", "demo-month (bucket 1 GiB)", demo_scenario(730, 1.0),
                "bucket size unreadable: upper case")]
    storage_rate = sheet["prices"]["storage"]["price"]
    smoke_hours = 0.5
    smoke = {"scenario": "illustrative bounded model smoke (OWNER, paid, not approved)",
             "what": "readiness step 5: rendered/sft-smoke.json, 12 steps, MaxRuntimeInSeconds 1800",
             "compute": round(smoke_hours * TRAINING_RATE["usd_per_hour"], 2),
             "storage": round(BASE_WEIGHTS_GB * storage_rate / sheet["hours_per_month"] * 24, 3),
             "storage_note": f"{BASE_WEIGHTS_GB:.2f} GB of base weights in S3 for one day at ${storage_rate:g}/GB-month",
             "rate": TRAINING_RATE}
    smoke["total_bound"] = round(smoke["compute"] + smoke["storage"], 2)
    unknown = ["model inference on the staging host: not measured (the extraction sidecar is rule-based; no model runs there)",
               "GPU inference for E5 or Qwen outside SageMaker: no approved instance or rate; not proposed",
               "SageMaker predict and experiment steps 6–8: bounded in readiness/README.md but not run; actual cost unknown",
               "ECR storage for the training image and S3 requests during training: not measured",
               "the 50 GB SageMaker training volume of each rendered job: no approved rate in the repository"]
    return {"sheet_as_of": sheet["as_of"], "sheet": "deploy/aws/private-staging/staging/cost_sheet.json",
            "transfer": "no approved rate in the sheet; assumed inside the 100 GB/month free allowance (sheet assumptions)",
            "rows": rows, "model_smoke": smoke, "model_unknown": unknown, "assumptions": sheet["assumptions"]}


RESIDUAL = [
    ("Data volume (8 GiB gp3) and bucket", "only if terraform destroy is not run; the power-off terminates the instance and root disk",
     "about $0.25 per 7 days (scenario staging-not-destroyed-7d)", "describe-volumes --filters tag:Component=workbench-staging; list-buckets flh-stg-*"),
    ("Old object versions in the staging bucket", "if destroy fails before force_destroy empties it", "cents per GB-month",
     "s3api list-object-versions on the flh-stg- bucket"),
    ("Unattached EBS volume", "if the instance was terminated but destroy stopped part-way", "$0.08 per GiB-month",
     "describe-volumes --filters Name=status,Values=available"),
    ("EBS snapshot", "none is created by the plan; only a manual one", "$0.05 per GiB-month", "describe-snapshots --owner-ids self"),
    ("Elastic IP", "none in the plan (plan_check STOPs on one); only if created by hand", "$0.005 per hour, attached or idle",
     "describe-addresses"),
    ("CloudWatch Logs group", "none in the plan (journald on the host); only if Session Manager logging is turned on", "per GiB stored",
     "logs describe-log-groups"),
    ("AWS Budget", "the $2 alert budget the owner creates", "free for the first budgets (confirm on the AWS Budgets pricing page)",
     "Billing → Budgets"),
    ("SSM parameters, IAM policies, default KMS keys", "kept until RUNBOOK §9 or the administrator removes them", "free",
     "ssm get-parameters-by-path /flh/staging; IAM console"),
    ("Public IPv4 (auto-assigned)", "released with the instance", "stops at terminate", "describe-instances"),
    ("Public demo resources", "not part of staging; they keep billing as today", "about $10.42–10.45 per month", "R5 report"),
]

BILL_TEMPLATE = {
    "format": "flh-billing-inputs/v1",
    "comment": "Copy from Billing and Cost Management, redacted: no account ID, name, address, e-mail, card or invoice number.",
    "month": "<YYYY-MM>",
    "charges_before_credits_usd": "<number from Bills: total charges>",
    "credits_applied_usd": "<number from Bills: credits>",
    "tax_usd": "<number from Bills: tax>",
    "total_due_usd": "<number from Bills: total due>",
    "credits_remaining_usd": "<number from Credits: amount remaining>",
    "credit_expiration": "<YYYY-MM-DD from Credits>",
    "credit_applicable_products": "<as listed, e.g. all AWS services>",
    "account_plan": "<Free | Paid>",
    "charges_by_service_usd": {"Elastic Compute Cloud": "<number>", "Virtual Private Cloud": "<number>",
                               "Simple Storage Service": "<number>", "other services (name: amount)": "<text or 0>"},
}

QUOTAS = [
    ("EC2: Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances (vCPU), L-1216C47A",
     "quota − running_vCPU ≥ staging_vCPU", "running_vCPU = 2 (demo t4g.micro), staging_vCPU = 2 (t3.small)", 4),
    ("VPC: VPCs per Region (default 5)", "existing_VPCs + 1 ≤ quota", "existing_VPCs = 2 (demo, default)", 3),
    ("VPC: Internet gateways per Region (default 5)", "existing_IGWs + 1 ≤ quota", "existing_IGWs = 2 (demo, default; IGW reads refused)", 3),
    ("EC2: EC2-VPC Elastic IPs (L-0263D0A3)", "staging needs 0", "the demo may hold 1", 0),
    ("EBS: Storage for gp3 volumes (TiB)", "used_TiB + 0.024 ≤ quota", "staging adds 16 + 8 GiB", 0.024),
    ("S3: General purpose buckets per account", "existing_buckets + 1 ≤ quota", "bucket list refused", 1),
    ("SageMaker: ml.g5.xlarge for training job usage (model smoke only)", "quota ≥ 1", "new accounts often start at 0", 1),
]


def parse_utc(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def placeholders(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from placeholders(v, f"{path}.{k}" if path else k)
    elif isinstance(o, str) and o.startswith("<"):
        yield path


def check(inp, now):
    """Returns (holds, notes). holds: reasons the slot is not a GO. notes: facts that are fine but worth reading."""
    holds, notes = [], []
    H = holds.append
    if inp.get("format") != FORMAT:
        return [f"format must be {FORMAT}"], notes
    for p in placeholders(inp):
        H(f"placeholder left: {p}")
    r, acct, appr, lim = inp.get("run", {}), inp.get("account", {}), inp.get("approvals", {}), inp.get("limits", {})
    host, cand, cap = inp.get("host", {}), inp.get("candidate", {}), inp.get("capacity", {})
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", str(r.get("run_id", ""))) and not str(r.get("run_id", "")).startswith("<"):
        H("run.run_id must look like 20261121T090000Z (terraform.tfvars run_id)")
    if r.get("region") != "us-east-1":
        H("run.region must be us-east-1 (the IAM templates, AMI pin and cost sheet name it)")
    if r.get("environment") != "staging":
        H("run.environment must be staging: this slot never touches production or the demo")
    try:
        ws, we, ex = parse_utc(r["window_start_utc"]), parse_utc(r["window_end_utc"]), parse_utc(r["expires_at"])
        hours = (we - ws).total_seconds() / 3600
        if hours <= 0:
            H("run.window_end_utc must be after window_start_utc")
        elif hours > WINDOW_MAX_HOURS:
            H(f"the window is {hours:.1f} h; at most {WINDOW_MAX_HOURS} h (4 h runtime + install, checks and teardown)")
        if not we < ex <= ws + datetime.timedelta(hours=24):
            H("run.expires_at must be after the window end and at most 24 h after its start (preflight refuses otherwise)")
        if now and we < now:
            H("the window has already ended")
        if now and ws > now + datetime.timedelta(hours=24):
            notes.append("the window starts more than 24 h from now; preflight's expiry check runs on the day")
    except (KeyError, ValueError):
        if not any(p.startswith("run.window") or p == "run.expires_at" for p in placeholders(inp)):
            H("run window and expires_at must be UTC times like 2026-11-21T09:00:00Z")
    mrh = r.get("max_runtime_hours")
    if not (isinstance(mrh, int) and 1 <= mrh <= 4):
        H("run.max_runtime_hours must be 1–4 for a first pass (Terraform allows up to 12)")
    if not re.fullmatch(r"[0-9a-f]{64}", str(acct.get("allowed_account_sha256", ""))) and not str(acct.get("allowed_account_sha256", "")).startswith("<"):
        H("account.allowed_account_sha256 must be 64 lowercase hex (a hash, never the account ID)")
    if re.search(r"\b\d{12}\b", json.dumps(inp)):
        H("the inputs contain a 12-digit number: remove the account ID; only its SHA-256 belongs here")
    if acct.get("readonly_profile") != "flh-staging-release":
        H("account.readonly_profile must be flh-staging-release")
    if acct.get("operator_profile") == acct.get("readonly_profile"):
        H("account.operator_profile must differ from the read-only profile (it cannot apply)")
    if appr.get("A2_staging_pass") is not True:
        H("A2 not approved: budget, window, account and synthetic-only staging pass")
    if appr.get("A3_iam_policies_created") is not True:
        H("A3 not done: an IAM administrator creates the four staging policies and the boundary")
    if appr.get("synthetic_data_only") is not True:
        H("approvals.synthetic_data_only must be true: no learner data in staging")
    if appr.get("A1_teardown_verification") not in ("granted", "use-operator-profile") and not str(appr.get("A1_teardown_verification", "")).startswith("<"):
        H("A1 must be granted or use-operator-profile: otherwise teardown cannot be proven")
    c, al, mch = lim.get("budget_cap_usd"), lim.get("budget_alert_usd"), lim.get("max_compute_hours")
    if not (isinstance(c, (int, float)) and 0 < c <= CAP_CEILING_USD):
        H(f"limits.budget_cap_usd must be > 0 and ≤ {CAP_CEILING_USD:g} for a first pass")
    if not (isinstance(al, (int, float)) and isinstance(c, (int, float)) and 0 < al < c):
        H("limits.budget_alert_usd must be > 0 and below the cap")
    if not (isinstance(mch, (int, float)) and isinstance(mrh, int) and 0 < mch <= mrh):
        H("limits.max_compute_hours must be > 0 and ≤ run.max_runtime_hours")
    ami = str(host.get("ami_id", ""))
    if not ami.startswith("<") and not re.fullmatch(r"ami-[0-9a-f]{8,17}", ami):
        H("host.ami_id must look like ami-0123456789abcdef0")
    if host.get("ami_architecture") != "x86_64":
        H("host.ami_architecture must be x86_64: the candidate image is linux/amd64 and the policy allows t3.small")
    if host.get("instance_type") != "t3.small":
        H("host.instance_type must be t3.small (the deploy-ec2 policy refuses any other type)")
    cs = str(host.get("compose_plugin_sha256", ""))
    if not cs.startswith("<") and not re.fullmatch(r"[0-9a-f]{64}", cs):
        H("host.compose_plugin_sha256 must be 64 lowercase hex")
    for b, s in (("bundle", "sha256"), ("rollback_bundle", "rollback_sha256")):
        name, digest = cand.get(b), cand.get(s)
        if not re.fullmatch(r"[0-9a-f]{64}", str(digest or "")):
            H(f"candidate.{s} must be 64 lowercase hex")
        elif name in PINNED and PINNED[name] != digest:
            H(f"candidate.{s} does not match the recorded SHA-256 of {name}")
        elif name not in PINNED:
            notes.append(f"{name} is not the R4 pin: candidate.py promote-check must PROMOTE it before the slot")
    if cand.get("bundle") == cand.get("rollback_bundle"):
        H("the rollback bundle must differ from the candidate")
    q = cap.get("running_standard_vcpu_quota")
    need = DEMO_VCPU + STAGING_VCPU
    if q is None:
        H(f"capacity unverified: running on-demand standard vCPU quota must be ≥ {need} (demo {DEMO_VCPU} + staging {STAGING_VCPU})")
    elif not isinstance(q, (int, float)) or q < need:
        H(f"vCPU quota {q} < {need}: request an increase before the slot")
    if inp.get("billing", {}).get("baseline_recorded") is not True:
        H("billing baseline not recorded: note today's month-to-date charges so tomorrow's bill can be compared")
    return holds, notes


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        print(f"daytime: unreadable {path}: {type(e).__name__}: {e}", file=sys.stderr)
        raise SystemExit(2)


def bill(b, as_json):
    """Amount due and months covered from the owner's redacted billing fields; refuses identifiers."""
    problems = []
    if b.get("format") != "flh-billing-inputs/v1":
        problems.append("format must be flh-billing-inputs/v1")
    if re.search(r"\b\d{12}\b|@|\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b", json.dumps(b)):
        problems.append("the file contains an account ID, e-mail or card-like number: remove it")
    def num(k):
        v = b.get(k)
        if isinstance(v, (int, float)) and v >= 0:
            return float(v)
        problems.append(f"{k} is not filled with a non-negative number")
        return None
    ch, cr, tx, cl = num("charges_before_credits_usd"), num("credits_applied_usd"), num("tax_usd"), num("credits_remaining_usd")
    due_stated = b.get("total_due_usd") if isinstance(b.get("total_due_usd"), (int, float)) else None
    out = {"problems": problems}
    if not problems:
        due = max(0.0, ch - cr) + tx
        rate = round(next(r["total"] for r in costs()["rows"] if r["scenario"] == "demo-month (bucket 1 GiB)"), 2)
        out.update(amount_due_usd=round(due, 2), stated_total_due_usd=due_stated,
                   matches_statement=None if due_stated is None else abs(due - due_stated) < 0.01,
                   demo_months_covered_by_remaining_credits=round(cl / rate, 1) if rate else None,
                   demo_month_estimate_usd=rate, credit_expiration=b.get("credit_expiration"))
    if as_json:
        print(json.dumps(out, indent=1))
    elif problems:
        for p_ in problems:
            print(f"REFUSED  {p_}")
    else:
        print(f"Amount due: ${out['amount_due_usd']:.2f} (max(0, charges − credits) + tax)"
              + ("" if due_stated is None else f"; the bill states ${due_stated:.2f}" + ("" if out["matches_statement"] else " (DIFFERS)")))
        print(f"Remaining credits cover about {out['demo_months_covered_by_remaining_credits']} month(s) of the demo at "
              f"${out['demo_month_estimate_usd']:.2f}/month, unless they expire first ({out['credit_expiration']}).")
    return 0 if not problems else 1


def sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def model_record(rendered, manifest, readyz_status, expect):
    """Render evidence (a job file) and readiness evidence (a live /manifest and /readyz) never vouch for each other."""
    rec = {"format": "flh-model-evidence/v1", "render": {"state": "not_collected"}, "readiness": {"state": "not_collected"}}
    if rendered:
        j = load(rendered)
        raw = json.dumps(j)
        problems = []
        rc, sc = j.get("ResourceConfig", {}), j.get("StoppingCondition", {})
        if re.search(r"\b0{12}\b|sha256:0{64}|example-", raw):
            problems.append("placeholders left (all-zero account or digest, example bucket): a dry render, not a submittable job")
        if not re.search(r"@sha256:[0-9a-f]{64}", json.dumps(j.get("AlgorithmSpecification", {}))):
            problems.append("training image is not pinned by digest")
        if j.get("EnableNetworkIsolation") is not True:
            problems.append("network isolation is off")
        mx = sc.get("MaxRuntimeInSeconds")
        if not (isinstance(mx, int) and 0 < mx <= 10800):
            problems.append("MaxRuntimeInSeconds missing or above 3 h")
        if rc.get("InstanceType") != "ml.g5.xlarge" or rc.get("InstanceCount") != 1:
            problems.append("instance must be 1 x ml.g5.xlarge (the priced bound)")
        rec["render"] = {"state": "ok" if not problems else "not_submittable", "problems": problems,
                         "file_sha256": sha256_file(rendered), "instance": rc.get("InstanceType"), "count": rc.get("InstanceCount"),
                         "volume_gb": rc.get("VolumeSizeInGB"), "max_runtime_s": mx, "network_isolation": j.get("EnableNetworkIsolation"),
                         "note": "recorded without the account, role, bucket or image registry"}
    if manifest:
        m = load(manifest)
        body = m.get("body", m)
        observed = body.get("deployment_id")
        problems = []
        if readyz_status != 200:
            problems.append(f"/readyz answered {readyz_status}, not 200")
        if not expect:
            problems.append("no expected deployment_id was given")
        elif observed != expect:
            problems.append(f"deployment_id {observed!r} differs from the recorded {expect!r}")
        rec["readiness"] = {"state": "ready" if not problems else "not_ready", "problems": problems, "readyz_status": readyz_status,
                            "deployment_id_observed": observed, "deployment_id_expected": expect,
                            "manifest_sha256": sha256_file(manifest)}
    return rec


# (item, who supplies it, how it is checked)
CHECKLIST = [
    ("Daytime inputs filled (no <placeholder> left)", "owner", "daytime.py check <inputs.json> says GO"),
    ("A2 approved: budget cap, window, account, synthetic data only", "owner", "approvals.A2_staging_pass = true"),
    ("A3 done: four staging policies + host boundary created", "IAM administrator", "approvals.A3_iam_policies_created = true"),
    ("A1 decided: verify-readonly attached, or the operator profile does the listings", "owner / IAM administrator", "approvals.A1_teardown_verification"),
    ("Budget with a $2 alert exists", "owner (billing access)", "Billing → Budgets"),
    ("Billing baseline recorded (month-to-date charges per service)", "owner (billing access)", "daytime.py bill-template, filled"),
    ("vCPU quota ≥ running + 2", "owner (Service Quotas console)", "daytime.py quotas; capacity.running_standard_vcpu_quota"),
    ("AL2023 x86_64 AMI ID and Compose plugin SHA-256", "owner", "host.ami_id, host.compose_plugin_sha256"),
    ("Operator signed in; caller identity matches the allowed account hash", "owner", "candidate.py gate → GATE PASSED"),
    ("Candidate and rollback bundles verified", "owner (local)", "candidate.py promote-check → PROMOTE; sha256sum -c"),
    ("Stand-in rehearsal of this candidate COMPLETE", "owner or agent (local)", "evidence_index.py --approve <run_id> → APPROVABLE"),
    ("No staging resource exists before the start", "owner (read-only listings)", "lifecycle.py residual → PASSED on fresh evidence"),
]
STOP_TRIGGERS = [
    "daytime.py check says HOLD",
    "candidate.py gate is not GATE PASSED (wrong account hash, region, environment or workspace)",
    "candidate.py promote-check is not PROMOTE, or a bundle's sha256sum -c fails",
    "preflight.py is not READY",
    "plan_check.py is not SAFE, or the create plan is not exactly 21 to add, 0 to change, 0 to destroy",
    "the plan names any demo address, ingress rule, Elastic IP, load balancer or DNS record",
    "a residual listing before the start is not PASSED (something of staging already exists)",
    "a Budgets alert arrives, or the window has less than 1 h left before teardown must start",
    "any command prints an account ID, credential or learner data: stop, do not paste it anywhere",
    "anything touches the demo or the daily instance",
]
ROLLBACK_ENTRY = [
    "Before apply: nothing exists; stop and fix the input.",
    "After apply, before install: terraform plan -destroy → plan_check.py --mode destroy (SAFE) → apply; RUNBOOK §9.",
    "After a failed install: flh-staging-bundle switches back by itself; if not, flh-staging-bundle rollback (re-verifies previous).",
    "After a bad restore: flh-daily.sh restore of the pre-install backup named in deploy.log.",
    "In every case end with teardown and lifecycle.py residual → PASSED; record what happened.",
]


def checklist_text():
    out = ["# Daytime go-or-hold checklist (copy, fill the <placeholders>, tick each line)", "",
           "Inputs file: `<~/flh-daytime/inputs.json>` · operator profile: `<operator-profile>` · run: `<YYYYMMDDTHHMMSSZ>`", "",
           "## Go only when every line is ticked", ""]
    out += [f"- [ ] {i} (who: {w}; check: {c})" for i, w, c in CHECKLIST]
    out += ["", "## Stop before any live write if", ""] + [f"- {t}" for t in STOP_TRIGGERS]
    out += ["", "## Rollback entry", ""] + [f"{n}. {r}" for n, r in enumerate(ROLLBACK_ENTRY, 1)]
    return "\n".join(out) + "\n"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    out += ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in rows]
    return "\n".join(out)


def page(inp, now):
    holds, notes = check(inp, now)
    verdict = "GO" if not holds else "HOLD"
    r = inp.get("run", {})
    lines = [f"# Daytime staging slot: {verdict}", "",
             f"Run `{r.get('run_id')}` · {r.get('region')} · window {r.get('window_start_utc')} → {r.get('window_end_utc')} · "
             f"generated {now.strftime('%Y-%m-%dT%H:%M:%SZ') if now else '-'} by `daytime.py page` (offline).", ""]
    if holds:
        lines += ["## Why HOLD", ""] + [f"- {h}" for h in holds] + [""]
    else:
        lines += ["## GO", "", "Every input is filled, consistent and approved. Start with RUNBOOK §1 and stop at the first refusal.", ""]
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    lines += ["## Limits", "", table(["Limit", "Value", "Kind", "Enforced by"], LIMITS), "",
              "ALERT-ONLY limits do not stop spending. The enforced ones are the runtime, the instance and volume types, the "
              "resource set and the expiry tag.", "",
              "## Who does what", "", table(["Operation", "Role", "How obtained", "Writes"], ROLES), "",
              "## Before the slot (offline, rehearsed)", "",
              "- Stand-in rehearsal: `python3 -I deploy/aws/private-staging/staging/rehearsal/r4_release_rehearsal.py --candidate … "
              "--rollback … --broken … --ahead … --fixture … --inventory scripts/validation/migration/inventory.py WORK` "
              "(R4 run 24/24; see docs/plans/FLH-AWS-PREP-20261121.md §9).",
              "- Gates: `candidate.py gate`, `candidate.py promote-check`, `candidate.py authorize` (dry run), `preflight.py`.", ""]
    return verdict, "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("template"); s.add_argument("--out", required=True)
    s = sub.add_parser("check"); s.add_argument("inputs"); s.add_argument("--now"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("roles"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("limits"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("page"); s.add_argument("inputs"); s.add_argument("--out", required=True); s.add_argument("--now")
    s = sub.add_parser("cost"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("residual"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("bill-template"); s.add_argument("--out", required=True)
    s = sub.add_parser("bill"); s.add_argument("billing"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("quotas"); s.add_argument("--running-vcpu", type=int, default=2); s.add_argument("--json", action="store_true")
    sub.add_parser("checklist")
    s = sub.add_parser("model-record"); s.add_argument("--rendered"); s.add_argument("--manifest")
    s.add_argument("--readyz-status", type=int); s.add_argument("--expect-deployment")
    a = ap.parse_args()
    if a.cmd == "checklist":
        print(checklist_text(), end="")
        return 0
    if a.cmd == "model-record":
        if not (a.rendered or a.manifest):
            print("model-record: give --rendered and/or --manifest", file=sys.stderr)
            return 2
        rec = model_record(a.rendered, a.manifest, a.readyz_status, a.expect_deployment)
        print(json.dumps(rec, indent=1))
        bad = [k for k in ("render", "readiness") if rec[k]["state"] not in ("ok", "ready", "not_collected")]
        return 1 if bad else 0
    if a.cmd == "cost":
        c = costs()
        if a.json:
            print(json.dumps(c, indent=1))
            return 0
        money = lambda v: "n/a (see note)" if v is None else ("<$0.01" if 0 < v < 0.005 else f"${v:,.2f}")
        print(f"Rates: cost sheet as of {c['sheet_as_of']} (list prices, not fetched); training rate as of {TRAINING_RATE['as_of']}.")
        print(table(["Group", "Scenario", "Compute", "Disks", "Storage", "Transfer", "Public IPv4", "Total"],
                    [(r["group"], r["scenario"], money(r["compute"]), money(r["disks"]), money(r["storage"]), money(r["transfer"]),
                      money(r["public_ipv4"]), money(r["total"])) for r in c["rows"]]))
        print(f"Transfer: {c['transfer']}.")
        m = c["model_smoke"]
        print(f"Model smoke (illustrative, {m['what']}): compute {money(m['compute'])} at ${TRAINING_RATE['usd_per_hour']}/h "
              f"({TRAINING_RATE['source']}) + storage {money(m['storage'])} ({m['storage_note']}) = at most {money(m['total_bound'])}.")
        print("Unknown (not measured): " + "; ".join(c["model_unknown"]) + ".")
        return 0
    if a.cmd == "residual":
        head = ["Possible residual", "When", "Cost", "How to see it"]
        print(json.dumps([dict(zip(head, r)) for r in RESIDUAL], indent=1) if a.json else table(head, RESIDUAL))
        return 0
    if a.cmd == "bill-template":
        with open(a.out, "x", encoding="utf-8") as fh:
            json.dump(BILL_TEMPLATE, fh, indent=2)
            fh.write("\n")
        print(f"wrote {a.out}: fill the numbers from the console, redacted; keep it outside the repository")
        return 0
    if a.cmd == "bill":
        return bill(load(a.billing), a.json)
    if a.cmd == "quotas":
        head = ["Quota", "Formula", "Inputs", "Needs"]
        rows = [(q, f, i.replace("running_vCPU = 2", f"running_vCPU = {a.running_vcpu}"),
                 a.running_vcpu + 2 if n == 4 else n) for q, f, i, n in QUOTAS]
        print(json.dumps([dict(zip(head, r)) for r in rows], indent=1) if a.json else table(head, rows))
        return 0
    now = parse_utc(a.now) if getattr(a, "now", None) else (datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
                                                             if a.cmd in ("check", "page") else None)
    if a.cmd == "template":
        with open(a.out, "x", encoding="utf-8") as fh:
            json.dump(TEMPLATE, fh, indent=2)
            fh.write("\n")
        print(f"wrote {a.out}: fill every <placeholder>; keep the file outside the repository")
        return 0
    if a.cmd in ("roles", "limits"):
        rows, head = (ROLES, ["Operation", "Role", "How obtained", "Writes"]) if a.cmd == "roles" else \
                     (LIMITS, ["Limit", "Value", "Kind", "Enforced by"])
        print(json.dumps([dict(zip(head, r)) for r in rows], indent=1) if a.json else table(head, rows))
        return 0
    inp = load(a.inputs)
    if a.cmd == "check":
        holds, notes = check(inp, now)
        if a.json:
            print(json.dumps({"verdict": "GO" if not holds else "HOLD", "holds": holds, "notes": notes}, indent=1))
        else:
            for n in notes:
                print(f"NOTE  {n}")
            for h in holds:
                print(f"HOLD  {h}")
            print("GO: every input is filled, consistent and approved" if not holds else f"HOLD: {len(holds)} reason(s)")
        return 0 if not holds else 1
    verdict, text = page(inp, now)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"{verdict}: wrote {a.out}")
    return 0 if verdict == "GO" else 1


if __name__ == "__main__":
    sys.exit(main())
