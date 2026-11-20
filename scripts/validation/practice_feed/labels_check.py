#!/usr/bin/env python3
"""Check that both message catalogs keep their approved labels.

    python3 -I -B scripts/validation/practice_feed/labels_check.py --approved APPROVED [--allow-changed FILE]

APPROVED is the tree whose labels were last approved: a directory or a .tar holding
web/src/i18n/en.ts and web/src/i18n/zh-CN.ts (for this lane, the sealed increment-4 tree).
Against the current tree's catalogs it checks, for each language:
  - every approved key is still present (nothing removed);
  - every approved key keeps exactly its approved text, unless listed in --allow-changed
    (one key per line, "key<TAB>reason"); a listed key that did not change is an error;
  - English and Chinese hold the same keys, with the same {placeholders};
  - a key ending in .one has its .other, and back.
Prints the counts (approved, kept, added) and exits 0 when all hold, 1 otherwise.
"""
import json
import re
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CATALOGS = ("web/src/i18n/en.ts", "web/src/i18n/zh-CN.ts")
# "key": "text", possibly with the text on the next line (as the formatter wraps long ones).
ENTRY = re.compile(r'^\s*("(?:[^"\\\n]|\\.)+"):\s*("(?:[^"\\\n]|\\.)*")', re.M)


def parse(text: str) -> dict:
    return {json.loads(m.group(1)): json.loads(m.group(2)) for m in ENTRY.finditer(text)}


def read_approved(src: Path, rel: str) -> str:
    if src.is_dir():
        return (src / rel).read_text(encoding="utf-8")
    with tarfile.open(src) as tf:
        for name in (rel, "./" + rel):
            try:
                return tf.extractfile(name).read().decode("utf-8")
            except KeyError:
                continue
    raise SystemExit(f"{src}: no {rel}")


def main():
    args = sys.argv[1:]
    allow = {}
    if "--allow-changed" in args:
        i = args.index("--allow-changed")
        for line in Path(args[i + 1]).read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                k, _, why = line.partition("\t")
                allow[k.strip()] = why.strip()
        args = args[:i] + args[i + 2:]
    if len(args) != 2 or args[0] != "--approved":
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    src = Path(args[1])
    problems, report = [], {}
    now = {}
    for rel in CATALOGS:
        old = parse(read_approved(src, rel))
        cur = parse((REPO / rel).read_text(encoding="utf-8"))
        now[rel] = cur
        removed = sorted(set(old) - set(cur))
        changed = sorted(k for k in set(old) & set(cur) if old[k] != cur[k])
        problems += [f"{rel}: approved key removed: {k}" for k in removed]
        problems += [f"{rel}: approved text changed without approval: {k}: {old[k]!r} -> {cur[k]!r}" for k in changed if k not in allow]
        problems += [f"{rel}: listed as changed but unchanged: {k}" for k in allow if k in old and k in cur and old[k] == cur[k]]
        report[rel] = {"approved": len(old), "kept_unchanged": len(old) - len(removed) - len(changed), "changed_with_reason": len([k for k in changed if k in allow]),
                       "added": len(set(cur) - set(old)), "total": len(cur)}
    en, zh = (now[r] for r in CATALOGS)
    problems += [f"key only in en.ts: {k}" for k in sorted(set(en) - set(zh))]
    problems += [f"key only in zh-CN.ts: {k}" for k in sorted(set(zh) - set(en))]
    ph = lambda s: sorted(set(re.findall(r"\{(\w+)\}", s)))
    problems += [f"placeholders differ for {k}: {ph(en[k])} vs {ph(zh[k])}" for k in sorted(set(en) & set(zh)) if ph(en[k]) != ph(zh[k])]
    for k in en:
        if k.endswith(".one") and k[:-4] + ".other" not in en:
            problems.append(f"{k} has no .other")
        if k.endswith(".other") and k[:-6] + ".one" not in en:
            problems.append(f"{k} has no .one")
    for rel, r in report.items():
        print(f"{rel}: {r['approved']} approved, {r['kept_unchanged']} kept unchanged, {r['changed_with_reason']} changed with a listed reason, {r['added']} added, {r['total']} now")
    for p in problems:
        print("FAIL", p)
    print("labels: OK" if not problems else f"labels: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
