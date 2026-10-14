"""FLH-065 tests for runner.py (POSIX here; the Windows CTRL_BREAK path is not run).

python3 -B -m unittest discover -s tools/embedding/e5/windows/operations/tests -p 'test_*.py'
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(os.path.dirname(HERE), "runner.py")
FAKE_E5 = os.path.join(HERE, "fake_e5")
MODEL_FILES = ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
               "special_tokens_map.json", "sentencepiece.bpe.model")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(pred, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(0.1)
    return None


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="flh065 runner ")
        self.addCleanup(self.tmp.cleanup)  # runs last: cleanups are LIFO and follow tearDown
        self.root = self.tmp.name
        self.model = os.path.join(self.root, "model dir with spaces")
        os.makedirs(self.model)
        for f in MODEL_FILES:
            open(os.path.join(self.model, f), "w").close()
        self.run_dir = os.path.join(self.root, "run dir")
        os.makedirs(self.run_dir)
        self.port = free_port()
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait()

    def spec(self, mode="ready", graceful=5, args=None, **extra):
        with open(os.path.join(self.model, "FAKE_MODE"), "w") as f:
            f.write(mode)
        spec = {
            "schema": "flh065_e5_launch_v1", "run_id": "20260101T000000Z-abcdef01", "run_dir": self.run_dir,
            "python": sys.executable,
            "args": args or ["-B", "-m", "flh_e5", "serve", "--model-dir", self.model, "--host", "127.0.0.1",
                             "--port", str(self.port), "--dtype", "float16", "--microbatch", "8", "--batching", "singleton_v1"],
            "cwd": FAKE_E5, "env_set": {"FLH065_MARK": "a value with spaces"}, "env_path_prepend": [self.root],
            "stdout_log": os.path.join(self.run_dir, "stdout.log"), "stderr_log": os.path.join(self.run_dir, "stderr.log"),
            "stop_request": os.path.join(self.run_dir, "stop-request.json"), "graceful_timeout_s": graceful,
        }
        spec.update(extra)
        path = os.path.join(self.run_dir, "launch.json")
        with open(path, "w", encoding="utf-8-sig") as f:  # BOM, as PowerShell 5.1 may write
            json.dump(spec, f)
        return path

    def launch(self, spec_path):
        p = subprocess.Popen([sys.executable, "-B", "-I", RUNNER, "--spec", spec_path],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.procs.append(p)
        return p

    def ready(self):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/readyz" % self.port, timeout=1) as r:
                return r.status == 200
        except OSError:
            return False

    def stop(self, mode="graceful", timeout=None):
        req = {"mode": mode}
        if timeout is not None:
            req["graceful_timeout_s"] = timeout
        with open(os.path.join(self.run_dir, "stop-request.json"), "w") as f:
            json.dump(req, f)

    def test_graceful_stop_records_exit(self):
        p = self.launch(self.spec())
        self.assertTrue(wait_for(self.ready), "fake service became ready")
        rj = read_json(os.path.join(self.run_dir, "runner.json"))
        self.assertEqual(rj["state"], "running")
        self.assertEqual(rj["runner_pid"], p.pid)
        self.stop()
        self.assertEqual(p.wait(timeout=15), 0)
        ex = read_json(os.path.join(self.run_dir, "exit.json"))
        self.assertEqual(ex["reason"], "stop_requested_graceful")
        self.assertEqual(ex["child_exit_code"], 0)
        with open(os.path.join(self.run_dir, "stderr.log"), encoding="utf-8") as f:
            err = f.read()
        self.assertIn("stopping", err)
        with open(os.path.join(self.run_dir, "stdout.log"), encoding="utf-8") as f:
            self.assertIn("fake stdout line", f.read())

    def test_arguments_with_spaces_reach_the_child_exactly(self):
        p = self.launch(self.spec())
        self.assertTrue(wait_for(self.ready))
        with open(os.path.join(self.model, "argv.log"), encoding="utf-8") as f:
            argv = json.loads(f.readlines()[-1])
        self.assertEqual(argv[1:5], ["serve", "--model-dir", self.model, "--host"])
        self.stop()
        p.wait(timeout=15)

    def test_environment_additions(self):
        out = os.path.join(self.root, "env.json")
        code = "import json,os,sys; json.dump({'mark': os.environ.get('FLH065_MARK'), 'path0': os.environ['PATH'].split(os.pathsep)[0]}, open(sys.argv[1],'w'))"
        p = self.launch(self.spec(args=["-c", code, out]))
        self.assertEqual(p.wait(timeout=15), 0)
        env = read_json(out)
        self.assertEqual(env["mark"], "a value with spaces")
        self.assertEqual(env["path0"], self.root)
        self.assertEqual(read_json(os.path.join(self.run_dir, "exit.json"))["reason"], "exited")

    def test_startup_failure_exit_code_recorded(self):
        p = self.launch(self.spec(mode="fail"))
        self.assertEqual(p.wait(timeout=15), 0)
        ex = read_json(os.path.join(self.run_dir, "exit.json"))
        self.assertEqual((ex["reason"], ex["child_exit_code"]), ("exited", 3))

    def test_forced_after_graceful_timeout(self):
        p = self.launch(self.spec(mode="ignore-signals", graceful=1))
        self.assertTrue(wait_for(self.ready))
        self.stop()
        p.wait(timeout=15)
        ex = read_json(os.path.join(self.run_dir, "exit.json"))
        self.assertEqual(ex["reason"], "stop_requested_forced")
        self.assertFalse(self.ready())

    def test_force_mode_skips_grace(self):
        p = self.launch(self.spec(mode="ignore-signals", graceful=60))
        self.assertTrue(wait_for(self.ready))
        t0 = time.monotonic()
        self.stop(mode="force")
        p.wait(timeout=15)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(read_json(os.path.join(self.run_dir, "exit.json"))["reason"], "stop_requested_forced")

    def test_launch_failure(self):
        p = self.launch(self.spec(python=os.path.join(self.root, "no python here")))
        self.assertEqual(p.wait(timeout=15), 1)
        ex = read_json(os.path.join(self.run_dir, "exit.json"))
        self.assertEqual(ex["reason"], "launch_failed")

    def test_invalid_spec_refused(self):
        path = os.path.join(self.run_dir, "bad.json")
        with open(path, "w") as f:
            json.dump({"schema": "other"}, f)
        p = self.launch(path)
        self.assertEqual(p.wait(timeout=15), 2)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "runner.json")))
        rel = self.spec(cwd="relative/dir")
        p = self.launch(rel)
        self.assertEqual(p.wait(timeout=15), 2)

    def test_child_survives_runner_parent_exit(self):
        """The runner must not depend on its launcher: start it through a parent
        that exits immediately, then stop it through the stop file."""
        spec = self.spec()
        launcher = subprocess.run([sys.executable, "-c",
                                   "import subprocess,sys; p=subprocess.Popen([sys.executable,'-B','-I',sys.argv[1],'--spec',sys.argv[2]], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); print(p.pid)",
                                   RUNNER, spec], capture_output=True, text=True, timeout=15)
        runner_pid = int(launcher.stdout.strip())
        def stop_detached():  # if an assertion fails, the detached runner still stops its child
            self.stop()
            wait_for(lambda: read_json(os.path.join(self.run_dir, "exit.json")), 15)
        self.addCleanup(stop_detached)
        self.assertTrue(wait_for(self.ready), "service ready after its launcher exited")
        self.stop()
        self.assertTrue(wait_for(lambda: read_json(os.path.join(self.run_dir, "exit.json"))))
        try:
            os.kill(runner_pid, 0)
            alive = wait_for(lambda: not _alive(runner_pid), 10) is None
        except OSError:
            alive = False
        self.assertFalse(alive)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


if __name__ == "__main__":
    unittest.main()
