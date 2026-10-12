"""Service behaviour over real loopback HTTP with an injected fake encoder.
Mechanics only: no torch, CUDA, model or quality is involved."""

import http.client
import json
import logging
import math
import socket
import threading
import time
import unittest
from pathlib import Path

from flh_e5 import __main__ as cli
from flh_e5 import contract
from flh_e5.service import READY, EmbeddingHTTPServer, EmbeddingService, Limits, validate_bind_host

from .fakes import FakeEncoder, fake_vector

GOLDEN = json.loads((Path(__file__).resolve().parent / "golden_inputs.json").read_text(encoding="utf-8"))
BY_NAME = {c["name"]: c for c in GOLDEN["accepted"]}
SEARCH, UNIT, CONCEPT = BY_NAME["search_query"]["input"], BY_NAME["unit_query"]["input"], BY_NAME["concept_document"]["input"]
DEPLOYMENT = "fake-deployment-for-tests"


def make_service(encoder=None, limits=None):
    enc = encoder or FakeEncoder()
    svc = EmbeddingService(lambda: enc, lambda e: {"deployment_id": DEPLOYMENT, "fake": True}, limits or Limits())
    return svc, enc


class Running:
    """A loaded service on 127.0.0.1:<ephemeral>."""

    def __init__(self, test, encoder=None, limits=None, load=True):
        self.svc, self.enc = make_service(encoder, limits)
        self.server = EmbeddingHTTPServer(("127.0.0.1", 0), self.svc)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        test.addCleanup(self.stop)
        if load:
            self.svc.load()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        resp = conn.getresponse()
        payload = json.loads(resp.read() or b"{}")
        conn.close()
        return resp.status, payload

    def embed(self, inputs, model=DEPLOYMENT, **kw):
        return self.request("POST", "/v1/embeddings", {"model": model, "input": inputs}, **kw)


def assert_unit(test, v):
    test.assertEqual(len(v), 768)
    test.assertTrue(all(math.isfinite(x) for x in v))
    test.assertAlmostEqual(math.sqrt(sum(x * x for x in v)), 1.0, places=6)


class Embeddings(unittest.TestCase):
    def test_mixed_batch_order_indices_and_prefixes(self):
        s = Running(self)
        inputs = [SEARCH, UNIT, CONCEPT, CONCEPT, SEARCH]
        status, body = s.embed(inputs)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["model"], DEPLOYMENT)
        self.assertEqual([d["index"] for d in body["data"]], list(range(5)))
        expected = [contract.adapt(t).model_text for t in inputs]
        self.assertEqual(s.enc.batches[1:], [expected])  # [0] is warmup; one microbatch, prefixed once, in order
        for item, text in zip(body["data"], expected):
            assert_unit(self, item["embedding"])
            self.assertEqual(item["embedding"], fake_vector(text))
        self.assertTrue(expected[0].startswith("query: {") and expected[1].startswith("query: {") and expected[2].startswith("passage: {"))

    def test_singleton_batches_take_the_role_of_their_content(self):
        s = Running(self)
        for text, prefix in ((CONCEPT, "passage: "), (SEARCH, "query: "), (UNIT, "query: ")):
            status, body = s.embed([text])
            self.assertEqual(status, 200)
            self.assertEqual(s.enc.batches[-1], [prefix + text])
            self.assertEqual(body["data"][0]["index"], 0)

    def test_microbatches_preserve_order(self):
        s = Running(self, limits=Limits(microbatch=2))
        inputs = [CONCEPT.replace("passé composé avec être", f"c{i}", 1) for i in range(5)]
        status, body = s.embed(inputs)
        self.assertEqual(status, 200)
        self.assertEqual([len(b) for b in s.enc.batches[1:]], [2, 2, 1])  # [0] is warmup
        self.assertEqual([d["embedding"] for d in body["data"]], [fake_vector("passage: " + t) for t in inputs])

    def test_overlength_is_rejected_not_truncated(self):
        enc = FakeEncoder(tokens=lambda t: 513 if "LONG" in t else (512 if "EDGE" in t else 5))
        s = Running(self, encoder=enc)
        long_ = SEARCH.replace("subjonctif", "LONG")
        status, body = s.embed([SEARCH, long_])
        self.assertEqual((status, body["error"]["type"]), (422, "input_too_long"))
        self.assertIn("input 1 has 513 tokens", body["error"]["message"])
        self.assertNotIn("LONG", body["error"]["message"])
        status, _ = s.embed([SEARCH.replace("subjonctif", "EDGE")])
        self.assertEqual(status, 200)
        c = s.svc.metrics()["counters"]
        self.assertEqual((c["overlength_inputs"], c["truncations"], c["max_tokens_seen"]), (1, 0, 513))
        self.assertEqual(len(enc.batches), 2)  # warmup + the 512-token request only


class Rejections(unittest.TestCase):
    def test_request_shape_and_limits(self):
        s = Running(self)
        big = '{"representation":"concept_search_query_v2","type":"query","text":"' + "x" * 4100 + '"}'
        cases = [
            ({"model": "other", "input": [SEARCH]}, 400, "unknown_model"),
            ({"model": DEPLOYMENT, "input": [SEARCH], "encoding_format": "float"}, 400, "invalid_request"),
            ({"model": DEPLOYMENT, "input": []}, 400, "invalid_request"),
            ({"model": DEPLOYMENT, "input": SEARCH}, 400, "invalid_request"),
            ({"model": DEPLOYMENT, "input": [SEARCH, 5]}, 400, "invalid_request"),
            ({"model": DEPLOYMENT, "input": [SEARCH] * 33}, 413, "too_many_inputs"),
            ({"model": DEPLOYMENT, "input": [big]}, 413, "input_too_large"),
            ({"model": DEPLOYMENT, "input": [SEARCH, "raw learner text"]}, 422, "invalid_input"),
            ({"model": DEPLOYMENT, "input": ["query: " + SEARCH]}, 422, "invalid_input"),
        ]
        for body, status, kind in cases:
            with self.subTest(kind=kind, status=status):
                got, payload = s.request("POST", "/v1/embeddings", body)
                self.assertEqual((got, payload["error"]["type"]), (status, kind))
                self.assertNotIn("raw learner text", json.dumps(payload))
        for raw, status, kind in ((b"{not json", 400, "invalid_request"), (b'{"model":"a","model":"b","input":[]}', 400, "invalid_request"),
                                  (b'{"model":NaN,"input":[]}', 400, "invalid_request"), (b"\xff\xfe", 400, "invalid_request")):
            with self.subTest(raw=raw):
                got, payload = s.request("POST", "/v1/embeddings", raw=raw)
                self.assertEqual((got, payload["error"]["type"]), (status, kind))
        self.assertEqual(s.enc.batches[1:], [])  # nothing reached the encoder
        self.assertEqual(s.request("GET", "/nope")[0], 404)
        self.assertEqual(s.request("POST", "/v1/other", {"model": DEPLOYMENT, "input": [SEARCH]})[0], 404)
        self.assertEqual(s.request("PUT", "/v1/embeddings", raw=b"{}")[0], 405)

    def test_body_limit_and_content_length(self):
        s = Running(self, limits=Limits(max_body_bytes=2048))
        status, payload = s.embed([SEARCH] * 30)
        self.assertEqual((status, payload["error"]["type"]), (413, "request_too_large"))
        sock = socket.create_connection(("127.0.0.1", s.port), timeout=5)
        sock.sendall(b"POST /v1/embeddings HTTP/1.0\r\nContent-Type: application/json\r\n\r\n{}")
        reply = sock.recv(4096).decode()
        sock.close()
        self.assertIn(" 411 ", reply.splitlines()[0])

    def test_oom_and_encoder_errors_fail_without_retry(self):
        for fail, status, kind in (("oom", 503, "gpu_out_of_memory"), ("error", 500, "encoder_error"),
                                   ("nan", 500, "invalid_model_output"), ("unnormalized", 500, "invalid_model_output"),
                                   ("short", 500, "invalid_model_output"), ("count", 500, "invalid_model_output")):
            with self.subTest(fail):
                enc = FakeEncoder()
                s = Running(self, encoder=enc)
                enc.fail = fail  # after a clean warmup
                got, payload = s.embed([SEARCH, CONCEPT])
                self.assertEqual((got, payload["error"]["type"]), (status, kind))
                self.assertEqual(len(enc.batches), 2)  # warmup + exactly one attempt
                self.assertNotIn("subjonctif", json.dumps(payload))
                enc.fail = None
                self.assertEqual(s.embed([SEARCH])[0], 200)  # the service stays up


class Admission(unittest.TestCase):
    def _blocked(self, limits):
        gate = threading.Event()
        enc = FakeEncoder()
        s = Running(self, encoder=enc, limits=limits)
        enc.gate, enc.entered = gate, threading.Event()
        results = []
        t = threading.Thread(target=lambda: results.append(s.embed([SEARCH])))
        t.start()
        self.assertTrue(enc.entered.wait(5))
        self.addCleanup(lambda: (gate.set(), t.join(10)))
        return s, gate, t, results

    def test_queue_full_is_rejected_immediately(self):
        s, gate, t, results = self._blocked(Limits(max_queue=1))
        started = time.monotonic()
        status, payload = s.embed([SEARCH])
        self.assertEqual((status, payload["error"]["type"]), (503, "overloaded"))
        self.assertLess(time.monotonic() - started, 2)
        gate.set()
        t.join(10)
        self.assertEqual(results[0][0], 200)

    def test_waiting_for_the_gpu_times_out(self):
        s, gate, t, _ = self._blocked(Limits(max_queue=2, queue_timeout_s=0.3))
        status, payload = s.embed([SEARCH])
        self.assertEqual((status, payload["error"]["type"]), (503, "overloaded"))
        self.assertIn("timed out", payload["error"]["message"])

    def test_connection_limit(self):
        s, gate, t, _ = self._blocked(Limits(max_connections=1))
        status, payload = s.embed([SEARCH])
        self.assertEqual((status, payload["error"]["type"]), (503, "overloaded"))
        gate.set()
        t.join(10)
        self.assertEqual(s.svc.metrics()["counters"]["rejected"].get("too_many_connections"), 1)


class Readiness(unittest.TestCase):
    def test_not_ready_until_loaded_and_warmed(self):
        gate = threading.Event()
        enc = FakeEncoder(gate=gate)
        s = Running(self, encoder=enc, load=False)
        self.assertEqual(s.request("GET", "/readyz"), (503, {"ready": False, "state": "starting", "deployment_id": None}))
        loader = threading.Thread(target=s.svc.load)
        loader.start()
        self.assertTrue(enc.entered.wait(5))  # inside warmup
        status, body = s.request("GET", "/readyz")
        self.assertEqual((status, body["state"]), (503, "warming"))
        self.assertEqual(s.embed([SEARCH])[1]["error"]["type"], "not_ready")
        self.assertEqual(s.request("GET", "/healthz")[0], 200)
        gate.set()
        loader.join(10)
        enc.gate = None
        self.assertEqual(s.request("GET", "/readyz"), (200, {"ready": True, "state": "ready", "deployment_id": DEPLOYMENT}))
        self.assertEqual(s.request("GET", "/manifest")[1]["deployment_id"], DEPLOYMENT)
        self.assertEqual(s.svc.state, READY)

    def test_failed_load_or_warmup_never_becomes_ready(self):
        def boom():
            raise RuntimeError("CUDA is not available")
        svc = EmbeddingService(boom, lambda e: {}, Limits())
        with self.assertRaises(RuntimeError):
            svc.load()
        self.assertEqual(svc.state, "failed")
        self.assertIn("CUDA is not available", svc.state_detail)
        enc = FakeEncoder(fail="nan")
        svc2, _ = make_service(enc)
        with self.assertRaises(Exception):
            svc2.load()
        self.assertEqual(svc2.state, "failed")


class Observability(unittest.TestCase):
    def test_counters_and_no_text_in_logs(self):
        marker = "MARKER-LEARNER-TEXT"
        with self.assertLogs("flh_e5", level="INFO") as logs:
            s = Running(self)
            secret = SEARCH.replace("subjonctif", marker)
            self.assertEqual(s.embed([secret, CONCEPT])[0], 200)
            self.assertEqual(s.embed([secret])[0], 200)
            self.assertEqual(s.embed(["raw " + marker])[0], 422)
            self.assertEqual(s.embed([secret], headers={"Authorization": "Bearer sk-" + marker})[0], 200)
        self.assertFalse(any(marker in line for line in logs.output), logs.output)
        m = s.svc.metrics()
        c = m["counters"]
        self.assertEqual((c["requests_total"], c["requests_ok"], c["input_positions"]), (4, 3, 4))
        self.assertEqual(c["inputs_by_role"], {"query": 3, "passage": 1})
        self.assertEqual(c["distinct_input_hashes"], 2)
        self.assertEqual(c["rejected"], {"invalid_input": 1})
        self.assertEqual((c["computations"], c["truncations"]), (3, 0))  # request microbatches; warmup is not counted
        self.assertEqual(m["gpu"]["device"], "fake (not a GPU)")
        self.assertNotIn(marker, json.dumps(m))


class Shutdown(unittest.TestCase):
    def test_serve_stops_cleanly_and_releases_the_encoder(self):
        gate = threading.Event()
        enc = FakeEncoder()
        svc, _ = make_service(enc)
        stop, bound = threading.Event(), {}
        codes = []
        runner = threading.Thread(target=lambda: codes.append(cli.serve(svc, "127.0.0.1", 0, stop=stop, on_bound=lambda a: bound.setdefault("port", a[1]))))
        runner.start()
        deadline = time.monotonic() + 5
        while svc.state != READY and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(svc.state, READY)
        port = bound["port"]
        # An in-flight request finishes before the encoder is released.
        enc.gate, enc.entered = gate, threading.Event()
        result = []

        def call():
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("POST", "/v1/embeddings", json.dumps({"model": DEPLOYMENT, "input": [SEARCH]}), {"Content-Type": "application/json"})
            result.append(conn.getresponse().status)
        t = threading.Thread(target=call)
        t.start()
        self.assertTrue(enc.entered.wait(5))
        stop.set()
        time.sleep(0.3)
        self.assertFalse(enc.closed)
        gate.set()
        t.join(10)
        runner.join(15)
        self.assertEqual(result, [200])
        self.assertEqual(codes, [0])
        self.assertTrue(enc.closed)
        self.assertEqual(svc.state, "stopped")
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1).close()

    def test_startup_failure_exits_nonzero_and_closes(self):
        def boom():
            raise RuntimeError("no CUDA")
        svc = EmbeddingService(boom, lambda e: {}, Limits())
        with self.assertLogs("flh_e5", level="ERROR"):
            self.assertEqual(cli.serve(svc, "127.0.0.1", 0), 3)


class Binding(unittest.TestCase):
    def test_bind_addresses(self):
        for ok in ("127.0.0.1", "::1", "192.168.1.20", "10.0.0.5", "172.16.3.4", "fd12:3456::1"):
            self.assertEqual(validate_bind_host(ok), ok)
        for bad in ("0.0.0.0", "::", "8.8.8.8", "169.254.1.1", "100.64.1.1", "localhost", "224.0.0.1", "2001:db8::1"):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    validate_bind_host(bad)

    def test_cli_refuses_public_host_before_loading(self):
        self.assertEqual(cli.main(["serve", "--model-dir", "/nonexistent", "--host", "0.0.0.0"]), 2)
        self.assertEqual(cli.main(["serve", "--model-dir", "/nonexistent", "--max-inputs", "64"]), 2)
        self.assertEqual(cli.main(["verify-files", "--model-dir", "/nonexistent"]), 3)


if __name__ == "__main__":
    unittest.main()
