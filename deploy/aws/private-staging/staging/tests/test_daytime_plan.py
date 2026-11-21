"""Tests for the owner daytime plan tools (synthetic inputs only; no AWS, no network, no Git)."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
DAYTIME = os.path.join(TOOLS, "daytime.py")
NOW = "2026-11-21T08:00:00Z"


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def run(*args, cwd=None):
    return subprocess.run([sys.executable, "-I", "-B", *args], capture_output=True, text=True, cwd=cwd)


def filled(template):
    d = copy.deepcopy(template)
    d["run"].update(run_id="20261121T140000Z", window_start_utc="2026-11-21T14:00:00Z",
                    window_end_utc="2026-11-21T19:00:00Z", expires_at="2026-11-21T22:00:00Z")
    d["account"].update(allowed_account_sha256=hashlib.sha256(b"synthetic-account").hexdigest(), operator_profile="flh-operator-SYNTHETIC")
    d["approvals"].update(A1_teardown_verification="use-operator-profile", A2_staging_pass=True, A3_iam_policies_created=True)
    d["host"].update(ami_id="ami-0123456789abcdef0", compose_plugin_version="v2.99.0",
                     compose_plugin_sha256=hashlib.sha256(b"synthetic-compose").hexdigest())
    d["capacity"]["running_standard_vcpu_quota"] = 5
    d["billing"]["baseline_recorded"] = True
    return d


class DaytimeInputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = os.path.join(self.tmp.name, "template.json")
        r = run(DAYTIME, "template", "--out", self.t)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.template = json.loads(read(self.t))

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, data):
        p = os.path.join(self.tmp.name, "inputs.json")
        write(p, json.dumps(data))
        r = run(DAYTIME, "check", p, "--now", NOW, "--json")
        self.assertIn(r.returncode, (0, 1), r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["verdict"] == "GO", r.returncode == 0)
        return out

    def test_template_holds_and_names_every_placeholder(self):
        out = self.check(self.template)
        self.assertEqual(out["verdict"], "HOLD")
        text = "\n".join(out["holds"])
        for field in ("run.run_id", "account.allowed_account_sha256", "account.operator_profile", "host.ami_id",
                      "host.compose_plugin_sha256", "approvals.A1_teardown_verification"):
            self.assertIn(f"placeholder left: {field}", text)
        self.assertIn("A2 not approved", text)
        self.assertIn("capacity unverified", text)

    def test_template_is_never_overwritten(self):
        r = run(DAYTIME, "template", "--out", self.t)
        self.assertNotEqual(r.returncode, 0)

    def test_filled_synthetic_inputs_go(self):
        self.assertEqual(self.check(filled(self.template)), {"verdict": "GO", "holds": [], "notes": []})

    def test_each_rule_holds(self):
        cases = {
            "window": (lambda d: d["run"].update(window_end_utc="2026-11-21T21:00:00Z"), "the window is 7.0 h"),
            "expiry": (lambda d: d["run"].update(expires_at="2026-11-22T15:00:00Z"), "expires_at must be after"),
            "runtime": (lambda d: d["run"].update(max_runtime_hours=8), "max_runtime_hours must be 1–4"),
            "account id": (lambda d: d["account"].update(operator_profile="op-123456789012"), "12-digit number"),
            "same profile": (lambda d: d["account"].update(operator_profile="flh-staging-release"), "must differ"),
            "real data": (lambda d: d["approvals"].update(synthetic_data_only=False), "synthetic_data_only"),
            "alert above cap": (lambda d: d["limits"].update(budget_alert_usd=6), "below the cap"),
            "cap ceiling": (lambda d: d["limits"].update(budget_cap_usd=50, budget_alert_usd=2), "≤ 10"),
            "arm ami": (lambda d: d["host"].update(ami_architecture="arm64"), "linux/amd64"),
            "type": (lambda d: d["host"].update(instance_type="t3.medium"), "t3.small"),
            "digest": (lambda d: d["candidate"].update(sha256="0" * 64), "does not match the recorded SHA-256"),
            "same rollback": (lambda d: d["candidate"].update(rollback_bundle=d["candidate"]["bundle"],
                                                              rollback_sha256=d["candidate"]["sha256"]), "must differ from the candidate"),
            "quota": (lambda d: d["capacity"].update(running_standard_vcpu_quota=2), "vCPU quota 2 < 4"),
            "baseline": (lambda d: d["billing"].update(baseline_recorded=False), "billing baseline"),
            "past": (lambda d: d["run"].update(window_start_utc="2026-11-20T01:00:00Z", window_end_utc="2026-11-20T05:00:00Z",
                                               expires_at="2026-11-20T09:00:00Z"), "already ended"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(name):
                d = filled(self.template)
                mutate(d)
                out = self.check(d)
                self.assertEqual(out["verdict"], "HOLD")
                self.assertTrue(any(needle in h for h in out["holds"]), out["holds"])

    def test_unpinned_candidate_is_a_note_not_a_go_blocker(self):
        d = filled(self.template)
        d["candidate"].update(bundle="flh-staging-aaaaaaaaaaaa.tar", sha256="a" * 64)
        out = self.check(d)
        self.assertEqual(out["verdict"], "GO")
        self.assertIn("promote-check", out["notes"][0])

    def test_malformed_file_is_exit_2(self):
        p = os.path.join(self.tmp.name, "bad.json")
        write(p, "{not json")
        self.assertEqual(run(DAYTIME, "check", p).returncode, 2)

    def test_page_exit_codes_and_sections(self):
        hold = os.path.join(self.tmp.name, "hold.md")
        go = os.path.join(self.tmp.name, "go.md")
        gi = os.path.join(self.tmp.name, "go.json")
        write(gi, json.dumps(filled(self.template)))
        self.assertEqual(run(DAYTIME, "page", self.t, "--out", hold, "--now", NOW).returncode, 1)
        self.assertEqual(run(DAYTIME, "page", gi, "--out", go, "--now", NOW).returncode, 0)
        h, g = read(hold), read(go)
        self.assertTrue(h.startswith("# Daytime staging slot: HOLD"))
        self.assertTrue(g.startswith("# Daytime staging slot: GO"))
        for section in ("## Limits", "## Who does what", "## Before the slot"):
            self.assertIn(section, g)


class DaytimeRolesAndLimits(unittest.TestCase):
    def test_limits_mark_spending_as_alert_only(self):
        rows = json.loads(run(DAYTIME, "limits", "--json").stdout)
        kinds = {r["Limit"]: r["Kind"] for r in rows}
        self.assertEqual(kinds["Spending cap"], "ALERT-ONLY")
        self.assertEqual(kinds["Spending alert"], "ALERT-ONLY")
        self.assertEqual(kinds["Compute runtime per pass"], "ENFORCED")
        self.assertEqual(kinds["Instance type"], "ENFORCED")

    def test_roles_keep_writes_off_the_read_only_profile(self):
        rows = json.loads(run(DAYTIME, "roles", "--json").stdout)
        for r in rows:
            if "flh-staging-release" in r["Role"]:
                self.assertEqual(r["Writes"], "no", r)
        ops = {r["Operation"]: r["Role"] for r in rows}
        self.assertIn("operator", ops["terraform plan / apply / destroy"])
        self.assertIn("IAM administrator", ops["Create the four staging policies and the permissions boundary"])


if __name__ == "__main__":
    unittest.main()


class DaytimeCost(unittest.TestCase):
    def test_cost_rows_come_from_the_sheet_and_keep_the_demo_apart(self):
        c = json.loads(run(DAYTIME, "cost", "--json").stdout)
        self.assertEqual(c["sheet_as_of"], "2026-11-20")
        rows = {r["scenario"]: r for r in c["rows"]}
        self.assertAlmostEqual(rows["staging-pass"]["total"], 0.1166, places=3)
        self.assertAlmostEqual(rows["production-month"]["total"], 22.00, places=1)
        self.assertTrue(all(r["transfer"] is None for r in c["rows"]), "transfer has no approved rate")
        demo = [r for r in c["rows"] if "public demo" in r["group"]]
        self.assertEqual(len(demo), 2)
        self.assertTrue(all("private" not in r["group"] for r in demo))
        self.assertAlmostEqual(sum(r[k] for k in ("compute", "disks", "storage", "public_ipv4")
                                   for r in [rows["staging-pass"]]), rows["staging-pass"]["total"], places=3)

    def test_model_smoke_is_bounded_dated_and_model_costs_stay_unknown(self):
        c = json.loads(run(DAYTIME, "cost", "--json").stdout)
        m = c["model_smoke"]
        self.assertEqual(m["rate"]["as_of"], "2026-11-07")
        self.assertAlmostEqual(m["compute"], 0.70, places=2)
        self.assertLessEqual(m["total_bound"], 0.72)
        self.assertTrue(any("not measured" in u for u in c["model_unknown"]))

    def test_residual_lists_the_data_volume_and_elastic_ip(self):
        rows = json.loads(run(DAYTIME, "residual", "--json").stdout)
        names = " ".join(r["Possible residual"] for r in rows)
        for needle in ("Data volume", "Unattached EBS volume", "Elastic IP", "snapshot", "Public demo"):
            self.assertIn(needle, names)

    def test_quota_formula_follows_running_vcpu(self):
        rows = json.loads(run(DAYTIME, "quotas", "--json").stdout)
        self.assertEqual(rows[0]["Needs"], 4)
        rows = json.loads(run(DAYTIME, "quotas", "--running-vcpu", "6", "--json").stdout)
        self.assertEqual(rows[0]["Needs"], 8)
        self.assertTrue(any("SageMaker" in r["Quota"] for r in rows))


class DaytimeBill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = os.path.join(self.tmp.name, "bill.json")
        self.assertEqual(run(DAYTIME, "bill-template", "--out", self.t).returncode, 0)
        self.b = json.loads(read(self.t))

    def tearDown(self):
        self.tmp.cleanup()

    def bill(self, data):
        p = os.path.join(self.tmp.name, "filled.json")
        write(p, json.dumps(data))
        r = run(DAYTIME, "bill", p, "--json")
        return r.returncode, json.loads(r.stdout)

    def test_template_is_refused_until_filled(self):
        rc, out = self.bill(self.b)
        self.assertEqual(rc, 1)
        self.assertTrue(any("charges_before_credits_usd" in p for p in out["problems"]))

    def test_synthetic_bill_computes_due_and_coverage(self):
        d = dict(self.b, month="2026-11", charges_before_credits_usd=10.30, credits_applied_usd=10.30, tax_usd=0,
                 total_due_usd=0, credits_remaining_usd=52.25, credit_expiration="2027-05-01")
        rc, out = self.bill(d)
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["amount_due_usd"], 0.0)
        self.assertTrue(out["matches_statement"])
        self.assertAlmostEqual(out["demo_months_covered_by_remaining_credits"], 5.0, places=1)

    def test_identifiers_are_refused(self):
        d = dict(self.b, charges_before_credits_usd=1, credits_applied_usd=0, tax_usd=0, credits_remaining_usd=0,
                 month="account 123456789012")
        rc, out = self.bill(d)
        self.assertEqual(rc, 1)
        self.assertTrue(any("account ID" in p for p in out["problems"]))


REPO = os.path.realpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
RENDERED = os.path.join(REPO, "deploy", "aws", "sagemaker-extractor", "readiness", "rendered", "sft-smoke.json")
MANIFEST = os.path.join(REPO, "tools", "extraction", "fixtures", "service_v1", "07-manifest.response.json")
PIN = "flh-extraction-rules@e978b6c2bdb6/flh_extraction_service_v1/flh_practice_drafter_v1"


@unittest.skipUnless(os.path.exists(RENDERED) and os.path.exists(MANIFEST), "Extraction fixtures not in this tree")
class ModelRecord(unittest.TestCase):
    def record(self, *args):
        r = run(DAYTIME, "model-record", *args)
        return r.returncode, json.loads(r.stdout)

    def test_render_and_readiness_are_separate(self):
        rc, rec = self.record("--rendered", RENDERED)
        self.assertEqual(rec["render"]["state"], "not_submittable")      # the committed job is a placeholder render
        self.assertEqual(rec["readiness"]["state"], "not_collected")     # and says nothing about readiness
        self.assertEqual(rc, 1)
        rc, rec = self.record("--manifest", MANIFEST, "--readyz-status", "200", "--expect-deployment", PIN)
        self.assertEqual((rc, rec["readiness"]["state"], rec["render"]["state"]), (0, "ready", "not_collected"))

    def test_readiness_needs_200_and_the_pinned_id(self):
        rc, rec = self.record("--manifest", MANIFEST, "--readyz-status", "503", "--expect-deployment", PIN)
        self.assertEqual((rc, rec["readiness"]["state"]), (1, "not_ready"))
        rc, rec = self.record("--manifest", MANIFEST, "--readyz-status", "200", "--expect-deployment", PIN.replace("e978", "0000"))
        self.assertTrue(any("differs" in p for p in rec["readiness"]["problems"]))

    def test_record_holds_no_account_or_bucket(self):
        _, rec = self.record("--rendered", RENDERED)
        text = json.dumps(rec)
        self.assertNotRegex(text, r"\b\d{12}\b")
        self.assertNotIn("s3://", text)
        self.assertNotIn("arn:aws", text)


LIFECYCLE = os.path.join(TOOLS, "lifecycle.py")
LIFECYCLE_FIXTURES = os.path.join(HERE, "fixtures", "lifecycle")


class ResidualEvidenceIncomplete(unittest.TestCase):
    """The teardown report parser on incomplete synthetic evidence (REL-080): never a PASS from missing proof."""

    def variant(self, change):
        import shutil
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        dst = os.path.join(d, "evidence")
        shutil.copytree(os.path.join(LIFECYCLE_FIXTURES, "clean"), dst)
        change(dst)
        return run(LIFECYCLE, "residual", dst, "--env", "staging")

    def test_clean_evidence_passes(self):
        self.assertEqual(self.variant(lambda d: None).returncode, 0)

    def test_missing_truncated_and_wrong_shape_are_incomplete(self):
        cases = {
            "missing file": lambda d: os.remove(os.path.join(d, "s3-buckets.json")),
            "truncated file": lambda d: write(os.path.join(d, "ec2-volumes.json"), '{"Vol'),
            "error envelope": lambda d: write(os.path.join(d, "ec2-addresses.json"), '{"Error": {"Code": "UnauthorizedOperation"}}'),
            "wrong listing": lambda d: write(os.path.join(d, "tagged-resources.json"), '{"Buckets": []}'),
            "no collection time": lambda d: os.remove(os.path.join(d, "collected-at.txt")),
        }
        for name, change in cases.items():
            with self.subTest(name):
                r = self.variant(change)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertNotIn("PASSED", r.stdout)


STATE_GUARD = os.path.join(TOOLS, "state_guard.py")


class StateGuard(unittest.TestCase):
    def test_classifies_state_like_files_and_allows_the_pins(self):
        sys.path.insert(0, TOOLS)
        import state_guard
        cases = {"deploy/aws/private-staging/staging/terraform/terraform.tfstate": "terraform-state",
                 "terraform.tfstate.backup": "terraform-state", "stg.tfplan": "terraform-plan", "stg-destroy.plan.json": "terraform-plan",
                 "deploy/aws/private-staging/staging/terraform/terraform.tfvars": "terraform-vars",
                 "deploy/aws/terraform/.terraform/providers/x/terraform-provider-aws": "terraform-workdir",
                 "data/release/app.db": "database", "app.db-wal": "database", ".env": "env-file", "staging.env": "env-file",
                 "id_ed25519": "private-key", "crash.log": "crash-log"}
        for path, cls in cases.items():
            with self.subTest(path):
                self.assertEqual(state_guard.classify(path), cls)
        for ok in ("deploy/aws/private-staging/staging/terraform/terraform.tfvars.example", "deploy/aws/terraform/.terraform.lock.hcl",
                   "deploy/aws/private-staging/staging/tools/daytime.py", "docs/plans/FLH-AWS-PREP-20261121.md"):
            self.assertIsNone(state_guard.classify(ok), ok)

    def test_stdin_and_scan_modes(self):
        r = subprocess.run([sys.executable, "-I", "-B", STATE_GUARD, "--stdin"], input="docs/x.md\nstg.tfplan\n.env\n",
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.count("REFUSED  "), 2)
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "evidence"))
            write(os.path.join(d, "evidence", "notes.md"), "fine\n")
            self.assertEqual(run(STATE_GUARD, "scan", d).returncode, 0)
            write(os.path.join(d, "evidence", "terraform.tfstate"), "{}")
            self.assertEqual(run(STATE_GUARD, "scan", d).returncode, 1)

    def test_terraform_roots_still_ignore_state(self):
        self.assertEqual(run(STATE_GUARD, "ignore-check").returncode, 0)


PLAN_DOCS = [os.path.join(REPO, "docs", "plans", n) for n in ("FLH-AWS-PREP-20261121.md", "FLH-AWS-PREP-interfaces.md")]


@unittest.skipUnless(all(os.path.exists(p) for p in PLAN_DOCS), "plan documents not in this tree")
class PlanCommandHygiene(unittest.TestCase):
    """Every command example names credentials by placeholder only (REL-083)."""

    def test_profiles_accounts_and_keys_are_placeholders(self):
        import re
        allowed_profiles = {"flh-staging-release"}
        for path in PLAN_DOCS:
            text = read(path)
            for m in re.finditer(r"--profile\s+(\S+)", text):
                with self.subTest(path=os.path.basename(path), profile=m.group(1)):
                    self.assertTrue(m.group(1).startswith("<") or m.group(1) in allowed_profiles, m.group(1))
            for m in re.finditer(r"--account(?:-id)?\s+(\S+)", text):
                self.assertTrue(m.group(1).startswith("<"), m.group(1))
            self.assertNotRegex(text, r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")
            self.assertNotRegex(text, r"(?<![0-9a-f…])\b\d{12}\b(?![0-9a-f…])")
            self.assertNotRegex(text, r"aws_secret_access_key|AWS_SECRET_ACCESS_KEY=\S")


class DaytimeChecklist(unittest.TestCase):
    def test_checklist_has_items_stop_triggers_and_rollback(self):
        text = run(DAYTIME, "checklist").stdout
        self.assertGreaterEqual(text.count("- [ ] "), 12)
        for needle in ("## Stop before any live write if", "## Rollback entry", "<operator-profile>", "21 to add",
                       "lifecycle.py residual", "GATE PASSED", "PROMOTE"):
            self.assertIn(needle, text)
        self.assertNotRegex(text, r"\b\d{12}\b")


TOOL_FILES = {name: os.path.join(TOOLS, name) for name in os.listdir(TOOLS) if name.endswith(".py")}
TOOL_FILES["review_permissions.py"] = os.path.join(HERE, "..", "iam", "review_permissions.py")
TOOL_FILES["render_policies.py"] = os.path.join(HERE, "..", "iam", "render_policies.py")


@unittest.skipUnless(all(os.path.exists(p) for p in PLAN_DOCS), "plan documents not in this tree")
class PlanCommandsMatchTheTools(unittest.TestCase):
    """Every flag the plan passes to a merged tool exists in that tool's own help (REL-108, REL-142)."""

    def test_every_flag_is_known_to_its_tool(self):
        import re
        seen = 0
        text = "\n".join(read(p) for p in PLAN_DOCS)
        for m in re.finditer(r"([a-z_]+\.py) +([a-z][a-z-]*)?([^\n`|]*)", text):
            tool, sub, rest = m.group(1), m.group(2), m.group(3)
            if tool not in TOOL_FILES:
                continue
            flags = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", rest))
            if not flags:
                continue
            args = [TOOL_FILES[tool]] + ([sub] if sub else []) + ["--help"]
            helptext = run(*args).stdout + run(TOOL_FILES[tool], "--help").stdout
            source = read(TOOL_FILES[tool])   # tools that read sys.argv directly name their flags as literals
            for f in flags:
                with self.subTest(tool=tool, sub=sub, flag=f):
                    self.assertTrue(f in helptext or f'"{f}"' in source, f"{f} unknown to {tool}")
                    seen += 1
        self.assertGreater(seen, 20)
