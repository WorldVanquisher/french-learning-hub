"""Evaluation-data intake checks (standard library only; no audio is read, nothing is downloaded).

Speaking Lab 2 left one gap: no frozen split has the 30 independent speakers the candidate
review requires. Before any new evaluation source is fetched, these checks say whether it can
close that gap honestly:

* ``check_proposal``: the intake checklist (``flh_speaking_intake_checklist_v1``) for a
  proposed source: licence, pinned revision, attribution, published speaker IDs, speaker
  provenance and consent statement, audio not redistributed, no personal data in the
  metadata, recording conditions labelled, and evaluation speakers kept apart from training.
* ``speaker_needs``: from a pinned data manifest, how many distinct speakers each split
  offers, whether the evaluation splits share speakers with training, and how many more are
  needed for ``min_groups``.
* ``merge_check``: several evaluation sources together: a raw speaker ID that appears in two
  sources is a collision (namespacing is required; the same person is never assumed), and the
  same audio hash twice is a duplicate.
* ``pair_check``: noise conditions stay paired: a speaker-quality report may only use clips
  present in every condition; unpaired clips are listed and dropped, never compared.

The review's support rule is unchanged: below ``min_groups`` speakers a comparison remains an
observation, whatever these checks say.
"""

from __future__ import annotations

import re

CHECKLIST = "flh_speaking_intake_checklist_v1"
LICENSES = {"CC-BY-4.0": "attribution required", "CC0-1.0": "no conditions", "CC-BY-SA-4.0": "attribution and share-alike: owner decision"}
ITEMS = [
    ("license", "an open licence that allows evaluation use", "license"),
    ("pinned_revision", "a dataset repository and a 40-hex revision", "revision"),
    ("attribution", "the attribution text to cite", "attribution"),
    ("speaker_ids", "per-utterance speaker IDs are published (otherwise speakers cannot be counted as groups)", "speaker_id_field"),
    ("speaker_provenance", "who the speakers are and how they agreed to be recorded (for example read speech by volunteers, consent stated)",
     "speaker_provenance"),
    ("no_redistribution", "audio stays outside the repository; only manifests with hashes are kept", "audio_redistributed"),
    ("no_personal_data", "no names, contact details or free-text personal fields in the metadata kept", "metadata_fields"),
    ("conditions_labelled", "recording or noise conditions are labelled per clip", "condition_field"),
    ("eval_apart_from_train", "evaluation speakers can be kept disjoint from any training speakers", "speaker_disjoint_splits"),
]
PERSONAL = re.compile(r"name|email|e-mail|phone|address|birth|age_exact|ssn", re.I)


def check_proposal(p: dict) -> dict:
    rows = []

    def row(i, ok, detail):
        rows.append({"id": i, "status": "pass" if ok else "fail", "detail": detail})

    lic = p.get("license")
    row("license", lic in LICENSES, f"{lic}: {LICENSES.get(lic, 'not on the accepted list (' + ', '.join(sorted(LICENSES)) + ')')}")
    row("pinned_revision", bool(p.get("repo")) and bool(re.fullmatch(r"[0-9a-f]{40}", str(p.get("revision", "")))),
        f"{p.get('repo')} @ {p.get('revision')}")
    row("attribution", bool((p.get("attribution") or "").strip()), p.get("attribution") or "missing")
    row("speaker_ids", bool(p.get("speaker_id_field")), f"field {p.get('speaker_id_field')!r}" if p.get("speaker_id_field")
        else "no speaker IDs: every clip would have to count as one unknown speaker, so the source adds no support")
    row("speaker_provenance", bool((p.get("speaker_provenance") or "").strip()) and bool(p.get("consent_statement")),
        (p.get("speaker_provenance") or "missing") + ("; consent statement given" if p.get("consent_statement") else "; no consent statement"))
    row("no_redistribution", p.get("audio_redistributed") is False, "audio kept outside the repository" if p.get("audio_redistributed") is False
        else "the proposal would put audio in the repository")
    personal = sorted(f for f in p.get("metadata_fields", []) if PERSONAL.search(f))
    row("no_personal_data", not personal, "metadata fields: " + ", ".join(p.get("metadata_fields", [])) + (f"; personal: {personal}" if personal else ""))
    row("conditions_labelled", bool(p.get("condition_field")), f"field {p.get('condition_field')!r}" if p.get("condition_field") else "no condition label")
    row("eval_apart_from_train", p.get("speaker_disjoint_splits") is True, "speaker-disjoint splits" if p.get("speaker_disjoint_splits")
        else "splits are not speaker-disjoint (or unknown)")
    fails = [r["id"] for r in rows if r["status"] == "fail"]
    return {"schema": CHECKLIST, "source_id": p.get("source_id"), "rows": rows, "decision": "eligible for owner approval" if not fails
            else "not eligible: " + ", ".join(fails), "note": "eligibility is not approval: fetching data is the owner's decision"}


def speaker_needs(rows: list[dict], min_groups: int = 30, eval_splits=("test", "dev")) -> dict:
    by: dict = {}
    unknown: dict = {}
    for r in rows:
        spk = r.get("speaker")
        if spk in (None, "", "unknown"):
            unknown[r.get("split", "?")] = unknown.get(r.get("split", "?"), 0) + 1
            continue
        by.setdefault(r.get("split", "?"), set()).add(f"{r.get('corpus', '?')}:{spk}")
    train = by.get("train", set())
    out = {}
    for s in sorted(set(by) | set(unknown)):
        have = by.get(s, set())
        out[s] = {"speakers": len(have), "clips_without_speaker_id": unknown.get(s, 0),
                  "shared_with_train": len(have & train) if s != "train" else None,
                  "usable_for_evaluation": s in eval_splits, "needed_for_min_groups": max(0, min_groups - len(have - train)) if s in eval_splits else None}
    pooled = set().union(*(by.get(s, set()) for s in eval_splits)) - train
    return {"min_groups": min_groups, "splits": out, "pooled_evaluation_speakers": len(pooled),
            "pooled_needed": max(0, min_groups - len(pooled)),
            "rule": "speakers are counted per corpus (corpus:speaker); training speakers never count for evaluation; clips without a "
                    "speaker ID add no group", "pooling_note": "pooling dev and test into one evaluation set is an owner decision: it "
                                                               "removes the development split"}


def merge_check(sources: dict) -> dict:
    """``sources`` maps a source name to its manifest rows."""
    seen_spk: dict = {}
    seen_audio: dict = {}
    collisions, dups = [], []
    for name in sorted(sources):
        for r in sources[name]:
            spk = str(r.get("speaker", ""))
            if spk:
                other = seen_spk.setdefault(spk, name)
                if other != name and (spk, other, name) not in collisions:
                    collisions.append((spk, other, name))
            h = r.get("pcm_sha256")
            if h:
                if h in seen_audio and seen_audio[h] != (name, r.get("id")):
                    dups.append({"pcm_sha256": h[:16], "first": seen_audio[h], "again": (name, r.get("id"))})
                seen_audio.setdefault(h, (name, r.get("id")))
    groups = {f"{n}:{r['speaker']}" for n, rs in sources.items() for r in rs if r.get("speaker")}
    return {"collisions": [{"speaker": s, "sources": [a, b], "rule": "kept apart as two groups (source:speaker); never assumed to be one person"}
                           for s, a, b in sorted(set(collisions))],
            "duplicate_audio": dups, "groups_after_namespacing": len(groups),
            "groups_if_raw_ids_were_trusted": len({str(r.get("speaker")) for rs in sources.values() for r in rs if r.get("speaker")}),
            "ok": not dups}


def pair_check(rows: list[dict], conditions=None) -> dict:
    """Rows carry ``speaker``, ``clip`` and ``condition``. Only clips present in every condition are paired."""
    conds = sorted(set(conditions or {r["condition"] for r in rows}))
    have: dict = {}
    for r in rows:
        have.setdefault((r["speaker"], r["clip"]), set()).add(r["condition"])
    paired = sorted(k for k, v in have.items() if set(conds) <= v)
    unpaired = sorted(({"speaker": k[0], "clip": k[1], "missing": sorted(set(conds) - v)} for k, v in have.items() if not set(conds) <= v),
                      key=lambda x: (x["speaker"], x["clip"]))
    per_spk: dict = {}
    for s, c in paired:
        per_spk[s] = per_spk.get(s, 0) + 1
    return {"conditions": conds, "paired_clips": len(paired), "unpaired": unpaired, "speakers_with_pairs": len(per_spk),
            "per_speaker_pairs": dict(sorted(per_spk.items())),
            "rule": "a speaker-quality report compares conditions only on clips present in every condition; unpaired clips are dropped, not imputed"}


def render(rep: dict) -> str:
    L = []
    if "proposal" in rep:
        p = rep["proposal"]
        L.append(f"Intake checklist for {p['source_id']}: {p['decision']}")
        L += [f"  {r['status']:4} {r['id']:22} {r['detail']}" for r in p["rows"]]
        L.append(f"  ({p['note']})")
    if "needs" in rep:
        n = rep["needs"]
        L.append(f"Speakers per split (min_groups {n['min_groups']}):")
        for s, v in n["splits"].items():
            L.append(f"  {s:6} speakers {v['speakers']:3}  without ID {v['clips_without_speaker_id']:4}  shared with train "
                     f"{'-' if v['shared_with_train'] is None else v['shared_with_train']:>3}  "
                     + (f"needed {v['needed_for_min_groups']}" if v["usable_for_evaluation"] else "not an evaluation split"))
        L.append(f"  dev and test pooled: {n['pooled_evaluation_speakers']} speakers, {n['pooled_needed']} more needed ({n['pooling_note']})")
    if "merge" in rep:
        m = rep["merge"]
        L.append(f"Merge: {m['groups_after_namespacing']} groups after namespacing ({m['groups_if_raw_ids_were_trusted']} if raw IDs were trusted); "
                 f"collisions {len(m['collisions'])}; duplicate audio {len(m['duplicate_audio'])}")
        L += [f"  collision {c['speaker']} in {' and '.join(c['sources'])}: {c['rule']}" for c in m["collisions"]]
        L += [f"  duplicate audio {d['pcm_sha256']}…: {d['first']} and {d['again']}" for d in m["duplicate_audio"]]
    if "pairs" in rep:
        q = rep["pairs"]
        L.append(f"Pairs over {', '.join(q['conditions'])}: {q['paired_clips']} paired clips from {q['speakers_with_pairs']} speakers; "
                 f"unpaired {len(q['unpaired'])}")
        L += [f"  unpaired {u['speaker']}/{u['clip']}: missing {', '.join(u['missing'])}" for u in q["unpaired"]]
    return "\n".join(L) + "\n"
