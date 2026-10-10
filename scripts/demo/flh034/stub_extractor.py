"""Local stand-in for the extraction provider (OpenAI Responses-compatible shape).

Usage: python3 -B stub_extractor.py PORT [WORK_DIR]

WORK_DIR is not used by the stub; demo.sh passes it so that proc_guard.py can
attribute this process to one demo directory before signalling it.

Returns fixed synthetic French-learning units for the FLH-034 demo records,
chosen by a phrase in the learner's original input. The second extraction of
the "il faut que" record returns a reworded version, so the demo has a
historical extraction. It makes no network call and needs no key.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def unit(kind, canonical, statement, example=None):
    return {"kind": kind, "canonical": canonical, "statement": statement, "example": example, "confidence": 0.9}


SCRIPTS = {
    "il faut que je": [
        [
            unit("grammar", "subjonctif après il faut que",
                 "Après « il faut que », le verbe se met au subjonctif.", "Il faut que je fasse mes devoirs."),
            unit("morphology", "subjonctif de faire",
                 "Le subjonctif présent de « faire » est irrégulier : que je fasse, que nous fassions.",
                 "Il faut que nous fassions attention."),
        ],
        [
            unit("grammar", "subjonctif après il faut que",
                 "« Il faut que » exprime une nécessité et déclenche toujours le subjonctif.",
                 "Il faut que tu viennes demain."),
            unit("morphology", "subjonctif de faire",
                 "Que je fasse, que tu fasses, qu'il fasse : radical « fass- » au subjonctif.", None),
        ],
    ],
    "Bien que": [
        [
            unit("grammar", "subjonctif après bien que",
                 "« Bien que » introduit une concession et exige le subjonctif.", "Bien qu'il pleuve, nous sortons."),
            unit("usage", "bien que ou malgré",
                 "« Malgré » est suivi d'un nom, « bien que » d'une proposition au subjonctif.",
                 "Malgré la pluie, nous sortons."),
        ],
    ],
    "suis allé": [
        [
            unit("grammar", "passé composé avec être",
                 "Les verbes de mouvement comme « aller » forment le passé composé avec « être ».",
                 "Je suis allé au cinéma hier."),
            unit("orthography", "accord du participe passé avec être",
                 "Avec « être », le participe passé s'accorde avec le sujet.", "Elle est allée au cinéma."),
        ],
    ],
    "I miss you": [
        [
            unit("expression", "tu me manques",
                 "Avec « manquer », la personne qui manque est le sujet : « tu me manques » = I miss you.",
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
