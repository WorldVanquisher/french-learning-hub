"""Render a canonical reading/listening workbook to student and teacher
editions (Markdown and printable HTML) and to recording material.

The student edition carries no answer key in any form: no correct-option
marker, no explanations, no distractor reasons, no follow-up answers, no
data attributes, comments, scripts, embedded JSON or extra metadata."""

import html
import json

E = html.escape

BANNER = {
    "fr": "Matériel synthétique, non relu par un enseignant. Niveaux indicatifs, non certifiés.",
    "en": "Synthetic material, not reviewed by a teacher. Levels are targets, not certified.",
    "zh": "合成练习材料，未经教师审核。等级仅为参考，并非认证等级。",
}
NO_AUDIO = {
    "fr": ("Il n'existe pas d'enregistrement audio. Faites lire le script à voix haute par une autre personne "
           "ou enregistrez-le vous-même, puis répondez sans regarder la transcription."),
    "en": ("No audio recording exists. Have someone read the script aloud, or record it yourself, "
           "then answer without looking at the transcript."),
    "zh": "本练习没有录音。请让他人朗读脚本或自行录音，然后在不看文字稿的情况下作答。",
}
KIND_LABEL = {"main_idea": "idée générale", "detail": "détail", "inference": "inférence",
              "vocabulary_in_context": "vocabulaire en contexte"}

CSS = """
:root { --ink:#1d1d1f; --muted:#5b5b66; --line:#c9c9d1; --soft:#f3f3f6; --accent:#1f4e79; --warn:#7a4b00; --warnbg:#fff6e0; --ok:#1d6b33; }
* { box-sizing: border-box; }
html { background:#fff; }
body { margin:0 auto; max-width:46rem; padding:1.25rem 16px 3rem; color:var(--ink); background:#fff;
  font: 11pt/1.5 "Noto Serif","DejaVu Serif",Georgia,serif; }
:lang(zh-Hans) { font-family:"Noto Sans CJK SC","WenQuanYi Zen Hei","Source Han Sans SC","Microsoft YaHei",sans-serif; }
h1 { font-size:1.6rem; line-height:1.25; margin:0 0 .5rem; color:var(--accent); }
h2 { font-size:1.3rem; margin:0 0 .4rem; color:var(--accent); }
h3 { font-size:1.08rem; margin:1.2rem 0 .4rem; border-bottom:1px solid var(--line); padding-bottom:.15rem; }
h4 { font-size:1rem; margin:.9rem 0 .3rem; }
p { margin:.35rem 0; }
.sub { color:var(--muted); font-size:.92rem; }
.banner { border:1px solid #e3c27a; background:var(--warnbg); color:var(--warn); padding:.5rem .7rem; border-radius:4px; font-size:.9rem; margin:.6rem 0; }
.banner p { margin:.15rem 0; }
.goal { background:var(--soft); padding:.5rem .7rem; border-radius:4px; }
.text { border-left:3px solid var(--accent); padding:.2rem 0 .2rem .8rem; margin:.5rem 0; }
.text p { margin:.45rem 0; }
.pn { display:inline-block; min-width:1.9rem; color:var(--muted); font:600 .78rem/1 "DejaVu Sans",sans-serif; }
ol.qs { padding-left:0; list-style:none; margin:.3rem 0; }
li.q { margin:.55rem 0; break-inside:avoid; page-break-inside:avoid; }
.qn { font-weight:700; margin-right:.3rem; }
.qk { color:var(--muted); font-size:.8rem; }
ul.opts { list-style:none; padding-left:1.4rem; margin:.2rem 0; }
ul.opts li { margin:.1rem 0; }
.key { display:inline-block; width:1.5rem; font-weight:700; }
.blank { display:inline-block; min-width:60%; border-bottom:1px solid var(--ink); height:1.1rem; vertical-align:bottom; }
.speakers { font-size:.92rem; }
table { border-collapse:collapse; width:100%; font-size:.9rem; margin:.4rem 0; }
th, td { border:1px solid var(--line); padding:.25rem .4rem; text-align:left; vertical-align:top; }
th { background:var(--soft); }
.unit { margin-top:2rem; }
.correct { color:var(--ok); font-weight:700; }
.why { color:var(--muted); font-size:.9rem; }
.tk { background:var(--soft); border-radius:4px; padding:.35rem .6rem; margin:.25rem 0 .2rem 1.4rem; font-size:.92rem; }
.turn { margin:.3rem 0; }
.spk { font-weight:700; }
nav ol { columns:2; font-size:.95rem; }
@media (max-width: 30rem) { body { font-size:10.5pt; } nav ol { columns:1; } .blank { min-width:80%; } }
@page { size:A4; margin:15mm 14mm 16mm; }
@media print {
  body { max-width:none; padding:0; }
  .unit, .appendix { break-before:page; page-break-before:always; margin-top:0; }
  h2, h3, h4 { break-after:avoid; page-break-after:avoid; }
  .text p, .turn, tr { break-inside:avoid; }
}
"""


def _zh(s):
    return f'<span lang="zh-Hans">{E(s)}</span>'


def _banner():
    return ('<div class="banner">'
            f'<p lang="fr">{E(BANNER["fr"])}</p><p lang="en">{E(BANNER["en"])}</p><p>{_zh(BANNER["zh"])}</p></div>')


def _page(title, body):
    return ('<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{E(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n')


def _segments_html(segs):
    return '<div class="text">' + "".join(
        f'<p><span class="pn">¶{E(s["id"][1:])}</span>{E(s["text"])}</p>' for s in segs) + "</div>"


def _turns_html(sec):
    labels = {s["id"]: s["label"] for s in sec["speakers"]}
    return "".join(f'<p class="turn"><span class="pn">{E(t["id"])}</span><span class="spk">{E(labels[t["speaker"]])} :</span> {E(t["text"])}</p>'
                   for t in sec["turns"])


def _question_html(n, q, teacher):
    out = [f'<li class="q"><span class="qn">{n}.</span>{E(q["stem"])}']
    if teacher:
        out.append(f' <span class="qk">[{E(q["id"])} · {E(KIND_LABEL.get(q["kind"], q["kind"]))}]</span>')
    if q["type"] == "single_choice":
        out.append('<ul class="opts">')
        for o in q["options"]:
            if teacher and o["correct"]:
                out.append(f'<li class="correct"><span class="key">{o["key"]}</span>{E(o["text"])} ✓</li>')
            else:
                out.append(f'<li><span class="key">{o["key"]}</span>{E(o["text"])}</li>')
        out.append("</ul>")
    else:
        out.append('<p>Réponse : <span class="blank"></span></p>')
    if teacher:
        ev = " · ".join(f'{E(e["ref"])} « {E(e["excerpt"])} »' for e in q["evidence"])
        out.append('<div class="tk">')
        if q["type"] == "single_choice":
            out.append(f'<p><b>Réponse : {q["answer"]}</b></p>')
        else:
            alts = "".join(f" / {E(a)}" for a in q["accepted_alternatives"])
            out.append(f'<p><b>Réponse : {E(q["reference_answer"])}</b>{alts}</p>')
        out.append(f'<p>Preuve : {ev}</p><p lang="en">{E(q["explanation_en"])}</p><p>{_zh(q["explanation_zh"])}</p>')
        for o in q.get("options", []):
            if not o["correct"]:
                out.append(f'<p class="why">{o["key"]} — <span lang="en">{E(o["why_wrong_en"])}</span> {_zh(o["why_wrong_zh"])}</p>')
        out.append("</div>")
    out.append("</li>")
    return "".join(out)


def _follow_up_html(fu, teacher):
    out = [f'<h4>Prolongement</h4><p lang="en">{E(fu["instructions_en"])}</p><p>{_zh(fu["instructions_zh"])}</p>',
           '<table><thead><tr><th>Item</th><th>Votre réponse</th></tr></thead><tbody>' if not teacher else
           '<table><thead><tr><th>Item</th><th>Réponse attendue (exemple)</th></tr></thead><tbody>']
    for it in fu["items"]:
        right = E(it["answer"]) if teacher else "&nbsp;"
        out.append(f'<tr><td>{E(it["prompt"])}</td><td>{right}</td></tr>')
    out.append("</tbody></table>")
    return "".join(out)


def _vocab_html(vocab):
    rows = "".join(f'<tr><td lang="fr">{E(v["fr"])}</td><td lang="en">{E(v["en"])}</td><td>{_zh(v["zh"])}</td><td>{E(v["ref"])}</td></tr>'
                   for v in vocab)
    return ('<h4>Vocabulaire</h4><table><thead><tr><th>Français</th><th>English</th><th>中文</th><th>Réf.</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def _speakers_html(sec):
    rows = "".join(f'<tr><td>{E(s["id"])}</td><td>{E(s["label"])}</td><td>{E(s["voice"])}</td></tr>' for s in sec["speakers"])
    return f'<table class="speakers"><thead><tr><th>Id</th><th>Personnage</th><th>Voix (consigne)</th></tr></thead><tbody>{rows}</tbody></table>'


def rl_html(doc, teacher):
    ed = "livre du professeur" if teacher else "cahier de l'élève"
    t = doc["title"]
    body = [f'<header><h1>{E(t["fr"])}</h1><p class="sub" lang="en">{E(t["en"])}</p><p class="sub">{_zh(t["zh"])}</p>',
            f'<p><b>{E(ed.capitalize())}</b></p>', _banner(),
            f'<p class="sub">{E(doc["notices"]["fictional"])}</p>',
            f'<p class="sub">{E(doc["notices"]["telephone"])} {E(doc["notices"]["real_reference"])}</p>',
            f'<div class="banner"><p lang="fr">{E(NO_AUDIO["fr"])}</p><p lang="en">{E(NO_AUDIO["en"])}</p><p>{_zh(NO_AUDIO["zh"])}</p></div>',
            '</header><nav><h3>Sommaire</h3><ol>']
    body += [f'<li>Unité {int(u["id"][1:])} — {E(u["theme"])} ({E(u["band"])})</li>' for u in doc["units"]]
    body.append("</ol></nav>")
    for u in doc["units"]:
        g = u["goal"]
        body.append(f'<section class="unit"><h2>Unité {int(u["id"][1:])} — {E(u["theme"])}</h2>'
                    f'<p class="sub">Niveau visé (indicatif) : {E(u["band"])} · synthétique, non relu</p>'
                    f'<div class="goal"><p><b>Objectif :</b> {E(g["fr"])}</p><p lang="en">{E(g["en"])}</p><p>{_zh(g["zh"])}</p>'
                    f'<p class="sub">Prérequis : {E(" · ".join(u["prerequisites"]))}</p></div>')
        r = u["reading"]
        body.append(f'<h3>A. Lecture — {E(r["title"])}</h3><p class="sub">{E(r["genre"])}</p>{_segments_html(r["segments"])}')
        body.append('<ol class="qs">' + "".join(_question_html(i, q, teacher) for i, q in enumerate(r["questions"], 1)) + "</ol>")
        l = u["listening"]
        body.append(f'<h3>B. Écoute — {E(l["title"])}</h3><p class="sub">{E(l["genre"])} · script écrit, pas d\'enregistrement</p>')
        if teacher:
            body.append("<h4>Personnages et consignes de voix</h4>" + _speakers_html(l) + "<h4>Script</h4>" + _turns_html(l))
        else:
            body.append(f'<p class="sub">Transcription : annexe, unité {int(u["id"][1:])}. À lire seulement après avoir répondu.</p>')
        body.append('<ol class="qs">' + "".join(_question_html(i, q, teacher) for i, q in enumerate(l["questions"], 1)) + "</ol>")
        body.append(_follow_up_html(u["follow_up"], teacher) + _vocab_html(u["vocabulary"]) + "</section>")
    if not teacher:
        body.append('<section class="appendix"><h2>Annexe — transcriptions des écoutes</h2>'
                    '<p class="sub">Scripts écrits, non enregistrés. À lire après avoir répondu.</p>')
        for u in doc["units"]:
            l = u["listening"]
            body.append(f'<h3>Unité {int(u["id"][1:])} — {E(l["title"])}</h3>{_turns_html(l)}')
        body.append("</section>")
    return _page(f'{t["fr"]} — {ed}', "\n".join(body))


# ---------- Markdown ----------

def _md_question(n, q, teacher):
    lines = [f'{n}. {q["stem"]}' + (f'  _[{q["id"]} · {KIND_LABEL.get(q["kind"], q["kind"])}]_' if teacher else "")]
    if q["type"] == "single_choice":
        for o in q["options"]:
            mark = " ✓" if teacher and o["correct"] else ""
            lines.append(f'   - {o["key"]}. {o["text"]}{mark}')
    else:
        lines.append("   - Réponse : ______________________")
    if teacher:
        ans = q["answer"] if q["type"] == "single_choice" else " / ".join([q["reference_answer"]] + q["accepted_alternatives"])
        lines.append(f'   - **Réponse : {ans}**')
        lines.append("   - Preuve : " + " · ".join(f'{e["ref"]} « {e["excerpt"]} »' for e in q["evidence"]))
        lines.append(f'   - EN: {q["explanation_en"]}')
        lines.append(f'   - 中文：{q["explanation_zh"]}')
        for o in q.get("options", []):
            if not o["correct"]:
                lines.append(f'   - {o["key"]} — {o["why_wrong_en"]} {o["why_wrong_zh"]}')
    return lines


def rl_markdown(doc, teacher):
    ed = "Livre du professeur" if teacher else "Cahier de l'élève"
    t = doc["title"]
    out = [f'# {t["fr"]} — {ed}', "", f'_{t["en"]}_ · {t["zh"]}', "",
           f'> **{BANNER["fr"]}**  ', f'> {BANNER["en"]}  ', f'> {BANNER["zh"]}', "",
           f'> {NO_AUDIO["fr"]}  ', f'> {NO_AUDIO["en"]}  ', f'> {NO_AUDIO["zh"]}', "",
           doc["notices"]["fictional"], "", doc["notices"]["telephone"] + " " + doc["notices"]["real_reference"], ""]
    for u in doc["units"]:
        g = u["goal"]
        out += [f'## Unité {int(u["id"][1:])} — {u["theme"]}', "",
                f'Niveau visé (indicatif) : {u["band"]} · synthétique, non relu', "",
                f'**Objectif :** {g["fr"]}  ', g["en"] + "  ", g["zh"], "",
                "Prérequis : " + " · ".join(u["prerequisites"]), ""]
        r = u["reading"]
        out += [f'### A. Lecture — {r["title"]}', "", f'_{r["genre"]}_', ""]
        out += [f'> ¶{s["id"][1:]} {s["text"]}\n>' for s in r["segments"]]
        out.append("")
        for i, q in enumerate(r["questions"], 1):
            out += _md_question(i, q, teacher)
        l = u["listening"]
        labels = {s["id"]: s["label"] for s in l["speakers"]}
        out += ["", f'### B. Écoute — {l["title"]}', "", f'_{l["genre"]} · script écrit, pas d\'enregistrement_', ""]
        if teacher:
            out += ["| Id | Personnage | Voix (consigne) |", "|---|---|---|"]
            out += [f'| {s["id"]} | {s["label"]} | {s["voice"]} |' for s in l["speakers"]]
            out += [""] + [f'- {t["id"]} **{labels[t["speaker"]]} :** {t["text"]}' for t in l["turns"]] + [""]
        else:
            out += [f'Transcription : annexe, unité {int(u["id"][1:])}. À lire seulement après avoir répondu.', ""]
        for i, q in enumerate(l["questions"], 1):
            out += _md_question(i, q, teacher)
        fu = u["follow_up"]
        out += ["", "#### Prolongement", "", fu["instructions_en"] + "  ", fu["instructions_zh"], ""]
        out += [f'- {it["prompt"]} → ' + (it["answer"] if teacher else "______________") for it in fu["items"]]
        out += ["", "#### Vocabulaire", "", "| Français | English | 中文 | Réf. |", "|---|---|---|---|"]
        out += [f'| {v["fr"]} | {v["en"]} | {v["zh"]} | {v["ref"]} |' for v in u["vocabulary"]]
        out.append("")
    if not teacher:
        out += ["## Annexe — transcriptions des écoutes", "", "_Scripts écrits, non enregistrés. À lire après avoir répondu._", ""]
        for u in doc["units"]:
            l = u["listening"]
            labels = {s["id"]: s["label"] for s in l["speakers"]}
            out += [f'### Unité {int(u["id"][1:])} — {l["title"]}', ""]
            out += [f'- {t["id"]} **{labels[t["speaker"]]} :** {t["text"]}' for t in l["turns"]] + [""]
    return "\n".join(out).rstrip() + "\n"


# ---------- recording material ----------

def recording_script_md(doc):
    out = ["# Scripts d'écoute — à enregistrer", "",
           "Statut : **scripts écrits, aucun enregistrement n'existe**. Pas d'horodatage : les numéros s1, s2… "
           "repèrent des répliques, pas des temps. Synthetic, unreviewed.", ""]
    for u in doc["units"]:
        l = u["listening"]
        labels = {s["id"]: s["label"] for s in l["speakers"]}
        out += [f'## {l["id"]} — {l["title"]}', "", f'Genre : {l["genre"]} · niveau visé {u["band"]} (indicatif)', "",
                "| Id | Personnage | Consigne de voix |", "|---|---|---|"]
        out += [f'| {s["id"]} | {s["label"]} | {s["voice"]} |' for s in l["speakers"]]
        out += [""] + [f'{t["id"]}. [{t["speaker"]}] {labels[t["speaker"]]} : {t["text"]}' for t in l["turns"]] + [""]
    return "\n".join(out).rstrip() + "\n"


def tts_script_json(doc):
    scripts = []
    for u in doc["units"]:
        l = u["listening"]
        scripts.append({"id": l["id"], "unit": u["id"], "title": l["title"], "genre": l["genre"],
                        "speakers": l["speakers"],
                        "turns": [{"id": t["id"], "speaker": t["speaker"], "text": t["text"]} for t in l["turns"]],
                        "recorded": False, "audio": None})
    return json.dumps({"schema_version": "flh_listening_script_v1", "workbook_id": doc["workbook_id"],
                       "status": {"synthetic": True, "human_reviewed": False, "recorded": False,
                                  "timestamps": None,
                                  "note": "Text and voice directions only. No audio, timing or quality evidence exists."},
                       "scripts": scripts}, ensure_ascii=False, indent=1) + "\n"


PRODUCTION_CHECKLIST = """# Listening production checklist (not started)

Nothing on this list has been done. No audio exists for this workbook.

## Before recording
- [ ] A French-speaking reviewer reads every script aloud and fixes unnatural lines; record the change list.
- [ ] Confirm the answer key still matches the edited scripts (rerun `python3 -m flh_workbooks check`).
- [ ] Choose voices that match each speaker's direction (`listening_scripts_v1.json`, `speakers[].voice`).
- [ ] For human voices: written consent for recording, editing and the intended use.
- [ ] For synthetic (TTS) voices: confirm the voice licence allows this use and label the audio as synthetic.

## Recording
- [ ] One file per script, named `<script id>.<ext>` (for example `u07-l.flac`); keep the raw take.
- [ ] Quiet room, consistent microphone distance, no background music under speech.
- [ ] Natural pace for the target band; do not slow A2 scripts artificially.
- [ ] Keep repairs and hesitations written in the script (for example « dimanche… euh, non, samedi »): they are tested.

## After recording
- [ ] A listener who did not read the script answers the questions; note any item that becomes ambiguous.
- [ ] Only then add timing: measure real timestamps from the audio. Never copy or estimate them from the script.
- [ ] Update `recorded`, `audio` and any timing fields only for files that actually exist.
- [ ] Keep the "synthetic, unreviewed" labels until a human review is recorded.
"""


# ---------- productive workbook (writing and speaking) ----------

PW_EXTRA_CSS = """
.lines { margin:.4rem 0 .8rem; }
.lines div { border-bottom:1px solid var(--line); height:1.9rem; }
.chk td, .chk th { text-align:center; }
.chk td:first-child { text-align:left; }
.draft { background:var(--soft); border-radius:4px; padding:.5rem .7rem; white-space:pre-wrap; }
.sample { border:1px solid var(--line); border-radius:4px; padding:.5rem .7rem; white-space:pre-wrap; }
"""


def _reqs_html(reqs):
    return "<ol>" + "".join(f"<li>{E(r)}</li>" for r in reqs) + "</ol>"


def _rubric_html(doc):
    rb = doc["rubric"]
    head = "".join(f'<th>{E(l["fr"])}<br><span lang="en">{E(l["en"])}</span><br>{_zh(l["zh"])}</th>' for l in rb["levels"])
    rows = []
    for c in rb["criteria"]:
        applies = " · ".join({"writing": "écrit", "speaking": "oral"}[a] for a in c["applies_to"])
        cells = "".join(f'<td><span lang="en">{E(c["descriptors"][l["id"]]["en"])}</span><br>{_zh(c["descriptors"][l["id"]]["zh"])}</td>'
                        for l in rb["levels"])
        rows.append(f'<tr><td><b>{E(c["fr"])}</b><br><span lang="en">{E(c["en"])}</span><br>{_zh(c["zh"])}<br><span class="sub">{applies}</span></td>{cells}</tr>')
    return (f'<h3>Grille d\'auto-évaluation</h3><p lang="en">{E(rb["notice"]["en"])}</p><p>{_zh(rb["notice"]["zh"])}</p>'
            f'<table><thead><tr><th>Critère</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>')


def _checklist_html(doc, kind):
    rb = doc["rubric"]
    head = "".join(f"<th>{E(l['fr'])}</th>" for l in rb["levels"])
    rows = "".join(f"<tr><td>{E(c['fr'])}</td>" + "<td>☐</td>" * len(rb["levels"]) + "</tr>"
                   for c in rb["criteria"] if kind in c["applies_to"])
    return f'<table class="chk"><thead><tr><th>Critère</th>{head}</tr></thead><tbody>{rows}</tbody></table>'


def _sample_html(label, s, reqs):
    cov = "".join(f'<li>{E(reqs[c["requirement"] - 1])} — « {E(c["excerpt"])} »</li>' for c in s["covers"])
    notes = "".join(f'<li>« {E(n["excerpt"])} » — <span lang="en">{E(n["en"])}</span> {_zh(n["zh"])}</li>' for n in s["notes"])
    return (f'<h4>{E(label)} (un exemple possible, pas la seule réponse)</h4><div class="sample">{E(s["text"])}</div>'
            f'<p><b>Points traités</b></p><ul>{cov}</ul><p><b>Expressions utiles</b></p><ul>{notes}</ul>')


def pw_html(doc, teacher):
    ed = "livre du professeur" if teacher else "cahier de l'élève"
    t = doc["title"]
    n = doc["notices"]
    body = [f'<header><h1>{E(t["fr"])}</h1><p class="sub" lang="en">{E(t["en"])}</p><p class="sub">{_zh(t["zh"])}</p>',
            f'<p><b>{E(ed.capitalize())}</b></p>', _banner(),
            f'<p class="sub">{E(n["fictional"])} {E(n["telephone"])} {E(n["real_reference"])}</p>',
            f'<p class="sub">{E(n["speaking"])}</p>']
    if not teacher:
        body.append('<p class="sub">Les exemples de réponses et les corrigés se trouvent dans le livre du professeur.</p>')
    body.append('<h3>Après une tâche : vos actions, rien d\'automatique</h3><ol>')
    body += [f'<li><span lang="en">{E(w["en"])}</span><br>{_zh(w["zh"])}</li>' for w in doc["workflow"]]
    body.append("</ol>" + _rubric_html(doc) + '</header><nav><h3>Sommaire</h3><ol>')
    body += [f'<li>Unité {int(u["id"][1:])} — {E(u["theme"])} ({E(u["band"])})</li>' for u in doc["units"]]
    body.append("</ol></nav>")
    for u in doc["units"]:
        g, w, s = u["goal"], u["writing"], u["speaking"]
        body.append(f'<section class="unit"><h2>Unité {int(u["id"][1:])} — {E(u["theme"])}</h2>'
                    f'<p class="sub">Niveau visé (indicatif) : {E(u["band"])} · synthétique, non relu</p>'
                    f'<div class="goal"><p><b>Objectif :</b> {E(g["fr"])}</p><p lang="en">{E(g["en"])}</p><p>{_zh(g["zh"])}</p></div>')
        body.append(f'<h3>A. Écrire — {E(w["title"])}</h3><p class="sub">{E(w["format"])} · {w["word_min"]}–{w["word_max"]} mots</p>'
                    f'<p>{E(w["prompt"])}</p>{_reqs_html(w["requirements"])}')
        if teacher:
            body.append(_sample_html("Exemple de réponse écrite", u["writing_sample"], w["requirements"]))
        else:
            lines = 10 if w["word_max"] <= 90 else 14
            body.append('<div class="lines">' + "<div></div>" * lines + "</div>")
        body.append(_checklist_html(doc, "writing"))
        body.append(f'<h3>B. Parler — {E(s["title"])}</h3><p class="sub">{E(s["format"])} · {s["seconds_min"]}–{s["seconds_max"]} secondes · pas d\'enregistrement fourni</p>'
                    f'<p>{E(s["situation"])}</p>{_reqs_html(s["requirements"])}')
        if teacher:
            body.append(_sample_html("Exemple de transcription", u["speaking_sample"], s["requirements"]))
        body.append(_checklist_html(doc, "speaking"))
        body.append('<h3>C. Grammaire et vocabulaire</h3><ol class="qs">')
        for i, p in enumerate(u["practice"], 1):
            body.append(f'<li class="q"><span class="qn">{i}.</span>{E(p["prompt"])}')
            if teacher:
                alts = "".join(f" / {E(a)}" for a in p["accepted"])
                body.append(f'<div class="tk"><p><b>Réponse : {E(p["answer"])}</b>{alts}</p><p lang="en">{E(p["explanation_en"])}</p><p>{_zh(p["explanation_zh"])}</p></div>')
            else:
                body.append('<p>Réponse : <span class="blank"></span></p>')
            body.append("</li>")
        body.append("</ol><h3>D. Erreurs fréquentes</h3><table><thead><tr><th>À éviter</th><th>Correct</th><th>Pourquoi</th></tr></thead><tbody>")
        body += [f'<tr><td>{E(m["wrong"])}</td><td>{E(m["right"])}</td><td><span lang="en">{E(m["why_en"])}</span><br>{_zh(m["why_zh"])}</td></tr>'
                 for m in u["mistakes"]]
        r = u["retry"]
        body.append(f'</tbody></table><h3>E. Réécriture</h3><p>Ce brouillon contient {len(r["corrections"])} erreurs. Trouvez-les et réécrivez le texte.</p>'
                    f'<div class="draft">{E(r["draft"])}</div>')
        if teacher:
            body.append('<table><thead><tr><th>Erreur</th><th>Correction</th><th>Pourquoi</th></tr></thead><tbody>')
            body += [f'<tr><td>{E(c["quote"])}</td><td>{E(c["correction"])}</td><td><span lang="en">{E(c["why_en"])}</span><br>{_zh(c["why_zh"])}</td></tr>'
                     for c in r["corrections"]]
            body.append(f'</tbody></table><p><b>Texte corrigé</b></p><div class="sample">{E(r["corrected"])}</div>')
        else:
            body.append('<div class="lines">' + "<div></div>" * 6 + "</div>")
        body.append("</section>")
    page = _page(f'{t["fr"]} — {ed}', "\n".join(body))
    return page.replace("</style>", PW_EXTRA_CSS + "</style>", 1)


def pw_markdown(doc, teacher):
    ed = "Livre du professeur" if teacher else "Cahier de l'élève"
    t, n = doc["title"], doc["notices"]
    out = [f'# {t["fr"]} — {ed}', "", f'_{t["en"]}_ · {t["zh"]}', "",
           f'> **{BANNER["fr"]}**  ', f'> {BANNER["en"]}  ', f'> {BANNER["zh"]}', "",
           n["fictional"] + " " + n["telephone"] + " " + n["real_reference"], "", n["speaking"], ""]
    if not teacher:
        out += ["Les exemples de réponses et les corrigés se trouvent dans le livre du professeur.", ""]
    out += ["## Après une tâche : vos actions, rien d'automatique", ""]
    out += [f'{i}. {w["en"]} {w["zh"]}' for i, w in enumerate(doc["workflow"], 1)]
    rb = doc["rubric"]
    out += ["", "## Grille d'auto-évaluation", "", rb["notice"]["en"], "", rb["notice"]["zh"], "",
            "| Critère | " + " | ".join(l["fr"] for l in rb["levels"]) + " |", "|---" * (len(rb["levels"]) + 1) + "|"]
    out += [f'| {c["fr"]} ({c["en"]}) | ' + " | ".join(c["descriptors"][l["id"]]["en"] for l in rb["levels"]) + " |" for c in rb["criteria"]]
    out.append("")
    for u in doc["units"]:
        w, s, r = u["writing"], u["speaking"], u["retry"]
        out += [f'## Unité {int(u["id"][1:])} — {u["theme"]}', "", f'Niveau visé (indicatif) : {u["band"]} · synthétique, non relu', "",
                f'**Objectif :** {u["goal"]["fr"]}  ', u["goal"]["en"] + "  ", u["goal"]["zh"], "",
                f'### A. Écrire — {w["title"]}', "", f'_{w["format"]} · {w["word_min"]}–{w["word_max"]} mots_', "", w["prompt"], ""]
        out += [f"{i}. {x}" for i, x in enumerate(w["requirements"], 1)] + [""]
        if teacher:
            out += ["**Exemple de réponse (un exemple possible, pas la seule réponse)**", "", "```text", u["writing_sample"]["text"], "```", ""]
            out += [f'- {w["requirements"][c["requirement"] - 1]} — « {c["excerpt"]} »' for c in u["writing_sample"]["covers"]] + [""]
        out += [f'### B. Parler — {s["title"]}', "", f'_{s["format"]} · {s["seconds_min"]}–{s["seconds_max"]} secondes · pas d\'enregistrement fourni_', "", s["situation"], ""]
        out += [f"{i}. {x}" for i, x in enumerate(s["requirements"], 1)] + [""]
        if teacher:
            out += ["**Exemple de transcription (un exemple possible)**", "", "```text", u["speaking_sample"]["text"], "```", ""]
        out += ["### C. Grammaire et vocabulaire", ""]
        for i, p in enumerate(u["practice"], 1):
            out.append(f'{i}. {p["prompt"]}' + (f'  \n   **{p["answer"]}**' + "".join(f" / {a}" for a in p["accepted"])
                                                   + f' — {p["explanation_en"]} {p["explanation_zh"]}' if teacher else "  \n   Réponse : ______"))
        out += ["", "### D. Erreurs fréquentes", "", "| À éviter | Correct | Pourquoi |", "|---|---|---|"]
        out += [f'| {m["wrong"]} | {m["right"]} | {m["why_en"]} {m["why_zh"]} |' for m in u["mistakes"]]
        out += ["", "### E. Réécriture", "", f'Ce brouillon contient {len(r["corrections"])} erreurs. Trouvez-les et réécrivez le texte.', "",
                "```text", r["draft"], "```", ""]
        if teacher:
            out += ["| Erreur | Correction | Pourquoi |", "|---|---|---|"]
            out += [f'| {c["quote"]} | {c["correction"]} | {c["why_en"]} {c["why_zh"]} |' for c in r["corrections"]]
            out += ["", "```text", r["corrected"], "```", ""]
    return "\n".join(out).rstrip() + "\n"
