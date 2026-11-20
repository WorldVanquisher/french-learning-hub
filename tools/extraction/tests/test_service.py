"""The private extraction service (flh_extraction.service): offline, loopback only, synthetic data."""

from __future__ import annotations

import contextlib
import io
import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flh_extraction import feed_compat as fc  # noqa: E402
from flh_extraction import packet as pk  # noqa: E402
from flh_extraction import practice as pr  # noqa: E402
from flh_extraction import review2 as rv  # noqa: E402
from flh_extraction import service as svc  # noqa: E402

FIX = ROOT / "fixtures" / "practice_v1"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class Server:
    def __init__(self, **limits):
        self.srv = svc.make_server("127.0.0.1", 0, {**svc.LIMITS, **limits})
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.srv.state.pool.shutdown(wait=True)


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self._err = io.StringIO()
        self._redir = contextlib.redirect_stderr(self._err)
        self._redir.__enter__()
        self.s = Server()

    def tearDown(self):
        self.s.close()
        self._redir.__exit__(None, None, None)

    def post(self, path, payload, **kw):
        return svc.call(self.s.url, path, payload, **kw)

    def test_smoke_against_a_running_server(self):
        rc, text = svc.smoke(self.s.url)
        self.assertEqual(rc, 0, text)

    def test_review_equals_the_library_and_keeps_source_revisions(self):
        srcs = [load("y_en.r1.json"), load("y_en.r2.json"), load("y_en.r3.json")]
        d1 = pr.draft(srcs[0])
        ids = {i["proposal_ref"]: i["item_id"] for i in d1["items"]}
        decs = [pr.decision(d1, ids["en-de"], "approve", 1), pr.decision(d1, ids["ex-piscine"], "approve", 2)]
        s, doc = self.post("/v1/review", svc.request(sources=srcs, decisions=decs))
        self.assertEqual(s, 200, doc)
        lib = rv.resolve2({x["revision"]: pr.draft(x) for x in srcs}, decs, {x["revision"]: x for x in srcs})
        self.assertEqual(doc["states"], lib["states"])
        by = {i["item_id"]: i for i in doc["items"]}
        self.assertEqual((by[ids["ex-piscine"]]["state"], by[ids["ex-piscine"]]["decided_on_revision"], by[ids["ex-piscine"]]["carried_from_revision"]),
                         ("approved", 1, 1))
        self.assertEqual((by[ids["en-de"]]["state"], by[ids["en-de"]]["review_kind"]), ("needs_review", "restored"))
        self.assertTrue(all(e["source_revision"] == 3 for e in doc["evidence"]))
        self.assertEqual(doc["deployment_id"], self.s.srv.state.manifest["deployment_id"])

    def test_unsupported_claim_with_an_exact_quote_is_flagged(self):
        s, doc = self.post("/v1/review", svc.request(sources=[load("a_en_lieux.json")]))
        flagged = {i["text"][:30]: [c["cue"] for c in i["cues"]] for i in doc["items"] if i["cues"]}
        self.assertEqual(sorted(sum(flagged.values(), [])), ["en_plus_ant", "generalises"])
        self.assertTrue(all(i["support"] == "supported" for i in doc["items"] if i["cues"]))
        self.assertEqual(len(doc["plan"]["selected"]), 5)

    def test_feed_contract_and_withdrawal_after_a_revision(self):
        r1, r2 = load("y_en.r1.json"), load("y_en.r2.json")
        d1 = pr.draft(r1)
        decs = [pr.decision(d1, i["item_id"], "approve", k + 1) for k, i in enumerate(d1["items"]) if i["support"] in ("supported", "generated")]
        s, a = self.post("/v1/feed", svc.request(sources=[r1], decisions=decs, feed_seq=1))
        self.assertEqual(s, 200, a)
        f1 = a["feed"]
        self.assertEqual((fc.contract_issues(f1), fc.consumer_issues(f1)), ([], []))
        pid = f1["items"][0]["practice_id"]
        att = [{"schema": pr.ATTEMPT_SCHEMA, "seq": 1, "practice_id": pid, "action": "reveal", "outcome": "revealed"}]
        s, b = self.post("/v1/feed", svc.request(sources=[r1, r2], decisions=decs, attempts=att, feed_seq=2, previous=f1))
        self.assertEqual(s, 200, b)
        f2 = b["feed"]
        self.assertEqual(fc.contract_issues(f2), [])
        self.assertEqual(sorted(x["practice_id"] for x in f2["withdrawn"]), sorted(p["practice_id"] for p in f1["items"]))
        self.assertIn("all-withdrawn feed is refused", " ".join(fc.consumer_issues(f2)))
        bad = [{**att[0], "practice_id": "p-000000000000"}]
        s, e = self.post("/v1/feed", svc.request(sources=[r1], decisions=decs, attempts=bad, feed_seq=1))
        self.assertEqual((s, e["error"]["type"]), (422, "invalid_decisions"))

    def test_attempts_on_withdrawn_ids_after_an_empty_feed(self):
        # R4 corpus scenario 10: revision 2 withdrew every item (feed 2 offers none); feed 3 still carries the
        # learner's earlier attempts on those IDs. Before R4 the service refused them (422) although the CLI built the feed.
        r1, r2, r3 = load("y_en.r1.json"), load("y_en.r2.json"), load("y_en.r3.json")
        d1 = pr.draft(r1)
        decs = [pr.decision(d1, i["item_id"], "approve", k + 1) for k, i in enumerate(d1["items"]) if i["support"] in ("supported", "generated")]
        f1 = self.post("/v1/feed", svc.request(sources=[r1], decisions=decs, feed_seq=1))[1]["feed"]
        att = [{"schema": pr.ATTEMPT_SCHEMA, "seq": 1, "practice_id": f1["items"][0]["practice_id"], "action": "reveal", "outcome": "revealed"}]
        s, b = self.post("/v1/feed", svc.request(sources=[r1, r2], decisions=decs, attempts=att, feed_seq=2, previous=f1))
        f2 = b["feed"]
        self.assertEqual((s, f2["items"]), (200, []))
        s, c = self.post("/v1/feed", svc.request(sources=[r1, r2, r3], decisions=decs, attempts=att, feed_seq=3, previous=f2))
        self.assertEqual(s, 200, c)
        self.assertIn(att[0]["practice_id"], [w["practice_id"] for w in c["feed"]["withdrawn"]])
        bad = [{**att[0], "practice_id": "p-000000000000"}]
        s, e = self.post("/v1/feed", svc.request(sources=[r1, r2, r3], decisions=decs, attempts=bad, feed_seq=3, previous=f2))
        self.assertEqual((s, e["error"]["type"]), (422, "invalid_decisions"))

    def test_import_preview_of_a_return(self):
        s, d = self.post("/v1/import-preview", svc.request(packet=load("expected2/06-packet-1-codex.json"), proposals=load("switch/codex-return.json")))
        self.assertEqual(s, 200)
        self.assertEqual(d["preview"]["corrections"]["counts"]["duplicate"], 1)
        s, d = self.post("/v1/import-preview", svc.request(packet=load("expected2/06-packet-1-codex.json"),
                                                           proposals={**load("switch/codex-return.json"), "schema": "flh_agent_proposals_v9"}))
        self.assertEqual((s, d["error"]["type"]), (422, "invalid_return"))

    def test_envelope_and_media_errors(self):
        s, d = self.post("/v1/review", svc.request(sources=[load("y_en.r1.json")]), contract="flh_extraction_service_v2")
        self.assertEqual((s, d["error"]["type"], d["service_contract"]), (409, "contract_mismatch", svc.CONTRACT))
        import urllib.request
        req = urllib.request.Request(self.s.url + "/v1/review", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        with self.assertRaises(Exception) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 400)
        req = urllib.request.Request(self.s.url + "/v1/review", data=b"x", method="POST", headers={"Content-Type": "text/plain", "X-FLH-Contract": svc.CONTRACT})
        with self.assertRaises(Exception) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 415)
        too_many = [load("y_en.r1.json")] * (svc.LIMITS["max_revisions"] + 1)
        s, d = self.post("/v1/review", svc.request(sources=too_many))
        self.assertEqual((s, d["error"]["type"]), (413, "too_large"))
        s, d = self.post("/v1/review", svc.request(sources=[load("y_en.r1.json"), load("savoir_connaitre.json")]))
        self.assertEqual((s, d["error"]["type"]), (422, "invalid_source"))

    def test_request_id_is_echoed_or_generated(self):
        import urllib.request
        body = json.dumps(svc.request(sources=[load("y_en.r1.json")])).encode()
        for given, expect_same in (("0123456789abcdef", True), ("bad id with spaces", False), (None, False)):
            h = {"Content-Type": "application/json", "X-FLH-Contract": svc.CONTRACT}
            if given:
                h["X-Request-Id"] = given
            with urllib.request.urlopen(urllib.request.Request(self.s.url + "/v1/review", data=body, method="POST", headers=h), timeout=10) as r:
                rid = r.headers["X-Request-Id"]
            self.assertTrue(svc.REQUEST_ID.fullmatch(rid))
            self.assertEqual(rid == given, expect_same)
        for _ in range(50):
            if '"request_id": "0123456789abcdef"' in self._err.getvalue():
                break
            time.sleep(0.02)
        self.assertIn('"request_id": "0123456789abcdef"', self._err.getvalue())

    def test_counters_for_monitoring(self):
        self.post("/v1/review", svc.request(sources=[load("y_en.r1.json")]))
        self.post("/v1/review", {"schema": "x"})
        s, d = svc.call(self.s.url, "/metrics")
        self.assertEqual((s, d["counters"]["ok"], d["counters"]["client_error"]), (200, 1, 1))
        self.assertEqual(set(d), {"status", "counters", "deployment_id"})

    def test_logs_carry_no_learner_text(self):
        self.post("/v1/review", svc.request(sources=[load("y_en.r1.json")]))
        for _ in range(50):  # the line is written just after the response body
            if '"path": "/v1/review"' in self._err.getvalue():
                break
            time.sleep(0.02)
        log = self._err.getvalue()
        self.assertIn('"path": "/v1/review"', log)
        for q in ("boulangerie", "j'y vais", "confonds"):
            self.assertNotIn(q, log)
        self.assertEqual(pk.privacy_findings(json.dumps(self.s.srv.state.manifest)), [])


class Bounds(unittest.TestCase):
    def setUp(self):
        self._redir = contextlib.redirect_stderr(io.StringIO())
        self._redir.__enter__()

    def tearDown(self):
        self._redir.__exit__(None, None, None)

    def test_busy_and_timeout(self):
        gate = threading.Event()
        s = Server(max_inflight=1, request_timeout_s=2.0)
        s.srv.state.slow_hook = lambda: gate.wait(3)
        try:
            out = []
            t = threading.Thread(target=lambda: out.append(svc.call(s.url, "/v1/review", svc.request(sources=[load("y_en.r1.json")]))))
            t.start()
            time.sleep(0.3)
            busy = svc.call(s.url, "/v1/review", svc.request(sources=[load("y_en.r1.json")]))
            gate.set()
            t.join(5)
            self.assertEqual((busy[0], busy[1]["error"]["type"]), (503, "busy"))
            self.assertEqual(out[0][0], 200)
        finally:
            s.close()
        s = Server(request_timeout_s=0.2)
        s.srv.state.slow_hook = lambda: time.sleep(0.6)
        try:
            st, d = svc.call(s.url, "/v1/review", svc.request(sources=[load("y_en.r1.json")]))
            self.assertEqual((st, d["error"]["type"]), (504, "timeout"))
            self.assertEqual(s.srv.state.counters["timeout"], 1)
        finally:
            s.close()

    def test_concurrent_requests_at_the_worker_limit(self):
        # max_inflight normal requests run at the same time (a barrier proves it) and all succeed with the same
        # result; one more while they are held is refused at once with busy, never queued.
        n = svc.LIMITS["max_inflight"]
        barrier, gate = threading.Barrier(n, timeout=5), threading.Event()
        s = Server(request_timeout_s=10.0)
        s.srv.state.slow_hook = lambda: (barrier.wait(), gate.wait(5))
        try:
            out = []
            ts = [threading.Thread(target=lambda: out.append(svc.call(s.url, "/v1/review", svc.request(sources=[load("y_en.r1.json")]), timeout=15)))
                  for _ in range(n)]
            for t in ts:
                t.start()
            for _ in range(250):
                if barrier.n_waiting == 0 and s.srv.state.sem._value == 0:  # all n passed the barrier and hold a slot
                    break
                time.sleep(0.02)
            extra = svc.call(s.url, "/v1/review", svc.request(sources=[load("y_en.r1.json")]))
            gate.set()
            for t in ts:
                t.join(15)
            self.assertEqual((extra[0], extra[1]["error"]["type"]), (503, "busy"))
            self.assertEqual(sorted(o[0] for o in out), [200] * n)
            self.assertEqual(len({o[1]["draft_id"] for o in out}), 1)
            self.assertFalse(barrier.broken)
            self.assertEqual((s.srv.state.counters["ok"], s.srv.state.counters["busy"]), (n, 1))
        finally:
            gate.set()
            s.close()

    def test_not_ready_refuses_work(self):
        s = Server()
        s.srv.state.status = "failed"
        try:
            self.assertEqual(svc.call(s.url, "/readyz")[0], 503)
            st, d = svc.call(s.url, "/v1/review", svc.request(sources=[load("y_en.r1.json")]))
            self.assertEqual((st, d["error"]["type"]), (503, "not_ready"))
        finally:
            s.close()

    def test_client_unavailable_and_deployment_mismatch(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        st, d = svc.call(f"http://127.0.0.1:{port}", "/v1/review", svc.request(sources=[load("y_en.r1.json")]), timeout=1)
        self.assertEqual((st, d["error"]["type"]), (0, "unavailable"))
        s = Server()
        try:
            st, d = svc.call(s.url, "/v1/review", svc.request(sources=[load("y_en.r1.json")]), expect_deployment="flh-extraction-rules@000000000000/x/y")
            self.assertEqual((st, d["error"]["type"]), (0, "deployment_mismatch"))
        finally:
            s.close()

    def test_host_rules(self):
        svc.check_host("127.0.0.1")
        svc.check_host("10.1.2.3")
        for bad in ("8.8.8.8", "localhost"):
            with self.assertRaises(SystemExit):
                svc.check_host(bad)

    def test_payload_examples_are_current(self):
        import subprocess
        r = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts" / "service_examples.py"), "--check"], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr[-500:])
        names = sorted(p.name for p in (ROOT / "fixtures" / "service_v1").iterdir())
        self.assertIn("07-manifest.response.json", names)
        body = "".join((ROOT / "fixtures" / "service_v1" / n).read_text(encoding="utf-8") for n in names if n.endswith(".json"))
        self.assertEqual(pk.privacy_findings(body), [])

    def test_manifest_hashes_the_shipped_code(self):
        m = svc.manifest()
        self.assertEqual(sorted(m["code_sha256"]), sorted(svc.CODE_FILES))
        for f, h in m["code_sha256"].items():
            self.assertEqual(svc._sha_file(str(ROOT / "flh_extraction" / f)), h)
        self.assertIsNone(m["model"]["learned_weights"])
        df = (ROOT / "Dockerfile.service").read_text(encoding="utf-8")
        for f in svc.CODE_FILES:
            self.assertIn(f"flh_extraction/{f}", df)


if __name__ == "__main__":
    unittest.main()
