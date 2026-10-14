# Cloud experiment: AWS backup/restore and Bedrock embedding smoke (FLH-063)

This is a bounded first experiment on AWS. It uses **synthetic data only** and
has a USD 10 incremental allowance. It doesn't change how the application runs:
- no production code, provider default or migration changes;
- no scheduled backups;
- no real personal data;
- no public deployment.

Tools and command reference: [tools/cloud/aws/README.md](../tools/cloud/aws/README.md).
Contract: [plan](plans/FLH-063-aws-backup-and-embedding.md). Evidence:
[validation](validation/FLH-063-aws-backup-and-embedding.md).

**Recovery and reproducibility (FLH-066):** [plan](plans/FLH-066-aws-experiment-recovery.md),
[validation](validation/FLH-066-aws-experiment-recovery.md). These changes
address the three gaps FLH-064's live run exposed:
- the `aws login` dependency;
- the Titan account-verification block;
- deletion that could not be verified, because the StackId was not kept.

The guide for the next real run is [below](#next-real-run-flh-066).

## What it shows

**A. Backup and isolated restore.**
1. A consistent SQLite snapshot of a synthetic demo database is packaged with
   its metadata and hashes.
2. It is uploaded under immutable keys to one private, encrypted, TLS-only
   bucket that expires its contents.
3. It is downloaded into a new directory and verified.
4. Only then is it accepted as restored.

The original database is never touched.

**B. Bedrock embedding smoke.** At most 10 on-demand InvokeModel calls to
Amazon Titan Text Embeddings V2 on synthetic sentences, checking that the
vectors are finite, nonzero, normalized and of the requested dimension. A
loopback adapter lets the existing Go `HTTPProvider` use Titan under its own
model identity. It's for a later, separately authorized comparison.

**Not shown:** retrieval quality, RAG, training, automatic SAME, hybrid search,
production readiness or any billing figure.

## Region and model decision

The decision is **`ca-central-1` (Canada Central), base model
`amazon.titan-embed-text-v2:0`, on-demand in-region InvokeModel.** The tools
refuse inference-profile ids and never choose a region themselves.

**Checked on 2026-10-13 against AWS documentation and price data:**
- **Regional availability** (Bedrock user guide, "Model support by AWS
  Region"): Titan Text Embeddings V2 is supported **in-region** in
  `ca-central-1`. Geo and Global inference profiles are **not** supported
  there. `ca-west-1` is not listed for this model.
- **API** (Bedrock user guide, Titan Embeddings request/response):
  - request fields `inputText` (required), `dimensions` (1024 default, 512 or
    256), `normalize` (default true) and `embeddingTypes`;
  - response fields `embedding`, `inputTextTokenCount` and `embeddingsByType`;
  - at most 8,192 tokens or 50,000 characters per input.
  - The model is documented as optimized for English, with French among the
    listed supported languages.
- **Price** (AWS Price List API, Bedrock `ca-central-1` offer published
  2026-10-10T18:22:42Z): `CAN1-TitanEmbeddingV2-Text-input-tokens` is **USD
  0.0001 per 1K input tokens** on demand. This is higher than the USD 0.00002
  figure in AWS's 2024 launch post, so the regional price list is used here.

## Cost plan (before any write)

| Item | Bounded use | Conservative estimate |
| --- | --- | --- |
| Titan V2 input tokens (USD 0.0001 / 1K) | ≤ 8,000 characters, counted as ≤ 8,000 tokens | ≤ USD 0.0008 |
| S3 Standard storage (USD 0.025 / GB-month) | ≤ 100 MiB for ≤ 14 days | ≤ USD 0.0012 |
| S3 PUT/LIST (USD 0.0055 / 1,000) | ≤ 40 | ≤ USD 0.0003 |
| S3 GET and other (USD 0.0044 / 10,000) | ≤ 140 | ≤ USD 0.0001 |
| Data transfer out | ≤ 300 MiB at an **assumed** ≤ USD 0.15/GB | ≤ USD 0.045 |
| **Total** | | **≈ USD 0.05 upper bound** |

`python3 -m flh_aws plan` prints the same figures from the caps.

**Assumptions and limits:**
- S3 prices are from the `ca-central-1` S3 offer published
  2026-10-12T23:11:02Z. The transfer price is an assumption, not read from the
  price list.
- CloudFormation (AWS resource types), SSE-S3 and the public-access block are
  not expected to cost anything.
- Free tier is not assumed. This is an estimate, not a bill.
- An AWS Budget alert can be set in the console as monitoring. It is not a hard
  spending ceiling.

**Never created:**
- EC2, GPU instances, NAT gateways, provisioned throughput, a vector database
  or always-on compute;
- KMS keys, CloudTrail data events or other extra logging.

## Safety design in one page

- **Synthetic only**
  - The source must be an FLH-034 or FLH-060 demo directory.
  - Every stored learner text and Concept target must appear in those demos'
    seed sources.
  - This guards against accidents; it doesn't prove that data is synthetic.
- **Consistent snapshot.** It uses the SQLite online backup API, never a file
  copy. In the local run, a raw copy of the running demo's `demo.db` had **0
  tables**, because every row was still in the `-wal` file.
- **Immutable keys.** The bucket policy and every request require
  `If-None-Match: *`, so an existing key fails with 412 and is never
  overwritten.
- **Restore is verified before acceptance.** It checks:
  - the manifest hash recorded at upload, and the snapshot's size and hash;
  - SQLite integrity and foreign keys;
  - the migrations, the domain counts and fingerprint, and the synthetic gate.

  A failure keeps evidence and restores nothing. The target is always a new
  directory.
- **Owned-only cleanup**
  - Each object the tools wrote is deleted with `If-Match: <recorded ETag>`.
  - Any unknown object stops the cleanup and is reported, never deleted.
  - The stack is deleted only when the bucket is empty and its tags identify
    the state directory.
- **Receipts and honest cleanup (FLH-066)**
  - **Receipt:** the full StackId is saved as soon as `CreateStack` answers.
    Every later read and the `DeleteStack` use it.
  - **Deletion confirmed** means `DELETE_COMPLETE` read by StackId *and*
    `NoSuchBucket`. Otherwise cleanup reports one of: deletion requested,
    verification unavailable, or resources still present.
  - **Lost answers:** a write whose answer was lost is never resent blindly.
    `recover` reconciles read-only.
- **Short retention.** Lifecycle expiration is 7 days by default (14 at most).
  Incomplete multipart uploads are aborted after 1 day. S3 removes expired
  objects asynchronously.
- **Budget**
  - A local ledger reserves every billable call before sending it and keeps
    every attempt and outcome.
  - It has hard local caps.
  - There are no SDK retries and no live call on startup.
- **Credentials.** A named profile goes through boto3's normal resolution. The
  tools never read or print credential files, keys, tokens or `.env`.

## Running it (human operator)

**Prerequisites**
- An AWS account and a profile whose identity has the three policies in
  `tools/cloud/aws/iam/` attached, with `ACCOUNT_ID` replaced.
- Sign in with your usual AWS CLI flow first (`aws login --profile P`, or SSO).
  An `aws login` profile needs `awscrt`, which `requirements.txt` now pins.
  `auth-check` confirms the credentials resolve before anything is created.
- If InvokeModel answers `AccessDeniedException`, the smoke report's
  `category` names the cause (see the tool README):
  - account verification still pending;
  - IAM denial;
  - model access not granted;
  - `unknown`.

```sh
cd tools/cloud/aws
python3 -m venv "$HOME/flh063/venv" && "$HOME/flh063/venv/bin/pip" install -r requirements.txt
PY="$HOME/flh063/venv/bin/python"; P=YOUR_PROFILE; R=ca-central-1
STATE="$HOME/flh063/state-aws"; DEMO="$HOME/flh063/demo"

DEMO_PORT=18944 STUB_PORT=18943 bash ../../../scripts/demo/flh034/demo.sh setup "$DEMO"   # synthetic DB
$PY -B -m flh_aws init  --state "$STATE" --backend aws
$PY -B -m flh_aws plan  --state "$STATE" --region $R --dimensions 512      # read the region decision and estimate
$PY -B -m flh_aws titan-preflight --state "$STATE" --profile $P --region $R  # read-only

$PY -B -m flh_aws deploy   --state "$STATE" --profile $P --region $R --allow-live
$PY -B -m flh_aws snapshot --state "$STATE" --source-demo "$DEMO"           # prints run_id
$PY -B -m flh_aws upload   --state "$STATE" --profile $P --run RUN_ID --allow-live
$PY -B -m flh_aws restore  --state "$STATE" --profile $P --run RUN_ID --into "$HOME/flh063/restore-1"
$PY -B -m flh_aws titan-smoke --state "$STATE" --profile $P --region $R --dimensions 512 --allow-live   # 6 calls
$PY -B -m flh_aws cleanup  --state "$STATE" --profile $P --allow-live
$PY -B -m flh_aws status   --state "$STATE"
bash ../../../scripts/demo/flh034/demo.sh stop "$DEMO"
```

- **Evidence:** keep the state directory's `evidence/`, `ledger.json` and
  `resources.json` outside the repository.
- **Check afterwards:** look at the Billing console after AWS's usual reporting
  delay. The ledger records attempted calls and the usage AWS returned; it is
  not a bill.

**Trying the adapter with the server** (a later, separately authorized
comparison). Start `adapter … --allow-live --port 18951`, then run the server
with:
- `EMBEDDING_PROVIDER=http`;
- `EMBEDDING_BASE_URL=http://127.0.0.1:18951/v1`;
- `EMBEDDING_MODEL` and `EMBEDDING_MODEL_ID` set to the adapter's printed
  identity, and `EMBEDDING_DIMENSIONS` to the chosen size.

Every vector costs one InvokeModel call from the same 10-call budget, so a
semantic index build needs a separately authorized, larger budget.

## Next real run (FLH-066)

This is the human operator's procedure. It continues FLH-064 **without
repeating the S3 deployment**. It has not been run: every command below
contacts AWS, and FLH-066 was implemented and tested offline only.

**What carries over from FLH-064** (read from `~/flh064/state-aws`):
- The backup/restore stages passed, and cleanup reported `DELETED`.
- The stack was never confirmed `DELETE_COMPLETE` by StackId, because none
  was recorded. `status` now shows it as `verification_unavailable`.
- The ledger has 35 calls, 1 of them failed: the Titan InvokeModel
  (account verification). That leaves **9 of 10** invocations.

**1. A venv from the pinned requirements, and the offline tests in it.**
`test_requirements_pin_awscrt_exactly_as_botocores_crt_extra` and the
credential tests must pass.

```sh
cd tools/cloud/aws
mkdir -p "$HOME/flh066"
python3 -m venv "$HOME/flh066/venv" && "$HOME/flh066/venv/bin/pip" install -r requirements.txt
PY="$HOME/flh066/venv/bin/python"; P=flh; R=ca-central-1
(cd ../../.. && "$PY" -B -m unittest discover -s tools/cloud/aws/tests -p 'test_*.py')
```

**2. Continue the same ledger in a copy, keeping the FLH-064 evidence
frozen.**
- The copy carries every counter, so nothing is reset.
- From now on, use only the copy for live commands. Two live copies of one
  ledger would double the budget.

```sh
cp -Rp "$HOME/flh064/state-aws" "$HOME/flh066/state-aws"
chmod -R a-w "$HOME/flh064/state-aws"          # optional: makes accidental reuse fail
STATE="$HOME/flh066/state-aws"
$PY -B -m flh_aws status --state "$STATE"       # no network: 9 invocations remaining
```

**3. Sign in and check credentials.** This creates nothing; its only request
is `GetCallerIdentity`.

```sh
aws login --profile $P
$PY -B -m flh_aws auth-check --state "$STATE" --profile $P --region $R
```

A refusal names its category, for example `missing_dependency` (wrong venv)
or `expired_credentials` (sign in again).

**4. Rerun only the Titan smoke.**
- **Before:** make sure AWS has finished verifying the account (the
  verification email, or the console no longer showing the banner). Each
  failed attempt still costs 1 of the remaining invocations.

```sh
$PY -B -m flh_aws titan-preflight --state "$STATE" --profile $P --region $R
$PY -B -m flh_aws titan-smoke --state "$STATE" --profile $P --region $R --dimensions 512 --allow-live --only-missing
$PY -B -m flh_aws status --state "$STATE"
```

- **Expected:**
  - `completed_calls: 6`;
  - `bedrock_invocations` used 7 of 10;
  - `ledger_history_before.failed_by_category` is `{"unrecorded": 1}`, because
    FLH-064's failure predates categories (its evidence file keeps the
    message).
- **If it fails again:** the report's `error.category` says why. Stop, and
  rerun the same command only after addressing that cause. Never reset the
  ledger, raise a cap or redeploy S3 to retry Titan.

**5. (Optional, read-only) Settle FLH-064's stack record.**
1. Find the StackId of `flh063-74ca91fbb3d3`: in the CloudFormation console,
   region `ca-central-1`, Stacks, use the filter **Deleted** and copy the
   Stack ID. Or look in the CloudTrail event history for `CreateStack` →
   `responseElements.stackId`.
2. Then run:

   ```sh
   $PY -B -m flh_aws recover --state "$STATE" --profile $P --stack-id 'arn:aws:cloudformation:ca-central-1:ACCOUNT:stack/flh063-74ca91fbb3d3/UUID'
   ```

- **Result:**
  - `deletion_confirmed` (exit 0) needs `DELETE_COMPLETE` by StackId and
    `NoSuchBucket`;
  - anything else exits 4 with steps.
- **Retention:** CloudFormation keeps deleted stacks readable for a limited
  time (90 days per its documentation), so do this soon.

**6. (Optional, needs a separate owner decision) A fresh receipt
acceptance.** Only this step creates resources: a new stack and bucket, and
the S3 requests under the same caps. Use a **new** state directory with its
own ledger. Then run `deploy`, `cleanup` and `status` from the command list
above. The new receipt has a full StackId, and `cleanup` should report
`deletion_confirmed`.

**Afterwards:** check the Billing console after AWS's reporting delay. The
ledger and these commands are not a bill, and nothing here proves zero
charges.
