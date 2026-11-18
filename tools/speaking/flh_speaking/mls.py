"""Deterministic selection of a small Multilingual LibriSpeech (MLS) French subset.

The rule uses only pinned text files from the dataset revision (``metainfo.txt``
and each split's ``transcripts.txt``), so anyone can recompute it:

* MLS's own partitions give the splits, and MLS keeps speakers apart between
  them. Book (source text) disjointness is not guaranteed by MLS: dev and test
  share books. The rule therefore removes every book that occurs anywhere in
  the MLS dev or test partitions from the training candidates, and keeps the
  selected dev and test archives on books distinct from each other.
* An archive is one ``<speaker>_<book>`` recording set. Per split, speakers are
  taken alternately by gender (F, M, F, ...), each with its archive of fewest
  utterances that still has the required minimum, smallest first, ties broken
  by identifier. A speaker is used at most once per split; in dev and test a
  book is too (training archives may share a book, never with dev or test).
* Within an archive the first ``per_speaker`` utterance ids (sorted) are kept.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass

SELECTION_RULE = "flh_mls_fr_subset_v1"

# (split, MLS partition name, speakers per gender, minimum utterances, utterances per speaker)
PLAN = (
    ("test", "test", 4, 30, 30),
    ("dev", "dev", 2, 25, 25),
    ("train", "train", 12, 60, 60),
)


@dataclass(frozen=True)
class Archive:
    speaker: str
    book: str
    gender: str
    utterances: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.speaker}_{self.book}"


def parse_metainfo(text: str) -> dict[tuple[str, str], dict]:
    """(speaker, book) -> {gender, partition}. Header line and blank lines are skipped."""
    out: dict[tuple[str, str], dict] = {}
    for line in text.splitlines()[1:]:
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 5 or not cols[0]:
            continue
        out.setdefault((cols[0], cols[4]), {"gender": cols[1], "partition": cols[2]})
    return out


def parse_transcripts(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        uid, _, sentence = line.partition("\t")
        if not sentence or uid in out:
            raise ValueError(f"malformed or duplicate transcript line for {uid!r}")
        out[uid] = sentence
    return out


def archives(meta: dict, transcripts: dict[str, str]) -> list[Archive]:
    groups: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for uid in transcripts:
        spk, book, _ = uid.split("_")
        groups[(spk, book)].append(uid)
    out = []
    for (spk, book), uids in groups.items():
        gender = meta.get((spk, book), {}).get("gender")
        if gender not in ("F", "M"):
            raise ValueError(f"no gender in metainfo for {spk}_{book}")
        out.append(Archive(spk, book, gender, tuple(sorted(uids))))
    return out


def _pick(cands: list[Archive], per_gender: int, minimum: int, banned_books: set[str], distinct_books: bool) -> list[Archive]:
    best: dict[str, Archive] = {}
    for a in cands:
        if len(a.utterances) < minimum or a.book in banned_books:
            continue
        cur = best.get(a.speaker)
        if cur is None or (len(a.utterances), a.book) < (len(cur.utterances), cur.book):
            best[a.speaker] = a
    queues = {g: sorted((a for a in best.values() if a.gender == g), key=lambda a: (len(a.utterances), a.speaker)) for g in ("F", "M")}
    chosen: list[Archive] = []
    books: set[str] = set()
    for _ in range(per_gender):
        for g in ("F", "M"):
            q = queues[g]
            while q and distinct_books and q[0].book in books:
                q.pop(0)
            if not q:
                raise ValueError(f"not enough {g} speakers")
            a = q.pop(0)
            chosen.append(a)
            books.add(a.book)
    return chosen


def select(meta: dict, transcripts_by_split: dict[str, dict[str, str]]) -> dict[str, list[dict]]:
    """Returns {split: [{archive, speaker, book, gender, utterances: [...]}, ...]}."""
    held_out_books = {uid.split("_")[1] for s in ("dev", "test") for uid in transcripts_by_split[s]}
    result: dict[str, list[dict]] = {}
    used_books: set[str] = set()
    for split, part, per_gender, minimum, per_speaker in PLAN:
        cands = archives(meta, transcripts_by_split[part])
        banned = set(used_books) if split != "train" else set(held_out_books)
        picked = _pick(cands, per_gender, minimum, banned, distinct_books=split != "train")
        used_books |= {a.book for a in picked}
        result[split] = [
            {"archive": a.key, "speaker": a.speaker, "book": a.book, "gender": a.gender, "utterances": list(a.utterances[:per_speaker])}
            for a in picked
        ]
    return result
