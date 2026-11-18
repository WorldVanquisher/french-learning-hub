#!/usr/bin/env python3
"""Staging stand-in rehearsal of the NAS -> AWS migration (batch 5, items 26-31).

  standin_rehearsal.py BUNDLE_DIR NAS_BACKUP_DIR CONTRACT_JSON WORK_DIR

Runs, on this machine, the exact procedure AWS_STAGING_PLAN.md gives the
owner for the staging host. Only S3 and SSM are replaced, by local files:
  D  deploy: transfer the bundle (tar + SHA-256, verified on arrival), verify
     its SHA256SUMS, docker load, check the image ID against VERSION.json,
     render the settings file from parameters (flh-staging-env), then
     flh-daily.sh check and up (isolated mode, the bundle's override, no build)
     and check that the running container is that image
  27 transfer the NAS-shaped backup the same way and restore it with
     flh-daily.sh restore (the supported path, with its write check)
  28 readiness and the first supported write
  29 restart: the write and the restored data persist
  30 import (create + idempotent replay), workbook revision update, search,
     source evidence
  31 backup staging with flh-daily.sh, transfer, restore into another
     disposable target, compare snapshots
Two isolated Compose projects (flh-stg-<run>-stg, -dr) on free loopback
ports, data under WORK_DIR. The daily project, image and data are never
touched (fingerprint before and after). Every result is a line in
WORK_DIR/results.tsv. No provider is configured, so no call can be paid.
"""
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

BUNDLE, NAS_BACKUP, CONTRACT, WORK = (os.path.realpath(x) for x in sys.argv[1:5])
HERE = os.path.dirname(os.path.abspath(__file__))
RUN = time.strftime("%Y%m%d%H%M%S", time.gmtime())
if os.path.exists(WORK):
    sys.exit(f"refused: {WORK} exists")
os.makedirs(os.path.join(WORK, "evidence"))
E = os.path.join(WORK, "evidence")
RESULTS = os.path.join(WORK, "results.tsv")
failed = 0
contract = json.load(open(CONTRACT))


def record(step, ok, expected, actual):
    global failed
    failed += 0 if ok else 1
    line = f"{step}\t{'PASS' if ok else 'FAIL'}\t{expected}\t{actual}"
    print(line, flush=True)
    with open(RESULTS, "a") as fh:
        fh.write(line + "\n")
    return ok


class Abort(Exception):
    pass


def require(ok, what):
    """A deploy or restore step that later steps depend on: stop the run if it failed."""
    if not ok:
        raise Abort(what)


def note(step, text):
    print(f"{step}\tNOTE\t{text}", flush=True)
    with open(RESULTS, "a") as fh:
        fh.write(f"{step}\tNOTE\t{text}\t\n")


def sha(path):
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
    for args in (["docker", "inspect", "-f", "{{.Id}} {{.Image}} {{.State.StartedAt}} {{.State.Status}}",
                  "french-learning-hub-app-1"],
                 ["docker", "image", "inspect", "-f", "{{.Id}}", "french-learning-hub:local"]):
        r = subprocess.run(args, capture_output=True, text=True)
        out.append(r.stdout.strip() or f"absent ({r.returncode})")
    return "\n".join(out)


def transfer(src_dir, name):
    """tar + SHA-256 (the S3/SSM hop), verified on arrival, unpacked under WORK/transfer."""
    tdir = os.path.join(WORK, "transfer")
    os.makedirs(tdir, exist_ok=True)
    tar = os.path.join(tdir, f"{name}.tar")
    with tarfile.open(tar, "w") as tf:
        tf.add(src_dir, arcname=name)
    digest = sha(tar)
    arrived = os.path.join(tdir, "arrived", f"{name}.tar")
    os.makedirs(os.path.dirname(arrived), exist_ok=True)
    shutil.copyfile(tar, arrived)
    ok = sha(arrived) == digest
    dest = os.path.join(tdir, "unpacked")
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(arrived) as tf:
        tf.extractall(dest, filter="tar")
    return ok, digest, os.path.join(dest, name)


class Target:
    def __init__(self, name, bundle_dir, port):
        self.name, self.port = name, port
        self.root = os.path.join(WORK, f"host-{name}")
        self.data = os.path.join(self.root, "data", "app")
        os.makedirs(self.data)
        os.chmod(self.data, 0o700)
        os.makedirs(os.path.join(self.root, "etc"))
        self.env_file = os.path.join(self.root, "etc", "staging.env")
        self.project = f"flh-stg-{RUN}-{name}"
        self.bundle = bundle_dir
        self.wrapper = os.path.join(bundle_dir, "repo", "scripts", "daily", "flh-daily.sh")
        self.override = os.path.join(bundle_dir, "staging.override.yaml")

    def url(self, path=""):
        return f"http://127.0.0.1:{self.port}{path}"

    def render_settings(self):
        params = {"Parameters": [{"Name": f"/flh/staging/{k}", "Value": v} for k, v in [
            ("FLH_DATA_DIR", self.data), ("FLH_HOST_PORT", str(self.port)), ("FLH_UID", str(os.getuid())),
            ("FLH_GID", str(os.getgid())), ("AI_PROVIDER", "rule-based"), ("EXTRACTOR_PROVIDER", "disabled"),
            ("SUGGESTION_PROVIDER", "disabled"), ("LISTENING_PROVIDER", "disabled"), ("READING_PROVIDER", "disabled"),
            ("WRITING_PROVIDER", "disabled"), ("SPEAKING_TRANSCRIPTION_PROVIDER", "disabled"),
            ("SPEAKING_PROVIDER", "disabled"), ("HTTP_WRITE_TIMEOUT", "75"), ("LISTENING_PLAYLIST_SOURCE", "disabled"),
            ("LISTENING_AUTO_PREPARE", "disabled"), ("LISTENING_NOTIFY", "disabled"),
            ("OPENAI_API_KEY", "stand-in-secret-value-never-printed")]]}
        pj = os.path.join(self.root, "etc", "ssm-stand-in.json")
        with open(pj, "w") as fh:
            json.dump(params, fh)
        os.chmod(pj, 0o600)
        r = subprocess.run(["bash", os.path.join(HERE, "host", "flh-staging-env"), "us-east-1", "/flh/staging",
                            self.env_file], env=dict(os.environ, FLH_STAGING_PARAMS_JSON=pj),
                           capture_output=True, text=True)
        out = r.stdout + r.stderr
        with open(os.path.join(E, f"{self.name}-render-settings.txt"), "w") as fh:
            fh.write(out)
        mode = stat.S_IMODE(os.stat(self.env_file).st_mode) if os.path.exists(self.env_file) else None
        return r.returncode == 0 and mode == 0o600 and "stand-in-secret-value" not in out, mode, out

    def wrap(self, *args, log=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("COMPOSE_", "DOCKER_HOST"))}
        env.update(FLH_DAILY_ENV=self.env_file, FLH_COMPOSE_PROJECT=self.project, FLH_COMPOSE_OVERRIDE=self.override)
        r = subprocess.run(["bash", self.wrapper, *args], env=env, capture_output=True, text=True)
        with open(os.path.join(E, f"{self.name}-{log or args[0]}.log"), "w") as fh:
            fh.write(f"$ flh-daily.sh {' '.join(args)}\nexit {r.returncode}\n{r.stdout}{r.stderr}")
        return r.returncode, r.stdout + r.stderr

    def container_image(self):
        r = subprocess.run(["docker", "ps", "--filter", f"label=com.docker.compose.project={self.project}",
                            "--format", "{{.ID}}"], capture_output=True, text=True)
        cid = r.stdout.split()[0] if r.stdout.split() else None
        if not cid:
            return None
        return subprocess.run(["docker", "inspect", "-f", "{{.Image}}", cid], capture_output=True, text=True).stdout.strip()

    def down(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
        subprocess.run(["docker", "compose", "-p", self.project, "-f", os.path.join(self.bundle, "repo", "compose.yaml"),
                        "-f", self.override, "--env-file", self.env_file, "down", "--remove-orphans"],
                       env=env, capture_output=True, text=True)


def call(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        return None, str(e).encode()


def js(b):
    try:
        return json.loads(b)
    except (ValueError, TypeError):
        return {}


def wait_ready(t, secs=60):
    end = time.time() + secs
    while time.time() < end:
        if call("GET", t.url("/readyz"))[0] == 200:
            return True
        time.sleep(1)
    return False


def snapshot(t, name):
    out = os.path.join(E, name)
    subprocess.run([sys.executable, "-I", "-B", os.path.join(t.bundle, "repo", "scripts", "validation", "v1_rehearsal",
                                                               "snapshot.py"), t.url(), out], capture_output=True)
    return out


def ledger(db):
    r = subprocess.run(["sqlite3", "-readonly", db, "select count(*) from schema_migrations"], capture_output=True, text=True)
    return r.stdout.strip()


targets = []
try:
    # ---- P. preflight -------------------------------------------------------------------------
    fp_before = daily_fingerprint()
    open(os.path.join(E, "daily-fingerprint-before.txt"), "w").write(fp_before + "\n")
    note("P", f"daily fingerprint recorded ({hashlib.sha256(fp_before.encode()).hexdigest()[:12]})")
    version = json.load(open(os.path.join(BUNDLE, "VERSION.json")))

    # ---- D. deploy the bundle ---------------------------------------------------------------------
    ok, digest, bdir = transfer(BUNDLE, "bundle")
    record("D1", ok, "bundle tar arrives with the SHA-256 recorded before transfer", f"sha256 {digest[:16]}")
    r = subprocess.run(["sha256sum", "--quiet", "-c", "SHA256SUMS"], cwd=bdir, capture_output=True, text=True)
    record("D2", r.returncode == 0, "bundle SHA256SUMS verifies", r.stdout.strip() or "all files verify")
    r = subprocess.run(["docker", "load", "-q", "-i", os.path.join(bdir, "image.tar")], capture_output=True, text=True)
    loaded = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", version["image_tag"]], capture_output=True,
                            text=True).stdout.strip()
    record("D3", r.returncode == 0 and loaded == version["image_id"], f"docker load gives image {version['image_id'][:19]}",
           f"{loaded[:19]}")
    stg = Target("stg", bdir, free_port())
    dr = Target("dr", bdir, free_port())
    targets = [stg, dr]
    for t in targets:
        ok, mode, out = t.render_settings()
        record("D4", ok, f"{t.name}: settings rendered from parameters, 0600, values never printed",
               f"mode {oct(mode) if mode else None}; {out.count(': set')} set")
        rc, out = t.wrap("check")
        require(ok, f"D4 {t.name} settings")
        record("D5", rc == 0, f"{t.name}: flh-daily.sh check (isolated project {t.project}, bundle override)", f"exit {rc}")
        require(rc == 0, f"D5 {t.name} check")
    rc, out = stg.wrap("up")
    ready = rc == 0 and wait_ready(stg)
    img = stg.container_image()
    record("26", ready and img == version["image_id"],
           "stg: up without a build; ready; the running container is the bundle's image (explicit version identity)",
           f"up exit {rc}, ready {ready}, container image {str(img)[:19]}, tree {version['tree_id'][:12]}")
    require(ready, "26 up")

    # ---- 27. restore the NAS-shaped backup ----------------------------------------------------------
    ok, digest, nas = transfer(NAS_BACKUP, "nas-backup")
    modes = sorted({oct(stat.S_IMODE(os.stat(os.path.join(nas, f)).st_mode)) for f in os.listdir(nas)})
    record("27a", ok, "NAS backup tar arrives with its recorded SHA-256", f"sha256 {digest[:16]}, files {modes}")
    t0 = time.time()
    rc, out = stg.wrap("restore", nas, log="restore")
    if rc != 0 and "could not write the restored database" in out:
        record("27b", True, "a read-only backup restores read-only: the write check refuses to start it and says how to fix it",
               f"exit {rc}: {out.strip().splitlines()[-1][:160]}")
        for f in os.listdir(stg.data):
            os.chmod(os.path.join(stg.data, f), 0o600)
        wc = subprocess.run([sys.executable, "-I", os.path.join(bdir, "repo", "scripts", "release", "restore_write_check.py"),
                             "--uid", str(os.getuid()), "--gid", str(os.getgid()), stg.data], capture_output=True, text=True)
        rc2, _ = stg.wrap("start", log="start-after-chmod")
        ready = rc2 == 0 and wait_ready(stg)
        record("27c", wc.returncode == 0 and ready, "after chmod 600 as the message says: write check passes, start, ready",
               f"check exit {wc.returncode}, start exit {rc2}, ready {ready}")
    else:
        ready = rc == 0 and wait_ready(stg)
        record("27b", ready, "restore through flh-daily.sh, ready", f"exit {rc}, ready {ready}")
    led = ledger(os.path.join(stg.data, "app.db"))
    require(call("GET", stg.url("/readyz"))[0] == 200, "27 restore")
    record("27d", led == "21", "restored ledger = 21 migrations, accepted by the candidate", f"{led} migrations, {round(time.time() - t0)} s")
    entry_cap = contract["entry"]["capture"]["capture_id"]
    mistake_cap = contract["old_mistake"]["capture"]["capture_id"]
    st_e, b_e = call("GET", stg.url(f"/captures/{entry_cap}"))
    st_m, b_m = call("GET", stg.url(f"/captures/{mistake_cap}"))
    entry_id = js(b_e).get("entry_id")
    mistake_id = js(b_m).get("entry_id")
    record("27e", st_e == 200 and st_m == 200 and entry_id and mistake_id,
           "restored data readable: the contract entry and the old mistake", f"entry {entry_id}, mistake {mistake_id}")
    snapshot(stg, "snapshot-stg-restored.json")

    # ---- 28. readiness and first supported write -----------------------------------------------------
    st_r = call("GET", stg.url("/readyz"))[0]
    st_h = call("GET", stg.url("/healthz"))[0]
    first = dict(contract["entry"]["capture"], capture_id="staging-first-write-001",
                 original_input="FIXTURE-PRIVATE-STAGING: première écriture sur la cible de staging.")
    st_w, b_w = call("POST", stg.url("/captures"), first)
    wid = js(b_w).get("entry_id") or (js(b_w).get("entry") or {}).get("id")
    st_g = call("GET", stg.url(f"/entries/{wid}"))[0] if wid else None
    record("28", st_r == 200 and st_h == 200 and st_w == 201 and st_g == 200,
           "/readyz 200, /healthz 200, POST /captures 201 and readable", f"{st_r}/{st_h}, POST {st_w}, GET {st_g}, entry {wid}")

    # ---- 29. restart: persistence ------------------------------------------------------------------
    rc, _ = stg.wrap("restart")
    ready = rc == 0 and wait_ready(stg)
    st_g2, b_g2 = call("GET", stg.url(f"/entries/{wid}"))
    st_e2 = call("GET", stg.url(f"/captures/{entry_cap}"))[0]
    record("29", ready and st_g2 == 200 and b"STAGING" in b_g2 and st_e2 == 200,
           "after flh-daily.sh restart: the first write and the restored entry are still there",
           f"restart exit {rc}, ready {ready}, write {st_g2}, restored {st_e2}")

    # ---- 30. import, workbook revision, search, source evidence --------------------------------------
    cap = dict(contract["entry"]["capture"], capture_id="staging-import-002",
               original_input="Import sur staging : « je me souviens de » ou « je me souviens » ?")
    st_i1 = call("POST", stg.url("/captures"), cap)[0]
    st_i2 = call("POST", stg.url("/captures"), cap)[0]
    record("30a", st_i1 == 201 and st_i2 == 200, "import (learning_capture_v1) 201, identical replay 200", f"{st_i1}, {st_i2}")
    wb = contract["workbook"]
    scripts = js(call("GET", stg.url("/listening/scripts"))[1])
    row = next((x for x in scripts.get("scripts", []) if x.get("id") == wb["script_id"]), {})
    mat = row.get("imported_material_id")
    st_p, b_p = call("GET", stg.url(f"/listening/materials/{mat}/script-update"))
    prev = js(b_p)
    open(os.path.join(E, "revision-preview.json"), "wb").write(b_p)
    changed = [c["item_id"] for c in (prev.get("changes") or {}).get("questions", [])]
    body = {"from_revision": prev.get("current_revision"), "pack_fingerprint": prev.get("pack_fingerprint")}
    st_u, b_u = call("POST", stg.url(f"/listening/materials/{mat}/script-update"), body)
    st_ur = call("POST", stg.url(f"/listening/materials/{mat}/script-update"), body)[0]
    st_r1, b_r1 = call("GET", stg.url(f"/listening/materials/{mat}/revisions/1"))
    lesson = js(call("GET", stg.url(f"/listening/materials/{mat}"))[1])
    rev = (lesson.get("script_revision") or {})
    ok = (row.get("pack_status") == "update_available" and row.get("imported_revision") == 1 and st_p == 200
          and changed == [wb["question"]["id"]] and st_u == 201 and js(b_u).get("revision") == 2 and st_ur == 200
          and st_r1 == 200 and wb["revision_1_rationale_en"].encode() in b_r1 and rev.get("revision") == 2)
    record("30b", ok, "workbook revision: update_available rev 1; preview changes only the contract question; "
           "update 201 -> rev 2; replay 200; rev 1 keeps its text",
           f"{row.get('pack_status')} rev {row.get('imported_revision')}; preview {st_p} {changed}; update {st_u}; "
           f"replay {st_ur}; rev1 {st_r1}; now rev {rev.get('revision')} {rev.get('pack_status')}")
    st_s, b_s = call("GET", stg.url("/learning-records?q=parte"))
    record("30c", st_s == 200 and (entry_cap.encode() in b_s or contract["entry"]["capture"]["original_input"].encode() in b_s),
           "search: GET /learning-records?q=parte finds the restored entry", f"{st_s}")
    st_src, b_src = call("GET", stg.url(f"/entries/{mistake_id}/source"))
    src = js(b_src)
    open(os.path.join(E, "source.json"), "wb").write(b_src)
    dup = json.loads(json.dumps(contract["old_mistake"]["capture"]))
    dup["capture_id"] = "staging-mistake-duplicate"
    dup["source_ref"]["record_id"] = ((src.get("item") or {}).get("source") or {}).get("record_id")  # the stored rev-1 exercise
    st_dup, b_dup = call("POST", stg.url("/captures"), dup)
    record("30d", st_src == 200 and src.get("linked") is True and wb["revision_1_rationale_en"].encode() in b_src
           and st_dup == 409 and b"source_already_saved" in b_dup,
           "source evidence: the old mistake stays linked to revision 1 after the update; a second save is 409",
           f"source {st_src} linked {src.get('linked')}; duplicate {st_dup}")
    snap_stg = snapshot(stg, "snapshot-stg-final.json")

    # ---- 31. backup staging, restore into another disposable target ------------------------------------
    rc, out = stg.wrap("backup")
    bpath = next((l.split("backup written to ", 1)[1].split(" (copy", 1)[0] for l in out.splitlines()
                  if "backup written to" in l), None)
    vr = subprocess.run(["sha256sum", "--quiet", "-c", "SHA256SUMS"], cwd=bpath, capture_output=True) if bpath else None
    ready = wait_ready(stg)
    record("31a", rc == 0 and vr is not None and vr.returncode == 0 and ready,
           "flh-daily.sh backup on staging: written, SHA256SUMS verifies, service back up", f"exit {rc}, {os.path.basename(str(bpath))}")
    require(bpath is not None, "31 backup")
    ok, digest, sb = transfer(bpath, "staging-backup")
    rc, _ = dr.wrap("up")
    up_ok = rc == 0 and wait_ready(dr)
    rc2, out2 = dr.wrap("restore", sb, log="restore")
    ready = rc2 == 0 and wait_ready(dr)
    record("31b", ok and up_ok and ready, "transfer (tar + SHA-256), then restore into the dr target (empty first), ready",
           f"transfer {ok}, dr up {up_ok}, restore exit {rc2}, ready {ready}")
    snap_dr = snapshot(dr, "snapshot-dr.json")
    same = os.path.exists(snap_stg) and os.path.exists(snap_dr) and open(snap_stg, "rb").read() == open(snap_dr, "rb").read()
    st_dw = call("GET", dr.url(f"/entries/{wid}"))[0]
    lesson_dr = js(call("GET", dr.url(f"/listening/materials/{mat}"))[1])
    record("31c", same and st_dw == 200 and (lesson_dr.get("script_revision") or {}).get("revision") == 2,
           "dr snapshot == staging snapshot after its writes; first write and revision 2 present",
           f"snapshot equal {same}, write {st_dw}, rev {(lesson_dr.get('script_revision') or {}).get('revision')}")
    dr_img = dr.container_image()
    record("31d", dr_img == version["image_id"], "dr runs the same bundle image", f"{str(dr_img)[:19]}")
except Abort as e:
    note("ABORT", f"stopped after a failed prerequisite step: {e}")
finally:
    for t in targets:
        t.down()
    left = subprocess.run(["docker", "ps", "-a", "--filter", f"name=flh-stg-{RUN}", "--format", "{{.Names}}"],
                          capture_output=True, text=True).stdout.split()
    fp_after = daily_fingerprint()
    open(os.path.join(E, "daily-fingerprint-after.txt"), "w").write(fp_after + "\n")
    record("C1", not left, "cleanup: no stand-in container left", " ".join(left) or "none")
    record("C2", fp_after == fp_before, "daily container and image unchanged", "unchanged" if fp_after == fp_before else "CHANGED")
    note("RESULT", f"{'PASSED' if failed == 0 else 'FAILED'} ({failed} failed)")
sys.exit(1 if failed else 0)
