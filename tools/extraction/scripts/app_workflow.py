"""FLH capture -> extraction service, as an application workflow (local rehearsal; synthetic data only).

  python3 -I -B scripts/app_workflow.py --server-bin BIN --work NEW_DIR [--service-url URL] [--repeat 20] [--json OUT]

1. Starts the FLH Go server built from this checkout on a free loopback port with its own
   SQLite file in NEW_DIR, a clean environment and every provider disabled (no .env is read:
   the working directory is NEW_DIR).
2. For each shipped synthetic contrast (y/en, savoir/connaître, à/en), imports the capture
   through ``POST /captures``, reads it back (``GET /entries/{id}``), and sends the stored
   learner text with the fixture's proposal to the extraction service (``POST /v1/review``).
   The service must ground the quotes in the text FLH stored, byte for byte.
3. Provider failure keeps learner input: ``POST /entries/{id}/extractions`` with the
   extractor disabled must be refused (503) and leave the entry unchanged.
4. Unavailable upstream: with the extraction service stopped, one review call reports
   ``unavailable`` and is not retried; FLH is unaffected; an explicit retry after a restart
   succeeds.
5. Latency: ``--repeat`` review calls per case; p50 / p95 / max in milliseconds.

The report (``--json``) carries IDs, counts, statuses and timings only, never learner text.
Without ``--service-url`` an in-process service is started on a free loopback port.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from flh_extraction import packet as pk  # noqa: E402
from flh_extraction import practice as pr  # noqa: E402
from flh_extraction import service as svc  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "practice_v1")
CASES = ("y_en.r1.json", "savoir_connaitre.json", "a_en_lieux.json")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http(method: str, url: str, doc=None, timeout: float = 10.0) -> tuple[int, dict]:
    data = None if doc is None else json.dumps(doc, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {}


def start_flh(binary: str, work: str) -> tuple[subprocess.Popen, str]:
    port = free_port()
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": work, "PORT": str(port), "LISTEN_HOST": "127.0.0.1",
           "DB_PATH": os.path.join(work, "flh.db")}
    log = open(os.path.join(work, "flh-server.log"), "w", encoding="utf-8")  # noqa: SIM115 (closed with the process)
    p = subprocess.Popen([binary], cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
    p._flh_log = log  # type: ignore[attr-defined]
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if http("GET", url + "/readyz", timeout=1)[0] == 200:
                return p, url
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.1)
    p.terminate()
    raise RuntimeError("the FLH server did not become ready")


def stop_flh(p: subprocess.Popen) -> None:
    p.terminate()
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait(5)
    p._flh_log.close()  # type: ignore[attr-defined]


class InProcess:
    def __init__(self, port: int = 0):
        self.srv = svc.make_server("127.0.0.1", port)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.srv.state.pool.shutdown(wait=True)


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def run(binary: str, work: str, service_url: str | None, repeat: int) -> dict:
    if os.path.exists(work) and os.listdir(work):
        raise SystemExit("--work must be a new or empty directory")
    os.makedirs(work, exist_ok=True)
    inproc = None
    if service_url is None:
        inproc = InProcess()
        service_url = inproc.url
    flh, flh_url = start_flh(binary, work)
    report = {"schema": "flh_extraction_app_workflow_v1", "synthetic": True, "service": {}, "cases": [], "checks": {}}
    try:
        _, man = svc.call(service_url, "/manifest")
        dep = man["deployment_id"]
        report["service"] = {"deployment_id": dep, "contract": man["contract"], "code_id": man["code_id"][:16]}
        for name in CASES:
            with open(os.path.join(FIX, name), encoding="utf-8") as fh:
                src = json.load(fh)
            cap = {k: src["capture"][k] for k in ("schema_version", "original_input", "original_context", "source")}
            cap["capture_id"] = "app-workflow-" + src["source_id"]
            t0 = time.monotonic()
            st, created = http("POST", flh_url + "/captures", cap)
            t_capture = (time.monotonic() - t0) * 1000
            entry_id = created.get("entry_id") or (created.get("entry") or {}).get("id")
            st2, entry = http("GET", f"{flh_url}/entries/{entry_id}")
            stored = {"original_input": entry.get("original_input"), "original_context": entry.get("original_context")}
            same_text = stored == {k: src["capture"][k] for k in stored}
            doc = json.loads(json.dumps(src))
            doc["capture"].update(stored)
            t0 = time.monotonic()
            st3, rv_doc = svc.call(service_url, "/v1/review", svc.request(sources=[doc]), expect_deployment=dep)
            t_review = (time.monotonic() - t0) * 1000
            local = pr.draft(src)
            times = []
            for _ in range(repeat):
                t0 = time.monotonic()
                svc.call(service_url, "/v1/review", svc.request(sources=[doc]))
                times.append((time.monotonic() - t0) * 1000)
            st4, refused = http("POST", f"{flh_url}/entries/{entry_id}/extractions", {})
            st5, after = http("GET", f"{flh_url}/entries/{entry_id}")
            gr = [g["status"] for i in rv_doc.get("items", []) for g in i["groundings"]]
            report["cases"].append({
                "fixture": name, "capture_http": st, "entry_id": entry_id, "read_back_http": st2, "stored_text_equals_capture": same_text,
                "review_http": st3, "draft_id": rv_doc.get("draft_id"), "draft_id_equals_local": rv_doc.get("draft_id") == local["draft_id"],
                "items": len(rv_doc.get("items", [])), "groundings": {s: gr.count(s) for s in sorted(set(gr))},
                "flagged_by_cues": sum(1 for i in rv_doc.get("items", []) if i["cues"]), "batch_size": len(rv_doc.get("plan", {}).get("selected", [])),
                "left_for_learner": len(rv_doc.get("plan", {}).get("left_for_you", [])),
                "extractor_disabled_http": st4, "extractor_disabled_error_present": bool(refused.get("error")),
                "entry_unchanged_after_refusal": after == entry,
                "ms": {"capture": round(t_capture, 1), "first_review": round(t_review, 1), "review_p50": pct(times, 0.5), "review_p95": pct(times, 0.95),
                       "review_max": round(max(times), 1), "n": repeat}})
        # unavailable upstream: stop the in-process service, one call, no retry, FLH unaffected, explicit retry after restart
        if inproc:
            port = int(inproc.url.rsplit(":", 1)[1])
            inproc.stop()
            t0 = time.monotonic()
            st, err = svc.call(f"http://127.0.0.1:{port}", "/v1/review", svc.request(sources=[src]), timeout=2)
            dt = (time.monotonic() - t0) * 1000
            flh_ok = http("GET", flh_url + "/readyz")[0] == 200
            entries_ok = http("GET", f"{flh_url}/entries/{report['cases'][0]['entry_id']}")[0] == 200
            inproc = InProcess(port)
            st_retry, _ = svc.call(inproc.url, "/v1/review", svc.request(sources=[src]))
            report["checks"]["unavailable_upstream"] = {"first_call": st, "code": err.get("error", {}).get("type"), "ms": round(dt, 1),
                                                         "automatic_retries": 0, "flh_still_ready": flh_ok, "entry_readable": entries_ok,
                                                         "explicit_retry_after_restart": st_retry}
    finally:
        stop_flh(flh)
        if inproc:
            inproc.stop()
    cs = report["cases"]
    report["checks"].update({
        "every_capture_stored": all(c["capture_http"] in (200, 201) for c in cs),
        "stored_text_equals_capture": all(c["stored_text_equals_capture"] for c in cs),
        "service_grounds_flh_text_like_the_library": all(c["draft_id_equals_local"] for c in cs),
        "extractor_failure_keeps_learner_input": all(c["extractor_disabled_http"] == 503 and c["entry_unchanged_after_refusal"] for c in cs)})
    text = json.dumps(report, ensure_ascii=False)
    report["checks"]["report_privacy_findings"] = len(pk.privacy_findings(text))
    report["checks"]["report_contains_learner_text"] = any(src_text in text for src_text in ("boulangerie", "restaurant", "pompiers"))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server-bin", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--service-url")
    ap.add_argument("--repeat", type=int, default=20)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rep = run(os.path.abspath(a.server_bin), os.path.abspath(a.work), a.service_url, a.repeat)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rep, indent=1, sort_keys=True) + "\n")
    for c in rep["cases"]:
        print(f"{c['fixture']}: capture {c['capture_http']}, stored text equal {c['stored_text_equals_capture']}, review {c['review_http']} "
              f"draft equal {c['draft_id_equals_local']}, groundings {c['groundings']}, cue flags {c['flagged_by_cues']}, batch {c['batch_size']}, "
              f"extractor disabled -> {c['extractor_disabled_http']} entry unchanged {c['entry_unchanged_after_refusal']}, review p50 {c['ms']['review_p50']} ms "
              f"p95 {c['ms']['review_p95']} ms")
    for k, v in rep["checks"].items():
        print(f"{k}: {v}")
    ok = all(v is True for k, v in rep["checks"].items() if isinstance(v, bool) and k != "report_contains_learner_text") \
        and not rep["checks"]["report_contains_learner_text"] and rep["checks"]["report_privacy_findings"] == 0
    u = rep["checks"].get("unavailable_upstream")
    if u is not None:
        ok = ok and u["first_call"] == 0 and u["code"] == "unavailable" and u["flh_still_ready"] and u["entry_readable"] and u["explicit_retry_after_restart"] == 200
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
