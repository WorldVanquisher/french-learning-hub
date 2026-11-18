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
PY = sys.executable


def load_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


bundle_tool = load_module("flh_staging_bundle", os.path.join(STAGING, "host", "flh-staging-bundle"))
identity = load_module("bundle_identity", os.path.join(STAGING, "bundle_identity.py"))


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
                    self.assertEqual(open(os.path.join(td, f), "rb").read(), open(os.path.join(FIX, f), "rb").read())


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
                text = open(os.path.join(out, f)).read()
                self.assertNotIn("__AWS_ACCOUNT_ID__", text)
                self.assertNotIn("__STAGING_AMI_ID__", text)
                self.assertEqual(os.stat(os.path.join(out, f)).st_mode & 0o777, 0o600)
            self.assertIn("image/ami-0123456789abcdef0", open(os.path.join(out, "flh-stg-deploy-ec2-policy.json")).read())
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
        text = "".join(open(os.path.join(STAGING, "iam", "out", f)).read() for f in os.listdir(os.path.join(STAGING, "iam", "out"))
                       if f.endswith(".json"))
        for a in ("AllocateAddress", "AssociateAddress", "AuthorizeSecurityGroupIngress", "elastic-ip"):
            self.assertNotIn(a, text)


class TreeId(unittest.TestCase):
    def test_known_git_objects(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(identity.tree_id(td, {}), "4b825dc642cb6eb9a060e54bf8d69288fbee4904")  # Git's empty tree
            open(os.path.join(td, "hello"), "w").write("hello\n")
            rows = identity.scan(td)
            # blob "hello\n" = ce013625030ba8dba906f756967f9e9ca394464a (git hash-object)
            want = hashlib.sha1(b"tree 33\x00100644 hello\x00" + bytes.fromhex("ce013625030ba8dba906f756967f9e9ca394464a")).hexdigest()
            self.assertEqual(identity.tree_id(td, rows), want)

    def test_excludes_local_state(self):
        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "a.txt"), "w").write("a")
            base = identity.tree_id(td, identity.scan(td))
            os.makedirs(os.path.join(td, "deploy/aws/private-staging/staging/terraform/.terraform"))
            for p in ("x.tfstate", "y.tfplan", "app.db", "deploy/aws/private-staging/staging/terraform/.terraform/p"):
                open(os.path.join(td, p), "w").write("local")
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
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def make_bundle(parent, commit=None):
    d = os.path.join(parent, NAME)
    os.makedirs(os.path.join(d, "repo", "scripts", "daily"))
    os.makedirs(os.path.join(d, "repo", "scripts", "release"))
    open(os.path.join(d, "repo", "compose.yaml"), "w").write("services: {}\n")
    open(os.path.join(d, "repo", "scripts", "daily", "flh-daily.sh"), "w").write("#!/bin/bash\n")
    open(os.path.join(d, "repo", "scripts", "release", "restore_write_check.py"), "w").write("# check\n")
    open(os.path.join(d, "staging.override.yaml"), "w").write(bundle_tool.OVERRIDE.format(tag=TAG))
    labels = {bundle_tool.LABEL_REVISION: commit or "", bundle_tool.LABEL_TREE: TID}
    image_id = make_image_tar(os.path.join(d, "image.tar"), labels)
    files = {os.path.relpath(os.path.join(dp, f), d): sha(os.path.join(dp, f))
             for dp, _, fns in os.walk(d) for f in fns}
    pinned = {p: h for p, h in files.items() if p.startswith("repo/") or p == "staging.override.yaml"}
    manifest = {"format": bundle_tool.FORMAT, "name": NAME,
                "revision": {"commit": commit, "tree_id": TID, "files": 3, "content_sha256": "0" * 64},
                "image": {"tag": TAG, "platform": "linux/amd64", "labels": labels},
                "server_sha256": "1" * 64, "web_files_sha256": "2" * 64,
                "migrations": {"count": 21, "last": "021_x.sql"}, "files": pinned}
    json.dump(manifest, open(os.path.join(d, "MANIFEST.json"), "w"), indent=1, sort_keys=True)
    json.dump({"manifest_sha256": sha(os.path.join(d, "MANIFEST.json")), "image_id": image_id,
               "image_tar_sha256": sha(os.path.join(d, "image.tar"))}, open(os.path.join(d, "BUILD.json"), "w"))
    reseal(d)
    return d


def reseal(d):
    lines = []
    for dp, _, fns in os.walk(d):
        for f in fns:
            p = os.path.relpath(os.path.join(dp, f), d)
            if p != "SHA256SUMS":
                lines.append(f"{sha(os.path.join(d, p))}  {p}")
    open(os.path.join(d, "SHA256SUMS"), "w").write("\n".join(sorted(lines, key=lambda l: l[66:])) + "\n")


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
        open(os.path.join(self.d, "repo", "compose.yaml"), "a").write("# changed\n")
        self.refused("altered file")

    def test_added_file(self):
        open(os.path.join(self.d, "repo", "extra.sh"), "w").write("x")
        self.refused("added")

    def test_missing_file(self):
        os.unlink(os.path.join(self.d, "repo", "scripts", "release", "restore_write_check.py"))
        self.refused("missing file")

    def test_resealed_but_manifest_disagrees(self):
        open(os.path.join(self.d, "repo", "compose.yaml"), "a").write("# changed\n")
        reseal(self.d)  # an attacker can recompute SHA256SUMS, but MANIFEST.json pins the files
        self.refused("MANIFEST files differ")

    def test_inconsistent_identity(self):
        m = json.load(open(os.path.join(self.d, "MANIFEST.json")))
        m["revision"]["tree_id"] = "f" * 40
        json.dump(m, open(os.path.join(self.d, "MANIFEST.json"), "w"))
        reseal(self.d)
        self.refused("identity mismatch")

    def test_build_json_must_match_manifest(self):
        m = json.load(open(os.path.join(self.d, "MANIFEST.json")))
        m["server_sha256"] = "3" * 64
        json.dump(m, open(os.path.join(self.d, "MANIFEST.json"), "w"), indent=1, sort_keys=True)
        reseal(self.d)
        self.refused("BUILD.json manifest_sha256")

    def test_forged_image_labels(self):
        image_id = make_image_tar(os.path.join(self.d, "image.tar"),
                                  {bundle_tool.LABEL_REVISION: "", bundle_tool.LABEL_TREE: "e" * 40})
        b = json.load(open(os.path.join(self.d, "BUILD.json")))
        b.update(image_id=image_id, image_tar_sha256=sha(os.path.join(self.d, "image.tar")))
        json.dump(b, open(os.path.join(self.d, "BUILD.json"), "w"))
        reseal(self.d)
        self.refused("image label")

    def test_image_config_not_matching_build(self):
        b = json.load(open(os.path.join(self.d, "BUILD.json")))
        b["image_id"] = "sha256:" + "9" * 64
        json.dump(b, open(os.path.join(self.d, "BUILD.json"), "w"))
        reseal(self.d)
        self.refused("is not BUILD.json image_id")

    def test_override_must_name_the_image(self):
        os.chmod(os.path.join(self.d, "staging.override.yaml"), 0o644)
        open(os.path.join(self.d, "staging.override.yaml"), "w").write(bundle_tool.OVERRIDE.format(tag="flh-staging:other"))
        m = json.load(open(os.path.join(self.d, "MANIFEST.json")))
        m["files"]["staging.override.yaml"] = sha(os.path.join(self.d, "staging.override.yaml"))
        json.dump(m, open(os.path.join(self.d, "MANIFEST.json"), "w"), indent=1, sort_keys=True)
        b = json.load(open(os.path.join(self.d, "BUILD.json")))
        b["manifest_sha256"] = sha(os.path.join(self.d, "MANIFEST.json"))
        json.dump(b, open(os.path.join(self.d, "BUILD.json"), "w"))
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
    RULES = open(os.path.join(os.path.dirname(STAGING), ".gitignore")).read().splitlines()
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

    def test_every_tracked_file_here_is_kept(self):
        root = os.path.dirname(STAGING)
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in ("__pycache__",)]
            for f in fns:
                rel = os.path.relpath(os.path.join(dp, f), root)
                with self.subTest(path=rel):
                    self.assertFalse(gitignored(self.RULES, rel), f"{rel} would be ignored")


class Syntax(unittest.TestCase):
    def test_host_tool_is_python39(self):
        import ast
        ast.parse(open(os.path.join(STAGING, "host", "flh-staging-bundle")).read(), feature_version=(3, 9))

    def test_shell_syntax(self):
        for f in ("build_bundle.sh", "host/flh-staging-env"):
            with self.subTest(f=f):
                self.assertEqual(subprocess.run(["bash", "-n", os.path.join(STAGING, f)]).returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
