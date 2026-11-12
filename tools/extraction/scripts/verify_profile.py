"""Verify a model profile against the pinned checkpoint's own files, offline.

  python3 -B scripts/verify_profile.py --profile qwen3.5-4b --meta DIR --sft SFT.jsonl [SFT2 …]
         [--sums SHA256SUMS] [--tokenizer DIR] [--max-length N] [--max-new-tokens N] --out REPORT.json

DIR holds the checkpoint's small files at the pinned revision (config.json,
tokenizer_config.json, chat_template.jinja, model.safetensors.index.json).
Weights are never needed. Needs transformers (its own chat-template renderer,
the one apply_chat_template uses); no network.

  metadata    hashes (with --sums), architecture, layer types, vocabulary, special tokens
  lora        the profile's target regex against the checkpoint's real weight names,
              mapped to the text-only causal-LM module names the loader produces
  template    with the profile's template options, for every SFT record: the
              generation prompt is a prefix of the full conversation, and the
              continuation is exactly the target JSON plus the end-of-turn text;
              without the options, the prompt opens a thinking block
  decoding    which end and thinking markers survive skip_special_tokens
  tokens      only with --tokenizer (tokenizer.json at the pinned revision):
              train.encode on every record (token prefix, label tail, lengths
              vs --max-length, answers vs --max-new-tokens); otherwise PENDING
"""

import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flh_extraction import models  # noqa: E402
from flh_extraction.sft import target_text  # noqa: E402  (target format check)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def metadata(meta, sums):
    cfg = json.loads((meta / "config.json").read_text())
    tc = cfg.get("text_config", cfg)
    tok = json.loads((meta / "tokenizer_config.json").read_text())
    dec = {v["content"]: v for v in tok.get("added_tokens_decoder", {}).values()}
    out = {"architectures": cfg.get("architectures"), "model_type": cfg.get("model_type"),
           "text_model_type": tc.get("model_type"), "num_hidden_layers": tc.get("num_hidden_layers"),
           "layer_types": dict(Counter(tc.get("layer_types") or [])), "vocab_size": tc.get("vocab_size"),
           "tie_word_embeddings": cfg.get("tie_word_embeddings", tc.get("tie_word_embeddings")),
           "eos_token": tok.get("eos_token"), "pad_token": tok.get("pad_token"), "tokenizer_class": tok.get("tokenizer_class"),
           "special": {t: dec.get(t, {}).get("special") for t in ("<|im_start|>", "<|im_end|>", "<|endoftext|>", "<think>", "</think>")},
           "files": {p.name: sha(p) for p in sorted(meta.iterdir()) if p.is_file()}}
    if sums:
        expected = dict(reversed(line.split()) for line in Path(sums).read_text().splitlines() if line.strip())
        out["hash_check"] = {n: ("ok" if expected.get(n) == h else "MISMATCH" if n in expected else "unpinned")
                             for n, h in out["files"].items()}
        out["pinned_but_absent"] = sorted(set(expected) - set(out["files"]))
    return out


def lora(meta, profile):
    idx = json.loads((meta / "model.safetensors.index.json").read_text())["weight_map"]
    rx = profile["lora_target_modules"]
    names = sorted({re.sub(r"\.(weight|bias)$", "", k).replace("model.language_model.", "model.", 1) for k in idx})
    if isinstance(rx, str):
        hit = [n for n in names if re.fullmatch(rx, n)]
    else:
        hit = [n for n in names if n.split(".")[-1] in rx]
    kinds = Counter(".".join(n.split(".")[3:]) for n in hit)
    layers = {int(n.split(".")[2]) for n in hit}
    return {"weight_tensors": len(idx), "candidate_modules": len(names), "targeted": len(hit),
            "by_module": dict(sorted(kinds.items())), "layers_covered": len(layers),
            "outside_text_stack": [n for n in hit if not n.startswith("model.layers.")],
            "vision_or_mtp_present_in_checkpoint": sum(1 for n in names if n.startswith(("model.visual", "mtp."))),
            "regex": rx}


def template(meta, sft_rows, kwargs):
    from transformers.utils.chat_template_utils import render_jinja_template
    tpl = (meta / "chat_template.jinja").read_text()

    def render(msgs, gen, kw):
        return render_jinja_template([msgs], chat_template=tpl, add_generation_prompt=gen, **kw)[0][0]
    demo = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]
    out = {"default_prompt_tail": render(demo, True, {})[-40:], "profile_prompt_tail": render(demo, True, kwargs)[-40:],
           "template_kwargs": kwargs}
    bad_prefix, bad_tail, think, fmt = [], [], [], []
    p_chars, a_chars = [], []
    for r in sft_rows:
        m = r["messages"]
        prompt, full = render(m[:2], True, kwargs), render(m, False, kwargs)
        if not full.startswith(prompt):
            bad_prefix.append(r["id"])
            continue
        cont = full[len(prompt):]
        if cont != m[2]["content"] + "<|im_end|>\n":
            bad_tail.append(r["id"])
        if "<think>" in cont or "</think>" in cont:
            think.append(r["id"])
        if target_text(json.loads(m[2]["content"])) != m[2]["content"]:
            fmt.append(r["id"])
        p_chars.append(len(prompt))
        a_chars.append(len(m[2]["content"]))
    out.update({"records": len(sft_rows), "prompt_not_prefix": bad_prefix[:5], "prompt_not_prefix_count": len(bad_prefix),
                "continuation_not_target_plus_im_end": len(bad_tail), "think_markers_in_target": len(think),
                "target_not_contract_format": len(fmt),
                "prompt_chars": _stats(p_chars), "answer_chars": _stats(a_chars)})
    return out


def tokens(tok_dir, sft_rows, kwargs, max_length, max_new):
    from transformers import AutoTokenizer
    from flh_extraction.train import IGNORE, encode
    tok = AutoTokenizer.from_pretrained(tok_dir, local_files_only=True)
    lens, ans, errors, tails = [], [], [], Counter()
    for r in sft_rows:
        try:
            e = encode(tok, r, 10 ** 9, kwargs)
        except ValueError as err:
            errors.append(str(err)[:120])
            continue
        lens.append(len(e["input_ids"]))
        lab = [x for x in e["labels"] if x != IGNORE]
        ans.append(len(lab))
        tails[tok.decode(lab[-1:])] += 1
    return {"records": len(sft_rows), "prefix_errors": len(errors), "first_errors": errors[:3], "tokens": _stats(lens),
            "answer_tokens": _stats(ans), "label_last_token": dict(tails), "over_max_length": sum(x > max_length for x in lens),
            "answers_over_max_new_tokens": sum(x > max_new for x in ans), "max_length": max_length, "max_new_tokens": max_new}


def decoding(meta_info):
    s = meta_info["special"]
    return {"im_end_removed_by_skip_special_tokens": bool(s.get("<|im_end|>")),
            "think_markers_kept_by_skip_special_tokens": not s.get("<think>") and not s.get("</think>"),
            "consequence": ("a generated <think>…</think> block survives decoding and the production parser refuses the text "
                            "(quality.parse_diagnostic reports think_block); with thinking off, the prompt already ends with "
                            "the empty block, so a well-trained answer starts with « { »")}


def _stats(xs):
    if not xs:
        return None
    q = statistics.quantiles(xs, n=20) if len(xs) > 1 else xs
    return {"min": min(xs), "median": statistics.median(xs), "p95": q[-1], "max": max(xs)}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--sft", nargs="+", required=True)
    ap.add_argument("--sums")
    ap.add_argument("--tokenizer")
    ap.add_argument("--max-length", type=int)
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    prof = models.get(a.profile)
    meta = Path(a.meta)
    rows = [json.loads(line) for f in a.sft for line in Path(f).read_text(encoding="utf-8").splitlines() if line.strip()]
    kw = dict(prof["chat_template_kwargs"])
    rep = {"schema": "flh_extraction_profile_verification_v1", "profile": a.profile, "hf_id": prof["hf_id"],
           "revision": prof["revision"], "verified_with_profile": prof.get("verified_with"),
           "sft_files": {Path(f).name: sha(f) for f in a.sft}}
    import transformers
    rep["libraries"] = {"transformers": transformers.__version__}
    rep["metadata"] = metadata(meta, a.sums)
    rep["lora"] = lora(meta, prof)
    rep["template"] = template(meta, rows, kw)
    rep["decoding"] = decoding(rep["metadata"])
    if a.tokenizer:
        rep["tokens"] = tokens(a.tokenizer, rows, kw, a.max_length or 10 ** 9, a.max_new_tokens)
    else:
        rep["tokens"] = ("PENDING: tokenizer.json, vocab.json and merges.txt at the pinned revision are not available here; "
                         "rerun with --tokenizer DIR")
    Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    t = rep["template"]
    print(json.dumps({"records": t["records"], "prompt_not_prefix": t["prompt_not_prefix_count"],
                      "continuation_mismatch": t["continuation_not_target_plus_im_end"],
                      "think_in_target": t["think_markers_in_target"], "lora_targeted": rep["lora"]["targeted"],
                      "lora_outside_text_stack": len(rep["lora"]["outside_text_stack"]),
                      "tokens": "measured" if a.tokenizer else "PENDING"}))
    ok = not (t["prompt_not_prefix_count"] or t["continuation_not_target_plus_im_end"] or t["think_markers_in_target"]
              or t["target_not_contract_format"] or rep["lora"]["outside_text_stack"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
