"""FLH-089 deterministic extraction-provider stand-in (OpenAI Responses shape).

Usage: python3 -B stub_extractor.py PORT

Every fixture record's input carries a marker "[fx:N]". The stub answers each
extraction request with three synthetic units derived from N. Each later
extraction of the same record rewords the statements, so re-extraction
produces a new, distinguishable version. It makes no network call and needs no
key. The content is synthetic test text, not learning evidence.
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KINDS = ["grammar", "morphology", "vocabulary", "orthography", "usage", "expression", "pronunciation"]
calls = {}


def units_for(n, version):
    out = []
    for i in range(3):
        k = (n * 3 + i)
        kind = KINDS[k % len(KINDS)]
        topic = f"synthetic topic {k % 600:03d}"
        out.append({
            "kind": kind,
            "canonical": f"{topic} note {n}-{i}",
            "statement": f"Synthetic {kind} statement v{version} for {topic} (record {n}, unit {i}).",
            "example": f"Exemple synthétique {n}-{i}." if i != 2 else None,
            # A few low-confidence units, so admission recommendations are mixed.
            "confidence": 0.45 if k % 17 == 0 else 0.9,
        })
    return out


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        m = re.search(r"\[fx:(\d+)\]", body)
        units = []
        if m:
            n = int(m.group(1))
            calls[n] = calls.get(n, 0) + 1
            units = units_for(n, calls[n])
        text = json.dumps({"units": units}, ensure_ascii=False)
        raw = json.dumps({"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
