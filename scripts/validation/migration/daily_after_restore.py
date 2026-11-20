#!/usr/bin/env python3
"""Daily learning after a restore: the existing browser journeys on restored data, compared with the
same journeys on the source (R3-031..R3-040).

    python3 -I scripts/validation/migration/daily_after_restore.py WORK_DIR --rehearsal REHEARSAL_DIR --handoff HANDOFF_2_1

REHEARSAL_DIR is a finished `rehearse.py` work directory (its v021-daily fixture: the source in
nas/data, the restored copy in aws/data, the seed's facts in facts.json). Both databases are only
copied: each journey starts on its own copy. Runs, sequentially:
  learning-day/source     scripts/validation/learning_day/walkthrough.py --from-db <source> --facts <facts>
  learning-day/restored   the same on the restored data
  practice/restored       scripts/validation/practice_feed/walkthrough.py --from-db <restored> (5 combinations)
  measure/restored        the same with --script measure.mjs (interactions from Review Today to the
                          first graded answer) on desktop and 320 px
then compares the two learning-day runs check by check (parity: the same checks, the same outcome)
and writes WORK_DIR/daily-after-restore.json. Exit 0 when every run passed and the runs agree.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def main():
    args = sys.argv[1:]
    opts = {}
    for flag in ("--rehearsal", "--handoff"):
        if flag in args:
            i = args.index(flag)
            opts[flag] = args[i + 1]
            args = args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]) or len(opts) != 2:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    work = Path(os.path.realpath(args[0]))
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        print("refused: WORK_DIR must be new or empty", file=sys.stderr)
        return 2
    fx = Path(os.path.realpath(opts["--rehearsal"])) / "v021-daily"
    src, dst, facts = fx / "nas" / "data" / "app.db", fx / "aws" / "data" / "app.db", fx / "facts.json"
    for p in (src, dst, facts):
        if not p.exists():
            print(f"refused: {p} missing (run rehearse.py first)", file=sys.stderr)
            return 2
    runs = {}

    def run(name, cmd):
        t = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True)
        (work / f"{name.replace('/', '-')}.out").write_text(r.stdout + r.stderr)
        line = next((ln for ln in reversed(r.stdout.splitlines()) if ln.endswith("PASS") and "/" in ln.split()[0]), "")
        runs[name] = {"exit": r.returncode, "seconds": round(time.time() - t), "summary": line}
        print(name, runs[name], flush=True)
        return r.returncode

    py = [sys.executable, "-I"]
    run("learning-day/source", py + [str(REPO / "scripts/validation/learning_day/walkthrough.py"), str(work / "ld-source"), "--from-db", str(src), "--facts", str(facts)])
    run("learning-day/restored", py + [str(REPO / "scripts/validation/learning_day/walkthrough.py"), str(work / "ld-restored"), "--from-db", str(dst), "--facts", str(facts)])
    run("practice/restored", py + [str(REPO / "scripts/validation/practice_feed/walkthrough.py"), str(work / "practice-restored"), "--handoff", opts["--handoff"], "--from-db", str(dst)])
    run("measure/restored", py + [str(REPO / "scripts/validation/practice_feed/walkthrough.py"), str(work / "measure-restored"), "--handoff", opts["--handoff"],
                                  "--from-db", str(dst), "--script", "measure.mjs", "--combos", "desktop-en,phone320-en"])
    a = json.loads((work / "ld-source" / "results.json").read_text()) if (work / "ld-source" / "results.json").exists() else []
    b = json.loads((work / "ld-restored" / "results.json").read_text()) if (work / "ld-restored" / "results.json").exists() else []
    key = lambda r: (r.get("combo"), r.get("name"))
    pa, pb = {key(r): r["pass"] for r in a}, {key(r): r["pass"] for r in b}
    parity = {"source_checks": len(pa), "restored_checks": len(pb), "same_checks": sorted(pa) == sorted(pb),
              "differing": [list(k) for k in pa if pa.get(k) != pb.get(k)] + [list(k) for k in pb if k not in pa]}
    measure = json.loads((work / "measure-restored" / "measure.json").read_text()) if (work / "measure-restored" / "measure.json").exists() else None
    out = {"runs": runs, "learning_day_parity": parity, "measure_on_restored": measure}
    (work / "daily-after-restore.json").write_text(json.dumps(out, indent=1))
    ok = all(r["exit"] == 0 for r in runs.values()) and parity["same_checks"] and not parity["differing"]
    print(json.dumps(parity))
    print("PASS" if ok else "FAIL", "daily learning after restore: every run passed and the source and restored runs agree")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
