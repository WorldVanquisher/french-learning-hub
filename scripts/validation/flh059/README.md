# FLH-059 E5 numerical-reproducibility diagnostic

This diagnostic checks whether the same model input gets the same vector when
it is encoded in different batch shapes. It runs on the Windows CUDA GPU,
loading the prepared model files directly through the real `flh_e5` encoder
code. It **does not contact the embedding service or any endpoint**,
**changes no tolerance** and **adds no labels**. Contract:
[plan](../../../docs/plans/FLH-059-e5-reproducibility.md).

## Files

| File | Purpose |
| --- | --- |
| `inputs.json` | The 24 Concept documents and 56 Unit queries exactly as the production Go renderers produce them from the frozen FLH-045 fixture. Model input strings and opaque ids only |
| `diagnose.py` | `plan`, `run`, `analyze` and `inputs` (standard library; `run` imports `flh_e5`) |
| `run-diagnostic.ps1` | The human's Windows entry point |
| `test_diagnose.py` | Offline tests with a shape-dependent fake |

## Matrix (identical texts, varied shapes)

Each configuration is a dtype × batching policy pair: `float16` and `float32`
× `dynamic_v1`, `singleton_v1` and `fixed_v1`, six in all. Each one encodes
the same 456 positions, split into microbatches of 8 by the service's rule:

| Condition | Requests |
| --- | --- |
| `singleton_a`, `singleton_b` | Each of the 24 documents and 8 sampled queries alone, twice. `singleton_a` is the reference; `singleton_b` checks run-to-run repeatability |
| `ordered`, `reversed`, `rotated` | All 24 documents in one request (three full microbatches), in three orders |
| `short_companion`, `long_companion` | Each document paired with the shortest or the longest text |
| `partial3` | The documents in requests of 3 (partial microbatches) |
| `flh058_shape` | `[query] + 24 documents` for the 8 sampled queries: FLH-058's request shape (8+8+8+1) |

The 8 queries are chosen only by token count: evenly spaced from shortest to
longest. In total that's 2,736 positions, all local. There are no endpoint
requests and FLH-058's 1,400-position experiment isn't repeated.

## Measures (in `analysis.json`)

Measured per configuration, against the same text's `singleton_a` vector:
- **Per condition:** bitwise-equal count, the unchanged FLH-056 tolerance
  (`1e-5 + 1e-4*max(|a|,|b|)`) failure count, maximum coordinate difference and
  maximum cosine distance.
- **Norms:** minimum and maximum.
- **Shape attribution:**
  - whether occurrences computed with the same forward shape and row agree
    bitwise whatever their companions;
  - bitwise counts split by same shape as the reference versus a different
    shape.
- **Ranking sensitivity:** for each sampled query, the 24 documents ranked by
  cosine under `ordered`, `reversed`, `rotated` and `flh058_shape`, compared
  with the reference ranking. The output gives top-5 order and set changes, the
  maximum score change, the smallest reference margin among the top 6, and how
  many margins are within twice the maximum score change.
- **Cross-configuration:** each configuration's singletons compared with the
  `float32`/`singleton_v1` singletons (closeness, not reproducibility).
- **Cost:** encode seconds and forward passes. These are indicative only,
  especially while the service shares the GPU.

**Pre-registered rule.**
- A configuration passes when it has zero tolerance failures in every
  condition and no top-5 order change.
- `candidate` is the first passing configuration in the order `float16`
  dynamic, singleton, fixed, then `float32` dynamic, singleton, fixed, so no
  change is preferred when nothing fails.
- Bitwise equality is reported but not required.
- The output is evidence for a decision; it isn't the decision.

## Human commands (Windows, PowerShell 5.1 or 7)

From the repository root, with the model prepared and verified as described in
[tools/embedding/e5/README.md](../../../tools/embedding/e5/README.md):

```powershell
conda activate flh-embedding
$ModelDir = "$HOME\models\multilingual-e5-base"               # where you prepared it
$OutDir   = "$HOME\flh-evidence\flh059-$(Get-Date -Format yyyyMMdd-HHmmss)"   # new, outside the repo
python -B scripts\validation\flh059\diagnose.py plan
.\scripts\validation\flh059\run-diagnostic.ps1 -ModelDir $ModelDir -OutDir $OutDir
```

- **Memory:** the running service doesn't need to stop. The diagnostic loads
  its own copy, about 0.6 GB in float16 and 1.1 GB in float32, one dtype at a
  time.
- **Timing:** timings are cleaner with the service idle or stopped (Ctrl+C in
  its console).
- **Partial runs:** a failed run leaves partial files. Start again with a new
  `-OutDir`, because results are never overwritten.
- **Re-checking:** re-analyze offline with
  `python -B scripts\validation\flh059\diagnose.py analyze --out <dir>` after
  deleting `analysis.json`.

**Send back** (or keep outside the repository):
- the console output;
- from `$OutDir`: `environment.json`, `analysis.json`, `matrix.json`,
  `nvidia-smi-after.txt` and `artifact-sha256.txt`.

The `vectors-*.f32` files (about 1.4 MB each) and `records-*.json` let anyone
re-run `analyze`; keep them with the rest.

## Offline checks (any machine)

```sh
python3 -B -m unittest discover -s scripts/validation/flh059 -p 'test_*.py'
python3 -B scripts/validation/flh059/diagnose.py plan
python3 -B scripts/validation/flh059/diagnose.py inputs     # re-renders with Go; exit 0 if inputs.json matches
```

`inputs` writes only to a temporary directory and needs Go. The fake tests
check the plumbing and arithmetic only, never CUDA numerics.
