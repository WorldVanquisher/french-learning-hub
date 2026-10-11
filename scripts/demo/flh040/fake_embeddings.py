"""Deterministic fake embedding service for FLH-040 (OpenAI-compatible shape).

Usage: python3 -B fake_embeddings.py PORT DIMENSIONS [WORK_DIR]

POST /v1/embeddings  {"model": ..., "input": [texts]} -> {"data": [{"index", "embedding"}]}
GET  /stats          {"requests": n, "texts": m}  (counters since start)
POST /control        {"mode": "normal" | "fail" | "bad_dims" | "nan" | "slow"}
                     ("slow" waits 2 s per request, to exercise interruption)

Each text becomes a bag-of-words vector: words of two or more letters/digits
(lowercased, accents removed, JSON keys of the concept document ignored) are
hashed to +/-1 at a fixed index. Similarity therefore reflects shared words
only. This proves index mechanics (caching, publication, re-validation); it
says nothing about semantic quality. WORK_DIR is unused; it lets an operator
recognize the process. Binds 127.0.0.1 only. Makes no network call.
"""
import hashlib
import json
import sys
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, DIMS = int(sys.argv[1]), int(sys.argv[2])
IGNORE = {"representation", "type", "concept", "target", "pedagogical_intent", "scope",
          "identity_features", "key", "value", "concept_embedding_text_v1"}
state = {"requests": 0, "texts": 0, "mode": "normal"}
lock = threading.Lock()


def words(text):
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    out, cur = [], []
    for ch in text:
        if ch.isalnum() or ch == "_":
            cur.append(ch)
        else:
            if cur:
                out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return [w for w in out if len(w) >= 2 and w not in IGNORE]


def embed(text):
    v = [0.0] * DIMS
    for w in words(text):
        h = hashlib.sha256(w.encode()).digest()
        v[int.from_bytes(h[:4], "big") % DIMS] += -1.0 if h[4] & 1 else 1.0
    if not any(v):
        v[-1] = 1.0  # a text with no words still gets a valid vector
    return v


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/stats":
            with lock:
                self._send(200, {"requests": state["requests"], "texts": state["texts"]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if self.path == "/control":
            with lock:
                state["mode"] = body.get("mode", "normal")
            return self._send(200, {"mode": state["mode"]})
        if self.path != "/v1/embeddings":
            return self._send(404, {"error": "not found"})
        texts = body.get("input", [])
        with lock:
            state["requests"] += 1
            mode = state["mode"]
            if mode != "fail":
                state["texts"] += len(texts)
        if mode == "slow":
            time.sleep(2)
        if mode == "fail":
            return self._send(503, {"error": {"type": "server_error"}})
        data = []
        for i, t in enumerate(texts):
            v = embed(t)
            if mode == "bad_dims":
                v.append(1.0)
            elif mode == "nan":
                v[0] = float("nan")
            data.append({"index": i, "embedding": v})
        # In "nan" mode the body contains a bare NaN, which strict JSON
        # decoders (the Go provider) reject as a malformed response.
        self._send(200, {"data": data})

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
