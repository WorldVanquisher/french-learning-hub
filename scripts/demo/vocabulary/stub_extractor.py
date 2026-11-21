"""Local stand-in for the extraction provider for the Vocabulary fixture (OpenAI Responses-compatible
shape, like scripts/demo/flh034/stub_extractor.py).

Usage: python3 -B stub_extractor.py PORT

Returns fixed synthetic French vocabulary units (meaning in English and Simplified Chinese), chosen
by a phrase in the learner's original input. The second extraction of the "apporter le dessert"
record returns a reworded unit, so a saved example can be superseded. No network call, no key.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def unit(kind, canonical, statement, statement_zh, example=None):
    return {"kind": kind, "canonical": canonical, "statement": statement, "statement_zh": statement_zh,
            "example": example, "confidence": 0.9}


SCRIPTS = {
    "apporter le dessert": [
        [unit("vocabulary", "apporter", "to bring (a thing)", "带来（东西）", "Pouvez-vous apporter le dessert ?")],
        [unit("vocabulary", "apporter", "to bring (an object you carry)", "带来（随身携带的东西）", "J'apporte le dessert.")],
    ],
    "apporter ou amener": [[unit("vocabulary", "apporter", "to bring a thing, not a person (amener)", "带来东西（带人用 amener）")]],
    "grasse matinée": [[unit("vocabulary", "faire  la grasse matinée", "to sleep in", "睡懒觉", "Le dimanche, je fais la grasse matinée.")]],
    "le chat dort": [[unit("vocabulary", "chat", "cat (French word)", "猫（法语词）", "Le chat dort sur le canapé.")]],
    "un chat en ligne": [[unit("vocabulary", "chat", "online chat (English loanword)", "在线聊天（英语借词）", "On a fait un chat en ligne.")]],
    "aujourd’hui": [[unit("vocabulary", "aujourd’hui", "today (typographic apostrophe)", "今天（印刷体撇号）", "Aujourd’hui, il pleut.")]],
    "aujourd'hui": [[unit("vocabulary", "aujourd'hui", "today (straight apostrophe)", "今天（直撇号）", "Aujourd'hui, il fait beau.")]],
    "un café crème": [[unit("vocabulary", "café", "coffee (é as one character)", "咖啡（é 为单个字符）", "Un café crème, s'il vous plaît.")]],
    "un café noir": [[unit("vocabulary", "café", "coffee (e + combining accent)", "咖啡（e 加组合重音）", "Un café noir.")]],
    "en revanche": [[unit("vocabulary", "en revanche", "on the other hand", "另一方面", "Il pleut ; en revanche, il fait doux.")]],
    "accord du participe": [[unit("grammar", "accord du participe passé", "Agreement with être.", "与 être 配合。")]],
    "il pleut des cordes": [[unit("vocabulary", "il pleut des cordes, n'est-ce pas ? — « oui » (vraiment) !",
                                  "it is raining cats and dogs, isn't it? — \"yes\" (really)!", "下着倾盆大雨，不是吗？——“是的”（真的）！")]],
}
calls = {}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        body = json.loads(body) if body.startswith("{") else body
        text = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
        units = []
        for key, versions in SCRIPTS.items():
            if key in text:
                n = calls.get(key, 0)
                calls[key] = n + 1
                units = versions[min(n, len(versions) - 1)]
                break
        out = json.dumps({"units": units}, ensure_ascii=False)
        raw = json.dumps({"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": out}]}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
