# Independent runner acceptance — FLH-055 retarget of FLH-051

Run from the repository root using standard-library Python, existing Go and its
cached modules. No download or dependency install is performed.

```sh
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off python3 -B scripts/validation/flh051/accept.py --output /tmp/flh055-acceptance-new
```

Use a new `/tmp/flh051...` or `/tmp/flh055...` output directory. The cache in the example is the
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

The three `.go.txt` files are virtual Go source for the overlay. They are never
copied into production or FLH-048. The small production bridge calls the actual
unexported converters, allowing field-for-field parity checks without mirroring
them again in the test. The runner overlay checks metadata perturbation and
file-order reversal, actual provider-text invariance, equal-score ordering,
runtime cap refusal, seven invalid-rank/candidate scenarios and MRR@5 boundaries.

FLH-055 changes the historical defect expectations to corrected acceptance:

- `-timeout 1ns`: exit 1, failed offline retrievers, no retrieval when already
  expired, no hits or partial-run metric slices. Zero/negative values: exit 2.
- Modified fixture with its own expected hash: exit 2 and no output. The same
  copy with the compiled hash: exit 3. The caller cannot redefine the reference.
- Successful reports: schema v2, freeze JSON/summary agreement and the standalone
  explanation that scoped fixture Concepts cannot match unscoped derived identities.
- Delayed synchronous context-ignoring retriever: first result retained, late
  second result discarded, later queries stopped, all metric slices null.
  Cancellation and terminal completion checks are also exercised independently.

The runner checks context cooperatively before/after calls. It does not interrupt
a context-ignoring synchronous call or impose a hard process deadline. The
harness's 90-second subprocess timeout is a separate harness bound.

The harness asserts required outcomes, actual named Go test pass events, raw-hit
metric reconstruction and preservation, then records `acceptance.json`. Do not
infer acceptance from exit zero alone: inspect that file, deadline evidence,
commands (expected versus actual exits), observations and artifact hashes. A
failed requirement stops the harness and prevents a final ACCEPTED artifact.
The historical FLH-051 NOT ACCEPTED report and its evidence are not rewritten.

Modified fixture copies remain explicitly unreviewed and exist only in output.
The original FLH-045 and FLH-048 files (including nested test data), plus the
historical FLH-051 report, are hashed before/after and must remain identical.
The script shuts down its fake servers, joins server threads and
removes the temporary repository symlink. Output logs/binary/copies are retained
under the supplied output path for review; no database or persistent service is
created. `artifact-sha256.json` lists every retained regular artifact except
itself. Reports are exploratory synthetic comparisons, not semantic-quality
results, production-policy evaluation or human approval.
