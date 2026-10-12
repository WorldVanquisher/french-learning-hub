# FLH-057 validation: E5 HTTP provenance and Windows environment check

Date: 2026-10-12. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` on **macOS arm64** (Go
`go1.26.5`, Python 3.13.5). This is **not** a Windows machine, and neither
`pwsh` nor `powershell` is installed. No Git/GitHub command, subagent,
download, installation, secret, `.env` read or daily data was used. The
human's live model service and its proxy were not contacted, restarted or
changed. Contract: [plan](../plans/FLH-057-e5-integration-reporting.md).

## HTTP provenance (run here)

| Command | Result |
| --- | --- |
| `go test ./internal/transport/http -count=1 -run SemanticSearch -v` | `ResponseShapeAndAPIPrefix`, `ExplicitFailuresWithoutKeywordFallback` and new `QueryRepresentationFromReport` PASS |
| `go test ./internal/transport/http -race -count=1` | ok |
| Mutation: hardcode `application.ConceptSearchQueryRepresentationV2` in the handler | `QueryRepresentationFromReport` FAILS (the `synthetic_query_representation_x` case); file restored byte-identical (`cmp`) |
| FLH-056 overlay, recreated in the session scratchpad (`flh057-overlay.json` maps `internal/transport/http/flh056_metadata_acceptance_test.go` to `scripts/validation/flh053/http_metadata_probe_test.go.txt`, same as FLH-056's recipe): `go test -overlay <scratch>/flh057-overlay.json ./internal/transport/http -run TestFLH056HTTPMetadataMatchesEmbeddedRepresentation -count=1 -v` | **Exit 0**, PASS on both root and `/api` (FLH-056: exit 1, v1 twice). The overlay file never entered the tree |

The new test checks root and `/api` with v2 and with an arbitrary value, so a
different hardcoded constant can't pass. It also checks that a report with no
representation gives 500 with no `results` or `query_representation`.

## Windows environment check (static here; Windows NOT RUN)

| Check | Result |
| --- | --- |
| `grep` for `-c` or stdin Python invocations in `windows/*.ps1` | Only the explanatory comment in `check-env.ps1`; no invocation |
| `check_env.py` parsed with `ast.parse(..., feature_version=(3, 11))` | ok |
| `python3 -B check_env.py` here (no torch) | Versions listed as `NOT INSTALLED`; exit **2** |
| Same with stub `torch` packages in the scratchpad on `PYTHONPATH` | ok stub → exit 0; CUDA unavailable → exit 1; wrong result → exit 1 |

The stubs test only the script's control flow and exit codes, **not CUDA**.
The PowerShell scripts weren't parsed or run: no PowerShell is available. The
claim that 5.1 strips embedded quotes from native arguments rests on the
human's observed `SyntaxError` and on documented PowerShell behaviour, not on a
run here.

## Repository checks

| Command | Result |
| --- | --- |
| `gofmt -l .` | no output |
| `go vet ./...` | ok |
| `TMPDIR=<symlink-free scratch dir> go test ./... -count=1` | all ok. With macOS's default `TMPDIR`, FLH-053 `TestCapsTimeoutAndOptIn` still fails as recorded in FLH-054; that's unrelated and its file isn't edited |
| `python3 -B -m unittest discover -s tools/embedding/e5/tests -t tools/embedding/e5` | 31 tests OK |

No `__pycache__` was left.

## NOT RUN

- **Windows:** `check-env.ps1` on Windows PowerShell 5.1 and on PowerShell 7,
  including the real CUDA computation and `nvidia-smi`. One human validation
  command, from the repository root in the activated `flh-embedding`
  environment, read-only, which doesn't touch the running service:
  ```powershell
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\embedding\e5\windows\check-env.ps1; "exit=$LASTEXITCODE"
  ```
  Expected: `cuda tensor computation ok on cuda:0`, the `nvidia-smi` table and
  `exit=0`. Running the same command with `pwsh.exe` covers PowerShell 7.
- **Live endpoint:** the HTTP change wasn't exercised against a real Qdrant
  index or the human's E5 service. It's a transport serialization change, and
  the tests use a fake application report.
- No model, evaluation or quality claim.
