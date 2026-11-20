"""Versioned request/response examples of flh_extraction_service_v1 for Runtime and Workbooks (synthetic).

  python3 -I -B scripts/service_examples.py --out NEW_DIR      # write the examples (in-process service, loopback)
  python3 -I -B scripts/service_examples.py --check            # regenerate and compare with fixtures/service_v1/

Each example is a pair ``NN-name.request.json`` / ``NN-name.response.json`` taken from a real
call to an in-process service on a free loopback port. ``README.md`` (hand-written) and
``SHA256SUMS`` sit beside them. A response carries the service's ``deployment_id``: a code
change gives new examples, which ``--check`` reports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from flh_extraction import practice as pr  # noqa: E402
from flh_extraction import service as svc  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "practice_v1")
OUT = os.path.join(HERE, "fixtures", "service_v1")


def load(n):
    with open(os.path.join(FIX, n), encoding="utf-8") as fh:
        return json.load(fh)


def cases() -> list[tuple[str, str, dict | None]]:
    a1 = load("a_en_lieux.json")
    d1 = pr.draft(a1)
    ids = {i["proposal_ref"]: i["item_id"] for i in d1["items"]}
    decs = [pr.decision(d1, ids[r], "approve", k + 1) for k, r in enumerate(("a-ville", "en-pays", "a-vs-en", "ex-lyon", "ex-espagne"))]
    decs.append(pr.decision(d1, ids["en-tous-pays"], "reject", 6, reason="« au Japon »: Japon is masculine"))
    prac = pr.build_practice(pr.resolve(d1, decs))
    att = [{"schema": pr.ATTEMPT_SCHEMA, "seq": 1, "practice_id": prac["items"][0]["practice_id"], "action": "reveal", "outcome": "revealed"}]
    return [
        ("01-review-first-revision", "/v1/review", svc.request(sources=[a1])),
        ("02-review-with-decisions-and-revisions", "/v1/review", svc.request(sources=[a1, load("a_en_lieux.r2.json")], decisions=decs)),
        ("03-feed", "/v1/feed", svc.request(sources=[a1], decisions=decs, attempts=att, feed_seq=1)),
        ("04-import-preview", "/v1/import-preview", svc.request(packet=load("expected3/05-packet-1-codex.json"), proposals=load("switch2/codex-a-en.json"))),
        ("05-error-contract-mismatch", "/v1/review", svc.request(sources=[a1])),
        ("06-error-invalid-source", "/v1/review", svc.request(sources=[{**a1, "revision": 0}])),
        ("07-manifest", "/manifest", None),
    ]


def write(out: str) -> list[str]:
    srv = svc.make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    os.makedirs(out, exist_ok=True)
    names = []
    try:
        for name, path, req in cases():
            contract = "flh_extraction_service_v0" if "contract-mismatch" in name else svc.CONTRACT
            status, doc = svc.call(url, path, req, contract=contract)
            if req is not None:
                with open(os.path.join(out, f"{name}.request.json"), "w", encoding="utf-8") as fh:
                    fh.write(json.dumps({"method": "POST", "path": path, "headers": {"Content-Type": "application/json", "X-FLH-Contract": contract},
                                         "body": req}, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
                names.append(f"{name}.request.json")
            with open(os.path.join(out, f"{name}.response.json"), "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"status": status, "body": doc}, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
            names.append(f"{name}.response.json")
    finally:
        srv.shutdown()
        srv.server_close()
        srv.state.pool.shutdown(wait=True)
    return names


def _bytes(p: str) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()


def seal(d: str) -> None:
    rows = []
    for n in sorted(os.listdir(d)):
        if n != "SHA256SUMS":
            with open(os.path.join(d, n), "rb") as fh:
                rows.append(f"{hashlib.sha256(fh.read()).hexdigest()}  {n}\n")
    with open(os.path.join(d, "SHA256SUMS"), "w", encoding="utf-8") as fh:
        fh.write("".join(rows))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--out")
    g.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.out:
        if os.path.exists(a.out) and os.listdir(a.out):
            raise SystemExit("--out must be a new or empty directory")
        names = write(a.out)
        if os.path.exists(os.path.join(OUT, "README.md")):
            shutil.copyfile(os.path.join(OUT, "README.md"), os.path.join(a.out, "README.md"))
        seal(a.out)
        print(f"wrote {len(names)} example files")
        return 0
    with tempfile.TemporaryDirectory() as t:
        write(t)
        shutil.copyfile(os.path.join(OUT, "README.md"), os.path.join(t, "README.md"))
        seal(t)
        bad = [n for n in sorted(set(os.listdir(t)) | set(os.listdir(OUT)))
               if not (os.path.exists(os.path.join(t, n)) and os.path.exists(os.path.join(OUT, n)))
               or _bytes(os.path.join(t, n)) != _bytes(os.path.join(OUT, n))]
    print("check: the examples equal fixtures/service_v1/" if not bad else f"CHECK FAILED: {', '.join(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
