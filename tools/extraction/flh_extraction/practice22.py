"""Extraction 2.2 work directory (PROTOTYPE, offline): the 2.1 directory plus reliable approval.

``Work2`` keeps every 2.1 file and adds:

  sources/rN.json            each revision's source (for paraphrases and material hashes)
  exercise-decisions.jsonl   learner decisions on agent exercise proposals (append-only)
  packets/pk-….json          every exported packet, so a later session can continue without
                             the earlier agent conversation or its directory
  decisions.torn-N.txt       bytes of an interrupted write set aside by ``repair`` (never deleted)

Its resolution is ``review2.resolve2``; its batch is ``review2.plan``. A 2.1 work directory
keeps working with the 2.1 commands; the 2.2 commands are ``practice2 …``.
"""

from __future__ import annotations

import json
import os

from . import exercises as ex
from . import portable as pt
from . import practice as pr
from . import review2 as rv
from .practice_workflow import Work, _read, _write


class TornWrite(ValueError):
    pass


class Work2(Work):
    def init(self, source_path: str, with_review: bool = True) -> str:
        if os.path.exists(self.path) and os.listdir(self.path):
            raise ValueError("the work directory must be new or empty")
        src = _read(source_path)
        drf = pr.draft(src)
        for name in ("source.json", f"sources/r{src['revision']}.json"):
            _write(self.p(name), pr.dumps(src))
        for name in ("draft.json", f"drafts/r{src['revision']}.json"):
            _write(self.p(name), pr.dumps(drf))
        return self.show(with_review)

    def revise(self, source_path: str, with_review: bool = True) -> str:
        old, src = _read(self.p("source.json")), _read(source_path)
        if src.get("source_id") != old["source_id"] or not isinstance(src.get("revision"), int) or src["revision"] <= old["revision"]:
            raise ValueError("a revision must keep the source_id and raise the revision number")
        drf = pr.draft(src)
        for name in ("source.json", f"sources/r{src['revision']}.json"):
            _write(self.p(name), pr.dumps(src))
        for name in ("draft.json", f"drafts/r{src['revision']}.json"):
            _write(self.p(name), pr.dumps(drf))
        if os.path.exists(self.p("practice.json")):
            os.remove(self.p("practice.json"))
        return self.show(with_review)

    def show(self, with_review: bool = True) -> str:
        return rv.render_items(self.resolved()) + ("\n" + rv.render_plan(self.plan()) if with_review else "")

    def sources(self) -> dict:
        d = self.p("sources")
        return {int(f[1:-5]): _read(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.startswith("r") and f.endswith(".json")} \
            if os.path.isdir(d) else {}

    # -- decisions: torn-write detection and repair --

    def decisions(self):
        path = self.p("decisions.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, "rb") as fh:
            raw = fh.read()
        lines = raw.decode("utf-8", errors="replace").split("\n")
        if raw and not raw.endswith(b"\n"):
            try:
                json.loads(lines[-1])
            except ValueError:
                raise TornWrite("decisions.jsonl ends with an incomplete line (an interrupted write); "
                                "run: practice2 repair --work W (it sets the bytes aside, then retry the same command)") from None
        return pr.read_decisions(lines)

    def repair(self) -> str:
        path = self.p("decisions.jsonl")
        if not os.path.exists(path):
            return "nothing to repair: no decisions yet"
        with open(path, "rb") as fh:
            raw = fh.read()
        if raw.endswith(b"\n") or not raw:
            return "nothing to repair: the last line is complete"
        cut = raw.rfind(b"\n") + 1
        tail = raw[cut:]
        try:
            json.loads(tail.decode("utf-8"))
            with open(path, "ab") as fh:
                fh.write(b"\n")
            return "the last record was complete but had no line end; added it"
        except ValueError:
            n = 1
            while os.path.exists(self.p(f"decisions.torn-{n}.txt")):
                n += 1
            with open(self.p(f"decisions.torn-{n}.txt"), "wb") as fh:
                fh.write(tail)
            with open(path, "r+b") as fh:
                fh.truncate(cut)
            return f"set aside {len(tail)} bytes of an incomplete record in decisions.torn-{n}.txt; the {raw[:cut].count(b'\n')} complete records are kept"

    def _append(self, recs: list[dict]) -> None:
        self.decisions()  # refuses on a torn tail
        body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in recs)
        with open(self.p("decisions.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(body)  # one write for the whole batch
            fh.flush()
            os.fsync(fh.fileno())
        self._stale()

    def _stale(self) -> None:
        """A decision changes what practice offers: the next practice() rebuilds."""
        if os.path.exists(self.p("practice.json")):
            os.remove(self.p("practice.json"))

    def resolved(self):
        return rv.resolve2(self.drafts(), self.decisions(), self.sources())

    def _stamp(self, d: dict, it: dict) -> dict:
        d["based_on"]["draft_id"] = self.draft()["draft_id"]
        d["based_on"]["material_hash"] = it["material_hash"]
        return d

    def decide(self, item_id, action, text=None, reason="", via=None, attest: bool = False):
        res = self.resolved()
        it = next((i for i in res["items"] if i["item_id"] == item_id), None)
        if it is None:
            raise ValueError(f"unknown item {item_id!r}")
        if attest and not it["paraphrases"]:
            raise ValueError(f"{item_id} has no paraphrase to attest")
        if action == "approve" and it["paraphrases"] and not attest:
            raise ValueError(f"{item_id} carries a paraphrase: approve it with --attest-paraphrase once you have checked that it says "
                             "what the quoted words say (the attestation is recorded as yours)")
        seq = max([d["seq"] for d in self.decisions()] + [0]) + 1
        d = self._stamp(pr.decision(self.draft(), item_id, action, seq, text, reason, via=via), it)
        if attest:
            d["attest"] = {"what": "the paraphrase restates " + ", ".join(p["of_evidence_id"] or "an uncited quote" for p in it["paraphrases"]),
                           "paraphrases": [p["text"] for p in it["paraphrases"]], "by": "learner"}
        self._append([d])
        return d

    def plan(self, select=None, except_ids=()):
        return rv.plan(self.resolved(), select, except_ids)

    def approve_batch(self, batch_id: str, select=None, except_ids=(), reason: str = "") -> list[dict]:
        res, decs = self.resolved(), self.decisions()
        resumed = rv.resume_check(res, batch_id, decs)
        if resumed is not None:
            if select is not None or except_ids:
                raise ValueError("a resumed batch keeps the selection it was started with; give only --approve-batch")
            todo, meta = resumed
        else:
            pl = rv.plan(res, select, except_ids)
            if pl["batch_id"] is None:
                raise ValueError("nothing can be approved together: every remaining item needs its own decision")
            if batch_id != pl["batch_id"]:
                raise ValueError(f"batch {batch_id} is not the batch shown now ({pl['batch_id']}): the draft or your decisions changed; review again")
            if not pl["selected"]:
                raise ValueError("nothing selected: every batch member was left out")
            todo, meta = pl["selected"], rv.batch_meta(pl)
        byid = {i["item_id"]: i for i in res["items"]}
        seq = max([d["seq"] for d in decs] + [0]) + 1
        out = [self._stamp(pr.decision(self.draft(), iid, "approve", seq + k, reason=reason, batch=meta), byid[iid]) for k, iid in enumerate(todo)]
        if out:
            self._append(out)
        return out

    def answer(self, practice_id, text=None, reveal=False):
        """As 2.1, and the attempt records the source revision it was made on (Workbooks stores it)."""
        seq = max([a["seq"] for a in self.attempts()] + [0]) + 1
        rec, fb = pr.attempt(self.practice(), practice_id, seq, text, reveal)
        s = self.draft()["source"]
        rec["source_revision"] = {"revision": s["revision"], "revision_sha256": s["revision_sha256"]}
        with open(self.p("attempts.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        return pr.render_feedback(fb)

    # -- agent exercise proposals --

    def exercise_decisions(self) -> list[dict]:
        return _jsonl(self.p("exercise-decisions.jsonl"))

    def exercise(self, packet: dict, ret: dict, proposal_id: str, action: str, edits: dict | None = None, reason: str = "") -> tuple[dict, bool]:
        decided = self.exercise_decisions()
        seq = max([d["seq"] for d in decided] + [0]) + 1
        rec, new = ex.decide(packet, ret, proposal_id, action, seq, self.resolved(), decided, edits, reason)
        if new:
            with open(self.p("exercise-decisions.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
            self._stale()
        return rec, new

    def practice(self, rebuild=False):
        if rebuild or not os.path.exists(self.p("practice.json")):
            res = self.resolved()
            prac = pr.build_practice(res)
            src = _read(self.p("source.json"))
            items, suspended = ex.practice_items(res, self.exercise_decisions(), pr.source_text(src))
            prac["items"] = prac["items"] + items
            prac["counts"] = {k: sum(1 for p in prac["items"] if p["kind"] == k) for k in ("explain", "choose", "produce")}
            prac["from_agents"] = {"offered": [p["practice_id"] for p in items], "suspended": suspended}
            _write(self.p("practice.json"), pr.dumps(prac))
        return _read(self.p("practice.json"))

    # -- packets: every export is kept, so the next session needs no earlier conversation --

    def export3(self, mode="study", include_rubrics=False, previous=None, variant="full", omit=(), awaiting=None, keep=True) -> dict:
        if previous == "latest":
            previous = self.latest_packet()
            if previous is None:
                raise ValueError("--previous latest: no packet has been exported from this work directory yet")
        p = pt.export3(self.resolved(), self.practice(rebuild=True), self.attempts(), mode, include_rubrics, previous, variant, omit, awaiting)
        if keep:
            n = len(_jsonl(self.p("packets/index.jsonl"))) + 1
            _write(self.p(f"packets/{p['packet_id']}.json"), pr.dumps(p))
            with open(self.p("packets/index.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"n": n, "packet_id": p["packet_id"], "schema": p["schema"], "variant": p["variant"], "mode": p["mode"],
                                     "source_revision": p["source"]["revision"]}, sort_keys=True) + "\n")
        return p

    def latest_packet(self) -> dict | None:
        idx = [r for r in _jsonl(self.p("packets/index.jsonl")) if r["variant"] == "full"]
        return _read(self.p(f"packets/{idx[-1]['packet_id']}.json")) if idx else None


def _jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


# ---- acceptance matrix (R2-020): every state transition, executed ----

def _mini(rev: int, quote_in_text: bool = True, statement: str = "« y » replaces a place after « à ».", ctx_prefix: str = "",
          para: bool = False, with_item: bool = True, extra_error: bool = False, canonical: str = "y") -> dict:
    ctx = ctx_prefix + ("Elle a dit : « On dit : oui, j'y vais. »" if quote_in_text else "Elle a dit : « On dit : oui, j'irai. »")
    items = []
    if with_item:
        it = {"type": "claim", "ref": "c1", "statement": statement, "quotes": ["On dit : oui, j'y vais."], "kind": "grammar", "canonical": canonical}
        if para:
            it["paraphrases"] = [{"text": "Her answer uses « y » for the place.", "of": "On dit : oui, j'y vais."}]
        items.append(it)
    items.append({"type": "claim", "ref": "c2", "statement": "« y » comes before the verb.", "quotes": ["Elle a dit"], "kind": "grammar", "canonical": "y-place"})
    items.append({"type": "claim", "ref": "c3", "statement": "« en » goes with every verb.", "quotes": ["not in the text"], "kind": "grammar", "canonical": "en-all"})
    if extra_error:
        items.append({"type": "common_error", "ref": "e1", "wrong": "j'en vais", "right": "j'y vais", "why": "aller à takes y", "quotes": ["Elle a dit"]})
        items.append({"type": "claim", "ref": "c4", "statement": "« j'en vais » is also correct.", "quotes": ["Elle a dit"], "kind": "grammar", "canonical": "en-vais"})
    return {"schema": pr.SOURCE_SCHEMA, "source_id": "matrix-demo", "revision": rev, "learner_goal": "",
            "capture": {"schema_version": "learning_capture_v1", "source": "manual", "original_input": "Pourquoi « y » ?", "original_context": ctx},
            "proposal": {"proposer": "synthetic: acceptance matrix", "items": items}}


def acceptance_matrix(root: str) -> dict:
    """Run each transition on a small synthetic source in its own work directory under ``root``."""
    rows = []

    def w_(name, *srcs):
        w = Work2(os.path.join(root, name))
        for k, s in enumerate(srcs):
            p = os.path.join(root, f"{name}.r{s['revision']}.json")
            _write(p, pr.dumps(s))
            w.init(p) if k == 0 else w.revise(p)
        return w

    def state(w, ref):
        res = w.resolved()
        it = next(i for i in res["items"] if i["proposal_ref"] == ref)
        return it["state"] + (f" ({it['review_kind']})" if it.get("review_kind") else "")

    def iid(w, ref):
        return next(i["item_id"] for i in w.draft()["items"] if i["proposal_ref"] == ref)

    def row(frm, event, expect, got, rule):
        rows.append({"from": frm, "event": event, "expected": expect, "observed": got, "ok": expect == got, "rule": rule})

    def refused(fn):
        try:
            fn()
            return "accepted"
        except ValueError:
            return "refused"

    w = w_("a", _mini(1))
    w.decide(iid(w, "c1"), "approve")
    row("pending", "approve", "approved", state(w, "c1"), "a learner decision")
    w.decide(iid(w, "c3"), "reject", reason="not in my text")
    row("pending", "reject", "rejected", state(w, "c3"), "a learner decision")
    w.decide(iid(w, "c2"), "edit", "« y » comes before the conjugated verb.")
    row("pending", "edit", "corrected", state(w, "c2"), "the learner's wording replaces the proposal; the proposal is kept")

    w = w_("b", _mini(1))
    bid = w.plan()["batch_id"]
    w.approve_batch(bid)
    row("pending (supported)", "batch approve", "approved", state(w, "c1"), "only supported items without cue, conflict or paraphrase")
    row("pending (unsupported)", "batch approve", "pending", state(w, "c3"), "never batched")
    again = w.approve_batch(bid)
    row("batch applied", "the same batch command again", "nothing written", "nothing written" if again == [] else f"{len(again)} records",
        "a repeated batch is a no-op")
    w = w_("b2", _mini(1))
    bid = w.plan()["batch_id"]
    w.decide(iid(w, "c3"), "reject", reason="not in my text")
    row("batch shown, then a decision on a non-member", "batch approve with the shown ID", "accepted",
        "accepted" if w.plan()["batch_id"] == bid else "refused", "the members and their hashes are unchanged")
    w.decide(iid(w, "c2"), "reject", reason="changed my mind")
    row("batch shown, then a decision on a member", "batch approve with the shown ID", "refused", refused(lambda: w.approve_batch(bid)),
        "a batch ID binds exactly the members shown")

    w = w_("c", _mini(1, para=True))
    row("pending (paraphrase)", "approve without attestation", "refused", refused(lambda: w.decide(iid(w, "c1"), "approve")),
        "a paraphrase is never evidence")
    w.decide(iid(w, "c1"), "approve", attest=True)
    row("pending (paraphrase)", "approve with --attest-paraphrase", "approved", state(w, "c1"), "the attestation is recorded as the learner's")

    w = w_("d", _mini(1))
    w.decide(iid(w, "c1"), "approve")
    w.decide(iid(w, "c3"), "reject", reason="not in my text")
    w.revise(_p(root, "d", _mini(2)))
    row("approved", "revision, item unchanged", "approved", state(w, "c1"), "carried while unchanged")
    row("rejected", "revision, item unchanged", "rejected", state(w, "c3"), "the reason stays with revision 1")
    w.revise(_p(root, "d", _mini(3, statement="« y »  replaces a place after « à ».")))
    row("approved", "revision, spacing only", "approved", state(w, "c1"), "not material: Unicode spaces, apostrophes, NFC")
    w.revise(_p(root, "d", _mini(4, canonical="y (lieu)")))
    row("approved", "revision, material change (same item ID)", "needs_review (changed)", state(w, "c1"),
        "a material change is never covered by the old approval")
    old_id = iid(w, "c1")
    w.revise(_p(root, "d", _mini(5, canonical="y (lieu)", statement="« y » replaces a place after « à », « dans » or « chez ».")))
    row("approved", "revision rewrites the claim statement", "pending (new item ID)",
        state(w, "c1") + (" (new item ID)" if iid(w, "c1") != old_id else " (same ID)"),
        "a claim's ID hashes its statement: a rewritten claim is a new item, and no approval transfers to it")

    w = w_("e", _mini(1))
    w.decide(iid(w, "c1"), "approve")
    w.revise(_p(root, "e", _mini(2, quote_in_text=False)))
    row("approved", "revision removes the quote", "needs_review (changed)", state(w, "c1"), "practice is withdrawn")
    w.revise(_p(root, "e", _mini(3)))
    row("needs_review (quote removed)", "revision restores the quote", "needs_review (restored)", state(w, "c1"),
        "no silent reactivation")
    w.decide(iid(w, "c1"), "approve", reason="checked again")
    row("needs_review (restored)", "approve", "approved", state(w, "c1"), "a new learner decision")

    w = w_("f", _mini(1))
    w.decide(iid(w, "c1"), "approve")
    w.revise(_p(root, "f", _mini(2, with_item=False)))
    w.revise(_p(root, "f", _mini(3)))
    row("approved", "absent from one revision, back unchanged", "approved", state(w, "c1"), "a decision on an unchanged item is kept")

    w = w_("g", _mini(1))
    w.decide(iid(w, "c1"), "approve")
    w.revise(_p(root, "g", _mini(2, ctx_prefix="Hier, il pleuvait. ")))
    moved = bool(w.resolved()["moves"])
    row("approved", "revision moves the quote", "approved (moved shown)", state(w, "c1") + (" (moved shown)" if moved else ""),
        "a moved quote is still located")

    w = w_("h", _mini(1, extra_error=True))
    blocked = {r["item_id"] for r in w.plan()["left_for_you"]}
    row("pending conflict pair", "batch", "both left to the learner",
        "both left to the learner" if {iid(w, "e1"), iid(w, "c4")} <= blocked else "batched", "a conflict is decided one by one")
    w.decide(iid(w, "c4"), "reject", reason="my friend corrected it")
    row("conflict, one side rejected", "batch", "other side batchable",
        "other side batchable" if iid(w, "e1") in {m["item_id"] for m in w.plan()["members"]} else "still blocked", "a resolved conflict blocks nothing")

    w = w_("i", _mini(1))
    pl = w.plan()
    meta = rv.batch_meta(pl)
    res = w.resolved()
    byid = {i["item_id"]: i for i in res["items"]}
    first = w._stamp(pr.decision(w.draft(), pl["selected"][0], "approve", 1, batch=meta), byid[pl["selected"][0]])
    with open(w.p("decisions.jsonl"), "w", encoding="utf-8") as fh:  # an interrupted batch: one record, then half of the next
        fh.write(json.dumps(first, ensure_ascii=False, sort_keys=True) + "\n" + '{"schema": "flh_practice_dec')
    row("batch interrupted", "retry without repair", "refused", refused(lambda: w.approve_batch(pl["batch_id"])), "a torn write is never read as data")
    w.repair()
    w.approve_batch(pl["batch_id"])
    ids = [d["item_id"] for d in w.decisions()]
    row("batch interrupted, repaired", "retry the same batch", "each member approved once",
        "each member approved once" if sorted(ids) == sorted(pl["selected"]) else f"records {ids}", "the retry writes only what is missing")
    return {"schema": "flh_practice_acceptance_matrix_v1", "rows": rows, "all_ok": all(r["ok"] for r in rows)}


def _p(root: str, name: str, src: dict) -> str:
    p = os.path.join(root, f"{name}.r{src['revision']}.json")
    _write(p, pr.dumps(src))
    return p


def render_matrix(m: dict) -> str:
    L = ["| From | Event | Expected | Observed | OK | Rule |", "|---|---|---|---|---|---|"]
    L += [f"| {r['from']} | {r['event']} | {r['expected']} | {r['observed']} | {'yes' if r['ok'] else '**NO**'} | {r['rule']} |" for r in m["rows"]]
    return "\n".join(L) + f"\n\n{sum(r['ok'] for r in m['rows'])} of {len(m['rows'])} transitions as expected.\n"
