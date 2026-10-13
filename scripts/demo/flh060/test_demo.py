"""Offline tests for the FLH-060 demo harness (loopback stubs only; no model,
no real endpoint, no Docker)."""

import json
import socket
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import catalog  # noqa: E402
import demo  # noqa: E402
import gateway  # noqa: E402

QUERY = '{"representation":"concept_search_query_v2","type":"query","text":"x"}'
DOC = ('{"representation":"concept_embedding_text_v1","type":"concept","target":"t","pedagogical_intent":"grammar",'
       '"scope":"","identity_features":[]}')
UNITQ = ('{"representation":"concept_embedding_text_v1","type":"query","canonical":"c","statement":"s","example":null,'
         '"candidate_target":"t","pedagogical_intent":"grammar","scope":"","identity_features":[]}')


class Upstream(BaseHTTPRequestHandler):
    received: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Upstream.received.append((self.path, body))
        n = len(json.loads(body)["input"])
        data = json.dumps({"data": [{"index": i, "embedding": [1.0]} for i in range(n)]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        Upstream.received = []
        self.up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=self.up.serve_forever, daemon=True).start()
        self.servers = [self.up]

    def tearDown(self):
        for s in self.servers:
            s.shutdown()
            s.server_close()
        self.tmp.cleanup()

    def start(self, mode="real", max_posts=3, max_positions=4, upstream=None):
        upstream = upstream or f"http://127.0.0.1:{self.up.server_address[1]}/v1"
        (self.work / "demo.json").write_text(json.dumps({"mode": mode, "embedding": {"upstream_base_url": upstream, "model": "m"}}))
        (self.work / "gateway").mkdir(exist_ok=True)
        budget = self.work / "gateway" / "budget.json"
        if mode == "real" and not budget.exists():
            budget.write_text(json.dumps({"max_posts": max_posts, "max_positions": max_positions,
                                          "used_posts": 0, "used_positions": 0}))

        class H(gateway.Handler):
            pass
        H.gw = gateway.Gateway(self.work)
        H.log_message = lambda *a: None
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    def state(self, base):
        with urllib.request.urlopen(base + "/gateway/state") as r:
            return json.loads(r.read())

    def test_classify_by_declared_representation_only(self):
        self.assertEqual(gateway.classify(QUERY), "search_query")
        self.assertEqual(gateway.classify(DOC), "concept_document")
        self.assertEqual(gateway.classify(UNITQ), "unit_query")
        for raw in ("plain words", "[1]", '{"representation":"x","type":"query"}', ""):
            self.assertEqual(gateway.classify(raw), "other")

    def test_counts_kinds_and_forwards_bytes_unchanged(self):
        base = self.start(mode="fake")
        self.assertEqual(post(base + "/v1/embeddings", {"model": "m", "input": [DOC, DOC]})[0], 200)
        self.assertEqual(post(base + "/v1/embeddings", {"model": "m", "input": [QUERY]})[0], 200)
        st = self.state(base)
        self.assertEqual((st["posts_forwarded"], st["positions_forwarded"]), (2, 3))
        self.assertEqual(st["positions_by_kind"]["concept_document"], 2)
        self.assertEqual(st["positions_by_kind"]["search_query"], 1)
        self.assertEqual(st["posts_by_kind"], {"index": 1, "search": 1, "mixed": 0})
        self.assertEqual([p for p, _ in Upstream.received], ["/v1/embeddings", "/v1/embeddings"])
        self.assertEqual(json.loads(Upstream.received[1][1]), {"model": "m", "input": [QUERY]})

    def test_budget_is_charged_before_sending_and_refuses_without_contacting_upstream(self):
        base = self.start(max_posts=2, max_positions=3)
        self.assertEqual(post(base + "/v1/embeddings", {"model": "m", "input": [DOC, DOC]})[0], 200)
        status, body = post(base + "/v1/embeddings", {"model": "m", "input": [DOC, DOC]})  # 4 > 3 positions
        self.assertEqual((status, body["error"]["type"]), (429, "budget_exhausted"))
        self.assertEqual(len(Upstream.received), 1)
        self.assertEqual(post(base + "/v1/embeddings", {"model": "m", "input": [QUERY]})[0], 200)
        status, _ = post(base + "/v1/embeddings", {"model": "m", "input": [QUERY]})  # 3 > 2 posts
        self.assertEqual(status, 429)
        self.assertEqual(len(Upstream.received), 2)
        b = json.loads((self.work / "gateway" / "budget.json").read_text())
        self.assertEqual((b["used_posts"], b["used_positions"]), (2, 3))
        self.assertEqual(self.state(base)["refused"]["budget"], 2)

    def test_unreachable_upstream_is_charged_and_not_retried(self):
        base = self.start(upstream=f"http://127.0.0.1:{free_port()}/v1")
        status, body = post(base + "/v1/embeddings", {"model": "m", "input": [QUERY]})
        self.assertEqual((status, body["error"]["type"]), (502, "upstream_unreachable"))
        b = json.loads((self.work / "gateway" / "budget.json").read_text())
        self.assertEqual(b["used_posts"], 1)
        self.assertEqual(self.state(base)["upstream_unreachable"], 1)

    def test_offline_switch_and_wrong_model_never_reach_upstream(self):
        base = self.start()
        self.assertEqual(post(base + "/gateway/offline", {"offline": True})[0], 200)
        status, body = post(base + "/v1/embeddings", {"model": "m", "input": [QUERY]})
        self.assertEqual((status, body["error"]["type"]), (503, "demo_offline"))
        post(base + "/gateway/offline", {"offline": False})
        status, body = post(base + "/v1/embeddings", {"model": "other", "input": [QUERY]})
        self.assertEqual((status, body["error"]["type"]), (400, "unknown_model"))
        self.assertEqual(post(base + "/v1/embeddings", {"model": "m", "input": "not a list"})[0], 400)
        self.assertEqual(Upstream.received, [])
        b = json.loads((self.work / "gateway" / "budget.json").read_text())
        self.assertEqual(b["used_posts"], 0)
        st = self.state(base)
        self.assertEqual((st["refused"]["offline"], st["refused"]["model"], st["refused"]["malformed"]), (1, 1, 1))

    def test_counters_persist_across_gateway_restarts(self):
        base = self.start(mode="fake")
        post(base + "/v1/embeddings", {"model": "m", "input": [QUERY]})
        post(base + "/gateway/offline", {"offline": True})
        base2 = self.start(mode="fake")
        st = self.state(base2)
        self.assertEqual((st["posts_forwarded"], st["offline"]), (1, True))

    def test_real_mode_requires_a_budget_file(self):
        (self.work / "demo.json").write_text(json.dumps({"mode": "real", "embedding": {"upstream_base_url": "http://127.0.0.1:1/v1", "model": "m"}}))
        with self.assertRaises(SystemExit):
            gateway.Gateway(self.work)


class HarnessTests(unittest.TestCase):
    def run_main(self, *argv):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = demo.main(list(argv))
        return code, err.getvalue()

    def test_setup_refusals_happen_before_anything_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_main("setup", "relative/dir", "--mode", "fake")[0], 2)
            self.assertEqual(self.run_main("setup", str(demo.REPO / "x-demo"), "--mode", "fake")[0], 2)
            self.assertFalse((demo.REPO / "x-demo").exists())
            (Path(tmp) / "keep").write_text("1")
            self.assertEqual(self.run_main("setup", tmp, "--mode", "fake")[0], 2)
            new = Path(tmp) / "new"
            code, err = self.run_main("setup", str(new), "--mode", "real", "--embedding-model", "m")
            self.assertEqual(code, 2)
            self.assertIn("real mode needs", err)
            code, err = self.run_main("setup", str(new), "--mode", "fake", "--embedding-base-url", "http://127.0.0.1:1/v1")
            self.assertEqual(code, 2)
            self.assertFalse(new.exists())

    def test_commands_refuse_non_demo_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            for cmd in ("start", "stop", "status", "cleanup", "walkthrough"):
                self.assertEqual(self.run_main(cmd, tmp)[0], 2, cmd)
            self.assertTrue(Path(tmp).exists())
            self.assertEqual(self.run_main("cleanup", str(Path(tmp) / "absent"))[0], 0)

    def test_child_environment_never_inherits_provider_settings(self):
        import os
        old = dict(os.environ)
        os.environ.update({"OPENAI_API_KEY": "sk-should-not-leak", "EMBEDDING_API_KEY": "x", "QDRANT_API_KEY": "y",
                           "EMBEDDING_BASE_URL": "http://elsewhere/v1"})
        try:
            cfg = {"embedding": {"model": "m", "dimensions": 768}, "ports": {"server": 1, "gateway": 2, "qdrant": 3}}
            env = demo.child_env(cfg, Path("/w"), demo.app_env(cfg, Path("/w")))
        finally:
            os.environ.clear()
            os.environ.update(old)
        for k in ("OPENAI_API_KEY", "EMBEDDING_API_KEY", "QDRANT_API_KEY"):
            self.assertNotIn(k, env)
        self.assertEqual(env["EMBEDDING_BASE_URL"], "http://127.0.0.1:2/v1")
        self.assertEqual(env["LISTEN_HOST"], "127.0.0.1")
        self.assertEqual(env["EMBEDDING_MODEL"], env["EMBEDDING_MODEL_ID"])

    def test_role_matching_needs_this_directory(self):
        cfg = {"qdrant": {"kind": "docker"}}
        w = Path("/tmp/demo-a")
        self.assertTrue(demo.role_matches("server", w, cfg, "/tmp/demo-a/flh034/server -web-dir x"))
        self.assertFalse(demo.role_matches("server", w, cfg, "/tmp/demo-b/flh034/server"))
        gw = f"python3 -B {demo.HERE / 'gateway.py'} 18961"
        self.assertTrue(demo.role_matches("gateway", w, cfg, gw + " /tmp/demo-a"))
        self.assertFalse(demo.role_matches("gateway", w, cfg, gw + " /tmp/demo-a2"))
        self.assertFalse(demo.role_matches("qdrant", w, cfg, "/usr/bin/qdrant --config-path /tmp/demo-a/qdrant.yaml"))

    def test_helpers(self):
        self.assertEqual(demo.service_root("http://100.1.2.3:8765/v1"), "http://100.1.2.3:8765")
        self.assertEqual(demo.service_root("http://127.0.0.1:9/v1/"), "http://127.0.0.1:9")
        self.assertEqual(demo.planned_positions(15), (2 + len(catalog.SEARCHES) + 1, 15 + len(catalog.SEARCHES) + 1))
        b = {"posts_forwarded": 1, "positions_forwarded": 2, "positions_by_kind": {"search_query": 1, "concept_document": 1},
             "refused": {"budget": 0}}
        a = {"posts_forwarded": 3, "positions_forwarded": 5, "positions_by_kind": {"search_query": 2, "concept_document": 3},
             "refused": {"budget": 1}}
        self.assertEqual(demo.delta(b, a), {"posts": 2, "positions": 3, "search_query_positions": 1,
                                            "concept_document_positions": 2, "refused_budget": 1})
        self.assertEqual(demo.counter_delta({"n": 1, "r": {"q": 1}}, {"n": 4, "r": {"q": 3, "p": 2}, "s": "x"}),
                         {"n": 3, "r": {"q": 2, "p": 2}})


class CatalogTests(unittest.TestCase):
    def test_catalog_shape(self):
        targets = [t for t, *_ in catalog.ADDITIONS]
        self.assertEqual(len(targets), len(set(targets)))
        self.assertEqual(len(targets), 8)
        for target, intent, scope, features in catalog.ADDITIONS:
            self.assertEqual(target, target.lower())  # identity is stored normalized
            self.assertTrue(any("example" in k for k in features))
        for q in catalog.KEYWORD_SEARCHES:
            self.assertLessEqual(len(q.split()), 8)
        body = catalog.concept_body(*catalog.ADDITIONS[0])
        self.assertEqual(set(body), {"identity", "seed_unit_id", "link_seed_as_same"})
        self.assertIsNone(body["seed_unit_id"])


if __name__ == "__main__":
    unittest.main()
