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

from .diagnostics import classify
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


BINDING = "flh068_titan_request_v1"
BINDING_KEYS = ("binding", "model", "region", "dimensions", "normalize", "embedding_types", "text_convention",
                "identity", "input_sha256", "request_sha256")


def request_binding(region: str, dimensions: int, text: str) -> dict:
    """Everything that defines an InvokeModel result: model, region, dimensions, normalization, text
    convention, the exact input text and the exact request body (FLH-068)."""
    body = build_body(text, dimensions)
    return {"binding": BINDING, "model": MODEL_ID, "region": region, "dimensions": dimensions, "normalize": True,
            "embedding_types": ["float"], "text_convention": TEXT_CONVENTION, "identity": identity(region, dimensions),
            "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "request_sha256": hashlib.sha256(body).hexdigest()}


def invoke(ledger: Ledger, runtime, dimensions: int, text: str, backend: str, label: str, *, region: str) -> dict:
    """One InvokeModel call, reserved in the ledger first. Returns the vector and usage.

    The ledger record carries the full request binding, so a later continuation
    can tell exactly which request succeeded.
    """
    body = build_body(text, dimensions)
    amounts = {"bedrock_invocations": 1, "bedrock_input_chars": len(text), "bedrock_request_bytes": len(body)}
    with charged(ledger, "bedrock_invoke_model", amounts,
                 {"label": label, **request_binding(region, dimensions, text)}, backend) as out:
        t0 = time.monotonic()
        try:
            r = runtime.invoke_model(modelId=MODEL_ID, body=body, contentType="application/json",
                                     accept="application/json")
        except Exception as e:  # noqa: BLE001 - categorized in the ledger record, then re-raised
            info = classify(e)
            out.update({"error_category": info["category"], "error_code": info["code"],
                        "request_id": info["request_id"], "may_have_been_processed": info["may_have_been_processed"]})
            raise
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


def _invocations(state: Path) -> list:
    return [c for c in Ledger(state).read()["calls"] if c.get("kind") == "bedrock_invoke_model"]


def invocation_history(state: Path) -> dict:
    """Earlier InvokeModel records in this state's ledger, by outcome (failures stay counted)."""
    calls = _invocations(state)
    ok = [c for c in calls if c.get("outcome") == "ok"]
    return {"attempted_total": len(calls),
            "ok": len(ok),
            "ok_bound": sum(1 for c in ok if (c.get("detail") or {}).get("binding") == BINDING),
            "ok_unbound_legacy": sum(1 for c in ok if (c.get("detail") or {}).get("binding") != BINDING),
            "failed": sum(1 for c in calls if c.get("outcome") == "failed"),
            "unfinished": sum(1 for c in calls if c.get("outcome") == "attempted"),
            "failed_by_category": _count((c.get("result") or {}).get("error_category", "unrecorded")
                                         for c in calls if c.get("outcome") == "failed")}


def continuation_plan(state: Path, inputs: list, region: str, dimensions: int, backend: str) -> tuple:
    """Split inputs into (already done, still to send, reasons not reused).

    An input counts as done only when an ``ok`` record matches its label, the
    backend and every binding field exactly (FLH-068). Records without a
    binding (written before FLH-068) never qualify; they stay charged.
    """
    ok = [c for c in _invocations(state) if c.get("outcome") == "ok" and c.get("backend") == backend]
    done, todo, not_reused = [], [], []
    for it in inputs:
        want = request_binding(region, dimensions, it["text"])
        same_label = [c for c in ok if (c.get("detail") or {}).get("label") == it["id"]]
        if any(all((c["detail"]).get(k) == want[k] for k in BINDING_KEYS) for c in same_label):
            done.append(it["id"])
            continue
        todo.append(it)
        if same_label:
            legacy = all((c["detail"]).get("binding") != BINDING for c in same_label)
            not_reused.append({"input": it["id"], "reason": "legacy_unbound_record" if legacy else
                               "different_text_model_region_dimensions_or_convention"})
    return done, todo, not_reused


def _count(items) -> dict:
    out = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items()))


def smoke(state: Path, runtime, region: str, dimensions: int, backend: str, inputs: list,
          only_missing: bool = False) -> dict:
    """Embed each synthetic input once. Stops at the first failure; never retries.

    ``only_missing`` skips inputs whose exact request (text, model, region,
    dimensions, normalization, convention, backend) already has an ``ok``
    record in this state's ledger. It never resets a counter or raises a cap;
    every earlier attempt, failed ones included, stays charged.
    """
    led = Ledger(state)
    history = invocation_history(state)
    skipped, not_reused = [], []
    if only_missing:
        skipped, inputs, not_reused = continuation_plan(state, inputs, region, dimensions, backend)
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
            r = invoke(led, runtime, dimensions, it["text"], backend, it["id"], region=region)
        except Exception as e:  # noqa: BLE001 - stop at the first failure, recorded
            info = classify(e)
            error = {"input": it["id"], "type": info["error_type"], **{k: v for k, v in info.items()
                                                                       if k != "error_type"}}
            break
        vectors[it["id"]] = r.pop("vector")
        calls.append({"input": it["id"], "chars": len(it["text"]), **{k: v for k, v in r.items() if k != "tokens"}})
    ids = list(vectors)
    cos = {f"{a}|{b}": round(sum(x * y for x, y in zip(vectors[a], vectors[b])), 6)
           for i, a in enumerate(ids) for b in ids[i + 1:]}
    report = {"schema": "flh068_titan_smoke_v3", "backend": backend, "started_utc": started,
              "finished_utc": utc_now(), "region": region, "model_id": MODEL_ID, "identity": identity(region, dimensions),
              "dimensions": dimensions, "text_convention": TEXT_CONVENTION, "planned_calls": len(inputs),
              "only_missing": only_missing, "skipped_already_ok": skipped, "not_reused": not_reused,
              "ledger_history_before": history,
              "completed_calls": len(calls), "error": error, "calls": calls,
              "pairwise_cosine_exploratory": cos,
              "note": "cosine values are exploratory observations on synthetic inputs, not relevance or SAME judgments",
              "ledger_after": Ledger(state).read()["used"]}
    ev = Path(state) / "evidence"
    ev.mkdir(exist_ok=True)
    write_json(ev / f"titan-smoke-{started.replace(':', '').replace('.', '')}.json", report)
    return report
