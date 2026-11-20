"""Every setting the server reads is forwarded by compose.yaml, fixed by it, or excluded on purpose (R3-064).

  python3 -I -B scripts/release/test_compose_forwarding.py

The server's settings are the names internal/config and cmd/server read; the forwarded ones are
the keys under the app service's `environment:` in compose.yaml. A server setting that is neither
forwarded nor listed in EXCLUDED fails, and so does an excluded name that compose now forwards:
both directions need a deliberate edit here, with the reason.
"""
import glob
import os
import re
import unittest

REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# set by compose.yaml to a fixed value, never taken from the operator's settings
FIXED = {"PORT", "DB_PATH"}

# name -> why the packaged release does not forward it
EXCLUDED = {
    "LISTEN_HOST": "the container listens on every interface inside its network; compose publishes 127.0.0.1 only",
    "SPEAKING_TRANSCRIPTION_BASE_URL": "local transcription is not packaged: flh-daily.sh check accepts only openai or disabled "
                                       "(R3 plan §8: enabled together with the wrapper after the owner approves the sidecar)",
    "SPEAKING_TRANSCRIPTION_TIMEOUT": "only the local transcription provider reads it (see SPEAKING_TRANSCRIPTION_BASE_URL)",
}


def server_settings():
    names = set()
    for f in glob.glob(os.path.join(REPO, "internal", "config", "*.go")) + glob.glob(os.path.join(REPO, "cmd", "server", "*.go")):
        if f.endswith("_test.go"):
            continue
        with open(f, encoding="utf-8") as fh:
            text = fh.read()
        names |= set(re.findall(r'(?:Getenv|LookupEnv|getdur|getint|getbool|get\w*|\.get)\(\s*"([A-Z][A-Z0-9_]+)"', text))
    return names


def forwarded():
    with open(os.path.join(REPO, "compose.yaml"), encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"^  app:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)", text, re.S | re.M)
    assert m, "compose.yaml has no app service"
    env = re.search(r"^    environment:\n((?:^      .*\n)+)", m.group(1), re.M)
    assert env, "the app service has no environment block"
    return dict(re.findall(r"^      ([A-Z][A-Z0-9_]+):\s*(.*)$", env.group(1), re.M))


class ComposeForwarding(unittest.TestCase):
    def test_every_server_setting_is_forwarded_or_excluded_on_purpose(self):
        read, fwd = server_settings(), set(forwarded())
        self.assertGreater(len(read), 30, "the settings scan found too few names; the reader pattern changed")
        self.assertEqual(sorted(read - fwd), sorted(EXCLUDED), "server settings compose does not forward")

    def test_excluded_names_are_not_forwarded_and_fixed_ones_are_literal(self):
        env = forwarded()
        self.assertEqual(sorted(set(EXCLUDED) & set(env)), [])
        for name in FIXED:
            with self.subTest(name=name):
                self.assertIn(name, env)
                self.assertNotIn("${", env[name], f"{name} must be fixed, not taken from the settings")

    def test_local_transcription_exclusion_matches_the_wrapper(self):
        with open(os.path.join(REPO, "scripts", "daily", "flh-daily.sh"), encoding="utf-8") as fh:
            wrapper = fh.read()
        refuses_local = 'if stt not in ("openai", "disabled")' in wrapper
        self.assertEqual(refuses_local, "SPEAKING_TRANSCRIPTION_BASE_URL" in EXCLUDED,
                         "the wrapper and compose must enable local transcription together")


if __name__ == "__main__":
    unittest.main()
