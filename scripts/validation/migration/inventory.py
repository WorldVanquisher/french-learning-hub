#!/usr/bin/env python3
"""Migration inventory of a private learner database: read-only, without printing any record.

    python3 -I -B scripts/validation/migration/inventory.py SOURCE --out DIR [--zone ZONE] [--dest-repo REPO]

SOURCE is an app.db, a data directory holding one, or a `flh-daily.sh backup` directory. It is
never opened: its files (app.db and any -wal/-shm sidecar) are copied byte for byte into a private
scratch directory and only the copy is read (SQLite would otherwise create -shm files beside a
WAL database even for a read). Before and after, the source files' size, mtime, inode and SHA-256
are recorded; the receipt proves they did not change (R3-020).

Reports (R3-011..R3-019), never a row value:
  counts       rows per table, grouped by role (entities.py); learner records by source and by
               source type; versions per source (transcripts, passages, drafts, script revisions)
  references   PRAGMA foreign_key_check; every Mistake Notebook record's (type, record, item)
               resolves to a stored item; retry marks name a notebook record; transcripts and
               feedback belong to the take or draft they name
  attachments  speaking takes keep audio metadata only (no audio column, by design): counted;
               external links (YouTube, reading sources) counted, never fetched
  encoding     every TEXT value is valid UTF-8 without NUL or other C0 control characters
               (tab, newline, return allowed); identifiers (capture IDs, operation IDs, pack IDs)
               are NFC and match their formats
  time         every timestamp parses as RFC 3339; per table the first and last ISO week only
               (no day, no time); active local days counted in ZONE (default UTC); future times
  sizes        bytes of private free text per category (entities.py `private`), rounded to KiB
  duplicates   repeated capture fingerprints, notebook item references, speaking audio digests
               per exercise, identical consecutive retry marks, identical entries
  invariants   version chains 1..N without gaps (listening transcripts, reading passages, writing
               drafts, speaking transcripts); exactly one authored exercise per listening script
               revision; no exam answer saved after its session's deadline or submission
  parity       the ledger against the destination checkout's migrations/ (default: this
               tree): EQUAL, BEHIND (the server will upgrade it), AHEAD or FOREIGN (refuse)
Writes DIR/inventory.json (flh_migration_inventory_v1, the machine receipt) and DIR/summary.txt.

Exit codes, each with its next action in the summary:
  0  ready to copy
  1  data problems found (dangling references, bad encoding, unparseable times)
  3  partial input (no app.db, a WAL without its database, a backup without SHA256SUMS or with a
     mismatch, an unreadable or not-ok integrity check, unknown tables)
  4  the database is newer than (or foreign to) the destination: do not copy
  2  usage or unreadable source
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import entities  # noqa: E402

REPO = HERE.parents[2]
SCHEMA = "flh_migration_inventory_v1"
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
FORMATS = {
    ("learning_captures", "capture_id"): re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
    ("listening_materials", "pack_script_id"): re.compile(r"^flh_listening_script_pack_v1/[a-z0-9-]+$"),
    ("speaking_exercises", "prompt_id"): re.compile(r"^[a-z0-9][a-z0-9._-]*$"),
}
UUIDISH = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def stat_of(p: Path) -> dict:
    st = p.stat()
    return {"name": p.name, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "inode": st.st_ino, "sha256": sha256(p)}


def locate(src: Path):
    """(directory, kind, problems): kind is file, data or backup."""
    if src.is_file():
        return src.parent, "file", []
    if (src / "app.db").is_file():
        kind = "backup" if (src / "SHA256SUMS").exists() or src.name.startswith("flh-") else "data"
        return src, kind, []
    if src.is_dir() and any(src.glob("app.db-*")):
        return None, None, ["a WAL or SHM sidecar without its app.db (never open it alone: copy the whole directory back from where it came)"]
    return None, None, ["no app.db at the source"]


def parse_time(v):
    if not isinstance(v, str) or not v:
        return None
    s = v.strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(.*)$", s)
    if not m:
        return None
    frac = (m.group(2) or "")[:7]
    try:
        t = dt.datetime.fromisoformat(m.group(1) + frac + (m.group(3) or ""))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def week(t: dt.datetime) -> str:
    y, w, _ = t.isocalendar()
    return f"{y}-W{w:02d}"


def main():
    args = sys.argv[1:]
    opts = {"--out": None, "--zone": "UTC", "--dest-repo": str(REPO)}
    for k in list(opts):
        if k in args:
            i = args.index(k)
            opts[k] = args[i + 1]
            args = args[:i] + args[i + 2:]
    if len(args) != 1 or not opts["--out"]:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    src = Path(os.path.realpath(args[0]))
    out = Path(os.path.realpath(opts["--out"]))
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(opts["--zone"])
    except Exception:
        print(f"unknown time zone {opts['--zone']!r}", file=sys.stderr)
        return 2
    d, kind, partial = locate(src)
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"schema": SCHEMA, "source_kind": kind, "zone": opts["--zone"], "partial": partial, "problems": [], "warnings": []}
    if d is None:
        receipt["verdict"] = "PARTIAL"
        (out / "inventory.json").write_text(json.dumps(receipt, indent=1))
        (out / "summary.txt").write_text("PARTIAL: " + "; ".join(partial) + ". Next: point at the data directory, the app.db or a backup directory.\n")
        print((out / "summary.txt").read_text(), end="")
        return 3
    names = ["app.db", "app.db-wal", "app.db-shm"] if kind != "file" else [src.name, src.name + "-wal", src.name + "-shm"]
    files = [d / n for n in names if (d / n).exists()]
    before = [stat_of(p) for p in files]
    if kind == "backup":
        sums = d / "SHA256SUMS"
        if not sums.exists():
            partial.append("a backup directory without SHA256SUMS (incomplete: flh-daily.sh writes it last)")
        else:
            want = {ln[66:].strip(): ln[:64] for ln in sums.read_text().splitlines() if ln.strip()}
            got = {s["name"]: s["sha256"] for s in before}
            bad = sorted(n for n in want if got.get(n) != want[n])
            if bad:
                partial.append(f"backup checksums do not match for {', '.join(bad)}")
    scratch = Path(tempfile.mkdtemp(prefix="flh-inventory-", dir=os.environ.get("TMPDIR")))
    os.chmod(scratch, 0o700)
    try:
        for p in files:
            shutil.copyfile(p, scratch / p.name.replace(src.name if kind == "file" else "app.db", "app.db", 1))
        con = sqlite3.connect(f"file:{scratch / 'app.db'}?mode=ro", uri=True)
        con.text_factory = bytes
        con.execute("PRAGMA query_only = ON")
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0].decode()
        if integrity != "ok":
            partial.append(f"integrity_check: {integrity[:80]}")
        tables = [r[0].decode() for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        unknown = [t for t in tables if t not in entities.TABLES]
        if unknown:
            partial.append(f"tables this inventory does not map: {', '.join(unknown)}")
        missing = [t for t in entities.TABLES if t not in tables and t != "schema_migrations"]
        counts = {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
        by_role = Counter()
        for t, n in counts.items():
            by_role[entities.TABLES.get(t, {}).get("role", "unmapped")] += n
        q = lambda sql, *a: con.execute(sql, a).fetchall()
        has = lambda t: t in tables
        dec = lambda b: b.decode("utf-8", "replace") if isinstance(b, bytes) else b
        rec = {
            "captures_by_source": {dec(k): v for k, v in q("SELECT source, count(*) FROM learning_captures GROUP BY source")} if has("learning_captures") else {},
            "notebook_by_source_type": {dec(k): v for k, v in q("SELECT source_type, count(*) FROM learning_capture_sources GROUP BY source_type")} if has("learning_capture_sources") else {},
            "notebook_marked_for_retry": q("""SELECT count(*) FROM (SELECT entry_id, marked FROM mistake_retry_marks m WHERE id = (SELECT max(id) FROM mistake_retry_marks x WHERE x.entry_id = m.entry_id)) WHERE marked = 1""")[0][0] if has("mistake_retry_marks") else 0,
            "listening_materials_by_kind": {dec(k): v for k, v in q("SELECT source_kind, count(*) FROM listening_materials GROUP BY source_kind")} if has("listening_materials") and "source_kind" in [r[1].decode() for r in con.execute("PRAGMA table_info(listening_materials)")] else ({"youtube": counts.get("listening_materials", 0)} if has("listening_materials") else {}),
        }
        revisions = {}
        for t, spec in entities.TABLES.items():
            col = spec.get("revision")
            if col and has(t):
                revisions[t] = {f"v{dec(k)}": v for k, v in q(f'SELECT "{col}", count(*) FROM "{t}" GROUP BY 1 ORDER BY 1')}
        # references
        fk = q("PRAGMA foreign_key_check")
        dangling = Counter(dec(r[0]) for r in fk)
        bad_refs = Counter()
        if has("learning_capture_sources"):
            for st, rid, item in q("SELECT source_type, record_id, item FROM learning_capture_sources"):
                target = entities.SOURCE_REFS.get(dec(st))
                if not target or not has(target[0]):
                    bad_refs["unknown source type"] += 1
                    continue
                row = q(f'SELECT content FROM "{target[0]}" WHERE id = ?', rid)
                if not row or row[0][0] is None:
                    bad_refs[f"{dec(st)}: record missing"] += 1
                    continue
                try:
                    n = len(json.loads(row[0][0]).get(target[1]) or [])
                except (ValueError, AttributeError):
                    bad_refs[f"{dec(st)}: unreadable content"] += 1
                    continue
                if not 1 <= item <= n:
                    bad_refs[f"{dec(st)}: item out of range"] += 1
        if has("speaking_feedback") and has("speaking_transcripts"):
            n = q("""SELECT count(*) FROM speaking_feedback f JOIN speaking_transcripts t ON t.id = f.transcript_id JOIN speaking_takes k ON k.id = t.take_id
                     WHERE k.exercise_id != f.exercise_id""")[0][0]
            if n:
                bad_refs["speaking feedback names a transcript of another exercise"] += n
        if has("writing_feedback"):
            n = q("SELECT count(*) FROM writing_feedback f JOIN writing_drafts d ON d.id = f.draft_id WHERE d.task_id != f.task_id")[0][0]
            if n:
                bad_refs["writing feedback names a draft of another task"] += n
        if has("listening_exercises"):
            n = q("SELECT count(*) FROM listening_exercises e JOIN listening_transcripts t ON t.id = e.transcript_id WHERE t.material_id != e.material_id")[0][0]
            if n:
                bad_refs["listening exercise names a transcript of another material"] += n
        attachments = {
            "speaking_takes_with_audio_metadata": q("SELECT count(*) FROM speaking_takes WHERE audio_sha256 IS NOT NULL AND audio_sha256 != ''")[0][0] if has("speaking_takes") else 0,
            "audio_stored": "never (no audio column; takes keep type, size, SHA-256 and duration only)",
            "external_links_not_fetched": (q("SELECT count(*) FROM listening_materials WHERE source_url IS NOT NULL")[0][0] if has("listening_materials") and "source_url" in [r[1].decode() for r in con.execute("PRAGMA table_info(listening_materials)")] else 0)
            + (q("SELECT count(*) FROM reading_lessons WHERE source_url IS NOT NULL")[0][0] if has("reading_lessons") else 0),
            "blob_columns": sorted(f"{t}.{r[1].decode()}" for t in tables for r in con.execute(f'PRAGMA table_info("{t}")') if r[2].decode().upper() == "BLOB"),
        }
        # encoding, identifiers, time, sizes
        enc = Counter()
        ids = Counter()
        times = {"unparseable": Counter(), "future": Counter(), "weeks": {}, "active_local_days": set()}
        sizes = Counter()
        now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
        for t in tables:
            cols = [(r[1].decode(), r[2].decode().upper()) for r in con.execute(f'PRAGMA table_info("{t}")')]
            spec = entities.TABLES.get(t, {})
            for c, typ in cols:
                if typ not in ("TEXT", ""):
                    continue
                for (v,) in con.execute(f'SELECT "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL'):
                    if isinstance(v, int) or isinstance(v, float):
                        continue
                    try:
                        s = v.decode("utf-8") if isinstance(v, bytes) else v
                    except UnicodeDecodeError:
                        enc[f"{t}.{c}: invalid UTF-8"] += 1
                        continue
                    if CTRL.search(s):
                        enc[f"{t}.{c}: control character"] += 1
                    if c in spec.get("private", []):
                        sizes[t + "." + c] += len(v)
                    fmt = FORMATS.get((t, c))
                    if fmt is not None:
                        if unicodedata.normalize("NFC", s) != s:
                            ids[f"{t}.{c}: not NFC"] += 1
                        if not fmt.match(s):
                            ids[f"{t}.{c}: unexpected format"] += 1
                    if c == "operation_id" and not UUIDISH.match(s):
                        ids[f"{t}.{c}: not a lowercase UUID"] += 1
                    if c in spec.get("when", []):
                        tv = parse_time(s)
                        if tv is None:
                            times["unparseable"][f"{t}.{c}"] += 1
                            continue
                        if tv > now:
                            times["future"][f"{t}.{c}"] += 1
                        w = times["weeks"].setdefault(t, [week(tv), week(tv)])
                        w[0], w[1] = min(w[0], week(tv)), max(w[1], week(tv))
                        if spec.get("role") in ("learner", "learner-derived"):
                            times["active_local_days"].add(tv.astimezone(zone).date())
        duplicates = {
            "capture_fingerprints": q("SELECT count(*) FROM (SELECT content_fingerprint FROM learning_captures GROUP BY 1 HAVING count(*) > 1)")[0][0] if has("learning_captures") else 0,
            "notebook_item_references": q("SELECT count(*) FROM (SELECT 1 FROM learning_capture_sources GROUP BY source_type, record_id, item HAVING count(*) > 1)")[0][0] if has("learning_capture_sources") else 0,
            "speaking_audio_per_exercise": q("SELECT count(*) FROM (SELECT 1 FROM speaking_takes WHERE audio_sha256 IS NOT NULL GROUP BY exercise_id, audio_sha256 HAVING count(*) > 1)")[0][0] if has("speaking_takes") else 0,
            "identical_consecutive_retry_marks": q("""SELECT count(*) FROM mistake_retry_marks a JOIN mistake_retry_marks b ON b.entry_id = a.entry_id AND b.id = (SELECT min(id) FROM mistake_retry_marks c WHERE c.entry_id = a.entry_id AND c.id > a.id) WHERE a.marked = b.marked""")[0][0] if has("mistake_retry_marks") else 0,
            "identical_entries": q("SELECT count(*) FROM (SELECT 1 FROM learning_entries GROUP BY original_input, original_context HAVING count(*) > 1)")[0][0] if has("learning_entries") else 0,
        }
        # Workbook invariants (R3; the restore and cutover runbooks call this command): version chains
        # without gaps, one authored exercise per script revision, exam answers inside their window.
        inv = Counter()
        for table, key in (("listening_transcripts", "material_id"), ("reading_passages", "lesson_id"), ("writing_drafts", "task_id"), ("speaking_transcripts", "take_id")):
            if has(table):
                inv[f"{table}: versions not 1..N per {key}"] = q(f"SELECT count(*) FROM (SELECT 1 FROM {table} GROUP BY {key} HAVING min(version) != 1 OR max(version) != count(*))")[0][0]
        if has("listening_materials") and "source_kind" in [r[1] for r in q("PRAGMA table_info(listening_materials)")]:
            inv["listening script revisions without exactly one authored exercise"] = q("""SELECT count(*) FROM listening_transcripts t JOIN listening_materials m ON m.id = t.material_id
                WHERE m.source_kind = 'authored_script' AND (SELECT count(*) FROM listening_exercises e WHERE e.transcript_id = t.id AND e.generator LIKE 'authored:%') != 1""")[0][0]
        if has("exam_answers") and has("exam_sessions"):
            rows = q("""SELECT a.saved_at, s.deadline_at, x.submitted_at FROM exam_answers a JOIN exam_sessions s ON s.id = a.session_id
                LEFT JOIN exam_submissions x ON x.session_id = a.session_id""")
            for saved, deadline, submitted in rows:
                a, b, c = parse_time(dec(saved)), parse_time(dec(deadline)), parse_time(dec(submitted)) if submitted else None
                if a and b and a > b:
                    inv["exam answers saved after their session's deadline"] += 1
                if a and c and a > c:
                    inv["exam answers saved after their session's submission"] += 1
        inv = Counter({k: v for k, v in inv.items() if v})
        ledger = [dec(r[0]) for r in q("SELECT name FROM schema_migrations ORDER BY name")] if has("schema_migrations") else []
        dest = sorted(p.name for p in Path(opts["--dest-repo"], "migrations").glob("*.sql"))
        foreign = [m for m in ledger if m not in dest]
        if ledger == dest:
            parity = "EQUAL"
        elif foreign:
            parity = "AHEAD" if all(m > (dest[-1] if dest else "") for m in foreign) else "FOREIGN"
        elif ledger == dest[: len(ledger)]:
            parity = "BEHIND"
        else:
            parity = "FOREIGN"
        digests = {}
        for t in tables:
            h = hashlib.sha256()
            for row in con.execute(f'SELECT * FROM "{t}" ORDER BY rowid'):
                h.update(repr(row).encode())
            digests[t] = h.hexdigest()
        con.close()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    after = [stat_of(p) for p in files]
    untouched = before == after and sorted(p.name for p in d.iterdir() if p.name.startswith(names[0])) == sorted(p.name for p in files)
    problems = []
    if dangling:
        problems.append("foreign keys: " + ", ".join(f"{k} {v}" for k, v in sorted(dangling.items())))
    if bad_refs:
        problems.append("notebook and record references: " + ", ".join(f"{k} {v}" for k, v in sorted(bad_refs.items())))
    if enc:
        problems.append("encoding: " + ", ".join(f"{k} {v}" for k, v in sorted(enc.items())))
    if ids:
        problems.append("identifiers: " + ", ".join(f"{k} {v}" for k, v in sorted(ids.items())))
    if inv:
        problems.append("invariants: " + ", ".join(f"{k} {v}" for k, v in sorted(inv.items())))
    if times["unparseable"]:
        problems.append("times: " + ", ".join(f"{k} {v} unparseable" for k, v in sorted(times["unparseable"].items())))
    warnings = []
    if missing:
        warnings.append(f"tables of this checkout not in the source (an older schema): {', '.join(missing)}")
    if times["future"]:
        warnings.append("future times: " + ", ".join(f"{k} {v}" for k, v in sorted(times["future"].items())))
    if any(duplicates.values()):
        warnings.append("duplicates (kept as they are; a copy never merges): " + ", ".join(f"{k} {v}" for k, v in duplicates.items() if v))
    receipt.update({
        "source_files": before,
        "source_unchanged": untouched,
        "integrity": integrity,
        "ledger": {"count": len(ledger), "last": ledger[-1] if ledger else None, "destination_last": dest[-1] if dest else None, "parity": parity, "foreign": foreign},
        "tables": len(tables),
        "rows_by_table": counts,
        "rows_by_role": dict(by_role),
        "learner_records": rec,
        "versions_by_source": revisions,
        "references": {"foreign_key_violations": dict(dangling), "logical": dict(bad_refs)},
        "attachments": attachments,
        "encoding": dict(enc),
        "identifiers": dict(ids),
        "time": {"weeks_first_last": times["weeks"], "active_local_days": len(times["active_local_days"]), "future": dict(times["future"]), "unparseable": dict(times["unparseable"])},
        "private_text_kib": {k: round(v / 1024, 1) for k, v in sorted(sizes.items())},
        "duplicates": duplicates,
        "invariants": dict(inv),
        "logical_digest": hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest(),
        "table_digests": digests,
        "excludable": {t: entities.EXCLUDABLE[s["role"]] for t, s in entities.TABLES.items() if s["role"] in entities.EXCLUDABLE and t in tables},
        "problems": problems,
        "warnings": warnings,
    })
    if not untouched:
        problems.append("the source changed while it was read (another writer?): the inventory does not describe a stable copy")
    if parity in ("AHEAD", "FOREIGN"):
        code, verdict, nxt = 4, "REFUSE", f"the ledger is {parity} of the destination ({', '.join(foreign)}): do not copy; update the destination first"
    elif partial:
        code, verdict, nxt = 3, "PARTIAL", "fix the input first: " + "; ".join(partial)
    elif problems:
        code, verdict, nxt = 1, "PROBLEMS", "resolve or accept each problem below before a copy; nothing was changed"
    else:
        code, verdict, nxt = 0, "READY", "ready to copy" + (" (the destination server will apply the newer migrations on start)" if parity == "BEHIND" else "")
    receipt.update({"verdict": verdict, "exit_code": code, "next_action": nxt, "partial": partial})
    (out / "inventory.json").write_text(json.dumps(receipt, indent=1, default=str))
    lines = [f"Migration inventory ({SCHEMA}): {verdict}, exit {code}", f"Next: {nxt}",
             f"Source: {kind}; {len(before)} file(s), {sum(s['bytes'] for s in before)} bytes; unchanged by this inventory: {untouched}",
             f"Integrity: {integrity}; ledger {len(ledger)} ({ledger[-1] if ledger else '-'}) vs destination {dest[-1] if dest else '-'}: {parity}",
             f"Tables {len(tables)}; rows by role: " + ", ".join(f"{k} {v}" for k, v in sorted(by_role.items())),
             "Learner records: " + json.dumps(rec, sort_keys=True), "Versions per source: " + json.dumps(revisions, sort_keys=True),
             "Attachments: " + json.dumps({k: v for k, v in attachments.items() if k != "audio_stored"}, sort_keys=True) + "; audio " + attachments["audio_stored"],
             f"Time ({opts['--zone']}): {len(times['active_local_days'])} active local days; first and last ISO weeks per table are in the receipt",
             "Private text (KiB): " + ", ".join(f"{k} {v}" for k, v in receipt["private_text_kib"].items()),
             "Duplicates: " + json.dumps(duplicates, sort_keys=True), f"Logical digest: {receipt['logical_digest']}"]
    lines += [f"PROBLEM: {p}" for p in problems] + [f"PARTIAL: {p}" for p in partial] + [f"WARNING: {w}" for w in warnings]
    (out / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return code


def guarded():
    try:
        return main()
    except sqlite3.DatabaseError as e:
        # A malformed or unreadable database: say so with the next action, never a traceback.
        out = Path(os.path.realpath(sys.argv[sys.argv.index("--out") + 1]))
        msg = f"the database cannot be read ({e}); next: do not copy it; restore the latest COMPLETE backup (backup_tool.py latest) and inventory that"
        (out / "inventory.json").write_text(json.dumps({"schema": SCHEMA, "verdict": "PARTIAL", "exit_code": 3, "partial": [msg], "next_action": msg}, indent=1))
        (out / "summary.txt").write_text(f"Migration inventory ({SCHEMA}): PARTIAL, exit 3\nNext: {msg}\n")
        print((out / "summary.txt").read_text(), end="")
        return 3


if __name__ == "__main__":
    sys.exit(guarded())
