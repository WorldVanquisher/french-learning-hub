#!/usr/bin/env python3
"""One local check of the key learner flows of the Review Today batch.

    python3 -I scripts/validation/learning_day/verify.py WORK_DIR [--no-browser]

WORK_DIR must be absolute, outside the repository, and new or empty; every
log and the browser run's output go there. Steps, in order (each PASS/FAIL
with its duration; the log is WORK_DIR/<step>.log):

  gofmt      gofmt -l ./cmd ./internal prints nothing
  go         go test -count=1 for Review Today, the scheduling prototype, the
             revision studio, the learning week and the history export
             (domain, application, transport/http, historyexport)
  web        npm run typecheck (tsc -b --noEmit), then vitest on the batch's
             test files
  browser    scripts/validation/learning_day/walkthrough.py (Docker; skipped
             with --no-browser)

Needs Go, web/node_modules (npm ci) and, for the browser step, Docker with
the Playwright volume flh-listening-workbook-pw. No provider, no network
call, nothing written outside WORK_DIR. Exit 0 when every step passes.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GO_RUN = ("TestBuildReviewToday|TestReviewToday|TestNextRecommendation|TestSimulateWeek|TestScheduleInputsFromExport|"
          "TestDiffWords|TestAlignListeningBlocks|TestRevisionStudio|TestBuildLearningWeek|TestLearningWeek|TestHistoryExport|"
          "TestSafeFile|TestWriteNew|TestRun_")
WEB_TESTS = ["src/pages/ReviewToday.test.tsx", "src/pages/practiceDraft.test.ts", "src/pages/NotebookPractice.test.tsx",
             "src/pages/RevisionStudio.test.tsx", "src/pages/Speaking.test.tsx", "src/pages/LearningWeek.test.tsx",
             "src/pages/HistoryExport.test.tsx", "src/pages/AccessibleLearning.test.tsx", "src/prototype", "src/i18n"]


def main():
    args = [a for a in sys.argv[1:] if a != "--no-browser"]
    browser = "--no-browser" not in sys.argv[1:]
    if len(args) != 1 or not os.path.isabs(args[0]):
        print("usage: verify.py /abs/new/empty/dir [--no-browser]", file=sys.stderr)
        return 2
    work = Path(os.path.realpath(args[0]))
    if work == REPO or REPO in work.parents:
        print("refused: WORK_DIR must be outside the repository", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        print("refused: WORK_DIR must be new or empty", file=sys.stderr)
        return 2
    env = dict(os.environ, GOFLAGS="-buildvcs=false", NODE_OPTIONS="--no-experimental-webstorage")
    steps = [
        ("gofmt", [["gofmt", "-l", "./cmd", "./internal"]], REPO, True),
        ("go", [["go", "test", "-count=1", "-run", GO_RUN, "./internal/domain/", "./internal/application/", "./internal/transport/http/", "./internal/historyexport/"]], REPO, False),
        # npm run typecheck is tsc -b --noEmit: it follows tsconfig.json's
        # references. (tsc --noEmit -p . checks no file, since tsconfig.json
        # lists none.)
        ("web", [["npm", "run", "--silent", "typecheck"], ["npx", "vitest", "run", "--maxWorkers=2", "--minWorkers=1", *WEB_TESTS]], REPO / "web", False),
    ]
    if browser:
        steps.append(("browser", [[sys.executable, "-I", str(REPO / "scripts/validation/learning_day/walkthrough.py"), str(work / "browser")]], REPO, False))
    failed = 0
    for name, cmds, cwd, empty_ok in steps:
        t = time.time()
        ok = True
        with open(work / f"{name}.log", "w") as log:
            for cmd in cmds:
                r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
                log.write(f"$ {' '.join(cmd)}\n{r.stdout}{r.stderr}\n")
                if r.returncode != 0 or (empty_ok and r.stdout.strip()):
                    ok = False
                    break
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}\t{name}\t{time.time() - t:.0f}s\t{work / (name + '.log')}")
    if not browser:
        print("SKIP\tbrowser\t(--no-browser)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
