"""Speaking test entry point (same discovery as ``python3 -B -m unittest discover -s tests -t tests``).

  cd tools/speaking
  python3 -B scripts/run_tests.py                   # offline: standard library only; tests that need
                                                    # NumPy/PyAV/torch skip with their reason, exit 0
  python3 -B scripts/run_tests.py --require-deps    # full: NumPy, PyAV, torch and transformers must import and
                                                    # FLH_SPEAKING_TOKENIZER_DIR must hold the 10 pinned whisper-tiny
                                                    # config/tokenizer files (no weights), each verified against
                                                    # its pin before any test runs; any skip fails the run

Exit codes: 0 every test passed (offline: skips allowed); 1 a test failed or
errored, or with --require-deps a test was skipped; 2 an environment problem
found before any test runs: with --require-deps a required module (for example
no Python 3.12 environment with the lock installed) or the tokenizer fixture is
missing, or with --expect-offline the network is reachable. A 2 is never a test
result; a 1 always is.

``--json FILE`` writes the totals, the skips grouped by reason, the module
versions and the elapsed test time. Nothing is downloaded: the tests read the
fixture directory only, and the image run uses ``--network none``.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never leave __pycache__ in the repository

import argparse  # noqa: E402
import hashlib  # noqa: E402
import importlib.metadata  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402
from collections import Counter  # noqa: E402

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(PKG, "tests")
sys.path.insert(0, PKG)
from flh_speaking import fetch, pins  # noqa: E402 (standard library only)

REQUIRED_MODULES = ("numpy", "av", "torch", "transformers")
FIXTURE_ENV = "FLH_SPEAKING_TOKENIZER_DIR"
FIXTURE_MODEL = "whisper-tiny"


def fixture_files() -> dict:
    """The fixture contract: every pinned whisper-tiny file except the weights
    (the training tests build a tiny random model from config.json and copy the
    tokenizer files; weights are never read). {name: (size, (kind, digest))}."""
    return {f: v for f, v in sorted(pins.MODELS[FIXTURE_MODEL]["files"].items()) if not f.endswith(".safetensors")}


def fixture_contract() -> dict:
    """Identity of the fixture, for a CI cache key: repository, revision and a
    SHA-256 over the sorted 'name size kind digest' lines of the contract."""
    lines = "".join(f"{f}\t{size}\t{kind}\t{dg}\n" for f, (size, (kind, dg)) in fixture_files().items())
    src = pins.MODELS[FIXTURE_MODEL]
    return {"repo": src["repo"], "revision": src["revision"], "files": len(fixture_files()),
            "bytes": sum(size for size, _ in fixture_files().values()), "contract_sha256": hashlib.sha256(lines.encode()).hexdigest()}


def fixture_problems(tok: str) -> list[str]:
    """Each fixture file is checked against its pin (size, then hash): a
    missing, truncated or edited file is named; an empty list means usable."""
    if not tok:
        return [f"{FIXTURE_ENV} is not set"]
    return [f"{f}: {bad}" for f, (size, dg) in fixture_files().items() if (bad := fetch.verify(os.path.join(tok, f), size, dg))]


def preflight(modules=REQUIRED_MODULES, env=None) -> tuple[list[str], dict]:
    """Missing required modules or fixture, and the versions of those present."""
    env = os.environ if env is None else env
    missing, versions = [], {}
    for m in modules:
        if importlib.util.find_spec(m) is None:
            missing.append(f"module {m}")
            continue
        try:
            versions[m] = importlib.metadata.version(m)
        except importlib.metadata.PackageNotFoundError:
            versions[m] = "unknown"
    bad = fixture_problems(env.get(FIXTURE_ENV, ""))
    if bad:
        missing.append(f"fixture {FIXTURE_ENV} does not match its pins ({'; '.join(bad)}); "
                       "fetch it with: python3 -B -m flh_speaking fetch --dest DIR --what whisper-tiny --no-weights")
    return missing, versions


PROBE_ENDPOINTS = (("1.1.1.1", 443), ("8.8.8.8", 53), ("pypi.org", 443))


def network_reachable(timeout: float = 2.0) -> list[str]:
    """Endpoints this process can reach (empty: isolated). Used by --expect-offline
    to prove the test run cannot download anything once the fixture is in place."""
    import socket
    ok = []
    for host, port in PROBE_ENDPOINTS:
        try:
            socket.create_connection((host, port), timeout=timeout).close()
            ok.append(f"{host}:{port}")
        except OSError:
            pass
    return ok


def run_suite(suite: unittest.TestSuite, require: bool, stream=None) -> tuple[bool, dict]:
    """Run a suite; with ``require`` any skip makes the run fail."""
    stream = stream or sys.stderr

    def flat(s):
        for t in s:
            yield from (flat(t) if isinstance(t, unittest.TestSuite) else [t])
    by_class = Counter(f"{type(t).__module__}.{type(t).__name__}" for t in flat(suite))
    t0 = time.monotonic()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    elapsed = time.monotonic() - t0
    skips = Counter(reason for _, reason in result.skipped)
    summary = {
        "mode": "require-deps" if require else "offline",
        "ran": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "skips_by_reason": dict(sorted(skips.items())),
        "skipped_tests": sorted(t.id() for t, _ in result.skipped),
        "tests_by_class": dict(sorted(by_class.items())),
        "skipped_by_class": dict(sorted(Counter(f"{type(t).__module__}.{type(t).__name__}" for t, _ in result.skipped).items())),
        "expected_failures": len(result.expectedFailures), "unexpected_successes": len(result.unexpectedSuccesses),
        "test_seconds": round(elapsed, 2),
    }
    try:  # peak memory of this process so far (Linux: KiB)
        import resource
        summary["max_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except (ImportError, AttributeError):
        pass
    # the summary must describe exactly what ran: per-class counts add up to "ran",
    # and every skip is listed
    summary["counts_consistent"] = sum(by_class.values()) == result.testsRun and len(summary["skipped_tests"]) == len(result.skipped)
    ok = result.wasSuccessful() and not (require and result.skipped) and summary["counts_consistent"]
    if require and result.skipped:
        print(f"FAILED: {len(result.skipped)} test(s) skipped, but --require-deps requires every test to run:", file=stream)
        for t, reason in result.skipped:
            print(f"  {t.id()}: {reason}", file=stream)
    return ok, summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--require-deps", action="store_true", help="fail on a missing dependency, a missing fixture or any skip")
    ap.add_argument("--json", help="write the summary here")
    ap.add_argument("--expect-offline", action="store_true", help="exit 2 if any public endpoint is reachable (run with --network none)")
    a = ap.parse_args(argv)
    summary: dict = {}
    if a.expect_offline:
        reachable = network_reachable()
        summary["network"] = {"expected": "offline", "reachable": reachable}
        if reachable:
            print("NETWORK REACHABLE (--expect-offline): " + ", ".join(reachable), file=sys.stderr)
            if a.json:
                with open(a.json, "w", encoding="utf-8") as fh:
                    json.dump(summary, fh, indent=1, sort_keys=True)
            return 2
    if a.require_deps:
        missing, versions = preflight()
        summary["versions"] = versions
        summary["fixture"] = fixture_contract()
        if missing:
            print("MISSING (required by --require-deps): " + "; ".join(missing), file=sys.stderr)
            summary.update({"mode": "require-deps", "missing": missing})
            if a.json:
                with open(a.json, "w", encoding="utf-8") as fh:
                    json.dump(summary, fh, indent=1, sort_keys=True)
            return 2
    suite = unittest.TestLoader().discover(start_dir=TESTS, top_level_dir=TESTS)
    ok, res = run_suite(suite, a.require_deps)
    summary.update(res)
    print(json.dumps({k: v for k, v in summary.items() if k != "skipped_tests"}, sort_keys=True), file=sys.stderr)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=1, sort_keys=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
