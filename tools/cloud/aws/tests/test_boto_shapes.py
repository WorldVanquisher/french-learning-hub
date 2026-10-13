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
from types import SimpleNamespace

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
from flh_aws.s3store import TEMPLATE, cleanup, deploy, upload
from flh_aws.snapshot import MANIFEST_NAME, SNAPSHOT_NAME, make_package

REGION, ACCOUNT = "ca-central-1", "111122223333"


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
                # deploy
                sts_s.add_response("get_caller_identity", {"Account": ACCOUNT, "Arn": "arn:aws:iam::111122223333:user/x",
                                                           "UserId": "AIDAEXAMPLE"}, {})
                cfs.add_response("create_stack", {"StackId": "arn:aws:cloudformation:ca-central-1:111122223333:stack/x/y"},
                                 {"StackName": ANY, "TemplateBody": TEMPLATE.read_text(), "Parameters": ANY,
                                  "Tags": ANY, "OnFailure": "DELETE", "TimeoutInMinutes": 10,
                                  "ClientRequestToken": ANY})
                cfs.add_response("describe_stacks", {"Stacks": [{"StackName": "x", "CreationTime": "2026-10-13T00:00:00Z",
                                                                 "StackStatus": "CREATE_COMPLETE"}]}, {"StackName": ANY})
                # the bucket name is random: read it from state once deploy has recorded it
                orig = deploy.__globals__["verify_bucket"]

                def stub_then_verify(state_, clients_, backend_):
                    res = json.loads((state / "resources.json").read_text())
                    self.bucket_reads(s3s, res["bucket"], res["state_id"])
                    return orig(state_, clients_, backend_)

                deploy.__globals__["verify_bucket"] = stub_then_verify
                try:
                    deploy(state, c, REGION, 7, "aws", sleep=lambda s: None)
                finally:
                    deploy.__globals__["verify_bucket"] = orig
                res = json.loads((state / "resources.json").read_text())
                bucket, sid = res["bucket"], res["state_id"]

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

                # cleanup
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
                cfs.add_response("delete_stack", {}, {"StackName": bucket, "ClientRequestToken": f"{bucket}-delete"})
                cfs.add_client_error("describe_stacks", "ValidationError", f"Stack with id {bucket} does not exist",
                                     expected_params={"StackName": bucket})
                out = cleanup(state, c, "aws", sleep=lambda s: None)
                self.assertEqual(out["stack"], "DELETED")
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


if __name__ == "__main__":
    unittest.main()
