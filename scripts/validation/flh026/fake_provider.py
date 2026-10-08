"""Local Responses-API fixture. No outbound requests or third-party modules."""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Provider(ThreadingHTTPServer):
    def __init__(self, address):
        super().__init__(address, Handler)
        self.lock = threading.Lock()
        self.calls = {"analysis": 0, "extraction": 0}
        self.block_next = False
        self.waiting = threading.Event()
        self.release = threading.Event()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Never log Authorization or submitted learning content.

    def reply(self, code, value):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/control/state":
            return self.reply(404, {})
        with self.server.lock:
            self.reply(200, {"calls": dict(self.server.calls),
                             "waiting": self.server.waiting.is_set()})

    def do_POST(self):
        if self.path == "/control/block":
            with self.server.lock:
                self.server.block_next = True
                self.server.waiting.clear()
                self.server.release.clear()
            return self.reply(200, {})
        if self.path == "/control/release":
            self.server.release.set()
            return self.reply(200, {})
        if self.path != "/v1/responses":
            return self.reply(404, {})
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        name = request["text"]["format"]["name"]
        kind = {"analysis_result": "analysis", "knowledge_units": "extraction"}.get(name)
        if kind is None or self.headers.get("Authorization") != "Bearer flh026-fake-only":
            return self.reply(400, {"error": "invalid fixture request"})
        with self.server.lock:
            self.server.calls[kind] += 1
            ordinal = self.server.calls[kind]
            block = kind == "extraction" and self.server.block_next
            if block:
                self.server.block_next = False
                self.server.waiting.set()
        if block and not self.server.release.wait(20):
            return self.reply(500, {"error": "fixture gate timed out"})
        if kind == "analysis":
            payload = {"category": "grammar", "explanation": "La négation encadre le verbe.",
                       "confidence": 0.95, "uncertainty": ""}
        else:
            # Unique evidence prevents duplicate-admission suppression obscuring tests.
            payload = {"units": [{"kind": "grammar", "canonical": f"négation fixture {ordinal}",
                                  "statement": "Ne et pas encadrent le verbe conjugué.",
                                  "example": "Je ne parle pas.", "confidence": 0.95}]}
        self.reply(200, {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(payload)}]}]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", action="store_true")
    args = parser.parse_args()
    Provider(("0.0.0.0" if args.container else "127.0.0.1", 8081)).serve_forever()
