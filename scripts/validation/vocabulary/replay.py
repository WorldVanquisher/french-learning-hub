#!/usr/bin/env python3
"""Replay the Vocabulary fixture through the API and record every state transition (VOC-120, VOC-129,
VOC-130, VOC-141, VOC-143).

    python3 -I scripts/validation/vocabulary/replay.py WORK [--binary SERVER] [--check EXPECTED] [--write EXPECTED]

WORK must be absolute, outside the repository, and new or empty. Starts the local stub extractor and a
server on a FRESH database (fresh fixture import: scripts/demo/vocabulary/seed.py), then runs a fixed
sequence of learner actions and records, after each, the response status and the saved list's state:
saved count, rows (target, example statuses, review units). Times and database IDs are replaced by
stable names, so two runs give the same transcript (determinism).

The sequence: empty book; save all ten vocabulary terms (the ten-item review fixture: each term's
review input, i.e. its Concept and current supporting units, is written to WORK/ten_items.json);
repeat a save; add a second example; search accent-blind; refuse a grammar Concept; remove one
term; remove it again; save it again; re-extract a record (superseded example); search for a
translation.

--write EXPECTED stores the transcript; --check EXPECTED compares (exit 1 on a difference).
Exit 0 on success, 1 on a failed check, 2 refused.
"""
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.dont_write_bytecode = True


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(base, method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"null")
        except ValueError:
            return e.code, {"text": raw.decode("utf-8", "replace")[:100]}


def main():
    args = sys.argv[1:]
    opts = {"--binary": None, "--check": None, "--write": None}
    for k in list(opts):
        if k in args:
            i = args.index(k)
            opts[k] = args[i + 1]
            args = args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    w = Path(os.path.realpath(args[0]))
    if w == REPO or REPO in w.parents or (w.exists() and any(w.iterdir())):
        print("refused: WORK must be outside the repository and new or empty", file=sys.stderr)
        return 2
    w.mkdir(parents=True)
    binary = Path(opts["--binary"]) if opts["--binary"] else w / "bin" / "server"
    if not opts["--binary"]:
        subprocess.run(["go", "build", "-trimpath", "-o", str(binary), "./cmd/server"], cwd=REPO, env=dict(os.environ, GOFLAGS="-buildvcs=false"), check=True)
    sp, ap = free_port(), free_port()
    stub = subprocess.Popen([sys.executable, "-I", "-B", str(REPO / "scripts/demo/vocabulary/stub_extractor.py"), str(sp)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(w), "LISTEN_HOST": "127.0.0.1", "PORT": str(ap), "DB_PATH": str(w / "app.db"),
           "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "openai", "OPENAI_API_KEY": "sk-local-demo-not-a-secret",
           "OPENAI_BASE_URL": f"http://127.0.0.1:{sp}", "OPENAI_MODEL": "stub-model", "EMBEDDING_PROVIDER": "disabled",
           "SPEAKING_PROVIDER": "disabled", "SPEAKING_TRANSCRIPTION_PROVIDER": "disabled", "LISTENING_PROVIDER": "disabled"}
    log = open(w / "server.log", "ab")
    srv = subprocess.Popen([str(binary)], cwd=w, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    base = f"http://127.0.0.1:{ap}"
    try:
        for _ in range(300):
            try:
                if urllib.request.urlopen(base + "/readyz", timeout=2).status == 200:
                    break
            except OSError:
                time.sleep(0.1)
        seed = subprocess.run([sys.executable, "-I", "-B", str(REPO / "scripts/demo/vocabulary/seed.py"), base], capture_output=True, text=True)
        if seed.returncode != 0:
            print(seed.stderr, file=sys.stderr)
            return 1
        f = json.loads(seed.stdout.strip().splitlines()[-1])
        name = {v: k for k, v in f.items() if k.startswith("concept_")}
        unit_name = {v: k for k, v in f.items() if k.startswith("unit_")}
        steps = []

        def state(label, status, out=None):
            _, lst = call(base, "GET", "/vocabulary")
            rows = [{"concept": name.get(it["concept_id"], "?"), "target": (it["concept"] or {}).get("target"),
                     "state": (it["concept"] or {}).get("state"), "review_units": it["review_units"],
                     "examples": [{"unit": unit_name.get(e["unit_id"], "?"), "status": e["status"], "newer": e["newer_extraction"], "version": e["extraction_version"]} for e in it["examples"]]}
                    for it in lst["items"]]
            step = {"step": label, "status": status, "saved": lst["saved"], "rows": rows}
            if out and isinstance(out, dict):
                step["response"] = {k: out[k] for k in ("changed", "saved_now", "example_added", "code", "saved") if k in out}
            steps.append(step)

        state("empty book", 200)
        ten = [k for k in f if k.startswith("concept_") and k != "concept_grammar_concept"]
        review = []
        for key in ten:
            unit = f["unit_" + key[len("concept_"):]]
            st, out = call(base, "PUT", f"/vocabulary/{f[key]}", {"unit_id": unit})
            review.append({"concept": key, "target": out["item"]["concept"]["target"], "review_units": out["item"]["review_units"],
                           "question": out["item"]["examples"][0]["source"]["original_input"], "answer": out["item"]["examples"][0]["meaning"]})
            state(f"save {key}", st, out)
        st, out = call(base, "PUT", f"/vocabulary/{f['concept_apporter']}", {"unit_id": f["unit_apporter"]})
        state("repeat save of apporter (idempotent)", st, out)
        st, out = call(base, "PUT", f"/vocabulary/{f['concept_apporter']}", {"unit_id": f["unit_apporter2"]})
        state("second example for apporter (another record)", st, out)
        st, out = call(base, "GET", "/vocabulary?q=matinee")
        steps.append({"step": "search matinee (accent-blind)", "status": st, "found": [name[i["concept_id"]] for i in out["items"]]})
        st, out = call(base, "PUT", f"/vocabulary/{f['concept_grammar_concept']}", {"unit_id": f["unit_grammar"]})
        state("save a grammar Concept (refused)", st, out)
        st, out = call(base, "DELETE", f"/vocabulary/{f['concept_chat_en']}")
        state("remove chat (loanword)", st, out)
        st, out = call(base, "DELETE", f"/vocabulary/{f['concept_chat_en']}")
        state("remove it again (no change)", st, out)
        st, out = call(base, "PUT", f"/vocabulary/{f['concept_chat_en']}", {"unit_id": f["unit_chat_en"]})
        state("save it again (examples kept)", st, out)
        st, out = call(base, "POST", f"/entries/{f['entry_apporter']}/extractions")
        state("re-extract the first apporter record (superseded example)", st, {})
        st, out = call(base, "GET", "/vocabulary?q=" + urllib.request.quote("另一方面"))
        steps.append({"step": "search a Chinese meaning", "status": st, "found": [name[i["concept_id"]] for i in out["items"]]})
        transcript = {"fixture": "scripts/demo/vocabulary (synthetic)", "steps": steps}
        (w / "transcript.json").write_text(json.dumps(transcript, indent=1, ensure_ascii=False))
        (w / "ten_items.json").write_text(json.dumps({"schema": "flh_wb_vocabulary_review_fixture_v0", "items": review}, indent=1, ensure_ascii=False))
        print(f"{len(steps)} steps; ten-item review fixture: {len(review)} items")
        if opts["--write"]:
            Path(opts["--write"]).write_text(json.dumps(transcript, indent=1, ensure_ascii=False) + "\n")
            print(f"wrote {opts['--write']}")
        if opts["--check"]:
            want = json.loads(Path(opts["--check"]).read_text())
            if want != transcript:
                for a, b in zip(want["steps"], transcript["steps"]):
                    if a != b:
                        print("DIFFERS at", a.get("step"), "\nwant", json.dumps(a, ensure_ascii=False)[:400], "\ngot ", json.dumps(b, ensure_ascii=False)[:400])
                        break
                return 1
            print("transcript equals the expected one")
        return 0
    finally:
        for p in (srv, stub):
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=20)
        log.close()


if __name__ == "__main__":
    sys.exit(main())
