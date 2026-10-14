# FLH-074 independent public-demo acceptance

Uses existing cached dependencies, synthetic artifacts and mechanical vectors only.
No external endpoint, model, Docker or Qdrant. Run from the repository root on Linux.
Choose a **new** absolute `/tmp` evidence directory and free ports (19874–19876
by default). Raw artifacts and HTTP bodies remain outside the repository.

```sh
mkdir -p /tmp/flh074-new
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off go build -o /tmp/flh074-new/server ./cmd/server
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off go build -o /tmp/flh074-new/prepare ./scripts/demo/flh073/prepare
/tmp/flh074-new/prepare build -out /tmp/flh074-new/artifact -fixtures scripts/demo/flh073/fixtures/catalog.json
(cd web && VITE_FLH_PUBLIC_DEMO=1 ./node_modules/.bin/vite build --outDir /tmp/flh074-new/web)
python3 -B scripts/validation/flh074/accept.py --server /tmp/flh074-new/server --prepare /tmp/flh074-new/prepare --artifact /tmp/flh074-new/artifact --web /tmp/flh074-new/web --output /tmp/flh074-new/independent
python3 -B scripts/validation/flh074/followup.py --evidence /tmp/flh074-new --output /tmp/flh074-new/followup
```

Run the two Python commands separately: both currently exit **1**, because each
retains one reproducible failed acceptance expectation. Inspect `checks.json`,
`summary.json`, `http.jsonl` and follow-up `changed-public-results.json`; exit alone
is not acceptance. `accept.py` enumerates the production route registrations,
checks responses and state preservation, and records the static symlink defect.
`followup.py` supplies fully valid synthetic live-provider configurations and
checks the missing admission-recommendation fingerprint binding.

The initial harness also tests invalid live configurations; those may be refused
by configuration validation before the explicit public-demo guard. The follow-up
requires the explicit guard diagnostic. Its dummy key is invented, never loaded
from a credential file; all configured endpoints are loopback port 9, and startup
must fail before clients are constructed.

Only direct child server processes are terminated. The temporary static symlink
is removed in `finally`. Evidence, copied mutations and the normal-mode synthetic
DB are retained. Do not expose these test artifacts publicly. Mechanical rankings
prove no relevance; release validation must remain BLOCKED. Browser interactions
are not covered by these HTTP probes or by existing JSDOM tests.
