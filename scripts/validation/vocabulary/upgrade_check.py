#!/usr/bin/env python3
"""A pre-feature database through migration 022 on disposable copies (VOC-019, VOC-068, VOC-139, VOC-142).

    python3 -I scripts/validation/vocabulary/upgrade_check.py WORK --old-binary OLD_SERVER [--binary NEW_SERVER]

WORK must be absolute, outside the repository, and new or empty. OLD_SERVER is a server built from a tree
without migration 022 (the start tree); NEW_SERVER defaults to one built from this tree.

  1. the old server seeds the synthetic Vocabulary fixture on a fresh database (ledger 021), then stops;
  2. inventory.py records the baseline;
  3. a COPY is opened by the new server (it applies 022): the empty book reads, a first save works;
  4. inventory.py --expect baseline on that copy: every pre-existing table has the same rows and digest
     (no missing family, no content change); only the vocabulary tables are new;
  5. another copy of the upgraded database is opened by the OLD server: what it can read is recorded.
Writes WORK/upgrade_check.json. Exit 0 when steps 3 and 4 hold, 1 otherwise, 2 refused.
"""
import json
import os
import shutil
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
INV = REPO / "scripts/validation/migration/inventory.py"
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append({"check": name, "pass": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name} {'' if ok else detail}".rstrip(), flush=True)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(base, method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    def parse(b):
        try:
            return json.loads(b or b"null")
        except ValueError:
            return {"text": b.decode("utf-8", "replace")[:200]}
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, parse(r.read())
    except urllib.error.HTTPError as e:
        return e.code, parse(e.read())


class Server:
    def __init__(self, binary, db, d, stub_port):
        d.mkdir(parents=True, exist_ok=True)
        port = free_port()
        self.url = f"http://127.0.0.1:{port}"
        env = {"PATH": "/usr/bin:/bin", "HOME": str(d), "LISTEN_HOST": "127.0.0.1", "PORT": str(port), "DB_PATH": str(db),
               "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "openai", "OPENAI_API_KEY": "sk-local-demo-not-a-secret",
               "OPENAI_BASE_URL": f"http://127.0.0.1:{stub_port}", "OPENAI_MODEL": "stub-model", "EMBEDDING_PROVIDER": "disabled",
               "SPEAKING_PROVIDER": "disabled", "SPEAKING_TRANSCRIPTION_PROVIDER": "disabled", "LISTENING_PROVIDER": "disabled"}
        self.log = open(d / "server.log", "ab")
        self.proc = subprocess.Popen([str(binary)], cwd=d, env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        self.ok = False
        end = time.time() + 30
        while time.time() < end and self.proc.poll() is None:
            try:
                if urllib.request.urlopen(self.url + "/readyz", timeout=2).status == 200:
                    self.ok = True
                    break
            except OSError:
                time.sleep(0.1)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
        self.proc.wait(timeout=20)
        self.log.close()


def copy_db(src: Path, dst: Path):
    dst.mkdir(parents=True)
    for p in src.iterdir():
        if p.name.startswith("app.db"):
            shutil.copy2(p, dst / p.name)


def inventory(src, out, expect=None):
    cmd = [sys.executable, "-I", "-B", str(INV), str(src), "--out", str(out)] + (["--expect", str(expect)] if expect else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, json.loads((out / "inventory.json").read_text())


def main():
    args = sys.argv[1:]
    opts = {"--old-binary": None, "--binary": None}
    for k in list(opts):
        if k in args:
            i = args.index(k)
            opts[k] = args[i + 1]
            args = args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]) or not opts["--old-binary"]:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    w = Path(os.path.realpath(args[0]))
    if w == REPO or REPO in w.parents or (w.exists() and any(w.iterdir())):
        print("refused: WORK must be outside the repository and new or empty", file=sys.stderr)
        return 2
    w.mkdir(parents=True)
    new = Path(opts["--binary"]) if opts["--binary"] else w / "bin" / "server"
    if not opts["--binary"]:
        subprocess.run(["go", "build", "-trimpath", "-o", str(new), "./cmd/server"], cwd=REPO, env=dict(os.environ, GOFLAGS="-buildvcs=false"), check=True)
    old = Path(opts["--old-binary"])
    sp = free_port()
    stub = subprocess.Popen([sys.executable, "-I", "-B", str(REPO / "scripts/demo/vocabulary/stub_extractor.py"), str(sp)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    out = {}
    try:
        # 1. the pre-feature database
        pre = w / "pre"
        s = Server(old, pre / "app.db", pre, sp)
        check("the old server starts on a fresh database", s.ok)
        seed = subprocess.run([sys.executable, "-I", "-B", str(REPO / "scripts/demo/vocabulary/seed.py"), s.url], capture_output=True, text=True)
        status, _ = call(s.url, "GET", "/vocabulary")
        s.stop()
        check("the fixture seeds through the old server's API", seed.returncode == 0, seed.stderr[-300:])
        check("the old server has no vocabulary route", status == 404, status)
        facts = json.loads(seed.stdout.strip().splitlines()[-1])
        # 2. baseline
        code, base = inventory(pre, w / "inv-pre")
        check("baseline inventory of the pre-feature database", base.get("ledger", {}).get("count") == 21, base.get("ledger"))
        # 3. upgrade a copy with the new server
        up = w / "upgraded"
        copy_db(pre, up)
        n = Server(new, up / "app.db", up, sp)
        check("the new server starts on the pre-feature copy (applies 022)", n.ok)
        st, empty = call(n.url, "GET", "/vocabulary")
        check("old data without any vocabulary row reads as an empty book", st == 200 and empty.get("saved") == 0 and empty.get("items") == [], empty)
        st, saved = call(n.url, "PUT", f"/vocabulary/{facts['concept_apporter']}", {"unit_id": facts["unit_apporter"]})
        check("a first save works on the upgraded copy", st == 200 and saved.get("saved_now") is True, saved)
        n.stop()
        # 4. nothing pre-existing changed
        code, after = inventory(up, w / "inv-up", w / "inv-pre" / "inventory.json")
        e = after["expect"]
        bd, ad = base["table_digests"], after["table_digests"]
        changed = sorted(t for t in bd if t != "schema_migrations" and ad.get(t) != bd[t])
        added = sorted(t for t in ad if t not in bd)
        check("every pre-existing table keeps its rows and digest (all tables but the ledger); only vocabulary is new",
              not e["missing"] and not e["content_differs"] and changed == [] and added == ["vocabulary_examples", "vocabulary_marks"]
              and sorted(x.split(" ")[0] for x in e["newer"]) == ["vocabulary_examples", "vocabulary_marks"],
              {"changed": changed, "added": added, "expect": e})
        out["tables_compared"] = len([t for t in bd if t != "schema_migrations"])
        check("the upgraded ledger is 022", after.get("ledger", {}).get("count") == 22 and after.get("ledger", {}).get("parity") == "EQUAL", after.get("ledger"))
        out["upgrade"] = {"pre_ledger": base["ledger"], "post_ledger": after["ledger"], "newer": e["newer"]}
        # 5. the old server on an upgraded copy
        older = w / "older"
        copy_db(up, older)
        o = Server(old, older / "app.db", older, sp)
        if o.ok:
            st1, concepts = call(o.url, "GET", "/concepts")
            st2, _ = call(o.url, "GET", "/vocabulary")
            out["older_version"] = {"starts": True, "concepts_status": st1, "concepts": len((concepts or {}).get("concepts", [])), "vocabulary_status": st2}
            o.stop()
        else:
            o.stop()
            log = (older / "server.log").read_text()[-400:]
            out["older_version"] = {"starts": False, "log_tail": log}
        print("older version:", json.dumps(out["older_version"])[:300])
    finally:
        stub.send_signal(signal.SIGTERM)
        stub.wait(timeout=10)
    out["checks"] = CHECKS
    (w / "upgrade_check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    failed = [c for c in CHECKS if not c["pass"]]
    print(f"{'PASS' if not failed else 'FAIL'}: {len(CHECKS) - len(failed)}/{len(CHECKS)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
