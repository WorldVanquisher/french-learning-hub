"""Build the frozen dataset: decoded 16 kHz mono PCM16 WAV files plus a sealed manifest.

Splits
  train, dev, test  MLS French subset (``mls.select``): speaker-disjoint (MLS),
                    book-disjoint (enforced), LibriVox-source-disjoint (checked)
  ood               FLEURS fr_fr dev: other speakers, another domain (Wikipedia
                    sentences), cased and punctuated references with digits.
                    FLEURS publishes no speaker ids; utterances are grouped by
                    sentence id for leakage checks and uncertainty.

Everything is computed from the pinned files, so a rerun produces the same
manifest bytes (``manifest_sha256``).
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import tarfile

from . import audio, fetch, mls, pins, textnorm

SCHEMA = "flh_speaking_dataset_manifest_v1"
MAX_SOURCE_SECONDS = 35.0
TINY_TRAIN = (8, 2)  # first N train archives, first K utterances each
TINY_EVAL = (4, 2)  # first N dev archives, first K utterances each (never test)
NGRAM = 8
FLEURS_FILES = ("data/fr_fr/dev.tsv", "data/fr_fr/audio/dev.tar.gz")


def _src(dest: str, source: dict, path: str) -> str:
    return fetch.local_path(dest, source, path)


def _read(dest, source, path) -> str:
    with open(_src(dest, source, path), encoding="utf-8") as fh:
        return fh.read()


def _members(tar_path: str, wanted: set[str], pattern: re.Pattern):
    """Yield (stem, bytes) for wanted regular-file members; refuses unsafe members."""
    with tarfile.open(tar_path, "r:gz") as tf:
        for m in tf:
            name = m.name
            if m.isdir():
                continue
            if not m.isfile() or name.startswith("/") or ".." in name.split("/"):
                raise ValueError(f"unsafe archive member in {os.path.basename(tar_path)}")
            base = name.rsplit("/", 1)[-1]
            if not pattern.fullmatch(base):
                raise ValueError(f"unexpected archive member {base!r}")
            stem = base.rsplit(".", 1)[0]
            if stem in wanted:
                if m.size > 20 << 20:
                    raise ValueError(f"oversized member {base}")
                yield stem, tf.extractfile(m).read()


def _write_audio(out_dir: str, split: str, uid: str, dec: audio.Decoded) -> tuple[str, str]:
    wav = audio.to_wav_pcm16(dec.samples)
    rel = f"audio/{split}/{uid}.wav"
    full = os.path.join(out_dir, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full + ".tmp", "wb") as fh:
        fh.write(wav)
    os.replace(full + ".tmp", full)
    return rel, hashlib.sha256(wav[44:]).hexdigest()  # PCM payload only (header is fixed)


def _row(uid, split, corpus, speaker, group, gender, text, source, rel, pcm_sha, dec) -> dict:
    q = audio.quality(dec.samples)
    return {
        "id": uid, "split": split, "corpus": corpus, "speaker": speaker, "group": group,
        "gender": gender, "text": text, "source": source, "file": rel, "pcm_sha256": pcm_sha,
        "seconds": q["seconds"], "source_rate": dec.source_rate, "source_channels": dec.source_channels,
        "source_codec": dec.source_codec, "quality": q,
    }


def prepare(sources: str, out_dir: str, log=print) -> dict:
    problems = fetch.check(sources, ["mls"]) + [
        f"google/fleurs/{p}: {bad}" for p in FLEURS_FILES
        if (bad := fetch.verify(_src(sources, pins.FLEURS, p), *pins.FLEURS["files"][p]))]
    if problems:
        raise ValueError("pinned sources do not verify: " + "; ".join(problems[:5]))
    meta = mls.parse_metainfo(_read(sources, pins.MLS, "data/mls_french/metainfo.txt"))
    tr = {s: mls.parse_transcripts(_read(sources, pins.MLS, f"data/mls_french/{s}/transcripts.txt")) for s in ("train", "dev", "test")}
    seg = {}
    for s in ("train", "dev", "test"):
        for line in _read(sources, pins.MLS, f"data/mls_french/{s}/segments.txt").splitlines():
            uid, url, *_ = line.split("\t")
            seg[uid] = url
    selection = mls.select(meta, tr)
    rows: list[dict] = []
    flac = re.compile(r"\d+_\d+_\d+\.flac")
    for split in ("train", "dev", "test"):
        for arch in selection[split]:
            path = f"data/mls_french/{split}/audio/{arch['archive']}_000.tar.gz"
            wanted = set(arch["utterances"])
            got = {}
            for stem, data in _members(_src(sources, pins.MLS, path), wanted, flac):
                got[stem] = audio.decode(data, max_seconds=MAX_SOURCE_SECONDS, allowed=audio.DATA_FAMILIES)
            if set(got) != wanted:
                raise ValueError(f"{arch['archive']}: {len(wanted - set(got))} selected utterances missing from the archive")
            for uid in arch["utterances"]:
                rel, sha = _write_audio(out_dir, split, uid, got[uid])
                rows.append(_row(uid, split, "mls_fr", arch["speaker"], f"book:{arch['book']}", arch["gender"],
                                 tr[split][uid], seg[uid], rel, sha, got[uid]))
            log(f"{split} {arch['archive']}: {len(wanted)} utterances")
    fl = [line.rstrip("\n").split("\t") for line in _read(sources, pins.FLEURS, "data/fr_fr/dev.tsv").splitlines() if line.strip()]
    if any(len(r) != 7 for r in fl):
        raise ValueError("FLEURS dev.tsv: expected 7 columns")
    by_file = {r[1].rsplit(".", 1)[0]: r for r in fl}
    got = dict(_members(_src(sources, pins.FLEURS, "data/fr_fr/audio/dev.tar.gz"), set(by_file), re.compile(r"\d+\.wav")))
    if set(got) != set(by_file):
        raise ValueError("FLEURS dev: archive and TSV disagree")
    for stem in sorted(by_file):
        r = by_file[stem]
        dec = audio.decode(got[stem], max_seconds=MAX_SOURCE_SECONDS, allowed=audio.DATA_FAMILIES)
        uid = f"fleurs_fr_dev_{stem}"
        rel, sha = _write_audio(out_dir, "ood", uid, dec)
        rows.append(_row(uid, "ood", "fleurs_fr_fr", None, f"sentence:{r[0]}", {"MALE": "M", "FEMALE": "F"}.get(r[6], "?"),
                         r[2], f"fleurs:fr_fr/dev/{r[1]}", rel, sha, dec))
    log(f"ood fleurs fr_fr dev: {len(by_file)} utterances")
    order = {"train": 0, "dev": 1, "test": 2, "ood": 3}
    rows.sort(key=lambda r: (order[r["split"]], r["id"]))
    checks = leakage(rows)
    tiny = {
        "train": [u for a in selection["train"][: TINY_TRAIN[0]] for u in a["utterances"][: TINY_TRAIN[1]]],
        "eval": [u for a in selection["dev"][: TINY_EVAL[0]] for u in a["utterances"][: TINY_EVAL[1]]],
    }
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    with open(os.path.join(out_dir, "manifest.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(body)
    manifest = {
        "schema": SCHEMA,
        "selection_rule": mls.SELECTION_RULE,
        "audio_convention": audio.CONVENTION,
        "text_normalization": textnorm.NORM_VERSION,
        "sources": {
            "mls": {k: pins.MLS[k] for k in ("repo", "revision", "license")},
            "fleurs": {k: pins.FLEURS[k] for k in ("repo", "revision", "license", "config")},
        },
        "attribution": "Multilingual LibriSpeech (Pratap et al., 2020; LibriVox recordings) and FLEURS (Conneau et al., 2022), both CC-BY-4.0. Audio is not redistributed in the repository.",
        "selection": {s: [{k: a[k] for k in ("archive", "speaker", "book", "gender")} for a in selection[s]] for s in ("train", "dev", "test")},
        "splits": split_stats(rows),
        "checks": checks,
        "tiny_fixture": tiny,
        "manifest_jsonl_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    with open(os.path.join(out_dir, "dataset_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    return manifest


def split_stats(rows):
    out = {}
    for split in ("train", "dev", "test", "ood"):
        rs = [r for r in rows if r["split"] == split]
        out[split] = {
            "utterances": len(rs),
            "hours": round(sum(r["seconds"] for r in rs) / 3600, 3),
            "speakers": len({r["speaker"] for r in rs if r["speaker"]}),
            "groups": len({r["group"] for r in rs}),
            "gender": dict(sorted(collections.Counter(r["gender"] for r in rs).items())),
            "seconds_min_max": [min(r["seconds"] for r in rs), max(r["seconds"] for r in rs)] if rs else None,
            "source_rates": sorted({r["source_rate"] for r in rs}),
            "source_channels": sorted({r["source_channels"] for r in rs}),
            "source_codecs": sorted({r["source_codec"] for r in rs}),
        }
    return out


def _ngrams(text: str, n: int) -> set:
    w = textnorm.words(text)
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def leakage(rows: list[dict]) -> dict:
    """Disjointness and duplicate checks. Hard failures raise; overlaps are reported."""
    by = collections.defaultdict(list)
    for r in rows:
        by[r["split"]].append(r)
    res: dict = {}

    def overlap(key, a, b):
        return sorted({r[key] for r in by[a] if r[key]} & {r[key] for r in by[b] if r[key]})

    for a, b in (("train", "dev"), ("train", "test"), ("dev", "test")):
        for key in ("speaker", "group", "source"):
            ov = overlap(key, a, b)
            res[f"{key}_overlap_{a}_{b}"] = len(ov)
            if ov:
                raise ValueError(f"leakage: {key} shared by {a} and {b}: {ov[:3]}")
    sha = collections.Counter(r["pcm_sha256"] for r in rows)
    dups = sorted(h for h, n in sha.items() if n > 1)
    res["duplicate_audio"] = len(dups)
    if dups:
        raise ValueError(f"duplicate audio in the dataset ({len(dups)} hashes)")
    norm = collections.defaultdict(set)
    for r in rows:
        norm[textnorm.normalize_fr(r["text"])].add(r["split"])
    res["same_text_across_splits"] = sum(1 for s in norm.values() if len(s) > 1)
    res["same_text_within_ood"] = sum(1 for r in by["ood"]) - len({textnorm.normalize_fr(r["text"]) for r in by["ood"]})
    train_ng = set().union(*(_ngrams(r["text"], NGRAM) for r in by["train"])) if by["train"] else set()
    for s in ("dev", "test", "ood"):
        hit = [r["id"] for r in by[s] if _ngrams(r["text"], NGRAM) & train_ng]
        res[f"{s}_utterances_sharing_an_{NGRAM}gram_with_train"] = len(hit)
        res[f"{s}_sharing_examples"] = hit[:5]
    res["ood_speaker_ids"] = "not published by FLEURS; grouped by sentence id"
    return res


NON_FRENCH = {"en_us": "data/en_us", "cmn_hans_cn": "data/cmn_hans_cn"}


def prepare_non_french(sources: str, out_dir: str, per_language: int = 10) -> dict:
    """Other-language speech for the not_french abstention probe: the first
    ``per_language`` FLEURS dev utterances (sorted by file name) of English and
    Mandarin, decoded with the same convention, as ``<lang>_<stem>.wav``."""
    os.makedirs(out_dir, exist_ok=True)
    out = {}
    for lang, base in NON_FRENCH.items():
        for p in (f"{base}/dev.tsv", f"{base}/audio/dev.tar.gz"):
            bad = fetch.verify(_src(sources, pins.FLEURS, p), *pins.FLEURS["files"][p])
            if bad:
                raise ValueError(f"google/fleurs/{p}: {bad}")
        rows = [line.split("\t") for line in _read(sources, pins.FLEURS, f"{base}/dev.tsv").splitlines() if line.strip()]
        stems = sorted(r[1].rsplit(".", 1)[0] for r in rows)[:per_language]
        got = dict(_members(_src(sources, pins.FLEURS, f"{base}/audio/dev.tar.gz"), set(stems), re.compile(r"\d+\.wav")))
        for stem in stems:
            dec = audio.decode(got[stem], max_seconds=MAX_SOURCE_SECONDS, allowed=audio.DATA_FAMILIES)
            wav = audio.to_wav_pcm16(dec.samples)
            with open(os.path.join(out_dir, f"{lang}_{stem}.wav"), "wb") as fh:
                fh.write(wav)
            out[f"{lang}_{stem}"] = hashlib.sha256(wav[44:]).hexdigest()
    with open(os.path.join(out_dir, "non_french_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"source": "google/fleurs@" + pins.FLEURS["revision"], "files": out}, fh, indent=1, sort_keys=True)
    return out


def prepare_accent(sources: str, out_dir: str) -> dict:
    """SLR57 (African Accented French) test split, CA16 part: 12 speakers from
    Cameroon, Chad, Congo and Gabon reading short role-play prompts. Transcripts
    are verbatim, including the speakers' own deviations from standard French.
    Every transcribed recording is used; speaker = folder name."""
    path = "African_Accented_French.tar.gz"
    bad = fetch.verify(_src(sources, pins.SLR57, path), *pins.SLR57["files"][path])
    if bad:
        raise ValueError(f"openslr/57/{path}: {bad}")
    texts, wavs = {}, {}
    with tarfile.open(_src(sources, pins.SLR57, path), "r:gz") as tf:
        for m in tf:
            n = m.name
            if not m.isfile():
                continue
            if n.startswith("/") or ".." in n.split("/"):
                raise ValueError("unsafe archive member")
            if n == "African_Accented_French/transcripts/test/ca16/prompts.txt":
                for line in tf.extractfile(m).read().decode("utf-8").splitlines():
                    uid, _, text = line.strip().partition(" ")
                    if uid and text.strip():
                        texts[uid] = text.strip()
            elif n.startswith("African_Accented_French/speech/test/ca16/") and n.endswith(".wav"):
                wavs[n.rsplit("/", 1)[-1][:-4]] = tf.extractfile(m).read()
    rows = []
    for uid in sorted(set(texts) & set(wavs)):
        dec = audio.decode(wavs[uid], max_seconds=MAX_SOURCE_SECONDS, allowed=audio.DATA_FAMILIES)
        rel, sha = _write_audio(out_dir, "accent", uid, dec)
        spk = uid.rsplit("_", 1)[0]
        gender = "F" if "_f_" in uid else "M" if "_m_" in uid else "?"
        rows.append(_row(uid, "accent", "slr57_ca16", spk, f"speaker:{spk}", gender, texts[uid], f"slr57:test/ca16/{uid}", rel, sha, dec))
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    with open(os.path.join(out_dir, "manifest.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(body)
    man = {"schema": SCHEMA, "audio_convention": audio.CONVENTION, "text_normalization": textnorm.NORM_VERSION,
           "sources": {"slr57": {k: pins.SLR57[k] for k in ("repo", "revision", "license", "pinning")}},
           "attribution": "African Accented French (OpenSLR SLR57), Apache-2.0. Audio is not redistributed in the repository.",
           "splits": {"accent": {"utterances": len(rows), "hours": round(sum(r["seconds"] for r in rows) / 3600, 3),
                                 "speakers": len({r["speaker"] for r in rows}),
                                 "transcripts_without_audio": len(set(texts) - set(wavs)), "audio_without_transcript": len(set(wavs) - set(texts)),
                                 "source_rates": sorted({r["source_rate"] for r in rows}), "source_channels": sorted({r["source_channels"] for r in rows})}},
           "manifest_jsonl_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}
    with open(os.path.join(out_dir, "dataset_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    return man


PUNCT_RULE = "flh_fleurs_fr_punctuated_train_v1"


def prepare_punctuated(sources: str, base_data: str, out_dir: str, n: int = 1440, n_dev: int = 100, max_seconds: float = 20.0, log=print) -> dict:
    """Training data for the punctuated-target experiment (v2).

    ``train``: ``n`` FLEURS French train utterances with their raw transcription
    (case and punctuation kept), at most ``max_seconds`` long (seed 20261118). A sentence is excluded when its id is a FLEURS dev
    sentence (the frozen ``ood`` holdout) or its normalized text equals any
    held-out reference (MLS dev/test, FLEURS dev). FLEURS publishes no speaker
    ids, so speaker overlap with FLEURS dev cannot be excluded: that set is
    near-domain for this experiment, which is why SLR57 is evaluated as well.
    Sentences are drawn one recording each; a second reader of a sentence is
    used only once every train sentence has one (FLEURS has about 1,500
    sentences).
    ``dev``: ``n_dev`` further FLEURS train sentences (punctuated too), for the
    logged dev loss only (the candidate is the final step, as in the pilot).
    """
    import random

    for p in pins.FLEURS_FR_TRAIN["files"]:
        bad = fetch.verify(_src(sources, pins.FLEURS_FR_TRAIN, p), *pins.FLEURS_FR_TRAIN["files"][p])
        if bad:
            raise ValueError(f"google/fleurs/{p}: {bad}")
    with open(os.path.join(base_data, "manifest.jsonl"), encoding="utf-8") as fh:
        base_rows = [json.loads(line) for line in fh]
    held = [r for r in base_rows if r["split"] in ("dev", "test", "ood")]
    held_norm = {textnorm.normalize_fr(r["text"]) for r in held}
    held_sentences = {r["group"].split(":", 1)[1] for r in held if r["corpus"] == "fleurs_fr_fr"}
    tsv = [line.split("\t") for line in _read(sources, pins.FLEURS_FR_TRAIN, "data/fr_fr/train.tsv").splitlines() if line.strip()]
    excluded = {"dev_sentence": 0, "held_out_text": 0, "too_long": 0}
    by_sentence: dict[str, list[list[str]]] = {}
    for r in tsv:
        if r[0] in held_sentences:
            excluded["dev_sentence"] += 1
        elif textnorm.normalize_fr(r[2]) in held_norm:
            excluded["held_out_text"] += 1
        elif int(r[5]) / audio.SAMPLE_RATE > max_seconds:
            excluded["too_long"] += 1
        else:
            by_sentence.setdefault(r[0], []).append(r)
    rng = random.Random(20261118)
    sentences = sorted(by_sentence)
    rng.shuffle(sentences)
    # dev: the first n_dev sentences, one recording each. train: the other
    # sentences, one recording each first, then further recordings (other
    # readers of the same sentence) round-robin until n. Sentence-disjoint.
    pools = {sent: sorted(by_sentence[sent], key=lambda r: r[1]) for sent in sentences}
    for sent in sentences:
        rng.shuffle(pools[sent])
    dev_sents, train_sents = sentences[:n_dev], sentences[n_dev:]
    if len(dev_sents) < n_dev or sum(len(pools[sent]) for sent in train_sents) < n:
        raise ValueError(f"not enough eligible recordings for n={n} + n_dev={n_dev} ({len(sentences)} sentences)")
    want = {pools[sent][0][1].rsplit(".", 1)[0]: ("dev", pools[sent][0]) for sent in dev_sents}
    taken, depth = 0, 0
    while taken < n:
        for sent in train_sents:
            if depth < len(pools[sent]) and taken < n:
                r = pools[sent][depth]
                want[r[1].rsplit(".", 1)[0]] = ("train", r)
                taken += 1
        depth += 1
    rows = []
    # Decoded and written as the archive streams by: one clip in memory at a time.
    for stem, blob in _members(_src(sources, pins.FLEURS_FR_TRAIN, "data/fr_fr/audio/train.tar.gz"), set(want), re.compile(r"\d+\.wav")):
        split, r = want.pop(stem, (None, None))
        if r is None:  # a file name listed twice in the archive
            continue
        dec = audio.decode(blob, max_seconds=MAX_SOURCE_SECONDS, allowed=audio.DATA_FAMILIES)
        uid = f"fleurs_fr_train_{stem}"
        rel, sha = _write_audio(out_dir, split, uid, dec)
        rows.append(_row(uid, split, "fleurs_fr_fr", None, f"sentence:{r[0]}", {"MALE": "M", "FEMALE": "F"}.get(r[6].strip(), "?"),
                         r[2].strip(), f"fleurs:fr_fr/train/{r[1]}", rel, sha, dec))
    if want:
        raise ValueError(f"{len(want)} selected files are missing from the archive")
    rows.sort(key=lambda r: (r["split"] != "train", r["id"]))
    log(f"fleurs fr_fr (punctuated): {len(rows)} utterances, excluded {excluded}")
    leak = sorted({textnorm.normalize_fr(r["text"]) for r in rows} & held_norm)
    if leak:
        raise ValueError(f"held-out text in training: {leak[:3]}")
    train = [r for r in rows if r["split"] == "train"]
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    with open(os.path.join(out_dir, "manifest.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(body)
    with open(os.path.join(base_data, "manifest.jsonl"), "rb") as fh:
        held_sha = hashlib.sha256(fh.read()).hexdigest()
    man = {"schema": SCHEMA, "selection_rule": PUNCT_RULE, "audio_convention": audio.CONVENTION, "text_normalization": textnorm.NORM_VERSION,
           "sources": {"fleurs_fr_train": {k: pins.FLEURS_FR_TRAIN[k] for k in ("repo", "revision", "license", "config")},
                       "held_out_from": {"manifest_jsonl_sha256": held_sha}},
           "attribution": "FLEURS (google/fleurs), CC BY 4.0. Audio is not redistributed in the repository.",
           "excluded": excluded, "leakage": {"held_out_normalized_text_in_train": 0, "fleurs_dev_sentences_in_train": 0,
                                             "speaker_overlap_with_fleurs_dev": "unknown (FLEURS publishes no speaker ids)"},
           "splits": {"train": {"utterances": len(train), "hours": round(sum(r["seconds"] for r in train) / 3600, 3),
                                "sentences": len({r["group"] for r in train}),
                                "with_second_reader": len(train) - len({r["group"] for r in train}),
                                "with_punctuation": round(sum(1 for r in train if re.search(r"[.,;:!?]", r["text"])) / len(train), 4),
                                "with_uppercase": round(sum(1 for r in train if any(ch.isupper() for ch in r["text"])) / len(train), 4)},
                      "dev": {"utterances": sum(1 for r in rows if r["split"] == "dev"), "sentences_shared_with_train": len({r["group"] for r in rows if r["split"] == "dev"} & {r["group"] for r in train})}},
           "manifest_jsonl_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}
    with open(os.path.join(out_dir, "dataset_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    return man
