#!/usr/bin/env python3
"""FLH-084 local end-to-end test of deploy/aws/host/flh-release.

Runs the host tool unprivileged against a temporary root with two fakes:
`aws` copies objects from a local directory standing in for the bucket, and
`systemctl` starts the package's own flh-server with the exact environment of
the rendered unit (loopback, providers disabled, empty HTTP_ALLOWED_HOSTS).
The input is an existing CANDIDATE tarball (FLH-081 rc1), which is only read;
renamed copies give a second release and a deliberately broken one.

    python3 -B scripts/validation/flh084/release_tool_test.py \
        --tarball ~/flh081/release/flh-public-demo-flh081-rc1.tar.gz --work DIR [--port 18996]
No AWS call, no network beyond 127.0.0.1, no Git.
"""
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TOOL = os.path.join(REPO, "deploy", "aws", "host", "flh-release")
BUCKET = "flh-demo-artifacts-test"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok or not detail else f"  [{detail}]"), flush=True)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def make_writable(path):
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            p = os.path.join(root, n)
            if not os.path.islink(p):
                os.chmod(p, os.stat(p).st_mode | stat.S_IWUSR)
    os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)


def http(port, path, method="GET", host=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tarball", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--port", type=int, default=18996)
    a = ap.parse_args()
    src = os.path.abspath(os.path.expanduser(a.tarball))
    base = os.path.basename(src)[: -len(".tar.gz")]
    work = os.path.abspath(a.work)
    if os.path.exists(work):
        make_writable(work)
        shutil.rmtree(work)
    s3, root, fakes = (os.path.join(work, d) for d in ("s3", "root", "fakes"))
    for d in (os.path.join(s3, BUCKET, "releases"), root, fakes):
        os.makedirs(d)

    # Bucket contents: the original, a renamed copy (second release), a renamed
    # copy the fake systemctl refuses to start (failed identity), a traversal tarball.
    def put(name, from_dir=None):
        dst = os.path.join(s3, BUCKET, "releases", name + ".tar.gz")
        if from_dir is None:
            shutil.copyfile(src, dst)
        else:
            with tarfile.open(dst, "w:gz") as t:
                t.add(from_dir, arcname=name)
        return dst
    stage = os.path.join(work, "stage")
    with tarfile.open(src) as t:
        t.extractall(stage, filter="data")
    put(base)
    second, broken = base + "b", base + "broken"
    put(second, os.path.join(stage, base))
    put(broken, os.path.join(stage, base))
    evil = os.path.join(s3, BUCKET, "releases", "flh-public-demo-evil.tar.gz")
    with tarfile.open(evil, "w:gz") as t:
        info = tarfile.TarInfo("../escape")
        info.size = 0
        t.addfile(info)
    with tarfile.open(os.path.join(s3, BUCKET, "releases", "flh-public-demo-x-BLOCKED.tar.gz"), "w:gz"):
        pass
    hashes = {n: sha(os.path.join(s3, BUCKET, "releases", n + ".tar.gz")) for n in (base, second, broken)}

    with open(os.path.join(fakes, "aws"), "w") as f:
        f.write(f"""#!/bin/sh
# fake: aws s3 cp --only-show-errors s3://BUCKET/KEY DEST --region REGION
[ "$1 $2 $3 $6 $7" = "s3 cp --only-show-errors --region test-region-1" ] || {{ echo "fake aws: unexpected $*" >&2; exit 2; }}
key=${{4#s3://}}
cp "{s3}/$key" "$5"
""")
    unit_env = (f"LISTEN_HOST=127.0.0.1 PORT={a.port} AI_PROVIDER=rule-based EXTRACTOR_PROVIDER=disabled "
                "EMBEDDING_PROVIDER=disabled SEMANTIC_SEARCH=disabled HTTP_ALLOWED_HOSTS=")
    with open(os.path.join(fakes, "systemctl"), "w") as f:
        f.write(f"""#!/bin/sh
# fake systemctl for flh-public-demo.service: runs the selected release's server.
PID={work}/server.pid
stop() {{ [ -f $PID ] && kill "$(cat $PID)" 2>/dev/null; sleep 0.3; rm -f $PID; }}
case "$1" in
  enable) exit 0 ;;
  stop) stop ;;
  is-active) [ -f $PID ] && kill -0 "$(cat $PID)" 2>/dev/null && echo active || {{ echo inactive; exit 3; }} ;;
  restart)
    stop
    cur=$(readlink {root}/current)
    case "$cur" in *broken) exit 0 ;; esac
    cd {root}/current || exit 1
    env -i PATH=/usr/bin:/bin {unit_env} {root}/current/bin/linux-amd64/flh-server \\
      -public-demo-artifact {root}/current/artifact -web-dir {root}/current/web >> {work}/server.log 2>&1 &
    echo $! > $PID ;;
  *) echo "fake systemctl: $*" >&2; exit 2 ;;
esac
""")
    for n in ("aws", "systemctl"):
        os.chmod(os.path.join(fakes, n), 0o755)
    config = os.path.join(work, "deploy.env")
    with open(config, "w") as f:
        f.write(f"ROOT={root}\nPORT={a.port}\nARCH=amd64\nREGION=test-region-1\nARTIFACT_BUCKET={BUCKET}\n")
    env = dict(os.environ, FLH_CONFIG=config, FLH_AWS=os.path.join(fakes, "aws"),
               FLH_SYSTEMCTL=os.path.join(fakes, "systemctl"), FLH_ALLOW_NONROOT="1",
               FLH_OWNER=f"{os.getuid()}:{os.getgid()}", FLH_HEALTH_TIMEOUT="10")

    def run(*args):
        p = subprocess.run([TOOL, *args], env=env, capture_output=True, text=True, timeout=300)
        return p.returncode, p.stdout + p.stderr

    def uri(n):
        return f"s3://{BUCKET}/releases/{n}.tar.gz"

    def current():
        return os.path.basename(os.readlink(os.path.join(root, "current"))) if os.path.islink(os.path.join(root, "current")) else None

    def serving(name):
        st, body = http(a.port, "/knowledge-library/demo")
        rel = json.load(open(os.path.join(root, "releases", name, "RELEASE.json")))
        return st == 200 and json.loads(body)["artifact"]["manifest_sha256"] == rel["artifact"]["manifest_sha256"]

    try:
        # Refusals before anything is installed.
        rc, out = run("install", uri(base), "0" * 64)
        check("wrong expected SHA-256 refused", rc != 0 and "expected" in out and current() is None, out[-300:])
        rc, out = run("install", uri(base), hashes[base].upper())
        check("non-lowercase hash refused (exit 2)", rc == 2, out[-200:])
        rc, out = run("install", f"s3://other-bucket/releases/{base}.tar.gz", hashes[base])
        check("object outside ARTIFACT_BUCKET/releases/ refused", rc == 2 and "refused" in out, out[-200:])
        rc, out = run("install", uri("flh-public-demo-x-BLOCKED"), "a" * 64)
        check("BLOCKED package name refused", rc != 0 and "BLOCKED" in out, out[-200:])
        rc, out = run("install", uri("flh-public-demo-evil"), sha(evil))
        check("path-traversal tarball refused", rc != 0 and "unsafe" in out and not os.path.exists(os.path.join(root, "escape")), out[-200:])
        check("no partial release or incoming dir left behind",
              os.listdir(os.path.join(root, "releases")) == [] and not [d for d in os.listdir(root) if d.startswith(".incoming")])
        rc, out = run("status")
        check("status with nothing selected exits 3", rc == 3, out[-200:])

        # First install.
        rc, out = run("install", uri(base), hashes[base])
        check("install rc1: success", rc == 0 and "(match)" in out, out[-600:])
        check("current -> rc1 and server reports rc1 identity", current() == base and serving(base))
        rel = os.path.join(root, "releases", base)
        check("installed release is read-only", not os.access(os.path.join(rel, "RELEASE.json"), os.W_OK)
              and not (os.stat(rel).st_mode & 0o222))
        st, _ = http(a.port, "/readyz")
        check("/readyz 200", st == 200)
        st, _ = http(a.port, "/", host=f"localhost:{a.port}")
        check("workbench / served for Host localhost:<port> with empty HTTP_ALLOWED_HOSTS (SSM preview)", st == 200)
        st, _ = http(a.port, "/knowledge-library/concepts?q=avoir", host=f"127.0.0.1:{a.port}")
        check("keyword search 200 over loopback", st == 200)
        st, _ = http(a.port, "/entries")
        check("non-demo route /entries is 404 (allowlist preserved)", st == 404)
        st, _ = http(a.port, "/knowledge-library/concepts", method="POST")
        check("POST is 405 (read-only boundary preserved)", st == 405)
        st, _ = http(a.port, "/healthz", host="demo.example.org")
        check("non-loopback Host refused while public exposure is frozen", st in (400, 403, 421), st)

        # Failed identity -> automatic rollback.
        rc, out = run("install", uri(broken), hashes[broken])
        check("install of a release that never becomes ready fails", rc != 0 and "not ready" in out, out[-400:])
        check("automatic rollback restored rc1 and it serves", current() == base and serving(base))

        # Second release, then explicit rollback.
        rc, out = run("install", uri(second), hashes[second])
        check("install second release: success", rc == 0 and current() == second and serving(second), out[-400:])
        rc, out = run("install", uri(base), hashes[second])
        check("same name with different bytes refused (immutability)", rc != 0 and "different" in out and current() == second, out[-300:])
        rc, out = run("rollback")
        check("rollback -> rc1 serving", rc == 0 and current() == base and serving(base), out[-400:])
        rc, out = run("rollback")
        check("rollback again -> second release (previous swaps)", rc == 0 and current() == second and serving(second), out[-400:])
        rc, out = run("install", uri(base), hashes[base])
        check("re-selecting an installed release with the same hash", rc == 0 and "re-selecting" in out and current() == base, out[-300:])

        rc, out = run("status")
        check("status reports hash, source revision, artifact and live match",
              rc == 0 and hashes[base] in out and "source rev:" in out and "(match)" in out, out[-500:])
        log = open(os.path.join(root, "state", "deployments.log")).read().splitlines()
        actions = [l.split("\t")[1:3] + [l.split("\t")[6]] for l in log]
        check("deployment log records every switch with result", actions == [
            ["install", base, "ok"], ["install", broken, "failed"], ["auto-rollback", base, "ok"],
            ["install", second, "ok"], ["rollback", base, "ok"], ["rollback", second, "ok"], ["install", base, "ok"]], actions)
        check("log lines carry tarball hash and source revision", hashes[base] in log[0] and len(log[0].split("\t")) == 7)
    finally:
        subprocess.run([os.path.join(fakes, "systemctl"), "stop"], capture_output=True)
        time.sleep(0.3)
        make_writable(work)
        shutil.rmtree(work)
    failed = [n for n, ok in results if not ok]
    print(f"release tool test: {len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
