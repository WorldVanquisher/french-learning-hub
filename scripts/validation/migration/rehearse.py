#!/usr/bin/env python3
"""Rehearse moving a learner database from the NAS to a fresh staging volume (stand-in), on
deterministic synthetic fixtures, through the existing mechanisms only.

    python3 -I -B scripts/validation/migration/rehearse.py WORK_DIR [--fixtures v021-daily,v020-legacy]

WORK_DIR must be absolute, outside the repository, and new or empty. Nothing here touches the
daily instance or any real learner data: every database is built in WORK_DIR from synthetic
input, and the daily wrapper runs in its isolated mode (its own Compose project and image name;
no container is started, because a backup only needs the service stopped).

Fixtures (R3-021), each built twice to show its content is deterministic (a digest of every row
without its volatile columns: timestamps, operation IDs, audio digests of typed takes):
  v021-daily   the current schema: a fresh database written by this tree's server through the API
               (scripts/demo/learning_day/seed.py: a revised authored script with saved mistakes,
               Speaking takes with an own correction, Writing drafts) plus a Mock Exam session
  v020-legacy  the previous supported schema: scripts/release/upgrade_021/rehearse.py's populate
               (a local fake provider, no paid call) and its exact 020 conversion
Stages per fixture, each a PASS/FAIL line in results.json:
  inventory   inventory.py on the source (read-only; receipt kept)
  backup      `flh-daily.sh backup` (isolated mode), then backup_tool.py inspect: COMPLETE
  pack        backup_tool.py pack: archive size and SHA-256 (R3-023)
  transfer    the archive copied to an inbox; interrupted (half the bytes), damaged (one byte
              changed) and truncated-with-its-own-digest copies are refused by backup_tool.py
              unpack, leaving nothing behind (R3-027)
  restore     unpack onto a fresh private volume (stand-in for the staging EBS volume), then the
              RELEASE.md restore copy into an empty data directory, integrity_check (R3-024)
  write       restore_write_check.py passes; a read-only app.db and a read-only directory fail
              with the exact reason, and pass again once fixed (R3-028)
  serve       this tree's server starts on the restored data (a 020 copy is upgraded to 021 by
              its own migrations) and /readyz answers
  parity      inventory.py on the restored data: stable IDs (entries, capture IDs, notebook
              references, Speaking takes and their transcripts, script revisions) and every
              learner table's rows equal the source's, the 021 rebuild aside (R3-025, R3-026)
  export      the history export from a served copy of the source equals the restored one's, and
              import-preview of the source export on the restored server: complete, 0 new,
              0 conflicts (R3-029)
  receipt     backup_tool.py receipt (flh-recovery-receipt/v1) with the write check and timings
  repeat      a second restore into another empty directory gives the same logical digest; the
              source files are byte-identical and untouched throughout (R3-030)
Exit 0 when every check passes, 1 otherwise, 2 when refused.
"""
import hashlib
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True  # never write __pycache__ into the repository
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import entities  # noqa: E402

VOLATILE = {"created_at", "updated_at", "applied_at", "started_at", "finished_at", "deadline_at", "saved_at", "submitted_at",
            "lease_expires_at", "published_at", "operation_id", "content_fingerprint", "answers_sha256", "completed_at", "run_started_at"}
LEARNER_ROLES = ("learner", "learner-derived", "authored", "generated")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def call(base, method, path, body=None, raw=False):
    data = body if isinstance(body, bytes) else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            b = r.read()
            return r.status, (b if raw else json.loads(b or b"null"))
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Server:
    def __init__(self, binary, db, d):
        d.mkdir(parents=True, exist_ok=True)
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        env = {"PATH": "/usr/bin:/bin", "HOME": str(d), "LISTEN_HOST": "127.0.0.1", "PORT": str(self.port), "DB_PATH": str(db),
               "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled", "SPEAKING_PROVIDER": "disabled",
               "SPEAKING_TRANSCRIPTION_PROVIDER": "disabled", "LISTENING_PROVIDER": "disabled", "WRITING_PROVIDER": "disabled", "READING_PROVIDER": "disabled"}
        self.log = open(d / "server.log", "ab")
        self.proc = subprocess.Popen([str(binary)], cwd=d, env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        end = time.time() + 30
        self.ok = False
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


def content_digest(db: Path) -> tuple[str, dict]:
    """Every learner-facing row without its volatile columns: what must not change between two builds."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    per = {}
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        if entities.TABLES.get(t, {}).get("role") not in LEARNER_ROLES:
            continue
        cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")') if r[1] not in VOLATILE]
        rows = con.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{t}" ORDER BY rowid').fetchall()
        per[t] = hashlib.sha256(repr(rows).encode()).hexdigest()
    con.close()
    return hashlib.sha256(json.dumps(per, sort_keys=True).encode()).hexdigest(), per


def stable_ids(base) -> dict:
    """What a learner's links rest on, read through the API: never row text."""
    out = {}
    s, nb = call(base, "GET", "/mistake-notebook/items")
    items = nb.get("items", []) if s == 200 else []
    src = lambda it: it.get("source") if isinstance(it.get("source"), dict) else {}
    out["notebook"] = sorted((it.get("entry_id"), it.get("capture_id"), src(it).get("type"), src(it).get("record_id"), src(it).get("item"), it.get("source_status")) for it in items)
    s, mats = call(base, "GET", "/listening/materials")
    mats = mats.get("materials", []) if s == 200 else []
    out["listening"] = sorted((m["material"]["id"], m["material"].get("pack_script_id"), m.get("transcript_version")) for m in mats)
    revs = {}
    for m in mats:
        s, r = call(base, "GET", f"/listening/materials/{m['material']['id']}/revisions")
        if s == 200:
            revs[m["material"]["id"]] = [(x.get("revision"), x.get("transcript_version"), x.get("exercise_id")) for x in r.get("revisions", [])]
    out["script_revisions"] = revs
    s, sp = call(base, "GET", "/speaking/practice")
    ex = sorted(e["exercise"]["id"] for e in (sp.get("exercises", []) if s == 200 else []))
    takes = {}
    for eid in ex:
        s, v = call(base, "GET", f"/speaking/exercises/{eid}")
        if s == 200:
            takes[eid] = {"takes": sorted((t["id"], t["number"], t.get("audio_source"), t.get("audio_sha256")) for t in v.get("takes", [])),
                          "transcripts": sorted((x.get("id"), x.get("take_id"), x.get("version"), x.get("origin")) for x in v.get("transcripts", []) if isinstance(x, dict))}
    out["speaking_takes"] = takes
    s, today = call(base, "GET", "/review-today?zone=Europe/Paris")
    out["review_today_keys"] = sorted(it["key"] for it in today.get("items", [])) if s == 200 else None
    return out


def ndjson(body: bytes):
    rows = [json.loads(x) for x in body.decode("utf-8").splitlines() if x.strip()]

    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k not in ("exported_at", "generated_at")}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    return [strip(r) for r in rows]


def build_v021(work: Path, binary: Path, db: Path) -> dict:
    srv = Server(binary, db, work / "build-server")
    if not srv.ok:
        raise RuntimeError("server did not start for the v021 fixture")
    try:
        seed = subprocess.run([sys.executable, "-I", "-B", str(REPO / "scripts/demo/learning_day/seed.py"), srv.url, str(db)], capture_output=True, text=True)
        if seed.returncode != 0:
            raise RuntimeError(f"learning-day seed failed: {seed.stderr[-300:]}")
        facts = json.loads(seed.stdout.strip().splitlines()[-1])
        s, forms = call(srv.url, "GET", "/exam/forms")
        req = urllib.request.Request(srv.url + "/exam/sessions", data=json.dumps({"form_id": forms["forms"][0]["id"]}).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Idempotency-Key": "4f6d1c3e-8a7b-4c2d-9e1f-0a1b2c3d4e5f"})
        sess = json.loads(urllib.request.urlopen(req, timeout=30).read())
        n = len(sess["questions"])
        call(srv.url, "POST", f"/exam/sessions/{sess['session']['id']}/submit", {"answers": {str(i): None for i in range(1, n + 1)}})
        facts["exam_session"] = sess["session"]["id"]
    finally:
        srv.stop()
    return facts


def build_v020(work: Path, binary: Path, db: Path) -> dict:
    sys.path.insert(0, str(REPO / "scripts/release/upgrade_021"))
    import rehearse as r021  # the release lane's own 020 fixture builder (local fake provider only)
    for sub in ("run", "logs", "evidence"):
        (work / sub).mkdir(parents=True, exist_ok=True)
    facts = r021.populate(work, binary, db)
    pristine = work / "pristine-020.db"
    r021.build_pristine(pristine)
    r021.downgrade_to_020(db, pristine)
    return facts


def main():
    args = sys.argv[1:]
    fixtures = ["v021-daily", "v020-legacy"]
    if "--fixtures" in args:
        i = args.index("--fixtures")
        fixtures, args = args[i + 1].split(","), args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    work = Path(os.path.realpath(args[0]))
    if work == REPO or REPO in work.parents:
        print("refused: WORK_DIR must be outside the repository", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        print("refused: WORK_DIR must be new or empty", file=sys.stderr)
        return 2
    os.chmod(work, 0o700)
    results, timings = [], {}

    def check(fx, name, ok, detail=""):
        results.append({"fixture": fx, "name": name, "pass": bool(ok), "detail": detail if isinstance(detail, str) else json.dumps(detail, default=str)[:600]})
        print(("PASS" if ok else "FAIL"), fx, name, "" if ok else str(detail)[:400], flush=True)

    def tool(*a, **kw):
        return subprocess.run([sys.executable, "-I", "-B", *map(str, a)], capture_output=True, text=True, **kw)

    binary = work / "bin" / "server"
    subprocess.run(["go", "build", "-trimpath", "-o", str(binary), "./cmd/server"], cwd=REPO, env=dict(os.environ, GOFLAGS="-buildvcs=false"), check=True)
    run_id = hex(int(time.time()))[2:]
    builders = {"v021-daily": build_v021, "v020-legacy": build_v020}
    for fx in fixtures:
        F = work / fx
        F.mkdir(mode=0o700)
        T = {}
        # fixture, twice
        digests = []
        for k in ("a", "b"):
            bd = F / f"build-{k}"
            bd.mkdir()
            t = time.time()
            facts = builders[fx](bd, binary, bd / "app.db")
            T[f"build_{k}_s"] = round(time.time() - t, 1)
            digests.append(content_digest(bd / "app.db"))
        same = digests[0][0] == digests[1][0]
        check(fx, f"R3-021 the fixture is deterministic: two builds give the same content digest ({digests[0][0][:12]}…)", same,
              {t: (a[:12], digests[1][1].get(t, "")[:12]) for t, a in digests[0][1].items() if digests[1][1].get(t) != a})
        (F / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1, default=str))
        nas = F / "nas" / "data"
        nas.mkdir(parents=True, mode=0o700)
        os.chmod(F / "nas", 0o700)
        for side in ("", "-wal", "-shm"):
            if (F / "build-a" / f"app.db{side}").exists():
                shutil.copy2(F / "build-a" / f"app.db{side}", nas / f"app.db{side}")
        for p in nas.iterdir():
            os.chmod(p, 0o600)
        source_before = {p.name: (sha(p), p.stat().st_mtime_ns) for p in nas.iterdir()}
        # inventory of the source
        r = tool(HERE / "inventory.py", nas, "--out", F / "inventory-source", "--zone", "Europe/Paris")
        inv_src = json.loads((F / "inventory-source" / "inventory.json").read_text())
        check(fx, f"R3-011..R3-020 inventory of the source: {inv_src['verdict']} (exit {r.returncode}), source unchanged {inv_src['source_unchanged']}",
              r.returncode == 0 and inv_src["source_unchanged"], inv_src.get("problems"))
        # backup through the daily wrapper, isolated mode
        envf = F / "daily.env"
        envf.write_text(f"FLH_DATA_DIR={nas}\nFLH_QDRANT_DIR={F / 'nas' / 'qdrant'}\nFLH_UID={os.getuid()}\nFLH_GID={os.getgid()}\n"
                        f"FLH_HOST_PORT={free_port()}\nAI_PROVIDER=rule-based\nEXTRACTOR_PROVIDER=disabled\n")
        os.chmod(envf, 0o600)
        override = F / "compose.override.yaml"
        override.write_text(f"services:\n  app:\n    image: flh-r3-{run_id}-{fx}:app\n")
        env = dict(os.environ, FLH_DAILY_ENV=str(envf), FLH_COMPOSE_PROJECT=f"flh-r3-{run_id}-{fx}", FLH_COMPOSE_OVERRIDE=str(override))
        t = time.time()
        b = subprocess.run(["bash", str(REPO / "scripts/daily/flh-daily.sh"), "backup"], env=env, capture_output=True, text=True)
        T["backup_s"] = round(time.time() - t, 2)
        (F / "backup.log").write_text(b.stdout + b.stderr)
        backups = sorted((F / "nas" / "data.backups").glob("flh-*")) if (F / "nas" / "data.backups").exists() else []
        check(fx, "R3-022 `flh-daily.sh backup` (isolated project, no container running) wrote a verified backup", b.returncode == 0 and len(backups) == 1, (b.stdout + b.stderr)[-400:])
        if not backups:
            continue
        bk = backups[0]
        ins = tool(REPO / "scripts/release/backup_tool.py", "inspect", bk, "--json")
        insj = json.loads(ins.stdout) if ins.stdout.strip().startswith("{") else {}
        (F / "backup-inspect.json").write_text(ins.stdout)
        check(fx, f"R3-022 backup_tool.py inspect: {insj.get('state')}", ins.returncode == 0 and insj.get("state") == "COMPLETE", ins.stderr[-300:])
        # pack
        archive = F / "nas" / f"{bk.name}.tar.gz"
        t = time.time()
        pk = tool(REPO / "scripts/release/backup_tool.py", "pack", bk, archive)
        T["pack_s"] = round(time.time() - t, 2)
        digest = (archive.with_name(archive.name + ".sha256").read_text().split()[0] if archive.with_name(archive.name + ".sha256").exists() else "")
        size = archive.stat().st_size if archive.exists() else 0
        check(fx, f"R3-023 pack: {size} bytes, SHA-256 {digest[:12]}… (the database is {sum(p.stat().st_size for p in bk.glob('app.db*'))} bytes)",
              pk.returncode == 0 and digest == sha(archive), pk.stdout[-300:] + pk.stderr[-300:])
        # transfer and its failures
        inbox = F / "aws" / "inbox"
        inbox.mkdir(parents=True)
        os.chmod(F / "aws", 0o700)
        data = archive.read_bytes()
        cases = {"interrupted (half the bytes)": data[: len(data) // 2], "damaged (one byte changed)": data[:100] + bytes([data[100] ^ 1]) + data[101:]}
        for label, blob in cases.items():
            p = inbox / "bad.tar.gz"
            p.write_bytes(blob)
            dest = F / "aws" / f"bad-{len(label)}"
            dest.mkdir()
            u = tool(REPO / "scripts/release/backup_tool.py", "unpack", p, "--sha256", digest, dest)
            check(fx, f"R3-027 an {label} archive is refused with the published digest, nothing left behind", u.returncode != 0 and not any(dest.iterdir()), (u.returncode, (u.stdout + u.stderr)[-200:]))
            p.unlink()
        trunc = inbox / "trunc.tar.gz"
        trunc.write_bytes(data[: int(len(data) * 0.8)])
        dest = F / "aws" / "bad-trunc"
        dest.mkdir()
        u = tool(REPO / "scripts/release/backup_tool.py", "unpack", trunc, "--sha256", sha(trunc), dest)
        check(fx, "R3-027 a truncated archive whose digest matches its own bytes is still refused (incomplete member), nothing left behind",
              u.returncode != 0 and not any(dest.iterdir()), (u.returncode, (u.stdout + u.stderr)[-300:]))
        trunc.unlink()
        shutil.copy2(archive, inbox / archive.name)
        # restore onto a fresh private volume (stand-in), then into an empty data directory
        volume = F / "aws" / "volume"
        volume.mkdir(mode=0o700)
        t = time.time()
        u = tool(REPO / "scripts/release/backup_tool.py", "unpack", inbox / archive.name, "--sha256", digest, volume)
        restored_bk = next(iter(sorted(volume.iterdir())), None)
        check(fx, "R3-024 unpack onto a fresh private volume (stand-in for the staging volume): the backup's checksums verify",
              u.returncode == 0 and restored_bk is not None and subprocess.run(["sha256sum", "--quiet", "-c", "SHA256SUMS"], cwd=restored_bk).returncode == 0, (u.stdout + u.stderr)[-300:])
        if restored_bk is None:
            continue

        def restore_into(target: Path):
            target.mkdir(mode=0o700)
            for p in sorted(restored_bk.glob("app.db*")):  # RELEASE.md: cp -a app.db and its sidecars
                shutil.copy2(p, target / p.name)
            return subprocess.run(["sqlite3", "-readonly", str(target / "app.db"), "PRAGMA integrity_check;"], capture_output=True, text=True).stdout.strip()

        active = F / "aws" / "data"
        integ = restore_into(active)
        T["restore_s"] = round(time.time() - t, 2)
        check(fx, f"R3-024 the RELEASE.md restore copy into an empty data directory: integrity {integ}", integ == "ok")
        # write readiness and permissions
        wc = tool(REPO / "scripts/release/restore_write_check.py", active)
        (F / "write-check.out").write_text(wc.stdout + wc.stderr)
        check(fx, "R3-028 restore_write_check.py: the restored data takes a first write", wc.returncode == 0, wc.stdout[-300:])
        os.chmod(active / "app.db", 0o400)
        bad1 = tool(REPO / "scripts/release/restore_write_check.py", active)
        os.chmod(active / "app.db", 0o600)
        os.chmod(active, 0o500)
        bad2 = tool(REPO / "scripts/release/restore_write_check.py", active)
        os.chmod(active, 0o700)
        again = tool(REPO / "scripts/release/restore_write_check.py", active)
        check(fx, "R3-028 a read-only app.db and a read-only directory each fail the write check with the reason; fixed, it passes",
              bad1.returncode == 1 and bad2.returncode == 1 and again.returncode == 0 and "app.db" in (bad1.stdout + bad1.stderr),
              {"ro_file": (bad1.stdout + bad1.stderr)[-200:], "ro_dir": (bad2.stdout + bad2.stderr)[-200:]})
        # serve: the source (a copy) and the restored data, side by side
        src_copy = F / "nas-served"
        src_copy.mkdir(mode=0o700)
        for p in sorted(nas.glob("app.db*")):
            shutil.copy2(p, src_copy / p.name)
        t = time.time()
        s_src = Server(binary, src_copy / "app.db", F / "run-source")
        s_dst = Server(binary, active / "app.db", F / "run-restored")
        T["serve_s"] = round(time.time() - t, 2)
        check(fx, "the server of this tree starts on a served copy of the source and on the restored data (a 020 copy is upgraded by its own migrations)", s_src.ok and s_dst.ok)
        try:
            ids_src, ids_dst = stable_ids(s_src.url), stable_ids(s_dst.url)
            (F / "stable-ids.json").write_text(json.dumps({"source": ids_src, "restored": ids_dst}, indent=1, default=str))
            diff = [k for k in ids_src if ids_src[k] != ids_dst[k]]
            check(fx, f"R3-025 stable IDs equal through the API (notebook {len(ids_src['notebook'])}, listening {len(ids_src['listening'])}, script revisions {sum(len(v) for v in ids_src['script_revisions'].values())}, Review Today {len(ids_src['review_today_keys'] or [])})", not diff, diff)
            check(fx, f"R3-026 Speaking takes keep their transcripts and versions (exercises {len(ids_src['speaking_takes'])}, takes {sum(len(v["takes"]) for v in ids_src['speaking_takes'].values())}, transcripts {sum(len(v["transcripts"]) for v in ids_src['speaking_takes'].values())})",
                  ids_src["speaking_takes"] == ids_dst["speaking_takes"] and (fx != "v021-daily" or sum(len(v["transcripts"]) for v in ids_src["speaking_takes"].values()) > 0), "")
            s1, e_src = call(s_src.url, "GET", "/learning-history/export?transcripts=true&notes=true", raw=True)
            s2, e_dst = call(s_dst.url, "GET", "/learning-history/export?transcripts=true&notes=true", raw=True)
            s3, pv = call(s_dst.url, "POST", "/learning-history/import-preview", body=e_src)
            (F / "export-source.ndjson").write_bytes(e_src if isinstance(e_src, bytes) else b"")
            check(fx, f"R3-029 the history export of the restored data equals the source's ({len(ndjson(e_src)) if s1 == 200 else '?'} lines), and the source export previews complete with 0 new and 0 conflicts",
                  s1 == s2 == s3 == 200 and ndjson(e_src) == ndjson(e_dst) and pv.get("integrity") == "complete" and pv.get("new") == 0 and pv.get("conflicts") == 0,
                  {"status": (s1, s2, s3), "preview": pv if s3 == 200 else None})
        finally:
            s_src.stop()
            s_dst.stop()
        # parity by inventory (after the server ran its migrations on the restored copy)
        r2 = tool(HERE / "inventory.py", active, "--out", F / "inventory-restored", "--zone", "Europe/Paris")
        inv_dst = json.loads((F / "inventory-restored" / "inventory.json").read_text())
        upgraded = {"listening_materials"} if inv_src["ledger"]["last"] != inv_dst["ledger"]["last"] else set()
        learner = [t for t, sp in entities.TABLES.items() if sp["role"] in LEARNER_ROLES and t in inv_src["rows_by_table"]]
        rows_diff = {t: (inv_src["rows_by_table"][t], inv_dst["rows_by_table"].get(t)) for t in learner if inv_src["rows_by_table"][t] != inv_dst["rows_by_table"].get(t)}
        dig_diff = sorted(t for t in learner if inv_src["table_digests"].get(t) != inv_dst["table_digests"].get(t) and t not in upgraded)
        check(fx, f"R3-029 counts reconcile: every learner table has the same rows ({sum(inv_src['rows_by_table'][t] for t in learner)}) and the same row digest"
                  + (f" (except {', '.join(sorted(upgraded))}, rebuilt by 021: compared through the API above)" if upgraded else ""),
              not rows_diff and not dig_diff, {"rows": rows_diff, "digests": dig_diff})
        check(fx, f"ledger: source {inv_src['ledger']['last']} -> restored {inv_dst['ledger']['last']} ({inv_dst['ledger']['parity']} with this checkout)",
              inv_dst["ledger"]["parity"] == "EQUAL")
        # receipt
        (F / "timings.json").write_text(json.dumps(T))
        rc = tool(REPO / "scripts/release/backup_tool.py", "receipt", "--backup", restored_bk, "--active", active, "--write-check", F / "write-check.out",
                  "--timings", F / "timings.json", "--out", F / "recovery-receipt.json")
        check(fx, "backup_tool.py receipt (flh-recovery-receipt/v1) written", rc.returncode in (0, 1) and (F / "recovery-receipt.json").exists(), (rc.stdout + rc.stderr)[-300:])
        # repeat, and the source never touched
        again_dir = F / "aws" / "data-again"
        restore_into(again_dir)
        r3 = tool(HERE / "inventory.py", again_dir, "--out", F / "inventory-again")
        inv_again = json.loads((F / "inventory-again" / "inventory.json").read_text())
        source_after = {p.name: (sha(p), p.stat().st_mtime_ns) for p in nas.iterdir()}
        check(fx, "R3-030 a second restore from the same backup gives the source's logical digest; the source files are byte-identical and untouched",
              inv_again["logical_digest"] == inv_src["logical_digest"] and source_after == source_before, {"again": inv_again["logical_digest"][:12], "source": inv_src["logical_digest"][:12]})
        timings[fx] = T
    (work / "results.json").write_text(json.dumps({"results": results, "timings": timings}, indent=1))
    failed = [r for r in results if not r["pass"]]
    print(f"{len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
