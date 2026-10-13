"""Amazon Titan Text Embeddings V2 on Bedrock: request/response contract,
read-only preflight and a bounded smoke.

Text convention ``flh_titan_verbatim_v1``: the input string is sent unchanged
as ``inputText``. No E5 ``query: ``/``passage: `` prefix is added; Titan V2 has
no such role convention. The identity therefore names model, region,
dimensions and normalization, and is never equal to any E5 identity.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from .ledger import MAX_CHARS_PER_INPUT, Ledger, charged, utc_now
from .snapshot import Refused, VerificationError, write_json

MODEL_ID = "amazon.titan-embed-text-v2:0"
ALLOWED_DIMENSIONS = (256, 512, 1024)
TEXT_CONVENTION = "flh_titan_verbatim_v1"
RECOMMENDED_REGION = "ca-central-1"
MAX_RESPONSE_BYTES = 1 << 20
SMOKE_INPUTS = Path(__file__).resolve().parents[1] / "smoke_inputs.json"
MAX_SMOKE_CALLS = 10
# Inference-profile ids start with a geography; this task allows on-demand
# in-region invocation of the base model only.
PROFILE_PREFIXES = ("us.", "eu.", "apac.", "ca.", "jp.", "au.", "us-gov.", "global.")


def identity(region: str, dimensions: int) -> str:
    return f"bedrock/{MODEL_ID}/{region}/d{dimensions}/normalize/{TEXT_CONVENTION}"


def check_model_and_dims(model_id: str, dimensions: int) -> None:
    if model_id.startswith(PROFILE_PREFIXES) or model_id != MODEL_ID:
        raise Refused(f"only the on-demand base model {MODEL_ID} is allowed (no inference profile)")
    if dimensions not in ALLOWED_DIMENSIONS:
        raise Refused(f"--dimensions must be one of {ALLOWED_DIMENSIONS}")


def build_body(text: str, dimensions: int) -> bytes:
    if not isinstance(text, str) or not text.strip():
        raise Refused("Titan V2 requires a non-empty string")
    if len(text) > MAX_CHARS_PER_INPUT:
        raise Refused(f"input has {len(text)} characters; this tool's per-input cap is {MAX_CHARS_PER_INPUT}")
    return json.dumps({"inputText": text, "dimensions": dimensions, "normalize": True,
                       "embeddingTypes": ["float"]}, ensure_ascii=False).encode("utf-8")


def parse_response(raw: bytes, dimensions: int) -> tuple[list, int]:
    try:
        d = json.loads(raw)
    except ValueError:
        raise VerificationError("Titan response is not JSON") from None
    vec = d.get("embedding")
    if not isinstance(vec, list) or len(vec) != dimensions:
        raise VerificationError(f"embedding has {len(vec) if isinstance(vec, list) else 'no'} values, expected {dimensions}")
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in vec):
        raise VerificationError("embedding contains a non-finite or non-numeric value")
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        raise VerificationError("embedding is the zero vector")
    if abs(norm - 1.0) > 1e-3:
        raise VerificationError(f"normalize=true but the norm is {norm}")
    by_type = d.get("embeddingsByType", {}).get("float")
    if by_type is not None and by_type != vec:
        raise VerificationError("embeddingsByType.float differs from embedding")
    tokens = d.get("inputTextTokenCount")
    if not isinstance(tokens, int) or tokens <= 0:
        raise VerificationError("inputTextTokenCount missing or not positive")
    return vec, tokens


def invoke(ledger: Ledger, runtime, dimensions: int, text: str, backend: str, label: str) -> dict:
    """One InvokeModel call, reserved in the ledger first. Returns the vector and usage."""
    body = build_body(text, dimensions)
    amounts = {"bedrock_invocations": 1, "bedrock_input_chars": len(text), "bedrock_request_bytes": len(body)}
    with charged(ledger, "bedrock_invoke_model", amounts,
                 {"label": label, "model": MODEL_ID, "dimensions": dimensions}, backend) as out:
        t0 = time.monotonic()
        r = runtime.invoke_model(modelId=MODEL_ID, body=body, contentType="application/json",
                                 accept="application/json")
        raw = r["body"].read(MAX_RESPONSE_BYTES + 1)
        out["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
        out["request_id"] = r.get("ResponseMetadata", {}).get("RequestId")
        headers = r.get("ResponseMetadata", {}).get("HTTPHeaders", {})
        out["header_input_token_count"] = headers.get("x-amzn-bedrock-input-token-count")
        if len(raw) > MAX_RESPONSE_BYTES:
            raise VerificationError("Titan response exceeded the size bound")
        vec, tokens = parse_response(raw, dimensions)
        out["input_text_token_count"] = tokens
        out["norm"] = math.sqrt(sum(x * x for x in vec))
        out["vector_sha256"] = hashlib.sha256(json.dumps(vec).encode()).hexdigest()
    return {"vector": vec, "tokens": tokens, **out}


def preflight(control, region: str) -> dict:
    """Read-only GetFoundationModel: the model must be ACTIVE with ON_DEMAND inference."""
    d = control.get_foundation_model(modelIdentifier=MODEL_ID)["modelDetails"]
    report = {"region": region, "model_id": d.get("modelId"), "model_arn": d.get("modelArn"),
              "lifecycle": d.get("modelLifecycle", {}).get("status"),
              "inference_types": d.get("inferenceTypesSupported"),
              "output_modalities": d.get("outputModalities")}
    problems = []
    if d.get("modelId") != MODEL_ID:
        problems.append(f"model id {d.get('modelId')}")
    if report["lifecycle"] != "ACTIVE":
        problems.append(f"lifecycle {report['lifecycle']}")
    if "ON_DEMAND" not in (report["inference_types"] or []):
        problems.append("ON_DEMAND not supported in this region")
    if "EMBEDDING" not in (report["output_modalities"] or []):
        problems.append("not an embedding model")
    if problems:
        raise VerificationError("preflight failed: " + "; ".join(problems))
    return report


def load_smoke_inputs(path: Path = SMOKE_INPUTS) -> list:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("data_classification") != "synthetic":
        raise Refused("smoke inputs must be marked synthetic")
    items = d["inputs"]
    if not 1 <= len(items) <= MAX_SMOKE_CALLS:
        raise Refused(f"smoke needs 1..{MAX_SMOKE_CALLS} inputs")
    for it in items:
        if not isinstance(it.get("id"), str) or not isinstance(it.get("text"), str):
            raise Refused("each smoke input needs string id and text")
    return items


def smoke(state: Path, runtime, region: str, dimensions: int, backend: str, inputs: list) -> dict:
    """Embed each synthetic input once. Stops at the first failure; never retries."""
    led = Ledger(state)
    rem = led.remaining()
    bodies = [build_body(it["text"], dimensions) for it in inputs]
    need = {"bedrock_invocations": len(inputs), "bedrock_input_chars": sum(len(i["text"]) for i in inputs),
            "bedrock_request_bytes": sum(len(b) for b in bodies)}
    short = {k: (v, rem[k]) for k, v in need.items() if v > rem[k]}
    if short:
        raise Refused(f"smoke needs more than the remaining budget {short}; nothing sent")
    calls, vectors, error = [], {}, None
    started = utc_now()
    for it in inputs:
        try:
            r = invoke(led, runtime, dimensions, it["text"], backend, it["id"])
        except Exception as e:  # noqa: BLE001 - stop at the first failure, recorded
            error = {"input": it["id"], "type": type(e).__name__, "message": str(e)[:300]}
            break
        vectors[it["id"]] = r.pop("vector")
        calls.append({"input": it["id"], "chars": len(it["text"]), **{k: v for k, v in r.items() if k != "tokens"}})
    ids = list(vectors)
    cos = {f"{a}|{b}": round(sum(x * y for x, y in zip(vectors[a], vectors[b])), 6)
           for i, a in enumerate(ids) for b in ids[i + 1:]}
    report = {"schema": "flh063_titan_smoke_v1", "backend": backend, "started_utc": started,
              "finished_utc": utc_now(), "region": region, "model_id": MODEL_ID, "identity": identity(region, dimensions),
              "dimensions": dimensions, "text_convention": TEXT_CONVENTION, "planned_calls": len(inputs),
              "completed_calls": len(calls), "error": error, "calls": calls,
              "pairwise_cosine_exploratory": cos,
              "note": "cosine values are exploratory observations on synthetic inputs, not relevance or SAME judgments",
              "ledger_after": Ledger(state).read()["used"]}
    ev = Path(state) / "evidence"
    ev.mkdir(exist_ok=True)
    write_json(ev / f"titan-smoke-{started.replace(':', '').replace('.', '')}.json", report)
    return report
