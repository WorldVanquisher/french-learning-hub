#!/usr/bin/env python3
"""Tests for check_bundle.py (R2-054): python3 -I scripts/validation/demo_candidate/test_check_bundle.py"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_bundle  # noqa: E402

INDEX = '<!doctype html><script type="module" src="/assets/index-a1.js"></script><link rel="stylesheet" href="/assets/index-b2.css">'


def build(files):
    d = tempfile.mkdtemp()
    for name, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(d, name)) or d, exist_ok=True)
        open(os.path.join(d, name), "w", encoding="utf-8").write(text)
    return d


def run(*args):
    out = io.StringIO()
    with redirect_stdout(out):
        code = check_bundle.main(list(args))
    return code, out.getvalue()


GOOD = {"index.html": INDEX, "assets/index-a1.js": 'fetch("/api/knowledge-library/concepts/"+id);', "assets/index-b2.css": ".record-row{color:red}"}


class CheckBundle(unittest.TestCase):
    def test_a_public_build_passes(self):
        self.assertEqual(run(build(GOOD))[0], 0)

    def test_private_routes_storage_keys_and_extra_files_fail(self):
        for extra, why in [
            ({"assets/index-a1.js": 'fetch("/api/listening/pull")'}, "/listening"),
            ({"assets/index-a1.js": 'x(`/entries/${id}/extractions`)'}, "/entries"),
            ({"assets/index-a1.js": 'get("/concepts/"+id)'}, "/concepts"),
            ({"assets/index-a1.js": 'localStorage.getItem("flh.ui-theme.v1")'}, "workbench storage key"),
            ({"assets/index-a1.js.map": "{}"}, "unexpected file"),
            ({"assets/app-c3.js": ""}, "workbench chunk"),
            # A made-up address in the CGNAT range, assembled so this file holds none.
            ({"assets/index-b2.css": "/* " + ".".join(["100", "101", "2", "3"]) + " */"}, "tailnet address"),
            ({"index.html": INDEX.replace("index-b2.css", "index-zz.css")}, "not there"),
        ]:
            code, out = run(build({**GOOD, **extra}))
            self.assertEqual(code, 1, extra)
            self.assertIn(why, out)

    def test_the_private_host_is_found_but_never_printed(self):
        host = "secret-host.example.internal"
        hf = os.path.join(build({}), "host.txt")
        open(hf, "w").write(host + "\n")
        code, out = run(build({**GOOD, "assets/index-a1.js": f'const u="http://{host}:8765"'}), "--private-host-file", hf)
        self.assertEqual(code, 1)
        self.assertNotIn(host, out)
        self.assertIn("value not printed", out)


if __name__ == "__main__":
    unittest.main()
