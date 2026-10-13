"""Persistent caps ledger for billable calls.

Every billable request is *reserved* (counted, with its byte/character size)
and flushed to disk before it is sent. A crash after reservation therefore
over-counts, never under-counts. The outcome is recorded afterwards. Caps are
checked at reservation, so a refused call never reaches the network.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import fcntl
import json
import os
from pathlib import Path

MIB = 1024 * 1024

# Defaults for one state directory (the whole first experiment).
DEFAULT_CAPS = {
    "s3_put_requests": 20,
    "s3_put_bytes": 100 * MIB,
    "s3_get_requests": 100,
    "s3_get_bytes": 300 * MIB,
    "s3_delete_requests": 40,
    "s3_list_requests": 20,
    "bedrock_invocations": 10,
    "bedrock_input_chars": 8000,
    "bedrock_request_bytes": 64 * 1024,
}
# Per-request limit, enforced separately from the totals.
MAX_CHARS_PER_INPUT = 2000


class CapExceeded(Exception):
    """Raised before sending when a reservation would exceed a cap."""


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Ledger:
    """A JSON ledger guarded by an exclusive file lock for each update."""

    def __init__(self, state_dir: Path, caps: dict | None = None):
        self.path = Path(state_dir) / "ledger.json"
        self.lock_path = Path(state_dir) / "ledger.lock"
        if not self.path.exists():
            with self._locked():
                if not self.path.exists():
                    _atomic_write(self.path, {
                        "schema": "flh063_ledger_v1",
                        "created_utc": utc_now(),
                        "caps": dict(caps or DEFAULT_CAPS),
                        "used": {k: 0 for k in DEFAULT_CAPS},
                        "calls": [],
                    })

    @contextlib.contextmanager
    def _locked(self):
        with open(self.lock_path, "a+") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def read(self) -> dict:
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def remaining(self) -> dict:
        d = self.read()
        return {k: d["caps"][k] - d["used"].get(k, 0) for k in d["caps"]}

    def reserve(self, kind: str, amounts: dict, detail: dict, backend: str) -> int:
        """Count a call before sending it. Returns the call's sequence number.

        ``amounts`` maps cap names to the quantity this call consumes. Raises
        CapExceeded, and records nothing, if any cap would be exceeded.
        """
        with self._locked():
            d = self.read()
            for k, v in amounts.items():
                if k not in d["caps"]:
                    raise KeyError(f"unknown cap {k}")
                if d["used"].get(k, 0) + v > d["caps"][k]:
                    raise CapExceeded(
                        f"{k}: used {d['used'].get(k, 0)} + {v} would exceed cap {d['caps'][k]}; nothing sent")
            for k, v in amounts.items():
                d["used"][k] = d["used"].get(k, 0) + v
            seq = len(d["calls"]) + 1
            d["calls"].append({"seq": seq, "kind": kind, "backend": backend, "reserved_utc": utc_now(),
                               "amounts": amounts, "detail": detail, "outcome": "attempted"})
            _atomic_write(self.path, d)
            return seq

    def finish(self, seq: int, outcome: str, result: dict | None = None) -> None:
        with self._locked():
            d = self.read()
            call = d["calls"][seq - 1]
            call["outcome"] = outcome
            call["finished_utc"] = utc_now()
            if result:
                call["result"] = result
            _atomic_write(self.path, d)


@contextlib.contextmanager
def charged(ledger: Ledger, kind: str, amounts: dict, detail: dict, backend: str):
    """Reserve, yield a dict for the result, then record ok/failed."""
    seq = ledger.reserve(kind, amounts, detail, backend)
    result: dict = {}
    try:
        yield result
    except BaseException as e:  # noqa: BLE001 - recorded, then re-raised
        ledger.finish(seq, "failed", {"error_type": type(e).__name__, **result})
        raise
    ledger.finish(seq, "ok", result)
