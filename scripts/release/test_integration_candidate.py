"""Tests for integration_candidate.py and integration_receipt.py on small synthetic lanes (no Git)."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import integration_candidate as IC  # noqa: E402
import integration_receipt as IR  # noqa: E402

EN = '''export const en = {
  "a.one": "One {n}",
  "a.two": "Two",
  "b.three": "Three",
} satisfies Record<string, string>;
'''
ZH = '''export const zhCN: Record<MessageKey, string> = {
  "a.one": "一 {n}",
  "a.two": "二",
  "b.three": "三",
};
'''


def sha(b):
    return hashlib.sha256(b).hexdigest()


def write(root, rel, data, mode=0o644):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(data if isinstance(data, bytes) else data.encode())
    os.chmod(full, mode)


def make_tar(path, files, symlinks=None):
    with tarfile.open(path, "w") as tf:
        for rel, (data, mode) in sorted(files.items()):
            data = data if isinstance(data, bytes) else data.encode()
            ti = tarfile.TarInfo(rel)
            ti.size, ti.mode, ti.mtime = len(data), mode, 0
            tf.addfile(ti, io.BytesIO(data))
        for rel, target in (symlinks or {}).items():
            ti = tarfile.TarInfo(rel)
            ti.type, ti.linkname = tarfile.SYMTYPE, target
            tf.addfile(ti)


def seal(d):
    lines = []
    for dp, _, fns in os.walk(d):
        for f in sorted(fns):
            if f == "SHA256SUMS":
                continue
            full = os.path.join(dp, f)
            with open(full, "rb") as fh:
                lines.append(f"{sha(fh.read())}  ./{os.path.relpath(full, d)}")
    with open(os.path.join(d, "SHA256SUMS"), "w") as fh:
        fh.write("\n".join(sorted(lines, key=lambda x: x[66:])) + "\n")
    with open(os.path.join(d, "SHA256SUMS"), "rb") as fh:
        return sha(fh.read())


class Fixture(unittest.TestCase):
    """A base and three lanes: 'docs' (delta tar), 'web' (whole-tree tar), 'tools' (hash manifest + store)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ic-test-")
        self.addCleanup(shutil.rmtree, self.tmp)
        t = self.tmp
        self.base = os.path.join(t, "base")
        write(self.base, "AGENTS.md", "agents\n")
        os.symlink("AGENTS.md", os.path.join(self.base, "CLAUDE.md"))
        write(self.base, "docs/RELEASE.md", "one\ntwo\nthree\nfour\nfive\nsix\nseven\n")
        write(self.base, "web/src/i18n/en.ts", EN)
        write(self.base, "web/src/i18n/zh-CN.ts", ZH)
        write(self.base, "tools/run.sh", "#!/bin/sh\necho base\n", 0o755)
        write(self.base, "old.txt", "remove me\n")
        self.base_tid = IC.BI.tree_id(self.base, IC.BI.scan(self.base))
        # lane docs: delta tar adds a file, edits RELEASE.md near the top, deletes old.txt
        self.docs = os.path.join(t, "h-docs")
        os.makedirs(os.path.join(self.docs, "snapshot"))
        rel = "zero\none\ntwo\nthree\nfour\nfive\nsix\nseven\n"
        make_tar(os.path.join(self.docs, "snapshot/s.tar"),
                 {"docs/NEW.md": ("new\n", 0o644), "docs/RELEASE.md": (rel, 0o644),
                  "tools/new.sh": ("#!/bin/sh\n", 0o755)})
        with open(os.path.join(self.docs, "snapshot/paths.txt"), "w") as fh:
            fh.write("A docs/NEW.md\nM docs/RELEASE.md\nA tools/new.sh\nD old.txt\n")
        # lane web: whole tree; adds a catalog key in both catalogs
        self.web = os.path.join(t, "h-web")
        os.makedirs(os.path.join(self.web, "seal"))
        files = {}
        for p, _ in IC.BI.scan(self.base).items():
            full = os.path.join(self.base, p)
            if os.path.islink(full):
                continue
            with open(full, "rb") as fh:
                files[p] = (fh.read(), 0o755 if os.stat(full).st_mode & 0o111 else 0o644)
        files["web/src/i18n/en.ts"] = (EN.replace('  "a.one"', '  "a.web": "Web",\n  "a.one"'), 0o644)
        files["web/src/i18n/zh-CN.ts"] = (ZH.replace('  "a.one"', '  "a.web": "网",\n  "a.one"'), 0o644)
        make_tar(os.path.join(self.web, "seal/tree.tar"), files, {"CLAUDE.md": "AGENTS.md"})
        # lane tools: a full hash manifest (no modes, no symlinks), bytes in a hash-only store
        self.tools = os.path.join(t, "h-tools")
        self.store = os.path.join(t, "store")
        shutil.copytree(self.base, self.store, symlinks=True)
        write(self.store, "web/src/i18n/en.ts", EN.replace('  "a.two": "Two",\n', '  "a.two": "Two",\n  "a.tools": "Tools",\n'))
        write(self.store, "web/src/i18n/zh-CN.ts", ZH.replace('  "a.two": "二",\n', '  "a.two": "二",\n  "a.tools": "工具",\n'))
        write(self.store, "docs/RELEASE.md", "one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\n")
        os.makedirs(self.tools)
        with open(os.path.join(self.tools, "worktree.manifest"), "w") as fh:
            for p, (mode, h) in sorted(IC.BI.scan(self.store).items()):
                if mode != "120000":
                    fh.write(f"{h}  {p}\n")
        self.digests = {"docs": seal(self.docs), "web": seal(self.web), "tools": seal(self.tools)}

    def selection(self, **over):
        S = {"format": IC.SELECTION, "base": {"dir": self.base, "tree_id": self.base_tid},
             "order": ["web", "docs", "tools"],
             "lanes": {
                 "docs": {"seal": {"dir": self.docs, "digest": self.digests["docs"], "id": "docs-1"},
                          "snapshot": {"kind": "delta-tar", "tar": "snapshot/s.tar", "paths": "snapshot/paths.txt"}},
                 "web": {"seal": {"dir": self.web, "digest": self.digests["web"], "id": "web-1"},
                         "snapshot": {"kind": "tree-tar", "tar": "seal/tree.tar"}},
                 "tools": {"seal": {"dir": self.tools, "digest": self.digests["tools"], "id": "tools-1"},
                           "snapshot": {"kind": "manifest", "manifest": "worktree.manifest", "omits_symlinks": True},
                           "stores": [{"kind": "dir", "label": "store", "path": self.store, "modes": True}]}},
             "pending_proposals": [{"id": "later", "lane": "tools", "after": "docs", "creates": [".github/workflows/later.yml"]}]}
        S.update(over)
        p = os.path.join(self.tmp, "selection.json")
        with open(p, "w") as fh:
            json.dump(S, fh)
        return p

    def select(self, **over):
        out = os.path.join(self.tmp, "selected.json")
        IC.select(self.selection(**over), out)
        return out

    def assemble(self, selected=None, name="cand", **kw):
        return IC.assemble(selected or self.select(), os.path.join(self.tmp, name), **kw)


class Lanes(Fixture):
    # --- assembly ---------------------------------------------------------------------------------
    def test_assembles_every_lane_and_merges_shared_paths(self):
        rec = self.assemble()
        c = os.path.join(self.tmp, "cand")
        self.assertEqual(sorted(rec["merges"]), ["docs/RELEASE.md", "web/src/i18n/en.ts", "web/src/i18n/zh-CN.ts"])
        with open(os.path.join(c, "docs/RELEASE.md")) as fh:
            self.assertEqual(fh.read(), "zero\none\ntwo\nthree\nfour\nfive\nsix\nseven\neight\n")
        with open(os.path.join(c, "web/src/i18n/en.ts")) as fh:
            en = fh.read()
        self.assertIn('"a.web": "Web"', en)
        self.assertIn('"a.tools": "Tools"', en)
        self.assertFalse(os.path.exists(os.path.join(c, "old.txt")))
        self.assertEqual(os.readlink(os.path.join(c, "CLAUDE.md")), "AGENTS.md")
        self.assertTrue(os.stat(os.path.join(c, "tools/new.sh")).st_mode & 0o111)     # mode from the tar
        self.assertTrue(rec["catalogs"]["ok"])
        self.assertEqual(rec["tree"]["tree_id"], IC.BI.tree_id(c, IC.BI.scan(c)))

    def test_same_inputs_same_tree(self):
        sel = self.select()
        a = self.assemble(sel, "c1")["tree"]["tree_id"]
        b = self.assemble(sel, "c2")["tree"]["tree_id"]
        self.assertEqual(a, b)

    def test_resealed_handoff_is_refused(self):
        with open(os.path.join(self.docs, "snapshot/paths.txt"), "a") as fh:
            fh.write("")
        write(self.docs, "NOTE.md", "a later handoff\n")
        seal(self.docs)                                  # a newer seal under the same directory
        with self.assertRaisesRegex(IC.Refused, "re-sealed or replaced"):
            self.select()

    def test_file_not_matching_its_seal_is_refused(self):
        with open(os.path.join(self.docs, "snapshot/paths.txt"), "a") as fh:
            fh.write("A docs/extra.md\n")
        with self.assertRaisesRegex(IC.Refused, "do not match"):
            self.select()

    def test_path_both_deleted_and_supplied_is_refused(self):
        with open(os.path.join(self.docs, "snapshot/paths.txt"), "w") as fh:
            fh.write("A docs/NEW.md\nM docs/RELEASE.md\nA tools/new.sh\nD docs/NEW.md\n")
        self.digests["docs"] = seal(self.docs)
        with self.assertRaisesRegex(IC.Refused, "listed twice"):
            self.select()
        with open(os.path.join(self.docs, "snapshot/paths.txt"), "w") as fh:
            fh.write("M docs/RELEASE.md\nA tools/new.sh\nD docs/NEW.md\n")
        self.digests["docs"] = seal(self.docs)
        with self.assertRaisesRegex(IC.Refused, "both deleted and supplied"):
            self.select()

    def test_symlink_outside_the_tree_is_refused(self):
        make_tar(os.path.join(self.docs, "snapshot/s.tar"), {"docs/NEW.md": ("new\n", 0o644)}, {"docs/evil": "../../etc/passwd"})
        with open(os.path.join(self.docs, "snapshot/paths.txt"), "w") as fh:
            fh.write("A docs/NEW.md\nA docs/evil\n")
        self.digests["docs"] = seal(self.docs)
        with self.assertRaisesRegex(IC.Refused, "outside the tree"):
            self.select()

    def test_pending_proposal_already_present_is_refused(self):
        with self.assertRaisesRegex(IC.Refused, "not pending"):
            self.select(pending_proposals=[{"id": "p", "creates": ["docs/NEW.md"]}])

    def test_pending_proposal_stays_out(self):
        rec = self.assemble()
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "cand", ".github/workflows/later.yml")))
        with open(os.path.join(self.tmp, "selected.json")) as fh:
            self.assertEqual(json.load(fh)["pending_proposals"][0]["state"], "excluded from the candidate")
        self.assertIn("tree", rec)

    def test_live_worktree_edit_cannot_change_the_candidate(self):
        sel = self.select()
        before = self.assemble(sel, "c1")["tree"]["tree_id"]
        write(self.store, "web/src/i18n/en.ts", "edited after the seal\n")        # the lane keeps working
        with self.assertRaisesRegex(IC.Refused, "no source holds web/src/i18n/en.ts"):
            self.assemble(sel, "c2")
        write(self.store, "web/src/i18n/en.ts", EN.replace('  "a.two": "Two",\n', '  "a.two": "Two",\n  "a.tools": "Tools",\n'))
        self.assertEqual(self.assemble(sel, "c3")["tree"]["tree_id"], before)

    def test_tar_replaced_during_copying_is_refused(self):
        sel = self.select()
        tar = os.path.join(self.docs, "snapshot/s.tar")

        def hook(p):
            if p == "docs/NEW.md":
                with open(tar, "ab") as fh:
                    fh.write(b"\0" * 512)
        with self.assertRaisesRegex(IC.Refused, "changed during copying"):
            self.assemble(sel, "c1", hook=hook)

    def test_seal_changed_during_copying_is_refused(self):
        sel = self.select()

        def hook(p):
            if p == "docs/NEW.md":
                with open(os.path.join(self.tools, "SHA256SUMS"), "a") as fh:
                    fh.write("\n")
        with self.assertRaisesRegex(IC.Refused, "seal changed during copying"):
            self.assemble(sel, "c1", hook=hook)

    def test_store_file_changing_while_read_is_refused(self):
        p = os.path.join(self.tmp, "f")
        write(self.tmp, "f", "x" * 10)
        real_open = open

        def growing_open(path, *a, **k):
            fh = real_open(path, *a, **k)
            if path == p:
                with real_open(p, "a") as g:
                    g.write("more")
            return fh
        import builtins
        builtins.open = growing_open
        try:
            with self.assertRaisesRegex(IC.Refused, "changed while it was read"):
                IC.read_stable(p)
        finally:
            builtins.open = real_open

    def test_text_merge_that_drops_a_key_is_refused(self):
        """A diff3 that reports success but loses a lane's new key is caught by the key check."""
        sel = self.select()
        shim = os.path.join(self.tmp, "shim")
        os.makedirs(shim)
        with open(os.path.join(shim, "diff3"), "w") as fh:
            fh.write('#!/bin/sh\n/usr/bin/diff3 "$@" | grep -v \'"a.tools"\'\nexit 0\n')
        os.chmod(os.path.join(shim, "diff3"), 0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = shim + os.pathsep + old
        try:
            with self.assertRaisesRegex(IC.Refused, r"drops lane changes.*a\.tools"):
                self.assemble(sel, "c1")
        finally:
            os.environ["PATH"] = old

    def test_conflicting_edits_stop_the_assembly(self):
        write(self.store, "docs/RELEASE.md", "ZERO\none\ntwo\nthree\nfour\nfive\nsix\nseven\n")
        with open(os.path.join(self.tools, "worktree.manifest"), "w") as fh:
            for p, (mode, h) in sorted(IC.BI.scan(self.store).items()):
                if mode != "120000":
                    fh.write(f"{h}  {p}\n")
        self.digests["tools"] = seal(self.tools)
        with self.assertRaisesRegex(IC.Refused, "diff3 conflict"):
            self.assemble()

    def test_compare_attributes_differences_to_lanes(self):
        sel = self.select()
        self.assemble(sel, "c1")
        r = IC.compare(self.base, os.path.join(self.tmp, "c1"), sel)
        lanes = {d["path"]: d["lane"] for d in r["differences"]}
        self.assertEqual(lanes["docs/NEW.md"], "docs")
        self.assertEqual(lanes["web/src/i18n/en.ts"], "web+tools")
        self.assertEqual(lanes["old.txt"], "docs")

    def test_verify_finds_a_lost_lane_change_in_another_merge(self):
        sel = self.select()
        self.assemble(sel, "c1")
        c = os.path.join(self.tmp, "c1")
        self.assertTrue(IC.verify(sel, c)["ok"])
        with open(os.path.join(c, "web/src/i18n/en.ts")) as fh:
            text = fh.read()
        write(c, "web/src/i18n/en.ts", text.replace('  "a.web": "Web",\n', ""))      # e.g. an owner merge resolved badly
        r = IC.verify(sel, c)
        self.assertFalse(r["ok"])
        self.assertTrue(any(f.startswith("web: web/src/i18n/en.ts") for f in r["failures"]), r["failures"])

    # --- catalogs -------------------------------------------------------------------------------------
    def test_catalog_problems_are_reported(self):
        d = os.path.join(self.tmp, "cat")
        write(d, "web/src/i18n/en.ts", EN.replace('  "b.three"', '  "a.two": "Again",\n  "b.three"'))
        write(d, "web/src/i18n/zh-CN.ts", ZH.replace("一 {n}", "一 {m}").replace('  "b.three": "三",\n', ""))
        r = IC.catalog_report(d)
        text = " ".join(r["problems"])
        self.assertFalse(r["ok"])
        self.assertIn("duplicate keys: ['a.two']", text)
        self.assertIn("zh-CN lacks 1 key(s): ['b.three']", text)
        self.assertIn("different placeholders: ['a.one']", text)

    # --- rebuild ---------------------------------------------------------------------------------------
    def test_rebuild_from_manifest_and_patch(self):
        start = os.path.join(self.tmp, "start.manifest")
        with open(start, "w") as fh:
            for p, (mode, h) in sorted(IC.BI.scan(self.base).items()):
                if mode != "120000":
                    fh.write(f"{h}  {p}\n")
        final = os.path.join(self.tmp, "final")
        shutil.copytree(self.base, final, symlinks=True)
        write(final, "docs/RELEASE.md", "one\ntwo\nTHREE\nfour\nfive\nsix\nseven\n")
        write(final, "docs/added.md", "added\n")
        patch = os.path.join(self.tmp, "c.patch")
        a, b = os.path.join(self.tmp, "pa"), os.path.join(self.tmp, "pb")
        os.makedirs(os.path.join(a, "docs"))
        os.makedirs(os.path.join(b, "docs"))
        shutil.copy(os.path.join(self.base, "docs/RELEASE.md"), os.path.join(a, "docs/RELEASE.md"))
        shutil.copy(os.path.join(final, "docs/RELEASE.md"), os.path.join(b, "docs/RELEASE.md"))
        shutil.copy(os.path.join(final, "docs/added.md"), os.path.join(b, "docs/added.md"))
        r = subprocess.run(["diff", "-ruN", "pa", "pb"], cwd=self.tmp, capture_output=True)
        with open(patch, "wb") as fh:
            fh.write(r.stdout)
        expect = os.path.join(self.tmp, "final.manifest")
        with open(expect, "w") as fh:
            for p, (mode, h) in sorted(IC.BI.scan(final).items()):
                if mode != "120000":
                    fh.write(f"{h}  {p}\n")
        res = IC.rebuild(start, [self.base], os.path.join(self.tmp, "rb"), expect, patch, mode_from=self.base)
        self.assertEqual(res["verified"], res["files"])
        self.assertTrue(os.stat(os.path.join(self.tmp, "rb", "tools/run.sh")).st_mode & 0o111)
        with open(expect, "a") as fh:
            fh.write(f"{'0' * 64}  docs/missing.md\n")
        with self.assertRaisesRegex(IC.Refused, "differs from"):
            IC.rebuild(start, [self.base], os.path.join(self.tmp, "rb2"), expect, patch)


class Receipts(Fixture):
    def receipt(self):
        sel = self.select()
        self.assemble(sel, "cand")
        rd = os.path.join(self.tmp, "receipt")
        IR.init(rd, os.path.join(self.tmp, "cand.assembly.json"), sel)
        return rd, os.path.join(self.tmp, "cand")

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = IR.main(list(argv))
        return rc, out.getvalue()

    def test_run_records_time_exit_counts_and_digest(self):
        rd, cand = self.receipt()
        rc, _ = self.run_cli("run", rd, "--id", "go", "--title", "t", "--tree", cand, "--parse", "unittest",
                             "--required-for", "local-rehearsal", "--", "sh", "-c", "echo 'Ran 3 tests'; echo 'OK (skipped=1)'")
        self.assertEqual(rc, 0)
        c = next(c for c in IR.load(rd)["checks"] if c["id"] == "go")
        self.assertEqual((c["exit"], c["status"], c["counts"]["ran"], c["counts"]["skipped"]), (0, "pass", 3, 1))
        self.assertTrue(c["started_at"].endswith("Z") and c["finished_at"])
        with open(os.path.join(rd, c["evidence"]["path"]), "rb") as fh:
            self.assertEqual(sha(fh.read()), c["evidence"]["sha256"])
        self.assertEqual(c["tree_id"], IR.load(rd)["candidate"]["tree_id"])

    def test_a_command_that_changes_the_tree_fails(self):
        rd, cand = self.receipt()
        rc, out = self.run_cli("run", rd, "--id", "w", "--title", "t", "--tree", cand, "--", "sh", "-c", "echo x > stray.txt")
        self.assertEqual(rc, 1)
        self.assertIn("changed the tree", out)

    def test_result_from_another_tree_is_refused(self):
        rd, cand = self.receipt()
        rc, out = self.run_cli("run", rd, "--id", "w", "--title", "t", "--tree", self.base, "--", "true")
        self.assertEqual(rc, 2)
        self.assertIn("not the candidate", out)

    def test_stale_when_tree_or_artifact_bytes_change(self):
        rd, cand = self.receipt()
        art = os.path.join(self.tmp, "pkg.tar")
        write(self.tmp, "pkg.tar", "v1")
        self.run_cli("run", rd, "--id", "pkg", "--title", "t", "--tree", cand, "--artifact", art,
                     "--required-for", "local-rehearsal", "--", "true")
        r = IR.load(rd)
        eff = {c["id"]: c["effective"] for c in IR.evaluate(r, rd)["checks"]}
        self.assertEqual(eff["pkg"], "pass")
        write(self.tmp, "pkg.tar", "v2")                       # same file name, other bytes
        ev = IR.evaluate(r, rd)
        c = next(c for c in ev["checks"] if c["id"] == "pkg")
        self.assertEqual(c["effective"], "stale")
        self.assertIn("other bytes", c["reason"])
        r["candidate"]["tree_id"] = "0" * 40                   # the candidate moved on
        c = next(c for c in IR.evaluate(r, rd)["checks"] if c["id"] == "assembly")
        self.assertEqual(c["effective"], "stale")

    def test_changed_evidence_and_missing_required_checks(self):
        rd, cand = self.receipt()
        r = IR.load(rd)
        ev = IR.evaluate(r, rd)
        self.assertEqual(ev["verdict"], "BLOCKED")
        self.assertIn("go", {c["id"] for c in ev["blockers"] if c["effective"] == "missing"})
        with open(os.path.join(rd, "evidence/assembly.json"), "a") as fh:
            fh.write(" ")
        c = next(c for c in IR.evaluate(r, rd)["checks"] if c["id"] == "assembly")
        self.assertEqual(c["effective"], "changed")

    def test_claimed_ready_with_missing_checks_is_invalid(self):
        rd, _ = self.receipt()
        r = IR.load(rd)
        r["claimed_verdict"] = {"local-rehearsal": "READY"}
        IR.save(rd, r)
        rc, out = self.run_cli("check", rd)
        self.assertEqual(rc, 2)
        self.assertIn("claims READY", out)

    def test_ready_when_every_required_check_passes(self):
        rd, cand = self.receipt()
        for cid in IR.REQUIRED["local-rehearsal"][1:]:
            self.run_cli("run", rd, "--id", cid, "--title", cid, "--tree", cand, "--required-for", "local-rehearsal", "--", "true")
        rc, out = self.run_cli("check", rd)
        self.assertEqual(rc, 0, out)
        rc, out = self.run_cli("check", rd, "--target", "staging")
        self.assertEqual(rc, 1)
        self.assertIn("aws-plan-check MISSING", out)

    def test_validates_from_a_clean_directory(self):
        rd, cand = self.receipt()
        self.run_cli("run", rd, "--id", "go", "--title", "t", "--tree", cand, "--", "true")
        moved = os.path.join(tempfile.mkdtemp(prefix="moved-"), "r")
        self.addCleanup(shutil.rmtree, os.path.dirname(moved))
        shutil.copytree(rd, moved)
        shutil.rmtree(rd)
        r = IR.load(moved)
        eff = {c["id"]: c["effective"] for c in IR.evaluate(r, moved)["checks"]}
        self.assertEqual((eff["go"], eff["assembly"]), ("pass", "pass"))

    def test_resume_keeps_an_intact_pass(self):
        rd, cand = self.receipt()
        marker = os.path.join(self.tmp, "ran")
        cmd = ["--", "sh", "-c", f"echo once >> {marker}"]
        self.run_cli("run", rd, "--id", "s", "--title", "t", "--tree", cand, *cmd)
        rc, out = self.run_cli("run", rd, "--id", "s", "--title", "t", "--tree", cand, "--resume", *cmd)
        self.assertIn("kept", out)
        with open(marker) as fh:
            self.assertEqual(fh.read().count("once"), 1)

    def test_summary_fits_a_narrow_terminal_and_names_stale_first(self):
        rd, cand = self.receipt()
        self.run_cli("run", rd, "--id", "go", "--title", "t", "--tree", cand, "--required-for", "local-rehearsal", "--", "false")
        r = IR.load(rd)
        text = IR.summary(r, IR.evaluate(r, rd), width=40)
        self.assertTrue(all(len(line) <= 40 for line in text.splitlines()), text)
        self.assertLess(text.index("Failed on the candidate"), text.index("Required but never run"))

    def test_carried_results_are_stale_not_failed_until_rerun(self):
        rd, cand = self.receipt()
        self.run_cli("run", rd, "--id", "go", "--title", "t", "--tree", cand, "--required-for", "local-rehearsal", "--", "true")
        write(self.store, "docs/LATER.md", "x\n")                     # a later candidate: the tools lane adds a file
        with open(os.path.join(self.tools, "worktree.manifest"), "a") as fh:
            fh.write(f"{sha(b'x' + bytes([10]))}  docs/LATER.md\n")
        self.digests["tools"] = seal(self.tools)
        sel2 = os.path.join(self.tmp, "selected2.json")
        IC.select(self.selection(), sel2)
        IC.assemble(sel2, os.path.join(self.tmp, "cand2"))
        rd2 = os.path.join(self.tmp, "receipt2")
        IR.init(rd2, os.path.join(self.tmp, "cand2.assembly.json"), sel2)
        self.assertEqual(IR.carry(rd2, rd), 1)
        ev = IR.evaluate(IR.load(rd2), rd2)
        go = next(c for c in ev["checks"] if c["id"] == "go")
        self.assertEqual(go["effective"], "stale")
        self.assertIn("rerun", go["next"])
        self.assertNotIn("go", {c["id"] for c in ev["checks"] if c["effective"] == "fail"})

    def test_receipt_carried_with_its_artifacts_still_checks_them(self):
        rd, cand = self.receipt()
        write(self.tmp, "pkg.tar", "v1")
        self.run_cli("run", rd, "--id", "pkg", "--title", "t", "--tree", cand, "--artifact", os.path.join(self.tmp, "pkg.tar"), "--", "true")
        moved = os.path.join(self.tmp, "elsewhere")
        shutil.copytree(rd, moved)
        os.unlink(os.path.join(self.tmp, "pkg.tar"))
        eff = lambda: next(c for c in IR.evaluate(IR.load(moved), moved)["checks"] if c["id"] == "pkg")["effective"]
        self.assertEqual(eff(), "unavailable")
        write(moved, "artifacts/pkg.tar", "v1")
        self.assertEqual(eff(), "pass")
        write(moved, "artifacts/pkg.tar", "v2")
        self.assertEqual(eff(), "stale")

    def test_lane_trees_and_reproduce(self):
        sel = self.select()
        self.assertEqual(IC.lane_tree_id(sel, "docs"), IC.lane_tree_id(sel, "docs"))
        rec = self.assemble(sel, "c1")
        r = IC.reproduce(self.selection(), expect=rec["tree"]["tree_id"])
        self.assertTrue(r["equal"])
        with self.assertRaisesRegex(IC.Refused, "expected"):
            IC.reproduce(self.selection(), expect="0" * 40)
        keep = os.path.join(self.tmp, "kept", "new")                 # --keep creates a new directory
        r = IC.reproduce(self.selection(), expect=rec["tree"]["tree_id"], keep=keep)
        self.assertTrue(r["equal"] and os.path.isdir(os.path.join(keep, "tree")))
        with self.assertRaisesRegex(IC.Refused, "must be new or empty"):
            IC.reproduce(self.selection(), keep=keep)

    def test_expected_failures_are_not_counted_as_failures(self):
        c = IR.parse_counts("unittest", "Ran 143 tests in 3.9s\nOK (skipped=7, expected failures=1)\n")
        self.assertEqual((c["ran"], c["skipped"], c["expected_failures"], c["failures"]), (143, 7, 1, 0))
        c = IR.parse_counts("unittest", "Ran 3 tests\nFAILED (failures=2, expected failures=1)\n")
        self.assertEqual((c["failures"], c["expected_failures"]), (2, 1))

    def test_review_order_names_shared_paths_and_assumes_no_pr(self):
        rd, _ = self.receipt()
        steps = IR.review_order(IR.load(rd))
        self.assertEqual([s["lane"] for s in steps], ["web", "docs", "tools"])
        self.assertTrue(all("no PR" in s["state"] for s in steps))
        self.assertTrue(any("docs/RELEASE.md" in x for x in steps[2]["reasons"]))
        self.assertTrue(any("later needs docs merged first" in x for x in steps[2]["reasons"]))


if __name__ == "__main__":
    unittest.main()
