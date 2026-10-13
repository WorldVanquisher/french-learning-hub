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
- For SSO, sign in with your usual AWS CLI flow first.
- If InvokeModel answers `AccessDeniedException` for the model, check Bedrock
  model access for Amazon Titan Text Embeddings V2 in the console.

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
