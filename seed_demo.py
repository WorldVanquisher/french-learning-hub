#!/usr/bin/env python3
"""Import synthetic French Learning Hub captures through the public HTTP API.

The server owns all capture validation, analysis, extraction, and persistence.
Repeated runs reuse the same capture IDs and skip existing extractions.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


CAPTURES = Path(__file__).resolve().parent / "captures"


def request(base, method, path, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {path}: {exc.reason}") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="running FLH backend")
    parser.add_argument(
        "--extract-count", type=int, default=0, metavar="N",
        help="explicitly extract the first N records (external API calls; default 0)",
    )
    parser.add_argument(
        "--verify-replay", action="store_true",
        help="resubmit the first capture and verify idempotent 200/created=false",
    )
    args = parser.parse_args()
    base = args.url.rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or args.extract_count < 0:
        parser.error("--url must be an absolute HTTP(S) URL and --extract-count must be nonnegative")

    files = sorted(CAPTURES.glob("*.json"))
    if not files:
        raise RuntimeError(f"no capture files in {CAPTURES}")
    if args.extract_count > len(files):
        parser.error(f"--extract-count must be <= {len(files)}")

    request(base, "GET", "/healthz")
    print(f"Connected to {base}; {len(files)} synthetic captures")
    first = None
    for index, file in enumerate(files):
        payload = json.loads(file.read_text(encoding="utf-8"))
        status, result = request(base, "POST", "/captures", payload)
        entry_id = result["entry_id"]
        print(f"{file.name}: HTTP {status}, entry={entry_id}, analysis={result['analysis_id']}, new={result['created']}")
        if index == 0:
            first = (payload, result)

        if index >= args.extract_count:
            continue

        _, existing = request(base, "GET", f"/entries/{entry_id}/extractions")
        if existing.get("extractions"):
            print(f"  extraction already exists; skipping (no new version)")
            continue
        if result["analysis_id"] is None:
            _, analyses = request(base, "GET", f"/entries/{entry_id}/analyses")
            if not analyses.get("analyses"):
                _, analysis = request(base, "POST", f"/entries/{entry_id}/analysis")
                print(f"  local/provider analysis created: id={analysis['id']}")
        _, extraction = request(base, "POST", f"/entries/{entry_id}/extractions")
        units = extraction.get("units", [])
        print(f"  extraction={extraction['id']}, units={len(units)}")
        for unit in units:
            print(f"    unit {unit['id']}: {unit['canonical']}")

    if args.verify_replay and first is not None:
        payload, original = first
        status, replay = request(base, "POST", "/captures", payload)
        if status != 200 or replay["created"] or replay["entry_id"] != original["entry_id"]:
            raise RuntimeError(f"unexpected idempotency result: {replay}")
        print(f"Replay verified: HTTP 200, entry={replay['entry_id']}, new=false")

    print("Done. Open Concept Review → Reload queue; then Inspector and Experiment Dashboard.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"seed_demo: {exc}", file=sys.stderr)
        sys.exit(1)
