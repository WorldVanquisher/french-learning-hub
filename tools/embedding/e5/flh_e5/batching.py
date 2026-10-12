"""Explicit tensor-shape (batching/padding) policies (FLH-059).

FLH-058 observed that the same document text, encoded in float16 in different
mixed microbatches, gave vectors differing by up to 3.0e-4 per coordinate. The
legacy encoder pads each microbatch to its longest input, so a text's tensor
shape depends on its companions. Whether that causes the drift is NOT
established; scripts/validation/flh059 measures it on the real GPU.

Policies (the service's microbatch splitting happens before these):

  dynamic_v1    legacy FLH-054 behaviour: one forward pass per microbatch,
                right-padded to the longest input in it. A text's shape
                depends on its companions. Served with the unchanged v1
                manifest, so the existing deployment identity is preserved.
  singleton_v1  one forward pass per input, no padding: shape (1, own length).
                A text's shape depends only on the text itself.
  fixed_v1      one forward pass per microbatch, always shape
                (microbatch rows, 512): unused rows hold "<s></s>" and are
                discarded; every row is right-padded to 512 tokens.

No policy promises bitwise determinism; that is a measured property. Any
policy other than dynamic_v1 uses manifest schema v2, which records the policy
and the attention/matmul settings and hashes this file, so it always gets a
new deployment identity. This file defines vectors.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Sequence

from . import manifest

POLICIES = ("dynamic_v1", "singleton_v1", "fixed_v1")
LEGACY_POLICY = "dynamic_v1"
FIXED_WIDTH = manifest.MAX_TOKENS

MANIFEST_SCHEMA_V2 = "flh_e5_deployment_manifest_v2"
VECTOR_CODE_FILES_V2 = manifest.VECTOR_CODE_FILES + ("batching.py",)

DESCRIPTIONS = {
    "dynamic_v1": "one forward pass per service microbatch, right-padded to the longest input in it (shape depends on companions)",
    "singleton_v1": "one forward pass per input with no padding: shape (1, own token count)",
    "fixed_v1": f"one forward pass per service microbatch with shape (microbatch, {FIXED_WIDTH}); filler rows are <s></s> and discarded; every row right-padded to {FIXED_WIDTH}",
}

Vectors = list[list[float]]


def check_policy(policy: str) -> str:
    if policy not in POLICIES:
        raise ValueError(f"batching policy must be one of {POLICIES}")
    return policy


def apply_policy(policy: str, texts: Sequence[str], *, rows: int,
                 encode_dynamic: Callable[[Sequence[str]], Vectors],
                 encode_fixed: Callable[[Sequence[str], int, int], Vectors]) -> Vectors:
    """Encode one service microbatch under `policy`. `encode_dynamic` is the
    legacy padded forward pass; `encode_fixed(texts, rows, width)` runs one
    pass of exactly that shape."""
    check_policy(policy)
    texts = list(texts)
    if not texts:
        return []
    if policy == "dynamic_v1":
        return encode_dynamic(texts)
    if policy == "singleton_v1":
        out: Vectors = []
        for text in texts:
            out.extend(encode_dynamic([text]))  # a batch of one has no padding
        return out
    if len(texts) > rows:
        raise ValueError("fixed_v1: more inputs than the fixed row count")
    return encode_fixed(texts, rows, FIXED_WIDTH)


def code_sha256_v2(package_dir: Path) -> str:
    h = hashlib.sha256()
    for name in VECTOR_CODE_FILES_V2:
        data = (package_dir / name).read_bytes().replace(b"\r\n", b"\n")
        h.update(name.encode() + b"\0" + str(len(data)).encode() + b"\0" + data)
    return h.hexdigest()


def build_manifest_v2(*, files: dict, code_hash: str, convention: str, accepted_pairs: list[str],
                      prefixes: dict[str, str], dtype: str, microbatch: int, policy: str,
                      numerics: dict, runtime: dict, service: dict) -> dict:
    """Manifest for a non-legacy policy. Like v1, plus an explicit batching
    section and the observed numerics settings; all of it is hashed."""
    check_policy(policy)
    if policy == LEGACY_POLICY:
        raise ValueError("dynamic_v1 keeps the v1 manifest and its identity")
    v1 = manifest.build_manifest(files=files, code_hash=code_hash, convention=convention,
                                 accepted_pairs=accepted_pairs, prefixes=prefixes, dtype=dtype,
                                 microbatch=microbatch, runtime=runtime, service=service)
    vd = v1["vector_defining"]
    vd["schema"] = MANIFEST_SCHEMA_V2
    vd["adapter"]["code_files"] = list(VECTOR_CODE_FILES_V2)
    vd["inference"]["batching"] = {
        "policy": policy, "description": DESCRIPTIONS[policy], "service_microbatch": microbatch,
        "padding_side": "right", "fixed_width": FIXED_WIDTH if policy == "fixed_v1" else None,
        "rows_per_forward": 1 if policy == "singleton_v1" else microbatch,
    }
    vd["inference"]["numerics"] = numerics
    digest = hashlib.sha256(manifest.canonical(vd)).hexdigest()
    return {"deployment_id": deployment_identity_v2(dtype, policy, digest), "manifest_sha256": digest,
            "vector_defining": vd, "service": service}


def deployment_identity_v2(dtype: str, policy: str, manifest_sha256: str) -> str:
    identity = f"{manifest.DEPLOYMENT_NAME}@{manifest.REVISION}/flh_e5_role_prefix_v1/{dtype}/{policy}/{manifest_sha256[:16]}"
    if len(identity.encode()) > manifest.MAX_IDENTITY_BYTES:
        raise ValueError("deployment identity exceeds 200 bytes")
    return identity


def numerics_settings(torch, model) -> dict:
    """Observed settings that can change floating-point results. Recorded,
    not changed: the legacy deployment never set them."""
    cfg = getattr(model, "config", None)
    out = {
        "attn_implementation": getattr(cfg, "_attn_implementation", None),
        "matmul_allow_tf32": bool(torch.backends.cuda.matmul.allow_tf32),
        "matmul_allow_fp16_reduced_precision_reduction": bool(torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction),
        "float32_matmul_precision": torch.get_float32_matmul_precision(),
        "cudnn_allow_tf32": bool(torch.backends.cudnn.allow_tf32),
        "cudnn_deterministic": bool(torch.backends.cudnn.deterministic),
        "cudnn_benchmark": bool(torch.backends.cudnn.benchmark),
        "deterministic_algorithms": bool(torch.are_deterministic_algorithms_enabled()),
    }
    for name in ("flash_sdp_enabled", "mem_efficient_sdp_enabled", "math_sdp_enabled", "cudnn_sdp_enabled"):
        fn = getattr(torch.backends.cuda, name, None)
        out[name] = bool(fn()) if fn is not None else None
    return out


def make_policy_encoder(model_dir: Path, dtype: str, policy: str, rows: int):
    """The real CUDA encoder under a non-legacy policy (imports torch)."""
    from .encoder import E5CudaEncoder, EncoderOutOfMemory

    class PolicyEncoder(E5CudaEncoder):
        def __init__(self):
            super().__init__(model_dir, dtype)
            self.policy = check_policy(policy)
            self.rows = rows
            self.numerics = numerics_settings(self._torch, self.model)
            self.filler = self.tokenizer.encode("").ids
            if self.filler != [0, 2]:
                from .encoder import EncoderStartupError
                raise EncoderStartupError("tokenizer does not encode the fixed_v1 filler row as <s></s>")

        def encode(self, texts):
            return apply_policy(self.policy, texts, rows=self.rows,
                                encode_dynamic=super().encode, encode_fixed=self.encode_fixed)

        def encode_fixed(self, texts, rows, width):
            torch = self._torch
            encodings = self.tokenizer.encode_batch(list(texts))
            if max(len(e.ids) for e in encodings) > width:
                raise ValueError("overlength input reached the encoder")  # the service rejects earlier
            ids = torch.full((rows, width), self.pad_id, dtype=torch.long)
            mask = torch.zeros((rows, width), dtype=torch.long)
            for row in range(rows):
                seq = encodings[row].ids if row < len(encodings) else self.filler
                ids[row, : len(seq)] = torch.tensor(seq, dtype=torch.long)
                mask[row, : len(seq)] = 1
            try:
                with torch.inference_mode():
                    ids, mask = ids.to(self.device), mask.to(self.device)
                    hidden = self.model(input_ids=ids, attention_mask=mask).last_hidden_state.float()
                    weights = mask.unsqueeze(-1).float()
                    pooled = (hidden * weights).sum(dim=1) / weights.sum(dim=1)
                    vectors = torch.nn.functional.normalize(pooled, p=2, dim=1)
                    result = vectors[: len(encodings)].cpu().tolist()
                torch.cuda.synchronize(self.device)
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                raise EncoderOutOfMemory() from None
            return result

    return PolicyEncoder()
