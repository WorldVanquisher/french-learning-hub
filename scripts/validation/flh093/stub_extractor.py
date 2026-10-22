"""FLH-093 extraction-provider stand-in with authored French-learning units.

Usage: python3 -B stub_extractor.py PORT CALL_LOG

Each fixture record's input carries a marker "[flh093:N]". The stub answers with
the units authored for N below (English statement, Simplified Chinese
statement_zh since FLH-095, French examples); a later extraction of record 2 returns a reworded
unit, so that record gets a newer current extraction. Every request appends one
line to CALL_LOG, so a check can prove that read-only inspection made no provider
call. The content is synthetic test text written for FLH-093, not learning
evidence, and the stub makes no network call and needs no key.
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UNITS = {
    1: [{"kind": "grammar", "canonical": "ne … plus (cessation)",
         "statement": "« Ne … plus » indicates that a habitual action has stopped.",
         "statement_zh": "« Ne … plus » 表示一个习惯性的动作已经停止。",
         "example": "Je ne fume plus depuis un an.", "confidence": 0.92}],
    2: [{"kind": "grammar", "canonical": "ne … plus aux temps composés",
         "statement": "In compound tenses, « plus » goes between the auxiliary and the past participle.",
         "statement_zh": "在复合时态中，« plus » 位于助动词和过去分词之间。",
         "example": "Je n'ai plus vu Paul.", "confidence": 0.9}],
    3: [{"kind": "usage", "canonical": "omission du ne à l'oral",
         "statement": "In speech, the « ne » of « ne … plus » is often dropped.",
         "statement_zh": "在口语中，« ne … plus » 里的 « ne » 常常被省略。",
         "example": "J'en veux plus.", "confidence": 0.88}],
    4: [{"kind": "grammar", "canonical": "ne … jamais",
         "statement": "« Ne … jamais » expresses that an action never happens.",
         "statement_zh": "« Ne … jamais » 表示一个动作从不发生。",
         "example": "Il ne ment jamais.", "confidence": 0.9}],
    5: [{"kind": "vocabulary", "canonical": "ne … guère",
         "statement": "« Ne … guère » means « pas beaucoup » (hardly) and belongs mainly to formal writing.",
         "statement_zh": "« Ne … guère » 意为 « pas beaucoup »（几乎不），主要用于正式书面语。",
         "example": "Il ne mange guère.", "confidence": 0.86}],
}
REWORDED_2 = [{"kind": "grammar", "canonical": "ne … plus aux temps composés",
               "statement": "With a compound tense, « plus » follows the auxiliary: « je n'ai plus vu ».",
               "statement_zh": "使用复合时态时，« plus » 紧跟助动词：« je n'ai plus vu »。",
               "example": "Nous n'avons plus parlé.", "confidence": 0.9}]
calls = {}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        with open(sys.argv[2], "a", encoding="utf-8") as log:
            log.write("call\n")
        m = re.search(r"\[flh093:(\d+)\]", body)
        units = []
        if m:
            n = int(m.group(1))
            calls[n] = calls.get(n, 0) + 1
            units = REWORDED_2 if n == 2 and calls[n] > 1 else UNITS.get(n, [])
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
