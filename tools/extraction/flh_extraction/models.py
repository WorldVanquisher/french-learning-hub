"""Model-specific wiring, kept apart from the dataset, the prompts and the evaluator.

A profile names a base model, its pinned revision, how it is loaded for
text-only causal-LM training and prediction, its chat-template options, its
LoRA target modules and the library version it was verified with. Training
(`train.py`), prediction (`predict.py`) and the tokenizer check select a
profile with the config key `model_profile`; nothing else in flh_extraction
knows which model is used, so a future small model is one new entry here.

Verified facts are recorded with each profile; "auto" is the generic
behaviour used by the tiny random smoke fixture.
"""

from __future__ import annotations

PROFILES = {
    "auto": {
        "status": "generic",
        "hf_id": None,
        "revision": None,
        "loader": "causal_lm",
        "chat_template_kwargs": {},
        "lora_target_modules": None,
        "verified_with": None,
        "notes": "AutoTokenizer + AutoModelForCausalLM; used by the tiny random smoke fixture (tests/build_tiny_model.py).",
    },
    "qwen3.5-4b": {
        "status": "default candidate",
        "hf_id": "Qwen/Qwen3.5-4B",
        "revision": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
        "license": "apache-2.0",
        # The checkpoint is Qwen3_5ForConditionalGeneration (image-text-to-text).
        # AutoModelForCausalLM maps model_type qwen3_5 to the text-only
        # Qwen3_5ForCausalLM and loads model.language_model.* from it (verified:
        # no missing or unexpected keys, identical logits on a text prompt). The
        # vision tower is not loaded; no processor, Pillow or torchvision needed.
        "loader": "causal_lm",
        # The template's default opens a thinking block (<think>\n); the
        # extractor answers JSON directly, so thinking is off in training and
        # prediction alike (prompt ends with an empty <think></think> block).
        "chat_template_kwargs": {"enable_thinking": False},
        # 24 Gated DeltaNet layers (linear_attn.*) and 8 full-attention layers
        # (self_attn.*), every layer with an MLP. Anchored on the text stack, so
        # nothing in a vision tower or MTP head can match.
        "lora_target_modules": (r"model\.layers\.\d+\."
                                r"(self_attn\.(q|k|v|o)_proj|linear_attn\.(in_proj_qkv|in_proj_z|out_proj)|mlp\.(gate|up|down)_proj)"),
        "verified_with": {"transformers": "5.21.1", "tokenizers": "0.23.3", "peft": "0.21.2", "torch": "2.15.0"},
        "weights_bytes": 9319737856,
        "notes": ("Hybrid attention: without the optional causal-conv1d and flash-linear-attention kernels, "
                  "transformers uses a correct but much slower PyTorch fallback."),
    },
    "qwen3-1.7b": {
        "status": "superseded (2026-11-11) by qwen3.5-4b; never trained",
        "hf_id": "Qwen/Qwen3-1.7B",
        "revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
        "license": "apache-2.0",
        "loader": "causal_lm",
        "chat_template_kwargs": {"enable_thinking": False},
        "lora_target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        "verified_with": {"transformers": "4.57.6", "tokenizers": "0.22.2"},
        "notes": "Tokenizer-checked 2026-11-10 (0 prefix errors); kept for reproducibility only.",
    },
}

DEFAULT_CANDIDATE = "qwen3.5-4b"


def get(name):
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown model_profile {name!r}; known: {sorted(PROFILES)}") from None


def template_kwargs(cfg):
    """Explicit config options win; otherwise the profile's."""
    return cfg.get("chat_template_kwargs") or dict(get(cfg.get("model_profile", "auto"))["chat_template_kwargs"])


def lora_config(cfg):
    """The config's LoRA settings, with the profile's target modules unless the
    config names its own."""
    lora = dict(cfg["lora"])
    if "target_modules" not in lora:
        targets = get(cfg.get("model_profile", "auto"))["lora_target_modules"]
        if targets is None:
            raise ValueError("lora.target_modules is required for this model_profile")
        lora["target_modules"] = targets
    return lora


def _common(cfg):
    return {"revision": cfg.get("revision"), "trust_remote_code": cfg.get("trust_remote_code", False),
            "local_files_only": cfg.get("local_files_only", True)}


def load_tokenizer(cfg):
    from transformers import AutoTokenizer
    get(cfg.get("model_profile", "auto"))
    tok = AutoTokenizer.from_pretrained(cfg.get("tokenizer_name_or_path") or cfg["model_name_or_path"], **_common(cfg))
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    return tok


def load_model(cfg, dtype=None):
    from transformers import AutoModelForCausalLM
    profile = get(cfg.get("model_profile", "auto"))
    if profile["loader"] != "causal_lm":
        raise ValueError(f"unsupported loader {profile['loader']}")
    kw = _common(cfg)
    if dtype is not None:
        kw["dtype"] = dtype
    return AutoModelForCausalLM.from_pretrained(cfg["model_name_or_path"], **kw)


def library_versions():
    import importlib
    out = {}
    for name in ("torch", "transformers", "tokenizers", "peft"):
        try:
            out[name] = importlib.import_module(name).__version__
        except Exception:  # noqa: BLE001 - absent optional backend
            out[name] = None
    return out
