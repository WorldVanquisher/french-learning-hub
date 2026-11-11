"""Authoring helpers for the FLH French workbooks (hand-written, synthetic,
unreviewed). Single-choice questions are written with the correct answer
first; the builder decides the displayed order (balanced positions)."""


def SC(qid, kind, stem, correct, wrongs, evidence, en, zh):
    """Single choice: exactly one correct option; each wrong option carries why
    it is wrong in English and Chinese. evidence: [(ref, excerpt), ...]."""
    assert len(wrongs) >= 2, qid
    return {"id": qid, "type": "single_choice", "kind": kind, "stem": stem, "correct": correct,
            "distractors": [{"text": t, "why_en": a, "why_zh": b} for t, a, b in wrongs],
            "evidence": [{"ref": r, "excerpt": x} for r, x in evidence], "explanation_en": en, "explanation_zh": zh}


def SA(qid, kind, stem, accepted, evidence, en, zh):
    """Short answer: a reference answer first, then accepted alternatives."""
    return {"id": qid, "type": "short_answer", "kind": kind, "stem": stem, "accepted": accepted,
            "evidence": [{"ref": r, "excerpt": x} for r, x in evidence], "explanation_en": en, "explanation_zh": zh}


def V(fr, en, zh, ref):
    return {"fr": fr, "en": en, "zh": zh, "ref": ref}


def P(*texts):
    return [{"id": f"p{k}", "text": t} for k, t in enumerate(texts, 1)]


def T(*turns):
    return [{"id": f"s{k}", "speaker": s, "text": t} for k, (s, t) in enumerate(turns, 1)]


# ---- productive workbook (writing and speaking) ----

def W(title, fmt, prompt, requirements, word_min, word_max):
    """A writing task in the shape POST /writing/tasks accepts."""
    return {"title": title, "format": fmt, "prompt": prompt, "requirements": list(requirements),
            "word_min": word_min, "word_max": word_max}


def S(title, fmt, situation, requirements, seconds_min, seconds_max):
    """A speaking task in the shape of the speaking prompts (stack tree)."""
    return {"title": title, "format": fmt, "situation": situation, "requirements": list(requirements),
            "seconds_min": seconds_min, "seconds_max": seconds_max}


def A(text, covers, notes):
    """An annotated sample: one possible answer, not the only one.
    covers: [(requirement index from 1, excerpt that shows it)];
    notes: [(excerpt, note_en, note_zh)] on useful expressions."""
    return {"text": text, "covers": [{"requirement": i, "excerpt": x} for i, x in covers],
            "notes": [{"excerpt": x, "en": a, "zh": b} for x, a, b in notes]}


def G(qid, kind, prompt, answer, en, zh, accepted=()):
    """Grammar or vocabulary practice item (fill / transform / choose)."""
    return {"id": qid, "kind": kind, "prompt": prompt, "answer": answer, "accepted": list(accepted),
            "explanation_en": en, "explanation_zh": zh}


def M(wrong, right, en, zh):
    """A common mistake and its correction."""
    return {"wrong": wrong, "right": right, "why_en": en, "why_zh": zh}


def R(draft, corrections):
    """Retry exercise: a learner-like draft with errors; each correction quotes
    a span that occurs exactly once in the draft."""
    return {"draft": draft, "corrections": [{"quote": q, "correction": c, "why_en": a, "why_zh": b}
                                            for q, c, a, b in corrections]}
