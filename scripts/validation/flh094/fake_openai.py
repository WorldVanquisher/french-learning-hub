"""FLH-094 fake OpenAI-compatible provider for wiring tests (no network, no key).

Usage: python3 -B fake_openai.py PORT CALL_LOG

Answers POST /v1/responses for both existing schemas:
- "analysis_result" (the analyzer): one fixed, schema-valid interpretation;
- "knowledge_units" (the extractor): two units, or zero when the record text
  contains "bonjour", to exercise a valid empty extraction.
A record text containing "ERREUR-FOURNISSEUR" gets HTTP 500, to exercise the
provider-failure path. Every request appends one JSON line to CALL_LOG with the
schema name, the requested model and whether a bearer token was sent (never the
token itself). The output is fixed test text, not a language judgment.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, LOG = int(sys.argv[1]), sys.argv[2]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        body = json.loads(raw)
        schema = ((body.get("text") or {}).get("format") or {}).get("name", "")
        auth = self.headers.get("Authorization", "")
        with open(LOG, "a", encoding="utf-8") as log:
            log.write(json.dumps({"path": self.path, "schema": schema, "model": body.get("model"),
                                  "bearer": auth.startswith("Bearer ") and len(auth) > 7}) + "\n")
        if self.path != "/v1/responses":
            return self.reply(404, {"error": {"message": "not found"}})
        if "ERREUR-FOURNISSEUR" in raw:
            return self.reply(500, {"error": {"message": "fake provider failure"}})
        if schema == "analysis_result":
            out = {"category": "grammar", "explanation": "Fake provider explanation (FLH-094 wiring test).",
                   "explanation_zh": "假提供方的说明（FLH-094 连接测试）。",
                   "confidence": 0.7, "uncertainty": "Fake provider: not a language judgment."}
        elif schema == "knowledge_units":
            units = [] if "bonjour" in raw.lower() else [
                {"kind": "grammar", "canonical": "fake unit one", "statement": "Fake statement one (FLH-094).",
                 "statement_zh": "假陈述一（FLH-094）。",
                 "example": "Exemple factice un.", "confidence": 0.9},
                {"kind": "usage", "canonical": "fake unit two", "statement": "Fake statement two (FLH-094).",
                 "statement_zh": "假陈述二（FLH-094）。",
                 "example": None, "confidence": 0.9}]
            out = {"units": units}
        else:
            return self.reply(400, {"error": {"message": "unknown schema"}})
        text = json.dumps(out, ensure_ascii=False)
        self.reply(200, {"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]}]})

    def reply(self, status, obj):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
