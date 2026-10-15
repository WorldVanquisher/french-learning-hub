#!/usr/bin/env python3
"""FLH-081 resource measurement of a packaged public-demo server (Linux).

    unshare -rn python3 -B scripts/validation/flh081/resource_probe.py --pkg /abs/package \
        --work /abs/new/dir [--port 18987] [--requests 2000] [--concurrency 8]

Inside `unshare -rn` (loopback only), it does the following:
- starts the package with its own deploy/ctl.sh and times start-to-ready;
- reads VmRSS and Threads of the recorded pid;
- sends a bounded mixed GET load over loopback: static index, keyword
  search, Concept detail, unit source, and preset semantic and hybrid search;
- reports latency percentiles, peak RSS (VmHWM), CPU seconds and errors;
- stops the server.

These are sizing inputs on this NAS, not a load test of a public deployment.
The output is WORK/resources.json.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import http.client

PATHS = ["/", "/api/knowledge-library/concepts?q=subj", "/api/knowledge-library/concepts/1",
         "/api/knowledge-library/units/1/source", "/api/knowledge-library/demo/semantic-search?preset=no-longer",
         "/api/knowledge-library/demo/hybrid-search?preset=subjunctive&state=active"]


def status(pid):
    out = {}
    for line in open(f"/proc/{pid}/status"):
        k, _, v = line.partition(":")
        if k in ("VmRSS", "VmHWM", "Threads"):
            out[k] = v.strip()
    stat = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
    tck = os.sysconf("SC_CLK_TCK")
    out["cpu_seconds"] = round((int(stat[11]) + int(stat[12])) / tck, 2)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pkg", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--port", type=int, default=18987)
    p.add_argument("--requests", type=int, default=2000)
    p.add_argument("--concurrency", type=int, default=8)
    a = p.parse_args()
    if os.path.lexists(a.work):
        print("refused: --work exists", file=sys.stderr)
        return 2
    os.makedirs(a.work)
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    env = {**os.environ, "PORT": str(a.port)}
    ctl = os.path.join(a.pkg, "deploy", "ctl.sh")
    run = os.path.join(a.work, "run")
    t0 = time.monotonic()
    r = subprocess.run([ctl, "start", run], env=env, capture_output=True, text=True, timeout=60)
    ready_s = round(time.monotonic() - t0, 2)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    pid = int(open(os.path.join(run, "flh-public-demo.pid")).read())
    idle = status(pid)
    lat, errors, lock = [], [], threading.Lock()
    per = a.requests // a.concurrency

    def worker(k):
        c = http.client.HTTPConnection("127.0.0.1", a.port, timeout=10)
        for i in range(per):
            path = PATHS[(k + i) % len(PATHS)]
            s = time.perf_counter()
            try:
                c.request("GET", path)
                resp = c.getresponse()
                resp.read()
                ok = resp.status == 200
            except OSError as e:
                ok = False
                c.close()
                c = http.client.HTTPConnection("127.0.0.1", a.port, timeout=10)
            d = time.perf_counter() - s
            with lock:
                lat.append(d)
                if not ok:
                    errors.append(path)
        c.close()

    w0 = time.monotonic()
    ts = [threading.Thread(target=worker, args=(k,)) for k in range(a.concurrency)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    wall = time.monotonic() - w0
    loaded = status(pid)
    subprocess.run([ctl, "stop", run], env=env, capture_output=True, text=True, timeout=60)
    lat.sort()
    q = lambda f: round(lat[min(len(lat) - 1, int(f * len(lat)))] * 1000, 2)
    out = {"schema": "flh081_resource_probe_v1", "start_to_ready_s": ready_s, "idle": idle, "after_load": loaded,
           "requests": len(lat), "concurrency": a.concurrency, "errors": len(errors), "wall_s": round(wall, 2),
           "throughput_rps": round(len(lat) / wall, 1), "latency_ms": {"p50": q(0.5), "p95": q(0.95), "p99": q(0.99),
                                                                        "max": round(lat[-1] * 1000, 2)},
           "paths": PATHS, "stopped": not os.path.exists(f"/proc/{pid}")}
    json.dump(out, open(os.path.join(a.work, "resources.json"), "w"), indent=2)
    print(json.dumps(out, indent=2))
    return 0 if not errors and out["stopped"] else 1


if __name__ == "__main__":
    sys.exit(main())
