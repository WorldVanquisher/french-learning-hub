"""Latency and peak memory of the extraction service on repeatable synthetic traffic (local only).

  python3 -I -B scripts/service_bench.py [--cold-runs 5] [--warm 200] [--image TAG] [--oom-score-adj N] [--json OUT]

Traffic: the R4 corpus requests (reviews of one to three revisions, feeds with a previous
feed) plus the largest legal request of the runtime rehearsal, in a fixed order. No learner
data, no network beyond loopback.

* **cold**: ``--cold-runs`` fresh server processes (or containers with ``--image``); for each,
  the time from start to ``/readyz`` 200 and the latency of the first request of each kind.
* **warm**: one server; ``--warm`` passes over the mix after one discarded pass; p50, p95 and
  max per kind.
* **memory**: host processes report peak RSS from ``wait4`` after a clean stop; containers
  report the cgroup's ``memory.peak``.

Results depend on the machine and its other load: the report records CPU, cores, Python,
kernel, the load average before and after, and the run counts. Compare runs from one
machine only.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "scripts"))

from flh_extraction import r4corpus as rc  # noqa: E402
from flh_extraction import service as svc  # noqa: E402

import runtime_rehearsal as rr  # noqa: E402

MIX = ("01-evidence-r1", "05-approved-r1", "09-revision-r3", "06-feed-r1", "12-feed-r3-restored")


def traffic() -> list[tuple[str, str, dict]]:
    sc = {s["name"]: s for s in rc.scenarios()}
    out = [(n, sc[n]["route"], sc[n]["request"]) for n in MIX]
    return out + [("largest-legal", "/v1/review", rr.large_request())]


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))], 2)


def timed(url: str, route: str, req: dict) -> float:
    t0 = time.perf_counter()
    st, d = svc.call(url, route, req, timeout=30)
    ms = (time.perf_counter() - t0) * 1000
    if st != 200:
        raise RuntimeError(f"{route}: {st} {d.get('error')}")
    return ms


class HostServer:
    def __init__(self):
        self.port = rr.free_port()
        # -I would drop the working directory from sys.path; the clean environment keeps PYTHON* settings out instead
        self.p = subprocess.Popen([sys.executable, "-B", "-m", "flh_extraction.service", "serve", "--port", str(self.port)], cwd=HERE,
                                  env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.url = f"http://127.0.0.1:{self.port}"

    def stop(self) -> float | None:
        if self.p.returncode is not None:
            return None
        self.p.send_signal(signal.SIGTERM)
        _, _, ru = os.wait4(self.p.pid, 0)
        self.p.returncode = 0
        return round(ru.ru_maxrss / 1024, 1)  # KiB -> MiB on Linux


class ContainerServer:
    n = 0

    def __init__(self, image: str, oom):
        ContainerServer.n += 1
        self.name = f"flh-extr-bench-{os.getpid()}-{ContainerServer.n}"
        self.port = rr.free_port()
        flags = rr.RUN_FLAGS + (["--oom-score-adj", str(oom)] if oom is not None else [])
        rr.sh("docker", "run", "-d", "--name", self.name, *flags, "-p", f"127.0.0.1:{self.port}:8090", image)
        self.url = f"http://127.0.0.1:{self.port}"

    def stop(self) -> float:
        try:
            peak = int(rr.sh("docker", "exec", self.name, "cat", "/sys/fs/cgroup/memory.peak"))
            return round(peak / 2 ** 20, 1)
        finally:
            rr.sh("docker", "rm", "-f", self.name, check=False)


def environment() -> dict:
    cpu = "unknown"
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            cpu = next((ln.split(":", 1)[1].strip() for ln in fh if ln.startswith("model name")), cpu)
    except OSError:
        pass
    return {"cpu": cpu, "cores": os.cpu_count(), "python": platform.python_version(), "kernel": platform.release(),
            "load_average_before": [round(x, 2) for x in os.getloadavg()]}


def run(cold_runs: int, warm: int, image: str | None, oom) -> dict:
    mix = traffic()
    make = (lambda: ContainerServer(image, oom)) if image else HostServer
    rep = {"schema": "flh_extraction_service_bench_v1", "mode": "container" if image else "host process", "environment": environment(),
           "deployment_id": None, "requests": [{"kind": n, "route": r, "bytes": len(json.dumps(q, ensure_ascii=False).encode())} for n, r, q in mix],
           "cold": {"runs": cold_runs, "ready_s": [], "first_ms": {n: [] for n, _, _ in mix}, "peak_mib": []},
           "warm": {"passes": warm, "ms": {}, "peak_mib": None}}
    for _ in range(cold_runs):
        s = make()
        try:
            rep["cold"]["ready_s"].append(rr.wait_ready(s.url))
            if rep["deployment_id"] is None:
                rep["deployment_id"] = svc.call(s.url, "/manifest")[1]["deployment_id"]
            for n, r, q in mix:
                rep["cold"]["first_ms"][n].append(round(timed(s.url, r, q), 2))
        finally:
            rep["cold"]["peak_mib"].append(s.stop())
    s = make()
    lat = {n: [] for n, _, _ in mix}
    try:
        rr.wait_ready(s.url)
        for n, r, q in mix:
            timed(s.url, r, q)
        t0 = time.perf_counter()
        for _ in range(warm):
            for n, r, q in mix:
                lat[n].append(timed(s.url, r, q))
        rep["warm"]["wall_s"] = round(time.perf_counter() - t0, 2)
    finally:
        rep["warm"]["peak_mib"] = s.stop()
    rep["warm"]["ms"] = {n: {"p50": pct(v, 0.5), "p95": pct(v, 0.95), "max": round(max(v), 2), "n": len(v)} for n, v in lat.items()}
    c = rep["cold"]
    c["summary"] = {"ready_s_median": pct(c["ready_s"], 0.5), "ready_s_max": max(c["ready_s"]),
                    "first_ms_median": {n: pct(v, 0.5) for n, v in c["first_ms"].items()}, "peak_mib_max": max(c["peak_mib"])}
    rep["environment"]["load_average_after"] = [round(x, 2) for x in os.getloadavg()]
    return rep


def render(rep: dict) -> str:
    e, c, w = rep["environment"], rep["cold"], rep["warm"]
    L = [f"Extraction service benchmark ({rep['mode']}), {rep['deployment_id']}",
         f"environment: {e['cpu']}, {e['cores']} cores, Python {e['python']}, kernel {e['kernel']}, load {e['load_average_before']} -> "
         f"{e['load_average_after']}",
         f"cold: {c['runs']} starts; ready median {c['summary']['ready_s_median']} s (max {c['summary']['ready_s_max']}); "
         f"peak memory max {c['summary']['peak_mib_max']} MiB",
         f"warm: {w['passes']} passes over {len(w['ms'])} kinds in {w.get('wall_s')} s; peak memory {w['peak_mib']} MiB",
         "kind                    bytes   cold first (median ms)   warm p50   p95    max"]
    by = {r["kind"]: r["bytes"] for r in rep["requests"]}
    for n, v in w["ms"].items():
        L.append(f"{n:22} {by[n]:7}   {c['summary']['first_ms_median'][n]:>10}            {v['p50']:>7} {v['p95']:>6} {v['max']:>7}")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cold-runs", type=int, default=5)
    ap.add_argument("--warm", type=int, default=200)
    ap.add_argument("--image")
    ap.add_argument("--oom-score-adj", type=int)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rep = run(a.cold_runs, a.warm, a.image, a.oom_score_adj)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rep, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(render(rep), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
