"""End-to-end check through FLH's own Speaking API (no provider, no network).

  python3 -I tools/speaking/scripts/e2e_flh.py --repo . --work DIR --sources DIR --data DIR \
      --model-subdir openai/whisper-base/<rev> [--server-bin BIN] [--provider openai|local] [--image flh-speaking:cpu-dev]

1. starts the transcription service container (published on 127.0.0.1 only) and
   records /readyz until it turns ready (loading vs usable inference);
2. starts FLH's server with a scrubbed environment (no inherited keys), a fresh
   database in DIR, and the Speaking transcription provider pointed at the service;
3. drives the existing API: start a prompt, add a take (webm/opus of a frozen test
   utterance), transcribe it, replay the same Idempotency-Key, confirm the
   transcript, transcribe a silent take, then stop the service and transcribe again;
4. writes DIR/e2e.json (statuses, timings, counters) and DIR/fixtures/*.json
   (real backend responses, for frontend development).
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
import time
import urllib.error
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(url, method="GET", body=None, headers=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null"), dict(r.headers), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            doc = json.loads(raw)
        except ValueError:
            doc = {"raw": raw.decode("utf-8", "replace")[:200]}
        return e.code, doc, dict(e.headers), time.monotonic() - t0


def wait(url, until, timeout=300, every=0.5):
    seen, t0 = [], time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            code, doc, _, _ = call(url, timeout=5)
            state = (code, (doc or {}).get("status"))
        except Exception as e:  # noqa: BLE001 - connection refused while starting
            state = ("down", type(e).__name__)
        if not seen or seen[-1][1:] != state:
            seen.append((round(time.monotonic() - t0, 2),) + state)
        if until(state):
            return seen
        time.sleep(every)
    raise SystemExit(f"timeout waiting for {url}: {seen}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--model-subdir", required=True)
    ap.add_argument("--server-bin")
    ap.add_argument("--provider", choices=("openai", "local"), default="openai")
    ap.add_argument("--image", default="flh-speaking:cpu-dev")
    a = ap.parse_args()
    work = os.path.abspath(a.work)
    os.makedirs(os.path.join(work, "fixtures"), exist_ok=True)
    report: dict = {"provider_setting": a.provider, "steps": {}}
    uid = os.getuid()

    # -- audio: a frozen test utterance as webm/opus (browser-like) and 3 s of silence
    prep = ("import json,sys; sys.path.insert(0,'/opt/program'); from flh_speaking import evaluate, probes, audio; import numpy as np\n"
            "rows = evaluate.load_rows('/data', 'test'); r = rows[0]; x = evaluate.read_audio('/data', r)\n"
            "open('/out/take.webm','wb').write(probes.encode(x, 'webm', 'libopus', rate=48000))\n"
            "open('/out/silence.webm','wb').write(probes.encode(np.zeros(3*16000, np.float32), 'webm', 'libopus', rate=48000))\n"
            "json.dump({'id': r['id'], 'ref': r['text'], 'seconds': r['seconds']}, open('/out/take.json','w'), ensure_ascii=False)\n")
    subprocess.run(["docker", "run", "--rm", "--oom-score-adj", "1000", "--network", "none", "--memory", "1g", "--user", f"{uid}:{os.getgid()}", "-e", "HOME=/tmp",
                    "-v", f"{PKG}/flh_speaking:/opt/program/flh_speaking:ro", "-v", f"{os.path.abspath(a.data)}:/data:ro", "-v", f"{work}:/out",
                    "--entrypoint", "python3", a.image, "-B", "-c", prep], check=True)
    take = json.load(open(os.path.join(work, "take.json"), encoding="utf-8"))
    audio_bytes = open(os.path.join(work, "take.webm"), "rb").read()
    silence = open(os.path.join(work, "silence.webm"), "rb").read()

    # -- transcription service
    sport = free_port()
    name = f"flh-speaking-e2e-{uuid.uuid4().hex[:8]}"
    model_dir = f"/sources/{a.model_subdir}"
    subprocess.run(["docker", "run", "-d", "--oom-score-adj", "1000", "--name", name, "-p", f"127.0.0.1:{sport}:8765", "--memory", "2g", "--memory-swap", "2g", "--cpus", "4",
                    "--user", f"{uid}:{os.getgid()}", "-e", "HOME=/tmp", "-v", f"{PKG}/flh_speaking:/opt/program/flh_speaking:ro",
                    "-v", f"{os.path.abspath(a.sources)}:/sources:ro", a.image, "serve", "--model", model_dir, "--host", "0.0.0.0", "--port", "8765"],
                   check=True, stdout=subprocess.DEVNULL)
    server = None
    try:
        surl = f"http://127.0.0.1:{sport}"
        report["readiness_transitions"] = wait(surl + "/readyz", lambda s: s[0] == 200 or s[1] == "failed")
        manifest = call(surl + "/manifest")[1]
        dep = manifest["deployment_id"]
        report["deployment_id"] = dep
        report["manifest_sha256"] = manifest["manifest_sha256"]
        json.dump(manifest, open(os.path.join(work, "manifest.json"), "w"), indent=1, sort_keys=True)

        # -- FLH server (scrubbed environment)
        fport = free_port()
        env = {"PATH": "/usr/bin:/bin", "HOME": work, "DB_PATH": os.path.join(work, "flh.db"), "PORT": str(fport), "LISTEN_HOST": "127.0.0.1",
               "TMPDIR": work}
        if a.provider == "openai":
            env.update({"SPEAKING_TRANSCRIPTION_PROVIDER": "openai", "SPEAKING_TRANSCRIPTION_MODEL": dep, "OPENAI_BASE_URL": surl + "/v1",
                        "OPENAI_API_KEY": "local-not-a-secret", "OPENAI_TIMEOUT": "120"})
        else:
            env.update({"SPEAKING_TRANSCRIPTION_PROVIDER": "local", "SPEAKING_TRANSCRIPTION_MODEL": dep,
                        "SPEAKING_TRANSCRIPTION_BASE_URL": surl + "/v1", "SPEAKING_TRANSCRIPTION_TIMEOUT": "120"})
        log = open(os.path.join(work, "flh-server.log"), "w")
        server = subprocess.Popen([a.server_bin], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=work)
        furl = f"http://127.0.0.1:{fport}"
        wait(furl + "/healthz", lambda s: s[0] == 200, timeout=60)

        st = report["steps"]
        code, prompts, _, _ = call(furl + "/speaking/prompts")
        pid = (prompts.get("prompts") if isinstance(prompts, dict) else prompts)[0]["id"]
        code, ex, _, _ = call(furl + f"/speaking/prompts/{pid}", "POST")
        st["start_prompt"] = code
        exid = ex["exercise"]["id"] if "exercise" in ex else ex["id"]

        def add_take(blob, ms):
            code, v, _, _ = call(furl + f"/speaking/exercises/{exid}/takes", "POST", {
                "audio_source": "recording", "audio_mime": "audio/webm", "audio_bytes": len(blob),
                "audio_sha256": hashlib.sha256(blob).hexdigest(), "duration_ms": ms})
            assert code == 201, (code, v)
            return v["takes"][-1]["id"] if "takes" in v else v["exercise"]["takes"][-1]["id"]

        tid = add_take(audio_bytes, int(take["seconds"] * 1000))
        key = str(uuid.uuid4())
        body = {"audio_base64": base64.b64encode(audio_bytes).decode(), "audio_mime": "audio/webm"}
        before = call(surl + "/metrics")[1]["counters"]
        code, res, hdr, secs = call(furl + f"/speaking/takes/{tid}/transcriptions", "POST", body, {"Idempotency-Key": key})
        st["transcribe"] = {"http": code, "seconds": round(secs, 3), "status": (res.get("transcription") or {}).get("status"),
                            "transcriber": (res.get("transcription") or {}).get("transcriber")}
        json.dump(res, open(os.path.join(work, "fixtures", "transcription-created.json"), "w"), ensure_ascii=False, indent=1)
        text = (res.get("transcription") or {}).get("text") or ""
        sys.path.insert(0, PKG)
        from flh_speaking import textnorm
        st["transcribe"]["wer_vs_reference"] = textnorm.rate([textnorm.score(take["ref"], text)])["wer"]
        code2, res2, hdr2, secs2 = call(furl + f"/speaking/takes/{tid}/transcriptions", "POST", body, {"Idempotency-Key": key})
        after = call(surl + "/metrics")[1]["counters"]
        st["replay_same_key"] = {"http": code2, "replayed_header": hdr2.get("Idempotency-Replayed"), "same_text": (res2.get("transcription") or {}).get("text") == text,
                                 "service_requests_before": before["requests"], "service_requests_after": after["requests"], "seconds": round(secs2, 3)}
        json.dump(res2, open(os.path.join(work, "fixtures", "transcription-replayed.json"), "w"), ensure_ascii=False, indent=1)
        code, rq, _, _ = call(furl + f"/speaking/transcription-requests/{key}")
        st["request_lookup"] = {"http": code, "state": (rq.get("request") or {}).get("state")}
        json.dump(rq, open(os.path.join(work, "fixtures", "transcription-request.json"), "w"), ensure_ascii=False, indent=1)
        trid = (res.get("transcription") or {}).get("id")
        code, conf, _, _ = call(furl + f"/speaking/takes/{tid}/transcripts", "POST", {"text": text, "transcription_id": trid})
        st["confirm_transcript"] = {"http": code}
        json.dump(conf, open(os.path.join(work, "fixtures", "transcript-confirmed.json"), "w"), ensure_ascii=False, indent=1)

        sid = add_take(silence, 3000)
        code, res3, _, secs3 = call(furl + f"/speaking/takes/{sid}/transcriptions", "POST",
                                    {"audio_base64": base64.b64encode(silence).decode(), "audio_mime": "audio/webm"}, {"Idempotency-Key": str(uuid.uuid4())})
        st["silent_take"] = {"http": code, "status": (res3.get("transcription") or {}).get("status"),
                             "failure_code": (res3.get("transcription") or {}).get("failure_code"), "seconds": round(secs3, 3)}
        json.dump(res3, open(os.path.join(work, "fixtures", "transcription-no-speech.json"), "w"), ensure_ascii=False, indent=1)
        report["service_tmp_after"] = subprocess.run(["docker", "exec", name, "sh", "-c", "ls -A /tmp | wc -l"], capture_output=True, text=True).stdout.strip()
        report["service_log_lines"] = subprocess.run(["docker", "logs", name], capture_output=True, text=True).stderr.splitlines()[-8:]
        report["service_log_mentions_transcript"] = any(w in "\n".join(subprocess.run(["docker", "logs", name], capture_output=True, text=True).stderr.splitlines())
                                                        for w in text.split()[:3] if len(w) > 4)
        subprocess.run(["docker", "stop", "-t", "5", name], check=True, stdout=subprocess.DEVNULL)
        uid2 = add_take(audio_bytes, int(take["seconds"] * 1000))
        code, res4, _, secs4 = call(furl + f"/speaking/takes/{uid2}/transcriptions", "POST", body, {"Idempotency-Key": str(uuid.uuid4())})
        st["service_down"] = {"http": code, "status": (res4.get("transcription") or {}).get("status"),
                              "failure_code": (res4.get("transcription") or {}).get("failure_code"), "seconds": round(secs4, 3)}
        json.dump(res4, open(os.path.join(work, "fixtures", "transcription-service-down.json"), "w"), ensure_ascii=False, indent=1)
        report["take"] = take["id"]
        report["take_seconds"] = take["seconds"]
    finally:
        if server:
            server.terminate()
            server.wait(10)
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    json.dump(report, open(os.path.join(work, "e2e.json"), "w"), ensure_ascii=False, indent=1, sort_keys=True)
    print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
