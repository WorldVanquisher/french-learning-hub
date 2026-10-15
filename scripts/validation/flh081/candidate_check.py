#!/usr/bin/env python3
"""FLH-081 offline validation of a public-demo release CANDIDATE tarball on Linux.

    unshare -rn python3 -B scripts/validation/flh081/candidate_check.py \
        --tarball /abs/flh-public-demo-NAME.tar.gz --work "/abs/new work dir" \
        --revision LABEL --artifact-version VERSION [--port 18981]

Run from the repository root (for scripts/demo/flh076/smoke_package.sh) inside
`unshare -rn`. That is an unprivileged user and network namespace with only
loopback, so the packaged server has no route to the encoder or to any other
host. Steps:

  1. namespace: bring `lo` up and record the interfaces and routes; require
     no non-loopback interface and no route; check that the encoder base_url
     named in RELEASE.json is unreachable (no route, so nothing is sent)
  2. the tarball's .sha256; extract into WORK/"install root"; make it read-only
  3. the packaged validate-release.sh: exit 0, CANDIDATE
  4. RELEASE.json: CANDIDATE, the expected revision label and artifact version,
     real model
  5. the existing FLH-076 smoke_package.sh against the package, unchanged
  6. the package's own deploy/ctl.sh starts the PACKAGED native binary, then:
     - artifact identity from /knowledge-library/demo;
     - root and /api routes;
     - keyword search;
     - every preset in semantic mode and representative hybrid presets;
     - every Concept, and the original question behind every supporting unit
       compared with the artifact's own fixtures.json;
     - denied writes, free-text and private-file routes
  7. stop and restart through ctl.sh: identical responses, counters reset
  8. final stop, port closed, package bytes unchanged

The candidate is never modified. Results go to WORK/results.tsv and
WORK/summary.json. Exit 0 only if no check FAILED.
"""

import argparse
import hashlib
import http.client
import json
import os
import socket
import stat
import subprocess
import sys
import tarfile
import time

REPO = os.getcwd()
SMOKE = os.path.join(REPO, "scripts", "demo", "flh076", "smoke_package.sh")
FIXTURE_EXTRACTOR = "fixture:flh073:knowledge_extraction_v1"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def tree_hash(root):
    h = hashlib.sha256()
    for dirpath, dirs, files in sorted(os.walk(root)):
        dirs.sort()
        for n in sorted(files):
            p = os.path.join(dirpath, n)
            h.update(os.path.relpath(p, root).encode() + b"\0" + sha256(p).encode() + b"\n")
    return h.hexdigest()


class Check:
    def __init__(self, a):
        self.a = a
        self.work = a.work
        self.results = []
        self.port = a.port

    def rec(self, status, name, detail=""):
        self.results.append({"status": status, "check": name, "detail": str(detail)[:300]})
        line = f"{status}\t{name}\t{detail}"
        print(line, flush=True)
        with open(os.path.join(self.work, "results.tsv"), "a") as f:
            f.write(line + "\n")

    def check(self, name, ok, detail=""):
        self.rec("PASS" if ok else "FAIL", name, detail)
        return ok

    def http(self, method, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            body = b"{}" if method in ("POST", "PUT", "PATCH", "DELETE") else None
            c.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()

    def get(self, path):
        st, body = self.http("GET", path)
        if st != 200:
            raise RuntimeError(f"GET {path} -> {st}")
        return json.loads(body)

    def expect(self, method, path, want):
        try:
            got = self.http(method, path)[0]
        except OSError as e:
            got = f"error {e}"
        self.check(f"{method} {path} -> {want}", got == want, got)

    def ctl(self, action, run):
        env = {**os.environ, "PORT": str(self.port)}
        r = subprocess.run([os.path.join(self.pkg, "deploy", "ctl.sh"), action, run], env=env,
                           capture_output=True, text=True, timeout=90)
        with open(os.path.join(self.work, "ctl.log"), "a") as f:
            f.write(f"$ ctl.sh {action}\n{r.stdout}{r.stderr}rc={r.returncode}\n")
        return r.returncode, r.stdout + r.stderr

    def port_open(self):
        s = socket.socket()
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", self.port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    # ---- steps -----------------------------------------------------------
    def namespace(self):
        subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
        addr = subprocess.run(["ip", "-brief", "addr"], capture_output=True, text=True).stdout
        routes = (subprocess.run(["ip", "route"], capture_output=True, text=True).stdout
                  + subprocess.run(["ip", "-6", "route"], capture_output=True, text=True).stdout)
        with open(os.path.join(self.work, "netns.txt"), "w") as f:
            f.write(f"# ip -brief addr\n{addr}# ip route; ip -6 route\n{routes}")
        ifaces = [l.split()[0] for l in addr.splitlines() if l.strip()]
        self.check("namespace has only loopback", ifaces == ["lo"], ifaces)
        non_lo = [l for l in routes.splitlines() if l.strip() and " lo " not in f" {l} " and not l.startswith(("local", "::1"))]
        self.check("namespace has no route off the host", not non_lo, non_lo)

    def unpack(self):
        tb = self.a.tarball
        want = open(tb + ".sha256").read().split()[0]
        self.check("tarball .sha256", sha256(tb) == want, want)
        inst = os.path.join(self.work, "install root")
        os.makedirs(inst)
        with tarfile.open(tb) as t:
            names = t.getnames()
            self.check("tarball members are relative and one directory",
                       all(not n.startswith("/") and ".." not in n.split("/") for n in names)
                       and len({n.split("/")[0] for n in names}) == 1)
            t.extractall(inst, filter="data")
        self.pkg = os.path.join(inst, names[0].split("/")[0])
        for dirpath, dirs, files in os.walk(self.pkg):
            for n in files + dirs:
                p = os.path.join(dirpath, n)
                os.chmod(p, os.stat(p).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        os.chmod(self.pkg, 0o555)
        self.tree0 = tree_hash(self.pkg)

    def release(self):
        r = subprocess.run([os.path.join(self.pkg, "validate-release.sh")], capture_output=True, text=True,
                           cwd=self.work, timeout=120)
        self.check("validate-release.sh exit 0 CANDIDATE", r.returncode == 0 and r.stdout.startswith("CANDIDATE"),
                   (r.stdout + r.stderr).strip()[-200:])
        rel = json.load(open(os.path.join(self.pkg, "RELEASE.json")))
        self.rel = rel
        a = rel["artifact"]
        self.check("RELEASE.json status CANDIDATE", rel["release_status"] == "CANDIDATE")
        self.check("RELEASE.json source_revision is the supplied label", rel["source_revision"] == self.a.revision,
                   rel["source_revision"])
        self.check("RELEASE.json artifact version", a["version"] == self.a.artifact_version, a["version"])
        self.check("RELEASE.json real model vectors", a["real_model"] is True and a["vector_source"] == "model"
                   and rel["model_provenance"]["deployment_id"] == a["model_id"], a["model_id"])
        base = (rel.get("model_provenance") or {}).get("base_url", "")
        if base:
            host = base.split("//", 1)[1].split("/", 1)[0]
            h, _, p = host.partition(":")
            s = socket.socket()
            s.settimeout(2)
            try:
                s.connect((h, int(p or 80)))
                reachable = True
            except OSError as e:
                reachable, why = False, e
            finally:
                s.close()
            self.check("encoder named in RELEASE.json unreachable from the namespace", not reachable,
                       f"{host}: {why if not reachable else 'CONNECTED'}")

    def smoke(self):
        r = subprocess.run(["bash", SMOKE, self.pkg, os.path.join(self.work, "smoke run"), str(self.port + 1)],
                           capture_output=True, text=True, timeout=300)
        with open(os.path.join(self.work, "smoke.log"), "w") as f:
            f.write(r.stdout + r.stderr)
        self.check("FLH-076 smoke_package.sh", r.returncode == 0, (r.stdout.strip().splitlines() or [""])[-1])

    def serve(self):
        run = os.path.join(self.work, "runtime dir")
        rc, out = self.ctl("start", run)
        self.check("ctl.sh start (packaged native binary)", rc == 0 and "started" in out, out.strip()[-200:])
        pid = open(os.path.join(run, "flh-public-demo.pid")).read().strip()
        argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")[0].decode()
        self.check("server process is the packaged linux-amd64 binary",
                   argv == os.path.join(self.pkg, "bin", "linux-amd64", "flh-server"), argv)
        info = self.get("/knowledge-library/demo")
        a = info["artifact"]
        self.check("served identity: version, manifest SHA-256, model, real_model",
                   a["version"] == self.a.artifact_version
                   and a["manifest_sha256"] == sha256(os.path.join(self.pkg, "artifact", "manifest.json"))
                   and a["model_id"] == self.rel["artifact"]["model_id"] and a["real_model"] is True
                   and a["vector_source"] == "model" and a["dimensions"] == 768,
                   json.dumps({k: a.get(k) for k in ("version", "vector_source", "real_model", "release_status")}))
        self.check("counters start at zero", info["counters"] == {"preset_vector_lookups": 0, "refused_vector_lookups": 0})
        fx = json.load(open(os.path.join(self.pkg, "artifact", "fixtures.json")))
        presets = {p["id"]: p["text"] for p in info["presets"]}
        self.check("presets equal the artifact fixtures", presets == {p["id"]: p["text"] for p in fx["presets"]})
        for prefix in ("", "/api"):
            for p in ("/", "/healthz", "/readyz", "/knowledge-library/demo"):
                if prefix and p == "/":
                    continue
                self.expect("GET", prefix + p, 200)
        r = self.get("/api/knowledge-library/concepts?q=subj")
        self.check("keyword search 'subj'", r["total_matches"] >= 2 and any("subjunctive" in x["concept"]["target"]
                                                                          for x in r["results"]), r["total_matches"])
        calls = 0
        for pid_, text in presets.items():
            s = self.get(f"/api/knowledge-library/demo/semantic-search?preset={pid_}")
            calls += 1
            self.check(f"semantic preset {pid_}", s["query"] == text and s["results"]
                       and s["index"]["model_id"] == self.rel["artifact"]["model_id"] and s["skipped"]["stale"] == 0,
                       f"top: {s['results'][0]['concept']['target'] if s['results'] else None}")
        for q in ("subjunctive&state=active", "miss-someone", "still-going-on"):
            h = self.get(f"/api/knowledge-library/demo/hybrid-search?preset={q}")
            calls += 1
            self.check(f"hybrid preset {q}", h["policy"]["version"] == "concept_hybrid_rrf_v1" and h["results"],
                       f"top: {h['results'][0]['concept']['target']}")
        info = self.get("/knowledge-library/demo")
        self.check("each preset search used one cached vector, none refused",
                   info["counters"] == {"preset_vector_lookups": calls, "refused_vector_lookups": 0}, info["counters"])
        by_stmt = {u["statement"]: e for e in fx["entries"] for u in e["units"]}
        browse = self.get("/api/knowledge-library/concepts")
        ids = sorted(x["concept"]["id"] for x in browse["results"])
        self.check("every fixture Concept listed", len(ids) == len(fx["concepts"]), len(ids))
        sources = []
        for cid in ids:
            d = self.get(f"/api/knowledge-library/concepts/{cid}")
            for u in d["supporting_units"]:
                s = self.get(f"/api/knowledge-library/units/{u['unit_id']}/source")
                e = by_stmt.get(u["statement"], {})
                sources.append(u["unit_id"])
                self.check(f"Concept {cid} unit {u['unit_id']}: original question provenance",
                           s["entry"]["original_input"] == e.get("original_input")
                           and s["entry"]["original_context"] == e.get("original_context")
                           and s["extraction"]["extractor"] == FIXTURE_EXTRACTOR
                           and s["annotation"]["current_concept_id"] == cid, s["entry"]["original_input"])
        n_units = sum(len(e["units"]) for e in fx["entries"])
        self.check("every fixture unit's source checked", len(sources) == n_units, f"{len(sources)}/{n_units}")
        for m in ("POST", "PUT", "PATCH", "DELETE"):
            for p in ("/entries", "/captures", "/concepts", "/api/knowledge-library/concepts",
                      "/api/knowledge-units/1/concept-links/same"):
                self.expect(m, p, 405)
        for p in ("/knowledge-library/semantic-search?q=x", "/api/knowledge-library/hybrid-search?q=x", "/api/entries",
                  "/inventory", "/retrieval-comparison/v1", "/annotation-dataset/v1/export"):
            self.expect("GET", p, 404)
        self.expect("GET", "/api/knowledge-library/demo/semantic-search?q=free+text", 400)
        self.expect("GET", "/api/knowledge-library/demo/hybrid-search?preset=miss-someone&q=x", 400)
        for p in ("/artifact/demo.db", "/demo.db", "/RELEASE.json", "/SHA256SUMS", "/artifact/provenance.json",
                  "/deploy/ctl.sh", "/assets/../artifact/demo.db", "/assets/"):
            st, body = self.http("GET", p)
            self.check(f"private file {p} not served", st == 404 and b"SQLite format 3" not in body, st)
        self.snapshot_paths = (["/api/knowledge-library/concepts", "/api/knowledge-library/concepts?q=subj"]
                               + [f"/api/knowledge-library/concepts/{i}" for i in ids]
                               + [f"/api/knowledge-library/units/{u}/source" for u in sources]
                               + [f"/api/knowledge-library/demo/semantic-search?preset={p}" for p in presets]
                               + ["/api/knowledge-library/demo/hybrid-search?preset=subjunctive&state=active"])
        snap1 = {p: self.http("GET", p)[1] for p in self.snapshot_paths}
        rc, out = self.ctl("stop", run)
        self.check("ctl.sh stop", rc == 0 and not self.port_open(), out.strip())
        self.check("server process gone after stop", not os.path.exists(f"/proc/{pid}"), pid)
        rc, out = self.ctl("start", run)
        self.check("ctl.sh restart", rc == 0, out.strip()[-200:])
        info = self.get("/knowledge-library/demo")
        self.check("restart: counters reset (no state persisted)", info["counters"]["preset_vector_lookups"] == 0)
        snap2 = {p: self.http("GET", p)[1] for p in self.snapshot_paths}
        diff = [p for p in self.snapshot_paths if snap1[p] != snap2[p]]
        self.check("restart: responses byte-identical", not diff, f"{len(snap2)} compared; differing {diff[:3]}")
        rc, out = self.ctl("stop", run)
        self.check("final ctl.sh stop, port closed", rc == 0 and not self.port_open(), out.strip())
        self.check("package bytes unchanged", tree_hash(self.pkg) == self.tree0)
        self.check("no SQLite side files", not any(os.path.exists(os.path.join(self.pkg, "artifact", "demo.db" + s))
                                                   for s in ("-wal", "-shm", "-journal")))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--tarball", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--artifact-version", required=True)
    p.add_argument("--port", type=int, default=18981)
    a = p.parse_args()
    if not os.path.isfile(SMOKE):
        print("run from the repository root", file=sys.stderr)
        return 2
    if not os.path.isabs(a.work) or os.path.lexists(a.work):
        print("refused: --work must be a new absolute path", file=sys.stderr)
        return 2
    os.makedirs(a.work)
    c = Check(a)
    try:
        c.namespace()
        c.unpack()
        c.release()
        c.smoke()
        c.serve()
    except Exception as e:  # a harness error is a FAIL
        c.rec("FAIL", "harness completed", f"{type(e).__name__}: {e}")
        if hasattr(c, "pkg"):
            c.ctl("stop", os.path.join(a.work, "runtime dir"))
    finally:
        if hasattr(c, "pkg"):  # leave the extracted copy removable
            for dirpath, dirs, _ in os.walk(c.pkg):
                os.chmod(dirpath, os.stat(dirpath).st_mode | stat.S_IWUSR)
    counts = {k: sum(r["status"] == k for r in c.results) for k in ("PASS", "FAIL")}
    with open(os.path.join(a.work, "summary.json"), "w") as f:
        json.dump({"schema": "flh081_candidate_check_v1", "tarball": a.tarball, "tarball_sha256": sha256(a.tarball),
                   "counts": counts, "failed": [r for r in c.results if r["status"] == "FAIL"]}, f, indent=2)
        f.write("\n")
    print(json.dumps(counts))
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
