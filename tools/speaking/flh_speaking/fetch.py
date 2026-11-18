"""Download pinned files and verify them (size, then SHA-256 or git blob SHA-1).

Layout: ``<dest>/<repo>/<revision>/<path>``. A file already present is
re-verified, never trusted. A mismatch deletes the partial download and fails.
Standard library only; no credentials are sent (every source is public and ungated).
"""

from __future__ import annotations

import hashlib
import os
import time
import urllib.request

from . import pins

USER_AGENT = "flh-speaking-fetch/1"


def file_digest(path: str, kind: str) -> str:
    size = os.path.getsize(path)
    h = hashlib.sha256() if kind == "sha256" else hashlib.sha1(b"blob %d\0" % size)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path: str, size: int, digest: tuple[str, str]) -> str | None:
    """None when the file matches; otherwise a short reason."""
    if not os.path.isfile(path):
        return "missing"
    if os.path.getsize(path) != size:
        return f"size {os.path.getsize(path)} != {size}"
    got = file_digest(path, digest[0])
    return None if got == digest[1] else f"{digest[0]} {got[:12]}… != {digest[1][:12]}…"


def local_path(dest: str, source: dict, path: str) -> str:
    return os.path.join(dest, source["repo"], source["revision"], path)


def url(source: dict, path: str, dataset: bool) -> str:
    if "url" in source:
        return source["url"] + path
    kind = "datasets/" if dataset else ""
    return f"{pins.HF}/{kind}{source['repo']}/resolve/{source['revision']}/{path}"


def fetch_one(dest: str, source: dict, path: str, dataset: bool, log=print) -> str:
    size, digest = source["files"][path]
    target = local_path(dest, source, path)
    if verify(target, size, digest) is None:
        return target
    os.makedirs(os.path.dirname(target), exist_ok=True)
    part = target + ".part"
    req = urllib.request.Request(url(source, path, dataset), headers={"User-Agent": USER_AGENT})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(part, "wb") as out:
            for chunk in iter(lambda: resp.read(1 << 20), b""):
                out.write(chunk)
        bad = verify(part, size, digest)
        if bad:
            raise ValueError(f"{source['repo']}/{path}: {bad}")
        os.replace(part, target)
    finally:
        if os.path.exists(part):
            os.remove(part)
    log(f"fetched {source['repo']}/{path} ({size} bytes, {time.monotonic() - t0:.1f}s)")
    return target


def fetch(dest: str, what: list[str], log=print) -> dict:
    """what: model names (whisper-tiny, ...), 'mls', 'fleurs', 'slr57' and/or 'fleurs-fr-train'. Returns {key: local dir}."""
    out = {}
    for w in what:
        if w in pins.MODELS:
            src, dataset = pins.MODELS[w], False
        elif w == "mls":
            src, dataset = pins.MLS, True
        elif w == "fleurs":
            src, dataset = pins.FLEURS, True
        elif w == "slr57":
            src, dataset = pins.SLR57, True
        elif w == "fleurs-fr-train":
            src, dataset = pins.FLEURS_FR_TRAIN, True
        else:
            raise ValueError(f"unknown source {w!r}")
        for path in sorted(src["files"]):
            fetch_one(dest, src, path, dataset, log)
        out[w] = os.path.join(dest, src["repo"], src["revision"])
    return out


def check(dest: str, what: list[str]) -> list[str]:
    """Problems with already fetched files (empty when every pinned file matches)."""
    problems = []
    for w in what:
        src = pins.MODELS.get(w) or {"mls": pins.MLS, "fleurs": pins.FLEURS, "slr57": pins.SLR57, "fleurs-fr-train": pins.FLEURS_FR_TRAIN}[w]
        for path, (size, digest) in sorted(src["files"].items()):
            bad = verify(local_path(dest, src, path), size, digest)
            if bad:
                problems.append(f"{src['repo']}/{path}: {bad}")
    return problems
