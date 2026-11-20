"""Private extraction service (``flh_extraction_service_v1``; standard library only).

It serves the existing, offline practice pipeline over HTTP so a staged FLH can call it:
grounding a learner's question and its evidence (``practice.draft``), the 2.2 review
(``review2.resolve2`` / ``plan``), the Workbooks feed (``feed2.feed``) and the read-only
agent-return preview (``portable.import_any``). It holds no state between requests, keeps
no request body, and contacts no model, provider or network.

  python3 -B -m flh_extraction.service serve [--host 127.0.0.1] [--port 8090] [--max-inflight 4] [--timeout 5]
  python3 -B -m flh_extraction.service smoke [--url http://127.0.0.1:8090]   # one-command smoke (in-process when no --url)
  python3 -B -m flh_extraction.service manifest

Contract (``tools/extraction/SERVICE.md``):

* ``GET /metrics`` (requests by outcome since start: ok, client_error, busy, timeout,
  internal; for monitoring, no request content), ``GET /healthz`` (alive), ``GET /readyz`` (200 only after the self-check drafts a
  built-in synthetic source and gets its pinned draft ID and grounding), ``GET /manifest`` (deployment identity:
  code hashes, rules, limits; no paths, no environment).
* ``POST /v1/review``, ``POST /v1/feed``, ``POST /v1/import-preview``: JSON bodies
  ``flh_extraction_request_v1`` with ``"contract": "flh_extraction_service_v1"``; the
  ``X-FLH-Contract`` header must carry the same value (a different value is 409).
* Bounds: body size, revisions, decisions and attempts per request, one deadline per
  request (504) and a fixed number of requests in flight (503 ``busy``; never queued
  without bound). Errors are ``{"error": {"type": CODE, "message": …}}`` with the codes in
  ``CODES``; a 500 never carries a traceback or input text.
* It binds loopback by default; any other address must be private (RFC 1918 / ULA), or
  ``0.0.0.0`` inside a container whose port is published privately.
* Logs: one JSON line per request with method, path, status, code, request ID, sizes and
  duration; never a body, a quote or any other header value. ``X-Request-Id`` is echoed when
  the caller sends a well-formed one (letters, digits, ``._-``, at most 64), else generated.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import ipaddress
import json
import os
import re
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import feed2
from . import portable as pt
from . import practice as pr
from . import review2 as rv

CONTRACT = "flh_extraction_service_v1"
REQUEST = "flh_extraction_request_v1"
RESULT = "flh_extraction_result_v1"
MANIFEST = "flh_extraction_deployment_manifest_v1"
LIMITS = {"max_body_bytes": 262144, "max_revisions": 8, "max_items_per_source": 64, "max_decisions": 1000, "max_attempts": 5000,
          "request_timeout_s": 5.0, "max_inflight": 4}
CODES = {
    "invalid_request": (400, "not JSON, a wrong schema or contract field, or a missing X-FLH-Contract header"),
    "not_found": (404, "no such path"),
    "method_not_allowed": (405, "GET for health, readiness and the manifest; POST for /v1/*"),
    "contract_mismatch": (409, "the client speaks another contract version; the body names the service's"),
    "length_required": (411, "Content-Length is required"),
    "too_large": (413, "the body, the number of revisions, items, decisions or attempts exceeds a limit"),
    "unsupported_media_type": (415, "Content-Type must be application/json"),
    "invalid_source": (422, "a source is not a valid flh_practice_source_v1, or the revisions do not belong together"),
    "invalid_decisions": (422, "decisions or attempts are not valid records for these sources"),
    "invalid_return": (422, "an agent return or packet cannot be read (format version, fields)"),
    "busy": (503, "the service is at its in-flight limit; nothing was processed (the client decides whether to retry)"),
    "not_ready": (503, "the self-check has not passed"),
    "timeout": (504, "the request exceeded its deadline; its result is discarded"),
    "internal": (500, "an unexpected error; details stay in the service's own counters, never in the response"),
}
CODE_FILES = ("__init__.py", "audit.py", "evaluate.py", "evidence_review.py", "exercises.py", "feed2.py", "feed_compat.py", "packet.py",
              "portable.py", "practice.py", "quality.py", "records.py", "review2.py", "service.py", "textnorm.py")
PKG = os.path.dirname(os.path.abspath(__file__))
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
SELF_CHECK_SOURCE = {"schema": "flh_practice_source_v1", "source_id": "service-self-check", "revision": 1, "learner_goal": "", "capture": {"schema_version": "learning_capture_v1", "source": "manual", "original_input": "Pourquoi « j'y vais » ?", "original_context": "Elle a dit : « On dit : oui, j'y vais. »"}, "proposal": {"proposer": "synthetic: service self-check", "items": [{"type": "claim", "ref": "y", "statement": "« y » replaces a place after « à ».", "quotes": ["On dit : oui, j'y vais."], "kind": "grammar", "canonical": "y"}, {"type": "claim", "ref": "x", "statement": "« en » goes with every verb.", "quotes": ["not in the text"], "kind": "grammar", "canonical": "en"}]}}
SELF_CHECK_EXPECT = ("d-57ae5bbb7fa3", ["supported", "unsupported"])  # pinned: the rules ground one quote and refuse the other


class ServiceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.status = code, CODES[code][0]


def _sha_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def manifest(limits: dict | None = None) -> dict:
    code = {f: _sha_file(os.path.join(PKG, f)) for f in CODE_FILES}
    code_id = hashlib.sha256(pr.canon(code).encode()).hexdigest()
    rules = {"drafter": pr.DRAFTER, "review": rv.REVIEW_SCHEMA, "batch_plan": rv.PLAN_SCHEMA, "cues": rv.CUES, "material_hash": rv.MATERIAL,
             "feed": pk_feed(), "packet": pt.PACKET_SCHEMA_V3}
    return {"schema": MANIFEST, "contract": CONTRACT, "deployment_id": f"flh-extraction-rules@{code_id[:12]}/{CONTRACT}/{pr.DRAFTER}",
            "model": {"kind": "rules", "learned_weights": None, "note": "deterministic grounding and review rules; no model is loaded or called"},
            "rules": rules, "code_sha256": code, "code_id": code_id, "limits": dict(limits or LIMITS), "codes": {k: v[0] for k, v in CODES.items()}}


def pk_feed() -> str:
    return feed2.fc.FEED


# ---- request handling (pure functions; the HTTP layer only maps them) ----

def _sources(req: dict, limits: dict) -> tuple[dict, dict]:
    srcs = req.get("sources")
    if not isinstance(srcs, list) or not srcs:
        raise ServiceError("invalid_request", "sources must be a non-empty list of flh_practice_source_v1 documents (oldest revision first)")
    if len(srcs) > limits["max_revisions"]:
        raise ServiceError("too_large", f"at most {limits['max_revisions']} revisions per request")
    drafts, by_rev = {}, {}
    for s in srcs:
        try:
            pr.validate_source(s)
        except ValueError as e:
            raise ServiceError("invalid_source", str(e)) from None
        if len(s["proposal"]["items"]) > limits["max_items_per_source"]:
            raise ServiceError("too_large", f"at most {limits['max_items_per_source']} proposal items per source")
        if s["revision"] in by_rev:
            raise ServiceError("invalid_source", f"revision {s['revision']} is given twice")
        by_rev[s["revision"]] = s
    if len({s["source_id"] for s in srcs}) != 1:
        raise ServiceError("invalid_source", "all revisions must have the same source_id")
    for r, s in by_rev.items():
        drafts[r] = pr.draft(s)
    return drafts, by_rev


def _decisions(req: dict, drafts: dict, limits: dict) -> list[dict]:
    ds = req.get("decisions", [])
    if not isinstance(ds, list) or len(ds) > limits["max_decisions"]:
        raise ServiceError("too_large" if isinstance(ds, list) else "invalid_decisions", f"decisions: a list of at most {limits['max_decisions']}")
    try:
        out = pr.read_decisions(json.dumps(d) for d in ds)
    except (ValueError, TypeError) as e:
        raise ServiceError("invalid_decisions", str(e)) from None
    known = {i["item_id"] for d in drafts.values() for i in d["items"]}
    for d in out:
        if d["item_id"] not in known or d.get("based_on", {}).get("source_revision") not in drafts:
            raise ServiceError("invalid_decisions", f"decision {d['seq']} names an item or revision that is not in the request")
    return out


def _compact(it: dict) -> dict:
    return {"item_id": it["item_id"], "type": it["type"], "origin": it["origin"], "support": it["support"], "state": it["state"],
            "review_kind": it.get("review_kind"), "text": it.get("effective", it["content"])[pr.MAIN_TEXT[it["type"]]],
            "groundings": [{k: g[k] for k in ("quote", "status", "evidence_id") if k in g} for g in it["groundings"]],
            "evidence_ids": it["evidence_ids"], "cues": [{"cue": c["cue"], "detail": c["detail"]} for c in it["cues"]],
            "conflicts": [c["other_id"] if c["error_id"] == it["item_id"] else c["error_id"] for c in it["conflicts"]],
            "paraphrases": len(it["paraphrases"]), "decided_on_revision": it.get("decided_on_revision"),
            "carried_from_revision": it.get("carried_from_revision"), "item_hash": it["item_hash"], "material_hash": it["material_hash"]}


def handle_review(req: dict, limits: dict) -> dict:
    drafts, srcs = _sources(req, limits)
    res = rv.resolve2(drafts, _decisions(req, drafts, limits), srcs)
    plan = rv.plan(res)
    return {"operation": "review", "draft_id": res["draft_id"], "source": res["source"], "states": res["states"], "counts": res["counts"],
            "items": [_compact(i) for i in res["items"]], "evidence": res["evidence"], "moves": res["moves"],
            "plan": {"batch_id": plan["batch_id"], "selected": plan["selected"], "left_for_you": [{"item_id": r["item_id"], "why": r["why"]}
                                                                                                  for r in plan["left_for_you"]],
                     "effects": plan["effects"]},
            "text": rv.render_items(res) + "\n" + rv.render_plan(plan)}


def handle_feed(req: dict, limits: dict) -> dict:
    drafts, srcs = _sources(req, limits)
    res = rv.resolve2(drafts, _decisions(req, drafts, limits), srcs)
    attempts = req.get("attempts", [])
    if not isinstance(attempts, list) or len(attempts) > limits["max_attempts"]:
        raise ServiceError("too_large" if isinstance(attempts, list) else "invalid_decisions", f"attempts: a list of at most {limits['max_attempts']}")
    prac = pr.build_practice(res)
    # An attempt may name any practice ID the learner was offered: offered now, offered in the previous feed, or
    # withdrawn there (a withdrawn ID stays listed until it is offered again and keeps its outcome history).
    prev = req.get("previous") or {}
    known = {p["practice_id"] for p in prac["items"]} | {x.get("practice_id") for k in ("items", "withdrawn")
                                                          for x in (prev.get(k) or [] if isinstance(prev, dict) else []) if isinstance(x, dict)}
    for a in attempts:
        if not isinstance(a, dict) or a.get("schema") != pr.ATTEMPT_SCHEMA or a.get("practice_id") not in known or not isinstance(a.get("seq"), int) \
                or a.get("action") not in ("attempt", "reveal") or a.get("outcome") not in ("correct", "incorrect", "self_check", "revealed", "invalid"):
            raise ServiceError("invalid_decisions", "every attempt must be a flh_practice_attempt_v1 record for a practice ID of these sources")
    seq = req.get("feed_seq")
    if not isinstance(seq, int) or seq < 1:
        raise ServiceError("invalid_request", "feed_seq must be a positive integer")
    try:
        f = feed2.feed(res, prac, [{k: a[k] for k in ("seq", "practice_id", "action", "outcome")} for a in attempts], seq, req.get("previous"))
    except ValueError as e:
        raise ServiceError("invalid_request", str(e)) from None
    return {"operation": "feed", "feed": f}


def handle_import_preview(req: dict, limits: dict) -> dict:
    packet, ret = req.get("packet"), req.get("proposals")
    if not isinstance(packet, dict) or not isinstance(ret, dict):
        raise ServiceError("invalid_request", "packet and proposals must be JSON objects")
    try:
        rep = pt.import_any(packet, ret)
    except (ValueError, KeyError, TypeError) as e:
        raise ServiceError("invalid_return", str(e) if not isinstance(e, KeyError) else f"missing field {e}") from None
    return {"operation": "import_preview", "preview": rep, "text": pt.render_import_any(rep)}


ROUTES = {"/v1/review": handle_review, "/v1/feed": handle_feed, "/v1/import-preview": handle_import_preview}


def dispatch(path: str, body: bytes, headers: dict, limits: dict, deployment_id: str) -> dict:
    """Validate the envelope, run one operation, return the result document (raises ServiceError)."""
    if path not in ROUTES:
        raise ServiceError("not_found", f"no route {path}")
    client = headers.get("x-flh-contract")
    if not client:
        raise ServiceError("invalid_request", f"send the X-FLH-Contract header ({CONTRACT})")
    if client != CONTRACT:
        raise ServiceError("contract_mismatch", f"this service speaks {CONTRACT}; the client sent {client[:64]}")
    try:
        req = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ServiceError("invalid_request", "the body is not UTF-8 JSON") from None
    if not isinstance(req, dict) or req.get("schema") != REQUEST or req.get("contract") != CONTRACT:
        raise ServiceError("invalid_request", f"the body must be {REQUEST} with contract {CONTRACT}")
    out = ROUTES[path](req, limits)
    return {"schema": RESULT, "contract": CONTRACT, "deployment_id": deployment_id, "status": "ok", **out}


# ---- HTTP layer ----

class State:
    def __init__(self, limits: dict, slow_hook=None):
        self.limits = dict(limits)
        self.manifest = manifest(self.limits)
        self.status, self.reason = "starting", ""
        self.sem = threading.BoundedSemaphore(self.limits["max_inflight"])
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.limits["max_inflight"])
        self.counters = {k: 0 for k in ("ok", "client_error", "busy", "timeout", "internal")}
        self.lock = threading.Lock()
        self.slow_hook = slow_hook  # tests only: delay inside the timed work

    def self_check(self) -> None:
        try:
            d = pr.draft(SELF_CHECK_SOURCE)
            got = (d["draft_id"], [i["support"] for i in d["items"]])
            self.status, self.reason = ("ready", "") if got == (SELF_CHECK_EXPECT[0], SELF_CHECK_EXPECT[1]) else ("failed", "self-check result differs")
        except Exception as exc:  # stays failed; /readyz reports the class only
            self.status, self.reason = "failed", type(exc).__name__

    def count(self, k: str) -> None:
        with self.lock:
            self.counters[k] += 1


class Handler(BaseHTTPRequestHandler):
    server_version = "flh-extraction"
    sys_version = ""

    @property
    def st(self) -> State:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):
        pass

    def _request_id(self) -> str:
        """The caller's X-Request-Id when it is well formed (FLH sends 16 hex), else a new one; echoed and logged."""
        if not hasattr(self, "_rid"):
            given = self.headers.get("X-Request-Id") or ""
            self._rid = given if REQUEST_ID.fullmatch(given) else secrets.token_hex(8)
        return self._rid

    def _log(self, status: int, code: str, t0: float, n_in: int, n_out: int) -> None:
        sys.stderr.write(json.dumps({"method": self.command, "path": self.path.split("?")[0], "status": status, "code": code,
                                     "request_id": self._request_id(), "bytes_in": n_in, "bytes_out": n_out,
                                     "ms": round((time.monotonic() - t0) * 1000)}) + "\n")

    def _send(self, status: int, doc: dict, t0: float, code: str = "ok", n_in: int = 0) -> None:
        body = (json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-FLH-Contract", CONTRACT)
        self.send_header("X-Request-Id", self._request_id())
        self.end_headers()
        self.wfile.write(body)
        self._log(status, code, t0, n_in, len(body))

    def _error(self, e: ServiceError, t0: float, n_in: int = 0) -> None:
        doc = {"error": {"type": e.code, "message": str(e)}}
        if e.code == "contract_mismatch":
            doc["service_contract"] = CONTRACT
        self._send(e.status, doc, t0, e.code, n_in)

    def do_GET(self):
        t0, path = time.monotonic(), self.path.split("?")[0]
        if path == "/healthz":
            self._send(200, {"status": "alive"}, t0)
        elif path == "/readyz":
            self._send(200 if self.st.status == "ready" else 503, {"status": self.st.status, "reason": self.st.reason,
                                                                   "deployment_id": self.st.manifest["deployment_id"]}, t0)
        elif path == "/manifest":
            self._send(200, self.st.manifest, t0)
        elif path == "/metrics":
            with self.st.lock:
                counters = dict(self.st.counters)
            self._send(200, {"status": self.st.status, "counters": counters, "deployment_id": self.st.manifest["deployment_id"]}, t0)
        elif path in ROUTES:
            self._error(ServiceError("method_not_allowed", "use POST"), t0)
        else:
            self._error(ServiceError("not_found", f"no route {path}"), t0)

    def do_POST(self):
        t0, path, n_in = time.monotonic(), self.path.split("?")[0], 0
        st = self.st
        try:
            if path in ("/healthz", "/readyz", "/manifest", "/metrics"):
                raise ServiceError("method_not_allowed", "use GET")
            if path not in ROUTES:
                raise ServiceError("not_found", f"no route {path}")
            if st.status != "ready":
                raise ServiceError("not_ready", f"the service is {st.status}")
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                raise ServiceError("unsupported_media_type", "Content-Type must be application/json")
            if self.headers.get("Content-Length") is None:
                raise ServiceError("length_required", "Content-Length is required")
            n_in = int(self.headers.get("Content-Length") or 0)
            if n_in > st.limits["max_body_bytes"]:
                if n_in <= 4 * st.limits["max_body_bytes"]:
                    self.rfile.read(n_in)  # drained and discarded so the client can read the refusal
                self.close_connection = True
                raise ServiceError("too_large", f"the body is larger than {st.limits['max_body_bytes']} bytes")
            body = self.rfile.read(n_in)
            if not st.sem.acquire(blocking=False):
                raise ServiceError("busy", f"{st.limits['max_inflight']} requests are in flight")
            try:
                headers = {k.lower(): v for k, v in self.headers.items()}

                def work():
                    if st.slow_hook:
                        st.slow_hook()
                    return dispatch(path, body, headers, st.limits, st.manifest["deployment_id"])
                fut = st.pool.submit(work)
                try:
                    doc = fut.result(timeout=st.limits["request_timeout_s"])
                except concurrent.futures.TimeoutError:
                    raise ServiceError("timeout", f"no result within {st.limits['request_timeout_s']} s") from None
            finally:
                st.sem.release()
            st.count("ok")
            self._send(200, doc, t0, "ok", n_in)
        except ServiceError as e:
            st.count({"busy": "busy", "timeout": "timeout"}.get(e.code, "client_error"))
            self._error(e, t0, n_in)
        except Exception:  # never echo input or a traceback
            st.count("internal")
            self._error(ServiceError("internal", "internal error"), t0, n_in)


def check_host(host: str) -> None:
    """Loopback or a private address; 0.0.0.0 only inside a container."""
    if host == "0.0.0.0":
        if not (os.path.exists("/.dockerenv") or os.environ.get("FLH_IN_CONTAINER") == "1"):
            raise SystemExit("refusing 0.0.0.0 outside a container: bind 127.0.0.1 or a private address")
        return
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise SystemExit("--host must be an IP literal") from None
    if not (ip.is_loopback or ip.is_private) or ip.is_unspecified:
        raise SystemExit(f"refusing to bind a public address ({host})")


def make_server(host: str, port: int, limits: dict | None = None, slow_hook=None) -> ThreadingHTTPServer:
    st = State(dict(limits or LIMITS), slow_hook)
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    srv.state = st  # type: ignore[attr-defined]
    st.self_check()
    return srv


# ---- client (no automatic retry) ----

def call(url: str, path: str, payload: dict | None = None, timeout: float = 10.0, contract: str = CONTRACT,
         expect_deployment: str | None = None) -> tuple[int, dict]:
    """(HTTP status, document). A connection failure is (0, unavailable). Never retries: the caller decides.
    With ``expect_deployment``, a 200 from another deployment is reported as (0, deployment_mismatch)."""
    import urllib.error
    import urllib.request
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url.rstrip("/") + path, data=data, method="GET" if data is None else "POST",
                                 headers={"Content-Type": "application/json", "X-FLH-Contract": contract} if data is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, doc = r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except ValueError:
            return e.code, {"error": {"type": "invalid_response", "message": "not JSON"}}
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return 0, {"error": {"type": "unavailable", "message": type(getattr(e, "reason", e)).__name__}}
    if status == 200 and expect_deployment and doc.get("deployment_id") not in (None, expect_deployment):
        return 0, {"error": {"type": "deployment_mismatch", "message": f"expected {expect_deployment}, got {doc.get('deployment_id')}"}}
    return status, doc


def request(**fields) -> dict:
    return {"schema": REQUEST, "contract": CONTRACT, **fields}


def smoke(url: str | None = None) -> tuple[int, str]:
    """Health, readiness, manifest, one review per shipped contrast, a feed, an import preview and
    six refusals. In-process on a free loopback port when ``url`` is None."""
    srv = None
    if url is None:
        srv = make_server("127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"
    fix = os.path.join(os.path.dirname(PKG), "fixtures", "practice_v1")

    def load(n):
        with open(os.path.join(fix, n), encoding="utf-8") as fh:
            return json.load(fh)
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))
    try:
        s, d = call(url, "/healthz")
        check("healthz 200", s == 200)
        s, d = call(url, "/readyz")
        check("readyz 200", s == 200 and d.get("status") == "ready", d.get("deployment_id", ""))
        s, man = call(url, "/manifest")
        check("manifest names the contract", s == 200 and man.get("contract") == CONTRACT)
        dep = man.get("deployment_id")
        for name in ("y_en.r1.json", "savoir_connaitre.json", "a_en_lieux.json"):
            s, d = call(url, "/v1/review", request(sources=[load(name)]), expect_deployment=dep)
            local = pr.draft(load(name))["draft_id"]
            check(f"review {name}", s == 200 and d.get("draft_id") == local, f"draft {d.get('draft_id')}, batch {d.get('plan', {}).get('batch_id')}")
        s, d = call(url, "/v1/review", request(sources=[load("y_en.r1.json"), load("y_en.r2.json"), load("y_en.r3.json")]))
        check("review three revisions", s == 200 and len(d.get("moves", {})) == 3, f"states {d.get('states')}")
        s, d = call(url, "/v1/feed", request(sources=[load("a_en_lieux.json")], feed_seq=1))
        check("feed", s == 200 and d["feed"]["schema"] == "flh_practice_review_feed_v1", f"{len(d.get('feed', {}).get('items', []))} items")
        s, d = call(url, "/v1/import-preview", request(packet=load("expected3/05-packet-1-codex.json"), proposals=load("switch2/codex-a-en.json")))
        check("import preview", s == 200 and d["preview"]["exercises"]["counts"]["candidate"] == 3)
        s, d = call(url, "/v1/review", request(sources=[load("y_en.r1.json")]), contract="flh_extraction_service_v0")
        check("old client refused (409 contract_mismatch)", s == 409 and d["error"]["type"] == "contract_mismatch")
        bad = load("y_en.r1.json")
        bad["revision"] = 0
        s, d = call(url, "/v1/review", request(sources=[bad]))
        check("invalid source (422)", s == 422 and d["error"]["type"] == "invalid_source")
        s, d = call(url, "/v1/review", {"schema": "something_else"})
        check("wrong envelope (400)", s == 400 and d["error"]["type"] == "invalid_request")
        s, d = call(url, "/v1/review", request(sources=[load("y_en.r1.json")], pad="x" * (LIMITS["max_body_bytes"] + 1)))
        check("oversized body (413)", s == 413 and d["error"]["type"] == "too_large")
        s, d = call(url, "/v1/nothing", request())
        check("unknown path (404)", s == 404)
        s, d = call(url, "/manifest", request())
        check("POST on a GET path (405)", s == 405)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
            srv.state.pool.shutdown(wait=True)  # type: ignore[attr-defined]
    ok = all(c[1] for c in checks)
    text = "".join(f"{'PASS' if c[1] else 'FAIL'} {c[0]}" + (f"  ({c[2]})" if c[2] else "") + "\n" for c in checks)
    return (0 if ok else 1), text + f"smoke: {sum(c[1] for c in checks)}/{len(checks)} passed against {'an in-process server' if srv else 'the given URL'}\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="flh_extraction.service")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8090)
    s.add_argument("--max-inflight", type=int, default=LIMITS["max_inflight"])
    s.add_argument("--timeout", type=float, default=LIMITS["request_timeout_s"])
    sm = sub.add_parser("smoke")
    sm.add_argument("--url")
    sub.add_parser("manifest")
    a = ap.parse_args(argv)
    if a.cmd == "manifest":
        print(json.dumps(manifest(), indent=1, sort_keys=True))
        return 0
    if a.cmd == "smoke":
        rc, text = smoke(a.url)
        sys.stdout.write(text)
        return rc
    check_host(a.host)
    srv = make_server(a.host, a.port, {**LIMITS, "max_inflight": a.max_inflight, "request_timeout_s": a.timeout})
    sys.stderr.write(json.dumps({"event": "listening", "port": srv.server_address[1], "status": srv.state.status,  # type: ignore[attr-defined]
                                 "deployment_id": srv.state.manifest["deployment_id"]}) + "\n")  # type: ignore[attr-defined]
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
