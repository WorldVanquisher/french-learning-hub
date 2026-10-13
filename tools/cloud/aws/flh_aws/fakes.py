"""Filesystem-backed fakes of the AWS calls this package makes.

They prove plumbing only: request bookkeeping, refusals, verification and
cleanup logic. They enforce the behaviour the real bucket policy and S3
conditional requests promise (SSE header, If-None-Match, If-Match, checksum,
expected owner), and build the bucket from the real CloudFormation template.
They say nothing about AWS availability, IAM evaluation, latency, billing or
Titan's semantic behaviour. Faults are injected through ``<root>/faults.json``.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

FAKE_ACCOUNT = "000000000000"


class FakeClientError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(f"An error occurred ({code}): {message}")
        self.response = {"Error": {"Code": code, "Message": message},
                         "ResponseMetadata": {"HTTPStatusCode": status}}


def _faults(root: Path) -> dict:
    p = root / "faults.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _bump(root: Path, name: str) -> int:
    p = root / "counters.json"
    d = json.loads(p.read_text()) if p.exists() else {}
    d[name] = d.get(name, 0) + 1
    p.write_text(json.dumps(d, indent=2, sort_keys=True))
    return d[name]


def counters(root: Path) -> dict:
    p = Path(root) / "counters.json"
    return json.loads(p.read_text()) if p.exists() else {}


class FakeS3:
    def __init__(self, root: Path, region: str):
        self.root, self.region = Path(root), region

    def _bdir(self, bucket: str) -> Path:
        return self.root / "s3" / bucket

    def _cfg(self, bucket: str, owner: str | None) -> dict:
        d = self._bdir(bucket)
        if not d.is_dir():
            raise FakeClientError("NoSuchBucket", "The specified bucket does not exist", 404)
        cfg = json.loads((d / "config.json").read_text())
        if owner is not None and owner != cfg["owner"]:
            raise FakeClientError("AccessDenied", "Access Denied", 403)
        return cfg

    def _obj(self, bucket: str, key: str) -> Path:
        return self._bdir(bucket) / "objects" / hashlib.sha256(key.encode()).hexdigest()

    # created only by FakeCloudFormation
    def _create_bucket(self, bucket: str, cfg: dict) -> None:
        d = self._bdir(bucket)
        if d.exists():
            raise FakeClientError("BucketAlreadyExists", "bucket exists", 409)
        (d / "objects").mkdir(parents=True)
        (d / "config.json").write_text(json.dumps(cfg, indent=2))

    def _delete_bucket(self, bucket: str) -> None:
        d = self._bdir(bucket)
        if any((d / "objects").glob("*.meta")):
            raise FakeClientError("BucketNotEmpty", "The bucket you tried to delete is not empty", 409)
        shutil.rmtree(d)

    def plant_object(self, bucket: str, key: str, data: bytes) -> None:
        """Test helper: an object written by someone else."""
        p = self._obj(bucket, key)
        p.with_suffix(".bin").write_bytes(data)
        p.with_suffix(".meta").write_text(json.dumps({"Key": key, "ETag": '"planted"', "Metadata": {}}))

    def _get_cfg_item(self, name, Bucket, ExpectedBucketOwner=None):
        _bump(self.root, f"s3.{name}")
        return self._cfg(Bucket, ExpectedBucketOwner)

    def get_bucket_location(self, **kw):
        cfg = self._get_cfg_item("GetBucketLocation", **kw)
        return {"LocationConstraint": None if cfg["region"] == "us-east-1" else cfg["region"]}

    def get_public_access_block(self, **kw):
        return {"PublicAccessBlockConfiguration": self._get_cfg_item("GetPublicAccessBlock", **kw)["pab"]}

    def get_bucket_encryption(self, **kw):
        return {"ServerSideEncryptionConfiguration": self._get_cfg_item("GetBucketEncryption", **kw)["encryption"]}

    def get_bucket_policy(self, **kw):
        return {"Policy": self._get_cfg_item("GetBucketPolicy", **kw)["policy"]}

    def get_bucket_lifecycle_configuration(self, **kw):
        return {"Rules": self._get_cfg_item("GetBucketLifecycleConfiguration", **kw)["lifecycle"]}

    def get_bucket_ownership_controls(self, **kw):
        return {"OwnershipControls": {"Rules": self._get_cfg_item("GetBucketOwnershipControls", **kw)["ownership"]}}

    def get_bucket_versioning(self, **kw):
        return self._get_cfg_item("GetBucketVersioning", **kw).get("versioning", {})

    def get_bucket_tagging(self, **kw):
        return {"TagSet": self._get_cfg_item("GetBucketTagging", **kw)["tags"]}

    def put_object(self, Bucket, Key, Body, ExpectedBucketOwner=None, IfNoneMatch=None,
                   ServerSideEncryption=None, ChecksumSHA256=None, Metadata=None, ContentType=None):
        _bump(self.root, "s3.PutObject")
        self._cfg(Bucket, ExpectedBucketOwner)
        f = _faults(self.root).get("put_object_fail")
        if f and Key.endswith(f.get("key_suffix", "")):
            raise FakeClientError(f.get("code", "InternalError"), "injected failure", 500)
        if ServerSideEncryption != "AES256" or IfNoneMatch is None:
            raise FakeClientError("AccessDenied", "Access Denied (bucket policy)", 403)
        p = self._obj(Bucket, Key)
        if p.with_suffix(".meta").exists():
            raise FakeClientError("PreconditionFailed", "At least one of the pre-conditions you specified did not hold", 412)
        if ChecksumSHA256 is not None and base64.b64encode(hashlib.sha256(Body).digest()).decode() != ChecksumSHA256:
            raise FakeClientError("BadDigest", "checksum mismatch", 400)
        etag = '"' + hashlib.md5(Body).hexdigest() + '"'
        p.with_suffix(".bin").write_bytes(Body)
        p.with_suffix(".meta").write_text(json.dumps({"Key": Key, "ETag": etag, "Metadata": Metadata or {}}))
        return {"ETag": etag, "ServerSideEncryption": "AES256"}

    def _meta(self, Bucket, Key):
        m = self._obj(Bucket, Key).with_suffix(".meta")
        if not m.exists():
            raise FakeClientError("404", "Not Found", 404)
        return json.loads(m.read_text())

    def head_object(self, Bucket, Key, ExpectedBucketOwner=None):
        _bump(self.root, "s3.HeadObject")
        self._cfg(Bucket, ExpectedBucketOwner)
        meta = self._meta(Bucket, Key)
        size = self._obj(Bucket, Key).with_suffix(".bin").stat().st_size
        return {"ETag": meta["ETag"], "Metadata": meta["Metadata"], "ContentLength": size}

    def get_object(self, Bucket, Key, ExpectedBucketOwner=None, ChecksumMode=None):
        _bump(self.root, "s3.GetObject")
        self._cfg(Bucket, ExpectedBucketOwner)
        meta = self._meta(Bucket, Key)
        data = self._obj(Bucket, Key).with_suffix(".bin").read_bytes()
        f = _faults(self.root).get("get_object_corrupt")
        if f and Key.endswith(f.get("key_suffix", "")):  # in-transit corruption after S3's own checks
            i = min(len(data) - 1, f.get("offset", 100))
            data = data[:i] + bytes([data[i] ^ 0xFF]) + data[i + 1:]
        return {"Body": io.BytesIO(data), "ETag": meta["ETag"], "ContentLength": len(data)}

    def delete_object(self, Bucket, Key, IfMatch=None, ExpectedBucketOwner=None):
        _bump(self.root, "s3.DeleteObject")
        self._cfg(Bucket, ExpectedBucketOwner)
        if IfMatch is None:
            raise FakeClientError("AccessDenied", "Access Denied (bucket policy)", 403)
        meta = self._meta(Bucket, Key)
        if IfMatch != meta["ETag"]:
            raise FakeClientError("PreconditionFailed", "ETag mismatch", 412)
        p = self._obj(Bucket, Key)
        p.with_suffix(".bin").unlink()
        p.with_suffix(".meta").unlink()
        return {}

    def list_objects_v2(self, Bucket, ExpectedBucketOwner=None, MaxKeys=1000, ContinuationToken=None):
        _bump(self.root, "s3.ListObjectsV2")
        self._cfg(Bucket, ExpectedBucketOwner)
        keys = sorted(json.loads(m.read_text())["Key"] for m in (self._bdir(Bucket) / "objects").glob("*.meta"))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}


def _resolve(node, params: dict):
    if isinstance(node, dict):
        if set(node) == {"Ref"}:
            return params[node["Ref"]]
        if set(node) == {"Fn::Sub"}:
            return re.sub(r"\$\{([^}]+)\}", lambda m: str(params[m.group(1)]), node["Fn::Sub"])
        return {k: _resolve(v, params) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(v, params) for v in node]
    return node


class FakeCloudFormation:
    def __init__(self, root: Path, s3: FakeS3, region: str):
        self.root, self.s3, self.region = Path(root), s3, region

    def _p(self, name):
        return self.root / "cfn" / f"{name}.json"

    def create_stack(self, StackName, TemplateBody, Parameters, Tags=None, OnFailure=None,
                     TimeoutInMinutes=None, ClientRequestToken=None):
        _bump(self.root, "cfn.CreateStack")
        if self._p(StackName).exists():
            raise FakeClientError("AlreadyExistsException", f"Stack [{StackName}] already exists")
        t = json.loads(TemplateBody)
        params = {k: v.get("Default") for k, v in t["Parameters"].items()}
        params.update({p["ParameterKey"]: p["ParameterValue"] for p in Parameters})
        for k, spec in t["Parameters"].items():
            v = params[k]
            if "AllowedPattern" in spec and not re.fullmatch(spec["AllowedPattern"], str(v)):
                raise FakeClientError("ValidationError", f"Parameter {k} fails AllowedPattern")
            if spec["Type"] == "Number":
                params[k] = int(v)
                if not spec.get("MinValue", -math.inf) <= params[k] <= spec.get("MaxValue", math.inf):
                    raise FakeClientError("ValidationError", f"Parameter {k} out of range")
        params["AWS::Partition"] = "aws"
        params["Bucket"] = params["BucketName"]
        res = _resolve(t["Resources"], params)
        b = res["Bucket"]["Properties"]
        lc = []
        for r in b["LifecycleConfiguration"]["Rules"]:
            lc.append({"ID": r["Id"], "Status": r["Status"], "Filter": {"Prefix": ""},
                       "Expiration": {"Days": int(r["ExpirationInDays"])},
                       "AbortIncompleteMultipartUpload": r["AbortIncompleteMultipartUpload"]})
        enc = [{"ApplyServerSideEncryptionByDefault": e["ServerSideEncryptionByDefault"],
                "BucketKeyEnabled": e.get("BucketKeyEnabled", False)}
               for e in b["BucketEncryption"]["ServerSideEncryptionConfiguration"]]
        cfg = {"owner": FAKE_ACCOUNT, "region": self.region, "pab": b["PublicAccessBlockConfiguration"],
               "encryption": {"Rules": enc}, "ownership": b["OwnershipControls"]["Rules"], "lifecycle": lc,
               "tags": b["Tags"], "policy": json.dumps(res["BucketPolicy"]["Properties"]["PolicyDocument"]),
               "versioning": {}}
        self._p(StackName).parent.mkdir(parents=True, exist_ok=True)
        status = "CREATE_COMPLETE"
        if _faults(self.root).get("create_stack_fail"):
            status = "DELETE_COMPLETE" if OnFailure == "DELETE" else "ROLLBACK_COMPLETE"
        else:
            self.s3._create_bucket(b["BucketName"], cfg)
        self._p(StackName).write_text(json.dumps({"StackName": StackName, "StackStatus": status,
                                                  "Bucket": b["BucketName"], "Tags": Tags}))
        return {"StackId": f"arn:aws:cloudformation:{self.region}:{FAKE_ACCOUNT}:stack/{StackName}/fake"}

    def describe_stacks(self, StackName):
        _bump(self.root, "cfn.DescribeStacks")
        p = self._p(StackName)
        if not p.exists():
            raise FakeClientError("ValidationError", f"Stack with id {StackName} does not exist")
        return {"Stacks": [json.loads(p.read_text())]}

    def delete_stack(self, StackName, ClientRequestToken=None):
        _bump(self.root, "cfn.DeleteStack")
        p = self._p(StackName)
        if not p.exists():
            return {}
        st = json.loads(p.read_text())
        if st["StackStatus"] != "DELETE_COMPLETE":
            try:
                if self.s3._bdir(st["Bucket"]).exists():
                    self.s3._delete_bucket(st["Bucket"])
                st["StackStatus"] = "DELETE_COMPLETE"
            except FakeClientError:
                st["StackStatus"] = "DELETE_FAILED"
            p.write_text(json.dumps(st))
        return {}


class FakeSTS:
    def __init__(self, root):
        self.root = Path(root)

    def get_caller_identity(self):
        _bump(self.root, "sts.GetCallerIdentity")
        return {"Account": FAKE_ACCOUNT, "Arn": f"arn:aws:iam::{FAKE_ACCOUNT}:user/fake"}


def fake_vector(text: str, dims: int) -> list:
    out, i = [], 0
    while len(out) < dims:
        h = hashlib.sha256(f"{i}:{text}".encode()).digest()
        out += [(b - 127.5) / 127.5 for b in h]
        i += 1
    out = out[:dims]
    n = math.sqrt(sum(x * x for x in out))
    return [x / n for x in out]


class FakeBedrockRuntime:
    def __init__(self, root):
        self.root = Path(root)

    def invoke_model(self, modelId, body, contentType, accept):
        n = _bump(self.root, "bedrock.InvokeModel")
        f = _faults(self.root)
        if modelId != "amazon.titan-embed-text-v2:0":
            raise FakeClientError("ValidationException", "The provided model identifier is invalid.")
        req = json.loads(body)
        if set(req) - {"inputText", "dimensions", "normalize", "embeddingTypes"}:
            raise FakeClientError("ValidationException", "extraneous key")
        dims = req.get("dimensions", 1024)
        if dims not in (256, 512, 1024) or not req.get("inputText"):
            raise FakeClientError("ValidationException", "Malformed input request")
        if "invoke_fail" in f and n > f["invoke_fail"].get("after", 0):
            raise FakeClientError(f["invoke_fail"].get("code", "ThrottlingException"), "injected failure", 429)
        vec = fake_vector(req["inputText"], dims)
        bad = f.get("invoke_bad")
        if bad == "nan":
            vec[0] = float("nan")
        elif bad == "zero":
            vec = [0.0] * dims
        elif bad == "short":
            vec = vec[:-1]
        tokens = max(1, len(req["inputText"].split()))
        raw = json.dumps({"embedding": vec, "inputTextTokenCount": tokens, "embeddingsByType": {"float": vec}},
                         allow_nan=True).encode()
        return {"body": io.BytesIO(raw), "contentType": "application/json",
                "ResponseMetadata": {"RequestId": f"fake-{n}",
                                     "HTTPHeaders": {"x-amzn-bedrock-input-token-count": str(tokens)}}}


class FakeBedrock:
    def __init__(self, root, region):
        self.root, self.region = Path(root), region

    def get_foundation_model(self, modelIdentifier):
        _bump(self.root, "bedrock.GetFoundationModel")
        return {"modelDetails": {
            "modelId": modelIdentifier,
            "modelArn": f"arn:aws:bedrock:{self.region}::foundation-model/{modelIdentifier}",
            "modelLifecycle": {"status": "ACTIVE"}, "inferenceTypesSupported": ["ON_DEMAND"],
            "outputModalities": ["EMBEDDING"]}}


def fake_clients(root: Path, region: str) -> SimpleNamespace:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    s3 = FakeS3(root, region)
    return SimpleNamespace(s3=s3, cfn=FakeCloudFormation(root, s3, region), sts=FakeSTS(root),
                           bedrock_runtime=FakeBedrockRuntime(root), bedrock=FakeBedrock(root, region))
