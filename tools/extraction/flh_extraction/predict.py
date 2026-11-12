"""Generate outputs for inputs-only evaluation prompts (optional backend).

  python3 -m flh_extraction.predict --model DIR --profile NAME [--adapter DIR] --prompts P.jsonl --out O.jsonl
         [--candidates C.jsonl] [--max-new-tokens N] [--template-kwargs JSON] [--limit N]

--profile (flh_extraction/models.py) supplies the loader and the chat-template
options; --template-kwargs overrides the latter. For Qwen3.5 the profile turns
thinking off, which the template would otherwise open by default.

Greedy decoding. Each output line is {"id", "output_text", "generated_tokens",
"stopped"} plus the candidate's model-visible "input" when --candidates is
given, ready for `extraction-render validate` (which ignores the extra
fields). `stopped` is "eos" when the model ended its turn and
"max_new_tokens" when generation was cut, so `quality --outputs` can report a
truncated answer as such. References are never read here.
"""

import argparse
import json
import sys
from pathlib import Path

from . import models
from .train import render_chat


def stop_reason(new_ids, eos_id, max_new_tokens):
    """"max_new_tokens" when generation reached the cap without ending on the
    end-of-turn token; otherwise "eos" (the model ended its answer itself)."""
    if new_ids and eos_id is not None and new_ids[-1] == eos_id:
        return "eos"
    return "max_new_tokens" if len(new_ids) >= max_new_tokens else "eos"


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
            new = gen[0, ids["input_ids"].shape[1]:]
            out = tok.decode(new, skip_special_tokens=True).strip()
            row = {"id": p["id"], "output_text": out, "generated_tokens": int(new.shape[0]),
                   "stopped": stop_reason(new.tolist(), tok.eos_token_id, a.max_new_tokens)}
            if p["id"] in inputs:
                row["input"] = inputs[p["id"]]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"predicted": len(prompts), "profile": a.profile, "chat_template_kwargs": kw}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
