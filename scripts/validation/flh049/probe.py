#!/usr/bin/env python3
"""Independent offline fixture and real-Go helper enforcement probes.

The loopback facade is NOT Qdrant: it exercises helper orchestration only.
Use -B; Go modules must already be cached. Outputs go to an explicit /tmp path.
"""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[3]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def fixture_probes(output):
    validator = module("flh045_validator", ROOT / "scripts/validation/flh045/validate.py")
    fixture = validator.load(ROOT / "scripts/validation/flh045/fixture.json")
    results = {}
    for name in ("wrong_target", "partial_identity_copy", "semantic_split", "cross_family_alternative"):
        data = copy.deepcopy(fixture)
        if name == "wrong_target":
            for judgment in data["judgments"][:4]:
                judgment["proposed_relevant_concept_ids"] = ["C002" if judgment["query_id"] in ("Q001", "Q002") else "C001"]
                judgment["hard_negatives"][0]["concept_id"] = "C001" if judgment["query_id"] in ("Q001", "Q002") else "C002"
        elif name == "partial_identity_copy":
            data["queries"][0]["unit_evidence"]["canonical"] = "imparfait de description"
            data["queries"][0]["unit_evidence"]["statement"] = "Explique l’arrière-plan passé."
        elif name == "semantic_split":
            data["queries"][40]["free_text"] = "How do I describe the weather that was continuing behind yesterday’s story?"
        else:
            data["judgments"][16]["hard_negatives"].append({"concept_id": "C024", "rationale": "Useful article-change search alternative, but distinct SAME identity."})
        with tempfile.TemporaryDirectory(prefix="flh049-fixture-") as temp:
            path = Path(temp) / "fixture.json"
            path.write_text(json.dumps(data, ensure_ascii=False))
            run = subprocess.run(["python3", "-B", str(ROOT / "scripts/validation/flh045/validate.py"), str(path)], capture_output=True, text=True)
        results[name] = {"exit": run.returncode, "error": run.stderr.strip()}
    (output / "fixture-probes.json").write_text(json.dumps(results, indent=2) + "\n")
    assert [results[n]["exit"] for n in results] == [0, 0, 0, 1], results
    print(json.dumps(results, indent=2))


def helper_probes(output):
    # Unmodified helper subprocess, actual Go package, temporary PATH wrapper.
    real_go = shutil.which("go")
    assert real_go
    state = {"lists": 0, "names": set(), "deleted": [], "case": ""}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, body):
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/collections":
                state["lists"] += 1
                # Controlled leftover appears after the suite; preexisting stays.
                if state["case"] in ("cleanup", "timeout") and state["lists"] == 2:
                    state["names"].add("flh042_it_flh049_leftover")
                if state["case"] == "cleanup_error" and state["lists"] >= 3:
                    self.send_error(503)
                    return
                self.reply({"result": {"collections": [{"name": n} for n in sorted(state["names"])]}})
            elif self.path == "/":
                self.reply({"version": "facade-not-qdrant"})
            else:
                self.reply({})

        def do_DELETE(self):
            name = self.path.rsplit("/", 1)[1]
            state["names"].discard(name)
            state["deleted"].append(name)
            self.reply({"result": True})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    results = {}
    try:
        with tempfile.TemporaryDirectory(prefix="flh049-wrapper-") as temp:
            wrapper = Path(temp) / "go"
            wrapper.write_text("#!/usr/bin/python3\nimport os, sys\na=sys.argv[1:]\nm=os.environ['FLH049_CASE']\nif m=='skip': os.environ.pop('FLH_QDRANT_URL',None)\nif m=='zero': a[a.index('-run')+1]='^FLH049_NoMatchingTests$'\nif m in ('fail','cleanup'): os.environ['FLH_QDRANT_URL']='http://127.0.0.1:9'\nos.execv(" + repr(real_go) + ", [" + repr(real_go) + "]+a)\n")
            wrapper.chmod(0o700)
            for case in ("skip", "zero", "fail", "cleanup", "cleanup_error", "timeout"):
                state.update(lists=0, names={"flh042_it_preexisting"}, deleted=[], case=case)
                artifacts = output / case
                env = dict(os.environ, PATH=temp + os.pathsep + os.environ["PATH"], FLH049_CASE=case, GOPROXY="off", GOSUMDB="off")
                cmd = ["python3", "-B", str(ROOT / "scripts/ci/flh046/qdrant_regression.py"), "--endpoint", f"http://127.0.0.1:{server.server_port}", "--artifacts", str(artifacts), "--test-timeout", "60"]
                if case in ("cleanup_error", "timeout"):
                    # Eight trivial Go tests isolate a successful verdict followed
                    # by a failed cleanup listing. This is orchestration evidence,
                    # never evidence of Qdrant integration success.
                    package = Path(temp) / "internal/vectorindex"
                    package.mkdir(parents=True, exist_ok=True)
                    (Path(temp) / "go.mod").write_text("module flh049probe\n\ngo 1.27\n")
                    helper = module("flh046_helper", ROOT / "scripts/ci/flh046/qdrant_regression.py")
                    names = helper.read_expected(helper.EXPECTED_FILE.read_text())
                    imports = 'import "testing"\n' if case == "cleanup_error" else 'import ("testing"; "time")\n'
                    body = "" if case == "cleanup_error" else "time.Sleep(3*time.Second)"
                    (package / "probe_test.go").write_text('package vectorindex\n' + imports + "\n".join('func ' + n + '(t *testing.T) {' + body + '}' for n in names))
                    launcher = Path(temp) / "launch.py"
                    launcher.write_text("import importlib.util, pathlib, sys\ns=importlib.util.spec_from_file_location('helper', " + repr(str(ROOT / "scripts/ci/flh046/qdrant_regression.py")) + ")\nh=importlib.util.module_from_spec(s)\ns.loader.exec_module(h)\nh.ROOT=pathlib.Path(" + repr(temp) + ")\nh.TEST_DIR=h.ROOT/'internal/vectorindex'\nsys.exit(h.main(sys.argv[1:]))\n")
                    cmd[2] = str(launcher)
                    if case == "timeout":
                        cmd[-1] = "1"
                with (output / (case + ".log")).open("w") as log:
                    run = subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=200)
                summary = json.loads((artifacts / "summary.json").read_text())
                results[case] = {"exit": run.returncode, "go_exit": summary["go_exit"], "results": summary["verdict"]["results"], "reasons": summary["verdict"]["reasons"], "cleanup": summary.get("leftover_cleanup"), "deleted": state["deleted"], "remaining": sorted(state["names"])}
                if case == "cleanup_error":
                    assert run.returncode == 0 and "error" in summary["leftover_cleanup"], results[case]
                    continue
                assert run.returncode == (4 if case == "timeout" else 1), results[case]
                assert state["names"] == {"flh042_it_preexisting"}, results[case]
                assert state["deleted"] == (["flh042_it_flh049_leftover"] if case in ("cleanup", "timeout") else []), results[case]
                reasons = " ".join(summary["verdict"]["reasons"])
                assert {"skip": "skipped:", "zero": "zero tests ran", "fail": "failed:", "cleanup": "test collections left behind", "timeout": "go test did not finish"}[case] in reasons, results[case]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    (output / "helper-probes.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


def real_probes(output):
    """Run unchanged container helper using only the already-cached pinned image."""
    docker = shutil.which("docker")
    assert docker
    helper = module("flh046_real", ROOT / "scripts/ci/flh046/qdrant_regression.py")
    image, _ = helper.pinned_image(helper.COMPOSE_FILE.read_text())
    inspected = subprocess.run([docker, "image", "inspect", image], capture_output=True, text=True, check=True)
    (output / "cached-image.json").write_text(inspected.stdout)
    image_info = json.loads(inspected.stdout)[0]
    assert image.split("@", 1)[1] in " ".join(image_info["RepoDigests"])
    with tempfile.TemporaryDirectory(prefix="flh049-docker-wrapper-") as temp:
        wrapper = Path(temp) / "docker"
        wrapper.write_text("#!/usr/bin/python3\nimport json, os, sys\na=sys.argv[1:]\nwith open(" + repr(str(output / "docker-commands.jsonl")) + ", 'a') as log: log.write(json.dumps(a)+'\\n')\nif a and a[0]=='pull':\n assert a[1]==" + repr(image) + "\n a=['image','inspect',a[1]]\nos.execv(" + repr(docker) + ", [" + repr(docker) + "]+a)\n")
        wrapper.chmod(0o700)
        env = dict(os.environ, PATH=temp + os.pathsep + os.environ["PATH"], GOPROXY="off", GOSUMDB="off")
        results = {}
        for case, timeout in (("pass", "60"), ("timeout", "1"), ("fail", "60"), ("skip", "60"), ("zero", "60")):
            artifacts = output / case
            cmd = ["python3", "-B", str(ROOT / "scripts/ci/flh046/qdrant_regression.py"), "--artifacts", str(artifacts), "--ready-timeout", "10", "--test-timeout", timeout]
            case_env = dict(env)
            if case in ("timeout", "fail"):
                copied = Path(temp) / case
                copied.mkdir()
                shutil.copytree(ROOT / "internal", copied / "internal")
                shutil.copytree(ROOT / "migrations", copied / "migrations")
                for name in ("go.mod", "go.sum"):
                    shutil.copyfile(ROOT / name, copied / name)
                source = copied / "internal/vectorindex/qdrant_integration_test.go"
                text = source.read_text()
                marker = "func TestQdrantIntegration_BuildSyncRebuildRestartAndCacheReuse(t *testing.T) {"
                assert text.count(marker) == 1
                # Delay/fail after the first actual rig is established; never
                # change the production source or the helper's expected list.
                start = text.index(marker)
                position = text.index("r := newRig(t)", start) + len("r := newRig(t)")
                injection = '\n time.Sleep(3*time.Second)' if case == "timeout" else '\n t.Fatal("FLH049 deliberate failure")'
                source.write_text(text[:position] + injection + text[position:])
                launcher = copied / "launch.py"
                launcher.write_text("import importlib.util, pathlib, sys\ns=importlib.util.spec_from_file_location('helper', " + repr(str(ROOT / "scripts/ci/flh046/qdrant_regression.py")) + ")\nh=importlib.util.module_from_spec(s)\ns.loader.exec_module(h)\nh.ROOT=pathlib.Path(" + repr(str(copied)) + ")\nh.TEST_DIR=h.ROOT/'internal/vectorindex'\nsys.exit(h.main(sys.argv[1:]))\n")
                cmd[2] = str(launcher)
            elif case in ("skip", "zero"):
                go = shutil.which("go")
                go_wrapper = Path(temp) / "go"
                go_wrapper.write_text("#!/usr/bin/python3\nimport os,sys\na=sys.argv[1:]\n" + ("os.environ.pop('FLH_QDRANT_URL',None)\n" if case == "skip" else "a[a.index('-run')+1]='^FLH049_NoMatchingTests$'\n") + "os.execv(" + repr(go) + ", [" + repr(go) + "]+a)\n")
                go_wrapper.chmod(0o700)
            with (output / (case + ".log")).open("w") as log:
                run = subprocess.run(cmd, env=case_env, stdout=log, stderr=subprocess.STDOUT, timeout=300)
            summary = json.loads((artifacts / "summary.json").read_text())
            results[case] = summary
            assert run.returncode == {"pass": 0, "timeout": 4, "fail": 1, "skip": 1, "zero": 1}[case], summary
            assert summary["image"] == image and summary["qdrant"]["version"] == "1.19.1", summary
            assert summary["cleanup"]["removed"] is True, summary
            if case == "pass":
                events = [json.loads(line) for line in (artifacts / "go-test.jsonl").read_text().splitlines()]
                for name in summary["expected"]:
                    assert any(e.get("Test") == name and e["Action"] == "run" for e in events), name
                    assert any(e.get("Test") == name and e["Action"] == "pass" for e in events), name
                assert len(summary["verdict"]["passed"]) == 8 and summary["go_exit"] == 0, summary
            print(case, run.returncode, summary["qdrant"], summary["cleanup"])
    (output / "real-probes.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fixture", "helper", "real"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.output.is_absolute() or not str(args.output).startswith("/tmp/flh049"):
        parser.error("output must be an isolated /tmp/flh049... directory")
    args.output.mkdir(parents=True, exist_ok=False)
    {"fixture": fixture_probes, "helper": helper_probes, "real": real_probes}[args.mode](args.output)
