"""Local stand-in for the extraction provider (OpenAI Responses-compatible shape).

Usage: python3 -B stub_extractor.py PORT [WORK_DIR]

WORK_DIR is not used by the stub; demo.sh passes it so that proc_guard.py can
attribute this process to one demo directory before signalling it.

Returns fixed synthetic French-learning units, explained in English and (since
FLH-095) in Simplified Chinese, for the FLH-034 demo records,
chosen by a phrase in the learner's original input. The second extraction of
the "il faut que" record returns a reworded version, so the demo has a
historical extraction. It makes no network call and needs no key.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def unit(kind, canonical, statement, statement_zh, example=None):
    return {"kind": kind, "canonical": canonical, "statement": statement, "statement_zh": statement_zh,
            "example": example, "confidence": 0.9}


# Rule names and explanations are English for an English-speaking audience;
# examples and the grammar terms a learner meets in class stay French.
SCRIPTS = {
    "il faut que je": [
        [
            unit("grammar", "subjunctive after il faut que",
                 "After « il faut que » (it is necessary that), the verb goes into the subjunctive (subjonctif).",
                 "在 « il faut que »（必须）之后，动词要用虚拟式（subjonctif）。",
                 "Il faut que je fasse mes devoirs."),
            unit("morphology", "subjunctive of faire",
                 "The present subjunctive of « faire » (to do) is irregular: que je fasse, que nous fassions.",
                 "« faire »（做）的现在时虚拟式是不规则的：que je fasse, que nous fassions。",
                 "Il faut que nous fassions attention."),
        ],
        [
            unit("grammar", "subjunctive after il faut que",
                 "« Il faut que » expresses necessity, so it always triggers the subjunctive.",
                 "« Il faut que » 表示必要性，因此总是要求使用虚拟式。",
                 "Il faut que tu viennes demain."),
            unit("morphology", "subjunctive of faire",
                 "Que je fasse, que tu fasses, qu'il fasse: the subjunctive stem of « faire » is « fass- ».",
                 "Que je fasse, que tu fasses, qu'il fasse：« faire » 的虚拟式词干是 « fass- »。", None),
        ],
    ],
    "Bien que": [
        [
            unit("grammar", "subjunctive after bien que",
                 "« Bien que » (although) introduces a concession and requires the subjunctive.",
                 "« Bien que »（虽然）引出让步，要求使用虚拟式。",
                 "Bien qu'il pleuve, nous sortons."),
            unit("usage", "bien que or malgré",
                 "« Malgré » (despite) is followed by a noun; « bien que » by a clause in the subjunctive.",
                 "« Malgré »（尽管）后接名词；« bien que » 后接虚拟式从句。",
                 "Malgré la pluie, nous sortons."),
        ],
    ],
    "suis allé": [
        [
            unit("grammar", "passé composé with être",
                 "Verbs of movement such as « aller » (to go) form the passé composé (compound past) with « être », not « avoir ».",
                 "« aller »（去）等表示移动的动词用 « être » 而不是 « avoir » 构成复合过去时（passé composé）。",
                 "Je suis allé au cinéma hier."),
            unit("orthography", "past participle agreement with être",
                 "With « être », the past participle takes the gender and number of the person or thing doing the action.",
                 "用 « être » 时，过去分词要与动作的执行者在性和数上保持一致。",
                 "Elle est allée au cinéma."),
        ],
    ],
    "I miss you": [
        [
            unit("expression", "tu me manques",
                 "With « manquer », the roles are reversed: « tu me manques » means “I miss you” (literally “you are missing to me”).",
                 "« manquer » 的主宾关系是颠倒的：« tu me manques » 意为“我想你”（字面意思是“你对我来说缺失了”）。",
                 "Tu me manques beaucoup."),
            unit("vocabulary", "manquer", "Manquer = to miss.", "Manquer = 想念、错过。", None),
        ],
    ],
}
calls = {}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        units = []
        for key, versions in SCRIPTS.items():
            if key in body:
                n = calls.get(key, 0)
                calls[key] = n + 1
                units = versions[min(n, len(versions) - 1)]
                break
        text = json.dumps({"units": units}, ensure_ascii=False)
        raw = json.dumps({"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
