# FLH-059 validation: E5 numerical reproducibility contract

Date: 2026-10-12. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` on **macOS arm64** (Go
`go1.26.5`, Python 3.13.5; no torch, no CUDA, no model files). This is **not**
the human's Windows RTX 4070 Laptop.
- **Not used:** Git/GitHub commands, subagents, weight downloads, paid calls,
  secrets, `.env` or daily data.
- **Live endpoint:** not contacted or restarted.
- **FLH-058's experiment:** not repeated.

Contract: [plan](../plans/FLH-059-e5-reproducibility.md).

**No numerical fix is claimed.** Everything below is scaffolding checked with
fakes, static analysis or container checks. The GPU checkpoint is NOT RUN.

## Inputs (offline, Go)

| Command | Result |
| --- | --- |
| FLH-058's read-only FLH-051 overlay, writing its capture to the session scratchpad | 56 batches of 25. Every batch is `[query] + the same 24 Concepts in the same order`, which confirms C001–C007 always shared microbatch 1 with a varying query |
| `python3 -B scripts/validation/flh059/diagnose.py inputs --write` | Wrote `inputs.json` (sha256 `da7804a1…7c4a24`): 24 documents and 56 queries, ids and text only |
| `python3 -B scripts/validation/flh059/diagnose.py inputs` | `inputs.json matches the production renderers`, exit 0 (also with the default macOS `TMPDIR`) |
| `python3 -B scripts/validation/flh059/diagnose.py plan` | 9 conditions, 456 positions per configuration, 6 configurations, 2,736 positions |
| `shasum -a 256 scripts/validation/flh045/fixture.json` | `92726376…7043a`, unchanged |

No overlay file remained in `internal/application` or `scripts/validation/flh048`.

## Offline tests (fakes only)

| Command | Result |
| --- | --- |
| `python3 -B -m unittest discover -s tools/embedding/e5/tests -t tools/embedding/e5` | **41 OK** (31 earlier and 10 new in `test_batching.py`) |
| `python3 -B -m unittest discover -s scripts/validation/flh059 -p 'test_*.py'` | **11 OK** |
| `python3 -B -m unittest discover -s scripts/validation/flh058 -p 'test_*.py'` | 5 OK (unchanged files) |
| All new and changed Python parsed with `feature_version=(3, 11)` | ok |
| `gofmt -l .`; `go vet ./...`; `TMPDIR=<symlink-free scratch> go test ./... -count=1` | clean; ok; all ok (no Go file changed) |

**What the fakes show**
- Policy shapes: dynamic makes one call; singleton makes one unpadded call per
  input, in order; fixed always requests (8, 512) and refuses more than 8.
- `dynamic_v1` builds a v1 manifest identical to the FLH-054 builder's.
- The other four configurations get distinct `…/<dtype>/<policy>/…` identities.
  The v2 identity changes with numerics, microbatch, code, policy and dtype,
  but not with service limits.
- The code hash ignores line endings.
- The legacy code hash is pinned at
  `96ab7c27ec6e18ec98cbafd3c8f3aac39c72f317110b98887d24d95d5e466bc0`, the
  value FLH-056/058 observed, and is unchanged. The v2 code hash is
  `44353228…799d24f`.
- The diagnostic, with a fake whose drift depends on the forward shape:
  - `float16-dynamic_v1` reports tolerance failures, including in
    `flh058_shape`;
  - repeats with the same shape are bitwise equal;
  - singleton and fixed are fully bitwise equal with no top-5 change, and the
    rule picks `float16-singleton_v1`;
  - with zero drift every configuration passes and `float16-dynamic_v1` is
    picked, so no change is preferred.
- Guards: `analyze` refuses to overwrite and detects a flipped vector byte.
  `--out` is refused inside the repository or when non-empty. Unknown dtypes
  exit 2.
- **These checks show plumbing and arithmetic only, not CUDA numerics.**

**Mutation checks** (each restored byte-identical; all caught):
- `singleton_v1` passing the whole microbatch: 1 E5 failure and 1 diagnostic
  failure;
- tolerance loosened to 1e-2: 2 diagnostic failures;
- one comment appended to legacy `encoder.py`: 3 E5 failures, including the
  pinned identity.

## PowerShell (Linux container, not Windows)

These used the temporary image
`mcr.microsoft.com/powershell:7.4-ubuntu-22.04` (amd64 under emulation,
PowerShell 7.4.6) with `--network none` and read-only mounts. It was pulled,
used and then removed (`docker images | grep -c powershell` → 0). Stub
`python` and `nvidia-smi` commands printed their arguments.

| Check | Result |
| --- | --- |
| Parse of all six `.ps1` files (the five `windows/` helpers and `run-diagnostic.ps1`), re-run after the `start.ps1` change | 0 parse errors each |
| `check-env.ps1` from a directory containing a space, `Standard` and `Legacy` modes | `python -B` receives `/w/dir with space/windows/check_env.py` as one argument in both modes; with a stub exit of 1 the script throws `environment check failed (exit 1)` and pwsh exits 1 |
| FLH-054's old `python -c $code` with `print(name, "NOT INSTALLED")` | `Standard`: one intact argument. **`Legacy`: split into `print(name, NOT` and `INSTALLED)`**, reproducing the human's Windows `SyntaxError` |
| `run-diagnostic.ps1` with paths containing spaces, both modes | All 11 arguments intact. The final exit 1 is expected: the stub creates no output directory, so the hashing step after Python fails |
| `start.ps1 -Batching fixed_v1`, both modes; `-Batching bogus` | `--batching fixed_v1` passed; `bogus` refused by `ValidateSet` |

`Legacy` mode on Linux mimics how Windows PowerShell 5.1 builds a native
command line. **It is not Windows execution.** Windows PowerShell 5.1 and 7 on
the laptop remain NOT RUN.

## NOT RUN

**The GPU checkpoint.** The human runs this on the laptop. It's read-only
toward the service and writes only to `$OutDir`:
```powershell
conda activate flh-embedding
$ModelDir = "$HOME\models\multilingual-e5-base"
$OutDir = "$HOME\flh-evidence\flh059-$(Get-Date -Format yyyyMMdd-HHmmss)"
.\scripts\validation\flh059\run-diagnostic.ps1 -ModelDir $ModelDir -OutDir $OutDir
```
Return the console output plus `environment.json`, `analysis.json`,
`matrix.json`, `nvidia-smi-after.txt` and `artifact-sha256.txt`.

**Code never run against torch, transformers or CUDA**
- `PolicyEncoder` (`encode_fixed`, the filler check, `numerics_settings`) and
  `CudaBackend`;
- `manifest` and `serve` with `--batching singleton_v1` or `fixed_v1`.

**Windows PowerShell**
- `check-env.ps1` (the FLH-057 human validation command still applies);
- `run-diagnostic.ps1` and the changed `start.ps1`.

**Other**
- Tailscale Serve commands: documented from the official knowledge base page,
  not run.
- The choice of strategy, any deployment change, any new index build and any
  quality claim.
