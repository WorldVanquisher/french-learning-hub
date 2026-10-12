#!/usr/bin/env python3
"""Independent FLH-048 acceptance, local counted fake embeddings only.

No dependency installation. Retains results/logs/hashes under a new /tmp path.
Known defects are recorded as observations, not silently repaired.
"""
import argparse
from collections import defaultdict
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
FIXTURE = ROOT / "scripts/validation/flh045/fixture.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(ranks):
    n = len(ranks)
    hits = [sum(r is not None and 1 <= r <= k for r in ranks) for k in (1, 3, 5)]
    return dict(n=n, hits_at_1=hits[0], hits_at_3=hits[1], hits_at_5=hits[2],
                recall_at_1=hits[0] / n if n else None,
                recall_at_3=hits[1] / n if n else None,
                recall_at_5=hits[2] / n if n else None,
                mrr_at_5=sum(1 / r for r in ranks if r is not None and 1 <= r <= 5) / n if n else None)


def recompute(report, fixture):
    truth = {j["query_id"]: j for j in fixture["judgments"]}
    qmap = {q["id"]: q for q in fixture["queries"]}
    output = {}
    for run in report["offline_baselines"] + [report["embedding"]]:
        evaluation = run["evaluation"]
        if run["state"] != "completed":
            for key in ("overall", "by_split", "by_language", "by_split_language", "by_group"):
                assert evaluation[key] is None, (run["name"], key)
            continue
        assert len(run["queries"]) == 56
        groups = {key: defaultdict(list) for key in ("by_split", "by_language", "by_split_language", "by_group")}
        overall = []
        for row in run["queries"]:
            q = qmap[row["query_id"]]
            assert row["status"] == "ok"
            hits = row["hits"]
            assert len(hits) <= 5
            assert [h["rank"] for h in hits] == list(range(1, len(hits) + 1))
            assert len({h["concept_id"] for h in hits}) == len(hits)
            for i, hit in enumerate(hits):
                assert 1 <= hit["concept_id"] <= 24
                assert hit["concept_fixture_id"] == f"C{hit['concept_id']:03d}"
                assert math.isfinite(hit["score"])
                if i:
                    previous = hits[i - 1]
                    assert previous["score"] >= hit["score"]
                    if previous["score"] == hit["score"]:
                        assert previous["concept_id"] < hit["concept_id"]
            if q["bucket"] != "single_target":
                continue
            target = truth[q["id"]]["proposed_relevant_concept_ids"][0]
            rank = next((h["rank"] for h in hits if h["concept_fixture_id"] == target), None)
            case = next(c for c in evaluation["single_target_cases"] if c["query_id"] == q["id"])
            assert case["target_rank"] == rank and case["proposed_target"] == target
            overall.append(rank)
            for field, value in (("by_split", q["split"]), ("by_language", q["language"]),
                                 ("by_split_language", q["split"] + "/" + q["language"]), ("by_group", q["group_id"])):
                groups[field][value].append(rank)
        calculated = {"overall": metrics(overall)}
        calculated.update({key: {group: metrics(ranks) for group, ranks in values.items()} for key, values in groups.items()})
        for key, values in calculated.items():
            pairs = [(values, evaluation[key])] if key == "overall" else [(m, evaluation[key][g]) for g, m in values.items()]
            for want, actual in pairs:
                for field, value in want.items():
                    assert actual[field] == value if value is None or isinstance(value, int) else math.isclose(actual[field], value, abs_tol=1e-14), (run["name"], key, field)
        assert len(evaluation["single_target_cases"]) == 48
        assert len(evaluation["ambiguous_cases"]) == len(evaluation["no_match_cases"]) == 4
        for key, values in groups.items():
            assert sum(len(v) for v in values.values()) == 48
        for case in evaluation["ambiguous_cases"]:
            row = next(q for q in run["queries"] if q["query_id"] == case["query_id"])
            assert case["returned"] == len(row["hits"])
            for alt in truth[case["query_id"]]["possible_concept_ids"]:
                assert case["alternative_ranks"][alt] == next((h["rank"] for h in row["hits"] if h["concept_fixture_id"] == alt), None)
        for case in evaluation["no_match_cases"]:
            row = next(q for q in run["queries"] if q["query_id"] == case["query_id"])
            assert case["returned"] == len(row["hits"])
        assert evaluation["no_match_queries_with_any_result"] == sum(c["returned"] > 0 for c in evaluation["no_match_cases"])
        output[run["name"]] = calculated
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    if not output.is_absolute() or not str(output).startswith("/tmp/flh051"):
        parser.error("output must be an isolated new /tmp/flh051... directory")
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, GOPROXY="off", GOSUMDB="off")
    fixture = json.loads(FIXTURE.read_text())
    preserved = [*sorted((ROOT / "scripts/validation/flh045").glob("*")), *sorted((ROOT / "scripts/validation/flh048").glob("*"))]
    preserved = [p for p in preserved if p.is_file()]
    before = {str(p.relative_to(ROOT)): sha(p) for p in preserved}
    commands = []
    observations = {}

    def execute(name, cmd, expected=None, extra_env=None):
        task_env = dict(env, **(extra_env or {}))
        start = time.monotonic()
        run = subprocess.run(cmd, cwd=ROOT, env=task_env, capture_output=True, text=True, timeout=90)
        (output / (name + ".stdout")).write_text(run.stdout)
        (output / (name + ".stderr")).write_text(run.stderr)
        commands.append(dict(name=name, argv=cmd, exit=run.returncode, elapsed_s=time.monotonic() - start))
        if expected is not None:
            assert run.returncode == expected, (name, run.returncode, run.stderr)
        return run

    binary = output / "runner"
    execute("build", ["go", "build", "-o", str(binary), "./scripts/validation/flh048"], 0)
    execute("existing-tests", ["go", "test", "-json", "-count=1", "./scripts/validation/flh048"], 0)
    overlay = {"Replace": {
        str(ROOT / "internal/application/flh051_virtual_bridge.go"): str(HERE / "production_bridge.go.txt"),
        str(ROOT / "scripts/validation/flh048/flh051_virtual_test.go"): str(HERE / "independent_test.go.txt"),
    }}
    (output / "overlay.json").write_text(json.dumps(overlay, indent=2) + "\n")
    execute("independent-go", ["go", "test", "-overlay", str(output / "overlay.json"), "-json", "-count=1", "-run", "^TestFLH051", "./scripts/validation/flh048"], 0,
            {"FLH051_FIXTURE": str(FIXTURE), "FLH051_GO_EVIDENCE": str(output / "go-evidence.json")})

    reports = {}
    for name in ("offline-a", "offline-b", "offline-expired"):
        flags = ["-timeout", "1ns"] if name == "offline-expired" else []
        execute(name, [str(binary), "-out", str(output / name), *flags], 0)
        reports[name] = json.loads((output / name / "report.json").read_text())
    for a, b in zip(reports["offline-a"]["offline_baselines"], reports["offline-b"]["offline_baselines"]):
        assert a["ranking_digest"] == b["ranking_digest"]
    observations["overall_deadline"] = {"exit": 0, "configured": "1ns", "states": [r["state"] for r in reports["offline-expired"]["offline_baselines"]], "defect": "expired overall deadline yields completed baselines and quality metrics"}

    class Server(ThreadingHTTPServer):
        daemon_threads = True

    for mode in ("constant", "fail_second", "slow", "overall_timeout", "wrong_count", "empty_vector", "mixed_dimensions", "wrong_dimensions", "duplicate_index", "nonfinite", "cap_1399"):
        ledger = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                ledger.append({"path": self.path, "model": request["model"], "input": request["input"]})
                call = len(ledger)
                if mode in ("slow", "overall_timeout"):
                    time.sleep(1.5)
                if mode == "fail_second" and call == 2:
                    self.send_error(503)
                    return
                data = [{"index": i, "embedding": [1.0, 0.0]} for i in range(len(request["input"]))]
                if mode == "wrong_count":
                    data.pop()
                elif mode == "empty_vector":
                    data[0]["embedding"] = []
                elif mode == "mixed_dimensions":
                    data[-1]["embedding"] = [1.0]
                elif mode == "duplicate_index":
                    data[-1]["index"] = 0
                elif mode == "nonfinite":
                    data[0]["embedding"] = [float("nan"), 0]
                raw = json.dumps({"data": data}).encode()
                self.send_response(200)
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server = Server(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        name = "fake-" + mode
        try:
            flags = ["-embedding", "http", "-embedding-base-url", f"http://127.0.0.1:{server.server_port}/v1", "-embedding-model", "flh051-counted-constant-fake",
                     "-embedding-max-inputs", "1399" if mode == "cap_1399" else "1400", "-embedding-dimensions", "3" if mode == "wrong_dimensions" else "2", "-embedding-timeout", "1s"]
            if mode == "overall_timeout":
                flags += ["-timeout", "200ms"]
            expected = 0 if mode == "constant" else 2 if mode == "cap_1399" else 1
            execute(name, [str(binary), "-out", str(output / name), *flags], expected)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            # Let timed-out handlers finish before mutating the loop's captured mode.
            if mode in ("slow", "overall_timeout"):
                time.sleep(1.5)
        (output / (name + ".provider.json")).write_text(json.dumps(ledger, indent=2) + "\n")
        if mode == "cap_1399":
            assert not ledger and not (output / name).exists()
            observations[mode] = {"exit": 2, "requests": 0}
            continue
        report = json.loads((output / name / "report.json").read_text())
        reports[name] = report
        er = report["embedding"]
        counter = er["provider_counters"]
        assert counter["requests"] == len(ledger)
        assert counter["input_positions"] == sum(len(row["input"]) for row in ledger)
        assert counter["unique_input_hashes"] == len({hashlib.sha256(text.encode()).hexdigest() for row in ledger for text in row["input"]})
        assert all(row["path"] == "/v1/embeddings" for row in ledger)
        if mode == "constant":
            assert len(ledger) == 56 and counter["input_positions"] == 1400
            assert all([h["concept_id"] for h in q["hits"]] == [1, 2, 3, 4, 5] for q in er["queries"])
            evidence = json.loads((output / "go-evidence.json").read_text())
            assert [row["input"] for row in ledger] == evidence["provider_batches"]
        else:
            assert er["state"] == "failed" and er["evaluation"]["overall"] is None
            assert len(ledger) == (2 if mode == "fail_second" else 1)
            assert sum(q["status"] == "error" for q in er["queries"]) == 1
            error_position = next(i for i, q in enumerate(er["queries"]) if q["status"] == "error")
            assert all(q["status"] == "not_run_after_error" for q in er["queries"][error_position + 1:])
            assert all(r["state"] == "completed" for r in report["offline_baselines"])
        observations[mode] = {"exit": expected, "state": er["state"], "counter": counter}

    # Output and fixture protections: all collision targets are task-owned or read-only.
    existing = output / "existing"
    existing.mkdir()
    sentinel = existing / "sentinel"
    sentinel.write_text("preserve FLH051 sentinel\n")
    sentinel_hash = sha(sentinel)
    for name, target in (("nonempty", existing), ("rerun", output / "offline-a"),
                         ("repo", HERE / "rejected-output"), ("fixture-path", FIXTURE)):
        execute("reject-" + name, [str(binary), "-out", str(target)], 3)
    assert sha(sentinel) == sentinel_hash
    link = output / "repo-link"
    link.symlink_to(HERE, target_is_directory=True)
    execute("reject-symlink", [str(binary), "-out", str(link / "rejected-output")], 3)
    link.unlink()
    external = output / "external-fixture"
    external.mkdir()
    copied_fixture = external / "fixture.json"
    copied_fixture.write_bytes(FIXTURE.read_bytes())
    execute("reject-fixture-adjacent", [str(binary), "-fixture", str(copied_fixture), "-out", str(external / "out")], 3)
    execute("reject-fixture-parent", [str(binary), "-fixture", str(copied_fixture), "-out", str(external)], 3)
    mutated = json.loads(FIXTURE.read_text())
    mutated["judgments"][0]["rationale"] = "FLH051_UNREVIEWED_MUTATED_COPY"
    copied_fixture.write_text(json.dumps(mutated, ensure_ascii=False))
    execute("reject-modified", [str(binary), "-fixture", str(copied_fixture), "-out", str(output / "modified-refused")], 3)
    override = execute("digest-override", [str(binary), "-fixture", str(copied_fixture), "-expect-fixture-sha256", sha(copied_fixture), "-out", str(output / "digest-override")], 0)
    assert "matches frozen FLH-045: true" in override.stdout
    observations["freeze_override"] = {"exit": 0, "actual_sha256": sha(copied_fixture), "frozen_sha256": sha(FIXTURE), "misleading_summary": "matches frozen FLH-045: true"}

    calculated = {name: recompute(report, fixture) for name, report in reports.items()}
    (output / "independent-metrics.json").write_text(json.dumps(calculated, indent=2) + "\n")
    for name in ("offline-a", "offline-b"):
        report = reports[name]
        assert report["concept_id_mapping"] == [{"fixture_id": f"C{i:03d}", "runtime_id": i} for i in range(1, 25)]
        assert report["query_id_mapping"] == [{"fixture_id": f"Q{i:03d}", "runtime_id": i} for i in range(1, 57)]
        assert report["inputs"]["fixture_sha256"] == sha(FIXTURE)
        assert report["denominators"]["single_target_by_split"] == {"development": 32, "held_out": 16}
        assert report["denominators"]["single_target_by_language"] == {"en": 24, "fr": 24}
        for label in ("author-proposed", "NOT the production", "NOT independently collected", "correlated", "author has seen"):
            assert label in " ".join(report["labels"])
    after = {str(p.relative_to(ROOT)): sha(p) for p in preserved}
    assert before == after, "read-only input changed during acceptance"
    (output / "preserved-sources.json").write_text(json.dumps(before, indent=2) + "\n")
    (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    (output / "observations.json").write_text(json.dumps(observations, indent=2) + "\n")
    artifacts = {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob("*")) if p.is_file() and not p.is_symlink()}
    (output / "artifact-sha256.json").write_text(json.dumps(artifacts, indent=2) + "\n")
    print(json.dumps({"result": "NOT ACCEPTED", "reproduced_defects": ["overall_deadline", "freeze_override"],
                      "offline_metrics": {name: rows["overall"] for name, rows in calculated["offline-a"].items()}, "outputs": str(output)}, indent=2))


if __name__ == "__main__":
    main()
