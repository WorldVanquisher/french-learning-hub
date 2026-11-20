#!/usr/bin/env python3
"""Seed a synthetic learner for the Review Today demo, through the server's API.

    python3 -I scripts/demo/review_today/seed.py http://127.0.0.1:PORT

Loopback only, and only into an EMPTY database (a fresh scratch DB_PATH):
the script refuses a server that already holds Review Today history, so it
can never write into daily data. No provider is called (run the server with
the Speaking providers disabled). Synthetic French practice text only.

Creates one due item from each source, plus history that must NOT be queued:
  - workbook: the authored listening script ls-wb1-u05 imported; question 2
    saved as a mistake and marked for retry (due: retry_marked); question 1
    saved but not marked (history only);
  - Speaking: "Répondre à une invitation" started, a typed take with its
    transcript confirmed; feedback is off, so it is due as
    review_without_feedback; "Demander des renseignements" is not started
    (not due).
Prints the Review Today queue it produces. Exit 0 on success, 1 on any error,
2 when refused.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def call(base, method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def expect(base, method, path, statuses, body=None):
    status, out = call(base, method, path, body)
    if status not in statuses:
        raise SystemExit(f"{method} {path}: {status} {out}")
    return out


def main():
    if len(sys.argv) != 2:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    base = sys.argv[1].rstrip("/")
    host = urllib.parse.urlparse(base).hostname
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("refused: the demo seed only talks to a loopback server", file=sys.stderr)
        return 2
    today = expect(base, "GET", "/review-today", (200,))
    h = today["history"]
    if today["items"] or h["notebook_items"] or h["speaking_exercises"] or h["speaking_takes"]:
        print("refused: this server already holds Review Today history; seed a fresh scratch database", file=sys.stderr)
        return 2
    # Workbook: an authored script and two saved mistakes, one marked for retry.
    lesson = expect(base, "POST", "/listening/scripts/ls-wb1-u05", (201,))
    exercise = lesson["current_exercise_id"]
    entries = {}
    for item, attempt in ((1, "Le lundi."), (2, "Parce qu'il est moins cher.")):
        doc = {"schema_version": "learning_capture_v1", "capture_id": f"review-today-demo-{item}", "source": "manual",
               "original_input": f"Je me suis trompé à la question {item} de l'écoute.",
               "original_context": "Listening exercise: authored script (no audio or video)",
               "source_ref": {"type": "listening_item", "record_id": exercise, "item": item, "attempt": attempt}}
        entries[item] = expect(base, "POST", "/captures", (201,), doc)["entry_id"]
    expect(base, "PUT", f"/mistake-notebook/items/{entries[2]}/retry", (200,), {"marked": True})
    # Speaking: a typed take whose checked transcript waits for feedback (off).
    view = expect(base, "POST", "/speaking/prompts/sp-invitation-reponse", (201,))
    take = expect(base, "POST", f"/speaking/exercises/{view['exercise']['id']}/takes", (201,), {"audio_source": "none"})["take_id"]
    expect(base, "POST", f"/speaking/takes/{take}/transcripts", (201,),
           {"text": "Salut Léa, c'est Sam. Merci pour ton invitation, c'est très gentil ! Oui, je viens samedi, vers midi et demi. "
                    "J'apporte une tarte aux pommes. C'est où exactement dans le parc ? À samedi !"})
    today = expect(base, "GET", "/review-today", (200,))
    for it in today["items"]:
        title = (it["speaking"] or it["notebook"])["title"]
        print(f"{it['source']}\t{it['reason']}\t{title}")
    print(f"history: {json.dumps(today['history'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
