"""Local stand-in for the extraction provider (OpenAI Responses-compatible shape).

Usage: python3 -B stub_extractor.py PORT [WORK_DIR]

WORK_DIR is not used by the stub; demo.sh passes it so that proc_guard.py can
attribute this process to one demo directory before signalling it.

Returns fixed synthetic French-learning units, explained in English, for the FLH-034 demo records,
chosen by a phrase in the learner's original input. The second extraction of
the "il faut que" record returns a reworded version, so the demo has a
historical extraction. It makes no network call and needs no key.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def unit(kind, canonical, statement, example=None):
    return {"kind": kind, "canonical": canonical, "statement": statement, "example": example, "confidence": 0.9}


# Rule names and explanations are English for an English-speaking audience;
# examples and the grammar terms a learner meets in class stay French.
SCRIPTS = {
    "il faut que je": [
        [
            unit("grammar", "subjunctive after il faut que",
                 "After « il faut que » (it is necessary that), the verb goes into the subjunctive (subjonctif).",
                 "Il faut que je fasse mes devoirs."),
            unit("morphology", "subjunctive of faire",
                 "The present subjunctive of « faire » (to do) is irregular: que je fasse, que nous fassions.",
                 "Il faut que nous fassions attention."),
        ],
        [
            unit("grammar", "subjunctive after il faut que",
                 "« Il faut que » expresses necessity, so it always triggers the subjunctive.",
                 "Il faut que tu viennes demain."),
            unit("morphology", "subjunctive of faire",
                 "Que je fasse, que tu fasses, qu'il fasse: the subjunctive stem of « faire » is « fass- ».", None),
        ],
    ],
    "Bien que": [
        [
            unit("grammar", "subjunctive after bien que",
                 "« Bien que » (although) introduces a concession and requires the subjunctive.",
                 "Bien qu'il pleuve, nous sortons."),
            unit("usage", "bien que or malgré",
                 "« Malgré » (despite) is followed by a noun; « bien que » by a clause in the subjunctive.",
                 "Malgré la pluie, nous sortons."),
        ],
    ],
    "suis allé": [
        [
            unit("grammar", "passé composé with être",
                 "Verbs of movement such as « aller » (to go) form the passé composé (compound past) with « être », not « avoir ».",
                 "Je suis allé au cinéma hier."),
            unit("orthography", "past participle agreement with être",
                 "With « être », the past participle takes the gender and number of the person or thing doing the action.",
                 "Elle est allée au cinéma."),
        ],
    ],
    "I miss you": [
        [
            unit("expression", "tu me manques",
                 "With « manquer », the roles are reversed: « tu me manques » means “I miss you” (literally “you are missing to me”).",
                 "Tu me manques beaucoup."),
            unit("vocabulary", "manquer", "Manquer = to miss.", None),
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
