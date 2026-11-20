"""Tests for owner_preflight.py (R2-087) against a stub `git` (agents never run Git)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "owner_preflight.py")
STUB = """#!/bin/sh
# stub git: answers from $STUB_STATE (a JSON file); never touches a repository
exec python3 -c '
import json, os, sys
s = json.load(open(os.environ["STUB_STATE"]))
a = sys.argv[1:]
if a[0] == "rev-parse":
    ref = a[1].replace("^{tree}", "")
    t = s["trees"].get(ref)
    print(t) if t else sys.exit(128)
elif a[0] == "status":
    print(s.get("status", ""), end="")
elif a[0] == "merge-base":
    sys.exit(0 if a[3] in s.get("descends", []) else 1)
else:
    sys.exit(2)
' "$@"
"""


class OwnerPreflight(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.td)
        os.makedirs(os.path.join(self.td, "bin"))
        with open(os.path.join(self.td, "bin", "git"), "w") as fh:
            fh.write(STUB)
        os.chmod(os.path.join(self.td, "bin", "git"), 0o755)
        self.expect = os.path.join(self.td, "expect.json")
        with open(self.expect, "w") as fh:
            json.dump({"base_tree": "b" * 40, "lanes": {"demo-refresh": "d" * 40},
                       "states": [{"after": "demo-refresh", "tree_id": "1" * 40}]}, fh)
        self.state = {"trees": {"origin/main": "b" * 40, "lane/demo": "d" * 40, "HEAD": "1" * 40}, "descends": ["lane/demo"]}

    def run_it(self, *extra):
        st = os.path.join(self.td, "state.json")
        with open(st, "w") as fh:
            json.dump(self.state, fh)
        env = dict(os.environ, PATH=os.path.join(self.td, "bin") + os.pathsep + os.environ["PATH"], STUB_STATE=st)
        return subprocess.run([sys.executable, "-B", TOOL, self.expect, "--ref", "main=origin/main",
                               "--ref", "demo-refresh=lane/demo", *extra], capture_output=True, text=True, env=env)

    def test_ready_when_everything_matches(self):
        r = self.run_it("--after-merge", "demo-refresh")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("READY: 4/4 checks pass", r.stdout)

    def test_stops_when_main_moved_or_a_lane_holds_other_bytes(self):
        self.state["trees"]["origin/main"] = "c" * 40
        self.state["trees"]["lane/demo"] = "e" * 40
        self.state["status"] = " M x\n"
        r = self.run_it()
        self.assertEqual(r.returncode, 1)
        self.assertIn("STOP\tbase", r.stdout)
        self.assertIn("STOP\tclean", r.stdout)
        self.assertIn("STOP\tlane demo-refresh", r.stdout)
        self.assertIn("main moved since the rehearsal", r.stdout)


if __name__ == "__main__":
    unittest.main()
