# FLH-038 validation: English-first Knowledge Library demo

Date: 2026-10-10. Working directory: `/Users/lowx/projects/FLH/french-learning-hub`.
Implementation owner: local Claude Code. No Git/GitHub command or subagent was
used. The contract is in [FLH-038 plan](../plans/FLH-038-english-demo-experience.md).

**Host and tools**
- macOS (arm64), Go 1.26.5, Node v24.16.0, Python 3.13.5.
- Headless Google Chrome 154 driven by `playwright-core` 1.49.1, installed only in session scratch.

**Isolation**
- Every demo used a fresh directory under the session scratchpad.
- Analysis used the rule-based analyzer and extraction the local stub; embedding was disabled.
- No secret, `.env`, daily or personal database, paid provider, or permanent dependency was used.
- Frontend checks ran in a scratch copy of `web/`. It used `node_modules` from an earlier session copy with the same lockfile.

## Automated checks

| Command | Result |
| --- | --- |
| `npm run test -- src/pages/KnowledgeLibrary.test.tsx` | 6 passed (5 updated, 1 new) |
| `npm run typecheck` | ok |
| `npm run test` | 17 files, 213 tests passed |
| `npm run build` | ok; bundle `index-WUJGe7ns.js`, the same bundle served in the PROD and DEV runs below |
| `python3 -m py_compile seed.py stub_extractor.py`; `node --check walkthrough.mjs` | ok |

The new focused test, "explains filing versus support in plain English and keeps
French examples marked as French", covers:
- the results-page introduction;
- the definition of filed versus supporting;
- the plain Status sentence;
- technical IDs kept in small print;
- the French example rendered with `lang="fr"`;
- the suppressed reason ("The learner hid it");
- the moved-unit history note with its link to concept #6.

## Fixture: the seven cases on a fresh database

Read-only GETs against a freshly seeded demo returned:

| Concept | State | Support | Filed, not supporting | Links | History |
| --- | --- | --- | --- | --- | --- |
| C1 subjunctive after « il faut que » | active | unit 9 (preferred) | unit 1 (older extraction) | unit 3 RELATED | — |
| C2 subjunctive forms of faire | orphaned | — | unit 2 (older extraction) | — | — |
| C3 subjunctive after « bien que » | active | unit 3 (preferred) | unit 4 (admission suppressed) | — | — |
| C4 overview of the subjunctive mood | orphaned | — | — | unit 9 NARROWER | — |
| C5 passé composé with être | active | unit 5 | — | — | unit 6, now concept 6 |
| C6 agreement of the past participle with être | active | unit 6 | — | — | — |
| C7 tu me manques: saying you miss someone | active | unit 7 | — | — | unit 8 INVALID |

**Unchanged from the FLH-034/036 fixture**
- Unit, record and extraction IDs.
- The structure of every Concept.
- Unit 3's source interpretation is `corrected`, with the English correction ("Concession: …").
- Unit 1's source is extraction v1, with analysis v1 and a newer v2 noted.

**French content kept**
- Learner records quote the French: « il faut que je fasse », « bien qu'il pleut ».
- Every unit example is French.

### Documented searches and FLH-035 harness expectations (replayed, harness unchanged)

A scratch script issued the same GET searches that
`scripts/validation/flh035/verify_integrated.py` asserts on the fixture, and
compared the IDs and tiers. **22 of 22 matched**:

| Query | Expected and observed |
| --- | --- |
| browse | `[6,5,3,1,7,4,2]` |
| `subjonctif`, `SUBJONCTIF`, `subj subj` | `[3,1,4,2]`, identity tier |
| `fasse` | `[1,2]`, both unit-wording |
| `ÊTRE—COMPOSÉ` and its decomposed form | `[5]` |
| `subj bie` | `[3]` |
| `à y être` | `[6,5]` |
| `déclencheur` | `[3,1]` |
| `irreg` | `[2]`, unit-wording |
| `malgre` | `[3]` |
| `manquer` | `[7]` |
| `allee` | `[6]` |
| `ensemble` | `[4]` |
| `jonctif`, `fasse introuvable`, `mardi` | empty |
| state filters (all / active / orphaned / retired) | `[6,5,3,1,7,4,2]` / `[6,5,3,1,7]` / `[4,2]` / `[]` |

**English searches:**
- `subjunctive` → `[3,1,4,2]`, identity tier;
- `manques` → `[7]`;
- `être` → `[6,5]`.

**Search-collision fix.** A first English draft used the word "subject" in two
unit explanations, which made `subj subj` also return 6 and 7. Those two
explanations were reworded, and the replay then passed. The SQLite dump hash
was unchanged by the replay.

The integrated verifier itself was not run: it needs Linux `/proc` and the NAS
toolchain, as recorded in FLH-036. Its edge probes that write after the
walkthrough were not replayed.

## Real-browser walkthrough (headless Chrome)

| Run | Server | Result | Persisted data |
| --- | --- | --- | --- |
| PROD, fresh demo | Go server with `-web-dir` (production build) | **10/10** | `.dump` SHA-256 unchanged (`d0bdea2e…`) |
| Restart | `demo.sh start` (API only) on the same database | ok | dump unchanged across restart |
| DEV | Vite 5.4 on 127.0.0.1:5334, React development build | **10/10** | dump unchanged |
| DEV `--multi-relation` | same | **11/11**; W11 shows BROADER and RELATED from unit #9, no duplicate-key warning | W11 writes two links by design |

In every run W10 recorded 0 non-GET browser requests and no failed API
response. The only console error is the browser's `/favicon.ico` 404; the
workbench has no favicon, which predates FLH-034.

**What the steps checked**

| Step | What was checked |
| --- | --- |
| W2 | `subjunctive` and `subjonctif` give identical result lists; each result says "N units filed here, M currently supporting" |
| W3 | Plain Status sentence; definition of filed versus supporting; best explanation includes "French example: Il faut que tu viennes demain." in a `lang="fr"` span; the older v1 unit is "Filed here but not supporting" with the extraction reason and its French example; a RELATED link |
| W4, W5, W9 | Source "Where unit #1 came from: learning record #1": what the learner wrote, extraction v1 marked Historical, interpretation analysis v1 with v2 noted. Back to the concept, then back to results for "subjunctive" with query and focus preserved. Switching views keeps the source screen |
| W6 | `fasse` gives two unit-wording results with the "being filed here does not mean … supports" note; orphaned "subjunctive forms of faire" shows its French examples |
| W7 | A moved unit ("now filed under concept #6", link followed) and "later marked INVALID"; current support shows « Tu me manques beaucoup. » |
| W8 | "The learner hid it (admission suppressed)"; source interpretation "corrected by a person", with "Before correction" |

**Screenshots** were taken in scratch and inspected:
- results for "subjunctive";
- the concept "subjunctive after « il faut que »";
- the source of unit #1;
- the orphaned concept;
- the history of "tu me manques";
- the relations (DEV).

They are not committed. The first PROD attempt failed W3–W9 because the
seeded titles were stored lower-case (identity normalization); the fixture and
walkthrough were changed to lower-case titles.

## Timing

| Activity | Time |
| --- | --- |
| `demo.sh setup` (warm Go cache) | about 3 s |
| Automated walkthrough W1–W10 | about 4 s |
| Human two-minute presentation | **NOT RUN** in this session; `docs/DEMO.md` holds the script |

## Remaining limits

- The concept, unit and record headers and the badge words ("active",
  "orphaned", "current extraction") come from backend facts and stay terse.
  Concept titles display in lower case.
- Real (non-demo) records and Concepts are shown exactly as stored. Nothing is
  translated, and a French-titled Concept stays French.
- The unchanged FLH-035 integrated verifier still has the B3/B5
  defect-reproduction probes noted in FLH-036. Its fixture search expectations
  were confirmed compatible by replay only.
- `docs/plans/FLH-034-knowledge-library.md` still quotes the FLH-036 label
  wording. It is outside this task's ownership.
