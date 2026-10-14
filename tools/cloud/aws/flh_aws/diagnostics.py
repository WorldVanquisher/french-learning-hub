"""Secret-safe error categories for AWS failures (FLH-066).

``classify`` looks only at the exception's class names, its AWS error code,
HTTP status and message. It returns a bounded, sanitized summary with one
category and operator guidance. A category is chosen only on explicit evidence
(a documented error code, class or message phrase); anything else stays
``unknown``. Nothing here retries or changes a cap.
"""

from __future__ import annotations

import re

MAX_MESSAGE_CHARS = 300

# Category -> operator guidance. Retrying is always a manual operator decision.
GUIDANCE = {
    "missing_dependency": "This profile uses the `aws login` credential provider, which needs awscrt. Install the "
                          "pinned requirements (pip install -r tools/cloud/aws/requirements.txt) in the venv you run "
                          "and rerun the same command.",
    "profile_not_found": "The named --profile is not in your AWS config. Check the name with `aws configure list-profiles`.",
    "no_credentials": "The profile resolved no credentials. Sign in with your usual flow (for example "
                      "`aws login --profile P`) and rerun.",
    "expired_credentials": "The sign-in session or credentials are expired, missing or invalid. Sign in again "
                           "(`aws login --profile P`, or `aws sso login --profile P`) and rerun the same command.",
    "account_verification_pending": "AWS says the account is still being verified. Wait for AWS to finish (or contact "
                                    "AWS Support), then rerun only this command with the same --state. Do not redeploy "
                                    "S3 or reset the ledger.",
    "iam_denied": "The IAM identity is not allowed to perform this action. An administrator must attach the matching "
                  "policy from tools/cloud/aws/iam/ (with ACCOUNT_ID replaced); the tool never changes IAM.",
    "model_access_denied": "Bedrock model access for Amazon Titan Text Embeddings V2 is not granted in this region. "
                           "Request it in the Bedrock console, then rerun only this command.",
    "throttling": "AWS throttled the request. Wait, then rerun manually if the remaining budget allows; there is no "
                  "automatic retry.",
    "service_unavailable": "The AWS service reported a temporary failure. Rerun manually later if the budget allows.",
    "validation": "AWS rejected the request as invalid. This is a tool or input problem; do not retry unchanged.",
    "transport": "A network failure. The request may not have reached AWS, or reached it and the response was lost "
                 "(see may_have_been_processed). Check connectivity; for writes, run the read-only recovery first.",
    "response_invalid": "AWS answered, but the response failed this tool's checks. Keep the evidence; do not retry "
                        "unchanged.",
    "unknown": "The evidence does not identify the cause. Keep the evidence and inspect it before any rerun.",
}

_CREDENTIAL_CLASSES = {
    "MissingDependencyException": "missing_dependency",
    "ProfileNotFound": "profile_not_found",
    "NoCredentialsError": "no_credentials",
    "PartialCredentialsError": "no_credentials",
    "LoginInsufficientPermissions": "iam_denied",
    "LoginRefreshRequired": "expired_credentials",
    "LoginTokenLoadError": "expired_credentials",
    "LoginAuthorizationCodeError": "expired_credentials",
    "LoginError": "expired_credentials",
    "UnauthorizedSSOTokenError": "expired_credentials",
    "SSOTokenLoadError": "expired_credentials",
    "TokenRetrievalError": "expired_credentials",
    "CredentialRetrievalError": "expired_credentials",
}
# Transport failures: True when the request may have been received and processed.
_TRANSPORT_CLASSES = {
    "EndpointConnectionError": False,
    "ConnectTimeoutError": False,
    "ProxyConnectionError": False,
    "ReadTimeoutError": True,
    "ConnectionClosedError": True,
    "ResponseStreamingError": True,
    "IncompleteReadError": True,
    "SSLError": None,
    "HTTPClientError": None,
}
_EXPIRED_CODES = {"ExpiredToken", "ExpiredTokenException", "RequestExpired", "InvalidClientTokenId",
                  "UnrecognizedClientException", "InvalidSignatureException", "SignatureDoesNotMatch",
                  "InvalidAccessKeyId", "TokenRefreshRequired"}
_THROTTLE_CODES = {"ThrottlingException", "Throttling", "TooManyRequestsException", "SlowDown",
                   "RequestLimitExceeded"}
_UNAVAILABLE_CODES = {"ServiceUnavailableException", "ServiceUnavailable", "InternalServerException",
                      "InternalError", "ModelNotReadyException"}
_VALIDATION_CODES = {"ValidationException", "ValidationError", "SerializationException"}
_ACCESS_CODES = {"AccessDeniedException", "AccessDenied"}

ACCOUNT_VERIFICATION_PHRASE = "account is currently being verified"
_IAM_PHRASES = ("is not authorized to perform", "no identity-based policy allows", "explicit deny")
_MODEL_ACCESS_PHRASE = "don't have access to the model"


def sanitize(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    """Mask account ids and access-key ids, collapse whitespace and bound the length."""
    s = re.sub(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b", "<key-id>", str(text))
    s = re.sub(r"(?<!\d)\d{12}(?!\d)", "<account>", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[:limit] + "..."


def _class_names(e: BaseException) -> list:
    return [c.__name__ for c in type(e).__mro__]


def error_code(e: BaseException) -> str | None:
    resp = getattr(e, "response", None)
    if isinstance(resp, dict):
        return resp.get("Error", {}).get("Code")
    return None


def _status(e: BaseException) -> int | None:
    resp = getattr(e, "response", None)
    if isinstance(resp, dict):
        return resp.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return None


def _request_id(e: BaseException) -> str | None:
    resp = getattr(e, "response", None)
    if isinstance(resp, dict):
        return resp.get("ResponseMetadata", {}).get("RequestId")
    return None


def _message(e: BaseException) -> str:
    resp = getattr(e, "response", None)
    if isinstance(resp, dict) and resp.get("Error", {}).get("Message"):
        return resp["Error"]["Message"]
    return str(e)


def classify(e: BaseException) -> dict:
    """A bounded, secret-safe summary of one failure."""
    names = _class_names(e)
    code, status, msg = error_code(e), _status(e), _message(e)
    low = msg.lower()
    category, processed = None, None
    if code is not None:  # AWS answered: the request was received and rejected
        processed = False if status is not None and 400 <= status < 500 else None
        if code in _ACCESS_CODES:
            if ACCOUNT_VERIFICATION_PHRASE in low:
                category = "account_verification_pending"
            elif any(p in low for p in _IAM_PHRASES):
                category = "iam_denied"
            elif _MODEL_ACCESS_PHRASE in low:
                category = "model_access_denied"
        elif code in _EXPIRED_CODES:
            category = "expired_credentials"
        elif code in _THROTTLE_CODES:
            category = "throttling"
        elif code in _UNAVAILABLE_CODES:
            category = "service_unavailable"
        elif code in _VALIDATION_CODES:
            category = "validation"
    else:
        for n in names:
            if n in _CREDENTIAL_CLASSES:
                category, processed = _CREDENTIAL_CLASSES[n], False
                break
            if n in _TRANSPORT_CLASSES:
                category, processed = "transport", _TRANSPORT_CLASSES[n]
                break
        if category is None and "VerificationError" in names:
            category, processed = "response_invalid", True
        if category is None and any(n in ("TimeoutError", "ConnectionError") for n in names):
            category = "transport"
    category = category or "unknown"
    return {"category": category, "error_type": type(e).__name__, "code": code, "http_status": status,
            "request_id": _request_id(e), "message": sanitize(msg), "may_have_been_processed": processed,
            "guidance": GUIDANCE[category]}


def is_definite_rejection(e: BaseException) -> bool:
    """True only when AWS answered with a 4xx error: the request had no effect.

    AlreadyExists-style answers are excluded: they can mean an earlier attempt
    of ours already took effect.
    """
    code, status = error_code(e), _status(e)
    if code is None or status is None or not 400 <= status < 500:
        return False
    return code not in ("AlreadyExistsException", "TokenAlreadyExistsException", "ConditionalRequestConflict")
