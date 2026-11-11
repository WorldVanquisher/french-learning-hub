"""Learning-point record used by the training and evaluation banks.

A point is one learning objective with the expected unit and the material a
generator needs to build varied interactions around it:
  bad / good  a wrong sentence and its correction (the objective's contrast)
  q_fr, q_en  a learner question in French and in English
  expl        an English explanation an analysis could have given
  focus       what the learner doubted, in French (for minimal pairs)
  myth        a learner misconception, in the learner's voice (optional)
  group       a topic group: two points of one group are never combined
"""

from common import KINDS, CATEGORIES

BANDS = ("A1", "A2", "B1")


def P(id, band, topic, kind, cat, canonical, en, zh, ex, bad, good, q_fr, q_en, expl, focus=None, myth=None, group=None):
    if band not in BANDS or kind not in KINDS or cat not in CATEGORIES:
        raise ValueError(f"{id}: bad band/kind/category")
    for name, v in (("bad", bad), ("good", good)):
        if not v or v.strip() != v:
            raise ValueError(f"{id}: {name}")
    if bad == good:
        raise ValueError(f"{id}: bad == good")
    return {"id": id, "band": band, "topic": topic, "kind": kind, "category": cat, "canonical": canonical,
            "en": en, "zh": zh, "example": ex, "bad": bad, "good": good, "q_fr": q_fr, "q_en": q_en,
            "expl": expl, "focus": focus, "myth": myth, "group": group or id}
