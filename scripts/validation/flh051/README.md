# FLH-051 independent runner acceptance

Run from the repository root using standard-library Python, existing Go and its
cached modules. No download or dependency install is performed.

```sh
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off python3 -B scripts/validation/flh051/accept.py --output /tmp/flh051-acceptance-new
```

Use a new `/tmp/flh051...` output directory. The cache in the example is the
temporary cache preserved by FLH-049; another writable existing cache is fine.
Loopback socket permission is required for the counted fake embedding servers
and the existing runner tests. Nothing contacts a real embedding provider.

The script builds the actual runner into isolated output, executes its existing
tests, runs independent Go tests through `-overlay`, repeats offline Linux
baselines, checks local fake-provider success/failure/timeout/malformed-vector/
cap cases, challenges path protection and freeze claims, then independently
recomputes metrics from raw hits joined with fixture proposals. It preserves
per-query reports, provider request texts/counters, stdout/stderr, commands and
SHA-256 manifests. The fixed-vector fake measures plumbing and tie ordering only.

The two `.go.txt` files are virtual Go source for the overlay. They are never
copied into production or FLH-048. The small production bridge calls the actual
unexported converters, allowing field-for-field parity checks without mirroring
them again in the test. The runner overlay checks metadata perturbation and
file-order reversal, actual provider-text invariance, equal-score ordering,
runtime cap refusal, seven invalid-rank/candidate scenarios and MRR@5 boundaries.

Known defects are asserted as observed reproductions: the expired offline
overall deadline returns success with metrics, and the explicit expected-hash
override reports a modified copy as matching frozen FLH-045. The harness exits
zero when its observations and passing checks reproduce; its printed verdict
is **NOT ACCEPTED**. After an owner fix, an old defect assertion should fail and
must be adjudicated rather than relaxed to make the acceptance pass.

Modified fixture copies remain explicitly unreviewed and exist only in output.
The original FLH-045 and FLH-048 files are hashed before/after and must remain
identical. The script shuts down its fake servers, joins server threads and
removes the temporary repository symlink. Output logs/binary/copies are retained
under the supplied output path for review; no database or persistent service is
created. `artifact-sha256.json` lists every retained regular artifact except
itself. Reports are exploratory synthetic comparisons, not semantic-quality
results, production-policy evaluation or human approval.
