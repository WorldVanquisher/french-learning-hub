#!/usr/bin/env python3
"""Phase A existing-contract probe; never seeds or runs the FLH-034 demo."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "flh026"))
from run import Harness, snapshot  # noqa: E402
from expectations import read_view, require, verify_view  # noqa: E402


class Probe:
    def __init__(self, harness):
        self.h = harness
        self.fixture = {name: {} for name in
                        ("concepts", "entries", "extractions", "memberships",
                         "selections", "invalid", "history")}
        self.cases = []

    def write(self, method, path, body=None, expected=201):
        calls = self.h.calls()
        result = self.h.request(method, path, body, expected=expected)
        if not path.endswith("/extractions"):
            require(self.h.calls() == calls, "fixture annotation/import invoked provider")
        else:
            require(self.h.calls() == calls | {"extraction": calls["extraction"] + 1},
                    "fixture extraction provider count")
        return result

    def extract(self, entry):
        extraction = self.write("POST", f"/entries/{entry}/extractions")
        require(len(extraction["units"]) == 1, "local provider fixture must return one unit")
        source = {k: v for k, v in extraction.items() if k != "units"}
        source["units"] = {u["id"]: {k: v for k, v in u.items() if k != "admission"}
                           for u in extraction["units"]}
        self.fixture["extractions"][extraction["id"]] = source
        uid = extraction["units"][0]["id"]
        self.fixture["memberships"][uid] = None
        self.fixture["invalid"][uid] = False
        self.select(entry, extraction["id"], "automatic")
        return extraction["id"], uid

    def select(self, entry, extraction, mode):
        self.fixture["selections"][entry] = {
            "entry_id": entry, "current_extraction_id": extraction, "selection_mode": mode}

    def source(self, label):
        payload = {"schema_version": "learning_capture_v1", "capture_id": f"flh035-{label}",
                   "source": "manual", "original_input": f"Je ne parle pas. [{label}]",
                   "original_context": f"Synthetic FLH-035 source {label}",
                   "analysis": {"category": "grammar", "explanation": "La négation encadre le verbe.",
                                "confidence": 0.95, "uncertainty": ""}}
        receipt = self.write("POST", "/captures", payload)
        eid = receipt["entry_id"]
        self.fixture["entries"][eid] = {k: payload[k] for k in ("original_input", "original_context")}
        xid, uid = self.extract(eid)
        require(self.fixture["extractions"][xid]["source_analysis_id"] == receipt["analysis_id"],
                "imported analysis attribution")
        require(self.fixture["extractions"][xid]["source_feedback_id"] is None, "unreviewed provenance")
        return eid, xid, uid

    def concept(self, target):
        response = self.write("POST", "/concepts", {"identity": {
            "target": target, "pedagogical_intent": "grammar", "scope": "flh035 synthetic",
            "identity_features": {"language": "français"}}})
        cid = response["concept"]["id"]
        self.fixture["concepts"][cid] = {"supporting_unit_ids": [], "preferred_unit_id": None}
        return cid

    def same(self, unit, concept, replace=False):
        suffix = "concept-membership" if replace else "concept-links/same"
        link = self.write("PUT" if replace else "POST", f"/knowledge-units/{unit}/{suffix}",
                          {"concept_id": concept}, expected=200 if replace else 201)
        self.fixture["history"][link["id"]] = link
        self.fixture["memberships"][unit] = concept

    def checkpoint(self, name, shared_support, preferred, moved_support=()):
        self.fixture["concepts"][self.shared] = {
            "supporting_unit_ids": list(shared_support), "preferred_unit_id": preferred}
        self.fixture["concepts"][self.moved] = {
            "supporting_unit_ids": list(moved_support), "preferred_unit_id": None}
        before, calls = snapshot(self.h.active / "app.db"), self.h.calls()
        root = read_view(lambda path: self.h.request("GET", path), self.fixture)
        prefixed = read_view(lambda path: self.h.request("GET", "/api" + path), self.fixture)
        verify_view(root, self.fixture)
        for state in ("active", "orphaned"):
            expected_catalog = [c for c in root["catalog"] if c["state"] == state]
            for prefix in ("", "/api"):
                actual = self.h.request("GET", prefix + "/concepts?state=" + state)["concepts"]
                require(actual == expected_catalog, "state filter/order mismatch")
        require(root == prefixed, "root versus production /api mismatch")
        require(snapshot(self.h.active / "app.db") == before, "read-only GET sequence changed tables")
        require(self.h.calls() == calls, "read-only GET sequence invoked provider")
        self.cases.append({"case": name, "result": "PASS", "evidence_type": "HTTP + SQLite",
                           "expected": copy.deepcopy(self.fixture), "actual": root,
                           "provider_counters": calls, "unchanged_tables": True})
        print("PASS " + name, flush=True)
        return root

    def run(self):
        a, x1, u1 = self.source("a")
        _, _, ub = self.source("b")
        # Deliberately create nonalphabetical catalog order to expose ID ordering.
        self.shared = self.concept("négation ne pas")
        self.moved = self.concept("accord adjectif")
        empty = self.concept("être auxiliaire")
        self.same(u1, self.shared)
        self.same(ub, self.shared)
        self.checkpoint("two independent supporting sources; preferred unset", [u1, ub], None)
        self.write("POST", f"/concepts/{self.shared}/preferred-unit", {"unit_id": u1}, expected=200)
        self.checkpoint("explicit preferred representation", [u1, ub], u1)
        relation = self.write("POST", f"/knowledge-units/{ub}/concept-links/relation",
                              {"concept_id": empty, "relation": "related"})
        self.fixture["history"][relation["id"]] = relation
        self.checkpoint("RELATED history gives no support to empty concept", [u1, ub], u1)
        analysis = self.fixture["extractions"][x1]["source_analysis_id"]
        feedback = self.write("POST", f"/analyses/{analysis}/feedback",
                              {"status": "accepted", "user_note": "FLH-035 provenance fixture"})
        x2, u2 = self.extract(a)
        newer = self.fixture["extractions"][x2]
        require(newer["version"] == 2 and newer["source_analysis_id"] == analysis
                and newer["source_feedback_id"] == feedback["id"], "new extraction provenance")
        self.checkpoint("latest extraction: historical preferred is not supporting", [ub], u1)
        self.write("PUT", f"/entries/{a}/current-extraction", {"extraction_id": x1}, expected=200)
        self.select(a, x1, "pinned")
        self.checkpoint("pin older extraction restores its support", [u1, ub], u1)
        self.write("POST", f"/knowledge-units/{ub}/invalid", expected=200)
        self.fixture["memberships"][ub] = None
        self.fixture["invalid"][ub] = True
        self.checkpoint("INVALID clears current SAME", [u1], u1)
        self.write("POST", f"/knowledge-units/{ub}/invalid/restore", expected=200)
        self.fixture["invalid"][ub] = False
        self.checkpoint("restore does not restore SAME", [u1], u1)
        self.write("DELETE", f"/entries/{a}/current-extraction", expected=200)
        self.select(a, x2, "automatic")
        self.checkpoint("unsupported concept retains historical preferred", [], u1)
        self.same(u1, self.moved, replace=True)
        self.checkpoint("reassignment clears invalid preferred; historical SAME preserved", [], None)
        self.write("PUT", f"/entries/{a}/current-extraction", {"extraction_id": x1}, expected=200)
        self.select(a, x1, "pinned")
        self.checkpoint("support follows changed current membership", [], None, [u1])
        self.same(u2, self.shared)
        self.write("DELETE", f"/entries/{a}/current-extraction", expected=200)
        self.select(a, x2, "automatic")
        self.write("POST", f"/concepts/{self.shared}/preferred-unit", {"unit_id": u2}, expected=200)
        self.checkpoint("new current source supports stable Concept", [u2], u2)
        self.write("POST", f"/knowledge-units/{u2}/admission-overrides", {"decision": "suppressed", "reason": "other"})
        self.checkpoint("suppressed SAME keeps preferred but loses support", [], u2)
        self.write("POST", f"/knowledge-units/{u2}/admission-overrides", {"decision": "active"})
        stable = self.checkpoint("admission restoration recovers support", [u2], u2)
        before, calls = snapshot(self.h.active / "app.db"), self.h.calls()
        self.h.replace()
        require(snapshot(self.h.active / "app.db") == before and self.h.calls() == calls,
                "restart changed persistent data or provider counters")
        restarted = self.checkpoint("restart preserves catalog, evidence and authority", [u2], u2)
        require(stable == restarted, "restart changed HTTP read models")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="new evidence file outside repository")
    args = parser.parse_args()
    target = args.report.resolve()
    require(not target.exists() and ROOT not in target.parents and target.parent.is_dir(), "unsafe report path")
    os.umask(0o077)
    harness = Harness("native")
    probe = Probe(harness)
    error = None
    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f"signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        harness.prepare()
        harness.start()
        probe.run()
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        print("FAIL " + error, flush=True)
    finally:
        log = (harness.run_dir / "service.log").read_text()
        cleanup = harness.cleanup()
        report = {"phase": "A", "scope": "existing contracts; FLH-034 not accepted",
                  "status": "FAIL" if error or cleanup else "PASS", "error": error,
                  "cases": probe.cases, "commands": harness.commands,
                  "native_compiler": getattr(harness, "compiler", None),
                  "source_sha256": getattr(harness, "manifest", {}),
                  "checks_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in sorted(HERE.glob("*.py"))},
                  "launcher_sha256": harness.harness_manifest, "service_log": log,
                  "cleanup_errors": cleanup, "temporary_directory_removed": not harness.run_dir.exists(),
                  "pending": ["FLH-034 search/rendering/navigation", "documented two-minute demo",
                              "release assets/container delivery", "actual browser"]}
        with target.open("x") as output:
            json.dump(report, output, indent=2, ensure_ascii=False)
        print(f"RESULT={report['status']} CASES={len(probe.cases)} CLEANUP={cleanup}", flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
