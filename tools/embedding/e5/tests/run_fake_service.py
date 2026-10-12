"""Test-only launcher: the real service and HTTP stack with the FAKE encoder
(hash vectors, no model, no GPU). For plumbing checks of Go callers, e.g.

    python3 -B tools/embedding/e5/tests/run_fake_service.py --port 18765

Deployment id: fake-e5-plumbing-only. Never use its vectors as data.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flh_e5 import __main__ as cli  # noqa: E402
from flh_e5.service import EmbeddingService, Limits  # noqa: E402
from tests.fakes import FakeEncoder  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
args = ap.parse_args()
svc = EmbeddingService(FakeEncoder, lambda e: {"deployment_id": "fake-e5-plumbing-only", "fake": True}, Limits())
sys.exit(cli.serve(svc, "127.0.0.1", args.port))
