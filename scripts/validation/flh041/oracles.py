"""Independent assertions over supplied observations, not index/search behavior.

A Phase B adapter must read real SQLite/Qdrant/provider state and normalize it
here. These helpers never construct production documents, choose collections,
cache embeddings, publish points, filter hits, or decide a run's state.
"""
from collections import Counter
from dataclasses import dataclass
import math


def require(condition, message):
    if not condition:
        raise AssertionError(message)


@dataclass(frozen=True)
class CacheKey:
    content_hash: str
    representation: str
    model_id: str
    dimensions: int

    def __post_init__(self):
        if not all(isinstance(value, str) and value for value in
                   (self.content_hash, self.representation, self.model_id)):
            raise ValueError("nonempty observed cache identity fields required")
        if not isinstance(self.dimensions, int) or isinstance(self.dimensions, bool) or self.dimensions < 1:
            raise ValueError("positive integer dimensions required")


def assert_cache(actual, expected):
    """Mappings of observed keys -> vectors; expected is an explicit test manifest."""
    require(set(actual) == set(expected), "cache key inventory differs")
    for key, vector in actual.items():
        require(len(vector) == key.dimensions, "cached vector dimensions differ")
        require(all(math.isfinite(value) for value in vector), "cached vector is nonfinite")
        require(any(value != 0 for value in vector), "cached vector is zero")
        target = expected[key]
        require(len(target) == key.dimensions, "expected vector dimensions differ")
        require(all(math.isclose(value, want, rel_tol=0, abs_tol=1e-6)
                    for value, want in zip(vector, target)), "cached vector bytes/value attribution differs")


def assert_index(actual, expected):
    """Compare real normalized point inventory, including vector and payload evidence.

    Caller supplies the expected manifest; this helper neither computes content
    hashes nor infers eligibility from link history. Read ALL owned points, not
    just a search result or Qdrant's point count.
    """
    require(actual == expected, "vector record inventory/content differs")


def assert_result_ids(actual, expected):
    require(len(actual) == len(set(actual)), "duplicate returned Concept ID")
    require(actual == expected, "returned IDs/order differ from explicit SQLite-authority expectation")


def assert_not_complete(observed_state, complete_state="complete"):
    require(observed_state != complete_state, "failed/stale/superseded run falsely complete")


def _event_identity(event):
    return tuple(event[key] if not isinstance(event[key], list) else tuple(event[key])
                 for key in ("call", "model", "input_sha256", "roles", "batch_size"))


def assert_embedding_delta(before, after, expected_documents=(), expected_queries=()):
    """Expected input SHA-256 multisets, counting attempts including failed batches."""
    old, new = before["events"], after["events"]
    require(len(new) >= len(old), "provider ledger reset/truncated")
    require([_event_identity(e) for e in new[:len(old)]] == [_event_identity(e) for e in old],
            "provider request identity history changed")
    require(after["active"] == 0, "provider still has in-flight requests")
    documents, queries = [], []
    for event in new[len(old):]:
        require(len(event["input_sha256"]) == len(event["roles"]) == event["batch_size"],
                "provider event attribution/count mismatch")
        for digest, role in zip(event["input_sha256"], event["roles"]):
            require(role in ("document", "query"), "unclassified embedding input")
            (documents if role == "document" else queries).append(digest)
    require(Counter(documents) == Counter(expected_documents), "document embedding attempts differ")
    require(Counter(queries) == Counter(expected_queries), "query embedding attempts differ")


def assert_bounded_provider(snapshot, max_batch, max_concurrency=1):
    require(snapshot["active"] == 0, "provider has in-flight requests")
    require(snapshot["max_active"] <= max_concurrency, "embedding concurrency exceeds bound")
    for event in snapshot["events"]:
        require(0 < event["batch_size"] <= max_batch, "embedding batch exceeds bound")


def assert_read_only(sqlite_before, sqlite_after, vectors_before, vectors_after,
                     provider_before, provider_after, expected_queries=()):
    require(sqlite_before == sqlite_after, "search changed SQLite snapshot")
    require(vectors_before == vectors_after, "search changed vector records")
    assert_embedding_delta(provider_before, provider_after, expected_queries=expected_queries)
