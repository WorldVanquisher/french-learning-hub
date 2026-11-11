"""Key-exposure scan for student editions (HTML and text extracted from PDF).

A student edition must not reveal which option is correct or carry teacher
material in any form: visible text, hidden markup, attributes, comments,
scripts, embedded JSON or document metadata."""

import re
from html.parser import HTMLParser

TEACHER_MARKERS = ["✓", "Preuve :", "Réponse attendue", "Personnages et consignes de voix", "Texte corrigé",
                   "un exemple possible, pas la seule réponse", "Points traités"]
STRUCTURAL = [(r"<script", "script element"), (r"<!--", "HTML comment"), (r"\sdata-[\w-]+=", "data attribute"),
              (r"\saria-[\w-]+=", "aria attribute"), (r"\stitle=", "title attribute"), (r"\salt=", "alt attribute"),
              (r'class="(?:correct|tk|why)"', "teacher class"), (r"application/(?:ld\+)?json", "embedded JSON"),
              (r"<template", "template element"), (r"<noscript", "noscript element"), (r"hidden", "hidden content"),
              (r"display\s*:\s*none", "display:none")]
WS = re.compile(r"\s+")


def norm(s):
    return WS.sub(" ", s).strip()


def secrets_pw(doc):
    """Teacher-only strings of the productive workbook. Strings that also
    appear in public teaching text (prompts, mistakes table, drafts) are not
    secrets."""
    out = []
    rb = doc["rubric"]
    public = norm(" ".join(
        [x for u in doc["units"] for x in [u["writing"]["prompt"], u["speaking"]["situation"], u["retry"]["draft"]]
         + u["writing"]["requirements"] + u["speaking"]["requirements"] + [p["prompt"] for p in u["practice"]]
         + [y for m in u["mistakes"] for y in (m["wrong"], m["right"], m["why_en"], m["why_zh"])]]
        + [d[k] for c in rb["criteria"] for d in c["descriptors"].values() for k in ("en", "zh")]
        + [w[k] for w in doc["workflow"] for k in ("en", "zh")] + list(doc["notices"].values())))
    for u in doc["units"]:

        def add(kind, ref, s, minlen=6):
            s2 = norm(s)
            if len(s2) >= minlen and s2 not in public:
                out.append((kind, ref, s))
        for p in u["practice"]:
            add("practice_answer", p["id"], p["answer"])
            for a in p["accepted"]:
                add("practice_answer", p["id"], a)
            add("practice_explanation_en", p["id"], p["explanation_en"])
            add("practice_explanation_zh", p["id"], p["explanation_zh"], 4)
        for c in u["retry"]["corrections"]:
            add("retry_correction", u["id"], c["correction"])
            add("retry_why_en", u["id"], c["why_en"])
            add("retry_why_zh", u["id"], c["why_zh"], 4)
        fixed = u["retry"]["corrected"]
        for c in u["retry"]["corrections"]:
            i = fixed.find(c["correction"])
            if i >= 0:
                add("retry_corrected_window", u["id"], fixed[max(0, i - 12): i + len(c["correction"]) + 12])
        for k in ("writing_sample", "speaking_sample"):
            add(k, u["id"], u[k]["text"])
            for nte in u[k]["notes"]:
                add(k + "_note", u["id"], nte["en"])
    return out


def secrets(doc):
    """Strings that only the teacher edition may contain."""
    if doc.get("schema_version") == "flh_workbook_productive_v1":
        return secrets_pw(doc)
    out = []
    for u in doc["units"]:
        for sec in ("reading", "listening"):
            for q in u[sec]["questions"]:
                out += [("explanation_en", q["id"], q["explanation_en"]), ("explanation_zh", q["id"], q["explanation_zh"])]
                for o in q.get("options", []):
                    if not o["correct"]:
                        out += [("why_wrong_en", q["id"], o["why_wrong_en"]), ("why_wrong_zh", q["id"], o["why_wrong_zh"])]
        public = norm(" ".join([s["text"] for s in u["reading"]["segments"]] + [t["text"] for t in u["listening"]["turns"]]
                               + [q["stem"] for s in ("reading", "listening") for q in u[s]["questions"]]
                               + [o["text"] for s in ("reading", "listening") for q in u[s]["questions"] for o in q.get("options", [])]
                               + [v["fr"] for v in u["vocabulary"]]
                               + [it["prompt"] for it in u["follow_up"]["items"]]))
        for it in u["follow_up"]["items"]:
            a = norm(it["answer"])
            if len(a) >= 6 and a not in public:
                out.append(("follow_up_answer", u["id"], it["answer"]))
    return out


class _Meta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.metas, self.q_blocks, self._q, self._depth = [], [], None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            self.metas.append(a)
        if tag == "li" and a.get("class") == "q":
            self._q, self._depth = [], 1
        elif tag == "li" and self._q is not None:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag == "li" and self._q is not None:
            self._depth -= 1
            if self._depth == 0:
                self.q_blocks.append(norm(" ".join(self._q)))
                self._q = None

    def handle_data(self, data):
        if self._q is not None:
            self._q.append(data)


def _visible_text(markup):
    return norm(re.sub(r"<style>.*?</style>", " ", re.sub(r"<[^>]+>", " ", markup, flags=re.S), flags=re.S))


def scan_text(text, doc, where):
    """Visible text (from HTML or a PDF) must contain no teacher-only string."""
    findings = []
    t = norm(text)
    for kind, ref, s in secrets(doc):
        s = norm(s)
        # whole-string match on whitespace-normalised text; only very long
        # strings (samples) also use a distinctive opening as a probe
        if s in t or (len(s) > 200 and s[:60] in t):
            findings.append(f"{where}: {kind} of {ref} present")
    for m in TEACHER_MARKERS:
        if m in t:
            findings.append(f"{where}: teacher marker « {m} » present")
    return findings


def scan_html(markup, doc, where="student.html"):
    import html as _h
    findings = []
    body = re.sub(r"<style>.*?</style>", "", markup, flags=re.S)
    for pat, label in STRUCTURAL:
        if re.search(pat, body, flags=re.I):
            findings.append(f"{where}: {label}")
    p = _Meta()
    p.feed(markup)
    for m in p.metas:
        if set(m) - {"charset", "name", "content"} or (m.get("name") not in (None, "viewport")):
            findings.append(f"{where}: unexpected meta {m}")
    findings += scan_text(_h.unescape(_visible_text(markup)), doc, where)
    if doc.get("schema_version") != "flh_workbook_reading_listening_v1":
        return findings
    # a short answer must not sit inside its own question block
    sa = [q for u in doc["units"] for s in ("reading", "listening") for q in u[s]["questions"] if q["type"] == "short_answer"]
    blocks = p.q_blocks
    if len(blocks) != sum(len(u[s]["questions"]) for u in doc["units"] for s in ("reading", "listening")):
        findings.append(f"{where}: question block count {len(blocks)} does not match the workbook")
    else:
        flat = [q for u in doc["units"] for s in ("reading", "listening") for q in u[s]["questions"]]
        for q, b in zip(flat, blocks):
            if q["type"] == "short_answer":
                for ans in [q["reference_answer"]] + q["accepted_alternatives"]:
                    if len(ans) >= 3 and norm(ans).lower() in b.lower() and norm(ans).lower() not in q["stem"].lower():
                        findings.append(f"{where}: short answer of {q['id']} inside its question block")
    _ = sa
    return findings


def scan_pdf_info(info_text, doc, where="student.pdf"):
    findings = []
    for line in info_text.splitlines():
        k, _, v = line.partition(":")
        if k.strip() in ("Title", "Subject", "Keywords", "Author"):
            findings += scan_text(v, doc, f"{where} metadata {k.strip()}")
    for bad in ("JavaScript: yes", "Attachments: yes"):
        if bad in info_text:
            findings.append(f"{where}: {bad}")
    return findings
