"""Task-owned bucket: CloudFormation deploy, verification, immutable upload,
bounded download and cleanup of exactly the recorded objects and stack.

Every S3 request goes through the ledger and passes ExpectedBucketOwner. The
functions take client objects, so the same code runs against boto3 clients or
the local fakes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from . import TASK_TAG
from .ledger import Ledger, charged
from .snapshot import MANIFEST_NAME, SNAPSHOT_NAME, Refused, VerificationError, sha256_file, write_json

TEMPLATE = Path(__file__).resolve().parents[1] / "template" / "flh063-backup-bucket.json"
KEY_PREFIX = "flh063/"
MAX_RETENTION_DAYS = 14
REQUIRED_POLICY_SIDS = ("DenyInsecureTransport", "DenyWrongEncryption", "DenyMissingEncryption",
                        "DenyUnconditionalPut", "DenyUnconditionalDelete")
STACK_POLL_SECONDS = 5
STACK_TIMEOUT_SECONDS = 600


def error_code(e: BaseException) -> str | None:
    resp = getattr(e, "response", None)
    if isinstance(resp, dict):
        return resp.get("Error", {}).get("Code")
    return None


# --- resources.json --------------------------------------------------------------

def resources_path(state: Path) -> Path:
    return Path(state) / "resources.json"


def load_resources(state: Path) -> dict:
    p = resources_path(state)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_resources(state: Path, res: dict) -> None:
    write_json(resources_path(state), res)


# --- deploy and verify -------------------------------------------------------------

def deploy(state: Path, clients, region: str, retention_days: int, backend: str,
           sleep=time.sleep) -> dict:
    if not 1 <= retention_days <= MAX_RETENTION_DAYS:
        raise Refused(f"--retention-days must be 1..{MAX_RETENTION_DAYS}")
    res = load_resources(state)
    if res.get("stack"):
        raise Refused(f"this state directory already owns stack {res['stack']['name']}; "
                      "use a new state directory or run cleanup first")
    account = clients.sts.get_caller_identity()["Account"]
    sid = secrets.token_hex(6)
    name = f"flh063-{sid}"
    res = {"region": region, "account": account, "state_id": sid,
           "stack": {"name": name, "status": "CREATING"}, "bucket": name,
           "retention_days": retention_days, "objects": [], "runs": {}}
    save_resources(state, res)  # recorded before the request, so cleanup can find it
    clients.cfn.create_stack(
        StackName=name, TemplateBody=TEMPLATE.read_text(encoding="utf-8"),
        Parameters=[{"ParameterKey": "BucketName", "ParameterValue": name},
                    {"ParameterKey": "StateId", "ParameterValue": sid},
                    {"ParameterKey": "RetentionDays", "ParameterValue": str(retention_days)}],
        Tags=[{"Key": "flh:task", "Value": TASK_TAG}, {"Key": "flh:state-id", "Value": sid}],
        OnFailure="DELETE", TimeoutInMinutes=10, ClientRequestToken=f"{name}-create")
    status = wait_stack(clients.cfn, name, ("CREATE_COMPLETE",), sleep)
    res["stack"]["status"] = status
    save_resources(state, res)
    if status != "CREATE_COMPLETE":
        raise VerificationError(f"stack {name} ended in {status}")
    return {"stack": name, "bucket": name, "region": region, "checks": verify_bucket(state, clients, backend)}


def wait_stack(cfn, name: str, ok: tuple, sleep=time.sleep) -> str:
    deadline = time.monotonic() + STACK_TIMEOUT_SECONDS
    while True:
        try:
            st = cfn.describe_stacks(StackName=name)["Stacks"][0]["StackStatus"]
        except Exception as e:  # noqa: BLE001
            if "does not exist" in str(e):
                return "DOES_NOT_EXIST"
            raise
        if st in ok or st.endswith("_FAILED") or st.endswith("ROLLBACK_COMPLETE") or st == "DELETE_COMPLETE":
            return st
        if time.monotonic() > deadline:
            return st + " (timed out waiting)"
        sleep(STACK_POLL_SECONDS)


def _s3_read(ledger: Ledger, backend: str, what: str, fn, **kw):
    with charged(ledger, "s3_get_config", {"s3_get_requests": 1}, {"op": what}, backend):
        return fn(**kw)


def verify_bucket(state: Path, clients, backend: str) -> dict:
    """Read back every security setting; raise VerificationError on any mismatch."""
    res = load_resources(state)
    if not res.get("bucket"):
        raise Refused("no bucket recorded in this state directory; run deploy first")
    b, owner, region = res["bucket"], res["account"], res["region"]
    s3, led = clients.s3, Ledger(state)
    kw = {"Bucket": b, "ExpectedBucketOwner": owner}
    problems, checks = [], {}

    loc = _s3_read(led, backend, "GetBucketLocation", s3.get_bucket_location, **kw).get("LocationConstraint")
    checks["region"] = loc or "us-east-1"
    if checks["region"] != region:
        problems.append(f"bucket region {checks['region']} != {region}")

    pab = _s3_read(led, backend, "GetPublicAccessBlock", s3.get_public_access_block, **kw)["PublicAccessBlockConfiguration"]
    checks["public_access_block"] = pab
    for k in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"):
        if pab.get(k) is not True:
            problems.append(f"public access block {k} is not true")

    enc = _s3_read(led, backend, "GetBucketEncryption", s3.get_bucket_encryption, **kw)
    algos = [r["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]
             for r in enc["ServerSideEncryptionConfiguration"]["Rules"]]
    checks["default_encryption"] = algos
    if algos != ["AES256"]:
        problems.append(f"default encryption is {algos}, expected ['AES256']")

    pol = json.loads(_s3_read(led, backend, "GetBucketPolicy", s3.get_bucket_policy, **kw)["Policy"])
    sids = {s.get("Sid") for s in pol.get("Statement", []) if s.get("Effect") == "Deny"}
    checks["policy_deny_sids"] = sorted(x for x in sids if x)
    for sid in REQUIRED_POLICY_SIDS:
        if sid not in sids:
            problems.append(f"bucket policy lacks Deny statement {sid}")
    if any(s.get("Effect") == "Allow" for s in pol.get("Statement", [])):
        problems.append("bucket policy contains an Allow statement")

    rules = _s3_read(led, backend, "GetBucketLifecycleConfiguration",
                     s3.get_bucket_lifecycle_configuration, **kw)["Rules"]
    days = [r["Expiration"]["Days"] for r in rules
            if r.get("Status") == "Enabled" and "Days" in r.get("Expiration", {})
            and r.get("Filter", {}).get("Prefix", "") == "" and "Tag" not in r.get("Filter", {})
            and "And" not in r.get("Filter", {})]
    checks["expiration_days"] = days
    if not days or min(days) > MAX_RETENTION_DAYS:
        problems.append("no whole-bucket expiration rule within the retention limit")

    own = _s3_read(led, backend, "GetBucketOwnershipControls", s3.get_bucket_ownership_controls, **kw)
    oo = [r["ObjectOwnership"] for r in own["OwnershipControls"]["Rules"]]
    checks["object_ownership"] = oo
    if oo != ["BucketOwnerEnforced"]:
        problems.append(f"object ownership is {oo}")

    ver = _s3_read(led, backend, "GetBucketVersioning", s3.get_bucket_versioning, **kw).get("Status")
    checks["versioning"] = ver or "Never enabled"
    if ver == "Enabled":
        problems.append("versioning is enabled (deleted objects would leave noncurrent versions)")

    tags = {t["Key"]: t["Value"] for t in _s3_read(led, backend, "GetBucketTagging", s3.get_bucket_tagging, **kw)["TagSet"]}
    checks["tags"] = {k: v for k, v in tags.items() if k.startswith("flh:")}
    if tags.get("flh:task") != TASK_TAG or tags.get("flh:state-id") != res["state_id"]:
        problems.append("bucket tags do not identify this state directory")

    if problems:
        raise VerificationError("bucket verification failed: " + "; ".join(problems))
    return checks


# --- upload / download ---------------------------------------------------------------

def upload(state: Path, clients, package_dir: Path, run_id: str, manifest_sha256: str, backend: str) -> dict:
    res = load_resources(state)
    if not res.get("bucket") or res.get("stack", {}).get("status") != "CREATE_COMPLETE":
        raise Refused("no verified bucket in this state directory; run deploy first")
    if run_id in res.get("runs", {}):
        raise Refused(f"run {run_id} was already uploaded from this state directory; keys are immutable")
    package_dir = Path(package_dir)
    files = [package_dir / SNAPSHOT_NAME, package_dir / MANIFEST_NAME]  # manifest last: completion marker
    for f in files:
        if not f.is_file():
            raise Refused(f"package is missing {f.name}")
    if sha256_file(package_dir / MANIFEST_NAME) != manifest_sha256:
        raise Refused("package manifest changed since it was created")
    total = sum(f.stat().st_size for f in files)
    led = Ledger(state)
    rem = led.remaining()
    if total > rem["s3_put_bytes"] or len(files) > rem["s3_put_requests"]:
        raise Refused(f"package needs {total} bytes / {len(files)} PUTs; remaining {rem['s3_put_bytes']} "
                      f"bytes / {rem['s3_put_requests']} PUTs; nothing sent")
    checks = verify_bucket(state, clients, backend)
    res["runs"][run_id] = {"state": "uploading", "manifest_sha256": manifest_sha256, "keys": []}
    save_resources(state, res)
    for f in files:
        data = f.read_bytes()
        digest = hashlib.sha256(data).digest()
        key = f"{KEY_PREFIX}{run_id}/{f.name}"
        with charged(led, "s3_put_object", {"s3_put_requests": 1, "s3_put_bytes": len(data)},
                     {"key": key, "bytes": len(data)}, backend) as out:
            try:
                r = clients.s3.put_object(
                    Bucket=res["bucket"], Key=key, Body=data, IfNoneMatch="*",
                    ServerSideEncryption="AES256", ChecksumSHA256=base64.b64encode(digest).decode(),
                    ExpectedBucketOwner=res["account"], ContentType="application/octet-stream",
                    Metadata={"flh-task": TASK_TAG, "flh-run": run_id, "flh-sha256": digest.hex()})
            except Exception as e:  # noqa: BLE001
                res["runs"][run_id]["state"] = "incomplete"
                save_resources(state, res)
                if error_code(e) in ("PreconditionFailed", "412", "ConditionalRequestConflict"):
                    raise Refused(f"{key} already exists in the bucket; not overwritten") from None
                raise
            out.update({"etag": r.get("ETag"), "sse": r.get("ServerSideEncryption")})
        res["objects"].append({"key": key, "etag": r["ETag"], "bytes": len(data), "sha256": digest.hex(),
                               "run_id": run_id})
        res["runs"][run_id]["keys"].append(key)
        save_resources(state, res)
    res["runs"][run_id]["state"] = "uploaded"
    save_resources(state, res)
    return {"run_id": run_id, "keys": res["runs"][run_id]["keys"], "bytes": total, "bucket_checks": checks}


def download(state: Path, clients, run_id: str, dest: Path, backend: str) -> list:
    res = load_resources(state)
    run = res.get("runs", {}).get(run_id)
    if not run or run["state"] != "uploaded":
        raise Refused(f"run {run_id} is not a completed upload recorded in this state directory")
    led = Ledger(state)
    objs = {o["key"]: o for o in res["objects"]}
    need = sum(objs[k]["bytes"] for k in run["keys"])
    rem = led.remaining()
    if need > rem["s3_get_bytes"] or len(run["keys"]) > rem["s3_get_requests"]:
        raise Refused(f"download needs {need} bytes; remaining {rem['s3_get_bytes']}; nothing sent")
    dest.mkdir(parents=True, exist_ok=False)
    got = []
    for key in run["keys"]:
        expected = objs[key]["bytes"]
        target = dest / key.rsplit("/", 1)[1]
        part = Path(str(target) + ".part")
        with charged(led, "s3_get_object", {"s3_get_requests": 1, "s3_get_bytes": expected},
                     {"key": key}, backend) as out:
            r = clients.s3.get_object(Bucket=res["bucket"], Key=key, ExpectedBucketOwner=res["account"],
                                      ChecksumMode="ENABLED")
            n = 0
            with open(part, "wb") as f:
                body = r["Body"]
                while True:
                    chunk = body.read(1 << 20)
                    if not chunk:
                        break
                    n += len(chunk)
                    if n > expected:
                        raise VerificationError(f"{key}: more bytes than recorded ({expected})")
                    f.write(chunk)
            out.update({"bytes": n, "etag": r.get("ETag")})
        os.replace(part, target)
        got.append({"key": key, "bytes": n})
    return got


# --- cleanup -------------------------------------------------------------------------

def cleanup(state: Path, clients, backend: str, sleep=time.sleep) -> dict:
    """Delete exactly the recorded objects, then the stack only if the bucket is empty."""
    res = load_resources(state)
    if not res.get("stack"):
        return {"objects_deleted": [], "stack": "none recorded", "unknown_keys": []}
    led = Ledger(state)
    b, owner = res["bucket"], res["account"]
    deleted, kept = [], []
    for obj in list(res["objects"]):
        key = obj["key"]
        with charged(led, "s3_head_object", {"s3_get_requests": 1}, {"key": key}, backend):
            try:
                head = clients.s3.head_object(Bucket=b, Key=key, ExpectedBucketOwner=owner)
            except Exception as e:  # noqa: BLE001
                if error_code(e) in ("404", "NoSuchKey", "NotFound"):
                    head = None
                else:
                    raise
        if head is None:  # already gone (for example expired by lifecycle)
            res["objects"].remove(obj)
            save_resources(state, res)
            deleted.append({"key": key, "result": "already absent"})
            continue
        meta = {k.lower(): v for k, v in (head.get("Metadata") or {}).items()}
        if head.get("ETag") != obj["etag"] or meta.get("flh-run") != obj["run_id"]:
            kept.append({"key": key, "reason": "ETag or run metadata differs from the record; not deleted"})
            continue
        with charged(led, "s3_delete_object", {"s3_delete_requests": 1}, {"key": key}, backend):
            clients.s3.delete_object(Bucket=b, Key=key, IfMatch=obj["etag"], ExpectedBucketOwner=owner)
        res["objects"].remove(obj)
        save_resources(state, res)
        deleted.append({"key": key, "result": "deleted"})

    stack_status = res["stack"].get("status")
    unknown = []
    if stack_status in ("CREATE_COMPLETE", "CREATING", "DELETE_FAILED"):
        try:
            unknown = list_keys(state, clients, backend)
        except Exception as e:  # noqa: BLE001
            if error_code(e) not in ("NoSuchBucket",):
                raise
    if kept or unknown:
        return {"objects_deleted": deleted, "kept": kept, "unknown_keys": unknown,
                "stack": f"kept: bucket is not empty ({len(unknown)} object(s) remain); nothing unknown was deleted"}
    if res["stack"].get("status") != "DELETED":
        tags_ok = True
        try:
            verify_tags_only(state, clients, backend)
        except VerificationError:
            tags_ok = False
        except Exception as e:  # noqa: BLE001
            if error_code(e) != "NoSuchBucket":
                raise
        if not tags_ok:
            return {"objects_deleted": deleted, "unknown_keys": [],
                    "stack": "kept: bucket tags do not identify this state directory"}
        clients.cfn.delete_stack(StackName=res["stack"]["name"],
                                 ClientRequestToken=f"{res['stack']['name']}-delete")
        status = wait_stack(clients.cfn, res["stack"]["name"], ("DELETE_COMPLETE",), sleep)
        res["stack"]["status"] = "DELETED" if status in ("DELETE_COMPLETE", "DOES_NOT_EXIST") else status
        save_resources(state, res)
    return {"objects_deleted": deleted, "unknown_keys": [], "stack": res["stack"]["status"]}


def list_keys(state: Path, clients, backend: str, max_pages: int = 5) -> list:
    res = load_resources(state)
    led, keys, token = Ledger(state), [], None
    for _ in range(max_pages):
        kw = {"Bucket": res["bucket"], "ExpectedBucketOwner": res["account"], "MaxKeys": 1000}
        if token:
            kw["ContinuationToken"] = token
        with charged(led, "s3_list_objects", {"s3_list_requests": 1}, {}, backend):
            r = clients.s3.list_objects_v2(**kw)
        keys += [o["Key"] for o in r.get("Contents", [])]
        if not r.get("IsTruncated"):
            return keys
        token = r.get("NextContinuationToken")
    raise VerificationError("bucket listing exceeded the page limit")


def verify_tags_only(state: Path, clients, backend: str) -> None:
    res = load_resources(state)
    tags = {t["Key"]: t["Value"] for t in _s3_read(
        Ledger(state), backend, "GetBucketTagging", clients.s3.get_bucket_tagging,
        Bucket=res["bucket"], ExpectedBucketOwner=res["account"])["TagSet"]}
    if tags.get("flh:task") != TASK_TAG or tags.get("flh:state-id") != res["state_id"]:
        raise VerificationError("bucket tags do not identify this state directory")
