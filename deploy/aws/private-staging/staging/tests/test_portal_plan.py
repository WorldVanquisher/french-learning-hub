"""Tests for the proposed portal routing plan and its offline simulator (synthetic requests only)."""
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "portal_check.py")
PLAN = os.path.join(HERE, "..", "portal", "routing_plan.json")
REPO = os.path.realpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
GO_BOUNDARY = os.path.join(REPO, "internal", "transport", "http", "public_demo.go")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import portal_check  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, "-I", "-B", TOOL, *args], capture_output=True, text=True)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class PortalPlan(unittest.TestCase):
    def setUp(self):
        self.plan = read_json(PLAN)

    def test_committed_plan_validates_and_simulates(self):
        self.assertEqual(run("validate").returncode, 0)
        r = run("simulate", "--json")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(json.loads(r.stdout)["mismatches"], 0)

    def test_private_routes_never_reach_a_server(self):
        for host in ("flh.vanquisher.world", "demo.flh.vanquisher.world"):
            for method, path in (("GET", "/entries"), ("GET", "/api/entries"), ("POST", "/captures"),
                                 ("GET", "/annotation-dataset/v1"), ("POST", "/knowledge-units/1/concept-links/same")):
                with self.subTest(host=host, path=path):
                    self.assertIn(portal_check.route(self.plan, host, method, path), (404, 405))
        self.assertEqual(portal_check.route(self.plan, "app.flh.vanquisher.world", "GET", "/entries"), "no-record")

    def test_mirror_matches_the_go_allowlist(self):
        if not os.path.exists(GO_BOUNDARY):
            self.skipTest("public_demo.go not in this tree")
        with open(GO_BOUNDARY, encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("var publicDemoAPIRoutes")
        block = src[start:src.index("\n}", start)]
        go = re.findall(r"regexp\.MustCompile\(`([^`]+)`\)", block)
        self.assertEqual(go, portal_check.DEMO_API)
        self.assertIn('r.Method != http.MethodGet && r.Method != http.MethodHead', src)

    def invalid(self, mutate, needle):
        plan = copy.deepcopy(self.plan)
        mutate(plan)
        problems = portal_check.validate(plan)
        self.assertTrue(any(needle in p for p in problems), problems)

    def test_validation_findings(self):
        self.invalid(lambda p: p["hosts"]["app.flh.vanquisher.world"].update(dns={"type": "A", "value": "x"}), "no DNS record")
        self.invalid(lambda p: p["hosts"]["flh.vanquisher.world"].update(role="public-demo"), "no host has role portal")
        self.invalid(lambda p: p["changes"][0].pop("rollback"), "lacks rollback")
        self.invalid(lambda p: p["hosts"]["flh.vanquisher.world"]["rules"][0]["methods"].append("POST"), "GET/HEAD only")
        self.invalid(lambda p: p.update(staging="demo-staging.flh.vanquisher.world"), "no host name")

    def test_a_drifted_plan_fails_the_simulation(self):
        plan = copy.deepcopy(self.plan)
        plan["hosts"]["demo.flh.vanquisher.world"].pop("boundary")
        plan["hosts"]["demo.flh.vanquisher.world"]["rules"] = [{"methods": ["GET", "POST"], "paths": ["/*"], "outcome": 200}]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "plan.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(plan, fh)
            r = run("simulate", p, "--json")
        self.assertEqual(r.returncode, 1)
        self.assertGreater(json.loads(r.stdout)["mismatches"], 0)


if __name__ == "__main__":
    unittest.main()
