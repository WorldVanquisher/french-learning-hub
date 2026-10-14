"""FLH-065 test double for `python -m flh_e5 serve`: no model, no GPU.

Accepts the real serve arguments, answers /readyz (503 "loading" until a delay
passes, then 200), /healthz and /manifest, and stops gracefully on
SIGINT/SIGTERM/SIGBREAK, like the real service. Behaviour is chosen by an
optional file FAKE_MODE in --model-dir (so no environment plumbing is needed):

  ready            (default) ready after FAKE_DELAY seconds (default 0.5)
  fail             log "startup failed" and exit 3 after the delay
  mismatch         serve a different deployment_id
  ignore-signals   ignore graceful stop signals (forces a terminate)
  never-ready      stay at 503 "loading"

Each start appends its argv (JSON) to argv.log in --model-dir, so tests can
check quoting of paths with spaces.
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EXPECTED = ("multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/"
            "flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff")


def main(argv):
    ap = argparse.ArgumentParser(prog="python -m flh_e5")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("serve")
    p.add_argument("--model-dir", required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--dtype", default="float16")
    p.add_argument("--microbatch", type=int, default=8)
    p.add_argument("--batching", default="dynamic_v1")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s flh_e5(fake): %(message)s", stream=sys.stderr)
    log = logging.getLogger()

    def setting(name, default):
        try:
            with open(os.path.join(args.model_dir, name), encoding="utf-8") as f:
                return f.read().strip() or default
        except OSError:
            return default

    mode = setting("FAKE_MODE", "ready")
    delay = float(setting("FAKE_DELAY", "0.5"))
    with open(os.path.join(args.model_dir, "argv.log"), "a", encoding="utf-8") as f:
        f.write(json.dumps(sys.argv) + "\n")
    print("fake stdout line", flush=True)
    dep = EXPECTED if mode != "mismatch" else EXPECTED.replace("5a3e23f28a05baff", "0000000000000000")
    if args.dtype != "float16" or args.batching != "singleton_v1" or args.microbatch != 8:
        dep = "fake-unexpected-settings"
    state = {"state": "loading"}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path == "/readyz":
                ok = state["state"] == "ready"
                self.send(200 if ok else 503, {"ready": ok, "state": state["state"]})
            elif self.path == "/healthz":
                self.send(200, {"ok": True})
            elif self.path == "/manifest" and state["state"] == "ready":
                self.send(200, {"deployment_id": dep, "manifest_sha256": "f" * 64})
            else:
                self.send(404, {"error": "not_found"})

    try:
        server = ThreadingHTTPServer((args.host, args.port), H)
    except OSError as e:
        print("bind %s:%d failed: %s" % (args.host, args.port, e), file=sys.stderr)
        return 3
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("listening on http://%s:%d (state loading)", args.host, args.port)
    stop = threading.Event()

    def on_signal(signum, _frame):
        if mode == "ignore-signals":
            log.info("signal %s ignored (fake ignore-signals mode)", signum)
            return
        log.info("signal %s: stopping", signum)
        stop.set()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), on_signal)
    time.sleep(delay)
    if mode == "fail":
        log.error("startup failed, not ready: fake failure")
        server.shutdown()
        return 3
    if mode != "never-ready":
        state["state"] = "ready"
        log.info("ready")
    while not stop.wait(0.2):
        pass
    state["state"] = "stopping"
    server.shutdown()
    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
