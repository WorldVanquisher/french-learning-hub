#!/usr/bin/env python3
"""Seed the R4 synthetic learner profile (Speaking, Mistake Notebook, workbook lessons) for the
Review Today walkthrough, through the server's API.

    python3 -I scripts/demo/review_today_r4/profile.py http://127.0.0.1:PORT /abs/path/to/that/server.db

Loopback only, and only into an EMPTY scratch database (the learning-day seed it starts with refuses
anything else). No provider is called. Synthetic French practice text only.

1. scripts/demo/learning_day/seed.py: the authored listening script ls-wb1-u05 (questions 1 and 2
   saved as mistakes), Speaking "Répondre à une invitation" (two typed takes, one corrected), a
   writing task with two drafts, and an older wording of the script's revision 1.
2. The pack update applied through the API (preview, then POST …/script-update): revision 2.
3. Question 2 saved again on revision 2 (the same question from another revision), and questions
   1 and 2 of revision 1 and question 2 of revision 2 marked for retry: Review Today shows ONE row
   for question 2, standing for both records.
4. A second listening script ls-wb1-u06 with question 1 saved and marked.
5. The reading example rd-notice-piscine imported, question 1 saved and marked.
6. A second Speaking prompt started with one typed, confirmed take.
7. A legacy-style record: a capture with no source (no notebook item; it stays in the records).
8. A duplicate save of the same item: refused with 409 source_already_saved.
9. A long French mistake on question 3 of revision 2, marked (the phone layout's long text).
Prints the profile's facts as JSON (IDs and expected queue keys). Exit 0, 1 on error, 2 refused.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
LONG = ("Je pensais que la responsable de l'inscription demandait seulement une photocopie de la carte d'identité, "
        "mais en réalité elle voulait aussi un justificatif de domicile récent et l'attestation de l'employeur.")


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


def capture(base, cid, ref, text, statuses=(201,)):
    doc = {"schema_version": "learning_capture_v1", "capture_id": cid, "source": "manual", "original_input": text,
           "original_context": "R4 synthetic profile", "source_ref": ref}
    if ref is None:
        del doc["source_ref"]
    status, out = call(base, "POST", "/captures", doc)
    if status not in statuses:
        raise SystemExit(f"capture {cid}: {status} {out}")
    return status, out


def mark(base, entry):
    expect(base, "PUT", f"/mistake-notebook/items/{entry}/retry", (200,), {"marked": True})


def main():
    if len(sys.argv) != 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    base, db = sys.argv[1].rstrip("/"), sys.argv[2]
    if urllib.parse.urlparse(base).hostname not in ("127.0.0.1", "localhost", "::1"):
        print("refused: loopback only", file=sys.stderr)
        return 2
    r = subprocess.run([sys.executable, "-I", os.path.join(REPO, "scripts/demo/learning_day/seed.py"), base, db], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr.strip() or r.stdout.strip(), file=sys.stderr)
        return r.returncode
    facts = json.loads(r.stdout.strip().splitlines()[-1])
    material = facts["material_id"]

    # 2. revision 2 through the explicit, previewed update
    preview = expect(base, "GET", f"/listening/materials/{material}/script-update", (200,))
    expect(base, "POST", f"/listening/materials/{material}/script-update", (200, 201),
           {"from_revision": preview["current_revision"], "pack_fingerprint": preview["pack_fingerprint"]})
    lesson = expect(base, "GET", f"/listening/materials/{material}", (200,))
    ex2 = lesson["current_exercise_id"]
    notebook = expect(base, "GET", "/mistake-notebook/items", (200,))["items"]
    r1 = {it["source"]["item"]: it["entry_id"] for it in notebook if it["source"]["type"] == "listening_item"}

    # 3. the same question from revision 2, and the marks
    _, q2r2 = capture(base, "r4-ls-u05-r2-q2", {"type": "listening_item", "record_id": ex2, "item": 2, "attempt": "Parce qu'il commence tôt."},
                      "Question 2 encore manquée après la mise à jour du script.")
    for entry in (r1[1], r1[2], q2r2["entry_id"]):
        mark(base, entry)

    # 4. another script
    u06 = expect(base, "POST", "/listening/scripts/ls-wb1-u06", (201,))
    _, u06q1 = capture(base, "r4-ls-u06-q1", {"type": "listening_item", "record_id": u06["current_exercise_id"], "item": 1}, "Question 1 du deuxième script.")
    mark(base, u06q1["entry_id"])

    # 5. reading
    rd = expect(base, "POST", "/reading/examples/rd-notice-piscine", (200, 201))
    rd_ex = rd.get("current_exercise_id") or (rd.get("exercise") or {}).get("id") or (rd.get("exercises") or [{}])[0].get("id")
    if not rd_ex:
        raise SystemExit(f"reading import: no exercise id in {sorted(rd)}")
    _, rdq1 = capture(base, "r4-rd-piscine-q1", {"type": "reading_item", "record_id": rd_ex, "item": 1}, "Question 1 de la notice de la piscine.")
    mark(base, rdq1["entry_id"])

    # 6. a second Speaking prompt with one confirmed typed take
    prompts = [p["id"] for p in expect(base, "GET", "/speaking/prompts", (200,))["prompts"] if p["id"] != "sp-invitation-reponse"]
    view = expect(base, "POST", f"/speaking/prompts/{prompts[0]}", (201,))
    take = expect(base, "POST", f"/speaking/exercises/{view['exercise']['id']}/takes", (201,), {"audio_source": "none"})["take_id"]
    expect(base, "POST", f"/speaking/takes/{take}/transcripts", (201,), {"text": "Bonjour, je voudrais des renseignements sur les horaires, s'il vous plaît."})

    # 7. legacy-style record without a source, 8. a refused duplicate, 9. long French text
    _, legacy = capture(base, "r4-legacy-no-source", None, "Une ancienne note sans source : « en » ou « y » ?")
    dup_status, dup = capture(base, "r4-duplicate", {"type": "listening_item", "record_id": ex2, "item": 2}, "Encore la question 2.", statuses=(409,))
    _, longq = capture(base, "r4-long-french", {"type": "listening_item", "record_id": ex2, "item": 3}, LONG)
    mark(base, longq["entry_id"])

    today = expect(base, "GET", "/review-today?zone=Europe/Paris", (200,))
    out = {**facts, "revision2_exercise": ex2, "u06_material": u06["material"]["id"], "reading_exercise": rd_ex,
           "second_speaking_exercise": view["exercise"]["id"], "legacy_entry": legacy["entry_id"],
           "duplicate": {"status": dup_status, "code": dup.get("code"), "entry_id": dup.get("entry_id")},
           "grouped": {"lead": q2r2["entry_id"], "also": [r1[2]]}, "long_entry": longq["entry_id"],
           "queue": [{"key": it["key"], "reason": it["reason"], "also": it.get("also_entry_ids")} for it in today["items"]],
           "history": today["history"]}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
