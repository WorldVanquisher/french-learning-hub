"""Injected fake encoder for service tests. It is NOT a model: vectors are a
deterministic hash of the exact model text, so tests can check prefixes,
ordering and indexing. Fake results say nothing about CUDA or quality."""

from __future__ import annotations

import hashlib
import math
import threading

from flh_e5.encoder import EncoderOutOfMemory

DIMS = 768


def fake_vector(text: str) -> list[float]:
    out, seed = [], hashlib.sha256(text.encode("utf-8")).digest()
    while len(out) < DIMS:
        seed = hashlib.sha256(seed).digest()
        out.extend((b - 127.5) / 127.5 for b in seed)
    out = out[:DIMS]
    norm = math.sqrt(sum(x * x for x in out))
    return [x / norm for x in out]


class FakeEncoder:
    dimensions = DIMS

    def __init__(self, tokens=None, fail=None, gate: threading.Event | None = None):
        self.tokens = tokens or (lambda t: len(t.split()) + 2)
        self.fail = fail          # None, "oom", "error", "nan", "unnormalized", "short", "count"
        self.gate = gate          # encode() waits on it when set
        self.entered = threading.Event()
        self.batches: list[list[str]] = []
        self.closed = False
        self.files = {"fake": {"size": 0, "sha256": "0" * 64}}

    def count_tokens(self, texts):
        return [self.tokens(t) for t in texts]

    def encode(self, texts):
        self.batches.append(list(texts))
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(10)
        if self.fail == "oom":
            raise EncoderOutOfMemory()
        if self.fail == "error":
            raise RuntimeError("encoder exploded")
        vectors = [fake_vector(t) for t in texts]
        if self.fail == "nan":
            vectors[0][0] = float("nan")
        elif self.fail == "unnormalized":
            vectors[0] = [x * 2 for x in vectors[0]]
        elif self.fail == "short":
            vectors[0] = vectors[0][:767]
        elif self.fail == "count":
            vectors = vectors[:-1]
        return vectors

    def gpu_evidence(self):
        return {"device": "fake (not a GPU)", "memory_allocated_bytes": 0}

    def runtime_versions(self):
        return {"fake": "not a model"}

    def close(self):
        self.closed = True
