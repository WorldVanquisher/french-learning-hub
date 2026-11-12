"""Ten-minute study packs for listening units: per pack, a student checklist,
a reader sheet and a teacher debrief, plus a verification report.

Inputs are the canonical workbook (content/workbooks/reading_listening_v1.json)
and hand-written pack files (content/workbooks/study_packs/<unit>_v1.json),
each with its own practice goal, the questions it focuses on, a ten-minute
plan, the debrief prompts and a short authored transfer exercise. Nothing here
calls a provider or the server, and nothing makes audio: a person reads the
script aloud. Output is deterministic: the same inputs give the same bytes.

verify() checks, for the unit and the transfer exercise, that:
  * every evidence excerpt occurs exactly once in its cited line;
  * a single-choice item has exactly one correct option, and every wrong
    option has an English and a Chinese reason citing lines that exist;
  * numbers and clock times in explanations and reasons occur in the script.
    A time or number found only elsewhere (e.g. the unit's reading brochure)
    is FLAGGED with where it was found: the debrief shows the flag, and the
    teacher decides. A fact found only in the unit's reading text is an
    ERROR: the pack would rely on something the listener never hears (a
    context line read aloud before the dialogue counts as heard). A fact
    found nowhere (e.g. 8:15 computed from 7:00 plus an hour and a quarter)
    stays a flag. The canonical workbook is never rewritten here.
The student checklist and reader sheet must hold no key: build() runs the
workbook's key-exposure scanner on them and the teacher debrief must fail it
(positive control). The checklist must not contain the script, an evidence
excerpt (unless the stem or an option already shows those words), a
reference answer, a reason or the transfer key either.
"""

import html
import json
import re

from . import model, render, scan

E = html.escape
PACKS = model.CONTENT / "study_packs"
REF = re.compile(r"(?<![A-Za-z0-9])([st])(\d+)(?!\d)")
TIME = re.compile(r"(?<!\d)(\d{1,2})\s?(?::|h|点)\s?(\d{2})(?:分)?(?!\d)")
HOURS = re.compile(r"(?<![\d:])(\d{1,2})\s?heures?(?!\s?\d)")  # « 9 heures » is 9:00
NUMBER = re.compile(r"(?<![A-Za-z0-9])\d+(?!\d)")


def pack_units():
    """The units that have a study pack, in file-name order."""
    return sorted(p.name[: -len("_v1.json")] for p in PACKS.glob("*_v1.json"))


def load_pack(unit_id):
    p = PACKS / f"{unit_id}_v1.json"
    pack = json.loads(p.read_text(encoding="utf-8"))
    if pack.get("schema_version") != "flh_study_pack_v1" or pack.get("unit") != unit_id or pack.get("section") != "listening":
        raise ValueError(f"{p.name}: expected flh_study_pack_v1 for listening unit {unit_id}")
    if sum(step["minutes"] for step in pack["plan"]) != 10:
        raise ValueError(f"{p.name}: the plan must add up to ten minutes")
    if not all(pack.get("goal", {}).get(k) for k in ("fr", "en", "zh")) or not pack.get("focus") or not pack.get("debrief"):
        raise ValueError(f"{p.name}: a pack needs a goal (fr, en, zh), focus questions and debrief prompts")
    return pack


def find_unit(doc, unit_id):
    for u in doc["units"]:
        if u["id"] == unit_id:
            return u
    raise KeyError(unit_id)


def _times(s):
    return {f"{int(h)} h {m}" for h, m in TIME.findall(s)} | {f"{int(h)} h 00" for h in HOURS.findall(s)}


def _numbers(s):
    return set(NUMBER.findall(TIME.sub(" ", REF.sub(" ", s))))


def _check_block(where, prefix, lines, questions, elsewhere):
    """Check one script (unit or transfer). lines: id -> text; elsewhere: id -> text
    searched to say where an unsupported fact comes from."""
    errors, flags, rows = [], [], []
    script = " ".join(lines.values())
    script_times, script_numbers = _times(script), _numbers(script)
    for q in questions:
        row = {"id": q["id"], "type": q["type"], "evidence": [], "reasons": [], "facts": []}
        for e in q["evidence"]:
            n = lines.get(e["ref"], "").count(e["excerpt"])
            row["evidence"].append((e["ref"], e["excerpt"], n))
            if n != 1:
                errors.append(f"{where} {q['id']}: evidence « {e['excerpt']} » occurs {n} times in {e['ref']}")
        texts = [("explanation_en", q["explanation_en"]), ("explanation_zh", q["explanation_zh"])]
        if q["type"] == "single_choice":
            correct = [o for o in q["options"] if o["correct"]]
            if len(correct) != 1:
                errors.append(f"{where} {q['id']}: {len(correct)} correct options")
            for o in q["options"]:
                if o["correct"]:
                    continue
                for lang in ("en", "zh"):
                    reason = o.get(f"why_wrong_{lang}", "")
                    refs = [f"{p}{n}" for p, n in REF.findall(reason)]
                    ok = bool(reason) and bool(refs) and all(r.startswith(prefix) and r in lines and r != "context" for r in refs)
                    row["reasons"].append((o["key"], lang, refs, ok))
                    if not ok:
                        errors.append(f"{where} {q['id']} option {o['key']}: the {lang} reason must cite existing lines ({refs})")
                    texts.append((f"why_wrong_{lang} {o['key']}", reason))
        elif not q.get("reference_answer"):
            errors.append(f"{where} {q['id']}: a short answer needs a reference answer")
        for field, s in texts:
            missing = sorted(_times(s) - script_times) + sorted(_numbers(s) - script_numbers)
            for fact in missing:
                found = [k for k, v in elsewhere.items() if fact in _times(v) | _numbers(v)]
                flag = {"where": where, "id": q["id"], "field": field, "fact": fact, "found_in": found}
                flags.append(flag)
                row["facts"].append(flag)
        rows.append(row)
    return errors, flags, rows


def verify(doc, pack):
    u = find_unit(doc, pack["unit"])
    L = u["listening"]
    lines = {t["id"]: t["text"] for t in L["turns"]}
    reading = {s["id"]: s["text"] for s in u["reading"]["segments"]}
    context_errors = []
    ctx = pack.get("context")
    if ctx:
        # The reader's context line quotes the unit's own reading text verbatim; it
        # is heard before the dialogue, so facts it states count as heard.
        if reading.get(ctx["source"], "").count(ctx["excerpt"]) != 1 or ctx["excerpt"] not in ctx["fr"]:
            context_errors.append(f"context: « {ctx['excerpt']} » must occur once in {ctx['source']} and in the context line")
        lines = {"context": ctx["fr"], **lines}
    e1, f1, r1 = _check_block(u["id"], "s", lines, L["questions"], reading)
    unit_ids = [q["id"] for q in L["questions"]]
    e1 = context_errors + e1 + [f"focus: {q} is not a question of {u['id']}" for q in pack["focus"] if q not in unit_ids]
    e1 += [f"{f['id']} {f['field']}: « {f['fact']} » is not heard; it is only in the reading text ({', '.join(f['found_in'])})"
           for f in f1 if f["found_in"]]
    tr = pack["transfer"]
    tlines = {t["id"]: t["text"] for t in tr["lines"]}
    e2, f2, r2 = _check_block("transfer", "t", tlines, tr["questions"], {})
    if [t["id"] for t in tr["lines"]] != [f"t{i}" for i in range(1, len(tr["lines"]) + 1)]:
        e2.append("transfer: line ids must be t1..tN in order")
    return e1 + e2, f1 + f2, r1 + r2


# ---- rendering ----

def _lines_html(lines, speakers):
    labels = {s["id"]: s["label"] for s in speakers}
    return "".join(f'<p class="turn"><span class="pn">{E(t["id"])}</span><span class="spk">{E(labels[t["speaker"]])} :</span> {E(t["text"])}</p>'
                   for t in lines)


def _student_question(n, q, focus=()):
    star = "★ " if q["id"] in focus else ""
    if q["type"] == "single_choice":
        opts = "".join(f'<li>☐ {E(o["key"])}. {E(o["text"])}</li>' for o in q["options"])
        return f'<li class="q"><p>{star}{n}. {E(q["stem"])}</p><ul class="opts">{opts}</ul></li>'
    return f'<li class="q"><p>{star}{n}. {E(q["stem"])}</p><p>Réponse : ______________________</p></li>'


def _tri(d):
    return f'<p lang="fr">{E(d["fr"])}</p><p lang="en">{E(d["en"])}</p><p>{render._zh(d["zh"])}</p>'


def student_html(doc, pack):
    u = find_unit(doc, pack["unit"])
    L, tr = u["listening"], pack["transfer"]
    steps = "".join(f'<li><p><strong>☐ {s["minutes"]} min</strong></p>{_tri(s)}</li>' for s in pack["plan"])
    qs = "".join(_student_question(i + 1, q, pack["focus"]) for i, q in enumerate(L["questions"]))
    tq = "".join(_student_question(i + 1, q) for i, q in enumerate(tr["questions"]))
    body = (f'<h1>{E(pack["title"])} — fiche de l\'élève</h1>{render._banner()}'
            f'<div class="banner">{_tri(render.NO_AUDIO)}</div>'
            f'<p lang="fr">Niveau visé (indicatif) : {E(u["band"])}. Objectif de l\'unité : {E(u["goal"]["fr"])}</p>'
            f'<h2>Objectif de ces dix minutes</h2>{_tri(pack["goal"])}'
            f'<h2>Les dix minutes</h2><ol class="plan">{steps}</ol><div class="note">{_tri(pack["optional"])}</div>'
            f'<h2>Écoute : {E(L["title"])}</h2>'
            '<p lang="fr">★ : les questions qui travaillent l\'objectif de ces dix minutes.</p>'
            f'<ol class="qs">{qs}</ol>'
            f'<h2>Transfert : {E(tr["title"])}</h2><p>Écoutez la personne qui lit (deux fois), puis répondez.</p><ol class="qs">{tq}</ol>'
            f'<div class="note">{_tri(tr["productive"])}</div>')
    return render._page(f'{pack["title"]} — élève', body)


def reader_html(doc, pack):
    u = find_unit(doc, pack["unit"])
    L, tr = u["listening"], pack["transfer"]
    voices = "".join(f'<li>{E(s["label"])} : {E(s["voice"])}</li>' for s in L["speakers"])
    tvoices = "".join(f'<li>{E(s["label"])} : {E(s["voice"])}</li>' for s in tr["speakers"])
    how = ('<ul><li lang="fr">Ne montrez pas cette feuille à la personne qui écoute.</li>'
           '<li lang="fr">Lisez le dialogue deux fois, à un rythme naturel, avec deux voix différentes.</li>'
           '<li lang="fr">Ne lisez ni les numéros de ligne ni les noms : changez simplement de voix.</li>'
           '<li lang="fr">Faites une pause d\'environ deux secondes entre les répliques ; n\'insistez sur aucun mot.</li>'
           '<li lang="en">Do not show this sheet to the listener. Read the dialogue twice at a natural pace, with two voices; '
           'do not read line numbers or names; pause about two seconds between lines; stress no word.</li>'
           f'<li>{render._zh("不要给听的人看这张纸。用自然语速、两种不同的声音读两遍；不要读行号和人名；每句之间停顿约两秒；不要强调任何词。")}</li></ul>')
    body = (f'<h1>{E(pack["title"])} — feuille du lecteur</h1>{render._banner()}{how}'
            f'<h2>1. {E(L["title"])}</h2><p>Voix :</p><ul>{voices}</ul>'
            + (f'<p class="turn"><span class="pn">ctx</span>{E(pack["context"]["fr"])}</p>'
               '<p lang="fr">(Lisez d\'abord cette phrase de contexte, une fois, puis le dialogue.)</p>' if pack.get("context") else "")
            + f'{_lines_html(L["turns"], L["speakers"])}'
            f'<h2>2. Transfert : {E(tr["title"])}</h2><p>Voix :</p><ul>{tvoices}</ul>{_lines_html(tr["lines"], tr["speakers"])}')
    return render._page(f'{pack["title"]} — lecteur', body)


def _key_row(q, flags):
    if q["type"] == "single_choice":
        right = next(o for o in q["options"] if o["correct"])
        answer = f'{E(right["key"])}. {E(right["text"])}'
        wrong = "".join(f'<li>{E(o["key"])}. {E(o["text"])} — {E(o["why_wrong_en"])} {render._zh(o["why_wrong_zh"])}</li>'
                        for o in q["options"] if not o["correct"])
    else:
        answer = E(q["reference_answer"]) + (f' (aussi : {E(" / ".join(q["accepted_alternatives"]))})' if q["accepted_alternatives"] else "")
        wrong = ""
    ev = "; ".join(f'{E(e["ref"])} « {E(e["excerpt"])} »' for e in q["evidence"])
    notes = "".join(f'<p class="warn">À vérifier : « {E(f["fact"])} » ({E(f["field"])}) n\'est pas dans le script'
                    + (f' ; il se trouve dans {E(", ".join(f["found_in"]))} (texte de lecture de l\'unité)' if f["found_in"] else "")
                    + '.</p>' for f in flags if f["id"] == q["id"])
    return (f'<li class="q"><p>{E(q["id"])} — {E(q["stem"])}</p><p><strong>Réponse : {answer}</strong></p>'
            f'<p>Preuve : {ev}</p><p>{E(q["explanation_en"])} {render._zh(q["explanation_zh"])}</p>'
            + (f'<ul>{wrong}</ul>' if wrong else "") + notes + '</li>')


def teacher_html(doc, pack, flags):
    u = find_unit(doc, pack["unit"])
    L, tr = u["listening"], pack["transfer"]
    keys = "".join(_key_row(q, flags) for q in L["questions"])
    tkeys = "".join(_key_row(q, flags) for q in tr["questions"])
    vocab = "".join(f'<li>« {E(v["fr"])} » ({E(v["ref"])}) — {E(v["en"])} {render._zh(v["zh"])}</li>' for v in u["vocabulary"] if v["ref"].startswith("s"))
    fu = u["follow_up"]
    card = "".join(f'<li>{E(it["prompt"])} {E(it["answer"])}</li>' for it in fu["items"])
    focus = ", ".join(pack["focus"])
    debrief = "".join(f'<li lang="fr">{E(line)}</li>' for line in pack["debrief"])
    p = tr["productive"]
    body = (f'<h1>{E(pack["title"])} — fiche de l\'enseignant</h1>{render._banner()}'
            f'<p>{E(pack["provenance"]["authoring"])}</p>'
            f'<h2>Objectif de ces dix minutes</h2>{_tri(pack["goal"])}<p>Questions ★ : {E(focus)}</p>'
            f'<h2>Corrigé : {E(L["title"])}</h2><p>Chaque mauvaise réponse est expliquée ; les numéros de ligne renvoient au script de la feuille du lecteur.</p>'
            f'<ol class="key">{keys}</ol>'
            f'<h2>Vocabulaire du script</h2><ul>{vocab}</ul>'
            f'<h2>Prolongement : {E(fu["instructions_en"])}</h2><p>{render._zh(fu["instructions_zh"])}</p><ul>{card}</ul>'
            f'<h2>Transfert : {E(tr["title"])}</h2><ol class="key">{tkeys}</ol>'
            f'<p>Production : {E(p["fr"])}</p><p>Exemple : « {E(p["model"])} » — {E(p["model_note_en"])} {render._zh(p["model_note_zh"])}</p>'
            f'<h2>Débriefing (deux minutes)</h2><ul>{debrief}'
            '<li lang="fr">Pour chaque erreur, relisez seulement la ligne citée, puis faites réécouter cette réplique.</li>'
            '<li lang="fr">Ne donnez pas de note : l\'élève coche lui-même ce qu\'il a compris ou manqué.</li></ul>')
    return render._page(f'{pack["title"]} — enseignant', body)


def _md_from(markup):
    """A plain-text Markdown twin of an HTML sheet (for reading in a terminal)."""
    t = re.sub(r"<style>.*?</style>", "", markup, flags=re.S)
    t = re.sub(r"</(p|li|h1|h2|div)>", "\n", t)
    t = re.sub(r"<h1>", "# ", t)
    t = re.sub(r"<h2>", "\n## ", t)
    t = re.sub(r"<li[^>]*>", "- ", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.strip() for line in t.splitlines())).strip() + "\n"


def _transfer_secrets(pack, with_short_answers=True):
    out = []
    for q in pack["transfer"]["questions"]:
        out += [q["explanation_en"], q["explanation_zh"]]
        out += [o[f"why_wrong_{l}"] for o in q.get("options", []) if not o["correct"] for l in ("en", "zh")]
        if q["type"] == "short_answer" and with_short_answers:
            out += [q["reference_answer"]]
    out.append(pack["transfer"]["productive"]["model"])
    return out


def _scan_sheet(markup, doc, where, short_answers=()):
    """The workbook scanner's checks for one sheet: structural markup, extra
    metadata, every teacher-only string and marker of the workbook, plus the
    given short-answer references. (scan.scan_html also compares the question
    count with the whole workbook, which only fits the full edition.)"""
    findings = []
    body = re.sub(r"<style>.*?</style>", "", markup, flags=re.S)
    for pat, label in scan.STRUCTURAL:
        if re.search(pat, body, flags=re.I):
            findings.append(f"{where}: {label}")
    meta = scan._Meta()
    meta.feed(markup)
    for m in meta.metas:
        if set(m) - {"charset", "name", "content"} or (m.get("name") not in (None, "viewport")):
            findings.append(f"{where}: unexpected meta {m}")
    visible = html.unescape(scan._visible_text(markup))
    findings += scan.scan_text(visible, doc, where)
    for ans in short_answers:
        if len(ans) >= 3 and scan.norm(ans).lower() in visible.lower():
            findings.append(f"{where}: short-answer reference « {ans} » present")
    return findings


def build(doc, unit_id, out):
    pack = load_pack(unit_id)
    errors, flags, rows = verify(doc, pack)
    u = find_unit(doc, unit_id)
    sheets = {"student-checklist": student_html(doc, pack), "reader-sheet": reader_html(doc, pack),
              "teacher-debrief": teacher_html(doc, pack, flags)}
    scans = {}
    shorts = [a for q in u["listening"]["questions"] + pack["transfer"]["questions"] if q["type"] == "short_answer"
              for a in [q["reference_answer"]] + q["accepted_alternatives"]]
    for name in ("student-checklist", "reader-sheet", "teacher-debrief"):
        # the reader sheet carries the script, which contains the short answers by design
        findings = _scan_sheet(sheets[name], doc, name, shorts if name == "student-checklist" else ())
        visible = scan._visible_text(sheets[name])
        # the reader sheet carries the transfer script, which holds its short answers by design
        findings += [f"{name}: transfer key present: {s[:40]}" for s in _transfer_secrets(pack, name != "reader-sheet") if scan.norm(s) in visible]
        scans[name] = findings
    checklist = scan._visible_text(sheets["student-checklist"])
    script_in_checklist = [t["id"] for t in u["listening"]["turns"] + pack["transfer"]["lines"] if scan.norm(t["text"]) in checklist]
    # Answer separation beyond the scanner: no evidence excerpt (unless the stem
    # or an option already shows those words) and no reference answer.
    shown = " ".join(scan.norm(x) for q in u["listening"]["questions"] + pack["transfer"]["questions"]
                     for x in [q["stem"]] + [o["text"] for o in q.get("options", [])])
    leaked = [f"{q['id']} evidence « {e['excerpt']} »" for q in u["listening"]["questions"] + pack["transfer"]["questions"]
              for e in q["evidence"] if scan.norm(e["excerpt"]) not in shown and scan.norm(e["excerpt"]) in checklist]
    leaked += [f"{q['id']} reference « {q['reference_answer']} »" for q in u["listening"]["questions"] + pack["transfer"]["questions"]
               if q["type"] == "short_answer" and len(q["reference_answer"]) >= 3 and scan.norm(q["reference_answer"]) in checklist]
    if scans["student-checklist"] or scans["reader-sheet"]:
        errors.append("a student or reader sheet exposes the key: " + "; ".join(scans["student-checklist"] + scans["reader-sheet"]))
    if not scans["teacher-debrief"]:
        errors.append("positive control failed: the teacher debrief should contain the key")
    if script_in_checklist:
        errors.append(f"the student checklist contains script lines {script_in_checklist}")
    if leaked:
        errors.append("the student checklist shows " + "; ".join(leaked))
    out.mkdir(parents=True, exist_ok=True)
    for name, markup in sheets.items():
        (out / f"{unit_id}-{name}.html").write_text(markup, encoding="utf-8")
        (out / f"{unit_id}-{name}.md").write_text(_md_from(markup), encoding="utf-8")
    (out / f"{unit_id}-verification.md").write_text(report_md(unit_id, pack, errors, flags, rows, scans), encoding="utf-8")
    return {"errors": errors, "flags": flags, "questions": len(rows), "scan_findings": {k: len(v) for k, v in scans.items()}}


def build_all(doc, out):
    """Every pack in study_packs/, each into OUT with its unit prefix."""
    return {unit_id: build(doc, unit_id, out) for unit_id in pack_units()}


def report_md(unit_id, pack, errors, flags, rows, scans):
    out = [f"# Study pack {unit_id}: verification", "",
           f"Goal: {pack['goal']['en']}", "",
           "Automatic checks against the script (`python3 -m flh_workbooks studypack`). A flag is not an error:",
           "it names a fact the script does not contain (for example a time computed from two heard times), for",
           "the teacher to judge. A fact found only in the unit's reading text is an error.", "",
           "| Question | Evidence (line, occurrences) | Wrong-option reasons cite existing lines | Facts not in the script |",
           "|---|---|---|---|"]
    for r in rows:
        ev = "; ".join(f"{ref} ×{n}" for ref, _, n in r["evidence"])
        rs = "n/a" if not r["reasons"] else ("yes" if all(ok for *_, ok in r["reasons"]) else "NO")
        fx = "; ".join(f"{f['fact']} in {f['field']}" + (f" (found in {', '.join(f['found_in'])})" if f["found_in"] else "") for f in r["facts"]) or "none"
        out.append(f"| {r['id']} | {ev} | {rs} | {fx} |")
    out += ["", "A context line, when the pack has one, is quoted from the unit's reading text and read aloud",
            "before the dialogue, so it counts as heard. The in-app script-only lesson has no such line.",
            "", f"Errors: {len(errors)}"] + [f"- {e}" for e in errors]
    out += ["", f"Flags: {len(flags)}", "", "Key-exposure scan (student and reader must be 0; the teacher debrief is the positive control):"]
    out += [f"- {k}: {len(v)} findings" for k, v in scans.items()]
    return "\n".join(out) + "\n"
