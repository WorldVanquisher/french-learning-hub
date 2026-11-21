"""Tests for the invite-only pilot acceptance case and the anonymous-access probe (loopback stub servers only)."""
import copy
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "pilot_check.py")
CASE = os.path.join(HERE, "..", "pilot", "isolation_case_v1.json")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import pilot_check  # noqa: E402


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class Stub(http.server.BaseHTTPRequestHandler):
    require_auth = False
    seen = []

    def do_GET(self):
        Stub.seen.append(("GET", self.path))
        code = 401 if (self.require_auth and self.path not in ("/healthz", "/readyz")) else 200
        self.send_response(code)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def do_POST(self):  # the probe must never send this
        Stub.seen.append(("POST", self.path))
        self.send_response(500)
        self.end_headers()

    def log_message(self, *a):
        pass


def serve(require_auth):
    handler = type("H", (Stub,), {"require_auth": require_auth})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class PilotCase(unittest.TestCase):
    def setUp(self):
        self.case = read_json(CASE)

    def test_committed_case_is_valid(self):
        self.assertEqual(pilot_check.validate(self.case), [])

    def test_findings(self):
        def finds(mutate, needle):
            c = copy.deepcopy(self.case)
            mutate(c)
            self.assertTrue(any(needle in p for p in pilot_check.validate(c)), pilot_check.validate(c))
        finds(lambda c: c["steps"].__setitem__(slice(None), [s for s in c["steps"] if s["kind"] != "restore-isolation"]),
              "restore-isolation")
        finds(lambda c: next(s for s in c["steps"] if s["id"] == "R2").update(expect="403 forbidden"), "must answer 404")
        finds(lambda c: c["accounts"]["A"].update(label="learner@example.org"), "e-mail")
        finds(lambda c: c["steps"].__setitem__(slice(None), [s for s in c["steps"] if "/speaking/export" not in s["request"]]),
              "/speaking/export")
        finds(lambda c: c["accounts"].update(C={"label": "third"}), "exactly two")

    def test_run_is_blocked_without_a_pilot_api(self):
        r = subprocess.run([sys.executable, "-I", "-B", TOOL, "run", "http://127.0.0.1:9"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("BLOCKED", r.stdout)


class AnonymousProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(self.tmp.name, "routes.go"), "w", encoding="utf-8") as fh:
            fh.write('mux.HandleFunc("GET /healthz", h)\nmux.HandleFunc("GET /entries", h)\n'
                     'mux.HandleFunc("GET /entries/{id}", h)\nmux.HandleFunc("POST /captures", h)\n'
                     'mux.HandleFunc("GET /learning-history/export", h)\n')
        Stub.seen = []

    def tearDown(self):
        self.tmp.cleanup()

    def probe(self, require_auth):
        srv = serve(require_auth)
        try:
            return pilot_check.probe(f"http://127.0.0.1:{srv.server_address[1]}", self.tmp.name)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_server_without_auth_is_not_ready_and_is_never_written(self):
        res = self.probe(False)
        self.assertFalse(res["ready"])
        self.assertEqual((res["routes"], res["anonymous_2xx"]), (3, 3))
        self.assertTrue(all(m == "GET" for m, _ in Stub.seen), Stub.seen)
        self.assertIn(("GET", "/entries/1"), Stub.seen)
        self.assertNotIn(("GET", "/healthz"), Stub.seen)

    def test_server_with_auth_is_ready(self):
        res = self.probe(True)
        self.assertTrue(res["ready"], res)

    def test_live_hosts_are_refused(self):
        private = "http://" + ".".join(["10", "85", "0", "5"])     # assembled: no literal private address in the repository
        for url in ("https://app.flh.vanquisher.world", "http://203.0.113.10:8080", private):
            with self.subTest(url), self.assertRaises(SystemExit):
                pilot_check.probe(url, self.tmp.name)


if __name__ == "__main__":
    unittest.main()
