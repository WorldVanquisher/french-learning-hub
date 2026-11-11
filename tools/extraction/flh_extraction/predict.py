"""Generate outputs for inputs-only evaluation prompts (optional backend).

  python3 -m flh_extraction.predict --model DIR --profile NAME [--adapter DIR] --prompts P.jsonl --out O.jsonl
         [--candidates C.jsonl] [--max-new-tokens N] [--template-kwargs JSON] [--limit N]

--profile (flh_extraction/models.py) supplies the loader and the chat-template
options; --template-kwargs overrides the latter. For Qwen3.5 the profile turns
thinking off, which the template would otherwise open by default.

Greedy decoding. Each output line is {"id", "output_text"} plus the
candidate's model-visible "input" when --candidates is given, ready for
`extraction-render validate`. References are never read here.
"""

import argparse
import json
import sys
from pathlib import Path

from . import models
from .train import render_chat


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter")
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--candidates")
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--profile", default="auto", choices=sorted(models.PROFILES))
    ap.add_argument("--template-kwargs")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    import torch
    cfg = {"model_name_or_path": a.model, "model_profile": a.profile, "local_files_only": True}
    tok = models.load_tokenizer(cfg)
    model = models.load_model(cfg)
    if a.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, a.adapter)
    model.eval()
    kw = json.loads(a.template_kwargs) if a.template_kwargs is not None else models.template_kwargs(cfg)
    inputs = {}
    if a.candidates:
        for line in Path(a.candidates).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            inputs[r["id"]] = r["input"]
    prompts = [json.loads(l) for l in Path(a.prompts).read_text(encoding="utf-8").splitlines() if l.strip()]
    if any(len(p["messages"]) != 2 for p in prompts):
        raise ValueError("prompts must be inputs-only (system and user messages)")
    if a.limit:
        prompts = prompts[:a.limit]
    with open(a.out, "w", encoding="utf-8") as f:
        for p in prompts:
            text = render_chat(tok, p["messages"], add_generation_prompt=True, template_kwargs=kw)
            ids = tok(text, return_tensors="pt", add_special_tokens=False, return_token_type_ids=False)
            with torch.no_grad():
                gen = model.generate(**ids, max_new_tokens=a.max_new_tokens, do_sample=False,
                                     pad_token_id=tok.pad_token_id or tok.eos_token_id)
            out = tok.decode(gen[0, ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
            row = {"id": p["id"], "output_text": out}
            if p["id"] in inputs:
                row["input"] = inputs[p["id"]]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"predicted": len(prompts), "profile": a.profile, "chat_template_kwargs": kw}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
