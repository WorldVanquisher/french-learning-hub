# Local stub of the extraction provider endpoint: three synthetic units per call.
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        units = [{"kind": "grammar", "canonical": f"unité synthétique {i}", "statement": f"Énoncé synthétique {i}.", "example": None, "confidence": 0.9} for i in range(1, 4)]
        raw = json.dumps({"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"units": units})}]}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(raw)
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
