"""Role adapter contract flh_e5_role_prefix_v1 (FLH-054).

Every input string must be exactly one of three known JSON representations.
Its role comes only from the declared representation/type pair, never from
the input's position in the batch or from guessing at raw text:

  concept_search_query_v2 / query    -> "query: "    (Go semantic search)
  concept_embedding_text_v1 / query  -> "query: "    (Unit query, retriever)
  concept_embedding_text_v1 / concept -> "passage: " (Concept document)

The model text is the ASCII prefix followed by the original input string,
unchanged (no re-serialization, no trimming), so the prefix is applied once.
Anything else is rejected. Standard library only; this file defines vectors
and is part of the deployment's code hash.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

CONVENTION = "flh_e5_role_prefix_v1"

QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
PREFIXES = {"query": QUERY_PREFIX, "passage": PASSAGE_PREFIX}

SEARCH_QUERY_V2 = "concept_search_query_v2"
CONCEPT_TEXT_V1 = "concept_embedding_text_v1"

# (representation, type) -> (exact key set, role)
_SCHEMAS: dict[tuple[str, str], tuple[frozenset[str], str]] = {
    (SEARCH_QUERY_V2, "query"): (frozenset({"representation", "type", "text"}), "query"),
    (CONCEPT_TEXT_V1, "query"): (
        frozenset({"representation", "type", "canonical", "statement", "example", "candidate_target",
                   "pedagogical_intent", "scope", "identity_features"}),
        "query",
    ),
    (CONCEPT_TEXT_V1, "concept"): (
        frozenset({"representation", "type", "target", "pedagogical_intent", "scope", "identity_features"}),
        "passage",
    ),
}

ACCEPTED_PAIRS = sorted(f"{r}/{t}->{role}" for (r, t), (_, role) in _SCHEMAS.items())


class InputRejected(ValueError):
    """An input that is not a recognized representation. The message never
    contains the input text."""


@dataclass(frozen=True)
class AdaptedInput:
    role: str          # "query" or "passage"
    representation: str
    model_text: str    # prefix + original input


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise InputRejected("duplicate JSON key")
        out[key] = value
    return out


def _reject_constant(name):
    raise InputRejected("non-standard JSON constant")


def _is_str(value) -> bool:
    return isinstance(value, str)


def _check_features(value) -> None:
    if not isinstance(value, list):
        raise InputRejected("identity_features must be a list")
    for item in value:
        if not isinstance(item, dict) or set(item) != {"key", "value"} or not _is_str(item["key"]) or not _is_str(item["value"]):
            raise InputRejected("identity_features items must be {key, value} strings")


def adapt(text: str) -> AdaptedInput:
    """Validate one input and return its role and model text, or raise
    InputRejected."""
    if not isinstance(text, str):
        raise InputRejected("input must be a string")
    if not text.startswith("{") or not text.endswith("}"):
        raise InputRejected("input must be a JSON object with no surrounding whitespace")
    try:
        value = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
    except InputRejected:
        raise
    except (ValueError, RecursionError):
        raise InputRejected("input is not valid JSON") from None
    if not isinstance(value, dict):
        raise InputRejected("input must be a JSON object")
    pair = (value.get("representation"), value.get("type"))
    if not all(_is_str(p) for p in pair) or pair not in _SCHEMAS:
        raise InputRejected("unrecognized representation/type")
    keys, role = _SCHEMAS[pair]
    if set(value) != keys:
        raise InputRejected("keys do not match the representation")
    if pair[0] == SEARCH_QUERY_V2:
        if not _is_str(value["text"]) or value["text"] == "":
            raise InputRejected("search query text must be a non-empty string")
    else:
        for key in keys - {"identity_features", "example"}:
            if not _is_str(value[key]):
                raise InputRejected(f"{key} must be a string")
        if "example" in keys and value["example"] is not None and not _is_str(value["example"]):
            raise InputRejected("example must be a string or null")
        _check_features(value["identity_features"])
    return AdaptedInput(role=role, representation=pair[0], model_text=PREFIXES[role] + text)
