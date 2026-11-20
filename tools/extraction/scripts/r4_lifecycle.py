"""Revision and provenance across the R4 lifecycle, over HTTP and the CLI (offline, synthetic).

  python3 -I -B scripts/r4_lifecycle.py --write     # (re)write fixtures/r4_v1/lifecycle/
  python3 -I -B scripts/r4_lifecycle.py --check     # regenerate and compare byte for byte

Checks, each recorded in ``lifecycle/report.json``:

  replay      every corpus request sent twice to a real loopback server gives byte-identical
              bodies; the stable identifiers (draft, items, evidence, batch, feed) are listed
  correction  a learner edit keeps the source, item and evidence identity; the item becomes
              ``corrected`` with the learner's text; the decision names the proposed item's hash
              and the proposed text stays in the immutable source
  restore     the items withdrawn by revision 2 come back in feed 4 with every earlier outcome;
              ``since_revision`` and reason codes survive the feed in between; the reference
              consumer converges also when it misses a feed, ignores a replay and a stale feed
  cli_http    the same steps through ``python3 -m flh_extraction practice2`` (a learner's CLI
              session) give the same plans and byte-identical feeds as the HTTP service

``lifecycle/`` also carries the four feeds and ``replay-cases.json`` in the format of the
sealed replay cases (``feed_compat.run_replay``), so Workbooks can run the whole lifecycle
offline with its own consumer (``feedClient.applyFeed``).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from flh_extraction import feed_compat as fc  # noqa: E402
from flh_extraction import practice as pr  # noqa: E402
from flh_extraction import practice22 as p22  # noqa: E402
from flh_extraction import r4corpus as rc  # noqa: E402
from flh_extraction import service as svc  # noqa: E402

OUT = os.path.join(HERE, "fixtures", "r4_v1", "lifecycle")
FEEDS = (("06-feed-r1", "feed-1-r1.json"), ("08-feed-r2-withdrawn", "feed-2-r2-withdrawn.json"),
         ("10-feed-r3-awaiting", "feed-3-r3-awaiting.json"), ("12-feed-r3-restored", "feed-4-r3-restored.json"))
def ORDERS(n: list[str]) -> list[tuple[str, list[str]]]:
    """Delivery orders for the reference consumer: in order, a missed feed, duplicates, and a late (stale) feed."""
    return [("in_order", n), ("missed_feed_3", [n[0], n[1], n[3]]), ("replay_and_stale", [n[0], n[1], n[1], n[2], n[3], n[1]]),
            ("late_feed_3", [n[0], n[1], n[3], n[2]])]


README = """# R4 lifecycle fixture (synthetic, offline)

The y/en source through revisions 1-3 as four `flh_practice_review_feed_v1` feeds with the
2.2 additions, produced by the extraction service (`flh_extraction_service_v1`):

1. `feed-1-r1.json`: five items, three outcomes (two attempts, one reveal).
2. `feed-2-r2-withdrawn.json`: no item offered; all five withdrawn (`knowledge_changed`).
3. `feed-3-r3-awaiting.json`: still none offered; three withdrawn as `awaiting_confirmation`,
   two as `knowledge_changed`, `since_revision` 2 kept.
4. `feed-4-r3-restored.json`: all five restored with their three outcomes.

`replay-cases.json` uses the format of the sealed replay cases (`deliver` = feed files in
order; `expect.actions` and `expect.items` with `offered`, `history` count and `reason`). Run it
with the reference consumer:

    python3 -I -B check_feed_compat.py --replay replay-cases.json   # from this directory, with a copy of feed_compat.py

or with Workbooks' `feedClient.applyFeed` the way `feedClient.test.ts` runs the earlier cases.
Attempt texts are never in a feed. Regenerate with `scripts/r4_lifecycle.py --write`.
"""


def _dump(obj) -> str:
    return pr.dumps(obj)


def _serve():
    srv = svc.make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _close(srv) -> None:
    srv.shutdown()
    srv.server_close()
    srv.state.pool.shutdown(wait=True)


def replay_check(url: str, sc: list[dict]) -> dict:
    rows = []
    for s in sc:
        a = svc.call(url, s["route"], s["request"])
        b = svc.call(url, s["route"], s["request"])
        same = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        d = a[1]
        ids = {}
        if s["route"] == "/v1/review" and a[0] == 200:
            ids = {"draft_id": d["draft_id"], "items": [i["item_id"] for i in d["items"]], "evidence": [e["evidence_id"] for e in d["evidence"]],
                   "batch_id": d["plan"]["batch_id"]}
        elif a[0] == 200:
            ids = {"feed_id": d["feed"]["feed_id"], "practice": [i["practice_id"] for i in d["feed"]["items"]]}
        rows.append({"name": s["name"], "http": a[0], "identical_replay": same, "ids": ids})
    return {"scenarios": rows, "ok": all(r["identical_replay"] and r["http"] == 200 for r in rows)}


def correction_check(url: str) -> dict:
    src = rc._read(os.path.join(rc.PRACTICE, "y_en.r1.json"))
    with tempfile.TemporaryDirectory() as t:
        w = p22.Work2(os.path.join(t, "w"))
        w.init(os.path.join(rc.PRACTICE, "y_en.r1.json"), with_review=False)
        before = {i["proposal_ref"]: i for i in w.resolved()["items"]}
        target = before["y-a"]
        text = "« y » remplace un lieu introduit par « à » : « Tu vas à la boulangerie ? — Oui, j'y vais. »"
        d = w.decide(target["item_id"], "edit", text, reason="my own words")
        decs = w.decisions()
    st0, r0 = svc.call(url, "/v1/review", svc.request(sources=[src]))
    st1, r1 = svc.call(url, "/v1/review", svc.request(sources=[src], decisions=decs))
    i0 = next(i for i in r0["items"] if i["item_id"] == target["item_id"])
    i1 = next(i for i in r1["items"] if i["item_id"] == target["item_id"])
    out = {"http": [st0, st1], "item_id": target["item_id"], "source_id_kept": r1["source"]["source_id"] == r0["source"]["source_id"],
           "revision_kept": r1["source"]["revision"] == r0["source"]["revision"], "evidence_ids_kept": i1["evidence_ids"] == i0["evidence_ids"],
           "state": [i0["state"], i1["state"]], "text_is_the_learners": i1["text"] == text, "decision_action": d["action"],
           "decision_based_on_proposed_item_hash": d["based_on"]["item_hash"] == target["item_hash"] == i0["item_hash"],
           "proposed_text_kept_in_source": any(i["ref"] == "y-a" and i["statement"] == i0["text"] for i in src["proposal"]["items"]),
           "counts_after": r1["states"]}
    out["ok"] = (out["source_id_kept"] and out["revision_kept"] and out["evidence_ids_kept"] and out["state"] == ["pending", "corrected"]
                 and out["text_is_the_learners"] and out["decision_based_on_proposed_item_hash"] and out["proposed_text_kept_in_source"])
    return out


def restore_check(feeds: dict) -> dict:
    f1, f2, f3, f4 = (feeds[n] for n, _ in FEEDS)
    w2 = {x["practice_id"]: x for x in f2["withdrawn"]}
    w3 = {x["practice_id"]: x for x in f3["withdrawn"]}
    hist1 = {i["practice_id"]: i["outcomes"] for i in f1["items"]}
    hist4 = {i["practice_id"]: i["outcomes"] for i in f4["items"]}
    out = {"withdrawn_by_r2": sorted(w2), "offered_in_r1": sorted(hist1), "restored_in_feed_4": sorted(f4["restored"]),
           "since_revision_kept": all(x["since_revision"] == 2 for x in w3.values()),
           "reason_codes": {"feed_2": sorted({x["reason_code"] for x in w2.values()}), "feed_3": sorted({x["reason_code"] for x in w3.values()})},
           "outcome_history_kept": hist4 == hist1, "outcomes": sum(len(v) for v in hist1.values())}
    files = {fname: feeds[n] for n, fname in FEEDS}
    names = [fname for _, fname in FEEDS]
    consumer = {}
    for case, order in ORDERS(names):
        state: dict = {}
        acts = [fc.client_apply(state, json.loads(json.dumps(files[n]))) for n in order]
        consumer[case] = {"actions": acts, "items": {pid: {"offered": v["offered"], "history": len(v["history"]),
                                                           **({"reason": v["withdrawn_reason"]} if "withdrawn_reason" in v else {})}
                                                     for pid, v in sorted(state["items"].items())}}
    out["consumer"] = {k: v["actions"] for k, v in consumer.items()}
    out["consumer_converges"] = len({json.dumps(v["items"], sort_keys=True) for v in consumer.values()}) == 1
    out["late_feed_is_stale"] = consumer["late_feed_3"]["actions"][-1] == "stale"
    out["contract_issues"] = {n: fc.contract_issues(f) for n, f in files.items()}
    out["ok"] = (sorted(w2) == sorted(hist1) == sorted(f4["restored"]) and out["since_revision_kept"] and out["outcome_history_kept"]
                 and out["consumer_converges"] and out["late_feed_is_stale"] and not any(out["contract_issues"].values()))
    cases = {"schema": "flh_feed_replay_cases_v1", "source": "R4 lifecycle (fixtures/r4_v1/lifecycle)",
             "cases": {k: {"deliver": order, "expect": consumer[k]} for k, order in ORDERS(names)}}
    return out, cases


def cli_check(sc: list[dict], feeds: dict) -> dict:
    """Run the learner's CLI session for the same lifecycle and compare its plans and feeds with the service."""
    def cli(*args):
        r = subprocess.run([sys.executable, "-B", "-m", "flh_extraction", "practice2", *args], cwd=HERE, capture_output=True, text=True,
                           env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        if r.returncode:
            raise RuntimeError(f"practice2 {args[0]} failed: {r.stderr.strip()[-300:]}")
        return r.stdout

    review = {s["name"]: rc.call(s["route"], s["request"])["body"] for s in sc if s["route"] == "/v1/review"}
    out = {"plans": {}, "feeds": {}}
    with tempfile.TemporaryDirectory() as t:
        w, F = os.path.join(t, "w"), lambda n: os.path.join(rc.PRACTICE, n)
        cli("init", "--source", F("y_en.r1.json"), "--work", w)
        cli("review", "--work", w, "--json", os.path.join(t, "plan-1.json"))
        with open(os.path.join(w, "draft.json"), encoding="utf-8") as fh:
            drf = json.load(fh)
        out["draft_id_equal"] = drf["draft_id"] == review["01-evidence-r1"]["draft_id"]
        ids = {i["proposal_ref"]: i["item_id"] for i in drf["items"]}
        cli("decide", "--work", w, "--item", ids["en-mouvement"], "--reject", "--reason", "my friend corrected exactly this: « j'en vais » is wrong")
        cli("review", "--work", w, "--json", os.path.join(t, "plan-2.json"))
        with open(os.path.join(t, "plan-2.json"), encoding="utf-8") as fh:
            plan = json.load(fh)
        cli("decide", "--work", w, "--approve-batch", plan["batch_id"])
        cli("review", "--work", w, "--json", os.path.join(t, "plan-3.json"))
        cli("build", "--work", w)
        with open(os.path.join(w, "practice.json"), encoding="utf-8") as fh:
            prac = json.load(fh)
        kind = {}
        for p in prac["items"]:
            kind.setdefault(p["kind"], []).append(p["practice_id"])
        cli("answer", "--work", w, "--item", kind["choose"][0], "--text", "y")
        cli("answer", "--work", w, "--item", kind["produce"][0], "--text", "J'en vais au marché.")
        cli("answer", "--work", w, "--item", kind["explain"][0], "--reveal")
        prev = None
        for k, (src, (name, _)) in enumerate(zip((None, "y_en.r2.json", "y_en.r3.json", None), FEEDS), start=1):
            if src:
                cli("revise", "--source", F(src), "--work", w)
            if k == 4:
                with open(os.path.join(w, "draft.json"), encoding="utf-8") as fh:
                    ids3 = {i["proposal_ref"]: i["item_id"] for i in json.load(fh)["items"]}
                for ref in ("en-de", "y-vs-en", "en-vais", "ex-marche"):
                    cli("decide", "--work", w, "--item", ids3[ref], "--approve", "--reason", "re-read in revision 3")
            path = os.path.join(t, f"feed-{k}.json")
            cli("feed", "--work", w, "--out", path, "--seq", str(k), *(["--previous", prev] if prev else []))
            with open(path, encoding="utf-8") as fh:
                got = json.load(fh)
            out["feeds"][name] = {"feed_id_cli": got["feed_id"], "feed_id_http": feeds[name]["feed_id"], "identical": got == feeds[name]}
            prev = path
        for n, (pf, scen) in {"after_rejection": ("plan-2.json", None), "after_batch": ("plan-3.json", "05-approved-r1")}.items():
            with open(os.path.join(t, pf), encoding="utf-8") as fh:
                p = json.load(fh)
            out["plans"][n] = {"batch_id": p["batch_id"], "selected": len(p["selected"])}
        hp = review["05-approved-r1"]["plan"]
        out["plans"]["after_batch"]["equals_http"] = (out["plans"]["after_batch"]["batch_id"] == hp["batch_id"]
                                                      and out["plans"]["after_batch"]["selected"] == len(hp["selected"]))
    out["ok"] = out["draft_id_equal"] and all(v["identical"] for v in out["feeds"].values()) and out["plans"]["after_batch"]["equals_http"]
    return out


def build() -> dict:
    sc = rc.scenarios()
    feeds = {}
    for s in sc:
        if s["route"] == "/v1/feed":
            r = rc.call(s["route"], s["request"])
            if r["status"] == 200:
                feeds[s["name"]] = r["body"]["feed"]
    srv, url = _serve()
    quiet = contextlib.redirect_stderr(io.StringIO())  # the server's per-request log lines
    quiet.__enter__()
    try:
        rep = {"schema": "flh_extraction_r4_lifecycle_report_v1", "deployment_id": srv.state.manifest["deployment_id"],
               "replay": replay_check(url, sc), "correction": correction_check(url)}
    finally:
        _close(srv)
        quiet.__exit__(None, None, None)
    missing = [n for n, _ in FEEDS if n not in feeds]
    if missing:
        rep["restore"] = {"ok": False, "missing_feeds": missing}
        cases = None
    else:
        rep["restore"], cases = restore_check(feeds)
        rep["cli_http"] = cli_check(sc, feeds)
    rep["ok"] = all(v.get("ok") for k, v in rep.items() if isinstance(v, dict))
    return {"report": rep, "feeds": feeds, "cases": cases}


def write(out: str) -> dict:
    b = build()
    os.makedirs(out, exist_ok=True)
    files = {"report.json": _dump(b["report"]), "README.md": README}
    if b["cases"]:
        files["replay-cases.json"] = _dump(b["cases"])
        for n, fname in FEEDS:
            files[fname] = _dump(b["feeds"][n])
    for n, text in files.items():
        with open(os.path.join(out, n), "w", encoding="utf-8") as fh:
            fh.write(text)
    rows = []
    for n in sorted(files):
        rows.append(f"{hashlib.sha256(files[n].encode('utf-8')).hexdigest()}  {n}\n")
    with open(os.path.join(out, "SHA256SUMS"), "w", encoding="utf-8") as fh:
        fh.write("".join(rows))
    return b["report"]


def _bytes(p: str) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.write:
        shutil.rmtree(OUT, ignore_errors=True)
        rep = write(OUT)
    else:
        with tempfile.TemporaryDirectory() as t:
            rep = write(t)
            names = sorted(set(os.listdir(t)) | set(os.listdir(OUT)))
            bad = []
            for n in names:
                pa, pb = os.path.join(t, n), os.path.join(OUT, n)
                if not (os.path.exists(pa) and os.path.exists(pb)) or _bytes(pa) != _bytes(pb):
                    bad.append(n)
        print("check: lifecycle/ equals a fresh run" if not bad else "CHECK FAILED: " + ", ".join(bad))
        if bad:
            return 1
    for k in ("replay", "correction", "restore", "cli_http"):
        v = rep.get(k, {})
        print(f"{k:10} {'ok' if v.get('ok') else 'FAIL'}")
    print("lifecycle:", "PASS" if rep["ok"] else "FAIL")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
