"""R4 synthetic corpus and its frozen baseline (offline, synthetic, standard library only).

The corpus is a fixed list of ``flh_extraction_service_v1`` requests that walk one source
through every state a learner meets, plus the three R4 grounding-quality sources:

  01  evidence: revision 1 before any decision (supported, unsupported and generated items)
  02-04  grounding quality: negation, accents and case, paraphrase (``fixtures/r4_v1/quality``)
  05  pending review decided: one rejection, then the batch the review proposes
  06  first feed, with two attempts and a reveal (attempt texts are never sent)
  07  revision 2: two approved items need review again
  08  feed 2: no item offered, every earlier item withdrawn (reason codes, history kept)
  09  revision 3: evidence restored, awaiting the learner's confirmation
  10  feed 3: withdrawn with ``awaiting_confirmation``
  11  revision 3 confirmed one by one
  12  feed 4: the withdrawn items restored with their outcome history

Every request is built with the existing 2.2 work-directory API in a temporary directory
(the same calls a learner's CLI session makes) and answered by the service's own
``dispatch``. Nothing here calls a model or the network; the output is byte-identical on
every run. ``scripts/r4_corpus.py`` writes it to ``fixtures/r4_v1/`` and checks it.
"""

from __future__ import annotations

import json
import os
import tempfile

from . import practice as pr
from . import practice22 as p22
from . import service as svc

CORPUS = "flh_extraction_r4_corpus_v1"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRACTICE = os.path.join(HERE, "fixtures", "practice_v1")
QUALITY = os.path.join(HERE, "fixtures", "r4_v1", "quality")
QUALITY_SOURCES = ("q_negation.json", "q_accents.json", "q_paraphrase.json")
ATTEMPT_KEYS = ("schema", "seq", "practice_id", "action", "outcome")


def _read(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def call(path: str, req: dict) -> dict:
    """One in-process service call (no socket): the HTTP layer adds only status codes and headers."""
    body = json.dumps(req, ensure_ascii=False).encode("utf-8")
    try:
        return {"status": 200, "body": svc.dispatch(path, body, {"x-flh-contract": svc.CONTRACT}, dict(svc.LIMITS), svc.manifest(dict(svc.LIMITS))["deployment_id"])}
    except svc.ServiceError as e:
        return {"status": e.status, "body": {"error": {"type": e.code, "message": str(e)}}}


def _ids(w) -> dict:
    return {i["proposal_ref"]: i["item_id"] for i in w.resolved()["items"]}


def _attempts(w) -> list[dict]:
    """Attempt outcomes only: the service never needs (and the corpus never sends) the learner's answer text."""
    return [{k: a[k] for k in ATTEMPT_KEYS} for a in w.attempts()]


def scenarios() -> list[dict]:
    """The ordered scenarios: name, route, request. Feeds after the first carry the previous service feed."""
    out = []
    last_feed = []

    def add(name, route, **fields):
        out.append({"name": name, "route": route, "request": svc.request(**fields)})
        if route == "/v1/feed":
            r = call(route, out[-1]["request"])
            if r["status"] == 200:
                last_feed[:] = [r["body"]["feed"]]
        return out[-1]

    def previous():
        """The client's last applied feed: a refused feed request is never treated as applied."""
        return last_feed[0]

    srcs = [_read(os.path.join(PRACTICE, f"y_en.r{r}.json")) for r in (1, 2, 3)]
    with tempfile.TemporaryDirectory() as t:
        y = p22.Work2(os.path.join(t, "y-en"))
        y.init(os.path.join(PRACTICE, "y_en.r1.json"), with_review=False)
        add("01-evidence-r1", "/v1/review", sources=srcs[:1])
        for n, f in zip(("02-quality-negation", "03-quality-accents", "04-quality-paraphrase"), QUALITY_SOURCES):
            add(n, "/v1/review", sources=[_read(os.path.join(QUALITY, f))])
        yi = _ids(y)
        y.decide(yi["en-mouvement"], "reject", reason="my friend corrected exactly this: « j'en vais » is wrong")
        y.approve_batch(y.plan()["batch_id"])
        add("05-approved-r1", "/v1/review", sources=srcs[:1], decisions=y.decisions())
        prac = y.practice(rebuild=True)
        by_kind = {}
        for p in prac["items"]:
            by_kind.setdefault(p["kind"], []).append(p["practice_id"])
        y.answer(by_kind["choose"][0], "y")
        y.answer(by_kind["produce"][0], "J'en vais au marché.")
        y.answer(by_kind["explain"][0], reveal=True)
        add("06-feed-r1", "/v1/feed", sources=srcs[:1], decisions=y.decisions(), attempts=_attempts(y), feed_seq=1)
        y.revise(os.path.join(PRACTICE, "y_en.r2.json"), with_review=False)
        add("07-revision-r2", "/v1/review", sources=srcs[:2], decisions=y.decisions())
        add("08-feed-r2-withdrawn", "/v1/feed", sources=srcs[:2], decisions=y.decisions(), attempts=_attempts(y), feed_seq=2,
                 previous=previous())
        y.revise(os.path.join(PRACTICE, "y_en.r3.json"), with_review=False)
        add("09-revision-r3", "/v1/review", sources=srcs, decisions=y.decisions())
        add("10-feed-r3-awaiting", "/v1/feed", sources=srcs, decisions=y.decisions(), attempts=_attempts(y), feed_seq=3,
                 previous=previous())
        yi = _ids(y)
        for ref in ("en-de", "y-vs-en", "en-vais", "ex-marche"):
            y.decide(yi[ref], "approve", reason="re-read in revision 3")
        add("11-confirmed-r3", "/v1/review", sources=srcs, decisions=y.decisions())
        add("12-feed-r3-restored", "/v1/feed", sources=srcs, decisions=y.decisions(), attempts=_attempts(y), feed_seq=4,
            previous=previous())
    return out


def summarize(name: str, route: str, resp: dict) -> dict:
    b = resp["body"]
    row = {"name": name, "route": route, "status": resp["status"]}
    if b.get("status") != "ok":
        return {**row, "error": b.get("error", {}).get("type"), "message": b.get("error", {}).get("message")}
    if route == "/v1/review":
        return {**row, "draft_id": b["draft_id"], "revision": b["source"]["revision"], "states": b["states"],
                "support": {k: v for k, v in b["counts"].items() if v} if isinstance(b.get("counts"), dict) else b.get("counts"),
                "batch_selected": len(b["plan"]["selected"]), "left_for_you": len(b["plan"]["left_for_you"]),
                "items": [{"item_id": i["item_id"], "support": i["support"], "state": i["state"], "cues": [c["cue"] for c in i["cues"]],
                           "groundings": [g["status"] for g in i["groundings"]]} for i in b["items"]]}
    f = b["feed"]
    return {**row, "feed_id": f["feed_id"], "feed_seq": f["feed_seq"], "revision": f["source"]["revision"], "items": len(f["items"]),
            "outcomes": sum(len(i.get("outcomes", [])) for i in f["items"]),
            "withdrawn": [[w["practice_id"], w["reason_code"], w["since_revision"]] for w in f.get("withdrawn", [])],
            "restored": f.get("restored"), "added": f.get("added")}


def build() -> tuple[list[dict], list[dict], list[dict]]:
    """(scenarios, responses, summaries) in corpus order."""
    sc = scenarios()
    resp = [call(s["route"], s["request"]) for s in sc]
    return sc, resp, [summarize(s["name"], s["route"], r) for s, r in zip(sc, resp)]


def report(summaries: list[dict], deployment_id: str) -> str:
    L = ["# R4 baseline report (frozen before any R4 change)", "",
         f"Service `{deployment_id}`. Synthetic corpus `{CORPUS}`; requests in `corpus/`, full responses in `baseline/`.", "",
         "| # | Scenario | Route | Status | What the learner sees |", "|---|---|---|---|---|"]
    for s in summaries:
        if s.get("error"):
            what = f"error {s['error']}"
        elif s["route"] == "/v1/review":
            st = ", ".join(f"{k} {v}" for k, v in s["states"].items() if v)
            sup = ", ".join(f"{k} {v}" for k, v in s["support"].items())
            what = f"r{s['revision']}: {st}; support {sup}; batch {s['batch_selected']}, left for review {s['left_for_you']}"
        else:
            wd = {}
            for _, code, _ in s["withdrawn"] or []:
                wd[code] = wd.get(code, 0) + 1
            what = (f"r{s['revision']} seq {s['feed_seq']}: {s['items']} offered, {s['outcomes']} outcomes; withdrawn "
                    + (", ".join(f"{k} {v}" for k, v in sorted(wd.items())) or "none")
                    + f"; restored {len(s['restored'] or [])}; added {len(s['added'] or [])}")
        L.append(f"| {s['name'][:2]} | {s['name'][3:]} | `{s['route']}` | {s['status']} | {what} |")
    return "\n".join(L) + "\n"


def dumps(obj) -> str:
    return pr.dumps(obj)
