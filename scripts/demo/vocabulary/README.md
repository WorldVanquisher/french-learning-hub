# Vocabulary fixture (synthetic)

A small, synthetic French vocabulary corpus for the saved-vocabulary feature
(`docs/plans/VOC-VOCABULARY.md`).

| File | Purpose |
| --- | --- |
| `stub_extractor.py` | Local extraction-provider stand-in. It returns fixed vocabulary units chosen by a phrase of the record; no network, no key |
| `seed.py` | Seeds records, analyses, extractions and Concepts through the public API only. It refuses non-loopback or non-empty backends and prints the IDs as JSON |
| `expected/replay_transcript.json` | The expected state after each step of `scripts/validation/vocabulary/replay.py` (times and IDs replaced by names) |
| `expected/ten_items.json` | The ten-item review fixture: each saved term's question (the learner's record) and its stored answer |

## The corpus

Ten vocabulary Concepts and one grammar Concept:

| Concept | Edge it covers |
|---|---|
| `apporter` | two records, so two examples of one term |
| `faire la grasse matinée` | a phrase whose wording keeps a double space |
| `chat` ×2 | the same spelling in two meanings: French "cat", and the English loanword "online chat" |
| `aujourd’hui`, `aujourd'hui` | two apostrophes, two Concepts |
| `café` ×2 | NFC and NFD, two Concepts |
| a long punctuated phrase | wrapping and search |
| `en revanche` | a plain term |
| one grammar Concept | must be refused |

## Smoke test (one example)

```
export TMPDIR=~/.cache/flh-20261121/workbooks/voc/tmp    # any scratch directory outside the repository
W=$(mktemp -d); cd <worktree>
go build -o "$W/server" ./cmd/server
python3 -B scripts/demo/vocabulary/stub_extractor.py 18471 &
(cd "$W" && env -i PATH=/usr/bin:/bin HOME="$W" LISTEN_HOST=127.0.0.1 PORT=18472 DB_PATH="$W/app.db" \
  AI_PROVIDER=rule-based EXTRACTOR_PROVIDER=openai OPENAI_API_KEY=sk-local-demo-not-a-secret \
  OPENAI_BASE_URL=http://127.0.0.1:18471 OPENAI_MODEL=stub-model EMBEDDING_PROVIDER=disabled "$W/server" &)
python3 -I -B scripts/demo/vocabulary/seed.py http://127.0.0.1:18472 > "$W/facts.json"
C=$(python3 -c "import json;print(json.load(open('$W/facts.json'))['concept_apporter'])")
U=$(python3 -c "import json;print(json.load(open('$W/facts.json'))['unit_apporter'])")
curl -s -X PUT -H 'Content-Type: application/json' -d "{\"unit_id\": $U}" http://127.0.0.1:18472/vocabulary/$C
curl -s "http://127.0.0.1:18472/vocabulary?q=bring"   # expect saved 1, the item "apporter"
```

**Expected result:**
- The PUT answers `"saved_now": true, "example_added": true`, and repeating it gives `"changed": false`.
- The search for `bring` lists `apporter` with the meaning `to bring (a thing)` / `带来（东西）` and the
  learner's question "Comment dit-on « bring » …".

## Replay

```
python3 -I scripts/validation/vocabulary/replay.py "$(mktemp -d)" --check scripts/demo/vocabulary/expected/replay_transcript.json
python3 -I scripts/validation/vocabulary/walkthrough.py "$(mktemp -d)"     # the browser journey (Docker, Playwright 1.49.1)
```

Both start their own stub and server on a fresh database, and stop them.
