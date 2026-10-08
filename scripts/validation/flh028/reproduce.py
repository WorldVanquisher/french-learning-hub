#!/usr/bin/env python3
"""FLH-028: actual annotation response-loss probes against a private service."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from proxy import LossProxy, public_job

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
# Read-only reuse of isolated build/process/fake-provider infrastructure, not its assertions.
sys.path.insert(0, str(HERE.parent / "flh026"))
from run import Harness, owns_listener, require, snapshot  # noqa: E402

OPERATIONS = ("same", "reassign", "reject-same", "invalid", "restore", "new-concept",
              "preferred", "distinct", "broader", "narrower", "related")


class Investigation:
    def __init__(self, harness):
        self.harness = harness
        self.proxy = LossProxy(self.forward)
        self.thread = threading.Thread(target=self.proxy.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.proxy.server_address[1]
        self.cases = []
        self.sequence = 0

    def forward(self, method, path, body, headers):
        process = self.harness.process
        require(process is not None and process.poll() is None
                and owns_listener(process.pid, self.harness.port), "refuse unowned upstream listener")
        conn = http.client.HTTPConnection("127.0.0.1", self.harness.port, timeout=5)
        try:
            conn.request(method, path, body=body or None, headers=headers)
            response = conn.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            conn.close()

    def api(self, method, path, body=None, expected=200, headers=None):
        return self.harness.http(self.port, method, path, body, expected=expected,
                                 headers={"Origin": f"http://127.0.0.1:{self.port}",
                                          "Sec-Fetch-Site": "same-origin", **(headers or {})})

    def fixture(self, operation, prefix):
        self.sequence += 1
        receipt = self.api("POST", prefix + "/captures", {
            "schema_version": "learning_capture_v1", "capture_id": f"flh028-{self.sequence}",
            "source": "manual", "original_input": "Je ne parle pas.", "original_context": "Isolated fixture",
            "analysis": {"category": "grammar", "explanation": "La négation encadre le verbe.",
                         "confidence": 0.95, "uncertainty": ""}}, expected=201)
        entry = receipt["entry_id"]
        extraction = self.api("POST", prefix + f"/entries/{entry}/extractions", expected=201)
        unit = extraction["units"][0]["id"]
        candidate = self.api("GET", prefix + f"/reviewable-units?entry_id={entry}")["reviewable_units"][0]["candidate_identity"]
        concepts = []
        for suffix in ("a", "b"):
            identity = candidate | {"target": f"flh028-{self.sequence}-{suffix}"}
            concepts.append(self.api("POST", prefix + "/concepts", {"identity": identity}, expected=201)["concept"]["id"])
        a, b = concepts
        unit_path = prefix + f"/knowledge-units/{unit}"
        if operation in {"reassign", "reject-same", "invalid", "preferred"}:
            self.api("POST", unit_path + "/concept-links/same", {"concept_id": a}, expected=201)
        if operation == "restore":
            self.api("POST", unit_path + "/invalid")
        spec = {"operation": operation, "prefix": prefix, "unit": unit, "entry": entry,
                "a": a, "b": b, "method": "POST", "expected_status": 201}
        if operation == "same":
            spec.update(path=unit_path + "/concept-links/same", body={"concept_id": a})
        elif operation == "reassign":
            spec.update(method="PUT", path=unit_path + "/concept-membership", body={"concept_id": b}, expected_status=200)
        elif operation == "reject-same":
            spec.update(path=unit_path + "/concept-membership/reject", body=None, expected_status=200)
        elif operation in {"invalid", "restore"}:
            spec.update(path=unit_path + "/invalid" + ("/restore" if operation == "restore" else ""),
                        body=None, expected_status=200)
        elif operation == "new-concept":
            spec.update(path=prefix + "/concepts", body={
                "identity": candidate | {"target": f"flh028-{self.sequence}-new"},
                "seed_unit_id": unit, "link_seed_as_same": True})
        elif operation == "preferred":
            spec.update(path=prefix + f"/concepts/{a}/preferred-unit", body={"unit_id": unit}, expected_status=200)
        elif operation == "distinct":
            spec.update(path=unit_path + "/concept-distinctions", body={"concept_id": a})
        else:
            spec.update(path=unit_path + "/concept-links/relation", body={"concept_id": a, "relation": operation})
        return spec

    def read(self, spec):
        prefix, unit, a = spec["prefix"], spec["unit"], spec["a"]
        unit_path = prefix + f"/knowledge-units/{unit}"
        observation = {
            "membership": self.api("GET", unit_path + "/concept-membership"),
            "invalid": self.api("GET", unit_path + "/invalid"),
            "distinctions": self.api("GET", unit_path + "/concept-distinctions"),
            "concept_a": self.api("GET", prefix + f"/concepts/{a}"),
            "annotation": self.api("GET", unit_path + "/effective-annotation"),
        }
        if spec["operation"] == "reassign":
            observation["concept_b"] = self.api("GET", prefix + f"/concepts/{spec['b']}")
        if spec["operation"] == "new-concept":
            identity = spec["body"]["identity"]
            observation["matching_concepts"] = [c for c in self.api("GET", prefix + "/concepts")["concepts"]
                                                 if all(c[k] == v for k, v in identity.items())]
        return observation

    @staticmethod
    def confirmed(spec, read):
        operation = spec["operation"]
        membership = read["membership"]["current_membership"]
        if operation in {"same", "reassign"}:
            target = spec["b"] if operation == "reassign" else spec["a"]
            return membership is not None and membership["concept_id"] == target
        if operation == "reject-same":
            return membership is None
        if operation in {"invalid", "restore"}:
            return read["invalid"]["invalid"] == (operation == "invalid") and membership is None
        if operation == "new-concept":
            return (len(read["matching_concepts"]) == 1 and membership is not None
                    and membership["concept_id"] == read["matching_concepts"][0]["id"])
        if operation == "preferred":
            return read["concept_a"]["concept"]["preferred_unit_id"] == spec["unit"]
        if operation == "distinct":
            return any(item["concept_id"] == spec["a"] for item in read["distinctions"]["distinctions"])
        return any(item["unit_id"] == spec["unit"] and item["relation"] == operation
                   for item in read["concept_a"]["links"])

    def lost(self, spec, mode):
        job = self.proxy.arm(mode, spec["method"], spec["path"])
        try:
            self.api(spec["method"], spec["path"], spec["body"], expected=spec["expected_status"], headers=spec.get("headers"))
        except (http.client.HTTPException, OSError) as exc:
            client = {"status": None, "error_type": type(exc).__name__, "message": str(exc)}
        else:
            raise AssertionError("faulted request unexpectedly delivered an HTTP response")
        require(job["received"].wait(2), "proxy did not receive mutation")
        return job, client

    def scenario(self, operation, prefix, mode):
        spec = self.fixture(operation, prefix)
        before = self.read(spec)
        require(not self.confirmed(spec, before), "fixture already meets desired state")
        before_db = snapshot(self.harness.active / "app.db")
        calls = self.harness.calls()
        job, client = self.lost(spec, mode)
        if mode != "delay-drop":
            require(job["done"].wait(3), "proxy job did not complete")
        reconciled = self.read(spec)  # GETs go through the SAME proxy while a delayed write is pending.
        get_done = time.monotonic_ns()
        require(self.confirmed(spec, reconciled) == (mode == "commit-drop"),
                "reconciliation GET state mismatch")
        if mode in {"never", "delay-drop"}:
            require(not job["forwarded"] and reconciled == before, "pre-forward GET did not observe baseline")
            require(snapshot(self.harness.active / "app.db") == before_db, "unforwarded request wrote data")
        if mode == "delay-drop":
            job["release"].set()
            require(job["done"].wait(3), "delayed mutation did not complete")
            require(next(e["time_ns"] for e in job["events"] if e["event"] == "forwarding") > get_done,
                    "mutation forwarding preceded reconciliation GET completion")
        require(job["error"] is None, "proxy infrastructure error: " + str(job["error"]))
        after = self.read(spec)
        changed = snapshot(self.harness.active / "app.db") != before_db
        require(self.harness.calls() == calls, "annotation unexpectedly called provider")
        require(self.confirmed(spec, after) == (mode != "never"), "authoritative desired-state confirmation mismatch")
        require(changed == (mode != "never"), "persisted write outcome mismatch")
        if mode != "never":
            require(job["upstream_status"] == spec["expected_status"], "unexpected upstream write result")
        self.cases.append({"spec": spec, "mode": mode, "expected": {
            "client_http_status": None, "reconciliation_confirms_desired_state": mode == "commit-drop",
            "final_confirms_desired_state": mode != "never", "persisted_change": mode != "never"},
            "actual": {"client": client, "reconciliation": reconciled, "reconciliation_completed_ns": get_done,
                       "final": after, "persisted_change": changed, "provider_calls_before": calls,
                       "provider_calls_after": self.harness.calls(), "proxy": public_job(job)}, "result": "PASS"})
        print(f"PASS {prefix or 'root'} {operation} {mode}", flush=True)
        if mode == "commit-drop":
            self.preexisting(spec)

    def preexisting(self, spec):
        baseline = self.read(spec)
        before = snapshot(self.harness.active / "app.db")
        calls = self.harness.calls()
        require(self.confirmed(spec, baseline), "preexisting-state fixture missing")
        job, client = self.lost(spec, "never")
        require(job["done"].wait(3) and not job["forwarded"] and job["error"] is None,
                "preexisting-state request was forwarded")
        after = self.read(spec)
        require(after == baseline and self.confirmed(spec, after), "preexisting desired state changed")
        require(snapshot(self.harness.active / "app.db") == before and self.harness.calls() == calls,
                "unforwarded preexisting-state request had side effects")
        self.cases.append({"spec": spec, "mode": "preexisting-state-no-attribution", "result": "PASS",
                           "expected": {"state_confirms_desired": True, "this_request_forwarded": False,
                                        "new_event_or_write": False},
                           "actual": {"client": client, "proxy": public_job(job), "state": after,
                                      "new_event_or_write": False, "provider_calls": calls}})
        print(f"PASS {spec['prefix'] or 'root'} {spec['operation']} preexisting state cannot attribute unforwarded request", flush=True)

    def repeated(self, operation, prefix):
        spec = self.fixture(operation, prefix)
        calls = self.harness.calls()
        job, client = self.lost(spec, "commit-drop")
        require(job["done"].wait(3) and job["error"] is None, "first repeated-operation job failed")
        first = self.read(spec)
        require(self.confirmed(spec, first), "lost-response event missing")
        # Deliberate explicit resubmissions, NOT automatic retry logic.
        responses = [self.api(spec["method"], spec["path"], spec["body"], expected=201) for _ in range(2)]
        final = self.read(spec)
        if operation == "distinct":
            events = [d for d in final["distinctions"]["distinctions"] if d["concept_id"] == spec["a"]]
            projected = final["annotation"]["snapshot"]["distinctions"]
            table = "unit_concept_distinctions"
        else:
            events = [link for link in final["concept_a"]["links"]
                      if link["unit_id"] == spec["unit"] and link["relation"] == operation]
            projected = [link for link in final["annotation"]["snapshot"]["relations"] if link["relation"] == operation]
            table = "unit_concept_links"
        ids = [e["id"] for e in events]
        require(len(events) == 3 and len(set(ids)) == 3, "repeated explicit submissions did not append three distinct events")
        originals = [job["upstream_body"], *responses]
        require({r["id"]: r for r in originals} == {e["id"]: e for e in events},
                "append-only history mutated an earlier response event")
        if operation != "distinct":
            ordered = sorted(events, key=lambda e: e["id"])
            require([e["supersedes_link_id"] for e in ordered] == [None, ordered[0]["id"], ordered[1]["id"]],
                    "relation replacement back-pointers are inconsistent")
        stored = snapshot(self.harness.active / "app.db")[table]
        require(set(ids) <= {row[0] for row in stored}, "API history events not physically persisted")
        dataset = next(r for r in self.api("GET", prefix + "/annotation-dataset/v1")["records"]
                       if r["unit"]["id"] == spec["unit"])
        projected_dataset = dataset["effective_annotation"]["distinctions" if operation == "distinct" else "relations"]
        require(len(projected) == len(projected_dataset) == 1, "effective projection did not deduplicate pair/type")
        require(projected[0]["id"] == max(ids), "effective projection did not select newest event")
        nested = "distinction" if operation == "distinct" else "decision"
        require(projected_dataset[0][nested]["id"] == max(ids), "dataset selected wrong event")
        require(final["membership"]["current_membership"] is None and not final["invalid"]["invalid"],
                "DISTINCT/relation incorrectly changed SAME or INVALID")
        require(self.harness.calls() == calls, "repeated annotation called provider")
        self.cases.append({"spec": spec, "mode": "explicit-repeat-after-loss", "result": "PASS",
                           "expected": {"append_only_event_count": 3, "effective_pair_count": 1},
                           "actual": {"client": client, "proxy": public_job(job), "repeat_responses": responses,
                                      "history": events, "stored_event_ids": ids,
                                      "effective_annotation": projected, "dataset": projected_dataset,
                                      "provider_calls_before": calls, "provider_calls_after": self.harness.calls()}})
        print(f"PASS {prefix or 'root'} {operation} repeated: history=3 effective=1", flush=True)

    def delayed_existing_pair(self, operation, prefix):
        spec = self.fixture(operation, prefix)
        first = self.api(spec["method"], spec["path"], spec["body"], expected=201)
        baseline, before = self.read(spec), snapshot(self.harness.active / "app.db")
        calls = self.harness.calls()
        job, client = self.lost(spec, "delay-drop")
        reconciled = self.read(spec)
        get_done = time.monotonic_ns()
        require(self.confirmed(spec, reconciled) and reconciled == baseline and not job["forwarded"],
                "existing pair was not confirmed while original remained pending")
        require(snapshot(self.harness.active / "app.db") == before, "delayed duplicate wrote before GET")
        job["release"].set()
        require(job["done"].wait(3) and job["error"] is None and job["upstream_status"] == 201,
                "delayed existing-pair write failed")
        require(next(e["time_ns"] for e in job["events"] if e["event"] == "forwarding") > get_done,
                "delayed duplicate preceded GET completion")
        final = self.read(spec)
        if operation == "distinct":
            history = final["distinctions"]["distinctions"]
        else:
            history = [link for link in final["concept_a"]["links"] if link["relation"] == operation]
        require({e["id"] for e in history} == {first["id"], job["upstream_body"]["id"]}
                and len(history) == 2, "delayed duplicate did not append a separate event")
        require(self.harness.calls() == calls, "delayed duplicate called provider")
        self.cases.append({"spec": spec, "mode": "delayed-existing-pair", "result": "PASS",
                           "expected": {"matching_state_before_forwarding": True, "final_history_count": 2},
                           "actual": {"client": client, "first_event": first, "reconciliation": reconciled,
                                      "reconciliation_completed_ns": get_done, "proxy": public_job(job),
                                      "final_history": history, "provider_calls": calls}})
        print(f"PASS {prefix or 'root'} {operation} desired state precedes delayed duplicate commit", flush=True)

    def keyed(self, operation, prefix, mode):
        spec = self.fixture(operation, prefix)
        key = str(uuid.uuid4())
        spec["headers"] = {"Idempotency-Key": key}
        lookup = prefix + "/annotation-operations/" + key
        calls = self.harness.calls()
        before = snapshot(self.harness.active / "app.db")
        self.api("GET", lookup, expected=404)
        job, client = self.lost(spec, mode)
        if mode == "delay-drop":
            unknown = self.api("GET", lookup, expected=404)
            require(not job["forwarded"] and snapshot(self.harness.active / "app.db") == before,
                    "unknown lookup changed or fenced delayed operation")
            # Retry may win while the original request is still gated.
            original = self.api("POST", spec["path"], spec["body"], expected=201, headers=spec["headers"])
            job["release"].set()
        require(job["done"].wait(3) and job["error"] is None, "keyed proxy job failed")
        if mode == "never":
            self.api("GET", lookup, expected=404)
            require(snapshot(self.harness.active / "app.db") == before, "never request wrote")
            original = self.api("POST", spec["path"], spec["body"], expected=201, headers=spec["headers"])
        elif mode == "commit-drop":
            original = job["upstream_body"]
        else:
            require(job["upstream_body"] == original, "delayed original did not replay retry result")
        receipt = self.api("GET", lookup)
        require(receipt["state"] == "committed" and receipt["result"] == original, "receipt attribution mismatch")
        committed = snapshot(self.harness.active / "app.db")
        with ThreadPoolExecutor(max_workers=8) as pool:
            replays = list(pool.map(lambda _: self.api("POST", spec["path"], spec["body"], expected=201,
                                                      headers=spec["headers"]), range(8)))
        require(all(result == original for result in replays), "concurrent replay changed result")
        require(snapshot(self.harness.active / "app.db") == committed, "replay wrote")
        self.api("POST", spec["path"], spec["body"] | {"concept_id": spec["b"]}, expected=409, headers=spec["headers"])
        other_path = prefix + f"/knowledge-units/{spec['unit']}/" + ("concept-links/relation" if operation == "distinct" else "concept-distinctions")
        other_body = {"concept_id":spec["a"]} | ({"relation":"related"} if operation == "distinct" else {})
        self.api("POST", other_path, other_body, expected=409, headers=spec["headers"])
        require(snapshot(self.harness.active / "app.db") == committed, "conflict wrote")
        self.api("POST", spec["path"], spec["body"], expected=403,
                 headers={"Idempotency-Key":str(uuid.uuid4()), "Origin":"http://evil.invalid", "Sec-Fetch-Site":"cross-site"})
        self.api("GET", lookup, expected=403, headers={"Host":"evil.invalid"})
        require(snapshot(self.harness.active / "app.db") == committed, "browser-blocked request wrote")
        # Later deliberate decision changes effective history but never the receipt.
        later = self.api("POST", spec["path"], spec["body"], expected=201, headers={"Idempotency-Key":str(uuid.uuid4())})
        require(later["id"] != original["id"], "new key did not append")
        latest = self.read(spec)
        if operation == "distinct":
            events = latest["distinctions"]["distinctions"]
            projection = self.api("GET", prefix + f"/knowledge-units/{spec['unit']}/effective-annotation")["snapshot"]["distinctions"]
        else:
            events = [e for e in latest["concept_a"]["links"] if e["relation"] == operation and e["unit_id"] == spec["unit"]]
            projection = self.api("GET", prefix + f"/knowledge-units/{spec['unit']}/effective-annotation")["snapshot"]["relations"]
        require(len(events) == 2 and any(e == original for e in events), "history changed")
        require(len(projection) == 1 and projection[0]["id"] == later["id"], "current projection wrong")
        replay = self.api("POST", spec["path"], spec["body"], expected=201, headers=spec["headers"])
        require(replay == original and self.api("GET", lookup) == receipt, "historical replay changed")
        if mode == "commit-drop":
            self.harness.replace()
            require(self.api("GET", lookup) == receipt, "restart lost receipt")
        require(self.harness.calls() == calls, "keyed annotation called provider")
        self.cases.append({"spec":spec, "mode":"keyed-"+mode, "result":"PASS",
                           "actual":{"client":client,"proxy":public_job(job),"receipt":receipt,"later":later,
                                     "concurrent_replays":replays,"history":events,"provider_calls":calls}})
        print(f"PASS {prefix or 'root'} {operation} keyed {mode}: attribution, replay, conflict, boundary, history", flush=True)

    def run(self):
        for prefix in ("", "/api"):
            for operation in OPERATIONS:
                for mode in ("never", "commit-drop", "delay-drop"):
                    self.scenario(operation, prefix, mode)
            for operation in ("distinct", "broader", "narrower", "related"):
                self.repeated(operation, prefix)
                self.delayed_existing_pair(operation, prefix)
                for mode in ("never", "commit-drop", "delay-drop"):
                    self.keyed(operation, prefix, mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="new evidence JSON outside repository; never overwritten")
    args = parser.parse_args()
    if args.report:
        target = args.report.resolve()
        require(not target.exists() and ROOT not in target.parents and target.parent.is_dir(), "invalid report destination")
    os.umask(0o077)
    harness = Harness("native")
    investigation = None
    error = None
    evidence = {"status": "FAIL", "source_sha256": {}, "cases": [], "cleanup_errors": []}
    print(f"FLH028_RUN={harness.run_dir}", flush=True)
    def interrupted(number, _):
        raise KeyboardInterrupt(f"signal {number}")
    signal.signal(signal.SIGTERM, interrupted)
    try:
        harness.prepare()
        harness.start()
        investigation = Investigation(harness)
        investigation.run()
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        print("FAIL " + error, flush=True)
    finally:
        evidence.update(status="FAIL" if error else "PASS", error=error,
                        source_sha256=getattr(harness, "manifest", {}), commands=harness.commands,
                        harness_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for folder in (HERE, HERE.parent / "flh026")
                                        for p in sorted(folder.glob("*.py"))},
                        cases=investigation.cases if investigation else [],
                        service_log=(harness.run_dir / "service.log").read_text())
        if investigation:
            try:
                investigation.proxy.close()
                investigation.thread.join(timeout=3)
                require(not investigation.thread.is_alive(), "proxy serve thread did not stop")
            except BaseException as exc:
                evidence["cleanup_errors"].append(str(exc))
        evidence["cleanup_errors"].extend(harness.cleanup())
        evidence["temporary_directory_removed"] = not harness.run_dir.exists()
        if evidence["cleanup_errors"]:
            evidence["status"] = "FAIL"
        if args.report:
            with args.report.open("x") as output:
                json.dump(evidence, output, indent=2)
        print(f"RESULT={evidence['status']} CASES={len(evidence['cases'])} "
              f"CLEANUP={'FAIL' if evidence['cleanup_errors'] else 'PASS'}", flush=True)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
