"""Daily-workflow v1.0 RC fake OpenAI-compatible provider (loopback, no key, no network).

Usage: python3 -I -B fake_openai.py PORT CALL_LOG CASES_JSON

Answers POST /v1/responses for the three existing schemas, from authored cases:
- "analysis_result": one fixed, schema-valid bilingual interpretation;
- "knowledge_units": the units of the case whose "match" text occurs in the
  request (the record's original input is part of it);
- "concept_suggestions": for each unit, the candidate whose target the case
  table names, else "no_suitable_candidate". It only ever chooses among the
  candidates the server supplied.
Every request appends one JSON line to CALL_LOG (schema, model, bearer present,
unit ids for suggestions); never the token. Fixed test text, not a language judgment.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, LOG, CASES = int(sys.argv[1]), sys.argv[2], sys.argv[3]
with open(CASES, encoding="utf-8") as f:
    cases = json.load(f)


def user_text(body):
    for message in body.get("input") or []:
        if message.get("role") == "user":
            return "".join(c.get("text", "") for c in message.get("content") or [])
    return ""


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        body = json.loads(raw)
        schema = ((body.get("text") or {}).get("format") or {}).get("name", "")
        auth = self.headers.get("Authorization", "")
        entry = {"path": self.path, "schema": schema, "model": body.get("model"),
                 "bearer": auth.startswith("Bearer ") and len(auth) > 7}
        text = user_text(body)
        if self.path != "/v1/responses":
            self.log(entry)
            return self.reply(404, {"error": {"message": "not found"}})
        if schema == "analysis_result":
            out = {"category": "grammar", "explanation": "Fake provider: describes and classifies the question only.",
                   "explanation_zh": "假提供方：只描述并归类这个问题。",
                   "confidence": 0.8, "uncertainty": "Fake provider: not a language judgment."}
        elif schema == "knowledge_units":
            matched = [c for c in cases["records"].values() if c["match"] in text]
            entry["case_matches"] = len(matched)
            out = {"units": matched[0]["units"] if len(matched) == 1 else []}
        elif schema == "concept_suggestions":
            payload = json.loads(text)
            answers = []
            for unit in payload["units"]:
                rule = cases["suggestions"].get(unit["canonical"])
                pick = [c for c in unit["candidates"] if rule and c["target"] == rule["target"]]
                if pick:
                    answers.append({"unit_id": unit["unit_id"], "outcome": "suggested", "concept_id": pick[0]["concept_id"],
                                    "reason": rule["reason"]})
                else:
                    answers.append({"unit_id": unit["unit_id"], "outcome": "no_suitable_candidate", "concept_id": None,
                                    "reason": "Fake provider: none of the supplied candidates is named for this unit."})
            entry["units"] = [u["unit_id"] for u in payload["units"]]
            entry["candidates"] = {str(u["unit_id"]): [c["concept_id"] for c in u["candidates"]] for u in payload["units"]}
            out = {"suggestions": answers}
        else:
            self.log(entry)
            return self.reply(400, {"error": {"message": "unknown schema"}})
        self.log(entry)
        self.reply(200, {"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(out, ensure_ascii=False)}]}]})

    def log(self, entry):
        with open(LOG, "a", encoding="utf-8") as log:
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def reply(self, status, obj):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
