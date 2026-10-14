"""Request-shape tests against the pinned botocore service models (no network).

botocore's Stubber validates every request's parameter names and types, and
every stubbed response, against the real AWS API models. Skipped when boto3 is
not installed. AWS_CONFIG_FILE/AWS_SHARED_CREDENTIALS_FILE point at missing
files, and fixed placeholder credentials are used, so no local AWS
configuration is read and nothing can be signed for a real account.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from helpers import TempDir, make_demo

try:
    import boto3
    from botocore.config import Config
    from botocore.response import StreamingBody
    from botocore.stub import ANY, Stubber
except ImportError:  # pragma: no cover
    boto3 = None

from flh_aws import titan
from flh_aws.ledger import Ledger
from flh_aws.restore import restore_from_s3
from flh_aws.awsclients import aws_clients
from flh_aws.s3store import TEMPLATE, cleanup, deploy, recover, upload
from flh_aws.snapshot import Refused
from flh_aws.snapshot import MANIFEST_NAME, SNAPSHOT_NAME, make_package

REGION, ACCOUNT = "ca-central-1", "111122223333"
SID, STACK_UUID = "0123456789ab", "8d1c2f1e-6a6b-4c1e-9a7a-2f0e5b8c9d10"


def streaming(data: bytes) -> "StreamingBody":
    return StreamingBody(io.BytesIO(data), len(data))


@unittest.skipIf(boto3 is None, "boto3 not installed")
class BotoShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = {k: os.environ.get(k) for k in ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE", "AWS_PROFILE")}
        os.environ["AWS_CONFIG_FILE"] = "/nonexistent/flh063-config"
        os.environ["AWS_SHARED_CREDENTIALS_FILE"] = "/nonexistent/flh063-credentials"
        os.environ.pop("AWS_PROFILE", None)

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def client(self, name):
        s = boto3.session.Session(aws_access_key_id="AKIAFLH063PLACEHOLDER", aws_secret_access_key="placeholder",
                                  region_name=REGION)
        return s.client(name, config=Config(retries={"total_max_attempts": 1, "mode": "standard"}))

    def bucket_reads(self, stub: "Stubber", bucket: str, state_id: str):
        kw = {"Bucket": bucket, "ExpectedBucketOwner": ACCOUNT}
        policy = json.loads(TEMPLATE.read_text())["Resources"]["BucketPolicy"]["Properties"]["PolicyDocument"]
        stub.add_response("get_bucket_location", {"LocationConstraint": REGION}, kw)
        stub.add_response("get_public_access_block", {"PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True}}, kw)
        stub.add_response("get_bucket_encryption", {"ServerSideEncryptionConfiguration": {"Rules": [
            {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}, "BucketKeyEnabled": False}]}}, kw)
        stub.add_response("get_bucket_policy", {"Policy": json.dumps(policy)}, kw)
        stub.add_response("get_bucket_lifecycle_configuration", {"Rules": [
            {"ID": "flh063-expire-all", "Status": "Enabled", "Filter": {"Prefix": ""}, "Expiration": {"Days": 7},
             "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1}}]}, kw)
        stub.add_response("get_bucket_ownership_controls", {"OwnershipControls": {"Rules": [
            {"ObjectOwnership": "BucketOwnerEnforced"}]}}, kw)
        stub.add_response("get_bucket_versioning", {}, kw)
        stub.add_response("get_bucket_tagging", {"TagSet": [{"Key": "flh:task", "Value": "FLH-063"},
                                                             {"Key": "flh:state-id", "Value": state_id}]}, kw)

    def test_backup_workflow_requests_match_the_aws_models(self):
        with TempDir() as t:
            state = t / "state"
            state.mkdir()
            Ledger(state)
            demo, _ = make_demo(t)
            s3, cfn, sts = self.client("s3"), self.client("cloudformation"), self.client("sts")
            c = SimpleNamespace(s3=s3, cfn=cfn, sts=sts)
            with Stubber(s3) as s3s, Stubber(cfn) as cfs, Stubber(sts) as sts_s:
                # deploy: the full StackId from CreateStack is used for every later read
                sts_s.add_response("get_caller_identity", {"Account": ACCOUNT, "Arn": "arn:aws:iam::111122223333:user/x",
                                                           "UserId": "AIDAEXAMPLE"}, {})
                bucket = f"flh063-{SID}"
                stack_id = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{bucket}/{STACK_UUID}"
                cfs.add_response("create_stack", {"StackId": stack_id},
                                 {"StackName": bucket, "TemplateBody": TEMPLATE.read_text(), "Parameters": ANY,
                                  "Tags": ANY, "OnFailure": "DELETE", "TimeoutInMinutes": 10,
                                  "ClientRequestToken": f"{bucket}-create"})
                cfs.add_response("describe_stacks", {"Stacks": [{
                    "StackName": bucket, "StackId": stack_id, "CreationTime": "2026-10-13T00:00:00Z",
                    "StackStatus": "CREATE_COMPLETE"}]}, {"StackName": stack_id})
                self.bucket_reads(s3s, bucket, SID)
                with mock.patch("flh_aws.s3store.secrets.token_hex", return_value=SID):
                    deploy(state, c, REGION, 7, "aws", sleep=lambda s: None)
                res = json.loads((state / "resources.json").read_text())
                self.assertEqual(res["stack"]["id"], stack_id)
                sid = res["state_id"]

                # upload
                out = make_package(demo, t / "pkg", "run1")
                self.bucket_reads(s3s, bucket, sid)
                for name in (SNAPSHOT_NAME, MANIFEST_NAME):
                    data = (t / "pkg" / name).read_bytes()
                    s3s.add_response("put_object", {"ETag": f'"{name}"', "ServerSideEncryption": "AES256"}, {
                        "Bucket": bucket, "Key": f"flh063/run1/{name}", "Body": data, "IfNoneMatch": "*",
                        "ServerSideEncryption": "AES256",
                        "ChecksumSHA256": base64.b64encode(hashlib.sha256(data).digest()).decode(),
                        "ExpectedBucketOwner": ACCOUNT, "ContentType": "application/octet-stream",
                        "Metadata": {"flh-task": "FLH-063", "flh-run": "run1",
                                     "flh-sha256": hashlib.sha256(data).hexdigest()}})
                upload(state, c, t / "pkg", "run1", out["manifest_sha256"], "aws")

                # restore
                for name in (SNAPSHOT_NAME, MANIFEST_NAME):
                    data = (t / "pkg" / name).read_bytes()
                    s3s.add_response("get_object", {"Body": streaming(data), "ETag": f'"{name}"'},
                                     {"Bucket": bucket, "Key": f"flh063/run1/{name}", "ExpectedBucketOwner": ACCOUNT,
                                      "ChecksumMode": "ENABLED"})
                rec = restore_from_s3(state, c, "run1", t / "restored", None, "aws")
                self.assertEqual(rec["checks"]["integrity"]["integrity_check"], ["ok"])

                # cleanup: read by StackId, owned objects, empty listing, tags, DeleteStack by StackId,
                # DELETE_COMPLETE read by StackId, then NoSuchBucket for the expected owner
                cfs.add_response("describe_stacks", {"Stacks": [{
                    "StackName": bucket, "StackId": stack_id, "CreationTime": "2026-10-13T00:00:00Z",
                    "StackStatus": "CREATE_COMPLETE"}]}, {"StackName": stack_id})
                for name in (SNAPSHOT_NAME, MANIFEST_NAME):
                    key = f"flh063/run1/{name}"
                    s3s.add_response("head_object", {"ETag": f'"{name}"', "Metadata": {"flh-run": "run1"}},
                                     {"Bucket": bucket, "Key": key, "ExpectedBucketOwner": ACCOUNT})
                    s3s.add_response("delete_object", {}, {"Bucket": bucket, "Key": key, "IfMatch": f'"{name}"',
                                                           "ExpectedBucketOwner": ACCOUNT})
                s3s.add_response("list_objects_v2", {"IsTruncated": False, "KeyCount": 0},
                                 {"Bucket": bucket, "ExpectedBucketOwner": ACCOUNT, "MaxKeys": 1000})
                s3s.add_response("get_bucket_tagging", {"TagSet": [{"Key": "flh:task", "Value": "FLH-063"},
                                                                   {"Key": "flh:state-id", "Value": sid}]},
                                 {"Bucket": bucket, "ExpectedBucketOwner": ACCOUNT})
                cfs.add_response("delete_stack", {}, {"StackName": stack_id, "ClientRequestToken": f"{bucket}-delete"})
                cfs.add_response("describe_stacks", {"Stacks": [{
                    "StackName": bucket, "StackId": stack_id, "CreationTime": "2026-10-13T00:00:00Z",
                    "DeletionTime": "2026-10-13T00:05:00Z", "StackStatus": "DELETE_COMPLETE"}]},
                    {"StackName": stack_id})
                s3s.add_client_error("get_bucket_location", "NoSuchBucket", "The specified bucket does not exist",
                                     http_status_code=404, expected_params={"Bucket": bucket,
                                                                            "ExpectedBucketOwner": ACCOUNT})
                out = cleanup(state, c, "aws", sleep=lambda s: None)
                self.assertEqual(out["cleanup_state"], "deletion_confirmed")
                s3s.assert_no_pending_responses()
                cfs.assert_no_pending_responses()

    def test_titan_requests_match_the_bedrock_models(self):
        with TempDir() as t:
            Ledger(t)
            rt, ctl = self.client("bedrock-runtime"), self.client("bedrock")
            vec = [1.0] + [0.0] * 255
            with Stubber(rt) as rs, Stubber(ctl) as cs:
                cs.add_response("get_foundation_model", {"modelDetails": {
                    "modelArn": "arn:aws:bedrock:ca-central-1::foundation-model/amazon.titan-embed-text-v2:0",
                    "modelId": titan.MODEL_ID, "modelLifecycle": {"status": "ACTIVE"},
                    "inferenceTypesSupported": ["ON_DEMAND"], "outputModalities": ["EMBEDDING"]}},
                    {"modelIdentifier": titan.MODEL_ID})
                self.assertEqual(titan.preflight(ctl, REGION)["lifecycle"], "ACTIVE")
                raw = json.dumps({"embedding": vec, "inputTextTokenCount": 4, "embeddingsByType": {"float": vec}}).encode()
                rs.add_response("invoke_model", {"body": streaming(raw), "contentType": "application/json"},
                                {"modelId": titan.MODEL_ID, "body": titan.build_body("je ne fume plus", 256),
                                 "contentType": "application/json", "accept": "application/json"})
                r = titan.invoke(Ledger(t), rt, 256, "je ne fume plus", "aws", "shape")
                self.assertEqual(r["tokens"], 4)
                rs.assert_no_pending_responses()

    def test_recover_adopts_a_tagged_stack_by_name_then_reads_by_stack_id(self):
        with TempDir() as t:
            state = t / "state"
            state.mkdir()
            Ledger(state)
            bucket = f"flh063-{SID}"
            stack_id = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{bucket}/{STACK_UUID}"
            (state / "resources.json").write_text(json.dumps({  # an FLH-063 record: no StackId
                "region": REGION, "account": ACCOUNT, "state_id": SID, "bucket": bucket, "retention_days": 7,
                "stack": {"name": bucket, "status": "CREATING"}, "objects": [], "runs": {}}))
            cfn = self.client("cloudformation")
            live = {"StackName": bucket, "StackId": stack_id, "CreationTime": "2026-10-13T00:00:00Z",
                    "StackStatus": "CREATE_COMPLETE",
                    "Tags": [{"Key": "flh:task", "Value": "FLH-063"}, {"Key": "flh:state-id", "Value": SID}]}
            with Stubber(cfn) as cfs:
                cfs.add_response("describe_stacks", {"Stacks": [live]}, {"StackName": bucket})
                cfs.add_response("describe_stacks", {"Stacks": [live]}, {"StackName": stack_id})
                out = recover(state, SimpleNamespace(cfn=cfn, s3=None), "aws")
                cfs.assert_no_pending_responses()
            self.assertEqual(out["stack"]["state"], "resources_present")
            self.assertEqual(json.loads((state / "resources.json").read_text())["stack"]["id"], stack_id)


@unittest.skipIf(boto3 is None, "boto3 not installed")
class AuthPrerequisiteTests(unittest.TestCase):
    """The real botocore credential chain on a synthetic `aws login` profile (no network).

    AWS_CONFIG_FILE, the shared-credentials file and the login cache all point
    into a temporary directory, so no real AWS configuration or token is read.
    """

    def setUp(self):
        self.td = TempDir()
        t = self.td.__enter__()
        (t / "cache").mkdir()
        (t / "config").write_text("[profile flh-synthetic]\nregion = ca-central-1\n"
                                  "login_session = arn:aws:iam::111122223333:user/synthetic\n")
        keep = ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE", "AWS_LOGIN_CACHE_DIRECTORY", "AWS_PROFILE",
                "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_EC2_METADATA_DISABLED")
        self._env = {k: os.environ.get(k) for k in keep}
        for k in keep:
            os.environ.pop(k, None)
        os.environ.update({"AWS_CONFIG_FILE": str(t / "config"),
                           "AWS_SHARED_CREDENTIALS_FILE": str(t / "no-credentials"),
                           "AWS_LOGIN_CACHE_DIRECTORY": str(t / "cache"), "AWS_EC2_METADATA_DISABLED": "true"})

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.td.__exit__()

    def test_without_awscrt_the_login_profile_is_refused_before_any_client(self):
        import botocore.credentials as bc
        with mock.patch.object(bc, "EC", None):  # what FLH-064's first venv had: awscrt not installed
            with self.assertRaises(Refused) as cm:
                aws_clients("flh-synthetic", REGION)
        msg = str(cm.exception)
        self.assertIn("missing_dependency", msg)
        self.assertIn("MissingDependencyException", msg)
        self.assertIn("requirements.txt", msg)
        self.assertIn("No AWS resource request was sent", msg)

    def test_requirements_pin_awscrt_exactly_as_botocores_crt_extra(self):
        from importlib.metadata import requires, version
        req = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
        pinned = dict(line.split("==") for line in req.splitlines() if "==" in line and not line.startswith("#"))
        extra = [r for r in requires("botocore") if r.startswith("awscrt") and "extra == 'crt'" in r.replace('"', "'")]
        self.assertEqual(pinned["botocore"], version("botocore"))
        self.assertEqual(len(extra), 1)
        self.assertIn(f"=={pinned['awscrt']}", extra[0].replace("(", "").replace(")", "").replace(" ", ""))

    def test_with_the_pinned_awscrt_an_absent_login_session_asks_for_aws_login(self):
        import importlib.util
        if importlib.util.find_spec("awscrt") is None:
            self.fail("awscrt is not installed: this environment was not built from tools/cloud/aws/requirements.txt, "
                      "and an `aws login` profile would fail with MissingDependencyException")
        with self.assertRaises(Refused) as cm:
            aws_clients("flh-synthetic", REGION)
        msg = str(cm.exception)
        self.assertIn("expired_credentials", msg)
        self.assertIn("LoginTokenLoadError", msg)
        self.assertIn("aws login --profile flh-synthetic", msg)
        self.assertNotIn("111122223333", msg)

    def test_unknown_profile_is_refused(self):
        with self.assertRaises(Refused) as cm:
            aws_clients("flh-no-such-profile", REGION)
        self.assertIn("profile_not_found", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
