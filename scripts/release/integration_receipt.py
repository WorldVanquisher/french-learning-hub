#!/usr/bin/env python3
"""Integration receipts: which sealed lanes made a candidate tree, and which checks ran on it.

  integration_receipt.py init     RECEIPT_DIR --assembly TREE.assembly.json --selected SELECTED.json
  integration_receipt.py run      RECEIPT_DIR --id ID --title TEXT [--scope S] [--required-for T]... [--tree DIR]
                                  [--artifact FILE]... [--parse KIND] [--resume] -- COMMAND...
  integration_receipt.py record   RECEIPT_DIR --id ID --title TEXT --status S --evidence FILE [--tree-id ID]
                                  [--artifact FILE]... [--counts JSON] [--scope S] [--required-for T]... [--command TEXT]
  integration_receipt.py check    RECEIPT_DIR [--target local-rehearsal|staging]   # exit 0 READY, 1 BLOCKED, 2 invalid
  integration_receipt.py summary  RECEIPT_DIR [--target T] [--width N]             # stale and failed evidence first
  integration_receipt.py markdown RECEIPT_DIR [--target T]
  integration_receipt.py order    RECEIPT_DIR                                      # lane review order and its reasons
  integration_receipt.py carry    RECEIPT_DIR OLD_RECEIPT_DIR    # older results, shown STALE until rerun

Format `flh-integration-receipt/v1` (RECEIPT_DIR/receipt.json; evidence paths relative to it). It
follows `flh-release-report/v1` (scripts/release/release_report.py): the same statuses
(pass|fail|pending|unavailable|skipped), required_for targets, next actions, and evaluation that
trusts nothing in the file:
  candidate      the assembled tree (tree id, files, content digest) and the digests of the
                 assembly and selection files that produced it
  lanes[]        per lane: the seal it was imported from (id, SHA256SUMS digest), the seals it
                 supersedes, the shared base tree, its snapshot identity and change counts
  pending[]      owner proposals deliberately left out of the candidate
  checks[]       id, title, scope (candidate|package|bundle|synthetic|owner), required_for[],
                 command, started_at, finished_at, seconds, exit, status, counts{ran, skipped, ...},
                 tree_id (the tree the command ran on, re-identified after it finished),
                 artifacts[{name, sha256}] and evidence{path, sha256}
Effective state (`check`): evidence missing or changed -> UNAVAILABLE/CHANGED; a check whose tree id
is not the candidate's, or whose artifact file now has other bytes under the same name -> STALE;
a required check that is absent -> MISSING. READY only when every check required for the target
passes with intact, current evidence. A receipt that claims READY while a required check is
missing, failed or stale is invalid (exit 2). Standard library only; no Git, no network.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time

FORMAT = "flh-integration-receipt/v1"
STATUSES = ("pass", "fail", "pending", "unavailable", "skipped")
TARGETS = ("local-rehearsal", "staging")
SCOPES = ("candidate", "package", "bundle", "synthetic", "owner")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.realpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "deploy", "aws", "private-staging", "staging"))
sys.path.insert(0, HERE)                       # integration_candidate (python3 -I does not add the script's directory)
import bundle_identity as BI  # noqa: E402

# What READY needs, per target. staging adds the owner-only gates of release_report.py.
REQUIRED = {
    "local-rehearsal": ["assembly", "go", "web-typecheck", "web-test", "web-build", "python-suites",
                        "speaking-strict", "learning-day", "practice-feed", "demo-package-gate",
                        "demo-browser", "staging-bundle", "release-report"],
}
REQUIRED["staging"] = REQUIRED["local-rehearsal"] + ["aws-plan-check", "staging-identity"]
MARK = {"pass": "PASS", "fail": "FAIL", "pending": "PENDING", "unavailable": "UNAVAILABLE", "skipped": "SKIPPED",
        "stale": "STALE", "changed": "CHANGED", "missing": "MISSING"}
# How each effective state reads to an operator: a STALE pass is not a failure, it is old.
MEANING = {"stale": "ran on other bytes; rerun on the candidate (not a failure)",
           "changed": "evidence edited after it was recorded; rerun, never edit",
           "missing": "never run for this candidate", "unavailable": "evidence file absent",
           "fail": "ran on the candidate and failed", "pending": "waiting", "skipped": "not run by choice",
           "pass": "passed on the candidate"}


class Invalid(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def tree_identity(d):
    rows = BI.scan(d)
    return {"tree_id": BI.tree_id(d, rows), "files": len(rows), "content_sha256": BI.content_digest(rows)}


# --- the receipt file ------------------------------------------------------------------------------
def path_of(rd):
    return os.path.join(rd, "receipt.json")


def load(rd):
    with open(path_of(rd)) as fh:
        r = json.load(fh)
    if r.get("format") != FORMAT:
        raise Invalid(f"format is {r.get('format')!r}, not {FORMAT}")
    for k in ("candidate", "lanes", "checks"):
        if k not in r:
            raise Invalid(f"missing {k}")
    ids = [c.get("id") for c in r["checks"]]
    if len(ids) != len(set(ids)):
        raise Invalid("duplicate check id")
    for c in r["checks"]:
        if c.get("status") not in STATUSES:
            raise Invalid(f"check {c.get('id')}: status {c.get('status')!r}")
        if c.get("scope", "candidate") not in SCOPES:
            raise Invalid(f"check {c.get('id')}: scope {c.get('scope')!r}")
        if c["status"] in ("pass", "fail") and not (c.get("evidence") or {}).get("path"):
            raise Invalid(f"check {c['id']}: a {c['status']} result needs an evidence file")
        if (c.get("evidence") or {}).get("path", "").startswith(("/", "..")):
            raise Invalid(f"check {c['id']}: evidence path must be inside the receipt directory")
    return r


def save(rd, r):
    tmp = path_of(rd) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(r, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path_of(rd))


def init(rd, assembly, selected):
    if os.path.exists(path_of(rd)):
        raise Invalid(f"{path_of(rd)} exists")
    with open(assembly) as fh:
        A = json.load(fh)
    with open(selected) as fh:
        S = json.load(fh)
    if A.get("selected_sha256") != sha256_file(selected):
        raise Invalid("the assembly was not made from this selected file")
    lanes = []
    for ln in S["order"]:
        L = S["lanes"][ln]
        snap = {k: v for k, v in (L.get("snapshot_identity") or {}).items()}
        for s in L.get("sources", []):
            if s.get("kind") == "tar" and s.get("sha256"):
                snap.setdefault("tar_sha256", s["sha256"])
                snap.setdefault("tar", os.path.basename(s["path"]))
        import integration_candidate as IC
        lanes.append({"lane": ln, "tree_id": IC.lane_tree_id(selected, ln),
                      "seal_id": L["seal"].get("id"), "seal_digest": L["seal"]["digest"],
                      "seal_files": L["seal"]["files"], "base_tree_id": S["base"]["tree_id"], "base": L.get("base"),
                      "supersedes": [{"id": x.get("id"), "digest": x.get("digest")} for x in L.get("supersedes", [])],
                      "snapshot": snap, "counts": L["counts"], "paths": sorted(L["delta"])})
    os.makedirs(os.path.join(rd, "evidence"), exist_ok=True)
    r = {"format": FORMAT, "created_at": now(),
         "candidate": dict(A["tree"], assembly_sha256=sha256_file(assembly), selected_sha256=A["selected_sha256"]),
         "base_tree_id": S["base"]["tree_id"], "order": S["order"], "lanes": lanes,
         "shared_paths": S.get("shared_paths", {}), "merges": {p: m.get("merged_sha256") for p, m in A["merges"].items()},
         "pending": [{"id": p["id"], "lane": p.get("lane"), "why": p.get("why", ""),
                      "patch_sha256": p.get("patch_sha256")} for p in S.get("pending_proposals", [])],
         "requires": [{"lane": p["lane"], "what": p["id"], "needs": p["after"], "why": p.get("why", "")}
                      for p in S.get("pending_proposals", []) if p.get("after")],
         "checks": []}
    shutil.copyfile(assembly, os.path.join(rd, "evidence", "assembly.json"))
    r["checks"].append({"id": "assembly", "title": "Candidate assembled from the selected seals", "scope": "candidate",
                        "required_for": list(TARGETS), "status": "pass", "exit": 0, "started_at": A["assembled_at"],
                        "finished_at": A["assembled_at"], "seconds": None, "tree_id": A["tree"]["tree_id"],
                        "command": "integration_candidate.py assemble SELECTED.json --out TREE",
                        "counts": {"files": A["tree"]["files"], "merges": len(A["merges"])},
                        "evidence": {"path": "evidence/assembly.json",
                                     "sha256": sha256_file(os.path.join(rd, "evidence", "assembly.json"))}})
    save(rd, r)
    return r


# --- counts from logs ----------------------------------------------------------------------------------
def parse_counts(kind, text, json_path=None):
    c = {}
    # the receipt's own header and footer lines ("$ command", "# exit ...") are not test output
    text = "\n".join(line for line in text.splitlines() if not line.startswith(("$ ", "# ")))
    if kind == "go":
        c["packages_ok"] = len(re.findall(r"^ok\s+\S+", text, re.M))
        c["packages_failed"] = len(re.findall(r"^FAIL\s+\S+", text, re.M))
        c["packages_no_tests"] = len(re.findall(r"^\?\s+\S+\s+\[no test files\]", text, re.M))
        c["failures"] = len(re.findall(r"^\s*--- FAIL", text, re.M))
        c["skipped"] = len(re.findall(r"^\s*--- SKIP", text, re.M))
    elif kind == "vitest":
        tf = re.findall(r"Test Files\s+(.+?)\s*\((\d+)\)", text)
        ts = re.findall(r"^\s*Tests\s+(.+?)\s*\((\d+)\)", text, re.M)
        if tf:
            c["files"] = int(tf[-1][1])
        if ts:
            parts = dict((k, int(v)) for v, k in re.findall(r"(\d+)\s+(passed|failed|skipped|todo)", ts[-1][0]))
            c.update({"ran": int(ts[-1][1]), "passed": parts.get("passed", 0), "failures": parts.get("failed", 0),
                      "skipped": parts.get("skipped", 0) + parts.get("todo", 0)})
    elif kind == "unittest":
        ran = re.findall(r"^Ran (\d+) tests?", text, re.M)
        if ran:
            c["ran"] = sum(int(x) for x in ran)
        for k, pat in (("skipped", r"skipped=(\d+)"), ("expected_failures", r"expected failures=(\d+)"),
                       ("failures", r"(?<!expected )failures=(\d+)"), ("errors", r"errors=(\d+)")):
            c[k] = sum(int(x) for x in re.findall(pat, text))
    elif kind == "python-suites" and json_path and os.path.isfile(json_path):
        with open(json_path) as fh:
            js = json.load(fh)
        for k in ("ran", "skipped", "expected_failures", "failures", "errors"):
            c[k] = sum(s.get(k, 0) or 0 for s in js.get("suites", []))
        c["suites"] = {s["label"]: {k: s.get(k) for k in ("status", "ran", "skipped", "exit")} for s in js.get("suites", [])}
    elif kind == "results":                       # browser walkthroughs and suites
        items = None
        if json_path and os.path.isfile(json_path):
            with open(json_path) as fh:
                items = json.load(fh)
        if isinstance(items, list) and all(isinstance(x, dict) and "pass" in x for x in items):
            c["ran"], c["passed"] = len(items), sum(1 for x in items if x["pass"] is True)
        else:                                     # "N/M checks passed" lines, and {"pass":N,"fail":M} summaries
            pairs = [(int(a), int(b)) for a, b in re.findall(r"(\d+)\s*/\s*(\d+)\s+checks? passed", text)]
            pairs += [(int(a), int(a) + int(b)) for a, b in re.findall(r'"pass":\s*(\d+),\s*"fail":\s*(\d+)', text)]
            if pairs:
                c["passed"], c["ran"] = sum(a for a, _ in pairs), sum(b for _, b in pairs)
                c["suites"] = len(pairs)
        if "ran" in c:
            c["failures"] = c["ran"] - c["passed"]
    return c


# --- run / record ------------------------------------------------------------------------------------
def upsert(r, check):
    r["checks"] = [c for c in r["checks"] if c["id"] != check["id"]] + [check]


def artifacts_of(paths):
    return [{"name": os.path.basename(p), "path": os.path.realpath(p), "sha256": sha256_file(p)} for p in paths]


def run_check(rd, a):
    r = load(rd)
    cand = r["candidate"]["tree_id"]
    cmd_text = " ".join(a.command)
    if a.resume:
        prev = next((c for c in r["checks"] if c["id"] == a.id), None)
        if prev:
            ev = evaluate(r, rd)
            eff = next(c for c in ev["checks"] if c["id"] == a.id)
            if eff["effective"] == "pass" and prev.get("command") == cmd_text:
                print(f"{a.id}: kept (already PASS on {cand[:12]} with intact evidence; --resume)")
                return 0
    tree_before = tree_identity(a.tree)["tree_id"] if a.tree else None
    if a.tree and tree_before != cand and not a.allow_other_tree:
        raise Invalid(f"{a.tree} is tree {tree_before[:12]}, not the candidate {cand[:12]}: refusing to record "
                      "its result against this receipt")
    log = os.path.join(rd, "evidence", f"{a.id}.log")
    started, t0 = now(), time.time()
    with open(log, "w") as fh:
        fh.write(f"$ {cmd_text}\n# cwd: {'TREE' if a.tree and os.path.realpath(a.cwd or a.tree) == os.path.realpath(a.tree) else (a.cwd or '.')}"
                 f"\n# started {started}\n")
        fh.flush()
        p = subprocess.run(a.command, cwd=a.cwd or a.tree, stdout=fh, stderr=subprocess.STDOUT)
    secs = round(time.time() - t0, 1)
    tree_after = tree_identity(a.tree)["tree_id"] if a.tree else None
    with open(log, "a") as fh:
        fh.write(f"\n# exit {p.returncode} after {secs} s\n")
        if a.tree:
            fh.write(f"# tree before {tree_before} after {tree_after}\n")
    with open(log, errors="replace") as fh:
        text = fh.read()
    counts = parse_counts(a.parse, text, a.json) if a.parse else {}
    status = "pass" if p.returncode == 0 else "fail"
    note = None
    if a.tree and tree_after != tree_before:
        status, note = "fail", f"the command changed the tree ({tree_before[:12]} -> {tree_after[:12]})"
    check = {"id": a.id, "title": a.title, "scope": a.scope, "required_for": a.required_for or [],
             "command": cmd_text, "started_at": started, "finished_at": now(), "seconds": secs, "exit": p.returncode,
             "status": status, "counts": counts, "tree_id": tree_after if a.tree else a.tree_id,
             "artifacts": artifacts_of(a.artifact), "note": note,
             "next_action": None if status == "pass" else (a.next_action or f"read evidence/{a.id}.log and rerun"),
             "evidence": {"path": f"evidence/{a.id}.log", "sha256": sha256_file(log)}}
    if a.json and os.path.isfile(a.json):
        dst = os.path.join(rd, "evidence", f"{a.id}.json")
        shutil.copyfile(a.json, dst)
        check["evidence_json"] = {"path": f"evidence/{a.id}.json", "sha256": sha256_file(dst)}
    r = load(rd)                                    # reload: another stage may have written meanwhile
    upsert(r, check)
    save(rd, r)
    print(f"{a.id}: {MARK[status]} exit {p.returncode} in {secs} s"
          + (f" [{counts_text(counts)}]" if counts else "") + (f" ({note})" if note else ""))
    return 0 if status == "pass" else 1


def record_check(rd, a):
    r = load(rd)
    src = a.evidence
    dst_rel = f"evidence/{a.id}{os.path.splitext(src)[1] or '.txt'}"
    shutil.copyfile(src, os.path.join(rd, dst_rel))
    check = {"id": a.id, "title": a.title, "scope": a.scope, "required_for": a.required_for or [],
             "command": a.command, "started_at": a.started_at or now(), "finished_at": now(), "seconds": a.seconds,
             "exit": a.exit, "status": a.status, "counts": json.loads(a.counts) if a.counts else {},
             "tree_id": a.tree_id, "artifacts": artifacts_of(a.artifact),
             "next_action": a.next_action if a.status != "pass" else None,
             "evidence": {"path": dst_rel, "sha256": sha256_file(os.path.join(rd, dst_rel))}}
    if a.status != "pass" and not check["next_action"]:
        raise Invalid("a non-pass record needs --next-action")
    upsert(r, check)
    save(rd, r)
    print(f"{a.id}: recorded {MARK[a.status]}")
    return 0


def carry(rd, old_rd):
    """Copy an older receipt's checks (and their evidence) into this one. A carried result keeps its own
    tree id, so it shows as STALE here until the check is rerun on this candidate: old evidence is visible,
    never counted."""
    r, old = load(rd), load(old_rd)
    have = {c["id"] for c in r["checks"]}
    n = 0
    for c in old["checks"]:
        if c["id"] in have:
            continue
        c = dict(c, carried_from=old["candidate"]["tree_id"])
        for key in ("evidence", "evidence_json"):
            ev = c.get(key)
            if ev and ev.get("path"):
                dst = f"evidence/carried-{os.path.basename(ev['path'])}"
                shutil.copyfile(os.path.join(old_rd, ev["path"]), os.path.join(rd, dst))
                c[key] = dict(ev, path=dst)
        r["checks"].append(c)
        n += 1
    save(rd, r)
    return n


# --- evaluation ------------------------------------------------------------------------------------------
def evaluate(r, rd, target="local-rehearsal"):
    cand = r["candidate"]["tree_id"]
    out = []
    for c in r["checks"]:
        eff, why = c["status"], c.get("note") or ""
        ev = c.get("evidence") or {}
        if ev.get("path"):
            p = os.path.join(rd, ev["path"])
            if not os.path.isfile(p):
                eff, why = "unavailable", f"evidence file missing: {ev['path']}"
            elif sha256_file(p) != ev.get("sha256"):
                eff, why = "changed", f"evidence changed after it was recorded: {ev['path']}"
        if eff in ("pass", "fail") and c.get("tree_id") and c["tree_id"] != cand:
            eff, why = "stale", f"ran on tree {c['tree_id'][:12]}, not the candidate {cand[:12]}"
        if eff in ("pass", "fail"):
            for art in c.get("artifacts") or []:
                p = art.get("path")
                if not (p and os.path.isfile(p)) and os.path.isfile(os.path.join(rd, "artifacts", art["name"])):
                    p = os.path.join(rd, "artifacts", art["name"])       # a receipt carried with its artifacts
                if not (p and os.path.isfile(p)):
                    eff, why = "unavailable", (f"artifact {art['name']} is not here to recheck; put it in "
                                               f"artifacts/ beside the receipt, or rerun")
                    break
                if sha256_file(p) != art["sha256"]:
                    eff, why = "stale", f"artifact {art['name']} now has other bytes than the ones tested"
                    break
        if not why:
            why = MEANING[eff] + (f" ({counts_text(c.get('counts'))})" if c.get("counts") else "")
        required = target in (c.get("required_for") or [])
        nxt = c.get("next_action") if eff == c["status"] else (
            f"rerun `{c.get('command', c['id'])}` on tree {cand[:12]}" if eff == "stale" else
            "rerun the check: evidence must be regenerated, never edited")
        out.append(dict(c, effective=eff, reason=why, required=required, blocking=required and eff != "pass",
                        next=nxt if eff != "pass" else None))
    have = {c["id"] for c in out}
    for cid in REQUIRED[target]:
        if cid not in have:
            out.append({"id": cid, "title": "(not recorded)", "scope": "owner" if cid in ("aws-plan-check", "staging-identity") else "candidate",
                        "status": "pending", "effective": "missing", "required": True, "blocking": True,
                        "reason": MEANING["missing"], "required_for": [target],
                        "next": OWNER_NEXT.get(cid, f"run the `{cid}` check on tree {cand[:12]} and record it")})
    blockers = [c for c in out if c["blocking"]]
    verdict = "BLOCKED" if blockers else "READY"
    claimed = r.get("claimed_verdict", {}).get(target)
    if claimed == "READY" and verdict != "READY":
        raise Invalid(f"the receipt claims READY for {target}, but {len(blockers)} required check(s) are not current passes: "
                      + ", ".join(f"{c['id']} {MARK[c['effective']]}" for c in blockers[:6]))
    return {"verdict": verdict, "target": target, "checks": out, "blockers": blockers}


OWNER_NEXT = {
    "aws-plan-check": "owner: RUNBOOK §3.2 terraform plan + plan_check.py, then release_report.py collect --plan-json",
    "staging-identity": "owner: RUNBOOK §5 install on the staging host, then release_report.py collect --host-status",
}


def counts_text(c):
    if not c:
        return ""
    keys = [k for k in ("ran", "passed", "skipped", "expected_failures", "failures", "errors", "files",
                        "packages_ok", "packages_failed") if k in c and c[k] is not None]
    return ", ".join(f"{k} {c[k]}" for k in keys)


def wrap(text, width, indent):
    return textwrap.fill(text, width=max(width, 30), subsequent_indent=" " * indent, break_long_words=True,
                         break_on_hyphens=False)


def summary(r, ev, width=None):
    """Plain text; stale and failed first; every line fits WIDTH (default: the terminal's)."""
    width = width or shutil.get_terminal_size((100, 24)).columns
    cand = r["candidate"]
    lines = [wrap(f"{ev['verdict']} for {ev['target']}: tree {cand['tree_id']} ({cand['files']} files)", width, 2)]
    for ln in r["lanes"]:
        lines.append(wrap(f"  lane {ln['lane']}: seal {ln['seal_digest'][:12]} ({ln.get('seal_id') or '-'})", width, 4))
    order = {"fail": 0, "changed": 1, "stale": 2, "missing": 3, "unavailable": 4, "pending": 5, "skipped": 6, "pass": 7}
    groups = {}
    for c in sorted(ev["checks"], key=lambda c: (order[c["effective"]], c["id"])):
        groups.setdefault(c["effective"], []).append(c)
    for eff in sorted(groups, key=order.get):
        title = {"fail": "Failed on the candidate", "stale": "Stale (ran on other bytes; not failures)",
                 "changed": "Evidence changed", "missing": "Required but never run", "pass": "Passed"}.get(eff, MARK[eff].title())
        lines.append(wrap(f"{title} ({len(groups[eff])}):", width, 2))
        for c in groups[eff]:
            flag = "!" if c["blocking"] else " "
            lines.append(wrap(f"{flag} {c['id']}: {c['reason']}", width, 4))
            if c.get("next"):
                lines.append(wrap(f"    next: {c['next']}", width, 10))
    lines.append(wrap(f"{len(ev['blockers'])} blocking for {ev['target']}; '!' marks them.", width, 2))
    return "\n".join(lines)


def markdown(r, ev):
    cand = r["candidate"]
    m = [f"# Integration receipt: tree `{cand['tree_id']}`", "",
         f"**{ev['verdict']}** for `{ev['target']}` ({len(ev['blockers'])} blocking). Format `{FORMAT}`, "
         f"created {r.get('created_at')}.", "",
         "| Lane | Seal | SHA256SUMS digest | Supersedes | Changes (A/M/D) |", "| --- | --- | --- | --- | --- |"]
    for ln in r["lanes"]:
        c = ln["counts"]
        m.append(f"| {ln['lane']} | {ln.get('seal_id') or ''} | `{ln['seal_digest'][:16]}` | "
                 f"{', '.join(x['id'] for x in ln.get('supersedes', [])) or '-'} | {c['A']}/{c['M']}/{c['D']} |")
    m += ["", "| Check | Scope | Required | State | Why | Exit | Seconds | Evidence |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for c in ev["checks"]:
        e = c.get("evidence") or {}
        m.append(f"| `{c['id']}` | {c.get('scope', '')} | {'yes' if c['required'] else 'no'} | **{MARK[c['effective']]}** | "
                 f"{c['reason']} | {c.get('exit', '')} | {c.get('seconds') or ''} | {'`' + e['path'] + '`' if e.get('path') else ''} |")
    if r.get("pending"):
        m += ["", "Left out on purpose (pending owner proposals):", ""]
        m += [f"- `{p['id']}` ({p.get('lane')}): {p.get('why')}" for p in r["pending"]]
    if ev["blockers"]:
        m += ["", "To become READY:", ""] + [f"- `{c['id']}`: {c['next']}" for c in ev["blockers"]]
    return "\n".join(m) + "\n"


# --- review order ------------------------------------------------------------------------------------------
def review_order(r):
    """Lane order from file-level facts only: a lane that changes a path another lane also changes
    follows it in the selected order; extra 'requires' edges come from the receipt."""
    order = list(r["order"])
    reasons = {ln: [] for ln in order}
    for p, lns in (r.get("shared_paths") or {}).items():
        for i in range(1, len(lns)):
            reasons[lns[i]].append(f"merges {p} after {lns[i - 1]}")
    for dep in r.get("requires", []):
        reasons.setdefault(dep["lane"], []).append(f"{dep['what']} needs {dep['needs']} merged first ({dep['why']})")
        if order.index(dep["needs"]) > order.index(dep["lane"]):
            raise Invalid(f"order puts {dep['lane']} before {dep['needs']}, which it requires")
    return [{"step": i + 1, "lane": ln, "after": order[:i], "reasons": reasons.get(ln, []),
             "state": "proposed (no PR is assumed to exist)"} for i, ln in enumerate(order)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("dir")
    i.add_argument("--assembly", required=True)
    i.add_argument("--selected", required=True)
    for name in ("run", "record"):
        p = sub.add_parser(name)
        p.add_argument("dir")
        p.add_argument("--id", required=True)
        p.add_argument("--title", required=True)
        p.add_argument("--scope", choices=SCOPES, default="candidate")
        p.add_argument("--required-for", action="append", choices=TARGETS)
        p.add_argument("--artifact", action="append", default=[])
        p.add_argument("--next-action")
        p.add_argument("--tree-id")
        if name == "run":
            p.add_argument("--tree")
            p.add_argument("--cwd")
            p.add_argument("--parse", choices=("go", "vitest", "unittest", "python-suites", "results"))
            p.add_argument("--json", help="a JSON result file the command writes (kept as evidence)")
            p.add_argument("--resume", action="store_true", help="keep an intact PASS of the same command on this tree")
            p.add_argument("--allow-other-tree", action="store_true")
        else:
            p.add_argument("--status", required=True, choices=STATUSES)
            p.add_argument("--evidence", required=True)
            p.add_argument("--counts")
            p.add_argument("--command", default="")
            p.add_argument("--exit", type=int)
            p.add_argument("--seconds", type=float)
            p.add_argument("--started-at")
    cr = sub.add_parser("carry")
    cr.add_argument("dir")
    cr.add_argument("old")
    for name in ("check", "summary", "markdown", "order"):
        p = sub.add_parser(name)
        p.add_argument("dir")
        p.add_argument("--target", choices=TARGETS, default="local-rehearsal")
        if name == "summary":
            p.add_argument("--width", type=int)
    argv = list(sys.argv[1:] if argv is None else argv)
    command = []
    if "--" in argv:                                # run ... -- COMMAND...: the command is never parsed as options
        k = argv.index("--")
        argv, command = argv[:k], argv[k + 1:]
    a = ap.parse_args(argv)
    a.command = command
    try:
        if a.cmd == "init":
            r = init(a.dir, a.assembly, a.selected)
            print(f"receipt for tree {r['candidate']['tree_id']} ({len(r['lanes'])} lanes)")
            return 0
        if a.cmd == "run":
            if not a.command:
                raise Invalid("no command after --")
            return run_check(a.dir, a)
        if a.cmd == "record":
            return record_check(a.dir, a)
        if a.cmd == "carry":
            n = carry(a.dir, a.old)
            print(f"carried {n} check(s); they show as STALE until rerun on this candidate")
            return 0
        r = load(a.dir)
        if a.cmd == "order":
            print(json.dumps(review_order(r), indent=1))
            return 0
        ev = evaluate(r, a.dir, a.target)
    except (Invalid, ValueError, KeyError, OSError) as e:
        print(f"integration_receipt: invalid: {e}", file=sys.stderr)
        return 2
    if a.cmd == "check":
        print(f"{ev['verdict']} for {a.target}: " + ("; ".join(f"{c['id']} {MARK[c['effective']]}" for c in ev["blockers"])
                                                  or "every required check passes on the candidate"))
    elif a.cmd == "summary":
        print(summary(r, ev, a.width))
    elif a.cmd == "markdown":
        sys.stdout.write(markdown(r, ev))
    return 0 if ev["verdict"] == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
