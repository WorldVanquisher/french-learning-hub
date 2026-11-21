#!/usr/bin/env python3
"""Local mock model smoke (REL-122..130): the behaviours the plan relies on, with a synthetic model package.

  mock_model_smoke.py WORK_DIR [--config runtime/model-runtime.example.json]

An in-process HTTP server on 127.0.0.1 plays a model runtime. Nothing is downloaded, no real model runs. Steps:
  S1  process boot is not readiness: /healthz 200 while /readyz is 503 "loading"
  S2  ready only after the files match the manifest and a warm-up: /readyz 200 names the pinned identity
  S3  a known-good request returns the expected output
  S4  an unknown model is 404 unknown_model, nothing loaded
  S5  limits: an oversized body is 413; a slow request is 504 after the timeout, sent once (no retry)
  S6  logs name the identity (name@revision12, manifest sha256 prefix) and never the request text
  S7  a corrupted package never becomes ready: /readyz stays 503 failed manifest_mismatch
  S8  app + model identity pair: upgrade to v2, then roll back to v1; the pair after rollback equals the one before
  S9  cleanup: the unpacked model cache is removed; only the evidence remains
Exit criteria: every step PASS -> exit 0; any FAIL -> exit 1. Results: WORK_DIR/results.tsv and results.json.
"""
import hashlib
import http.client
import http.server
import json
import os
import shutil
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP_IDENTITY = "flh-staging-35da542d0dd4"     # the R4 candidate the pair is recorded with
SECRET_MARK = "SYNTHETIC-LEARNER-TEXT-7f3a"   # must never appear in a log


def text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def make_package(root, name, revision, corrupt=False):
    d = os.path.join(root, f"{name}-{revision[:8]}")
    os.makedirs(d)
    weights = hashlib.sha256(revision.encode()).digest() * 2048           # deterministic synthetic bytes
    with open(os.path.join(d, "weights.bin"), "wb") as fh:
        fh.write(weights)
    manifest = {"name": name, "revision": revision, "files": {"weights.bin": sha(weights)}}
    with open(os.path.join(d, "MANIFEST.json"), "w") as fh:
        json.dump(manifest, fh, sort_keys=True)
    if corrupt:
        with open(os.path.join(d, "weights.bin"), "ab") as fh:
            fh.write(b"tampered")
    return d


class Runtime:
    def __init__(self, package, cache, cfg, log):
        self.package, self.cache, self.cfg, self.logf = package, cache, cfg, log
        self.state, self.identity, self.error, self.in_flight = "starting", None, None, 0
        self.lock = threading.Lock()

    def log(self, **kw):
        with open(self.logf, "a") as fh:
            fh.write(json.dumps(kw, sort_keys=True) + "\n")

    def load(self):
        self.state = "loading"
        time.sleep(self.cfg["mock"]["load_seconds"])
        with open(os.path.join(self.package, "MANIFEST.json"), "rb") as fh:
            raw = fh.read()
        m = json.loads(raw)
        for f, digest in m["files"].items():
            with open(os.path.join(self.package, f), "rb") as fh:
                if sha(fh.read()) != digest:
                    self.state, self.error = "failed", "manifest_mismatch"
                    self.log(event="load_failed", error="manifest_mismatch", model=f"{m['name']}@{m['revision'][:12]}")
                    return
        os.makedirs(self.cache, exist_ok=True)
        shutil.copy(os.path.join(self.package, "weights.bin"), os.path.join(self.cache, "weights.bin"))   # the "unpacked" copy
        self.identity = {"model": f"{m['name']}@{m['revision'][:12]}", "manifest_sha256": sha(raw), "name": m["name"], "revision": m["revision"]}
        self.infer({"model": m["name"], "input": "warm-up"})                                                  # warm-up before ready
        self.state = "ready"
        self.log(event="model_ready", model=self.identity["model"], manifest_sha256=self.identity["manifest_sha256"][:16])

    def infer(self, req):
        return {"model": self.identity["model"], "output": sha((req["input"] + self.identity["revision"]).encode())[:16]}


def handler_for(rt):
    class H(http.server.BaseHTTPRequestHandler):
        def reply(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/healthz":
                return self.reply(200, {"status": "alive"})
            if self.path == "/readyz":
                if rt.state == "ready":
                    return self.reply(200, {"state": "ready", **{k: rt.identity[k] for k in ("model", "manifest_sha256")}})
                return self.reply(503, {"state": rt.state, **({"error": rt.error} if rt.error else {})})
            return self.reply(404, {"error": "not_found"})

        def do_POST(self):
            rid = hashlib.sha256(f"{time.time_ns()}".encode()).hexdigest()[:12]
            n = int(self.headers.get("Content-Length", "0"))
            if n > rt.cfg["limits"]["max_request_bytes"]:
                rt.log(event="request", request_id=rid, status=413)
                return self.reply(413, {"error": "too_large"})
            body = json.loads(self.rfile.read(n) or b"{}")
            if rt.state != "ready":
                rt.log(event="request", request_id=rid, status=503)
                return self.reply(503, {"error": "unavailable", "state": rt.state})
            if body.get("model") != rt.identity["name"]:
                rt.log(event="request", request_id=rid, status=404, model=rt.identity["model"])
                return self.reply(404, {"error": "unknown_model"})
            if body.get("input") == "__slow__":
                time.sleep(rt.cfg["mock"]["request_timeout_s"] + 0.2)
                rt.log(event="request", request_id=rid, status=504, model=rt.identity["model"])
                return self.reply(504, {"error": "timeout"})
            out = rt.infer(body)
            rt.log(event="request", request_id=rid, status=200, model=rt.identity["model"], bytes_in=n)
            return self.reply(200, out)

        def log_message(self, *a):
            pass
    return H


class Server:
    def __init__(self, package, work, cfg):
        self.rt = Runtime(package, os.path.join(work, "cache"), cfg, os.path.join(work, "mock.log"))
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.rt))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        threading.Thread(target=self.rt.load, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


def call(port, method, path, body=None, timeout=5):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    data = json.dumps(body).encode() if body is not None else None
    c.request(method, path, body=data, headers={"Content-Type": "application/json"} if data else {})
    r = c.getresponse()
    out = (r.status, json.loads(r.read() or b"{}"))
    c.close()
    return out


def wait_ready(port, deadline):
    t0 = time.time()
    while time.time() - t0 < deadline:
        code, body = call(port, "GET", "/readyz")
        if code == 200 or body.get("state") == "failed":
            return code, body
        time.sleep(0.05)
    return call(port, "GET", "/readyz")


def main():
    work = sys.argv[1]
    cfg_path = sys.argv[sys.argv.index("--config") + 1] if "--config" in sys.argv else os.path.join(HERE, "..", "runtime", "model-runtime.example.json")
    with open(cfg_path) as fh:
        cfg = json.load(fh)
    if os.path.exists(work):
        raise SystemExit(f"refused: {work} exists (evidence is never overwritten)")
    os.makedirs(work)
    pkgs = os.path.join(work, "packages")
    v1 = make_package(pkgs, "mock-encoder", "1" * 8 + "a" * 32)
    v2 = make_package(pkgs, "mock-encoder", "2" * 8 + "b" * 32)
    bad = make_package(pkgs, "mock-encoder", "3" * 8 + "c" * 32, corrupt=True)
    rows = []

    def step(sid, ok, expected, actual):
        rows.append({"step": sid, "status": "PASS" if ok else "FAIL", "expected": expected, "actual": str(actual)[:200]})

    s = Server(v1, work, cfg)
    h, rz = call(s.port, "GET", "/healthz"), call(s.port, "GET", "/readyz")
    step("S1", h[0] == 200 and rz[0] == 503 and rz[1].get("state") in ("starting", "loading"),
         "/healthz 200 while /readyz 503 loading", f"healthz {h[0]}, readyz {rz}")
    code, body = wait_ready(s.port, cfg["limits"]["startup_deadline_s"])
    with open(os.path.join(v1, "MANIFEST.json"), "rb") as fh:
        v1_manifest = sha(fh.read())
    step("S2", code == 200 and body.get("manifest_sha256") == v1_manifest, "/readyz 200 with the v1 manifest identity", body)
    expected = sha(("synthetic known-good input" + "1" * 8 + "a" * 32).encode())[:16]
    c, b = call(s.port, "POST", "/v1/infer", {"model": "mock-encoder", "input": "synthetic known-good input"})
    step("S3", c == 200 and b.get("output") == expected, f"200 with output {expected}", (c, b))
    c, b = call(s.port, "POST", "/v1/infer", {"model": "unknown-model", "input": "x"})
    step("S4", c == 404 and b.get("error") == "unknown_model", "404 unknown_model", (c, b))
    c1, _ = call(s.port, "POST", "/v1/infer", {"model": "mock-encoder", "input": "x" * (cfg["limits"]["max_request_bytes"] + 1)})
    before = len(text(os.path.join(work, "mock.log")).splitlines())
    c2, b2 = call(s.port, "POST", "/v1/infer", {"model": "mock-encoder", "input": "__slow__"})
    sent = sum(1 for l in text(os.path.join(work, "mock.log")).splitlines() if '"status": 504' in l)
    step("S5", c1 == 413 and c2 == 504 and sent == 1, "413 oversized; 504 timeout logged exactly once (no retry)", (c1, c2, sent, before))
    call(s.port, "POST", "/v1/infer", {"model": "mock-encoder", "input": SECRET_MARK})
    log = text(os.path.join(work, "mock.log"))
    step("S6", SECRET_MARK not in log and "synthetic known-good input" not in log and '"event": "model_ready"' in log
         and "mock-encoder@11111111aaaa" in log, "identity logged, request text never", f"{len(log.splitlines())} log lines")
    pair_before = {"app": APP_IDENTITY, "model": s.rt.identity["model"], "manifest_sha256": s.rt.identity["manifest_sha256"]}
    s.stop()
    shutil.rmtree(os.path.join(work, "cache"))

    s = Server(bad, work, cfg)
    code, body = wait_ready(s.port, cfg["limits"]["startup_deadline_s"])
    c, b = call(s.port, "POST", "/v1/infer", {"model": "mock-encoder", "input": "x"})
    step("S7", code == 503 and body.get("error") == "manifest_mismatch" and c == 503, "never ready; requests 503 unavailable", (code, body, c))
    s.stop()

    s = Server(v2, work, cfg)
    code, body = wait_ready(s.port, cfg["limits"]["startup_deadline_s"])
    upgraded = s.rt.identity["model"] if code == 200 else None
    s.stop()
    shutil.rmtree(os.path.join(work, "cache"))
    s = Server(v1, work, cfg)
    code, body = wait_ready(s.port, cfg["limits"]["startup_deadline_s"])
    pair_after = {"app": APP_IDENTITY, "model": s.rt.identity["model"] if code == 200 else None,
                  "manifest_sha256": s.rt.identity["manifest_sha256"] if code == 200 else None}
    step("S8", upgraded == "mock-encoder@22222222bbbb" and pair_after == pair_before,
         "upgrade to v2, roll back: the (app, model) pair equals the one before", {"upgraded": upgraded, "after": pair_after["model"]})
    s.stop()
    shutil.rmtree(os.path.join(work, "cache"))
    shutil.rmtree(pkgs)
    left = sorted(os.listdir(work))
    step("S9", left == ["mock.log"], "only the evidence remains (cache and packages removed)", left)
    with open(os.path.join(work, "results.json"), "w") as fh:
        json.dump({"format": "flh-mock-model-smoke/v1", "rows": rows, "pair": pair_before}, fh, indent=1)
    with open(os.path.join(work, "results.tsv"), "w") as fh:
        fh.write("".join(f"{r['step']}\t{r['status']}\t{r['expected']}\t{r['actual']}\n" for r in rows))
    bad_rows = [r for r in rows if r["status"] != "PASS"]
    for r in rows:
        print(f"{r['status']:4} {r['step']}  {r['expected']}")
    print(f"MOCK MODEL SMOKE: {len(rows) - len(bad_rows)} PASS, {len(bad_rows)} FAIL")
    return 1 if bad_rows else 0


if __name__ == "__main__":
    sys.exit(main())
