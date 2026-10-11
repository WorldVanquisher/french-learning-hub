#!/usr/bin/env python3
"""Available-prerequisite checks and SQLite diagnostics; no Qdrant substitute.

Preserves Phase A. This runner records NOT RUN for real-Qdrant acceptance when
no local Qdrant artifact is present. It never pulls images, installs packages,
reads caller credentials, or launches an existing personal service.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "flh026"))
from run import clean_env  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--docker-only", action="store_true", help="run only new Docker packaging probes")
    args = parser.parse_args()
    destination = args.report.resolve()
    if destination.exists() or ROOT in destination.parents or not destination.parent.is_dir():
        raise ValueError("new report outside repository required")
    parent = Path(tempfile.mkdtemp(prefix="flh041-phase-b-"))
    project = "flh041-" + uuid.uuid4().hex[:12]
    tag = project + ":acceptance"
    home = parent / "home"
    home.mkdir()
    source = parent / "source"
    source.mkdir()
    env = clean_env(home)
    env.update(AI_PROVIDER="rule-based", EXTRACTOR_PROVIDER="disabled", EMBEDDING_PROVIDER="disabled",
               SEMANTIC_SEARCH="disabled", GOCACHE=str(parent / "gocache"), TMPDIR=str(parent),
               DOCKER_BUILDKIT="0")
    env["GOMODCACHE"] = subprocess.check_output(
        ["go", "env", "GOMODCACHE"], env={"PATH": env["PATH"], "HOME": str(Path.home()),
                                         "GOENV": "off", "GOTOOLCHAIN": "local"}, text=True).strip()
    commands, cleanup_errors = [], []
    report = {"scope": "Phase B available-prerequisite checks; real Qdrant integration NOT RUN",
              "pwd": str(ROOT), "commands": commands, "cleanup_errors": cleanup_errors,
              "real_qdrant": "NOT_RUN", "browser": "NOT_RUN", "errors": [],
              "phase_a_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir()
                                    if p.name in ("fixtures.json", "fake_embeddings.py", "oracles.py", "test_fixtures.py")}}
    image_built = False
    compose_attempted = False

    def command(argv, cwd=source, timeout=120):
        started = time.monotonic()
        try:
            result = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=timeout)
            value = {"argv": list(map(str, argv)), "exit": result.returncode,
                     "stdout": result.stdout, "stderr": result.stderr,
                     "seconds": time.monotonic() - started}
        except subprocess.TimeoutExpired as exc:
            value = {"argv": list(map(str, argv)), "exit": "TIMEOUT",
                     "stdout": (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else exc.stdout,
                     "stderr": (exc.stderr or b"").decode() if isinstance(exc.stderr, bytes) else exc.stderr,
                     "seconds": time.monotonic() - started}
        commands.append(value)
        print("COMMAND " + json.dumps({"argv": value["argv"], "exit": value["exit"]}), flush=True)
        return value

    try:
        for directory in ("cmd", "internal", "migrations"):
            shutil.copytree(ROOT / directory, source / directory)
        for name in ("go.mod", "go.sum", "Dockerfile", ".dockerignore", "compose.yaml"):
            shutil.copy2(ROOT / name, source / name)
        (source / "web").mkdir()
        shutil.copytree(ROOT / "web/src", source / "web/src")
        for name in ("package.json", "package-lock.json", "index.html", "vite.config.ts",
                     "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json"):
            shutil.copy2(ROOT / "web" / name, source / "web" / name)
        shutil.copytree(HERE / "ownership_probe", source / "scripts/validation/flh041/ownership_probe")
        report["source_sha256"] = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in source.rglob("*") if p.is_file()}
        report["versions"] = {name: command(argv)["stdout"] for name, argv in (
            ("go", ["go", "version"]), ("python", ["python3", "--version"]),
            ("docker", ["docker", "version"]), ("compose", ["docker", "compose", "version"]))}
        qimage = "qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10"
        report["qdrant_image"] = command(["docker", "image", "inspect", qimage])
        report["cached_images"] = command(["docker", "image", "ls", "--format", "{{.Repository}} {{.Tag}} {{.ID}}"])
        report["qdrant_binary_on_isolated_path"] = shutil.which("qdrant", path=env["PATH"])
        report["browser_executables"] = {name: shutil.which(name, path=env["PATH"]) for name in
                                          ("chromium", "chromium-browser", "google-chrome", "firefox")}
        if report["qdrant_image"]["exit"] == 0 or report["qdrant_binary_on_isolated_path"]:
            raise RuntimeError("Qdrant now available: this prerequisite-limited diagnostic does not execute P01-P18")
        if not args.docker_only:
            test = command(["python3", "-B", str(HERE / "test_fixtures.py")], cwd=ROOT)
            if test["exit"] != 0:
                report["errors"].append("fixture self-tests failed")
            verify = command(["go", "mod", "verify"])
            test = command(["go", "test", "-json", "./internal/application", "./internal/storage/sqlite",
                            "./internal/vectorindex", "./internal/embedding", "./internal/transport/http",
                            "./internal/config", "./cmd/semantic-index", "-run",
                            "Test.*(Semantic|Qdrant|HTTPProvider|Embedding)", "-count=1"], timeout=240)
            report["production_tests"] = test
            if verify["exit"] != 0 or test["exit"] != 0:
                report["errors"].append("focused production checks failed")
            for target, output in (("./cmd/server", "server"), ("./cmd/semantic-index", "semantic-index"),
                                   ("./scripts/validation/flh041/ownership_probe", "ownership-probe")):
                result = command(["go", "build", "-o", str(parent / output), target], timeout=240)
                if result["exit"] != 0:
                    raise RuntimeError("native build failed: " + target)
                command(["go", "version", "-m", str(parent / output)])
            report["binary_sha256"] = {name: hashlib.sha256((parent / name).read_bytes()).hexdigest()
                                        for name in ("server", "semantic-index", "ownership-probe")}
            result = command([str(parent / "ownership-probe"), str(parent / "diagnostic.db")])
            if result["exit"] != 0:
                raise RuntimeError("SQLite diagnostic failed")
            report["sqlite_diagnostic"] = json.loads(result["stdout"])
        else:
            report["native_checks"] = "NOT_REPEATED: see separate native/SQLite run report"
        data, qdata = parent / "app-data", parent / "qdrant-data"
        data.mkdir()
        qdata.mkdir()
        empty = parent / "empty.env"
        empty.touch()
        env.update(FLH_DATA_DIR=str(data), FLH_QDRANT_DIR=str(qdata),
                   FLH_UID=str(os.getuid()), FLH_GID=str(os.getgid()))
        ports = []
        for _ in range(2):
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                ports.append(sock.getsockname()[1])
        env.update(FLH_HOST_PORT=str(ports[0]), FLH_QDRANT_PORT=str(ports[1]),
                   SEMANTIC_SEARCH="qdrant", EMBEDDING_PROVIDER="http",
                   EMBEDDING_MODEL="fixture", EMBEDDING_MODEL_ID="fixture/model@container",
                   EMBEDDING_DIMENSIONS="8", EMBEDDING_BASE_URL="http://127.0.0.1:9")
        override = parent / "image-override.yaml"
        override.write_text("services:\n  app:\n    image: " + tag + "\n")
        compose = ["docker", "compose", "--env-file", str(empty), "--project-name", project,
                   "-f", str(source / "compose.yaml"), "-f", str(override), "--profile", "semantic"]
        config = command(compose + ["config", "--format", "json"])
        report["compose_config"] = json.loads(config["stdout"]) if config["exit"] == 0 else config
        # pull=false alone still permits fetching a missing base. Require every
        # actual Dockerfile base to be local before invoking the legacy builder.
        bases = [line.split()[1] for line in (source / "Dockerfile").read_text().splitlines()
                 if line.startswith("FROM ")]
        report["local_build_bases"] = [command(["docker", "image", "inspect", base]) for base in bases]
        if any(result["exit"] != 0 for result in report["local_build_bases"]):
            raise RuntimeError("offline image build NOT RUN: a pinned Dockerfile base is not cached")
        # Legacy builder with local pinned bases, pull=false and no network in
        # RUN instructions. It cannot download npm/Go dependencies implicitly.
        result = command(["docker", "build", "--pull=false", "--network", "none",
                          "--tag", tag, str(source)], timeout=110)
        report["offline_image_build"] = result
        image_built = result["exit"] == 0
        if image_built:
            report["built_image"] = command(["docker", "image", "inspect", tag])
            result = command(["docker", "run", "--rm", "--pull=never", "--network", "none",
                              "--name", project + "-cli", "--user", f"{os.getuid()}:{os.getgid()}",
                              "--mount", f"type=bind,source={data},target=/data",
                              "--env", "DB_PATH=/data/app.db", "--env", "SEMANTIC_SEARCH=qdrant",
                              "--env", "EMBEDDING_PROVIDER=http", "--env", "EMBEDDING_MODEL=fixture",
                              "--env", "EMBEDDING_BASE_URL=http://127.0.0.1:9",
                              "--env", "EMBEDDING_MODEL_ID=fixture/model@container",
                              "--env", "EMBEDDING_DIMENSIONS=8", "--env", "QDRANT_URL=http://127.0.0.1:9",
                              "--entrypoint", "/app/semantic-index", tag, "-json", "status"])
            report["container_cli_no_qdrant"] = result
            if result["exit"] != 0:
                raise RuntimeError("integrated container semantic-index did not execute")
            cli_state = json.loads(result["stdout"])
            if cli_state["searchable_complete"] or cli_state["state"] is not None or cli_state["vector_store_error"] != "vector index unavailable":
                raise RuntimeError("container CLI falsely reported available/complete index")
            report["app_storage_after_cli"] = {
                "exists": (data / "app.db").is_file(),
                "uid": (data / "app.db").stat().st_uid,
                "gid": (data / "app.db").stat().st_gid,
                "mode": oct((data / "app.db").stat().st_mode & 0o777)}
            compose_attempted = True
            report["full_profile_launch_attempt"] = command(
                compose + ["up", "--no-build", "--pull", "never", "-d"])
            refusal = report["full_profile_launch_attempt"]
            if refusal["exit"] != 1 or "No such image: " + qimage not in refusal["stderr"]:
                raise RuntimeError("full profile did not fail explicitly at missing pinned Qdrant image")
            # App-only is distinct from a successful semantic profile. Actual
            # Qdrant runtime/storage tests remain NOT RUN.
            report["app_only_start"] = command(
                compose + ["up", "--no-build", "--pull", "never", "-d", "app"])
            if report["app_only_start"]["exit"] != 0:
                raise RuntimeError("owned Compose app did not start")
            report["compose_owned_app_id"] = command(compose + ["ps", "-q", "app"])
            ready = None
            for _ in range(20):
                ready = command(compose + ["exec", "-T", "app", "wget", "-q", "-O", "-",
                                           "http://127.0.0.1:8080/readyz"], timeout=8)
                if ready["exit"] == 0:
                    break
                time.sleep(0.1)
            report["compose_app_readiness"] = ready
            if ready["exit"] != 0:
                raise RuntimeError("owned Compose app did not become ready")

            def db_snapshot():
                with sqlite3.connect(f"file:{data / 'app.db'}?mode=ro", uri=True) as db:
                    db.execute("BEGIN")
                    names = [row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                    return {name: sorted(db.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(),
                                         key=repr) for name in names}

            before = db_snapshot()
            report["compose_container_cli_status"] = command(
                compose + ["exec", "-T", "app", "/app/semantic-index", "-json", "status"])
            report["compose_keyword_browse"] = command(compose + ["exec", "-T", "app", "wget", "-q", "-O", "-",
                                                                  "http://127.0.0.1:8080/knowledge-library/concepts"])
            cli = report["compose_container_cli_status"]
            if cli["exit"] != 0 or json.loads(cli["stdout"])["searchable_complete"]:
                raise RuntimeError("Compose CLI did not report incomplete/unavailable index")
            browse = report["compose_keyword_browse"]
            if browse["exit"] != 0 or json.loads(browse["stdout"])["results"] != []:
                raise RuntimeError("fresh Compose keyword browse did not remain empty/readable")
            after = db_snapshot()
            if before != after:
                raise RuntimeError("Compose status/keyword read changed SQLite rows")
            report["compose_read_only"] = {
                "all_tables_equal": True, "tables": {name: len(rows) for name, rows in before.items()},
                "sha256": hashlib.sha256(repr(before).encode()).hexdigest()}
        else:
            report["container_cli"] = "NOT_RUN: integrated image not built offline"
        report["compose_profile_runtime"] = "NOT_RUN: required pinned Qdrant image absent; app-only tested separately"
        report["qdrant_storage_permissions"] = "NOT_RUN: no Qdrant binary/image available"
        report["status"] = "PREREQUISITE_LIMITED_WITH_DIAGNOSTIC_FINDINGS" if not report["errors"] else "CHECK_FAILURE"
    except BaseException as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        report["status"] = "CHECK_FAILURE"
    finally:
        # Only this task's exact names/tags may be removed; no global prune.
        if compose_attempted:
            result = command(compose + ["down", "--remove-orphans", "--timeout", "10"])
            if result["exit"] != 0:
                cleanup_errors.append("owned Compose teardown failed")
            check = command(["docker", "ps", "-a", "--filter", "label=com.docker.compose.project=" + project,
                             "--format", "{{.ID}}"])
            if check["exit"] != 0 or check["stdout"].strip():
                cleanup_errors.append("owned Compose containers remain")
            check = command(["docker", "network", "ls", "--filter", "label=com.docker.compose.project=" + project,
                             "--format", "{{.ID}}"])
            if check["exit"] != 0 or check["stdout"].strip():
                cleanup_errors.append("owned Compose network remains")
        if image_built:
            result = command(["docker", "rm", "--force", project + "-cli"])
            # --rm means absence is normal; a present leftover must be removed.
            check = command(["docker", "ps", "-a", "--filter", "name=^/" + project + "-cli$", "--format", "{{.ID}}"])
            if check["exit"] != 0 or check["stdout"].strip():
                cleanup_errors.append("task CLI container remains")
            result = command(["docker", "image", "rm", tag])
            if result["exit"] != 0:
                cleanup_errors.append("task image tag removal failed")
        shutil.rmtree(parent)
        report["temporary_directory_removed"] = not parent.exists()
        with destination.open("x") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
        print("RESULT=" + report.get("status", "UNKNOWN") + " CLEANUP=" + str(cleanup_errors), flush=True)
    # Prerequisite-limited validation must not masquerade as passing acceptance.
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
