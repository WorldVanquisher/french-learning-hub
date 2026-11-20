#!/usr/bin/env python3
"""A synthetic restore, then learning on the restored data (R4 Workbooks; scratch only, no Docker).

    python3 -I scripts/validation/review_today_r4/restore_learning.py WORK [--binary SERVER]

WORK must be absolute, outside the repository, and new or empty. Without --binary the server is built
from this tree. Every step below uses the synthetic R4 profile (scripts/demo/review_today_r4/profile.py)
on a fresh scratch database; nothing is ever written to daily data, and no provider is called.

  writes   while captures arrive, a copy of app.db alone and a copy with its sidecars are taken, then
           compared with what was committed (R4-WB-048)
  source   the server is stopped; the source's API views are recorded first (Review Today, the
           notebook, a Speaking exercise, the lessons, the history export); the inventory is the
           baseline (counts, digests, auxiliary files: R4-WB-042, R4-WB-043)
  backup   a stopped-database snapshot with SHA256SUMS, checked by backup_tool inspect; packed;
           transferred to a scratch copy; the archive's SHA-256 verified on arrival (R4-WB-046);
           a truncated archive and a mismatched checksum are refused, leaving nothing (R4-WB-047)
  restore  unpacked into a fresh target, integrity, restore_write_check, inventory --expect the
           baseline (READY, the same logical digest); the source files are byte-identical before
           and after (R4-WB-049); a target missing a family is blocked (R4-WB-045)
  learn    on the restored server: Review Today equals the source's (keys, groups, schedule); the
           grouped mistake's archived correction and its retry (done, then marked again); the
           historical Speaking exercise (takes, transcript versions, origin); the listening and
           reading lessons reach their quiz, and a mock exam starts (R4-WB-051 to R4-WB-054)
  outside  files beside the database, external links, embedded packs (R4-WB-055)
  privacy  default export without private text; provenance values match the approved patterns; the
           offline diagnosis names no learner text (R4-WB-034)
  timings  restore (unpack, verify, integrity, write check) and first session (start to ready, first
           Review Today) measured apart (R4-WB-057)
Writes WORK/restore_learning.json. Exit 0 when every check passes, 1 otherwise, 2 refused.
"""
import hashlib
import json
import os
import re
import shutil
import signal
import socket
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
INV = REPO / "scripts/validation/migration/inventory.py"
BT = REPO / "scripts/release/backup_tool.py"
WC = REPO / "scripts/release/restore_write_check.py"
DIAG = REPO / "scripts/release/diagnose.py"
PROVENANCE = re.compile(r"^(authored:[a-z0-9_]+|openai:[^:\s]+:[a-z0-9_]+|imported:[a-z_]+:[a-z0-9_]+|rule-based:v\d+:[a-z0-9_]+|manual|typed|corrected|transcription|learner|generated|authored)$")
LEARNER_TEXT = ["Je pensais que la responsable", "Salut Léa", "Chère Éloïse", "Question 2 encore manquée", "ancienne note sans source"]
RESULTS, FAILED = [], []


def check(step, name, ok, detail=""):
    RESULTS.append({"step": step, "check": name, "pass": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} [{step}] {name} {detail if not ok or isinstance(detail, str) else ''}".rstrip(), flush=True)
    if not ok:
        FAILED.append(name)
    return ok


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(base, method, path, body=None, headers=None, raw=False):
    data = body if isinstance(body, bytes) else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            b = r.read()
            return r.status, (b if raw else json.loads(b or b"null"))
    except urllib.error.HTTPError as e:
        b = e.read()
        return e.code, (b if raw else json.loads(b or b"null"))


class Server:
    def __init__(self, binary, db, d):
        d.mkdir(parents=True, exist_ok=True)
        self.url = f"http://127.0.0.1:{free_port()}"
        env = {"PATH": "/usr/bin:/bin", "HOME": str(d), "LISTEN_HOST": "127.0.0.1", "PORT": self.url.rsplit(":", 1)[1], "DB_PATH": str(db),
               "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled", "SPEAKING_PROVIDER": "disabled",
               "SPEAKING_TRANSCRIPTION_PROVIDER": "disabled", "LISTENING_PROVIDER": "disabled", "WRITING_PROVIDER": "disabled", "READING_PROVIDER": "disabled"}
        self.log = open(d / "server.log", "ab")
        t0 = time.perf_counter()
        self.proc = subprocess.Popen([str(binary)], cwd=d, env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        self.ok = False
        while time.perf_counter() - t0 < 30 and self.proc.poll() is None:
            try:
                if urllib.request.urlopen(self.url + "/readyz", timeout=2).status == 200:
                    self.ok = True
                    break
            except OSError:
                time.sleep(0.05)
        self.ready_ms = round((time.perf_counter() - t0) * 1000)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
        self.proc.wait(timeout=20)
        self.log.close()


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rows(db, table="learning_entries"):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


def views(url, facts):
    """The learner-facing reads compared between the source and the restored data."""
    _, today = call(url, "GET", "/review-today?zone=Europe/Paris")
    _, nb = call(url, "GET", "/mistake-notebook/items")
    _, ex = call(url, "GET", f"/speaking/exercises/{facts['speaking_exercise']}")
    _, lesson = call(url, "GET", f"/listening/materials/{facts['material_id']}")
    s, export = call(url, "GET", "/learning-history/export?transcripts=true&notes=true", raw=True)
    strip = lambda o: {k: v for k, v in o.items() if k not in ("generated_at",)} if isinstance(o, dict) else o
    lines = [json.loads(x) for x in export.decode().splitlines() if x.strip()] if s == 200 else None
    for ln in lines or []:
        ln.pop("exported_at", None)
        ln.pop("generated_at", None)
    return {"today": [{k: it.get(k) for k in ("key", "reason", "priority", "since", "also_entry_ids", "schedule")} for it in today["items"]],
            "history": today["history"],
            "notebook": [{k: it.get(k) for k in ("entry_id", "source", "reference", "link", "source_status", "retry", "generator")} for it in nb["items"]],
            "speaking": {"takes": [(t["number"], t["id"]) for t in ex["takes"]], "transcripts": [(t["take_id"], t["version"], t["origin"]) for t in ex["transcripts"]]},
            "lesson": {"current_exercise_id": lesson.get("current_exercise_id"), "revision": strip(lesson.get("script_revision"))},
            "export": lines}


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
    w.mkdir(parents=True)
    if binary is None:
        binary = w / "bin" / "server"
        subprocess.run(["go", "build", "-trimpath", "-o", str(binary), "./cmd/server"], cwd=REPO, env=dict(os.environ, GOFLAGS="-buildvcs=false"), check=True)
    py = [sys.executable, "-I", "-B"]
    out = {"timings_ms": {}}

    # source: seed, then the writes-during-snapshot comparison
    src = w / "source"
    db = src / "app.db"
    s = Server(binary, db, src)
    check("source", "server ready", s.ok)
    seed = subprocess.run(py + [str(REPO / "scripts/demo/review_today_r4/profile.py"), s.url, str(db)], capture_output=True, text=True)
    if not check("source", "the R4 profile seeds", seed.returncode == 0, seed.stderr[-300:]):
        s.stop()
        return 1
    facts = json.loads(seed.stdout.strip().splitlines()[-1])
    (src / "profile.json").write_text(json.dumps(facts, ensure_ascii=False))
    before_views = views(s.url, facts)
    stop, done = threading.Event(), []

    def writer():
        i = 0
        while not stop.is_set():
            st, _ = call(s.url, "POST", "/captures", {"schema_version": "learning_capture_v1", "capture_id": f"r4-live-{i}", "source": "manual",
                                                     "original_input": f"Phrase {i} écrite pendant la copie.", "original_context": "R4 synthetic writes"})
            if st == 201:
                done.append(i)
            i += 1

    t = threading.Thread(target=writer)
    t.start()
    time.sleep(0.6)
    alone, withside = w / "copies" / "alone", w / "copies" / "with-sidecars"
    for d in (alone, withside):
        d.mkdir(parents=True)
    committed = rows(db)
    shutil.copy2(db, alone / "app.db")
    for sfx in ("", "-wal", "-shm"):
        if Path(str(db) + sfx).exists():
            shutil.copy2(str(db) + sfx, withside / ("app.db" + sfx))
    time.sleep(0.4)
    stop.set()
    t.join()
    # the live writes are not part of the profile: remove them through nothing (they stay as records),
    # but the source views below are re-read after them
    after_writes = rows(db)
    a_rows = rows(alone / "app.db")
    s_rows = rows(withside / "app.db")
    check("writes", "a copy of app.db alone taken during writes misses committed records", a_rows < committed, f"copy {a_rows}, committed {committed}")
    check("writes", "a copy with its sidecars during writes is only as new as its moment; the stopped snapshot below is the one to restore",
          s_rows <= after_writes, f"copy {s_rows}, at the stop {after_writes}")
    out["writes"] = {"committed_at_copy": committed, "copy_alone": a_rows, "copy_with_sidecars": s_rows, "at_stop": after_writes}
    final_views = views(s.url, facts)
    s.stop()

    # baseline inventory of the stopped source
    base = w / "inventory" / "source"
    r = subprocess.run(py + [str(INV), str(src), "--out", str(base), "--zone", "Europe/Paris"], capture_output=True, text=True)
    inv = json.loads((base / "inventory.json").read_text())
    check("source", "baseline inventory READY", r.returncode == 0, inv.get("verdict"))
    aux = [a["name"] for a in inv.get("auxiliary", [])]
    check("source", "auxiliary files beside the database are listed with what they are", aux == ["profile.json", "server.log"], aux)
    out["baseline"] = {"rows": {k: v for k, v in inv["rows_by_table"].items() if v}, "logical_digest": inv["logical_digest"], "auxiliary": inv["auxiliary"]}
    src_files = {p.name: sha(p) for p in src.iterdir() if p.name.startswith("app.db")}

    # stopped snapshot, pack, transfer, verify
    t0 = time.perf_counter()
    bk = w / "backup" / "flh-20261120T120000Z"
    bk.mkdir(parents=True)
    for p in src.iterdir():
        if p.name.startswith("app.db"):
            shutil.copy2(p, bk / p.name)
    (bk / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.name}\n" for p in sorted(bk.iterdir()) if p.name != "SHA256SUMS"))
    r = subprocess.run(py + [str(BT), "inspect", str(bk), "--json"], capture_output=True, text=True)
    state = json.loads(r.stdout).get("state") if r.stdout.strip().startswith("{") else r.stdout[:200]
    check("backup", "the stopped snapshot inspects COMPLETE", state == "COMPLETE", state)
    arc = w / "backup" / "r4.tar.gz"
    r = subprocess.run(py + [str(BT), "pack", str(bk), str(arc)], capture_output=True, text=True)
    sent = (Path(str(arc) + ".sha256").read_text().split()[0]) if Path(str(arc) + ".sha256").exists() else None
    check("backup", "packed with its SHA-256", r.returncode == 0 and sent == sha(arc), r.stderr[-200:])
    xfer = w / "transfer"
    xfer.mkdir()
    shutil.copy2(arc, xfer / arc.name)
    check("backup", "the archive's SHA-256 on arrival equals the sent one", sha(xfer / arc.name) == sent)
    out["timings_ms"]["snapshot_pack_transfer"] = round((time.perf_counter() - t0) * 1000)
    # refusals
    cut = xfer / "truncated.tar.gz"
    cut.write_bytes((xfer / arc.name).read_bytes()[: arc.stat().st_size // 2])
    for name, archive, digest in (("truncated archive with its own digest", cut, sha(cut)), ("mismatched checksum", xfer / arc.name, "0" * 64)):
        dest = w / f"refused-{name.split()[0]}"
        dest.mkdir()
        r = subprocess.run(py + [str(BT), "unpack", str(archive), "--sha256", digest, str(dest)], capture_output=True, text=True)
        check("backup", f"a {name} is refused and leaves nothing", r.returncode != 0 and not any(dest.iterdir()), (r.stdout + r.stderr)[-160:])

    # restore into a fresh target
    t0 = time.perf_counter()
    tgt_parent = w / "target"
    tgt_parent.mkdir()
    r = subprocess.run(py + [str(BT), "unpack", str(xfer / arc.name), "--sha256", sent, str(tgt_parent)], capture_output=True, text=True)
    unpacked = [p for p in tgt_parent.iterdir() if p.is_dir()]
    check("restore", "unpacked into a fresh target", r.returncode == 0 and len(unpacked) == 1, r.stderr[-200:])
    data = w / "target-data"
    data.mkdir()
    for p in unpacked[0].iterdir():
        if p.name.startswith("app.db"):
            shutil.copy2(p, data / p.name)
    ok_sums = all(sha(data / ln[66:].strip()) == ln[:64] for ln in (unpacked[0] / "SHA256SUMS").read_text().splitlines() if ln.strip())
    con = sqlite3.connect(f"file:{data / 'app.db'}?mode=ro", uri=True)
    integ = con.execute("PRAGMA integrity_check").fetchone()[0]
    con.close()
    wc = subprocess.run(py + [str(WC), str(data)], capture_output=True, text=True)
    out["timings_ms"]["restore_unpack_verify_integrity_writecheck"] = round((time.perf_counter() - t0) * 1000)
    check("restore", "SHA256SUMS hold, integrity ok, the first write is possible", ok_sums and integ == "ok" and wc.returncode == 0, f"{ok_sums} {integ} {wc.returncode}")
    tinv = w / "inventory" / "target"
    r = subprocess.run(py + [str(INV), str(data), "--out", str(tinv), "--zone", "Europe/Paris", "--expect", str(base / "inventory.json")], capture_output=True, text=True)
    ti = json.loads((tinv / "inventory.json").read_text())
    check("restore", "the target inventory is READY with the baseline's logical digest", r.returncode == 0 and ti["expect"]["same_logical_digest"], ti.get("verdict"))
    check("restore", "the source files are byte-identical after everything", {p.name: sha(p) for p in src.iterdir() if p.name.startswith("app.db")} == src_files)
    # a target that lost a family is blocked
    lost = w / "target-lost"
    shutil.copytree(data, lost)
    con = sqlite3.connect(lost / "app.db")
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("DELETE FROM mistake_retry_marks")
    con.commit()
    con.close()
    r = subprocess.run(py + [str(INV), str(lost), "--out", str(w / "inventory" / "lost"), "--expect", str(base / "inventory.json")], capture_output=True, text=True)
    li = json.loads((w / "inventory" / "lost" / "inventory.json").read_text())
    check("restore", "a restored copy missing the retry marks is a blocking gate", r.returncode == 1 and any("mistake notebook" in m for m in li["expect"]["missing"]), li["expect"]["missing"])

    # learning on the restored server
    t0 = time.perf_counter()
    rs = Server(binary, data / "app.db", w / "target-run")
    out["timings_ms"]["first_session_start_to_ready"] = rs.ready_ms
    t1 = time.perf_counter()
    s_today, today = call(rs.url, "GET", "/review-today?zone=Europe/Paris")
    out["timings_ms"]["first_session_first_review_today"] = round((time.perf_counter() - t1) * 1000)
    out["timings_ms"]["first_session_total"] = round((time.perf_counter() - t0) * 1000)
    restored = views(rs.url, facts)
    for k in ("today", "history", "notebook", "speaking", "lesson", "export"):
        check("learn", f"restored {k} equals the source's", restored[k] == final_views[k], "" if restored[k] == final_views[k] else json.dumps([restored[k], final_views[k]], ensure_ascii=False)[:300])
    lead, also = facts["grouped"]["lead"], facts["grouped"]["also"]
    row = next((it for it in today["items"] if it["key"] == f"notebook:entry:{lead}"), None)
    check("learn", "Review Today right after restore keeps the grouped question as one row", row is not None and row.get("also_entry_ids") == also)
    items = {it["entry_id"]: it for it in call(rs.url, "GET", "/mistake-notebook/items")[1]["items"]}
    arch = items.get(also[0], {})
    check("learn", "the archived correction resolves on its own revision (reference, revision 1, authored)",
          arch.get("source_status") == "resolved" and arch.get("reference") and (arch.get("link") or {}).get("listening_transcript_version") == 1 and arch.get("reference_origin") == "authored",
          {k: arch.get(k) for k in ("source_status", "link", "reference_origin")})
    for eid in [lead, *also]:
        call(rs.url, "PUT", f"/mistake-notebook/items/{eid}/retry", {"marked": False})
    gone = all(it["key"] != f"notebook:entry:{lead}" for it in call(rs.url, "GET", "/review-today")[1]["items"])
    st, again = call(rs.url, "PUT", f"/mistake-notebook/items/{lead}/retry", {"marked": True})
    st2, again2 = call(rs.url, "PUT", f"/mistake-notebook/items/{lead}/retry", {"marked": True})
    back = any(it["key"] == f"notebook:entry:{lead}" for it in call(rs.url, "GET", "/review-today")[1]["items"])
    check("learn", "done, then marked again: the retry returns; a repeated mark changes nothing", gone and back and again.get("changed") is True and again2.get("changed") is False and lead in items)
    sp = restored["speaking"]
    check("learn", "the historical Speaking exercise keeps its takes and transcript versions with their origin",
          len(sp["takes"]) == 2 and any(o == "corrected" for _, _, o in sp["transcripts"]) and sp == before_views["speaking"], sp)
    st, lesson = call(rs.url, "GET", f"/listening/materials/{facts['material_id']}")
    st, revs = call(rs.url, "GET", f"/listening/materials/{facts['material_id']}/revisions/2")
    quiz = (revs or {}).get("exercise", {}).get("content", {}).get("items", [])
    check("learn", "the listening lesson reaches its authored quiz on revision 2", lesson.get("current_exercise_id") == facts["revision2_exercise"] and len(quiz) >= 3, len(quiz))
    st, forms = call(rs.url, "GET", "/exam/forms")
    form = ((forms or {}).get("forms") or [{}])[0].get("id")
    st, sess = call(rs.url, "POST", "/exam/sessions", {"form_id": form}, headers={"Idempotency-Key": "6a1f2c3d-4b5e-4f60-8a71-92b3c4d5e6f7"})
    qs = (sess or {}).get("questions") or ((sess or {}).get("session") or {}).get("questions") or []
    check("learn", "a mock exam starts on the restored data (its questions frozen)", st in (200, 201) and len(qs) > 0, f"{st} {len(qs)} questions; keys {sorted(sess or {})}")

    # outside the database
    files = sorted(p.name for p in data.iterdir())
    check("outside", "the restored data directory holds the database only", all(n.startswith("app.db") for n in files), files)
    out["outside"] = {"data_files": files, "external_links_not_fetched": ti["attachments"]["external_links_not_fetched"],
                      "audio": ti["attachments"]["audio_stored"], "pack_status": (lesson.get("script_revision") or {}).get("pack_status")}

    # privacy: exports and the diagnosis
    st, plain = call(rs.url, "GET", "/learning-history/export", raw=True)
    st2, full = call(rs.url, "GET", "/learning-history/export?transcripts=true&notes=true", raw=True)
    lines = [json.loads(x) for x in plain.decode().splitlines() if x.strip()]
    check("privacy", "the default export holds none of the profile's private texts", not any(t in plain.decode() for t in LEARNER_TEXT))
    check("privacy", "the learner's own flags add their texts", sum(t in full.decode() for t in LEARNER_TEXT) >= 2)
    prov = sorted({str(v) for ln in lines for k, v in (ln.items() if isinstance(ln, dict) else []) if k in ("generator", "origin", "provenance", "reference_origin") and v})
    bad = [p for p in prov if not PROVENANCE.match(p)]
    check("privacy", "every provenance value in the export matches an approved form", not bad, {"values": prov, "unapproved": bad})
    rs.stop()
    d = subprocess.run(py + [str(DIAG), "--data", str(data), "--port", rs.url.rsplit(":", 1)[1], "--json"], capture_output=True, text=True)
    blob = d.stdout + d.stderr
    check("privacy", "the offline diagnosis names no learner text", not any(t in blob for t in LEARNER_TEXT), d.stdout[:160])
    out["checks"] = RESULTS
    (w / "restore_learning.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"{'PASS' if not FAILED else 'FAIL'}: {len(RESULTS) - len(FAILED)}/{len(RESULTS)}; timings {json.dumps(out['timings_ms'])}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
