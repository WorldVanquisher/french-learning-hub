#!/usr/bin/env python3
"""Offline release control: a versioned release report, why a candidate is READY or BLOCKED.

  release_report.py collect --candidate BUNDLE.tar --candidate-sha256 HEX [--rollback BUNDLE.tar --rollback-sha256 HEX]
                            [--source DIR] [--target local-rehearsal|staging] [--plan-json FILE] [--host-status FILE]
                            --out DIR
                            [--receipt RECEIPT_DIR]    # the integration receipt of the sealed sources
  release_report.py check REPORT.json          # exit 0 READY, 1 BLOCKED, 2 invalid report
  release_report.py terminal REPORT.json [--width N]   # compact view, wrapped to N columns (default: terminal)
  release_report.py commands REPORT.json       # the commands behind each gate, fastest check first
  release_report.py record REPORT.json         # the owner's release record: digests to type, verification policy
  release_report.py html REPORT.json --out FILE.html
  release_report.py markdown REPORT.json [--out FILE.md]
  release_report.py attest REPORT.json [--source DIR] [--probe-docker]   # tools, inputs, verified digests

Format `flh-release-report/v1` (one JSON file; evidence paths are relative to it):
  candidate         bundle name, transfer SHA-256, manifest SHA-256, image ID, source revision
                    (commit, tree), server/web digests, migration ledger
  rollback_target   the previous verified bundle and its ledger, or null
  target            what readiness means: local-rehearsal (local gates) or staging (also the
                    owner-only AWS plan check and host identity)
  gates[]           id, title, kind (build|artifact|rollback|test|staging|rollout), owner
                    (agent|owner), required_for[], status (pass|fail|pending|unavailable|skipped),
                    summary, counts{}, next_action (required unless pass), evidence{path, sha256,
                    command, bundle?, tree_id?}
  sources           with --receipt: the receipt's candidate tree and, per lane, the sealed handoff it came
                    from (seal id, SHA256SUMS digest, lane tree); the pending proposals left out
Evaluation (never trusted from the file): a gate whose evidence names another bundle or
source tree is STALE (old evidence, not a failure: rerun it); an evidence file that is missing or whose SHA-256 changed is
UNAVAILABLE/CHANGED; the candidate is READY only when every gate required for the target
passes with intact, current evidence. Everything else is BLOCKED, with one reason per gate.
`collect` runs the checks itself (bundle verification, rollback compatibility, the Python
CI suites, the staging preflight; the owner's plan JSON and host status when supplied) and
writes their outputs as evidence. It makes no AWS call, no network call and no deploy.
"""
import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time

FORMAT = "flh-release-report/v1"
REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
STATUSES = ("pass", "fail", "pending", "unavailable", "skipped")
TARGETS = ("local-rehearsal", "staging")
RUNBOOK = "deploy/aws/private-staging/RUNBOOK.md"


class Invalid(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load(path):
    with open(path) as fh:
        rep = json.load(fh)
    if rep.get("format") != FORMAT:
        raise Invalid(f"format is {rep.get('format')!r}, not {FORMAT}")
    for k in ("candidate", "target", "gates"):
        if k not in rep:
            raise Invalid(f"missing {k}")
    if rep["target"] not in TARGETS:
        raise Invalid(f"target {rep['target']!r} is not one of {TARGETS}")
    ids = [g.get("id") for g in rep["gates"]]
    if len(ids) != len(set(ids)):
        raise Invalid("duplicate gate id")
    for g in rep["gates"]:
        if g.get("status") not in STATUSES:
            raise Invalid(f"gate {g.get('id')}: status {g.get('status')!r}")
        if g["status"] != "pass" and not g.get("next_action"):
            raise Invalid(f"gate {g['id']}: a {g['status']} gate needs next_action")
        if g["status"] in ("pass", "fail") and not (g.get("evidence") or {}).get("path"):
            raise Invalid(f"gate {g['id']}: a {g['status']} result needs an evidence file")
    return rep


def evaluate(rep, base):
    """Effective state per gate plus the verdict. Nothing is taken on trust from the file."""
    cand = rep["candidate"]
    tree = (cand.get("revision") or {}).get("tree_id")
    out = []
    for g in rep["gates"]:
        ev = g.get("evidence") or {}
        eff, why = g["status"], g.get("summary", "")
        if ev.get("path"):
            p = os.path.join(base, ev["path"])
            if not os.path.isfile(p):
                eff, why = "unavailable", f"evidence file missing: {ev['path']}"
            elif ev.get("sha256") and sha256_file(p) != ev["sha256"]:
                eff, why = "changed", f"evidence file changed after the report was written: {ev['path']}"
        if eff in ("pass", "fail") and ev.get("bundle") and ev["bundle"] != cand["bundle"]["name"]:
            eff, why = "stale", f"evidence is for bundle {ev['bundle']}, not {cand['bundle']['name']}"
        if eff in ("pass", "fail") and ev.get("tree_id") and tree and ev["tree_id"] != tree:
            eff, why = "stale", f"evidence is for source tree {ev['tree_id'][:12]}, not the candidate's {tree[:12]}"
        required = rep["target"] in g.get("required_for", [])
        blocking = required and eff != "pass"
        if eff == g["status"]:
            nxt = g.get("next_action")
        elif eff == "stale" and g.get("stale_next"):
            nxt = g["stale_next"]
        elif eff == "stale" and "source tree" in why:
            nxt = f"rerun collect with --source set to a checkout of the candidate's tree {tree}"
        elif eff == "stale":
            nxt = f"rerun collect so this gate checks {cand['bundle']['name']} itself"
        else:
            nxt = "rerun collect: the evidence must be regenerated, never edited"
        out.append(dict(g, effective=eff, reason=why, required=required, blocking=blocking, next=nxt))
    blockers = [g for g in out if g["blocking"]]
    return {"verdict": "BLOCKED" if blockers else "READY", "gates": out, "blockers": blockers}


# --- renderings --------------------------------------------------------------------------------
MARK = {"pass": "PASS", "fail": "FAIL", "pending": "PENDING", "unavailable": "UNAVAILABLE", "skipped": "SKIPPED",
        "stale": "STALE", "changed": "CHANGED"}


def tallies(ev):
    """Failed and stale are different things: a FAIL ran on these bytes and failed; a STALE result ran on
    other bytes (old evidence) and only needs a rerun."""
    n = {}
    for g in ev["gates"]:
        n[g["effective"]] = n.get(g["effective"], 0) + 1
    parts = [f"{n.get('pass', 0)} pass", f"{n.get('fail', 0)} failed"]
    parts.append(f"{n.get('stale', 0)} stale (old evidence, rerun; not failures)")
    other = sum(v for k, v in n.items() if k not in ("pass", "fail", "stale"))
    if other:
        parts.append(f"{other} pending, unavailable, changed or skipped")
    return ", ".join(parts)


def rollback_line(rep):
    """Rollback availability and ledger compatibility, read together."""
    c, rb = rep["candidate"], rep.get("rollback_target")
    g = next((x for x in rep["gates"] if x["id"] == "rollback-target"), {})
    if not rb:
        return "none given: no previous bundle to switch back to (only a pre-install backup could restore)"
    n, m = c.get("migrations"), rb.get("migrations")
    compat = isinstance(n, int) and isinstance(m, int) and m >= n
    verified = g.get("status") == "pass" or (g.get("status") == "fail" and "does not verify" not in g.get("summary", ""))
    return (f"{rb['bundle']}: {'verifies' if verified else 'does NOT verify'}; ledger: knows {m} migration(s), the "
            f"candidate ships {n}: {'compatible (rollback needs no restore)' if compat else 'NOT compatible: after a migrating install only the pre-install backup restores, and writes made after it are lost'}")


def gate_rows(rep, ev):
    """One row per gate: the single model Markdown and HTML both render (same verdict, same reasons)."""
    rows = []
    for g in ev["gates"]:
        e = g.get("evidence") or {}
        rows.append({"id": g["id"], "title": g.get("title", ""), "kind": g.get("kind", ""), "owner": g.get("owner", "agent"),
                     "required": g["required"], "state": MARK[g["effective"]], "effective": g["effective"],
                     "why": g["reason"], "counts": counts_text(g.get("counts")), "evidence": e.get("path"),
                     "command": e.get("command"), "next": None if g["effective"] == "pass" else g["next"]})
    return rows


def command_list(rep, ev, report_path="REPORT.json"):
    """The commands behind the verdict, fastest first: re-evaluate the saved evidence (seconds), then each gate's
    own command (what reruns it)."""
    out = [("check (re-evaluates saved evidence; nothing reruns)", f"python3 -I scripts/release/release_report.py check {report_path}")]
    for g in ev["gates"]:
        e = g.get("evidence") or {}
        if e.get("command"):
            out.append((f"{g['id']} ({MARK[g['effective']]})", e["command"]))
        elif g["effective"] != "pass" and g.get("next"):
            out.append((f"{g['id']} ({MARK[g['effective']]}, no command yet)", g["next"]))
    return out


def blocked_by(rep, ev):
    """One sentence naming exactly what keeps the candidate from its target: agent gates first, then the
    owner-only gates with the owner action each needs."""
    if not ev["blockers"]:
        return ""
    agent = [g for g in ev["blockers"] if g.get("owner", "agent") != "owner"]
    owner = [g for g in ev["blockers"] if g.get("owner") == "owner"]
    if agent:
        return (f"blocked first by {len(agent)} agent gate(s): " + ", ".join(f"{g['id']} ({MARK[g['effective']]})" for g in agent)
                + (f"; then by owner-only gate(s): {', '.join(g['id'] for g in owner)}" if owner else ""))
    return (f"blocked for {rep['target']} ONLY by owner-only gate(s): "
            + "; ".join(f"{g['id']} ({MARK[g['effective']]}: {g['next']})" for g in owner))


def owner_record(rep, ev):
    """The owner's release record: what to install, the digests to type, and how they are verified."""
    c = rep["candidate"]
    b = c["bundle"]
    rb = rep.get("rollback_target") or {}
    lines = [f"# Owner release record: {b['name']}", "",
             f"Verdict: **{ev['verdict']}** for `{rep['target']}` ({FORMAT}, generated {rep.get('generated_at', 'unknown')}).", "",
             "| What | Value |", "| --- | --- |",
             f"| Bundle (transfer file) | `{b['name']}.tar` |",
             f"| Transfer SHA-256 (type this; never copy it from the host or the bucket) | `{b.get('transfer_sha256')}` |",
             f"| MANIFEST.json SHA-256 | `{b.get('manifest_sha256')}` |",
             f"| Image ID | `{b.get('image_id')}` |",
             f"| Source tree / commit | `{(c.get('revision') or {}).get('tree_id')}` / `{(c.get('revision') or {}).get('commit') or 'none (tree-only)'}` |",
             f"| Migration ledger | {c.get('migrations')} |",
             f"| Rollback target | `{rb.get('bundle', 'none')}` ({rollback_line(rep)}) |"]
    for ln in (rep.get("sources") or {}).get("lanes", []):
        lines.append(f"| Source lane {ln['lane']} | seal `{ln['seal_digest'][:16]}` ({ln.get('seal_id') or ''}) |")
    lines += ["", "Verification policy (what `flh-staging-bundle install … --sha256 <typed>` enforces before anything changes):", "",
              "1. The transfer file's SHA-256 must equal the value typed from this record.",
              "2. Tar safety: one `flh-staging-<tree12>/` directory; no absolute, `..`, link or device members.",
              "3. Every file matches `SHA256SUMS`; nothing missing or added; `MANIFEST.json` agrees with the tree id, image tag,",
              "   labels and files; `BUILD.json` agrees with `MANIFEST.json` and `image.tar`.",
              "4. Every image config and layer blob hashes to its name; the loaded image ID equals `BUILD.json`.",
              "5. A bundle that knows fewer migrations than the database is refused.",
              "6. After the switch, the running container's image, revision labels, `/app/server` SHA-256 and `/readyz` must",
              "   match the bundle, or the previous bundle is restored and its identity checked.", ""]
    line = blocked_by(rep, ev)
    lines.append(line if line else "Nothing blocks this target.")
    return "\n".join(lines) + "\n"


def counts_text(c):
    if not c:
        return ""
    return ", ".join(f"{k} {c[k]}" for k in ("ran", "skipped", "expected_failures", "failures", "errors") if k in c)


def terminal(rep, ev, width=None):
    """Compact view. Every line fits WIDTH columns (default: the terminal's); a gate line always starts
    with its flag, state and id, and the rest wraps underneath."""
    import textwrap
    width = max(40, width or shutil.get_terminal_size((120, 24)).columns)
    wrap = lambda text, ind: textwrap.wrap(text, width=width, subsequent_indent=" " * ind, break_long_words=True,
                                           break_on_hyphens=False) or [""]
    c = rep["candidate"]
    lines = wrap(f"{ev['verdict']} for {rep['target']}: {c['bundle']['name']}  "
                 f"(tree {(c.get('revision') or {}).get('tree_id', '?')[:12]}, commit {(c.get('revision') or {}).get('commit') or 'none'})", 2)
    lines += wrap(f"  artifact  transfer {c['bundle'].get('transfer_sha256', '?')[:16]}  manifest {c['bundle'].get('manifest_sha256', '?')[:16]}"
                  f"  image {c['bundle'].get('image_id', '?')[:19]}  migrations {c.get('migrations', '?')}", 12)
    lines += wrap(f"  rollback  {rollback_line(rep)}", 12)
    for ln in (rep.get("sources") or {}).get("lanes", []):
        lines += wrap(f"  source    {ln['lane']}: seal {ln['seal_digest'][:12]} {ln.get('seal_id') or ''}", 12)
    for g in ev["gates"]:
        flag = "!" if g["blocking"] else (" " if g["required"] else "-")
        head = f"{flag} {MARK[g['effective']]:<11} {g['id']:<24} "
        body = g["reason"] + (f"  [{counts_text(g.get('counts'))}]" if g.get("counts") else "")
        if len(head) + 20 > width:
            lines.append(head.rstrip())
            lines += wrap(" " * 4 + body, 4)
        else:
            w = wrap(head + body, len(head))
            lines += w
        if g["effective"] != "pass":
            lines += wrap(f"{'':6}next: {g['next']}", 12)
    lines += wrap(tallies(ev), 2)
    lines += wrap(f"{len(ev['blockers'])} blocking gate(s); '!' blocks {rep['target']}, '-' not required for it", 2)
    return "\n".join(lines)


def markdown(rep, ev):
    c = rep["candidate"]
    rev = c.get("revision") or {}
    rb = rep.get("rollback_target")
    m = [f"# Release report: {c['bundle']['name']}", "",
         f"**{ev['verdict']}** for target `{rep['target']}` ({len(ev['blockers'])} blocking gate(s)). "
         f"Report `{FORMAT}`, generated {rep.get('generated_at', 'unknown')}.", "",
         "| Build and artifact | Value |", "| --- | --- |",
         f"| Bundle | `{c['bundle']['name']}` |",
         f"| Source tree / commit | `{rev.get('tree_id')}` / `{rev.get('commit') or 'none (tree-only)'}` |",
         f"| Transfer SHA-256 | `{c['bundle'].get('transfer_sha256')}` |",
         f"| Manifest SHA-256 | `{c['bundle'].get('manifest_sha256')}` |",
         f"| Image ID | `{c['bundle'].get('image_id')}` |",
         f"| Server / web digests | `{c.get('server_sha256', '')[:16]}` / `{c.get('web_files_sha256', '')[:16]}` |",
         f"| Migration ledger | {c.get('migrations')} |",
         f"| Rollback target and ledger | {rollback_line(rep)} |", ""]
    src = rep.get("sources")
    if src:
        m += [f"Sources: integration receipt for tree `{src.get('tree_id')}` "
              f"(`{(src.get('receipt_sha256') or '')[:16]}`).", "",
              "| Lane | Sealed handoff | SHA256SUMS digest | Lane tree |", "| --- | --- | --- | --- |"]
        m += [f"| {ln['lane']} | {ln.get('seal_id') or ''} | `{ln['seal_digest'][:16]}` | `{(ln.get('tree_id') or '')[:12]}` |"
              for ln in src.get("lanes", [])]
        if src.get("pending"):
            m.append("")
            m.append("Left out on purpose: " + "; ".join(f"`{p['id']}` ({p.get('lane')})" for p in src["pending"]))
        m.append("")
    m += [f"Gates: {tallies(ev)}.", "",
          "| Gate | Kind | Owner | Required for this target | State | Why | Evidence | Next action |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in gate_rows(rep, ev):
        m.append(f"| `{r['id']}` | {r['kind']} | {r['owner']} | {'yes' if r['required'] else 'no'} | "
                 f"**{r['state']}** | {r['why']}{' (' + r['counts'] + ')' if r['counts'] else ''} | "
                 f"{'`' + r['evidence'] + '`' if r['evidence'] else ''}{' via `' + r['command'] + '`' if r['command'] else ''} | "
                 f"{r['next'] or ''} |")
    m += ["", "## Draft versus ready", ""]
    if ev["blockers"]:
        m.append(f"To become READY for `{rep['target']}`:")
        m += [f"- `{g['id']}`: now {MARK[g['effective']]}; needs PASS with current evidence. "
              f"{g['next']}" for g in ev["blockers"]]
    else:
        m.append(f"Every gate required for `{rep['target']}` passes with current evidence.")
        owner = [g for g in ev["gates"] if not g["required"] and g["effective"] != "pass"]
        if owner:
            m.append("")
            m.append("Not required for this target (owner-only, shown for the next target):")
            m += [f"- `{g['id']}`: {MARK[g['effective']]}. {g['next']}" for g in owner]
    m += ["", "## Commands behind this verdict (fastest first)", ""]
    m += [f"- {label}: `{cmd}`" for label, cmd in command_list(rep, ev)]
    return "\n".join(m) + "\n"


CSS = """body{font:14px/1.45 system-ui,sans-serif;margin:24px;color:#1d1d1f;background:#fff}
h1{font-size:20px;margin:0 0 4px}.verdict{display:inline-block;padding:4px 10px;border-radius:6px;font-weight:700}
.READY{background:#d8f5dd;color:#0b5d1e}.BLOCKED{background:#fde2e1;color:#8a1c12}
table{border-collapse:collapse;width:100%;margin:12px 0}th,td{border:1px solid #d0d0d6;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f3f3f6}code{font:12px ui-monospace,monospace;word-break:break-all}
.s{font-weight:700}.pass{color:#0b5d1e}.fail,.stale,.changed{color:#8a1c12}.pending,.unavailable,.skipped{color:#7a5300}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.card{border:1px solid #d0d0d6;border-radius:8px;padding:10px}
@media (prefers-color-scheme:dark){body{background:#111;color:#eee}th{background:#222}th,td,.card{border-color:#444}
.READY{background:#12391b;color:#bff0c8}.BLOCKED{background:#45130f;color:#ffd2cd}.pass{color:#8be39c}.fail,.stale,.changed{color:#ff9b90}.pending,.unavailable,.skipped{color:#ffd27a}}"""


def page(rep, ev, link_base=""):
    """Static HTML. Evidence links are relative to where the page is written (LINK_BASE is the report
    directory as seen from the page), so the report directory can move and the page can live elsewhere."""
    e = html.escape
    c = rep["candidate"]
    rev = c.get("revision") or {}
    rb = rep.get("rollback_target")
    rows = []
    for r in gate_rows(rep, ev):
        href = (link_base.rstrip("/") + "/" if link_base else "") + r["evidence"] if r["evidence"] else None
        link = (f'<a href="{e(href)}">{e(r["evidence"])}</a>' if href else "")
        cmd = f"<br><code>{e(r['command'])}</code>" if r["command"] else ""
        rows.append(f"<tr><td><code>{e(r['id'])}</code><br>{e(r['title'])}</td><td>{e(r['kind'])}</td>"
                    f"<td>{e(r['owner'])}</td><td>{'yes' if r['required'] else 'no'}</td>"
                    f"<td class='s {e(r['effective'])}'>{r['state']}</td><td>{e(r['why'])}"
                    f"{'<br>' + e(r['counts']) if r['counts'] else ''}</td><td>{link}{cmd}</td><td>{e(r['next'] or '')}</td></tr>")
    tests = [g for g in ev["gates"] if g.get("kind") == "test"]
    card = lambda title, body: f"<div class='card'><b>{e(title)}</b><br>{body}</div>"
    cards = [card("Build", f"tree <code>{e(str(rev.get('tree_id')))}</code><br>commit <code>{e(str(rev.get('commit') or 'none (tree-only)'))}</code>"
                  f"<br>server <code>{e(c.get('server_sha256', '')[:16])}</code> web <code>{e(c.get('web_files_sha256', '')[:16])}</code>"),
             card("Artifact", f"<code>{e(c['bundle']['name'])}</code><br>transfer <code>{e(str(c['bundle'].get('transfer_sha256')))}</code>"
                  f"<br>image <code>{e(str(c['bundle'].get('image_id')))}</code><br>migrations {e(str(c.get('migrations')))}"),
             card("Rollback target and ledger", e(rollback_line(rep))),
             card("Test evidence", "<br>".join(f"{e(g['id'])}: <span class='s {e(g['effective'])}'>{MARK[g['effective']]}</span> "
                                               f"{e(counts_text(g.get('counts')))}" for g in tests) or "none")]
    blockers = "".join(f"<li><code>{e(g['id'])}</code>: {MARK[g['effective']]}: {e(g['reason'])}. "
                       f"<b>Next:</b> {e(g['next'] or '')}</li>" for g in ev["blockers"])
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Release report {e(c['bundle']['name'])}</title><style>{CSS}</style></head><body>"
            f"<h1>{e(c['bundle']['name'])}</h1><span class='verdict {ev['verdict']}'>{ev['verdict']}</span> "
            f"for target <code>{e(rep['target'])}</code>: {len(ev['blockers'])} blocking gate(s). "
            f"<small>{e(FORMAT)}, generated {e(rep.get('generated_at', 'unknown'))}</small>"
            f"<div class='grid'>{''.join(cards)}</div>"
            + (f"<h2>Why it is blocked</h2><ul>{blockers}</ul>" if blockers else "<h2>Why it is ready</h2><p>Every gate required for this target passes with current evidence.</p>")
            + sources_html(rep)
            + f"<h2>Gates</h2><p>{e(tallies(ev))}</p><table><tr><th>Gate</th><th>Kind</th><th>Owner</th><th>Required</th><th>State</th><th>Why</th>"
              "<th>Evidence</th><th>Next action</th></tr>" + "".join(rows) + "</table>"
            + "<h2>Commands behind this verdict (fastest first)</h2><ol>"
            + "".join(f"<li>{e(label)}: <code>{e(cmd)}</code></li>" for label, cmd in command_list(rep, ev)) + "</ol></body></html>\n")


def sources_html(rep):
    e = html.escape
    src = rep.get("sources")
    if not src:
        return ""
    rows = "".join(f"<tr><td>{e(ln['lane'])}</td><td>{e(ln.get('seal_id') or '')}</td><td><code>{e(ln['seal_digest'][:16])}</code></td>"
                   f"<td><code>{e((ln.get('tree_id') or '')[:12])}</code></td></tr>" for ln in src.get("lanes", []))
    pend = "".join(f"<li><code>{e(p['id'])}</code> ({e(p.get('lane') or '')}): {e(p.get('why') or '')}</li>" for p in src.get("pending", []))
    return (f"<h2>Sources (sealed handoffs)</h2><p>Integration receipt for tree <code>{e(str(src.get('tree_id')))}</code></p>"
            "<table><tr><th>Lane</th><th>Sealed handoff</th><th>SHA256SUMS digest</th><th>Lane tree</th></tr>" + rows + "</table>"
            + (f"<p>Left out on purpose:</p><ul>{pend}</ul>" if pend else ""))


# --- collect -----------------------------------------------------------------------------------
def run(cmd, cwd=None, env=None):
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p.returncode, p.stdout, time.time() - t0


def read_member_json(tar, name):
    with tarfile.open(tar) as tf:
        stem = os.path.basename(tar)[:-4]
        return json.load(tf.extractfile(f"{stem}/{name}"))


def collect(a):
    out = os.path.realpath(a.out)
    if os.path.exists(out):
        raise Invalid(f"refused: {out} exists")
    os.makedirs(os.path.join(out, "evidence"))
    host_tool = os.path.join(REPO, "deploy/aws/private-staging/staging/host/flh-staging-bundle")
    ident = os.path.join(REPO, "deploy/aws/private-staging/staging/bundle_identity.py")
    source = os.path.realpath(a.source or REPO)
    py = sys.executable
    gates = []

    def evidence(name, text, **bind):
        p = os.path.join(out, "evidence", name)
        with open(p, "w") as fh:
            fh.write(text)
        return dict({"path": f"evidence/{name}", "sha256": sha256_file(p)}, **bind)

    def scratch():
        d = os.path.join(out, ".scratch")
        os.makedirs(d, exist_ok=True)
        return d

    man = read_member_json(a.candidate, "MANIFEST.json")
    build = read_member_json(a.candidate, "BUILD.json")
    name = man["name"]
    cmd = [py, "-I", host_tool, "verify", a.candidate, "--sha256", a.candidate_sha256, "--scratch", scratch()]
    rc, text, secs = run(cmd)
    gates.append({"id": "bundle-verify", "title": "Candidate bundle verifies (sums, manifest, image blobs, labels)",
                  "kind": "artifact", "owner": "agent", "required_for": list(TARGETS),
                  "status": "pass" if rc == 0 else "fail", "summary": (text.strip().splitlines() or ["no output"])[-1][:200],
                  "next_action": None if rc == 0 else "rebuild the bundle (build_bundle.sh --git . <rev> OUT) and use its .sha256",
                  "evidence": evidence("bundle-verify.txt", f"$ flh-staging-bundle verify {os.path.basename(a.candidate)} --sha256 {a.candidate_sha256}\nexit {rc} ({secs:.1f} s)\n{text}",
                                       command=f"flh-staging-bundle verify {os.path.basename(a.candidate)} --sha256 <sha256>", bundle=name)})
    rollback = None
    if a.rollback:
        rman = read_member_json(a.rollback, "MANIFEST.json")
        rollback = {"bundle": rman["name"], "migrations": rman["migrations"]["count"],
                    "tree_id": rman["revision"]["tree_id"]}
        rc, text, secs = run([py, "-I", host_tool, "verify", a.rollback, "--sha256", a.rollback_sha256, "--scratch", scratch()])
        compat = rman["migrations"]["count"] >= man["migrations"]["count"]
        ok = rc == 0 and compat
        why = ("rollback target verifies and knows every candidate migration" if ok else
               ("rollback target does not verify" if rc != 0 else
                f"rollback target knows {rman['migrations']['count']} migrations, the candidate ships {man['migrations']['count']}: "
                "after a migrating install only the pre-install backup restores it"))
        gates.append({"id": "rollback-target", "title": "Previous verified bundle, compatible with the candidate's ledger",
                      "kind": "rollback", "owner": "agent", "required_for": list(TARGETS), "status": "pass" if ok else "fail",
                      "summary": why, "next_action": None if ok else "choose a rollback bundle with the same ledger, or record the pre-install backup as the rollback (RUNBOOK §8)",
                      "evidence": evidence("rollback-verify.txt", f"$ flh-staging-bundle verify {os.path.basename(a.rollback)} --sha256 {a.rollback_sha256}\nexit {rc} ({secs:.1f} s)\n{text}"
                                           f"candidate migrations {man['migrations']['count']}, rollback migrations {rman['migrations']['count']}\n",
                                           command=f"flh-staging-bundle verify {os.path.basename(a.rollback)} --sha256 <sha256>", bundle=name)})
    else:
        gates.append({"id": "rollback-target", "title": "Previous verified bundle", "kind": "rollback", "owner": "agent",
                      "required_for": list(TARGETS), "status": "unavailable", "summary": "no rollback bundle given",
                      "next_action": "rerun collect with --rollback <previous bundle tar> --rollback-sha256 <its sha256>"})
    rc, text, _ = run([py, "-I", ident, "tree-id", source, "--allow-worktree"])
    src_tree = json.loads(text)["tree_id"] if rc == 0 else None
    js = os.path.join(scratch(), "suites.json")
    rc, text, secs = run([py, "-B", os.path.join(source, "scripts/ci/python_suites.py"), "--json", js], cwd=out)
    suites = json.load(open(js)) if os.path.isfile(js) else {"suites": []}
    tot = {k: sum(s.get(k, 0) for s in suites["suites"]) for k in ("ran", "skipped", "expected_failures", "failures", "errors")}
    gates.append({"id": "python-suites", "title": "Python CI suites (scripts/ci/python_suites.py)", "kind": "test", "owner": "agent",
                  "required_for": list(TARGETS), "status": "pass" if rc == 0 else "fail",
                  "summary": ", ".join(f"{s['label']} {s['status']}" for s in suites["suites"]) or "no results",
                  "counts": tot, "next_action": None if rc == 0 else "rerun the failing suite: python3 -B scripts/ci/python_suites.py --suite <label>",
                  "evidence": evidence("python-suites.txt", f"$ python3 -B scripts/ci/python_suites.py --json …\nexit {rc} ({secs:.1f} s)\n{text}",
                                       command="python3 -B scripts/ci/python_suites.py", tree_id=src_tree)})
    rc, text, secs = run([py, "-I", "-B", os.path.join(source, "deploy/aws/private-staging/staging/tools/preflight.py")])
    gates.append({"id": "staging-preflight", "title": "Staging preflight, repository checks (offline)", "kind": "staging", "owner": "agent",
                  "required_for": list(TARGETS), "status": "pass" if rc == 0 else "fail",
                  "summary": (text.strip().splitlines() or ["no output"])[-1], "next_action": None if rc == 0 else "fix each FAIL line in the evidence",
                  "evidence": evidence("staging-preflight.txt", f"$ python3 -I deploy/aws/private-staging/staging/tools/preflight.py\nexit {rc} ({secs:.1f} s)\n{text}",
                                       command="python3 -I deploy/aws/private-staging/staging/tools/preflight.py", tree_id=src_tree)})
    if a.plan_json:
        rc, text, secs = run([py, "-I", os.path.join(REPO, "deploy/aws/private-staging/staging/tools/plan_check.py"), "--mode", "create", a.plan_json])
        gates.append({"id": "aws-plan-check", "title": "Owner's Terraform plan passes the stop rule", "kind": "staging", "owner": "owner",
                      "required_for": ["staging"], "status": "pass" if rc == 0 else "fail", "summary": (text.strip().splitlines() or [""])[-1],
                      "next_action": None if rc == 0 else "fix the plan (INVENTORY.md §4) and plan again",
                      "evidence": evidence("aws-plan-check.txt", f"$ plan_check.py --mode create <plan json>\nexit {rc}\n{text}", command="plan_check.py --mode create stg.plan.json")})
    else:
        gates.append({"id": "aws-plan-check", "title": "Owner's Terraform plan passes the stop rule", "kind": "staging", "owner": "owner",
                      "required_for": ["staging"], "status": "unavailable", "summary": "owner-only: no plan JSON supplied (agents run no Terraform)",
                      "next_action": f"owner: {RUNBOOK} §3.2 (terraform plan, show -json, plan_check.py), then rerun collect with --plan-json stg.plan.json"})
    if a.host_status:
        with open(a.host_status) as fh:
            text = fh.read()
        ok = "IDENTITY OK" in text and name in text
        gates.append({"id": "staging-identity", "title": "Staging host runs the candidate (flh-staging-bundle status)", "kind": "rollout",
                      "owner": "owner", "required_for": ["staging"], "status": "pass" if ok else "fail",
                      "summary": "host reports IDENTITY OK for the candidate" if ok else "host status does not show IDENTITY OK for the candidate",
                      "next_action": None if ok else f"owner: {RUNBOOK} §5 (install) and §8 (rollback/recovery)",
                      "evidence": evidence("staging-identity.txt", text, command="flh-staging-bundle status (on the host)", bundle=name)})
    else:
        gates.append({"id": "staging-identity", "title": "Staging host runs the candidate", "kind": "rollout", "owner": "owner",
                      "required_for": ["staging"], "status": "unavailable", "summary": "owner-only: no host status supplied",
                      "next_action": f"owner: {RUNBOOK} §5 install, then save `flh-staging-bundle status` and rerun collect with --host-status FILE"})
    sources = None
    if a.receipt:
        sources, more = receipt_gates(a.receipt, a.target, man["revision"]["tree_id"], evidence)
        gates.extend(more)
    rep = {"format": FORMAT, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "target": a.target,
           "candidate": {"bundle": {"name": name, "transfer_sha256": a.candidate_sha256, "manifest_sha256": build["manifest_sha256"],
                                    "image_id": build["image_id"], "built_with_docker": build.get("docker_server"),
                                    "built_at": build.get("built_at")},
                         "revision": {"commit": man["revision"]["commit"], "tree_id": man["revision"]["tree_id"]},
                         "server_sha256": man["server_sha256"], "web_files_sha256": man["web_files_sha256"],
                         "migrations": man["migrations"]["count"]},
           "source": {"tree_id": src_tree}, "rollback_target": rollback, "gates": gates}
    if sources:
        rep["sources"] = sources
    with open(os.path.join(out, "report.json"), "w") as fh:
        json.dump(rep, fh, indent=1, sort_keys=True)
        fh.write("\n")
    import shutil
    shutil.rmtree(os.path.join(out, ".scratch"), ignore_errors=True)
    return os.path.join(out, "report.json")


BROWSER = ("learning-day", "practice-feed", "demo-browser")


def receipt_gates(rd, target, bundle_tree, evidence):
    """Gates from an integration receipt (scripts/release/integration_receipt.py): the sealed sources and their
    checks, and the browser evidence. Both bind to the tree the receipt checked, so a receipt or browser run for
    other bytes than this bundle is STALE, with one command as its next action."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import integration_receipt as IR
    r = IR.load(rd)
    ev = IR.evaluate(r, rd, target)
    rtree = r["candidate"]["tree_id"]
    checks = {c["id"]: c for c in ev["checks"]}
    req = [c for c in ev["checks"] if c["required"]
           and c["id"] not in ("release-report", "aws-plan-check", "staging-identity") + BROWSER]   # browser: own gate
    bad = [c for c in req if c["effective"] != "pass"]
    old_trees = {c.get("tree_id") for c in bad if c["effective"] == "stale"}
    # passes recorded for other bytes are old evidence (STALE), not failures: bind the gate to that tree
    only_old = bool(bad) and all(c["effective"] == "stale" for c in bad) and len(old_trees) == 1
    summ = IR.summary(r, ev, width=100)
    sources = {"receipt_sha256": sha256_file(os.path.join(rd, "receipt.json")), "tree_id": rtree,
               "lanes": [{k: ln.get(k) for k in ("lane", "seal_id", "seal_digest", "tree_id")} for ln in r["lanes"]],
               "pending": [{k: p.get(k) for k in ("id", "lane", "why")} for p in r.get("pending", [])]}
    rerun = f"bash scripts/release/integration_battery.sh <tree {bundle_tree[:12]}> RECEIPT WORK"
    gates = []
    gates.append({"id": "integration-receipt", "title": "Sealed lane sources and every check on their tree (integration receipt)",
              "kind": "source", "owner": "agent", "required_for": list(TARGETS), "status": "pass" if not bad or only_old else "fail",
              "summary": (f"{len(r['lanes'])} sealed lanes; {len(req)} required checks pass on tree {rtree[:12]}" if not bad else
                          f"{len(bad)} required check(s) not passing: " + ", ".join(f"{c['id']} {IR.MARK[c['effective']]}" for c in bad[:5])),
              "next_action": None if not bad or only_old else f"run the missing or failed checks: {rerun}",
              "stale_next": f"the checks ran on other bytes; rerun on this bundle's tree: {rerun}",
              "evidence": evidence("integration-receipt.txt", summ + "\n", command=f"python3 -I scripts/release/integration_receipt.py check {rd}",
                                   tree_id=(old_trees.pop() if only_old else rtree))})
    br = [checks.get(i) for i in BROWSER]
    trees = sorted({c.get("tree_id") for c in br if c and c.get("tree_id")})
    missing = [i for i, c in zip(BROWSER, br) if not c or c["effective"] == "missing"]
    failed = [c["id"] for c in br if c and c["effective"] not in ("pass", "missing", "stale")]
    ok = not missing and not failed and trees == [rtree]
    text = "\n".join(f"{i}: {IR.MARK[c['effective']] if c else 'MISSING'} on tree {(c or {}).get('tree_id', '-')}"
                     f" ({IR.counts_text((c or {}).get('counts'))})" for i, c in zip(BROWSER, br)) + "\n"
    gates.append({"id": "browser-evidence", "title": "Browser journeys on the bundle's tree (learning day, practice feed, demo)",
                  "kind": "test", "owner": "agent", "required_for": list(TARGETS), "status": "pass" if ok else "fail",
                  "summary": ("all three journeys pass on tree " + rtree[:12]) if ok else
                             (f"missing: {', '.join(missing)}" if missing else f"failed: {', '.join(failed)}" if failed else
                              f"browser runs are for tree(s) {', '.join(t[:12] for t in trees)}"),
                  "next_action": None if ok else f"rerun the browser stages on this tree: {rerun} learning practice demo",
                  "stale_next": f"rerun the browser stages on this bundle's tree: {rerun} learning practice demo",
                  "evidence": evidence("browser-evidence.txt", text, command="integration_battery.sh … learning practice demo",
                                       tree_id=(trees[0] if len(trees) == 1 else rtree))})
    return sources, gates


TOOLS = ("scripts/release/release_report.py", "scripts/ci/python_suites.py",
         "deploy/aws/private-staging/staging/host/flh-staging-bundle", "deploy/aws/private-staging/staging/bundle_identity.py",
         "deploy/aws/private-staging/staging/build_bundle.sh", "deploy/aws/private-staging/staging/tools/preflight.py")
INPUTS = ("Dockerfile", ".dockerignore", "go.mod", "go.sum", "web/package-lock.json")


def attest(rep, ev, source, probe_docker=False):
    """The Docker that built the candidate comes from its BUILD.json (recorded by collect). The local
    daemon is asked only with --probe-docker, so an attestation (and its tests) contact no daemon."""
    import platform
    def digest(root, rel):
        p = os.path.join(root, rel)
        return sha256_file(p) if os.path.isfile(p) else None
    docker = subprocess.run(["docker", "version", "-f", "{{.Server.Version}}"], capture_output=True, text=True) \
        if probe_docker and shutil.which("docker") else None
    c = rep["candidate"]
    return {"format": "flh-release-attestation/v1", "verdict": ev["verdict"], "target": rep["target"],
            "candidate": {"bundle": c["bundle"]["name"], "transfer_sha256": c["bundle"].get("transfer_sha256"),
                          "manifest_sha256": c["bundle"].get("manifest_sha256"), "image_id": c["bundle"].get("image_id"),
                          "tree_id": (c.get("revision") or {}).get("tree_id"), "commit": (c.get("revision") or {}).get("commit"),
                          "server_sha256": c.get("server_sha256"), "web_files_sha256": c.get("web_files_sha256"),
                          "migrations": c.get("migrations")},
            "rollback_target": (rep.get("rollback_target") or {}).get("bundle"),
            "gates": {g["id"]: {"state": g["effective"], "evidence_sha256": (g.get("evidence") or {}).get("sha256")} for g in ev["gates"]},
            "tools": {"python": platform.python_version(), "platform": platform.platform(terse=True),
                      "docker_built_with": c["bundle"].get("built_with_docker"),
                      "docker_server_local": ((docker.stdout.strip() or None) if docker and docker.returncode == 0 else None)
                      if probe_docker else "not probed (--probe-docker)",
                      **{t: digest(REPO, t) for t in TOOLS}},
            "pinned_inputs": {f: digest(source, f) for f in INPUTS} if source else None}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--candidate", required=True)
    c.add_argument("--candidate-sha256", required=True)
    c.add_argument("--rollback")
    c.add_argument("--rollback-sha256")
    c.add_argument("--source")
    c.add_argument("--target", choices=TARGETS, default="local-rehearsal")
    c.add_argument("--plan-json")
    c.add_argument("--host-status")
    c.add_argument("--receipt", help="integration receipt directory (integration_receipt.py) of the sealed sources")
    c.add_argument("--out", required=True)
    for n in ("check", "terminal", "html", "markdown", "attest", "commands", "record"):
        p = sub.add_parser(n)
        p.add_argument("report")
        if n in ("html", "markdown"):
            p.add_argument("--out")
        if n == "terminal":
            p.add_argument("--width", type=int)
        if n == "attest":
            p.add_argument("--source")
            p.add_argument("--probe-docker", action="store_true", help="also record the local Docker daemon's version")
    a = ap.parse_args()
    try:
        if a.cmd == "collect":
            path = collect(a)
            rep = load(path)
            ev = evaluate(rep, os.path.dirname(path))
            print(terminal(rep, ev))
            print(f"report: {path}")
            return 0 if ev["verdict"] == "READY" else 1
        rep = load(a.report)
        ev = evaluate(rep, os.path.dirname(os.path.realpath(a.report)))
    except (Invalid, ValueError, KeyError, OSError) as e:
        print(f"release_report: invalid: {e}", file=sys.stderr)
        return 2
    if a.cmd == "check":
        print(f"{ev['verdict']}: " + ("; ".join(f"{g['id']} {MARK[g['effective']]}" for g in ev["blockers"]) or "every required gate passes"))
        line = blocked_by(rep, ev)
        if line:
            print(line)
    elif a.cmd == "record":
        sys.stdout.write(owner_record(rep, ev))
    elif a.cmd == "terminal":
        print(terminal(rep, ev, a.width))
    elif a.cmd == "commands":
        for label, cmd in command_list(rep, ev, a.report):
            print(f"# {label}\n{cmd}")
    elif a.cmd == "attest":
        print(json.dumps(attest(rep, ev, a.source, a.probe_docker), indent=1, sort_keys=True))
    else:
        base = ""
        if a.cmd == "html" and a.out:
            base = os.path.relpath(os.path.dirname(os.path.realpath(a.report)), os.path.dirname(os.path.realpath(a.out)))
            base = "" if base == "." else base
        text = page(rep, ev, base) if a.cmd == "html" else markdown(rep, ev)
        if a.out:
            with open(a.out, "w") as fh:
                fh.write(text)
        else:
            sys.stdout.write(text)
    return 0 if ev["verdict"] == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
