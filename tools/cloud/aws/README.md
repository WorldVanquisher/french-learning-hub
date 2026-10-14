# FLH-063 AWS tools: synthetic backup/restore and Titan embedding smoke

Bounded operator tools for one AWS experiment, on **synthetic data only**.
Overview and decisions: [docs/CLOUD_EXPERIMENT.md](../../../docs/CLOUD_EXPERIMENT.md).
Contracts: [FLH-063 plan](../../../docs/plans/FLH-063-aws-backup-and-embedding.md), the
[FLH-066 recovery plan](../../../docs/plans/FLH-066-aws-experiment-recovery.md) and the
[FLH-068 receipt-integrity plan](../../../docs/plans/FLH-068-aws-receipt-integrity.md).

Nothing here changes the application: no production Go, frontend, migration
or provider default.

## Layout

| Path | Purpose |
| --- | --- |
| `flh_aws/` | The `python3 -m flh_aws` CLI (run from this directory) |
| `template/flh063-backup-bucket.json` | CloudFormation template: one private bucket plus its policy, nothing else |
| `iam/*.json` | Least-privilege policy examples (replace `ACCOUNT_ID`) |
| `smoke_inputs.json` | 6 synthetic Titan smoke inputs (from the FLH-060 catalog) |
| `requirements.txt` | Pinned boto3/botocore/awscrt, for live use only |
| `tests/` | Offline tests; `test_boto_shapes.py` also needs the pinned requirements |

## State directory and backends

Every command takes `--state DIR`: an absolute directory outside the
repository. `init` binds it to one backend:

- **`aws`:** real AWS. It needs `--profile` and `--region` on each command,
  and `--allow-live` for anything that creates, writes, deletes or invokes.
- **`fake`:** local filesystem fakes in `DIR/fake-aws`. Nothing leaves the
  machine.

Fake and live budgets therefore never mix. The state directory holds:
- `ledger.json`: caps, used amounts and every attempted call;
- `resources.json`: stack (with its full StackId, from FLH-066), bucket,
  account, region and owned objects with ETags;
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
$PY -B -m flh_aws auth-check --state "$STATE" --profile P --region ca-central-1      # credentials + GetCallerIdentity only
$PY -B -m flh_aws recover  --state "$STATE" --profile P [--stack-id ARN]            # read-only reconciliation

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
$PY -B -m flh_aws titan-smoke     --state "$STATE" --profile P --region ca-central-1 --dimensions 512 --allow-live [--only-missing]
$PY -B -m flh_aws adapter         --state "$STATE" --profile P --region ca-central-1 --dimensions 512 --port 18951 --allow-live
```

**Exit codes:**

| Code | Meaning |
| --- | --- |
| 0 | OK |
| 1 | AWS error or failed verification |
| 2 | Usage or refusal, including a whole-plan budget pre-check; nothing sent |
| 3 | A single call would exceed a cap; that call is not sent |
| 4 | Outcome not verified: a request's effect is unknown, or deletion could not be confirmed. Run `recover` |

## Credentials (FLH-066)

- **When they are checked:** every live command resolves the profile's
  credentials in memory **before** it creates any client or sends any request.
  A failure is a refusal (exit 2) with a category and the fix; no value is
  printed.
- **`aws login` profiles** (a `login_session` entry in the AWS config) need
  `awscrt`. Without it botocore raises `MissingDependencyException`, which
  FLH-064's first preflight hit. `requirements.txt` therefore pins
  `awscrt==0.36.0`, exactly what botocore 1.43.104's `crt` extra requires.
- **`auth-check`** reports the SDK versions, the credential method (for
  example `login`), the principal ARN with the account masked and the
  account's last 4 digits. Its only request is `GetCallerIdentity`, which needs
  no IAM permission and creates nothing.

| Category | Typical cause | Fix |
| --- | --- | --- |
| `missing_dependency` | `aws login` profile, `awscrt` absent | Reinstall `requirements.txt` in the venv |
| `profile_not_found` | Wrong `--profile` | `aws configure list-profiles` |
| `no_credentials` | Nothing resolvable | Sign in |
| `expired_credentials` | Login/SSO session missing or expired; `ExpiredToken` | `aws login --profile P` (or `aws sso login`) |

## Stack receipts and recovery (FLH-066)

- **Receipt:** `deploy` saves the stack name, `ClientRequestToken` and tags
  **before** `CreateStack`, and the full `StackId` from its response
  **immediately** after, before waiting. Every later read and `DeleteStack`
  uses that StackId. By name, CloudFormation finds only live stacks; by
  StackId, it also returns a deleted stack as `DELETE_COMPLETE`. So only a
  StackId can confirm deletion.
- **`CreateStack` outcomes:**
  - AWS answered 4xx: `CREATE_REJECTED`, nothing was created. `cleanup`
    reports `not_created`, and `deploy` may run again in the same state
    directory (same ledger; the old record is kept under `history`).
  - No usable answer (network failure, lost response) or `AlreadyExists`:
    `CREATE_UNKNOWN`, exit 4. Nothing is resent, and `deploy` refuses until
    the record is settled.
- **`recover` (read-only; it sends no write):**
  1. With `--stack-id`, it checks that the ARN names this state's stack,
     account and region, then reads it.
  2. Without a recorded StackId, it looks the stack up by name and adopts its
     StackId only if the tags `flh:task` and `flh:state-id` match.
  3. With a StackId, it reads the current status.
  4. When no stack is found, or the stack is `DELETE_COMPLETE`, it probes the
     bucket with `GetBucketLocation` and `ExpectedBucketOwner`. `NoSuchBucket`
     proves it is absent.

  No `ListStacks` permission is needed.
- **Receipt integrity (FLH-068):** every command that reads `resources.json` validates it
  before using it.
  - **Checked:** the schema; the region, account and state-id formats; bucket
    and stack name derived from the state id; known statuses and observers;
    timestamps; and the object list.
  - **StackId:** a saved one must name this state's stack, account and region.
  - **Failure:** malformed, inconsistent or invalid-JSON receipts are refused
    (exit 1) before any request, and `status` reports `receipt_invalid`.
  - **Cached confirmation:** `deletion_confirmed` is returned without a new
    read only with a `deletion_confirmation` record. That record restates the
    StackId, the `DELETE_COMPLETE` read by StackId and the later `NoSuchBucket`
    probe; only the code that observed them writes it. A bare
    `DELETE_COMPLETE` status is not proof, and cleanup reads the stack again.
  - **Trust boundary:** this detects corruption and inconsistent edits, **not
    forgery**. Anyone who can rewrite every local file consistently can forge
    a receipt or ledger; there is no cryptographic protection.
- **Ownership before writes (FLH-068):** before deleting any object or the
  stack, cleanup reads the stack by its StackId. The answer must have the same
  StackId and name and this state's `flh:task`/`flh:state-id` tags. Otherwise
  the result is `ownership_refused`, with zero destructive requests. `recover`
  refuses a live, foreign-tagged stack the same way.
- **Old state directories** (FLH-063/064: no `schema`, no StackId) still work:
  - a live record adopts its StackId by name, with the tag check;
  - a record saved as `DELETED` is reported as `verification_unavailable`
    until you supply the StackId with `recover --stack-id`.

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
  - **First:** it reads the stack by StackId. Without one, it runs the
    `recover` lookup and deletes nothing unless a StackId is adopted.
  - **Objects:** each recorded object is re-read (HEAD) and deleted with
    `If-Match: <recorded ETag>`, after checking its `flh-run` metadata. If a
    delete's answer is lost, the object stays recorded and the next run
    re-reads it: if it is gone it is recorded as `already absent`, otherwise
    it is deleted under the same ETag condition.
  - **Unknown keys:** any key it didn't write stops the cleanup (exit 1). It is
    reported, never deleted, and the stack stays.
  - **Stack:**
    - only an empty bucket with the right tags is removed, via `DeleteStack`
      on the StackId;
    - each attempt is recorded before sending;
    - another attempt (with a new token) happens only after a fresh read shows
      the stack still exists and is not deleting.
  - **Result:** `cleanup_state` is one of:

    | `cleanup_state` | Meaning | Exit |
    | --- | --- | --- |
    | `deletion_confirmed` | `DELETE_COMPLETE` read by StackId **and** `NoSuchBucket` | 0 |
    | `not_created`, `none_recorded` | Nothing was ever created | 0 |
    | `resources_present` | Stack or objects observed present (unknown keys, refused delete) | 1 |
    | `ownership_refused` | The live stack read by StackId lacks this state's name, StackId or `flh:task`/`flh:state-id` tags; nothing destructive was sent | 1 |
    | `deletion_requested` | `DeleteStack` sent, completion not observed | 4 |
    | `verification_unavailable` | AccessDenied, network failure, or no StackId | 4 |

    A stack that "does not exist" by name is never reported as
    `DELETE_COMPLETE`. Repeating cleanup after `deletion_confirmed` sends
    nothing.

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

**Smoke failures (FLH-066).** A failed InvokeModel stays charged in the
ledger, which records its `error_category`, code and request id. The smoke
report adds a sanitized message (account ids and access-key ids are masked; at
most 300 characters) and guidance. Categories:
- `account_verification_pending`: AccessDenied saying "account is currently
  being verified" (FLH-064);
- `iam_denied`: "not authorized to perform";
- `model_access_denied`: "don't have access to the model";
- `expired_credentials`, `throttling`, `service_unavailable`, `validation`;
- `transport`, with `may_have_been_processed`: true for a read timeout, false
  when the endpoint was never reached;
- `response_invalid`, and `unknown` for an AccessDenied or error without a
  recognized message.

**Rerunning only the smoke.** Run `titan-smoke --only-missing` with the
**same** `--state`.
- It never resets a counter, raises a cap, retries automatically or needs a
  deployment, and the whole-plan budget check still applies.
- **What counts as done (FLH-068):** an input is skipped only when an `ok`
  ledger record has the same label and backend, plus the same binding
  `flh068_titan_request_v1`. The binding covers model, region, dimensions,
  `normalize`, embedding types, text convention, identity, and the SHA-256 of
  the exact input text and request body.
- **Reported, not reused:** a changed text, region, model, dimensions or
  convention is listed under `not_reused`, and the input is sent again.
- **Older records:** an `ok` record written before FLH-068 has no binding and
  never qualifies (`legacy_unbound_record`). It stays charged.

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
- **Credential tests:** they run the real botocore credential chain on a
  synthetic `aws login` profile in a temporary config and login cache.
- **Recovery tests:** `test_recovery.py` covers lost responses, a crash before
  the StackId is saved, AccessDenied, repeated cleanup, old state directories
  and Titan categories, using fault injection in the fakes.
- **Integrity tests:** `test_integrity.py` covers malformed and foreign
  receipts, confirmation records, observed ownership and Titan request
  binding.
- **Independent acceptance:** `scripts/validation/flh067/accept.py` (see its
  README) is the FLH-067 oracle.
