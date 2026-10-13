#!/usr/bin/env python3
"""FLH-060 counting gateway between the demo's server/CLI and the embedding
service.

    gateway.py PORT WORK

Settings come from WORK/demo.json (written by demo.py setup): the upstream base
URL, the exact model, the mode and, in real mode, the budget. It listens on
127.0.0.1 only and forwards POST /v1/embeddings bodies to <upstream>/embeddings
byte for byte, making exactly one attempt with no proxy, no redirect and no
retry. It never logs input text.

What it adds:
  - counts per request kind, separating search queries (concept_search_query_v2)
    from Concept documents (concept_embedding_text_v1/concept), persisted in
    WORK/gateway/state.json so they survive stop/start;
  - in real mode, a hard budget in WORK/gateway/budget.json. Each POST is
    charged BEFORE it is forwarded, so failed or timed-out calls count too.
    Exhausted -> HTTP 429 budget_exhausted, nothing sent;
  - a demo "offline" switch (POST /gateway/offline) that answers 503 without
    contacting the upstream, to show recovery without touching the real service.

GET /gateway/state returns the counters. Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 1 << 20
UPSTREAM_TIMEOUT = 30
KINDS = ("search_query", "concept_document", "unit_query", "other")


def classify(text: str) -> str:
    """Role of one input by its declared representation/type, never by position."""
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return "other"
    if not isinstance(value, dict):
        return "other"
    pair = (value.get("representation"), value.get("type"))
    return {("concept_search_query_v2", "query"): "search_query",
            ("concept_embedding_text_v1", "concept"): "concept_document",
            ("concept_embedding_text_v1", "query"): "unit_query"}.get(pair, "other")


def new_state() -> dict:
    return {"posts_forwarded": 0, "positions_forwarded": 0,
            "positions_by_kind": {k: 0 for k in KINDS},
            "posts_by_kind": {"search": 0, "index": 0, "mixed": 0},
            "upstream_non_200": 0, "upstream_unreachable": 0,
            "refused": {"budget": 0, "offline": 0, "model": 0, "malformed": 0},
            "offline": False}


def atomic_write(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class Gateway:
    def __init__(self, work: Path):
        self.work = work
        cfg = json.loads((work / "demo.json").read_text(encoding="utf-8"))
        self.mode = cfg["mode"]
        self.upstream = cfg["embedding"]["upstream_base_url"].rstrip("/")
        self.model = cfg["embedding"]["model"]
        self.dir = work / "gateway"
        self.dir.mkdir(exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.budget_path = self.dir / "budget.json"
        self.lock = threading.Lock()
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else new_state()
        if self.mode == "real" and not self.budget_path.exists():
            raise SystemExit("gateway: real mode requires WORK/gateway/budget.json (written by demo.py setup)")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def save(self) -> None:
        atomic_write(self.state_path, self.state)

    def charge(self, positions: int) -> str | None:
        """Real mode: reserve one POST and its positions before sending."""
        if self.mode != "real":
            return None
        budget = json.loads(self.budget_path.read_text())
        if budget["used_posts"] + 1 > budget["max_posts"] or budget["used_positions"] + positions > budget["max_positions"]:
            return "budget_exhausted"
        budget["used_posts"] += 1
        budget["used_positions"] += positions
        atomic_write(self.budget_path, budget)
        return None

    def snapshot(self) -> dict:
        out = dict(self.state)
        if self.budget_path.exists():
            out["budget"] = json.loads(self.budget_path.read_text())
        out["mode"], out["model"] = self.mode, self.model
        return out


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - never follow
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "flh060-gateway"
    gw: Gateway

    def log_message(self, fmt, *args):  # request lines only; never bodies
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def send(self, status: int, body: bytes, ctype="application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def error(self, status: int, kind: str, msg: str) -> None:
        self.send(status, json.dumps({"error": {"type": kind, "message": msg}}).encode())

    def do_GET(self):
        if self.path == "/readyz":
            self.send(200, b'{"ready":true}')
        elif self.path == "/gateway/state":
            with self.gw.lock:
                self.send(200, json.dumps(self.gw.snapshot(), sort_keys=True).encode())
        else:
            self.error(404, "not_found", "unknown path")

    def do_POST(self):
        gw = self.gw
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self.error(413, "malformed", "missing or oversized body")
            return
        body = self.rfile.read(length)
        if self.path == "/gateway/offline":
            try:
                flag = bool(json.loads(body)["offline"])
            except (ValueError, KeyError, TypeError):
                self.error(400, "malformed", 'expected {"offline": true|false}')
                return
            with gw.lock:
                gw.state["offline"] = flag
                gw.save()
                self.send(200, json.dumps({"offline": flag}).encode())
            return
        if self.path != "/v1/embeddings":
            self.error(404, "not_found", "unknown path")
            return
        try:
            req = json.loads(body)
            inputs = req["input"]
            if not isinstance(inputs, list) or not inputs or not all(isinstance(x, str) for x in inputs):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            with gw.lock:
                gw.state["refused"]["malformed"] += 1
                gw.save()
            self.error(400, "malformed", "expected {model, input: [strings]}")
            return
        kinds = [classify(x) for x in inputs]
        with gw.lock:
            if req.get("model") != gw.model:
                gw.state["refused"]["model"] += 1
                gw.save()
                self.error(400, "unknown_model", "model is not this demo's configured deployment")
                return
            if gw.state["offline"]:
                gw.state["refused"]["offline"] += 1
                gw.save()
                self.error(503, "demo_offline", "the demo gateway is switched offline; the upstream was not contacted")
                return
            refusal = gw.charge(len(inputs))
            if refusal:
                gw.state["refused"]["budget"] += 1
                gw.save()
                self.error(429, refusal, "the live embedding budget for this demo directory is used up; nothing was sent")
                return
            gw.state["posts_forwarded"] += 1
            gw.state["positions_forwarded"] += len(inputs)
            for k in kinds:
                gw.state["positions_by_kind"][k] += 1
            kind_set = set(kinds)
            post_kind = "search" if kind_set == {"search_query"} else "index" if kind_set == {"concept_document"} else "mixed"
            gw.state["posts_by_kind"][post_kind] += 1
            gw.save()
        upstream = urllib.request.Request(gw.upstream + "/embeddings", data=body, method="POST",
                                          headers={"Content-Type": "application/json"})
        try:
            with gw.opener.open(upstream, timeout=UPSTREAM_TIMEOUT) as resp:
                status, data = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, data = e.code, e.read()
        except (urllib.error.URLError, OSError):
            with gw.lock:
                gw.state["upstream_unreachable"] += 1
                gw.save()
            self.error(502, "upstream_unreachable", "the embedding service could not be reached (one attempt, no retry)")
            return
        if status != 200:
            with gw.lock:
                gw.state["upstream_non_200"] += 1
                gw.save()
        self.send(status, data)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    port, work = int(argv[0]), Path(argv[1]).resolve()
    Handler.gw = Gateway(work)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print(f"gateway on 127.0.0.1:{port} -> {Handler.gw.upstream} ({Handler.gw.mode})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _interrupt(*_):
    raise KeyboardInterrupt


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGTERM, _interrupt)
    sys.exit(main(sys.argv[1:]))
