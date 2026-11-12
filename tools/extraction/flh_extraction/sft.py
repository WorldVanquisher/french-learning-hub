"""Supervised fine-tuning records from rendered production prompts.

Each record is {"id", "split", "messages": [system, user, assistant]}: the
system and user messages are exactly what `extraction-render render` reports
the production extractor sends; the assistant message is the expected
knowledge_extraction_v2 JSON. Only train and dev records are accepted:
evaluation records, quarantined records and boundary cases are refused, and
evaluation prompts can be exported only without their expected output.
"""

import json


def target_text(expected):
    # Compact, key-ordered JSON exactly in the contract's field order.
    units = [{k: u[k] for k in ("kind", "canonical", "statement", "statement_zh", "example", "confidence")}
             for u in expected["units"]]
    return json.dumps({"units": units}, ensure_ascii=False, separators=(",", ":"))


def build(candidates, rendered, splits=("train", "dev")):
    by_id = {r["id"]: r for r in rendered}
    out, refused = [], []
    for c in candidates:
        m = c["meta"]
        if m.get("quarantine_reason") or m.get("split_group") not in splits or c["schema"] != "flh_extraction_candidate_v1":
            refused.append(c["id"])
            continue
        r = by_id.get(c["id"])
        if r is None:
            raise ValueError(f"{c['id']}: no rendered prompt")
        out.append({"id": c["id"], "split": m["split_group"], "family_id": m["family_id"],
                    "messages": [{"role": "system", "content": r["developer"]},
                                 {"role": "user", "content": r["user"]},
                                 {"role": "assistant", "content": target_text(c["expected"])}]})
    return out, refused


def eval_prompts(candidates, rendered, split_groups=("eval",)):
    """Evaluation prompts without any expected output (for a prediction job)."""
    by_id = {r["id"]: r for r in rendered}
    return [{"id": c["id"], "messages": [{"role": "system", "content": by_id[c["id"]]["developer"]},
                                         {"role": "user", "content": by_id[c["id"]]["user"]}]}
            for c in candidates if c["meta"]["split_group"] in split_groups]
