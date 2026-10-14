# FLH-067 independent AWS recovery acceptance

Standard-library fake-client probes only. No AWS request, credential-provider
process, Docker, model call or dependency installation. Run from repository root:

```sh
python3 -B scripts/validation/flh067/accept.py --out /tmp/flh067-review-new
```

Output must be a new direct `/tmp/flh067-*` directory. Every CLI operation runs
in a fresh Python process with a synthetic login config, empty credentials file
and empty login cache. Worker audit hooks prohibit network access. Auth boundary
probes inject synthetic SDK/session classes into the actual `aws_clients` path;
they do not claim real botocore credential-chain validation. Persisted fakes
supply the actual CLI's AWS clients and retain resources/counters across restarts.

Faults cover create/delete response loss, creation crash before StackId save,
invocation crash before outcome recording, AccessDenied, delayed deletion,
missing-by-name, legacy state copies, unknown objects, ownership and malformed
receipts. Each Titan attempt remains charged, and only-missing continuation,
completed repeats, dimensions changes and budget exhaustion are checked.
Changed text/region/model cases exercise incompatible-success evidence reuse.

Exit 0 means all recorded expectations pass; 1 means contract expectations fail.
The integrated baseline has reproducible failures; inspect `results.json`, actual
CLI exits/stdout/stderr, fake service records and ledgers. Every artifact and all
inspected AWS source files receive SHA-256 hashes. A crash worker intentionally
exits 86 (creation) or 87 (invocation); the parent retains the interrupted state.
Only synthetic state is retained; no real resource cleanup is attempted.

Shortest isolated defect reproducers (choose fresh output names):

```sh
python3 -B scripts/validation/flh067/accept.py --case foreign-id --out /tmp/flh067-foreign-id-new
python3 -B scripts/validation/flh067/accept.py --case foreign-tag --out /tmp/flh067-foreign-tag-new
python3 -B scripts/validation/flh067/accept.py --case stale-receipt --out /tmp/flh067-stale-new
python3 -B scripts/validation/flh067/accept.py --case changed-text --out /tmp/flh067-text-new
python3 -B scripts/validation/flh067/accept.py --case changed-region --out /tmp/flh067-region-new
python3 -B scripts/validation/flh067/accept.py --case changed-model --out /tmp/flh067-model-new
```

All six commands intentionally exit 1 on this baseline. Other selectors are
`auth`, `receipts`, `cleanup`, `invalid-json`, `titan` and `changed-dimensions`.
No original or historical state is modified: malformed/legacy records are created
only in task-local copies. Recovery is read-only to the fake AWS service but can
update the tool's own receipt/ledger/evidence files, as production is designed to do.

Existing suites and exact acceptance adjudication are recorded in the
[FLH-067 report](../../../docs/validation/FLH-067-aws-recovery-acceptance.md).
Real AWS behavior, IAM evaluation and billing remain NOT RUN. SDK/Stubber checks
require preinstalled optional dependencies; this task installs nothing and does
not treat absent dependencies as passing tests.
