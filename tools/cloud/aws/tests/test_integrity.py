"""FLH-068: persisted stack ownership, receipt integrity and Titan continuation identity
(filesystem fakes, standard library only, no network)."""

from __future__ import annotations

import json
import unittest

from helpers import TempDir, make_demo, run_cli

from flh_aws import fakes, titan
from flh_aws.ledger import Ledger


class Case(unittest.TestCase):
    def setUp(self):
        self.td = TempDir()
        self.t = self.td.__enter__()
        self.state = self.t / "state"
        self.fake = self.state / "fake-aws"
        self.assertEqual(run_cli("init", "--state", self.state, "--backend", "fake")[0], 0)
        self.fake.mkdir()

    def tearDown(self):
        self.td.__exit__()

    def cli(self, *a):
        return run_cli(a[0], "--state", self.state, *a[1:])

    def res(self):
        return json.loads((self.state / "resources.json").read_text())

    def write_res(self, r):
        (self.state / "resources.json").write_text(json.dumps(r))

    def counts(self):
        return fakes.counters(self.fake)

    def deploy(self):
        code, _, err = self.cli("deploy", "--region", "ca-central-1")
        self.assertEqual(code, 0, err)

    def cloud_record(self):
        return self.fake / "cfn" / f"{self.res()['stack']['name']}.json"

    def assert_refused_without_requests(self, *argv):
        before = self.counts()
        code, out, err = self.cli(*argv)
        self.assertEqual(code, 1, err)
        self.assertIn("nothing was sent", err)
        self.assertEqual(self.counts(), before)
        self.assertNotIn("deletion_confirmed", json.dumps(out) if out else "")
        return err


class ReceiptIntegrityTests(Case):
    def test_malformed_receipts_are_refused_with_zero_requests(self):
        self.deploy()
        good = self.res()
        sid = good["stack"]["id"]
        bad = {
            "foreign StackId (other stack name)": lambda r: r["stack"].update(id=sid.replace(r["stack"]["name"],
                                                                                             "flh063-aaaaaaaaaaaa")),
            "foreign account": lambda r: r["stack"].update(id=sid.replace(":000000000000:", ":111122223333:")),
            "foreign region": lambda r: r["stack"].update(id=sid.replace(":ca-central-1:", ":us-east-1:")),
            "not an ARN": lambda r: r["stack"].update(id="NOT-A-STACK-ARN"),
            "non-string id": lambda r: r["stack"].update(id=12345),
            "unknown status": lambda r: r["stack"].update(status="TOTALLY_GONE"),
            "unknown schema": lambda r: r.update(schema="flh999"),
            "bucket/state mismatch": lambda r: r.update(bucket="flh063-bbbbbbbbbbbb"),
            "bad account": lambda r: r.update(account="12345"),
            "objects not a list": lambda r: r.update(objects={"k": 1}),
            "foreign recorded tags": lambda r: r["stack"].update(tags={"flh:task": "FLH-063", "flh:state-id": "x"}),
            "id-observation without id": lambda r: (r["stack"].pop("id"), r["stack"].update(status="DELETE_COMPLETE")),
        }
        for name, mutate in bad.items():
            with self.subTest(name):
                r = json.loads(json.dumps(good))
                mutate(r)
                self.write_res(r)
                self.assert_refused_without_requests("cleanup")
                code, st, _ = self.cli("status")
                self.assertEqual((code, st["stack"]["state"]), (1, "receipt_invalid"))
                self.assertEqual(self.cli("recover")[0], 1)
        self.write_res(good)
        self.assertEqual(self.cli("cleanup")[1]["cleanup_state"], "deletion_confirmed")

    def test_invalid_json_is_refused(self):
        self.deploy()
        (self.state / "resources.json").write_text("{not json")
        self.assert_refused_without_requests("cleanup")

    def test_bare_delete_complete_text_is_not_proof(self):
        """A consistent-looking DELETE_COMPLETE without the confirmation record is re-read, not trusted."""
        self.deploy()
        r = self.res()
        r["stack"].update(status="DELETE_COMPLETE", observed_by="describe_stacks_by_id")
        r["bucket_probe"] = {"result": "absent", "utc": "2026-10-14T00:00:00.000000Z"}
        self.write_res(r)
        code, st, _ = self.cli("status")
        self.assertEqual(st["stack"]["state"], "verification_unavailable")
        # cleanup reads the stack by StackId, finds it live and owned, and deletes it properly
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"), err)
        self.assertEqual(self.counts()["cfn.DeleteStack"], 1)
        self.assertFalse((self.fake / "s3" / r["bucket"]).exists())

    def test_inconsistent_confirmation_record_is_invalid(self):
        self.deploy()
        self.assertEqual(self.cli("cleanup")[0], 0)
        good = self.res()
        c = good["stack"]["deletion_confirmation"]
        self.assertEqual((c["stack_id"], c["stack_status"]), (good["stack"]["id"], "DELETE_COMPLETE"))
        for field, value in (("stack_id", good["stack"]["id"][:-1] + "0"), ("bucket_probe_utc", "2020-01-01T00:00:00Z"),
                             ("stack_status", "DELETE_FAILED")):
            with self.subTest(field):
                r = json.loads(json.dumps(good))
                r["stack"]["deletion_confirmation"][field] = value
                self.write_res(r)
                self.assert_refused_without_requests("cleanup")
        r = json.loads(json.dumps(good))
        r["bucket_probe"]["result"] = "present"
        self.write_res(r)
        self.assert_refused_without_requests("cleanup")

    def test_valid_confirmation_repeats_with_zero_requests(self):
        self.deploy()
        self.assertEqual(self.cli("cleanup")[0], 0)
        before = self.counts()
        for _ in range(3):
            code, cl, _ = self.cli("cleanup")
            self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"))
        self.assertEqual(self.counts(), before)

    def test_flh066_receipt_without_confirmation_is_reread_once_then_cached(self):
        self.deploy()
        self.assertEqual(self.cli("cleanup")[0], 0)
        r = self.res()
        r["stack"].pop("deletion_confirmation")  # what an FLH-066 cleanup wrote
        self.write_res(r)
        before = self.counts().get("cfn.DescribeStacks", 0)
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"), err)
        self.assertEqual(self.counts()["cfn.DescribeStacks"], before + 1)
        self.assertEqual(self.counts()["cfn.DeleteStack"], 1)
        snapshot = self.counts()
        self.assertEqual(self.cli("cleanup")[0], 0)
        self.assertEqual(self.counts(), snapshot)


class OwnershipTests(Case):
    def set_cloud_tags(self, tags):
        p = self.cloud_record()
        rec = json.loads(p.read_text())
        rec["Tags"] = tags
        p.write_text(json.dumps(rec))

    def test_foreign_or_missing_observed_tags_refuse_every_delete(self):
        self.deploy()
        demo, _ = make_demo(self.t)
        _, snap, _ = self.cli("snapshot", "--source-demo", demo)
        self.assertEqual(self.cli("upload", "--run", snap["run_id"])[0], 0)
        good = json.loads(self.cloud_record().read_text())["Tags"]
        for tags in ([{"Key": "flh:task", "Value": "FLH-063"}, {"Key": "flh:state-id", "Value": "another"}],
                     [{"Key": "flh:task", "Value": "other"}, {"Key": "flh:state-id", "Value": self.res()["state_id"]}],
                     []):
            with self.subTest(tags=tags):
                self.set_cloud_tags(tags)
                code, cl, err = self.cli("cleanup")
                self.assertEqual((code, cl["cleanup_state"]), (1, "ownership_refused"), err)
                self.assertEqual(self.counts().get("cfn.DeleteStack", 0), 0)
                self.assertEqual(self.counts().get("s3.DeleteObject", 0), 0)
                self.assertEqual(self.counts().get("s3.HeadObject", 0), 0)
                self.assertEqual(len(self.res()["objects"]), 2)
                self.assertEqual(self.cli("recover")[0], 1)
        self.set_cloud_tags(good)  # ownership proven again: the normal cleanup proceeds
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"), err)
        self.assertNotIn("ownership_refused", self.res()["stack"])

    def test_answer_for_a_different_stack_id_is_not_recorded(self):
        self.deploy()
        rec = json.loads(self.cloud_record().read_text())
        recorded = self.res()["stack"]["id"]
        real = fakes.FakeCloudFormation.describe_stacks

        def other_id(this, StackName):
            out = real(this, StackName)
            out["Stacks"][0]["StackId"] = recorded[:-1] + ("1" if recorded[-1] != "1" else "2")
            return out

        from unittest import mock
        with mock.patch.object(fakes.FakeCloudFormation, "describe_stacks", other_id):
            code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (1, "ownership_refused"), err)
        self.assertEqual(self.counts().get("cfn.DeleteStack", 0), 0)
        self.assertEqual(json.loads(self.cloud_record().read_text())["StackStatus"], rec["StackStatus"])

    def test_legacy_adoption_by_name_still_works_without_new_permissions(self):
        self.deploy()
        r = self.res()
        r.pop("schema")
        r["stack"] = {"name": r["stack"]["name"], "status": "CREATE_COMPLETE"}
        self.write_res(r)
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"), err)
        self.assertEqual(self.res()["stack"]["id_source"], "describe_stacks_by_name")


class TitanBindingTests(Case):
    def inputs(self, text="Bonjour, texte synthétique.", ident="same-id"):
        p = self.t / "inputs.json"
        p.write_text(json.dumps({"data_classification": "synthetic", "inputs": [{"id": ident, "text": text}]}))
        return p

    def smoke(self, inputs, *extra, region="ca-central-1", dims="256"):
        return self.cli("titan-smoke", "--region", region, "--dimensions", dims, "--inputs", inputs, *extra)

    def invokes(self):
        return self.counts().get("bedrock.InvokeModel", 0)

    def test_records_carry_the_full_binding(self):
        p = self.inputs()
        self.assertEqual(self.smoke(p)[0], 0)
        d = Ledger(self.state).read()["calls"][0]["detail"]
        want = titan.request_binding("ca-central-1", 256, "Bonjour, texte synthétique.")
        self.assertEqual({k: d[k] for k in titan.BINDING_KEYS}, want)
        self.assertEqual(d["identity"], titan.identity("ca-central-1", 256))

    def test_unchanged_continuation_sends_nothing(self):
        p = self.inputs()
        self.assertEqual(self.smoke(p)[0], 0)
        for _ in range(2):
            code, out, err = self.smoke(p, "--only-missing")
            self.assertEqual((code, out["planned_calls"], out["skipped_already_ok"]), (0, 0, ["same-id"]), err)
        self.assertEqual(self.invokes(), 1)

    def test_any_identity_change_is_not_reused(self):
        p = self.inputs()
        self.assertEqual(self.smoke(p)[0], 0)
        variants = [("text", lambda: (self.inputs("Changed synthetic text."), {})),
                    ("region", lambda: (self.inputs(), {"region": "us-east-1"})),
                    ("dimensions", lambda: (self.inputs(), {"dims": "512"}))]
        n = 1
        for name, make in variants:
            with self.subTest(name):
                path, kw = make()
                code, out, err = self.smoke(path, "--only-missing", **kw)
                n += 1
                self.assertEqual((code, out["planned_calls"], out["skipped_already_ok"]), (0, 1, []), err)
                self.assertEqual(out["not_reused"][0]["reason"],
                                 "different_text_model_region_dimensions_or_convention")
                self.assertEqual(self.invokes(), n)
        for field, value in (("model", "unrelated-model"), ("text_convention", "e5_prefix"), ("normalize", False),
                             ("request_sha256", "0" * 64)):
            with self.subTest(field):
                led = Ledger(self.state).read()
                for c in led["calls"]:
                    c["detail"][field] = value
                (self.state / "ledger.json").write_text(json.dumps(led))
                code, out, err = self.smoke(self.inputs(), "--only-missing")
                n += 1
                self.assertEqual((code, out["planned_calls"]), (0, 1), err)
                self.assertEqual(self.invokes(), n)

    def test_legacy_unbound_success_does_not_qualify_and_stays_charged(self):
        p = self.inputs()
        self.assertEqual(self.smoke(p)[0], 0)
        led = Ledger(self.state).read()
        led["calls"][0]["detail"] = {"label": "same-id", "model": titan.MODEL_ID, "dimensions": 256}  # FLH-066 shape
        (self.state / "ledger.json").write_text(json.dumps(led))
        code, out, err = self.smoke(p, "--only-missing")
        self.assertEqual((code, out["planned_calls"]), (0, 1), err)
        self.assertEqual(out["not_reused"], [{"input": "same-id", "reason": "legacy_unbound_record"}])
        self.assertEqual(out["ledger_history_before"]["ok_unbound_legacy"], 1)
        led = Ledger(self.state).read()
        self.assertEqual(led["used"]["bedrock_invocations"], 2)
        self.assertEqual(led["caps"]["bedrock_invocations"], 10)
        self.assertEqual(self.invokes(), 2)

    def test_failed_bound_attempt_is_not_success(self):
        (self.fake / "faults.json").write_text(json.dumps({"invoke_fail": {"after": 0, "code": "ThrottlingException"}}))
        p = self.inputs()
        self.assertEqual(self.smoke(p)[0], 1)
        (self.fake / "faults.json").write_text("{}")
        code, out, _ = self.smoke(p, "--only-missing")
        self.assertEqual((code, out["planned_calls"], out["not_reused"]), (0, 1, []))
        self.assertEqual(Ledger(self.state).read()["used"]["bedrock_invocations"], 2)


if __name__ == "__main__":
    unittest.main()
