"""Service latency and resource benchmark (offline, loopback only).

  python3 -I tools/speaking/scripts/service_bench.py --sources DIR --data DIR --model-subdir openai/whisper-base/<rev> --out FILE

Starts the service container, records readiness transitions, then sends WAV
requests built from frozen test utterances at about 10, 30, 60 and 120 seconds
(three times each, sequentially) and reads `docker stats` while it runs. It
also sends one request twice to check that identical bytes give identical text.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never leave __pycache__ in the repository

import argparse
import json
import os
import subprocess
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from e2e_flh import call, free_port, wait  # noqa: E402


def multipart(fields: dict) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        if k == "file":
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="take.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + v + b"\r\n")
        else:
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    return b"".join(parts) + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


def post(url, body, ctype, timeout=300):
    import urllib.request
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": ctype})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()), time.monotonic() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--model-subdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--image", default="flh-speaking:cpu-dev")
    ap.add_argument("--memory", default="1536m")
    a = ap.parse_args()
    work = os.path.dirname(os.path.abspath(a.out))
    uid = os.getuid()
    prep = ("import sys; sys.path.insert(0,'/opt/program'); from flh_speaking import evaluate, audio; import numpy as np\n"
            "rows = evaluate.load_rows('/data', 'test'); xs = [evaluate.read_audio('/data', r) for r in rows[:12]]\n"
            "allx = np.concatenate(xs)\n"
            "for s in (10, 30, 60, 120):\n"
            "    open(f'/out/bench-{s}s.wav','wb').write(audio.to_wav_pcm16(allx[: s * 16000]))\n")
    subprocess.run(["docker", "run", "--rm", "--oom-score-adj", "1000", "--network", "none", "--memory", "1g", "--user", f"{uid}:{os.getgid()}", "-e", "HOME=/tmp",
                    "-v", f"{PKG}/flh_speaking:/opt/program/flh_speaking:ro", "-v", f"{os.path.abspath(a.data)}:/data:ro", "-v", f"{work}:/out",
                    "--entrypoint", "python3", a.image, "-B", "-c", prep], check=True)
    port = free_port()
    name = f"flh-speaking-bench-{uuid.uuid4().hex[:8]}"
    t_start = time.monotonic()
    subprocess.run(["docker", "run", "-d", "--oom-score-adj", "1000", "--name", name, "-p", f"127.0.0.1:{port}:8765", "--memory", a.memory, "--memory-swap", a.memory, "--cpus", "4",
                    "--user", f"{uid}:{os.getgid()}", "-e", "HOME=/tmp", "-v", f"{PKG}/flh_speaking:/opt/program/flh_speaking:ro",
                    "-v", f"{os.path.abspath(a.sources)}:/sources:ro", a.image, "serve", "--model", f"/sources/{a.model_subdir}", "--host", "0.0.0.0", "--port", "8765"],
                   check=True, stdout=subprocess.DEVNULL)
    peak = {"mem_mib": 0.0}
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", name], capture_output=True, text=True).stdout.strip()
            try:
                v, unit = out.split("/")[0].strip()[:-3], out.split("/")[0].strip()[-3:]
                mib = float(v) * (1024 if unit == "GiB" else 1)
                peak["mem_mib"] = max(peak["mem_mib"], mib)
            except (ValueError, IndexError):
                pass
            time.sleep(0.5)
    th = threading.Thread(target=sample, daemon=True)
    th.start()
    report: dict = {"model_subdir": a.model_subdir, "memory_limit": a.memory}
    try:
        url = f"http://127.0.0.1:{port}"
        report["readiness_transitions"] = wait(url + "/readyz", lambda s: s[0] == 200 or s[1] == "failed")
        report["ready_after_s"] = round(time.monotonic() - t_start, 2)
        rd = call(url + "/readyz")[1]
        report["load_s"], report["warm_s"], report["deployment_id"] = rd["load_s"], rd["warm_s"], rd["deployment_id"]
        report["idle_mem_mib"] = peak["mem_mib"]
        lat = {}
        for s in (10, 30, 60, 120):
            blob = open(os.path.join(work, f"bench-{s}s.wav"), "rb").read()
            body, ct = multipart({"file": blob, "model": rd["deployment_id"], "response_format": "json"})
            runs = []
            for _ in range(3):
                doc, secs = post(url + "/v1/audio/transcriptions", body, ct)
                runs.append({"wall_s": round(secs, 3), "model_s": doc["flh"]["timing"]["model_s"], "decode_s": doc["flh"]["timing"]["decode_s"],
                             "windows": doc["flh"]["windows"], "status": doc["flh"]["status"], "text_sha256": __import__("hashlib").sha256(doc["text"].encode()).hexdigest()[:16]})
            lat[f"{s}s"] = {"runs": runs, "identical_text": len({r["text_sha256"] for r in runs}) == 1,
                            "median_wall_s": sorted(r["wall_s"] for r in runs)[1], "rtf": round(sorted(r["wall_s"] for r in runs)[1] / s, 3)}
        report["latency"] = lat
        report["peak_mem_mib"] = round(peak["mem_mib"], 1)
        report["metrics"] = call(url + "/metrics")[1]
        report["tmp_entries_after"] = subprocess.run(["docker", "exec", name, "sh", "-c", "ls -A /tmp | wc -l"], capture_output=True, text=True).stdout.strip()
    finally:
        stop.set()
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, sort_keys=True)
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
