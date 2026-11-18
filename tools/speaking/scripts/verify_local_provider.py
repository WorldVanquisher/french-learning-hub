"""Real-inference check of SPEAKING_TRANSCRIPTION_PROVIDER=local through FLH's
normal Speaking API, against the pretrained Whisper service (no OpenAI call, no
AWS, no learner data).

  # 1. audio from the frozen public test split (MLS French, CC BY 4.0), in the image:
  docker run --rm --network none -v $PWD/tools/speaking:/s:ro -v DATA:/data:ro -v WORK/audio:/out \\
      --entrypoint python3 flh-speaking:cpu-dev -B /s/scripts/verify_local_provider.py prep --data /data --out /out
  # 2. the scenarios (host, standard library only):
  python3 -I -B tools/speaking/scripts/verify_local_provider.py run --repo . --work WORK --sources SOURCES \\
      --server-bin BIN --model-subdir openai/whisper-base/<rev> --other-model-subdir openai/whisper-small/<rev>

``run`` starts FLH's server (scrubbed environment, fresh database in WORK) with
local transcription pointed at the service container (published on 127.0.0.1
only) and OpenAI-style feedback pointed at a synthetic local stub in this
process, then drives the API: startup before the service exists, readiness
during loading, a real transcription, confirmation and provenance, feedback
beside it, duplicate and concurrent submissions, a client that goes away,
slow inference against a short FLH timeout and against the service deadline,
browser formats, refused inputs, a service restart, a service started with
other weights, and what is left on disk afterwards. It writes WORK/report.json.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never leave __pycache__ in the repository

import argparse
import base64
import hashlib
import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
STUB_KEY = "sk-synthetic-feedback-stub-not-a-secret"
STUB_MODEL = "stub-feedback-model"


# ---------------------------------------------------------------- prep (image)
def prep(data: str, out: str) -> int:
    sys.path.insert(0, PKG)
    import numpy as np
    from flh_speaking import evaluate, probes

    SR = 16000
    rows = evaluate.load_rows(data, "test")
    a = next(r for r in rows if 8.0 <= r["seconds"] <= 16.0)
    gap = np.zeros(int(0.4 * SR), np.float32)

    def concat(min_s, max_s):
        parts, refs, ids, n = [], [], [], 0.0
        for r in rows:
            if n + r["seconds"] > max_s:
                continue
            parts += [evaluate.read_audio(data, r), gap]
            refs.append(r["text"])
            ids.append(r["id"])
            n += r["seconds"] + 0.4
            if n >= min_s:
                break
        return np.concatenate(parts), " ".join(refs), ids

    xa = evaluate.read_audio(data, a)
    xl, ref_l, ids_l = concat(95.0, 100.0)
    xo, _, ids_o = concat(124.0, 130.0)
    xb, ref_b, ids_b = concat(45.0, 60.0)
    clips = {
        "a.webm": (probes.encode(xa, "webm", "libopus", rate=48000), "audio/webm", len(xa) / SR, a["text"], [a["id"]]),
        "a.m4a": (probes.encode(xa, "mp4", "aac"), "audio/mp4", len(xa) / SR, a["text"], [a["id"]]),
        "a.mp3": (probes.encode(xa, "mp3", "libmp3lame", rate=44100), "audio/mpeg", len(xa) / SR, a["text"], [a["id"]]),
        "a.wav": (probes.encode(xa, "wav", "pcm_s16le"), "audio/wav", len(xa) / SR, a["text"], [a["id"]]),
        "a.ogg": (probes.encode(xa, "ogg", "libopus", rate=48000), "audio/ogg", len(xa) / SR, a["text"], [a["id"]]),
        "long.webm": (probes.encode(xl, "webm", "libopus", rate=48000), "audio/webm", len(xl) / SR, ref_l, ids_l),
        "overlong.webm": (probes.encode(xo, "webm", "libopus", rate=48000), "audio/webm", len(xo) / SR, "", ids_o),
        # 48 kHz stereo PCM: 43 s is just under 8 MiB (FLH's limit), 44 s just over.
        "limit.wav": (probes.encode(xb[: 43 * SR], "wav", "pcm_s16le", rate=48000, layout="stereo"), "audio/wav", 43.0, "", ids_b),
        "over8mib.wav": (probes.encode(xb[: 44 * SR], "wav", "pcm_s16le", rate=48000, layout="stereo"), "audio/wav", 44.0, "", ids_b),
        "silence.webm": (probes.encode(np.zeros(3 * SR, np.float32), "webm", "libopus", rate=48000), "audio/webm", 3.0, "", []),
        "garbage.webm": (bytes([0x1A, 0x45, 0xDF, 0xA3]) + np.random.default_rng(20261118).integers(0, 256, 20000, dtype=np.uint8).tobytes(),
                         "audio/webm", 2.0, "", []),
    }
    index = {}
    for name, (blob, mime, secs, ref, ids) in clips.items():
        with open(os.path.join(out, name), "wb") as fh:
            fh.write(blob)
        index[name] = {"mime": mime, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(), "seconds": round(secs, 2),
                       "reference": ref, "source_ids": ids}
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"source": "MLS French test split (frozen, CC BY 4.0), flh_mls_fr_subset_v1; synthetic silence and garbage",
                   "clips": index}, fh, ensure_ascii=False, indent=1, sort_keys=True)
    return 0


# ---------------------------------------------------------------- helpers (host)
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(url, method="GET", body=None, headers=None, timeout=180, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json"} if data is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null"), dict(r.headers), round(time.monotonic() - t0, 3)
    except urllib.error.HTTPError as e:
        raw_body = e.read()
        try:
            doc = json.loads(raw_body)
        except ValueError:
            doc = {"raw": raw_body.decode("utf-8", "replace")[:200]}
        return e.code, doc, dict(e.headers), round(time.monotonic() - t0, 3)


def status_of(url):
    try:
        code, doc, _, _ = call(url, timeout=3)
        return code, (doc or {}).get("status")
    except Exception as e:  # noqa: BLE001 - refused while the container starts
        return "down", type(e).__name__


class FeedbackStub:
    """Synthetic stand-in for the OpenAI Responses endpoint used by Speaking
    feedback: checks the synthetic key, records what arrived, answers with the
    authored feedback fixture (quotes may not occur in a real transcript; the
    server then grounds them as not_found)."""

    def __init__(self, fixture: str):
        self.calls, self.fixture = [], fixture
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                ok = self.headers.get("Authorization") == "Bearer " + STUB_KEY and self.path == "/responses"
                doc = json.loads(body or b"{}")
                stub.calls.append({"path": self.path, "authorized": ok, "model": doc.get("model"), "input": json.dumps(doc.get("input"), ensure_ascii=False)})
                out = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": stub.fixture}]}]}
                raw = json.dumps(out).encode() if ok else b'{"error":{"type":"unauthorized"}}'
                self.send_response(200 if ok else 401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"


class MemSampler:
    def __init__(self, name):
        self.name, self.peak_mib, self.stop = name, 0.0, False
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while not self.stop:
            try:
                with open(f"/sys/fs/cgroup/system.slice/docker-{self.cid()}.scope/memory.peak") as fh:
                    self.peak_mib = max(self.peak_mib, int(fh.read()) / 2**20)
            except (OSError, ValueError):
                pass
            time.sleep(0.5)

    def cid(self):
        if not hasattr(self, "_cid"):
            self._cid = subprocess.run(["docker", "inspect", "-f", "{{.Id}}", self.name], capture_output=True, text=True).stdout.strip()
        return self._cid


# ---------------------------------------------------------------- run (host)
def run(a) -> int:
    work = os.path.abspath(a.work)
    adir = os.path.join(work, "audio")
    clips = json.load(open(os.path.join(adir, "index.json"), encoding="utf-8"))["clips"]
    blob = {n: open(os.path.join(adir, n), "rb").read() for n in clips}
    sys.path.insert(0, PKG)
    from flh_speaking import textnorm

    def wer(ref, hyp):
        return round(textnorm.rate([textnorm.score(ref, hyp or "")])["wer"], 4)

    uid, gid = os.getuid(), os.getgid()
    rep: dict = {"schema": "flh_speaking_local_provider_verification_v1", "clips": clips, "scenarios": {}}
    sc = rep["scenarios"]
    sport = free_port()
    surl = f"http://127.0.0.1:{sport}"
    names: list[str] = []
    mem: dict[str, MemSampler] = {}

    def manifest_offline(subdir):
        out = subprocess.run(["docker", "run", "--rm", "--oom-score-adj", "1000", "--network", "none", "--memory", "1g", "--user", f"{uid}:{gid}",
                              "-e", "HOME=/tmp", "-v", f"{PKG}/flh_speaking:/opt/program/flh_speaking:ro", "-v", f"{os.path.abspath(a.sources)}:/sources:ro",
                              a.image, "manifest", "--model", f"/sources/{subdir}"], capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def start_service(subdir, extra=()):
        name = f"flh-speaking-verify-{uuid.uuid4().hex[:8]}"
        names.append(name)
        subprocess.run(["docker", "run", "-d", "--oom-score-adj", "1000", "--name", name, "-p", f"127.0.0.1:{sport}:8765", "--memory", "2g",
                        "--memory-swap", "2g", "--cpus", "4", "--user", f"{uid}:{gid}", "-e", "HOME=/tmp",
                        "-v", f"{PKG}/flh_speaking:/opt/program/flh_speaking:ro", "-v", f"{os.path.abspath(a.sources)}:/sources:ro",
                        a.image, "serve", "--model", f"/sources/{subdir}", "--host", "0.0.0.0", "--port", "8765", *extra],
                       check=True, stdout=subprocess.DEVNULL)
        mem[name] = MemSampler(name)
        return name

    def stop_service(name):
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait_ready(timeout=300):
        seen, t0 = [], time.monotonic()
        while time.monotonic() - t0 < timeout:
            st = status_of(surl + "/readyz")
            if not seen or seen[-1][1:] != st:
                seen.append((round(time.monotonic() - t0, 2),) + st)
            if st[0] == 200 or st[1] == "failed":
                return seen
            time.sleep(0.2)
        raise SystemExit(f"service not ready: {seen}")

    def metrics():
        return call(surl + "/metrics", timeout=5)[1]["counters"]

    base_manifest = manifest_offline(a.model_subdir)
    dep = base_manifest["deployment_id"]
    rep["deployment_id_offline"] = dep
    json.dump(base_manifest, open(os.path.join(work, "manifest-offline.json"), "w"), indent=1, sort_keys=True)

    fixture = open(os.path.join(a.repo, "internal", "speaking", "testdata", "invitation_feedback.json"), encoding="utf-8").read()
    stub = FeedbackStub(fixture)
    fport = free_port()
    furl = f"http://127.0.0.1:{fport}"
    flh = {"proc": None, "log": []}

    def start_flh(timeout_s):
        env = {"PATH": "/usr/bin:/bin", "HOME": work, "TMPDIR": work, "DB_PATH": os.path.join(work, "flh.db"), "PORT": str(fport), "LISTEN_HOST": "127.0.0.1",
               "HTTP_WRITE_TIMEOUT": "75", "SPEAKING_TRANSCRIPTION_PROVIDER": "local", "SPEAKING_TRANSCRIPTION_MODEL": dep,
               "SPEAKING_TRANSCRIPTION_BASE_URL": surl + "/v1", "SPEAKING_TRANSCRIPTION_TIMEOUT": str(timeout_s),
               "SPEAKING_PROVIDER": "openai", "OPENAI_API_KEY": STUB_KEY, "OPENAI_MODEL": STUB_MODEL, "OPENAI_BASE_URL": stub.url, "OPENAI_TIMEOUT": "8"}
        logpath = os.path.join(work, f"flh-server-{len(flh['log'])}.log")
        flh["log"].append(logpath)
        flh["proc"] = subprocess.Popen([a.server_bin], env=env, stdout=open(logpath, "w"), stderr=subprocess.STDOUT, cwd=work)
        t0 = time.monotonic()
        while status_of(furl + "/healthz")[0] != 200:
            if time.monotonic() - t0 > 60:
                raise SystemExit("FLH did not start")
            time.sleep(0.2)
        return [ln.split(" ", 2)[-1].strip() for ln in open(logpath, encoding="utf-8") if ln.split(" ", 2)[-1].startswith("speaking ")]

    def stop_flh():
        if flh["proc"]:
            flh["proc"].terminate()
            flh["proc"].wait(15)
            flh["proc"] = None

    exercises = {}

    def exercise(i):
        if i not in exercises:
            pid = call(furl + "/speaking/prompts")[1]["prompts"][i]["id"]
            exercises[i] = call(furl + f"/speaking/prompts/{pid}", "POST")[1]["exercise"]["id"]
        return exercises[i]

    def take(ex, name, mime=None, duration_ms=None, nbytes=None):
        b = blob[name]
        body = {"audio_source": "recording", "audio_mime": mime or clips[name]["mime"], "audio_bytes": nbytes if nbytes is not None else len(b),
                "audio_sha256": hashlib.sha256(b).hexdigest(), "duration_ms": duration_ms or int(clips[name]["seconds"] * 1000)}
        code, v, _, _ = call(furl + f"/speaking/exercises/{ex}/takes", "POST", body)
        if code not in (200, 201):
            return code, v
        return code, next(t["id"] for t in v["takes"] if t["audio_sha256"] == body["audio_sha256"])

    def transcribe(tid, name, key=None, mime=None, confirm=False, timeout=180, audio=None):
        key = key or str(uuid.uuid4())
        data = blob[name] if audio is None else audio
        body = {"audio_base64": base64.b64encode(data).decode(), "audio_mime": mime or clips[name]["mime"], "confirm_unknown_retry": confirm}
        code, res, hdr, secs = call(furl + f"/speaking/takes/{tid}/transcriptions", "POST", body, {"Idempotency-Key": key}, timeout=timeout)
        t = (res or {}).get("transcription") or {}
        r = (res or {}).get("request") or {}
        return {"http": code, "key": key, "seconds": secs, "state": r.get("state"), "status": t.get("status"), "failure_code": t.get("failure_code"),
                "transcriber": t.get("transcriber"), "text": t.get("text"), "transcription_id": t.get("id"), "code": (res or {}).get("code"),
                "replayed": hdr.get("Idempotency-Replayed"), "after_unknown": r.get("after_unknown"),
                "deadline_s": _span(r.get("started_at"), r.get("deadline_at")), "error": (res or {}).get("error")}

    try:
        # ---- item 6: FLH starts before the service exists; then readiness during loading
        rep["flh_startup_log"] = start_flh(60)
        ex1 = exercise(0)
        _, ta = take(ex1, "a.webm")
        sc["service_not_started"] = transcribe(ta, "a.webm")
        svc = start_service(a.model_subdir)
        during, transitions, t0 = None, [], time.monotonic()
        while time.monotonic() - t0 < 300:
            st = status_of(surl + "/readyz")
            if not transitions or transitions[-1][1:] != st:
                transitions.append((round(time.monotonic() - t0, 2),) + st)
            if during is None and st[1] in ("loading", "warming"):
                during = transcribe(ta, "a.webm")
                during["service_status_when_sent"] = st[1]
            if st[0] == 200 or st[1] == "failed":
                break
            time.sleep(0.1)
        sc["readiness_transitions"] = transitions
        sc["during_loading"] = during
        served = call(surl + "/manifest")[1]
        rep["deployment_id_served"] = served["deployment_id"]
        rep["service_limits"] = served["limits"]
        json.dump(served, open(os.path.join(work, "manifest-served.json"), "w"), indent=1, sort_keys=True)

        # ---- items 2, 3, 5: a real transcription, confirmation and provenance
        m0 = metrics()
        first = transcribe(ta, "a.webm")
        m1 = metrics()
        first["wer"] = wer(clips["a.webm"]["reference"], first["text"])
        first["service_requests_delta"] = m1["requests"] - m0["requests"]
        sc["real_transcription"] = first
        _, prompts, _, _ = call(furl + "/speaking/prompts")
        sc["provider_identity"] = {"api_transcription_name": prompts["providers"]["transcription"]["name"],
                                   "api_feedback_name": prompts["providers"]["feedback"]["name"],
                                   "stored_transcriber": first["transcriber"], "served_deployment_id": served["deployment_id"],
                                   "offline_deployment_id": dep,
                                   "consistent": first["transcriber"] == prompts["providers"]["transcription"]["name"] == f"local:{served['deployment_id']}:speaking_transcription_v1" and served["deployment_id"] == dep,
                                   "request_deadline_s": first["deadline_s"]}
        view0 = call(furl + f"/speaking/exercises/{ex1}")[1]
        code_c1, v1, _, _ = call(furl + f"/speaking/takes/{ta}/transcripts", "POST", {"text": first["text"], "transcription_id": first["transcription_id"]})
        code_c2, v2, _, _ = call(furl + f"/speaking/takes/{ta}/transcripts", "POST", {"text": clips["a.webm"]["reference"], "transcription_id": first["transcription_id"]})
        stop_flh()
        start_flh(60)  # the saved result survives a restart of FLH
        view = call(furl + f"/speaking/exercises/{ex1}")[1]
        mine = [t for t in view["transcripts"] if t["take_id"] == ta]
        sc["confirmation"] = {"transcripts_before_confirm": len([t for t in view0["transcripts"] if t["take_id"] == ta]),
                              "confirm_unchanged_http": code_c1, "confirm_corrected_http": code_c2,
                              "versions_after_restart": [{"version": t["version"], "origin": t["origin"], "transcription_id": t["transcription_id"]} for t in mine],
                              "stored_transcriptions": sorted({(t["transcriber"], t["status"]) for t in view["transcriptions"]})}

        # ---- item 4: OpenAI-style feedback beside local transcription
        v2id = max(t["id"] for t in mine)
        mf = metrics()
        code, fb, _, secs = call(furl + f"/speaking/transcripts/{v2id}/feedback", "POST", raw=b"", headers={"Idempotency-Key": str(uuid.uuid4())})
        sc["feedback_beside"] = {"http": code, "generator": (fb.get("feedback") or {}).get("generator"), "status": (fb.get("feedback") or {}).get("status"),
                                 "stub_calls": len(stub.calls), "stub_authorized": all(c["authorized"] for c in stub.calls),
                                 "stub_model": stub.calls[-1]["model"] if stub.calls else None,
                                 "stub_saw_confirmed_text": bool(stub.calls) and clips["a.webm"]["reference"].split()[0] in stub.calls[-1]["input"],
                                 "service_requests_delta": metrics()["requests"] - mf["requests"], "seconds": secs}

        # ---- item 9: duplicates, a second click while one runs, a client that goes away
        mr = metrics()
        rp = transcribe(ta, "a.webm", key=first["key"])
        sc["replay_same_key"] = {**{k: rp[k] for k in ("http", "replayed", "state", "text")}, "same_text": rp["text"] == first["text"],
                                 "service_requests_delta": metrics()["requests"] - mr["requests"]}
        _, tl = take(ex1, "long.webm")
        _, ta2 = take(ex1, "a.wav")
        mi = metrics()
        box = {}
        kl = str(uuid.uuid4())
        th = threading.Thread(target=lambda: box.update(r=transcribe(tl, "long.webm", key=kl)))
        th.start()
        while metrics()["requests"] == mi["requests"]:
            time.sleep(0.05)
        second = transcribe(ta2, "a.wav")
        same = transcribe(tl, "long.webm", key=kl)
        th.join()
        box["r"]["wer"] = wer(clips["long.webm"]["reference"], box["r"]["text"])
        sc["concurrent"] = {"first_long": {k: box["r"][k] for k in ("http", "state", "status", "seconds", "wer")},
                            "second_click_other_take": {k: second[k] for k in ("http", "code")},
                            "same_key_while_running": {k: same[k] for k in ("http", "replayed", "state", "status")},
                            "service_requests_delta": metrics()["requests"] - mi["requests"]}
        kc = str(uuid.uuid4())
        mc = metrics()
        try:
            transcribe(tl, "long.webm", key=kc, timeout=0.5)
            gone = "answered"
        except Exception as e:  # noqa: BLE001 - the client gives up on purpose
            gone = type(e).__name__
        t0 = time.monotonic()
        while True:
            code, rq, _, _ = call(furl + f"/speaking/transcription-requests/{kc}")
            if code == 200 and rq["request"]["state"] != "in_progress" or time.monotonic() - t0 > 120:
                break
            time.sleep(0.5)
        sc["client_went_away"] = {"client": gone, "lookup_http": code, "state": rq["request"]["state"],
                                  "status": (rq.get("transcription") or {}).get("status"), "seconds_until_stored": round(time.monotonic() - t0, 2),
                                  "service_requests_delta": metrics()["requests"] - mc["requests"]}

        # ---- items 5, 9, 14: FLH's timeout shorter than the inference
        stop_flh()
        rep["flh_startup_log_short_timeout"] = start_flh(2)
        ex3 = exercise(2)
        _, tl3 = take(ex3, "long.webm")
        slow = transcribe(tl3, "long.webm")
        retry_plain = transcribe(tl3, "long.webm")
        time.sleep(8)  # let the abandoned inference finish on the service
        stop_flh()
        start_flh(60)
        retry_ack = transcribe(tl3, "long.webm", confirm=True)
        sc["flh_timeout_shorter_than_inference"] = {"timeout_s": 2, "first": {k: slow[k] for k in ("http", "state", "failure_code", "seconds", "deadline_s")},
                                                    "new_click_without_ack": {k: retry_plain[k] for k in ("http", "code")},
                                                    "acknowledged_retry_timeout_60": {k: retry_ack[k] for k in ("http", "state", "status", "after_unknown", "deadline_s")}}

        # ---- item 8: browser formats; item 7: refused inputs (through the API)
        ex2 = exercise(1)
        fm = {}
        for name, mime in (("a.webm", "audio/webm;codecs=opus"), ("a.m4a", "audio/mp4"), ("a.m4a", "audio/x-m4a"), ("a.mp3", "audio/mpeg"), ("a.wav", "audio/wav")):
            code, tid = take(ex2, name, mime=mime)
            r = transcribe(tid, name, mime=mime) if code in (200, 201) else {"http": code, "take_refused": tid}
            if r.get("text") is not None:
                r["wer"] = wer(clips[name]["reference"], r["text"])
            fm[f"{name} as {mime}"] = {k: r.get(k) for k in ("http", "status", "failure_code", "wer", "seconds", "text", "take_refused")}
        code, v = take(ex2, "a.ogg")
        fm["a.ogg as audio/ogg"] = {"take_http": code, "error": v.get("error") if isinstance(v, dict) else None}
        sc["formats"] = fm
        ref = {}
        mref = metrics()
        code, v = take(ex2, "a.webm", nbytes=0)
        ref["take_with_zero_bytes"] = {"http": code, "error": v.get("error")}
        code, v = take(ex2, "overlong.webm", duration_ms=125_000)
        ref["take_declared_125s"] = {"http": code, "error": v.get("error")}
        code, v = take(ex2, "over8mib.wav")
        ref["take_over_8MiB"] = {"http": code, "error": v.get("error")}
        _, tw = take(ex2, "a.wav")
        r = transcribe(tw, "a.wav", audio=b"")
        ref["empty_audio_body"] = {k: r[k] for k in ("http", "error")}
        r = transcribe(tw, "a.wav", mime="audio/webm")
        ref["wav_sent_as_webm"] = {k: r[k] for k in ("http", "error")}
        r = transcribe(tw, "a.wav", audio=blob["over8mib.wav"])
        ref["body_over_8MiB"] = {k: r[k] for k in ("http", "error")}
        ref["service_requests_delta_before_any_call"] = metrics()["requests"] - mref["requests"]
        _, tg = take(ex2, "garbage.webm")
        r = transcribe(tg, "garbage.webm")
        ref["undecodable_webm"] = {k: r[k] for k in ("http", "state", "failure_code")}
        _, to = take(ex2, "overlong.webm", duration_ms=119_000)
        r = transcribe(to, "overlong.webm")
        ref["audio_longer_than_120s_declared_119s"] = {k: r[k] for k in ("http", "state", "failure_code", "seconds")}
        _, ts = take(ex2, "silence.webm")
        r = transcribe(ts, "silence.webm")
        ref["silence"] = {k: r[k] for k in ("http", "state", "failure_code", "seconds")}
        _, tb = take(ex2, "limit.wav")
        r = transcribe(tb, "limit.wav")
        ref["wav_just_under_8MiB"] = {"bytes": clips["limit.wav"]["bytes"], **{k: r[k] for k in ("http", "state", "status", "seconds")}}
        sc["refused_inputs"] = ref

        # ---- item 6: restart; other weights; the service's own deadline
        rs = {}
        subprocess.run(["docker", "restart", "-t", "5", svc], check=True, stdout=subprocess.DEVNULL)
        rs["right_after_restart"] = {k: v for k, v in transcribe(ta, "a.webm").items() if k in ("http", "state", "failure_code")}
        rs["readiness_after_restart"] = wait_ready()
        r = transcribe(ta, "a.webm")
        rs["after_ready"] = {k: r[k] for k in ("http", "state", "status", "transcriber")}
        rs["same_deployment_after_restart"] = call(surl + "/manifest")[1]["deployment_id"] == dep
        stop_service(svc)
        if a.other_model_subdir:
            other = start_service(a.other_model_subdir)
            wait_ready()
            rs["other_weights_deployment"] = call(surl + "/manifest")[1]["deployment_id"]
            r = transcribe(ta, "a.webm")
            rs["other_weights"] = {k: r[k] for k in ("http", "state", "failure_code", "text")}
            stop_service(other)
        short = start_service(a.model_subdir, ("--inference-timeout", "1"))
        wait_ready()
        rs["service_deadline_limits"] = call(surl + "/manifest")[1]["limits"]["inference_timeout_s"]
        _, tl5 = take(exercise(0), "long.webm")
        r = transcribe(tl5, "long.webm")
        rs["service_deadline_1s_long_clip"] = {k: r[k] for k in ("http", "state", "failure_code", "seconds")}
        rs["service_timeouts_counter"] = metrics()["timeouts"]
        stop_service(short)
        svc = start_service(a.model_subdir)
        wait_ready()
        r = transcribe(tl5, "long.webm")
        rs["recovered_default_deadline"] = {k: r[k] for k in ("http", "state", "status", "seconds")}
        sc["restart_and_recovery"] = rs
        # failures on the same container too, before looking at what it kept
        sc["final_container_failures"] = {n: transcribe(t, n)["failure_code"] for n, t in (("garbage.webm", tg), ("overlong.webm", to), ("silence.webm", ts))}

        # ---- item 9: nothing left behind, after successes and failures
        diff = subprocess.run(["docker", "diff", svc], capture_output=True, text=True).stdout.split("\n")
        files = sorted(os.listdir(work))
        dbbytes = b"".join(open(os.path.join(work, f), "rb").read() for f in files if f.startswith("flh.db"))
        leaked = [n for n, b in blob.items() if len(b) > 4096 and any(b[i:i + 48] in dbbytes for i in range(len(b) // 3, len(b) - 48, max(1, len(b) // 7)))]
        logs = "".join(open(p, encoding="utf-8").read() for p in flh["log"])
        svc_logs = subprocess.run(["docker", "logs", svc], capture_output=True, text=True).stderr
        words = [w for w in (first["text"] or "").split() if len(w) > 5][:5]
        sc["cleanup"] = {"service_container_changes": [d for d in diff if d], "flh_work_files": [f for f in files if f not in ("audio",)],
                         "audio_fragments_in_database": leaked, "transcript_words_in_flh_logs": [w for w in words if w in logs],
                         "transcript_words_in_service_logs": [w for w in words if w in svc_logs], "authorization_in_service_logs": "Bearer" in svc_logs}
        rep["service_peak_memory_mib"] = {n: round(m.peak_mib, 1) for n, m in mem.items()}
        rep["service_metrics_final"] = metrics()
    finally:
        stop_flh()
        for n in names:
            stop_service(n)
        for m in mem.values():
            m.stop = True
    with open(os.path.join(work, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1, sort_keys=True, default=list)
    print(json.dumps(rep["scenarios"], ensure_ascii=False, indent=1, sort_keys=True, default=list))
    return 0


def _span(start, end):
    if not start or not end:
        return None
    import re
    from datetime import datetime
    f = lambda s: datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", s).replace("Z", "+00:00"))  # noqa: E731
    return round((f(end) - f(start)).total_seconds(), 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep")
    p.add_argument("--data", required=True)
    p.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("--repo", required=True)
    r.add_argument("--work", required=True)
    r.add_argument("--sources", required=True)
    r.add_argument("--server-bin", required=True)
    r.add_argument("--model-subdir", required=True)
    r.add_argument("--other-model-subdir")
    r.add_argument("--image", default="flh-speaking:cpu-dev")
    a = ap.parse_args()
    return prep(a.data, a.out) if a.cmd == "prep" else run(a)


if __name__ == "__main__":
    sys.exit(main())
