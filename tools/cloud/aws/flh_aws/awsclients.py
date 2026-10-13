"""AWS clients from an explicitly named profile and region.

boto3 resolves the profile through its normal mechanisms (config, SSO cache,
credential process); this module never reads, prints or stores a credential.
Retries are off (one attempt per request) and timeouts are bounded.
"""

from __future__ import annotations

from types import SimpleNamespace

from .snapshot import Refused


def aws_clients(profile: str, region: str) -> SimpleNamespace:
    if not profile:
        raise Refused("live commands need an explicit --profile")
    if not region:
        raise Refused("live commands need an explicit --region")
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise Refused("boto3 is not installed: python3 -m pip install -r tools/cloud/aws/requirements.txt "
                      "(in a virtual environment)") from None
    cfg = Config(region_name=region, retries={"total_max_attempts": 1, "mode": "standard"},
                 connect_timeout=5, read_timeout=60, signature_version="v4")
    session = boto3.Session(profile_name=profile, region_name=region)
    return SimpleNamespace(
        s3=session.client("s3", config=cfg),
        cfn=session.client("cloudformation", config=cfg),
        sts=session.client("sts", config=cfg, endpoint_url=f"https://sts.{region}.amazonaws.com"),
        bedrock_runtime=session.client("bedrock-runtime", config=cfg),
        bedrock=session.client("bedrock", config=cfg),
    )
