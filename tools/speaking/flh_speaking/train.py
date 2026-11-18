"""Small, reproducible Whisper fine-tuning (``flh_speaking_train_v1``).

* Config: a JSON file (``configs/*.json``) pinned by SHA-256 in every checkpoint.
* Data: the frozen dataset's manifest; the order of every epoch is a seeded
  permutation, so the sample at any step is known in advance and a resumed run
  continues at exactly the next sample.
* Targets: ``<|fr|><|transcribe|><|notimestamps|>`` + reference text + EOT, the
  same prompt inference forces. Loss is cross-entropy on the text tokens and
  EOT only (the three forced prompt tokens are masked with -100).
* Checkpoints: ``checkpoints/step-NNNNNN/`` written to a temporary directory and
  renamed, then ``LATEST`` is replaced atomically. Each holds the model
  (``model.safetensors``; every other model file is a byte copy of the pinned
  base, so tokenizer and configuration stay identical), ``trainer_state.pt``
  (optimizer, scheduler, step, every RNG state) and ``run_manifest.json``
  (inputs, versions, loss history, file SHA-256). A run with an existing
  ``LATEST`` resumes; a config or data mismatch refuses to resume.
* SIGTERM/SIGINT: the current step finishes, a checkpoint is written, exit 0.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import random
import shutil
import signal
import time

import numpy as np

from . import audio, evaluate

SCHEMA = "flh_speaking_train_v1"
CONFIG_SCHEMA = "flh_speaking_train_config_v1"
MODEL_FILES_COPIED = ("config.json", "generation_config.json", "preprocessor_config.json", "tokenizer.json", "tokenizer_config.json",
                      "vocab.json", "merges.txt", "added_tokens.json", "special_tokens_map.json", "normalizer.json")
KEYS = {"schema", "base_model", "seed", "train_ids", "dev_ids", "max_steps", "batch_size", "grad_accum", "lr", "warmup_steps",
        "weight_decay", "max_grad_norm", "freeze", "gradient_checkpointing", "eval_every", "save_every", "keep_checkpoints", "threads", "note"}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()


def load_config(path: str) -> tuple[dict, str]:
    with open(path, "rb") as fh:
        raw = fh.read()
    cfg = json.loads(raw)
    if cfg.get("schema") != CONFIG_SCHEMA or set(cfg) - KEYS:
        raise ValueError(f"config must use schema {CONFIG_SCHEMA} and only known keys (unknown: {sorted(set(cfg) - KEYS)})")
    if cfg["freeze"] not in ("none", "encoder", "decoder"):
        raise ValueError("freeze must be none, encoder or decoder")
    return cfg, hashlib.sha256(raw).hexdigest()


def resolve_ids(data: str, spec) -> list[str]:
    if isinstance(spec, list):
        return list(spec)
    if isinstance(spec, str) and spec.startswith("split:"):
        return [r["id"] for r in evaluate.load_rows(data, spec[6:])]
    if isinstance(spec, str) and spec.startswith("tiny:"):
        with open(os.path.join(data, "dataset_manifest.json"), encoding="utf-8") as fh:
            return json.load(fh)["tiny_fixture"][spec[5:]]
    raise ValueError(f"unknown id spec {spec!r}")


def order(n: int, seed: int, epochs: int) -> list[int]:
    out = []
    for e in range(epochs):
        p = list(range(n))
        random.Random(seed * 1000 + e).shuffle(p)
        out += p
    return out


class Batcher:
    def __init__(self, data: str, rows: list[dict], processor, tokenizer_ids: dict):
        self.data, self.rows, self.proc, self.ids = data, rows, processor, tokenizer_ids

    def make(self, idx: list[int]):
        import torch
        rows = [self.rows[i] for i in idx]
        wavs = [evaluate.read_audio(self.data, r) for r in rows]
        feats = self.proc.feature_extractor(wavs, sampling_rate=audio.SAMPLE_RATE, return_tensors="pt").input_features
        tok = self.proc.tokenizer
        prompt = [self.ids["fr"], self.ids["transcribe"], self.ids["notimestamps"]]
        seqs = []
        for r in rows:
            text = tok(" " + r["text"].strip(), add_special_tokens=False).input_ids[:440]
            seqs.append(prompt + text + [self.ids["eot"]])
        L = max(len(s) for s in seqs)
        dec_in = torch.full((len(seqs), L), self.ids["eot"], dtype=torch.long)
        labels = torch.full((len(seqs), L), -100, dtype=torch.long)
        for b, s in enumerate(seqs):
            inp = [self.ids["sot"]] + s[:-1]
            dec_in[b, :len(inp)] = torch.tensor(inp)
            lab = list(s)
            for k in range(len(prompt)):
                lab[k] = -100
            labels[b, :len(lab)] = torch.tensor(lab)
        return feats, dec_in, labels


def _ids(tok) -> dict:
    c = tok.convert_tokens_to_ids
    return {"sot": c("<|startoftranscript|>"), "fr": c("<|fr|>"), "transcribe": c("<|transcribe|>"),
            "notimestamps": c("<|notimestamps|>"), "eot": tok.eos_token_id}


def loss_of(model, feats, dec_in, labels, check: bool = False):
    import torch
    dev = next(model.parameters()).device
    feats, dec_in, labels = feats.to(dev), dec_in.to(dev), labels.to(dev)
    out = model(input_features=feats, decoder_input_ids=dec_in)
    logits = out.logits.float()
    loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), labels.reshape(-1), ignore_index=-100)
    if check:  # independent computation of the same quantity
        lp = torch.log_softmax(logits, dim=-1)
        mask = labels != -100
        manual = -(lp.gather(-1, labels.clamp(min=0).unsqueeze(-1)).squeeze(-1) * mask).sum() / mask.sum()
        return loss, float(manual), int(mask.sum())
    return loss


def _rng_state():
    import torch
    st = {"python": random.getstate(), "numpy": np.random.get_state(), "torch": torch.get_rng_state()}
    if torch.cuda.is_available():
        st["cuda"] = torch.cuda.get_rng_state_all()
    return st


def _set_rng(st):
    import torch
    random.setstate(st["python"])
    np.random.set_state(st["numpy"])
    torch.set_rng_state(st["torch"])
    if "cuda" in st and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(st["cuda"])


def train(config_path: str, data: str, base: str, out: str, *, stop_after: int = 0, log=print) -> dict:
    import torch
    import transformers
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    cfg, cfg_sha = load_config(config_path)
    torch.set_num_threads(int(cfg["threads"]))
    torch.use_deterministic_algorithms(True, warn_only=True)
    with open(os.path.join(data, "dataset_manifest.json"), encoding="utf-8") as fh:
        data_manifest = json.load(fh)
    data_sha = data_manifest["manifest_jsonl_sha256"]
    train_ids = resolve_ids(data, cfg["train_ids"])
    dev_ids = resolve_ids(data, cfg["dev_ids"])
    rows_by_id = {r["id"]: r for s in ("train", "dev", "test", "ood") for r in evaluate.load_rows(data, s)}
    if any(rows_by_id[i]["split"] != "train" for i in train_ids):
        raise ValueError("training ids must come from the train split")
    if any(rows_by_id[i]["split"] not in ("dev", "train") for i in dev_ids):
        raise ValueError("dev ids must come from the dev (or train) split, never test or ood")
    train_rows = [rows_by_id[i] for i in train_ids]
    dev_rows = [rows_by_id[i] for i in dev_ids]
    os.makedirs(os.path.join(out, "checkpoints"), exist_ok=True)
    latest_file = os.path.join(out, "checkpoints", "LATEST")

    processor = WhisperProcessor.from_pretrained(base, local_files_only=True)
    ids = _ids(processor.tokenizer)
    resume_dir = None
    if os.path.exists(latest_file):
        resume_dir = os.path.join(out, "checkpoints", _text(latest_file))
        with open(os.path.join(resume_dir, "run_manifest.json"), encoding="utf-8") as fh:
            prev = json.load(fh)
        if prev["config_sha256"] != cfg_sha or prev["data_manifest_sha256"] != data_sha or prev["base"]["files"] != _base_files(base):
            raise ValueError("refusing to resume: config, data or base model differ from the checkpoint")
    model = WhisperForConditionalGeneration.from_pretrained(resume_dir or base, local_files_only=True, use_safetensors=True, torch_dtype=torch.float32)
    model.config.forced_decoder_ids = None
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")  # GPU on SageMaker, CPU locally
    model.to(device)
    if cfg["gradient_checkpointing"]:
        model.gradient_checkpointing_enable()
        model.config.use_cache = False
    if cfg["freeze"] == "encoder":
        for p in model.model.encoder.parameters():
            p.requires_grad_(False)
    elif cfg["freeze"] == "decoder":
        for p in model.model.decoder.parameters():
            p.requires_grad_(False)
    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    params = [p for p in model.parameters() if p.requires_grad]
    decay = [p for p in params if p.ndim >= 2]
    no_decay = [p for p in params if p.ndim < 2]
    opt = torch.optim.AdamW([{"params": decay, "weight_decay": cfg["weight_decay"]}, {"params": no_decay, "weight_decay": 0.0}], lr=cfg["lr"])
    warm, steps = int(cfg["warmup_steps"]), int(cfg["max_steps"])
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / max(1, warm)) * max(0.0, (steps - s) / max(1, steps - warm)) if s >= warm else (s + 1) / max(1, warm))
    per_step = int(cfg["batch_size"]) * int(cfg["grad_accum"])
    epochs = math.ceil(steps * per_step / len(train_rows)) + 1
    seq = order(len(train_rows), int(cfg["seed"]), epochs)
    batcher = Batcher(data, train_rows, processor, ids)
    dev_batcher = Batcher(data, dev_rows, processor, ids)
    step, history = 0, []
    if resume_dir:
        st = torch.load(os.path.join(resume_dir, "trainer_state.pt"), weights_only=False)
        opt.load_state_dict(st["optimizer"])
        sched.load_state_dict(st["scheduler"])
        _set_rng(st["rng"])
        step, history = st["step"], st["history"]
        log(f"resumed from {os.path.basename(resume_dir)} at step {step}")
    else:
        random.seed(cfg["seed"])
        np.random.seed(cfg["seed"])
        torch.manual_seed(cfg["seed"])
        if device.type == "cuda":
            torch.cuda.manual_seed_all(cfg["seed"])
        # Loss check before any update: library loss == independent log-softmax NLL.
        model.eval()
        with torch.no_grad():
            f, d, l = batcher.make(seq[:min(per_step, 4)])
            lib, manual, n_tok = loss_of(model, f, d, l, check=True)
        history.append({"step": 0, "check": {"library_loss": round(float(lib), 6), "manual_loss": round(manual, 6), "tokens": n_tok,
                                              "uniform_baseline_ln_vocab": round(math.log(model.config.vocab_size), 4)}})
        log(f"loss check: library {float(lib):.6f} manual {manual:.6f} over {n_tok} tokens")
    stop = {"flag": False}

    def _sig(signum, _frame):
        stop["flag"] = True
        log(f"signal {signum}: finishing the current step, then saving")
    old = {s: signal.signal(s, _sig) for s in (signal.SIGTERM, signal.SIGINT)}
    started = step
    try:
        model.train()
        for p in model.modules():  # dropout stays as configured in the pinned model config (0.0 for Whisper)
            pass
        while step < steps:
            t0 = time.monotonic()
            opt.zero_grad(set_to_none=True)
            tot = 0.0
            for a in range(int(cfg["grad_accum"])):
                k = (step * per_step) + a * int(cfg["batch_size"])
                f, d, l = batcher.make(seq[k:k + int(cfg["batch_size"])])
                loss = loss_of(model, f, d, l) / int(cfg["grad_accum"])
                loss.backward()
                tot += float(loss.detach())
            gn = float(torch.nn.utils.clip_grad_norm_(params, cfg["max_grad_norm"]))
            opt.step()
            sched.step()
            step += 1
            rec = {"step": step, "loss": round(tot, 6), "grad_norm": round(gn, 4), "lr": sched.get_last_lr()[0], "seconds": round(time.monotonic() - t0, 2)}
            if cfg["eval_every"] and (step % int(cfg["eval_every"]) == 0 or step == steps):
                rec["dev_loss"] = dev_loss(model, dev_batcher, len(dev_rows))
                model.train()
            history.append(rec)
            log(json.dumps(rec))
            boundary = step % int(cfg["save_every"]) == 0 or step == steps
            interrupted = stop["flag"] or (stop_after and step - started >= stop_after)
            if boundary or interrupted:
                save(out, base, model, opt, sched, step, history, cfg, cfg_sha, data_sha, total, trainable)
            if interrupted:
                return {"status": "interrupted", "step": step, "latest": _text(latest_file)}
    finally:
        for s, h in old.items():
            signal.signal(s, h)
    final = os.path.join(out, "checkpoints", _text(latest_file))
    return {"status": "completed", "step": step, "checkpoint": final, "trainable_params": trainable, "total_params": total, "device": device.type,
            "final_loss": history[-1].get("loss"), "dev_loss": history[-1].get("dev_loss"),
            "model_sha256": sha256_file(os.path.join(final, "model.safetensors")), "transformers": transformers.__version__}


def dev_loss(model, batcher, n: int, bs: int = 4) -> float:
    import torch
    model.eval()
    tot = cnt = 0.0
    with torch.no_grad():
        for k in range(0, n, bs):
            f, d, l = batcher.make(list(range(k, min(n, k + bs))))
            m = int((l != -100).sum())
            tot += float(loss_of(model, f, d, l)) * m
            cnt += m
    return round(tot / cnt, 6) if cnt else None


def _base_files(base: str) -> dict:
    return {f: sha256_file(os.path.join(base, f)) for f in MODEL_FILES_COPIED + ("model.safetensors",) if os.path.exists(os.path.join(base, f))}


def save(out, base, model, opt, sched, step, history, cfg, cfg_sha, data_sha, total, trainable):
    import tempfile
    import torch
    import transformers
    name = f"step-{step:06d}"
    ck_root = os.path.join(out, "checkpoints")
    tmp = tempfile.mkdtemp(prefix=f".{name}-", dir=ck_root)
    try:
        st = tempfile.mkdtemp(prefix=".hf-", dir=ck_root)
        try:
            model.save_pretrained(st, safe_serialization=True)
            shutil.copyfile(os.path.join(st, "model.safetensors"), os.path.join(tmp, "model.safetensors"))
        finally:
            shutil.rmtree(st, ignore_errors=True)
        for f in MODEL_FILES_COPIED:
            if os.path.exists(os.path.join(base, f)):
                shutil.copyfile(os.path.join(base, f), os.path.join(tmp, f))
        torch.save({"optimizer": opt.state_dict(), "scheduler": sched.state_dict(), "rng": _rng_state(), "step": step, "history": history},
                   os.path.join(tmp, "trainer_state.pt"))
        with open(os.path.join(tmp, "train_config.json"), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=1, sort_keys=True)
        files = {f: sha256_file(os.path.join(tmp, f)) for f in sorted(os.listdir(tmp))}
        man = {
            "schema": SCHEMA, "step": step, "config_sha256": cfg_sha, "data_manifest_sha256": data_sha,
            "base": {"dir_name": os.path.basename(os.path.normpath(base)), "files": _base_files(base)},
            "params": {"total": total, "trainable": trainable},
            "versions": {"python": platform.python_version(), "torch": torch.__version__, "transformers": transformers.__version__, "numpy": np.__version__},
            "device": next(model.parameters()).device.type,
            "loss_history_tail": history[-5:], "files": files,
            "suitable_for_production": False,
        }
        with open(os.path.join(tmp, "run_manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(man, fh, indent=1, sort_keys=True)
        final = os.path.join(ck_root, name)
        if os.path.exists(final):
            shutil.rmtree(final)
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    with open(os.path.join(ck_root, "LATEST.tmp"), "w") as fh:
        fh.write(name + "\n")
    os.replace(os.path.join(ck_root, "LATEST.tmp"), os.path.join(ck_root, "LATEST"))
    keep = int(cfg.get("keep_checkpoints") or 0)
    if keep:
        old = sorted(d for d in os.listdir(ck_root) if d.startswith("step-") and d != name)
        for d in old[:-max(0, keep - 1)] if keep > 1 else old:
            shutil.rmtree(os.path.join(ck_root, d), ignore_errors=True)


def verify_checkpoint(path: str) -> list[str]:
    """Problems with a checkpoint directory (empty list when every file matches its manifest)."""
    with open(os.path.join(path, "run_manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    probs = []
    for f, h in man["files"].items():
        p = os.path.join(path, f)
        if not os.path.exists(p):
            probs.append(f"{f}: missing")
        elif sha256_file(p) != h:
            probs.append(f"{f}: sha256 mismatch")
    return probs
