#!/usr/bin/env python3
"""FLH-046 real-Qdrant regression: run the internal/vectorindex integration
suite against an actual Qdrant and fail unless every expected test passed.

Default mode starts a disposable Qdrant container from the exact image digest
pinned in compose.yaml (tmpfs storage, loopback-only random port), waits for
readiness within a bound, runs the suite with FLH_QDRANT_URL set, saves
artifacts and always removes the container. --endpoint URL instead uses an
already running Qdrant and starts nothing.

The suite uses deterministic fake embeddings: no embedding service, secret or
paid call is involved. There is no fallback: if Docker or Qdrant is
unavailable, the run fails.

Exit status: 0 all expected tests passed; 1 regression failure (failed,
skipped, missing, unexpected or zero tests, list drift, leftover collections);
2 usage; 3 environment (Docker or Qdrant unavailable, pull or readiness
failed, cleanup failed); 4 the test command timed out.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
EXPECTED_FILE = HERE / "expected_tests.txt"
COMPOSE_FILE = ROOT / "compose.yaml"
TEST_PACKAGE = "./internal/vectorindex"
TEST_DIR = ROOT / "internal" / "vectorindex"
TEST_PATTERN = "^TestQdrantIntegration_"
OWNED_COLLECTION_PREFIX = "flh042_it_"  # prefix the integration rig uses and deletes

EXIT_OK, EXIT_REGRESSION, EXIT_USAGE, EXIT_ENV, EXIT_TIMEOUT = 0, 1, 2, 3, 4

IMAGE_RE = re.compile(r"^\s*image:\s*(qdrant/qdrant:(v[0-9][^\s@]*)@sha256:[0-9a-f]{64})\s*$", re.M)
DECL_RE = re.compile(r"^func (TestQdrantIntegration_\w+)\(t \*testing\.T\)", re.M)


class Interrupted(Exception):
    pass


class EnvError(Exception):
    pass


def log(msg: str) -> None:
    print(f"[flh046] {msg}", flush=True)


# ---------------------------------------------------------------- pure logic


def pinned_image(compose_text: str) -> tuple[str, str]:
    """Return (image reference with digest, version tag) from compose.yaml."""
    found = IMAGE_RE.findall(compose_text)
    if len(found) != 1:
        raise EnvError(f"expected exactly one digest-pinned qdrant image in compose.yaml, found {len(found)}")
    return found[0][0], found[0][1]


def read_expected(text: str) -> list[str]:
    names = [line.strip() for line in text.splitlines()]
    return [n for n in names if n and not n.startswith("#")]


def declared_tests(sources: list[str]) -> list[str]:
    out: list[str] = []
    for src in sources:
        out.extend(DECL_RE.findall(src))
    return out


def evaluate(events: list[dict], expected: list[str], declared: list[str], exit_code: int | None) -> dict:
    """Decide the verdict from `go test -json` events. Pure; unit-tested."""
    reasons: list[str] = []
    if sorted(set(expected)) != sorted(expected):
        reasons.append("expected_tests.txt lists a test twice")
    if sorted(expected) != sorted(declared):
        missing_decl = sorted(set(expected) - set(declared))
        new_decl = sorted(set(declared) - set(expected))
        reasons.append(f"expected list drifted from source (listed but not declared {missing_decl}; declared but not listed {new_decl})")

    results: dict[str, str] = {}  # top-level test -> final action
    skipped_any: list[str] = []
    failed_any: list[str] = []
    for ev in events:
        name, action = ev.get("Test"), ev.get("Action")
        if not name or action not in ("pass", "fail", "skip"):
            continue
        if action == "skip":
            skipped_any.append(name)
        if action == "fail":
            failed_any.append(name)
        if "/" not in name:
            results[name] = action
    package_failed = any(ev.get("Action") in ("fail", "build-fail") and not ev.get("Test") for ev in events)

    if not results:
        reasons.append("zero tests ran")
    if skipped_any:
        reasons.append(f"skipped: {sorted(set(skipped_any))}")
    if failed_any:
        reasons.append(f"failed: {sorted(set(failed_any))}")
    not_run = sorted(set(expected) - set(results))
    if not_run:
        reasons.append(f"expected but not run: {not_run}")
    unexpected = sorted(set(results) - set(expected))
    if unexpected:
        reasons.append(f"ran but not expected: {unexpected}")
    if package_failed and not failed_any:
        reasons.append("package failed (build error or test binary failure)")
    if exit_code not in (0, None) and not reasons:
        reasons.append(f"go test exited {exit_code}")
    if exit_code is None:
        reasons.append("go test did not finish")
    passed = sorted(n for n, a in results.items() if a == "pass")
    return {"ok": not reasons, "reasons": reasons, "results": dict(sorted(results.items())), "passed": passed}


# ---------------------------------------------------------------- side effects


def run(cmd: list[str], timeout: float, check: bool = True) -> subprocess.CompletedProcess:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise EnvError(f"{cmd[0]} not found") from e
    except subprocess.TimeoutExpired as e:
        raise EnvError(f"{' '.join(cmd[:3])} timed out after {timeout:.0f}s") from e
    if check and p.returncode != 0:
        raise EnvError(f"{' '.join(cmd[:3])} failed ({p.returncode}): {p.stderr.strip()[-500:]}")
    return p


def http_json(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 (loopback/operator URL)
        body = r.read(1 << 20)
        return r.status, (json.loads(body) if body.strip().startswith((b"{", b"[")) else body.decode(errors="replace"))


def wait_ready(url: str, deadline_s: float) -> dict:
    end = time.monotonic() + deadline_s
    last = "no attempt"
    while time.monotonic() < end:
        try:
            status, _ = http_json(url.rstrip("/") + "/readyz", timeout=2.0)
            if status == 200:
                _, info = http_json(url.rstrip("/") + "/", timeout=2.0)
                return info if isinstance(info, dict) else {"raw": info}
            last = f"HTTP {status}"
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = str(getattr(e, "reason", e))
        time.sleep(0.5)
    raise EnvError(f"Qdrant at {url} not ready within {deadline_s:.0f}s (last: {last})")


def owned_collections(url: str) -> list[str]:
    _, body = http_json(url.rstrip("/") + "/collections", timeout=5.0)
    names = [c["name"] for c in body["result"]["collections"]]
    return sorted(n for n in names if n.startswith(OWNED_COLLECTION_PREFIX))


def delete_collections(url: str, names: list[str]) -> list[str]:
    """Delete the given collections; return those that could not be deleted."""
    failed = []
    for n in names:
        req = urllib.request.Request(url.rstrip("/") + "/collections/" + urllib.parse.quote(n), method="DELETE")
        try:
            with urllib.request.urlopen(req, timeout=10.0) as r:  # noqa: S310
                if r.status != 200:
                    failed.append(n)
        except (urllib.error.URLError, OSError):
            failed.append(n)
    return failed


def run_suite(url: str, artifacts: Path, timeout_s: int) -> tuple[list[dict], int | None, bool]:
    """Run go test -json; stream to artifacts. Returns (events, exit code, timed_out)."""
    cmd = ["go", "test", "-json", "-count=1", f"-timeout={timeout_s}s", "-run", TEST_PATTERN, TEST_PACKAGE]
    env = dict(os.environ, FLH_QDRANT_URL=url)
    log("running: FLH_QDRANT_URL=" + url + " " + " ".join(cmd))
    events: list[dict] = []
    raw = (artifacts / "go-test.jsonl").open("w")
    readable = (artifacts / "go-test.txt").open("w")
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    # go's own -timeout normally fires first; the watchdog also bounds a
    # silent hang (for example a stuck build) and kills the whole group.
    fired = threading.Event()

    def kill_group() -> None:
        fired.set()
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    watchdog = threading.Timer(timeout_s + 120, kill_group)
    watchdog.daemon = True
    watchdog.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            raw.write(line)
            try:
                ev = json.loads(line)
            except ValueError:
                readable.write(line)
                sys.stdout.write(line)
                continue
            events.append(ev)
            out = ev.get("Output")
            if out:
                readable.write(out)
                sys.stdout.write(out)
        proc.wait()
    finally:
        watchdog.cancel()
        if proc.poll() is None or fired.is_set():
            kill_group()
            proc.wait()
        # The test binary is a child of `go` in the same group; make sure the
        # whole group is gone before anyone lists leftover collections.
        group_gone = time.monotonic() + 10
        while time.monotonic() < group_gone:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                break
            time.sleep(0.1)
        raw.close()
        readable.close()
    timed_out = fired.is_set()
    if any("panic: test timed out" in (ev.get("Output") or "") for ev in events):
        timed_out = True
    return events, (None if timed_out else proc.returncode), timed_out


class Container:
    def __init__(self, image: str, artifacts: Path, pull_timeout: int):
        self.image, self.artifacts, self.pull_timeout = image, artifacts, pull_timeout
        self.name = f"flh046-qdrant-{secrets.token_hex(6)}"
        self.started = False

    def start(self) -> str:
        run(["docker", "version", "--format", "{{.Server.Version}}"], 30)
        log(f"pulling {self.image}")
        run(["docker", "pull", self.image], self.pull_timeout)
        log(f"starting container {self.name}")
        self.started = True  # from here on, cleanup must run
        run(["docker", "run", "-d", "--pull", "never", "--name", self.name,
             "--label", "org.flh.task=flh046",
             "-p", "127.0.0.1::6333",
             "--tmpfs", "/qdrant/storage:rw,size=1g",
             "-e", "QDRANT__TELEMETRY_DISABLED=true",
             "-e", "QDRANT__STORAGE__SNAPSHOTS_PATH=/qdrant/storage/snapshots",
             self.image], 120)
        port = run(["docker", "port", self.name, "6333/tcp"], 30).stdout.strip().splitlines()[0]
        host_port = port.rsplit(":", 1)[1]
        return f"http://127.0.0.1:{host_port}"

    def cleanup(self) -> dict:
        if not self.started:
            return {"container": None}
        result: dict = {"container": self.name}
        for fname, cmd in (("qdrant.log", ["docker", "logs", self.name]),
                           ("docker-inspect.json", ["docker", "inspect", self.name])):
            try:
                p = run(cmd, 60, check=False)
                (self.artifacts / fname).write_text(p.stdout + p.stderr)
            except EnvError as e:
                result[f"{fname}_error"] = str(e)
        try:
            run(["docker", "rm", "-f", "-v", self.name], 60, check=False)
            left = run(["docker", "ps", "-a", "-q", "--filter", f"name=^/{self.name}$"], 30).stdout.strip()
            result["removed"] = left == ""
        except EnvError as e:
            result["removed"], result["error"] = False, str(e)
        return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--endpoint", help="use an already running Qdrant at this URL; start nothing")
    ap.add_argument("--artifacts", help="directory for logs and summary (default: a new temp dir)")
    ap.add_argument("--ready-timeout", type=int, default=60, help="seconds to wait for Qdrant readiness (default 60)")
    ap.add_argument("--pull-timeout", type=int, default=300, help="seconds allowed for docker pull (default 300)")
    ap.add_argument("--test-timeout", type=int, default=600, help="go test -timeout in seconds (default 600)")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return EXIT_USAGE if e.code else EXIT_OK
    for v in (args.ready_timeout, args.pull_timeout, args.test_timeout):
        if not 1 <= v <= 3600:
            print("timeouts must be between 1 and 3600 seconds", file=sys.stderr)
            return EXIT_USAGE
    if args.endpoint and not re.match(r"^https?://[^\s/]+(/.*)?$", args.endpoint):
        print("--endpoint must be an http(s) URL", file=sys.stderr)
        return EXIT_USAGE

    artifacts = Path(args.artifacts) if args.artifacts else Path(tempfile.mkdtemp(prefix="flh046-"))
    artifacts.mkdir(parents=True, exist_ok=True)
    summary: dict = {"mode": "endpoint" if args.endpoint else "container", "artifacts": str(artifacts)}

    def on_signal(signum, _frame):
        raise Interrupted(f"signal {signum}")

    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, on_signal)

    code = EXIT_ENV
    container = None
    url = None
    before = None  # test-prefix collections present before the suite ran
    try:
        expected = read_expected(EXPECTED_FILE.read_text())
        declared = declared_tests([p.read_text() for p in sorted(TEST_DIR.glob("*_test.go"))])
        summary["expected"] = expected
        if args.endpoint:
            url = args.endpoint.rstrip("/")
        else:
            image, tag = pinned_image(COMPOSE_FILE.read_text())
            summary["image"] = image
            container = Container(image, artifacts, args.pull_timeout)
            url = container.start()
        summary["url"] = url
        info = wait_ready(url, args.ready_timeout)
        summary["qdrant"] = info
        log(f"Qdrant ready: {info.get('version')} at {url}")
        if container and info.get("version") != tag.lstrip("v"):
            raise EnvError(f"running Qdrant {info.get('version')} does not match pinned tag {tag}")
        before = owned_collections(url)
        events, exit_code, timed_out = run_suite(url, artifacts, args.test_timeout)
        verdict = evaluate(events, expected, declared, exit_code)
        try:
            after = owned_collections(url)
            leftover = sorted(set(after) - set(before))
        except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
            leftover = [f"<could not list collections: {e}>"]
        if leftover:
            # Normally the rig's t.Cleanup deletes them; a killed or timed-out
            # test binary cannot. They are removed in the finally block below.
            verdict["ok"] = False
            verdict["reasons"].append(f"test collections left behind: {leftover}")

        summary.update(verdict=verdict, go_exit=exit_code, timed_out=timed_out)
        if timed_out:
            code = EXIT_TIMEOUT
        else:
            code = EXIT_OK if verdict["ok"] else EXIT_REGRESSION
    except EnvError as e:
        summary["error"] = str(e)
        log(f"environment error: {e}")
        code = EXIT_ENV
    except Interrupted as e:
        summary["error"] = f"interrupted ({e})"
        log(f"interrupted: {e}")
        code = EXIT_ENV
    finally:
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(s, signal.SIG_IGN)  # never abandon cleanup halfway
        if url and before is not None and not (container and container.started):
            # Endpoint mode: remove only collections with the rig's prefix that
            # appeared during this run (a container is discarded anyway).
            # A create request already in flight when the test binary was
            # killed can still complete after a first sweep, so sweep until a
            # round finds nothing new (bounded).
            found: list[str] = []
            undeleted: list[str] = []
            try:
                for _ in range(5):
                    new = sorted(set(owned_collections(url)) - set(before) - set(found))
                    if not new:
                        break
                    found += new
                    undeleted = delete_collections(url, sorted(set(owned_collections(url)) - set(before)))
                    time.sleep(1.0)
                else:
                    undeleted = sorted(set(owned_collections(url)) - set(before))
                summary["leftover_cleanup"] = {"found": found, "not_deleted": undeleted}
                if found:
                    log(f"deleted {len(found) - len(undeleted)} leftover test collection(s); not deleted: {undeleted}")
                if undeleted:
                    code = code or EXIT_ENV
            except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
                summary["leftover_cleanup"] = {"error": str(e)}
        if container and container.started:
            summary["cleanup"] = c = container.cleanup()
            if c.get("removed") is False:
                log(f"cleanup FAILED for {container.name}: {c}")
                code = code or EXIT_ENV
                summary.setdefault("error", "container cleanup failed")
            else:
                log(f"removed container {container.name}")
        summary["exit"] = code
        (artifacts / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    v = summary.get("verdict")
    if v:
        log(f"{len(v['passed'])}/{len(summary['expected'])} expected tests passed")
        for r in v["reasons"]:
            log(f"FAIL: {r}")
    log(f"{'PASS' if code == EXIT_OK else 'FAIL'} (exit {code}); artifacts in {artifacts}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
