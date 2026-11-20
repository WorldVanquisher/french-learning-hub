#!/usr/bin/env python3
"""Offline tests for the private-staging tools (no Docker, no AWS, no Terraform, no Git).

  python3 -I -B deploy/aws/private-staging/staging/tests/test_staging_tools.py

Covers: plan_check.py verdicts on the fixed fixtures; preflight's template
rendering and its refusal of unfilled inputs; render_policies.py refusals and
placeholder substitution; bundle_identity.py tree IDs against Git's known
object IDs; flh-staging-bundle verify on a synthetic bundle (accepted) and on
altered copies (rejected: changed, added and missing files, inconsistent
identity, a forged image config, unsafe tar members, a wrong SHA-256).
"""
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import warnings

warnings.simplefilter("ignore", ResourceWarning)  # one-line fixture writes; CPython closes them at once
TESTS =os.path.dirname(os.path.abspath(__file__))
STAGING = os.path.dirname(TESTS)
FIX = os.path.join(TESTS, "fixtures")
REPO = os.path.realpath(os.path.join(STAGING, "..", "..", "..", ".."))
PY = sys.executable


def load_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


bundle_tool = load_module("flh_staging_bundle", os.path.join(STAGING, "host", "flh-staging-bundle"))
identity = load_module("bundle_identity", os.path.join(STAGING, "bundle_identity.py"))


def rd(path, mode="r"):
    with open(path, mode) as fh:
        return fh.read()


def wr(path, text, mode="w"):
    with open(path, mode) as fh:
        fh.write(text)


def jload(path):
    with open(path) as fh:
        return json.load(fh)


def jdump(obj, path, **kw):
    with open(path, "w") as fh:
        json.dump(obj, fh, **kw)


def run(*args, **kw):
    return subprocess.run([PY, "-I", "-B", *args], capture_output=True, text=True, **kw)


class PlanCheck(unittest.TestCase):
    CASES = [
        ("plan-create-safe.json", "create", [], 0, "SAFE"),
        ("plan-update-noop-safe.json", "update", [], 0, "SAFE"),
        ("plan-destroy-safe.json", "destroy", [], 0, "SAFE"),
        ("plan-unsafe-public-ingress.json", "create", [], 1, "ingress"),
        ("plan-unsafe-replace-data-volume.json", "update", [], 1, "holds data"),
        ("plan-update-replace-instance.json", "update", [], 1, "without --allow-replace"),
        ("plan-update-replace-instance.json", "update",
         ["--allow-replace", "aws_instance.host", "--allow-replace", "aws_volume_attachment.data"], 0, "SAFE"),
        ("plan-unsafe-unexpected-resources.json", "create", [], 1, "aws_eip.public"),
        ("plan-unsafe-delete-in-update.json", "update", [], 1, "delete during an update"),
        ("plan-unsafe-weakened-settings.json", "create", [], 1, "IMDSv2"),
        ("plan-unsafe-create-over-state.json", "create", [], 1, "not a first apply"),
        ("plan-create-safe.json", "destroy", [], 1, "create in a destroy plan"),
        # R4: the data volume survives an instance replacement; anything else about its attachment STOPs
        ("plan-update-replace-instance-keeps-data.json", "update",
         ["--allow-replace", "aws_instance.host", "--allow-replace", "aws_volume_attachment.data"], 0, "re-attaches the same data volume"),
        ("plan-unsafe-attachment-other-volume.json", "update",
         ["--allow-replace", "aws_instance.host", "--allow-replace", "aws_volume_attachment.data"], 1, "volume_id changes"),
        ("plan-unsafe-attachment-edit.json", "update", [], 1, "in-place update of the data volume attachment"),
        ("plan-unsafe-attachment-edit.json", "update", [], 1, "device_name changes"),
        ("plan-staging-unsafe-production-resource.json", "update", [], 1, "tag Component is 'workbench-production'"),
        ("plan-staging-unsafe-production-resource.json", "update", [], 1, "belongs to another environment"),
        # R3: production settings, and each environment's plan checked as the other
        ("plan-production-create-safe.json", "create", ["--env", "production"], 0, "SAFE"),
        ("plan-production-update-replace-instance.json", "update", ["--env", "production"], 1, "without --allow-replace"),
        ("plan-production-update-replace-instance.json", "update",
         ["--env", "production", "--allow-replace", "aws_instance.host", "--allow-replace", "aws_volume_attachment.data"], 0, "SAFE"),
        ("plan-production-destroy.json", "destroy", ["--env", "production"], 1, "never destroyed through this check"),
        ("plan-production-unsafe-staging-settings.json", "create", ["--env", "production"], 1, "shutdown behaviour is not stop"),
        ("plan-production-unsafe-staging-settings.json", "create", ["--env", "production"], 1, "termination protection is False"),
        ("plan-production-unsafe-staging-settings.json", "create", ["--env", "production"], 1, "force_destroy is True"),
        ("plan-production-unsafe-staging-settings.json", "create", ["--env", "production"], 1, "production uses never"),
        ("plan-production-unsafe-staging-settings.json", "create", ["--env", "production"], 1, "belongs to another environment"),
        ("plan-create-safe.json", "create", ["--env", "production"], 1, "tag Component is 'workbench-staging'"),
        ("plan-create-safe.json", "create", ["--env", "production"], 1, "belongs to another environment"),
        ("plan-production-create-safe.json", "create", [], 1, "tag Environment is 'production'"),
        ("plan-production-create-safe.json", "create", [], 1, "made with environment='production' but is checked as --env staging"),
        ("plan-production-create-safe.json", "create", ["--env", "staging"], 1, "shutdown behaviour is not terminate"),
    ]

    def test_fixtures(self):
        for fname, mode, extra, want, needle in self.CASES:
            with self.subTest(fixture=fname, mode=mode, extra=extra):
                r = run(os.path.join(STAGING, "tools", "plan_check.py"), "--mode", mode, *extra, os.path.join(FIX, fname))
                self.assertEqual(r.returncode, want, r.stdout + r.stderr)
                self.assertIn(needle, r.stdout)

    def test_never_allow_data_volume_replace(self):
        r = run(os.path.join(STAGING, "tools", "plan_check.py"), "--mode", "update", "--allow-replace",
                "aws_ebs_volume.data", os.path.join(FIX, "plan-unsafe-replace-data-volume.json"))
        self.assertEqual(r.returncode, 2)

    def test_not_a_plan(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"hello": 1}, fh)
        try:
            r = run(os.path.join(STAGING, "tools", "plan_check.py"), "--mode", "create", fh.name)
            self.assertEqual(r.returncode, 2)
        finally:
            os.unlink(fh.name)

    def test_fixtures_are_what_the_generator_writes(self):
        with tempfile.TemporaryDirectory() as td:
            gen = load_module("make_plan_fixtures", os.path.join(TESTS, "make_plan_fixtures.py"))
            gen.OUT = td
            import contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                gen.main()
            for f in sorted(os.listdir(td)):
                with self.subTest(fixture=f):
                    self.assertEqual(rd(os.path.join(td, f), "rb"), rd(os.path.join(FIX, f), "rb"))


class Preflight(unittest.TestCase):
    def test_render_indent(self):
        pf = load_module("preflight", os.path.join(STAGING, "tools", "preflight.py"))
        out = pf.render_template("a: |\n  ${indent(2, body)}\nb: ${port}\n", {"body": "x\ny\n\nz", "port": 8080})
        self.assertEqual(out, "a: |\n  x\n  y\n\n  z\nb: 8080\n")

    def test_unfilled_tfvars_blocked(self):
        r = run(os.path.join(STAGING, "tools", "preflight.py"), "--tfvars",
                os.path.join(STAGING, "terraform", "terraform.tfvars.example"))
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertIn("FAIL terraform.tfvars has no REPLACE placeholder", r.stdout)


class RenderPolicies(unittest.TestCase):
    TOOL = os.path.join(STAGING, "iam", "render_policies.py")

    def test_fills_and_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "filled")
            r = run(self.TOOL, "--account", "111122223333", "--ami", "ami-0123456789abcdef0", "--out", out)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            for f in os.listdir(out):
                text = rd(os.path.join(out, f))
                self.assertNotIn("__AWS_ACCOUNT_ID__", text)
                self.assertNotIn("__STAGING_AMI_ID__", text)
                self.assertEqual(os.stat(os.path.join(out, f)).st_mode & 0o777, 0o600)
            self.assertIn("image/ami-0123456789abcdef0", rd(os.path.join(out, "flh-stg-deploy-ec2-policy.json")))
            self.assertNotEqual(run(self.TOOL, "--account", "111122223333", "--ami", "ami-0123456789abcdef0",
                                    "--out", out).returncode, 0, "a non-empty output directory must be refused")
            self.assertNotEqual(run(self.TOOL, "--account", "12345", "--ami", "ami-0123456789abcdef0",
                                    "--out", os.path.join(td, "x")).returncode, 0)
            self.assertNotEqual(run(self.TOOL, "--account", "111122223333", "--ami", "ami-0123456789abcdef0",
                                    "--out", os.path.join(td, "y"), "--region", "eu-west-3").returncode, 0)
            self.assertNotEqual(run(self.TOOL, "--account", "111122223333", "--ami", "ami-0123456789abcdef0",
                                    "--out", os.path.join(STAGING, "iam", "local")).returncode, 0)


class IamReview(unittest.TestCase):
    def test_every_required_action_is_allowed(self):
        r = run(os.path.join(STAGING, "iam", "review_permissions.py"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("MISSING", r.stdout)

    def test_tag_on_create_covers_every_tagged_create(self):
        rv = load_module("review_permissions", os.path.join(STAGING, "iam", "review_permissions.py"))
        deploy = list(rv.statements(os.path.join(STAGING, "iam", "out", "flh-stg-deploy-ec2-policy.json")))
        for t, (_, create) in rv.TF.items():
            if create:
                with self.subTest(resource=t):
                    self.assertTrue(rv.allows(deploy, "ec2:CreateTags", create), f"tag-on-create for {create}")
        # a ResourceTag-scoped statement must not count as tag-on-create
        self.assertEqual(rv.allows([("x", "Allow", ["ec2:CreateTags"], ["*"],
                                     {"StringEquals": {"aws:ResourceTag/Project": "flh"}})], "ec2:CreateTags", "CreateVolume"), [])

    def test_no_public_path_actions(self):
        text = "".join(rd(os.path.join(STAGING, "iam", "out", f)) for f in os.listdir(os.path.join(STAGING, "iam", "out"))
                       if f.endswith(".json"))
        for a in ("AllocateAddress", "AssociateAddress", "AuthorizeSecurityGroupIngress", "elastic-ip"):
            self.assertNotIn(a, text)


class IamEnvironments(unittest.TestCase):
    """R3: the committed staging and production outputs are what the generator writes; production
    withholds every delete of data or settings; both verify-readonly policies stay read-only."""
    GEN = os.path.join(STAGING, "iam", "make_policies.py")
    SRC = os.path.join(REPO, "deploy", "aws", "iam")

    def test_outputs_are_what_the_generator_writes(self):
        for env, committed in (("staging", "out"), ("production", "out-production")):
            with self.subTest(env=env), tempfile.TemporaryDirectory() as td:
                r = run(self.GEN, self.SRC, td, "--env", env)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                want = os.path.join(STAGING, "iam", committed)
                self.assertEqual(sorted(os.listdir(td)), sorted(os.listdir(want)))
                for f in os.listdir(td):
                    self.assertEqual(rd(os.path.join(td, f)), rd(os.path.join(want, f)), f)

    def test_production_withholds_deletes_and_keeps_its_names(self):
        d = os.path.join(STAGING, "iam", "out-production")
        text = "".join(rd(os.path.join(d, f)) for f in os.listdir(d) if f.endswith(".json"))
        allowed = set()
        for f in os.listdir(d):
            if f.endswith(".json"):
                for st in json.loads(rd(os.path.join(d, f)))["Statement"]:
                    if st["Effect"] == "Allow":
                        allowed |= set(st["Action"] if isinstance(st["Action"], list) else [st["Action"]])
        for a in ("ec2:DeleteVolume", "s3:DeleteBucket", "s3:DeleteObject", "s3:DeleteObjectVersion", "ssm:DeleteParameters"):
            self.assertNotIn(a, allowed)
        for leftover in ("flh-stg", "workbench-staging", "/flh/staging", "__STAGING_AMI_ID__"):
            self.assertNotIn(leftover, text)
        self.assertIn('"workbench-production"', text)
        r = run(os.path.join(STAGING, "iam", "review_permissions.py"), "--env", "production")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("ADMIN-ONLY deploy | aws_ebs_volume | ec2:DeleteVolume", r.stdout)
        self.assertNotIn("MISSING", r.stdout)

    def test_verify_policies_are_read_only(self):
        rv = load_module("review_permissions", os.path.join(STAGING, "iam", "review_permissions.py"))
        for committed, prefix in (("out", "flh-stg"), ("out-production", "flh-prd")):
            with self.subTest(policy=prefix):
                doc = json.loads(rd(os.path.join(STAGING, "iam", committed, f"{prefix}-verify-readonly-policy.json")))
                allows = [a for st in doc["Statement"] if st["Effect"] == "Allow"
                          for a in (st["Action"] if isinstance(st["Action"], list) else [st["Action"]])]
                self.assertTrue(allows and all(rv.READ_ONLY.match(a) for a in allows), allows)
                denies = {a for st in doc["Statement"] if st["Effect"] == "Deny" for a in st["Action"]}
                self.assertTrue(rv.NEVER_IN_VERIFY <= denies)

    def test_unexpected_wildcard_resource_is_refused(self):
        # R4-REL-013: a staging policy that widens a statement to Resource "*" fails the review
        rv = load_module("review_permissions_wc", os.path.join(STAGING, "iam", "review_permissions.py"))
        bad = list(rv.statements(os.path.join(FIX, "iam-unexpected-wildcard-operate.json")))
        probs = rv.wildcard_problems({"operate": bad})
        self.assertEqual(len(probs), 1, probs)
        self.assertIn("operate S3ReadBackups: unexpected wildcard resource *", probs[0])
        self.assertEqual(rv.wildcard_problems(rv.policy_set()), [])
        stripped = [(sid, eff, acts, res, {} if sid == "DecryptOnlyThroughSsm" else cond)
                    for sid, eff, acts, res, cond in rv.policy_set()["host-boundary"]]
        self.assertIn("wildcard allowed only with its condition", " ".join(rv.wildcard_problems({"host-boundary": stripped})))

    def test_verifier_cannot_read_backups(self):
        # R4-REL-014: the verify role is explicitly denied backup objects in both environments
        for env, prefix in (("staging", "flh-stg"), ("production", "flh-prd")):
            r = run(os.path.join(STAGING, "iam", "review_permissions.py"), "--env", env, "--simulate", "s3:GetObject",
                    f"arn:aws:s3:::{prefix}-abc/backups/flh-20261120T000000Z.tar")
            rows = dict(l.split()[:2] for l in r.stdout.splitlines() if l.strip())
            with self.subTest(env=env):
                self.assertEqual(rows["verify"], "Deny")
                self.assertEqual(rows["host-boundary"], "Allow")
            r = run(os.path.join(STAGING, "iam", "review_permissions.py"), "--env", env, "--simulate", "s3:GetObject",
                    f"arn:aws:s3:::{prefix}-abc/releases/flh-staging-0123456789ab.tar.sha256")
            self.assertIn("verify         Allow", r.stdout)

    def test_render_fills_production(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "filled")
            r = run(os.path.join(STAGING, "iam", "render_policies.py"), "--account", "111122223333", "--ami",
                    "ami-0123456789abcdef0", "--out", out, "--templates", os.path.join(STAGING, "iam", "out-production"))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(len(os.listdir(out)), 5)
            self.assertIn("image/ami-0123456789abcdef0", rd(os.path.join(out, "flh-prd-deploy-ec2-policy.json")))


class RollbackTarget(unittest.TestCase):
    """R3-036: the rollback target is explicit: ROOT/previous by default, or --to an installed bundle."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.mod = load_module("flh_staging_bundle_rb", os.path.join(STAGING, "host", "flh-staging-bundle"))
        self.mod.BUNDLES = os.path.join(self.td, "bundles")
        for n in ("flh-staging-aaaaaaaaaaaa", "flh-staging-bbbbbbbbbbbb", "flh-staging-cccccccccccc"):
            os.makedirs(os.path.join(self.mod.BUNDLES, n))
        self.cur = os.path.join(self.mod.BUNDLES, "flh-staging-cccccccccccc")
        self.prev = os.path.join(self.mod.BUNDLES, "flh-staging-bbbbbbbbbbbb")

    def tearDown(self):
        shutil.rmtree(self.td)

    def test_default_is_previous_and_named(self):
        self.assertEqual(self.mod.rollback_target(self.cur, self.prev, None), (self.prev, "ROOT/previous"))

    def test_to_names_an_installed_bundle(self):
        d, why = self.mod.rollback_target(self.cur, self.prev, "flh-staging-aaaaaaaaaaaa")
        self.assertEqual((os.path.basename(d), why), ("flh-staging-aaaaaaaaaaaa", "--to"))

    def test_refusals(self):
        for cur, prev, to, needle in ((self.cur, None, None, "no previous bundle"),
                                      (self.cur, self.prev, "flh-staging-dddddddddddd", "is not installed"),
                                      (self.cur, self.prev, "flh-staging-cccccccccccc", "is the current bundle"),
                                      (self.cur, self.prev, "../etc", "--to must name a bundle")):
            with self.subTest(to=to), self.assertRaises(self.mod.Refused) as cm:
                self.mod.rollback_target(cur, prev, to)
            self.assertIn(needle, str(cm.exception))


class CandidateGates(unittest.TestCase):
    """R4: candidate identity, provenance and promotion, the account/region/environment gate,
    the effective-variable inventory and the authorization dry run (tools/candidate.py)."""
    TOOL = os.path.join(STAGING, "tools", "candidate.py")
    COMMIT = "c" * 40

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.d = make_bundle(self.td, commit=self.COMMIT)
        self.tar, self.sha = make_tar(self.d)
        wr(self.tar + ".sha256", f"{self.sha}  {os.path.basename(self.tar)}\n")
        self.mod = load_module("candidate_mod", self.TOOL)

    def tearDown(self):
        shutil.rmtree(self.td)

    def run_tool(self, *args, env=None):
        e = {k: v for k, v in os.environ.items() if not k.startswith("TF_VAR_")}
        e.update(env or {})
        return subprocess.run([PY, "-I", "-B", self.TOOL, *args], capture_output=True, text=True, env=e)

    def test_identity_reads_the_bundle(self):
        ident = self.mod.identity(self.tar)
        self.assertEqual((ident["bundle"], ident["commit"], ident["tree"], ident["tar_sha256"], ident["image_platform"]),
                         (NAME, self.COMMIT, TID, self.sha, "linux/amd64"))
        self.assertEqual(ident["migrations"]["count"], 21)
        self.assertEqual(self.run_tool("identity", self.tar).returncode, 0)

    def test_promotion_requires_agreement(self):
        prov = os.path.join(self.td, "prov.json")
        r = self.run_tool("provenance", self.tar, "--commit", self.COMMIT, "--out", prov)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_tool("promote-check", self.tar, "--provenance", prov, "--sha256", self.sha)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("PROMOTE", r.stdout)
        doc = json.loads(rd(prov))
        for field, bad in (("commit", "d" * 40), ("tree", "e" * 40), ("tar_sha256", "f" * 64), ("image_id", "sha256:" + "0" * 64)):
            with self.subTest(field=field):
                p2 = os.path.join(self.td, f"prov-{field}.json")
                jdump(dict(doc, **{field: bad}), p2)
                r = self.run_tool("promote-check", self.tar, "--provenance", p2)
                self.assertEqual(r.returncode, 1)
                self.assertIn(f"MISMATCH {field}:", r.stdout)
                self.assertIn("REFUSED", r.stdout)
        r = self.run_tool("promote-check", self.tar, "--provenance", prov, "--sha256", "a" * 64)
        self.assertEqual(r.returncode, 1)
        self.assertIn("the typed SHA-256", r.stdout)
        self.assertNotEqual(self.run_tool("provenance", self.tar, "--commit", "d" * 40, "--out",
                                          os.path.join(self.td, "x.json")).returncode, 0)

    def test_gate_compares_the_account_by_hash_and_never_prints_it(self):
        acct = "111122223333"
        ci = os.path.join(self.td, "caller.json")
        jdump({"Account": acct, "Arn": f"arn:aws:sts::{acct}:assumed-role/AWSReservedSSO_X_abc/s", "UserId": "x"}, ci)
        good = hashlib.sha256(acct.encode()).hexdigest()
        r = self.run_tool("gate", "--caller-identity", ci, "--allowed-account-sha256", good, "--region", "us-east-1",
                          "--env", "staging", "--workspace", "default")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn(acct, r.stdout + r.stderr)
        for args, needle in ((["--allowed-account-sha256", "0" * 64, "--region", "us-east-1", "--env", "staging"], "FAIL account"),
                             (["--allowed-account-sha256", good, "--region", "eu-west-3", "--env", "staging"], "FAIL region"),
                             (["--allowed-account-sha256", good, "--region", "us-east-1", "--env", "prod"], "FAIL environment"),
                             (["--allowed-account-sha256", good, "--region", "us-east-1", "--env", "staging", "--workspace", "production"], "FAIL workspace"),
                             (["--allowed-account-sha256", good, "--region", "us-east-1", "--env", "production", "--workspace", "default"], "FAIL workspace")):
            with self.subTest(needle=needle, args=args):
                r = self.run_tool("gate", "--caller-identity", ci, *args)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(needle, r.stdout)
                self.assertNotIn(acct, r.stdout)

    def test_vars_show_sources_and_refuse_silent_inputs(self):
        tv = filled_tfvars(os.path.join(self.td, "stg.tfvars"))
        root = os.path.join(self.td, "root")
        os.makedirs(root)
        r = self.run_tool("vars", "--tfvars", tv, "--root", root, "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = {x["name"]: x for x in json.loads(r.stdout)["variables"]}
        self.assertEqual(rows["run_id"]["source"], "-var-file stg.tfvars")
        self.assertEqual((rows["vpc_cidr"]["value"], rows["vpc_cidr"]["source"]),
                         ("10.85.0.0/24", "environment default (staging, main.tf locals)"))
        self.assertEqual(rows["app_port"]["source"], "default")
        # R4-009: a production value inherited from the shell or an auto-loaded file never arrives silently
        r = self.run_tool("vars", "--tfvars", tv, "--root", root, env={"TF_VAR_environment": "production"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("REFUSE silent input: environment from environment TF_VAR_environment", r.stdout)
        wr(os.path.join(root, "terraform.tfvars"), 'data_volume_size_gib = 20\n')
        r = self.run_tool("vars", "--tfvars", tv, "--root", root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("REFUSE silent input: data_volume_size_gib from auto-loaded terraform.tfvars", r.stdout)
        r = self.run_tool("vars", "--tfvars", tv, "--root", os.path.join(self.td, "root2"), env={"TF_VAR_typo": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("REFUSE unknown TF_VAR_typo", r.stdout)

    def test_vars_redact_identifiers(self):
        self.assertEqual(self.mod.redact("arn:aws:iam::111122223333:role/x and 111122223333"), "<arn> and <account-id>")

    def test_authorize_is_a_dry_run_that_refuses_problems(self):
        tv = filled_tfvars(os.path.join(self.td, "stg.tfvars"))
        root = os.path.join(self.td, "root")
        os.makedirs(root)
        prov = os.path.join(self.td, "prov.json")
        self.run_tool("provenance", self.tar, "--commit", self.COMMIT, "--out", prov)
        r = self.run_tool("authorize", "--tfvars", tv, "--bundle", self.tar, "--sha256", self.sha, "--provenance", prov,
                          "--root", root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for needle in ("DRY RUN", "environment      staging", "A2 (budget", "plan_check.py --env staging --mode create",
                       "AUTHORIZATION MATERIAL READY"):
            self.assertIn(needle, r.stdout)
        r = self.run_tool("authorize", "--tfvars", tv, "--bundle", self.tar, "--sha256", "a" * 64, "--provenance", prov,
                          "--root", root, env={"TF_VAR_expires_at": "never"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("NOT READY", r.stdout)


class Lifecycle(unittest.TestCase):
    """R4-REL-021..025: dated cost sheet by category, billable-after-shutdown, teardown rehearsal on a
    synthetic inventory, and the residual-resource checklist from read-only evidence files."""
    TOOL = os.path.join(STAGING, "tools", "lifecycle.py")
    LF = os.path.join(FIX, "lifecycle")

    def test_cost_by_category_adds_up(self):
        mod = load_module("lifecycle_mod", self.TOOL)
        sheet = mod.load_sheet(mod.SHEET)
        self.assertRegex(sheet["as_of"], r"^\d{4}-\d{2}-\d{2}$")
        for name, sc in sheet["scenarios"].items():
            with self.subTest(scenario=name):
                rows = mod.cost(sheet, sc)
                self.assertEqual(sorted(rows), sorted(["compute", "disk", "snapshots", "storage", "ipv4", "logs"]))
        out = json.loads(run(self.TOOL, "cost", "--scenario", "staging-pass", "--json").stdout)
        self.assertAlmostEqual(out["total"], round(sum(out["by_category"].values()), 2), places=2)
        self.assertLess(out["total"], 0.5)
        more = json.loads(run(self.TOOL, "cost", "--scenario", "staging-pass", "--set", "compute_hours=12", "--json").stdout)
        self.assertGreater(more["by_category"]["compute"], out["by_category"]["compute"])

    def test_after_shutdown_names_what_keeps_billing(self):
        stg = run(self.TOOL, "after-shutdown", "--env", "staging").stdout
        prd = run(self.TOOL, "after-shutdown", "--env", "production").stdout
        self.assertRegex(stg, r"BILLS +aws_ebs_volume\.data")
        self.assertRegex(stg, r"free +root volume")
        self.assertRegex(prd, r"BILLS +root volume")
        self.assertRegex(stg, r"free +public IPv4")

    def test_teardown_rehearsal_finds_the_manual_snapshot(self):
        r = run(self.TOOL, "teardown-rehearse", os.path.join(self.LF, "inventory-synthetic.json"), "--now", "2026-11-20T21:00:00Z")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("RESIDUAL ebs_snapshot", r.stdout)
        self.assertIn("still billable: aws_ebs_volume, aws_s3_bucket", r.stdout)

    def test_residual_checklist(self):
        r = run(self.TOOL, "residual", os.path.join(self.LF, "clean"), "--env", "staging")
        self.assertEqual(r.returncode, 0, r.stdout)
        r = run(self.TOOL, "residual", os.path.join(self.LF, "residual"), "--env", "staging", "--json")
        self.assertEqual(r.returncode, 1)
        rows = {x["check"]: x for x in json.loads(r.stdout.split("RESIDUAL CHECK")[0])["rows"]}
        self.assertEqual((rows["volumes"]["status"], rows["buckets"]["count"], rows["instances"]["status"]),
                         ("RESIDUAL", 1, "PASS"))
        self.assertNotIn("111122223333", r.stdout)
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(run(self.TOOL, "residual", td, "--env", "staging").returncode, 2)
        cmds = run(self.TOOL, "verify-commands", "--env", "production", "--out", "/tmp/x").stdout
        self.assertIn("Values=workbench-production", cmds)
        self.assertNotRegex(cmds, r"aws [a-z0-9-]+ (delete|put|create|run|terminate)")


class EvidenceIndex(unittest.TestCase):
    """R4-REL-056..060: one offline index; partial runs and recovery; redaction; runs never merge."""
    TOOL = os.path.join(STAGING, "tools", "evidence_index.py")

    def setUp(self):
        self.td = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.td)

    def make_run(self, name, run_id, complete=True, status="PASS", extra_rows=()):
        d = os.path.join(self.td, name)
        os.makedirs(d)
        # the tailnet name below is assembled from pieces, so no literal one sits in the repository
        base = {"run_id": run_id, "source_commit": "c" * 40, "artifact": "flh-staging-aaaaaaaaaaaa.tar",
                "artifact_sha256": "a" * 64, "collected_at": "2026-11-20T18:00:00Z"}
        rows = [dict(base, item="R4-REL-026", step="B1", status=status, expected="installs",
                     actual="log at /home/someone/x via 10.85.0.9 and " + "box.tail0000" + ".ts" + ".net")] + list(extra_rows)
        raw = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
        wr(os.path.join(d, "results.jsonl"), raw)
        wr(os.path.join(d, "results.tsv"), "B1\tPASS\n")
        if complete:
            jdump({"format": "flh-r4-rehearsal/v1", "run_id": run_id, "artifact": base["artifact"], "artifact_sha256": "a" * 64,
                   "rows_sha256": hashlib.sha256(raw.encode()).hexdigest(), "counts": {"PASS": 1}}, os.path.join(d, "summary.json"))
        return d

    def test_complete_run_is_approvable_and_redacted(self):
        d = self.make_run("run1", "R4-A")
        out = os.path.join(self.td, "index.md")
        r = run(self.TOOL, d, "--out", out, "--approve", "R4-A")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("APPROVABLE: run R4-A", r.stdout)
        text = rd(out)
        for leak in ("/home/someone", "10.85.0.9", "ts.net"):
            self.assertNotIn(leak, text)
        self.assertIn("| R4-REL-026 | B1 | PASS | cccccccccccc | aaaaaaaaaaaa | 2026-11-20T18:00:00Z |", text)

    def test_partial_runs_are_named_with_their_recovery_and_refused(self):
        d = self.make_run("run2", "R4-B", complete=False)
        r = run(self.TOOL, d, "--out", os.path.join(self.td, "i.md"), "--approve", "R4-B")
        self.assertEqual(r.returncode, 1)
        self.assertIn("summary.json missing", r.stdout)
        self.assertIn("NEW directory", rd(os.path.join(self.td, "i.md")))
        d3 = self.make_run("run3", "R4-C")
        with open(os.path.join(d3, "results.jsonl"), "a") as fh:
            fh.write("{broken\n")
        r = run(self.TOOL, d3, "--out", os.path.join(self.td, "i3.md"), "--approve", "R4-C")
        self.assertEqual(r.returncode, 1)
        self.assertIn("rows_sha256 differs", r.stdout)

    def test_two_runs_never_form_one_approval(self):
        other = {"run_id": "R4-OTHER", "item": "R4-REL-027", "step": "B2", "status": "PASS", "source_commit": "c" * 40,
                 "artifact_sha256": "a" * 64, "collected_at": "2026-11-20T18:01:00Z", "expected": "", "actual": ""}
        mixed = self.make_run("mixed", "R4-D", extra_rows=[other])
        r = run(self.TOOL, mixed, "--out", os.path.join(self.td, "m.md"), "--approve", "R4-D")
        self.assertEqual(r.returncode, 1)
        self.assertIn("rows of other runs mixed in: R4-OTHER", r.stdout)
        a, b = self.make_run("ra", "R4-E"), self.make_run("rb", "R4-F")
        r = run(self.TOOL, a, b, "--out", os.path.join(self.td, "ab.md"), "--approve", "R4-E")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("not part of this approval", r.stdout)
        r = run(self.TOOL, a, b, "--out", os.path.join(self.td, "ab.md"), "--approve", "R4-G")
        self.assertEqual(r.returncode, 1)


class BundlePlatform(unittest.TestCase):
    """R4-REL-061/062: a bundle is verified for the host's architecture; a wrong one is refused with the reason."""

    def setUp(self):
        self.td = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.td)

    def verify(self, tar, sha, host_arch):
        env = dict(os.environ, FLH_STAGING_HOST_ARCH=host_arch)
        return subprocess.run([PY, "-I", "-B", os.path.join(STAGING, "host", "flh-staging-bundle"), "verify", tar,
                               "--sha256", sha, "--scratch", self.td], capture_output=True, text=True, env=env)

    def test_architecture_must_match_the_host(self):
        arm = make_bundle(os.path.join(self.td, "arm"), commit="c" * 40, arch="arm64")
        tar, sha = make_tar(arm)
        r = self.verify(tar, sha, "x86_64")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not match this host (linux/amd64)", r.stdout + r.stderr)
        r = self.verify(tar, sha, "aarch64")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        amd = make_bundle(os.path.join(self.td, "amd"), commit="c" * 40)
        tar2, sha2 = make_tar(amd)
        r = self.verify(tar2, sha2, "arm64")
        self.assertIn("does not match this host (linux/arm64)", r.stdout + r.stderr)
        self.assertEqual(self.verify(tar2, sha2, "x86_64").returncode, 0)


def compose_available():
    """Docker Compose usable, decided WITHOUT calling a trapped docker: the hermetic suite runner
    (scripts/ci/python_suites.py --hermetic) puts a recording trap first on PATH, and any call fails it."""
    path = shutil.which("docker")
    if not path:
        return False
    try:
        with open(path, "rb") as fh:
            if b"trapped by python_suites.py" in fh.read(4096):
                return False
    except OSError:
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0


@unittest.skipUnless(compose_available(), "docker compose not available (the check renders config only)")
class RuntimeOverride(unittest.TestCase):
    """R4-REL-052/053: the extraction sidecar override, checked offline with `docker compose config`."""
    TOOL = os.path.join(STAGING, "tools", "runtime_check.py")

    def test_pinned_override_passes_and_default_is_unchanged(self):
        r = run(self.TOOL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for needle in ("PASS the app service is unchanged by the override", "PASS extraction publishes no port",
                       "PASS a missing FLH_EXTRACTION_IMAGE fails visibly",
                       "PASS a missing FLH_EXTRACTION_DEPLOYMENT_ID fails visibly"):
            self.assertIn(needle, r.stdout)

    def test_malformed_deployment_id_fails(self):
        r = run(self.TOOL, "--deployment-id", "flh-extraction-rules@latest")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL the expected deployment_id is recorded and well formed", r.stdout)


class PathsWithSpaces(unittest.TestCase):
    """R4-REL-063: the host tool verifies a bundle whose path and scratch directory contain spaces."""

    def test_verify_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="flh r4 spaces ") as td:
            parent = os.path.join(td, "release bundles")
            d = make_bundle(parent, commit="c" * 40)
            tar, sha_ = make_tar(d)
            scratch = os.path.join(td, "scratch dir")
            os.makedirs(scratch)
            r = subprocess.run([PY, "-I", "-B", os.path.join(STAGING, "host", "flh-staging-bundle"), "verify", tar,
                                "--sha256", sha_, "--scratch", scratch], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("VERIFIED", r.stdout + r.stderr)


class CutoverEdges(unittest.TestCase):
    """R4-REL-047/048: stale snapshot -> DO-NOT-SWITCH (a fresh backup clears C3); writes on both sides -> DIVERGED;
    NAS-only writes after the switch -> ROLLBACK-A. Synthetic SQLite files, cutover_check.py verdicts."""

    def test_edges(self):
        with tempfile.TemporaryDirectory() as td:
            r = run(os.path.join(STAGING, "rehearsal", "r4_cutover_edges.py"), os.path.join(td, "w"))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("CUTOVER EDGES: 4 PASS, 0 FAIL", r.stdout)


class DocSnippets(unittest.TestCase):
    """R4-REL-065: every ```bash block in the release lane's runbooks and plans parses (bash -n), and so do
    the shell launchers. Placeholders such as <backup> or <flh-staging-TREE12> are documentation, not shell,
    and are replaced by a word before parsing."""
    DOCS = ["deploy/aws/private-staging/RUNBOOK.md", "deploy/aws/private-staging/CUTOVER_DRY_RUN.md",
            "deploy/aws/private-staging/DEMO_REFRESH_STAGING.md", "docs/plans/FLH-R3-aws-migration.md",
            "docs/plans/FLH-R4-release-candidate.md"]
    LAUNCHERS = ["deploy/aws/private-staging/staging/build_bundle.sh", "deploy/aws/private-staging/staging/host/flh-staging-env",
                 "scripts/daily/flh-daily.sh", "scripts/release/smoke.sh", "scripts/release/disk_preflight.sh"]

    def blocks(self, path):
        text = rd(os.path.join(REPO, path))
        return re.findall(r"^```bash\n(.*?)^```", text, re.S | re.M)

    def test_documented_snippets_parse(self):
        seen = 0
        for doc in self.DOCS:
            for i, block in enumerate(self.blocks(doc), 1):
                seen += 1
                code = re.sub(r"<[A-Za-z][^<>\n]*>", "PLACEHOLDER", block)
                with self.subTest(doc=doc, block=i):
                    r = subprocess.run(["bash", "-n"], input=code, capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, f"{doc} block {i}: {r.stderr.strip()}")
        self.assertGreaterEqual(seen, 19)

    def test_launchers_parse(self):
        for f in self.LAUNCHERS:
            with self.subTest(launcher=f):
                r = subprocess.run(["bash", "-n", os.path.join(REPO, f)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)


class TreeId(unittest.TestCase):
    def test_known_git_objects(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(identity.tree_id(td, {}), "4b825dc642cb6eb9a060e54bf8d69288fbee4904")  # Git's empty tree
            wr(os.path.join(td, "hello"), "hello\n")
            rows = identity.scan(td)
            # blob "hello\n" = ce013625030ba8dba906f756967f9e9ca394464a (git hash-object)
            want = hashlib.sha1(b"tree 33\x00100644 hello\x00" + bytes.fromhex("ce013625030ba8dba906f756967f9e9ca394464a")).hexdigest()
            self.assertEqual(identity.tree_id(td, rows), want)

    def test_excludes_local_state(self):
        with tempfile.TemporaryDirectory() as td:
            wr(os.path.join(td, "a.txt"), "a")
            base = identity.tree_id(td, identity.scan(td))
            os.makedirs(os.path.join(td, "deploy/aws/private-staging/staging/terraform/.terraform"))
            for p in ("x.tfstate", "y.tfplan", "app.db", "deploy/aws/private-staging/staging/terraform/.terraform/p"):
                wr(os.path.join(td, p), "local")
            self.assertEqual(identity.tree_id(td, identity.scan(td)), base)


# --- synthetic bundle (no Docker) -----------------------------------------------------------------
TID = "0123456789abcdef0123456789abcdef01234567"
NAME = f"flh-staging-{TID[:12]}"
TAG = f"flh-staging:{TID[:12]}"


def add_bytes(tf, name, data):
    ti = tarfile.TarInfo(name)
    ti.size = len(data)
    tf.addfile(ti, io.BytesIO(data))


def make_image_tar(path, labels, tag=TAG, arch="amd64"):
    layer = io.BytesIO()
    with tarfile.open(fileobj=layer, mode="w") as lt:
        add_bytes(lt, "app/server", b"#!fake server\n")
    layer = layer.getvalue()
    lh = hashlib.sha256(layer).hexdigest()
    cfg = json.dumps({"architecture": arch, "os": "linux", "config": {"Labels": labels},
                      "rootfs": {"type": "layers", "diff_ids": [f"sha256:{lh}"]}}).encode()
    ch = hashlib.sha256(cfg).hexdigest()
    with tarfile.open(path, "w") as tf:
        add_bytes(tf, f"blobs/sha256/{lh}", layer)
        add_bytes(tf, f"blobs/sha256/{ch}", cfg)
        add_bytes(tf, "manifest.json", json.dumps([{"Config": f"blobs/sha256/{ch}", "RepoTags": [tag],
                                                    "Layers": [f"blobs/sha256/{lh}"]}]).encode())
    return f"sha256:{ch}"


def sha(path):
    return hashlib.sha256(rd(path, "rb")).hexdigest()


def make_bundle(parent, commit=None, with_cleanup=False, arch="amd64"):
    d = os.path.join(parent, NAME)
    os.makedirs(os.path.join(d, "repo", "scripts", "daily"))
    os.makedirs(os.path.join(d, "repo", "scripts", "release"))
    wr(os.path.join(d, "repo", "compose.yaml"), "services: {}\n")
    wr(os.path.join(d, "repo", "scripts", "daily", "flh-daily.sh"), "#!/bin/bash\n")
    wr(os.path.join(d, "repo", "scripts", "release", "restore_write_check.py"), "# check\n")
    if with_cleanup:                                   # the shipped cleanup tool (R2-047), byte for byte
        shutil.copyfile(os.path.join(REPO, "scripts", "release", "bundle_cleanup.py"),
                        os.path.join(d, "repo", "scripts", "release", "bundle_cleanup.py"))
    wr(os.path.join(d, "staging.override.yaml"), bundle_tool.OVERRIDE.format(tag=TAG))
    labels = {bundle_tool.LABEL_REVISION: commit or "", bundle_tool.LABEL_TREE: TID}
    image_id = make_image_tar(os.path.join(d, "image.tar"), labels, arch=arch)
    files = {os.path.relpath(os.path.join(dp, f), d): sha(os.path.join(dp, f))
             for dp, _, fns in os.walk(d) for f in fns}
    pinned = {p: h for p, h in files.items() if p.startswith("repo/") or p == "staging.override.yaml"}
    manifest = {"format": bundle_tool.FORMAT, "name": NAME,
                "revision": {"commit": commit, "tree_id": TID, "files": 3, "content_sha256": "0" * 64},
                "image": {"tag": TAG, "platform": f"linux/{arch}", "labels": labels},
                "server_sha256": "1" * 64, "web_files_sha256": "2" * 64,
                "migrations": {"count": 21, "last": "021_x.sql"}, "files": pinned}
    jdump(manifest, os.path.join(d, "MANIFEST.json"), indent=1, sort_keys=True)
    jdump({"manifest_sha256": sha(os.path.join(d, "MANIFEST.json")), "image_id": image_id,
           "image_tar_sha256": sha(os.path.join(d, "image.tar"))}, os.path.join(d, "BUILD.json"))
    reseal(d)
    return d


def reseal(d):
    lines = []
    for dp, _, fns in os.walk(d):
        for f in fns:
            p = os.path.relpath(os.path.join(dp, f), d)
            if p != "SHA256SUMS":
                lines.append(f"{sha(os.path.join(d, p))}  {p}")
    wr(os.path.join(d, "SHA256SUMS"), "\n".join(sorted(lines, key=lambda l: l[66:])) + "\n")


def make_tar(d, extra=None):
    tar = d + ".tar"
    with tarfile.open(tar, "w") as tf:
        tf.add(d, arcname=os.path.basename(d))
        if extra:
            extra(tf)
    return tar, sha(tar)


class BundleVerify(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.d = make_bundle(self.td)

    def tearDown(self):
        bundle_tool.force_rmtree(self.td)

    def refused(self, needle, d=None):
        with self.assertRaises(bundle_tool.Refused) as cm:
            bundle_tool.verify_dir(d or self.d)
        self.assertIn(needle, str(cm.exception))

    def test_good_bundle_verifies_as_dir_and_tar(self):
        m, b = bundle_tool.verify_dir(self.d)
        self.assertEqual(m["name"], NAME)
        tar, h = make_tar(self.d)
        _, _, m2, _ = bundle_tool.verify_tar(tar, h, self.td)
        self.assertEqual(m2, m)

    def test_altered_file(self):
        wr(os.path.join(self.d, "repo", "compose.yaml"), "# changed\n", "a")
        self.refused("altered file")

    def test_added_file(self):
        wr(os.path.join(self.d, "repo", "extra.sh"), "x")
        self.refused("added")

    def test_missing_file(self):
        os.unlink(os.path.join(self.d, "repo", "scripts", "release", "restore_write_check.py"))
        self.refused("missing file")

    def test_resealed_but_manifest_disagrees(self):
        wr(os.path.join(self.d, "repo", "compose.yaml"), "# changed\n", "a")
        reseal(self.d)  # an attacker can recompute SHA256SUMS, but MANIFEST.json pins the files
        self.refused("MANIFEST files differ")

    def test_inconsistent_identity(self):
        m = jload(os.path.join(self.d, "MANIFEST.json"))
        m["revision"]["tree_id"] = "f" * 40
        jdump(m, os.path.join(self.d, "MANIFEST.json"))
        reseal(self.d)
        self.refused("identity mismatch")

    def test_build_json_must_match_manifest(self):
        m = jload(os.path.join(self.d, "MANIFEST.json"))
        m["server_sha256"] = "3" * 64
        jdump(m, os.path.join(self.d, "MANIFEST.json"), indent=1, sort_keys=True)
        reseal(self.d)
        self.refused("BUILD.json manifest_sha256")

    def test_forged_image_labels(self):
        image_id = make_image_tar(os.path.join(self.d, "image.tar"),
                                  {bundle_tool.LABEL_REVISION: "", bundle_tool.LABEL_TREE: "e" * 40})
        b = jload(os.path.join(self.d, "BUILD.json"))
        b.update(image_id=image_id, image_tar_sha256=sha(os.path.join(self.d, "image.tar")))
        jdump(b, os.path.join(self.d, "BUILD.json"))
        reseal(self.d)
        self.refused("image label")

    def test_image_config_not_matching_build(self):
        b = jload(os.path.join(self.d, "BUILD.json"))
        b["image_id"] = "sha256:" + "9" * 64
        jdump(b, os.path.join(self.d, "BUILD.json"))
        reseal(self.d)
        self.refused("is not BUILD.json image_id")

    def test_override_must_name_the_image(self):
        os.chmod(os.path.join(self.d, "staging.override.yaml"), 0o644)
        wr(os.path.join(self.d, "staging.override.yaml"), bundle_tool.OVERRIDE.format(tag="flh-staging:other"))
        m = jload(os.path.join(self.d, "MANIFEST.json"))
        m["files"]["staging.override.yaml"] = sha(os.path.join(self.d, "staging.override.yaml"))
        jdump(m, os.path.join(self.d, "MANIFEST.json"), indent=1, sort_keys=True)
        b = jload(os.path.join(self.d, "BUILD.json"))
        b["manifest_sha256"] = sha(os.path.join(self.d, "MANIFEST.json"))
        jdump(b, os.path.join(self.d, "BUILD.json"))
        reseal(self.d)
        self.refused("staging.override.yaml is not the override")

    def test_wrong_sha256(self):
        tar, h = make_tar(self.d)
        with self.assertRaises(bundle_tool.Refused) as cm:
            bundle_tool.verify_tar(tar, "0" * 64, self.td)
        self.assertIn("is not the expected", str(cm.exception))

    def test_unsafe_members(self):
        def evil(tf):
            add_bytes(tf, "../escape", b"x")
        tar, h = make_tar(self.d, evil)
        with self.assertRaises(bundle_tool.Refused) as cm:
            bundle_tool.verify_tar(tar, h, self.td)
        self.assertIn("unsafe tar member", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.td), "escape")))
        self.assertEqual([n for n in os.listdir(self.td) if n.startswith(".partial-")], [])

    def test_symlink_member(self):
        def link(tf):
            ti = tarfile.TarInfo(f"{NAME}/repo/link")
            ti.type = tarfile.SYMTYPE
            ti.linkname = "/etc/passwd"
            tf.addfile(ti)
        tar, h = make_tar(self.d, link)
        with self.assertRaises(bundle_tool.Refused) as cm:
            bundle_tool.verify_tar(tar, h, self.td)
        self.assertIn("not a regular file", str(cm.exception))


def gitignored(rules, path, is_dir=False):
    """Git's matching for the pattern forms private-staging/.gitignore uses (no negation,
    no '**'): 'dir/' matches a directory at any depth (and everything below it); a
    pattern without '/' matches a basename at any depth; a pattern with an inner '/'
    is anchored at the .gitignore's directory. The last matching rule wins."""
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
                prefix = "/".join(parts[:i])
                if fnmatch.fnmatchcase(prefix, anchored) and (i < len(parts) or is_dir or not dir_only):
                    hit = True
        else:
            for i, comp in enumerate(parts):
                last = i == len(parts) - 1
                if fnmatch.fnmatchcase(comp, p) and (not dir_only or not last or is_dir):
                    hit = True
        if hit:
            ignored = True
    return ignored


class IgnoreRules(unittest.TestCase):
    RULES = rd(os.path.join(os.path.dirname(STAGING), ".gitignore")).splitlines()
    IGNORED = ["staging/terraform/terraform.tfstate", "staging/terraform/terraform.tfstate.backup",
               "staging/terraform/terraform.tfstate.1700000000.backup", "staging/terraform/.terraform.tfstate.lock.info",
               "staging/terraform/.terraform/providers/registry.terraform.io/hashicorp/aws/6.69.1/x",
               "staging/terraform/terraform.tfvars", "staging/terraform/owner.auto.tfvars",
               "staging/terraform/stg.tfplan", "staging/terraform/stg-destroy.tfplan",
               "staging/terraform/stg.plan.json", "staging/terraform/stg-destroy.plan.json",
               "staging/terraform/crash.log", "staging/terraform/override.tf",
               "staging/iam/local/flh-stg-deploy-policy.json", "flh-staging-0123456789ab.tar",
               "flh-staging-0123456789ab.tar.sha256"]
    KEPT = ["staging/terraform/terraform.tfvars.example", "staging/terraform/.terraform.lock.hcl",
            "staging/terraform/main.tf", "staging/terraform/cloud-config.yaml.tftpl", "staging/expected_resources.json",
            "staging/iam/out/flh-stg-deploy-policy.json", "staging/iam/out/CHANGES.txt",
            "staging/tests/fixtures/plan-create-safe.json", "staging/tests/fixtures/plan-destroy-safe.json",
            "staging/host/flh-staging-bundle", "RUNBOOK.md"]

    def test_ignored(self):
        for p in self.IGNORED:
            with self.subTest(path=p):
                self.assertTrue(gitignored(self.RULES, p), p)

    def test_kept(self):
        for p in self.KEPT:
            with self.subTest(path=p):
                self.assertFalse(gitignored(self.RULES, p), p)

    # Local operator state that may exist in a real checkout (after terraform init,
    # plan, render_policies or a bundle build). Listed here independently of
    # .gitignore, so it stays outside every test input; test_local_state_is_ignored
    # proves each kind is ignored.
    LOCAL_STATE_DIRS = {".terraform", "__pycache__", "local"}
    LOCAL_STATE_FILES = ("terraform.tfvars", "*.auto.tfvars", "*.auto.tfvars.json", "*.tfstate", "*.tfstate.*",
                         ".terraform.tfstate.lock.info", "*.tfplan", "*.tfplan.json", "*.plan.json", "crash*.log",
                         "override.tf", "override.tf.json", "*_override.tf", "*_override.tf.json",
                         "flh-staging-*.tar", "flh-staging-*.tar.sha256")

    def committed_files(self):
        import fnmatch
        root = os.path.dirname(STAGING)
        for dp, dns, fns in os.walk(root):
            rel_dir = os.path.relpath(dp, root)
            dns[:] = [d for d in dns if d not in self.LOCAL_STATE_DIRS or (d == "local" and rel_dir != "staging/iam")]
            for f in fns:
                if not any(fnmatch.fnmatchcase(f, g) for g in self.LOCAL_STATE_FILES):
                    yield os.path.relpath(os.path.join(dp, f), root)

    def test_every_tracked_file_here_is_kept(self):
        for rel in self.committed_files():
            with self.subTest(path=rel):
                self.assertFalse(gitignored(self.RULES, rel), f"{rel} would be ignored")

    def test_local_state_is_ignored(self):
        for p in self.IGNORED:
            with self.subTest(path=p):
                self.assertTrue(gitignored(self.RULES, p), p)
                self.assertNotIn(p, set(self.committed_files()))


class InstallOverExistingUnpack(unittest.TestCase):
    """install when bundles/<name> already exists (an earlier, possibly interrupted or altered unpack):
    the highest-risk partial failure on the install path that needs no Docker to exercise."""

    def setUp(self):
        from unittest import mock
        self.td = tempfile.mkdtemp()
        self.root = os.path.join(self.td, "srv")
        os.makedirs(os.path.join(self.root, "bundles"))
        wr(os.path.join(self.root, "staging.env"), "FLH_HOST_PORT='8080'\n")
        src = os.path.join(self.td, "src")
        os.makedirs(src)
        self.tar, self.sha = make_tar(make_bundle(src))
        self.final = os.path.join(self.root, "bundles", NAME)
        self.calls = []

        def forbidden(*a, **k):
            self.calls.append(a)
            raise AssertionError("docker or the wrapper must not run before the bundle is accepted")
        self.patches = [mock.patch.object(bundle_tool, n, v) for n, v in (
            ("ROOT", self.root), ("BUNDLES", os.path.join(self.root, "bundles")),
            ("CURRENT", os.path.join(self.root, "current")), ("PREVIOUS", os.path.join(self.root, "previous")),
            ("LOG", os.path.join(self.root, "deploy.log")), ("ENV_FILE", os.path.join(self.root, "staging.env")),
            ("docker", forbidden), ("wrapper", forbidden))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        bundle_tool.force_rmtree(self.td)

    def args(self):
        import argparse
        return argparse.Namespace(tar=self.tar, sha256=self.sha, no_backup=False)

    def tree_digest(self, d):
        return sorted((os.path.relpath(os.path.join(dp, f), d), sha(os.path.join(dp, f)))
                      for dp, _, fns in os.walk(d) for f in fns)

    def test_altered_earlier_unpack_is_refused_and_left_alone(self):
        shutil.copytree(os.path.join(os.path.dirname(self.tar), NAME), self.final)
        os.chmod(os.path.join(self.final, "BUILD.json"), 0o644)
        b = jload(os.path.join(self.final, "BUILD.json"))
        b["built_at"] = "an earlier, different build"
        jdump(b, os.path.join(self.final, "BUILD.json"))
        before = self.tree_digest(self.final)
        with self.assertRaises(bundle_tool.Refused) as cm:
            bundle_tool.cmd_install(self.args())
        self.assertIn("exists with different content", str(cm.exception))
        self.assertEqual(self.tree_digest(self.final), before, "the existing directory must not change")
        self.assertEqual([n for n in os.listdir(os.path.join(self.root, "bundles")) if n.startswith(".partial-")], [])
        self.assertFalse(os.path.lexists(os.path.join(self.root, "current")))
        self.assertFalse(os.path.lexists(os.path.join(self.root, "previous")))
        self.assertEqual(self.calls, [])

    def test_identical_earlier_unpack_is_reverified_and_reused(self):
        shutil.copytree(os.path.join(os.path.dirname(self.tar), NAME), self.final)
        stop = bundle_tool.Refused("stopped at ensure_image (test)")
        from unittest import mock
        with mock.patch.object(bundle_tool, "ensure_image", side_effect=stop) as ei:
            with self.assertRaises(bundle_tool.Refused):
                bundle_tool.cmd_install(self.args())
        self.assertEqual(ei.call_args[0][0], self.final)   # reached the image step with the reused directory
        self.assertEqual([n for n in os.listdir(os.path.join(self.root, "bundles")) if n.startswith(".partial-")], [])
        self.assertIn("\tverified\t", rd(os.path.join(self.root, "deploy.log")))
        self.assertFalse(os.path.lexists(os.path.join(self.root, "current")))


class Syntax(unittest.TestCase):
    def test_host_tool_is_python39(self):
        import ast
        ast.parse(rd(os.path.join(STAGING, "host", "flh-staging-bundle")), feature_version=(3, 9))

    def test_shell_syntax(self):
        for f in ("build_bundle.sh", "host/flh-staging-env"):
            with self.subTest(f=f):
                self.assertEqual(subprocess.run(["bash", "-n", os.path.join(STAGING, f)]).returncode, 0)


class BundleCompare(unittest.TestCase):
    TOOL = os.path.join(STAGING, "bundle_compare.py")

    def setUp(self):
        self.td = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.td, "a"))
        os.makedirs(os.path.join(self.td, "b"))
        self.a = make_bundle(os.path.join(self.td, "a"))
        self.b = make_bundle(os.path.join(self.td, "b"))

    def tearDown(self):
        bundle_tool.force_rmtree(self.td)

    def test_build_only_differences_keep_the_content_identical(self):
        b = jload(os.path.join(self.b, "BUILD.json"))
        b["built_at"] = "a later build"
        jdump(b, os.path.join(self.b, "BUILD.json"))
        reseal(self.b)
        r = run(self.TOOL, self.a, self.b)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("content: IDENTICAL", r.stdout)
        self.assertRegex(r.stdout, r"build-only built_at")

    def test_a_changed_pinned_file_is_a_content_difference(self):
        m = jload(os.path.join(self.b, "MANIFEST.json"))
        m["files"]["repo/compose.yaml"] = "9" * 64
        m["migrations"]["count"] = 22
        jdump(m, os.path.join(self.b, "MANIFEST.json"), indent=1, sort_keys=True)
        r = run(self.TOOL, self.a, self.b, "--json")
        self.assertEqual(r.returncode, 1, r.stderr)
        d = json.loads(r.stdout)
        fields = {x["field"] for x in d["differences"]["content"]}
        self.assertIn("file repo/compose.yaml", fields)
        self.assertIn("migrations", fields)
        self.assertEqual(d["a_facts"]["content"]["server_sha256 (image)"],
                         hashlib.sha256(b"#!fake server\n").hexdigest())   # read from the image layer, in memory

    def test_summary_has_identity_and_no_local_path(self):
        r = run(self.TOOL, self.a, "--summary", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertIsInstance(d["server_in_image_matches"], bool)    # the synthetic image holds a fake server
        self.assertEqual(d["migrations"], "21 (last 021_x.sql)")
        self.assertIn("repo/compose.yaml", d["files"])
        self.assertNotIn(self.td, r.stdout)
        self.assertNotIn(os.path.expanduser("~"), r.stdout)

    def test_unreadable_input_exits_2(self):
        r = run(self.TOOL, self.a, os.path.join(self.td, "missing.tar"))
        self.assertEqual(r.returncode, 2)


# --- staging preflight (inputs, tools, binding, publication, card) and plan review -------------------
def preflight_module():
    pf = load_module("preflight_t", os.path.join(STAGING, "tools", "preflight.py"))
    pf.results.clear()
    return pf


def quiet(fn, *args, **kw):
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn(*args, **kw)
    return out, buf.getvalue()


def filled_tfvars(path, **over):
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    v = {"aws_region": '"us-east-1"', "run_id": '"%s"' % now.strftime("%Y%m%dT%H%M%SZ"),
         "expires_at": '"%s"' % (now + datetime.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "ami_id": '"ami-0123456789abcdef0"', "instance_type": '"t3.small"', "compose_plugin_sha256": '"%s"' % ("a" * 64)}
    v.update(over)
    wr(path, "".join(f"{k} = {x}\n" for k, x in v.items() if x is not None))
    return path


RUNBOOK_PARAMS = {"FLH_DATA_DIR": "/srv/flh-staging/data/app", "FLH_HOST_PORT": "8080", "FLH_UID": "1000", "FLH_GID": "1000",
                  "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled", "SUGGESTION_PROVIDER": "disabled",
                  "LISTENING_PROVIDER": "disabled", "READING_PROVIDER": "disabled", "WRITING_PROVIDER": "disabled",
                  "SPEAKING_TRANSCRIPTION_PROVIDER": "disabled", "SPEAKING_PROVIDER": "disabled", "HTTP_WRITE_TIMEOUT": "75",
                  "LISTENING_PLAYLIST_SOURCE": "disabled", "LISTENING_AUTO_PREPARE": "disabled", "LISTENING_NOTIFY": "disabled"}


class PreflightInputs(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.pf = preflight_module()

    def tearDown(self):
        shutil.rmtree(self.td)

    def states(self):
        return {n: s for s, n, _ in self.pf.results if n.startswith("input var.")}

    def test_missing_expiry_and_malformed_run_id_are_rejected(self):
        # R4-REL-010: a staging candidate without expires_at, or with a run_id that is not UTC compact
        for over, name in (({"expires_at": None}, "tfvars expires_at set"),
                           ({"run_id": '"2026-11-20 08:00"'}, "tfvars run_id format"),
                           ({"run_id": None}, "tfvars run_id set"),
                           ({"expires_at": '"tomorrow"'}, "tfvars expires_at is RFC 3339 UTC")):
            with self.subTest(name=name):
                self.pf.results.clear()
                tv = filled_tfvars(os.path.join(self.td, "c.tfvars"), **over)
                quiet(self.pf.check_tfvars, tv)
                self.assertIn(("FAIL", name), [(r[0], r[1]) for r in self.pf.results])

    def test_production_tfvars_never_expire_and_use_production_policies(self):
        # R3: production tfvars need expires_at never and are checked against out-production's IAM shape
        tv = filled_tfvars(os.path.join(self.td, "prd.tfvars"), environment='"production"', expires_at='"never"')
        quiet(self.pf.check_tfvars, tv)
        fails = [r for r in self.pf.results if r[0] == "FAIL"]
        self.assertEqual(fails, [])
        self.assertTrue(any(r[0] == "WARN" and r[1] == "environment production" for r in self.pf.results))
        self.pf.results.clear()
        tv = filled_tfvars(os.path.join(self.td, "stg.tfvars"), expires_at='"never"')
        quiet(self.pf.check_tfvars, tv)
        self.assertTrue(any(r[0] == "FAIL" and r[1] == "tfvars expires_at is RFC 3339 UTC" for r in self.pf.results))
        self.pf.results.clear()
        tv = filled_tfvars(os.path.join(self.td, "prd2.tfvars"), environment='"production"')
        quiet(self.pf.check_tfvars, tv)
        self.assertTrue(any(r[0] == "FAIL" and r[1] == "tfvars expires_at is never (production)" for r in self.pf.results))
        # a staging terraform.tfvars left in the root would be auto-loaded into the production run
        self.pf.results.clear()
        root = os.path.join(self.td, "root")
        os.makedirs(root)
        wr(os.path.join(root, "terraform.tfvars"), 'data_volume_size_gib = 8\n')
        self.pf.TF = root
        tv = filled_tfvars(os.path.join(self.td, "prd3.tfvars"), environment='"production"', expires_at='"never"')
        quiet(self.pf.check_tfvars, tv)
        self.assertTrue(any(r[0] == "FAIL" and r[1].startswith("no auto-loaded tfvars in the root") for r in self.pf.results))

    def test_example_shows_defaults_and_placeholders(self):
        quiet(self.pf.check_inputs, os.path.join(STAGING, "terraform", "terraform.tfvars.example"), None, set())
        st = {n.split()[1]: n.split()[2] for n in self.states()}
        self.assertEqual(st["var.ami_id"], "PLACEHOLDER")
        self.assertEqual(st["var.compose_plugin_sha256"], "PLACEHOLDER")
        self.assertEqual(st["var.app_port"], "DEFAULT")
        self.assertEqual(st["var.aws_region"], "SET")
        self.assertEqual(len(st), 14)            # every variable in variables.tf is listed (R3: + environment, backup_retention_days)

    def test_missing_and_invalid_values(self):
        tv = filled_tfvars(os.path.join(self.td, "t.tfvars"), run_id=None, max_runtime_hours="13", vpc_cidr='"x"', typo_var='"1"')
        quiet(self.pf.check_inputs, tv, None, set())
        st = {n.split()[1]: (s, n.split()[2]) for n, s in self.states().items()}
        self.assertEqual(st["var.run_id"], ("FAIL", "MISSING"))
        self.assertEqual(st["var.max_runtime_hours"], ("FAIL", "INVALID"))
        self.assertEqual(st["var.ami_id"], ("PASS", "SET"))
        self.assertIn(("WARN", "input var.typo_var not declared"), [(s, n) for s, n, _ in self.pf.results])
        self.assertEqual(st["var.vpc_cidr"], ("PASS", "SET"))   # no offline-checkable validation: shown, not judged

    def test_parameters_are_checked_without_printing_values(self):
        bad = dict(RUNBOOK_PARAMS, AI_PROVIDER="openai-secretish", FLH_HOST_PORT="9090", LISTEN_HOST="0.0.0.0")
        del bad["FLH_GID"]
        pj = os.path.join(self.td, "params.json")
        jdump({"Parameters": [{"Name": f"/flh/staging/{k}", "Value": v} for k, v in bad.items()]}, pj)
        (_, params), out = quiet(self.pf.check_inputs, None, pj, set())
        names = {n: s for s, n, _ in self.pf.results}
        self.assertEqual(names["parameter FLH_GID MISSING"], "FAIL")
        self.assertEqual(names["parameter AI_PROVIDER differs from RUNBOOK §4"], "FAIL")
        self.assertEqual(names["parameter LISTEN_HOST not in RUNBOOK §4"], "WARN")
        self.assertNotIn("openai-secretish", out)
        self.assertNotIn("9090", out)
        _, out2 = quiet(self.pf.check_binding, 8080, params)
        self.assertIn("FAIL host parameter FLH_HOST_PORT == app_port: differs (value not shown)", out2)
        self.assertIn("FAIL no parameter widens the listener", out2)

    def test_good_parameters_and_supplied_inputs(self):
        pj = os.path.join(self.td, "params.json")
        jdump({"Parameters": [{"Name": f"/flh/staging/{k}", "Value": v} for k, v in RUNBOOK_PARAMS.items()]}, pj)
        quiet(self.pf.check_inputs, filled_tfvars(os.path.join(self.td, "t.tfvars")), pj,
              {"plan": "p.json", "bundle": os.path.join(self.td, "missing.tar")})
        self.assertEqual([r for r in self.pf.results if r[0] == "FAIL"], [])
        opened = {n for s, n, _ in self.pf.results if s == "OPEN"}
        self.assertEqual(opened, {"owner input authorization", "owner input account_id", "owner input synthetic_backup",
                                  "owner input revision"})      # a bundle without a pinned commit leaves it open


class HostShell(unittest.TestCase):
    """Items 072-074: one `eval "$(flh-staging-bundle shell)"` replaces the typed settings and helpers,
    and every value survives a directory name with spaces."""

    def test_eval_defines_settings_and_helpers(self):
        td = tempfile.mkdtemp()
        try:
            root = os.path.join(td, "host root with spaces")
            conf = os.path.join(td, "staging conf")
            wr(conf, f"REGION=us-east-1\nBUCKET=flh-stg-x\nPARAM_DIR=/flh/staging\nROOT={root}\nPORT=8080\nOTHER=ignored\n")
            env = dict(os.environ, FLH_STAGING_CONF=conf, FLH_STAGING_ROOT=root)
            r = subprocess.run([PY, "-I", "-B", os.path.join(STAGING, "host", "flh-staging-bundle"), "shell"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("OTHER", r.stdout)
            self.assertNotIn("sha256", r.stdout.lower())          # the bundle SHA-256 is typed, never offered
            probe = subprocess.run(["bash", "-c", 'eval "$1"; printf "%s|%s|%s\\n" "$ROOT" "$PORT" "$REGION"; '
                                    'type stg bt cc dx > /dev/null && declare -f stg', "_", r.stdout],
                                   capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertTrue(probe.stdout.startswith(f"{root}|8080|us-east-1"))
            self.assertIn(f"{root}/current/repo/scripts/daily/flh-daily.sh", probe.stdout)
            self.assertIn("FLH_COMPOSE_PROJECT=flh-staging", probe.stdout)
        finally:
            shutil.rmtree(td)


class BuildSecondRun(unittest.TestCase):
    """Item 079: build_bundle.sh after an early stop refuses, names the case and calls no docker."""

    def test_refusals_name_the_case(self):
        td = tempfile.mkdtemp()
        try:
            tree = os.path.join(td, "tree")
            os.makedirs(tree)
            for f in ("README.md", "Dockerfile", "compose.yaml"):
                wr(os.path.join(tree, f), "x\n")
            tid = json.loads(run(os.path.join(STAGING, "bundle_identity.py"), "tree-id", tree).stdout)["tree_id"]
            out_parent = os.path.join(td, "out")
            name = f"flh-staging-{tid[:12]}"
            os.makedirs(os.path.join(out_parent, name))                     # a build killed after it began
            stub = os.path.join(td, "bin")
            os.makedirs(stub)
            wr(os.path.join(stub, "docker"), f"#!/bin/sh\necho \"$*\" >> {td}/docker-calls\nexit 97\n")
            os.chmod(os.path.join(stub, "docker"), 0o755)
            env = dict(os.environ, PATH=stub + os.pathsep + os.environ["PATH"], TMPDIR=td)
            r = subprocess.run(["bash", os.path.join(STAGING, "build_bundle.sh"), "--tree", tree, out_parent],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn(f"an earlier build of {name} stopped early (found: {name};", r.stderr)
            self.assertIn("Move it aside", r.stderr)
            wr(os.path.join(out_parent, name + ".tar"), "x")
            wr(os.path.join(out_parent, name + ".tar.sha256"), "0" * 64 + f"  {name}.tar\n")
            r = subprocess.run(["bash", os.path.join(STAGING, "build_bundle.sh"), "--tree", tree, out_parent],
                               capture_output=True, text=True, env=env)
            self.assertIn(f"{name} is already built", r.stderr)
            self.assertFalse(os.path.exists(os.path.join(td, "docker-calls")))
        finally:
            shutil.rmtree(td)


class HostDeployControls(unittest.TestCase):
    """Items 082, 086, 087 without Docker (the stand-in rehearsal runs them with Docker)."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.root = os.path.join(self.td, "root")
        for d in ("bundles", "transfer", "data/app", "data/app.backups/flh-1"):
            os.makedirs(os.path.join(self.root, d))
        wr(os.path.join(self.root, "data/app/app.db"), "db")
        wr(os.path.join(self.root, "staging.env"), f"FLH_DATA_DIR={self.root}/data/app\nFLH_HOST_PORT=1\n")
        self.conf = os.path.join(self.td, "staging.conf")
        wr(self.conf, f"REGION=us-east-1\nBUCKET=flh-stg-a\nROOT={self.root}\nPORT=1\n")
        self.env = dict(os.environ, FLH_STAGING_ROOT=self.root, FLH_STAGING_CONF=self.conf)

    def tearDown(self):
        bundle_tool.force_rmtree(self.td)

    def tool(self, *args):
        return subprocess.run([PY, "-I", "-B", os.path.join(STAGING, "host", "flh-staging-bundle"), *args],
                              capture_output=True, text=True, env=self.env)

    def test_mismatched_target_is_refused_before_anything(self):
        r = self.tool("install", os.path.join(self.td, "flh-staging-0123456789ab.tar"), "--sha256", "0" * 64,
                      "--expect-target", "BUCKET=flh-stg-other")
        self.assertEqual(r.returncode, 1)
        self.assertIn("target identity mismatch: BUCKET is 'flh-stg-a', the operator expects 'flh-stg-other'", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.root, "deploy.log")) and
                         "verified" in rd(os.path.join(self.root, "deploy.log")))

    def test_cleanup_lists_then_removes_only_stale_items(self):
        cur = make_bundle(os.path.join(self.root, "bundles"), with_cleanup=True)
        for n in ("flh-staging-aaaaaaaaaaaa", ".partial-flh-staging-cccccccccccc-x"):
            os.makedirs(os.path.join(self.root, "bundles", n))
        os.symlink(cur, os.path.join(self.root, "current"))
        for i, n in enumerate(("flh-staging-000000000001", "flh-staging-000000000002", "flh-staging-000000000003")):
            wr(os.path.join(self.root, "transfer", n + ".tar"), "t")
            os.utime(os.path.join(self.root, "transfer", n + ".tar"), (1700000000 + i, 1700000000 + i))
        r = self.tool("cleanup")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"cleanup from {NAME} (verified)", r.stdout)
        self.assertIn("would remove bundles/flh-staging-aaaaaaaaaaaa (bundle neither current nor previous)", r.stdout)
        self.assertIn("would remove bundles/.partial-flh-staging-cccccccccccc-x (interrupted unpack)", r.stdout)
        self.assertIn("would remove transfer/flh-staging-000000000001.tar", r.stdout)
        self.assertNotIn(f"remove bundles/{NAME}", r.stdout)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "bundles", "flh-staging-aaaaaaaaaaaa")))   # dry run
        r = self.tool("cleanup", "--yes")
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "bundles"))), [NAME])
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "transfer"))),
                         ["flh-staging-000000000002.tar", "flh-staging-000000000003.tar"])
        self.assertTrue(os.path.isfile(os.path.join(self.root, "data/app/app.db")))
        self.assertTrue(os.path.isdir(os.path.join(self.root, "data/app.backups/flh-1")))
        self.assertIn("\tcleanup\tbundles/flh-staging-aaaaaaaaaaaa", rd(os.path.join(self.root, "deploy.log")))

    def test_cleanup_runs_only_a_verified_bundle_copy(self):
        os.makedirs(os.path.join(self.root, "bundles", "flh-staging-aaaaaaaaaaaa"))
        r = self.tool("cleanup")                                        # before the first install
        self.assertEqual(r.returncode, 1)
        self.assertIn("no installed bundle has repo/scripts/release/bundle_cleanup.py", r.stderr)
        cur = make_bundle(os.path.join(self.root, "bundles"), with_cleanup=True)
        os.symlink(cur, os.path.join(self.root, "current"))
        tool = os.path.join(cur, "repo/scripts/release/bundle_cleanup.py")
        with open(tool, "a") as fh:
            fh.write("\nimport shutil; shutil.rmtree('/')  # tampered\n")
        r = self.tool("cleanup", "--yes")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("cleanup from", r.stdout)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "bundles", "flh-staging-aaaaaaaaaaaa")))

    def test_shipped_cleanup_runs_before_any_install(self):
        os.makedirs(os.path.join(self.root, "bundles", "flh-staging-aaaaaaaaaaaa"))
        r = subprocess.run([PY, "-I", "-B", os.path.join(REPO, "scripts/release/bundle_cleanup.py"), "--root", self.root],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would remove bundles/flh-staging-aaaaaaaaaaaa", r.stdout)
        self.assertIn("1 stale item(s); nothing removed (add --yes)", r.stdout)

    def test_status_names_the_cleanup_copy_before_and_after_install(self):
        r = self.tool("status")
        self.assertIn("cleanup: no installed bundle has repo/scripts/release/bundle_cleanup.py", r.stdout)
        from unittest import mock
        cur = make_bundle(os.path.join(self.root, "bundles"), with_cleanup=True)
        os.symlink(cur, os.path.join(self.root, "current"))
        with mock.patch.dict(os.environ, {"FLH_STAGING_ROOT": self.root, "FLH_STAGING_CONF": self.conf}):
            mod = load_module("flh_staging_bundle_status", os.path.join(STAGING, "host", "flh-staging-bundle"))
        said = []
        with mock.patch.object(mod, "identity", lambda b: (True, {})), mock.patch.object(mod, "show_identity", lambda *a: None), \
                mock.patch.object(mod, "say", said.append):
            mod.cmd_status(None)
        self.assertIn(f"flh-staging-bundle: cleanup: {NAME}", said)

    def test_diagnostics_are_redacted_and_private(self):
        from unittest import mock
        import importlib
        with mock.patch.dict(os.environ, {"FLH_STAGING_ROOT": self.root, "FLH_STAGING_CONF": self.conf}):
            mod = load_module("flh_staging_bundle_diag", os.path.join(STAGING, "host", "flh-staging-bundle"))
        fake = lambda *a: subprocess.CompletedProcess(a, 0, stdout=f"log line from {self.root}/data/app 10.85.0.9\n", stderr="")
        with mock.patch.object(mod, "docker", fake), mock.patch.object(mod, "running_container", lambda: "abc123"), \
                mock.patch.object(mod, "readyz", lambda port: (503, "not_ready")), mock.patch.object(mod, "say", lambda t: None):
            path = mod.write_diagnostics(os.path.join(self.root, "bundles", "flh-staging-0123456789ab"), {"readyz": 503})
        text = rd(path)
        self.assertIn("readyz 503 not_ready", text)
        self.assertIn("last log lines:", text)
        self.assertNotIn(self.root, text)
        self.assertIn("<IP>", text)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


class HostStatusRedact(unittest.TestCase):
    def test_status_redact_masks_the_root(self):
        td = tempfile.mkdtemp()
        try:
            root = os.path.join(td, "private root")
            os.makedirs(os.path.join(root, "bundles"))
            env = dict(os.environ, FLH_STAGING_ROOT=root)
            tool = os.path.join(STAGING, "host", "flh-staging-bundle")
            plain = subprocess.run([PY, "-I", "-B", tool, "status"], capture_output=True, text=True, env=env).stdout
            red = subprocess.run([PY, "-I", "-B", tool, "status", "--redact"], capture_output=True, text=True, env=env).stdout
            self.assertIn(root, plain)
            self.assertNotIn(td, red)
            self.assertIn("root <ROOT>, project flh-staging", red)
        finally:
            shutil.rmtree(td)


class PreflightRuntimeWindow(unittest.TestCase):
    """Item 069: an uncovered operational failure. A host whose power-off timer (max_runtime_hours after
    boot) falls after expires_at keeps running, and billing, past the run's declared end."""

    def setUp(self):
        self.td = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.td)

    def verdict(self, hours_left, runtime):
        import datetime
        exp = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours_left)).strftime("%Y-%m-%dT%H:%M:%SZ")
        tv = filled_tfvars(os.path.join(self.td, f"t{runtime}.tfvars"), expires_at=f'"{exp}"', max_runtime_hours=str(runtime))
        r = run(os.path.join(STAGING, "tools", "preflight.py"), "--tfvars", tv)
        return r.stdout

    def test_power_off_must_come_before_expiry(self):
        out = self.verdict(2, 4)
        self.assertIn("FAIL the host powers off before expires_at", out)
        self.assertIn("past expires_at", out)
        self.assertIn("PASS the host powers off before expires_at", self.verdict(6, 4))


class PreflightTools(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.pf = preflight_module()

    def tearDown(self):
        shutil.rmtree(self.td)

    def stub(self, name, text):
        p = os.path.join(self.td, name)
        wr(p, "#!/bin/sh\necho '%s'\n" % text)
        os.chmod(p, 0o755)

    def tools(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"PATH": self.td}):
            quiet(self.pf.check_tools)
        return {n: (s, d) for s, n, d in self.pf.results}

    def test_versions_and_missing_tools(self):
        self.stub("terraform", '{"terraform_version": "1.5.7"}')
        self.stub("aws", "aws-cli/1.33.0 Python/3.12")
        self.stub("docker", "Docker version 29.9.3, build abc")
        self.stub("git", "should never run")
        self.stub("python3", "Python 3.8.10")
        self.stub("sha256sum", "sha256sum (GNU coreutils) 9.5")
        self.stub("tar", "tar (GNU tar) 1.27")
        self.stub("sqlite3", "3.54.1 2026-10-16")
        res = self.tools()
        self.assertEqual(res["tool terraform 1.5.7 supported"][0], "FAIL")
        self.assertEqual(res["tool aws 1.33.0 supported"][0], "FAIL")
        self.assertEqual(res["tool python3 3.8.10 supported"][0], "FAIL")
        self.assertEqual(res["tool tar 1.27 supported"][0], "FAIL")
        self.assertEqual(res["tool session-manager-plugin on PATH"][0], "FAIL")
        self.assertEqual(res["tool docker 29.9.3 supported"][0], "PASS")
        self.assertEqual(res["tool git present"][0], "PASS")             # presence only: never executed
        self.assertEqual(res["tool sqlite3 3.54.1 supported"][0], "PASS")

    def test_supported_versions_pass(self):
        for n, t in (("terraform", '{"terraform_version": "1.16.6"}'), ("aws", "aws-cli/2.31.0 Python/3.13"),
                     ("session-manager-plugin", "1.2.707.0"), ("docker", "Docker version 29.9.3"), ("git", "x"),
                     ("python3", "Python 3.12.3"), ("sha256sum", "sha256sum (GNU coreutils) 9.5"),
                     ("tar", "tar (GNU tar) 1.35"), ("sqlite3", "3.54.1")):
            self.stub(n, t)
        res = self.tools()
        self.assertEqual([k for k, (s, _) in res.items() if s != "PASS"], [])
        self.assertEqual(len(res), len(self.pf.TOOLS))


class PreflightBindingAndPublication(unittest.TestCase):
    def setUp(self):
        self.pf = preflight_module()

    def test_repository_binding_holds(self):
        _, out = quiet(self.pf.check_binding, "8080", self.pf.runbook_parameters()[0])
        self.assertNotIn("FAIL", out)
        self.assertIn("compose.yaml publishes on 127.0.0.1 only", out)

    def test_a_wildcard_port_is_found(self):
        ports = self.pf.compose_ports("services:\n  a:\n    ports:\n      - \"127.0.0.1:1:1\"\n      # c\n      - 8080:8080\n"
                                      "    environment:\n      X: 1\n  b:\n    ports:\n    - '0.0.0.0:2:2'\n")
        self.assertEqual(ports, ["127.0.0.1:1:1", "8080:8080", "0.0.0.0:2:2"])

    def test_app_port_mismatch_fails(self):
        _, out = quiet(self.pf.check_binding, "9000", self.pf.runbook_parameters()[0])
        self.assertIn("FAIL host parameter FLH_HOST_PORT == app_port", out)

    def test_publication_rules_agree_with_the_independent_matcher(self):
        rules = IgnoreRules.RULES
        for p in self.pf.LOCAL_SAMPLES + IgnoreRules.IGNORED:
            with self.subTest(path=p):
                self.assertTrue(self.pf.gitignored(rules, p))
                self.assertEqual(self.pf.gitignored(rules, p), gitignored(rules, p))
        for p in IgnoreRules.KEPT:
            self.assertFalse(self.pf.gitignored(rules, p), p)
        _, out = quiet(self.pf.check_publication)
        self.assertNotIn("FAIL", out)

    def test_launch_card_is_private_and_refused_in_the_repository(self):
        import argparse
        td = tempfile.mkdtemp()
        try:
            args = argparse.Namespace(bundle=None, sha256=None, tools=False)
            quiet(self.pf.rec, "FAIL", "example blocker", "fix it")
            quiet(self.pf.rec, "OPEN", "owner input authorization", "budget")
            card = os.path.join(td, "card.md")
            quiet(self.pf.write_card, card, {"aws_region": "us-east-1", "ami_id": "ami-REPLACE_ME"}, args)
            text = rd(card)
            self.assertEqual(os.stat(card).st_mode & 0o777, 0o600)
            self.assertIn("| ami_id | <AMI_ID> |", text)
            self.assertIn("<ACCOUNT_ID>", text)
            self.assertIn("- example blocker: fix it", text)
            self.assertIn("**BLOCKED**", text)
            self.assertNotRegex(text, r"\b[0-9]{12}\b")
            self.pf.results.clear()
            inside = os.path.join(STAGING, "card.md")
            quiet(self.pf.write_card, inside, {}, args)
            self.assertFalse(os.path.exists(inside))
            self.assertEqual(self.pf.results[-1][0], "FAIL")
        finally:
            shutil.rmtree(td)


class PlanChecklist(unittest.TestCase):
    """R2-041/R2-042: the owner's checklist from a plan, telling unknown values from settings left out on purpose."""

    def run_it(self, plan):
        p = os.path.join(self.td, "plan.json")
        jdump(plan, p)
        return subprocess.run([PY, "-I", "-B", os.path.join(STAGING, "tools", "plan_review.py"), "checklist", p, "--json"],
                              capture_output=True, text=True)

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.td)
        with open(os.path.join(FIX, "plan-create-safe.json")) as fh:
            self.plan = json.load(fh)

    def host(self):
        return next(rc for rc in self.plan["resource_changes"] if rc["address"] == "aws_instance.host")["change"]

    def test_safe_plan_passes_every_item(self):
        r = self.run_it(self.plan)
        self.assertEqual(r.returncode, 0, r.stdout)
        out = json.loads(r.stdout)
        self.assertEqual((out["wrong"], out["confirm_after_apply"]), (0, 0))
        key = next(x for x in out["rows"] if x["attribute"] == "key_name")
        self.assertEqual((key["state"], key["ok"]), ("OMITTED", True))      # left out on purpose: no SSH key

    def test_production_rows_follow_the_recorded_environment(self):
        # R3: a production plan is reviewed against production's settings, a weakened one is not
        safe = json.loads(self.run_it(json.loads(rd(os.path.join(FIX, "plan-production-create-safe.json")))).stdout)
        self.assertEqual(safe["wrong"], 0)
        rows = {x["item"]: x for x in safe["rows"]}
        self.assertEqual(rows["shutdown stops the host (never terminates)"]["value"], "stop")
        self.assertIs(rows["termination protection on"]["ok"], True)
        weak = json.loads(self.run_it(json.loads(rd(os.path.join(FIX, "plan-production-unsafe-staging-settings.json")))).stdout)
        bad = sorted(x["item"] for x in weak["rows"] if x["ok"] is False)
        self.assertEqual(bad, ["bucket kept on destroy (backups survive)", "shutdown stops the host (never terminates)",
                               "termination protection on"])

    def test_unknown_is_not_omitted_and_not_wrong(self):
        ch = self.host()
        ch["after"].pop("ami")
        ch.setdefault("after_unknown", {})["ami"] = True                     # resolved at apply (e.g. an SSM parameter)
        ch["after"]["metadata_options"][0]["http_tokens"] = None             # omitted: the provider default would apply
        out = json.loads(self.run_it(self.plan).stdout)
        rows = {x["attribute"]: x for x in out["rows"]}
        self.assertEqual((rows["ami"]["state"], rows["ami"]["ok"]), ("KNOWN AFTER APPLY", None))
        self.assertEqual((rows["metadata_options.0.http_tokens"]["state"], rows["metadata_options.0.http_tokens"]["ok"]),
                         ("OMITTED", False))
        self.assertEqual((out["wrong"], out["confirm_after_apply"]), (1, 1))

    def test_replaced_data_volume_plan_still_lists_settings_and_plan_check_stops_it(self):
        with open(os.path.join(FIX, "plan-unsafe-replace-data-volume.json")) as fh:
            plan = json.load(fh)
        out = json.loads(self.run_it(plan).stdout)
        self.assertTrue(any(x["address"] == "aws_ebs_volume.data" and x["state"] == "SET" for x in out["rows"]))
        r = subprocess.run([PY, "-I", "-B", os.path.join(STAGING, "tools", "plan_check.py"), "--mode", "update",
                            os.path.join(FIX, "plan-unsafe-replace-data-volume.json")], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("aws_ebs_volume.data: replace of a resource that holds data (stop rule): never allowed", r.stdout)


class PlanReview(unittest.TestCase):
    TOOL = os.path.join(STAGING, "tools", "plan_review.py")
    SAFE = os.path.join(FIX, "plan-create-safe.json")

    def setUp(self):
        self.td = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.td)

    def variant(self, name, edit):
        p = jload(self.SAFE)
        edit(p)
        out = os.path.join(self.td, name)
        jdump(p, out)
        return out

    def test_reordered_plan_with_other_metadata_is_the_same(self):
        def edit(p):
            p["resource_changes"].reverse()
            p["terraform_version"] = "9.9.9"
            p["prior_state"] = {"values": {}}
        r = run(self.TOOL, "diff", self.SAFE, self.variant("b.json", edit))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("(not compared) terraform_version: 1.16.6 -> 9.9.9", r.stdout)

    def test_diff_groups_by_service_and_blast_radius(self):
        def edit(p):
            for rc in p["resource_changes"]:
                if rc["address"] == "aws_ebs_volume.data":
                    rc["change"]["actions"] = ["delete", "create"]
                if rc["address"] == "aws_vpc.stg":
                    rc["change"]["after"]["tags_all"]["Run"] = "other"
                if rc["address"] == "aws_instance.host":
                    rc["change"]["after"]["instance_type"] = "t3.medium"
            p["resource_changes"].append({"address": "aws_eip.public", "mode": "managed", "type": "aws_eip", "name": "public",
                                          "change": {"actions": ["create"], "after": {"domain": "vpc"}}})
        r = run(self.TOOL, "diff", self.SAFE, self.variant("b.json", edit), "--json")
        self.assertEqual(r.returncode, 1)
        got = {d["address"]: (d["service"], d["radius"]) for d in json.loads(r.stdout)["differences"]}
        self.assertEqual(got, {"aws_ebs_volume.data": ("EC2", "data-loss"), "aws_eip.public": ("EC2", "access"),
                               "aws_instance.host": ("EC2", "service"), "aws_vpc.stg": ("VPC network", "metadata")})

    def test_values_known_after_apply_compare_equal(self):
        def mark(value):
            def edit(p):
                for rc in p["resource_changes"]:
                    if rc["address"] == "aws_instance.host":
                        rc["change"]["after"]["public_ip"] = value
                        rc["change"]["after_unknown"] = {"public_ip": True}
            return edit
        r = run(self.TOOL, "diff", self.variant("a.json", mark(None)), self.variant("b.json", mark("203.0.113.9")))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_summary_radius(self):
        r = run(self.TOOL, "summary", os.path.join(FIX, "plan-unsafe-replace-data-volume.json"), "--json")
        rows = {x["address"]: x["radius"] for x in json.loads(r.stdout)["changes"]}
        self.assertEqual(rows["aws_ebs_volume.data"], "data-loss")
        self.assertEqual(rows["aws_instance.host"], "service")
        self.assertEqual(rows["aws_s3_bucket.staging"], "none")

    def test_cost_keeps_counts_and_rates_apart(self):
        r = run(self.TOOL, "cost", self.SAFE)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("instance types {'t3.small': 1}; public IPv4 1; gp3 24 GiB", r.stdout)
        self.assertRegex(r.stdout, r"total\s+\$\s+0\.11 \| \$\s+20\.80")

        def edit(p):
            for rc in p["resource_changes"]:
                if rc["address"] == "aws_instance.host":
                    rc["change"]["after"]["instance_type"] = "m7i.large"
        r = run(self.TOOL, "cost", self.variant("b.json", edit))
        self.assertEqual(r.returncode, 1)
        self.assertIn("NOT COSTED: aws_instance m7i.large (no hourly rate)", r.stdout)
        asm = jload(os.path.join(STAGING, "cost_assumptions.json"))
        self.assertNotIn("count", json.dumps(asm["rates"]))        # the assumptions hold rates, never counts

    def test_freshness_by_stamp_variables_and_time(self):
        tv = filled_tfvars(os.path.join(self.td, "terraform.tfvars"))
        vals = {"aws_region": "us-east-1", "instance_type": "t3.small"}

        def edit(p):
            p["variables"] = {k: {"value": v} for k, v in vals.items()}
        plan = self.variant("stg.plan.json", edit)
        r = run(self.TOOL, "stamp", plan, "--tfvars", tv)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(gitignored(IgnoreRules.RULES, "staging/terraform/stg.plan-stamp.json"))
        r = run(self.TOOL, "freshness", plan, "--tfvars", tv)
        self.assertEqual(r.returncode, 1)          # variables set now but not recorded in this partial plan
        self.assertIn("STALE var.ami_id: set now but not recorded in the plan", r.stdout)
        vals.update({k: v.strip('"') for k, v in (l.split(" = ") for l in rd(tv).splitlines())})
        vals.update({"vpc_cidr": "10.85.0.0/24", "app_port": 8080, "max_runtime_hours": 4, "data_volume_size_gib": 8,
                     "host_role_permissions_boundary_name": "flh-stg-host-boundary", "compose_plugin_version": "v2.29.7",
                     "environment": "staging", "backup_retention_days": 35})
        plan = self.variant("stg.plan.json", edit)
        run(self.TOOL, "stamp", plan, "--tfvars", tv)
        r = run(self.TOOL, "freshness", plan, "--tfvars", tv)
        self.assertEqual(r.returncode, 0, r.stdout)
        wr(tv, rd(tv).replace("t3.small", "t3.medium"))
        r = run(self.TOOL, "freshness", plan, "--tfvars", tv)
        self.assertEqual(r.returncode, 1)
        self.assertIn("STALE tfvars:terraform.tfvars: changed since the plan was stamped", r.stdout)
        self.assertIn("STALE var.instance_type: the plan used t3.small, the inputs now say t3.medium", r.stdout)
        os.unlink(os.path.join(self.td, "stg.plan-stamp.json"))

        def old(p):
            edit(p)
            p["timestamp"] = "2001-01-01T00:00:00Z"
        r = run(self.TOOL, "freshness", self.variant("old.plan.json", old), "--tfvars", tv)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no stamp: comparing modification times with the plan's timestamp", r.stdout)
        self.assertIn("terraform/main.tf: modified after the plan", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=1)
