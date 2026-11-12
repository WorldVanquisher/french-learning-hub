"""Local fake of the OpenAI Responses endpoint for listening preparation.

Loopback only, no network, no billing. It builds a small valid exercise from
the numbered segments it receives (citing segment 1 and the last segment, with
a verbatim excerpt of segment 1), so the server's own validation passes. Every
generated sentence says it comes from a local fake. It records what it was sent
(segment numbers and whether any speaker or timestamp field arrived).
Usage: python3 -I fake_openai.py PORT_FILE LOG_FILE
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

port_file, log_file = sys.argv[1], sys.argv[2]


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        req = json.loads(raw)
        user = json.loads(req["input"][1]["content"][0]["text"])
        segs = user["segments"]
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"path": self.path, "title": user["title"], "segment_numbers": [s["number"] for s in segs],
                                "segment_keys": sorted({k for s in segs for k in s}),
                                "bearer": self.headers.get("Authorization", "").startswith("Bearer ")}, ensure_ascii=False) + "\n")
        first, last = segs[0], segs[-1]
        words = first["text"].split()
        excerpt = " ".join(words[:3]) if len(words) >= 3 else first["text"]
        content = {
            "items": [
                {"kind": "main_idea", "question": "(Faux fournisseur local) De quoi parle cet extrait ?",
                 "expected_answer": "(Faux fournisseur local) " + first["text"][:120],
                 "rationale_en": "Local fake provider: cites the first line.", "rationale_zh": "本地假提供方：引用第一行。",
                 "segments": [first["number"]]},
                {"kind": "detail", "question": "(Faux fournisseur local) Que dit la dernière ligne ?",
                 "expected_answer": "(Faux fournisseur local) " + last["text"][:120],
                 "rationale_en": "Local fake provider: cites the last line.", "rationale_zh": "本地假提供方：引用最后一行。",
                 "segments": [last["number"]]},
            ],
            "annotations": [{"kind": "vocabulary", "segment": first["number"], "excerpt": excerpt,
                             "note_en": "Local fake note.", "note_zh": "本地假注释。"}],
        }
        body = json.dumps({"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(content, ensure_ascii=False)}]}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
with open(port_file, "w") as f:
    f.write(str(srv.server_address[1]))
srv.serve_forever()
