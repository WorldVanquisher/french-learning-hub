"""Encoders behind the service.

`Encoder` is the small interface the service uses; tests inject a fake.
`E5CudaEncoder` is the real deployment: the pinned multilingual-e5-base
weights from a local directory, on CUDA only, in eval/inference mode, with
attention-mask mean pooling and L2 normalization in float32. torch,
transformers and tokenizers are imported only when it is constructed.
This file defines vectors and is part of the deployment's code hash.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Protocol, Sequence

from . import manifest

DTYPES = ("float16", "float32")


class EncoderStartupError(Exception):
    """The deployment cannot start (no CUDA, wrong files, wrong runtime)."""


class EncoderOutOfMemory(Exception):
    """The GPU ran out of memory for this request. Never retried."""


class Encoder(Protocol):
    dimensions: int

    def count_tokens(self, texts: Sequence[str]) -> list[int]:
        """Token counts including special tokens, without truncation."""

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """One microbatch: L2-normalized vectors, in input order."""

    def gpu_evidence(self) -> dict:
        """Measured placement and memory; no input text."""

    def runtime_versions(self) -> dict:
        """Versions that define the vectors, for the manifest."""

    def close(self) -> None:
        """Release the model and GPU memory."""


def _offline_environment() -> None:
    # Never download at startup, whatever the user's environment says.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def runtime_versions(torch_module=None) -> dict:
    """Library and device versions. Imports torch etc. (no model load)."""
    _offline_environment()
    import safetensors
    import tokenizers
    import transformers

    torch = torch_module
    if torch is None:
        import torch  # noqa: F811
    try:
        import numpy
        numpy_version = numpy.__version__
    except ImportError:  # recorded honestly; transformers requires it anyway
        numpy_version = "not installed"
    if not torch.cuda.is_available():
        raise EncoderStartupError("CUDA is not available to torch; this deployment requires CUDA (no CPU fallback)")
    props = torch.cuda.get_device_properties(0)
    return {
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "os": platform.platform(terse=True),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "transformers": transformers.__version__,
        "tokenizers": tokenizers.__version__,
        "safetensors": safetensors.__version__,
        "numpy": numpy_version,
        "gpu_name": props.name,
        "gpu_capability": f"{props.major}.{props.minor}",
    }


class E5CudaEncoder:
    """The real encoder. Construction loads and verifies everything; any
    problem raises EncoderStartupError instead of falling back."""

    def __init__(self, model_dir: Path, dtype: str = "float16", device_index: int = 0):
        if dtype not in DTYPES:
            raise EncoderStartupError(f"dtype must be one of {DTYPES}")
        _offline_environment()
        self.files = manifest.verify_model_dir(model_dir)
        import torch
        import tokenizers
        from transformers import XLMRobertaModel

        if not torch.cuda.is_available():
            raise EncoderStartupError("CUDA is not available to torch; this deployment requires CUDA (no CPU fallback)")
        self._torch = torch
        self.device = torch.device(f"cuda:{device_index}")
        self.dtype_name = dtype
        self.torch_dtype = {"float16": torch.float16, "float32": torch.float32}[dtype]
        self.dimensions = manifest.DIMENSIONS
        self._versions = runtime_versions(torch)

        tok = tokenizers.Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        tok.no_truncation()
        tok.no_padding()
        self.tokenizer = tok
        self.pad_id = tok.token_to_id("<pad>")
        bos, eos = tok.token_to_id("<s>"), tok.token_to_id("</s>")
        probe = tok.encode("query: x").ids
        if self.pad_id != 1 or bos != 0 or eos != 2 or probe[0] != bos or probe[-1] != eos:
            raise EncoderStartupError("tokenizer.json does not add <s>/</s> or has unexpected special token ids")

        torch.cuda.reset_peak_memory_stats(self.device)
        model = XLMRobertaModel.from_pretrained(str(model_dir), local_files_only=True, use_safetensors=True,
                                                trust_remote_code=False, dtype=self.torch_dtype)
        model.eval()
        model.to(self.device)
        if model.config.hidden_size != self.dimensions or model.config.pad_token_id != self.pad_id:
            raise EncoderStartupError("model config does not match the pinned deployment")
        bad = [n for n, p in model.named_parameters() if p.device != self.device or p.dtype != self.torch_dtype]
        if bad:
            raise EncoderStartupError(f"{len(bad)} parameter(s) not on {self.device} as {dtype}")
        self.model = model

    def runtime_versions(self) -> dict:
        return dict(self._versions)

    def count_tokens(self, texts: Sequence[str]) -> list[int]:
        return [len(e.ids) for e in self.tokenizer.encode_batch(list(texts))]

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        torch = self._torch
        encodings = self.tokenizer.encode_batch(list(texts))
        width = max(len(e.ids) for e in encodings)
        if width > manifest.MAX_TOKENS:
            raise ValueError("overlength input reached the encoder")  # the service rejects earlier
        ids = torch.full((len(encodings), width), self.pad_id, dtype=torch.long)
        mask = torch.zeros((len(encodings), width), dtype=torch.long)
        for row, e in enumerate(encodings):
            ids[row, : len(e.ids)] = torch.tensor(e.ids, dtype=torch.long)
            mask[row, : len(e.ids)] = 1
        try:
            with torch.inference_mode():
                ids, mask = ids.to(self.device), mask.to(self.device)
                hidden = self.model(input_ids=ids, attention_mask=mask).last_hidden_state.float()
                weights = mask.unsqueeze(-1).float()
                pooled = (hidden * weights).sum(dim=1) / weights.sum(dim=1)
                vectors = torch.nn.functional.normalize(pooled, p=2, dim=1)
                result = vectors.cpu().tolist()
            torch.cuda.synchronize(self.device)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            raise EncoderOutOfMemory() from None
        return result

    def gpu_evidence(self) -> dict:
        torch = self._torch
        params = list(self.model.parameters()) if getattr(self, "model", None) is not None else []
        return {
            "device": str(self.device),
            "gpu_name": torch.cuda.get_device_name(self.device),
            "total_memory_bytes": torch.cuda.get_device_properties(self.device).total_memory,
            "memory_allocated_bytes": torch.cuda.memory_allocated(self.device),
            "memory_reserved_bytes": torch.cuda.memory_reserved(self.device),
            "max_memory_allocated_bytes": torch.cuda.max_memory_allocated(self.device),
            "parameters_on_device": all(p.device == self.device for p in params) and bool(params),
            "parameter_dtype": self.dtype_name,
            "model_training_mode": bool(getattr(self.model, "training", True)) if params else None,
        }

    def close(self) -> None:
        torch = self._torch
        self.model = None
        torch.cuda.synchronize(self.device)
        torch.cuda.empty_cache()
