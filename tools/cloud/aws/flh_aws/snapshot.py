"""Synthetic-source gate, consistent SQLite snapshot, manifest and verification.

The snapshot uses SQLite's online backup API from a read-only connection, so it
is consistent even while the demo server holds the database open in WAL mode;
the raw file (and its -wal) is never copied. Verification never trusts the
manifest alone: it recomputes everything from the snapshot bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import datetime as _dt
from pathlib import Path

from . import TOOL_VERSION

REPO = Path(__file__).resolve().parents[4]
MANIFEST_SCHEMA = "flh063_backup_manifest_v1"
SNAPSHOT_NAME = "snapshot.sqlite3"
MANIFEST_NAME = "manifest.json"

# Reused synthetic sources (not copied): every learner text and Concept target
# in an uploaded database must occur in one of these files.
SYNTHETIC_SOURCES = (
    REPO / "scripts" / "demo" / "flh034" / "seed.py",
    REPO / "scripts" / "demo" / "flh060" / "catalog.py",
)
DEMO_MARKERS = {
    ".flh034-demo": ("flh034-demo", Path("demo.db")),
    ".flh060-demo": ("flh060-demo", Path("flh034") / "demo.db"),
}
# Domain tables whose full contents form the fingerprint.
DOMAIN_TABLES = ("learning_entries", "entry_analyses", "knowledge_units", "knowledge_concepts",
                 "unit_concept_links", "unit_concept_memberships")
REQUIRED_TABLES = ("schema_migrations", "learning_entries", "knowledge_concepts")


class Refused(Exception):
    """A precondition failed; nothing was written or sent."""


class VerificationError(Exception):
    """A package or restore failed verification."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_within(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def check_outside_repo(path: Path, what: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        raise Refused(f"{what} must be an absolute path")
    if is_within(p, REPO):
        raise Refused(f"{what} must be outside the repository")
    return p


def new_run_id() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)


# --- synthetic gate -------------------------------------------------------------

def locate_demo_db(demo_dir: Path) -> tuple[str, Path]:
    demo_dir = check_outside_repo(Path(demo_dir), "--source-demo")
    for marker, (kind, rel) in DEMO_MARKERS.items():
        if (demo_dir / marker).is_file():
            db = demo_dir / rel
            if not db.is_file():
                raise Refused(f"{kind} directory has no database at {rel}")
            return kind, db
    raise Refused("--source-demo is not an FLH-034 or FLH-060 demo directory (no demo marker); "
                  "only synthetic demo databases may be uploaded")


def _synthetic_corpus() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in SYNTHETIC_SOURCES).casefold()


def synthetic_gate(conn: sqlite3.Connection) -> dict:
    """Refuse unless every learner text and Concept target is a known synthetic string."""
    corpus = _synthetic_corpus()
    unknown = []
    for table, col in (("learning_entries", "original_input"), ("knowledge_concepts", "target")):
        for (value,) in conn.execute(f"SELECT {col} FROM {table}"):
            if not value or value.casefold() not in corpus:
                unknown.append(f"{table}.{col}")
    if unknown:
        raise Refused(f"synthetic gate: {len(unknown)} value(s) not found in the synthetic demo sources "
                      f"({sorted(set(unknown))}); refusing")
    return {"method": "verbatim_casefold_in_flh034_seed_or_flh060_catalog",
            "sources": [str(p.relative_to(REPO)) for p in SYNTHETIC_SOURCES]}


# --- facts computed from a database ---------------------------------------------

def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def domain_facts(conn: sqlite3.Connection) -> dict:
    tables = _tables(conn)
    missing = [t for t in REQUIRED_TABLES if t not in tables]
    if missing:
        raise VerificationError(f"missing required tables: {missing}")
    h = hashlib.sha256()
    counts = {}
    for t in DOMAIN_TABLES:
        if t not in tables:
            counts[t] = None
            continue
        rows = [json.dumps(list(r), ensure_ascii=False, default=lambda b: b.hex() if isinstance(b, bytes) else repr(b))
                for r in conn.execute(f"SELECT * FROM {t}")]
        rows.sort()
        counts[t] = len(rows)
        h.update(f"{t}\n{len(rows)}\n".encode())
        for line in rows:
            h.update(line.encode("utf-8") + b"\n")
    migrations = [r[0] for r in conn.execute("SELECT name FROM schema_migrations ORDER BY name")]
    return {"counts": counts, "fingerprint_sha256": h.hexdigest(),
            "fingerprint_method": "sha256 over each domain table's rows as sorted JSON arrays",
            "migrations_applied": migrations}


def integrity(conn: sqlite3.Connection) -> dict:
    ic = [r[0] for r in conn.execute("PRAGMA integrity_check")]
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    return {"integrity_check": ic, "foreign_key_violations": len(fk)}


def source_metadata(source_revision: str | None) -> dict:
    files = sorted((REPO / "migrations").glob("*.sql")) + [REPO / "go.mod", REPO / "go.sum"]
    return {"go_module_file": "go.mod",
            "source_revision": source_revision,
            "source_revision_note": "supplied by the operator; this tool runs no Git command",
            "files_sha256": {str(p.relative_to(REPO)): sha256_file(p) for p in files if p.is_file()}}


# --- snapshot and package -------------------------------------------------------

def make_package(demo_dir: Path, package_dir: Path, run_id: str, source_revision: str | None = None) -> dict:
    """Create package_dir (new) with snapshot.sqlite3 and manifest.json."""
    kind, db = locate_demo_db(demo_dir)
    package_dir = check_outside_repo(Path(package_dir), "package directory")
    if is_within(package_dir, demo_dir):
        raise Refused("the package directory must be outside the demo directory")
    if package_dir.exists():
        raise Refused(f"package directory already exists: {package_dir}")

    # Gate on the live source before writing anything.
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        gate = synthetic_gate(src)
        package_dir.mkdir(parents=True)
        snap = package_dir / SNAPSHOT_NAME
        dst = sqlite3.connect(snap)
        try:
            src.backup(dst)  # online backup API: consistent point-in-time copy
            dst.execute("PRAGMA journal_mode=DELETE")
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()

    conn = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
    try:
        integ = integrity(conn)
        if integ["integrity_check"] != ["ok"] or integ["foreign_key_violations"]:
            raise VerificationError(f"snapshot failed integrity checks: {integ}")
        synthetic_gate(conn)  # the snapshot itself must pass too
        facts = domain_facts(conn)
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "run_id": run_id,
        "created_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": TOOL_VERSION,
        "data_classification": "synthetic",
        "source": {"kind": kind, "synthetic_gate": gate},
        "snapshot": {"file": SNAPSHOT_NAME, "bytes": snap.stat().st_size, "sha256": sha256_file(snap),
                     "method": "sqlite3_online_backup_api", "sqlite_version": sqlite3.sqlite_version,
                     "page_size": page_size, "page_count": page_count, "journal_mode": journal,
                     "integrity": integ},
        "schema_info": {"migrations_applied": facts.pop("migrations_applied")},
        "application": source_metadata(source_revision),
        "domain": facts,
    }
    mpath = package_dir / MANIFEST_NAME
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    return {"package_dir": str(package_dir), "manifest_sha256": sha256_file(mpath), "manifest": manifest}


def verify_package(package_dir: Path, expected_manifest_sha256: str | None) -> dict:
    """Verify a downloaded or local package. Raises VerificationError."""
    package_dir = Path(package_dir)
    mpath, snap = package_dir / MANIFEST_NAME, package_dir / SNAPSHOT_NAME
    checks = {}
    if not mpath.is_file() or not snap.is_file():
        raise VerificationError("package is incomplete (manifest or snapshot missing)")
    msha = sha256_file(mpath)
    if expected_manifest_sha256 is None:
        raise VerificationError("no expected manifest SHA-256 (record from upload or --expect-manifest-sha256)")
    if msha != expected_manifest_sha256:
        raise VerificationError(f"manifest SHA-256 mismatch: got {msha}, expected {expected_manifest_sha256}")
    checks["manifest_sha256"] = msha
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except ValueError as e:
        raise VerificationError(f"manifest is not JSON: {e}") from None
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("data_classification") != "synthetic":
        raise VerificationError("unexpected manifest schema or classification")
    size = snap.stat().st_size
    if size != manifest["snapshot"]["bytes"]:
        raise VerificationError(f"snapshot size {size} != manifest {manifest['snapshot']['bytes']}")
    ssha = sha256_file(snap)
    if ssha != manifest["snapshot"]["sha256"]:
        raise VerificationError("snapshot SHA-256 mismatch")
    checks["snapshot_sha256"] = ssha
    try:
        conn = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise VerificationError(f"snapshot does not open: {e}") from None
    try:
        try:
            integ = integrity(conn)
        except sqlite3.DatabaseError as e:
            raise VerificationError(f"snapshot is not a valid SQLite database: {e}") from None
        if integ["integrity_check"] != ["ok"] or integ["foreign_key_violations"]:
            raise VerificationError(f"SQLite integrity failed: {integ}")
        checks["integrity"] = integ
        facts = domain_facts(conn)
        if facts["migrations_applied"] != manifest["schema_info"]["migrations_applied"]:
            raise VerificationError("applied migrations differ from the manifest")
        if facts["counts"] != manifest["domain"]["counts"]:
            raise VerificationError(f"domain counts differ: {facts['counts']} vs {manifest['domain']['counts']}")
        if facts["fingerprint_sha256"] != manifest["domain"]["fingerprint_sha256"]:
            raise VerificationError("domain fingerprint differs from the manifest")
        checks["domain"] = {"counts": facts["counts"], "fingerprint_sha256": facts["fingerprint_sha256"]}
        try:
            synthetic_gate(conn)
        except Refused as e:
            raise VerificationError(str(e)) from None
        checks["synthetic_gate"] = "passed"
    finally:
        conn.close()
    return {"manifest": manifest, "checks": checks}


def write_json(path: Path, data: dict) -> None:
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
