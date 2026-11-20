"""Tests for public_provenance.py on a synthetic artifact (no real address appears in this file).

  python3 -I -B scripts/demo/flh076/test_public_provenance.py
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import public_provenance as PP  # noqa: E402

PRIVATE_URL = "http://" + "box.tail0000a" + ".ts" + ".net:8765/v1"     # assembled: not a literal private host
MODEL = "model@0123/role_v1/float16/singleton_v1/abcdef"


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class PublicProvenance(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.td)
        self.pkg = os.path.join(self.td, "pkg")
        self.art = os.path.join(self.pkg, "artifact")
        os.makedirs(self.art)
        for name, body in (("demo.db", b"db"), ("vectors.json", b"{}"), ("fixtures.json", b"{}")):
            with open(os.path.join(self.art, name), "wb") as fh:
                fh.write(body)
        prov = {"schema": "flh076_vector_provenance_v1", "generator": "g", "deployment_id": MODEL, "dimensions": 768,
                "base_url": PRIVATE_URL, "plan_sha256": "a" * 64, "fixtures_sha256": sha(os.path.join(self.art, "fixtures.json")),
                "probes": [{"utc": "2026-11-12T00:00:00Z", "ready_status": 200, "manifest_deployment_id": MODEL,
                            "manifest_sha256": "b" * 64, "outcome": "ready"}],
                "posts": [{"seq": 1, "positions": 2, "outcome": "failed", "reserved_utc": "t", "finished_utc": "t",
                           "error": "connect to " + PRIVATE_URL + " refused"}],
                "accounting": {"max_positions": 64, "max_posts": 16, "max_probes": 2, "used_positions": 2, "used_posts": 1, "used_probes": 1},
                "positions": [], "note": "synthetic", "operator_host": "laptop"}
        with open(os.path.join(self.art, "provenance.json"), "w") as fh:
            json.dump(prov, fh)
        self.files = {n: sha(os.path.join(self.art, n)) for n in ("demo.db", "vectors.json", "fixtures.json", "provenance.json")}
        manifest = {"schema": "s", "artifact_version": "0123456789abcdef", "files": dict(self.files),
                    "vectors": {"model_id": MODEL, "dimensions": 768}, "domain_fingerprint": {"sha256": "c" * 64}}
        with open(os.path.join(self.art, "manifest.json"), "w") as fh:
            json.dump(manifest, fh)

    def release(self, **extra):
        man = os.path.join(self.art, "manifest.json")
        with open(man) as fh:
            m = json.load(fh)
        rel = {"schema": "flh076_public_demo_release_v1", "label": "x", "release_status": "CANDIDATE", "targets": ["linux/amd64"],
               "artifact": {"version": m["artifact_version"], "manifest_sha256": sha(man), "model_id": MODEL, "dimensions": 768,
                            "domain_fingerprint": "c" * 64},
               "model_provenance": {"deployment_id": MODEL, "plan_sha256": "a" * 64, "positions": 0, "posts": 1, "probes": 1}}
        rel["model_provenance"].update(extra)
        with open(os.path.join(self.pkg, "RELEASE.json"), "w") as fh:
            json.dump(rel, fh)

    def quiet(self, fn, *a):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                rc = fn(*a)
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue()

    def test_project_keeps_identity_and_drops_private_fields(self):
        rc, out = self.quiet(PP.project, self.art)
        self.assertEqual(rc, 0, out)
        with open(os.path.join(self.art, "provenance.json")) as fh:
            prov = json.load(fh)
        self.assertNotIn("base_url", prov)
        self.assertNotIn("operator_host", prov)
        self.assertEqual(prov["posts"][0]["error"], "")
        self.assertEqual(prov["deployment_id"], MODEL)
        with open(os.path.join(self.art, "manifest.json")) as fh:
            m = json.load(fh)
        self.assertEqual(m["artifact_version"], "0123456789abcdef")
        for n in ("demo.db", "vectors.json", "fixtures.json"):
            self.assertEqual(m["files"][n], self.files[n])
        self.assertEqual(m["files"]["provenance.json"], sha(os.path.join(self.art, "provenance.json")))
        self.assertNotEqual(m["files"]["provenance.json"], self.files["provenance.json"])
        self.assertNotIn("ts.net", out)
        self.release()
        rc, out = self.quiet(PP.check, self.pkg)
        self.assertEqual(rc, 0, out)

    def test_check_names_the_key_never_the_value(self):
        self.quiet(PP.project, self.art)
        self.release(base_url=PRIVATE_URL)
        rc, out = self.quiet(PP.check, self.pkg)
        self.assertEqual(rc, 1)
        self.assertIn("RELEASE.json: release.model_provenance.base_url: not a public field", out)
        self.assertNotIn("ts.net", out)
        self.assertNotIn("8765", out)

    def test_check_flags_the_unprojected_provenance_and_url_like_values(self):
        self.release()
        rc, out = self.quiet(PP.check, self.pkg)
        self.assertEqual(rc, 1)
        self.assertIn("artifact/provenance.json: provenance.base_url: not a public field", out)
        self.assertIn("provenance.posts[].error: must be empty in a public file", out)
        self.assertNotIn("ts.net", out)
        self.quiet(PP.project, self.art)
        with open(os.path.join(self.art, "provenance.json")) as fh:
            prov = json.load(fh)
        prov["note"] = "see " + PRIVATE_URL
        with open(os.path.join(self.art, "provenance.json"), "w") as fh:
            json.dump(prov, fh)
        rc, out = self.quiet(PP.check, self.pkg)
        self.assertIn("provenance.note: value looks like a url", out)
        self.assertIn("does not match manifest.json", out)

    def test_project_refuses_a_tampered_artifact(self):
        with open(os.path.join(self.art, "vectors.json"), "w") as fh:
            fh.write("[]")
        rc, out = self.quiet(PP.project, self.art)
        self.assertNotEqual(rc, 0)
        self.assertIn("vectors.json differs from manifest.json", str(rc) + out)

    def test_release_must_match_the_package_artifact(self):
        self.quiet(PP.project, self.art)
        self.release()
        with open(os.path.join(self.pkg, "RELEASE.json")) as fh:
            rel = json.load(fh)
        rel["artifact"]["version"] = "ffffffffffffffff"
        with open(os.path.join(self.pkg, "RELEASE.json"), "w") as fh:
            json.dump(rel, fh)
        rc, out = self.quiet(PP.check, self.pkg)
        self.assertEqual(rc, 1)
        self.assertIn("release.artifact.version does not match the package's artifact", out)

    def test_unexpected_nested_keys_are_dropped_and_refused(self):
        """R3-014: a synthetic record with unexpected keys at every depth, and private-looking
        values inside allowed fields. check names each key path; project drops the keys; values in
        allowed fields are not rewritten (only a post's error is), so check still refuses them."""
        with open(os.path.join(self.art, "provenance.json")) as fh:
            prov = json.load(fh)
        prov["probes"][0]["host"] = "box"                                  # nested, unexpected
        prov["accounting"]["operator"] = "someone"                         # nested, unexpected
        prov["positions"] = [{"key": "k", "kind": "query", "source_path": "/" + "home/someone/x"}]
        prov["probes"][0]["outcome"] = "ready via " + ".".join(["10", "0", "0", "5"])   # private-looking value, allowed key
        prov["note"] = "ask " + "ops" + "@" + "example.org"
        with open(os.path.join(self.art, "provenance.json"), "w") as fh:
            json.dump(prov, fh)
        with open(os.path.join(self.art, "manifest.json")) as fh:
            m = json.load(fh)
        m["files"]["provenance.json"] = sha(os.path.join(self.art, "provenance.json"))
        with open(os.path.join(self.art, "manifest.json"), "w") as fh:
            json.dump(m, fh)
        self.release()
        rc, out = self.quiet(PP.check, self.pkg)
        self.assertEqual(rc, 1)
        for path in ("provenance.probes[].host: not a public field", "provenance.accounting.operator: not a public field",
                     "provenance.positions[].source_path: not a public field", "provenance.probes[].outcome: value looks like a private-address",
                     "provenance.note: value looks like a email"):
            self.assertIn(path, out)
        self.assertNotIn("someone", out)
        self.assertNotIn("example.org", out)
        rc, out = self.quiet(PP.project, self.art)
        self.assertEqual(rc, 0, out)
        for dropped in ("provenance.probes[].host", "provenance.accounting.operator", "provenance.positions[].source_path"):
            self.assertIn(dropped, out)
        self.release()
        rc, out = self.quiet(PP.check, self.pkg)
        self.assertEqual(rc, 1)
        self.assertNotIn("not a public field", out)
        self.assertIn("provenance.probes[].outcome: value looks like a private-address", out)

    def test_every_manifest_hash_holds_after_projection(self):
        """R3-015: after project, every manifest entry is the SHA-256 of its file; only the
        provenance entry changed; projecting again changes nothing (a stable manifest digest)."""
        self.quiet(PP.project, self.art)
        man = os.path.join(self.art, "manifest.json")
        with open(man) as fh:
            m = json.load(fh)
        for name, want in m["files"].items():
            self.assertEqual(sha(os.path.join(self.art, name)), want, name)
        self.assertEqual({k: v for k, v in m["files"].items() if k != "provenance.json"},
                         {k: v for k, v in self.files.items() if k != "provenance.json"})
        first = sha(man), sha(os.path.join(self.art, "provenance.json"))
        rc, out = self.quiet(PP.project, self.art)
        self.assertEqual(rc, 0, out)
        self.assertIn("0 field(s) removed", out)
        self.assertEqual((sha(man), sha(os.path.join(self.art, "provenance.json"))), first)

if __name__ == "__main__":
    unittest.main()
