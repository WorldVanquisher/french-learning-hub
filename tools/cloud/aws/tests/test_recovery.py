"""FLH-066: receipts, honest cleanup states, interrupted operations and Titan
diagnostics, against the filesystem fakes (standard library only, no network)."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from helpers import TempDir, make_demo, run_cli

from flh_aws import diagnostics, fakes, s3store
from flh_aws.ledger import Ledger

FLH064_VERIFICATION_MESSAGE = (
    "Your account is currently being verified. Verification normally takes less than 2 hours. Until your account "
    "is verified, you may not have access to this operation. If you are still receiving this error after 2 hours, "
    "contact AWS Support.")


class StateCase(unittest.TestCase):
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

    def faults(self, d):
        (self.fake / "faults.json").write_text(json.dumps(d))

    def res(self) -> dict:
        return json.loads((self.state / "resources.json").read_text())

    def write_res(self, r: dict) -> None:
        (self.state / "resources.json").write_text(json.dumps(r))

    def n(self, name) -> int:
        return fakes.counters(self.fake).get(name, 0)

    def deploy_ok(self):
        code, out, err = self.cli("deploy", "--region", "ca-central-1")
        self.assertEqual(code, 0, err)
        return out


class ReceiptTests(StateCase):
    def test_full_stack_id_is_persisted_and_used(self):
        out = self.deploy_ok()
        st = self.res()["stack"]
        self.assertRegex(st["id"], r"^arn:aws:cloudformation:ca-central-1:000000000000:stack/flh063-[0-9a-f]{12}/")
        self.assertEqual(st["id_source"], "create_stack_response")
        self.assertEqual(st["observed_by"], "describe_stacks_by_id")
        self.assertEqual(st["client_request_token"], f"{st['name']}-create")
        self.assertEqual(st["tags"], {"flh:task": "FLH-063", "flh:state-id": self.res()["state_id"]})
        self.assertEqual(self.res()["schema"], "flh066_resources_v2")
        self.assertIn("<account>", out["stack_id"])  # printed copies mask the account id
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"), err)
        # A deleted stack is invisible by name but still readable by its StackId.
        cfn = fakes.fake_clients(self.fake, "ca-central-1").cfn
        self.assertIsNone(s3store.describe_stack(cfn, st["name"]))
        self.assertEqual(s3store.describe_stack(cfn, st["id"])["StackStatus"], "DELETE_COMPLETE")

    def test_repeated_cleanup_after_confirmation_sends_nothing(self):
        self.deploy_ok()
        self.assertEqual(self.cli("cleanup")[0], 0)
        before = fakes.counters(self.fake)
        code, cl, _ = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"))
        self.assertEqual(fakes.counters(self.fake), before)

    def test_failed_creation_with_on_failure_delete_is_confirmed_by_stack_id(self):
        self.faults({"create_stack_fail": True})
        code, _, err = self.cli("deploy", "--region", "ca-central-1")
        self.assertEqual(code, 1, err)
        self.assertEqual(self.res()["stack"]["status"], "DELETE_COMPLETE")
        self.faults({})
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"), err)
        self.assertEqual(self.n("cfn.DeleteStack"), 0)


class LegacyStateTests(StateCase):
    """FLH-063/064 records: no schema, no StackId."""

    def legacy(self, status: str):
        r = self.res()
        r.pop("schema", None)
        r["stack"] = {"name": r["stack"]["name"], "status": status}
        self.write_res(r)
        return r

    def test_flh064_shaped_deleted_record_is_never_reported_as_confirmed(self):
        self.deploy_ok()
        stack_id = self.res()["stack"]["id"]
        self.assertEqual(self.cli("cleanup")[0], 0)
        self.legacy("DELETED")  # exactly what FLH-064's resources.json holds
        code, cl, err = self.cli("cleanup")
        self.assertEqual(code, 4, err)
        self.assertEqual(cl["cleanup_state"], "verification_unavailable")
        self.assertEqual(cl["stack"]["bucket_probe"], "absent")
        self.assertIn("cannot be verified", cl["stack"]["reason"])
        self.assertTrue(any("--stack-id" in s for s in cl["operator_steps"]))
        code, st, _ = self.cli("status")
        self.assertEqual(st["stack"]["state"], "verification_unavailable")
        # The operator supplies the StackId from the console or CloudTrail; it is checked, then read.
        wrong = stack_id.replace("000000000000", "111111111111")
        self.assertEqual(self.cli("recover", "--stack-id", wrong)[0], 1)
        self.assertNotIn("id", self.res()["stack"])
        code, rec, err = self.cli("recover", "--stack-id", stack_id)
        self.assertEqual((code, rec["stack"]["state"]), (0, "deletion_confirmed"), err)
        self.assertEqual(self.res()["stack"]["id_source"], "operator")

    def test_legacy_live_record_adopts_the_stack_id_by_name_then_cleans_up(self):
        self.deploy_ok()
        self.legacy("CREATE_COMPLETE")
        demo, _ = make_demo(self.t)
        code, snap, err = self.cli("snapshot", "--source-demo", demo)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.cli("upload", "--run", snap["run_id"])[0], 0)  # old record still usable
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"), err)
        self.assertEqual(self.res()["stack"]["id_source"], "describe_stacks_by_name")
        self.assertEqual(len(cl["objects_deleted"]), 2)

    def test_stack_with_foreign_tags_is_not_adopted(self):
        self.deploy_ok()
        self.legacy("CREATING")
        p = next((self.fake / "cfn").glob("*.json"))
        rec = json.loads(p.read_text())
        rec["Tags"] = [{"Key": "flh:task", "Value": "FLH-063"}, {"Key": "flh:state-id", "Value": "someone-else"}]
        p.write_text(json.dumps(rec))
        code, _, err = self.cli("recover")
        self.assertEqual(code, 1)
        self.assertIn("not adopted", err)
        self.assertNotIn("id", self.res()["stack"])
        self.assertEqual(self.n("cfn.DeleteStack"), 0)


class InterruptedDeployTests(StateCase):
    def test_create_response_lost_is_never_resent_and_recover_adopts_the_stack(self):
        self.faults({"create_stack": "lost"})
        code, _, err = self.cli("deploy", "--region", "ca-central-1")
        self.assertEqual(code, 4, err)
        self.assertIn("not resent", err)
        self.assertEqual(self.res()["stack"]["status"], "CREATE_UNKNOWN")
        self.assertEqual(self.res()["stack"]["create_error"]["category"], "transport")
        self.faults({})
        self.assertEqual(self.cli("deploy", "--region", "ca-central-1")[0], 2)  # refused, nothing sent
        self.assertEqual(self.n("cfn.CreateStack"), 1)
        self.assertEqual(len(list((self.fake / "cfn").glob("*.json"))), 1)  # no replacement stack
        code, rec, err = self.cli("recover")
        self.assertEqual((code, rec["stack"]["state"]), (0, "resources_present"), err)
        self.assertEqual(self.res()["stack"]["status"], "CREATE_COMPLETE")
        self.assertEqual(self.cli("verify-bucket")[0], 0)
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"), err)
        self.assertEqual(self.n("cfn.CreateStack"), 1)

    def test_create_unreachable_then_nothing_found_stays_unverified(self):
        self.faults({"create_stack": "unreachable"})
        self.assertEqual(self.cli("deploy", "--region", "ca-central-1")[0], 4)
        self.faults({})
        code, rec, _ = self.cli("recover")
        self.assertEqual(code, 4)
        self.assertEqual(rec["stack"]["state"], "verification_unavailable")
        self.assertEqual(rec["stack"]["bucket_probe"], "absent")
        self.assertEqual(self.n("cfn.CreateStack"), 1)
        code, cl, _ = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (4, "verification_unavailable"))
        self.assertEqual(self.n("cfn.DeleteStack"), 0)

    def test_create_rejected_is_not_created_and_may_be_redeployed_in_the_same_state(self):
        self.faults({"create_stack": {"code": "AccessDenied", "status": 403,
                                      "message": "User: arn:aws:iam::123456789012:user/x is not authorized to "
                                                 "perform: cloudformation:CreateStack"}})
        code, _, err = self.cli("deploy", "--region", "ca-central-1")
        self.assertEqual(code, 1, err)
        self.assertIn("iam_denied", err)
        self.assertNotIn("123456789012", err)
        self.assertEqual(self.res()["stack"]["status"], "CREATE_REJECTED")
        code, cl, _ = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "not_created"))
        self.faults({})
        self.deploy_ok()
        self.assertEqual(len(self.res()["history"]), 1)
        self.assertEqual(self.res()["history"][0]["stack"]["status"], "CREATE_REJECTED")

    def test_crash_before_the_stack_id_was_saved_is_recovered_by_name(self):
        real_save, calls = s3store.save_resources, []

        def dying_save(state, res):
            calls.append(res["stack"]["status"])
            if res["stack"].get("id"):  # the process dies right after CreateStack returned
                raise KeyboardInterrupt
            real_save(state, res)

        c = fakes.fake_clients(self.fake, "ca-central-1")
        with mock.patch.object(s3store, "save_resources", dying_save):
            with self.assertRaises(KeyboardInterrupt):
                s3store.deploy(self.state, c, "ca-central-1", 7, "fake", sleep=lambda s: None)
        self.assertEqual(self.res()["stack"]["status"], "CREATE_REQUESTING")
        self.assertNotIn("id", self.res()["stack"])
        self.assertEqual(self.cli("status")[1]["stack"]["state"], "verification_unavailable")
        code, rec, err = self.cli("recover")
        self.assertEqual((code, rec["stack"]["state"]), (0, "resources_present"), err)
        self.assertEqual(self.n("cfn.CreateStack"), 1)

    def test_describe_denied_while_waiting_leaves_the_outcome_unknown(self):
        real = fakes.FakeCloudFormation.create_stack

        def create_then_deny(this, **kw):
            out = real(this, **kw)
            self.faults({"describe_stacks": {"code": "AccessDenied", "status": 403, "message": "denied"}})
            return out

        with mock.patch.object(fakes.FakeCloudFormation, "create_stack", create_then_deny):
            code, _, err = self.cli("deploy", "--region", "ca-central-1")
        self.assertEqual(code, 4, err)
        st = self.res()["stack"]
        self.assertTrue(st["id"])  # the receipt was saved before the wait
        self.assertEqual(st["last_observation_error"]["category"], "unknown")
        self.faults({})
        code, rec, _ = self.cli("recover")
        self.assertEqual((code, rec["stack"]["status"]), (0, "CREATE_COMPLETE"))


class InterruptedCleanupTests(StateCase):
    def test_describe_access_denied_is_not_deletion(self):
        self.deploy_ok()
        self.faults({"describe_stacks": {"code": "AccessDenied", "status": 403, "message": "not authorized"}})
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (4, "verification_unavailable"), err)
        self.assertEqual(self.n("cfn.DeleteStack"), 0)
        self.assertEqual(self.res()["stack"]["status"], "CREATE_COMPLETE")

    def test_delete_stack_response_lost_is_confirmed_later_without_resending(self):
        self.deploy_ok()
        self.faults({"delete_stack": "lost"})
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (4, "deletion_requested"), err)
        self.assertEqual(self.res()["stack"]["delete_attempts"][0]["outcome"], "unknown")
        self.faults({})
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"), err)
        self.assertEqual(self.n("cfn.DeleteStack"), 1)  # observed DELETE_COMPLETE by StackId; not resent

    def test_delete_stack_never_arrived_is_resent_only_after_observing_the_stack(self):
        self.deploy_ok()
        self.faults({"delete_stack": "unreachable"})
        self.assertEqual(self.cli("cleanup")[0], 4)
        self.faults({})
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"), err)
        attempts = self.res()["stack"]["delete_attempts"]
        self.assertEqual([a["from_status"] for a in attempts], ["CREATE_COMPLETE", "CREATE_COMPLETE"])
        self.assertEqual([a["token"].rsplit("-", 1)[-1] for a in attempts], ["delete", "2"])
        self.assertEqual(self.n("cfn.DeleteStack"), 2)

    def test_delete_stack_access_denied_reports_resources_present(self):
        self.deploy_ok()
        self.faults({"delete_stack": {"code": "AccessDenied", "status": 403, "message": "not authorized"}})
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (1, "resources_present"), err)
        self.assertEqual(self.res()["stack"]["status"], "CREATE_COMPLETE")
        self.assertEqual(self.res()["stack"]["delete_attempts"][0]["outcome"], "rejected")

    def test_delete_object_response_lost_then_rerun(self):
        self.deploy_ok()
        demo, _ = make_demo(self.t)
        _, snap, _ = self.cli("snapshot", "--source-demo", demo)
        self.assertEqual(self.cli("upload", "--run", snap["run_id"])[0], 0)
        self.faults({"delete_object": "lost"})
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (4, "verification_unavailable"), err)
        self.assertEqual(len(self.res()["objects"]), 2)  # not proven gone: still recorded
        self.assertEqual(self.n("cfn.DeleteStack"), 0)
        self.faults({})
        code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"), err)
        self.assertEqual([o["result"] for o in cl["objects_deleted"]], ["already absent", "deleted"])
        led = Ledger(self.state).read()
        self.assertEqual([c["outcome"] for c in led["calls"] if c["kind"] == "s3_delete_object"],
                         ["failed", "ok"])

    def test_slow_deletion_is_waited_for_by_stack_id(self):
        self.deploy_ok()
        self.faults({"delete_in_progress_polls": 2})
        with mock.patch.object(s3store, "STACK_POLL_SECONDS", 0):
            code, cl, err = self.cli("cleanup")
        self.assertEqual((code, cl["cleanup_state"]), (0, "deletion_confirmed"), err)


class TitanDiagnosticsTests(StateCase):
    def smoke(self, *extra):
        return self.cli("titan-smoke", "--region", "ca-central-1", "--dimensions", "512", *extra)

    def test_account_verification_then_targeted_rerun_with_the_same_ledger(self):
        self.faults({"invoke_fail": {"code": "AccessDeniedException", "status": 403,
                                     "message": FLH064_VERIFICATION_MESSAGE}})
        code, _, err = self.smoke()
        self.assertEqual(code, 1)
        self.assertIn("account_verification_pending", err)
        ev = json.loads(sorted((self.state / "evidence").glob("titan-smoke-*.json"))[-1].read_text())
        self.assertEqual(ev["error"]["category"], "account_verification_pending")
        self.assertIn("contact AWS Support", ev["error"]["message"])
        led = Ledger(self.state).read()
        self.assertEqual(led["used"]["bedrock_invocations"], 1)  # the failed attempt stays charged
        self.assertEqual(led["calls"][-1]["result"]["error_category"], "account_verification_pending")
        # Verification done: rerun only the smoke, same state and ledger.
        self.faults({})
        code, out, err = self.smoke("--only-missing")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["completed_calls"], 6)
        self.assertEqual(out["ledger_history_before"]["failed_by_category"], {"account_verification_pending": 1})
        self.assertEqual(Ledger(self.state).read()["used"]["bedrock_invocations"], 7)
        self.assertEqual(Ledger(self.state).remaining()["bedrock_invocations"], 3)
        # Nothing left to embed: no call. A plain full rerun needs 6 > 3: refused before sending.
        code, out, _ = self.smoke("--only-missing")
        self.assertEqual((code, out["completed_calls"], len(out["skipped_already_ok"])), (0, 0, 6))
        self.assertEqual(self.smoke()[0], 2)
        self.assertEqual(self.n("bedrock.InvokeModel"), 7)
        self.assertEqual(Ledger(self.state).read()["caps"]["bedrock_invocations"], 10)  # never raised
        self.assertFalse((self.fake / "cfn").exists())  # no deployment was needed

    def test_partial_failure_continues_only_with_the_missing_inputs(self):
        self.faults({"invoke_fail": {"after": 2, "code": "ThrottlingException", "status": 429}})
        code, _, err = self.smoke()
        self.assertEqual(code, 1)
        self.assertIn("throttling", err)
        self.faults({})
        code, out, err = self.smoke("--only-missing")
        self.assertEqual(code, 0, err)
        self.assertEqual((out["planned_calls"], len(out["skipped_already_ok"])), (4, 2))
        self.assertEqual(self.n("bedrock.InvokeModel"), 7)  # 3 + 4: the throttled one was redone once, by hand

    def test_categories(self):
        cases = [
            ({"code": "AccessDeniedException", "status": 403, "message": FLH064_VERIFICATION_MESSAGE},
             "account_verification_pending", False),
            ({"code": "AccessDeniedException", "status": 403, "message": "User: arn:aws:iam::123456789012:user/x is "
              "not authorized to perform: bedrock:InvokeModel because no identity-based policy allows it"},
             "iam_denied", False),
            ({"code": "AccessDeniedException", "status": 403,
              "message": "You don't have access to the model with the specified model ID."}, "model_access_denied",
             False),
            ({"code": "AccessDeniedException", "status": 403, "message": "Access denied."}, "unknown", False),
            ({"code": "ExpiredTokenException", "status": 403, "message": "The security token included in the "
              "request is expired"}, "expired_credentials", False),
            ({"code": "UnrecognizedClientException", "status": 403, "message": "invalid token"},
             "expired_credentials", False),
            ({"code": "ThrottlingException", "status": 429, "message": "Too many requests"}, "throttling", False),
            ({"code": "SomethingNew", "status": 400, "message": "?"}, "unknown", False),
            ({"code": "InternalServerException", "status": 500, "message": "oops"}, "service_unavailable", None),
            ({"transport": "lost"}, "transport", True),
            ({"transport": "unreachable"}, "transport", False),
        ]
        for spec, category, processed in cases:
            with self.subTest(category=category, spec=spec):
                st = self.t / f"s-{len(list(self.t.iterdir()))}"
                run_cli("init", "--state", st, "--backend", "fake")
                (st / "fake-aws").mkdir()
                (st / "fake-aws" / "faults.json").write_text(json.dumps({"invoke_fail": spec}))
                code, _, err = run_cli("titan-smoke", "--state", st, "--region", "ca-central-1", "--dimensions", "256")
                self.assertEqual(code, 1)
                ev = json.loads(sorted((st / "evidence").glob("titan-smoke-*.json"))[-1].read_text())
                self.assertEqual(ev["error"]["category"], category)
                self.assertEqual(ev["error"]["may_have_been_processed"], processed)
                self.assertNotIn("123456789012", json.dumps(ev) + err)
                call = Ledger(st).read()["calls"][-1]
                self.assertEqual((call["outcome"], call["result"]["error_category"]), ("failed", category))
                self.assertEqual(Ledger(st).read()["used"]["bedrock_invocations"], 1)


class DiagnosticsUnitTests(unittest.TestCase):
    def named(self, name):
        return type(name, (Exception,), {})("x")

    def test_credential_classes(self):
        for name, cat in [("MissingDependencyException", "missing_dependency"), ("ProfileNotFound", "profile_not_found"),
                          ("NoCredentialsError", "no_credentials"), ("LoginRefreshRequired", "expired_credentials"),
                          ("LoginTokenLoadError", "expired_credentials"),
                          ("UnauthorizedSSOTokenError", "expired_credentials"),
                          ("LoginInsufficientPermissions", "iam_denied"), ("ReadTimeoutError", "transport"),
                          ("SomeBrandNewError", "unknown")]:
            with self.subTest(name=name):
                self.assertEqual(diagnostics.classify(self.named(name))["category"], cat)

    def test_sanitize_masks_and_bounds(self):
        s = diagnostics.sanitize("acct 123456789012 key AKIAABCDEFGHIJKLMNOP " + "x" * 500)
        self.assertNotIn("123456789012", s)
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", s)
        self.assertLessEqual(len(s), diagnostics.MAX_MESSAGE_CHARS + 3)

    def test_definite_rejection(self):
        e = fakes.FakeClientError("AccessDenied", "no", 403)
        self.assertTrue(diagnostics.is_definite_rejection(e))
        self.assertFalse(diagnostics.is_definite_rejection(fakes.FakeClientError("AlreadyExistsException", "x", 400)))
        self.assertFalse(diagnostics.is_definite_rejection(fakes.FakeClientError("InternalFailure", "x", 500)))
        self.assertFalse(diagnostics.is_definite_rejection(fakes.ReadTimeoutError("x")))


class AuthCheckTests(StateCase):
    def test_auth_check_on_the_fake_backend_prints_no_account(self):
        code, out, err = self.cli("auth-check", "--region", "ca-central-1")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["account_last4"], "0000")
        self.assertNotIn("000000000000", json.dumps(out))

    def test_live_backend_without_profile_is_refused_before_anything(self):
        st = self.t / "live"
        run_cli("init", "--state", st, "--backend", "aws")
        for cmd in (["deploy", "--region", "ca-central-1", "--allow-live"], ["auth-check", "--region", "ca-central-1"]):
            self.assertEqual(run_cli(cmd[0], "--state", st, *cmd[1:])[0], 2)
        self.assertEqual(Ledger(st).read()["calls"], [])
        self.assertFalse((st / "resources.json").exists())


if __name__ == "__main__":
    unittest.main()
