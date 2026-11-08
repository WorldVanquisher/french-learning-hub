"""Establish that a URL belongs to the rehearsal instance `rehearse.sh serve` started.

    python3 -I ownership.py --work WORK --project P --port N --repo REPO \
        --image IMG:app --fake-image IMAGE --out OWNERSHIP.json

Read-only. Collects the live Docker state of every container (``docker ps``,
``docker inspect``) plus three GETs, then decides with ``evaluate()``, which is
pure so that test_ownership.py can exercise every refusal without Docker.

The verdict is "owned" only if all of these hold, otherwise "refused" (exit 1).
Any error while collecting is a refusal: it fails closed.
- the project is a rehearsal project (flh-rehearsal-<14 digits>), never the
  daily project, and it is the project recorded in WORK/project;
- it has exactly one running ``app`` and one running ``fake-provider``
  container, created from REPO/compose.yaml plus WORK/compose/upgrade.yaml;
- the app runs IMG:app (not a french-learning-hub image), publishes exactly
  127.0.0.1:PORT, and no other container publishes PORT;
- its only mount is WORK/data on /data, which no daily container mounts;
- its provider settings point at the fake provider with the placeholder key;
- the fake provider runs the fixture script, publishes nothing and shares the
  app's network;
- over HTTP the URL is ready, has suggestions enabled and holds no record.
The browser smoke refuses to seed without an "owned" file for its URL.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

DAILY_PROJECT = "french-learning-hub"
FAKE_BASE_URL = "http://fake-provider:19195/v1"
PLACEHOLDER_KEY = "placeholder-not-a-real-key"
PROJECT_RE = re.compile(r"^flh-rehearsal-\d{14}$")


def env_of(container):
    out = {}
    for item in container.get("Config", {}).get("Env") or []:
        k, _, v = item.partition("=")
        out[k] = v
    return out


def published(container):
    """[(host_ip, host_port)] for every published port of a container."""
    out = []
    for bindings in (container.get("NetworkSettings", {}).get("Ports") or {}).values():
        for b in bindings or []:
            out.append((b.get("HostIp", ""), str(b.get("HostPort", ""))))
    return out


def evaluate(state):
    """state: dict(project, recorded_project, port, work, repo, image, fake_image,
    containers=[inspect...], http={readyz, suggestions_enabled, entries}).
    Returns (verdict, checks) where checks is [(ok, name, detail)]."""
    checks = []

    def check(ok, name, detail=""):
        checks.append((bool(ok), name, str(detail)[:300]))
        return bool(ok)

    project, port, work, repo = state["project"], str(state["port"]), state["work"], state["repo"]
    data_dir = os.path.join(work, "data")
    upgrade = os.path.join(work, "compose", "upgrade.yaml")
    base = os.path.join(repo, "compose.yaml")
    check(project != DAILY_PROJECT and PROJECT_RE.match(project or ""), "rehearsal project name", project)
    check(state.get("recorded_project") == project, "project recorded by serve in WORK/project", state.get("recorded_project"))

    containers = state.get("containers") or []
    labels = lambda c: c.get("Config", {}).get("Labels") or {}
    mine = [c for c in containers if labels(c).get("com.docker.compose.project") == project]
    by_service = {}
    for c in mine:
        by_service.setdefault(labels(c).get("com.docker.compose.service"), []).append(c)
    check(sorted(by_service) == ["app", "fake-provider"] and all(len(v) == 1 for v in by_service.values()),
          "exactly one app and one fake-provider container", {k: len(v) for k, v in by_service.items()})
    app = (by_service.get("app") or [None])[0]
    fake = (by_service.get("fake-provider") or [None])[0]
    if app is None or fake is None:
        return "refused", checks

    for name, c in (("app", app), ("fake-provider", fake)):
        check(c.get("State", {}).get("Running") is True, f"{name} is running", c.get("State", {}).get("Status"))
        files = [f for f in labels(c).get("com.docker.compose.project.config_files", "").split(",") if f]
        check(files == [base, upgrade], f"{name} was created from compose.yaml + WORK/compose/upgrade.yaml", files)
        check(labels(c).get("com.docker.compose.project.working_dir") == repo, f"{name} working directory is this checkout",
              labels(c).get("com.docker.compose.project.working_dir"))

    image = app.get("Config", {}).get("Image", "")
    check(image == state["image"] and image.split(":")[0] != DAILY_PROJECT, "app image is the rehearsal tag", image)
    check(published(app) == [("127.0.0.1", port)], f"app publishes exactly 127.0.0.1:{port}", published(app))
    others = [c.get("Name") for c in containers if c is not app and any(p == port for _, p in published(c))]
    check(not others, f"no other container publishes {port}", others)

    mounts = [(m.get("Source"), m.get("Destination")) for m in app.get("Mounts") or []]
    check(mounts == [(data_dir, "/data")], "app mounts only WORK/data on /data", mounts)
    daily_sources = {m.get("Source") for c in containers if labels(c).get("com.docker.compose.project") == DAILY_PROJECT
                     for m in c.get("Mounts") or []}
    check(data_dir not in daily_sources, "no daily container mounts this data directory")

    env = env_of(app)
    check(env.get("OPENAI_BASE_URL") == FAKE_BASE_URL, "app provider is the fake provider", env.get("OPENAI_BASE_URL"))
    # Compared only; the value is never written out.
    check(env.get("OPENAI_API_KEY") == PLACEHOLDER_KEY, "app key is the rehearsal placeholder")
    check(all(env.get(k) == "openai" for k in ("AI_PROVIDER", "EXTRACTOR_PROVIDER", "SUGGESTION_PROVIDER")),
          "analysis, extraction and suggestions use the (fake) OpenAI-compatible provider")

    fcmd = " ".join((fake.get("Config", {}).get("Entrypoint") or []) + (fake.get("Config", {}).get("Cmd") or []))
    check(fake.get("Config", {}).get("Image") == state["fake_image"], "fake provider image", fake.get("Config", {}).get("Image"))
    check("/fixture/fake_openai.py" in fcmd, "fake provider runs the fixture script", fcmd)
    check(published(fake) == [], "fake provider publishes no port", published(fake))
    nets = lambda c: set((c.get("NetworkSettings", {}).get("Networks") or {}).keys())
    check(nets(app) and nets(app) == nets(fake), "app and fake provider share the project network", sorted(nets(app)))

    http = state.get("http") or {}
    check(http.get("readyz") == {"status": "ready"}, "URL is ready", http.get("readyz"))
    check(http.get("suggestions_enabled") is True, "URL has suggestions enabled")
    check(http.get("entries") == 0, "URL holds no record yet", http.get("entries"))
    return ("owned" if all(ok for ok, _, _ in checks) else "refused"), checks


def docker_json(args):
    out = subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=60).stdout
    return out


def collect(args):
    ids = docker_json(["ps", "-aq", "--no-trunc"]).split()
    containers = json.loads(docker_json(["inspect", *ids])) if ids else []

    def get(path):
        with urllib.request.urlopen(args.url + path, timeout=5) as r:
            return json.load(r)

    http = {
        "readyz": get("/readyz"),
        "suggestions_enabled": get("/concept-suggestion-runs").get("enabled"),
        "entries": len(get("/entries?limit=1").get("entries") or []),
    }
    with open(os.path.join(args.work, "project")) as f:
        recorded = f.read().strip()
    return {"project": args.project, "recorded_project": recorded, "port": args.port, "work": args.work,
            "repo": args.repo, "image": args.image, "fake_image": args.fake_image,
            "containers": containers, "http": http}


def main():
    p = argparse.ArgumentParser()
    for name in ("--work", "--project", "--port", "--repo", "--image", "--fake-image", "--out"):
        p.add_argument(name, required=True)
    args = p.parse_args()
    args.work, args.repo = os.path.realpath(args.work), os.path.realpath(args.repo)
    args.url = f"http://127.0.0.1:{args.port}"
    try:
        state = collect(args)
        verdict, checks = evaluate(state)
        app = next((c for c in state["containers"]
                    if (c.get("Config", {}).get("Labels") or {}).get("com.docker.compose.project") == args.project
                    and c["Config"]["Labels"].get("com.docker.compose.service") == "app"), {})
    except Exception as e:  # fail closed
        verdict, checks, app = "refused", [(False, "collect live state", f"{type(e).__name__}: {e}")], {}
    doc = {
        "verdict": verdict,
        "url": args.url,
        "project": args.project,
        "daily_project_refused": DAILY_PROJECT,
        "app_container": app.get("Id"),
        "data_dir": os.path.join(args.work, "data"),
        "provider_base_url": FAKE_BASE_URL,
        "verified_at": int(time.time()),
        "checks": [{"status": "PASS" if ok else "FAIL", "name": n, "detail": d} for ok, n, d in checks],
    }
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2)
    for ok, n, d in checks:
        print(f"{'PASS' if ok else 'FAIL'}\townership: {n}\t{d if not ok else ''}")
    print(f"ownership verdict: {verdict}")
    return 0 if verdict == "owned" else 1


if __name__ == "__main__":
    sys.exit(main())
