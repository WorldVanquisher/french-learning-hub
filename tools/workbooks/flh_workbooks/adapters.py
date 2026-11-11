"""Adapters from the canonical workbook to formats the application already
accepts. Nothing here calls the server; nothing here invents an endpoint.

* reading_pack: the reading passages in flh_reading_pack_v1 form (validated
  by Go `domain.ParseReadingPack` in internal/reading/workbook_adapter_test.go).
  The server embeds only internal/reading/pack/reading_pack_v1.json, so this
  file is NOT importable through the API as it stands; it is ready for a
  future, explicit pack change.
* learner_lessons: request bodies for the existing POST /reading/lessons
  (title, text, source_url). The text splits into the same p1..pN paragraphs,
  so workbook evidence references stay valid. Exercises are not attached:
  that route stores a passage only.
* capture: a learning_capture_v1 document (source manual, no analysis) built
  only when the learner supplies their own question about a workbook item.
  Importing it creates an ordinary learner record; it implies no acceptance,
  review or mastery.
* Listening scripts have no adapter: POST /listening/materials requires a
  YouTube link, and inventing one is not allowed.
"""

import hashlib
import json

PACK_SCHEMA = "flh_reading_pack_v1"
PACK_NOTICE = ("Synthetic practice material from the FLH reading/listening workbook v1 (unreviewed). "
               "Not an official exam item; no certified CEFR level.")
GENRE_FORMAT = {"petite annonce": "classified_ad", "courriel": "email", "programme": "announcement",
                "menu": "notice", "affiche": "notice", "information voyageurs": "notice",
                "offre d'emploi": "classified_ad", "brochure": "newsletter", "conditions de vente": "notice",
                "lettre d'information municipale": "newsletter",
                "page d'information pratique (fictive)": "notice", "alerte d'information (médiathèque)": "notice"}
PACK_KINDS = ("main_idea", "detail", "inference")


def _select(questions):
    """At most 5 single-choice items: the main idea, at most one inference,
    then details, kept in workbook order."""
    sc = [q for q in questions if q["type"] == "single_choice" and q["kind"] in PACK_KINDS]
    main = [q for q in sc if q["kind"] == "main_idea"][:1]
    inf = [q for q in sc if q["kind"] == "inference"][:1]
    det = [q for q in sc if q["kind"] == "detail"][:5 - len(main) - len(inf)]
    keep = {q["id"] for q in main + inf + det}
    return [q for q in sc if q["id"] in keep]


def reading_pack(doc):
    passages = []
    for u in doc["units"]:
        r = u["reading"]
        pid = f"rd-wb1-{u['id']}"
        items = []
        for i, q in enumerate(_select(r["questions"]), 1):
            correct = next(o for o in q["options"] if o["correct"])
            items.append({
                "id": f"{pid}:q{i}", "kind": q["kind"], "question": q["stem"],
                "reference_answer": correct["text"], "accepted_alternatives": [],
                "wrong_answers": [{"answer": o["text"], "why_wrong_en": o["why_wrong_en"], "why_wrong_zh": o["why_wrong_zh"]}
                                  for o in q["options"] if not o["correct"]],
                "evidence": [{"segment": e["ref"], "excerpt": e["excerpt"]} for e in q["evidence"]],
                "explanation_en": q["explanation_en"], "explanation_zh": q["explanation_zh"]})
        p = {"id": pid, "format": GENRE_FORMAT[r["genre"]], "style_level": u["band"], "title": r["title"],
             "source": {"kind": "authored", "pack": "flh_workbook_reading_listening_v1", "link": None, "notice": PACK_NOTICE},
             "segments": [{"id": s["id"], "text": s["text"]} for s in r["segments"]],
             "questions": items}
        if not any(it["kind"] == "inference" for it in items):
            p["no_inference_reason"] = "The workbook unit has no single-choice inference question for this passage."
        passages.append(p)
    return {"schema_version": PACK_SCHEMA, "notice": PACK_NOTICE, "passages": passages}


def learner_lessons(doc):
    return {"schema_version": "flh_workbook_learner_lessons_v1",
            "route": "POST /reading/lessons",
            "note": ("Each body creates a learner reading lesson (passage only). Paragraphs are separated by a blank line, "
                     "so they become p1..pN as in the workbook. No exercise, answer or review is attached."),
            "bodies": [{"workbook_unit": u["id"], "body": {
                "title": u["reading"]["title"],
                "text": "\n\n".join(s["text"] for s in u["reading"]["segments"]),
                "source_url": ""}} for u in doc["units"]]}


def find_question(doc, qid):
    for u in doc["units"]:
        for sec in ("reading", "listening"):
            s = u[sec]
            for q in s["questions"]:
                if q["id"] == qid:
                    return u, sec, s, q
    raise KeyError(qid)


def capture(doc, qid, learner_text):
    """learning_capture_v1 for the learner's own question about one item.
    The learner's words are the original input; the workbook item is context."""
    learner_text = learner_text.strip()
    if not learner_text:
        raise ValueError("the learner's own question is required; it is never generated")
    u, sec, s, q = find_question(doc, qid)
    if q["type"] == "single_choice":
        ref = next(o["text"] for o in q["options"] if o["correct"])
    else:
        ref = q["reference_answer"]
    ev = "; ".join(f'({e["ref"]}) « {e["excerpt"]} »' for e in q["evidence"])
    kind = "Lecture" if sec == "reading" else "Écoute (script écrit, pas d'enregistrement)"
    context = "\n".join([
        f"{kind}: {s['title']}",
        f"Workbook: {doc['workbook_id']} / {u['id']} (synthetic, unreviewed; band {u['band']} is a target, not certified)",
        f"Question {q['id']} ({q['kind']}): {q['stem']}",
        f"Evidence: {ev}",
        f"Reference answer (workbook key, not a human judgment): {ref}"])
    digest = hashlib.sha256(learner_text.encode("utf-8")).hexdigest()[:12]
    return {"schema_version": "learning_capture_v1", "capture_id": f"workbook-rl-v1:{qid}:{digest}",
            "source": "manual", "original_input": learner_text, "original_context": context}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


# ---- productive workbook ----

WRITING_NOTICE = ("Synthetic practice tasks from the FLH productive workbook v1 (unreviewed). Not official exam items; "
                  "no score and no certified CEFR level. Names and places are invented. Each example draft is the "
                  "unit's retry draft and contains deliberate mistakes.")
SPEAKING_NOTICE = ("Synthetic practice prompts from the FLH productive workbook v1 (unreviewed). Not official exam items; "
                   "no score and no certified CEFR level. Names and places are invented; phone numbers use ranges "
                   "reserved for fiction. Each example transcript is the unit's model answer, not a mistake demo. "
                   "Feedback reads a transcript only and cannot judge pronunciation.")
ID_SLUG = {"u01": "colocation", "u02": "retard-train", "u03": "annuler-dentiste", "u04": "candidature-ete",
           "u05": "absence-cours", "u06": "reclamation-colis", "u07": "sortie-quartier", "u08": "mairie-tri",
           "u09": "avis-hotel", "u10": "carte-volee", "u11": "invitation-diner", "u12": "forum-arnaque"}
SP_SLUG = {"u01": "message-visite", "u02": "guichet-train", "u03": "chez-le-medecin", "u04": "entretien",
           "u05": "presentation-cours", "u06": "retour-magasin", "u07": "raconter-soiree", "u08": "reunion-quartier",
           "u09": "reception-hotel", "u10": "verifier-telephone", "u11": "commander-allergie", "u12": "double-authentification"}


def writing_task_bodies(doc):
    return {"schema_version": "flh_workbook_writing_tasks_v1", "route": "POST /writing/tasks",
            "note": ("Each body creates a learner writing task. No draft, feedback, score or review is attached; "
                     "feedback exists only if the learner asks for it and the provider is enabled."),
            "bodies": [{"workbook_unit": u["id"], "body": {k: u["writing"][k] for k in ("title", "prompt", "requirements", "word_min", "word_max")}}
                       for u in doc["units"]]}


def writing_prompt_set(doc):
    return {"schema_version": "flh_writing_prompts_v1", "notice": WRITING_NOTICE,
            "prompts": [{"id": f"wr-wb1-{u['id']}-{ID_SLUG[u['id']]}", "format": u["writing"]["format"],
                         "style_level": u["band"], "title": u["writing"]["title"], "prompt": u["writing"]["prompt"],
                         "requirements": u["writing"]["requirements"], "word_min": u["writing"]["word_min"],
                         "word_max": u["writing"]["word_max"], "example_draft": u["retry"]["draft"]} for u in doc["units"]]}


def speaking_prompt_set(doc):
    return {"schema_version": "flh_speaking_prompts_v1", "notice": SPEAKING_NOTICE,
            "prompts": [{"id": f"sp-wb1-{u['id']}-{SP_SLUG[u['id']]}", "format": u["speaking"]["format"],
                         "style_level": u["band"], "title": u["speaking"]["title"], "situation": u["speaking"]["situation"],
                         "requirements": u["speaking"]["requirements"], "seconds_min": u["speaking"]["seconds_min"],
                         "seconds_max": u["speaking"]["seconds_max"], "example_transcript": u["speaking_sample"]["text"]}
                        for u in doc["units"]]}
