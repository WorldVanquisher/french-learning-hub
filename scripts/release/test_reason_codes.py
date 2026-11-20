#!/usr/bin/env python3
"""Item 076: the short reason codes are stable. Each tool's code list appears in its own output code
and in docs/RELEASE.md "Reason codes", and the doc lists no other code for that tool."""
import importlib.machinery
import importlib.util
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.realpath(os.path.join(HERE, "..", ".."))


def load(path):
    loader = importlib.machinery.SourceFileLoader(os.path.basename(path)[:-3] + "_codes", path)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def doc_codes():
    with open(os.path.join(REPO, "docs", "RELEASE.md")) as fh:
        text = fh.read()
    sec = text.split("\n## Reason codes (release and staging tools)\n", 1)[1].split("\n## ", 1)[0]
    out = {}
    for m in re.finditer(r"^\| `([a-z_]+\.py)[^`]*` \| `([^`]+)` \|", sec, re.M):
        out.setdefault(m.group(1), []).append(m.group(2))
    return out


class ReasonCodes(unittest.TestCase):
    def setUp(self):
        self.doc = doc_codes()
        bt = load(os.path.join(HERE, "backup_tool.py"))
        self.tools = {
            "diagnose.py": (os.path.join(HERE, "diagnose.py"), list(load(os.path.join(HERE, "diagnose.py")).REASONS)),
            "backup_tool.py": (os.path.join(HERE, "backup_tool.py"),
                               list(bt.BACKUP_STATES + bt.NEXT_CODES + bt.RESTORE_STATES + bt.ARCHIVE_VERDICTS
                                    + bt.RECEIPT_VERDICTS)),
            "cutover_check.py": (os.path.join(HERE, "cutover_check.py"), list(load(os.path.join(HERE, "cutover_check.py")).VERDICTS)),
            "plan_review.py": (os.path.join(REPO, "deploy", "aws", "private-staging", "staging", "tools", "plan_review.py"),
                               list(load(os.path.join(REPO, "deploy", "aws", "private-staging", "staging", "tools",
                                                      "plan_review.py")).VERDICTS)),
        }

    def test_doc_and_tools_agree(self):
        for tool, (path, codes) in self.tools.items():
            with self.subTest(tool=tool):
                self.assertEqual(sorted(self.doc.get(tool, [])), sorted(codes))

    def test_each_code_is_produced_by_its_tool(self):
        for tool, (path, codes) in self.tools.items():
            with open(path) as fh:
                src = fh.read()
            body = re.sub(r"^[A-Z_]+ = \(.*?\)$", "", src, flags=re.M | re.S)     # not just the constant itself
            for code in codes:
                with self.subTest(tool=tool, code=code):
                    self.assertRegex(body, re.escape(code), f"{tool} never emits {code}")


if __name__ == "__main__":
    unittest.main()
