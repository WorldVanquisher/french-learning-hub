#!/usr/bin/env python3
"""Build (or check) the workbench's copy of the SEALED Extraction 2.1 practice fixtures.

    python3 -I -B scripts/validation/extraction_practice/build_fixture.py --handoff H [--check]

H is the extraction lane's sealed handoff directory (handoff-2.1). Only H is read, never that
lane's live worktree. Before anything is built:
  1. H/SHA256SUMS and H/sample/workbooks/SHA256SUMS must verify (every file);
  2. a scratch overlay of the sealed code (this tree's shared baseline tools/extraction plus
     H/snapshot/extraction21.raw.tar) must reproduce the lane's sealed outputs byte for byte
     (`practice demo2 --check`, `practice workbooks-bundle --check`, bundle == H/sample/workbooks).

Inputs taken unchanged (byte for byte) from the seal:
  four flh_practice_review_feed_v1 feeds (y/en r1, r2 with `withdrawn`, r2 re-approved;
  savoir/connaître r1); the y/en r1 study packet v2 and its Markdown (session 2, Claude Code);
  the session 1 study packet and Markdown (Codex); both agent returns; the Codex return
  preview; the three Workbooks cases; the bundle MANIFEST.

Derived by running the sealed code in the scratch overlay (deterministic; the same run that
regenerates the sealed bundle byte for byte):
  GRADING fixtures: tutor packets with rubrics (the learner's explicit choice in that tool) for
  y/en r1, y/en r2 re-approved and savoir/connaître r1; the study packets for y/en r2 and
  savoir/connaître r1; the import preview of the Claude Code return (its text rendering must
  equal the sealed expected2/08-claude-code-return-preview.txt).

Writes web/src/prototype/extractionPracticeFixture.ts: every document as its exact text with
its SHA-256, so the page re-hashes each one before use (practiceFixture.ts) and refuses a
missing or altered document. --check writes nothing: it rebuilds in memory and exits 1 when the
module differs; exit 3 when a seal or the reproduction fails.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sealed_extraction as se  # noqa: E402

REPO = se.REPO
OUT = REPO / "web/src/prototype/extractionPracticeFixture.ts"

# (name in the module, path inside the handoff, role). Sealed: taken byte for byte.
SEALED = [
    ("feed-y-en-demo-r1.json", "sample/workbooks/feed-y-en-demo-r1.json", "feed"),
    ("feed-y-en-demo-r2.json", "sample/workbooks/feed-y-en-demo-r2.json", "feed"),
    ("feed-y-en-demo-r2-reapproved.json", "sample/workbooks/feed-y-en-demo-r2-reapproved.json", "feed"),
    ("feed-savoir-connaitre-demo-r1.json", "sample/workbooks/feed-savoir-connaitre-demo-r1.json", "feed"),
    ("study-y-en-r1.json", "sample/workbooks/study-packet.json", "study packet (session 2, Claude Code)"),
    ("study-y-en-r1.md", "sample/workbooks/study-packet.md", "study packet text"),
    ("session-1-codex-packet.json", "sample/session-1-codex/packet.json", "study packet (session 1, Codex)"),
    ("session-1-codex-packet.md", "sample/session-1-codex/packet.md", "study packet text"),
    ("session-1-codex-return.json", "sample/session-1-codex/proposals.fixture.json", "agent return (fixture)"),
    ("session-1-codex-preview.json", "sample/workbooks/duplicate-correction-preview.json", "import preview"),
    ("session-2-claude-code-return.json", "sample/session-2-claude-code/proposals.fixture.json", "agent return (fixture)"),
    ("cases.json", "sample/workbooks/cases.json", "Workbooks cases"),
    ("MANIFEST.json", "sample/workbooks/MANIFEST.json", "bundle manifest"),
]
# Derived by the sealed code in the overlay: (name, role).
GENERATED = [
    ("tutor-y-en-r1.json", "grading: tutor packet with rubrics, y/en revision 1"),
    ("tutor-y-en-r2.json", "grading: tutor packet with rubrics, y/en revision 2 re-approved"),
    ("tutor-savoir-connaitre-r1.json", "grading: tutor packet with rubrics, savoir/connaître revision 1"),
    ("study-y-en-r2.json", "study packet, y/en revision 2 re-approved"),
    ("study-y-en-r2.md", "study packet text"),
    ("study-savoir-connaitre-r1.json", "study packet, savoir/connaître revision 1"),
    ("study-savoir-connaitre-r1.md", "study packet text"),
    ("session-2-claude-code-preview.json", "import preview of the Claude Code return"),
]

# Runs inside the scratch overlay (cwd = its tools/extraction). It re-runs the lane's own 2.1
# pipeline and exports, at the moments the sealed feeds were written, what the feeds leave out.
DRIVER = r'''
import json, os, sys
sys.path.insert(0, os.getcwd())
from flh_extraction import practice_workflow as pw, practice_flow as pf, packet as pk, practice as pr
out, bundle = sys.argv[1], sys.argv[2]
cap = {}
orig = pw.Work.revise
def revise(self, src, with_review=False):
    # the y/en r1 feed was written just before this revision: export its keys now
    if "tutor-y-en-r1" not in cap:
        cap["tutor-y-en-r1"] = self.export("tutor", include_rubrics=True)
    return orig(self, src, with_review)
pw.Work.revise = revise
pf.pipeline(os.path.join(out, "run"))
w = pw.Work(os.path.join(out, "run", "work-y-en"))
w2 = pw.Work(os.path.join(out, "run", "work-savoir-connaitre"))
cap["tutor-y-en-r2"] = w.export("tutor", include_rubrics=True)
cap["tutor-savoir-connaitre-r1"] = w2.export("tutor", include_rubrics=True)
study = {"study-y-en-r2": w.export("study"), "study-savoir-connaitre-r1": w2.export("study")}
p2 = json.load(open(os.path.join(bundle, "study-packet.json"), encoding="utf-8"))
ret2 = json.load(open(os.path.join("fixtures", "practice_v1", "switch", "claude-code-return.json"), encoding="utf-8"))
rep2 = pk.import_preview(p2, ret2)
want = open(os.path.join("fixtures", "practice_v1", "expected2", "08-claude-code-return-preview.txt"), encoding="utf-8").read()
if pk.render_import(rep2) != want:
    sys.exit("the Claude Code preview does not render as the sealed expected2/08 text")
gen = os.path.join(out, "gen")
os.makedirs(gen)
def put(name, text):
    with open(os.path.join(gen, name), "w", encoding="utf-8", newline="") as f:
        f.write(text)
for k, v in cap.items():
    put(k + ".json", pr.dumps(v))
for k, v in study.items():
    put(k + ".json", pr.dumps(v)); put(k + ".md", pk.markdown(v))
put("session-2-claude-code-preview.json", pr.dumps(rep2))
print("generated", len(os.listdir(gen)), "files; the Claude Code preview renders as the sealed expected2/08 text")
'''


def generate(h: Path, tmp: Path) -> tuple[dict, list[str]]:
    tools = se.overlay(h, tmp / "overlay")
    log = se.reproduce(tools, tmp / "check", h)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C.UTF-8", "TMPDIR": str(tmp)}
    r = subprocess.run([sys.executable, "-B", "-c", DRIVER, str(tmp / "gen-run"), str(h / se.BUNDLE_DIR)], cwd=tools, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise se.SealError(f"generation failed: {(r.stdout + r.stderr)[-600:]}")
    gen = tmp / "gen-run" / "gen"
    got = {p.name: p.read_bytes() for p in gen.iterdir()}
    if sorted(got) != sorted(n for n, _ in GENERATED):
        raise se.SealError(f"generation wrote {sorted(got)}")
    log.append(r.stdout.strip())
    return got, log


def render(h: Path, digest: str, generated: dict, tar_sha: str) -> str:
    docs = []
    for name, rel, role in SEALED:
        raw = (h / rel).read_bytes()
        docs.append({"name": name, "origin": "sealed", "path": rel, "role": role, "sha256": hashlib.sha256(raw).hexdigest(), "text": raw.decode("utf-8")})
    for name, role in GENERATED:
        raw = generated[name]
        docs.append({"name": name, "origin": "generated", "path": None, "role": role, "sha256": hashlib.sha256(raw).hexdigest(), "text": raw.decode("utf-8")})
    source = {
        "owner": "extraction lane (Extraction 2.1 prototype, HANDOFF-2.1)",
        "handoff": "extraction2-20261119/handoff-2.1",
        "handoff_sha256sums": digest,
        "snapshot_tar_sha256": tar_sha,
        "generated_by": "scripts/validation/extraction_practice/build_fixture.py: the sealed snapshot code over this tree's "
                        "baseline tools/extraction, after it reproduced demo2 and the Workbooks bundle byte for byte",
        "synthetic": True,
    }
    head = ("// GENERATED by scripts/validation/extraction_practice/build_fixture.py --handoff <handoff-2.1>: do not edit.\n"
            "// The extraction lane's SEALED Extraction 2.1 practice fixtures (synthetic; the French is A1/A2 and\n"
            "// needs a native-speaker check before learner use). Each document is its exact text with its SHA-256:\n"
            "// practiceFixture.ts re-hashes every text before use and refuses a missing or altered one.\n\n")
    return (head + "export const FIXTURE_SOURCE = " + json.dumps(source, ensure_ascii=False, indent=1, sort_keys=True) + " as const;\n\n"
            + "export interface FixtureDocument {\n  name: string;\n  origin: \"sealed\" | \"generated\";\n  path: string | null;\n"
            + "  role: string;\n  sha256: string;\n  text: string;\n}\n\n"
            + "export const FIXTURE_DOCUMENTS: readonly FixtureDocument[] = " + json.dumps(docs, ensure_ascii=False, indent=1) + ";\n")


def main():
    args = sys.argv[1:]
    check = "--check" in args
    args = [a for a in args if a != "--check"]
    if len(args) != 2 or args[0] != "--handoff":
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    h = Path(os.path.realpath(args[1]))
    try:
        digest = se.verify_handoff(h)
        tar_sha = se.sha256_file(h / se.SNAPSHOT_TAR)
        with tempfile.TemporaryDirectory(prefix="flh-fixture-") as t:
            generated, log = generate(h, Path(t))
        text = render(h, digest, generated, tar_sha)
    except se.SealError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 3
    for line in log:
        print(line)
    print(f"handoff SHA256SUMS {digest}; snapshot tar {tar_sha}")
    if check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("fixture module up to date" if same else "fixture module differs from the sealed sources")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(text.encode())} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
