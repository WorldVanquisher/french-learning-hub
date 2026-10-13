"""Operator CLI: ``python3 -m flh_aws <command> --state DIR ...`` (run from tools/cloud/aws).

A state directory is bound to one backend at ``init``: ``aws`` (real, needs an
explicit --profile and --region) or ``fake`` (local filesystem fakes; nothing
leaves the machine). Fake and live budgets therefore never mix.

Exit codes: 0 OK; 1 failure (AWS error or failed verification); 2 usage or
refusal, including whole-plan budget pre-checks (nothing sent); 3 a single call
would exceed a cap (that call is not sent).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import TOOL_VERSION
from .ledger import DEFAULT_CAPS, MAX_CHARS_PER_INPUT, CapExceeded, Ledger, utc_now
from .snapshot import Refused, VerificationError, check_outside_repo, make_package, new_run_id, write_json

STATE_MARK = ".flh063-state"
PRICES = {  # AWS Price List API, read without credentials; see docs/plans/FLH-063-*.md
    "source": "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{AmazonBedrock,AmazonS3}/current/region_index.json",
    "bedrock_publication": "2026-10-10T18:22:42Z", "s3_publication": "2026-10-12T23:11:02Z",
    "region": "ca-central-1",
    "titan_v2_input_per_1k_tokens_usd": 0.0001,          # CAN1-TitanEmbeddingV2-Text-input-tokens
    "s3_standard_per_gb_month_usd": 0.025,               # CAN1-TimedStorage-ByteHrs, first 50 TB
    "s3_put_list_per_1k_usd": 0.0055,                    # CAN1-Requests-Tier1
    "s3_get_other_per_10k_usd": 0.0044,                  # CAN1-Requests-Tier2
    "data_transfer_out_per_gb_usd_assumed": 0.15,        # assumption, not read from the price list
}


def cost_estimate(caps: dict, retention_days: int) -> dict:
    gb = 1024 ** 3
    est = {
        "titan_tokens_upper_bound": caps["bedrock_input_chars"],  # conservative: <= 1 token per character
        "titan_usd": caps["bedrock_input_chars"] / 1000 * PRICES["titan_v2_input_per_1k_tokens_usd"],
        "s3_storage_usd": caps["s3_put_bytes"] / gb * PRICES["s3_standard_per_gb_month_usd"] * retention_days / 30,
        "s3_put_list_usd": (caps["s3_put_requests"] + caps["s3_list_requests"]) / 1000 * PRICES["s3_put_list_per_1k_usd"],
        "s3_get_other_usd": (caps["s3_get_requests"] + caps["s3_delete_requests"]) / 10000 * PRICES["s3_get_other_per_10k_usd"],
        "transfer_out_usd": caps["s3_get_bytes"] / gb * PRICES["data_transfer_out_per_gb_usd_assumed"],
    }
    est["total_upper_bound_usd"] = round(sum(v for k, v in est.items() if k.endswith("_usd")), 4)
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in est.items()}


def _state(args, must_exist=True) -> Path:
    s = check_outside_repo(Path(args.state), "--state")
    if must_exist and not (s / STATE_MARK).is_file():
        raise Refused(f"{s} is not an initialized FLH-063 state directory (run init)")
    return s


def _backend(state: Path) -> str:
    return json.loads((state / "state.json").read_text())["backend"]


def _clients(state: Path, args, region: str | None):
    backend = _backend(state)
    if backend == "fake":
        from .fakes import fake_clients
        return backend, fake_clients(state / "fake-aws", region or "ca-central-1")
    from .awsclients import aws_clients
    return backend, aws_clients(getattr(args, "profile", None), region)


def _need_live(backend: str, args) -> None:
    if backend == "aws" and not getattr(args, "allow_live", False):
        raise Refused("this command writes to, deletes from or invokes AWS: pass --allow-live")


def _bucket_region(state: Path) -> str | None:
    from .s3store import load_resources
    return load_resources(state).get("region")


def _evidence(state: Path, name: str, data: dict) -> None:
    ev = state / "evidence"
    ev.mkdir(exist_ok=True)
    stamp = utc_now().replace(":", "").replace(".", "")
    write_json(ev / f"{stamp}-{name}.json", data)


def _packages(state: Path) -> dict:
    p = state / "packages.json"
    return json.loads(p.read_text()) if p.exists() else {}


def cmd_init(args):
    s = _state(args, must_exist=False)
    if s.exists() and any(s.iterdir()):
        raise Refused(f"{s} exists and is not empty")
    s.mkdir(parents=True, exist_ok=True)
    write_json(s / "state.json", {"schema": "flh063_state_v1", "backend": args.backend, "created_utc": utc_now(),
                                  "tool": TOOL_VERSION})
    Ledger(s)
    (s / STATE_MARK).touch()
    return {"state": str(s), "backend": args.backend, "caps": DEFAULT_CAPS}


def cmd_plan(args):
    s = _state(args)
    caps = Ledger(s).read()["caps"]
    from .titan import MODEL_ID, RECOMMENDED_REGION, identity
    region = args.region
    return {
        "backend": _backend(s),
        "region_decision": {
            "requested": region, "recommended": RECOMMENDED_REGION,
            "basis": "AWS Bedrock 'Regional availability' lists Titan Text Embeddings V2 in ca-central-1 for "
                     "in-region inference; Geo and Global are not supported there. This tool never picks a region "
                     "or an inference profile; it uses exactly --region.",
            "warning": None if region == RECOMMENDED_REGION else "not the recommended Canadian region",
        },
        "model": {"id": MODEL_ID, "inference": "on-demand InvokeModel, base model id only",
                  "identity_if_dims": identity(region, args.dimensions) if args.dimensions else None},
        "resources": ["1 CloudFormation stack flh063-<id>", "1 S3 bucket flh063-<id> (SSE-S3, TLS-only, "
                      "public access blocked, expiration <= 14 days)"],
        "not_created": ["EC2/GPU", "NAT gateway", "provisioned throughput", "vector database",
                        "KMS key", "CloudTrail data events or extra logging", "always-on compute"],
        "caps": caps, "max_chars_per_input": MAX_CHARS_PER_INPUT,
        "prices": PRICES, "estimate": cost_estimate(caps, args.retention_days),
        "notes": ["Estimate, not a bill. Free tier is not assumed.",
                  "An AWS Budget alert is monitoring only, not a hard ceiling."],
    }


def cmd_deploy(args):
    s = _state(args)
    backend, c = _clients(s, args, args.region)
    _need_live(backend, args)
    from .s3store import deploy
    out = deploy(s, c, args.region, args.retention_days, backend)
    _evidence(s, "deploy", out)
    return out


def cmd_verify_bucket(args):
    s = _state(args)
    backend, c = _clients(s, args, _bucket_region(s))
    from .s3store import verify_bucket
    out = verify_bucket(s, c, backend)
    _evidence(s, "verify-bucket", out)
    return out


def cmd_snapshot(args):
    s = _state(args)
    run_id = new_run_id()
    pkg = s / "packages" / run_id
    (s / "packages").mkdir(exist_ok=True)
    out = make_package(Path(args.source_demo), pkg, run_id, args.source_revision)
    packages = _packages(s)
    packages[run_id] = {"dir": str(pkg), "manifest_sha256": out["manifest_sha256"],
                        "source_demo": str(Path(args.source_demo).resolve())}
    write_json(s / "packages.json", packages)
    summary = {"run_id": run_id, "package_dir": str(pkg), "manifest_sha256": out["manifest_sha256"],
               "snapshot": out["manifest"]["snapshot"], "domain": out["manifest"]["domain"]}
    _evidence(s, "snapshot", summary)
    return summary


def cmd_upload(args):
    s = _state(args)
    backend, c = _clients(s, args, _bucket_region(s))
    _need_live(backend, args)
    pkg = _packages(s).get(args.run)
    if not pkg:
        raise Refused(f"unknown run {args.run} (create it with snapshot)")
    from .s3store import upload
    out = upload(s, c, Path(pkg["dir"]), args.run, pkg["manifest_sha256"], backend)
    _evidence(s, "upload", out)
    return out


def cmd_restore(args):
    s = _state(args)
    backend, c = _clients(s, args, _bucket_region(s))
    from .restore import restore_from_s3
    try:
        out = restore_from_s3(s, c, args.run, Path(args.into), args.expect_manifest_sha256, backend)
    except VerificationError as e:
        _evidence(s, "restore-rejected", {"run_id": args.run, "into": args.into, "reason": str(e)})
        raise
    _evidence(s, "restore", out)
    return out


def cmd_restore_local(args):
    from .restore import restore_local
    return restore_local(Path(args.package), Path(args.into), args.expect_manifest_sha256)


def cmd_cleanup(args):
    s = _state(args)
    backend, c = _clients(s, args, _bucket_region(s))
    _need_live(backend, args)
    from .s3store import cleanup
    out = cleanup(s, c, backend)
    _evidence(s, "cleanup", out)
    if out.get("unknown_keys") or out.get("kept"):
        print(json.dumps(out, indent=2), file=sys.stderr)
        raise VerificationError("cleanup stopped: the bucket holds objects this state directory did not write")
    return out


def cmd_status(args):
    s = _state(args)
    from .s3store import load_resources
    led = Ledger(s).read()
    res = load_resources(s)
    res.pop("account", None)
    return {"backend": _backend(s), "used": led["used"], "caps": led["caps"],
            "calls": {"total": len(led["calls"]),
                      "failed": sum(1 for x in led["calls"] if x["outcome"] == "failed"),
                      "unfinished": sum(1 for x in led["calls"] if x["outcome"] == "attempted")},
            "resources": res, "packages": list(_packages(s))}


def cmd_titan_preflight(args):
    s = _state(args)
    backend, c = _clients(s, args, args.region)
    from .titan import preflight
    out = preflight(c.bedrock, args.region)
    _evidence(s, "titan-preflight", out)
    return out


def cmd_titan_smoke(args):
    s = _state(args)
    from .titan import MODEL_ID, check_model_and_dims, load_smoke_inputs, smoke
    check_model_and_dims(MODEL_ID, args.dimensions)
    inputs = load_smoke_inputs(Path(args.inputs)) if args.inputs else load_smoke_inputs()
    backend, c = _clients(s, args, args.region)
    _need_live(backend, args)
    out = smoke(s, c.bedrock_runtime, args.region, args.dimensions, backend, inputs)
    if out["error"]:
        print(json.dumps(out, indent=2), file=sys.stderr)
        raise VerificationError(f"smoke stopped at {out['error']['input']}: {out['error']['type']}")
    return out


def cmd_adapter(args):
    s = _state(args)
    from .titan import MODEL_ID, check_model_and_dims, identity
    check_model_and_dims(MODEL_ID, args.dimensions)
    backend, c = _clients(s, args, args.region)
    _need_live(backend, args)
    from .adapter import make_server
    srv = make_server(s, c.bedrock_runtime, args.region, args.dimensions, backend, "127.0.0.1", args.port)
    print(json.dumps({"listening": f"http://127.0.0.1:{args.port}/v1", "model": identity(args.region, args.dimensions),
                      "backend": backend, "note": "no AWS request is made until a POST arrives"}), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return {"stopped": True}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m flh_aws", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *, profile=False, region=False, live=False):
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn)
        if name != "restore-local":
            sp.add_argument("--state", required=True, help="absolute state directory outside the repository")
        if profile:
            sp.add_argument("--profile", help="AWS CLI profile name (aws backend)")
        if region:
            sp.add_argument("--region", required=True)
        if live:
            sp.add_argument("--allow-live", action="store_true", help="required for AWS writes/invocations")
        return sp

    sp = add("init", cmd_init)
    sp.add_argument("--backend", choices=("aws", "fake"), required=True)
    sp = add("plan", cmd_plan, region=True)
    sp.add_argument("--dimensions", type=int, choices=(256, 512, 1024))
    sp.add_argument("--retention-days", type=int, default=7)
    sp = add("deploy", cmd_deploy, profile=True, region=True, live=True)
    sp.add_argument("--retention-days", type=int, default=7)
    add("verify-bucket", cmd_verify_bucket, profile=True)
    sp = add("snapshot", cmd_snapshot)
    sp.add_argument("--source-demo", required=True, help="FLH-034 or FLH-060 demo directory")
    sp.add_argument("--source-revision", help="optional revision label you supply (no Git is run)")
    sp = add("upload", cmd_upload, profile=True, live=True)
    sp.add_argument("--run", required=True)
    sp = add("restore", cmd_restore, profile=True)
    sp.add_argument("--run", required=True)
    sp.add_argument("--into", required=True, help="new directory outside the repository and the source demo")
    sp.add_argument("--expect-manifest-sha256")
    sp = add("restore-local", cmd_restore_local)
    sp.add_argument("--package", required=True)
    sp.add_argument("--into", required=True)
    sp.add_argument("--expect-manifest-sha256", required=True)
    add("cleanup", cmd_cleanup, profile=True, live=True)
    add("status", cmd_status)
    add("titan-preflight", cmd_titan_preflight, profile=True, region=True)
    sp = add("titan-smoke", cmd_titan_smoke, profile=True, region=True, live=True)
    sp.add_argument("--dimensions", type=int, required=True, choices=(256, 512, 1024))
    sp.add_argument("--inputs", help="synthetic inputs file (default smoke_inputs.json)")
    sp = add("adapter", cmd_adapter, profile=True, region=True, live=True)
    sp.add_argument("--dimensions", type=int, required=True, choices=(256, 512, 1024))
    sp.add_argument("--port", type=int, required=True)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        out = args.fn(args)
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    except CapExceeded as e:
        print(f"cap reached: {e}", file=sys.stderr)
        return 3
    except VerificationError as e:
        print(f"verification failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - AWS/client errors; no credentials are in these messages
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
