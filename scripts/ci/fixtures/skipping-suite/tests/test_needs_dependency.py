"""Negative fixture for scripts/ci/test_python_suites.py: a required test that skips.

It stands for a suite whose dependency or data is missing on the runner. Offline the
skip is legitimate and counted; under `--fail-on-skip` it must fail the suite.
"""
import unittest

try:
    import flh_fixture_dependency_that_is_never_installed  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False


class NeedsDependency(unittest.TestCase):
    def test_runs_everywhere(self):
        self.assertTrue(True)

    @unittest.skipUnless(HAVE, "needs flh_fixture_dependency_that_is_never_installed")
    def test_needs_the_dependency(self):
        self.assertTrue(HAVE)


if __name__ == "__main__":
    unittest.main()
