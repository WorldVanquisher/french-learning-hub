# FLH-063 AWS tools: synthetic backup/restore and Titan embedding smoke

Bounded operator tools for one AWS experiment, on **synthetic data only**.
Overview and decisions: [docs/CLOUD_EXPERIMENT.md](../../../docs/CLOUD_EXPERIMENT.md).
Contract: [plan](../../../docs/plans/FLH-063-aws-backup-and-embedding.md).

Nothing here changes the application: no production Go, frontend, migration
or provider default.

## Layout

| Path | Purpose |
| --- | --- |
| `flh_aws/` | The `python3 -m flh_aws` CLI (run from this directory) |
| `template/flh063-backup-bucket.json` | CloudFormation template: one private bucket plus its policy, nothing else |
| `iam/*.json` | Least-privilege policy examples (replace `ACCOUNT_ID`) |
| `smoke_inputs.json` | 6 synthetic Titan smoke inputs (from the FLH-060 catalog) |
| `requirements.txt` | Pinned boto3/botocore, for live use only |
| `tests/` | Offline tests; `test_boto_shapes.py` also needs boto3 |

## State directory and backends

Every command takes `--state DIR`: an absolute directory outside the
repository. `init` binds it to one backend:

- **`aws`:** real AWS. It needs `--profile` and `--region` on each command,
  and `--allow-live` for anything that creates, writes, deletes or invokes.
- **`fake`:** local filesystem fakes in `DIR/fake-aws`. Nothing leaves the
  machine.

Fake and live budgets therefore never mix. The state directory holds:
- `ledger.json`: caps, used amounts and every attempted call;
- `resources.json`: stack, bucket, account, region and owned objects with ETags;
- `packages/` and `packages.json`;
- `evidence/`: one JSON per command.

Keep it out of Git.

## Caps (per state directory, reserved before each request)

| Cap | Default |
| --- | --- |
| S3 PUT requests / bytes | 20 / 100 MiB |
| S3 GET requests / bytes | 100 / 300 MiB |
| S3 DELETE / LIST requests | 40 / 20 |
| Bedrock InvokeModel calls | 10 |
| Bedrock input characters (total / per input) | 8,000 / 2,000 |
| Bedrock request body bytes | 64 KiB |

- **Accounting:** a call is counted before it is sent, failures included, and
  then marked `ok` or `failed`.
- **Refusals:** a call that would exceed a cap is refused with nothing sent.
  Commands also check their whole plan up front.
- **Retries:** none. The SDK uses `total_max_attempts=1`.

## Commands

```sh
cd tools/cloud/aws
PY=python3            # live: a venv with requirements.txt installed
STATE=/abs/path/outside/repo/flh063-state

$PY -B -m flh_aws init     --state "$STATE" --backend aws        # or: fake
$PY -B -m flh_aws plan     --state "$STATE" --region ca-central-1 --dimensions 512   # no network
$PY -B -m flh_aws status   --state "$STATE"                      # no network

# A. backup and restore
$PY -B -m flh_aws deploy   --state "$STATE" --profile P --region ca-central-1 --allow-live
$PY -B -m flh_aws verify-bucket --state "$STATE" --profile P
$PY -B -m flh_aws snapshot --state "$STATE" --source-demo /abs/demo-dir [--source-revision LABEL]
$PY -B -m flh_aws upload   --state "$STATE" --profile P --run RUN_ID --allow-live
$PY -B -m flh_aws restore  --state "$STATE" --profile P --run RUN_ID --into /abs/new-dir
$PY -B -m flh_aws restore-local --package DIR --into /abs/new-dir --expect-manifest-sha256 HEX
$PY -B -m flh_aws cleanup  --state "$STATE" --profile P --allow-live

# B. Titan Text Embeddings V2
$PY -B -m flh_aws titan-preflight --state "$STATE" --profile P --region ca-central-1   # GetFoundationModel only
$PY -B -m flh_aws titan-smoke     --state "$STATE" --profile P --region ca-central-1 --dimensions 512 --allow-live
$PY -B -m flh_aws adapter         --state "$STATE" --profile P --region ca-central-1 --dimensions 512 --port 18951 --allow-live
```

**Exit codes:**

| Code | Meaning |
| --- | --- |
| 0 | OK |
| 1 | AWS error or failed verification |
| 2 | Usage or refusal, including a whole-plan budget pre-check; nothing sent |
| 3 | A single call would exceed a cap; that call is not sent |

## What each step guarantees

- **`snapshot`**
  - **Accepted sources:** only an FLH-034 (`.flh034-demo`) or FLH-060
    (`.flh060-demo`) demo directory. Every learner text and Concept target
    must appear in `scripts/demo/flh034/seed.py` or
    `scripts/demo/flh060/catalog.py`; anything else is refused before writing.
  - **Copy method:** SQLite's online backup API from a read-only connection.
    This matters: in a running demo the data can sit entirely in `demo.db-wal`,
    and a raw copy of `demo.db` had **0 tables** in the local run.
  - **Checks and manifest:** the copy must pass `integrity_check` and
    `foreign_key_check`. The manifest records the snapshot's size and SHA-256,
    the applied migrations, the repository migration/`go.mod`/`go.sum` hashes,
    an optional revision label you supply (no Git is run), domain counts and a
    domain fingerprint.
- **`deploy`**
  - **Creation:** one CloudFormation stack and bucket `flh063-<12 hex>`, with
    tags `flh:task=FLH-063` and `flh:state-id`.
  - **Bucket settings:** all four public-access blocks, `BucketOwnerEnforced`,
    SSE-S3 (AES256), no versioning, and expiration after `--retention-days`
    (default 7, at most 14).
  - **Bucket policy:** denies non-TLS access, PUTs without SSE AES256 or
    without `If-None-Match`, and DELETEs without `If-Match`.
  - **Read-back:** every setting is read back and checked before any upload.
- **`upload`**
  - **Keys:** `flh063/<run>/snapshot.sqlite3`, then `manifest.json`. The
    manifest goes last, as the completion marker.
  - **Every PUT carries:**
    - `If-None-Match: *` (an existing key fails; never overwritten);
    - `x-amz-server-side-encryption: AES256`;
    - `x-amz-checksum-sha256`;
    - the expected bucket owner.
  - **Repeat:** a repeated run is refused locally.
- **`restore`**
  - **Target:** a new directory outside the repository, the state directory
    and every source demo.
  - **Order:**
    1. download;
    2. check the manifest SHA-256 against the upload record;
    3. check the snapshot's size and SHA-256;
    4. run the SQLite integrity and foreign-key checks;
    5. compare migrations, counts and fingerprint;
    6. rerun the synthetic gate;
    7. only then write `restored/demo.db` and `RESTORE-ACCEPTED.json`.
  - **On failure:** `RESTORE-REJECTED.json` is written, the downloaded files
    are kept, no database is restored, and the command exits 1. The original
    database is never written.
- **`cleanup`**
  - **Objects:** each recorded object is deleted with `If-Match: <recorded
    ETag>`, after checking its `flh-run` metadata.
  - **Unknown keys:** any key it didn't write stops the cleanup (exit 1). It is
    reported, never deleted, and the stack stays.
  - **Stack:** only an empty bucket with the right tags is removed, via
    `DeleteStack`. Repeating cleanup is safe.

## Titan V2 text convention and identity

- **Request:** `{"inputText": <text>, "dimensions": 256|512|1024,
  "normalize": true, "embeddingTypes": ["float"]}` to the base model
  `amazon.titan-embed-text-v2:0`, on demand in the given region. An
  inference-profile id is refused.
- **Text (`flh_titan_verbatim_v1`):** the input is sent exactly as received.
  The E5 `query: `/`passage: ` prefixes are **not** applied, and Titan V2 has
  no such role convention.
- **Adapter identity:**
  `bedrock/amazon.titan-embed-text-v2:0/<region>/d<dims>/normalize/flh_titan_verbatim_v1`.
  Used as `EMBEDDING_MODEL`/`EMBEDDING_MODEL_ID`, it names its own semantic
  index space, so Titan and E5 vectors never mix.
- **Response check:** the length must equal the dimensions, values must be
  finite, the norm nonzero, and the norm within 1e-3 of 1.
  `inputTextTokenCount` is recorded.

**Adapter wire format.** `POST /v1/embeddings` with `{"model": <identity>,
"input": [1..8 strings]}` returns `{"data": [{"index": i, "embedding": [...]}]}`,
as `internal/embedding/http.go` expects.
- **Requests:** one InvokeModel per input, charged to the same ledger.
- **Errors:** a wrong model gives 400, the budget 429, and any provider
  failure 502 with no partial vectors.
- **Readiness:** `GET /readyz` never calls AWS, and startup sends nothing.
- **Binding:** loopback only.

## Tests

```sh
python3 -B -m unittest discover -s tools/cloud/aws/tests -p 'test_*.py'        # stdlib; boto3 tests skip
.venv/bin/python -B -m unittest discover -s tools/cloud/aws/tests -p 'test_*.py' # with requirements.txt
```

- **Fakes:** they enforce what the real bucket policy and S3 conditional
  requests promise, and build the bucket from the real template. They prove
  plumbing only, not IAM evaluation, AWS availability, latency, billing or
  Titan's behaviour.
- **Shape tests:** `test_boto_shapes.py` checks every request and response
  against the pinned botocore API models with `Stubber` (no network, no local
  AWS configuration).
