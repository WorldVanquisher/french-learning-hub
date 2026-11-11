"""Check the SFT records against a real tokenizer: the prompt must be a token
prefix of the full conversation (so masking is exact), and report sequence
lengths against max_length.

  python3 check_tokenizer.py TOKENIZER_DIR SFT.jsonl [--profile NAME] [--template-kwargs JSON] [--max-length N]

--profile takes the chat-template options from flh_extraction/models.py;
--template-kwargs overrides them.
"""

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flh_extraction import models  # noqa: E402
from flh_extraction.train import IGNORE, encode  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402


def main(tok_dir, sft, template_kwargs, max_length):
    tok = AutoTokenizer.from_pretrained(tok_dir, local_files_only=True)
    lengths, answer_lengths, errors, too_long = [], [], [], 0
    for line in Path(sft).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        try:
            e = encode(tok, r, 10 ** 9, template_kwargs)
        except ValueError as err:
            errors.append(str(err)[:160])
            continue
        lengths.append(len(e["input_ids"]))
        answer_lengths.append(sum(1 for l in e["labels"] if l != IGNORE))
        too_long += len(e["input_ids"]) > max_length
    q = statistics.quantiles(lengths, n=20) if len(lengths) > 1 else lengths
    print(json.dumps({"records": len(lengths) + len(errors), "prefix_errors": len(errors), "first_errors": errors[:3],
                      "tokens_min": min(lengths), "tokens_median": statistics.median(lengths), "tokens_p95": q[-1],
                      "tokens_max": max(lengths), "answer_tokens_median": statistics.median(answer_lengths),
                      "answer_tokens_max": max(answer_lengths), "over_max_length": too_long, "max_length": max_length}))


if __name__ == "__main__":
    a = sys.argv[1:]
    profile = a[a.index("--profile") + 1] if "--profile" in a else "auto"
    kw = json.loads(a[a.index("--template-kwargs") + 1]) if "--template-kwargs" in a else dict(models.get(profile)["chat_template_kwargs"])
    ml = int(a[a.index("--max-length") + 1]) if "--max-length" in a else 1024
    main(a[0], a[1], kw, ml)
