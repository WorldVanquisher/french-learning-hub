# FLH-057 E5 HTTP provenance and Windows environment check

Owner: local Claude Code. Branch label supplied:
`fix/flh-057-e5-integration-reporting`. No Git/GitHub command or subagent was
used. Inputs: the FLH-056 defect report
([validation](../validation/FLH-056-live-e5-acceptance.md), read, not edited)
and the human's Windows `check-env.ps1` failure. Evidence:
[validation](../validation/FLH-057-e5-integration-reporting.md).

Not changed: the encoder, manifest, vector convention, dependencies,
migrations, application indexing/search, the frontend, evaluation fixtures,
FLH-053/054/056 files and historical reports.

## Files (exact edit set)

| File | Change |
| --- | --- |
| `internal/transport/http/semantic_search.go` | `query_representation` is `report.QueryRepresentation`; an empty one returns HTTP 500 |
| `internal/transport/http/semantic_search_test.go` | The fake reports a representation; shape test asserts v2; new `TestSemanticSearchHTTP_QueryRepresentationFromReport` (root and `/api`) |
| `tools/embedding/e5/windows/check-env.ps1` | Runs `python -B <path to check_env.py>`, with no `python -c`; checks every native exit code |
| `tools/embedding/e5/windows/check_env.py` (new) | The former inline Python, with explicit exit codes instead of `assert` |
| `tools/embedding/e5/README.md` | Status line; step 1 explains the file and its exit codes |
| `docs/SEMANTIC_SEARCH.md` | "What a search reports (FLH-057)"; status bullets |
| This plan and the validation report | New |

## Contracts

**HTTP provenance**
- `GET /knowledge-library/semantic-search` and `/api/...` serialize
  `query_representation` from `SemanticSearchReport.QueryRepresentation`, which
  the application sets to the representation it embedded
  (`concept_search_query_v2` since FLH-054). The transport has no constant of
  its own.
- If a report has no representation, the response is HTTP 500
  `could not run semantic search`. A guessed provenance would be worse than an
  error.
- The schema version `knowledge_library_semantic_search_v2` is unchanged: the
  field and its type are the same, and only its value is now correct.

**Windows Python invocation**
- No PowerShell helper passes Python source as a native command argument. The
  check's Python lives in `check_env.py` beside the script and is run by path
  (`$PSScriptRoot`). PowerShell quotes a path with spaces correctly in 5.1 and
  7, and Windows paths can't contain `"`.
- `check_env.py` takes no arguments and reads no paths or user text. It still
  performs the real CUDA tensor computation.
- Exit codes: 0 when the computation is correct, 1 when CUDA is unavailable or
  the result is wrong, 2 when torch can't be imported. `check-env.ps1` throws on
  any non-zero exit from pip, the check or `nvidia-smi`.
- Other helpers inspected:
  - `prepare-model.ps1` and `start.ps1` pass `$ModelDir` only as an argument to
    `-m flh_e5`, never into Python source, so they're unchanged.
  - `smoke.ps1` and `stop.ps1` don't run Python.
- The deployment code hash covers `contract.py`, `encoder.py` and `manifest.py`
  only, so `check_env.py` doesn't change the deployment identity.

## Bounded dependencies (reported, not edited)

1. `docs/ARCHITECTURE.md:1975` still says the search query is embedded as
   trimmed text, `concept_search_query_v1`.
2. `web/src/pages/KnowledgeLibrary.test.tsx:186` uses v1 in a fixture. This is
   cosmetic: the frontend type is a plain `string`.
3. `scripts/demo/flh040/fake_embeddings.py` `IGNORE` still lacks the envelope
   tokens (FLH-054 dependency 2).
