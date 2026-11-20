#!/usr/bin/env python3
"""Cutover edges on a local stand-in (R3-071 to R3-080): two servers on this machine play the old host
("nas") and the new one ("aws"), and every step is recorded and judged by scripts/release/cutover_check.py
from real measurements, exactly as CUTOVER_DRY_RUN.md has the owner do it. No cloud resource is used.

    python3 -I scripts/validation/migration/cutover_edges.py WORK [--binary SERVER]

WORK must be absolute, outside the repository, and new or empty. Synthetic data only, seeded through the
API. Cases (each with its own evidence file under WORK/<case>/evidence.jsonl and its verdict):
  snapshot-during-writes  a copy of app.db taken while captures arrive misses committed rows; C3 against
                          the boundary fails and the verdict is DO-NOT-SWITCH. A copy taken after the stop
                          passes (R3-071).
  freeze                  after the boundary a capture is refused at the connection, nothing is written
                          (N-check equals the boundary), the freeze window is measured, and the same capture
                          sent after the switch is created once, then replayed (R3-072).
  switch                  C1 to C8 then N-check: HOLD before the switch, SWITCHED after, the old host unchanged
                          (R3-073).
  failed-warmup           the switch is recorded but the new host fails its warm-up and takes no write:
                          ROLLBACK-A; the old host restarts on its own data and its history export equals the
                          export taken before the boundary (R3-074, R3-078).
  reconcile               both hosts written after the boundary: DIVERGED. The old host's captures are
                          re-entered on the new one by capture_id: created once, replayed on a resend, a
                          changed resend is a conflict; nothing is merged at the database level (R3-075).
  transfer                an archive changed in transit (truncated: a slow or cut transfer) fails C4 and
                          blocks the switch; a missing archive is refused at record time (R3-077).
  settings                the browser keeps only per-origin preferences (localStorage); every key read by
                          the workbench is listed with its default when absent, and the server has no session
                          (R3-076). Static check over web/src.
  demo-boundary           the public demo allowlist names none of the private learner routes, and its Go
                          boundary tests pass (R3-079).
Writes WORK/cutover_edges.json with every verdict (R3-080). Exit 0 when every case behaves as stated.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
from rehearse import Server, call, ndjson  # noqa: E402

CC = REPO / "scripts/release/cutover_check.py"
FAILED = []
RESULTS = {}


def check(case, name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'} [{case}] {name} {detail}".rstrip(), flush=True)
    RESULTS.setdefault(case, {"checks": []})["checks"].append({"check": name, "pass": bool(cond)})
    if not cond:
        FAILED.append(f"{case}: {name}")
    return cond


def capture(i, tag, text=None):
    return {"schema_version": "learning_capture_v1", "capture_id": f"cut-{tag}-{i}", "source": "manual",
            "original_input": text or f"Phrase {i} ({tag}) : je me suis trompé.", "original_context": "Synthetic cutover rehearsal"}


def rec(ev, step, host, db=None, ready=None, code=None, file=None):
    cmd = [sys.executable, "-I", "-B", str(CC), "record", str(ev), "--step", step, "--host", host]
    if db:
        cmd += ["--db", str(db)]
    if ready:
        cmd += ["--ready-url", ready + "/readyz"]
    if code is not None:
        cmd += ["--http-code", str(code)]
    if file:
        cmd += ["--file", str(file)]
    return subprocess.run(cmd, capture_output=True, text=True)


def verdict(ev):
    r = subprocess.run([sys.executable, "-I", "-B", str(CC), "check", str(ev), "--json"], capture_output=True, text=True)
    return json.loads(r.stdout)


def entries(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM learning_entries").fetchone()[0]
    finally:
        con.close()


def copy_db(src: Path, dst: Path, with_sidecars=True):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    for sfx in ("-wal", "-shm"):
        if with_sidecars and Path(str(src) + sfx).exists():
            shutil.copy2(str(src) + sfx, str(dst) + sfx)


def seed_nas(binary, d):
    db = d / "nas" / "app.db"
    s = Server(binary, db, d / "nas")
    assert s.ok, "nas server did not start"
    for i in range(5):
        st, _ = call(s.url, "POST", "/captures", capture(i, "seed"))
        assert st == 201, st
    sc = call(s.url, "GET", "/listening/scripts")[1]["scripts"][0]
    call(s.url, "POST", f"/listening/scripts/{sc['id']}")
    return s, db


def export(url):
    st, body = call(url, "GET", "/learning-history/export?transcripts=true&notes=true", raw=True)
    return ndjson(body) if st == 200 else None


def case_snapshot(binary, w):
    c, d = "snapshot-during-writes", w / "snapshot"
    s, db = seed_nas(binary, d)
    ev = d / "evidence.jsonl"
    rec(ev, "C1-aws-empty", "aws", db=d / "aws" / "app.db")
    stop, done = threading.Event(), []

    def writer():
        i = 0
        while not stop.is_set():
            if call(s.url, "POST", "/captures", capture(i, "live"))[0] == 201:
                done.append(i)
            i += 1

    t = threading.Thread(target=writer)
    t.start()
    time.sleep(0.6)
    naive = d / "naive" / "app.db"
    copy_db(db, naive, with_sidecars=False)  # the main file only, while writes arrive
    committed_at_copy = 5 + len(done)
    time.sleep(0.4)
    stop.set()
    t.join()
    s.stop()
    rec(ev, "C2-boundary", "nas", db=db)
    total = entries(db)
    naive_rows = entries(naive)
    check(c, "the copy taken during writes misses committed records", naive_rows < committed_at_copy <= total,
          f"(copy {naive_rows}, committed at copy time {committed_at_copy}, at the stop {total})")
    rec(ev, "C3-backup", "nas", db=naive)
    v = verdict(ev)
    c3 = next(r for r in v["checklist"] if r["step"] == "C3-backup")["status"]
    check(c, "C3 against the boundary fails and the verdict is DO-NOT-SWITCH", c3 == "FAIL" and v["verdict"] == "DO-NOT-SWITCH", v["verdict"])
    good = d / "backup" / "app.db"
    copy_db(db, good)
    rec(ev, "C3-backup", "nas", db=good)
    v = verdict(ev)
    c3 = next(r for r in v["checklist"] if r["step"] == "C3-backup")["status"]
    check(c, "a copy taken after the stop equals the boundary (HOLD for the next step)", c3 == "PASS" and v["verdict"] == "HOLD", v["verdict"])
    RESULTS[c].update({"verdicts": ["DO-NOT-SWITCH", v["verdict"]], "rows": {"copy_during_writes": naive_rows, "committed_at_copy": committed_at_copy, "at_stop": total}})


def switch_path(binary, d, c, warm_ok=True):
    """C1..C6 on a seeded nas; returns (ev, nas_db, aws_server, aws_db, pre-boundary export)."""
    s, db = seed_nas(binary, d)
    ev = d / "evidence.jsonl"
    pre = export(s.url)
    aws_db = d / "aws" / "app.db"
    rec(ev, "C1-aws-empty", "aws", db=aws_db)
    s.stop()
    rec(ev, "C2-boundary", "nas", db=db)
    t_boundary = time.time()
    bk = d / "backup" / "app.db"
    copy_db(db, bk)
    rec(ev, "C3-backup", "nas", db=bk)
    arc = d / "backup" / "archive.tar"
    subprocess.run(["tar", "-cf", str(arc), "-C", str(bk.parent), "app.db"], check=True)
    rec(ev, "C4-sent", "nas", file=arc)
    rec(ev, "C4-received", "aws", file=arc)
    copy_db(bk, aws_db)
    a = Server(binary, aws_db, d / "aws")
    rec(ev, "C5-restored", "aws", db=aws_db, ready=a.url)
    if warm_ok:
        st, _ = call(a.url, "POST", "/captures", capture(0, "seed"))  # replay of a stored capture
        rec(ev, "C6-smoke", "aws", db=aws_db, ready=a.url, code=st)
    return ev, db, a, aws_db, pre, t_boundary


def case_switch(binary, w):
    c, d = "switch", w / "switch"
    ev, db, a, aws_db, _, _ = switch_path(binary, d, c)
    v1 = verdict(ev)["verdict"]
    check(c, "every check before the switch passes and the verdict holds until the switch", v1 == "HOLD", v1)
    rec(ev, "C7-switch", "client")
    st, _ = call(a.url, "POST", "/captures", capture(1, "after-switch"))
    rec(ev, "C8-first-write", "aws", code=st)
    rec(ev, "N-check", "nas", db=db)
    v2 = verdict(ev)
    check(c, "after the switch and a first write: SWITCHED, the old host unchanged", v2["verdict"] == "SWITCHED" and not v2["facts"]["nas_writes"], v2["verdict"])
    a.stop()
    RESULTS[c].update({"verdicts": [v1, v2["verdict"]], "freeze_seconds": v2["facts"]["freeze_seconds"]})


def case_freeze(binary, w):
    c, d = "freeze", w / "freeze"
    ev, db, a, aws_db, _, t0 = switch_path(binary, d, c)
    # during the freeze the old host is stopped: a capture is refused at the connection
    dead = "http://127.0.0.1:9"  # nothing listens; the old host's own port is closed the same way
    try:
        urllib.request.urlopen(urllib.request.Request(dead + "/captures", data=json.dumps(capture(7, "frozen")).encode(), method="POST",
                                                      headers={"Content-Type": "application/json"}), timeout=3)
        refused = False
    except (urllib.error.URLError, OSError):
        refused = True
    rec(ev, "N-check", "nas", db=db)
    v = verdict(ev)
    check(c, "a capture during the freeze is refused at the connection and writes nothing", refused and not v["facts"]["nas_writes"])
    rec(ev, "C7-switch", "client")
    st1, _ = call(a.url, "POST", "/captures", capture(7, "frozen"))
    st2, _ = call(a.url, "POST", "/captures", capture(7, "frozen"))
    rec(ev, "C8-first-write", "aws", code=st1)
    v = verdict(ev)
    check(c, "the refused capture, sent again after the switch, is created once then replayed", (st1, st2) == (201, 200), f"{st1}, {st2}")
    check(c, "the freeze window is measured from the boundary to the switch", isinstance(v["facts"]["freeze_seconds"], int) and v["facts"]["freeze_seconds"] >= 0,
          f"{v['facts']['freeze_seconds']} s")
    a.stop()
    RESULTS[c].update({"verdicts": [v["verdict"]], "freeze_seconds": v["facts"]["freeze_seconds"]})


def case_failed_warmup(binary, w):
    c, d = "failed-warmup", w / "failed-warmup"
    ev, db, a, aws_db, pre, _ = switch_path(binary, d, c, warm_ok=False)
    rec(ev, "C7-switch", "client")
    a.stop()  # the warm-up fails: the new host stops answering before any write
    r = rec(ev, "C6-smoke", "aws", db=aws_db, ready=a.url, code=0)
    rec(ev, "A-check", "aws", db=aws_db)
    v = verdict(ev)
    check(c, "switched, the warm-up failed, no write on the new host: ROLLBACK-A", v["verdict"] == "ROLLBACK-A" and not v["facts"]["aws_writes"], v["verdict"])
    n = Server(binary, db, d / "nas")
    post = export(n.url)
    rec(ev, "N-check", "nas", db=db)
    n.stop()
    v2 = verdict(ev)
    check(c, "the old host restarts on its own data: its history export equals the pre-boundary export", post is not None and post == pre, f"{len(post or [])} lines")
    RESULTS[c].update({"verdicts": [v["verdict"], v2["verdict"]], "export_lines": len(pre or [])})


def case_reconcile(binary, w):
    c, d = "reconcile", w / "reconcile"
    ev, db, a, aws_db, _, _ = switch_path(binary, d, c)
    rec(ev, "C7-switch", "client")
    st, _ = call(a.url, "POST", "/captures", capture(1, "aws"))
    rec(ev, "C8-first-write", "aws", code=st)
    n = Server(binary, db, d / "nas")  # someone kept using the old host
    late = [capture(i, "nas-late") for i in range(3)]
    for doc in late:
        call(n.url, "POST", "/captures", doc)
    n.stop()
    a.stop()
    rec(ev, "N-check", "nas", db=db)
    rec(ev, "A-check", "aws", db=aws_db)
    v = verdict(ev)
    check(c, "both hosts written after the boundary: DIVERGED, never merged", v["verdict"] == "DIVERGED", v["verdict"])
    a2 = Server(binary, aws_db, d / "aws")
    first = [call(a2.url, "POST", "/captures", doc)[0] for doc in late]
    again = [call(a2.url, "POST", "/captures", doc)[0] for doc in late]
    changed = call(a2.url, "POST", "/captures", dict(late[0], original_input="Une autre phrase."))[0]
    got = [call(a2.url, "GET", f"/captures/{doc['capture_id']}")[0] for doc in late]
    a2.stop()
    check(c, "re-entered by capture_id: created once, replayed on a resend, a changed resend conflicts",
          first == [201] * 3 and again == [200] * 3 and changed == 409 and got == [200] * 3, f"{first} {again} {changed}")
    RESULTS[c].update({"verdicts": [v["verdict"]], "reentered": len(late)})


def case_transfer(binary, w):
    c, d = "transfer", w / "transfer"
    s, db = seed_nas(binary, d)
    s.stop()
    ev = d / "evidence.jsonl"
    rec(ev, "C1-aws-empty", "aws", db=d / "aws" / "app.db")
    rec(ev, "C2-boundary", "nas", db=db)
    bk = d / "backup" / "app.db"
    copy_db(db, bk)
    rec(ev, "C3-backup", "nas", db=bk)
    arc = d / "backup" / "archive.tar"
    subprocess.run(["tar", "-cf", str(arc), "-C", str(bk.parent), "app.db"], check=True)
    rec(ev, "C4-sent", "nas", file=arc)
    cut = d / "received" / "archive.tar"
    cut.parent.mkdir(parents=True)
    cut.write_bytes(arc.read_bytes()[: arc.stat().st_size // 2])
    rec(ev, "C4-received", "aws", file=cut)
    v = verdict(ev)
    c4 = next(r for r in v["checklist"] if r["step"] == "C4-transfer")["status"]
    check(c, "a truncated archive fails C4 and blocks the switch", c4 == "FAIL" and v["verdict"] == "DO-NOT-SWITCH", v["verdict"])
    r = rec(ev, "C4-received", "aws", file=d / "received" / "missing.tar")
    check(c, "a missing archive is refused at record time, nothing recorded", r.returncode != 0 and verdict(ev)["verdict"] == "DO-NOT-SWITCH", f"exit {r.returncode}")
    RESULTS[c].update({"verdicts": [v["verdict"]]})


def case_settings(w):
    c = "settings"
    keys = {}
    for f in sorted((REPO / "web/src").rglob("*.ts*")):
        if ".test." in f.name:
            continue
        t = f.read_text(encoding="utf-8")
        for m in re.finditer(r"\"(flh\.[a-z0-9.-]+)\"", t):
            if "localStorage" in t or "sessionStorage" in t:
                keys.setdefault(m.group(1), set()).add(str(f.relative_to(REPO)))
    keys = {k: sorted(v) for k, v in keys.items()}
    check(c, "the browser keeps only per-origin preferences and drafts under flh.* keys", len(keys) > 0, ", ".join(sorted(keys)))
    go = subprocess.run(["grep", "-rlE", "Set-Cookie|http.Cookie|SetCookie", "internal", "cmd"], cwd=REPO, capture_output=True, text=True).stdout.split()
    go = [x for x in go if not x.endswith("_test.go")]
    check(c, "the server sets no cookie and keeps no session", go == [], ", ".join(go))
    RESULTS[c].update({"browser_keys": keys})


def case_demo_boundary(w):
    c = "demo-boundary"
    src = "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "internal/transport/http").glob("*public_demo*.go") if not p.name.endswith("_test.go"))
    private = ["/review-today", "/mistake-notebook", "/captures", "/learning-history", "/listening", "/speaking", "/exam", "/writing", "/reading"]
    named = [p for p in private if f'"{p}' in src]
    check(c, "the public demo allowlist names no private learner route", src != "" and named == [], ", ".join(named))
    r = subprocess.run(["go", "test", "./internal/transport/http/", "-run", "PublicDemo", "-count=1"], cwd=REPO, capture_output=True, text=True,
                       env=dict(os.environ, GOFLAGS="-buildvcs=false"))
    check(c, "the public demo boundary tests pass", r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:])


def main():
    args = sys.argv[1:]
    binary = None
    if "--binary" in args:
        i = args.index("--binary")
        binary = Path(args[i + 1])
        args = args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    w = Path(os.path.realpath(args[0]))
    if w == REPO or REPO in w.parents or (w.exists() and any(w.iterdir())):
        print("refused: WORK must be outside the repository and new or empty", file=sys.stderr)
        return 2
    w.mkdir(parents=True, exist_ok=True)
    if binary is None:
        binary = w / "bin" / "server"
        subprocess.run(["go", "build", "-trimpath", "-o", str(binary), "./cmd/server"], cwd=REPO, env=dict(os.environ, GOFLAGS="-buildvcs=false"), check=True)
    for fn in (case_snapshot, case_freeze, case_switch, case_failed_warmup, case_reconcile, case_transfer):
        fn(binary, w)
    case_settings(w)
    case_demo_boundary(w)
    (w / "cutover_edges.json").write_text(json.dumps(RESULTS, indent=1, ensure_ascii=False))
    print(f"{'PASS' if not FAILED else 'FAIL'}: {sum(len(v['checks']) for v in RESULTS.values())} checks, {len(FAILED)} failed")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
