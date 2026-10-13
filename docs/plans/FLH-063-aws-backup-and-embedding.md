# FLH-063 Bounded AWS backup/restore and embedding smoke

Owner: local Claude Code. Branch label supplied: `feat/flh-063-aws-backup-and-embedding`.
No Git/GitHub command or subagent was used. Evidence:
[validation](../validation/FLH-063-aws-backup-and-embedding.md). Operator
guide: [CLOUD_EXPERIMENT.md](../CLOUD_EXPERIMENT.md).

**Human decisions:**
- AWS, with a USD 10 incremental allowance for this first experiment.
- Scoped cloud resources and a cloud model are authorized.
- Synthetic data only.
- No Windows GPU dependency.

**Not changed:** production Go, the frontend, migrations, provider defaults,
the evaluation fixtures, daily data and the FLH-034/FLH-060 demos (reused, not
edited). Nothing is deployed publicly.

## Files (exact edit set)

| File | Purpose |
| --- | --- |
| `tools/cloud/aws/flh_aws/__init__.py`, `__main__.py`, `cli.py` | Package and the `python3 -m flh_aws` operator CLI |
| `tools/cloud/aws/flh_aws/ledger.py` | Persistent, locked caps ledger: reserve before every billable call |
| `tools/cloud/aws/flh_aws/snapshot.py` | Synthetic-source gate, SQLite backup-API snapshot, manifest, package verification |
| `tools/cloud/aws/flh_aws/restore.py` | Isolated restore with verification before acceptance |
| `tools/cloud/aws/flh_aws/s3store.py` | Stack deploy and verification, immutable upload, download, owned-only cleanup |
| `tools/cloud/aws/flh_aws/titan.py` | Titan V2 request/response contract, preflight, bounded smoke |
| `tools/cloud/aws/flh_aws/adapter.py` | Loopback adapter speaking the existing `HTTPProvider` wire format |
| `tools/cloud/aws/flh_aws/awsclients.py` | boto3 sessions from an explicit profile and region; retries off |
| `tools/cloud/aws/flh_aws/fakes.py` | Filesystem-backed fake S3, CloudFormation, STS and Bedrock for local runs and tests |
| `tools/cloud/aws/template/flh063-backup-bucket.json` | CloudFormation template (the only resource-creation path) |
| `tools/cloud/aws/iam/*.json` | Least-privilege policy examples: deploy, backup runtime, Bedrock |
| `tools/cloud/aws/smoke_inputs.json` | Synthetic smoke inputs (at most 10) |
| `tools/cloud/aws/requirements.txt` | Pinned boto3/botocore and dependencies (live use only) |
| `tools/cloud/aws/tests/` | Offline tests (stdlib), plus botocore Stubber shape tests when boto3 is installed |
| `tools/cloud/aws/README.md` | Tool reference |
| `docs/CLOUD_EXPERIMENT.md`, this plan, the validation report | Documentation |

## Contracts

**State directory** (`--state DIR`, required by every command)
- It must be absolute, outside the repository, and not inside a demo directory.
- It holds:
  - `ledger.json`, the caps and every attempted call;
  - `resources.json`, the stack, bucket, account, region and owned objects with
    ETag, size and SHA-256;
  - `evidence/`;
  - packages and restores.
- Raw evidence stays there, outside Git.

**Credentials and region**
- Live commands need an explicit `--profile` and `--region`, and build a normal
  `boto3.Session(profile_name=…, region_name=…)`.
- No credential file, key, token or `.env` is read or printed.
- Clients use `retries={"total_max_attempts": 1}` and bounded timeouts.
- No call is made on import or startup.

**A. Backup and restore**
1. **Synthetic gate**
   - The source must be an FLH-034 (`.flh034-demo`) or FLH-060 (`.flh060-demo`)
     demo directory.
   - Every `learning_entries.original_input` and `knowledge_concepts.target`
     must appear verbatim (case-insensitively) in the reused synthetic
     sources: `scripts/demo/flh034/seed.py` or `scripts/demo/flh060/catalog.py`.
   - Anything else is refused before a snapshot is written. The gate is a guard
     against accidents, not a proof.
2. **Snapshot**
   - Uses Python `sqlite3.Connection.backup` from a read-only source
     connection, so it is safe on a running WAL database.
   - The copy's journal mode is set to DELETE, so it is one file.
   - `integrity_check` must be `ok`, and `foreign_key_check` must be empty.
3. **Manifest** `flh063_backup_manifest_v1`. It records:
   - the snapshot's bytes and SHA-256;
   - SQLite version, page size and count;
   - the applied migrations, and the SHA-256 of each repository migration,
     `go.mod` and `go.sum`;
   - an optional human-supplied source revision (no Git is run);
   - domain counts and a domain fingerprint computed from the snapshot;
   - the tool version.
   - Absolute paths are not recorded.
4. **Bucket**
   - Created only by the CloudFormation template, stack
     `flh063-<id>`, bucket `flh063-<id>` with tags `flh:task=FLH-063` and
     `flh:state-id=<id>`.
   - All four public-access blocks are on, and ownership is
     `BucketOwnerEnforced`.
   - SSE-S3 (`AES256`) is explicit, and versioning is not enabled.
   - Lifecycle: objects expire after `RetentionDays` (default 7, allowed
     1–14), and incomplete multipart uploads are aborted after 1 day.
   - The bucket policy denies:
     - non-TLS access;
     - PutObject without `x-amz-server-side-encryption: AES256`;
     - PutObject without `If-None-Match`;
     - DeleteObject without `If-Match`.
   - Before any upload, the tool reads back and checks every one of these
     settings and the bucket region.
5. **Upload**
   - Keys are `flh063/<run_id>/snapshot.sqlite3`, then
     `flh063/<run_id>/manifest.json`. The manifest goes last, as the
     completion marker.
   - Each put sends:
     - `IfNoneMatch="*"`, so an existing key fails with 412 and is never
       overwritten;
     - `ServerSideEncryption="AES256"`;
     - `ChecksumSHA256`, verified by S3;
     - `ExpectedBucketOwner`.
   - Local refusal comes before any request when the run already exists in
     state.
   - Caps: 100 MiB of total uploaded bytes and 20 PUTs per state directory,
     reserved before sending.
6. **Restore**
   - The target `--into` must be a new directory outside the repository and
     the source demo. The original database is never written.
   - The restore goes through these steps in order:
     1. download to `.part` files, then rename;
     2. check the manifest SHA-256 against the value recorded at upload (or
        `--expect-manifest-sha256`);
     3. check the snapshot's bytes and SHA-256;
     4. `integrity_check` and `foreign_key_check`;
     5. check the migrations, counts and fingerprint against the manifest;
     6. rerun the synthetic gate;
     7. only then copy to `restored/demo.db` and write `RESTORE-ACCEPTED.json`.
   - Any failure writes `RESTORE-REJECTED.json`, leaves no restored database
     and exits 1.
7. **Cleanup**
   - For each recorded object, it runs HeadObject, then checks the ETag and the
     `flh-run` metadata, then runs `DeleteObject(IfMatch=<etag>)`.
   - It then lists the bucket. Any unknown key stops the cleanup: unknown keys
     are reported and never deleted, and the stack is kept.
   - Only an empty, correctly tagged bucket is removed, through
     `DeleteStack` on the recorded stack name.

**B. Bedrock Titan Text Embeddings V2**
- **Model and region**
  - Model `amazon.titan-embed-text-v2:0`, on-demand InvokeModel only.
  - An inference-profile id (`us.`, `ca.`, `global.` and so on) is refused.
  - The region must be explicit, and the plan and docs recommend
    `ca-central-1`. AWS documents in-region support there, with no Geo or
    Global inference profile.
- **Request:** `{"inputText", "dimensions": 256|512|1024 (required flag),
  "normalize": true, "embeddingTypes": ["float"]}`. The text is sent verbatim:
  no `query: `/`passage: ` prefix.
- **Response check:** the length must equal the dimensions, values must be
  finite, the norm nonzero, and the normalized norm within 1e-3 of 1.
  `inputTextTokenCount` is recorded.
- **`titan-preflight`:** only `GetFoundationModel` (control plane), which must
  report `ACTIVE` and `ON_DEMAND`. No InvokeModel.
- **`titan-smoke --allow-live`**
  - Up to 10 inputs from `smoke_inputs.json`, one InvokeModel each.
  - Ledger caps: 10 invocations, 2,000 characters per input, 8,000 characters
    and 64 KiB of request bodies in total.
  - Every attempt is recorded before sending, failures included.
- **Adapter**
  - Loopback only; `POST /v1/embeddings {model, input[]}` returns `{data:
    [{index, embedding}]}`, as `internal/embedding/http.go` expects.
  - Its model identity is
    `bedrock/amazon.titan-embed-text-v2:0/<region>/d<dims>/normalize/flh_titan_verbatim_v1`.
    Any other identity gets 400.
  - It needs `--allow-live` to use AWS, and shares the ledger.
  - Failure gives 502 with no partial vectors.
  - It sends no request at startup.

**Exit codes:** 0 OK; 1 failure (AWS error, verification failed); 2 usage or
refusal, including a whole-plan budget pre-check (nothing sent); 3 a single
call would exceed a cap (that call is not sent).

## Resource plan and cost estimate (before any write)

Prices are from the AWS Price List API, read without credentials. The Bedrock
`ca-central-1` offer was published 2026-10-10T18:22:42Z, the S3 `ca-central-1`
offer 2026-10-12T23:11:02Z.

| Item | Price | Bounded use | Estimate |
| --- | --- | --- | --- |
| Titan V2 on-demand input tokens (`CAN1-TitanEmbeddingV2-Text-input-tokens`) | USD 0.0001 / 1K tokens | ≤ 8,000 characters, counted conservatively as ≤ 8,000 tokens | ≤ USD 0.0008 |
| S3 Standard storage (`CAN1-TimedStorage-ByteHrs`) | USD 0.025 / GB-month | ≤ 100 MiB for ≤ 14 days | ≤ USD 0.0012 |
| S3 PUT/COPY/POST/LIST (`CAN1-Requests-Tier1`) | USD 0.0055 / 1,000 | ≤ 20 PUT + ≤ 20 LIST | ≤ USD 0.0003 |
| S3 GET and other (`CAN1-Requests-Tier2`) | USD 0.0044 / 10,000 | ≤ 100 | ≤ USD 0.0001 |
| Data transfer out to the internet | Assumed ≤ USD 0.15 / GB (**not verified** from the price list) | ≤ 300 MiB download cap | ≤ USD 0.045 |
| CloudFormation (AWS resource types only), SSE-S3, public-access block | No charge expected | — | — |
| **Total (conservative)** | | | **< USD 0.05**, against the USD 10 allowance |

**Not created:**
- EC2, GPUs, NAT gateways, provisioned throughput, vector databases or always-on
  compute;
- CloudTrail data events, extra logging or KMS keys.

Free-tier eligibility is not assumed. An AWS Budget alert is optional
monitoring only, not a hard ceiling. This is an estimate, not a billing result.

## Acceptance

| # | Criterion | How |
| --- | --- | --- |
| L1 | Snapshot of a running WAL database is consistent | Local test with a concurrent writer and uncheckpointed WAL; FLH-034 demo end to end |
| L2 | Corruption of the snapshot, manifest, size or domain data fails before acceptance | Local tests and fake-backend CLI |
| L3 | Failed upload and failed invocation are recorded and leave no accepted state | Local fakes |
| L4 | An existing key and a repeated run are refused | Fake S3 enforcing `If-None-Match` and local state |
| L5 | Caps are enforced before sending and persist | Local tests |
| L6 | Cleanup removes only owned objects and resources; unknown keys are kept and reported | Local fakes |
| L7 | Requests match the real AWS API shapes | botocore Stubber with the pinned botocore |
| C1 | One synthetic upload/download/restore in AWS | Needs a supplied profile |
| C2 | Bounded Titan smoke (≤ 10 InvokeModel) | Needs a supplied profile |
