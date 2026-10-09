"""Proxy safety checks using counted loopback upstreams and an owned native server."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest

from proxy import LossProxy


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.committed = False
        self.headers = []

        def forward(method, path, body, headers):
            self.calls.append((method, path))
            self.headers = list(headers.items())
            if method == "POST":
                self.committed = True
            payload = json.dumps({"committed": self.committed}).encode()
            return 201 if method == "POST" else 200, [("Content-Type", "application/json")], payload

        self.proxy = LossProxy(forward)
        self.thread = threading.Thread(target=self.proxy.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.proxy.close()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())

    def request(self, method):
        conn = http.client.HTTPConnection("127.0.0.1", self.proxy.server_address[1], timeout=2)
        try:
            conn.request(method, "/state")
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def raw_request(self, headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.proxy.server_address[1], timeout=5)
        try:
            conn.putrequest("POST", "/state")
            for key, value in headers:
                conn.putheader(key, value)
            conn.endheaders()
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def test_duplicate_headers_preserved(self):
        pairs = [("Idempotency-Key", "a"), ("Idempotency-Key", "b"),
                 ("Origin", "http://a"), ("Origin", "http://b")]
        self.assertEqual(self.raw_request(pairs), 201)
        self.assertEqual([p for p in self.headers if p[0] in {"Idempotency-Key", "Origin"}], pairs)

    def test_real_upstream_receives_duplicates_and_single_framing(self):
        observed = []

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                observed.append(list(self.headers.raw_items()))
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(201)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()

        def forward(method, path, body, headers):
            conn = http.client.HTTPConnection("127.0.0.1", upstream.server_address[1], timeout=2)
            try:
                conn.request(method, path, body=body, headers=headers)
                response = conn.getresponse()
                return response.status, response.getheaders(), response.read()
            finally:
                conn.close()

        self.proxy.forward = forward
        try:
            pairs = [("Idempotency-Key", "a"), ("Idempotency-Key", "b"),
                     ("Origin", "http://a"), ("Origin", "http://b")]
            self.assertEqual(self.raw_request(pairs + [("Content-Length", "0")]), 201)
            self.assertEqual([p for p in observed[0] if p[0] in {"Idempotency-Key", "Origin"}], pairs)
            self.assertEqual([v for k, v in observed[0] if k.lower() == "content-length"], ["0"])
            self.assertFalse(any(k.lower() == "transfer-encoding" for k, _ in observed[0]))
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def test_ambiguous_framing_never_forwarded(self):
        for headers in [[("Content-Length", "0"), ("Content-Length", "0")],
                        [("Transfer-Encoding", "chunked")],
                        [("Content-Length", "0"), ("Transfer-Encoding", "chunked")],
                        [("Content-Length", "-1")]]:
            with self.subTest(headers=headers):
                self.assertEqual(self.raw_request(headers), 400)
        self.assertEqual(self.calls, [])

    def test_connection_nominated_headers_removed(self):
        self.assertEqual(self.raw_request([("Connection", "X-Hop"), ("X-Hop", "gone"),
                                          ("Content-Length", "0")]), 201)
        self.assertFalse(any(k.lower() in {"connection", "x-hop", "content-length", "transfer-encoding"}
                             for k, _ in self.headers))

    def test_never_forwarded(self):
        job = self.proxy.arm("never", "POST", "/state")
        with self.assertRaises(http.client.RemoteDisconnected):
            self.request("POST")
        self.assertTrue(job["done"].wait(2))
        self.assertEqual(self.calls, [])
        self.assertFalse(job["forwarded"])
        self.assertEqual(self.request("GET"), (200, {"committed": False}))

    def test_drop_only_after_upstream_commits(self):
        job = self.proxy.arm("commit-drop", "POST", "/state")
        with self.assertRaises(http.client.RemoteDisconnected):
            self.request("POST")
        self.assertTrue(job["done"].wait(2))
        self.assertEqual(self.calls, [("POST", "/state")])
        self.assertEqual(job["upstream_status"], 201)
        self.assertTrue(job["upstream_body"]["committed"])
        self.assertEqual(self.request("GET"), (200, {"committed": True}))

    def test_get_completes_before_original_delayed_post(self):
        job = self.proxy.arm("delay-drop", "POST", "/state")
        with self.assertRaises(http.client.RemoteDisconnected):
            self.request("POST")
        self.assertEqual(self.request("GET"), (200, {"committed": False}))
        self.assertEqual(self.calls, [("GET", "/state")])
        self.assertFalse(job["forwarded"])
        job["release"].set()
        self.assertTrue(job["done"].wait(2))
        self.assertEqual(self.calls, [("GET", "/state"), ("POST", "/state")])
        self.assertEqual(self.request("GET"), (200, {"committed": True}))

    def test_second_job_refused_while_first_pending(self):
        job = self.proxy.arm("delay-drop", "POST", "/state")
        with self.assertRaises(http.client.RemoteDisconnected):
            self.request("POST")
        with self.assertRaises(ValueError):
            self.proxy.arm("never", "POST", "/state")
        job["release"].set()
        self.assertTrue(job["done"].wait(2))

    def test_cleanup_cancels_a_job_never_received(self):
        job = self.proxy.arm("never", "POST", "/unused")
        # This test exercises cancellation before receipt; tearDown repeats close safely.
        self.proxy.close()
        self.assertTrue(job["done"].is_set())
        self.assertFalse(job["forwarded"])
        self.assertEqual(job["error"], "cancelled before receipt")


class ServerHeaderTests(unittest.TestCase):
    def test_duplicates_reach_owned_server_and_leave_data_unchanged(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "flh026"))
        from run import Harness, snapshot
        from reproduce import Investigation
        harness = Harness("native")
        investigation = None
        try:
            harness.prepare()
            harness.start()
            investigation = Investigation(harness)
            seen = []
            original = investigation.proxy.forward

            def forward(method, path, body, headers):
                seen.append(list(headers.items()))
                return original(method, path, body, headers)

            investigation.proxy.forward = forward
            for prefix in ("", "/api"):
                spec = investigation.fixture("distinct", prefix)
                probes = [("Idempotency-Key", ["11111111-1111-4111-8111-111111111111"] * 2, 400),
                          ("Origin", [f"http://127.0.0.1:{investigation.port}"] * 2, 403)]
                for name, values, expected in probes:
                    before, calls = snapshot(harness.active / "app.db"), harness.calls()
                    conn = http.client.HTTPConnection("127.0.0.1", investigation.port, timeout=5)
                    body = json.dumps(spec["body"]).encode()
                    try:
                        conn.putrequest("POST", spec["path"])
                        conn.putheader("Content-Type", "application/json")
                        conn.putheader("Content-Length", str(len(body)))
                        for value in values:
                            conn.putheader(name, value)
                        conn.endheaders(body)
                        response = conn.getresponse()
                        response.read()
                        self.assertEqual(response.status, expected)
                    finally:
                        conn.close()
                    self.assertEqual([v for k, v in seen[-1] if k.lower() == name.lower()], values)
                    self.assertEqual(snapshot(harness.active / "app.db"), before)
                    self.assertEqual(harness.calls(), calls)
        finally:
            try:
                if investigation:
                    investigation.proxy.close()
                    investigation.thread.join(timeout=3)
                    self.assertFalse(investigation.thread.is_alive())
            finally:
                self.assertEqual(harness.cleanup(), [])


if __name__ == "__main__":
    unittest.main()
