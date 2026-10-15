#!/usr/bin/env python3
"""FLH-079 offline acceptance of the read-only public demo (local and CI).

    python3 -B scripts/validation/flh079/run.py --work /abs/new/dir [--port 18990]
        [--require-browser] [--chrome PATH] [--npm-cache DIR] [--keep-work]
        [--probe assertion-failure|interrupt-hold]

One entry point that, inside a new task-local WORK directory outside the
repository:

  1. builds the real server and the FLH-073 `prepare` tool from source;
  2. builds a synthetic MECHANICAL artifact from the FLH-073 fixtures and checks
     that release validation refuses it (exit 3, BLOCKED) and that the server
     refuses it without -public-demo-allow-mechanical or with a live provider;
  3. builds the public-demo web bundle from a copy of web/ (npm ci into WORK);
  4. starts the demo on 127.0.0.1 and records HTTP evidence: static HTML and
     every referenced asset, root and /api routing, keyword search, preset
     semantic and hybrid search, every Concept detail with the original
     question behind each supporting unit, and denied write, free-text and
     private-file routes;
  5. restarts the server and checks identical responses and unchanged artifact
     bytes;
  6. runs the FLH-076 browser acceptance (scripts/demo/flh076/browser/accept.mjs)
     against it when a Chrome/Chromium is available, recorded as DOM evidence;
  7. stops the server and checks the artifact bytes and validation once more.

Mechanical vectors prove routing, preset and ranking MECHANICS only; nothing
here measures retrieval quality.

The application behaviour under test is never reimplemented: the server,
`prepare`, the web build and accept.mjs are the repository's own. Processes are
started and stopped through scripts/demo/flh034/proc_guard.py, which signals a
PID only when its start time and command line match the recorded launch.

Output: WORK/diagnostics/summary.json (schema flh079_public_demo_ci_summary_v1)
with explicit PASS / FAIL / BLOCKED / NOT RUN states, plus bounded logs and
browser screenshots. Unless --keep-work, everything else under WORK (binaries,
artifact database and vectors, node_modules, npm cache) is removed at the end.

Exit codes: 0 PASS, 1 FAIL, 2 usage or refused preflight, 3 BLOCKED (a required
prerequisite such as the browser is missing), 128+N interrupted by signal N.
"""

import argparse
import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone

SCHEMA = "flh079_public_demo_ci_summary_v1"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PROC_GUARD = os.path.join(REPO, "scripts", "demo", "flh034", "proc_guard.py")
ACCEPT_MJS = os.path.join(REPO, "scripts", "demo", "flh076", "browser", "accept.mjs")
FIXTURES = os.path.join(REPO, "scripts", "demo", "flh073", "fixtures", "catalog.json")
# Same pin as scripts/demo/flh076/browser/run.sh; no browser is downloaded.
PLAYWRIGHT_CORE = "playwright-core@1.49.1"
# Only these web/ sources are copied; node_modules and dist never are.
WEB_SOURCES = ("index.html", "package.json", "package-lock.json", "src",
               "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json", "vite.config.ts")
CHROME_CANDIDATES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
LOG_LIMIT = 200_000  # bytes kept from the end of each copied log
FIXTURE_EXTRACTOR = "fixture:flh073:knowledge_extraction_v1"
FIXTURE_ANALYZER = "fixture:flh073:fr_l2_taxonomy_v1"
PREFIXES = ("", "/api")
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
WRITE_PATHS = ("/entries", "/captures", "/concepts", "/knowledge-library/concepts",
               "/knowledge-units/1/concept-links/same", "/knowledge-units/1/concept-membership",
               "/knowledge-library/demo/hybrid-search?preset=subjunctive")
PRIVATE_API_PATHS = ("/entries", "/entries/1", "/concepts", "/concepts/1", "/reviewable-units", "/inventory",
                     "/captures/x", "/annotation-dataset/v1/export", "/annotation-dataset/v1/quality",
                     "/retrieval-evaluation/v1", "/retrieval-comparison/v1", "/annotation-operations/x")
FREE_TEXT_PATHS = ("/knowledge-library/semantic-search?q=subjunctive",
                   "/knowledge-library/hybrid-search?q=subjunctive")
# Raw paths (sent byte for byte) naming artifact or working files; none may be served.
PRIVATE_FILE_PATHS = ("/demo.db", "/manifest.json", "/vectors.json", "/fixtures.json", "/.env", "/server.log",
                      "/server", "/artifact/demo.db", "/assets/../demo.db", "/assets/../../artifact/demo.db",
                      "/assets/%2e%2e/%2e%2e/artifact/demo.db", "/api/../demo.db", "/%2e%2e/artifact/demo.db",
                      "/assets/", "/api/demo.db", "/api/assets/../manifest.json")


class Abort(Exception):
    """Stops the run after a recorded failure; cleanup still runs."""


class Interrupted(BaseException):
    def __init__(self, signum):
        super().__init__(f"signal {signum}")
        self.signum = signum


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def tree_hashes(root):
    """{relative path: sha256} of every regular file under root."""
    out = {}
    for dirpath, _, files in os.walk(root):
        for name in files:
            p = os.path.join(dirpath, name)
            out[os.path.relpath(p, root)] = sha256_file(p)
    return dict(sorted(out.items()))


def tail_copy(src, dst, limit=LOG_LIMIT):
    """Copy at most the last `limit` bytes of src; returns False if src is missing."""
    try:
        size = os.path.getsize(src)
        with open(src, "rb") as f:
            if size > limit:
                f.seek(size - limit)
            data = f.read()
    except OSError:
        return False
    with open(dst, "wb") as f:
        if size > limit:
            f.write(b"[truncated: last %d of %d bytes]\n" % (limit, size))
        f.write(data)
    return True


def asset_refs(html):
    """Same-origin /assets/ paths referenced by src= or href= in the HTML."""
    return sorted(set(re.findall(r'(?:src|href)="(/assets/[^"?#]+)"', html)))


def overall_status(stages, checks):
    """FAIL beats BLOCKED beats PASS; NOT RUN stages never make a run PASS by themselves."""
    states = [s["status"] for s in stages] + [c["status"] for c in checks]
    if "FAIL" in states:
        return "FAIL"
    if "BLOCKED" in states:
        return "BLOCKED"
    return "PASS"


def exit_code_for(status):
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 3}[status]


def find_chrome(explicit):
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    env = os.environ.get("CHROME")
    if env:
        return env if os.access(env, os.X_OK) else None
    for name in CHROME_CANDIDATES:
        p = shutil.which(name)
        if p:
            return p
    return None


def port_in_use(port):
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return True
        except OSError:
            continue
        finally:
            s.close()
    return False


class Harness:
    def __init__(self, args):
        self.args = args
        self.work = args.work
        self.port = args.port
        self.run_dir = os.path.join(self.work, "run")  # proc_guard: the server binary is RUN/server
        self.bin_dir = os.path.join(self.work, "bin")
        self.artifact = os.path.join(self.work, "artifact")
        self.web_src = os.path.join(self.work, "websrc")
        self.web_out = os.path.join(self.work, "web")
        self.tools = os.path.join(self.work, "tools")
        self.logs = os.path.join(self.work, "logs")
        self.diag = os.path.join(self.work, "diagnostics")
        self.npm_cache = args.npm_cache or os.path.join(self.work, "npm-cache")
        self.stages, self.checks, self.cleanup = [], [], {}
        self.server_runs = 0
        self.started = time.monotonic()
        self.interrupted = None
        self.environment = {"platform": platform.platform(), "python": platform.python_version()}
        self.fixtures = json.load(open(FIXTURES, encoding="utf-8"))
        os.makedirs(self.logs)

    # ---- recording -------------------------------------------------------
    def check(self, cid, evidence, ok, detail=""):
        status = "PASS" if ok else "FAIL"
        self.checks.append({"id": cid, "evidence": evidence, "status": status, "detail": str(detail)[:400]})
        print(f"{status} [{evidence}] {cid}" + (f" — {str(detail)[:160]}" if detail and not ok else ""), flush=True)
        return ok

    def stage(self, name, fn):
        self.write_state(name)
        print(f"== stage {name}", flush=True)
        t0, before = time.monotonic(), sum(c["status"] == "FAIL" for c in self.checks)
        entry = {"name": name, "status": "PASS", "detail": ""}
        try:
            result = fn()
            if isinstance(result, tuple):  # (status, detail) for BLOCKED / NOT RUN
                entry["status"], entry["detail"] = result
        except Abort as e:
            entry["status"], entry["detail"] = "FAIL", str(e)
        except Interrupted:
            entry["status"], entry["detail"] = "FAIL", "interrupted"
            raise
        except Exception as e:  # unexpected harness error is a FAIL, never a PASS
            entry["status"], entry["detail"] = "FAIL", f"{type(e).__name__}: {e}"
        finally:
            if entry["status"] == "PASS" and sum(c["status"] == "FAIL" for c in self.checks) > before:
                entry["status"] = "FAIL"
                entry["detail"] = "one or more checks failed"
            entry["duration_s"] = round(time.monotonic() - t0, 1)
            self.stages.append(entry)
            print(f"== stage {name}: {entry['status']} {entry['detail']}", flush=True)
        return entry["status"]

    def write_state(self, stage, **extra):
        os.makedirs(self.diag, exist_ok=True)
        tmp = os.path.join(self.diag, "state.json.tmp")
        with open(tmp, "w") as f:
            json.dump({"stage": stage, "harness_pid": os.getpid(), **extra}, f)
        os.replace(tmp, os.path.join(self.diag, "state.json"))

    # ---- subprocesses ----------------------------------------------------
    def run(self, args, log, timeout, cwd=REPO, env=None, check=True):
        """Run a bounded child; stdout+stderr go to logs/<log>. Returns the exit code."""
        path = os.path.join(self.logs, log)
        with open(path, "ab") as out:
            out.write(f"$ {' '.join(args)}\n".encode())
            out.flush()
            try:
                rc = subprocess.run(args, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, timeout=timeout).returncode
            except subprocess.TimeoutExpired:  # subprocess.run kills its own child
                raise Abort(f"{args[0]} timed out after {timeout}s (see logs/{log})")
        if check and rc != 0:
            raise Abort(f"{os.path.basename(args[0])} exited {rc} (see logs/{log})")
        return rc

    def guard(self, *a, timeout=30):
        return subprocess.run([sys.executable, "-B", PROC_GUARD, *a], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)

    def tool_version(self, args):
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=30).stdout.strip().splitlines()[0]
        except (OSError, IndexError, subprocess.SubprocessError):
            return None

    # ---- HTTP ------------------------------------------------------------
    def http(self, method, path, timeout=15):
        """(status, headers, body) for a raw path sent byte for byte."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            headers = {"Content-Type": "application/json"} if method in WRITE_METHODS else {}
            conn.request(method, path, body=b"{}" if method in WRITE_METHODS else None, headers=headers)
            r = conn.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
        finally:
            conn.close()

    def get_json(self, path):
        status, _, body = self.http("GET", path)
        if status != 200:
            raise Abort(f"GET {path} -> {status}")
        return json.loads(body)

    def expect(self, cid, method, path, want):
        try:
            got = self.http(method, path)[0]
        except OSError as e:
            got = f"error {e}"
        return self.check(cid, "http", got == want, f"{method} {path} -> {got} (want {want})")

    # ---- stages ----------------------------------------------------------
    def preflight(self):
        missing = [t for t in ("go", "node", "npm") if shutil.which(t) is None]
        for p in (PROC_GUARD, ACCEPT_MJS, FIXTURES):
            if not os.path.exists(p):
                missing.append(p)
        self.environment.update({"go": self.tool_version(["go", "version"]), "node": self.tool_version(["node", "--version"]),
                                 "npm": self.tool_version(["npm", "--version"])})
        if missing:
            return "BLOCKED", "missing prerequisites: " + ", ".join(missing)
        self.check("preflight.port_free", "process", not port_in_use(self.port), f"port {self.port}")
        if port_in_use(self.port):
            raise Abort(f"port {self.port} is in use; choose another --port")

    def build(self):
        os.makedirs(self.run_dir, exist_ok=True)
        os.makedirs(self.bin_dir, exist_ok=True)
        self.run(["go", "build", "-o", os.path.join(self.run_dir, "server"), "./cmd/server"], "go-build.log", 600)
        self.run(["go", "build", "-o", os.path.join(self.bin_dir, "prepare"), "./scripts/demo/flh073/prepare"],
                 "go-build.log", 600)
        self.check("build.binaries", "artifact", all(os.access(p, os.X_OK) for p in
                   (os.path.join(self.run_dir, "server"), os.path.join(self.bin_dir, "prepare"))))

    def artifact_stage(self):
        prepare = os.path.join(self.bin_dir, "prepare")
        self.run([prepare, "build", "-out", self.artifact, "-fixtures", FIXTURES], "prepare-build.log", 120)
        rc = self.run([prepare, "validate", "-artifact", self.artifact], "prepare-validate.log", 60, check=False)
        self.check("artifact.validates", "artifact", rc == 0, f"validate exit {rc} (want 0)")
        rc = self.run([prepare, "validate", "-artifact", self.artifact, "-release"], "prepare-validate-release.log",
                      60, check=False)
        log = open(os.path.join(self.logs, "prepare-validate-release.log"), encoding="utf-8", errors="replace").read()
        self.check("artifact.release_validation_refuses_mechanical", "artifact",
                   rc == 3 and "RELEASE BLOCKED" in log, f"validate -release exit {rc} (want 3 = BLOCKED)")
        manifest = json.load(open(os.path.join(self.artifact, "manifest.json"), encoding="utf-8"))
        self.check("artifact.mechanical_release_status", "artifact",
                   manifest.get("release_status") == "blocked_mechanical_vectors", manifest.get("release_status"))
        self.hashes = tree_hashes(self.artifact)
        self.check("artifact.files", "artifact", set(self.hashes) == {"demo.db", "manifest.json", "vectors.json",
                                                                     "fixtures.json"}, sorted(self.hashes))
        # Server-side refusals: these start nothing that listens if the refusal works.
        rc, out = self.server_once([])
        self.check("artifact.server_refuses_mechanical_without_flag", "process",
                   rc not in (None, 0) and "-public-demo-allow-mechanical" in out, f"exit {rc}")
        rc, out = self.server_once(["-public-demo-allow-mechanical"], extra_env={
            "EMBEDDING_PROVIDER": "http", "EMBEDDING_BASE_URL": "http://127.0.0.1:9/v1", "EMBEDDING_MODEL": "m",
            "EMBEDDING_MODEL_ID": "m", "EMBEDDING_DIMENSIONS": "8"})
        self.check("artifact.server_refuses_live_provider", "process",
                   rc not in (None, 0) and "refuses live providers" in out, f"exit {rc}")
        for dirpath, dirs, files in os.walk(self.artifact):  # read-only while served
            for n in files + dirs:
                p = os.path.join(dirpath, n)
                os.chmod(p, os.stat(p).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        os.chmod(self.artifact, os.stat(self.artifact).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))

    def server_env(self, extra_env=None):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.run_dir, "LISTEN_HOST": "127.0.0.1", "PORT": str(self.port)}
        env.update(extra_env or {})
        return env

    def server_once(self, flags, extra_env=None):
        """Start a server expected to refuse; bounded, and it is our own direct child."""
        args = [os.path.join(self.run_dir, "server"), "-public-demo-artifact", self.artifact, *flags]
        try:
            r = subprocess.run(args, cwd=self.run_dir, env=self.server_env(extra_env), capture_output=True,
                               text=True, stdin=subprocess.DEVNULL, timeout=20)
        except subprocess.TimeoutExpired:
            return None, "did not exit within 20s (it was killed)"
        with open(os.path.join(self.logs, "server-refusals.log"), "a") as f:
            f.write(f"$ {' '.join(args)} -> {r.returncode}\n{r.stdout}{r.stderr}\n")
        return r.returncode, r.stdout + r.stderr

    def web(self):
        os.makedirs(self.web_src)
        for name in WEB_SOURCES:
            src = os.path.join(REPO, "web", name)
            dst = os.path.join(self.web_src, name)
            (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, dst)
        env = {**os.environ, "npm_config_cache": self.npm_cache, "npm_config_update_notifier": "false"}
        self.run(["npm", "ci", "--no-audit", "--no-fund"], "npm-ci.log", 600, cwd=self.web_src, env=env)
        env["VITE_FLH_PUBLIC_DEMO"] = "1"
        self.run([os.path.join(self.web_src, "node_modules", ".bin", "vite"), "build", "--outDir", self.web_out,
                  "--emptyOutDir"], "vite-build.log", 300, cwd=self.web_src, env=env)
        self.check("web.build_output", "artifact", os.path.isfile(os.path.join(self.web_out, "index.html")))

    def start_server(self):
        self.server_runs += 1
        log = os.path.join(self.run_dir, f"server-{self.server_runs}.log")
        args = ["env", "-i", *[f"{k}={v}" for k, v in self.server_env().items()],
                os.path.join(self.run_dir, "server"), "-public-demo-artifact", self.artifact,
                "-public-demo-allow-mechanical", "-web-dir", self.web_out]
        with open(log, "ab") as out:  # env execs the server, so the child PID is the server
            proc = subprocess.Popen(args, cwd=self.run_dir, stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        with open(os.path.join(self.run_dir, "server.pid"), "w") as f:
            f.write(str(proc.pid))
        self.server_proc = proc
        r = self.guard("record", "server", self.run_dir)
        if r.returncode != 0:
            raise Abort(f"server did not start: {r.stderr.strip()}")
        self.write_state(f"server-{self.server_runs}", server_pid=proc.pid, port=self.port)
        r = self.guard("wait-listener", "server", self.run_dir, str(self.port), "30", timeout=45)
        self.check(f"process.server_{self.server_runs}_listens_loopback_only", "process", r.returncode == 0,
                   (r.stdout or r.stderr).strip())
        if r.returncode != 0:
            raise Abort("server is not listening")
        status = None
        for _ in range(100):
            try:
                status = self.http("GET", "/readyz", timeout=2)[0]
                if status == 200:
                    break
            except OSError:
                pass
            time.sleep(0.1)
        self.check(f"process.server_{self.server_runs}_ready", "http", status == 200, f"/readyz -> {status}")

    def stop_server(self):
        """Signal only the verified, recorded server; then require it gone and the port free."""
        if not os.path.exists(os.path.join(self.run_dir, "server.pid")):
            return True
        r = self.guard("stop", self.run_dir)
        proc = getattr(self, "server_proc", None)
        if proc is not None:
            try:
                proc.wait(timeout=5)  # reap our own child
            except subprocess.TimeoutExpired:
                pass
        left = self.guard("scan", self.run_dir).stdout.strip()
        ok = r.returncode == 0 and not left and not port_in_use(self.port)
        self.cleanup.setdefault("server_stops", []).append(
            {"ok": ok, "guard": (r.stdout + r.stderr).strip()[:300], "remaining": left})
        return ok

    def http_checks(self):
        self.start_server()
        if self.args.probe == "assertion-failure":
            # Controlled failure probe: a deliberately wrong expectation (the boundary
            # correctly refuses /demo.db). Proves a failed assertion exits nonzero and cleans up.
            self.expect("probe.deliberate_wrong_expectation", "GET", "/demo.db", 200)
            raise Abort("controlled failure probe: deliberate assertion failure")
        if self.args.probe == "interrupt-hold":
            self.write_state("probe-hold", server_pid=self.server_proc.pid, port=self.port)
            print("probe: holding with the server running until signalled", flush=True)
            time.sleep(120)
            raise Abort("interrupt-hold probe was not interrupted within 120s")
        self.static_checks()
        self.routing_checks()
        self.search_checks()
        self.concept_checks()
        self.denied_checks()
        self.snapshot_1 = self.snapshot()

    def static_checks(self):
        status, headers, body = self.http("GET", "/")
        html = body.decode("utf-8", "replace")
        self.check("static.index_html", "http", status == 200 and headers.get("content-type", "").startswith("text/html")
                   and '<div id="root">' in html, f"{status} {headers.get('content-type')}")
        refs = asset_refs(html)
        self.check("static.index_references_assets", "http", any(r.endswith(".js") for r in refs) and
                   any(r.endswith(".css") for r in refs), refs)
        bundle = b""
        for ref in refs:
            status, headers, data = self.http("GET", ref)
            ctype = headers.get("content-type", "")
            want = "javascript" if ref.endswith(".js") else "text/css" if ref.endswith(".css") else ""
            self.check(f"static.asset {ref}", "http", status == 200 and len(data) > 0 and want in ctype,
                       f"{status} {ctype} {len(data)} bytes")
            if ref.endswith(".js"):
                bundle += data
            head = self.http("HEAD", ref)
            self.check(f"static.asset_head {ref}", "http", head[0] == 200 and head[2] == b"", head[0])
        self.check("static.bundle_is_public_demo_build", "http", b"read-only public demo" in bundle)
        self.expect("static.missing_asset_404_no_spa_fallback", "GET", "/assets/does-not-exist.js", 404)
        self.expect("static.unknown_page_404_no_spa_fallback", "GET", "/some/page", 404)

    def routing_checks(self):
        for prefix in PREFIXES:
            for p in ("/healthz", "/readyz", "/knowledge-library/demo"):
                self.expect(f"routing.get {prefix or '/'} {p}", "GET", prefix + p, 200)
            self.expect(f"routing.head {prefix or '/'} demo", "HEAD", prefix + "/knowledge-library/demo", 200)
        info = self.get_json("/knowledge-library/demo")
        self.demo_info = info
        a = info.get("artifact", {})
        self.check("routing.demo_info_read_only_synthetic_mechanical", "http",
                   info.get("read_only") is True and info.get("data") == "synthetic" and a.get("real_model") is False
                   and a.get("vector_source") == "mechanical-test" and a.get("release_status") == "blocked_mechanical_vectors",
                   json.dumps(a)[:300])
        self.check("routing.demo_info_counters_start_at_zero", "http",
                   info.get("counters") == {"preset_vector_lookups": 0, "refused_vector_lookups": 0}, info.get("counters"))
        want = [p["id"] for p in self.fixtures["presets"]]
        self.check("routing.demo_info_lists_fixture_presets", "http", [p["id"] for p in info.get("presets", [])] == want)
        for p in ("/knowledge-library/concepts", "/knowledge-library/concepts?q=subj", "/knowledge-library/concepts/1",
                  "/knowledge-library/units/1/source", "/knowledge-library/demo/semantic-search?preset=miss-someone",
                  "/knowledge-library/demo/hybrid-search?preset=subjunctive"):
            root, api = self.http("GET", p), self.http("GET", "/api" + p)
            self.check(f"routing.root_equals_api {p}", "http", root[0] == api[0] == 200 and root[2] == api[2],
                       f"{root[0]} vs {api[0]}")
        self.expect("routing.api_prefix_alone_404", "GET", "/api", 404)

    def search_checks(self):
        r = self.get_json("/knowledge-library/concepts?q=subj")
        targets = [x["concept"]["target"] for x in r.get("results", [])]
        self.check("keyword.subj_matches", "http", r.get("schema_version") == "knowledge_library_search_v1" and
                   r.get("total_matches", 0) >= 2 and any("subjunctive" in t for t in targets) and
                   all(x.get("match_tier") for x in r["results"]), targets)
        r = self.get_json("/knowledge-library/concepts?q=zzzzzz")
        self.check("keyword.no_match_is_empty", "http", r.get("total_matches") == 0 and r.get("results") == [])
        self.expect("keyword.over_long_query_400", "GET", "/knowledge-library/concepts?q=" + "a" * 201, 400)
        presets = {p["id"]: p["text"] for p in self.demo_info["presets"]}
        calls = 0
        for pid, text in presets.items():
            r = self.get_json(f"/knowledge-library/demo/semantic-search?preset={pid}")
            calls += 1
            scores = [x.get("score") for x in r.get("results", [])]
            self.check(f"semantic.preset {pid}", "http", r.get("schema_version") == "knowledge_library_semantic_search_v2"
                       and r.get("query") == text and len(scores) > 0 and r.get("skipped", {}).get("stale") == 0,
                       f"{len(scores)} results")
        r = self.get_json("/knowledge-library/demo/hybrid-search?preset=subjunctive&state=active")
        calls += 1
        self.check("hybrid.preset_subjunctive_active", "http",
                   r.get("schema_version") == "knowledge_library_hybrid_search_v1" and r.get("query") == "subjunctive"
                   and r.get("policy", {}).get("version") == "concept_hybrid_rrf_v1" and len(r.get("results", [])) > 0
                   and all(x["concept"]["state"] == "active" for x in r["results"]), f"{len(r.get('results', []))} results")
        r = self.get_json("/knowledge-library/demo/hybrid-search?preset=miss-someone")
        calls += 1
        comps = r.get("components", {})
        self.check("hybrid.preset_has_keyword_and_semantic_components", "http",
                   "keyword" in comps and "semantic" in comps and len(r.get("results", [])) > 0)
        self.expect("semantic.unknown_preset_404", "GET", "/knowledge-library/demo/semantic-search?preset=unknown", 404)
        self.expect("hybrid.unknown_preset_404", "GET", "/knowledge-library/demo/hybrid-search?preset=unknown", 404)
        info = self.get_json("/knowledge-library/demo")
        # The root==/api comparison above made 2 semantic + 2 hybrid preset calls.
        want = {"preset_vector_lookups": calls + 4, "refused_vector_lookups": 0}
        self.check("semantic.preset_vector_counters", "http", info.get("counters") == want,
                   f"{info.get('counters')} (want {want})")

    def concept_checks(self):
        by_statement = {}
        for e in self.fixtures["entries"]:
            for u in e["units"]:
                by_statement[u["statement"]] = e
        fixture_concepts = {c["target"]: c for c in self.fixtures["concepts"]}
        units = {u["key"]: u for e in self.fixtures["entries"] for u in e["units"]}
        browse = self.get_json("/knowledge-library/concepts")
        ids = sorted(x["concept"]["id"] for x in browse.get("results", []))
        self.check("concept.browse_lists_every_fixture_concept", "http",
                   len(ids) == len(fixture_concepts) and not browse.get("truncated"), f"{len(ids)} concepts")
        sources = 0
        for cid in ids:
            d = self.get_json(f"/knowledge-library/concepts/{cid}")
            c = d.get("concept", {})
            fx = fixture_concepts.get(c.get("target"))
            if not self.check(f"concept.{cid}.detail_matches_fixture", "http",
                              d.get("schema_version") == "knowledge_library_concept_v1" and fx is not None
                              and c.get("pedagogical_intent") == fx["pedagogical_intent"]
                              and c.get("scope") == fx["scope"] and c.get("identity_features") == fx["identity_features"],
                              c.get("target")):
                continue
            want_statements = sorted(units[k]["statement"] for k in fx["members"])
            got = sorted(u["statement"] for u in d.get("supporting_units", []))
            want_support = "supported" if fx["members"] else "orphaned"
            self.check(f"concept.{cid}.support_matches_fixture_members", "http",
                       got == want_statements and c.get("support_state") == want_support,
                       f"{c.get('support_state')} {len(got)} units")
            for u in d.get("supporting_units", []):
                s = self.get_json(f"/knowledge-library/units/{u['unit_id']}/source")
                sources += 1
                entry = by_statement.get(u["statement"], {})
                interp = (s.get("source_interpretation") or {}).get("analysis") or {}
                self.check(f"concept.{cid}.unit_{u['unit_id']}.original_question_provenance", "http",
                           s.get("schema_version") == "knowledge_library_source_v1"
                           and s.get("entry", {}).get("original_input") == entry.get("original_input")
                           and s.get("entry", {}).get("original_context") == entry.get("original_context")
                           and s.get("entry", {}).get("id") == u.get("entry_id")
                           and s.get("extraction", {}).get("extractor") == FIXTURE_EXTRACTOR
                           and interp.get("analyzer") == FIXTURE_ANALYZER
                           and s.get("annotation", {}).get("current_concept_id") == cid,
                           s.get("entry", {}).get("original_input"))
        self.check("concept.every_fixture_unit_source_checked", "http", sources == len(units), f"{sources}/{len(units)}")
        self.expect("concept.unknown_concept_404", "GET", "/knowledge-library/concepts/9999", 404)
        self.expect("concept.unknown_unit_404", "GET", "/knowledge-library/units/9999/source", 404)
        self.concept_ids = ids

    def denied_checks(self):
        before = self.get_json("/knowledge-library/demo")["counters"]
        for prefix in PREFIXES:
            for m in WRITE_METHODS:
                for p in WRITE_PATHS:
                    self.expect(f"denied.write {m} {prefix}{p}", m, prefix + p, 405)
            for p in PRIVATE_API_PATHS + ("/unknown",):
                self.expect(f"denied.private_api {prefix}{p}", "GET", prefix + p, 404)
            for p in FREE_TEXT_PATHS:
                self.expect(f"denied.free_text_route {prefix}{p}", "GET", prefix + p, 404)
            self.expect(f"denied.free_text_semantic {prefix}", "GET",
                        prefix + "/knowledge-library/demo/semantic-search?q=free+text", 400)
            self.expect(f"denied.free_text_with_preset {prefix}", "GET",
                        prefix + "/knowledge-library/demo/hybrid-search?preset=miss-someone&q=free+text", 400)
        for p in PRIVATE_FILE_PATHS:
            try:
                status, _, body = self.http("GET", p)
            except OSError as e:
                status, body = f"error {e}", b""
            self.check(f"denied.private_file {p}", "http", status in (400, 404) and b"SQLite format 3" not in body
                       and b'"vector_generator"' not in body and b'"vectors"' not in body, status)
        after = self.get_json("/knowledge-library/demo")["counters"]
        self.check("denied.no_vector_lookup_from_denied_requests", "http", before == after, f"{before} -> {after}")

    def snapshot(self):
        paths = ["/knowledge-library/concepts", "/knowledge-library/concepts?q=subj",
                 "/knowledge-library/demo/semantic-search?preset=miss-someone",
                 "/knowledge-library/demo/hybrid-search?preset=subjunctive"]
        paths += [f"/knowledge-library/concepts/{i}" for i in self.concept_ids]
        units = sorted({u["unit_id"] for i in self.concept_ids
                        for u in self.get_json(f"/knowledge-library/concepts/{i}").get("supporting_units", [])})
        paths += [f"/knowledge-library/units/{u}/source" for u in units]
        snap = {p: self.http("GET", p)[2] for p in paths}
        info = self.get_json("/knowledge-library/demo")
        info.pop("counters", None)
        snap["demo-info-without-counters"] = json.dumps(info, sort_keys=True).encode()
        return snap

    def restart(self):
        self.check("restart.server_1_stopped_port_free", "process", self.stop_server())
        self.check("restart.artifact_bytes_unchanged_after_run_1", "artifact", tree_hashes(self.artifact) == self.hashes)
        self.start_server()
        info = self.get_json("/knowledge-library/demo")
        self.check("restart.counters_reset_nothing_persisted", "http",
                   info.get("counters") == {"preset_vector_lookups": 0, "refused_vector_lookups": 0}, info.get("counters"))
        snap = self.snapshot()
        diff = sorted(p for p in set(snap) | set(self.snapshot_1) if snap.get(p) != self.snapshot_1.get(p))
        self.check("restart.responses_identical_after_restart", "http", not diff and len(snap) > 10,
                   f"{len(snap)} responses compared; differing: {diff[:5]}")

    def browser(self):
        chrome = find_chrome(self.args.chrome)
        self.environment["chrome"] = chrome
        if chrome is None:
            why = "no Chrome/Chromium found (--chrome, $CHROME, " + ", ".join(CHROME_CANDIDATES) + ")"
            return ("BLOCKED" if self.args.require_browser else "NOT RUN"), why
        self.environment["chrome_version"] = self.tool_version([chrome, "--version"])
        os.makedirs(self.tools)
        env = {**os.environ, "npm_config_cache": self.npm_cache, "npm_config_update_notifier": "false",
               "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1"}
        self.run(["npm", "init", "-y"], "browser-tools.log", 60, cwd=self.tools, env=env)
        self.run(["npm", "install", "--no-audit", "--no-fund", "--ignore-scripts", PLAYWRIGHT_CORE],
                 "browser-tools.log", 300, cwd=self.tools, env=env)
        out = os.path.join(self.diag, "browser")
        env["PLAYWRIGHT_CORE_DIR"] = os.path.join(self.tools, "node_modules", "playwright-core")
        rc = self.run(["node", ACCEPT_MJS, "--url", f"http://127.0.0.1:{self.port}", "--out", out,
                       "--chrome", chrome, "--expect-vectors", "mechanical"], "browser-accept.log", 300,
                      cwd=self.tools, env=env, check=False)
        try:
            results = json.load(open(os.path.join(out, "results.json"), encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise Abort(f"accept.mjs exit {rc} wrote no results.json ({e})")
        for c in results.get("checks", []):
            self.check("dom." + c["name"], "dom", c["status"] == "PASS", c.get("detail", ""))
        self.check("dom.accept_mjs_exit_0", "dom", rc == 0, f"exit {rc}")
        # The browser only reads; it must not have changed the served artifact.
        self.check("dom.artifact_bytes_unchanged", "artifact", tree_hashes(self.artifact) == self.hashes)

    def final(self):
        self.check("final.server_stopped_port_free", "process", self.stop_server())
        self.check("final.artifact_bytes_unchanged", "artifact", tree_hashes(self.artifact) == self.hashes)
        self.check("final.no_sqlite_side_files", "artifact",
                   not any(os.path.exists(os.path.join(self.artifact, "demo.db" + s)) for s in ("-wal", "-shm", "-journal")))
        rc = self.run([os.path.join(self.bin_dir, "prepare"), "validate", "-artifact", self.artifact],
                      "prepare-validate-after.log", 60, check=False)
        self.check("final.artifact_still_validates", "artifact", rc == 0, f"exit {rc}")

    # ---- driver ----------------------------------------------------------
    def execute(self):
        pipeline = [("preflight", self.preflight), ("build", self.build), ("artifact", self.artifact_stage),
                    ("web", self.web), ("serve-http", self.http_checks), ("restart", self.restart),
                    ("browser", self.browser), ("final", self.final)]
        done = 0
        try:
            for name, fn in pipeline:
                done += 1
                if self.stage(name, fn) in ("FAIL", "BLOCKED") and name != "browser":
                    break
        except Interrupted as e:
            self.interrupted = e.signum
        for name, _ in pipeline[done:]:
            self.stages.append({"name": name, "status": "NOT RUN", "detail": "an earlier stage stopped the run",
                                "duration_s": 0})

    def finish(self):
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):  # cleanup must complete
            signal.signal(s, signal.SIG_IGN)
        self.write_state("cleanup")
        ok = self.stop_server()
        self.cleanup["server_stopped_and_port_free"] = ok and not port_in_use(self.port)
        if not self.cleanup["server_stopped_and_port_free"]:
            self.checks.append({"id": "cleanup.server_stopped", "evidence": "process", "status": "FAIL",
                                "detail": json.dumps(self.cleanup.get("server_stops", []))[:400]})
        if os.path.isdir(self.artifact):
            for dirpath, dirs, files in os.walk(self.artifact):
                os.chmod(dirpath, os.stat(dirpath).st_mode | stat.S_IWUSR)
        logs = os.path.join(self.diag, "logs")
        os.makedirs(logs, exist_ok=True)
        for d in (self.logs, self.run_dir):
            if os.path.isdir(d):
                for n in sorted(os.listdir(d)):
                    if n.endswith(".log"):
                        tail_copy(os.path.join(d, n), os.path.join(logs, n))
        removed = []
        if not self.args.keep_work:
            for n in sorted(os.listdir(self.work)):
                if n != "diagnostics":
                    shutil.rmtree(os.path.join(self.work, n), ignore_errors=True)
                    removed.append(n)
        self.cleanup["removed"] = removed
        status = overall_status(self.stages, self.checks)
        if self.interrupted:
            status = "FAIL"
        code = 128 + self.interrupted if self.interrupted else exit_code_for(status)
        summary = {
            "schema": SCHEMA, "overall": status, "exit_code": code, "interrupted_by_signal": self.interrupted,
            "probe": self.args.probe, "finished_at": now(), "duration_s": round(time.monotonic() - self.started, 1),
            "port": self.port, "environment": self.environment,
            "note": "Synthetic fixtures and mechanical vectors: these checks prove routing, preset and ranking "
                    "mechanics only, not retrieval quality. HTTP evidence (urllib against the server) and DOM "
                    "evidence (accept.mjs in a real browser) are recorded separately.",
            "counts": {k: sum(c["status"] == k for c in self.checks) for k in ("PASS", "FAIL")},
            "counts_by_evidence": {e: sum(c["evidence"] == e for c in self.checks)
                                   for e in sorted({c["evidence"] for c in self.checks})},
            "not_run": [s["name"] for s in self.stages if s["status"] == "NOT RUN"],
            "stages": self.stages, "cleanup": self.cleanup,
            "failed_checks": [c for c in self.checks if c["status"] == "FAIL"], "checks": self.checks,
        }
        tmp = os.path.join(self.diag, "summary.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, os.path.join(self.diag, "summary.json"))
        os.remove(os.path.join(self.diag, "state.json"))
        not_run = f"; NOT RUN: {', '.join(summary['not_run'])}" if summary["not_run"] else ""
        bad = [f"{s['name']} {s['status']}" for s in self.stages if s["status"] in ("FAIL", "BLOCKED")]
        bad = f"; stages: {', '.join(bad)}" if bad else ""
        if self.interrupted:
            bad += f"; INTERRUPTED by signal {self.interrupted}"
        print(f"OVERALL {status}: {summary['counts']['PASS']} checks passed, {summary['counts']['FAIL']} failed"
              f"{bad}{not_run}; summary {os.path.join(self.diag, 'summary.json')}", flush=True)
        return code


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--work", required=True, help="new absolute directory outside the repository")
    p.add_argument("--port", type=int, default=18990)
    p.add_argument("--require-browser", action="store_true", help="BLOCKED (exit 3) instead of NOT RUN without a browser")
    p.add_argument("--chrome", help="Chrome/Chromium executable (default: $CHROME, then PATH)")
    p.add_argument("--npm-cache", help="npm cache directory (default: task-local WORK/npm-cache)")
    p.add_argument("--keep-work", action="store_true", help="keep binaries, artifact and node_modules for inspection")
    p.add_argument("--probe", choices=("assertion-failure", "interrupt-hold"), help=argparse.SUPPRESS)
    return p.parse_args(argv)


def refuse_work(work):
    """Reason the work directory is unacceptable, or None."""
    if not os.path.isabs(work):
        return "--work must be an absolute path"
    real = os.path.realpath(work)
    if real == REPO or real.startswith(REPO + os.sep):
        return "--work must be outside the repository"
    if os.path.lexists(work):
        return f"{work} already exists"
    return None


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    why = refuse_work(args.work)
    if why is None and not 1024 <= args.port <= 65535:
        why = "--port must be between 1024 and 65535"
    if why:
        print(f"refused: {why}", file=sys.stderr)
        return 2
    os.makedirs(args.work)
    h = Harness(args)

    def on_signal(signum, _frame):
        raise Interrupted(signum)

    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, on_signal)
    try:
        h.execute()
    except Interrupted as e:
        h.interrupted = e.signum
    return h.finish()


if __name__ == "__main__":
    sys.exit(main())
