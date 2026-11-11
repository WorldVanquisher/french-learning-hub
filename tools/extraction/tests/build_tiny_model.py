"""Build a tiny, randomly initialized causal LM and a byte-level BPE tokenizer
trained locally on the SFT texts. Nothing is downloaded. The result proves the
training pipeline mechanics only; it has no language ability.

  python3 build_tiny_model.py SFT.jsonl OUT_DIR
"""

import json
import sys
from pathlib import Path

from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
from transformers import PreTrainedTokenizerFast, Qwen2Config, Qwen2ForCausalLM

CHAT_TEMPLATE = ("{% for m in messages %}<|{{ m['role'] }}|>\n{{ m['content'] }}\n<|end|>\n{% endfor %}"
                 "{% if add_generation_prompt %}<|assistant|>\n{% endif %}")


def build(sft_path, out, vocab=4000, seed=1):
    import torch
    torch.manual_seed(seed)
    texts = []
    for line in Path(sft_path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        texts += [m["content"] for m in r["messages"]]
    tok = Tokenizer(models.BPE(unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    special = ["<unk>", "<pad>", "<eos>", "<|system|>", "<|user|>", "<|assistant|>", "<|end|>"]
    tok.train_from_iterator(texts, trainers.BpeTrainer(vocab_size=vocab, special_tokens=special,
                                                       initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    fast = PreTrainedTokenizerFast(tokenizer_object=tok, unk_token="<unk>", pad_token="<pad>", eos_token="<eos>")
    fast.chat_template = CHAT_TEMPLATE
    cfg = Qwen2Config(vocab_size=len(fast), hidden_size=64, intermediate_size=128, num_hidden_layers=2,
                      num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=4096,
                      tie_word_embeddings=True, pad_token_id=fast.pad_token_id, eos_token_id=fast.eos_token_id)
    model = Qwen2ForCausalLM(cfg)
    out = Path(out)
    model.save_pretrained(out)
    fast.save_pretrained(out)
    (out / "FIXTURE.txt").write_text("Tiny randomly initialized fixture model for pipeline tests. Not a language model.\n")
    return out


if __name__ == "__main__":
    print(build(sys.argv[1], sys.argv[2]))
