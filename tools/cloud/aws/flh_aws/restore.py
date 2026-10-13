"""Isolated restore: download into a new directory, verify, and only then accept.

The original demo database is never opened for writing. A restore that fails
any check keeps its downloaded files as evidence, writes RESTORE-REJECTED.json
and produces no restored database.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .ledger import utc_now
from .s3store import download, load_resources
from .snapshot import (SNAPSHOT_NAME, Refused, VerificationError, check_outside_repo, is_within,
                       verify_package, write_json)


def _check_target(state: Path, into: Path) -> Path:
    into = check_outside_repo(Path(into), "--into")
    if into.exists():
        raise Refused(f"--into must not exist yet (never restore over existing data): {into}")
    if not into.parent.is_dir():
        raise Refused(f"parent of --into does not exist: {into.parent}")
    guarded = [("the state directory", str(state))]
    pk = Path(state) / "packages.json"
    if pk.exists():
        guarded += [("a source demo directory", v["source_demo"]) for v in json.loads(pk.read_text()).values()]
    for label, p in guarded:
        if is_within(into, Path(p)):
            raise Refused(f"--into must be outside {label}")
    return into


def accept(into: Path, package_dir: Path, expected_manifest_sha256: str | None, origin: dict) -> dict:
    """Verify package_dir, then copy the snapshot to into/restored/demo.db."""
    try:
        result = verify_package(package_dir, expected_manifest_sha256)
    except VerificationError as e:
        write_json(into / "RESTORE-REJECTED.json", {"rejected_utc": utc_now(), "reason": str(e), **origin})
        raise
    restored = into / "restored"
    restored.mkdir()
    shutil.copyfile(package_dir / SNAPSHOT_NAME, restored / "demo.db")
    record = {"accepted_utc": utc_now(), "restored_db": "restored/demo.db", "run_id": result["manifest"]["run_id"],
              "checks": result["checks"], **origin}
    write_json(into / "RESTORE-ACCEPTED.json", record)
    return record


def restore_from_s3(state: Path, clients, run_id: str, into: Path, expected_manifest_sha256: str | None,
                    backend: str) -> dict:
    into = _check_target(state, into)
    res = load_resources(state)
    run = res.get("runs", {}).get(run_id)
    if not run or run.get("state") != "uploaded":
        raise Refused(f"run {run_id} is not a completed upload recorded in this state directory")
    recorded = run.get("manifest_sha256")
    if expected_manifest_sha256 and recorded and expected_manifest_sha256 != recorded:
        raise Refused("--expect-manifest-sha256 differs from the value recorded at upload")
    into.mkdir()
    dl = into / "download"
    try:
        download(state, clients, run_id, dl, backend)
    except Exception as e:  # noqa: BLE001 - recorded, then re-raised
        write_json(into / "RESTORE-REJECTED.json", {"rejected_utc": utc_now(), "reason": f"download failed: {e}",
                                                     "origin": "s3", "run_id": run_id})
        raise
    return accept(into, dl, expected_manifest_sha256 or recorded,
                  {"origin": "s3", "bucket": res["bucket"], "run_id_requested": run_id})


def restore_local(package_dir: Path, into: Path, expected_manifest_sha256: str) -> dict:
    into = check_outside_repo(Path(into), "--into")
    if into.exists():
        raise Refused(f"--into must not exist yet: {into}")
    if is_within(into, package_dir):
        raise Refused("--into must be outside the package directory")
    into.mkdir()
    return accept(into, Path(package_dir), expected_manifest_sha256, {"origin": "local package"})
