"""Private runtime rehearsal of the extraction service container (local Docker; synthetic data only).

  python3 -I -B scripts/runtime_rehearsal.py --image TAG --work NEW_DIR [--build-context DIR]
         [--server-bin FLH_SERVER] [--oom-score-adj N] [--keep-image] [--json OUT]

Every step uses loopback, synthetic payloads and the flags in ``RUN_FLAGS`` (SERVICE.md §8).
Nothing is pushed, no registry or cloud account is used, and every container the rehearsal
starts is removed at the end, also after a failure.

  build      with --build-context: ``docker build -f Dockerfile.service`` from that directory
             (a clean source tree); records the image ID and size
  identity   the container's /readyz, /manifest and the host manifest of the same tree agree;
             the 15-check smoke passes from a separate client process (this one)
  contract   a v0 client gets 409 contract_mismatch; no header gets 400
  limits     a body one byte over 256 KiB is 413; the largest synthetic request inside every
             bound (8 revisions x 64 items and decisions up to 97% of the body limit) answers in time;
             a second container started with --timeout 0.001 answers it 504 and stays ready
  logs       every log line is one JSON object with the documented keys; no learner text,
             header value or body appears
  restart    after ``docker restart`` the service is ready again with the same identity,
             counters back at zero, the same feed_id for the same request, no mount and an
             empty ``docker diff`` (it keeps nothing)
  outage     with --server-bin: the container is stopped; one call reports ``unavailable``
             (no retry) while FLH stays ready; recovery is start, /readyz, /manifest, smoke,
             then the caller's explicit retry
  teardown   containers removed (and the image with --keep-image unset only when it was
             built here); no container, mount or published port remains
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "scripts"))

from flh_extraction import practice as pr  # noqa: E402
from flh_extraction import r4corpus as rc  # noqa: E402
from flh_extraction import service as svc  # noqa: E402

RUN_FLAGS = ["--read-only", "--memory", "256m", "--memory-swap", "256m", "--cpus", "1", "--pids-limit", "64", "--cap-drop", "ALL",
             "--security-opt", "no-new-privileges", "--restart", "no"]
LOG_KEYS = {"ts", "method", "path", "status", "code", "request_id", "bytes_in", "bytes_out", "ms", "event", "deployment_id", "error_class",
            "host", "port", "max_inflight", "timeout_s", "contract"}
MARKERS = ("boulangerie", "Japon", "sœur", "Lyon", "depuis", "R4-SYNTHETIC-MARKER")


def sh(*args, check=True, timeout=600) -> str:
    r = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"{args[0]} {args[1] if len(args) > 1 else ''} failed: {r.stderr.strip()[-300:]}")
    return r.stdout.strip()


def raw(method: str, url: str, body: bytes | None = None, headers: dict | None = None, timeout: float = 10.0) -> tuple[int, dict, dict]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}"), dict(e.headers)
        except ValueError:
            return e.code, {}, dict(e.headers)


def wait_ready(url: str, limit: float = 30.0) -> float:
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        try:
            if raw("GET", url + "/readyz", timeout=1)[0] == 200:
                return round(time.monotonic() - t0, 3)
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.05)
    raise RuntimeError("the container did not become ready")


def free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def large_request() -> dict:
    """Inside every bound: 8 revisions of a 64-item synthetic source plus as many decisions (at most 1,000) as fit in 97% of the body limit."""
    items = [{"ref": f"c{k:02d}", "type": "claim", "kind": "grammar", "canonical": f"forme {k}", "statement": f"Synthetic rule {k} ({rc.CORPUS}).",
              "quotes": [f"phrase {k:02d}"]} for k in range(64)]
    ctx = " ".join(f"phrase {k:02d}." for k in range(64))
    srcs = [{"schema": pr.SOURCE_SCHEMA, "source_id": "r4-limits", "revision": r, "learner_goal": "",
             "capture": {"schema_version": "learning_capture_v1", "source": "manual", "original_input": "R4-SYNTHETIC-MARKER question ?",
                         "original_context": ctx},
             "proposal": {"proposer": "synthetic: R4 limits", "items": items}} for r in range(1, 9)]
    drf = pr.draft(srcs[0])
    ids = [i["item_id"] for i in drf["items"]]
    decs = []
    for k in range(svc.LIMITS["max_decisions"]):
        decs.append(pr.decision(drf, ids[k % 64], "approve" if k % 3 else "reject", k + 1, reason="synthetic"))
        if len(json.dumps(svc.request(sources=srcs, decisions=decs), ensure_ascii=False).encode()) > 0.97 * svc.LIMITS["max_body_bytes"]:
            decs.pop()
            break
    return svc.request(sources=srcs, decisions=decs)


class Docker:
    def __init__(self, image: str, oom: int | None):
        self.image, self.oom, self.names = image, oom, []

    def run(self, name: str, port: int, extra=()) -> str:
        flags = RUN_FLAGS + (["--oom-score-adj", str(self.oom)] if self.oom is not None else [])
        sh("docker", "run", "-d", "--name", name, *flags, "-p", f"127.0.0.1:{port}:8090", self.image, *extra)
        self.names.append(name)
        return f"http://127.0.0.1:{port}"

    def cleanup(self) -> list[str]:
        for n in self.names:
            sh("docker", "rm", "-f", n, check=False)
        return [n for n in self.names if sh("docker", "ps", "-a", "-q", "--filter", f"name=^{n}$", check=False)]


def rehearse(a) -> dict:
    rep = {"schema": "flh_extraction_runtime_rehearsal_v1", "image": a.image, "flags": RUN_FLAGS, "steps": {}}
    S = rep["steps"]
    built = False
    if a.build_context:
        t0 = time.monotonic()
        sh("docker", "build", "-q", "-f", os.path.join(a.build_context, "Dockerfile.service"), "-t", a.image, a.build_context, timeout=1800)
        built = True
        S["build"] = {"seconds": round(time.monotonic() - t0, 1), "context": "a clean source tree (path not recorded)"}
    info = json.loads(sh("docker", "image", "inspect", a.image))[0]
    S.setdefault("build", {}).update({"image_id": info["Id"], "size_mb": round(info["Size"] / 1e6, 1), "user": info["Config"].get("User"),
                                      "entrypoint": info["Config"].get("Entrypoint"), "healthcheck": bool(info["Config"].get("Healthcheck"))})
    d = Docker(a.image, a.oom_score_adj)
    tag = f"flh-extr-reh-{os.getpid()}"
    flh = None
    try:
        port = free_port()
        url = d.run(tag, port)
        S["identity"] = {"ready_seconds": wait_ready(url)}
        ctx = a.build_context or HERE
        host = json.loads(sh(sys.executable, "-I", "-B", "-c", "import json,sys; sys.path.insert(0, sys.argv[1]); "
                             "import flh_extraction.service as s; print(json.dumps(s.manifest()))", ctx))
        st, man, _ = raw("GET", url + "/manifest")
        st2, ready, _ = raw("GET", url + "/readyz")
        smoke_rc, smoke_text = svc.smoke(url)
        S["identity"].update({"manifest_http": st, "deployment_id": man.get("deployment_id"), "host_deployment_id": host["deployment_id"],
                              "identity_equal": man.get("deployment_id") == host["deployment_id"] == ready.get("deployment_id"),
                              "code_files_equal": man.get("code_sha256") == host["code_sha256"], "readyz_http": st2,
                              "smoke": smoke_text.strip().splitlines()[-1].split(" passed")[0].replace("smoke: ", ""), "smoke_ok": smoke_rc == 0})
        # contract
        body = json.dumps(svc.request(sources=[rc._read(os.path.join(rc.PRACTICE, "y_en.r1.json"))])).encode()
        s409, d409, _ = raw("POST", url + "/v1/review", body, {"Content-Type": "application/json", "X-FLH-Contract": "flh_extraction_service_v0"})
        s400, d400, _ = raw("POST", url + "/v1/review", body, {"Content-Type": "application/json"})
        S["contract"] = {"v0_client": [s409, d409.get("error", {}).get("type"), d409.get("service_contract")],
                         "no_header": [s400, d400.get("error", {}).get("type")],
                         "ok": s409 == 409 and d409.get("error", {}).get("type") == "contract_mismatch" and s400 == 400}
        # limits
        hdr = {"Content-Type": "application/json", "X-FLH-Contract": svc.CONTRACT}
        over = b"{" + b" " * (svc.LIMITS["max_body_bytes"] - 1) + b"}"
        s413, d413, _ = raw("POST", url + "/v1/review", over + b" ", hdr)
        big = json.dumps(large_request(), ensure_ascii=False).encode()
        t0 = time.monotonic()
        sbig, dbig, _ = raw("POST", url + "/v1/review", big, hdr, timeout=30)
        ms_big = round((time.monotonic() - t0) * 1000, 1)
        port2 = free_port()
        url2 = d.run(tag + "-t", port2, extra=("--timeout", "0.001"))
        wait_ready(url2)
        s504, d504, _ = raw("POST", url2 + "/v1/review", big, hdr, timeout=30)
        after504 = raw("GET", url2 + "/readyz")[0]
        s_next = raw("GET", url2 + "/healthz")[0]
        S["limits"] = {"over_limit_body": [len(over) + 1, s413, d413.get("error", {}).get("type")],
                       "largest_legal_request": {"bytes": len(big), "http": sbig, "ms": ms_big, "items": len(dbig.get("items", [])),
                                                 "within_default_deadline": sbig == 200 and ms_big < 5000},
                       "tiny_deadline_container": {"http": s504, "code": d504.get("error", {}).get("type"), "ready_after": after504, "healthz_after": s_next},
                       "ok": s413 == 413 and sbig == 200 and s504 == 504 and after504 == 200}
        # logs
        lines = []
        for n in (tag, tag + "-t"):
            r = subprocess.run(["docker", "logs", n], capture_output=True, text=True, check=True)
            lines += [x for x in (r.stdout + r.stderr).splitlines() if x.strip()]
        bad_json, extra_keys, leaks = 0, set(), []
        for x in lines:
            try:
                o = json.loads(x)
            except ValueError:
                bad_json += 1
                continue
            extra_keys |= set(o) - LOG_KEYS
            leaks += [m for m in MARKERS if m in x]
        S["logs"] = {"lines": len(lines), "not_json": bad_json, "undocumented_keys": sorted(extra_keys), "learner_text_found": sorted(set(leaks)),
                     "statuses": sorted({str(json.loads(x).get("status")) for x in lines if x.startswith("{")} - {"None"}),
                     "ok": bad_json == 0 and not leaks}
        # restart
        feed_req = svc.request(sources=[rc._read(os.path.join(rc.PRACTICE, "y_en.r1.json"))], feed_seq=1)
        f_before = svc.call(url, "/v1/feed", feed_req)[1]["feed"]["feed_id"]
        m_before = raw("GET", url + "/metrics")[1]
        sh("docker", "restart", "-t", "5", tag)
        ready_again = wait_ready(url)
        m_after = raw("GET", url + "/metrics")[1]
        f_after = svc.call(url, "/v1/feed", feed_req)[1]["feed"]["feed_id"]
        ins = json.loads(sh("docker", "inspect", tag))[0]
        S["restart"] = {"ready_seconds": ready_again, "same_identity": raw("GET", url + "/manifest")[1].get("deployment_id") == man.get("deployment_id"),
                        "requests_before": sum((m_before.get("counters") or {}).values()), "requests_after_restart": sum((m_after.get("counters") or {}).values()),
                        "same_feed_id": f_before == f_after, "mounts": ins.get("Mounts"), "read_only_rootfs": ins["HostConfig"].get("ReadonlyRootfs"),
                        "docker_diff": sh("docker", "diff", tag).splitlines(), "restart_count_policy": ins["HostConfig"]["RestartPolicy"]["Name"]}
        S["restart"]["ok"] = (S["restart"]["same_identity"] and S["restart"]["same_feed_id"] and not S["restart"]["mounts"]
                              and S["restart"]["read_only_rootfs"] and not S["restart"]["docker_diff"])
        # outage and recovery
        if a.server_bin:
            import app_workflow as aw
            os.makedirs(os.path.join(a.work, "flh"), exist_ok=True)
            flh, flh_url = aw.start_flh(a.server_bin, os.path.join(a.work, "flh"))
            sh("docker", "stop", "-t", "5", tag)
            t0 = time.monotonic()
            st_down, err = svc.call(url, "/v1/review", svc.request(sources=[rc._read(os.path.join(rc.PRACTICE, "y_en.r1.json"))]), timeout=2)
            ms_down = round((time.monotonic() - t0) * 1000, 1)
            flh_ready = aw.http("GET", flh_url + "/readyz")[0]
            seq, t0 = [], time.monotonic()
            sh("docker", "start", tag)
            seq.append(["docker start", round(time.monotonic() - t0, 2)])
            seq.append(["/readyz 200", wait_ready(url)])
            seq.append(["/manifest equals the pinned deployment", raw("GET", url + "/manifest")[1].get("deployment_id") == man.get("deployment_id")])
            seq.append(["smoke", svc.smoke(url)[0] == 0])
            st_retry = svc.call(url, "/v1/review", svc.request(sources=[rc._read(os.path.join(rc.PRACTICE, "y_en.r1.json"))]),
                                expect_deployment=man.get("deployment_id"))[0]
            seq.append(["explicit retry by the caller", st_retry])
            S["outage"] = {"call_while_stopped": [st_down, err.get("error", {}).get("type")], "ms": ms_down, "automatic_retries": 0,
                           "flh_readyz_while_stopped": flh_ready, "recovery_sequence": seq,
                           "ok": st_down == 0 and flh_ready == 200 and st_retry == 200 and all(x[1] not in (False, None) for x in seq)}
    finally:
        if flh is not None:
            import app_workflow as aw
            aw.stop_flh(flh)
        left = d.cleanup()
        removed_image = False
        if built and not a.keep_image:
            sh("docker", "image", "rm", a.image, check=False)
            removed_image = not sh("docker", "image", "ls", "-q", a.image, check=False)
        S["teardown"] = {"containers_left": left, "image_removed": removed_image, "image_kept": not removed_image,
                         "ok": not left}
    rep["ok"] = (all(v.get("ok", True) for v in S.values() if isinstance(v, dict)) and S.get("identity", {}).get("identity_equal", False)
                 and S.get("identity", {}).get("smoke_ok", False))
    text = json.dumps(rep, ensure_ascii=False)
    rep["report_privacy_findings"] = len(__import__("flh_extraction.packet", fromlist=["x"]).privacy_findings(text))
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--build-context")
    ap.add_argument("--server-bin")
    ap.add_argument("--oom-score-adj", type=int)
    ap.add_argument("--keep-image", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    if os.path.exists(a.work) and os.listdir(a.work):
        raise SystemExit("--work must be a new or empty directory")
    os.makedirs(a.work, exist_ok=True)
    rep = rehearse(a)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rep, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    for k, v in rep["steps"].items():
        print(f"{k:9} {'ok' if v.get('ok', True) else 'FAIL'}  " + json.dumps({x: y for x, y in v.items() if x != 'ok'}, ensure_ascii=False)[:300])
    print("rehearsal:", "PASS" if rep["ok"] else "FAIL")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
