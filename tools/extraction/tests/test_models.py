"""Model profiles, target masking, the evaluation subset and the category report
(standard library only; no model, no network)."""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "scripts"))

from flh_extraction import categories, models  # noqa: E402
from flh_extraction.train import IGNORE, encode, load_config  # noqa: E402
import select_eval_subset  # noqa: E402

# Parameter names of one linear-attention and one full-attention layer of the
# pinned Qwen/Qwen3.5-4B checkpoint (model.safetensors.index.json), as module
# paths of the text-only Qwen3_5ForCausalLM, plus vision and MTP modules.
QWEN35_MODULES = [
    "model.layers.0.linear_attn.in_proj_qkv", "model.layers.0.linear_attn.in_proj_z", "model.layers.0.linear_attn.in_proj_a",
    "model.layers.0.linear_attn.in_proj_b", "model.layers.0.linear_attn.out_proj", "model.layers.0.linear_attn.conv1d",
    "model.layers.0.mlp.gate_proj", "model.layers.0.mlp.up_proj", "model.layers.0.mlp.down_proj",
    "model.layers.3.self_attn.q_proj", "model.layers.3.self_attn.k_proj", "model.layers.3.self_attn.v_proj",
    "model.layers.3.self_attn.o_proj", "model.layers.3.mlp.down_proj",
    "model.visual.blocks.0.attn.qkv", "model.visual.blocks.0.mlp.linear_fc1", "mtp.layers.0.self_attn.q_proj", "lm_head",
]
TARGETED = {"model.layers.0.linear_attn.in_proj_qkv", "model.layers.0.linear_attn.in_proj_z", "model.layers.0.linear_attn.out_proj",
            "model.layers.0.mlp.gate_proj", "model.layers.0.mlp.up_proj", "model.layers.0.mlp.down_proj",
            "model.layers.3.self_attn.q_proj", "model.layers.3.self_attn.k_proj", "model.layers.3.self_attn.v_proj",
            "model.layers.3.self_attn.o_proj", "model.layers.3.mlp.down_proj"}


class Profiles(unittest.TestCase):
    def test_default_candidate_is_pinned_qwen35(self):
        p = models.get(models.DEFAULT_CANDIDATE)
        self.assertEqual(p["hf_id"], "Qwen/Qwen3.5-4B")
        self.assertRegex(p["revision"], r"^[0-9a-f]{40}$")
        self.assertEqual(p["chat_template_kwargs"], {"enable_thinking": False})
        self.assertIn("superseded", models.get("qwen3-1.7b")["status"])

    def test_lora_targets_hit_the_text_stack_only(self):
        rx = re.compile(models.get("qwen3.5-4b")["lora_target_modules"])
        hit = {m for m in QWEN35_MODULES if rx.fullmatch(m)}
        self.assertEqual(hit, TARGETED)

    def test_config_files_select_profiles(self):
        cfg = load_config(HERE.parent / "configs" / "sft-qwen3.5-4b-lora.json")
        self.assertEqual(cfg["model_profile"], "qwen3.5-4b")
        self.assertEqual(models.template_kwargs(cfg), {"enable_thinking": False})
        self.assertEqual(models.lora_config(cfg)["target_modules"], models.get("qwen3.5-4b")["lora_target_modules"])
        old = load_config(HERE.parent / "configs" / "sft-qwen3-1.7b-lora.json")
        self.assertIn("SUPERSEDED", json.loads((HERE.parent / "configs" / "sft-qwen3-1.7b-lora.json").read_text())["$comment"])
        self.assertEqual(models.lora_config(old)["target_modules"][0], "q_proj")
        smoke = load_config(HERE.parent / "configs" / "sft-smoke-tiny.json")
        self.assertEqual(smoke["model_profile"], "auto")

    def test_unknown_profile_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps({"model_name_or_path": "x", "model_profile": "nope"}))
            with self.assertRaises(ValueError):
                load_config(p)


class FakeTok:
    """Character-level tokenizer with a Qwen-like template that closes the
    assistant turn itself ("<E>\\n"); <E> is one token (the eos)."""
    chat_template = "fake"
    eos_token_id = 1

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False, **kw):
        t = "".join(f"[{m['role']}]{m['content']}<E>\n" for m in messages)
        return t + ("[assistant]" if add_generation_prompt else "")

    def __call__(self, text, add_special_tokens=False):
        ids, k = [], 0
        while k < len(text):
            if text.startswith("<E>", k):
                ids.append(1); k += 3
            else:
                ids.append(ord(text[k]) + 10); k += 1
        return {"input_ids": ids}


class Masking(unittest.TestCase):
    def test_target_ends_at_the_templates_end_of_turn(self):
        rec = {"id": "r", "messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"},
                                       {"role": "assistant", "content": "{}"}]}
        e = encode(FakeTok(), rec, 10 ** 6)
        answer = [x for x in e["labels"] if x != IGNORE]
        self.assertEqual(answer, [ord("{") + 10, ord("}") + 10, 1])
        self.assertEqual(e["input_ids"][-1], 1)
        self.assertEqual(e["input_ids"].count(1), 3)


def cand(i, case, n_units):
    return {"id": f"ext-evl-{i:04d}", "input": {}, "expected": {"units": [{"canonical": f"c{i}{k}"} for k in range(n_units)]},
            "meta": {"case_type": case}}


class Subset(unittest.TestCase):
    def test_subset_is_deterministic_and_covers_categories(self):
        cands = ([cand(i, "single", 1) for i in range(1, 136)] + [cand(i, "multi_2", 2) for i in range(136, 161)]
                 + [cand(i, "zero", 0) for i in range(161, 181)] + [cand(i, "fragmentation", 1) for i in range(181, 184)]
                 + [cand(i, "false_premise", 1) for i in range(184, 201)])
        a, b = select_eval_subset.select(cands), select_eval_subset.select(list(reversed(cands)))
        self.assertEqual([r["id"] for r in a], [r["id"] for r in b])
        self.assertEqual(len(a), 50)
        self.assertEqual(sum(1 for r in a if not r["expected"]["units"]), 20)
        self.assertEqual(sum(1 for r in a if r["meta"]["case_type"] == "multi_2"), 10)


class Categories(unittest.TestCase):
    def test_categories_are_reported_separately(self):
        refs = [cand(1, "zero", 0), cand(2, "single", 1), cand(3, "multi_2", 2)]
        results = [{"id": "ext-evl-0001", "valid": True}, {"id": "ext-evl-0002", "valid": False, "error_class": "unparseable_output"},
                   {"id": "ext-evl-0003", "valid": True}]
        report = {"provisional": True, "errors": {"ABSTENTION_FAIL": 1, "UNSUPPORTED": 2, "OVER_SPLIT": 1, "MISSED": 1},
                  "abstention": {"zero_unit_refs": 1, "correct_empty": 0, "rate": 0.0, "nonzero_refs_answered_empty": 1},
                  "rows": [{"id": "ext-evl-0001", "errors": {"UNSUPPORTED": 2}}]}
        s = categories.summarize(refs, results, report)
        self.assertEqual(s["schema_validity"]["valid"], 2)
        self.assertEqual(s["schema_validity"]["invalid_by_class"], {"unparseable_output": 1})
        self.assertEqual(s["unsupported"]["units"], 2)
        self.assertEqual(s["abstention"]["abstention_fail"], 1)
        self.assertEqual(s["splitting"]["over_split"], 1)
        self.assertEqual(s["other_errors"], {"MISSED": 1})
        self.assertIn("Schema validity", categories.markdown(s, "t"))


if __name__ == "__main__":
    unittest.main()
