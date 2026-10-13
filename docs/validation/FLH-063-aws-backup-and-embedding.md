# FLH-063 validation: bounded AWS backup/restore and embedding smoke

Date: 2026-10-13. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` on **macOS arm64** (system
Python 3.13.5).

**Not used:**
- Git/GitHub commands or subagents;
- `.env` or credential files;
- daily data or production edits.

Contract: [plan](../plans/FLH-063-aws-backup-and-embedding.md). Guide:
[CLOUD_EXPERIMENT.md](../CLOUD_EXPERIMENT.md).

## Cloud execution: BLOCKED / NOT RUN

**No AWS profile was supplied with the task.** The AWS CLI is not installed on
this machine, and boto3 is not installed in the system Python. I didn't look for
or probe any credentials, profile or account, so:
- no AWS resource was created;
- no object was uploaded;
- no Bedrock request was sent, including the read-only `GetFoundationModel`;
- no AWS cost was incurred by this task.

The exact human commands are in [CLOUD_EXPERIMENT.md](../CLOUD_EXPERIMENT.md)
under "Running it". **Acceptance items C1 (synthetic upload/download/restore)
and C2 (≤ 10 InvokeModel) are NOT RUN.**

## Checked against AWS sources (read-only, no account)

| What | Source | Result |
| --- | --- | --- |
| Titan V2 API | Bedrock user guide, Titan Embeddings request/response | `inputText`, `dimensions` 1024 (default)/512/256, `normalize` (default true), `embeddingTypes`; response `embedding`, `inputTextTokenCount`, `embeddingsByType` |
| Input limits and languages | Bedrock user guide, Titan Text Embeddings models | 8,192 tokens or 50,000 characters; optimized for English; French is in the supported list; On-Demand inference |
| Regional availability | Bedrock user guide, model support by Region | `ca-central-1`: in-region supported, Geo and Global not supported; `ca-west-1` not listed |
| Titan V2 price | Price List API, AmazonBedrock `ca-central-1`, published 2026-10-10T18:22:42Z | `CAN1-TitanEmbeddingV2-Text-input-tokens` USD 0.0001 / 1K tokens (batch USD 0.00005) |
| S3 prices | Price List API, AmazonS3 `ca-central-1`, published 2026-10-12T23:11:02Z | Storage USD 0.025/GB-month (first 50 TB); Tier1 USD 0.0055/1,000; Tier2 USD 0.0044/10,000 |
| Conditional writes and deletes | S3 user guide | `If-None-Match`/`If-Match` on general-purpose buckets; enforcement through `s3:if-none-match`, `s3:if-match` and `s3:ObjectCreationOperation` |
| SDK parameter names | Pinned botocore 1.43.104 service models | `PutObject` has `IfNoneMatch`, `ChecksumSHA256` and `ExpectedBucketOwner`; `DeleteObject` has `IfMatch`; `retries.total_max_attempts` accepted |

- **Data transfer out:** the price is an **assumption** (≤ USD 0.15/GB), not
  read from the price list.
- **Price discrepancy:** the 2024 AWS launch post's USD 0.00002/1K-token figure
  differs from the regional price list; the plan uses the price list.

**Dependency pins.** boto3 and botocore 1.43.104 were released 2026-09-28. Their
dependencies were released between 2024-03-01 and 2026-09-15. All are at least
two weeks old. They were installed only in a scratch virtual environment.

## Local tests (fakes and Stubber, no network)

| Command | Result |
| --- | --- |
| `python3 -B -m unittest discover -s tools/cloud/aws/tests -p 'test_*.py'` (stdlib only) | **36 OK, 2 skipped** (boto3 absent) |
| Same command with the scratch venv (pinned boto3/botocore) | **38 OK** |
| `pyflakes flh_aws tests` (scratch venv) | Clean, after removing two unused imports |
| `ast.parse(..., feature_version=(3, 9))` on every module | OK |

**What the tests cover**
- **Snapshot consistency:**
  - a committed row only in the `-wal` file (autocheckpoint off) is included;
  - a concurrently open uncommitted insert is excluded;
  - the copy has `journal_mode=delete` and integrity `ok`;
  - the manifest contains no absolute paths;
  - the FLH-060 layout is accepted.
- **Refusals before anything is written:**
  - a non-synthetic entry;
  - a missing demo marker;
  - package, state or restore paths inside the repository;
  - restore into a source demo or an existing directory.
- **Corruption:** each of these is rejected, with `RESTORE-REJECTED.json`
  written and no restored database:
  - a flipped snapshot byte, or a truncated snapshot;
  - an edited manifest;
  - a consistently rewritten package (hashes recomputed, caught by the domain
    fingerprint);
  - a non-database file;
  - in-transit corruption of a download (evidence kept).
- **Failed operations:**
  - a failed manifest PUT is recorded `ok, failed`, the run stays incomplete,
    restore refuses it, and cleanup removes the one object that did upload;
  - a Bedrock throttle stops after the 3rd call with no retry (`ok, ok,
    failed`);
  - NaN, zero and short vectors fail after exactly 1 call.
- **Overwrite refusal:**
  - a repeated upload is refused locally with nothing sent;
  - a pre-existing key fails with 412 in the fake and is left intact.
- **Caps:**
  - a reservation over a cap fails, and the ledger persists across instances;
  - an over-size upload is refused with 0 PUTs;
  - a second smoke (6 + 6 > 10) is refused with 0 calls;
  - the adapter answers 429 at 8 + 3 > 10 with nothing sent.
- **Owned-only cleanup:**
  - an unknown key stops the cleanup (exit 1), stays in the bucket and keeps
    the stack;
  - an object whose ETag changed is not deleted;
  - repeated cleanup is safe.
- **Bucket checks:** weakened settings (BlockPublicPolicy false) block the
  upload with 0 PUTs; a second deploy from one state directory is refused.
- **Titan contract:**
  - inference-profile ids, unsupported dimensions, over-length and blank
    inputs are refused;
  - the body is verbatim with no prefix;
  - preflight is read-only;
  - the `aws` backend without a profile is refused with an empty ledger.
- **Adapter:**
  - the Go provider wire format works, sending text verbatim;
  - wrong model, more than 8 inputs or non-string input give 400;
  - a provider failure gives 502 with no data;
  - a non-loopback bind is refused;
  - startup and `/readyz` send nothing.
- **Static checks:**
  - the template has only a bucket and a Deny-only policy with the required
    statements, no versioning, and retention ≤ 14 days;
  - IAM examples have no wildcard actions and are scoped to `flh063`
    resources or the Titan model ARN;
  - smoke inputs are synthetic catalog strings;
  - importing the CLI doesn't import boto3.
- **Stubber** (pinned botocore, placeholder credentials,
  `AWS_CONFIG_FILE`/`AWS_SHARED_CREDENTIALS_FILE` pointed at missing files):
  - the whole deploy → verify → upload → restore → cleanup sequence, and
    `GetFoundationModel` and `InvokeModel`;
  - every request's parameters and stubbed response validated against the AWS
    API models.

## Local end to end on a running FLH-034 demo (fake backend)

**Setup.** `DEMO_PORT=18944 STUB_PORT=18943 scripts/demo/flh034/demo.sh setup
<scratch>/demo` gave exit 0 with 4 entries and 7 Concepts. With the server
running, `demo.db` was 4,096 bytes and `demo.db-wal` 1,273,112 bytes.

| Step | Result |
| --- | --- |
| Raw `cp` of `demo.db` (contrast only) | **0 tables**: the data was only in the WAL |
| `init --backend fake`; `plan --region ca-central-1 --dimensions 512` | Exit 0; upper-bound estimate **USD 0.0456**; no region warning |
| `deploy` | Stack and bucket `flh063-590e0f481feb`; read-back found the 5 Deny statements and 7-day expiration |
| `snapshot --source-demo <demo>` (server running) | 249,856 bytes, journal `delete`. Counts: entries 4, analyses 5, units 10, concepts 7, links 13, memberships 8. The synthetic gate passed on the real seed data |
| `upload` | 2 keys, 253,322 bytes |
| `upload` again | Exit 2: "already uploaded…; keys are immutable" |
| `restore --into <new>` | Integrity `ok`, 0 FK violations, gate passed, counts equal; the restored database reads 4 entries and 7 Concepts |
| `restore --into <demo>/inside` | Exit 2: "--into must be outside a source demo directory" |
| `restore` with an injected in-transit byte flip | Exit 1 "snapshot SHA-256 mismatch"; `download/` and `RESTORE-REJECTED.json` only |
| `cleanup`, then `cleanup` again | `DELETED`, 2 objects deleted; repeat exit 0 |
| `status` | 28 calls, 0 failed, 0 unfinished; S3 used: 2 PUTs, 253,322 bytes, 23 GETs, 1 LIST, 2 DELETEs; Bedrock 0 |

**Adapter with the production server (fake Titan).**
1. I started a copy of the *restored* database under the production
   `cmd/server` binary from the demo. It ran with an empty environment plus
   `LISTEN_HOST=127.0.0.1`, `EMBEDDING_PROVIDER=http`, `EMBEDDING_BASE_URL`
   set to the adapter, and `EMBEDDING_MODEL` set to the adapter identity.
   `/readyz` was ready.
2. `GET /retrieval-evaluation/v1?retriever=embedding_retriever_v1` gave
   `evaluated` with 2 samples.
3. The Go `HTTPProvider` sent 2 × 8 inputs through the adapter: **16 fake
   InvokeModel** calls, 16 ledger entries, 0 failed.

This shows that the restored database opens in the production server and that
the wire format is compatible. The metrics come from hash vectors and mean
nothing. Afterwards:
- the adapter, the server and the FLH-034 demo were stopped, with no listener
  left on 18943, 18944, 18950 or 18951;
- no `__pycache__` was left in the repository.

Scratch evidence (outside the repository) is in the session scratchpad, under
`flh063/e2e/`.

## NOT RUN

- **AWS** (no profile supplied):
  - CloudFormation stack creation and real bucket read-back;
  - real S3 conditional PUT/DELETE and bucket-policy evaluation;
  - upload, download and restore in AWS;
  - `GetFoundationModel`, the Titan smoke and real IAM evaluation of the
    example policies.
- **Not done:**
  - an AWS Budget alert;
  - Billing console reconciliation;
  - lifecycle expiration actually removing objects.
- **Platforms:** Windows (by decision; the ledger uses `fcntl`) and runtimes
  other than Python 3.13.
- **Out of scope:** any larger embedding comparison, retrieval-quality claim,
  semantic index build with Titan, scheduling or real personal backups.
