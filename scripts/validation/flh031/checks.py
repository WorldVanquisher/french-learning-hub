#!/usr/bin/env python3
"""Read-only shared-tree checks; all writable source/build output is private."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from verify import ROOT, digest, inspect_baseline

IMAGE = "golang:1.26.5-alpine@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report_path = args.report.resolve()
    if report_path.exists() or ROOT in report_path.parents or not report_path.parent.is_dir():
        raise ValueError("report must be new and outside repository")
    baseline = inspect_baseline()
    report = {"baseline_sha256": digest(baseline), "baseline_manifest": baseline, "commands": [], "status": "FAIL"}
    with tempfile.TemporaryDirectory(prefix="flh031-checks-") as directory:
        run = Path(directory)
        src, out, home = run / "source", run / "output", run / "home"
        src.mkdir()
        out.mkdir()
        home.mkdir()
        (home / "docker").mkdir()
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(home), "DOCKER_CONFIG": str(home / "docker"),
               "DOCKER_HOST": "unix:///var/run/docker.sock", "GOENV": "off", "GOTOOLCHAIN": "local",
               "GOFLAGS": "-mod=readonly -buildvcs=false", "GOPROXY": "off", "GOSUMDB": "off",
               "NODE_OPTIONS": "--no-experimental-webstorage", "AI_PROVIDER": "rule-based",
               "EXTRACTOR_PROVIDER": "disabled", "EMBEDDING_PROVIDER": "disabled"}
        def command(argv, cwd=src, command_env=env):
            result = subprocess.run(argv, cwd=cwd, env=command_env, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=600)
            report["commands"].append({"argv": argv, "exit": result.returncode, "output": result.stdout})
            print(f"EXIT={result.returncode} {argv}", flush=True)
            return result
        try:
            for name in ("cmd", "internal", "migrations", "web"):
                shutil.copytree(ROOT / name, src / name, ignore=shutil.ignore_patterns(
                    ".*", "node_modules", "dist", "data", "*.db*", "*.sqlite*", "*.tsbuildinfo"))
            for name in ("go.mod", "go.sum"):
                shutil.copy2(ROOT / name, src / name)
            modules = command(["go", "env", "GOMODCACHE"], command_env={"PATH":env["PATH"], "HOME":str(Path.home()), "GOENV":"off", "GOTOOLCHAIN":"local"})
            if modules.returncode != 0:
                raise RuntimeError("module cache discovery failed")
            cache = modules.stdout.strip()
            checked = command(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"])
            if checked.returncode != 0:
                raise RuntimeError("pinned Go image unavailable")
            docker = ["docker", "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}",
                      "--mount", f"type=bind,src={src},dst=/src,readonly", "--mount", f"type=bind,src={cache},dst=/gomod,readonly",
                      "--mount", f"type=bind,src={out},dst=/checks", "--workdir", "/src"]
            for key, value in {"GOTOOLCHAIN":"local", "GOFLAGS":"-mod=readonly -buildvcs=false", "CGO_ENABLED":"0",
                               "GOCACHE":"/checks/gocache", "GOMODCACHE":"/gomod", "GOPROXY":"off", "GOENV":"off",
                               "HOME":"/checks", "AI_PROVIDER":"rule-based", "EXTRACTOR_PROVIDER":"disabled", "EMBEDDING_PROVIDER":"disabled"}.items():
                docker += ["-e", key + "=" + value]
            script = '''set -eu
            go version
            test "$(go env GOVERSION)" = go1.26.5
            test -z "$(gofmt -l .)"
            go mod verify
            go test -json ./internal/storage/sqlite ./internal/application ./internal/transport/http -run 'Test(AnnotationOperation|BrowserBoundary)' -count=1
            go test -json ./... -count=1
            go vet ./...
            go build -o /checks/server ./cmd/server
            go build -o /checks/capture ./cmd/capture
            go version -m /checks/server
            go version -m /checks/capture
            '''
            go_checks = command(docker + [IMAGE, "sh", "-c", script])
            report["go_status"] = "PASS" if go_checks.returncode == 0 else "FAIL"
            report["go_test_totals"] = {}
            for line in go_checks.stdout.splitlines():
                if not line.startswith("{"):
                    continue
                event = json.loads(line)
                if event.get("Test") and event.get("Action") in {"pass", "fail", "skip"}:
                    outcome = event["Action"]
                    report["go_test_totals"][outcome] = report["go_test_totals"].get(outcome, 0) + 1
            # Never install or write through the shared dependency directory.
            if not (ROOT / "web/node_modules").is_dir():
                report["frontend_status"] = "NOT RUN: existing dependencies absent"
            else:
                shutil.copytree(ROOT / "web/node_modules", src / "web/node_modules", symlinks=True)
                frontend = [command(["npm", "run", "typecheck"], src / "web"),
                            command(["npm", "test", "--", "--reporter=json", "--outputFile=" + str(out / "frontend-tests.json")], src / "web"),
                            command(["npm", "run", "build"], src / "web")]
                report["frontend_status"] = "PASS" if all(r.returncode == 0 for r in frontend) else "FAIL"
                if (out / "frontend-tests.json").exists():
                    report["frontend_tests"] = json.loads((out / "frontend-tests.json").read_text())
            if inspect_baseline() != baseline:
                raise RuntimeError("shared baseline changed during checks")
            report["status"] = "PASS" if report.get("go_status") == report.get("frontend_status") == "PASS" else "FAIL"
        except BaseException as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
    report["temporary_directory_removed"] = not Path(directory).exists()
    with report_path.open("x") as output:
        json.dump(report, output, indent=2)
    print("RESULT=" + report["status"], flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
