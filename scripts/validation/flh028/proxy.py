"""One-shot loss/delay proxy, controlled in process; no dependencies or retries."""
import http.client
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class HeaderPairs:
    """HTTPConnection iterates names and calls items(); retain every raw pair."""
    def __init__(self, pairs):
        self.pairs = tuple(pairs)

    def __iter__(self):
        return (key for key, _ in self.pairs)

    def items(self):
        return iter(self.pairs)

    def keys(self):
        return list(self)


class LossProxy(ThreadingHTTPServer):
    def __init__(self, forward):
        # forward is an ownership-checking callback, never a configurable URL.
        super().__init__(("127.0.0.1", 0), Handler)
        self.forward = forward
        self.lock = threading.Lock()
        self.pending = None
        self.jobs = []

    def arm(self, mode, method, path):
        if mode not in {"never", "commit-drop", "delay-drop"}:
            raise ValueError("unknown proxy mode")
        with self.lock:
            if self.pending is not None or any(not j["done"].is_set() for j in self.jobs):
                raise ValueError("previous proxy job is still pending")
            job = {"mode": mode, "method": method, "path": path, "received": threading.Event(),
                   "release": threading.Event(), "done": threading.Event(), "forwarded": False,
                   "upstream_status": None, "upstream_body": None, "events": [], "error": None}
            self.pending = job
            self.jobs.append(job)
            return job

    def close(self):
        with self.lock:
            if self.pending is not None:
                self.pending["error"] = "cancelled before receipt"
                self.pending["done"].set()
                self.pending = None
        for job in self.jobs:
            job["release"].set()
        failures = []
        for job in self.jobs:
            if not job["done"].wait(10):
                failures.append("proxy handler did not terminate")
        self.shutdown()
        self.server_close()
        if failures:
            raise RuntimeError("; ".join(failures))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def disconnect(self):
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()

    def handle_request(self):
        lengths = self.headers.get_all("Content-Length", [])
        # This fixture supports fixed-length bodies only. Reject ambiguous framing
        # before consuming a body or invoking the ownership-checking callback.
        if (self.headers.get_all("Transfer-Encoding") or len(lengths) > 1
                or (lengths and (not lengths[0].isascii() or not lengths[0].isdigit()))):
            self.send_error(400, "unsupported request framing")
            self.close_connection = True
            return
        body = self.rfile.read(int(lengths[0]) if lengths else 0)
        excluded = {"connection", "content-length", "transfer-encoding", "keep-alive",
                    "proxy-authenticate", "proxy-authorization", "te", "trailer", "upgrade"}
        for value in self.headers.get_all("Connection", []):
            excluded.update(token.strip().lower() for token in value.split(","))
        headers = HeaderPairs((key, value) for key, value in self.headers.raw_items()
                              if key.lower() not in excluded)
        with self.server.lock:
            job = self.server.pending
            if job is not None and (job["method"], job["path"]) == (self.command, self.path):
                self.server.pending = None
            else:
                job = None
        if job:
            job["events"].append({"event": "received", "time_ns": time.monotonic_ns()})
            job["received"].set()
        try:
            if job and job["mode"] == "never":
                self.disconnect()
                return
            if job and job["mode"] == "delay-drop":
                # Client already sees loss, but the original request remains pending.
                self.disconnect()
                if not job["release"].wait(10):
                    raise RuntimeError("delay gate was never released")
            if job:
                job["forwarded"] = True
                job["events"].append({"event": "forwarding", "time_ns": time.monotonic_ns()})
            status, response_headers, payload = self.server.forward(self.command, self.path, body, headers)
            if job:
                job["upstream_status"] = status
                job["upstream_body"] = json.loads(payload)
                job["events"].append({"event": "upstream-response", "time_ns": time.monotonic_ns()})
                self.disconnect()  # Never send status, headers or body downstream.
                return
            self.send_response(status)
            for key, value in response_headers:
                if key.lower() not in {"connection", "content-length", "transfer-encoding", "server", "date"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except BaseException as exc:
            if job:
                job["error"] = f"{type(exc).__name__}: {exc}"
            self.disconnect()
        finally:
            if job:
                job["done"].set()

    do_GET = handle_request
    do_POST = handle_request
    do_PUT = handle_request
    do_DELETE = handle_request


def public_job(job):
    return {key: value for key, value in job.items()
            if key not in {"received", "release", "done"}}
