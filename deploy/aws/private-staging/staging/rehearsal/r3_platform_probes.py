#!/usr/bin/env python3
"""R3 platform probes on one stand-in host (R3-030, R3-058, R3-065).

  r3_platform_probes.py NEW.tar NEW_SHA OLD.tar OLD_SHA WORK_DIR

M  a model that is unavailable at startup: AI_PROVIDER=openai pointed at a closed port inside the
   container (OPENAI_BASE_URL=http://127.0.0.1:9/v1, a placeholder that is not a key). NEW installs
   and is ready; one analysis request fails fast with 502 and the generic message; /readyz stays
   200; the log holds one `request failed:` line naming the route pattern, and neither the
   placeholder key nor the entry's text.
I  an old deployment identity: OLD installed and running, then ROOT/current pointed at NEW without
   a restart. `status` must not report IDENTITY OK and `identity` must exit non-zero (the running
   image is OLD's). With current pointed back at OLD, `install NEW` ends in IDENTITY OK.
T  teardown with isolated fixtures: the host is taken down; no container, network or volume of this
   run's Compose project remains; the daily container and image are unchanged.
Stand-ins only (standin_lib: its own Compose project on a free loopback port, synthetic data); no
AWS, no network beyond loopback, no daily instance.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import standin_lib as S  # noqa: E402

PLACEHOLDER_KEY = "r3-placeholder-not-a-key-0000"
PROBE_TEXT = "R3 probe sentence: je suis alle au marche"


def main():
    if len(sys.argv) != 6:
        print(__doc__, file=sys.stderr)
        return 2
    new_tar, new_sha, old_tar, old_sha, work = sys.argv[1:6]
    rec = S.Recorder(work)
    fp_before = S.daily_fingerprint()
    rec.save("daily-fingerprint-before.txt", fp_before + "\n")
    S.PARAMS[:] = [(k, v) for k, v in S.PARAMS if k != "AI_PROVIDER"] + [
        ("AI_PROVIDER", "openai"), ("OPENAI_BASE_URL", "http://127.0.0.1:9/v1"), ("OPENAI_API_KEY", PLACEHOLDER_KEY),
        ("OPENAI_MODEL", "r3-probe-model"), ("OPENAI_TIMEOUT", "5")]
    h = S.Host(rec, "probe")
    ok, mode = h.render_settings()
    rec.record("H", ok, "settings rendered (0600, values never printed)", f"mode {oct(mode) if mode else None}")

    # --- M: model unavailable at startup -------------------------------------------------------------
    rc, text, secs = h.tool("install", new_tar, "--sha256", new_sha, log="install-new")
    rec.record("M1", rc == 0 and "IDENTITY OK" in text, "NEW installs and starts with its analysis model unreachable",
               f"exit {rc}, {secs:.1f} s")
    rec.record("M2", h.ready(30), "/readyz 200 although the model endpoint refuses connections", "ready")
    st, raw = h.call("POST", "/entries", {"original_input": PROBE_TEXT, "original_context": "synthetic R3 probe"})
    eid = S.js(raw).get("id")
    rec.record("M3", st == 201 and eid, "a learner entry is still accepted (no model needed)", f"{st}, id {eid}")
    t0 = time.time()
    st2, raw2 = h.call("POST", f"/entries/{eid}/analysis")
    dt = time.time() - t0
    body = raw2.decode(errors="replace")
    rec.record("M4", st2 == 502 and dt < 10 and PLACEHOLDER_KEY not in body and "127.0.0.1:9" not in body,
               "the analysis fails fast with 502 and a generic message (no key, no provider address)",
               f"{st2} in {dt:.2f} s: {body.strip()[:80]}")
    rec.record("M5", S.call(h.port, "GET", "/readyz", timeout=5)[0] == 200, "/readyz stays 200 after the failure", "200")
    rc, logs, _ = h.stg("logs", "--no-color", log="logs")
    lines = [l for l in logs.splitlines() if "request failed:" in l]
    rec.record("M6", any('route="POST /entries/{id}/analysis"' in l and "status=502" in l for l in lines),
               "one `request failed:` line names the route pattern and the status", f"{len(lines)} line(s)")
    rec.record("M7", PLACEHOLDER_KEY not in logs and PROBE_TEXT not in logs,
               "the log holds neither the key nor the learner's text", "absent" if PLACEHOLDER_KEY not in logs
               and PROBE_TEXT not in logs else "PRESENT")

    # --- I: an old deployment identity ---------------------------------------------------------------
    rc, text, secs = h.tool("install", old_tar, "--sha256", old_sha, log="install-old")
    rec.record("I1", rc == 0 and "IDENTITY OK" in text, "OLD installed and running (previous = NEW)", f"exit {rc}, {secs:.1f} s")
    cur_link = os.path.join(h.root, "current")
    old_dir = os.path.realpath(cur_link)
    new_dir = os.path.join(h.root, "bundles", os.path.basename(new_tar)[:-4])
    tmp = cur_link + ".r3probe"
    os.symlink(new_dir, tmp)
    os.replace(tmp, cur_link)
    rc_s, st_text, _ = h.tool("status", log="status-stale")
    rc_i, id_text, _ = h.tool("identity", log="identity-stale")
    rec.record("I2", "IDENTITY OK" not in st_text and rc_i != 0,
               "current names NEW but OLD is running: status and identity do not report a match",
               f"status exit {rc_s}, identity exit {rc_i}")
    os.symlink(old_dir, tmp)
    os.replace(tmp, cur_link)
    rc, text, secs = h.tool("install", new_tar, "--sha256", new_sha, log="install-new-again")
    rc_i2, id_text2, _ = h.tool("identity", log="identity-after")
    rec.record("I3", rc == 0 and rc_i2 == 0 and "IDENTITY OK" in id_text2, "after install NEW: identity OK again",
               f"install exit {rc}, identity exit {rc_i2}")

    # --- T: teardown -----------------------------------------------------------------------------------
    h.down()
    nets = subprocess.run(["docker", "network", "ls", "-q", "--filter", f"label=com.docker.compose.project={h.project}"],
                          capture_output=True, text=True).stdout.split()
    vols = subprocess.run(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={h.project}"],
                          capture_output=True, text=True).stdout.split()
    rec.record("T1", not nets and not vols, "no network or volume of the stand-in project remains",
               f"networks {len(nets)}, volumes {len(vols)}")
    return S.finish(rec, [h], fp_before)   # C1 no container left, C2 daily unchanged, RESULT


if __name__ == "__main__":
    sys.exit(main())
