"""Bounded local embedding HTTP service (FLH-054). Standard library only.

  POST /v1/embeddings  {"model": <deployment id>, "input": [<1..max_inputs strings>]}
       -> 200 {"object":"list","model":...,"data":[{"object":"embedding","index":i,"embedding":[...]}]}
  GET  /readyz    200 only after the model is loaded on the GPU and warmed up
  GET  /healthz   liveness (process up)
  GET  /manifest  the public deployment manifest
  GET  /metrics   counters and measured GPU placement/memory

Every input is validated (contract.adapt) and token-counted before any GPU
work; one bad input rejects the whole request. Errors use fixed, text-free
types. Nothing logs input text or request headers. No retry, no fallback.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from . import contract, manifest
from .encoder import Encoder, EncoderOutOfMemory

log = logging.getLogger("flh_e5")

# Readiness states.
STARTING, LOADING, WARMING, READY, STOPPING, STOPPED, FAILED = (
    "starting", "loading", "warming", "ready", "stopping", "stopped", "failed")

WARMUP_INPUTS = (
    '{"representation":"concept_search_query_v2","type":"query","text":"warmup"}',
    '{"representation":"concept_embedding_text_v1","type":"concept","target":"warmup","pedagogical_intent":"grammar","scope":"","identity_features":[]}',
)


@dataclass(frozen=True)
class Limits:
    max_inputs: int = 32
    max_input_bytes: int = 4096
    max_body_bytes: int = 262144
    microbatch: int = 8
    max_queue: int = 4           # requests admitted (running + waiting)
    queue_timeout_s: float = 30.0
    max_connections: int = 16
    socket_timeout_s: float = 30.0

    def validate(self) -> None:
        if not 1 <= self.max_inputs <= 32:
            raise ValueError("max_inputs must be 1..32")
        if not 1 <= self.microbatch <= self.max_inputs:
            raise ValueError("microbatch must be 1..max_inputs")
        if not 1 <= self.max_input_bytes <= 16384:
            raise ValueError("max_input_bytes must be 1..16384")
        if not 1024 <= self.max_body_bytes <= 4 << 20:
            raise ValueError("max_body_bytes must be 1 KiB..4 MiB")
        if not 1 <= self.max_queue <= 64 or not 1 <= self.max_connections <= 256:
            raise ValueError("max_queue must be 1..64 and max_connections 1..256")
        if not 0 < self.queue_timeout_s <= 600 or not 0 < self.socket_timeout_s <= 600:
            raise ValueError("timeouts must be in (0, 600] seconds")

    def public(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def validate_bind_host(host: str) -> str:
    """Loopback by default; a private (RFC 1918 / ULA) IP literal for NAS
    access. Never a wildcard or public address."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError("--host must be an IP literal (no host names)") from None
    if ip.is_loopback:
        return host
    if ip.is_unspecified or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        raise ValueError("--host must not be a wildcard, link-local, multicast or reserved address")
    private4 = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    if (ip.version == 4 and any(ip in n for n in private4)) or (ip.version == 6 and ip in ipaddress.ip_network("fc00::/7")):
        return host
    raise ValueError("--host must be loopback or a private RFC 1918 / ULA address; public binding is not supported")


class ApiError(Exception):
    def __init__(self, status: int, kind: str, message: str):
        super().__init__(message)
        self.status, self.kind, self.message = status, kind, message


@dataclass
class Counters:
    lock: threading.Lock = field(default_factory=threading.Lock)
    requests_total: int = 0
    requests_ok: int = 0
    rejected: dict = field(default_factory=dict)       # error type -> count
    input_positions: int = 0                           # accepted inputs that were encoded
    inputs_by_role: dict = field(default_factory=lambda: {"query": 0, "passage": 0})
    distinct_input_hashes: set = field(default_factory=set)
    distinct_cap: int = 100000
    distinct_overflow: bool = False
    computations: int = 0                              # encoder microbatch calls
    truncations: int = 0                               # always 0: overlength is rejected
    overlength_inputs: int = 0
    max_tokens_seen: int = 0
    encode_seconds: float = 0.0

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "requests_total": self.requests_total, "requests_ok": self.requests_ok,
                "rejected": dict(sorted(self.rejected.items())),
                "input_positions": self.input_positions, "inputs_by_role": dict(self.inputs_by_role),
                "distinct_input_hashes": len(self.distinct_input_hashes), "distinct_input_hashes_capped": self.distinct_overflow,
                "computations": self.computations, "truncations": self.truncations,
                "overlength_inputs": self.overlength_inputs, "max_tokens_seen": self.max_tokens_seen,
                "encode_seconds": round(self.encode_seconds, 6),
            }


class EmbeddingService:
    """State, limits and the request pipeline, independent of HTTP."""

    def __init__(self, encoder_factory: Callable[[], Encoder], manifest_factory: Callable[[Encoder], dict], limits: Limits):
        limits.validate()
        self.limits = limits
        self.encoder_factory, self.manifest_factory = encoder_factory, manifest_factory
        self.encoder: Encoder | None = None
        self.manifest: dict | None = None
        self.state = STARTING
        self.state_detail = ""
        self.warmup_ms: float | None = None
        self.counters = Counters()
        self.admission = threading.BoundedSemaphore(limits.max_queue)
        self.inference = threading.Lock()

    @property
    def deployment_id(self) -> str | None:
        return self.manifest["deployment_id"] if self.manifest else None

    def load(self) -> None:
        """Load the encoder, build the manifest, warm up. Ready only on success."""
        try:
            self.state = LOADING
            self.encoder = self.encoder_factory()
            self.manifest = self.manifest_factory(self.encoder)
            self.state = WARMING
            started = time.monotonic()
            texts = [contract.adapt(t).model_text for t in WARMUP_INPUTS]
            self._check_vectors(self.encoder.encode(texts), len(texts))
            self.warmup_ms = (time.monotonic() - started) * 1000
            self.state = READY
            log.info("ready: %s (warmup %.0f ms)", self.deployment_id, self.warmup_ms)
        except Exception as e:  # noqa: BLE001 - startup failure is reported, never hidden
            self.state, self.state_detail = FAILED, f"{type(e).__name__}: {e}"
            raise

    def close(self) -> None:
        self.state = STOPPING
        with self.inference:  # let a running computation finish
            if self.encoder is not None:
                self.encoder.close()
                self.encoder = None
        self.state = STOPPED

    def reject(self, err: ApiError) -> ApiError:
        with self.counters.lock:
            self.counters.rejected[err.kind] = self.counters.rejected.get(err.kind, 0) + 1
        return err

    def _check_vectors(self, vectors, n: int) -> None:
        dims = manifest.DIMENSIONS
        if not isinstance(vectors, list) or len(vectors) != n:
            raise ApiError(500, "invalid_model_output", "encoder returned the wrong number of vectors")
        for v in vectors:
            if len(v) != dims or not all(isinstance(x, float) and math.isfinite(x) for x in v):
                raise ApiError(500, "invalid_model_output", "encoder returned a malformed or non-finite vector")
            norm = math.sqrt(sum(x * x for x in v))
            if abs(norm - 1.0) > 1e-3:
                raise ApiError(500, "invalid_model_output", "encoder returned a vector that is not L2-normalized")

    def parse(self, body: bytes) -> tuple[list[contract.AdaptedInput], list[str]]:
        """Validate the whole request before any GPU work."""
        def reject_constant(_):
            raise ValueError("non-standard JSON constant")

        def no_dupes(pairs):
            d = {}
            for k, v in pairs:
                if k in d:
                    raise ValueError("duplicate key")
                d[k] = v
            return d
        try:
            req = json.loads(body.decode("utf-8"), object_pairs_hook=no_dupes, parse_constant=reject_constant)
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise ApiError(400, "invalid_request", "body must be UTF-8 JSON") from None
        if not isinstance(req, dict) or set(req) != {"model", "input"}:
            raise ApiError(400, "invalid_request", 'body must be exactly {"model": ..., "input": [...]}')
        if req["model"] != self.deployment_id:
            raise ApiError(400, "unknown_model", "model does not name this deployment (GET /manifest for its deployment_id)")
        inputs = req["input"]
        if not isinstance(inputs, list) or not inputs:
            raise ApiError(400, "invalid_request", "input must be a non-empty array of strings")
        if len(inputs) > self.limits.max_inputs:
            raise ApiError(413, "too_many_inputs", f"at most {self.limits.max_inputs} inputs per request")
        adapted = []
        for i, text in enumerate(inputs):
            if not isinstance(text, str):
                raise ApiError(400, "invalid_request", f"input {i} is not a string")
            if len(text.encode("utf-8")) > self.limits.max_input_bytes:
                raise ApiError(413, "input_too_large", f"input {i} exceeds {self.limits.max_input_bytes} UTF-8 bytes")
            try:
                adapted.append(contract.adapt(text))
            except contract.InputRejected as e:
                raise ApiError(422, "invalid_input", f"input {i}: {e} (accepted: {', '.join(contract.ACCEPTED_PAIRS)})") from None
        return adapted, inputs

    def count_request(self) -> None:
        with self.counters.lock:
            self.counters.requests_total += 1

    def embed(self, body: bytes) -> dict:
        """Run one request body. Rejections are counted here; the caller
        counts the request itself (count_request)."""
        try:
            if self.state != READY:
                raise ApiError(503, "not_ready", f"service is {self.state}")
            adapted, raw_inputs = self.parse(body)
            if not self.admission.acquire(blocking=False):
                raise ApiError(503, "overloaded", "request queue is full; not retried")
            try:
                if not self.inference.acquire(timeout=self.limits.queue_timeout_s):
                    raise ApiError(503, "overloaded", "timed out waiting for the GPU; not retried")
                try:
                    if self.state != READY or self.encoder is None:
                        raise ApiError(503, "not_ready", f"service is {self.state}")
                    vectors = self._encode_locked([a.model_text for a in adapted])
                finally:
                    self.inference.release()
            finally:
                self.admission.release()
        except ApiError as e:
            raise self.reject(e)
        with self.counters.lock:
            c = self.counters
            c.requests_ok += 1
            c.input_positions += len(adapted)
            for a in adapted:
                c.inputs_by_role[a.role] += 1
            for text in raw_inputs:
                if len(c.distinct_input_hashes) < c.distinct_cap:
                    c.distinct_input_hashes.add(hashlib.sha256(text.encode("utf-8")).digest())
                else:
                    c.distinct_overflow = True
        return {"object": "list", "model": self.deployment_id,
                "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)]}

    def _encode_locked(self, texts: list[str]) -> list[list[float]]:
        encoder = self.encoder
        counts = encoder.count_tokens(texts)
        with self.counters.lock:
            self.counters.max_tokens_seen = max([self.counters.max_tokens_seen, *counts])
        over = [i for i, n in enumerate(counts) if n > manifest.MAX_TOKENS]
        if over:
            with self.counters.lock:
                self.counters.overlength_inputs += len(over)
            raise ApiError(422, "input_too_long", f"input {over[0]} has {counts[over[0]]} tokens; the limit is {manifest.MAX_TOKENS} including the prefix (rejected, not truncated)")
        vectors: list[list[float]] = []
        mb = self.limits.microbatch
        for start in range(0, len(texts), mb):
            chunk = texts[start:start + mb]
            t0 = time.monotonic()
            try:
                out = encoder.encode(chunk)
            except EncoderOutOfMemory:
                raise ApiError(503, "gpu_out_of_memory", "GPU out of memory for this request; not retried, no fallback") from None
            except Exception:  # noqa: BLE001
                log.exception("encoder failure")  # traceback only; inputs are never logged
                raise ApiError(500, "encoder_error", "encoder failed") from None
            finally:
                with self.counters.lock:
                    self.counters.computations += 1
                    self.counters.encode_seconds += time.monotonic() - t0
            self._check_vectors(out, len(chunk))
            vectors.extend(out)
        return vectors

    def metrics(self) -> dict:
        gpu = None
        if self.encoder is not None:
            try:
                gpu = self.encoder.gpu_evidence()
            except Exception as e:  # noqa: BLE001
                gpu = {"error": type(e).__name__}
        return {"state": self.state, "deployment_id": self.deployment_id, "warmup_ms": self.warmup_ms,
                "counters": self.counters.snapshot(), "gpu": gpu, "limits": self.limits.public()}


class _Handler(BaseHTTPRequestHandler):
    server_version = "flh-e5/1"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    @property
    def svc(self) -> EmbeddingService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):  # default logging would print request lines only; keep it off
        pass

    def _send(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, err: ApiError) -> None:
        self._send(err.status, {"error": {"type": err.kind, "message": err.message}})

    def do_GET(self):  # noqa: N802
        svc = self.svc
        if self.path == "/readyz":
            ok = svc.state == READY
            self._send(200 if ok else 503, {"ready": ok, "state": svc.state, "deployment_id": svc.deployment_id if ok else None})
        elif self.path == "/healthz":
            self._send(200, {"alive": True, "state": svc.state})
        elif self.path == "/manifest" and svc.manifest is not None:
            self._send(200, svc.manifest)
        elif self.path == "/metrics":
            self._send(200, svc.metrics())
        else:
            self._error(ApiError(404, "not_found", "unknown path"))

    def do_POST(self):  # noqa: N802
        started = time.monotonic()
        status, kind, n = 200, "", 0
        svc = self.svc
        svc.count_request()
        try:
            try:
                if self.path != "/v1/embeddings":
                    raise ApiError(404, "not_found", "POST /v1/embeddings only")
                length = self.headers.get("Content-Length")
                if length is None or not length.isdigit():
                    raise ApiError(411, "length_required", "Content-Length is required")
                if int(length) > svc.limits.max_body_bytes:
                    raise ApiError(413, "request_too_large", f"body exceeds {svc.limits.max_body_bytes} bytes")
                body = self.rfile.read(int(length))
                if len(body) != int(length):
                    raise ApiError(400, "invalid_request", "incomplete body")
            except ApiError as e:
                raise svc.reject(e)
            payload = svc.embed(body)  # counts its own rejections
            n = len(payload["data"])
            self._send(200, payload)
        except ApiError as e:
            status, kind = e.status, e.kind
            self._error(e)
        except (ConnectionError, TimeoutError):
            status, kind = 499, "client_disconnected"
        finally:
            log.info("POST %s %d %s inputs=%d %.1fms", self.path, status, kind or "ok", n, (time.monotonic() - started) * 1000)

    def do_PUT(self):  # noqa: N802
        self._error(ApiError(405, "method_not_allowed", "method not allowed"))

    do_DELETE = do_PATCH = do_PUT


class EmbeddingHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False

    def __init__(self, address, service: EmbeddingService):
        self.service = service
        self.connections = threading.BoundedSemaphore(service.limits.max_connections)
        super().__init__(address, _Handler)

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(self.service.limits.socket_timeout_s)
        return sock, addr

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            try:
                body = b'{"error":{"type":"overloaded","message":"too many connections"}}'
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: "
                                + str(len(body)).encode() + b"\r\n\r\n" + body)
            except OSError:
                pass
            with self.service.counters.lock:
                self.service.counters.rejected["too_many_connections"] = self.service.counters.rejected.get("too_many_connections", 0) + 1
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()
