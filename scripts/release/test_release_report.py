#!/usr/bin/env python3
"""Tests for scripts/release/release_report.py on the synthetic fixture (standard library only).

  python3 -B -m unittest discover -s scripts/release -p 'test_*.py'
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "release_report.py")
FIX = os.path.join(HERE, "fixtures", "release-report", "ready")


def run(*args):
    return subprocess.run([sys.executable, "-B", TOOL, *args], capture_output=True, text=True)


class ReleaseReport(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.dir = os.path.join(self.td, "r")
        shutil.copytree(FIX, self.dir)
        self.path = os.path.join(self.dir, "report.json")

    def tearDown(self):
        shutil.rmtree(self.td)

    def edit(self, fn):
        with open(self.path) as fh:
            rep = json.load(fh)
        fn(rep)
        with open(self.path, "w") as fh:
            json.dump(rep, fh)

    def gate(self, rep, gid):
        return next(g for g in rep["gates"] if g["id"] == gid)

    def test_fixture_is_ready_for_local_rehearsal(self):
        r = run("check", self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("READY", r.stdout)

    def test_staging_target_is_blocked_by_owner_gates_with_next_actions(self):
        self.edit(lambda rep: rep.update(target="staging"))
        r = run("terminal", self.path)
        self.assertEqual(r.returncode, 1)
        self.assertIn("BLOCKED for staging", r.stdout)
        for gid in ("aws-plan-check", "staging-identity"):
            self.assertRegex(r.stdout, rf"! UNAVAILABLE +{gid}")
        self.assertIn("next: owner: deploy/aws/private-staging/RUNBOOK.md §3.2", r.stdout)

    def test_failed_and_pending_gates_block(self):
        def f(rep):
            g = self.gate(rep, "python-suites")
            g.update(status="fail", next_action="rerun the failing suite")
            self.gate(rep, "staging-preflight").update(status="pending", next_action="run the preflight", evidence=None)
        self.edit(f)
        r = run("check", self.path)
        self.assertEqual(r.returncode, 1)
        self.assertIn("python-suites FAIL", r.stdout)
        self.assertIn("staging-preflight PENDING", r.stdout)

    def test_evidence_for_another_bundle_or_tree_is_stale(self):
        def f(rep):
            self.gate(rep, "bundle-verify")["evidence"]["bundle"] = "flh-staging-aaaaaaaaaaaa"
            self.gate(rep, "python-suites")["evidence"]["tree_id"] = "b" * 40
        self.edit(f)
        r = run("terminal", self.path)
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"! STALE +bundle-verify +evidence is for bundle flh-staging-aaaaaaaaaaaa")
        self.assertRegex(r.stdout, r"! STALE +python-suites +evidence is for source tree bbbbbbbbbbbb")

    def test_changed_or_missing_evidence_blocks(self):
        with open(os.path.join(self.dir, "evidence", "python-suites.txt"), "a") as fh:
            fh.write("edited later\n")
        os.unlink(os.path.join(self.dir, "evidence", "staging-preflight.txt"))
        r = run("check", self.path)
        self.assertEqual(r.returncode, 1)
        self.assertIn("python-suites CHANGED", r.stdout)
        self.assertIn("staging-preflight UNAVAILABLE", r.stdout)

    def test_invalid_reports_exit_2(self):
        for fn in (lambda rep: rep.update(format="other/v9"),
                   lambda rep: self.gate(rep, "aws-plan-check").update(next_action=None),
                   lambda rep: self.gate(rep, "bundle-verify").update(evidence=None),
                   lambda rep: rep["gates"].append(dict(rep["gates"][0]))):
            shutil.copy(os.path.join(FIX, "report.json"), self.path)
            self.edit(fn)
            self.assertEqual(run("check", self.path).returncode, 2)

    def test_markdown_is_deterministic_and_html_links_evidence(self):
        a, b = run("markdown", self.path), run("markdown", self.path)
        self.assertEqual(a.stdout, b.stdout)
        self.assertIn("| `python-suites` | test | agent | yes | **PASS** |", a.stdout)
        self.assertIn("## Draft versus ready", a.stdout)
        h = os.path.join(self.td, "d.html")
        r = run("html", self.path, "--out", h)
        self.assertEqual(r.returncode, 0)
        with open(h) as fh:
            page = fh.read()
        import re
        hrefs = re.findall(r'<a href="([^"]+)">', page)
        self.assertEqual(len(hrefs), 4)
        for href in hrefs:                                   # relative to where the page was written
            self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(h), href)), href)
        self.assertIn("Rollback target", page)
        self.assertNotIn("<script", page)       # static, offline

    def test_attestation_names_tools_and_verified_digests(self):
        r = run("attest", self.path)
        self.assertEqual(r.returncode, 0, r.stderr)
        att = json.loads(r.stdout)
        self.assertEqual(att["format"], "flh-release-attestation/v1")
        self.assertEqual(att["candidate"]["transfer_sha256"], "1" * 64)
        self.assertEqual(att["gates"]["bundle-verify"]["state"], "pass")
        self.assertRegex(att["tools"]["scripts/release/release_report.py"], r"^[0-9a-f]{64}$")
        self.assertIsNone(att["pinned_inputs"])
        self.assertEqual(att["tools"]["docker_server_local"], "not probed (--probe-docker)")   # no daemon contact

    def test_all_views_agree_on_the_verdict(self):
        for target, want in (("local-rehearsal", "READY"), ("staging", "BLOCKED")):
            self.edit(lambda rep: rep.update(target=target))
            check, term, md = (run(v, self.path).stdout for v in ("check", "terminal", "markdown"))
            run("html", self.path, "--out", os.path.join(self.td, "x.html"))
            with open(os.path.join(self.td, "x.html")) as fh:
                page = fh.read()
            self.assertTrue(check.startswith(want + ":"), check)
            self.assertTrue(term.startswith(f"{want} for {target}:"), term)
            self.assertIn(f"**{want}** for target `{target}`", md)
            self.assertIn(f"<span class='verdict {want}'>{want}</span>", page)


def load_tool():
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("release_report_t", TOOL)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


class ViewsAgree(unittest.TestCase):
    """Item 092: check, terminal, Markdown and HTML show the same verdict and the same per-gate state as the
    evaluator, for every scenario fixture (ready, staging, fail, pending, skipped, stale, changed, missing)."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.rr = load_tool()

    def tearDown(self):
        shutil.rmtree(self.td)

    def scenario(self, name, edit):
        d = os.path.join(self.td, name)
        shutil.copytree(FIX, d)
        p = os.path.join(d, "report.json")
        with open(p) as fh:
            rep = json.load(fh)
        edit(rep, d)
        with open(p, "w") as fh:
            json.dump(rep, fh)
        return p

    @staticmethod
    def g(rep, gid):
        return next(x for x in rep["gates"] if x["id"] == gid)

    def scenarios(self):
        def stage(rep, d):
            rep["target"] = "staging"

        def fail(rep, d):
            self.g(rep, "python-suites").update(status="fail", next_action="rerun the suite")

        def pending(rep, d):
            self.g(rep, "staging-preflight").update(status="pending", next_action="run the preflight")

        def skipped(rep, d):
            self.g(rep, "rollback-target").update(status="skipped", next_action="give --rollback")

        def stale(rep, d):
            self.g(rep, "bundle-verify")["evidence"]["tree_id"] = "f" * 40

        def changed(rep, d):
            with open(os.path.join(d, "evidence", "python-suites.txt"), "a") as fh:
                fh.write("edited by hand\n")

        def missing(rep, d):
            os.unlink(os.path.join(d, "evidence", "staging-preflight.txt"))
        return [("ready", lambda rep, d: None), ("staging", stage), ("fail", fail), ("pending", pending),
                ("skipped", skipped), ("stale", stale), ("changed", changed), ("missing", missing)]

    def test_every_view_matches_the_evaluator(self):
        import re
        seen = set()
        for name, edit in self.scenarios():
            with self.subTest(scenario=name):
                p = self.scenario(name, edit)
                rep = self.rr.load(p)
                ev = self.rr.evaluate(rep, os.path.dirname(p))
                want = {g["id"]: self.rr.MARK[g["effective"]] for g in ev["gates"]}
                seen |= set(want.values())
                check, term, md = (run(v, p).stdout for v in ("check", "terminal", "markdown"))
                html_path = os.path.join(self.td, name + ".html")
                run("html", p, "--out", html_path)
                with open(html_path) as fh:
                    page = fh.read()
                t = dict((m.group(2), m.group(1)) for m in re.finditer(r"^[!\- ] ([A-Z]+) +([a-z][a-z-]+) ", term, re.M))
                m = dict((x.group(1), x.group(2)) for x in re.finditer(r"^\| `([a-z-]+)` \|[^\n]*?\| \*\*([A-Z]+)\*\* \|", md, re.M))
                h = {}
                for row in re.finditer(r"<tr><td><code>([a-z-]+)</code>(.*?)</tr>", page, re.S):
                    cell = re.search(r"<td class='s [a-z]+'>([A-Z]+)</td>", row.group(2))
                    if cell:
                        h[row.group(1)] = cell.group(1)
                self.assertEqual(t, want, "terminal")
                self.assertEqual(m, want, "markdown")
                self.assertEqual(h, want, "html")
                v = ev["verdict"]
                self.assertTrue(check.startswith(v + ":"), check)
                self.assertTrue(term.startswith(f"{v} for {rep['target']}:"), term)
                self.assertIn(f"**{v}** for target `{rep['target']}`", md)
                self.assertIn(f"<span class='verdict {v}'>{v}</span>", page)
        self.assertEqual(seen, set(self.rr.MARK.values()))     # the scenarios cover every state


class OperatorViews(unittest.TestCase):
    """R2-061 to R2-068: sources, commands, stale versus failed, rollback with its ledger, a single next action for
    browser evidence of other bytes, links after a move, narrow terminals, one row model for Markdown and HTML."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.td)
        self.dir = os.path.join(self.td, "r")
        shutil.copytree(FIX, self.dir)
        self.path = os.path.join(self.dir, "report.json")
        self.rr = load_tool()

    def ev(self, rep=None):
        rep = rep or self.rr.load(self.path)
        return rep, self.rr.evaluate(rep, self.dir)

    def receipt(self, browser_tree=None):
        """A minimal integration receipt for the fixture's tree, every required check passing."""
        rep = self.rr.load(self.path)
        tree = rep["candidate"]["revision"]["tree_id"]
        rd = os.path.join(self.td, "receipt")
        os.makedirs(os.path.join(rd, "evidence"))
        sys.path.insert(0, HERE)
        import integration_receipt as IR
        checks = []
        for cid in IR.REQUIRED["local-rehearsal"]:
            p = os.path.join(rd, "evidence", cid + ".log")
            with open(p, "w") as fh:
                fh.write("ok\n")
            t = browser_tree if (browser_tree and cid in self.rr.BROWSER) else tree
            checks.append({"id": cid, "title": cid, "scope": "candidate", "required_for": ["local-rehearsal", "staging"],
                           "status": "pass", "tree_id": t, "counts": {"ran": 3, "passed": 3},
                           "evidence": {"path": f"evidence/{cid}.log", "sha256": hashlib.sha256(b"ok\n").hexdigest()}})
        with open(os.path.join(rd, "receipt.json"), "w") as fh:
            json.dump({"format": IR.FORMAT, "candidate": {"tree_id": tree, "files": 1}, "lanes": [
                {"lane": "demo-refresh", "seal_id": "demo rehearsal", "seal_digest": "a" * 64, "tree_id": "b" * 40}],
                "pending": [{"id": "speaking-ci", "lane": "release", "why": "after extraction"}], "checks": checks}, fh)
        return rd, tree

    def collect_gates(self, rd, tree):
        made = {}

        def evidence(name, text, **bind):
            p = os.path.join(self.dir, "evidence", name)
            with open(p, "w") as fh:
                fh.write(text)
            made[name] = p
            return dict({"path": f"evidence/{name}", "sha256": hashlib.sha256(text.encode()).hexdigest()}, **bind)
        sources, gates = self.rr.receipt_gates(rd, "local-rehearsal", tree, evidence)
        rep = self.rr.load(self.path)
        rep["gates"] += gates
        rep["sources"] = sources
        with open(self.path, "w") as fh:
            json.dump(rep, fh)
        return self.ev()

    def test_sources_and_receipt_gates_shown_in_every_view(self):
        rd, tree = self.receipt()
        rep, ev = self.collect_gates(rd, tree)
        eff = {g["id"]: g["effective"] for g in ev["gates"]}
        self.assertEqual((eff["integration-receipt"], eff["browser-evidence"]), ("pass", "pass"))
        md = run("markdown", self.path).stdout
        self.assertIn("| demo-refresh | demo rehearsal | `aaaaaaaaaaaaaaaa` | `bbbbbbbbbbbb` |", md)
        self.assertIn("`speaking-ci` (release)", md)
        h = os.path.join(self.td, "x.html")
        run("html", self.path, "--out", h)
        with open(h) as fh:
            self.assertIn("Sources (sealed handoffs)", fh.read())
        self.assertIn("source    demo-refresh: seal aaaaaaaaaaaa", run("terminal", self.path, "--width", "100").stdout)

    def test_browser_evidence_for_other_bytes_is_stale_with_one_next_action(self):
        rd, tree = self.receipt(browser_tree="c" * 40)
        rep, ev = self.collect_gates(rd, tree)
        g = next(g for g in ev["gates"] if g["id"] == "browser-evidence")
        self.assertEqual(g["effective"], "stale")
        self.assertEqual(g["next"].count("integration_battery.sh"), 1)
        self.assertIn("learning practice demo", g["next"])
        self.assertEqual(ev["verdict"], "BLOCKED")
        self.assertIn("1 stale (old evidence, rerun; not failures)", self.rr.tallies(ev))
        self.assertIn("0 failed", self.rr.tallies(ev))

    def test_commands_list_starts_with_the_fastest_check(self):
        r = run("commands", self.path)
        lines = r.stdout.splitlines()
        self.assertTrue(lines[0].startswith("# check (re-evaluates saved evidence"))
        self.assertIn("release_report.py check", lines[1])
        self.assertIn("python3 -B scripts/ci/python_suites.py", r.stdout)

    def test_rollback_availability_and_ledger_read_together(self):
        rep, _ = self.ev()
        self.assertIn("verifies; ledger: knows 21 migration(s), the candidate ships 21: compatible", self.rr.rollback_line(rep))
        rep["rollback_target"]["migrations"] = 20
        self.assertIn("NOT compatible", self.rr.rollback_line(rep))
        rep["rollback_target"] = None
        self.assertIn("none given", self.rr.rollback_line(rep))

    def test_links_work_after_the_report_moves(self):
        moved = os.path.join(self.td, "elsewhere", "deep", "r2")
        shutil.copytree(self.dir, moved)
        shutil.rmtree(self.dir)
        out = os.path.join(self.td, "pages", "dash.html")
        os.makedirs(os.path.dirname(out))
        run("html", os.path.join(moved, "report.json"), "--out", out)
        import re
        with open(out) as fh:
            hrefs = re.findall(r'<a href="([^"]+)">', fh.read())
        self.assertTrue(hrefs)
        for href in hrefs:
            self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(out), href)), href)

    def test_terminal_fits_a_narrow_terminal(self):
        rd, tree = self.receipt(browser_tree="c" * 40)
        self.collect_gates(rd, tree)
        for width in (40, 60, 80):
            text = run("terminal", self.path, "--width", str(width)).stdout
            self.assertTrue(all(len(line) <= width for line in text.splitlines()), (width, text))
            self.assertRegex(text, r"(?m)^! STALE +browser-evidence")

    def test_markdown_and_html_render_the_same_rows(self):
        import re
        import html as H
        rd, tree = self.receipt(browser_tree="c" * 40)
        rep, ev = self.collect_gates(rd, tree)
        md = run("markdown", self.path).stdout
        h = os.path.join(self.td, "x.html")
        run("html", self.path, "--out", h)
        with open(h) as fh:
            page = fh.read()
        rows = self.rr.gate_rows(rep, ev)
        for r in rows:
            self.assertIn(f"| `{r['id']}` | {r['kind']} | {r['owner']} | {'yes' if r['required'] else 'no'} | **{r['state']}** | {r['why']}", md)
            self.assertIn(f"<td class='s {r['effective']}'>{r['state']}</td><td>{H.escape(r['why'])}", page)
            if r["next"]:
                self.assertIn(r["next"], md)
                self.assertIn(H.escape(r["next"]), page)


class OwnerFacing(unittest.TestCase):
    """R2-075 and R2-080: the owner release record, and a status naming exactly which owner gate blocks staging."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.td)
        self.dir = os.path.join(self.td, "r")
        shutil.copytree(FIX, self.dir)
        self.path = os.path.join(self.dir, "report.json")

    def test_record_has_digest_and_policy(self):
        r = run("record", self.path)
        self.assertIn("| Transfer SHA-256 (type this; never copy it from the host or the bucket) | `" + "1" * 64 + "` |", r.stdout)
        self.assertIn("Verification policy", r.stdout)
        self.assertIn("Nothing blocks this target.", r.stdout)

    def test_staging_status_names_the_owner_gates_only(self):
        with open(self.path) as fh:
            rep = json.load(fh)
        rep["target"] = "staging"
        with open(self.path, "w") as fh:
            json.dump(rep, fh)
        r = run("check", self.path)
        self.assertEqual(r.returncode, 1)
        self.assertIn("blocked for staging ONLY by owner-only gate(s): aws-plan-check (UNAVAILABLE: owner:", r.stdout)
        self.assertIn("staging-identity (UNAVAILABLE: owner:", r.stdout)
        rep["gates"][2]["evidence"]["sha256"] = "0" * 64                  # an agent gate breaks too
        with open(self.path, "w") as fh:
            json.dump(rep, fh)
        r = run("check", self.path)
        self.assertIn("blocked first by 1 agent gate(s): python-suites (CHANGED); then by owner-only gate(s)", r.stdout)


class DocumentedSurface(unittest.TestCase):
    """Item 091: docs/RELEASE.md lists exactly the gates collect can write and the effective states."""

    def test_doc_matches_the_code(self):
        import re
        with open(os.path.join(HERE, "..", "..", "docs", "RELEASE.md")) as fh:
            doc = fh.read().split("## Release control dashboard", 1)[1].split("\n## ", 1)[0]
        with open(TOOL) as fh:
            src = fh.read()
        gates_code = set(re.findall(r'gates\.append\(\{"id": "([a-z-]+)"', src))
        gates_doc = set(re.findall(r"^\| `([a-z-]+)` \| (?:agent|owner) \|", doc, re.M))
        self.assertEqual(gates_doc, gates_code)
        states = set(load_tool().MARK)
        for st in states:
            self.assertIn(f"`{st}`", doc)
        for opt in ("--candidate", "--rollback", "--source", "--target", "--plan-json", "--host-status", "--receipt", "--out"):
            self.assertIn(f"`{opt}", doc)


if __name__ == "__main__":
    unittest.main()
