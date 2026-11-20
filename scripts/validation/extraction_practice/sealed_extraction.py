"""Read the extraction lane's SEALED Extraction 2.1 handoff, never its live tree.

Shared by build_fixture.py and grade_parity.py (standard library only).

    verify_handoff(H)      every file of H/SHA256SUMS hashes as sealed; returns the digest of
                           SHA256SUMS itself (the handoff's identity)
    overlay(H, dest)       a scratch copy of that lane's code as sealed: this tree's shared
                           baseline tools/extraction with H/snapshot/extraction21.raw.tar
                           unpacked over it (the tar holds every path the lane changed)
    reproduce(tools, tmp)  proves the overlay IS the sealed code: `practice demo2 --check` and
                           `practice workbooks-bundle --check` must reproduce the sealed outputs
                           byte for byte, and the regenerated bundle must equal H/sample/workbooks

Nothing is written into H or into the extraction lane's worktree. Python runs with -B (no
bytecode) inside the scratch overlay only.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SNAPSHOT_TAR = "snapshot/extraction21.raw.tar"
BUNDLE_DIR = "sample/workbooks"


class SealError(Exception):
    pass


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_sums(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line[:64], line[66:]
        if len(digest) != 64 or line[64:66] != "  ":
            raise SealError(f"{path}: malformed line {line!r}")
        out[name[2:] if name.startswith("./") else name] = digest
    return out


def verify_sums(root: Path) -> str:
    sums = read_sums(root / "SHA256SUMS")
    if not sums:
        raise SealError(f"{root}/SHA256SUMS lists no file")
    for name, digest in sums.items():
        p = root / name
        if not p.is_file():
            raise SealError(f"{root}: sealed file missing: {name}")
        got = sha256_file(p)
        if got != digest:
            raise SealError(f"{root}: checksum mismatch for {name}: sealed {digest[:12]}…, found {got[:12]}…")
    return sha256_file(root / "SHA256SUMS")


def verify_handoff(h: Path) -> str:
    """Both seals: the handoff's SHA256SUMS and the bundle's own. Returns the handoff digest."""
    digest = verify_sums(h)
    verify_sums(h / BUNDLE_DIR)
    outer = read_sums(h / "SHA256SUMS")
    for name in read_sums(h / BUNDLE_DIR / "SHA256SUMS"):
        if f"{BUNDLE_DIR}/{name}" not in outer:
            raise SealError(f"the handoff seal does not cover {BUNDLE_DIR}/{name}")
    if SNAPSHOT_TAR not in outer:
        raise SealError(f"the handoff seal does not cover {SNAPSHOT_TAR}")
    return digest


def overlay(h: Path, dest: Path) -> Path:
    """Scratch copy: baseline tools/extraction of this tree, then the sealed tar over it."""
    if dest.exists() and any(dest.iterdir()):
        raise SealError(f"{dest} must be new or empty")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO / "tools/extraction", dest / "tools/extraction", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    with tarfile.open(h / SNAPSHOT_TAR) as tf:
        for m in tf.getmembers():
            n = os.path.normpath(m.name)
            if n.startswith("..") or os.path.isabs(n) or not (m.isfile() or m.isdir()):
                raise SealError(f"unsafe or unexpected tar member {m.name!r}")
        tf.extractall(dest, filter="data")
    return dest / "tools/extraction"


def run_extraction(tools: Path, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tools), "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C.UTF-8",
           "TMPDIR": os.environ.get("TMPDIR", "/tmp")}
    return subprocess.run([sys.executable, "-B", "-m", "flh_extraction", *args], cwd=tools, env=env, capture_output=True, text=True)


def reproduce(tools: Path, tmp: Path, h: Path) -> list[str]:
    """The overlay must reproduce the lane's sealed outputs; returns the lines it printed."""
    lines = []
    for args, out in ((("practice", "demo2"), tmp / "demo2"), (("practice", "workbooks-bundle"), tmp / "bundle")):
        r = run_extraction(tools, *args, "--out", str(out), "--check")
        if r.returncode != 0:
            raise SealError(f"the overlay does not reproduce `{' '.join(args)} --check` (exit {r.returncode}): {(r.stdout + r.stderr)[-400:]}")
        lines.append(f"{' '.join(args)} --check: exit 0: {r.stdout.strip().splitlines()[-1]}")
    sealed = h / BUNDLE_DIR
    names = sorted(p.name for p in sealed.iterdir())
    if names != sorted(p.name for p in (tmp / "bundle").iterdir()):
        raise SealError("the regenerated bundle lists other files than the sealed one")
    for n in names:
        if (sealed / n).read_bytes() != (tmp / "bundle" / n).read_bytes():
            raise SealError(f"the regenerated bundle differs from the sealed one at {n}")
    lines.append(f"regenerated bundle == sealed {BUNDLE_DIR} ({len(names)} files, byte for byte)")
    return lines
