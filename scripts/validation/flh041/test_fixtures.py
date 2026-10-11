"""Fixture/oracle self-tests; no production or Qdrant acceptance is claimed."""
from concurrent.futures import ThreadPoolExecutor
import copy
import http.client
import json
from pathlib import Path
import socket
import threading
import unittest

from fake_embeddings import FakeEmbeddings, Fault, deterministic_vector, text_digest
from oracles import (CacheKey, assert_bounded_provider, assert_cache, assert_embedding_delta,
                     assert_index, assert_not_complete, assert_read_only, assert_result_ids)

FIXTURE = json.loads((Path(__file__).with_name("fixtures.json")).read_text())


def post(provider, texts, model="fixture-model-a", timeout=2, raw=None):
    port = int(provider.base_url.rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        body = raw if raw is not None else json.dumps({"model": model, "input": texts})
        conn.request("POST", "/embeddings", body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


class FixtureTests(unittest.TestCase):
    def test_vectors_stable_across_instances_and_input_changes(self):
        text = FIXTURE["documents"][0]["text"]
        expected = deterministic_vector(text, "fixture-model-a", 8)
        self.assertEqual(expected, deterministic_vector(text, "fixture-model-a", 8))
        self.assertNotEqual(expected, deterministic_vector(text + " changed", "fixture-model-a", 8))
        self.assertNotEqual(expected, deterministic_vector(text, "fixture-model-b", 8))
        self.assertEqual(len(deterministic_vector(text, "fixture-model-a", 4)), 4)

    def test_batch_indices_duplicate_inputs_counters_and_restart_determinism(self):
        text = FIXTURE["documents"][0]["text"]
        values = []
        for _ in range(2):
            with FakeEmbeddings() as provider:
                provider.register(text, "document")
                provider.arm(1, Fault(kind="reverse"))
                status, body = post(provider, [text, text])
                self.assertEqual(status, 200)
                data = json.loads(body)["data"]
                self.assertEqual([item["index"] for item in data], [1, 0])
                self.assertEqual(data[0]["embedding"], data[1]["embedding"])
                values.append(data)
                self.assertTrue(provider.wait_idle())
                counts = provider.snapshot()
                self.assertEqual(counts["attempted_texts"], {"document": 2})
                self.assertEqual(counts["valid_response_texts"], {"document": 2})
        self.assertEqual(*values)  # Fake reproducibility, not persistent cache reuse.

    def test_all_controlled_faults_count_received_inputs(self):
        for kind in ("status", "malformed", "short", "duplicate-index", "wrong-dimension", "zero", "nonfinite", "disconnect"):
            with self.subTest(kind=kind), FakeEmbeddings() as provider:
                provider.register("doc", "document")
                provider.arm(1, Fault(kind=kind))
                if kind == "disconnect":
                    with self.assertRaises(http.client.RemoteDisconnected):
                        post(provider, ["doc", "doc"])
                else:
                    status, body = post(provider, ["doc", "doc"])
                    self.assertEqual(status, 503 if kind == "status" else 200)
                    if kind == "malformed":
                        with self.assertRaises(json.JSONDecodeError):
                            json.loads(body)
                    elif kind == "status":
                        self.assertEqual(json.loads(body)["error"]["type"], "fixture_failure")
                    else:
                        data = json.loads(body)["data"]
                        if kind == "short":
                            self.assertEqual(len(data), 1)
                        elif kind == "duplicate-index":
                            self.assertEqual(data[0]["index"], data[1]["index"])
                        elif kind == "wrong-dimension":
                            self.assertEqual(len(data[-1]["embedding"]), 9)
                        elif kind == "zero":
                            self.assertFalse(any(data[-1]["embedding"]))
                        else:
                            self.assertIn(b"NaN", body)
                self.assertTrue(provider.wait_idle())
                counts = provider.snapshot()
                self.assertEqual(counts["requests"], 1)
                self.assertEqual(counts["attempted_texts"], {"document": 2})
                self.assertEqual(counts["valid_response_texts"], {})

    def test_fault_on_second_call_preserves_first_success(self):
        with FakeEmbeddings() as provider:
            provider.register("doc", "document")
            provider.arm(2, Fault())
            self.assertEqual(post(provider, ["doc"])[0], 200)
            self.assertEqual(post(provider, ["doc"])[0], 503)
            self.assertTrue(provider.wait_idle())
            counts = provider.snapshot()
            self.assertEqual(counts["attempted_texts"], {"document": 2})
            self.assertEqual(counts["valid_response_texts"], {"document": 1})

    def test_gate_exposes_concurrency_and_releases_deterministically(self):
        gate = threading.Event()
        with FakeEmbeddings() as provider, ThreadPoolExecutor(max_workers=2) as pool:
            provider.arm(1, Fault(kind="none", gate=gate))
            first = pool.submit(post, provider, ["first"])
            try:
                self.assertTrue(provider.wait_received(1))
                second = pool.submit(post, provider, ["second"])
                self.assertEqual(second.result(timeout=2)[0], 200)
                self.assertEqual(provider.snapshot()["max_active"], 2)
            finally:
                gate.set()
            self.assertEqual(first.result(timeout=2)[0], 200)
            self.assertTrue(provider.wait_idle())
            with self.assertRaisesRegex(AssertionError, "concurrency"):
                assert_bounded_provider(provider.snapshot(), max_batch=2)

    def test_gate_timeout_and_client_cancellation(self):
        with FakeEmbeddings(gate_timeout=0.1) as provider:
            provider.arm(1, Fault(kind="none", gate=threading.Event()))
            self.assertEqual(post(provider, ["held"])[0], 504)
            self.assertTrue(provider.wait_idle())
            self.assertEqual(provider.snapshot()["events"][0]["outcome"], "gate-timeout")
        gate = threading.Event()
        with FakeEmbeddings() as provider:
            provider.arm(1, Fault(kind="none", gate=gate))
            with self.assertRaises(TimeoutError):
                post(provider, ["held"], timeout=0.1)
            self.assertEqual(provider.snapshot()["active"], 1)
            gate.set()
            self.assertTrue(provider.wait_idle())
            # TCP write success cannot establish client consumption. Both are
            # valid server-side outcomes after the observed client timeout.
            self.assertIn(provider.snapshot()["events"][0]["outcome"],
                          ("client-disconnected", "valid-response"))

    def test_query_and_document_attribution(self):
        with FakeEmbeddings() as provider:
            provider.register("doc", "document")
            provider.register("query", "query")
            before = provider.snapshot()
            post(provider, ["doc", "query"])
            self.assertTrue(provider.wait_idle())
            assert_embedding_delta(before, provider.snapshot(), [text_digest("doc")], [text_digest("query")])
            with self.assertRaisesRegex(ValueError, "conflicting"):
                provider.register("doc", "query")

    def test_invalid_requests_rejected_and_credentials_not_recorded(self):
        with FakeEmbeddings() as provider:
            self.assertEqual(post(provider, [], raw='{"model":"fixture","input":[]}')[0], 400)
            self.assertEqual(post(provider, [], raw='{broken')[0], 400)
            self.assertEqual(provider.snapshot()["rejected_requests"], 2)
            self.assertEqual(provider.snapshot()["requests"], 0)
            self.assertNotIn("Authorization", json.dumps(provider.snapshot()))
            with self.assertRaises(ValueError):
                provider.arm(0, Fault())

    def test_cleanup_closes_listener_after_failure(self):
        provider = FakeEmbeddings()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaisesRegex(RuntimeError, "test failure"):
                with provider:
                    port = int(provider.base_url.rsplit(":", 1)[1])
                    provider.arm(1, Fault(kind="none", gate=threading.Event()))
                    client = pool.submit(post, provider, ["held during cleanup"])
                    self.assertTrue(provider.wait_received(1))
                    self.assertEqual(provider.snapshot()["active"], 1)
                    raise RuntimeError("test failure")
            self.assertEqual(client.result(timeout=2)[0], 200)
        with socket.socket() as sock:
            self.assertNotEqual(sock.connect_ex(("127.0.0.1", port)), 0)
        self.assertFalse(provider._thread.is_alive())
        self.assertEqual(provider.snapshot()["active"], 0)


class OracleTests(unittest.TestCase):
    def ledger(self, texts=(), roles=()):
        events = [] if not texts else [{"call": 1, "model": "fixture", "input_sha256": list(texts),
                                      "roles": list(roles), "batch_size": len(texts)}]
        return {"events": events, "active": 0, "max_active": int(bool(events))}

    def test_cache_identity_separates_all_four_axes(self):
        key = CacheKey("hash-a", "repr-a", "model-a", 2)
        variants = [CacheKey("hash-b", "repr-a", "model-a", 2), CacheKey("hash-a", "repr-b", "model-a", 2),
                    CacheKey("hash-a", "repr-a", "model-b", 2), CacheKey("hash-a", "repr-a", "model-a", 3)]
        for other in variants:
            with self.subTest(other=other), self.assertRaisesRegex(AssertionError, "inventory"):
                assert_cache({key: [1, 2]}, {other: [1, 2]})
        assert_cache({key: [1, 2]}, {key: [1, 2]})

    def test_cache_rejects_wrong_values_dimensions_zero_and_nonfinite(self):
        key = CacheKey("hash", "repr", "model", 2)
        for vector in ([1], [2, 1], [0, 0], [float("inf"), 1], [float("nan"), 1]):
            with self.subTest(vector=vector), self.assertRaises(AssertionError):
                assert_cache({key: vector}, {key: [1, 2]})

    def test_cache_requires_exact_inventory(self):
        key = CacheKey("hash", "repr", "model", 2)
        with self.assertRaises(AssertionError):
            assert_cache({key: [1, 2]}, {})
        with self.assertRaises(AssertionError):
            assert_cache({}, {key: [1, 2]})

    def test_reuse_rejects_repeat_embedding_or_unclassified_text(self):
        before = self.ledger()
        for role in ("document", "unclassified"):
            with self.subTest(role=role), self.assertRaises(AssertionError):
                assert_embedding_delta(before, self.ledger(["hash"], [role]))
        assert_embedding_delta(before, before)

    def test_provider_ledger_reset_and_attribution_errors_fail(self):
        before = self.ledger(["doc"], ["document"])
        with self.assertRaisesRegex(AssertionError, "reset"):
            assert_embedding_delta(before, self.ledger())
        after = copy.deepcopy(before)
        after["events"][0]["model"] = "changed"
        with self.assertRaisesRegex(AssertionError, "history"):
            assert_embedding_delta(before, after)
        after = self.ledger(["doc"], [])
        with self.assertRaisesRegex(AssertionError, "attribution"):
            assert_embedding_delta(self.ledger(), after)

    def test_search_is_query_only_and_both_stores_read_only(self):
        before = self.ledger()
        after = self.ledger(["query"], ["query"])
        db = {"unit_concept_memberships": [[1, 2]], "unit_concept_links": [[3, "same"]]}
        points = {2: {"hash": "fresh", "vector": [1, 2]}}
        assert_read_only(db, db, points, points, before, after, ["query"])
        with self.assertRaisesRegex(AssertionError, "SQLite"):
            assert_read_only(db, {}, points, points, before, after, ["query"])
        with self.assertRaisesRegex(AssertionError, "vector records"):
            assert_read_only(db, db, points, {}, before, after, ["query"])
        with self.assertRaisesRegex(AssertionError, "document"):
            assert_read_only(db, db, points, points, before, self.ledger(["doc"], ["document"]))

    def test_bounds_reject_oversized_batches_active_calls_or_parallelism(self):
        data = self.ledger(["a", "b"], ["document", "document"])
        assert_bounded_provider(data, max_batch=2)
        with self.assertRaisesRegex(AssertionError, "batch"):
            assert_bounded_provider(data, max_batch=1)
        data["active"] = 1
        with self.assertRaisesRegex(AssertionError, "in-flight"):
            assert_bounded_provider(data, max_batch=2)

    def test_authority_order_duplicates_and_no_substitution(self):
        assert_result_ids([3, 1], [3, 1])
        for actual in ([3, 3], [3, 2], [1, 3], [3]):
            with self.subTest(actual=actual), self.assertRaises(AssertionError):
                assert_result_ids(actual, [3, 1])

    def test_index_compares_values_not_only_count(self):
        assert_index({1: {"vector": [1], "hash": "current"}}, {1: {"vector": [1], "hash": "current"}})
        with self.assertRaisesRegex(AssertionError, "inventory"):
            assert_index({1: {"vector": [1], "hash": "stale"}}, {1: {"vector": [1], "hash": "current"}})

    def test_failed_or_superseded_run_cannot_claim_complete(self):
        for state in ("partial", "building", "superseded"):
            assert_not_complete(state)
        with self.assertRaisesRegex(AssertionError, "falsely complete"):
            assert_not_complete("complete")


if __name__ == "__main__":
    unittest.main(verbosity=2)
