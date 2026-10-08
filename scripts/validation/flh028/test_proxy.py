"""Meaningful proxy mechanism tests using a counted local upstream substitute."""
import http.client
import json
import threading
import unittest

from proxy import LossProxy


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.committed = False

        def forward(method, path, body, headers):
            self.calls.append((method, path))
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


if __name__ == "__main__":
    unittest.main()
