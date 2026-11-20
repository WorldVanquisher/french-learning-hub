"""One offline end-to-end smoke for the R4 extraction lane (synthetic data, no network, no model, no AWS).

  python3 -I -B scripts/r4_smoke.py            # prints one line per check; exit 0 when all pass
  python3 -I -B scripts/r4_smoke.py --expect   # also compares the output with fixtures/r4_v1/SMOKE.expected.txt

Checks, in order:
1. the service smoke (in-process, 15 checks);
2. the R4 corpus and its current results;
3. lifecycle, learning loop and agent exchange (byte for byte);
4. the payload examples;
5. grounding quality;
6. feed interoperability;
7. the pre-registered leakage experiment;
8. Speaking training intake (eligible and refused fixtures);
9. the pilot render and teardown order.

The output holds no timing and no path, so it is the same on every run.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(HERE))
SPEAKING = os.path.join(ROOT, "tools", "speaking")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "scripts"))

EXPECTED = os.path.join(HERE, "fixtures", "r4_v1", "SMOKE.expected.txt")


def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
        rc = fn(*a)
    return rc, out.getvalue()


def checks():
    from flh_extraction import feed_interop, grounding_quality, leakage
    from flh_extraction import service as svc
    import r4_corpus
    import r4_exchange
    import r4_lifecycle
    import r4_loop
    import service_examples
    with contextlib.redirect_stderr(io.StringIO()):
        rc, text = svc.smoke()
    yield "service smoke", rc == 0, text.strip().splitlines()[-1].split(" against")[0].replace("smoke: ", "")
    yield "deployment", True, svc.manifest()["deployment_id"]
    for name, mod in (("corpus", r4_corpus), ("lifecycle", r4_lifecycle), ("loop", r4_loop), ("exchange", r4_exchange),
                      ("service examples", service_examples)):
        rc, _ = quiet(mod.main, ["--check"])
        yield name, rc == 0, "equal to a fresh run" if rc == 0 else "DIFFERS"
    g = grounding_quality.evaluate()["summary"]
    yield "grounding quality", g["exact_v1"]["correct"] == 11 and g["exact_v1+checks_v2"]["correct"] == 15, \
        f"exact_v1 {g['exact_v1']['correct']}/18, candidate {g['exact_v1+checks_v2']['correct']}/18"
    rep = feed_interop.report()
    yield "feed interop", rep["ok"], f"{rep['summary']['samples']} samples, merged mirror refuses {len(rep['summary']['merged_mirror_refuses'])}"
    with open(leakage.PREREG, encoding="utf-8") as fh:
        r = leakage.run(json.load(fh))
    yield "leakage experiment", r["decision"] == "branch_A", f"M1 {r['M1']}, M2 {r['M2']}, {r['decision']}"
    for fix, want in (("training-intake.ok.json", 0), ("training-intake.refused.json", 1)):
        p = subprocess.run([sys.executable, "-B", "-m", "flh_speaking", "lab", "training-intake", "--manifest", os.path.join("fixtures", "intake_r4", fix)],
                           cwd=SPEAKING, capture_output=True, text=True)
        yield f"speaking intake {fix.split('.')[1]}", p.returncode == want, p.stdout.splitlines()[0].split(": ", 1)[1] if p.stdout else p.stderr[-80:]
    p = subprocess.run([sys.executable, "-I", "-B", os.path.join("aws", "pilot_r4.py"), "teardown-check", os.path.join("aws", "r4-teardown-plan.json")],
                       cwd=SPEAKING, capture_output=True, text=True)
    yield "pilot teardown order", p.returncode == 0, p.stdout.strip()
    sys.path.insert(0, os.path.join(SPEAKING, "aws"))
    import tempfile
    from datetime import datetime, timezone

    import pilot_r4
    with open(os.path.join(SPEAKING, "aws", "values.r4.example.json"), encoding="utf-8") as fh:
        v = json.load(fh)
    with tempfile.TemporaryDirectory() as t:
        out = pilot_r4.render_r4(v, t, datetime(2026, 11, 20, tzinfo=timezone.utc))
        with open(out, "rb") as a, open(os.path.join(ROOT, "deploy", "aws", "model-runtime", "speaking-r4", os.path.basename(out)), "rb") as b:
            same = a.read() == b.read()
    yield "pilot render", same, os.path.basename(str(out)) + (" equals the committed example" if same else " DIFFERS")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect", action="store_true")
    a = ap.parse_args(argv)
    lines, ok = [], True
    for name, passed, detail in checks():
        ok &= bool(passed)
        lines.append(f"{'PASS' if passed else 'FAIL'}  {name:26} {detail}")
    lines.append(f"r4 smoke: {'PASS' if ok else 'FAIL'} ({len(lines)} checks)")
    text = "\n".join(lines) + "\n"
    sys.stdout.write(text)
    if a.expect:
        with open(EXPECTED, encoding="utf-8") as fh:
            same = fh.read() == text
        print("expected output: " + ("equal" if same else "DIFFERS from fixtures/r4_v1/SMOKE.expected.txt"))
        ok &= same
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
