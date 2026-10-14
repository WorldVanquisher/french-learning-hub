"""AWS clients from an explicitly named profile and region.

boto3 resolves the profile through its normal mechanisms (config, SSO or
`aws login` cache, credential process); this module never reads, prints or
stores a credential. Credentials are resolved once, in memory, before any
client is returned, so a missing dependency or an expired sign-in fails before
any AWS resource request. Retries are off (one attempt per request) and
timeouts are bounded.
"""

from __future__ import annotations

from types import SimpleNamespace

from .diagnostics import classify
from .snapshot import Refused


def sdk_versions() -> dict:
    """Installed SDK versions (None when absent). Imports nothing that contacts AWS."""
    out = {}
    for mod in ("boto3", "botocore", "awscrt"):
        try:
            from importlib.metadata import version
            out[mod] = version(mod)
        except Exception:  # noqa: BLE001 - absent or unreadable metadata
            out[mod] = None
    return out


def resolve_credentials(session, profile: str) -> str:
    """Resolve (and if needed refresh) the profile's credentials in memory.

    Returns botocore's credential method name (for example ``login`` or
    ``sso``), never a credential value. Raises Refused with category-specific,
    secret-safe guidance.
    """
    try:
        creds = session.get_credentials()
        if creds is None:
            raise NoCredentialsError()
        creds.get_frozen_credentials()  # forces a refresh of an expired session; values are discarded
    except Exception as e:  # noqa: BLE001 - every resolution failure becomes a refusal
        info = classify(e)
        hint = info["guidance"].replace("--profile P", f"--profile {profile}")
        raise Refused(f"credentials for profile {profile!r} could not be resolved "
                      f"[{info['category']}: {info['error_type']}]. {hint} No AWS resource request was sent.") from None
    return getattr(creds, "method", None) or "unknown"


class NoCredentialsError(Exception):
    """get_credentials() returned None (classified like botocore's class of the same name)."""


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
    try:
        session = boto3.Session(profile_name=profile, region_name=region)
    except Exception as e:  # noqa: BLE001 - ProfileNotFound and similar
        info = classify(e)
        raise Refused(f"profile {profile!r} cannot be used [{info['category']}: {info['error_type']}]. "
                      f"{info['guidance']} No AWS request was sent.") from None
    method = resolve_credentials(session, profile)
    cfg = Config(region_name=region, retries={"total_max_attempts": 1, "mode": "standard"},
                 connect_timeout=5, read_timeout=60, signature_version="v4")
    return SimpleNamespace(
        s3=session.client("s3", config=cfg),
        cfn=session.client("cloudformation", config=cfg),
        sts=session.client("sts", config=cfg, endpoint_url=f"https://sts.{region}.amazonaws.com"),
        bedrock_runtime=session.client("bedrock-runtime", config=cfg),
        bedrock=session.client("bedrock", config=cfg),
        credential_method=method,
    )
