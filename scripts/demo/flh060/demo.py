#!/usr/bin/env python3
"""FLH-060 isolated, persistent semantic-search demo (synthetic data only).

  demo.py setup   WORK --mode fake|real [real: --embedding-base-url URL --embedding-model ID
                       --embedding-dimensions N] [--qdrant docker|/path/to/qdrant]
                       [--web-dist DIR] [--port-base N] [--max-posts N --max-positions N]
  demo.py start   WORK            start the demo processes again (same directory, same data)
  demo.py stop    WORK            stop only this directory's processes/container; keep data
  demo.py status  WORK            processes, gateway counters, upstream readiness, index status
  demo.py index   WORK build|sync|rebuild|status     the operator CLI (semantic-index)
  demo.py search  WORK TEXT [--keyword] [--limit N]  the existing HTTP search routes
  demo.py offline WORK on|off     demo gateway switch: simulate the GPU service being away
  demo.py walkthrough WORK [--allow-live]            scripted build/search/restart/sync/recovery
  demo.py cleanup WORK            stop, then delete WORK (demo directories only)
  demo.py compose-up|compose-index|compose-status|compose-down WORK ...   see README.md

WORK must be an absolute path outside the repository. It holds the synthetic
SQLite database (seeded by the unchanged FLH-034 demo), the Qdrant storage, the
gateway counters/budget, logs and evidence, and survives stop/start.

Nothing reads .env or ambient provider variables: every child process gets an
explicit environment, with WORK as its working directory. Fake mode never
contacts a real model. Real mode needs the three --embedding-* arguments; setup
and start only make read-only readiness/manifest checks, and every embedding
POST goes through the task-owned gateway (budget charged before sending).
Listeners bind 127.0.0.1. A process is signalled only when its PID, start time
and command line (which names WORK) match what this tool recorded; the Qdrant
container is removed only when its label names WORK.

Exit status: 0 ok, 1 failure, 2 usage/refused.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FLH034 = REPO / "scripts" / "demo" / "flh034"
MARK = ".flh060-demo"
SCHEMA = "flh060_demo_v1"
FAKE_MODEL = "fake-e5-plumbing-only"
FAKE_DIMS = 768
DEFAULT_PORT_BASE = 18960
SEMANTIC_BATCH = 8
EMBEDDING_TIMEOUT = 30
DEFAULT_MAX_POSTS, DEFAULT_MAX_POSITIONS = 64, 256
ROLES = ("qdrant", "fake", "gateway", "server")
SCORE_NOTE = ("similarity is a cosine score between embeddings: not a probability, "
              "not a relevance judgment and never a SAME decision")

sys.path.insert(0, str(HERE))
import catalog  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# FLH-034's process identity and listener checks, reused unchanged.
pg = _load("flh034_proc_guard", FLH034 / "proc_guard.py")
# FLH-046 reads the Qdrant image pinned in compose.yaml; reused unchanged.
qr = _load("flh046_qdrant_regression", REPO / "scripts" / "ci" / "flh046" / "qdrant_regression.py")


class DemoError(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def say(msg: str = "") -> None:
    print(msg, flush=True)


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


# ------------------------------------------------------------------ directory

def work_id(work: Path) -> str:
    return hashlib.sha256(str(work).encode()).hexdigest()[:12]


def check_new_work(work: Path) -> Path:
    if not work.is_absolute():
        raise DemoError("WORK must be an absolute path", 2)
    resolved = work.resolve()
    for root in {REPO, REPO.resolve()}:
        if resolved == root or root in resolved.parents:
            raise DemoError("refusing a WORK inside the repository (protects data/ and the release)", 2)
    if resolved.exists() and any(resolved.iterdir()):
        raise DemoError(f"refusing: {resolved} is not empty; setup never reuses or resets a database", 2)
    return resolved


def open_work(work: Path) -> tuple[Path, dict]:
    work = work.resolve()
    if not (work / MARK).is_file() or not (work / "demo.json").is_file():
        raise DemoError(f"refusing: {work} is not an FLH-060 demo directory", 2)
    cfg = json.loads((work / "demo.json").read_text(encoding="utf-8"))
    if cfg.get("schema") != SCHEMA:
        raise DemoError("demo.json has an unexpected schema", 2)
    return work, cfg


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def evidence(work: Path, name: str, obj) -> Path:
    path = work / "evidence" / f"{stamp()}-{name}.json"
    n = 1
    while path.exists():
        path = work / "evidence" / f"{stamp()}-{name}-{n}.json"
        n += 1
    save_json(path, obj)
    return path


# ------------------------------------------------------------------ HTTP

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http(method: str, url: str, body=None, timeout: float = 10.0):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, _decode(r.read())
    except urllib.error.HTTPError as e:
        return e.code, _decode(e.read())


def _decode(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw[:200].decode(errors="replace")}


def service_root(base_url: str) -> str:
    """http://host:port/v1 -> http://host:port (the E5 service's /readyz and /manifest)."""
    u = urllib.parse.urlsplit(base_url.rstrip("/"))
    path = u.path[:-3] if u.path.endswith("/v1") else u.path
    return urllib.parse.urlunsplit((u.scheme, u.netloc, path, "", ""))


def preflight(cfg: dict) -> dict:
    """Read-only: the upstream must be ready and serve exactly the configured
    deployment with the configured dimensions. Never POSTs."""
    emb = cfg["embedding"]
    root = service_root(emb["upstream_base_url"])
    out = {"checked_utc": now(), "service_root": root, "expected_model": emb["model"],
           "expected_dimensions": emb["dimensions"]}
    try:
        rs, ready = http("GET", root + "/readyz", timeout=5)
        ms, manifest = http("GET", root + "/manifest", timeout=5)
    except (urllib.error.URLError, OSError) as e:
        out.update(reachable=False, error=type(e).__name__)
        return out
    dims = (((manifest or {}).get("vector_defining") or {}).get("inference") or {}).get("dimensions")
    out.update(reachable=True, ready_status=rs, ready=bool(ready and ready.get("ready")),
               manifest_status=ms, deployment_id=(manifest or {}).get("deployment_id"),
               manifest_sha256=(manifest or {}).get("manifest_sha256"), dimensions=dims)
    out["identity_ok"] = out["deployment_id"] == emb["model"] and dims == emb["dimensions"]
    return out


# ------------------------------------------------------------------ processes

def child_env(cfg: dict, work: Path, extra: dict | None = None) -> dict:
    """An explicit environment: nothing provider-related is inherited."""
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT") if k in os.environ}
    env.update(extra or {})
    return env


def app_env(cfg: dict, work: Path) -> dict:
    emb, p = cfg["embedding"], cfg["ports"]
    return {
        "LISTEN_HOST": "127.0.0.1", "PORT": str(p["server"]), "DB_PATH": str(work / "flh034" / "demo.db"),
        "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled",
        "EMBEDDING_PROVIDER": "http", "EMBEDDING_BASE_URL": f"http://127.0.0.1:{p['gateway']}/v1",
        "EMBEDDING_MODEL": emb["model"], "EMBEDDING_MODEL_ID": emb["model"],
        "EMBEDDING_DIMENSIONS": str(emb["dimensions"]), "EMBEDDING_TIMEOUT": str(EMBEDDING_TIMEOUT),
        "SEMANTIC_SEARCH": "qdrant", "QDRANT_URL": f"http://127.0.0.1:{p['qdrant']}",
        "SEMANTIC_BATCH_SIZE": str(SEMANTIC_BATCH),
    }


def role_matches(role: str, work: Path, cfg: dict, cmd: str) -> bool:
    w = str(work)
    if role == "server":
        exe = str(work / "flh034" / "server")
        return cmd == exe or cmd.startswith(exe + " ")
    if role == "gateway":
        return str(HERE / "gateway.py") in cmd and cmd.endswith(" " + w)
    if role == "fake":
        return str(HERE / "fake_e5.py") in cmd and cmd.endswith(" " + w)
    if role == "qdrant":
        q = cfg["qdrant"]
        return q["kind"] == "binary" and cmd.startswith(q["binary"]) and str(work / "qdrant.yaml") in cmd
    return False


def rec_path(work: Path, role: str) -> Path:
    return work / "run" / f"{role}.json"


def owned_pid(work: Path, cfg: dict, role: str) -> int | None:
    try:
        rec = json.loads(rec_path(work, role).read_text())
    except (OSError, ValueError):
        return None
    live = pg.identity(rec["pid"])
    if live is None or [rec.get("start"), rec.get("command")] != list(live):
        return None
    return rec["pid"] if role_matches(role, work, cfg, live[1]) else None


def scan(work: Path, cfg: dict) -> list[tuple[int, str]]:
    me = os.getpid()
    return [(pid, role) for pid, cmd in pg.commands() if pid != me
            for role in ROLES if role_matches(role, work, cfg, cmd)]


def port_free(port: int) -> bool:
    import socket
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return False
        except OSError:
            continue
        finally:
            s.close()
    return True


def require_free(port: int, what: str) -> None:
    if not port_free(port):
        raise DemoError(f"port {port} ({what}) is already in use; stop that process or choose --port-base", 2)


def launch(work: Path, cfg: dict, role: str, argv: list[str], env: dict, port: int, seconds: float = 30) -> int:
    require_free(port, role)
    log = (work / "logs" / f"{role}.log").open("ab")
    proc = subprocess.Popen(argv, cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True)
    log.close()
    deadline = time.monotonic() + 5
    while True:  # record identity once the exec has landed
        live = pg.identity(proc.pid)
        if live is None or proc.poll() is not None:
            raise DemoError(f"{role} exited during startup; see {work}/logs/{role}.log")
        if role_matches(role, work, cfg, live[1]):
            save_json(rec_path(work, role), {"pid": proc.pid, "start": live[0], "command": live[1]})
            break
        if time.monotonic() > deadline:
            raise DemoError(f"{role} (pid {proc.pid}) never became this demo's {role}")
        time.sleep(0.05)
    deadline = time.monotonic() + seconds
    while True:  # ready only once the owned process itself listens, on loopback only
        if owned_pid(work, cfg, role) != proc.pid:
            raise DemoError(f"{role} exited; see {work}/logs/{role}.log")
        hosts = pg.listeners(proc.pid, port)
        if hosts:
            bad = [h for h in hosts if not pg.is_loopback(h)]
            if bad:
                raise DemoError(f"{role} listens on non-loopback {bad}")
            say(f"  {role}: pid {proc.pid} listening on {', '.join(sorted(set(hosts)))}:{port}")
            return proc.pid
        if time.monotonic() > deadline:
            raise DemoError(f"{role} is not listening on {port}; see {work}/logs/{role}.log")
        time.sleep(0.1)


def stop_role(work: Path, cfg: dict, role: str) -> None:
    path = rec_path(work, role)
    if not path.exists():
        return
    pid = owned_pid(work, cfg, role)
    if pid is None:
        say(f"  {role}: recorded process is not running (or is not ours); record removed, nothing signalled")
    else:
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 15
        while owned_pid(work, cfg, role) == pid and time.monotonic() < deadline:
            time.sleep(0.1)
        if owned_pid(work, cfg, role) == pid:
            raise DemoError(f"{role} pid {pid} did not exit after SIGTERM; record kept")
        say(f"  {role}: stopped pid {pid}")
    path.unlink()


# ------------------------------------------------------------------ Qdrant

def docker(args: list[str], timeout: float = 120, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise DemoError(f"docker {args[0]} failed: {p.stderr.strip()[-400:]}")
    return p


def container_label(name: str) -> str | None:
    p = docker(["inspect", "--format", '{{ index .Config.Labels "flh060.work" }}', name], check=False)
    return p.stdout.strip() if p.returncode == 0 else None


def start_qdrant(work: Path, cfg: dict) -> None:
    q, port = cfg["qdrant"], cfg["ports"]["qdrant"]
    (work / "qdrant" / "storage").mkdir(parents=True, exist_ok=True)
    if q["kind"] == "binary":
        grpc = cfg["ports"]["qdrant_grpc"]
        require_free(grpc, "qdrant grpc")
        (work / "qdrant.yaml").write_text(
            f"service:\n  host: 127.0.0.1\n  http_port: {port}\n  grpc_port: {grpc}\n"
            f"storage:\n  storage_path: {work}/qdrant/storage\n  snapshots_path: {work}/qdrant/storage/snapshots\n"
            "telemetry_disabled: true\n")
        launch(work, cfg, "qdrant", [q["binary"], "--config-path", str(work / "qdrant.yaml")], child_env(cfg, work), port)
    else:
        name = q["container"]
        label = container_label(name)
        if label is not None:
            if label != str(work):
                raise DemoError(f"a container named {name} exists but is not this demo's; NOT touched", 2)
            docker(["rm", "-f", name])  # our stopped leftover; storage is on the host
        require_free(port, "qdrant")
        if docker(["image", "inspect", q["image"]], check=False).returncode != 0:
            raise DemoError(f"the pinned Qdrant image is not present locally; pull it explicitly first:\n  docker pull {q['image']}", 2)
        docker(["run", "-d", "--pull", "never", "--name", name, "--label", f"flh060.work={work}",
                "--label", "flh060.role=qdrant", "--user", f"{os.getuid()}:{os.getgid()}",
                "-p", f"127.0.0.1:{port}:6333", "-e", "QDRANT__TELEMETRY_DISABLED=true",
                "-e", "QDRANT__STORAGE__SNAPSHOTS_PATH=/qdrant/storage/snapshots",
                "-v", f"{work}/qdrant/storage:/qdrant/storage", q["image"]])
        binding = docker(["port", name, "6333/tcp"]).stdout.split()
        if not binding or any(not b.startswith("127.0.0.1:") for b in binding):
            raise DemoError(f"qdrant container published on {binding}, not loopback only")
        say(f"  qdrant: container {name} published on {', '.join(binding)}")
    deadline = time.monotonic() + 60
    while True:
        try:
            if http("GET", f"http://127.0.0.1:{port}/readyz", timeout=2)[0] == 200:
                return
        except (urllib.error.URLError, OSError):
            pass
        if time.monotonic() > deadline:
            raise DemoError("qdrant did not become ready")
        time.sleep(0.3)


def stop_qdrant(work: Path, cfg: dict) -> None:
    q = cfg["qdrant"]
    if q["kind"] == "binary":
        stop_role(work, cfg, "qdrant")
        return
    label = container_label(q["container"])
    if label is None:
        return
    if label != str(work):
        say(f"  qdrant: container {q['container']} is not this demo's; NOT touched")
        return
    docker(["rm", "-f", q["container"]])
    say(f"  qdrant: removed container {q['container']} (storage kept in {work}/qdrant)")


def qdrant_running(cfg: dict, work: Path) -> bool:
    q = cfg["qdrant"]
    if q["kind"] == "binary":
        return owned_pid(work, cfg, "qdrant") is not None
    p = docker(["inspect", "--format", "{{.State.Running}}", q["container"]], check=False)
    return p.returncode == 0 and p.stdout.strip() == "true" and container_label(q["container"]) == str(work)


# ------------------------------------------------------------------ lifecycle

def start_all(work: Path, cfg: dict) -> None:
    p = cfg["ports"]
    if cfg["mode"] == "real":
        pf = preflight(cfg)
        evidence(work, "preflight", pf)
        if pf.get("reachable") and not pf.get("identity_ok"):
            raise DemoError(f"the embedding service serves {pf.get('deployment_id')!r} ({pf.get('dimensions')} dims), "
                            f"not the configured {cfg['embedding']['model']!r}; refusing to start", 2)
        if not (pf.get("reachable") and pf.get("ready")):
            say("  WARNING: the GPU embedding service is not reachable/ready now. Keyword search works; "
                "semantic search and indexing will fail until it is back (nothing falls back).")
        else:
            say(f"  embedding service: ready, exact deployment {pf['deployment_id']}")
    start_qdrant(work, cfg)
    if cfg["mode"] == "fake":
        launch(work, cfg, "fake", [sys.executable, "-B", str(HERE / "fake_e5.py"), str(p["fake"]), str(work)],
               child_env(cfg, work), p["fake"])
        wait_ready(f"http://127.0.0.1:{p['fake']}/readyz", "fake embedding service", 30)
    launch(work, cfg, "gateway", [sys.executable, "-B", str(HERE / "gateway.py"), str(p["gateway"]), str(work)],
           child_env(cfg, work), p["gateway"])
    argv = [str(work / "flh034" / "server")]
    if cfg.get("web_dist"):
        argv += ["-web-dir", cfg["web_dist"]]
    launch(work, cfg, "server", argv, child_env(cfg, work, app_env(cfg, work)), p["server"])
    wait_ready(f"http://127.0.0.1:{p['server']}/readyz", "server", 20)
    say(f"demo ready: http://127.0.0.1:{p['server']}/  (mode {cfg['mode']}, model {cfg['embedding']['model']})")


def wait_ready(url: str, what: str, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            if http("GET", url, timeout=2)[0] == 200:
                return
        except (urllib.error.URLError, OSError):
            pass
        if time.monotonic() > deadline:
            raise DemoError(f"{what} did not become ready at {url}")
        time.sleep(0.2)


def stop_all(work: Path, cfg: dict) -> None:
    for role in ("server", "gateway", "fake"):
        stop_role(work, cfg, role)
    stop_qdrant(work, cfg)
    left = scan(work, cfg)
    if left:
        raise DemoError("demo processes for this directory are still running without a matching record "
                        "(not signalled): " + ", ".join(f"{r} pid {pid}" for pid, r in left))


def cmd_setup(a) -> int:
    work = check_new_work(Path(a.work))
    if a.mode == "real":
        missing = [n for n in ("embedding_base_url", "embedding_model", "embedding_dimensions") if getattr(a, n) in (None, "")]
        if missing:
            raise DemoError("real mode needs --embedding-base-url, --embedding-model and --embedding-dimensions "
                            "(nothing is read from .env or the environment)", 2)
        emb = {"upstream_base_url": a.embedding_base_url.rstrip("/"), "model": a.embedding_model,
               "dimensions": int(a.embedding_dimensions)}
    else:
        if a.embedding_base_url or a.embedding_model or a.embedding_dimensions:
            raise DemoError("fake mode takes no --embedding-* arguments (it never contacts a real model)", 2)
        base = a.port_base
        emb = {"upstream_base_url": f"http://127.0.0.1:{base + 2}/v1", "model": FAKE_MODEL, "dimensions": FAKE_DIMS}
    base = a.port_base
    ports = {"server": base, "gateway": base + 1, "fake": base + 2, "qdrant": base + 3, "qdrant_grpc": base + 4,
             "seed_stub": base + 5, "compose_app": base + 6, "compose_qdrant": base + 7}
    for name in ("server", "gateway", "qdrant", "seed_stub") + (("fake",) if a.mode == "fake" else ()):
        require_free(ports[name], name)
    if a.qdrant == "docker":
        image, _version = qr.pinned_image((REPO / "compose.yaml").read_text())
        qd = {"kind": "docker", "image": image, "container": f"flh060-qdrant-{work_id(work)}"}
    else:
        qbin = Path(a.qdrant).resolve()
        if not (qbin.is_file() and os.access(qbin, os.X_OK)):
            raise DemoError("--qdrant must be 'docker' or an executable Qdrant binary", 2)
        qd = {"kind": "binary", "binary": str(qbin)}
    web = str(Path(a.web_dist).resolve()) if a.web_dist else ""
    if web and not (Path(web) / "index.html").is_file():
        raise DemoError("--web-dist must be a built web/dist containing index.html", 2)
    cfg = {"schema": SCHEMA, "created_utc": now(), "mode": a.mode, "embedding": emb, "ports": ports,
           "qdrant": qd, "web_dist": web, "work_id": work_id(work)}

    work.mkdir(parents=True, exist_ok=True)
    (work / MARK).touch()
    for d in ("logs", "run", "evidence", "bin", "gateway"):
        (work / d).mkdir()
    save_json(work / "demo.json", cfg)
    if a.mode == "real":
        save_json(work / "gateway" / "budget.json", {"max_posts": a.max_posts, "max_positions": a.max_positions,
                                                      "used_posts": 0, "used_positions": 0, "created_utc": now(),
                                                      "note": "charged before each POST is forwarded"})
    try:
        if a.mode == "real":
            pf = preflight(cfg)
            evidence(work, "preflight", pf)
            if not pf.get("reachable") or not pf.get("identity_ok"):
                raise DemoError(f"real-mode preflight failed: {json.dumps(pf, sort_keys=True)}", 2)
            say(f"preflight: {pf['service_root']} ready={pf['ready']} serves exactly {pf['deployment_id']} ({pf['dimensions']} dims)")
        say("seeding the FLH-034 synthetic library (its own demo.sh, unchanged)...")
        seed_env = child_env(cfg, work, {"DEMO_PORT": str(ports["server"]), "STUB_PORT": str(ports["seed_stub"])})
        seed_args = ["sh", str(FLH034 / "demo.sh"), "setup", str(work / "flh034")] + ([web] if web else [])
        with (work / "logs" / "seed.log").open("w") as log:
            if subprocess.run(seed_args, env=seed_env, stdout=log, stderr=subprocess.STDOUT, cwd=work).returncode != 0:
                raise DemoError(f"FLH-034 seeding failed; see {work}/logs/seed.log")
            subprocess.run(["sh", str(FLH034 / "demo.sh"), "stop", str(work / "flh034")], env=seed_env,
                           stdout=log, stderr=subprocess.STDOUT, cwd=work, check=True)
        say("building the operator CLI (cmd/semantic-index)...")
        if subprocess.run(["go", "build", "-o", str(work / "bin" / "semantic-index"), "./cmd/semantic-index"],
                          cwd=REPO).returncode != 0:
            raise DemoError("semantic-index build failed")
        say("starting (loopback only):")
        start_all(work, cfg)
        add_catalog(cfg)
    except BaseException:
        say("setup FAILED; stopping what it started (data kept for inspection).")
        try:
            stop_all(work, cfg)
        except DemoError as e:
            say(f"  {e}")
        say(f"remove the failed directory with: python3 -B {HERE / 'demo.py'} cleanup {work}")
        raise
    say("setup complete. Nothing has been embedded yet; next: "
        f"python3 -B {HERE / 'demo.py'} index {work} build")
    return 0


def add_catalog(cfg: dict) -> None:
    base = f"http://127.0.0.1:{cfg['ports']['server']}"
    status, body = http("GET", base + "/concepts")
    existing = len((body or {}).get("concepts") or [])
    if status != 200 or existing != 7:
        raise DemoError(f"expected the 7 FLH-034 seed concepts before adding the catalog, found {existing}")
    for target, intent, scope, features in catalog.ADDITIONS:
        s, b = http("POST", base + "/concepts", catalog.concept_body(target, intent, scope, features))
        if s not in (200, 201):
            raise DemoError(f"adding a catalog concept failed with HTTP {s}: {b}")
    say(f"catalog: {existing} FLH-034 concepts + {len(catalog.ADDITIONS)} contrast concepts")


def cmd_start(a) -> int:
    work, cfg = open_work(Path(a.work))
    stop_all(work, cfg)  # clears stale records; signals only verified processes
    say("starting (loopback only):")
    try:
        start_all(work, cfg)
    except BaseException:
        say("start FAILED; stopping what it started.")
        stop_all(work, cfg)
        raise
    return 0


def cmd_stop(a) -> int:
    work, cfg = open_work(Path(a.work))
    stop_all(work, cfg)
    say(f"stopped; data kept in {work}")
    return 0


def cmd_cleanup(a) -> int:
    work = Path(a.work).resolve()
    if not work.exists():
        say(f"nothing to clean: {work} does not exist")
        return 0
    work, cfg = open_work(work)
    stop_all(work, cfg)
    if cfg.get("compose"):
        compose(work, cfg, ["down"], check=False)
    shutil.rmtree(work)
    say(f"removed {work}")
    return 0


# ------------------------------------------------------------------ operations

def gateway_state(cfg: dict) -> dict | None:
    try:
        s, b = http("GET", f"http://127.0.0.1:{cfg['ports']['gateway']}/gateway/state", timeout=3)
        return b if s == 200 else None
    except (urllib.error.URLError, OSError):
        return None


def delta(before: dict | None, after: dict | None) -> dict | None:
    if not before or not after:
        return None
    return {"posts": after["posts_forwarded"] - before["posts_forwarded"],
            "positions": after["positions_forwarded"] - before["positions_forwarded"],
            **{f"{k}_positions": after["positions_by_kind"][k] - before["positions_by_kind"][k]
               for k in after["positions_by_kind"]},
            **{f"refused_{k}": after["refused"][k] - before["refused"][k] for k in after["refused"]}}


def run_cli(work: Path, cfg: dict, op: str, as_json: bool) -> tuple[int, str, str]:
    argv = [str(work / "bin" / "semantic-index")] + (["-json"] if as_json else []) + [op]
    p = subprocess.run(argv, cwd=work, env=child_env(cfg, work, app_env(cfg, work)),
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout, p.stderr


def do_index(work: Path, cfg: dict, op: str) -> dict:
    before = gateway_state(cfg)
    code, out, err = run_cli(work, cfg, op, as_json=True)
    after = gateway_state(cfg)
    try:
        report = json.loads(out) if out.strip() else None
    except ValueError:
        report = None
    rec = {"operation": op, "exit": code, "report": report, "stderr": err.strip(), "gateway_delta": delta(before, after)}
    evidence(work, f"index-{op}", rec)
    return rec


def cmd_index(a) -> int:
    work, cfg = open_work(Path(a.work))
    if a.op == "status":
        code, out, err = run_cli(work, cfg, "status", as_json=False)
        say(out.rstrip())
        if err.strip():
            say(err.rstrip())
        return code
    rec = do_index(work, cfg, a.op)
    code, out, err = rec["exit"], rec["report"], rec["stderr"]
    if out:
        r = out
        say(f"{op_line(r)}")
    if err:
        say(err)
    d = rec["gateway_delta"]
    if d is not None:
        say(f"  embedding calls through the gateway: {d['posts']} POSTs, {d['concept_document_positions']} document "
            f"and {d['search_query_positions']} query positions")
    return code


def op_line(r: dict) -> str:
    if r.get("verified_unchanged"):
        return f"{r['operation']}: published collection verified healthy; published nothing; embedded {r['embedded_texts']}"
    return (f"{r['operation']}: concepts {r['concepts']}, embedded (provider) {r['embedded_texts']}, "
            f"reused from cache {r['reused_vectors']}, published {r['published']}, outcome {r['outcome']}")


def do_search(cfg: dict, text: str, keyword: bool, limit: int, port: int | None = None) -> dict:
    port = port or cfg["ports"]["server"]
    q = urllib.parse.urlencode({"q": text, "limit": limit})
    route = "/knowledge-library/concepts" if keyword else "/knowledge-library/semantic-search"
    before = gateway_state(cfg)
    status, body = http("GET", f"http://127.0.0.1:{port}{route}?{q}", timeout=60)
    after = gateway_state(cfg)
    hits = []
    for r in (body or {}).get("results") or []:
        hits.append({"target": r["concept"]["target"], "concept_id": r["concept"]["id"],
                     "similarity": r.get("similarity"), "match_tier": r.get("match_tier")})
    return {"mode": "keyword" if keyword else "semantic", "query": text, "status": status, "hits": hits,
            "error": (body or {}).get("error") if status != 200 else None,
            "query_representation": (body or {}).get("query_representation"),
            "index": {k: (body or {}).get("index", {}).get(k) for k in ("model_id", "collection", "health_verified")}
            if not keyword and status == 200 else None,
            "gateway_delta": delta(before, after)}


def print_search(r: dict) -> None:
    say(f"[{r['mode']}] \"{r['query']}\" -> HTTP {r['status']}")
    if r["status"] != 200:
        say(f"  error: {r['error']}")
    for i, h in enumerate(r["hits"], 1):
        score = f"  similarity {h['similarity']:.4f}" if h["similarity"] is not None else f"  ({h['match_tier']})"
        say(f"  {i}. {h['target']}{score}")
    if r["mode"] == "semantic" and r["status"] == 200:
        say(f"  ({SCORE_NOTE})")
    d = r["gateway_delta"]
    if d is not None:
        say(f"  embedding calls: {d['posts']} POST, {d['search_query_positions']} query position(s), "
            f"{d['concept_document_positions']} document positions")


def cmd_search(a) -> int:
    work, cfg = open_work(Path(a.work))
    port = cfg["ports"]["compose_app"] if a.compose else None
    if a.compose and not a.keyword:
        charge_bypass(work, cfg, 1, 1, "compose semantic search")
    r = do_search(cfg, a.text, a.keyword, a.limit, port)
    evidence(work, "search", r)
    print_search(r)
    return 0 if r["status"] == 200 else 1


def cmd_offline(a) -> int:
    work, cfg = open_work(Path(a.work))
    s, b = http("POST", f"http://127.0.0.1:{cfg['ports']['gateway']}/gateway/offline", {"offline": a.state == "on"})
    if s != 200:
        raise DemoError(f"gateway refused: {s} {b}")
    say(f"gateway offline = {b['offline']} (the real embedding service itself is not touched)")
    return 0


def cmd_status(a) -> int:
    work, cfg = open_work(Path(a.work))
    say(f"demo {work}  mode {cfg['mode']}  model {cfg['embedding']['model']} ({cfg['embedding']['dimensions']} dims)")
    ok = True
    for role in ("server", "gateway") + (("fake",) if cfg["mode"] == "fake" else ()):
        pid = owned_pid(work, cfg, role)
        ok &= pid is not None
        say(f"  {role:8} {'running pid ' + str(pid) if pid else 'NOT running'}")
    stray = [(pid, r) for pid, r in scan(work, cfg) if owned_pid(work, cfg, r) != pid]
    if stray:
        ok = False
        say("  UNRECORDED demo processes for this directory (never signalled automatically): "
            + ", ".join(f"{r} pid {pid}" for pid, r in stray))
    qr_ok = qdrant_running(cfg, work)
    ok &= qr_ok
    say(f"  {'qdrant':8} {'running' if qr_ok else 'NOT running'} ({cfg['qdrant']['kind']})")
    gs = gateway_state(cfg)
    if gs:
        say(f"  gateway counters (persist across restarts): {gs['posts_forwarded']} POSTs forwarded; positions "
            f"document {gs['positions_by_kind']['concept_document']}, search query {gs['positions_by_kind']['search_query']}; "
            f"refused {gs['refused']}; offline switch {gs['offline']}")
        if "budget" in gs:
            b = gs["budget"]
            say(f"  live budget: {b['used_posts']}/{b['max_posts']} POSTs, {b['used_positions']}/{b['max_positions']} positions")
    if cfg["mode"] == "real":
        pf = preflight(cfg)
        say(f"  embedding service (read-only check): reachable={pf.get('reachable')} ready={pf.get('ready')} "
            f"identity_ok={pf.get('identity_ok')}")
    else:
        say("  embedding service: local FAKE (hash vectors; rankings carry no meaning)")
    if owned_pid(work, cfg, "server") and qr_ok:
        code, out, err = run_cli(work, cfg, "status", as_json=False)
        say(out.rstrip())
        if err.strip():
            say(err.rstrip())
        ok &= code == 0
    return 0 if ok else 1


# ------------------------------------------------------------------ walkthrough

def planned_positions(concepts: int) -> tuple[int, int]:
    """(POSTs, positions) the walkthrough may use: one build plus the searches
    and one post-recovery search. sync/rebuild reuse the cache (0 expected)."""
    posts = -(-concepts // SEMANTIC_BATCH) + len(catalog.SEARCHES) + 1
    return posts, concepts + len(catalog.SEARCHES) + 1


def upstream_counters(cfg: dict) -> dict | None:
    """Read-only GET of the embedding service's own /metrics counters."""
    try:
        s, body = http("GET", service_root(cfg["embedding"]["upstream_base_url"]) + "/metrics", timeout=5)
    except (urllib.error.URLError, OSError):
        return None
    return (body or {}).get("counters") if s == 200 else None


def counter_delta(before: dict | None, after: dict | None) -> dict | None:
    if not before or not after:
        return None
    out = {}
    for k, v in after.items():
        if isinstance(v, (int, float)) and isinstance(before.get(k), (int, float)):
            out[k] = v - before[k]
        elif isinstance(v, dict) and isinstance(before.get(k), dict):
            out[k] = {kk: vv - before[k].get(kk, 0) for kk, vv in v.items() if isinstance(vv, (int, float))}
    return out


def cmd_walkthrough(a) -> int:
    work, cfg = open_work(Path(a.work))
    marker = work / "evidence" / "live-walkthrough.started"
    if cfg["mode"] == "real":
        if not a.allow_live:
            raise DemoError("real mode: the walkthrough sends live embedding requests; pass --allow-live", 2)
        if marker.exists():
            raise DemoError("the one live walkthrough for this directory was already started; not repeated", 2)
    s, body = http("GET", f"http://127.0.0.1:{cfg['ports']['server']}/concepts")
    concepts = len((body or {}).get("concepts") or [])
    posts, positions = planned_positions(concepts)
    gs = gateway_state(cfg)
    if gs is None:
        raise DemoError("the gateway is not running; run start first")
    if cfg["mode"] == "real":
        b = gs["budget"]
        if b["used_posts"] + posts > b["max_posts"] or b["used_positions"] + positions > b["max_positions"]:
            raise DemoError(f"planned {posts} POSTs/{positions} positions exceed the remaining budget {b}", 2)
        marker.write_text(json.dumps({"started_utc": now(), "planned_posts": posts, "planned_positions": positions}))
    log = {"started_utc": now(), "mode": cfg["mode"], "model": cfg["embedding"]["model"],
           "planned": {"posts": posts, "positions": positions}, "gateway_before": gs,
           "upstream_counters_before": upstream_counters(cfg), "steps": []}
    checks: list[tuple[str, bool]] = []

    def step(name, value):
        log["steps"].append({"step": name, "utc": now(), "result": value})
        return value

    def check(name, cond):
        checks.append((name, bool(cond)))
        say(f"  [{'ok' if cond else 'FAIL'}] {name}")

    try:
        code, out, _ = run_cli(work, cfg, "status", as_json=True)
        st = step("status-before", json.loads(out) if out.strip() else None)
        published = bool(((st or {}).get("state") or {}).get("published_collection"))
        if published:
            say("1. build: SKIPPED, this directory is already built (its cached vectors are reused below)")
        else:
            say("1. build: every Concept document is embedded once")
            r = step("build", do_index(work, cfg, "build"))
            say("   " + (op_line(r["report"]) if r["report"] else r["stderr"]))
            d = r["gateway_delta"] or {}
            check("build exit 0 and published", r["exit"] == 0 and (r["report"] or {}).get("published"))
            check(f"build embedded {concepts} documents, 0 query positions",
                  d.get("concept_document_positions") == concepts and d.get("search_query_positions") == 0)

        say("2. searches (demonstration inputs, not labels): semantic, then keyword for contrast")
        for text in catalog.SEARCHES:
            r = step("semantic-search", do_search(cfg, text, False, 5))
            print_search(r)
            check("semantic search HTTP 200, exactly 1 query position, 0 documents",
                  r["status"] == 200 and (r["gateway_delta"] or {}).get("search_query_positions") == 1
                  and (r["gateway_delta"] or {}).get("concept_document_positions") == 0)
        for text in catalog.KEYWORD_SEARCHES:
            r = step("keyword-search", do_search(cfg, text, True, 5))
            print_search(r)
            check("keyword search HTTP 200 with no embedding call",
                  r["status"] == 200 and (r["gateway_delta"] or {}).get("posts") == 0)

        say("3. restart: stop and start the same directory")
        stop_all(work, cfg)
        start_all(work, cfg)
        code, out, _ = run_cli(work, cfg, "status", as_json=True)
        st = step("status-after-restart", json.loads(out) if out.strip() else None)
        check("after restart the publication is still recorded and verified healthy",
              code == 0 and st and st.get("verified_healthy"))

        say("4. sync: verifies; republishes only if unhealthy")
        r = step("sync", do_index(work, cfg, "sync"))
        say("   " + (op_line(r["report"]) if r["report"] else r["stderr"]))
        check("sync verified unchanged with 0 embedding calls",
              r["exit"] == 0 and (r["report"] or {}).get("verified_unchanged") and (r["gateway_delta"] or {}).get("posts") == 0)

        say("5. rebuild: always republishes, from the SQLite embedding cache")
        r = step("rebuild", do_index(work, cfg, "rebuild"))
        say("   " + (op_line(r["report"]) if r["report"] else r["stderr"]))
        rep = r["report"] or {}
        check(f"rebuild reused {concepts} cached vectors with 0 embedding calls",
              r["exit"] == 0 and rep.get("embedded_texts") == 0 and rep.get("reused_vectors") == concepts
              and (r["gateway_delta"] or {}).get("posts") == 0)

        say("6. the embedding service goes away (demo gateway switched offline; the real service is untouched)")
        http("POST", f"http://127.0.0.1:{cfg['ports']['gateway']}/gateway/offline", {"offline": True})
        r = step("semantic-search-offline", do_search(cfg, catalog.SEARCHES[0], False, 5))
        print_search(r)
        check("semantic search fails explicitly (no keyword fallback)", r["status"] in (502, 504) and not r["hits"])
        r = step("keyword-search-offline", do_search(cfg, catalog.KEYWORD_SEARCHES[0], True, 5))
        print_search(r)
        check("keyword search still works", r["status"] == 200)
        code, out, _ = run_cli(work, cfg, "status", as_json=True)
        st = step("status-offline", json.loads(out) if out.strip() else None)
        check("index status stays healthy (it never calls the embedding service)", code == 0 and st and st.get("verified_healthy"))

        say("7. the service is back: no rebuild needed")
        http("POST", f"http://127.0.0.1:{cfg['ports']['gateway']}/gateway/offline", {"offline": False})
        r = step("semantic-search-recovered", do_search(cfg, catalog.SEARCHES[0], False, 5))
        print_search(r)
        check("semantic search works again", r["status"] == 200)
    finally:
        log["gateway_after"] = gateway_state(cfg)
        log["upstream_counters_after"] = upstream_counters(cfg)
        log["upstream_counters_delta"] = counter_delta(log["upstream_counters_before"], log["upstream_counters_after"])
        log["checks"] = [{"check": n, "ok": ok} for n, ok in checks]
        log["finished_utc"] = now()
        path = evidence(work, "walkthrough", log)
    failed = [n for n, ok in checks if not ok]
    ga = log["gateway_after"] or {}
    say(f"\ngateway totals: {ga.get('posts_forwarded')} POSTs; document positions "
        f"{(ga.get('positions_by_kind') or {}).get('concept_document')}, query positions "
        f"{(ga.get('positions_by_kind') or {}).get('search_query')}; budget {ga.get('budget')}")
    ud = log["upstream_counters_delta"]
    if ud is not None:
        say("embedding service's own counters (delta; a shared service may include other clients): "
            + json.dumps(ud, sort_keys=True))
    say(f"walkthrough {'PASSED' if not failed else 'FAILED: ' + '; '.join(failed)} ({len(checks)} mechanical checks; "
        f"no relevance judgment). Evidence: {path}")
    return 0 if not failed else 1


# ------------------------------------------------------------------ Compose

def compose_args(work: Path, cfg: dict) -> list[str]:
    return ["docker", "compose", "-p", f"flh060-{cfg['work_id']}", "--env-file", str(work / "compose" / "compose.env"),
            "-f", str(REPO / "compose.yaml"), "-f", str(HERE / "compose.override.yaml"), "--profile", "semantic"]


def compose(work: Path, cfg: dict, args: list[str], check: bool = True, timeout: float = 1800) -> subprocess.CompletedProcess:
    p = subprocess.run(compose_args(work, cfg) + args, cwd=REPO, capture_output=True, text=True, timeout=timeout,
                       env=child_env(cfg, work))
    if check and p.returncode != 0:
        raise DemoError(f"docker compose {args[0]} failed:\n{(p.stdout + p.stderr)[-1500:]}")
    return p


def cmd_compose_up(a) -> int:
    work, cfg = open_work(Path(a.work))
    cdir = work / "compose"
    (cdir / "data").mkdir(parents=True, exist_ok=True)
    (cdir / "qdrant").mkdir(parents=True, exist_ok=True)
    db = cdir / "data" / "app.db"
    if not db.exists():  # snapshot the seeded native database once (SQLite backup API)
        src = sqlite3.connect(f"file:{work / 'flh034' / 'demo.db'}?mode=ro", uri=True)
        dst = sqlite3.connect(db)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        say(f"compose: copied the synthetic database to {db} (once; later runs keep it)")
    emb, p = cfg["embedding"], cfg["ports"]
    for port, what in ((p["compose_app"], "compose app"), (p["compose_qdrant"], "compose qdrant")):
        require_free(port, what)
    url = a.container_embedding_url.rstrip("/")
    via_gateway = url == f"http://host.docker.internal:{p['gateway']}/v1"
    if cfg["mode"] == "real" and not via_gateway and url != emb["upstream_base_url"]:
        raise DemoError("real mode: --container-embedding-url must be the configured endpoint "
                        f"{emb['upstream_base_url']} or the gateway http://host.docker.internal:{p['gateway']}/v1", 2)
    env = {"FLH_UID": str(os.getuid()), "FLH_GID": str(os.getgid()), "FLH_HOST_PORT": str(p["compose_app"]),
           "FLH_QDRANT_PORT": str(p["compose_qdrant"]), "FLH_DATA_DIR": str(cdir / "data"),
           "FLH_QDRANT_DIR": str(cdir / "qdrant"), "FLH060_WORK": str(work),
           "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled", "EMBEDDING_PROVIDER": "http",
           "EMBEDDING_BASE_URL": url, "EMBEDDING_MODEL": emb["model"], "EMBEDDING_MODEL_ID": emb["model"],
           "EMBEDDING_DIMENSIONS": str(emb["dimensions"]), "EMBEDDING_TIMEOUT": str(EMBEDDING_TIMEOUT),
           "SEMANTIC_SEARCH": "qdrant", "QDRANT_URL": "http://qdrant:6333", "SEMANTIC_BATCH_SIZE": str(SEMANTIC_BATCH)}
    (cdir / "compose.env").write_text("".join(f"{k}={v}\n" for k, v in env.items()))
    cfg["compose"] = {"container_embedding_url": url, "via_gateway": via_gateway}
    save_json(work / "demo.json", cfg)
    say("compose: docker compose up (project flh060-%s, image flh060-demo-app:local)..." % cfg["work_id"])
    compose(work, cfg, ["up", "-d"] + (["--build"] if a.build else []))
    wait_ready(f"http://127.0.0.1:{p['compose_app']}/readyz", "compose app", 120)
    say(f"compose demo ready: http://127.0.0.1:{p['compose_app']}/")
    return 0


def charge_bypass(work: Path, cfg: dict, posts: int, positions: int, what: str) -> None:
    """Real mode with the Compose app calling the endpoint directly (no gateway):
    charge the worst case for this operation to the same budget BEFORE running."""
    if cfg["mode"] != "real" or (cfg.get("compose") or {}).get("via_gateway", True):
        return
    if posts == 0:
        return
    path = work / "gateway" / "budget.json"
    b = json.loads(path.read_text())
    if b["used_posts"] + posts > b["max_posts"] or b["used_positions"] + positions > b["max_positions"]:
        raise DemoError(f"{what} could use {posts} POSTs/{positions} positions; the live budget has "
                        f"{b['max_posts'] - b['used_posts']}/{b['max_positions'] - b['used_positions']} left. Refused.", 2)
    b["used_posts"] += posts
    b["used_positions"] += positions
    b.setdefault("compose_charges", []).append({"utc": now(), "what": what, "posts": posts, "positions": positions})
    save_json(path, b)
    say(f"  budget: charged worst case {posts} POSTs/{positions} positions for {what} (Compose bypasses the gateway)")


def compose_concepts(cfg: dict) -> int:
    s, body = http("GET", f"http://127.0.0.1:{cfg['ports']['compose_app']}/concepts")
    if s != 200:
        raise DemoError("the Compose app is not answering; run compose-up first")
    return len((body or {}).get("concepts") or [])


def cmd_compose_index(a) -> int:
    work, cfg = open_work(Path(a.work))
    if a.op in ("build", "sync", "rebuild"):
        n = compose_concepts(cfg)
        charge_bypass(work, cfg, -(-n // SEMANTIC_BATCH), n, f"compose-index {a.op}")
    before = gateway_state(cfg)
    p = compose(work, cfg, ["exec", "-T", "app", "/app/semantic-index", a.op], check=False, timeout=300)
    say((p.stdout + p.stderr).rstrip())
    d = delta(before, gateway_state(cfg))
    if d is not None:
        say(f"  embedding calls through the gateway: {d['posts']} POSTs ({d['concept_document_positions']} document positions)")
    evidence(work, f"compose-index-{a.op}", {"exit": p.returncode, "stdout": p.stdout, "stderr": p.stderr, "gateway_delta": d})
    return p.returncode


def cmd_compose_status(a) -> int:
    work, cfg = open_work(Path(a.work))
    p = compose(work, cfg, ["ps"], check=False)
    say(p.stdout.rstrip() or p.stderr.rstrip())
    return p.returncode


def cmd_compose_down(a) -> int:
    work, cfg = open_work(Path(a.work))
    if not cfg.get("compose"):
        say("compose was never started for this directory")
        return 0
    compose(work, cfg, ["down"])
    say(f"compose project flh060-{cfg['work_id']} removed; data kept in {work}/compose")
    return 0


# ------------------------------------------------------------------ main

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="demo.py", description="FLH-060 isolated semantic-search demo")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("setup")
    s.add_argument("work")
    s.add_argument("--mode", choices=("fake", "real"), required=True)
    s.add_argument("--embedding-base-url")
    s.add_argument("--embedding-model")
    s.add_argument("--embedding-dimensions", type=int)
    s.add_argument("--qdrant", default="docker", help="'docker' (pinned image, task-owned container) or a Qdrant binary path")
    s.add_argument("--web-dist")
    s.add_argument("--port-base", type=int, default=DEFAULT_PORT_BASE)
    s.add_argument("--max-posts", type=int, default=DEFAULT_MAX_POSTS)
    s.add_argument("--max-positions", type=int, default=DEFAULT_MAX_POSITIONS)
    for name in ("start", "stop", "status", "cleanup"):
        sub.add_parser(name).add_argument("work")
    i = sub.add_parser("index")
    i.add_argument("work")
    i.add_argument("op", choices=("build", "sync", "rebuild", "status"))
    q = sub.add_parser("search")
    q.add_argument("work")
    q.add_argument("text")
    q.add_argument("--keyword", action="store_true")
    q.add_argument("--limit", type=int, default=5)
    q.add_argument("--compose", action="store_true", help="query the Compose app instead of the native one")
    o = sub.add_parser("offline")
    o.add_argument("work")
    o.add_argument("state", choices=("on", "off"))
    w = sub.add_parser("walkthrough")
    w.add_argument("work")
    w.add_argument("--allow-live", action="store_true")
    cu = sub.add_parser("compose-up")
    cu.add_argument("work")
    cu.add_argument("--container-embedding-url", required=True)
    cu.add_argument("--build", action="store_true")
    ci = sub.add_parser("compose-index")
    ci.add_argument("work")
    ci.add_argument("op", choices=("build", "sync", "rebuild", "status"))
    for name in ("compose-status", "compose-down"):
        sub.add_parser(name).add_argument("work")
    a = ap.parse_args(argv)
    handlers = {"setup": cmd_setup, "start": cmd_start, "stop": cmd_stop, "status": cmd_status,
                "cleanup": cmd_cleanup, "index": cmd_index, "search": cmd_search, "offline": cmd_offline,
                "walkthrough": cmd_walkthrough, "compose-up": cmd_compose_up, "compose-index": cmd_compose_index,
                "compose-status": cmd_compose_status, "compose-down": cmd_compose_down}
    try:
        return handlers[a.command](a)
    except DemoError as e:
        print(f"demo.py: {e}", file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        print("demo.py: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
