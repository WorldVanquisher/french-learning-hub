"""Self-tests of ownership.evaluate(): no Docker, no network.

    python3 -B -m unittest discover -s scripts/validation/v1_rehearsal -p 'test_*.py'
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ownership  # noqa: E402

PROJECT = "flh-rehearsal-20261108010203"
WORK = "/scratch/smoke/instance"
REPO = "/src/flh"
FAKE = "python:3.12-slim@sha256:" + "a" * 64


def container(service, project=PROJECT, **over):
    c = {
        "Id": f"{service}-id",
        "Name": f"/{project}-{service}-1",
        "State": {"Running": True, "Status": "running"},
        "Config": {
            "Image": f"{PROJECT}:app" if service == "app" else FAKE,
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
                "com.docker.compose.project.config_files": f"{REPO}/compose.yaml,{WORK}/compose/upgrade.yaml",
                "com.docker.compose.project.working_dir": REPO,
            },
            "Env": [
                "OPENAI_BASE_URL=http://fake-provider:19195/v1",
                "OPENAI_API_KEY=placeholder-not-a-real-key",
                "AI_PROVIDER=openai", "EXTRACTOR_PROVIDER=openai", "SUGGESTION_PROVIDER=openai",
            ] if service == "app" else [],
            "Entrypoint": None,
            "Cmd": ["python3", "-I", "-B", "/fixture/fake_openai.py", "19195"] if service == "fake-provider" else ["/app/server"],
        },
        "NetworkSettings": {
            "Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18995"}]} if service == "app" else {},
            "Networks": {f"{project}_default": {}},
        },
        "Mounts": [{"Source": f"{WORK}/data", "Destination": "/data"}] if service == "app" else
                  [{"Source": f"{REPO}/scripts/validation/daily_v1_rc", "Destination": "/fixture"}],
    }
    c.update(over)
    return c


def daily():
    return {
        "Id": "daily", "Name": "/french-learning-hub-app-1",
        "State": {"Running": True},
        "Config": {"Image": "french-learning-hub:local",
                   "Labels": {"com.docker.compose.project": "french-learning-hub", "com.docker.compose.service": "app"}},
        "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}},
        "Mounts": [{"Source": "/home/owner/flh-data", "Destination": "/data"}],
    }


def state(**over):
    s = {
        "project": PROJECT, "recorded_project": PROJECT, "port": "18995", "work": WORK, "repo": REPO,
        "image": f"{PROJECT}:app", "fake_image": FAKE,
        "containers": [container("app"), container("fake-provider"), daily()],
        "http": {"readyz": {"status": "ready"}, "suggestions_enabled": True, "entries": 0},
    }
    s.update(over)
    return s


def failed(s):
    verdict, checks = ownership.evaluate(s)
    return verdict, [name for ok, name, _ in checks if not ok]


class Evaluate(unittest.TestCase):
    def test_owned(self):
        verdict, bad = failed(state())
        self.assertEqual((verdict, bad), ("owned", []))

    def test_daily_project_refused(self):
        s = state(project="french-learning-hub", recorded_project="french-learning-hub",
                  containers=[daily()])
        self.assertEqual(failed(s)[0], "refused")
        self.assertIn("rehearsal project name", failed(s)[1])

    def test_unrecorded_project_refused(self):
        self.assertIn("project recorded by serve in WORK/project", failed(state(recorded_project="flh-rehearsal-20260101000000"))[1])

    def test_missing_fake_provider_refused(self):
        self.assertEqual(failed(state(containers=[container("app")]))[0], "refused")

    def test_other_compose_files_refused(self):
        app = container("app")
        app["Config"]["Labels"]["com.docker.compose.project.config_files"] = f"{REPO}/compose.yaml"
        self.assertIn("app was created from compose.yaml + WORK/compose/upgrade.yaml",
                      failed(state(containers=[app, container("fake-provider")]))[1])

    def test_daily_image_refused(self):
        app = container("app")
        app["Config"]["Image"] = "french-learning-hub:local"
        self.assertIn("app image is the rehearsal tag", failed(state(containers=[app, container("fake-provider")]))[1])

    def test_wrong_or_public_port_refused(self):
        for binding in ({"HostIp": "0.0.0.0", "HostPort": "18995"}, {"HostIp": "127.0.0.1", "HostPort": "8080"}):
            app = container("app")
            app["NetworkSettings"]["Ports"] = {"8080/tcp": [binding]}
            self.assertEqual(failed(state(containers=[app, container("fake-provider")]))[0], "refused", binding)

    def test_port_shared_with_another_container_refused(self):
        other = daily()
        other["NetworkSettings"]["Ports"] = {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18995"}]}
        self.assertIn("no other container publishes 18995",
                      failed(state(containers=[container("app"), container("fake-provider"), other]))[1])

    def test_foreign_data_mount_refused(self):
        app = container("app", Mounts=[{"Source": "/home/owner/flh-data", "Destination": "/data"}])
        self.assertIn("app mounts only WORK/data on /data", failed(state(containers=[app, container("fake-provider")]))[1])

    def test_real_provider_refused(self):
        for env in ("OPENAI_BASE_URL=https://api.openai.com/v1", "OPENAI_API_KEY=sk-something"):
            app = container("app")
            key = env.split("=")[0]
            app["Config"]["Env"] = [e for e in app["Config"]["Env"] if not e.startswith(key + "=")] + [env]
            self.assertEqual(failed(state(containers=[app, container("fake-provider")]))[0], "refused", env)

    def test_key_value_never_reported(self):
        app = container("app")
        app["Config"]["Env"] = [e for e in app["Config"]["Env"] if not e.startswith("OPENAI_API_KEY=")] + ["OPENAI_API_KEY=sk-secret-value"]
        _, checks = ownership.evaluate(state(containers=[app, container("fake-provider")]))
        self.assertNotIn("sk-secret-value", repr(checks))

    def test_fake_provider_publishing_refused(self):
        fake = container("fake-provider")
        fake["NetworkSettings"]["Ports"] = {"19195/tcp": [{"HostIp": "0.0.0.0", "HostPort": "19195"}]}
        self.assertIn("fake provider publishes no port", failed(state(containers=[container("app"), fake]))[1])

    def test_stopped_container_refused(self):
        app = container("app", State={"Running": False, "Status": "restarting"})
        self.assertIn("app is running", failed(state(containers=[app, container("fake-provider")]))[1])

    def test_non_empty_or_unready_url_refused(self):
        for http in ({"readyz": {"status": "ready"}, "suggestions_enabled": True, "entries": 1},
                     {"readyz": {"status": "not_ready"}, "suggestions_enabled": True, "entries": 0},
                     {"readyz": {"status": "ready"}, "suggestions_enabled": False, "entries": 0}):
            self.assertEqual(failed(state(http=http))[0], "refused", http)

    def test_input_not_mutated(self):
        s = state()
        before = copy.deepcopy(s)
        ownership.evaluate(s)
        self.assertEqual(s, before)


if __name__ == "__main__":
    unittest.main()
