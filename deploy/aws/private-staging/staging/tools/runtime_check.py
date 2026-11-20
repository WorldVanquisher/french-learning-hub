#!/usr/bin/env python3
"""Offline Compose verification of the private extraction sidecar (R4-REL-052, R4-REL-053).

  runtime_check.py [--repo DIR] [--image REF]

Runs `docker compose config` (it parses and renders; it starts, pulls and builds nothing) on the
repository's compose.yaml, with and without staging/runtime/extraction.override.yaml, and a synthetic
settings file outside the repository. PASS when:
- with the override: an `extraction` service exists on the app's default network, publishes no port,
  runs read-only as user 10002 with every capability dropped, 256 MiB memory (no swap), at most 64
  processes and a /readyz health check, and carries the expected deployment_id as a label;
- without it: no `extraction` service, and the `app` service renders byte-for-byte the same as with it
  (the default deployment is unchanged);
- a missing FLH_EXTRACTION_IMAGE or FLH_EXTRACTION_DEPLOYMENT_ID fails visibly with its message, and a
  malformed --deployment-id fails the check.
Exit 0 PASS, 1 a check failed, 2 Docker Compose unavailable.
"""
import argparse
import json
import os
import subprocess
import sys
import re
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STAGING = os.path.dirname(HERE)
REPO = os.path.realpath(os.path.join(STAGING, "..", "..", "..", ".."))
OVERRIDE = os.path.join(STAGING, "runtime", "extraction.override.yaml")
IMAGE = "flh-extraction-service:e978b6c2bdb6"
DEPLOYMENT = "flh-extraction-rules@e978b6c2bdb6/flh_extraction_service_v1/flh_practice_drafter_v1"
DEPLOYMENT_RE = re.compile(r"^flh-extraction-rules@[0-9a-f]{12}/flh_extraction_service_v1/flh_practice_drafter_v1$")


def config(repo, env, with_override):
    files = ["-f", os.path.join(repo, "compose.yaml")] + (["-f", OVERRIDE] if with_override else [])
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("COMPOSE_", "FLH_", "DOCKER_HOST"))}
    clean.update(env)
    return subprocess.run(["docker", "compose", "-p", "flh-runtime-check", *files, "config", "--format", "json"],
                          capture_output=True, text=True, env=clean, cwd=repo)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--image", default=IMAGE)
    ap.add_argument("--deployment-id", default=DEPLOYMENT)
    a = ap.parse_args()
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0:
        print("runtime_check: docker compose is not available", file=sys.stderr)
        return 2
    td = tempfile.mkdtemp(prefix="flh-runtime-check-")
    base = {"FLH_DATA_DIR": td, "FLH_HOST_PORT": "18999", "FLH_UID": "1000", "FLH_GID": "1000"}
    results = []

    def check(name, ok, detail):
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")

    r_without = config(a.repo, base, False)
    full = dict(base, FLH_EXTRACTION_IMAGE=a.image, FLH_EXTRACTION_DEPLOYMENT_ID=a.deployment_id)
    r_with = config(a.repo, full, True)
    if r_without.returncode or r_with.returncode:
        check("compose config renders", False, (r_without.stderr + r_with.stderr).strip()[:300])
        return 1
    plain, extra = json.loads(r_without.stdout), json.loads(r_with.stdout)
    check("default deployment has no extraction service", "extraction" not in plain["services"],
          ", ".join(sorted(plain["services"])))
    check("the app service is unchanged by the override",
          json.dumps(plain["services"]["app"], sort_keys=True) == json.dumps(extra["services"]["app"], sort_keys=True),
          "app service JSON identical with and without the override")
    ex = extra["services"].get("extraction") or {}
    check("extraction publishes no port", not ex.get("ports") and not ex.get("expose"), f"ports {ex.get('ports')}")
    nets = set(ex.get("networks") or {}) or {"default"}
    app_nets = set(extra["services"]["app"].get("networks") or {}) or {"default"}
    check("extraction shares the app's network", bool(nets & app_nets), f"{sorted(nets)} vs app {sorted(app_nets)}")
    check("read-only, user 10002, no capability", ex.get("read_only") is True and str(ex.get("user")) == "10002"
          and ex.get("cap_drop") == ["ALL"], f"read_only {ex.get('read_only')}, user {ex.get('user')}, cap_drop {ex.get('cap_drop')}")
    check("256 MiB memory, no swap, at most 64 processes", str(ex.get("mem_limit")) in ("268435456", "256m")
          and str(ex.get("memswap_limit")) in ("268435456", "256m") and ex.get("pids_limit") == 64,
          f"mem_limit {ex.get('mem_limit')}, memswap_limit {ex.get('memswap_limit')}, pids_limit {ex.get('pids_limit')}")
    label = (ex.get("labels") or {}).get("org.flh.extraction.expect-deployment-id", "")
    check("the expected deployment_id is recorded and well formed", bool(DEPLOYMENT_RE.match(label)), label)
    check("no environment is passed to the service (it reads flags only)", not ex.get("environment"),
          f"environment {ex.get('environment')}")
    hc = " ".join(ex.get("healthcheck", {}).get("test") or [])
    check("health check is /readyz", "/readyz" in hc, hc[:120])
    for var in ("FLH_EXTRACTION_IMAGE", "FLH_EXTRACTION_DEPLOYMENT_ID"):
        r_missing = config(a.repo, {k: v for k, v in full.items() if k != var}, True)
        check(f"a missing {var} fails visibly", r_missing.returncode != 0 and var in r_missing.stderr,
              r_missing.stderr.strip().splitlines()[-1][:160] if r_missing.stderr.strip() else "no error")
    print("RUNTIME CHECK " + ("PASSED" if all(results) else "FAILED"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
