"""Local French transcription service (``flh_speaking_transcription_v1``).

It answers FLH's existing Go transcription client unchanged
(``POST {OPENAI_BASE_URL}/audio/transcriptions``, multipart ``file``, ``model``,
``response_format=json``) with ``{"text": ...}`` plus an ``flh`` block.

* Binds loopback or a private address only; no authentication (the Bearer
  header is ignored and never logged). Not a public service.
* Readiness: ``/readyz`` is 503 while loading or warming and turns 200 only
  after a warm-up inference through the real model succeeded.
* Limits: request bytes, audio bytes and seconds, accepted containers, one
  inference at a time with a bounded wait queue (429 when full), a read
  timeout and an inference deadline (504).
* Audio is decoded in memory and dropped after the response; nothing is
  written to disk, cached or logged. Logs carry status, sizes and timings only.
* No retries and no de-duplication: a repeated request re-runs inference and,
  decoding being deterministic, returns the same text. ``audio_sha256`` lets a
  client match a response to what it sent.
* An abstention (``no_speech``/``not_french``) is HTTP 200 with empty ``text``:
  FLH then records "no usable transcript" and the learner types the text.
"""

from __future__ import annotations

import email.parser
import email.policy
import hashlib
import ipaddress
import json
import os
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from . import audio, deployment, model

SCHEMA = "flh_speaking_transcription_v1"
FIELDS = {"file", "model", "response_format", "language"}


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


class State:
    def __init__(self, model_dir: str, threads: int, max_waiting: int, limits: dict, loader=None, manifest_fn=None):
        self.model_dir, self.threads, self.limits = model_dir, threads, limits
        self.status, self.reason = "starting", ""
        self.manifest: dict = {}
        self.tr = None
        self.lock = threading.Lock()  # one inference at a time
        self.slots = threading.BoundedSemaphore(1 + max_waiting)
        self.loader = loader or (lambda d, t: model.Transcriber(d, threads=t))
        self.manifest_fn = manifest_fn or deployment.manifest
        self.counters = {"requests": 0, "transcribed": 0, "abstained": 0, "refused": 0, "busy": 0, "timeouts": 0, "errors": 0}
        self.load_s = self.warm_s = None

    def load(self):
        try:
            self.status = "loading"
            self.manifest = self.manifest_fn(self.model_dir)
            t0 = time.monotonic()
            self.tr = self.loader(self.model_dir, self.threads)
            self.load_s = round(time.monotonic() - t0, 3)
            self.status = "warming"
            t0 = time.monotonic()
            rng = np.random.default_rng(0)
            probe = (rng.standard_normal(2 * audio.SAMPLE_RATE) * 0.01).astype(np.float32)
            out = self.tr.raw([probe])  # exercises encoder and decoder, whatever the abstention rules say
            if not out or not (0.0 <= out[0]["no_speech_prob"] <= 1.0) or not np.isfinite(out[0]["avg_logprob"]):
                raise RuntimeError("warm-up inference returned an unusable result")
            self.warm_s = round(time.monotonic() - t0, 3)
            self.status = "ready"
        except Exception as exc:  # stays failed; /readyz reports it
            self.status, self.reason = "failed", f"{type(exc).__name__}"
            print(json.dumps({"event": "startup_failed", "reason": self.reason}), file=sys.stderr, flush=True)


def parse_multipart(content_type: str, body: bytes) -> dict[str, bytes]:
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    if not msg.is_multipart():
        raise ServiceError(400, "invalid_request", "expected multipart/form-data")
    out: dict[str, bytes] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            raise ServiceError(400, "invalid_request", "a form part has no name")
        if name in out:
            raise ServiceError(400, "invalid_request", f"duplicate form field {name!r}")
        if name not in FIELDS:
            raise ServiceError(400, "invalid_request", f"unsupported form field {name!r}")
        out[name] = part.get_payload(decode=True) or b""
    return out


def transcribe_request(state: State, fields: dict[str, bytes]) -> dict:
    lim = state.limits
    if "file" not in fields:
        raise ServiceError(400, "invalid_request", "missing form field 'file'")
    want = fields.get("model", b"").decode("utf-8", "replace")
    if want != state.manifest["deployment_id"]:
        raise ServiceError(400, "unknown_model", "model must equal this service's deployment_id (GET /manifest)")
    if fields.get("response_format", b"json") != b"json":
        raise ServiceError(400, "invalid_request", "only response_format=json is supported")
    if fields.get("language", b"fr") != b"fr":
        raise ServiceError(400, "invalid_request", "only French (language=fr) is transcribed")
    data = fields["file"]
    if len(data) > lim["max_audio_bytes"]:
        raise ServiceError(413, "audio_too_large", f"audio exceeds {lim['max_audio_bytes']} bytes")
    t0 = time.monotonic()
    try:
        dec = audio.decode(data, max_seconds=lim["max_audio_seconds"], allowed=tuple(lim["accepted_containers"]))
    except audio.AudioError as e:
        status = 415 if e.code == "unsupported_audio" else 422
        raise ServiceError(status, e.code, str(e)) from None
    sha = hashlib.sha256(data).hexdigest()
    del data, fields["file"]
    decode_s = time.monotonic() - t0
    deadline = time.monotonic() + lim["inference_timeout_s"]
    try:
        res = state.tr.transcribe(dec.samples, deadline=deadline)
    except TimeoutError:
        raise ServiceError(504, "timeout", "transcription exceeded the service's time limit") from None
    finally:
        del dec
    return {
        "text": res.text,
        "flh": {
            "schema": SCHEMA, "status": res.status, "warnings": res.warnings, "language": res.language,
            "duration_s": res.quality.get("seconds"), "sound_s": res.quality.get("sound_seconds"),
            "windows": len(res.windows), "audio_sha256": sha, "deployment_id": state.manifest["deployment_id"],
            "timing": {"decode_s": round(decode_s, 3), "model_s": round(res.seconds_model, 3)},
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "flh-speaking/1"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    @property
    def state(self) -> State:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):  # default access log disabled; see _log
        pass

    def _log(self, status, t0, extra=None):
        rec = {"method": self.command, "path": self.path.split("?")[0], "status": status, "ms": round((time.monotonic() - t0) * 1000)}
        rec.update(extra or {})
        print(json.dumps(rec), file=sys.stderr, flush=True)

    def _send(self, status: int, doc: dict):
        body = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, e: ServiceError):
        self._send(e.status, {"error": {"type": e.code, "message": str(e)}})

    def do_GET(self):
        t0 = time.monotonic()
        st = self.state
        path = self.path.split("?")[0]
        if path == "/healthz":
            self._send(200, {"status": "alive"})
        elif path == "/readyz":
            doc = {"status": st.status, "deployment_id": st.manifest.get("deployment_id"), "load_s": st.load_s, "warm_s": st.warm_s}
            if st.reason:
                doc["reason"] = st.reason
            self._send(200 if st.status == "ready" else 503, doc)
        elif path == "/manifest" and st.manifest:
            self._send(200, st.manifest)
        elif path == "/metrics":
            self._send(200, {"counters": st.counters, "status": st.status})
        else:
            self._send(404, {"error": {"type": "not_found", "message": "unknown path"}})
        self._log(self._status_sent, t0)

    def send_response(self, code, message=None):
        self._status_sent = code
        super().send_response(code, message)

    def do_POST(self):
        t0 = time.monotonic()
        st = self.state
        extra = {}
        try:
            if self.path.split("?")[0] not in ("/v1/audio/transcriptions", "/audio/transcriptions"):
                raise ServiceError(404, "not_found", "unknown path")
            if st.status != "ready":
                raise ServiceError(503, "not_ready", f"the model is {st.status}")
            ctype = self.headers.get("Content-Type", "")
            if not ctype.lower().startswith("multipart/form-data"):
                raise ServiceError(415, "invalid_request", "expected multipart/form-data")
            try:
                n = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise ServiceError(411, "length_required", "Content-Length is required") from None
            if n < 0 or n > st.limits["max_request_bytes"]:
                self.close_connection = True
                raise ServiceError(413, "request_too_large", f"request exceeds {st.limits['max_request_bytes']} bytes")
            self.connection.settimeout(st.limits["read_timeout_s"])
            body = self.rfile.read(n)
            if len(body) != n:
                self.close_connection = True
                raise ServiceError(400, "invalid_request", "request body ended early")
            fields = parse_multipart(ctype, body)
            del body
            st.counters["requests"] += 1
            if not st.slots.acquire(blocking=False):
                st.counters["busy"] += 1
                raise ServiceError(429, "busy", "too many transcriptions in progress; try again later")
            try:
                with st.lock:
                    doc = transcribe_request(st, fields)
            finally:
                st.slots.release()
            extra = {"result": doc["flh"]["status"], "audio_s": doc["flh"]["duration_s"], "model_s": doc["flh"]["timing"]["model_s"]}
            st.counters["transcribed" if doc["flh"]["status"] == "transcribed" else "abstained"] += 1
            self._send(200, doc)
        except ServiceError as e:
            if e.code == "timeout":
                st.counters["timeouts"] += 1
            elif e.code not in ("busy", "not_ready", "not_found"):
                st.counters["refused"] += 1
            extra = {"error": e.code}
            self._error(e)
        except Exception as exc:
            st.counters["errors"] += 1
            extra = {"error": "internal", "kind": type(exc).__name__}
            self._send(500, {"error": {"type": "internal", "message": "internal error"}})
        self._log(self._status_sent, t0, extra)


def in_container() -> bool:
    return os.path.exists("/.dockerenv")


def check_host(host: str, container: bool | None = None) -> None:
    """Loopback or a private address. The unspecified address (all interfaces)
    only inside a container, whose port the host publishes on 127.0.0.1."""
    ip = ipaddress.ip_address(host)
    if ip.is_unspecified:
        if container if container is not None else in_container():
            return
        raise ValueError("binding all interfaces is allowed only inside a container (publish it on 127.0.0.1)")
    if not (ip.is_loopback or ip.is_private):
        raise ValueError("the service binds loopback or a private address only")


def make_server(model_dir: str, host: str, port: int, *, threads: int = 4, max_waiting: int = 2, loader=None, limits=None, manifest_fn=None):
    check_host(host)
    state = State(model_dir, threads, max_waiting, dict(limits or deployment.LIMITS), loader, manifest_fn)
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    srv.state = state  # type: ignore[attr-defined]
    return srv, state


def serve(model_dir: str, host: str, port: int, *, threads: int = 4, max_waiting: int = 2) -> int:
    srv, state = make_server(model_dir, host, port, threads=threads, max_waiting=max_waiting)
    threading.Thread(target=state.load, daemon=True).start()
    print(json.dumps({"event": "listening", "host": host, "port": srv.server_address[1]}), file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0
