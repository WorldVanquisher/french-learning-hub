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
import re
import secrets
import time
from pathlib import Path

from . import TASK_TAG
from .diagnostics import classify, error_code, is_definite_rejection
from .ledger import Ledger, charged
from .snapshot import MANIFEST_NAME, SNAPSHOT_NAME, Refused, VerificationError, sha256_file, write_json

TEMPLATE = Path(__file__).resolve().parents[1] / "template" / "flh063-backup-bucket.json"
KEY_PREFIX = "flh063/"
MAX_RETENTION_DAYS = 14
REQUIRED_POLICY_SIDS = ("DenyInsecureTransport", "DenyWrongEncryption", "DenyMissingEncryption",
                        "DenyUnconditionalPut", "DenyUnconditionalDelete")
STACK_POLL_SECONDS = 5
STACK_TIMEOUT_SECONDS = 600


# Stack statuses written by this tool itself (the rest are CloudFormation's own).
CREATE_REQUESTING = "CREATE_REQUESTING"   # saved before CreateStack is sent
CREATE_REJECTED = "CREATE_REJECTED"       # AWS answered 4xx: nothing was created
CREATE_UNKNOWN = "CREATE_UNKNOWN"         # no usable answer: the stack may or may not exist
DELETE_REQUESTED = "DELETE_REQUESTED"     # saved before DeleteStack is sent; final state not yet observed
LEGACY_CREATING = "CREATING"              # FLH-063 records (no StackId)
LEGACY_DELETED = "DELETED"                # FLH-063: "does not exist" by name, never confirmed by StackId
RESOURCES_SCHEMA = "flh066_resources_v2"
BY_ID = "describe_stacks_by_id"


CFN_STATUSES = frozenset(
    f"{op}_{st}" for op in ("CREATE", "ROLLBACK", "DELETE", "UPDATE", "UPDATE_ROLLBACK", "IMPORT",
                            "IMPORT_ROLLBACK", "UPDATE_COMPLETE_CLEANUP", "UPDATE_ROLLBACK_COMPLETE_CLEANUP")
    for st in ("IN_PROGRESS", "FAILED", "COMPLETE")) | {"REVIEW_IN_PROGRESS"}
LOCAL_STATUSES = frozenset({CREATE_REQUESTING, CREATE_REJECTED, CREATE_UNKNOWN, DELETE_REQUESTED,
                            LEGACY_CREATING, LEGACY_DELETED})
OBSERVERS = frozenset({BY_ID, "describe_stacks_by_name", "create_stack_response", "local"})
UTC_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z")


class OutcomeUnknown(Exception):
    """A request's effect could not be determined; nothing is retried automatically."""


class ReceiptInvalid(VerificationError):
    """resources.json is malformed or internally inconsistent; nothing is sent and no success is reported.

    This detects corruption and inconsistent edits. It is not tamper-proofing:
    whoever can rewrite every local file consistently can forge a receipt.
    """


# --- resources.json --------------------------------------------------------------

def resources_path(state: Path) -> Path:
    return Path(state) / "resources.json"


def load_resources(state: Path) -> dict:
    """Read and validate the receipt. Raises ReceiptInvalid; never returns an inconsistent record."""
    p = resources_path(state)
    if not p.exists():
        return {}
    try:
        res = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        raise ReceiptInvalid(f"{p.name} is not valid JSON; nothing was sent") from None
    problems = receipt_problems(res)
    if problems:
        raise ReceiptInvalid(f"{p.name} is malformed or inconsistent ({'; '.join(problems)}); nothing was sent "
                             "and no cleanup result is reported. Restore it from your own copy, or inspect the "
                             "resources in the AWS console")
    return res


def _is_str(v) -> bool:
    return isinstance(v, str) and bool(v)


def receipt_problems(res) -> list:
    """Schema, type and identifier/state invariants of resources.json (FLH-068).

    Legacy FLH-063/064 records (no ``schema``, no StackId) remain valid.
    """
    if not isinstance(res, dict):
        return ["not a JSON object"]
    if not res:
        return []
    out = []
    schema = res.get("schema")
    if schema is not None and schema != RESOURCES_SCHEMA:
        out.append(f"unknown schema {schema!r}")
    region, account, sid = res.get("region"), res.get("account"), res.get("state_id")
    if not (_is_str(region) and re.fullmatch(r"[a-z]{2}(-[a-z]+)+-\d", region)):
        out.append("region is not an AWS region name")
    if not (_is_str(account) and re.fullmatch(r"\d{12}", account)):
        out.append("account is not a 12-digit id")
    if not (_is_str(sid) and re.fullmatch(r"[0-9a-f]{12}", sid)):
        out.append("state_id is not 12 hex digits")
        return out
    expected = f"flh063-{sid}"
    if res.get("bucket") != expected:
        out.append("bucket does not match state_id")
    st = res.get("stack")
    if not isinstance(st, dict):
        return out + ["stack is missing or not an object"]
    if st.get("name") != expected:
        out.append("stack name does not match state_id")
    status = st.get("status")
    if status not in CFN_STATUSES and status not in LOCAL_STATUSES:
        out.append(f"unknown stack status {status!r}")
    if st.get("observed_by") is not None and st.get("observed_by") not in OBSERVERS:
        out.append("unknown observed_by")
    for k in ("observed_utc", "requested_utc"):
        if st.get(k) is not None and not (isinstance(st[k], str) and UTC_RE.fullmatch(st[k])):
            out.append(f"stack.{k} is not a UTC timestamp")
    if "tags" in st and st["tags"] != {"flh:task": TASK_TAG, "flh:state-id": sid}:
        out.append("stack tags do not identify this state")
    if st.get("id") is not None:
        if not out:
            try:
                check_stack_id(st["id"], res)
            except VerificationError:
                out.append("stack.id is not this state's StackId (name, account, region)")
    elif status == "DELETE_COMPLETE" or st.get("observed_by") == BY_ID or "deletion_confirmation" in st:
        out.append("a StackId observation is recorded without a StackId")
    if "deletion_confirmation" in st and not out and not _confirmation_ok(res):
        out.append("deletion_confirmation is inconsistent with the stack record and bucket probe")
    probe = res.get("bucket_probe")
    if probe is not None and not (isinstance(probe, dict) and probe.get("result") in ("absent", "present", "unknown")
                                  and isinstance(probe.get("utc"), str) and UTC_RE.fullmatch(probe["utc"])):
        out.append("bucket_probe is malformed")
    objs = res.get("objects", [])
    if not isinstance(objs, list) or not all(
            isinstance(o, dict) and _is_str(o.get("key")) and o["key"].startswith(KEY_PREFIX)
            and _is_str(o.get("etag")) and _is_str(o.get("run_id")) for o in objs):
        out.append("objects are malformed")
    if not isinstance(res.get("runs", {}), dict):
        out.append("runs is not an object")
    if not isinstance(st.get("delete_attempts", []), list):
        out.append("delete_attempts is not a list")
    return out


def _confirmation_ok(res: dict) -> bool:
    """A deletion confirmation must restate exactly what was observed: by StackId, then NoSuchBucket."""
    st, c, probe = res["stack"], res["stack"].get("deletion_confirmation"), res.get("bucket_probe") or {}
    return (isinstance(c, dict) and c.get("stack_id") == st.get("id") and c.get("stack_status") == "DELETE_COMPLETE"
            and st.get("status") == "DELETE_COMPLETE" and st.get("observed_by") == BY_ID
            and c.get("observed_utc") == st.get("observed_utc") and probe.get("result") == "absent"
            and c.get("bucket") == res.get("bucket") and c.get("bucket_probe_utc") == probe.get("utc")
            and isinstance(c.get("observed_utc"), str) and c.get("observed_utc") <= probe.get("utc", ""))


def save_resources(state: Path, res: dict) -> None:
    write_json(resources_path(state), res)


def _now() -> str:
    from .ledger import utc_now
    return utc_now()


def check_stack_id(stack_id: str, res: dict) -> None:
    """The full StackId must name this state's stack, account and region."""
    pat = (r"arn:aws[a-z-]*:cloudformation:" + re.escape(res["region"]) + ":" + re.escape(res["account"])
           + r":stack/" + re.escape(res["stack"]["name"]) + r"/[0-9a-fA-F-]{36}")
    if not isinstance(stack_id, str) or not re.fullmatch(pat, stack_id):
        raise VerificationError("StackId does not name this state directory's stack, account and region")


def _observe(st: dict, status: str, by: str) -> None:
    st.update({"status": status, "observed_utc": _now(), "observed_by": by})
    st.pop("last_observation_error", None)
    st.pop("deletion_confirmation", None)  # any new observation supersedes an earlier confirmation


def ownership_problems(s: dict, res: dict) -> list:
    """The observed stack must be exactly the recorded one and carry this state's task/state tags."""
    st = res["stack"]
    tags = {t.get("Key"): t.get("Value") for t in s.get("Tags") or [] if isinstance(t, dict)}
    out = []
    if s.get("StackId") != st.get("id"):
        out.append("observed StackId differs from the recorded one")
    if s.get("StackName") != st.get("name"):
        out.append("observed stack name differs from the recorded one")
    if tags.get("flh:task") != TASK_TAG or tags.get("flh:state-id") != res.get("state_id"):
        out.append("observed tags do not identify this task and state directory")
    return out


def stack_report(res: dict) -> dict:
    """Honest cleanup/presence state derived only from what was recorded and observed."""
    st = res.get("stack")
    if not st:
        return {"state": "none_recorded"}
    status, sid = st.get("status"), st.get("id")
    probe = (res.get("bucket_probe") or {}).get("result")
    rep = {"name": st["name"], "stack_id_recorded": bool(sid), "status": status,
           "observed_by": st.get("observed_by"), "observed_utc": st.get("observed_utc"), "bucket_probe": probe}
    if st.get("last_observation_error"):
        rep["last_observation_error"] = st["last_observation_error"]
    if status == CREATE_REJECTED:
        return {"state": "not_created", "reason": "CreateStack was rejected by AWS; nothing was created", **rep}
    if not sid:
        if status in (LEGACY_DELETED,) or st.get("by_name") == "absent":
            why = ("no StackId was recorded; a stack that does not exist by name may be deleted or never created, "
                   "so DELETE_COMPLETE cannot be verified")
            if probe == "absent":
                why += "; the bucket is confirmed absent (NoSuchBucket for the expected owner)"
            return {"state": "verification_unavailable", "reason": why, **rep}
        return {"state": "verification_unavailable",
                "reason": "the creation outcome is not known and no StackId is recorded; run recover", **rep}
    if st.get("ownership_refused"):
        return {"state": "ownership_refused", "reason": "the observed stack is not proven to belong to this state "
                "directory (" + "; ".join(st["ownership_refused"]["problems"]) + "); nothing destructive was sent",
                **rep}
    if status == "DELETE_COMPLETE" and st.get("observed_by") == BY_ID:
        if probe == "absent" and _confirmation_ok(res):
            return {"state": "deletion_confirmed", "reason": "DELETE_COMPLETE read by StackId and the bucket is absent",
                    **rep}
        if probe == "absent":
            return {"state": "verification_unavailable", "reason": "DELETE_COMPLETE and bucket absence are recorded "
                    "without a consistent deletion confirmation; cleanup or recover re-reads them", **rep}
        if probe == "present":
            return {"state": "resources_present", "reason": "the stack is DELETE_COMPLETE but the bucket still exists",
                    **rep}
        return {"state": "verification_unavailable",
                "reason": "DELETE_COMPLETE read by StackId; bucket absence not confirmed", **rep}
    if status in (DELETE_REQUESTED, "DELETE_IN_PROGRESS"):
        return {"state": "deletion_requested", "reason": "DeleteStack was sent; completion has not been observed", **rep}
    if status in (CREATE_REQUESTING, CREATE_UNKNOWN, LEGACY_CREATING):
        return {"state": "verification_unavailable", "reason": "the creation outcome is not known; run recover", **rep}
    return {"state": "resources_present", "reason": f"the stack was last observed as {status}", **rep}


# --- deploy and verify -------------------------------------------------------------

def deploy(state: Path, clients, region: str, retention_days: int, backend: str,
           sleep=time.sleep) -> dict:
    if not 1 <= retention_days <= MAX_RETENTION_DAYS:
        raise Refused(f"--retention-days must be 1..{MAX_RETENTION_DAYS}")
    res = load_resources(state)
    history = res.get("history", [])
    if res.get("stack"):
        if res["stack"].get("status") != CREATE_REJECTED:
            raise Refused(f"this state directory already owns stack {res['stack']['name']} "
                          f"({stack_report(res)['state']}); run recover/cleanup, or use a new state directory")
        history.append({k: res[k] for k in ("stack", "bucket", "state_id") if k in res})  # nothing was created
    account = clients.sts.get_caller_identity()["Account"]
    sid = secrets.token_hex(6)
    name = f"flh063-{sid}"
    token = f"{name}-create"
    res = {"schema": RESOURCES_SCHEMA, "region": region, "account": account, "state_id": sid,
           "stack": {"name": name, "status": CREATE_REQUESTING, "client_request_token": token,
                     "requested_utc": _now(), "tags": {"flh:task": TASK_TAG, "flh:state-id": sid}},
           "bucket": name, "retention_days": retention_days, "objects": [], "runs": {}}
    if history:
        res["history"] = history
    save_resources(state, res)  # recorded before the request, so recover/cleanup can find it
    st = res["stack"]
    try:
        r = clients.cfn.create_stack(
            StackName=name, TemplateBody=TEMPLATE.read_text(encoding="utf-8"),
            Parameters=[{"ParameterKey": "BucketName", "ParameterValue": name},
                        {"ParameterKey": "StateId", "ParameterValue": sid},
                        {"ParameterKey": "RetentionDays", "ParameterValue": str(retention_days)}],
            Tags=[{"Key": "flh:task", "Value": TASK_TAG}, {"Key": "flh:state-id", "Value": sid}],
            OnFailure="DELETE", TimeoutInMinutes=10, ClientRequestToken=token)
    except Exception as e:  # noqa: BLE001
        info = classify(e)
        st["create_error"] = {k: info[k] for k in ("category", "error_type", "code", "message")}
        if is_definite_rejection(e):
            _observe(st, CREATE_REJECTED, "create_stack_response")
            save_resources(state, res)
            raise VerificationError(f"CreateStack was rejected ({info['category']}: {info['code']}); nothing was "
                                    f"created. {info['guidance']}") from None
        _observe(st, CREATE_UNKNOWN, "local")
        save_resources(state, res)
        raise OutcomeUnknown(f"CreateStack for {name} has an unknown outcome ({info['category']}: "
                             f"{info['error_type']}); the stack may exist. It is not resent. Run `recover` "
                             "(read-only) before anything else.") from None
    st["id"] = r.get("StackId")
    st["id_source"] = "create_stack_response"
    try:
        check_stack_id(st["id"], res)
    except VerificationError:
        st["unexpected_stack_id"], st["id"] = st["id"], None
        _observe(st, CREATE_UNKNOWN, "create_stack_response")
        save_resources(state, res)
        raise
    _observe(st, "CREATE_IN_PROGRESS", "create_stack_response")
    save_resources(state, res)  # the full StackId is persisted before any wait
    status = _wait_and_record(state, res, clients.cfn, ("CREATE_COMPLETE",), sleep)
    if status != "CREATE_COMPLETE":
        raise VerificationError(f"stack {name} ended in {status}; run cleanup to confirm what remains")
    return {"stack": name, "stack_id": mask_account(st["id"]), "bucket": name, "region": region,
            "checks": verify_bucket(state, clients, backend)}


def mask_account(text):
    return re.sub(r"(?<!\d)\d{12}(?!\d)", "<account>", text) if isinstance(text, str) else text


def describe_stack(cfn, ident: str) -> dict | None:
    """DescribeStacks for one name or StackId; None only when CloudFormation says it does not exist.

    By name, only live stacks are found. By StackId, CloudFormation also
    returns deleted stacks (DELETE_COMPLETE) for a retention period.
    """
    try:
        stacks = cfn.describe_stacks(StackName=ident)["Stacks"]
    except Exception as e:  # noqa: BLE001
        if error_code(e) == "ValidationError" and "does not exist" in str(e):
            return None
        raise
    if len(stacks) != 1:
        raise VerificationError(f"DescribeStacks returned {len(stacks)} stacks for one identifier")
    return stacks[0]


def wait_stack(cfn, ident: str, ok: tuple, sleep=time.sleep) -> str:
    """Poll until a terminal status. A StackId that 'does not exist' is unknown, never deleted."""
    deadline = time.monotonic() + STACK_TIMEOUT_SECONDS
    while True:
        s = describe_stack(cfn, ident)
        if s is None:
            raise OutcomeUnknown("CloudFormation reports no stack for the recorded StackId")
        if s.get("StackId") != ident:
            raise VerificationError("DescribeStacks answered for a different StackId")
        st = s["StackStatus"]
        if st in ok or st.endswith("_FAILED") or st.endswith("ROLLBACK_COMPLETE") or st == "DELETE_COMPLETE":
            return st
        if time.monotonic() > deadline:
            raise OutcomeUnknown(f"stack still {st} after {STACK_TIMEOUT_SECONDS} s")
        sleep(STACK_POLL_SECONDS)


def _wait_and_record(state: Path, res: dict, cfn, ok: tuple, sleep) -> str:
    st = res["stack"]
    try:
        status = wait_stack(cfn, st["id"], ok, sleep)
    except Exception as e:  # noqa: BLE001 - AccessDenied, network, timeout: unknown, not success
        info = classify(e) if not isinstance(e, OutcomeUnknown) else {"category": "unknown", "message": str(e)}
        st["last_observation_error"] = {"category": info["category"], "message": info["message"], "utc": _now()}
        save_resources(state, res)
        raise OutcomeUnknown(f"could not observe stack {st['name']} ({info['category']}: {info['message']}); "
                             "run `recover` (read-only) later") from None
    _observe(st, status, BY_ID)
    save_resources(state, res)
    return status


# --- read-only reconciliation ---------------------------------------------------------

def _owned(s: dict, res: dict) -> bool:
    tags = {t["Key"]: t["Value"] for t in s.get("Tags") or []}
    return (s.get("StackName") == res["stack"]["name"] and tags.get("flh:task") == TASK_TAG
            and tags.get("flh:state-id") == res["state_id"])


def probe_bucket(state: Path, clients, backend: str) -> dict:
    """GetBucketLocation with ExpectedBucketOwner: NoSuchBucket proves the bucket is absent."""
    res = load_resources(state)
    try:
        _s3_read(Ledger(state), backend, "GetBucketLocation(probe)", clients.s3.get_bucket_location,
                 Bucket=res["bucket"], ExpectedBucketOwner=res["account"])
        out = {"result": "present"}
    except Exception as e:  # noqa: BLE001
        if error_code(e) == "NoSuchBucket":
            out = {"result": "absent"}
        else:
            info = classify(e)
            out = {"result": "unknown", "category": info["category"], "message": info["message"]}
    out["utc"] = _now()
    res["bucket_probe"] = out
    st = res.get("stack") or {}
    st.pop("deletion_confirmation", None)
    if out["result"] == "absent" and st.get("id") and st.get("status") == "DELETE_COMPLETE" \
            and st.get("observed_by") == BY_ID:
        st["deletion_confirmation"] = {"stack_id": st["id"], "stack_status": "DELETE_COMPLETE",
                                       "observed_utc": st["observed_utc"], "bucket": res["bucket"],
                                       "bucket_probe_utc": out["utc"]}
    save_resources(state, res)
    return out


def recover(state: Path, clients, backend: str, stack_id: str | None = None) -> dict:
    """Read-only reconciliation of the recorded stack. Sends no write to AWS.

    1. With an operator-supplied --stack-id (for a record without one), check
       it names this state's stack, account and region, then read it.
    2. Without a recorded StackId, look the stack up by name (live stacks only)
       and adopt its StackId only if its tags identify this state directory.
    3. With a StackId, read the current status by StackId.
    4. When no stack is found, or the stack is DELETE_COMPLETE, probe the bucket.
    """
    res = load_resources(state)
    st = res.get("stack")
    if not st:
        return {"stack": stack_report(res), "actions": []}
    actions = []
    if stack_id:
        if st.get("id") and st["id"] != stack_id:
            raise Refused("a different StackId is already recorded; not replaced")
        check_stack_id(stack_id, res)
        st["id"], st["id_source"] = stack_id, "operator"
        actions.append("adopted the operator-supplied StackId after checking name, account and region")
        save_resources(state, res)
    try:
        if not st.get("id"):
            s = describe_stack(clients.cfn, st["name"])
            if s is None:
                st["by_name"] = "absent"
                st["by_name_utc"] = _now()
                actions.append("no live stack by this name (deleted or never created; not distinguishable by name)")
            elif not _owned(s, res):
                raise VerificationError(f"a stack named {st['name']} exists but its tags do not identify this state "
                                        "directory; not adopted, nothing changed")
            else:
                st["id"] = s["StackId"]
                check_stack_id(st["id"], res)
                st["id_source"] = "describe_stacks_by_name"
                st.pop("by_name", None)
                actions.append("adopted the StackId of the live, correctly tagged stack")
        if st.get("id"):
            s = describe_stack(clients.cfn, st["id"])
            if s is None:
                raise OutcomeUnknown("CloudFormation reports no stack for the recorded StackId")
            if s.get("StackName") != st["name"] or s.get("StackId") != st["id"]:
                raise VerificationError("the StackId resolves to a different stack; nothing changed")
            if s["StackStatus"] != "DELETE_COMPLETE" and ownership_problems(s, res):
                raise VerificationError("the live stack is not proven to belong to this state directory ("
                                        + "; ".join(ownership_problems(s, res)) + "); nothing changed")
            _observe(st, s["StackStatus"], BY_ID)
            actions.append(f"read status {s['StackStatus']} by StackId")
    except (VerificationError, Refused):
        save_resources(state, res)
        raise
    except Exception as e:  # noqa: BLE001 - AccessDenied, network: report, change nothing else
        info = classify(e) if not isinstance(e, OutcomeUnknown) else {"category": "unknown", "message": str(e)}
        st["last_observation_error"] = {"category": info["category"], "message": info["message"], "utc": _now()}
        actions.append(f"observation failed ({info['category']})")
    save_resources(state, res)
    if st.get("by_name") == "absent" or (st.get("status") == "DELETE_COMPLETE" and st.get("observed_by") == BY_ID):
        p = probe_bucket(state, clients, backend)
        actions.append(f"bucket probe: {p['result']}")
    res = load_resources(state)
    return {"stack": stack_report(res), "actions": actions, "operator_steps": operator_steps(res)}


def operator_steps(res: dict) -> list:
    """Precise manual steps for states this tool cannot settle with its permissions."""
    rep = stack_report(res)
    st = res.get("stack") or {}
    name, region = st.get("name"), res.get("region")
    if rep["state"] in ("deletion_confirmed", "not_created", "none_recorded"):
        return []
    steps = []
    if not st.get("id"):
        steps += [
            f"Find the full StackId of {name}: CloudFormation console, region {region}, Stacks, filter "
            "'Deleted' (or 'Active'), open the stack and copy its Stack ID; or CloudTrail event history, event "
            "name CreateStack, responseElements.stackId.",
            "Then run: recover --state STATE --profile P --stack-id 'arn:aws:cloudformation:...' "
            "(read-only; it reads that StackId and probes the bucket).",
        ]
    if rep["state"] == "deletion_requested":
        steps.append("Run recover (read-only) to read the final status by StackId; rerun cleanup only if the stack "
                     "is not deleting.")
    if rep["state"] == "resources_present":
        steps.append("Run cleanup; if it keeps the stack, inspect the reported objects in the S3 console before "
                     "deciding anything by hand.")
    if rep["state"] == "verification_unavailable" and st.get("last_observation_error"):
        steps.append("The last read failed (" + st["last_observation_error"]["category"] + "); fix access or the "
                     "network, then rerun recover.")
    return steps


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

CLEANUP_EXIT = {"none_recorded": 0, "not_created": 0, "deletion_confirmed": 0, "resources_present": 1,
                "ownership_refused": 1,
                "deletion_requested": 4, "verification_unavailable": 4}


def cleanup(state: Path, clients, backend: str, sleep=time.sleep) -> dict:
    """Delete exactly the recorded objects, then the stack only if the bucket is empty.

    The result's ``cleanup_state`` is one of: ``none_recorded``, ``not_created``,
    ``deletion_confirmed`` (DELETE_COMPLETE read by StackId and the bucket
    absent), ``deletion_requested`` (DeleteStack sent, completion not
    observed), ``verification_unavailable`` (AccessDenied, network, or no
    StackId) and ``resources_present``. Only observed state is reported; a
    missing stack by name is never presented as DELETE_COMPLETE.
    """
    deleted, kept, unknown, notes = [], [], [], []

    def result(error: dict | None = None, present: bool = False) -> dict:
        r = load_resources(state)
        rep = stack_report(r)
        out = {"cleanup_state": rep["state"], "stack": rep, "objects_deleted": deleted, "kept": kept,
               "unknown_keys": unknown, "notes": notes, "operator_steps": operator_steps(r)}
        if present and rep["state"] not in ("verification_unavailable", "deletion_requested"):
            out["cleanup_state"] = "resources_present"
        if error:
            out["error"] = error
            if not error.get("definite") and rep["state"] != "deletion_requested":
                out["cleanup_state"] = "verification_unavailable"
            elif out["cleanup_state"] == "deletion_confirmed":
                out["cleanup_state"] = "resources_present"
        return out

    res = load_resources(state)
    st = res.get("stack")
    if not st or st.get("status") == CREATE_REJECTED:
        return result()
    if stack_report(res)["state"] == "deletion_confirmed":
        notes.append("deletion was already confirmed by StackId; nothing was sent")
        return result()
    if not st.get("id"):
        if st.get("status") != LEGACY_DELETED and st.get("by_name") != "absent":
            recover(state, clients, backend)  # read-only: adopt the StackId of a live, correctly tagged stack
            res = load_resources(state)
            st = res["stack"]
        if not st.get("id"):
            if (res.get("bucket_probe") or {}).get("result") != "absent":
                probe_bucket(state, clients, backend)
            notes.append("no StackId: nothing was deleted and DELETE_COMPLETE cannot be verified")
            return result()

    # Observe the stack by its exact StackId before acting.
    try:
        s = describe_stack(clients.cfn, st["id"])
        if s is None:
            raise OutcomeUnknown("CloudFormation reports no stack for the recorded StackId")
    except Exception as e:  # noqa: BLE001
        info = _info(e)
        st["last_observation_error"] = {"category": info["category"], "message": info["message"], "utc": _now()}
        save_resources(state, res)
        return result({"phase": "describe_stack", **info, "definite": False})
    # FLH-068: the answer must be exactly the recorded stack (StackId and name) before it is recorded, and a
    # live stack must carry this state's task/state tags before anything destructive is sent.
    problems = ownership_problems(s, res)
    if s.get("StackStatus") == "DELETE_COMPLETE":
        problems = [p for p in problems if "tags" not in p]  # nothing destructive follows a deleted stack
    if problems:
        st["ownership_refused"] = {"problems": problems, "utc": _now()}
        save_resources(state, res)
        notes.append("refused before any delete: " + "; ".join(problems))
        return result()
    st.pop("ownership_refused", None)
    _observe(st, s["StackStatus"], BY_ID)
    save_resources(state, res)
    if st["status"] == "DELETE_IN_PROGRESS":
        try:
            _wait_and_record(state, res, clients.cfn, ("DELETE_COMPLETE",), sleep)
        except OutcomeUnknown as e:
            return result({"phase": "wait_delete", "category": "unknown", "message": str(e), "definite": False})
    if st["status"] == "DELETE_COMPLETE":
        probe_bucket(state, clients, backend)
        return result()

    # Owned objects: each is re-read before it is deleted, so a rerun never acts blindly.
    led = Ledger(state)
    b, owner = res["bucket"], res["account"]
    try:
        for obj in list(res["objects"]):
            key = obj["key"]
            with charged(led, "s3_head_object", {"s3_get_requests": 1}, {"key": key}, backend):
                try:
                    head = clients.s3.head_object(Bucket=b, Key=key, ExpectedBucketOwner=owner)
                except Exception as e:  # noqa: BLE001
                    if error_code(e) in ("404", "NoSuchKey", "NotFound", "NoSuchBucket"):
                        head = None
                    else:
                        raise
            if head is None:  # already gone (deleted by an earlier run whose answer was lost, or expired)
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
        try:
            unknown = list_keys(state, clients, backend)
        except Exception as e:  # noqa: BLE001
            if error_code(e) != "NoSuchBucket":
                raise
    except Exception as e:  # noqa: BLE001 - stop; the record still lists every object not proven gone
        info = _info(e)
        notes.append("stopped in the object phase; rerun cleanup: it re-reads each recorded object first")
        return result({"phase": "objects", **info, "definite": is_definite_rejection(e)}, present=True)
    if kept or unknown:
        notes.append(f"stack kept: the bucket is not empty ({len(unknown)} object(s)); nothing unknown was deleted")
        return result(present=True)
    try:
        verify_tags_only(state, clients, backend)
    except VerificationError:
        notes.append("stack kept: bucket tags do not identify this state directory")
        return result(present=True)
    except Exception as e:  # noqa: BLE001
        if error_code(e) != "NoSuchBucket":
            info = _info(e)
            return result({"phase": "bucket_tags", **info, "definite": is_definite_rejection(e)}, present=True)

    # DeleteStack by StackId. Recorded before sending; a new token only after a fresh observation.
    attempts = st.setdefault("delete_attempts", [])
    token = f"{st['name']}-delete" if not attempts else f"{st['name']}-delete-{len(attempts) + 1}"
    attempt = {"token": token, "requested_utc": _now(), "from_status": st["status"], "outcome": "sending"}
    attempts.append(attempt)
    prev = {k: st.get(k) for k in ("status", "observed_utc", "observed_by")}
    _observe(st, DELETE_REQUESTED, "local")
    save_resources(state, res)
    try:
        clients.cfn.delete_stack(StackName=st["id"], ClientRequestToken=token)
    except Exception as e:  # noqa: BLE001
        info = _info(e)
        attempt.update({"outcome": "rejected" if is_definite_rejection(e) else "unknown",
                        "category": info["category"]})
        if is_definite_rejection(e):
            st.update(prev)  # AWS refused the request: the status read just before it still holds
        save_resources(state, res)
        return result({"phase": "delete_stack", **info, "definite": is_definite_rejection(e)},
                      present=is_definite_rejection(e))
    attempt["outcome"] = "accepted"
    save_resources(state, res)
    try:
        status = _wait_and_record(state, res, clients.cfn, ("DELETE_COMPLETE",), sleep)
    except OutcomeUnknown as e:
        return result({"phase": "wait_delete", "category": "unknown", "message": str(e), "definite": False})
    if status == "DELETE_COMPLETE":
        probe_bucket(state, clients, backend)
    return result()


def _info(e: BaseException) -> dict:
    if isinstance(e, OutcomeUnknown):
        return {"category": "unknown", "error_type": "OutcomeUnknown", "code": None, "message": str(e)}
    i = classify(e)
    return {k: i[k] for k in ("category", "error_type", "code", "message", "guidance")}


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
