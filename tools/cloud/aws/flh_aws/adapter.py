"""Loopback adapter: the existing Go HTTPProvider wire format in front of Titan V2.

``POST /v1/embeddings`` with ``{"model": <identity>, "input": [...]}`` returns
``{"data": [{"index": i, "embedding": [...]}]}``, as internal/embedding/http.go
expects. Each input is one InvokeModel call, charged to the state directory's
ledger before sending. Any failure answers 502 (429 when a cap is reached) with
no partial vectors. Nothing is sent to AWS at startup; GET /readyz never calls
AWS.
"""

from __future__ import annotations

import ipaddress
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .ledger import CapExceeded, Ledger
from .snapshot import Refused
from .titan import identity, invoke

MAX_REQUEST_BYTES = 256 * 1024
MAX_INPUTS_PER_REQUEST = 8


def make_server(state: Path, runtime, region: str, dimensions: int, backend: str, host: str, port: int):
    if not ipaddress.ip_address(host).is_loopback:
        raise Refused("the adapter binds a loopback address only")
    model = identity(region, dimensions)
    ledger = Ledger(state)

    class Handler(BaseHTTPRequestHandler):
        server_version = "flh063-titan-adapter"

        def log_message(self, fmt, *args):  # no request bodies in logs
            pass

        def _send(self, code: int, obj: dict):
            raw = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _error(self, code: int, typ: str, msg: str):
            self._send(code, {"error": {"type": typ, "message": msg}})

        def do_GET(self):
            if self.path == "/readyz":
                rem = ledger.remaining()
                self._send(200, {"ready": True, "model": model, "backend": backend, "region": region,
                                 "dimensions": dimensions,
                                 "remaining": {k: v for k, v in rem.items() if k.startswith("bedrock_")}})
            else:
                self._error(404, "not_found", "not found")

        def do_POST(self):
            if self.path != "/v1/embeddings":
                return self._error(404, "not_found", "not found")
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_REQUEST_BYTES:
                return self._error(413 if n > 0 else 400, "invalid_request", "bad request size")
            try:
                req = json.loads(self.rfile.read(n))
            except ValueError:
                return self._error(400, "invalid_request", "body is not JSON")
            if not isinstance(req, dict) or req.get("model") != model:
                return self._error(400, "invalid_request", f"model must be {model}")
            inputs = req.get("input")
            if (not isinstance(inputs, list) or not 1 <= len(inputs) <= MAX_INPUTS_PER_REQUEST
                    or not all(isinstance(t, str) for t in inputs)):
                return self._error(400, "invalid_request", f"input must be 1..{MAX_INPUTS_PER_REQUEST} strings")
            # Check the whole request fits before sending anything.
            rem = ledger.remaining()
            if len(inputs) > rem["bedrock_invocations"] or sum(map(len, inputs)) > rem["bedrock_input_chars"]:
                return self._error(429, "budget_exhausted", "request exceeds the remaining budget; nothing sent")
            data = []
            for i, text in enumerate(inputs):
                try:
                    r = invoke(ledger, runtime, dimensions, text, backend, f"adapter[{i}]")
                except CapExceeded:
                    return self._error(429, "budget_exhausted", "budget reached; no partial result")
                except Refused as e:
                    return self._error(400, "invalid_request", str(e))
                except Exception:  # noqa: BLE001 - details stay in the ledger
                    return self._error(502, "provider_unavailable", "embedding provider unavailable")
                data.append({"object": "embedding", "index": i, "embedding": r["vector"]})
            self._send(200, {"object": "list", "model": model, "data": data})

    return HTTPServer((host, port), Handler)
