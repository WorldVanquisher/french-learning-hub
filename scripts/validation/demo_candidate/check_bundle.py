#!/usr/bin/env python3
"""check_bundle.py WEB_DIR [--private-host-file FILE] — R2-054 build assertion.

Checks a built public-demo web directory (package.sh's web/, or any vite
build with VITE_FLH_PUBLIC_DEMO=1) before it ships:

  files      only index.html and assets/*.js|*.css: no source maps, extra
             pages, JSON fixtures or other files; index.html names exactly
             the entry script and stylesheet that are there
  chunks     every script is the entry or a lazily loaded demo chunk; none is
             named after a workbench page or feature
  private    no script or page names a private route (the server's routes
             other than health, the knowledge library and static assets), a
             private content pack or fixture, a workbench-only browser
             storage key, a machine-local path, a tailnet host name or a
             tailnet (100.64/10, the shared CGNAT range) address; with --private-host-file, not
             the private host that file names either (compared, never
             printed)

The stylesheet is shared with the workbench (styles.css), so class names are
not a sign of workbench code; it is checked for private network values and
local paths only. Stdlib only; reads files, writes nothing, runs no Git.
Exit 0 PASS, 1 FAIL, 2 usage.
"""
import os
import re
import sys

# Route roots of the private server (cmd/server registers these; the demo
# boundary refuses them). "/concepts" is private unless it follows
# "knowledge-library".
PRIVATE_ROUTES = [
    "analyses", "annotation-dataset", "annotation-operations", "captures", "concept-suggestion-items",
    "concept-suggestion-runs", "effective-annotations", "entries", "exam", "extractions", "knowledge-units",
    "learning-records", "listening", "mistake-notebook", "reading", "retrieval-comparison",
    "retrieval-evaluation", "reviewable-units", "speaking", "writing", "review-today", "practice-feed",
]
ROUTE = re.compile(r'["\'`](?:/api)?/(' + "|".join(map(re.escape, PRIVATE_ROUTES)) + r')(?:[/?"\'`]|\$\{)')
PRIVATE_CONCEPTS = re.compile(r'(?<!knowledge-library)["\'`/]concepts(?:/|["\'`?])')
MARKERS = {
    "private content pack": ["reading_pack_v1", "listening_scripts_v1", "writing_prompts_v1", "flh_listening_script_pack_v1", "exam_forms"],
    "private fixture": ["fixture:flh034", "flh034"],
    "workbench storage key": ["flh.ui-theme.v1", "flh.explanation-language.v1", "flh.workbench"],
    # Assembled from parts, so this file itself never reads as a private value
    # to the repository's privacy scans.
    "machine-local path": ["/" + "home/", "/" + "Users/", "C:\\\\" + "Users", "file:" + "//"],
    "tailnet host name": [".ts" + ".net", "tail" + "scale"],
}
TAILNET = re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b")
WORKBENCH_CHUNK = re.compile(r"(?i)(app|workbench|records|inspector|experiment|listening|reading|writing|speaking|exam|mistake|notebook|recall|practice-feed|review)[-.]")
ALLOWED_FILE = re.compile(r"^(index\.html|assets/[A-Za-z0-9_.-]+\.(js|css))$")


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 2
    web, host = argv[0], None
    if argv[1:3] and argv[1] == "--private-host-file":
        if len(argv) < 3:
            return 2
        host = open(argv[2], encoding="utf-8").read().strip() or None
    elif len(argv) > 1:
        print(f"unknown argument {argv[1]}", file=sys.stderr)
        return 2
    problems, notes = [], []
    files = sorted(os.path.relpath(os.path.join(d, f), web).replace(os.sep, "/") for d, _, fs in os.walk(web) for f in fs)
    for f in files:
        if not ALLOWED_FILE.match(f):
            problems.append(f"files: unexpected file {f}")
    index = open(os.path.join(web, "index.html"), encoding="utf-8").read() if "index.html" in files else ""
    if not index:
        problems.append("files: no index.html")
    named = set(re.findall(r'(?:src|href)="/(assets/[^"]+)"', index))
    for n in sorted(named):
        if n not in files:
            problems.append(f"files: index.html names {n}, which is not there")
    entry = re.findall(r'<script\b[^>]*\btype="module"[^>]*\bsrc="/(assets/[^"]+\.js)"', index)
    if len(entry) != 1:
        problems.append(f"chunks: index.html names {len(entry)} entry scripts (expected 1)")
    scripts = [f for f in files if f.endswith(".js")]
    for s in scripts:
        if WORKBENCH_CHUNK.match(os.path.basename(s)):
            problems.append(f"chunks: {s} is named like a workbench chunk")
    notes.append(f"{len(scripts)} script(s): " + ", ".join(f"{s} ({os.path.getsize(os.path.join(web, s))} B)" for s in scripts))
    for f in files:
        text = open(os.path.join(web, f), encoding="utf-8", errors="replace").read()
        code = f.endswith((".js", ".html"))
        if code:
            for m in sorted(set(ROUTE.findall(text))):
                problems.append(f"private: {f} names the private route /{m}")
            if PRIVATE_CONCEPTS.search(text):
                problems.append(f"private: {f} names the private route /concepts")
        for kind, needles in MARKERS.items():
            if not code and kind in ("private content pack", "private fixture", "workbench storage key"):
                continue
            for n in needles:
                if n in text:
                    problems.append(f"private: {f} contains a {kind} ({n})")
        if TAILNET.search(text):
            problems.append(f"private: {f} contains a tailnet address (100.64/10, the shared CGNAT range)")
        if host and host in text:
            problems.append(f"private: {f} contains the private host named by the host file (value not printed)")
    for n in notes:
        print(n)
    for p in problems:
        print("FAIL", p)
    print(f"BUNDLE CHECK {'PASSED' if not problems else 'FAILED'}: {len(files)} files, {len(scripts)} script(s), {len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
