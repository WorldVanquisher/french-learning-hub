#!/usr/bin/env python3
"""Seed the synthetic Vocabulary fixture through the server's public API only.

    python3 -I -B scripts/demo/vocabulary/seed.py http://127.0.0.1:PORT

The server must run with EXTRACTOR_PROVIDER=openai pointed at scripts/demo/vocabulary/stub_extractor.py
(no real provider, no key) on a fresh scratch database: the seed refuses a backend that already holds
records or Concepts, and a non-loopback address. Synthetic French only. Saves nothing to Vocabulary:
the walkthrough does that. Prints the facts (record, unit and Concept IDs) as JSON.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) == 2 else ""


def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path}: {e.code} {e.read()[:300]!r}")


def main():
    if not BASE or urllib.parse.urlparse(BASE).hostname not in ("127.0.0.1", "localhost", "::1"):
        print("usage: seed.py http://127.0.0.1:PORT (loopback only)", file=sys.stderr)
        return 2
    if call("GET", "/entries?limit=1")["entries"] or call("GET", "/concepts")["concepts"]:
        print("refused: the backend already holds records or Concepts; seed a fresh scratch database", file=sys.stderr)
        return 2
    facts = {}

    def record(key, text, context):
        e = call("POST", "/entries", {"original_input": text, "original_context": context})
        call("POST", f"/entries/{e['id']}/analysis")
        units = [u["id"] for u in call("POST", f"/entries/{e['id']}/extractions")["units"]]
        facts[f"entry_{key}"] = e["id"]
        return units

    def concept(key, target, seed, scope=""):
        c = call("POST", "/concepts", {"identity": {"target": target, "pedagogical_intent": "vocabulary", "scope": scope, "identity_features": {}},
                                       "seed_unit_id": seed, "link_seed_as_same": True})
        facts[f"concept_{key}"] = c["concept"]["id"]
        return c["concept"]["id"]

    u = record("apporter", "Comment dit-on « bring » quand on va dîner chez des amis ? (apporter le dessert)", "Invitation : « Pouvez-vous apporter le dessert ? »")
    facts["unit_apporter"] = u[0]
    concept("apporter", "apporter", u[0])
    u2 = record("apporter2", "apporter ou amener : quelle différence ?", "Un ami m'a corrigé : on apporte une chose, on amène une personne.")
    facts["unit_apporter2"] = u2[0]
    call("POST", f"/knowledge-units/{u2[0]}/concept-links/same", {"concept_id": facts["concept_apporter"]})
    u = record("grasse", "Que veut dire « faire la grasse matinée » ?", "Le dimanche, je fais la grasse matinée jusqu'à dix heures.")
    facts["unit_grasse"] = u[0]
    concept("grasse", "faire la grasse matinée", u[0])
    u = record("chat_fr", "« le chat dort » : chat veut dire quoi ?", "Le chat dort sur le canapé.")
    facts["unit_chat_fr"] = u[0]
    concept("chat_fr", "chat", u[0], "le mot français: animal")
    u = record("chat_en", "« on a fait un chat en ligne » : c'est de l'anglais ?", "On a fait un chat en ligne hier soir.")
    facts["unit_chat_en"] = u[0]
    concept("chat_en", "chat", u[0], "emprunt anglais: conversation en ligne")
    u = record("auj_typo", "Comment écrire aujourd’hui ?", "Aujourd’hui, il pleut.")
    facts["unit_auj_typo"] = u[0]
    concept("auj_typo", "aujourd’hui", u[0])
    u = record("auj_straight", "Et aujourd'hui avec une apostrophe droite ?", "Aujourd'hui, il fait beau.")
    facts["unit_auj_straight"] = u[0]
    concept("auj_straight", "aujourd'hui", u[0])
    u = record("cafe_nfc", "Commander un café crème", "Au comptoir.")
    facts["unit_cafe_nfc"] = u[0]
    concept("cafe_nfc", "café", u[0])
    u = record("cafe_nfd", "Commander un café noir", "Au comptoir.")
    facts["unit_cafe_nfd"] = u[0]
    concept("cafe_nfd", "café", u[0])
    u = record("long", "« il pleut des cordes » : une expression ?", "Il pleuvait depuis le matin. " * 12)
    facts["unit_long"] = u[0]
    concept("long", "il pleut des cordes, n'est-ce pas ? — « oui » (vraiment) !", u[0])
    u = record("revanche", "« en revanche » : ça veut dire quoi ?", "Il pleut ; en revanche, il fait doux.")
    facts["unit_revanche"] = u[0]
    concept("revanche", "en revanche", u[0])
    u = record("grammar", "accord du participe avec être ?", "Elle est allée.")
    facts["unit_grammar"] = u[0]
    concept("grammar_concept", "accord du participe passé", u[0])
    print(json.dumps(facts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
