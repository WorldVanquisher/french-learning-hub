# FLH-058 one bounded real-E5 exploration

Every result is an **exploratory comparison against author-proposed unreviewed
synthetic judgments; NOT production evaluation policy; NOT independently
collected human ground truth; small correlated author-visible holdout, no
tuning/generalization claim**. Measured embedding scores do not prove SAME or
useful free-text relevance.

`explore.py` uses Python's standard library and the existing Go FLH-048 runner.
It installs nothing and edits no runner, provider, label or service file.
The only authorized upstream is the exact supplied Tailscale endpoint/deployment
compiled into this helper. The completed model-run budget is exhausted.

Executed task commands (historical evidence; **do not repeat the run action**):

```sh
python3 -B scripts/validation/flh058/explore.py prepare --out /tmp/flh058-real-e5-exploration
python3 -B scripts/validation/flh058/explore.py run --out /tmp/flh058-real-e5-exploration --allow-one-model-run
python3 -B scripts/validation/flh058/explore.py analyze --out /tmp/flh058-real-e5-exploration
python3 -B scripts/validation/flh058/explore.py repeats --out /tmp/flh058-real-e5-exploration
```

- `prepare` is offline. A new `/tmp/flh058-*` directory retains source hashes,
  cached runner build/tests, offline baselines and an independent production
  converter/label-separation overlay. The overlay reads the existing owned
  FLH-051 bridge/test sources, without writing virtual files into their packages.
  It captures every actual Go-rendered provider input before real calls.
- `run` requires explicit opt-in. Fresh readiness, manifest and metrics must match
  the exact deployment, full manifest hash and local vector-code identity.
  Unavailability produces a BLOCKED checkpoint with no POSTs. The exclusive
  `/tmp/flh058-budget-reservation.json` reserves 56 requests/1,400 positions
  before the experiment. It survives failures and refuses reruns before network
  access. **Do not delete it or change output paths to repeat model work.**
- A task-owned loopback forwarder validates each request against the captured
  text batch, checks model/roles/caps and sends its original body unchanged to
  the service. It adds no prefix and does not trim/reorder input or response.
  Its upstream opener disables proxies/redirects and makes one attempt. Raw
  synthetic requests/responses and observations survive runner failure. The
  unmodified runner uses the forwarder's loopback base; the actual upstream
  endpoint is retained separately in `configuration.json`.
- Fixed bounds: upstream 8s, runner per-request 10s, overall 120s, process 150s,
  K=5, dimensions 768, 56 POSTs and 1,400 positions. The runner's overall timeout
  remains cooperative; the orchestration's subprocess deadline is separate.
  Failure stops work without retry/fallback/partial quality metrics. Only the
  forwarder's own listener is shut down; the human service/proxy is untouched.
- `analyze` is offline arithmetic over retained raw hits and vectors. It checks
  ID/rank/score integrity, independently reconstructs metrics and all population
  slices, alternatives/no-match observations, client/server accounting and all
  56 embedding rankings from response-vector cosine. Metric/score comparison
  tolerance is 1e-12; vector unit norm tolerance .001. It produces an initial
  artifact hash manifest without overwriting previous output.
- `repeats` is offline and deliberately returns **1** on this retained run:
  same-text document vectors exceed the earlier FLH-056 coordinate tolerance
  `1e-5 + 1e-4*max(abs(a),abs(b))`. It does not change quality metrics or tolerance.
  This is a numerical reproducibility observation, not a repeat model experiment.

Offline helper checks (no model or socket):

```sh
python3 -B -m unittest discover -s scripts/validation/flh058 -p 'test_*.py' -v
```

Go preparation fixes `GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off`.
Use a pre-existing writable cache on another machine; never install/download to
satisfy this task. Reports and per-command records retain the scope caveats.
See [the FLH-058 report](../../../docs/validation/FLH-058-real-e5-exploration.md).
