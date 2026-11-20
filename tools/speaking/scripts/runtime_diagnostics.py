"""Local runtime diagnostics of the transcription service (real model, CPU, bounded).

  python3 -I -B tools/speaking/scripts/runtime_diagnostics.py --sources SOURCES --work WORK \\
      [--model whisper-base] [--image flh-speaking:cpu] [--flh-bin BIN]

Starts the service container (127.0.0.1 only, --cpus 2, --memory 2g,
--oom-score-adj 1000) with a pinned local model and records:
- readiness transitions;
- load and warm-up time, first and warm inference;
- wall time, audio duration and RTF on the same sample;
- the limits in force;
- an oversized request and a timed-out request (synthetic bytes), each
  followed by a valid request;
- a bounded concurrency run (3 requests, 1 waiting slot) and its resource limits;
- the machine-readable error classes seen.

With ``--flh-bin``, it also starts FLH with the local provider pointed at a
closed port and OpenAI feedback pointed at a local sentinel. A transcription
must then fail as ``provider_unavailable`` with zero requests to the sentinel:
no paid request on a local failure.

Audio is synthetic (tones), so the transcripts say nothing about accuracy. It
writes WORK/runtime-diagnostics.json, with no machine path in it.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import base64  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import socket  # noqa: E402
import struct  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
import uuid  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)
from flh_speaking import client, pins, variants  # noqa: E402

LIMITS = {"cpus": "2", "memory": "2g"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def tone(seconds: float, freq: float = 220.0) -> bytes:
    n = int(16000 * seconds)
    return variants.write_pcm16(16000, [int(9000 * math.sin(2 * math.pi * freq * k / 16000)) for k in range(n)])


def multipart(fields: dict) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    out = b""
    for k, v in fields.items():
        head = f'--{b}\r\nContent-Disposition: form-data; name="{k}"' + ('; filename="take.wav"\r\nContent-Type: audio/wav' if k == "file" else "") + "\r\n\r\n"
        out += head.encode() + (v if isinstance(v, bytes) else v.encode()) + b"\r\n"
    return out + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


def call(url, method="GET", data=None, headers=None, timeout=120):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, json.loads(body or b"null"), round(time.monotonic() - t0, 3)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw), round(time.monotonic() - t0, 3)
        except ValueError:
            return e.code, {"raw": raw[:100].decode("utf-8", "replace")}, round(time.monotonic() - t0, 3)


def status_of(url):
    try:
        code, doc, _ = call(url, timeout=3)
        return code, (doc or {}).get("status")
    except Exception as e:  # noqa: BLE001
        return "down", type(e).__name__


class Service:
    def __init__(self, a, extra=()):
        self.port, self.name = free_port(), f"flh-speaking-diag-{uuid.uuid4().hex[:8]}"
        self.url = f"http://127.0.0.1:{self.port}"
        rev = pins.MODELS[a.model]["revision"]
        subprocess.run(["docker", "run", "-d", "--oom-score-adj", "1000", "--name", self.name, "-p", f"127.0.0.1:{self.port}:8765",
                        "--cpus", LIMITS["cpus"], "--memory", LIMITS["memory"], "--memory-swap", LIMITS["memory"], "--user", f"{os.getuid()}:{os.getgid()}",
                        "-e", "HOME=/tmp", "-v", f"{PKG}/flh_speaking:/opt/program/flh_speaking:ro", "-v", f"{os.path.abspath(a.sources)}:/sources:ro",
                        a.image, "serve", "--model", f"/sources/openai/{a.model}/{rev}", "--host", "0.0.0.0", "--port", "8765", "--threads", "2", *extra],
                       check=True, stdout=subprocess.DEVNULL)

    def wait_ready(self, timeout=300):
        seen, t0 = [], time.monotonic()
        while time.monotonic() - t0 < timeout:
            st = status_of(self.url + "/readyz")
            if not seen or seen[-1][1:] != list(st):
                seen.append([round(time.monotonic() - t0, 2), *st])
            if st[0] == 200 or st[1] == "failed":
                return seen
            state = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}", self.name],
                                   capture_output=True, text=True).stdout.strip()
            if state and not state.startswith("running"):
                logs = subprocess.run(["docker", "logs", "--tail", "15", self.name], capture_output=True, text=True)
                raise SystemExit(f"container {state} (status, exit code, OOM-killed): {logs.stdout[-600:]}{logs.stderr[-600:]}")
            time.sleep(0.1)
        raise SystemExit(f"not ready: {seen}")

    def transcribe(self, audio, model=None, extra_len=None, timeout=120):
        body, ctype = multipart({"file": audio, "model": model or self.dep, "response_format": "json"})
        headers = {"Content-Type": ctype}
        if extra_len is not None:  # claim a size over the limit; the service refuses before reading the body
            headers["Content-Length"] = str(extra_len)
            body = body[:1024]
        return call(self.url + "/v1/audio/transcriptions", "POST", body, headers, timeout)

    def peak_mib(self):
        cid = subprocess.run(["docker", "inspect", "-f", "{{.Id}}", self.name], capture_output=True, text=True).stdout.strip()
        try:
            with open(f"/sys/fs/cgroup/system.slice/docker-{cid}.scope/memory.peak") as fh:
                return round(int(fh.read()) / 2**20, 1)
        except OSError:
            return None

    def stop(self):
        subprocess.run(["docker", "rm", "-f", self.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--model", default="whisper-base")
    ap.add_argument("--image", default="flh-speaking:cpu")
    ap.add_argument("--flh-bin")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    rep = {"schema": "flh_speaking_runtime_diagnostics_v1", "model": a.model, "revision": pins.MODELS[a.model]["revision"],
           "container_limits": LIMITS, "threads": 2, "audio": "synthetic tones (not speech)", "errors_seen": {}}
    five, sixty = tone(5.0), tone(60.0)
    services = []

    rep["error_body_problems"] = []

    def err(code, doc):
        t = (doc or {}).get("error", {}).get("type") if isinstance(doc, dict) else None
        if t:
            rep["errors_seen"][t] = code
            rep["error_body_problems"] += client.check_error(doc)

    try:
        s = Service(a)
        services.append(s)
        rep["readiness"] = s.wait_ready()                                       # 051
        code, ready, _ = call(s.url + "/readyz")
        man = call(s.url + "/manifest")[1]
        s.dep = man["deployment_id"]
        rep["deployment_id"] = s.dep
        rep["load"] = {"load_s": ready["load_s"], "warm_up_s": ready["warm_s"]}  # 052
        runs = []
        for k in range(3):                                                     # 052/053: first vs warm
            code, doc, wall = s.transcribe(five)
            runs.append({"run": k + 1, "http": code, "wall_s": wall, "audio_s": 5.0, "rtf": round(wall / 5.0, 3),
                         "model_s": doc["flh"]["timing"]["model_s"], "status": doc["flh"]["status"]})
        rep["inference"] = runs
        code, body, _ = s.transcribe(tone(2.0, 440.0))                         # 081/085: loopback compatibility
        rep["client_check"] = {"healthz": status_of(s.url + "/healthz")[0], "readyz": status_of(s.url + "/readyz")[0], "http": code,
                               **client.check_response(body, s.dep), "status": (body.get("flh") or {}).get("status")}
        rep["limits_in_force"] = man["limits"]                                  # 054
        try:                                                                    # 055 oversized
            code, doc, _ = s.transcribe(five, extra_len=man["limits"]["max_request_bytes"] + 1)
        except (ConnectionError, urllib.error.URLError) as e:  # the service may close before the client reads the 413
            code, doc = f"closed ({type(e).__name__})", {}
        err(code, doc)
        after = s.transcribe(five)
        rep["oversized"] = {"http": code, "error": (doc.get("error") or {}).get("type"),
                            "then_readyz": status_of(s.url + "/readyz")[0], "then_valid_request": after[0]}  # 056
        code, doc, _ = s.transcribe(five, model="not-this-deployment")
        err(code, doc)
        code, doc, _ = s.transcribe(b"RIFF....WAVEnot audio")
        err(code, doc)
        code, doc, _ = s.transcribe(tone(125.0))
        err(code, doc)
        rep["peak_mib_main"] = s.peak_mib()
        s.stop()
        q = Service(a, ("--max-waiting", "1"))                                   # 059
        services.append(q)
        q.wait_ready()
        q.dep = s.dep
        res = [None] * 3

        def go(i):
            res[i] = q.transcribe(sixty)
        th = [threading.Thread(target=go, args=(i,)) for i in range(3)]
        t0 = time.monotonic()
        for t in th:
            t.start()
            time.sleep(0.3)
        for t in th:
            t.join()
        for c, d, _ in res:
            err(c, d)
        rep["concurrency"] = {"requests": 3, "max_waiting": 1, "concurrent_inferences": 1, "http": sorted(c for c, _, _ in res),
                              "wall_s": round(time.monotonic() - t0, 2), "peak_mib": q.peak_mib(), "limits": LIMITS}
        q.stop()
        t = Service(a, ("--inference-timeout", "1"))                          # 055 timed out
        services.append(t)
        t.wait_ready()
        t.dep = s.dep
        code, doc, wall = t.transcribe(sixty)
        err(code, doc)
        small = t.transcribe(tone(1.0))
        rep["timed_out"] = {"http": code, "error": doc.get("error", {}).get("type"), "wall_s": wall,
                            "then_readyz": status_of(t.url + "/readyz")[0], "then_short_request": small[0]}
        t.stop()
        if a.flh_bin:
            rep["no_paid_request_on_local_failure"] = flh_check(a, s.dep)        # 057
    finally:
        for sv in services:
            sv.stop()
    with open(os.path.join(a.work, "runtime-diagnostics.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, sort_keys=True)
    print(json.dumps(rep, indent=1, sort_keys=True))
    return 0


def flh_check(a, dep: str) -> dict:
    calls = []

    class Sentinel(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def do_POST(self):
            calls.append(self.path)
            self.send_response(500)
            self.end_headers()
    sent = ThreadingHTTPServer(("127.0.0.1", 0), Sentinel)
    threading.Thread(target=sent.serve_forever, daemon=True).start()
    port, closed = free_port(), free_port()
    env = {"PATH": "/usr/bin:/bin", "HOME": a.work, "TMPDIR": a.work, "DB_PATH": os.path.join(a.work, "flh.db"), "PORT": str(port),
           "LISTEN_HOST": "127.0.0.1", "SPEAKING_TRANSCRIPTION_PROVIDER": "local", "SPEAKING_TRANSCRIPTION_MODEL": dep,
           "SPEAKING_TRANSCRIPTION_BASE_URL": f"http://127.0.0.1:{closed}/v1", "SPEAKING_PROVIDER": "openai",
           "OPENAI_API_KEY": "sk-synthetic-sentinel-not-a-secret", "OPENAI_MODEL": "sentinel-model",
           "OPENAI_BASE_URL": f"http://127.0.0.1:{sent.server_address[1]}"}
    log = open(os.path.join(a.work, "flh.log"), "w")
    proc = subprocess.Popen([a.flh_bin], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=a.work)
    furl = f"http://127.0.0.1:{port}"
    try:
        t0 = time.monotonic()
        while status_of(furl + "/healthz")[0] != 200:
            if time.monotonic() - t0 > 60:
                raise SystemExit("FLH did not start")
            time.sleep(0.2)
        pid = call(furl + "/speaking/prompts")[1]["prompts"][0]["id"]
        ex = call(furl + f"/speaking/prompts/{pid}", "POST")[1]["exercise"]["id"]
        audio = tone(3.0)
        take = {"audio_source": "recording", "audio_mime": "audio/wav", "audio_bytes": len(audio), "audio_sha256": hashlib.sha256(audio).hexdigest(), "duration_ms": 3000}
        v = call(furl + f"/speaking/exercises/{ex}/takes", "POST", json.dumps(take).encode(), {"Content-Type": "application/json"})[1]
        tid = next(t["id"] for t in v["takes"] if t["audio_sha256"] == take["audio_sha256"])
        body = json.dumps({"audio_base64": base64.b64encode(audio).decode(), "audio_mime": "audio/wav"}).encode()
        code, res, _ = call(furl + f"/speaking/takes/{tid}/transcriptions", "POST", body, {"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())})
        out = {"flh_http": code, "failure_code": (res.get("transcription") or {}).get("failure_code"),
               "state": (res.get("request") or {}).get("state"), "user_message": res.get("error"), "sentinel_requests": len(calls),
               "note": "OpenAI feedback is configured in the same process; the failed local transcription sent nothing to it"}
    finally:
        proc.terminate()
        proc.wait(15)
    # 089/090: explicit rollback to the previous provider setting (disabled): the same click is refused visibly
    env.update({"SPEAKING_TRANSCRIPTION_PROVIDER": "disabled"})
    for k in ("SPEAKING_TRANSCRIPTION_MODEL", "SPEAKING_TRANSCRIPTION_BASE_URL"):
        env.pop(k)
    proc = subprocess.Popen([a.flh_bin], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=a.work)
    try:
        t0 = time.monotonic()
        while status_of(furl + "/healthz")[0] != 200:
            if time.monotonic() - t0 > 60:
                raise SystemExit("FLH did not restart")
            time.sleep(0.2)
        code, res, _ = call(furl + f"/speaking/takes/{tid}/transcriptions", "POST", body, {"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())})
        prov = call(furl + "/speaking/prompts")[1]["providers"]["transcription"]
        out["after_rollback_to_disabled"] = {"flh_http": code, "user_message": res.get("error"), "providers.transcription": prov,
                                             "stored_transcriptions_kept": len(call(furl + f"/speaking/exercises/{ex}")[1]["transcriptions"]),
                                             "sentinel_requests": len(calls)}
        return out
    finally:
        proc.terminate()
        proc.wait(15)
        sent.shutdown()


if __name__ == "__main__":
    sys.exit(main())
