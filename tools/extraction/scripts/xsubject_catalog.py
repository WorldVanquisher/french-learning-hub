"""Catalog of the cross-subject fixtures and their coverage by topic (offline; deterministic).

  python3 -I -B scripts/xsubject_catalog.py --write     # fixtures/xsubject_v1/CATALOG.json and COVERAGE.md
  python3 -I -B scripts/xsubject_catalog.py --check     # regenerate and compare

**Per source:** topic, subject, language, schema, data scope and licence, the gold claims it carries and its
split, and the phenomena it exercises (multi-span, cross-paragraph, chronology, contradiction, instruction-like
text, contact placeholders, no supported claim, revisions). Every source file must be in the catalog.

**Coverage report:** totals by topic and by phenomenon, and the gaps that no fixture covers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from flh_extraction import practice as pr  # noqa: E402
from flh_extraction import units as un  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "xsubject_v1")
LICENSE = "MIT (the repository's licence); synthetic text written for this repository; facts are general knowledge"
FRENCH = {"file": "../practice_v1/y_en.r1.json", "role": "French compatibility control (existing fixture)"}
PHENOMENA = ("multi_span", "cross_paragraph", "chronology", "contradiction", "instruction_like_text", "contact_placeholder",
             "no_supported_claim", "revisions", "explicit_spans_v2")


def _read(p: str):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def build() -> tuple[dict, str]:
    gold = _read(os.path.join(FIX, "gold", "gold_v2.json"))
    gdocs = {d["source_file"]: d for d in gold["documents"]}
    split = {sid: s for s, ids in gold["split"].items() for sid in ids}
    files = sorted(os.listdir(os.path.join(FIX, "sources")))
    by_id = {}
    for f in files:
        raw = _read(os.path.join(FIX, "sources", f))
        v1, info = un.read_source(raw)
        by_id.setdefault(v1["source_id"], []).append((f, raw, v1, info))
    rows = []
    for sid in sorted(by_id):
        revs = sorted(by_id[sid], key=lambda x: x[2]["revision"])
        f, raw, v1, info = revs[0]
        text = " ".join(pr.fold(v1["capture"][k]) for k in pr.LEARNER_FIELDS)
        g = next((gdocs[x[0]] for x in revs if x[0] in gdocs), None)
        claims = g["claims"] if g else []
        ph = {"multi_span": any(len(i.get("quotes", [])) > 1 for i in v1["proposal"]["items"]) or any(c["shape"] == "multi" for c in claims),
              "cross_paragraph": "\n\n" in v1["capture"]["original_context"] and any(c.get("require") == "all" for c in claims),
              "chronology": any(c.get("chronology") for c in claims),
              "contradiction": sid == "music-thirds-forum",
              "instruction_like_text": bool(re.search(r"(?im)^\s*(#+|system:).*\b(ignore|instructions?)\b", v1["capture"]["original_context"])),
              "contact_placeholder": bool(re.search(r"\[[^\]]*(e-?mail|phone)[^\]]*\]", text)),
              "no_supported_claim": bool(g) and not claims,
              "revisions": len(revs) > 1, "explicit_spans_v2": info["version"] == 2}
        rows.append({"source_id": sid, "files": [x[0] for x in revs], "schema_version": info["version"], "subject": v1.get("subject"),
                     "topic_area": g["topic_area"] if g else None, "language": v1.get("language"), "data_scope": v1.get("data_scope"),
                     "licence": LICENSE, "revisions": [x[2]["revision"] for x in revs], "proposal_items": len(v1["proposal"]["items"]),
                     "gold_claims": len(claims), "gold_shapes": {s: sum(1 for c in claims if c["shape"] == s) for s in ("single", "multi")},
                     "split": split.get(sid, "not in gold"), "phenomena": sorted(k for k, v in ph.items() if v)})
    cat = {"schema": "flh_xsubject_catalog_v1", "sources": rows, "control": FRENCH,
           "languages": sorted({r["language"] for r in rows} | {"fr"}), "files_listed": sum(len(r["files"]) for r in rows), "files_on_disk": len(files)}
    topics = {}
    for r in rows:
        t = topics.setdefault(r["topic_area"] or f"(no gold: {r['subject']})", {"sources": 0, "gold_claims": 0, "single": 0, "multi": 0})
        t["sources"] += 1
        t["gold_claims"] += r["gold_claims"]
        t["single"] += r["gold_shapes"]["single"]
        t["multi"] += r["gold_shapes"]["multi"]
    phen = {p: sorted(r["source_id"] for r in rows if p in r["phenomena"]) for p in PHENOMENA}
    gaps = [p for p, v in phen.items() if not v] + [
        "no language other than English and the French control", "no non-Latin script", "no table, list or formula layout",
        "no document longer than about 600 characters", "no real learner text (by design)", "one author for sources, gold and proposals"]
    cat["coverage"] = {"by_topic": dict(sorted(topics.items())), "by_phenomenon": phen, "gaps": gaps}
    L = ["# Cross-subject fixture coverage", "", f"{len(rows)} sources ({cat['files_on_disk']} files), languages {', '.join(cat['languages'])}. "
         f"Licence: {LICENSE}.", "", "| Topic | Sources | Gold claims | Single-span | Multi-span |", "|---|---|---|---|---|"]
    L += [f"| {k} | {v['sources']} | {v['gold_claims']} | {v['single']} | {v['multi']} |" for k, v in cat["coverage"]["by_topic"].items()]
    L += ["", "| Phenomenon | Sources |", "|---|---|"] + [f"| {p} | {', '.join(v) or '**none**'} |" for p, v in phen.items()]
    L += ["", "Gaps:", ""] + [f"- {x}" for x in gaps]
    return cat, "\n".join(L) + "\n"


CONSUMER_FILES = [
    ("expected/music/units.json", "flh_learning_units_v1", "experimental", "units with spans, review reasons and recall"),
    ("expected/inbox/inbox-r2.json", "flh_review_inbox_v1", "experimental", "review inbox for a UI"),
    ("expected/revisions/compare-r2-to-r3.json", "flh_learning_units_compare_v1", "experimental", "revision comparison"),
    ("expected/revisions/rerun-statuses.json", "flh_rerun_status_v1", "experimental", "rerun outcomes"),
    ("expected/recall/contradictions.json", "flh_unit_contradictions_v1", "experimental", "two-source contradiction"),
    ("expected/recall/feed.json", "flh_practice_review_feed_v1 + flh_practice_feed_additions_v1", "stable", "practice feed"),
    ("expected/music/loop.json", "flh_learning_loop_v1", "experimental", "learning loop"),
    ("expected/vocabulary/terms-music-thirds.json", "flh_vocabulary_reference_v1", "experimental", "vocabulary reference"),
    ("expected/handoff/handoff.json", "flh_unit_handoff_v1", "experimental", "agent handoff companion"),
    ("expected/handoff/followup-codex.json", "flh_unit_followup_v1", "experimental", "agent follow-up"),
    ("sources/chem_water_states.v2.json", "flh_practice_source_v2", "experimental", "source contract v2"),
    ("eval/scorecard.json", "flh_units_eval_v1.scorecard", "experimental", "trend scorecard"),
    ("expected/practice/music-practice.json", "flh_unit_practice_v1", "experimental", "practice prompts of four recall types"),
    ("expected/practice/graded-examples.json", "flh_unit_practice_graded_examples_v1", "experimental", "expected outcomes for sample answers"),
]


def consumers() -> dict:
    """The versioned fixture set for downstream consumers (EXT-130): path, schema, stability, SHA-256."""
    rows = []
    for path, schema, stab, what in CONSUMER_FILES:
        with open(os.path.join(FIX, path), encoding="utf-8") as fh:
            rows.append({"path": path, "schema": schema, "stability": stab, "what": what, "sha256": pr.sha(fh.read())})
    return {"schema": "flh_xsubject_consumer_fixtures_v1", "version": "2026-11-21.2", "files": rows,
            "rule": "experimental schemas may change without a version bump; a changed file gets a new manifest version"}


def inputs() -> dict:
    """Selected configuration and input digests of the cross-subject runs (EXT-144); nothing host-specific."""
    from flh_extraction import service as svc
    from flh_extraction import unit_eval as ue
    rows = {}
    for sub in ("sources", "gold", "practice", "regression"):
        d = os.path.join(FIX, sub)
        for n in sorted(os.listdir(d)):
            with open(os.path.join(d, n), encoding="utf-8") as fh:
                rows[f"{sub}/{n}"] = pr.sha(fh.read())
    with open(os.path.join(HERE, "..", "..", "tools", "extraction", "fixtures", "practice_v1", "y_en.r1.json"), encoding="utf-8") as fh:
        rows["../practice_v1/y_en.r1.json (French control)"] = pr.sha(fh.read())
    return {"schema": "flh_xsubject_inputs_v1", "inputs_sha256": rows,
            "configuration": {"drafter": pr.DRAFTER, "service_deployment_id": svc.manifest()["deployment_id"], "units_schema": un.SCHEMA,
                              "coverage_threshold": ue.COVER, "baseline_number_words": ue.NUMBER.pattern, "baseline_v2_label_rule": ue.LABEL.pattern,
                              "batch_rule": "approve exactly the review's proposed batch"},
            "not_recorded_here": "interpreter version, CPU and timings (host-specific; see the run evidence)"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    cat, md = build()
    files = {"CATALOG.json": pr.dumps(cat), "COVERAGE.md": md, "CONSUMERS.json": pr.dumps(consumers()), "INPUTS.json": pr.dumps(inputs())}
    if a.write:
        for n, t in files.items():
            with open(os.path.join(FIX, n), "w", encoding="utf-8") as fh:
                fh.write(t)
        print(md, end="")
        return 0 if cat["files_listed"] == cat["files_on_disk"] else 1
    bad = []
    for n, t in files.items():
        with open(os.path.join(FIX, n), encoding="utf-8") as fh:
            if fh.read() != t:
                bad.append(n)
    print("check: catalog current" if not bad else "CHECK FAILED: " + ", ".join(bad))
    return 0 if not bad and cat["files_listed"] == cat["files_on_disk"] else 1


if __name__ == "__main__":
    sys.exit(main())
