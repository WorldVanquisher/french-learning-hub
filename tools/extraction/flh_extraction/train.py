"""Supervised fine-tuning entry point (optional backend: torch + transformers).

  python3 -m flh_extraction.train --config CONFIG.json --train SFT.jsonl [--dev DEV.jsonl] --out DIR

The model is configurable (`model_name_or_path` + pinned `revision`); its
model-specific wiring (loader, chat-template options, LoRA targets) comes from
`model_profile` in flh_extraction/models.py. Only the
assistant tokens (the knowledge_extraction_v2 JSON) carry loss: system and user
tokens are masked with -100. A run writes the model, the tokenizer, the config,
per-step losses and a run manifest with input hashes. A model trained here is
a pipeline artefact: nothing in this module measures extraction quality, and
smoke checkpoints are never suitable for production.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from pathlib import Path

IGNORE = -100
DEFAULTS = {"model_name_or_path": None, "revision": None, "tokenizer_name_or_path": None, "trust_remote_code": False,
            "max_length": 1024, "learning_rate": 2e-4, "weight_decay": 0.0, "epochs": 1, "max_steps": None,
            "batch_size": 1, "grad_accum": 8, "seed": 1, "lora": None, "dtype": "float32", "eval_every": 50,
            "smoke": False, "local_files_only": True, "chat_template_kwargs": {}, "model_profile": "auto"}


def load_config(path):
    cfg = dict(DEFAULTS)
    user = json.loads(Path(path).read_text())
    unknown = set(user) - set(DEFAULTS) - {"$comment"}
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    cfg.update({k: v for k, v in user.items() if k != "$comment"})
    if not cfg["model_name_or_path"]:
        raise ValueError("model_name_or_path is required")
    from . import models
    models.get(cfg["model_profile"])
    return cfg


def render_chat(tokenizer, messages, add_generation_prompt=False, template_kwargs=None):
    """Text of a conversation: the tokenizer's chat template when it has one
    (with explicit template options, e.g. Qwen3's enable_thinking=False),
    otherwise a plain, explicit fallback template."""
    if getattr(tokenizer, "chat_template", None):
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=add_generation_prompt,
                                             **(template_kwargs or {}))
    text = "".join(f"<|{m['role']}|>\n{m['content']}\n<|end|>\n" for m in messages)
    return text + ("<|assistant|>\n" if add_generation_prompt else "")


def encode(tokenizer, record, max_length, template_kwargs=None):
    """input_ids and labels for one SFT record; labels mask everything except
    the assistant answer. Returns None when the answer would be truncated."""
    msgs = record["messages"]
    if [m["role"] for m in msgs] != ["system", "user", "assistant"]:
        raise ValueError(f"{record['id']}: expected system, user, assistant")
    prompt = render_chat(tokenizer, msgs[:2], add_generation_prompt=True, template_kwargs=template_kwargs)
    full = render_chat(tokenizer, msgs, template_kwargs=template_kwargs)
    if not full.startswith(prompt):
        raise ValueError(f"{record['id']}: the chat template does not extend the prompt")
    p_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    f_ids = tokenizer(full, add_special_tokens=False)["input_ids"]
    if f_ids[:len(p_ids)] != p_ids:
        raise ValueError(f"{record['id']}: prompt tokens are not a prefix of the full tokens")
    eos = tokenizer.eos_token_id
    if eos is not None:
        # A template that closes the assistant turn itself (Qwen: "<|im_end|>\n")
        # ends the target at its first end-of-turn token; anything the template
        # adds after it is not something the model should learn to generate.
        # Otherwise the end-of-turn token is appended once.
        answer = f_ids[len(p_ids):]
        f_ids = f_ids[:len(p_ids) + answer.index(eos) + 1] if eos in answer else f_ids + [eos]
    if len(f_ids) > max_length:
        return None
    labels = [IGNORE] * len(p_ids) + f_ids[len(p_ids):]
    return {"id": record["id"], "input_ids": f_ids, "labels": labels}


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def collate(batch, pad_id):
    import torch
    n = max(len(b["input_ids"]) for b in batch)
    ids = torch.full((len(batch), n), pad_id, dtype=torch.long)
    labels = torch.full((len(batch), n), IGNORE, dtype=torch.long)
    mask = torch.zeros((len(batch), n), dtype=torch.long)
    for k, b in enumerate(batch):
        m = len(b["input_ids"])
        ids[k, :m] = torch.tensor(b["input_ids"])
        labels[k, :m] = torch.tensor(b["labels"])
        mask[k, :m] = 1
    return ids, labels, mask


def masked_loss(model, ids, labels, mask):
    out = model(input_ids=ids, attention_mask=mask, labels=labels)
    return out.loss


def evaluate_loss(model, data, pad_id, batch_size):
    import torch
    model.eval()
    total, count = 0.0, 0
    with torch.no_grad():
        for k in range(0, len(data), batch_size):
            ids, labels, mask = collate(data[k:k + batch_size], pad_id)
            n = int((labels[:, 1:] != IGNORE).sum())
            total += float(masked_loss(model, ids, labels, mask)) * n
            count += n
    model.train()
    return total / count if count else None


def run(cfg, train_path, dev_path, out_dir, refuse_eval=True):
    import torch
    from . import models

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    random.seed(cfg["seed"])
    torch.manual_seed(cfg["seed"])
    train_recs = read_jsonl(train_path)
    dev_recs = read_jsonl(dev_path) if dev_path else []
    if refuse_eval and any(r.get("split") not in ("train", "dev") for r in train_recs + dev_recs):
        raise ValueError("training data may contain only train and dev records (evaluation records are refused)")
    tok = models.load_tokenizer(cfg)
    model = models.load_model(cfg, dtype=getattr(torch, cfg["dtype"]))
    if cfg["lora"]:
        from peft import LoraConfig, get_peft_model
        model = get_peft_model(model, LoraConfig(task_type="CAUSAL_LM", **models.lora_config(cfg)))
    kw = models.template_kwargs(cfg)
    train = [e for e in (encode(tok, r, cfg["max_length"], kw) for r in train_recs) if e]
    dev = [e for e in (encode(tok, r, cfg["max_length"], kw) for r in dev_recs) if e]
    skipped = len(train_recs) + len(dev_recs) - len(train) - len(dev)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"])
    steps_per_epoch = math.ceil(len(train) / (cfg["batch_size"] * cfg["grad_accum"]))
    total = cfg["max_steps"] or steps_per_epoch * cfg["epochs"]
    log, step, t0 = [], 0, time.time()
    model.train()
    order = list(range(len(train)))
    while step < total:
        random.shuffle(order)
        for k in range(0, len(order), cfg["batch_size"] * cfg["grad_accum"]):
            chunk = order[k:k + cfg["batch_size"] * cfg["grad_accum"]]
            opt.zero_grad()
            acc = 0.0
            for j in range(0, len(chunk), cfg["batch_size"]):
                ids, labels, mask = collate([train[i] for i in chunk[j:j + cfg["batch_size"]]], tok.pad_token_id)
                loss = masked_loss(model, ids, labels, mask) / math.ceil(len(chunk) / cfg["batch_size"])
                loss.backward()
                acc += float(loss)
            opt.step()
            step += 1
            entry = {"step": step, "train_loss": round(acc, 6)}
            if dev and (step % cfg["eval_every"] == 0 or step == total):
                entry["dev_loss"] = round(evaluate_loss(model, dev, tok.pad_token_id, cfg["batch_size"]), 6)
            log.append(entry)
            print(json.dumps(entry), flush=True)
            if step >= total:
                break
    model.save_pretrained(out / "model")
    tok.save_pretrained(out / "model")
    (out / "losses.jsonl").write_text("".join(json.dumps(e) + "\n" for e in log))
    (out / "config.json").write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")
    manifest = {"schema": "flh_extraction_training_run_v1", "train_sha256": sha256_file(train_path),
                "dev_sha256": sha256_file(dev_path) if dev_path else None, "train_examples": len(train),
                "dev_examples": len(dev), "skipped_too_long": skipped, "steps": step,
                "model_name_or_path": cfg["model_name_or_path"], "revision": cfg["revision"], "lora": cfg["lora"],
                "model_profile": cfg["model_profile"], "chat_template_kwargs": kw, "libraries": models.library_versions(),
                "seconds": round(time.time() - t0, 1), "smoke": cfg["smoke"],
                "suitable_for_production": False,
                "notice": "Pipeline artefact. No extraction-quality claim; evaluate on the frozen eval set with human-reviewed judgments."}
    files = {p.relative_to(out).as_posix(): sha256_file(p) for p in sorted(out.rglob("*")) if p.is_file() and p.name != "run_manifest.json"}
    manifest["files"] = files
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--train", required=True)
    ap.add_argument("--dev")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    m = run(load_config(a.config), a.train, a.dev, a.out)
    print(json.dumps({"event": "finished", "steps": m["steps"], "train_examples": m["train_examples"],
                      "suitable_for_production": False}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
