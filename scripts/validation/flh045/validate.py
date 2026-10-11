#!/usr/bin/env python3
"""Validate FLH-045 proposals offline; never produce annotation authority."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

SCHEMA = "flh045_retrieval_preparation_v1"
STATUS = "author_proposed_synthetic_awaiting_human_review"
KINDS = {"vocabulary", "grammar", "morphology", "orthography", "pronunciation", "usage", "expression"}
BUCKETS = {"single_target", "ambiguous", "no_match"}
SPLITS = {"development", "held_out"}
TAGS = {"paraphrase", "close_distinction", "lexical_overlap_trap", "ambiguous", "no_match"}
# Keys here may exist in judgments/metadata, but never in model input objects.
PROHIBITED = {
    "id", "concept_id", "unit_id", "signature", "lifecycle", "support", "state",
    "label", "labels", "relevance", "reason", "rationale", "target_concept_id",
    "expected_concept_id", "human_same", "human_labels", "group_id", "split",
    "rank", "score", "hit", "metrics", "target_rank", "candidate_identity",
    "proposed_relevant_concept_ids", "possible_concept_ids", "review_status",
}


class ValidationError(ValueError):
    """A fixture invariant failed."""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def keys(obj, allowed, where):
    require(isinstance(obj, dict), f"{where}: expected object")
    require(set(obj) == set(allowed), f"{where}: unexpected or missing fields: {sorted(set(obj) ^ set(allowed))}")


def string(value, where):
    require(isinstance(value, str) and bool(value.strip()), f"{where}: expected nonempty string")


def array(value, where):
    require(isinstance(value, list), f"{where}: expected array")


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def unique(values, where):
    require(len(set(values)) == len(values), f"{where}: duplicate")


def records(values, prefix, digits, fields, where):
    array(values, where)
    result = {}
    for obj in values:
        keys(obj, fields, where)
        rid = obj["id"]
        require(isinstance(rid, str) and re.fullmatch(prefix + rf"\d{{{digits}}}", rid), f"{where}: invalid stable id")
        require(rid not in result, f"{where}: duplicate id {rid}")
        result[rid] = obj
    return result


def input_safety(value, where):
    if isinstance(value, dict):
        for key, item in value.items():
            require(key not in PROHIBITED, f"{where}: prohibited leakage field {key}")
            input_safety(item, where)
    elif isinstance(value, str):
        require(not re.search(r"\b(?:C\d{3}|Q\d{3}|J\d{3}|F\d{2})\b", value), f"{where}: fixture id in input")
        require(not re.search(r'["\'](?:' + "|".join(sorted(PROHIBITED | {"identity_features", "pedagogical_intent"})) + r')["\']\s*:', value), f"{where}: serialized metadata or identity in input")


def digest(value):
    """Canonical JSON hash, distinct from file-byte and Go-rendered-input hashes."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate(data):
    keys(data, {"schema_version", "label_status", "groups", "concepts", "queries", "judgments"}, "fixture")
    require(data["schema_version"] == SCHEMA, "fixture: unknown schema")
    require(data["label_status"] == STATUS, "fixture: labels must remain proposed")
    groups = records(data["groups"], "F", 2, {"id", "name", "split", "rationale"}, "groups")
    concepts = records(data["concepts"], "C", 3, {"id", "group_id", "identity"}, "concepts")
    queries = records(data["queries"], "Q", 3, {"id", "group_id", "split", "language", "bucket", "tags", "unit_evidence", "free_text"}, "queries")
    judgments = records(data["judgments"], "J", 3, {"id", "query_id", "review_status", "proposed_relevant_concept_ids", "possible_concept_ids", "rationale", "hard_negatives"}, "judgments")
    require(len(concepts) >= 20 and len(queries) >= 40, "fixture: require >=20 concepts and >=40 queries")
    for group in groups.values():
        string(group["name"], "group name")
        string(group["rationale"], "group rationale")
        require(group["split"] in SPLITS, "group: invalid split")
    unique([normalized(g["name"]) for g in groups.values()], "group names")
    require({g["split"] for g in groups.values()} == SPLITS, "fixture: reserve development and held-out groups")
    for c in concepts.values():
        require(c["group_id"] in groups, "concept: unknown group")
        identity = c["identity"]
        input_safety(identity, "concept identity")
        keys(identity, {"target", "pedagogical_intent", "scope", "identity_features"}, "identity")
        for field in ("target", "pedagogical_intent", "scope"):
            string(identity[field], f"identity {field}")
            require(len(identity[field]) <= 200, "identity: field too long")
        features = identity["identity_features"]
        require(isinstance(features, dict) and len(features) <= 32, "identity: invalid features")
        for key, value in features.items():
            string(key, "feature key")
            string(value, "feature value")
            require(len(key) <= 80 and len(value) <= 200, "identity: feature too long")
    unique([digest({k: normalized(v) if isinstance(v, str) else {fk: normalized(fv) for fk, fv in v.items()} for k, v in c["identity"].items()}) for c in concepts.values()], "concept identities")
    for q in queries.values():
        require(q["group_id"] in groups, "query: unknown group")
        require(q["split"] == groups[q["group_id"]]["split"], "query: paraphrase group split mismatch")
        require(q["language"] in {"fr", "en"}, "query: invalid language")
        require(q["bucket"] in BUCKETS, "query: invalid bucket")
        array(q["tags"], "query tags")
        require(all(isinstance(tag, str) and tag in TAGS for tag in q["tags"]), "query: invalid tag")
        unique(q["tags"], "query tags")
        require(bool(q["tags"]), "query: missing tags")
        if q["bucket"] != "single_target":
            require(q["bucket"] in q["tags"], "query: bucket tag missing")
        evidence = q["unit_evidence"]
        input_safety(evidence, "unit input")
        input_safety(q["free_text"], "free-text input")
        keys(evidence, {"kind", "canonical", "statement", "example"}, "unit evidence")
        require(evidence["kind"] in KINDS, "unit evidence: invalid kind")
        for field, limit in (("canonical", 200), ("statement", 2000)):
            string(evidence[field], field)
            require(len(evidence[field]) <= limit, f"unit evidence: {field} too long")
        require(evidence["example"] is None or isinstance(evidence["example"], str), "example: expected string or null")
        if evidence["example"] is not None:
            string(evidence["example"], "example")
            require(len(evidence["example"]) <= 2000, "example: too long")
        string(q["free_text"], "free text")
        # Detect full visible identity copying, not conceptual/semantic leakage.
        text = normalized(" ".join([evidence["canonical"], evidence["statement"], evidence["example"] or "", q["free_text"]]))
        for concept in concepts.values():
            identity = concept["identity"]
            clues = [identity["target"], identity["scope"], *identity["identity_features"].values()]
            require(not all(normalized(clue) in text for clue in clues), "query: full visible concept identity copied")
    unique([normalized(q["free_text"]) for q in queries.values()], "free-text queries")
    unique([digest({k: normalized(v) if isinstance(v, str) else v for k, v in q["unit_evidence"].items()}) for q in queries.values()], "unit queries")
    require({q["bucket"] for q in queries.values()} == BUCKETS, "fixture: missing coverage bucket")
    require({q["language"] for q in queries.values()} == {"fr", "en"}, "fixture: need French and English")
    require({tag for q in queries.values() for tag in q["tags"]} >= {"paraphrase", "close_distinction", "lexical_overlap_trap"}, "fixture: missing contrast coverage")
    unique([j["query_id"] for j in judgments.values()], "judgment query references")
    require({j["query_id"] for j in judgments.values()} == set(queries), "judgments: require exactly one per query")
    for j in judgments.values():
        q = queries[j["query_id"]]
        require(j["id"] == "J" + q["id"][1:], "judgment: stable id mismatch")
        require(j["review_status"] == "awaiting_human_review", "judgment: review not yet authorized")
        string(j["rationale"], "judgment rationale")
        for field in ("proposed_relevant_concept_ids", "possible_concept_ids"):
            array(j[field], field)
            require(all(isinstance(x, str) and x in concepts for x in j[field]), f"judgment: unknown concept in {field}")
            unique(j[field], field)
        relevant, possible = j["proposed_relevant_concept_ids"], j["possible_concept_ids"]
        require(not set(relevant) & set(possible), "judgment: relevant/possible overlap")
        if q["bucket"] == "single_target":
            require(len(relevant) == 1 and not possible, "single target: exactly one proposed relevant concept")
        elif q["bucket"] == "ambiguous":
            require(not relevant and len(possible) >= 2, "ambiguous: possible alternatives only")
        else:
            require(not relevant and not possible, "no match: no relevant or possible concepts")
        array(j["hard_negatives"], "hard negatives")
        negative_ids = []
        for negative in j["hard_negatives"]:
            keys(negative, {"concept_id", "rationale"}, "hard negative")
            require(negative["concept_id"] in concepts, "hard negative: unknown concept")
            string(negative["rationale"], "hard negative rationale")
            negative_ids.append(negative["concept_id"])
        unique(negative_ids, "hard negatives")
        require(not (set(relevant) | set(possible)) & set(negative_ids), "judgment: contradictory negative")
        if q["bucket"] == "single_target":
            require(bool(negative_ids), "single target: require a contrast negative")
        for cid in relevant + possible + negative_ids:
            require(concepts[cid]["group_id"] == q["group_id"], "judgment: cross-family reference would leak a split")
    for gid in groups:
        family_queries = [q for q in queries.values() if q["group_id"] == gid]
        require(bool(family_queries), "group: no query cases")
        require({q["language"] for q in family_queries} == {"fr", "en"}, "group: missing bilingual paraphrases")
    for cid, concept in concepts.items():
        positive = [queries[j["query_id"]] for j in judgments.values() if cid in j["proposed_relevant_concept_ids"]]
        require({q["language"] for q in positive} == {"fr", "en"}, "concept: need French and English proposed positives")
    return {
        "schema_version": SCHEMA, "label_status": STATUS,
        "counts": {"groups": len(groups), "concepts": len(concepts), "queries": len(queries), "judgments": len(judgments)},
        "buckets": dict(sorted(Counter(q["bucket"] for q in queries.values()).items())),
        "splits": {split: dict(sorted(Counter(q["bucket"] for q in queries.values() if q["split"] == split).items())) for split in sorted(SPLITS)},
        "canonical_sha256": {section: digest(data[section]) for section in ("groups", "concepts", "queries", "judgments")},
    }


def reject_pairs(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, f"JSON: duplicate object key {key}")
        obj[key] = value
    return obj


def reject_constant(value):
    raise ValidationError(f"JSON: non-finite constant {value}")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=reject_pairs, parse_constant=reject_constant)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", nargs="?", type=Path, default=Path(__file__).with_name("fixture.json"))
    args = parser.parse_args()
    try:
        report = validate(load(args.fixture))
        report["fixture_file_sha256"] = hashlib.sha256(args.fixture.read_bytes()).hexdigest()
    except (ValidationError, OSError, ValueError, TypeError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
