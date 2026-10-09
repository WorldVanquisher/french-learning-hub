#!/usr/bin/env python3
"""FLH-031 author verification on private source, SQLite and local providers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import sys
import threading
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "flh028"))
from reproduce import Investigation, Harness, owns_listener, require, snapshot  # noqa: E402

KINDS = ("distinct", "broader", "narrower", "related")


def digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def inspect_baseline():
    # Explicit allowlist: never open Git metadata, secrets, databases or symlinks.
    paths = [ROOT / name for name in ("AGENTS.md", "README.md", "README.zh-CN.md",
             "docs/plans/FLH-029-annotation-idempotency.md", "Dockerfile", "compose.yaml", "go.mod", "go.sum")]
    for folder in ("cmd", "internal", "migrations", "web/src", "scripts/validation/flh026", "scripts/validation/flh028"):
        for base, dirs, files in os.walk(ROOT / folder, followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith(".") and not (Path(base) / d).is_symlink()]
            paths.extend(Path(base) / name for name in files if not name.startswith(".")
                         and Path(name).suffix in {".go", ".sql", ".ts", ".tsx", ".py"})
    paths += [ROOT / "web" / name for name in ("package.json", "package-lock.json", "vite.config.ts")]
    required = ["migrations/009_annotation_operations.sql", "internal/storage/sqlite/annotation_operation.go",
                "internal/transport/http/annotation_operation.go", "docs/plans/FLH-029-annotation-idempotency.md"]
    require(all((ROOT / p).is_file() for p in required), "FLH-029 prerequisite absent")
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths)) if p.is_file() and not p.is_symlink()}


class Verification(Investigation):
    def forward(self, method, path, body, headers):
        if self.harness.mode == "native":
            process = self.harness.process
            require(process is not None and process.poll() is None
                    and owns_listener(process.pid, self.harness.port), "refuse unowned upstream")
        else:
            # Harness.start validates project labels, published port and data mount.
            require(self.harness.compose_started, "container not started/verified")
        conn = http.client.HTTPConnection("127.0.0.1", self.harness.port, timeout=15)
        try:
            conn.request(method, path, body=body or None, headers=headers)
            res = conn.getresponse()
            return res.status, res.getheaders(), res.read()
        finally:
            conn.close()

    def wire(self, method, path, body=None, headers=None, direct=False):
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        port = self.harness.port if direct else self.port
        if direct and self.harness.mode == "native":
            require(self.harness.process is not None and owns_listener(self.harness.process.pid, port), "refuse unowned direct target")
        if direct and self.harness.mode == "container":
            require(self.harness.compose_started, "unverified container")
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=35)
        values = {"Origin": f"http://127.0.0.1:{port}", "Sec-Fetch-Site": "same-origin"}
        if body is not None:
            values["Content-Type"] = "application/json"
        # List headers is used to send actual duplicate header lines.
        pairs = list(values.items()) + list((headers or {}).items()) if isinstance(headers, (dict, type(None))) else list(values.items()) + headers
        try:
            conn.putrequest(method, path)
            for name, value in pairs:
                conn.putheader(name, value)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            res = conn.getresponse()
            raw = res.read().decode()
            return {"status": res.status, "headers": dict(res.getheaders()), "body": json.loads(raw), "raw": raw}
        finally:
            conn.close()

    def passed(self, name, actual):
        self.cases.append({"case": name, "result": "PASS", "actual": actual})
        print("PASS " + name, flush=True)

    @property
    def db(self):
        return self.harness.active / "app.db"

    def unchanged(self, before, counters):
        require(snapshot(self.db) == before, "unexpected persisted write")
        require(self.harness.calls() == counters, "unexpected provider call")

    def counts(self, spec, key):
        table = "unit_concept_distinctions" if spec["operation"] == "distinct" else "unit_concept_links"
        with sqlite3.connect(f"file:{self.db}?mode=ro", uri=True) as conn:
            events = conn.execute(f"SELECT count(*) FROM {table} WHERE unit_id=? AND concept_id=?",
                                  (spec["unit"], spec["a"])).fetchone()[0]
            receipts = conn.execute("SELECT count(*) FROM annotation_operations WHERE id=?", (key,)).fetchone()[0]
        return {"events": events, "receipts": receipts}

    def first_arrival(self, kind, prefix):
        spec = self.fixture(kind, prefix)
        key = str(uuid.uuid4())
        headers = {"Idempotency-Key": key}
        counters = self.harness.calls()
        gate = threading.Barrier(16)
        def submit(_):
            gate.wait(timeout=10)
            return self.wire("POST", spec["path"], spec["body"], headers, direct=True)
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(submit, range(16)))
        require(all(r["status"] == 201 and r["raw"] == results[0]["raw"] for r in results), "first-arrival results diverged")
        require(sum(r["headers"].get("Idempotency-Replayed") != "true" for r in results) == 1, "not exactly one first commit")
        require(self.counts(spec, key) == {"events": 1, "receipts": 1}, "first-arrival duplicate")
        self.harness.replace()
        before = snapshot(self.db)
        receipt = self.api("GET", prefix + "/annotation-operations/" + key)
        replay = self.wire("POST", spec["path"], spec["body"], headers)
        require(receipt["result"] == results[0]["body"] and replay["raw"] == results[0]["raw"], "restart changed result")
        self.unchanged(before, counters)
        self.passed(f"{prefix or 'root'} {kind} first-arrival/restart", {"count": self.counts(spec, key), "responses": results, "receipt": receipt})

    def competing_arrival(self, kind, prefix):
        spec = self.fixture(kind, prefix)
        key = str(uuid.uuid4())
        counters = self.harness.calls()
        gate = threading.Barrier(16)
        def submit(index):
            gate.wait(timeout=10)
            body = spec["body"] | {"concept_id": spec["a"] if index % 2 == 0 else spec["b"]}
            return self.wire("POST", spec["path"], body, {"Idempotency-Key": key}, direct=True)
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(submit, range(16)))
        require(sorted(r["status"] for r in results) == [201]*8 + [409]*8, "competing requests did not select one payload")
        successful = [r for r in results if r["status"] == 201]
        require(all(r["raw"] == successful[0]["raw"] for r in successful), "winner replay changed result")
        table = "unit_concept_distinctions" if kind == "distinct" else "unit_concept_links"
        with sqlite3.connect(f"file:{self.db}?mode=ro", uri=True) as conn:
            events = conn.execute(f"SELECT count(*) FROM {table} WHERE unit_id=?", (spec["unit"],)).fetchone()[0]
            receipts = conn.execute("SELECT count(*) FROM annotation_operations WHERE id=?", (key,)).fetchone()[0]
        require(events == receipts == 1 and self.harness.calls() == counters, "competing requests wrote twice or called provider")
        self.passed(f"{prefix or 'root'} {kind} competing first-arrivals", {"events":events, "receipts":receipts, "responses":results})

    def payload_and_rejection(self, kind, prefix):
        spec = self.fixture(kind, prefix)
        other = self.fixture(kind, prefix)
        key = str(uuid.uuid4())
        headers = {"Idempotency-Key": key}
        original = self.wire("POST", spec["path"], spec["body"], headers)
        require(original["status"] == 201, "initial POST failed")
        before, counters = snapshot(self.db), self.harness.calls()
        alias = "/api" if prefix == "" else ""
        suffix = "/concept-distinctions" if kind == "distinct" else "/concept-links/relation"
        equivalent_path = alias + f"/knowledge-units/000{spec['unit']}" + suffix
        equivalent_body = (f'{{ "concept_id" : {spec["a"]} }}' if kind == "distinct" else
                           f'{{ "relation" : "{kind}", "concept_id" : {spec["a"]} }}').encode()
        replay = self.wire("POST", equivalent_path, equivalent_body, {"Idempotency-Key": key.upper()})
        require(replay["status"] == 201 and replay["raw"] == original["raw"]
                and replay["headers"].get("Idempotency-Replayed") == "true", "normalization mismatch")
        conflicts = [(spec["path"], spec["body"] | {"concept_id": spec["b"]}),
                     (alias + f"/knowledge-units/{other['unit']}" + suffix, spec["body"])]
        alternate = "related" if kind != "related" else "broader"
        conflicts.append((alias + f"/knowledge-units/{spec['unit']}/concept-links/relation",
                          {"concept_id": spec["a"], "relation": alternate}))
        if kind != "distinct":
            conflicts.append((alias + f"/knowledge-units/{spec['unit']}/concept-distinctions", {"concept_id": spec["a"]}))
        responses = []
        for path, body in conflicts:
            response = self.wire("POST", path, body, headers)
            require(response["status"] == 409, "different valid operation did not conflict")
            responses.append(response)
            self.unchanged(before, counters)
        bad_keys = ["", "not-a-uuid", key.replace("-", ""), key + "," + key, "x" * 500, key[:12]]
        for bad in bad_keys:
            result = self.wire("POST", spec["path"], spec["body"], {"Idempotency-Key": bad})
            require(result["status"] == 400 and (not bad or bad not in result["raw"]), "invalid key accepted/leaked")
            self.unchanged(before, counters)
        repeated = self.wire("POST", spec["path"], spec["body"], [("Idempotency-Key", key), ("Idempotency-Key", key)], direct=True)
        require(repeated["status"] == 400, "duplicate header accepted")
        invalid = [b'{', b'null', b'[]', b'{}', b'{"concept_id":null}', b'{"concept_id":0}',
                   b'{"concept_id":1.0}', b'{"concept_id":"1"}', b'{"concept_id":1,"reason":"unexpected"}',
                   json.dumps(spec["body"]).encode() + b' {}', json.dumps(spec["body"]).encode() + b' garbage']
        if kind != "distinct":
            invalid += [json.dumps(spec["body"] | {"relation": value}).encode() for value in (kind.upper(), " " + kind, "same", "", None)]
        for body in invalid:
            invalid_key = str(uuid.uuid4())
            result = self.wire("POST", spec["path"], body, {"Idempotency-Key": invalid_key})
            require(result["status"] == 400, "malformed keyed payload accepted")
            self.api("GET", prefix + "/annotation-operations/" + invalid_key, expected=404)
            self.unchanged(before, counters)
        missing_key = str(uuid.uuid4())
        result = self.wire("POST", spec["path"], spec["body"] | {"concept_id": 999999999}, {"Idempotency-Key": missing_key})
        require(result["status"] == 404, "missing target status")
        self.api("GET", prefix + "/annotation-operations/" + missing_key, expected=404)
        self.unchanged(before, counters)
        self.passed(f"{prefix or 'root'} {kind} normalization/conflicts/validation", {"original": original, "alias_replay": replay, "conflicts": responses, "invalid_keys": len(bad_keys)+1, "malformed_payloads": len(invalid), "table_snapshot_sha256": digest(before)})

    def rollback(self, kind, prefix):
        spec = self.fixture(kind, prefix)
        # A prior event proves a failed relation replacement cannot supersede it.
        prior = self.api("POST", spec["path"], spec["body"], expected=201)
        key = str(uuid.uuid4())
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TRIGGER flh031_fail BEFORE INSERT ON annotation_operations BEGIN SELECT RAISE(ABORT, 'isolated fixture fault'); END")
        before, counters = snapshot(self.db), self.harness.calls()
        before_authority = self.read(spec)
        try:
            result = self.wire("POST", spec["path"], spec["body"], {"Idempotency-Key": key})
            require(result["status"] == 500 and "fixture fault" not in result["raw"], "fault not secret-safe")
            self.unchanged(before, counters)
            self.api("GET", prefix + "/annotation-operations/" + key, expected=404)
            require(self.read(spec) == before_authority, "failed event changed authority")
        finally:
            with sqlite3.connect(self.db) as conn:
                conn.execute("DROP TRIGGER flh031_fail")
        committed = self.api("POST", spec["path"], spec["body"], expected=201, headers={"Idempotency-Key": key})
        require(self.counts(spec, key) == {"events": 2, "receipts": 1}, "rollback retry wrong count")
        if kind != "distinct":
            require(committed["supersedes_link_id"] == prior["id"], "rolled-back event leaked supersession")
        self.passed(f"{prefix or 'root'} {kind} atomic rollback/retry", {"prior": prior, "failure": result, "after_retry": committed, "count": self.counts(spec, key)})

    def authority(self, kind, prefix):
        spec = self.fixture(kind, prefix)
        key = str(uuid.uuid4())
        headers = {"Idempotency-Key": key}
        original = self.api("POST", spec["path"], spec["body"], expected=201, headers=headers)
        later = self.api("POST", spec["path"], spec["body"], expected=201)
        unit_path = prefix + f"/knowledge-units/{spec['unit']}"
        before_same = self.api("GET", unit_path + "/effective-annotation")["snapshot"]["distinctions" if kind == "distinct" else "relations"]
        require(len(before_same) == 1 and before_same[0]["id"] == later["id"], "latest pair projection incorrect before SAME")
        self.api("POST", unit_path + "/concept-links/same", {"concept_id": spec["a"]}, expected=201)
        self.api("POST", prefix + f"/concepts/{spec['a']}/preferred-unit", {"unit_id": spec["unit"]})
        self.api("PUT", unit_path + "/concept-membership", {"concept_id": spec["b"]})
        current = self.read(spec)
        b = self.api("GET", prefix + f"/concepts/{spec['b']}")
        require(current["membership"]["current_membership"]["concept_id"] == spec["b"], "membership authority incorrect")
        require(current["concept_a"]["concept"]["preferred_unit_id"] is None, "invalid preferred unit retained")
        require(current["concept_a"]["concept"]["support_state"] == "orphaned"
                and b["concept"]["support_state"] == "supported", "support authority incorrect")
        projection = current["annotation"]["snapshot"]["distinctions" if kind == "distinct" else "relations"]
        require(projection == [], "historical pair resurrected despite newer affirmative SAME")
        before, counters = snapshot(self.db), self.harness.calls()
        receipt = self.api("GET", prefix + "/annotation-operations/" + key)
        replay = self.api("POST", spec["path"], spec["body"], expected=201, headers=headers)
        require(receipt["result"] == original == replay, "historical result reinterpreted")
        require(self.read(spec) == current and self.api("GET", prefix + f"/concepts/{spec['b']}") == b, "replay rewrote authority")
        self.unchanged(before, counters)
        self.passed(f"{prefix or 'root'} {kind} receipt/current authority separation", {"original": original, "later": later, "before_same_projection": before_same, "receipt": receipt, "current": current, "current_concept_b": b})

    def migration(self):
        require(self.harness.mode == "native", "migration fixture uses native private binaries")
        h = self.harness
        final_server = h.run_dir / "server-final"
        shutil.copy2(h.run_dir / "server", final_server)
        migration = h.source / "migrations/009_annotation_operations.sql"
        saved = h.run_dir / "009_annotation_operations.sql"
        migration.rename(saved)
        try:
            h.command(["go", "build", "-o", str(h.run_dir / "server"), "./cmd/server"])
            h.start()
            require("annotation_operations" not in snapshot(self.db), "legacy fixture unexpectedly has 009")
            fixtures = []
            for kind in KINDS:
                spec = self.fixture(kind, "")
                self.api("POST", spec["path"], spec["body"], expected=201)
                fixtures.append(spec)
            seed = fixtures[0]
            self.api("POST", f"/knowledge-units/{seed['unit']}/concept-links/same", {"concept_id": seed["b"]}, expected=201)
            self.api("POST", f"/concepts/{seed['b']}/preferred-unit", {"unit_id": seed["unit"]})
            before, counters = snapshot(self.db), h.calls()
            views = [self.read(spec) for spec in fixtures]
            catalog = self.api("GET", "/concepts")
            dataset = self.api("GET", "/annotation-dataset/v1")
            h.stop()
        finally:
            saved.rename(migration)
            shutil.copy2(final_server, h.run_dir / "server")
        h.start()
        after = snapshot(self.db)
        require(set(after) - set(before) == {"annotation_operations"} and after["annotation_operations"] == [], "unexpected migration tables/data")
        require({k:v for k,v in before.items() if k != "schema_migrations"} ==
                {k:v for k,v in after.items() if k not in {"schema_migrations", "annotation_operations"}}, "migration rewrote existing records")
        require([self.read(spec) for spec in fixtures] == views and self.api("GET", "/concepts") == catalog
                and self.api("GET", "/annotation-dataset/v1") == dataset, "migration changed projections")
        require(h.calls() == counters, "migration called provider")
        self.passed("008 to 009 migration preserves labels/projections", {"legacy_ledger": before["schema_migrations"], "current_ledger": after["schema_migrations"], "unchanged_tables": sorted(set(before)-{"schema_migrations"}), "projections": views, "catalog": catalog, "dataset": dataset})

    def extra_checks(self):
        for prefix in ("", "/api"):
            for kind in KINDS:
                self.first_arrival(kind, prefix)
                self.competing_arrival(kind, prefix)
                self.payload_and_rejection(kind, prefix)
                self.rollback(kind, prefix)
                self.authority(kind, prefix)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("native", "container"), default="native")
    parser.add_argument("--report", type=Path, required=True, help="new JSON evidence outside repository")
    args = parser.parse_args()
    destination = args.report.resolve()
    require(not destination.exists() and ROOT not in destination.parents and destination.parent.is_dir(), "invalid report destination")
    baseline = inspect_baseline()
    harness_manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for folder in (HERE, HERE.parent / "flh028", HERE.parent / "flh026")
                        for p in sorted(folder.glob("*.py"))}
    os.umask(0o077)
    h = Harness(args.mode)
    # The inherited random suffix may start with '_', yielding an invalid image
    # reference after 'flh026-'. Use a task-owned, Docker-safe project suffix.
    h.project = "flh026-flh031-" + uuid.uuid4().hex
    h.image = h.project + ":local"
    verification = None
    error = None
    cleanup_errors = []
    print(f"FLH031_RUN={h.run_dir} MODE={args.mode} BASELINE={digest(baseline)}", flush=True)
    def interrupted(number, _):
        raise KeyboardInterrupt(f"signal {number}")
    signal.signal(signal.SIGTERM, interrupted)
    try:
        h.prepare()
        verification = Verification(h)
        if args.mode == "native":
            verification.migration()
        else:
            h.start()
        verification.run()  # Existing 128-case FLH-028 matrix, read-only reuse.
        verification.extra_checks()
        require(inspect_baseline() == baseline, "shared baseline changed during verification")
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        print("FAIL " + error, flush=True)
    finally:
        service_log = (h.run_dir / "service.log").read_text()
        if verification:
            try:
                verification.proxy.close()
                verification.thread.join(timeout=3)
                require(not verification.thread.is_alive(), "proxy serve thread did not stop")
            except BaseException as exc:
                cleanup_errors.append(str(exc))
        cleanup_errors.extend(h.cleanup())
        report = {"mode": args.mode, "status": "FAIL" if error or cleanup_errors else "PASS", "error": error,
                  "baseline_sha256": digest(baseline), "baseline_manifest": baseline,
                  "source_sha256": getattr(h, "manifest", {}), "source_inventory_sha256": digest(getattr(h, "manifest", {})),
                  "cases": verification.cases if verification else [], "commands": h.commands,
                  "harness_manifest": harness_manifest,
                  "cleanup_errors": cleanup_errors, "temporary_directory_removed": not h.run_dir.exists(), "service_log": service_log,
                  "limits": ["Author verification, not independent review", "No real browser/DOM evidence", "No power-loss/disk failure injection", "Migration-upgrade probe native only"]}
        with destination.open("x") as output:
            json.dump(report, output, indent=2)
        print(f"RESULT={report['status']} CASES={len(report['cases'])} CLEANUP={'FAIL' if cleanup_errors else 'PASS'}", flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
