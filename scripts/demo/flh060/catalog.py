"""FLH-060 synthetic catalog additions and demonstration searches.

The FLH-034 seed (scripts/demo/flh034/seed.py, reused unchanged) creates seven
Concepts with records, units and memberships. These eight additions are
Concept-only (no records), created through the public POST /concepts endpoint
on top of it, so every identity rule still applies. They form contrasting
pairs a learner mixes up, with English titles and French examples.

SEARCHES are demonstration inputs for trying the two search modes. They are
NOT labels, expected answers or human ground truth, and no result is checked
against them.
"""

from __future__ import annotations

# (target, pedagogical_intent, scope, identity_features)
ADDITIONS: list[tuple[str, str, str, dict[str, str]]] = [
    ("imparfait for background and habits in the past", "grammar", "",
     {"tense (temps)": "imparfait", "example (exemple)": "quand j'étais petit, il pleuvait souvent"}),
    ("passé composé for a completed past event", "grammar", "",
     {"tense (temps)": "passé composé", "example (exemple)": "hier, il a plu toute la journée"}),
    ("depuis for something still going on", "grammar", "duration (durée)",
     {"preposition": "depuis (since, for)", "example (exemple)": "j'habite ici depuis trois ans"}),
    ("pendant for a finished stretch of time", "grammar", "duration (durée)",
     {"preposition": "pendant (for, during)", "example (exemple)": "j'ai habité à lyon pendant trois ans"}),
    ("ne … plus: no longer", "grammar", "negation (négation)",
     {"negation": "ne … plus", "example (exemple)": "je ne fume plus"}),
    ("ne … pas encore: not yet", "grammar", "negation (négation)",
     {"negation": "ne … pas encore", "example (exemple)": "il n'est pas encore arrivé"}),
    ("the pronoun y for places and à + thing", "grammar", "pronouns (pronoms)",
     {"pronoun (pronom)": "y", "example (exemple)": "j'y vais demain"}),
    ("the pronoun en for quantities and de + thing", "grammar", "pronouns (pronoms)",
     {"pronoun (pronom)": "en", "example (exemple)": "j'en veux deux"}),
]

# Demonstration inputs only (see the module docstring).
SEARCHES: list[str] = [
    "what the weather was like when I was a child",
    "I have lived here for three years and still do",
    "saying I don't do something anymore",
    "how do I tell a friend I miss them",
    "it is necessary that I do my homework",
    "I want two of them",
]

# Keyword search matches words (at most 8 terms per query), so it gets short
# word queries. Also demonstration inputs only.
KEYWORD_SEARCHES: list[str] = ["depuis", "weather", "miss"]


def concept_body(target: str, intent: str, scope: str, features: dict[str, str]) -> dict:
    return {"identity": {"target": target, "pedagogical_intent": intent, "scope": scope,
                         "identity_features": features},
            "seed_unit_id": None, "link_seed_as_same": False}
