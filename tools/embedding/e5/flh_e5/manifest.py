"""Pinned model files, file verification and the public deployment manifest.

The weights/tokenizer revision is fixed here, not taken from the command line:
changing it is a code change and therefore a new deployment identity.
Pins were read from the Hugging Face API for intfloat/multilingual-e5-base on
2026-10-12 (commit lastModified 2026-04-02). LFS files are pinned by SHA-256;
small files by their git blob SHA-1 (what the API reports), and their SHA-256
is recorded in the manifest. Standard library only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST_SCHEMA = "flh_e5_deployment_manifest_v1"
REPOSITORY = "intfloat/multilingual-e5-base"
REVISION = "d128750597153bb5987e10b1c3493a34e5a4502a"
LICENSE = "mit"
DIMENSIONS = 768
MAX_TOKENS = 512  # including the role prefix and the <s> </s> special tokens
DEPLOYMENT_NAME = "multilingual-e5-base"
MAX_IDENTITY_BYTES = 200  # EMBEDDING_MODEL_ID limit in the Go configuration

# file -> (size, kind, digest)
PINNED_FILES: dict[str, tuple[int, str, str]] = {
    "config.json": (694, "git-blob-sha1", "2b827c7eb80b3765ec6f465ab7cbfe173388c9dc"),
    "model.safetensors": (1112201288, "sha256", "a18a44fad1d0b46ded15928144138cff1135d5cc8233bdd90be5f18822de09a7"),
    "tokenizer.json": (17082660, "sha256", "62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626"),
    "tokenizer_config.json": (418, "git-blob-sha1", "6de1940d16d38be9877bf7cc228c9377841b311f"),
    "special_tokens_map.json": (280, "git-blob-sha1", "d5698132694f4f1bcff08fa7d937b1701812598e"),
    "sentencepiece.bpe.model": (5069051, "sha256", "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865"),
}
# Written by `hf download --local-dir`; tolerated, never read for weights.
TOLERATED_ENTRIES = {".cache", ".gitattributes"}

# Files whose bytes define the vectors (line endings normalized to LF so a
# Windows checkout with CRLF hashes the same).
VECTOR_CODE_FILES = ("contract.py", "encoder.py", "manifest.py")


class ModelFilesError(Exception):
    pass


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _file_sha256(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def verify_model_dir(model_dir: Path) -> dict[str, dict]:
    """Check that model_dir holds exactly the pinned files with the pinned
    digests. Returns {file: {size, sha256}}; raises ModelFilesError."""
    if not model_dir.is_dir():
        raise ModelFilesError(f"model directory not found: {model_dir}")
    entries = {p.name for p in model_dir.iterdir()}
    unexpected = sorted(entries - set(PINNED_FILES) - TOLERATED_ENTRIES)
    if unexpected:
        raise ModelFilesError(f"unexpected entries in the model directory (refusing; only the pinned safetensors files are allowed): {unexpected}")
    out: dict[str, dict] = {}
    for name, (size, kind, digest) in sorted(PINNED_FILES.items()):
        path = model_dir / name
        if not path.is_file() or path.is_symlink():
            raise ModelFilesError(f"missing pinned file (run the preparation step): {name}")
        sha256, actual_size = _file_sha256(path)
        if actual_size != size:
            raise ModelFilesError(f"{name}: size {actual_size}, pinned {size}")
        if kind == "sha256":
            ok = sha256 == digest
        else:
            ok = git_blob_sha1(path.read_bytes()) == digest
        if not ok:
            raise ModelFilesError(f"{name}: digest does not match the pinned revision {REVISION}")
        out[name] = {"size": size, "sha256": sha256, kind: digest}
    return out


def code_sha256(package_dir: Path) -> str:
    h = hashlib.sha256()
    for name in VECTOR_CODE_FILES:
        data = (package_dir / name).read_bytes().replace(b"\r\n", b"\n")
        h.update(name.encode() + b"\0" + str(len(data)).encode() + b"\0" + data)
    return h.hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def build_manifest(*, files: dict, code_hash: str, convention: str, accepted_pairs: list[str],
                   prefixes: dict[str, str], dtype: str, microbatch: int, runtime: dict, service: dict) -> dict:
    """The vector-defining part is hashed into the deployment identity; the
    service limits (which do not change vectors) are published beside it."""
    vector_defining = {
        "schema": MANIFEST_SCHEMA,
        "model": {"repository": REPOSITORY, "revision": REVISION, "license": LICENSE, "files": files,
                  "loader": "transformers XLMRobertaModel.from_pretrained(local dir, local_files_only, use_safetensors, trust_remote_code=False)"},
        "tokenizer": {"revision": REVISION, "source": "tokenizer.json via the tokenizers library",
                      "max_tokens": MAX_TOKENS, "special_tokens": "<s> and </s> from tokenizer.json's post-processor, counted",
                      "overlength": "reject (HTTP 422 input_too_long); never truncated", "truncations": "none by policy"},
        "adapter": {"convention": convention, "accepted": accepted_pairs, "prefixes": prefixes,
                    "rule": "prefix bytes followed by the original input string, applied once; role from representation/type only",
                    "code_sha256": code_hash, "code_files": list(VECTOR_CODE_FILES)},
        "inference": {"device": "cuda (required; no CPU fallback)", "dtype": dtype, "mode": "model.eval() + torch.inference_mode()",
                      "pooling": "attention-mask mean over last_hidden_state, computed in float32",
                      "normalization": "L2 in float32", "dimensions": DIMENSIONS, "microbatch": microbatch},
        "runtime": runtime,
    }
    digest = hashlib.sha256(canonical(vector_defining)).hexdigest()
    identity = deployment_identity(dtype, digest)
    return {"deployment_id": identity, "manifest_sha256": digest, "vector_defining": vector_defining, "service": service}


def deployment_identity(dtype: str, manifest_sha256: str) -> str:
    identity = f"{DEPLOYMENT_NAME}@{REVISION}/flh_e5_role_prefix_v1/{dtype}/{manifest_sha256[:16]}"
    if len(identity.encode()) > MAX_IDENTITY_BYTES:
        raise ValueError("deployment identity exceeds 200 bytes")
    return identity
