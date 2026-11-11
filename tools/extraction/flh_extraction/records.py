"""Loading and structural checks for candidate and boundary records."""

import json

KINDS = {"vocabulary", "grammar", "morphology", "orthography", "pronunciation", "usage", "expression"}
INPUT_FIELDS = {"entry_id", "original_input", "original_context", "effective_category", "effective_explanation", "resolution"}
UNIT_FIELDS = {"kind", "canonical", "statement", "statement_zh", "example", "confidence"}
ALLOWED_REVIEW = {"unreviewed", "human_reviewed"}
ALLOWED_LABEL = {"machine_authored_unreviewed", "human_reviewed"}


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def structural_errors(rec):
    """Field-level checks that do not need the production validator: the
    model-visible input has exactly the production fields, the expected output
    has the contract shape, and metadata carries honest statuses."""
    errs = []
    if set(rec.get("input", {})) != INPUT_FIELDS:
        errs.append("input fields differ from the production ExtractionSource fields")
    units = rec.get("expected", {}).get("units")
    if not isinstance(units, list):
        errs.append("expected.units missing")
        units = []
    for k, u in enumerate(units):
        if set(u) != UNIT_FIELDS:
            errs.append(f"unit {k} fields")
        elif u["kind"] not in KINDS or not u["statement_zh"].strip() or not (0 <= u["confidence"] <= 1):
            errs.append(f"unit {k} values")
    m = rec.get("meta", {})
    if m.get("origin") != "synthetic":
        errs.append("origin must be synthetic for generated data")
    if m.get("review_status") not in ALLOWED_REVIEW or m.get("label_status") not in ALLOWED_LABEL:
        errs.append("review/label status")
    if m.get("review_status") == "unreviewed" and m.get("label_status") != "machine_authored_unreviewed":
        errs.append("an unreviewed record cannot carry a reviewed label")
    if "gold" in json.dumps(m).lower():
        errs.append("metadata mentions gold")
    visible = json.dumps(rec.get("input", {}), ensure_ascii=False)
    for key in ("family_id", "rationale", "split_group"):
        v = m.get(key)
        if isinstance(v, str) and len(v) > 12 and v in visible:
            errs.append(f"metadata {key} leaks into model-visible input")
    return errs
