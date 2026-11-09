#!/usr/bin/env python3
"""Loopback proxy for the capture batch acceptance (scripts/validation/capture_batch).

Forwards every request to the real FLH server. For the first POST whose JSON
capture_id equals --drop-id it waits for the server's complete response (the
capture is committed), then closes the connection without answering: a
response lost after commit. Every request is logged as one line with method,
path and capture_id only, never the body, so a preview can be shown to send
nothing.

    python3 -I -B lossy_proxy.py --port 18998 --upstream http://127.0.0.1:18997 \
        --drop-id batch-lost --log WORK/proxy.log
"""
import argparse
import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARGS = None
LOCK = threading.Lock()
DROPPED = {"done": False}


def capture_id(body):
    try:
        value = json.loads(body).get("capture_id")
        return value if isinstance(value, str) else "-"
    except Exception:
        return "-"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence the default stderr log
        pass

    def _forward(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        cid = capture_id(body)
        with LOCK, open(ARGS.log, "a") as f:
            f.write(f"{self.command}\t{self.path}\t{cid}\n")
        req = urllib.request.Request(ARGS.upstream + self.path, data=body if self.command == "POST" else None, method=self.command)
        if self.headers.get("Content-Type"):
            req.add_header("Content-Type", self.headers["Content-Type"])
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status, payload, ctype = resp.status, resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as err:
            status, payload, ctype = err.code, err.read(), err.headers.get("Content-Type", "")
        drop = False
        with LOCK:
            if self.command == "POST" and cid == ARGS.drop_id and not DROPPED["done"]:
                DROPPED["done"] = drop = True
        if drop:
            with LOCK, open(ARGS.log, "a") as f:
                f.write(f"DROPPED\t{self.path}\t{cid}\tupstream_status={status}\n")
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return
        self.send_response(status)
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _forward
    do_POST = _forward


def main():
    global ARGS
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--upstream", required=True)
    p.add_argument("--drop-id", required=True)
    p.add_argument("--log", required=True)
    ARGS = p.parse_args()
    ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
