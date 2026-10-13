#!/usr/bin/env python3
"""FLH-060 fake-mode upstream: the real FLH-054 E5 service and HTTP stack with
its injected FAKE encoder (hash vectors; no model, no GPU), on 127.0.0.1.

    fake_e5.py PORT WORK

It enforces the same role contract, limits, /readyz, /manifest and /metrics as
the real service, so the demo exercises the same wire contract. Its vectors are
NOT semantic: fake-mode rankings say nothing about meaning. WORK only names the
demo directory on the command line (process identity). Deployment id:
fake-e5-plumbing-only.
"""

import sys
from pathlib import Path

E5 = Path(__file__).resolve().parents[3] / "tools" / "embedding" / "e5"
sys.path.insert(0, str(E5))

from flh_e5 import __main__ as cli  # noqa: E402
from flh_e5.service import EmbeddingHTTPServer, EmbeddingService, Limits  # noqa: E402
from tests.fakes import FakeEncoder  # noqa: E402

# For this demo listener only: allow binding while the previous run's
# connections sit in TIME_WAIT, so stop/start works at once. A port with an
# active listener is still refused. The real service keeps its own setting.
EmbeddingHTTPServer.allow_reuse_address = True

FAKE_DEPLOYMENT = "fake-e5-plumbing-only"

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    svc = EmbeddingService(FakeEncoder, lambda e: {"deployment_id": FAKE_DEPLOYMENT, "fake": True,
                                                   "vector_defining": {"inference": {"dimensions": 768}}}, Limits())
    sys.exit(cli.serve(svc, "127.0.0.1", int(sys.argv[1])))
