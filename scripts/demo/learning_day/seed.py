#!/usr/bin/env python3
"""Seed a synthetic learner's day for the learning-day walkthrough.

    python3 -I scripts/demo/learning_day/seed.py http://127.0.0.1:PORT /abs/path/to/that/server.db

Loopback only, and only into an EMPTY scratch database: the script refuses a
server whose Review Today or learning week already holds anything, so it can
never write into daily data. No provider is called (run the server with every
provider disabled). Synthetic French practice text only.

Through the API:
  - workbook: the authored listening script ls-wb1-u05 imported, questions 1
    and 2 saved as mistakes (not marked: the walkthrough makes practice from
    them);
  - Speaking: "Répondre à une invitation", take 1 typed and confirmed, take 2
    typed, then corrected by the learner (an own correction);
  - Writing: a learner task with a first draft and a revision.
Then one direct edit of the scratch database: revision 1 of the script gets
one uncited line as an older pack worded it (" Voilà." appended), so the
lesson offers a pack update and the revision studio has two revisions to
compare. This is the technique the Go revision tests use; nothing else is
written outside the API.
Exit 0 on success, 1 on any error, 2 when refused.
"""
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


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
    if len(sys.argv) != 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    base, db_path = sys.argv[1].rstrip("/"), sys.argv[2]
    if urllib.parse.urlparse(base).hostname not in ("127.0.0.1", "localhost", "::1"):
        print("refused: the seed only talks to a loopback server", file=sys.stderr)
        return 2
    real = os.path.realpath(db_path)
    if not os.path.isabs(db_path) or real == REPO or real.startswith(REPO + os.sep) or not os.path.isfile(real):
        print("refused: the database must be an existing absolute path outside the repository", file=sys.stderr)
        return 2
    today = expect(base, "GET", "/review-today", (200,))
    week = expect(base, "GET", "/learning-week", (200,))
    h, t = today["history"], week["totals"]
    if today["items"] or any(h.values()) or t["production"] or t["reviewed"] or t["own_corrections"]:
        print("refused: this server already holds learning history; seed a fresh scratch database", file=sys.stderr)
        return 2

    lesson = expect(base, "POST", "/listening/scripts/ls-wb1-u05", (201,))
    material, exercise = lesson["material"]["id"], lesson["current_exercise_id"]
    for item, attempt in ((1, "Le lundi."), (2, "Parce qu'il est moins cher.")):
        doc = {"schema_version": "learning_capture_v1", "capture_id": f"learning-day-{item}", "source": "manual",
               "original_input": f"Je me suis trompé à la question {item} de l'écoute.",
               "original_context": "Listening exercise: authored script (no audio or video)",
               "source_ref": {"type": "listening_item", "record_id": exercise, "item": item, "attempt": attempt}}
        expect(base, "POST", "/captures", (201,), doc)

    view = expect(base, "POST", "/speaking/prompts/sp-invitation-reponse", (201,))
    ex = view["exercise"]["id"]
    take1 = expect(base, "POST", f"/speaking/exercises/{ex}/takes", (201,), {"audio_source": "none"})["take_id"]
    expect(base, "POST", f"/speaking/takes/{take1}/transcripts", (201,),
           {"text": "Salut Léa, c'est Sam. Merci pour ton invitation ! Oui, je viens samedi, vers midi. À samedi !"})
    take2 = expect(base, "POST", f"/speaking/exercises/{ex}/takes", (201,), {"audio_source": "none"})["take_id"]
    for text in ("Salut Léa, merci pour ton invitation. Je viens samedi vers midi et demi, j'apporte une tarte.",
                 "Salut Léa, merci pour ton invitation ! Je viendrai samedi vers midi et demie ; j'apporterai une tarte aux pommes."):
        expect(base, "POST", f"/speaking/takes/{take2}/transcripts", (201,), {"text": text})

    task = expect(base, "POST", "/writing/tasks", (201,), {"title": "Lettre à Éloïse", "prompt": "Écrivez à votre amie pour accepter son invitation.",
                                                           "requirements": [], "word_min": 10, "word_max": 120})["task"]["id"]
    for text in ("Chère Éloïse, merci pour ton invitation, je suis content de venir samedi.",
                 "Chère Éloïse, merci beaucoup pour ton invitation : je serai très content de venir samedi prochain."):
        expect(base, "POST", f"/writing/tasks/{task}/drafts", (201,), {"text": text})

    # An older wording of revision 1 (scratch database only): one uncited line.
    rev = expect(base, "GET", f"/listening/materials/{material}/revisions/1", (200,))
    content = rev["exercise"]["content"]
    cited = {s for it in content["items"] for s in it.get("segments") or []} | {a["segment"] for a in content.get("annotations") or []}
    line = next(s["index"] for s in rev["transcript"]["segments"] if s["index"] not in cited)
    con = sqlite3.connect(real, timeout=10)
    try:
        rows = con.execute("SELECT id, segments FROM listening_transcripts WHERE material_id = ? AND version = 1", (material,)).fetchall()
        if len(rows) != 1 or con.execute("SELECT COUNT(*) FROM listening_transcripts WHERE material_id = ?", (material,)).fetchone()[0] != 1:
            raise SystemExit("unexpected transcripts for the imported script")
        segments = json.loads(rows[0][1])
        for s in segments:
            if s["index"] == line:
                s["text"] += " Voilà."
        con.execute("UPDATE listening_transcripts SET segments = ? WHERE id = ?", (json.dumps(segments, ensure_ascii=False), rows[0][0]))
        con.commit()
    finally:
        con.close()
    state = expect(base, "GET", f"/listening/materials/{material}", (200,))["script_revision"]
    if state["pack_status"] != "update_available":
        raise SystemExit(f"the older revision was not recognised: {state}")
    print(json.dumps({"material_id": material, "title": lesson["material"]["title"], "older_line": f"s{line}",
                      "speaking_exercise": ex, "takes": [take1, take2], "writing_task": task}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
