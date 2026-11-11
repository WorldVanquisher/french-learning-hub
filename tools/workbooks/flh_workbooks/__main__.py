"""FLH workbooks command line (run from tools/workbooks):

  python3 -m flh_workbooks build              write content/workbooks/*.json (and the embedded listening
                                              script pack) from the authoring modules
  python3 -m flh_workbooks check              quality gates; committed JSON must equal a fresh build
  python3 -m flh_workbooks render --out DIR   student/teacher Markdown + HTML, recording script, TTS script
  python3 -m flh_workbooks scan [--workbook rl|pw] --html F [--pdf-text F] [--pdf-info F]
                                              key-exposure scan of a student edition
  python3 -m flh_workbooks report --out DIR   inventory JSON/Markdown and machine-critique flags
  python3 -m flh_workbooks capture --question ID --text "learner's own question"
                                              print a learning_capture_v1 document (no analysis)
  python3 -m flh_workbooks studypack --unit u05 --out DIR
                                              ten-minute listening study pack: student checklist,
                                              reader sheet, teacher debrief and verification report
"""

import argparse
import json
import sys
from pathlib import Path

from . import adapters, model, quality, render, report, scan, studypack

ADAPTER_DIR = model.CONTENT / "adapters"
# The listening script pack is embedded by the server, so it lives in its package.
LISTENING_PACK = model.ROOT / "internal" / "listening" / "pack" / "listening_scripts_v1.json"


def outputs():
    """Every committed generated file and its expected content."""
    rl = model.build_rl()
    pw = model.build_pw()
    return rl, {
        model.RL_PATH: model.dumps(rl),
        ADAPTER_DIR / "reading_pack_workbook_rl_v1.json": adapters.dumps(adapters.reading_pack(rl)),
        ADAPTER_DIR / "reading_learner_lessons_rl_v1.json": adapters.dumps(adapters.learner_lessons(rl)),
        LISTENING_PACK: adapters.dumps(adapters.listening_script_pack(rl)),
        model.PW_PATH: model.dumps(pw),
        ADAPTER_DIR / "writing_tasks_pw_v1.json": adapters.dumps(adapters.writing_task_bodies(pw)),
        ADAPTER_DIR / "writing_prompts_workbook_pw_v1.json": adapters.dumps(adapters.writing_prompt_set(pw)),
        ADAPTER_DIR / "speaking_prompts_workbook_pw_v1.json": adapters.dumps(adapters.speaking_prompt_set(pw)),
    }


def gates():
    units = model.load_units(model.RL_MODULES)
    errs, notes, stats = quality.check_rl(units)
    perrs, pnotes, pstats = quality.check_pw(model.load_units(model.PW_MODULES))
    errs, notes = errs + perrs, notes + pnotes
    stats = dict(stats, productive=pstats)
    rl, _ = outputs()
    pos = model.position_stats(model.all_questions(rl))
    if pos["max_run"] > model.MAX_RUN:
        errs.append(f"answer letter repeats {pos['max_run']} times in a row")
    if max(pos["counts"].values()) - min(pos["counts"].values()) > 2:
        errs.append(f"answer positions unbalanced: {pos['counts']}")
    return errs, notes, dict(stats, positions=pos)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="flh_workbooks")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("check")
    r = sub.add_parser("render"); r.add_argument("--out", required=True)
    s = sub.add_parser("scan"); s.add_argument("--workbook", choices=("rl", "pw"), default="rl"); s.add_argument("--html", required=True); s.add_argument("--pdf-text"); s.add_argument("--pdf-info")
    p = sub.add_parser("report"); p.add_argument("--out", required=True)
    c = sub.add_parser("capture"); c.add_argument("--question", required=True); c.add_argument("--text", required=True)
    sp = sub.add_parser("studypack"); sp.add_argument("--unit", required=True); sp.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    if a.cmd in ("build", "check"):
        errs, notes, stats = gates()
        print(json.dumps(stats, ensure_ascii=False))
        for n in notes:
            print("note:", n)
        for e in errs:
            print("ERROR:", e, file=sys.stderr)
        if errs:
            return 1
        _, files = outputs()
        stale = []
        for path, text in files.items():
            if a.cmd == "build":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                print("wrote", path.relative_to(model.ROOT))
            elif not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(str(path.relative_to(model.ROOT)))
        if stale:
            print("ERROR: stale or missing generated files (run build):", ", ".join(stale), file=sys.stderr)
            return 1
        return 0

    rl = json.loads(model.RL_PATH.read_text(encoding="utf-8"))
    pw = json.loads(model.PW_PATH.read_text(encoding="utf-8"))
    if a.cmd == "render":
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        files = {
            "reading-listening-student.md": render.rl_markdown(rl, False),
            "reading-listening-teacher.md": render.rl_markdown(rl, True),
            "reading-listening-student.html": render.rl_html(rl, False),
            "reading-listening-teacher.html": render.rl_html(rl, True),
            "listening-recording-script.md": render.recording_script_md(rl),
            "listening_scripts_v1.json": render.tts_script_json(rl),
            "listening-production-checklist.md": render.PRODUCTION_CHECKLIST,
            "productive-student.md": render.pw_markdown(pw, False),
            "productive-teacher.md": render.pw_markdown(pw, True),
            "productive-student.html": render.pw_html(pw, False),
            "productive-teacher.html": render.pw_html(pw, True),
            "workbook-texts.txt": "\n\n".join([s["text"] for u in rl["units"] for s in u["reading"]["segments"]]
                                             + [t["text"] for u in rl["units"] for t in u["listening"]["turns"]]) + "\n",
        }
        for name, text in files.items():
            (out / name).write_text(text, encoding="utf-8")
            print("wrote", name)
        return 0
    if a.cmd == "scan":
        doc = rl if a.workbook == "rl" else pw
        f = scan.scan_html(Path(a.html).read_text(encoding="utf-8"), doc, Path(a.html).name)
        if a.pdf_text:
            f += scan.scan_text(Path(a.pdf_text).read_text(encoding="utf-8"), doc, Path(a.pdf_text).name)
        if a.pdf_info:
            f += scan.scan_pdf_info(Path(a.pdf_info).read_text(encoding="utf-8"), doc, Path(a.pdf_info).name)
        print(json.dumps({"findings": f, "pass": not f}, ensure_ascii=False, indent=1))
        return 0 if not f else 1
    if a.cmd == "report":
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        inv = report.inventory(rl)
        flags = report.critique(rl)
        (out / "inventory-rl-v1.json").write_text(json.dumps(inv, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        lines = ["# Machine-critique flags (heuristic)", "",
                 "Automatic flags for a human reader. A flag is not a defect; see the critique notes for decisions.", ""]
        lines += [f"- `{qid}` {why}" for qid, why in flags] or ["- none"]
        (out / "critique-flags-rl-v1.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(json.dumps({"totals": inv["totals"], "positions": inv["answer_positions"], "length_clue": inv["length_clue"],
                          "flags": len(flags)}, ensure_ascii=False))
        return 0
    if a.cmd == "capture":
        print(adapters.dumps(adapters.capture(rl, a.question, a.text)), end="")
        return 0
    if a.cmd == "studypack":
        summary = studypack.build(rl, a.unit, Path(a.out))
        print(json.dumps(summary, ensure_ascii=False))
        for e in summary["errors"]:
            print("ERROR:", e, file=sys.stderr)
        return 1 if summary["errors"] else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
