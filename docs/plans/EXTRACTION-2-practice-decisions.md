# Extraction 2.0: research notes and decision record (items 111–116)

Status: PROTOTYPE decision record, 2026-11-19. Owner: extraction lane. Sources were
looked up online in this run; each row says what was verified. "Observed" is what a
study measured. "Hypothesis" is what this prototype assumes and could test. Nothing
here was measured on FLH learners.

## 1. Research (111–112)

| # | Source (DOI / URL) | Population | Task | Measured outcome | A1/A2 French applicability |
|---|---|---|---|---|---|
| R1 | Karpicke & Roediger (2008), *Science* 319:966–968, [10.1126/science.1152408](https://doi.org/10.1126/science.1152408); [PubMed 18276894](https://pubmed.ncbi.nlm.nih.gov/18276894/) | university students | 40 Swahili–English word pairs; repeated study vs repeated retrieval after first recall | 1-week delayed cued recall: repeated retrieval gave a large advantage; repeated study after recall added little; students' predictions did not track it | Observed for vocabulary pairs in adults. Applying it to rule statements and pronoun choice is a **hypothesis**. A later replication qualifies the "restudy adds nothing" part ([Psych. Science page](https://www.psychologicalscience.org/journals/psychological-science/0956797615617778/)). |
| R2 | Cepeda, Pashler, Vul, Wixted & Rohrer (2006), *Psychol. Bull.* 132(3):354–380, [10.1037/0033-2909.132.3.354](https://doi.org/10.1037/0033-2909.132.3.354); [PubMed 16719566](https://pubmed.ncbi.nlm.nih.gov/16719566/) | meta-analysis: 839 assessments, 317 experiments, 184 articles | verbal recall after spaced vs massed study | spacing helps; the study gap that maximises retention grows with the retention interval | Verbal recall is close to word and form recall; grammar rules not specifically covered. |
| R3 | Cepeda, Vul, Rohrer, Wixted & Pashler (2008), *Psychol. Sci.* 19(11):1095–1102, [PubMed 19076480](https://pubmed.ncbi.nlm.nih.gov/19076480/) (DOI not re-checked in this run) | > 1,350 adults online | obscure facts; gap up to 3.5 months; test up to 1 year later | the optimal gap is about 20–40% of a 1-week test delay and 5–10% of a 1-year delay | Supports a growing review ladder. The ladder itself is **Workbooks'** decision, not this lane's. |
| R4 | Kim & Webb (2022), *Language Learning* 72(1):269–319, [10.1111/lang.12479](https://doi.org/10.1111/lang.12479) | L2 learners: 98 effect sizes, 48 experiments, N = 3,411 | spaced vs massed L2 practice, mostly vocabulary | medium-to-large spacing effect; short and long spacing tie on immediate tests, long spacing wins on delayed tests; equal and expanding schedules are similar | Language-specific. Grammar subgroup results were **not verified** in this run. |
| R5 | Suzuki (2017), *Language Learning* 67(3):512–545, [10.1111/lang.12236](https://doi.org/10.1111/lang.12236) | L2 learners (morphology) | lag effects in L2 morphology practice (conceptual replication) | full text not read in this run; a review notes that massed vs spaced **grammar** research is still scarce | The direction of the effect is **not verified** here. Treat grammar spacing as an open question. |
| R6 | Pashler, Cepeda, Wixted & Rohrer (2005), *JEP:LMC* 31(1):3–8, [10.1037/0278-7393.31.1.3](https://doi.org/10.1037/0278-7393.31.1.3) | 258 adults | Luganda–English word pairs, with and without feedback | showing the correct answer after an error raised final retention; right/wrong feedback was no better than none | Directly motivates "show the answer, not just ✓/✗" after an attempt. |
| R7 | Li (2010), *Language Learning* 60(2):309–365, [10.1111/j.1467-9922.2010.00561.x](https://doi.org/10.1111/j.1467-9922.2010.00561.x) | meta-analysis of 33 L2 studies | oral and written corrective feedback | medium overall effect, maintained on delayed tests; implicit feedback held better than explicit | Mostly interaction and classroom feedback, not self-study apps. |
| R8 | Lyster & Saito (2010), *SSLA* 32:265–302, [10.1017/S0272263109990520](https://doi.org/10.1017/S0272263109990520) | 15 classroom studies, N = 827 | oral corrective feedback in classrooms | prompts (pushing the learner to self-correct) beat recasts; younger learners gained more | A "try again or self-check before the key" step is a **hypothesis** borrowed from prompts. |
| R9 | Pan & Rickard (2018), *Psychol. Bull.* 144(7):710–756, [10.1037/bul0000151](https://doi.org/10.1037/bul0000151) | meta-analysis of transfer of test-enhanced learning | practice tests, then new questions or formats | transfer occurs under some conditions (the authors' three-factor framework), not by default | Transfer to a new sentence must be **measured**, not assumed. |
| R10 | VanPatten & Cadierno (1993), *SSLA* 15:225–243 (DOI not verified; secondary summaries only) | university learners of Spanish | Spanish object clitic pronouns: processing instruction vs traditional output practice | processing instruction improved interpretation | The closest grammar evidence for clitic pronouns such as French *y* and *en*. Input-based choice in a meaningful sentence is a **hypothesis** for French. |

Evidence gaps (recorded, not filled): L2 *grammar* retrieval practice is thin (one Turkish
grammar study and artificial-language rule learning appeared in search; neither was
read in full). No source here studied French *y*/*en* or A1/A2 self-study.

## 2. Tools: recall, export and bringing context into a fresh session (113)

**Anki** (official manual, read in this run):
- **Recall** ([docs.ankiweb.net/studying.html](https://docs.ankiweb.net/studying.html)): only the question shows; the learner thinks, then presses *Show Answer* and rates their own recall *Again / Hard / Good / Easy*. Recall is self-graded.
- **Export** ([docs.ankiweb.net/exporting.html](https://docs.ankiweb.net/exporting.html)): *File → Export*, then pick *Notes in Plain Text* (tab-separated fields), *Deck (.apkg)* (optional scheduling, media and presets) or *Collection (.colpkg)*, set the options and save. An .apkg import merges; a .colpkg import replaces the collection.
- **Lesson for FLH:** the self-check state mirrors Anki's self-rating. The packet is a plain export without scheduling, which stays with Workbooks.

**Codex** ([AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md); local `codex-cli 0.170.0 --help`):
- **Instructions:** Codex reads `~/.codex/AGENTS.md`, then `AGENTS.md` files from the project root down to the current directory. Outside a Git repository it reads only the current directory. The default limit is 32 KiB.
- **Steps:** make an empty directory, copy `packet.md`, `packet.json` and the prompt into it, then run `cd DIR && codex "$(cat PROMPT-codex.md)"` for an interactive session. `codex exec` is the non-interactive form; it reads the prompt from stdin when it is `-`.

**Claude Code** ([memory docs](https://code.claude.com/docs/en/memory); local `claude 2.1.327 --help`):
- **Instructions:** Claude Code loads `CLAUDE.md` or `CLAUDE.local.md` from the working directory and its parents. It reads `AGENTS.md` when there is no CLAUDE.md, and `@path` imports a file.
- **Steps:** the same empty directory and files, then `cd DIR && claude "$(cat PROMPT-claude-code.md)"`; `claude -p` is the print-and-exit form.

**Decision:** the prompt names the packet files explicitly. Neither prompt relies on an AGENTS.md or CLAUDE.md being picked up silently, so the same two files work for both tools and nothing loads that the learner did not choose.

## 3. Exercise types and the first-release mix (114)

| Type | What it measures | Grading | Risk |
|---|---|---|---|
| Recognition: choose between confusable alternatives (*y* / *en*) in a sentence | discrimination of form by meaning in context | exact: one option is correct; feedback names the rule | low retrieval effort; can be guessed (50% with two options) |
| Unaided recall: explain from memory | declarative knowledge of the rule | **self-check** against the approved statement; never graded automatically | free text; a good paraphrase cannot be graded exactly |
| Production in a new sentence (absent from the source) | near transfer: using the form in a sentence not seen in the source | exact against accepted variants (case, punctuation and apostrophes normalised), otherwise self-check; a known common error is marked incorrect | valid French outside the accepted list must not be marked wrong |

**First-release mix per approved Concept:** 1 explain, then 1 choose, then 1 produce.
Explain comes first because the choice item shows both forms and would cue the free
recall. Outcomes are recorded per type and never pooled into one score.

## 4. Audit of the current FLH path (115)

| Stage | Kept | Lost or not represented |
|---|---|---|
| Capture (`learning_capture_v1`, `POST /captures`) | original input and context, verbatim; optional analysis; source; fingerprint | the learner's **goal** (what they want to be able to do) has no field; a raw chat is deliberately not stored |
| Analysis + feedback | versioned analysis; immutable feedback and corrections of the explanation | — |
| Extraction (`knowledge_extraction_v2`) | units (kind, canonical, statement, bilingual statement, one example, confidence); `source_analysis_id` / `source_feedback_id` | **which words of the question support a unit**: there is no quote or span. `evidence-review` reconstructs it heuristically offline |
| Admission | machine recommendation + human override (active / suppressed / needs_review) | a learner cannot **correct a unit's wording**, only admit or suppress it. A correction becomes a new capture with no link back |
| Concept resolution | identity (target, `pedagogical_intent` = the knowledge **kind**, scope); SAME / DISTINCT / RELATED | a **contrast** (y vs en) is at most a relation between two Concepts, without the rule that separates them; `pedagogical_intent` is not a practice intent |
| Practice (Recall Practice v1, Mistake Notebook, Review Today) | session-only recall from supporting unit statements; mistake captures with `source_ref`; retry marks | exercises have **no stable ID and no evidence link**; Recall Practice attempts are never stored; no worked examples or common errors as data |

## 5. Decision record (116)

| Decision (prototype UX) | Evidence | Observed vs hypothesis |
|---|---|---|
| D1 Answers stay hidden until an attempt or an explicit reveal | R1 | Observed: retrieval beats restudy for 1-week recall of word pairs. Hypothesis H1: it holds for y/en choice and production. |
| D2 After an attempt, show the correct answer, a short explanation and the supporting excerpt with its evidence ID | R6, R7 | Observed: answer feedback beats right/wrong feedback (word pairs); corrective feedback is effective in L2. Hypothesis H2: an excerpt from the learner's own question makes feedback more relevant (untested). |
| D3 No scheduling in this lane: approved items and attempt outcomes go to Workbooks read-only; immediate and delayed outcomes are kept apart | R2, R3, R4 | Observed: spacing helps; longer gaps help delayed tests. Hypothesis H3: Workbooks' +1/+3/+7/+14 ladder suits these items (their lane, untested). |
| D4 One production item per Concept uses a sentence absent from the source, and its outcome is reported separately | R9 | Observed: transfer is conditional. Hypothesis H4: near transfer to a new sentence; to be measured in the trial (§6 of the trial design), never inferred from immediate recall. |
| D5 Recognition items put the confusable forms in a meaningful sentence (input-based) | R10 | Observed (Spanish clitics, secondary source): input processing helped interpretation. Hypothesis H5 for French y/en. |
| D6 A self-check state when exact grading would overclaim; explain-from-memory is always self-checked | Anki self-rating (product practice); R8 | Observed in classrooms: prompts beat recasts. Assumption A1: honest self-checks are informative enough for a prototype. |
| D7 Every machine statement is a draft beside its evidence; unsupported and uncertain ones stay visible; only the learner approves, edits or rejects | FLH principles (AI output is metadata; corrections are immutable records) | Assumption A2: showing the excerpt helps learners reject unsupported claims; the trial counts rejections. |
| D8 A portable packet: Markdown and JSON from one data source; study mode without answers; tutor rubrics only on an explicit choice; the agent's return is previewed read-only | Anki export separates plain notes from scheduled packages; Codex and Claude Code load context from files (§2) | Product reasoning, not research. Assumption A3: agents follow "cite evidence IDs, one question at a time" when asked; the live smoke is owner-only. |

Assumptions: A1–A3 above. A4: the synthetic A1/A2 sentences are correct French; they
were written for this prototype and need a native-speaker check before any learner use.
A5: two-option recognition is acceptable for a first release, even though the guessing
rate is 50%.

## 6. Optional learner trial (133, design only; nothing has been run)

**Question.** Does the prototype's sequence (approve → explain → choose → produce, with
answer-and-excerpt feedback) help an A1/A2 learner choose *y* or *en* correctly later, in
sentences they have not seen?

**Who.** The owner, or volunteers who opt in explicitly. Records stay local: decisions and
attempts in the work directory, nothing uploaded. No learner data enters Git or a packet
without the export preview.

**Materials.**
- Two y/en sets of equal difficulty, A and B, each with 6 choose and 6 produce items.
- Every sentence is absent from the learner's source. A native speaker checks them first (assumption A4).

**Outcomes (kept separate; never pooled).**

| Outcome | When | Measure |
|---|---|---|
| immediate recall | the same session, right after practice | explain-from-memory self-check (got it / partly / missed) and choose accuracy on the practised items |
| delayed recall | 7 days later (Workbooks' ladder step 3; the date set by Workbooks) | the same items, no feedback before the answer |
| transfer | same day as the delayed recall | produce accuracy on the **unpractised** set (A or B, counterbalanced); unlisted answers are self-checked, and two raters check a sample |

**Rules.**
- A retention claim is reported only once delayed data exists. Until then the report says "immediate only".
- Revealed-without-attempt items count as not attempted, never as correct.
- Self-check outcomes are reported apart from exact grading.
- Report counts with the number of learners. With the owner alone (n = 1) this is a usability check, not evidence of learning.

**Measured friction to collect.**
- decisions per source;
- time from capture to first practice;
- the share of drafts rejected, and how many of those were unsupported;
- self-check rate on produce;
- answers the learner disputes.
