"""The synthetic client for flh_speaking_transcription_v1 (standard library only)."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

from flh_speaking import client  # noqa: E402

DEP = "whisper-base@e37978b90ca9/flh_speaking_transcribe_v1/cpu-fp32/ac92e8688ef9e17b"


def contract_example() -> dict:
    """The 200 example printed in CONTRACT.md §3, with this deployment."""
    text = (PKG / "CONTRACT.md").read_text(encoding="utf-8")
    block = re.search(r"## 3\. Service response.*?```json\n(.*?)```", text, re.S).group(1)
    doc = json.loads(block.replace("<sha256 of the uploaded bytes>", "0" * 64).replace("<16 hex>", "ac92e8688ef9e17b"))
    doc["flh"]["deployment_id"] = DEP
    return doc


class Client(unittest.TestCase):
    def test_the_documented_response_passes(self):
        r = client.check_response(contract_example(), DEP)
        self.assertEqual((r["ok"], r["problems"], r["omitted_optional"]), (True, [], []))

    def test_an_older_service_may_omit_optional_fields(self):
        r = client.check_response({"text": "Bonjour.", "flh": {"deployment_id": DEP}}, DEP)
        self.assertTrue(r["ok"], r)
        self.assertEqual(sorted(r["omitted_optional"]), sorted(client.OPTIONAL))

    def test_what_the_go_client_would_refuse(self):
        self.assertFalse(client.check_response({"text": "Bonjour."}, DEP)["ok"])                     # no flh block
        self.assertFalse(client.check_response({"text": "x", "flh": {"deployment_id": "other"}}, DEP)["ok"])
        self.assertFalse(client.check_response({"text": 3, "flh": {"deployment_id": DEP}})["ok"])
        bad = client.check_response({"text": "x", "flh": {"deployment_id": DEP, "status": "no_speech", "warnings": "w"}})
        self.assertEqual(len(bad["problems"]), 2)  # an abstention with text; warnings not a list

    def test_error_bodies(self):
        self.assertEqual(client.check_error({"error": {"type": "busy", "message": "too many"}}), [])
        self.assertTrue(client.check_error({"error": "busy"}))


if __name__ == "__main__":
    unittest.main()
