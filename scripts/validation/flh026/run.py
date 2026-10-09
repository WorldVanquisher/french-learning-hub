#!/usr/bin/env python3
"""FLH-026 isolated workflow regression. See adjacent README.md."""
import argparse
import concurrent.futures
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid

from fake_provider import Provider

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SUFFIXES = {".go", ".sql", ".ts", ".tsx", ".css", ".html", ".json", ".svg"}
PROVIDER_IMAGE = "python:3.12-slim"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def clean_env(home):
    # Intentionally do not copy os.environ, PATH, proxy, provider or Docker context settings.
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(home),
            "LANG": "C.UTF-8", "DOCKER_CONFIG": str(home / "docker"),
            "DOCKER_HOST": "unix:///var/run/docker.sock", "GOENV": "off",
            "GOTOOLCHAIN": "local", "GOFLAGS": "-mod=readonly -buildvcs=false",
            "GOPROXY": "off", "GOSUMDB": "off", "CGO_ENABLED": "0",
            "AI_PROVIDER": "openai", "EXTRACTOR_PROVIDER": "openai",
            "EMBEDDING_PROVIDER": "disabled", "OPENAI_API_KEY": "flh026-fake-only",
            "OPENAI_MODEL": "flh026-local", "OPENAI_TIMEOUT": "25",
            "HTTP_READ_TIMEOUT": "30", "HTTP_WRITE_TIMEOUT": "30",
            "HTTP_ALLOWED_HOSTS": "nas.flh026.test,192.0.2.26",
            "HTTP_TRUSTED_ORIGINS": "", "EMBEDDING_API_KEY": "",
            "EMBEDDING_BASE_URL": "", "EMBEDDING_MODEL": "", "EMBEDDING_TIMEOUT": ""}


def docker_names():
    project = "flh026-" + uuid.uuid4().hex
    return project, project + ":local"


def native_compiler(env, selected=None):
    # Resolve only the isolated PATH unless explicitly selected; never inherit caller PATH.
    candidate = str(selected) if selected is not None else shutil.which("go", path=env["PATH"])
    require(candidate is not None, "native Go compiler not found")
    path = Path(candidate)
    require(path.is_absolute() and path.is_file() and os.access(path, os.X_OK),
            "native Go compiler must be an absolute executable file")
    return str(path.resolve())


def reserve_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    return sock, sock.getsockname()[1]


def owns_listener(pid, port):
    """Do not issue HTTP to a native port until its listener belongs to our child."""
    try:
        links = set()
        for path in Path(f"/proc/{pid}/fd").iterdir():
            try:
                links.add(os.readlink(path))
            except FileNotFoundError:
                pass  # An unrelated accepted HTTP connection may close during inspection.
        for table in ("/proc/net/tcp", "/proc/net/tcp6"):
            for row in Path(table).read_text().splitlines()[1:]:
                fields = row.split()
                if (int(fields[1].split(":")[1], 16) == port and fields[3] == "0A"
                        and f"socket:[{fields[9]}]" in links):
                    return True
    except (FileNotFoundError, ProcessLookupError):
        pass
    return False


def snapshot(db):
    # Read only OUR database, using a single SQLite snapshot, including every table.
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        conn.execute("BEGIN")
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: sorted(conn.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(),
                             key=repr) for name in names}


def integrity(db):
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        require(conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
                "SQLite integrity_check must return exactly one ok row")


def backup(active, destination):
    destination.mkdir(mode=0o700)
    require((active / "app.db").is_file(), "missing source database")
    checksums = {}
    for name in ("app.db", "app.db-wal", "app.db-shm"):
        if (active / name).exists():
            shutil.copy2(active / name, destination / name)
    integrity(destination / "app.db")
    # Opening a WAL database even read-only can update its SHM index. As in RELEASE.md,
    # hash AFTER integrity checking, with no connection left open.
    checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.iterdir())}
    (destination / "SHA256SUMS").write_text("".join(f"{v}  {k}\n" for k, v in checksums.items()))


def restore(active, source):
    require((source / "app.db").is_file(), "missing backup database")
    lines = (source / "SHA256SUMS").read_text().splitlines()
    checksums = {}
    for line in lines:
        digest, name = line.split("  ")
        require(name in {"app.db", "app.db-wal", "app.db-shm"} and name not in checksums,
                "unexpected checksum target")
        checksums[name] = digest
    require(set(checksums) == {p.name for p in source.iterdir() if p.name != "SHA256SUMS"},
            "backup manifest does not cover every file")
    require("app.db" in checksums, "manifest must include database")
    for name, digest in checksums.items():
        require(hashlib.sha256((source / name).read_bytes()).hexdigest() == digest,
                "backup checksum mismatch")
    stage = active.with_name(active.name + "-stage")
    old = active.with_name(active.name + "-preserved")
    require(not stage.exists() and not old.exists(), "ambiguous restoration destination")
    stage.mkdir(mode=0o700)
    try:
        for name in checksums:
            shutil.copy2(source / name, stage / name)
        integrity(stage / "app.db")
        active.rename(old)
        try:
            stage.rename(active)
        except BaseException:
            old.rename(active)
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return old


class Harness:
    def __init__(self, mode, go_binary=None):
        self.mode = mode
        self.go_binary = go_binary
        self.run_dir = Path(tempfile.mkdtemp(prefix="flh026-"))
        self.source = self.run_dir / "source"
        self.active = self.run_dir / "custom-private-data"
        self.home = self.run_dir / "home"
        for path in (self.source, self.active, self.home, self.home / "docker"):
            path.mkdir(mode=0o700)
        self.env = clean_env(self.home)
        self.env.update(FLH_DATA_DIR=str(self.active), FLH_UID=str(os.getuid()),
                        FLH_GID=str(os.getgid()), GOCACHE=str(self.run_dir / "gocache"))
        self.project, self.image = docker_names()
        try:
            self.port_socket, self.port = reserve_port()
        except BaseException:
            shutil.rmtree(self.run_dir)
            raise
        self.env["FLH_HOST_PORT"] = str(self.port)
        self.process = None
        self.provider = None
        self.provider_thread = None
        self.compose_started = False
        self.image_attempted = False
        self.results = []
        self.commands = []
        self.harness_manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted(HERE.glob("*.py"))}
        self.log = (self.run_dir / "service.log").open("w")

    def command(self, args, check=True, cwd=None, env=None):
        process = subprocess.Popen(args, cwd=cwd or self.source, env=env or self.env,
                                   text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            output, _ = process.communicate(timeout=600)
        except BaseException:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            raise
        result = subprocess.CompletedProcess(args, process.returncode, output)
        self.commands.append({"argv": args, "exit": result.returncode, "output": result.stdout})
        require(not check or result.returncode == 0,
                f"command failed: {args!r}\n{result.stdout[-6000:]}")
        return result

    def prepare(self):
        for directory in ("cmd", "internal", "migrations") + (("web",) if self.mode == "container" else ()):
            # Traverse only named source trees. Never open .env or data directories.
            for base, dirs, files in os.walk(ROOT / directory, followlinks=False):
                dirs[:] = [d for d in dirs if d not in {"node_modules", "dist", "data", ".git"}
                           and not d.startswith(".") and not (Path(base) / d).is_symlink()]
                for name in files:
                    path = Path(base) / name
                    if (not path.is_symlink() and not name.startswith(".")
                            and path.suffix in SUFFIXES):
                        target = self.source / path.relative_to(ROOT)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, target)
        for name in ("go.mod", "go.sum") + (("Dockerfile", ".dockerignore", "compose.yaml")
                                               if self.mode == "container" else ()):
            shutil.copy2(ROOT / name, self.source / name)
        self.manifest = {str(p.relative_to(self.source)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(self.source.rglob("*")) if p.is_file()}
        if self.mode == "native":
            # A known cache location is queried with only HOME/PATH, without shell startup.
            compiler = native_compiler(self.env, self.go_binary)
            self.compiler = {"path": compiler, "sha256": hashlib.sha256(Path(compiler).read_bytes()).hexdigest()}
            cache_env = {"HOME": str(Path.home()), "PATH": self.env["PATH"],
                         "GOTOOLCHAIN": "local", "GOENV": "off"}
            self.env["GOMODCACHE"] = self.command([compiler, "env", "GOMODCACHE"], env=cache_env).stdout.strip()
            self.compiler["version"] = self.command([compiler, "version"]).stdout.strip()
            self.command([compiler, "mod", "verify"])
            self.command([compiler, "build", "-o", str(self.run_dir / "server"), "./cmd/server"])
            self.compiler["binary_metadata"] = self.command([compiler, "version", "-m", str(self.run_dir / "server")]).stdout
            self.compiler["binary_sha256"] = hashlib.sha256((self.run_dir / "server").read_bytes()).hexdigest()
            web = self.run_dir / "test-web"
            web.mkdir()
            (web / "index.html").write_text("<!doctype html><title>FLH026 transport fixture</title>")
            self.provider = Provider(("127.0.0.1", 0))
            self.fake_port = self.provider.server_address[1]
            self.provider_thread = threading.Thread(target=self.provider.serve_forever, daemon=True)
            self.provider_thread.start()
            self.env.update(PORT=str(self.port), DB_PATH=str(self.active / "app.db"),
                            OPENAI_BASE_URL=f"http://127.0.0.1:{self.fake_port}/v1")
        else:
            self.command(["docker", "version", "--format", "{{.Server.Version}}"])
            self.command(["docker", "compose", "version"])
            # Installed local fixture image only: never pull it implicitly.
            self.command(["docker", "image", "inspect", PROVIDER_IMAGE, "--format", "{{.Id}}"])
            fake_socket, self.fake_port = reserve_port()
            fake_socket.close()
            shutil.copy2(HERE / "fake_provider.py", self.source / "fake_provider.py")
            override = {"services": {
                "app": {"image": self.image, "depends_on": ["fake"],
                        "environment": {"OPENAI_BASE_URL": "http://fake:8081/v1"}},
                "fake": {"image": PROVIDER_IMAGE, "pull_policy": "never",
                         "command": ["python", "/fixture/fake_provider.py", "--container"],
                         "ports": [f"127.0.0.1:{self.fake_port}:8081"],
                         "volumes": [{"type": "bind", "source": str(self.source / "fake_provider.py"),
                                      "target": "/fixture/fake_provider.py", "read_only": True}],
                         "environment": {"PYTHONDONTWRITEBYTECODE": "1"}, "restart": "no"}}}
            (self.source / "harness.compose.json").write_text(json.dumps(override))
            self.image_attempted = True
            self.compose(["build", "app"])

    def compose(self, args, check=True):
        require(self.mode == "container" and self.project.startswith("flh026-"), "ambiguous Compose target")
        return self.command(["docker", "compose", "--env-file", "/dev/null", "-p", self.project,
                             "-f", "compose.yaml", "-f", "harness.compose.json", *args], check=check)

    def start(self, build=False):
        if self.port_socket:
            self.port_socket.close()
            self.port_socket = None
        if self.mode == "native":
            require(self.process is None, "native service already owned")
            self.process = subprocess.Popen([str(self.run_dir / "server"), "-web-dir",
                                             str(self.run_dir / "test-web")], cwd=self.run_dir,
                                            env=self.env, stdout=self.log, stderr=self.log,
                                            start_new_session=True)
        else:
            self.compose_started = True
            self.compose(["up", "-d", *( ["--build"] if build else [] )])
            cid = self.compose(["ps", "-q", "app"]).stdout.strip()
            require(bool(cid) and "\n" not in cid, "ambiguous app container")
            info = json.loads(self.command(["docker", "inspect", cid]).stdout)[0]
            require(info["Config"]["Labels"]["com.docker.compose.project"] == self.project,
                    "wrong container project")
            require(any(m["Source"] == str(self.active) and m["Destination"] == "/data"
                        for m in info["Mounts"]), "wrong persistent data mount")
            require(info["NetworkSettings"]["Ports"]["8080/tcp"] == [
                {"HostIp": "127.0.0.1", "HostPort": str(self.port)}], "wrong published port")
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if self.mode == "native":
                require(self.process.poll() is None, "owned server exited before readiness")
                if not owns_listener(self.process.pid, self.port):
                    time.sleep(0.05)
                    continue
            try:
                self.request("GET", "/readyz")
                self.control("GET", "/control/state")
                return
            except (OSError, AssertionError):
                time.sleep(0.05)
        raise AssertionError("owned service/provider did not become ready")

    def stop(self):
        if self.mode == "native" and self.process:
            process, self.process = self.process, None
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            require(process.returncode == 0, f"server did not stop cleanly: {process.returncode}")
        elif self.mode == "container" and self.compose_started:
            self.compose(["stop", "app"])

    def replace(self, build=False):
        self.stop()
        if self.mode == "container":
            self.compose(["rm", "-f", "app"])
        self.start(build=build)

    @staticmethod
    def http(port, method, path, body=None, expected=200, headers=None, raw=False):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=35)
        data = json.dumps(body).encode() if body is not None else None
        values = {"Content-Type": "application/json"} if data is not None else {}
        values.update(headers or {})
        try:
            conn.request(method, path, body=data, headers=values)
            response = conn.getresponse()
            payload = response.read()
            require(response.status == expected,
                    f"{method} {path}: expected {expected}, got {response.status}: {payload[:1000]!r}")
            return payload.decode() if raw else json.loads(payload)
        finally:
            conn.close()

    def request(self, method, path, *args, **kwargs):
        if self.mode == "native":
            require(self.process is not None and self.process.poll() is None
                    and owns_listener(self.process.pid, self.port), "refuse unowned HTTP target")
        return self.http(self.port, method, path, *args, **kwargs)

    def control(self, method, path):
        return self.http(self.fake_port, method, path)

    def calls(self):
        return self.control("GET", "/control/state")["calls"]

    def passed(self, name):
        self.results.append({"case": name, "result": "PASS"})
        print("PASS " + name, flush=True)

    def workflow(self):
        api = self.request
        db = self.active / "app.db"
        capture = {"schema_version": "learning_capture_v1", "capture_id": "flh026-main",
                   "source": "manual", "original_input": "Je ne parle pas.",
                   "original_context": "Fixture de négation", "discussion_summary": "Local fixture"}
        receipt = api("POST", "/api/captures", capture, expected=201)
        entry = receipt["entry_id"]
        require(receipt["created"] and receipt["analysis_id"] is None, "capture receipt")
        require(api("GET", "/captures/flh026-main")["entry_id"] == entry, "capture receipt lookup")
        before, calls = snapshot(db), self.calls()
        replay = api("POST", "/captures", capture)
        require(not replay["created"] and replay["entry_id"] == entry, "idempotent capture replay")
        api("POST", "/captures", capture | {"original_input": "Conflicting content"}, expected=409)
        require(snapshot(db) == before and self.calls() == calls, "capture replay/conflict changed data")
        self.passed("capture create/replay/conflict; no provider calls")

        path = f"/entries/{entry}"
        selection = path + "/current-extraction"
        require(api("GET", selection) == {"entry_id": entry, "current_extraction_id": None,
                                           "selection_mode": "automatic"}, "empty automatic selection")
        api("DELETE", selection)
        api("DELETE", "/entries/999999/current-extraction", expected=404)
        before, calls = snapshot(db), self.calls()
        api("POST", path + "/extractions", expected=409)
        require(snapshot(db) == before and self.calls() == calls, "unanalyzed entry invoked extractor")
        analysis = api("POST", path + "/analysis", expected=201)
        aid = analysis["id"]
        require(self.calls() == calls | {"analysis": calls["analysis"] + 1}, "analysis call counter")

        def feedback(status):
            body = {"status": status, "user_note": "FLH026 human fixture"}
            if status == "corrected":
                body.update(corrected_category="grammar", corrected_explanation="Correction humaine de la négation.")
            item = api("POST", f"/analyses/{aid}/feedback", body, expected=201)
            effective = api("GET", f"/analyses/{aid}/effective")
            require(effective["resolution"] == status and effective["feedback_id"] == item["id"],
                    "effective interpretation did not follow feedback")
            inventory = api("GET", "/learning-records")["records"]
            require(next(r for r in inventory if r["entry_id"] == entry)["state"] == status,
                    "learning inventory did not follow feedback")
            if status == "corrected":
                require(effective["effective"]["explanation"] == body["corrected_explanation"],
                        "corrected interpretation lost")
            return item

        def extract():
            counts = self.calls()
            item = api("POST", path + "/extractions", expected=201)
            require(self.calls() == counts | {"extraction": counts["extraction"] + 1}, "extraction call count")
            require(len(item["units"]) == 1 and item["source_analysis_id"] == aid, "valid extraction evidence")
            require(item["units"][0]["admission"]["effective_state"] == "active", "fixture unit must be active")
            return item

        accepted = feedback("accepted")
        old = extract()
        require(old["source_feedback_id"] == accepted["id"], "accepted source provenance")
        corrected = feedback("corrected")
        newer = extract()
        require(newer["source_feedback_id"] == corrected["id"], "corrected source provenance")
        feedback("rejected")
        before, counts = snapshot(db), self.calls()
        api("POST", path + "/extractions", expected=409)
        require(snapshot(db) == before and self.calls() == counts, "rejected interpretation wrote/called provider")
        feedback("accepted")
        self.passed("accepted/corrected/rejected eligibility and exact provenance")

        # Synchronization uses an observable provider gate, never timing-dependent sleeps.
        for change in ("feedback", "analysis"):
            self.control("POST", "/control/block")
            counts = self.calls()
            before = snapshot(db)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(api, "POST", path + "/extractions", expected=409)
                try:
                    deadline = time.monotonic() + 5
                    while not self.control("GET", "/control/state")["waiting"]:
                        require(time.monotonic() < deadline, "provider race gate not reached")
                        time.sleep(0.02)
                    if change == "feedback":
                        feedback("corrected")
                    else:
                        aid = api("POST", path + "/analysis", expected=201)["id"]
                    expected = snapshot(db)  # Intentional source change is allowed to persist.
                finally:
                    self.control("POST", "/control/release")
                future.result(timeout=5)
            require(snapshot(db) == expected, "race partially persisted extraction/unit/admission data")
            changed = {name for name in before if before[name] != expected[name]}
            require(changed <= ({"analysis_feedback", "sqlite_sequence"} if change == "feedback"
                                else {"entry_analyses", "sqlite_sequence"}),
                    f"unexpected source-mutation tables: {changed}")
            require(self.calls()["extraction"] == counts["extraction"] + 1, "race provider not called once")
        self.passed("feedback/new-analysis races: 409 and no partial persistence")

        # Pinning makes old evidence reviewable for explicit annotation.
        api("PUT", selection, {"extraction_id": old["id"]})
        uid = old["units"][0]["id"]
        review = api("GET", "/reviewable-units")["reviewable_units"]
        candidate = next(item["candidate_identity"] for item in review if item["unit_id"] == uid)
        concept = api("POST", "/concepts", {"identity": candidate}, expected=201)["concept"]["id"]
        api("POST", f"/knowledge-units/{uid}/concept-links/same", {"concept_id": concept}, expected=201)

        def projections(status, human_same, invalid):
            inspected = api("GET", f"/knowledge-units/{uid}/effective-annotation")
            record = next(r for r in api("GET", "/annotation-dataset/v1")["records"] if r["unit"]["id"] == uid)
            require(inspected["snapshot"]["status"] == status
                    and record["effective_annotation"]["status"] == status, "Inspector/dataset authority mismatch")
            require((record["human_labels"]["same"] is not None) == human_same
                    and (record["human_labels"]["invalid"] is not None) == invalid, "human label projection mismatch")
            return record

        projections("resolved", True, False)
        require(api("GET", f"/concepts/{concept}")["concept"]["support_state"] == "supported", "SAME support")
        api("POST", f"/knowledge-units/{uid}/invalid")
        projections("invalid", False, True)
        require(api("GET", f"/concepts/{concept}")["concept"]["support_state"] == "orphaned", "INVALID support")
        api("POST", f"/knowledge-units/{uid}/invalid/restore")
        projections("unresolved", False, False)
        require(uid in {r["unit_id"] for r in api("GET", "/reviewable-units")["reviewable_units"]}, "restored unit not reviewable")
        api("POST", f"/knowledge-units/{uid}/concept-links/same", {"concept_id": concept}, expected=201)
        projections("resolved", True, False)
        judgments = api("GET", f"/knowledge-units/{uid}/invalid")["history"]
        require([j["judgment"] for j in judgments] == ["restored", "invalid"], "append-only INVALID history")
        exported = api("GET", "/annotation-dataset/v1/export", raw=True)
        require([json.loads(line) for line in exported.splitlines()] == api("GET", "/annotation-dataset/v1")["records"],
                "JSON/NDJSON dataset disagreement")
        self.passed("human SAME, INVALID/restore, support, reviewability, Inspector/dataset/NDJSON")

        pin = {"entry_id": entry, "current_extraction_id": old["id"], "selection_mode": "pinned"}
        require(api("GET", selection) == pin, "old pin not retained")
        latest = extract()
        require(api("GET", selection) == pin, "new extraction displaced persistent pin")
        persisted_pin = snapshot(db)
        self.replace()
        require(api("GET", selection) == pin and snapshot(db) == persisted_pin,
                "replacement lost explicit old-version pin")
        counts, before = self.calls(), snapshot(db)
        automatic = api("DELETE", "/api" + selection)
        require(automatic == {"entry_id": entry, "current_extraction_id": latest["id"],
                              "selection_mode": "automatic"}, "clear did not select latest")
        require(api("DELETE", selection) == automatic, "clear not idempotent")
        after = snapshot(db)
        require({k: v for k, v in before.items() if k != "entry_current_extractions"} ==
                {k: v for k, v in after.items() if k != "entry_current_extractions"}, "selection rewrote history/labels")
        require(self.calls() == counts, "selection called provider")
        require(api("GET", f"/concepts/{concept}")["concept"]["support_state"] == "orphaned", "reset support not derived")
        require({r["unit"]["id"] for r in api("GET", "/annotation-dataset/v1")["records"]} ==
                {latest["units"][0]["id"]}, "dataset did not follow reset")
        advancing = extract()
        require(api("GET", selection)["current_extraction_id"] == advancing["id"], "automatic selection did not advance")
        api("PUT", selection, {"extraction_id": advancing["id"]})
        require(api("GET", selection)["selection_mode"] == "pinned", "pin latest indistinguishable")
        api("DELETE", selection)
        self.passed("old pin/new versions/reset/advance; unchanged labels and derived projections")

        before, counts = snapshot(db), self.calls()
        mutations = [("POST", "/captures", capture), ("POST", path + "/analysis", None),
                     ("POST", path + "/extractions", None),
                     ("POST", f"/knowledge-units/{uid}/invalid", None), ("DELETE", selection, None)]
        for prefix in ("", "/api"):
            for method, route, body in mutations:
                for headers in ({"Origin": "https://attacker.invalid", "Content-Type": "text/plain"},
                                {"Origin": "https://attacker.invalid", "Content-Type": "application/json"},
                                {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"},
                                {"Host": "unknown.flh026.test", "Origin": "http://unknown.flh026.test",
                                 "X-Forwarded-Host": f"127.0.0.1:{self.port}"}):
                    api(method, prefix + route, body, expected=403, headers=headers)
            api("GET", prefix + "/entries", expected=403, headers={"Host": "unknown.flh026.test"})
        api("POST", "/captures", capture, expected=415,
            headers={"Origin": f"http://127.0.0.1:{self.port}", "Content-Type": "text/plain"})
        require(snapshot(db) == before and self.calls() == counts, "browser rejection wrote/called provider")
        # Allowed requests are capture replays, proving compatibility without adding rows.
        for headers in ({}, {"Origin": f"http://127.0.0.1:{self.port}", "Sec-Fetch-Site": "same-origin"},
                        {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-site"},
                        {"Host": f"nas.flh026.test:{self.port}", "Origin": f"http://nas.flh026.test:{self.port}"},
                        {"Host": f"192.0.2.26:{self.port}", "Origin": f"http://192.0.2.26:{self.port}"}):
            for prefix in ("", "/api"):
                require(not api("POST", prefix + "/captures", capture, headers=headers)["created"], "allowed replay")
        require(snapshot(db) == before and self.calls() == counts, "compatibility replay changed data")
        self.passed("root/api browser/Host rejection: zero rows changed and zero provider calls; CLI/release/dev/NAS allowed")

        expected_db = snapshot(db)
        expected_selection = api("GET", selection)
        expected_dataset = api("GET", "/annotation-dataset/v1")
        self.replace()
        require(snapshot(db) == expected_db and api("GET", selection) == expected_selection
                and api("GET", "/annotation-dataset/v1") == expected_dataset, "replacement lost persisted state")
        self.passed("service/container replacement preserves complete records and projections")

        self.stop()
        backup_dir = self.run_dir / "backup"
        backup(self.active, backup_dir)
        self.start()
        marker = api("POST", "/entries", {"original_input": "AFTER BACKUP C", "original_context": "discard on restore"}, expected=201)
        self.stop()
        changed_db = snapshot(db)
        old_dir = restore(self.active, backup_dir)
        require(snapshot(old_dir / "app.db") == changed_db, "restore did not preserve old directory")
        self.replace()
        require(snapshot(db) == expected_db and api("GET", selection) == expected_selection
                and api("GET", "/annotation-dataset/v1") == expected_dataset, "restored state mismatch")
        api("GET", f"/entries/{marker['id']}", expected=404)
        # Ordinary startup and --build use the SAME configured path, never a one-off override.
        if self.mode == "container":
            self.compose(["down"])
            self.start()
            require(snapshot(db) == expected_db, "ordinary down/up selected wrong restoration")
            require(self.calls() == {"analysis": 0, "extraction": 0}, "ordinary startup called fresh provider")
            counts = self.calls()  # The fake process also replaced; its counters start at zero.
        else:
            self.replace()
            require(snapshot(db) == expected_db, "ordinary native restart selected wrong restoration")
        self.replace(build=self.mode == "container")
        require(snapshot(db) == expected_db and snapshot(old_dir / "app.db") == changed_db,
                "subsequent startup/build lost restore or old directory")
        require(self.calls() == counts, "persistence/recovery called a provider")
        self.passed("checksum/integrity backup, old directory retained, durable restore across ordinary startup/build")

    def cleanup(self):
        errors = []
        try:
            self.stop()
        except BaseException as exc:
            errors.append(str(exc))
        if self.provider:
            self.provider.release.set()
            self.provider.shutdown()
            self.provider.server_close()
            self.provider_thread.join(timeout=5)
        if self.mode == "container" and self.compose_started:
            try:
                self.compose(["down", "--remove-orphans", "--volumes"])
            except BaseException as exc:
                errors.append(str(exc))
        if self.mode == "container" and self.image_attempted:
            try:
                # Remove only the unique harness tag, never shared base images/cache.
                if self.command(["docker", "image", "inspect", self.image], check=False).returncode == 0:
                    self.command(["docker", "image", "rm", self.image])
            except BaseException as exc:
                errors.append(str(exc))
        if self.port_socket:
            self.port_socket.close()
        self.log.close()
        if not errors:
            shutil.rmtree(self.run_dir)
        return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("native", "container"), default="native")
    parser.add_argument("--go-binary", type=Path, help="absolute native compiler executable; isolated environment still applies")
    parser.add_argument("--report", type=Path, help="new JSON evidence file outside repository; no overwrite")
    args = parser.parse_args()
    if args.report:
        target = args.report.resolve()
        require(not target.exists() and ROOT not in target.parents and target.parent.is_dir(),
                "report must be a new file outside repository in an existing directory")
    os.umask(0o077)
    require(args.go_binary is None or args.mode == "native", "--go-binary requires native mode")
    # Keep the established single-argument launcher hook used by read-only adapters.
    harness = Harness(args.mode)
    harness.go_binary = args.go_binary
    print(f"MODE={args.mode} ISOLATED_RUN={harness.run_dir}", flush=True)
    error = None
    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f"signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    try:
        harness.prepare()
        harness.start()
        harness.workflow()
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        print("FAIL " + error, flush=True)
    finally:
        evidence = {"mode": args.mode, "status": "FAIL" if error else "PASS", "error": error,
                    "harness_sha256": harness.harness_manifest,
                    "source_sha256": getattr(harness, "manifest", {}), "cases": harness.results,
                    "commands": harness.commands, "native_compiler": getattr(harness, "compiler", None), "service_log": (harness.run_dir / "service.log").read_text(),
                    "limits": ["No real browser/DOM checks; Vite headers simulated",
                               "FLH-025 frontend behavior excluded", "Browser boundary is not authentication"]}
        cleanup_errors = harness.cleanup()
        evidence["cleanup_errors"] = cleanup_errors
        evidence["temporary_directory_removed"] = not harness.run_dir.exists()
        if cleanup_errors:
            evidence["status"] = "FAIL"
            print("FAIL cleanup: " + repr(cleanup_errors), flush=True)
        if args.report:
            with args.report.open("x") as output:
                json.dump(evidence, output, indent=2)
        print(f"RESULT={evidence['status']} CLEANUP={'PASS' if not cleanup_errors else 'FAIL'}", flush=True)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
