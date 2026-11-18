"""Shared helpers for the local stand-in rehearsals of the private staging host.

A "host" here is a directory laid out like /srv/flh-staging on the EC2 host
(bundles/, transfer/, data/app, staging.env, current, previous). The host tool
(host/flh-staging-bundle) and the bundle's own flh-daily.sh run against it
unchanged; only S3 (a tar + SHA-256 copy) and SSM (a parameters JSON read by
the same renderer) are replaced. Every Compose project is flh-stg-<run>-<name>
on a free loopback port; the daily project, image and data are never touched
(a fingerprint is compared before and after). No provider is configured.
"""
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

REHEARSAL = os.path.dirname(os.path.abspath(__file__))
STAGING = os.path.dirname(REHEARSAL)
BUNDLE_TOOL = os.path.join(STAGING, "host", "flh-staging-bundle")
RENDER_ENV = os.path.join(STAGING, "host", "flh-staging-env")
RUN = time.strftime("%Y%m%d%H%M%S", time.gmtime())
DAILY_CONTAINER = "french-learning-hub-app-1"
DAILY_IMAGE = "french-learning-hub:local"


class Recorder:
    def __init__(self, work):
        if os.path.exists(work):
            sys.exit(f"refused: {work} exists")
        self.work = os.path.realpath(work)
        self.evidence = os.path.join(self.work, "evidence")
        os.makedirs(self.evidence)
        self.results = os.path.join(self.work, "results.tsv")
        self.failed = 0
        self.timings = {}

    def record(self, step, ok, expected, actual):
        self.failed += 0 if ok else 1
        line = f"{step}\t{'PASS' if ok else 'FAIL'}\t{expected}\t{actual}"
        print(line, flush=True)
        with open(self.results, "a") as fh:
            fh.write(line + "\n")
        return ok

    def note(self, step, text):
        print(f"{step}\tNOTE\t{text}", flush=True)
        with open(self.results, "a") as fh:
            fh.write(f"{step}\tNOTE\t{text}\t\n")

    def time(self, name, seconds):
        self.timings[name] = round(seconds, 2)
        with open(os.path.join(self.work, "timings.json"), "w") as fh:
            json.dump(self.timings, fh, indent=1, sort_keys=True)

    def save(self, name, text):
        with open(os.path.join(self.evidence, name), "w") as fh:
            fh.write(text if isinstance(text, str) else json.dumps(text, indent=1, ensure_ascii=False))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def daily_fingerprint():
    out = []
    for args in (["docker", "inspect", "-f", "{{.Id}} {{.Image}} {{.State.StartedAt}} {{.State.Status}}", DAILY_CONTAINER],
                 ["docker", "image", "inspect", "-f", "{{.Id}}", DAILY_IMAGE]):
        r = subprocess.run(args, capture_output=True, text=True)
        out.append(r.stdout.strip() or f"absent ({r.returncode})")
    return "\n".join(out)


def call(port, method, path, body=None, headers=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if data is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        return None, str(e).encode()


def js(raw):
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def wait_ready(port, secs=90):
    end = time.time() + secs
    while time.time() < end:
        if call(port, "GET", "/readyz", timeout=5)[0] == 200:
            return True
        time.sleep(0.5)
    return False


def dump_hash(db):
    r = subprocess.run(["sqlite3", "-readonly", db, ".dump"], capture_output=True)
    return hashlib.sha256(r.stdout).hexdigest() if r.returncode == 0 else None


def table_counts(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: con.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] for n in names}
    finally:
        con.close()


def ledger(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
    finally:
        con.close()


def transfer(src, work, name):
    """The S3 hop: tar the source, record its SHA-256, copy, verify on arrival, unpack."""
    tdir = os.path.join(work, "s3")
    os.makedirs(tdir, exist_ok=True)
    tar = os.path.join(tdir, f"{name}.tar")
    with tarfile.open(tar, "w") as tf:
        tf.add(src, arcname=name)
    digest = sha256(tar)
    return tar, digest


def fetch(tar, digest, dest_dir):
    """Host side of the S3 hop: copy into transfer/, check the SHA-256, unpack."""
    os.makedirs(dest_dir, exist_ok=True)
    arrived = os.path.join(dest_dir, os.path.basename(tar))
    shutil.copyfile(tar, arrived)
    ok = sha256(arrived) == digest
    with tarfile.open(arrived) as tf:
        kw = {"filter": "tar"} if hasattr(tarfile, "data_filter") else {}
        tf.extractall(dest_dir, **kw)
    return ok, os.path.join(dest_dir, os.path.basename(tar)[:-4])


PARAMS = [("AI_PROVIDER", "rule-based"), ("EXTRACTOR_PROVIDER", "disabled"), ("SUGGESTION_PROVIDER", "disabled"),
          ("LISTENING_PROVIDER", "disabled"), ("READING_PROVIDER", "disabled"), ("WRITING_PROVIDER", "disabled"),
          ("SPEAKING_TRANSCRIPTION_PROVIDER", "disabled"), ("SPEAKING_PROVIDER", "disabled"),
          ("HTTP_WRITE_TIMEOUT", "75"), ("LISTENING_PLAYLIST_SOURCE", "disabled"),
          ("LISTENING_AUTO_PREPARE", "disabled"), ("LISTENING_NOTIFY", "disabled")]


class Host:
    """One stand-in staging host: the /srv/flh-staging layout under WORK/host-<name>."""

    def __init__(self, rec, name):
        self.rec, self.name = rec, name
        self.root = os.path.join(rec.work, f"host-{name}")
        self.data = os.path.join(self.root, "data", "app")
        os.makedirs(self.data)
        os.chmod(os.path.join(self.root, "data"), 0o700)
        os.chmod(self.data, 0o700)
        for d in ("bundles", "transfer"):
            os.makedirs(os.path.join(self.root, d))
        self.env_file = os.path.join(self.root, "staging.env")
        self.project = f"flh-stg-{RUN}-{name}"
        self.port = free_port()

    def env(self):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("COMPOSE_", "DOCKER_HOST"))}
        e.update(FLH_STAGING_ROOT=self.root, FLH_STAGING_ENV=self.env_file, FLH_STAGING_PROJECT=self.project)
        return e

    def render_settings(self):
        params = {"Parameters": [{"Name": f"/flh/staging/{k}", "Value": v} for k, v in
                                 [("FLH_DATA_DIR", self.data), ("FLH_HOST_PORT", str(self.port)),
                                  ("FLH_UID", str(os.getuid())), ("FLH_GID", str(os.getgid()))] + PARAMS]}
        pj = os.path.join(self.rec.work, f"ssm-{self.name}.json")
        with open(pj, "w") as fh:
            json.dump(params, fh)
        os.chmod(pj, 0o600)
        r = subprocess.run(["bash", RENDER_ENV, "us-east-1", "/flh/staging", self.env_file],
                           env=dict(os.environ, FLH_STAGING_PARAMS_JSON=pj), capture_output=True, text=True)
        self.rec.save(f"{self.name}-render-settings.txt", r.stdout + r.stderr)
        mode = stat.S_IMODE(os.stat(self.env_file).st_mode) if os.path.exists(self.env_file) else None
        return r.returncode == 0 and mode == 0o600, mode

    def tool(self, *args, log=None, timeout=600):
        t0 = time.time()
        r = subprocess.run([sys.executable, "-I", BUNDLE_TOOL, *args], env=self.env(), capture_output=True, text=True,
                           timeout=timeout)
        secs = time.time() - t0
        text = r.stdout + r.stderr
        self.rec.save(f"{self.name}-{log or args[0]}.log", f"$ flh-staging-bundle {' '.join(args)}\nexit {r.returncode} ({secs:.1f} s)\n{text}")
        return r.returncode, text, secs

    def current(self):
        p = os.path.join(self.root, "current")
        return os.path.realpath(p) if os.path.islink(p) else None

    def stg(self, *args, log=None, bundle=None, extra_env=None, preexec=None):
        b = bundle or self.current()
        e = self.env()
        e.update(FLH_DAILY_ENV=self.env_file, FLH_COMPOSE_PROJECT=self.project,
                 FLH_COMPOSE_OVERRIDE=os.path.join(b, "staging.override.yaml"))
        e.update(extra_env or {})
        t0 = time.time()
        r = subprocess.run(["bash", os.path.join(b, "repo", "scripts", "daily", "flh-daily.sh"), *args], env=e,
                           capture_output=True, text=True, preexec_fn=preexec)
        secs = time.time() - t0
        self.rec.save(f"{self.name}-{log or args[0]}.log", f"$ flh-daily.sh {' '.join(args)}\nexit {r.returncode} ({secs:.1f} s)\n{r.stdout}{r.stderr}")
        return r.returncode, r.stdout + r.stderr, secs

    def call(self, method, path, body=None, headers=None):
        return call(self.port, method, path, body, headers)

    def ready(self, secs=90):
        return wait_ready(self.port, secs)

    def container(self):
        r = subprocess.run(["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={self.project}",
                            "--filter", "label=com.docker.compose.service=app"], capture_output=True, text=True)
        ids = r.stdout.split()
        return ids[0] if ids else None

    def running_image(self):
        c = self.container()
        if not c:
            return None
        return subprocess.run(["docker", "inspect", "-f", "{{.Image}}", c], capture_output=True, text=True).stdout.strip()

    def down(self):
        b = self.current()
        e = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
        if b and os.path.exists(self.env_file):
            subprocess.run(["docker", "compose", "-p", self.project, "-f", os.path.join(b, "repo", "compose.yaml"),
                            "-f", os.path.join(b, "staging.override.yaml"), "--env-file", self.env_file,
                            "down", "--remove-orphans"], env=e, capture_output=True, text=True)
        left = subprocess.run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={self.project}"],
                              capture_output=True, text=True).stdout.split()
        if left:
            subprocess.run(["docker", "rm", "-f", *left], capture_output=True)


def bundle_identity(bundle_dir):
    m = json.load(open(os.path.join(bundle_dir, "MANIFEST.json")))
    b = json.load(open(os.path.join(bundle_dir, "BUILD.json")))
    return m, b


def finish(rec, hosts, fp_before):
    for h in hosts:
        h.down()
    left = subprocess.run(["docker", "ps", "-a", "--filter", f"name=flh-stg-{RUN}", "--format", "{{.Names}}"],
                          capture_output=True, text=True).stdout.split()
    fp_after = daily_fingerprint()
    rec.save("daily-fingerprint-after.txt", fp_after + "\n")
    rec.record("C1", not left, "cleanup: no stand-in container left", " ".join(left) or "none")
    rec.record("C2", fp_after == fp_before, "daily container and image unchanged", "unchanged" if fp_after == fp_before else "CHANGED")
    rec.note("RESULT", f"{'PASSED' if rec.failed == 0 else 'FAILED'} ({rec.failed} failed)")
    return 1 if rec.failed else 0
