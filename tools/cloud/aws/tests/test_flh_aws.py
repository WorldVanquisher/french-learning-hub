"""Offline tests (standard library only). No network, no AWS, no boto3 needed."""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from helpers import CONCEPTS, ENTRIES, TempDir, add_entry, make_demo, run_cli

from flh_aws import fakes
from flh_aws.ledger import CapExceeded, Ledger
from flh_aws.restore import restore_local
from flh_aws.snapshot import (MANIFEST_NAME, REPO, SNAPSHOT_NAME, Refused, VerificationError, make_package,
                              sha256_file, verify_package)
from flh_aws import titan

AWS_DIR = Path(__file__).resolve().parents[1]


def flip_byte(path: Path, offset: int) -> None:
    data = bytearray(path.read_bytes())
    data[offset] ^= 0xFF
    path.write_bytes(bytes(data))


class SnapshotTests(unittest.TestCase):
    def test_backup_api_is_consistent_on_a_running_wal_database(self):
        with TempDir() as t:
            demo, db = make_demo(t)
            writer = sqlite3.connect(db, isolation_level=None)
            writer.execute("PRAGMA wal_autocheckpoint=0")
            add_entry(writer, ENTRIES[0])  # committed, only in the -wal file (no checkpoint)
            self.assertTrue(Path(str(db) + "-wal").stat().st_size > 0)
            writer.execute("BEGIN")
            add_entry(writer, "uncommitted text that must not appear")  # open transaction
            try:
                out = make_package(demo, t / "pkg", "run1")
            finally:
                writer.execute("ROLLBACK")
                writer.close()
            m = out["manifest"]
            self.assertEqual(m["domain"]["counts"]["learning_entries"], len(ENTRIES) + 1)
            self.assertEqual(m["snapshot"]["journal_mode"], "delete")
            self.assertEqual(m["snapshot"]["integrity"]["integrity_check"], ["ok"])
            self.assertEqual(m["snapshot"]["method"], "sqlite3_online_backup_api")
            self.assertFalse((t / "pkg" / (SNAPSHOT_NAME + "-wal")).exists())
            self.assertNotIn(str(t), json.dumps(m))  # no absolute paths in the manifest
            self.assertEqual(m["schema_info"]["migrations_applied"][-1], "011_semantic_index_runs.sql")
            self.assertIn("migrations/010_semantic_index.sql", m["application"]["files_sha256"])
            verify_package(t / "pkg", out["manifest_sha256"])

    def test_flh060_layout_is_accepted(self):
        with TempDir() as t:
            demo, _ = make_demo(t, "flh060")
            self.assertEqual(make_package(demo, t / "pkg", "r")["manifest"]["source"]["kind"], "flh060-demo")

    def test_non_synthetic_text_is_refused_before_writing(self):
        with TempDir() as t:
            demo, _ = make_demo(t, extra_entry="my real personal note about my week")
            with self.assertRaises(Refused):
                make_package(demo, t / "pkg", "r")
            self.assertFalse((t / "pkg").exists())

    def test_directory_without_demo_marker_is_refused(self):
        with TempDir() as t:
            demo, _ = make_demo(t)
            (demo / ".flh034-demo").unlink()
            with self.assertRaises(Refused):
                make_package(demo, t / "pkg", "r")

    def test_paths_inside_the_repository_are_refused(self):
        with TempDir() as t:
            demo, _ = make_demo(t)
            with self.assertRaises(Refused):
                make_package(demo, REPO / "data" / "flh063-pkg", "r")
            with self.assertRaises(Refused):
                make_package(REPO, t / "pkg", "r")


class CorruptionTests(unittest.TestCase):
    def setUp(self):
        self.td = TempDir()
        self.t = self.td.__enter__()
        demo, _ = make_demo(self.t)
        out = make_package(demo, self.t / "pkg", "run1")
        self.pkg, self.msha = self.t / "pkg", out["manifest_sha256"]

    def tearDown(self):
        self.td.__exit__()

    def assertRejected(self, expected_sha=None):
        with self.assertRaises(VerificationError):
            verify_package(self.pkg, expected_sha or self.msha)
        into = self.t / "restore"
        with self.assertRaises(VerificationError):
            restore_local(self.pkg, into, expected_sha or self.msha)
        self.assertTrue((into / "RESTORE-REJECTED.json").is_file())
        self.assertFalse((into / "restored").exists())
        self.assertFalse((into / "RESTORE-ACCEPTED.json").exists())

    def test_clean_package_restores_into_a_new_directory(self):
        rec = restore_local(self.pkg, self.t / "restore", self.msha)
        self.assertTrue((self.t / "restore" / "restored" / "demo.db").is_file())
        self.assertEqual(rec["checks"]["integrity"]["integrity_check"], ["ok"])
        with self.assertRaises(Refused):  # never over existing data
            restore_local(self.pkg, self.t / "restore", self.msha)

    def test_flipped_snapshot_byte(self):
        flip_byte(self.pkg / SNAPSHOT_NAME, 5000)
        self.assertRejected()

    def test_truncated_snapshot(self):
        p = self.pkg / SNAPSHOT_NAME
        p.write_bytes(p.read_bytes()[:-4096])
        self.assertRejected()

    def test_edited_manifest(self):
        m = json.loads((self.pkg / MANIFEST_NAME).read_text())
        m["domain"]["counts"]["learning_entries"] += 1
        (self.pkg / MANIFEST_NAME).write_text(json.dumps(m))
        self.assertRejected()

    def test_consistently_rewritten_package_still_fails_domain_check(self):
        # Someone edits a domain row and rewrites both hashes; only the domain
        # fingerprint (recomputed from the bytes) can catch it.
        snap = self.pkg / SNAPSHOT_NAME
        c = sqlite3.connect(snap)
        c.execute("UPDATE knowledge_concepts SET pedagogical_intent='expression' WHERE id=1")
        c.commit()
        c.close()
        m = json.loads((self.pkg / MANIFEST_NAME).read_text())
        m["snapshot"]["bytes"], m["snapshot"]["sha256"] = snap.stat().st_size, sha256_file(snap)
        (self.pkg / MANIFEST_NAME).write_text(json.dumps(m))
        self.assertRejected(sha256_file(self.pkg / MANIFEST_NAME))

    def test_not_a_database(self):
        snap = self.pkg / SNAPSHOT_NAME
        snap.write_bytes(b"x" * snap.stat().st_size)
        m = json.loads((self.pkg / MANIFEST_NAME).read_text())
        m["snapshot"]["sha256"] = sha256_file(snap)
        (self.pkg / MANIFEST_NAME).write_text(json.dumps(m))
        self.assertRejected(sha256_file(self.pkg / MANIFEST_NAME))


class LedgerTests(unittest.TestCase):
    def test_caps_are_checked_before_and_persist(self):
        with TempDir() as t:
            led = Ledger(t, caps={"s3_put_requests": 2, "s3_put_bytes": 10, "s3_get_requests": 1,
                                  "s3_get_bytes": 1, "s3_delete_requests": 1, "s3_list_requests": 1,
                                  "bedrock_invocations": 1, "bedrock_input_chars": 5, "bedrock_request_bytes": 99})
            led.reserve("x", {"s3_put_requests": 1, "s3_put_bytes": 6}, {}, "fake")
            with self.assertRaises(CapExceeded):
                Ledger(t).reserve("x", {"s3_put_requests": 1, "s3_put_bytes": 6}, {}, "fake")
            d = Ledger(t).read()  # a new instance sees the persisted state
            self.assertEqual(d["used"]["s3_put_bytes"], 6)
            self.assertEqual(len(d["calls"]), 1)
            self.assertEqual(d["calls"][0]["outcome"], "attempted")


class FakeWorkflowTests(unittest.TestCase):
    """The operator workflow through the CLI, against filesystem fakes."""

    def setUp(self):
        self.td = TempDir()
        self.t = self.td.__enter__()
        self.state = self.t / "state"
        self.demo, _ = make_demo(self.t)
        self.fake = self.state / "fake-aws"
        self.assertEqual(run_cli("init", "--state", self.state, "--backend", "fake")[0], 0)

    def tearDown(self):
        self.td.__exit__()

    def cli(self, *a):
        return run_cli(a[0], "--state", self.state, *a[1:])

    def faults(self, d):
        (self.fake / "faults.json").write_text(json.dumps(d))

    def deploy_and_snapshot(self):
        code, out, err = self.cli("deploy", "--region", "ca-central-1")
        self.assertEqual(code, 0, err)
        code, snap, err = self.cli("snapshot", "--source-demo", self.demo)
        self.assertEqual(code, 0, err)
        return out, snap

    def test_full_cycle_and_owned_cleanup(self):
        dep, snap = self.deploy_and_snapshot()
        self.assertEqual(dep["checks"]["default_encryption"], ["AES256"])
        self.assertEqual(dep["checks"]["expiration_days"], [7])
        run = snap["run_id"]
        code, up, err = self.cli("upload", "--run", run)
        self.assertEqual(code, 0, err)
        self.assertEqual([k.rsplit("/", 1)[1] for k in up["keys"]], [SNAPSHOT_NAME, MANIFEST_NAME])
        # Repeat: refused locally, nothing sent.
        before = fakes.counters(self.fake).get("s3.PutObject")
        self.assertEqual(self.cli("upload", "--run", run)[0], 2)
        self.assertEqual(fakes.counters(self.fake).get("s3.PutObject"), before)
        code, rest, err = self.cli("restore", "--run", run, "--into", self.t / "restored")
        self.assertEqual(code, 0, err)
        self.assertTrue((self.t / "restored" / "restored" / "demo.db").is_file())
        self.assertEqual(rest["checks"]["domain"]["counts"]["knowledge_concepts"], len(CONCEPTS))
        code, cl, err = self.cli("cleanup")
        self.assertEqual(code, 0, err)
        self.assertEqual(cl["cleanup_state"], "deletion_confirmed")
        self.assertEqual(cl["stack"]["observed_by"], "describe_stacks_by_id")
        self.assertEqual(cl["stack"]["bucket_probe"], "absent")
        self.assertEqual(len(cl["objects_deleted"]), 2)
        self.assertFalse((self.fake / "s3").exists() and any((self.fake / "s3").iterdir()))
        self.assertEqual(self.cli("cleanup")[0], 0)  # safe to repeat

    def test_existing_key_is_never_overwritten(self):
        _, snap = self.deploy_and_snapshot()
        res = json.loads((self.state / "resources.json").read_text())
        key = f"flh063/{snap['run_id']}/{SNAPSHOT_NAME}"
        fakes.FakeS3(self.fake, "ca-central-1").plant_object(res["bucket"], key, b"someone else's object")
        code, _, err = self.cli("upload", "--run", snap["run_id"])
        self.assertEqual(code, 2)
        self.assertIn("not overwritten", err)
        planted = fakes.FakeS3(self.fake, "ca-central-1")._obj(res["bucket"], key).with_suffix(".bin")
        self.assertEqual(planted.read_bytes(), b"someone else's object")

    def test_failed_upload_is_recorded_and_restore_refuses(self):
        _, snap = self.deploy_and_snapshot()
        self.faults({"put_object_fail": {"key_suffix": MANIFEST_NAME, "code": "InternalError"}})
        code, _, err = self.cli("upload", "--run", snap["run_id"])
        self.assertEqual(code, 1, err)
        led = Ledger(self.state).read()
        self.assertEqual([c["outcome"] for c in led["calls"] if c["kind"] == "s3_put_object"], ["ok", "failed"])
        self.assertEqual(self.cli("restore", "--run", snap["run_id"], "--into", self.t / "r")[0], 2)
        self.assertFalse((self.t / "r").exists())
        self.faults({})
        code, cl, err = self.cli("cleanup")  # removes the one object that did upload
        self.assertEqual(code, 0, err)
        self.assertEqual(len(cl["objects_deleted"]), 1)

    def test_corrupted_download_is_rejected_before_acceptance(self):
        _, snap = self.deploy_and_snapshot()
        self.assertEqual(self.cli("upload", "--run", snap["run_id"])[0], 0)
        self.faults({"get_object_corrupt": {"key_suffix": SNAPSHOT_NAME, "offset": 4096}})
        code, _, err = self.cli("restore", "--run", snap["run_id"], "--into", self.t / "r")
        self.assertEqual(code, 1, err)
        self.assertTrue((self.t / "r" / "RESTORE-REJECTED.json").is_file())
        self.assertFalse((self.t / "r" / "restored").exists())
        self.assertTrue((self.t / "r" / "download" / SNAPSHOT_NAME).is_file())  # evidence kept

    def test_restore_never_targets_the_source_or_existing_data(self):
        _, snap = self.deploy_and_snapshot()
        self.assertEqual(self.cli("upload", "--run", snap["run_id"])[0], 0)
        self.assertEqual(self.cli("restore", "--run", snap["run_id"], "--into", self.demo / "x")[0], 2)
        self.assertEqual(self.cli("restore", "--run", snap["run_id"], "--into", self.demo)[0], 2)
        self.assertEqual(self.cli("restore", "--run", snap["run_id"], "--into", REPO / "data" / "x")[0], 2)

    def test_cleanup_keeps_unknown_objects_and_the_stack(self):
        _, snap = self.deploy_and_snapshot()
        self.assertEqual(self.cli("upload", "--run", snap["run_id"])[0], 0)
        res = json.loads((self.state / "resources.json").read_text())
        s3 = fakes.FakeS3(self.fake, "ca-central-1")
        s3.plant_object(res["bucket"], "other/unknown.txt", b"not ours")
        code, _, err = self.cli("cleanup")
        self.assertEqual(code, 1)
        self.assertIn("other/unknown.txt", err)
        self.assertEqual(json.loads((self.state / "resources.json").read_text())["stack"]["status"], "CREATE_COMPLETE")
        self.assertTrue(s3._obj(res["bucket"], "other/unknown.txt").with_suffix(".bin").exists())
        st = json.loads((self.fake / "cfn" / f"{res['stack']['name']}.json").read_text())
        self.assertEqual(st["StackStatus"], "CREATE_COMPLETE")
        # owned objects were still removed
        self.assertEqual(json.loads((self.state / "resources.json").read_text())["objects"], [])

    def test_object_changed_after_upload_is_not_deleted(self):
        _, snap = self.deploy_and_snapshot()
        self.assertEqual(self.cli("upload", "--run", snap["run_id"])[0], 0)
        res = json.loads((self.state / "resources.json").read_text())
        key = res["objects"][0]["key"]
        s3 = fakes.FakeS3(self.fake, "ca-central-1")
        meta = s3._obj(res["bucket"], key).with_suffix(".meta")
        m = json.loads(meta.read_text())
        m["ETag"] = '"replaced-by-someone"'
        meta.write_text(json.dumps(m))
        code, _, err = self.cli("cleanup")
        self.assertEqual(code, 1)
        self.assertTrue(meta.exists())

    def test_bucket_with_weakened_settings_blocks_upload(self):
        _, snap = self.deploy_and_snapshot()
        res = json.loads((self.state / "resources.json").read_text())
        cfgp = self.fake / "s3" / res["bucket"] / "config.json"
        cfg = json.loads(cfgp.read_text())
        cfg["pab"]["BlockPublicPolicy"] = False
        cfgp.write_text(json.dumps(cfg))
        code, _, err = self.cli("upload", "--run", snap["run_id"])
        self.assertEqual(code, 1)
        self.assertIn("BlockPublicPolicy", err)
        self.assertIsNone(fakes.counters(self.fake).get("s3.PutObject"))

    def test_upload_over_the_size_cap_is_refused_before_sending(self):
        _, snap = self.deploy_and_snapshot()
        led = json.loads((self.state / "ledger.json").read_text())
        led["caps"]["s3_put_bytes"] = 1000
        (self.state / "ledger.json").write_text(json.dumps(led))
        code, _, err = self.cli("upload", "--run", snap["run_id"])
        self.assertEqual(code, 2, err)
        self.assertIsNone(fakes.counters(self.fake).get("s3.PutObject"))

    def test_second_deploy_from_one_state_is_refused(self):
        self.deploy_and_snapshot()
        self.assertEqual(self.cli("deploy", "--region", "ca-central-1")[0], 2)

    def test_status_and_plan_need_no_network(self):
        code, plan, _ = self.cli("plan", "--region", "ca-central-1", "--dimensions", "512")
        self.assertEqual(code, 0)
        self.assertLess(plan["estimate"]["total_upper_bound_usd"], 0.1)
        self.assertIsNone(plan["region_decision"]["warning"])
        self.assertEqual(self.cli("status")[0], 0)
        self.assertEqual(fakes.counters(self.fake), {})


class TitanTests(unittest.TestCase):
    def setUp(self):
        self.td = TempDir()
        self.t = self.td.__enter__()
        self.state = self.t / "state"
        run_cli("init", "--state", self.state, "--backend", "fake")
        self.fake = self.state / "fake-aws"

    def tearDown(self):
        self.td.__exit__()

    def smoke(self, *extra):
        return run_cli("titan-smoke", "--state", self.state, "--region", "ca-central-1", "--dimensions", "512", *extra)

    def faults(self, d):
        self.fake.mkdir(exist_ok=True)
        (self.fake / "faults.json").write_text(json.dumps(d))

    def test_smoke_counts_every_call_and_validates_vectors(self):
        code, out, err = self.smoke()
        self.assertEqual(code, 0, err)
        self.assertEqual(out["completed_calls"], 6)
        self.assertTrue(all(abs(c["norm"] - 1) < 1e-6 for c in out["calls"]))
        self.assertEqual(out["identity"],
                         "bedrock/amazon.titan-embed-text-v2:0/ca-central-1/d512/normalize/flh_titan_verbatim_v1")
        led = Ledger(self.state).read()
        self.assertEqual(led["used"]["bedrock_invocations"], 6)
        self.assertEqual(fakes.counters(self.fake)["bedrock.InvokeModel"], 6)
        # A second smoke would need 12 > 10: refused before any call.
        self.assertEqual(self.smoke()[0], 2)
        self.assertEqual(fakes.counters(self.fake)["bedrock.InvokeModel"], 6)

    def test_failure_stops_without_retry_and_is_recorded(self):
        self.faults({"invoke_fail": {"after": 2, "code": "ThrottlingException"}})
        code, _, err = self.smoke()
        self.assertEqual(code, 1)
        self.assertEqual(fakes.counters(self.fake)["bedrock.InvokeModel"], 3)  # no retry, no further inputs
        outcomes = [c["outcome"] for c in Ledger(self.state).read()["calls"]]
        self.assertEqual(outcomes, ["ok", "ok", "failed"])

    def test_invalid_vectors_fail(self):
        for bad in ("nan", "zero", "short"):
            with self.subTest(bad=bad):
                st = self.t / f"s-{bad}"
                run_cli("init", "--state", st, "--backend", "fake")
                (st / "fake-aws").mkdir()
                (st / "fake-aws" / "faults.json").write_text(json.dumps({"invoke_bad": bad}))
                code, _, err = run_cli("titan-smoke", "--state", st, "--region", "ca-central-1", "--dimensions", "256")
                self.assertEqual(code, 1, err)
                self.assertEqual(fakes.counters(st / "fake-aws")["bedrock.InvokeModel"], 1)

    def test_contract_refusals(self):
        with self.assertRaises(Refused):
            titan.check_model_and_dims("us.amazon.titan-embed-text-v2:0", 512)
        with self.assertRaises(Refused):
            titan.check_model_and_dims(titan.MODEL_ID, 768)
        with self.assertRaises(Refused):
            titan.build_body("x" * 2001, 256)
        with self.assertRaises(Refused):
            titan.build_body("   ", 256)
        body = json.loads(titan.build_body("je ne fume plus", 1024))
        self.assertEqual(body, {"inputText": "je ne fume plus", "dimensions": 1024, "normalize": True,
                                "embeddingTypes": ["float"]})  # verbatim: no query:/passage: prefix

    def test_preflight_is_read_only(self):
        code, out, err = run_cli("titan-preflight", "--state", self.state, "--region", "ca-central-1")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["inference_types"], ["ON_DEMAND"])
        self.assertNotIn("bedrock.InvokeModel", fakes.counters(self.fake))
        self.assertEqual(Ledger(self.state).read()["used"]["bedrock_invocations"], 0)

    def test_live_backend_needs_profile_and_allow_live(self):
        st = self.t / "live"
        run_cli("init", "--state", st, "--backend", "aws")
        code, _, err = run_cli("titan-smoke", "--state", st, "--region", "ca-central-1", "--dimensions", "512")
        self.assertEqual(code, 2)  # no profile (or no boto3): refused, nothing sent
        self.assertEqual(Ledger(st).read()["calls"], [])


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.td = TempDir()
        self.t = self.td.__enter__()
        self.state = self.t / "state"
        run_cli("init", "--state", self.state, "--backend", "fake")
        from flh_aws.adapter import make_server
        self.fake_root = self.state / "fake-aws"
        self.srv = make_server(self.state, fakes.fake_clients(self.fake_root, "ca-central-1").bedrock_runtime,
                               "ca-central-1", 256, "fake", "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.th.start()
        self.model = titan.identity("ca-central-1", 256)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.td.__exit__()

    def post(self, body):
        req = urllib.request.Request(self.url + "/v1/embeddings", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_go_provider_wire_format(self):
        with urllib.request.urlopen(self.url + "/readyz", timeout=5) as r:
            self.assertEqual(json.loads(r.read())["model"], self.model)
        self.assertEqual(fakes.counters(self.fake_root), {})  # startup and readyz send nothing
        code, out = self.post({"model": self.model, "input": ["a", "b"]})
        self.assertEqual(code, 200)
        self.assertEqual([d["index"] for d in out["data"]], [0, 1])
        self.assertEqual(len(out["data"][0]["embedding"]), 256)
        self.assertEqual(out["data"][0]["embedding"], fakes.fake_vector("a", 256))  # text sent verbatim

    def test_refusals(self):
        self.assertEqual(self.post({"model": "other", "input": ["a"]})[0], 400)
        self.assertEqual(self.post({"model": self.model, "input": ["a"] * 9})[0], 400)
        self.assertEqual(self.post({"model": self.model, "input": [1]})[0], 400)
        self.assertNotIn("bedrock.InvokeModel", fakes.counters(self.fake_root))

    def test_budget_and_failure(self):
        self.assertEqual(self.post({"model": self.model, "input": ["x"] * 8})[0], 200)
        code, out = self.post({"model": self.model, "input": ["x"] * 3})  # 8 + 3 > 10
        self.assertEqual(code, 429)
        self.assertEqual(fakes.counters(self.fake_root)["bedrock.InvokeModel"], 8)
        self.fake_root.joinpath("faults.json").write_text(json.dumps({"invoke_fail": {"after": 0}}))
        code, out = self.post({"model": self.model, "input": ["y"]})
        self.assertEqual(code, 502)
        self.assertNotIn("data", out)

    def test_non_loopback_bind_refused(self):
        from flh_aws.adapter import make_server
        with self.assertRaises(Refused):
            make_server(self.state, None, "ca-central-1", 256, "fake", "0.0.0.0", 0)


class StaticContractTests(unittest.TestCase):
    def test_template_and_policies(self):
        t = json.loads((AWS_DIR / "template" / "flh063-backup-bucket.json").read_text())
        self.assertEqual(sorted(t["Resources"]), ["Bucket", "BucketPolicy"])
        stmts = t["Resources"]["BucketPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        self.assertTrue(all(s["Effect"] == "Deny" for s in stmts))
        from flh_aws.s3store import REQUIRED_POLICY_SIDS
        self.assertEqual({s["Sid"] for s in stmts}, set(REQUIRED_POLICY_SIDS))
        b = t["Resources"]["Bucket"]["Properties"]
        self.assertNotIn("VersioningConfiguration", b)
        self.assertLessEqual(t["Parameters"]["RetentionDays"]["MaxValue"], 14)
        for f in (AWS_DIR / "iam").glob("*.json"):
            for s in json.loads(f.read_text())["Statement"]:
                acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
                self.assertFalse(any(a.endswith(":*") or a == "*" for a in acts), f)
                res = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
                self.assertTrue(all("flh063" in r or "titan-embed-text-v2:0" in r for r in res), f)

    def test_smoke_inputs_are_bounded_and_synthetic(self):
        items = titan.load_smoke_inputs()
        self.assertLessEqual(len(items), 10)
        catalog = (REPO / "scripts" / "demo" / "flh060" / "catalog.py").read_text()
        self.assertTrue(all(i["text"] in catalog for i in items))

    def test_importing_the_cli_does_not_import_boto3(self):
        import subprocess
        code = ("import sys; sys.path.insert(0, %r); import flh_aws.cli; "
                "print('boto3' in sys.modules)" % str(AWS_DIR))
        out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
