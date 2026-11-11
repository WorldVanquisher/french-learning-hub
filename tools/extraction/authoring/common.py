"""Shared helpers for the hand-authored extraction data (standard library only).

Every record built here is synthetic, machine-authored (by the Claude Code
session that wrote these files) and unreviewed. Nothing here is gold.
"""

from __future__ import annotations

AUTHORING = "claude-code local authoring session 2026-11-10 (hand-written source files; no provider call)"
CONFIDENCE_POLICY = "authoring convention 0.9/0.75/0.6 (ANNOTATION_POLICY.md rule 14); not calibrated"
KINDS = ("vocabulary", "grammar", "morphology", "orthography", "pronunciation", "usage", "expression")
CATEGORIES = ("vocabulary", "grammar", "morphology", "orthography", "pronunciation", "pragmatics",
              "discourse", "comprehension", "translation", "mixed", "other")


def U(kind: str, canonical: str, en: str, zh: str, example: str | None = None, confidence: float = 0.9) -> dict:
    """One expected unit in the production payload shape."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind}")
    return {"kind": kind, "canonical": canonical, "statement": en, "statement_zh": zh,
            "example": example, "confidence": confidence}


def I(original_input: str, context: str = "", category: str = "grammar", explanation: str = "",
      resolution: str = "accepted") -> dict:
    """The model-visible extraction input (production ExtractionSource fields)."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category}")
    if resolution not in ("unreviewed", "accepted", "corrected", "rejected"):
        raise ValueError(resolution)
    return {"entry_id": 0, "original_input": original_input, "original_context": context,
            "effective_category": category, "effective_explanation": explanation, "resolution": resolution}
