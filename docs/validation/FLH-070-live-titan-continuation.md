# FLH-070 validation: live Titan continuation

Date: 2026-10-14. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64). Procedure:
[CLOUD_EXPERIMENT.md, "Next real run"](../CLOUD_EXPERIMENT.md#next-real-run-flh-066).

**Outcome: COMPLETE.** All six missing synthetic smoke inputs were embedded
by Amazon Titan Text Embeddings V2 in `ca-central-1` at 512 dimensions:
- **6 successful live calls**, with no failure in this run;
- **7 attempted invocations in total**, counting FLH-064's failed attempt;
- **3 of 10 invocations remain.**

**Not claimed:**
- **Retrieval quality and benchmarks:** this smoke checks the API contract
  and vector shape only.
- **Billing:** unverified; there is no billing evidence, and no charge figure
  (zero or otherwise) is claimed.
- **Old stack record:** `flh063-74ca91fbb3d3` remains
  `verification_unavailable`, because its exact StackId is not available.
- **Account-verification timeline:** the successful InvokeModel calls prove
  **current** access. They do not establish when AWS finished verifying the
  account.

**Not used:** Git/GitHub, subagents, Windows, the NAS, a GPU or Docker. No
S3 deployment, new resource, IAM change, cap change, counter reset, automatic
retry, index build, adapter evaluation or benchmark.

**Not read or printed:** credentials, tokens, private keys or `.env`. The
account id is masked in all printed output.

## History: the earlier block

The first attempt that day stopped at sign-in:
- `auth-check` was refused before any request, with exit 2,
  `expired_credentials: LoginRefreshRequired`.
- It was not retried, and the ledger stayed byte-identical.
- The human ran `aws login --profile flh`, then authorized resuming from
  `auth-check`. Preparation was not repeated.

## Preparation (local, before any live call)

- **Venv:** the isolated scratchpad venv built in FLH-068 from the unchanged
  `tools/cloud/aws/requirements.txt` (SHA-256 `3e193efe…709b`).
  - Freeze: `awscrt==0.36.0 boto3==1.43.104 botocore==1.43.104
    jmespath==1.1.0 python-dateutil==2.9.0.post0 s3transfer==0.19.2
    six==1.17.0 urllib3==2.8.0`.
  - Offline suites in it, with the AWS config, credentials and login cache
    pointed at empty paths: **82 tests, OK, 0 skipped**. These are local tests
    only, not AWS evidence.
- **One authoritative continuation state:** `~/flh066/state-aws`.
  - The search found the original plus two read-only scratchpad test copies
    from FLH-066 and FLH-068. Both were identical to the original and never
    used live, and were deleted before the run.
  - No earlier continuation existed.
  - The new state was copied once with `cp -Rp` and was identical to
    `~/flh064/state-aws` (`diff -r`).
  - `~/flh064` was never written: 0 files changed, and no `chmod` was applied.
- **Status before the run:**
  - 35 ledger calls: 1 failed (FLH-064's Titan account-verification denial),
    0 unfinished;
  - invocations 1 used / 9 remaining;
  - the stack `verification_unavailable`.
- **Local continuation plan:** 0 done; 6 to send (209 characters, 714 request
  bytes). This fits the remaining budget.

## Live AWS results

All commands used profile `flh`, region `ca-central-1` and state
`~/flh066/state-aws`. Each ran exactly once.

| Step | Result |
| --- | --- |
| `auth-check` (GetCallerIdentity) | Exit 0. Credential method `login`; principal `arn:aws:iam::<account>:user/flh-experiment`, an IAM user and not root. The account matches the receipt's recorded account (compared locally, not printed) |
| Account verification evidence | No console or email evidence was available. The run went ahead on the human's authorization. Its success shows InvokeModel access at run time only (see above) |
| `titan-preflight` (GetFoundationModel) | Exit 0. `amazon.titan-embed-text-v2:0` is `ACTIVE`, `ON_DEMAND`, `EMBEDDING`. This alone was not taken as proof of InvokeModel access |
| `titan-smoke --dimensions 512 --allow-live --only-missing` | Exit 0, 2026-10-14T21:20:18.944Z–21:20:19.915Z. `planned_calls 6`, `completed_calls 6`, `error null`, `skipped_already_ok []`, `not_reused []`. Identity: `bedrock/amazon.titan-embed-text-v2:0/ca-central-1/d512/normalize/flh_titan_verbatim_v1` |

**Per-call results** (synthetic inputs from `tools/cloud/aws/smoke_inputs.json`):

| Input | Chars | `inputTextTokenCount` (= header) | Norm | Latency | Request id (prefix) | Vector SHA-256 (prefix) |
| --- | --- | --- | --- | --- | --- | --- |
| en-weather-child | 44 | 11 | 0.99999999 | 260.2 ms | `181d2cd3` | `5de1193e1133` |
| fr-imparfait-example | 40 | 14 | 1.00000003 | 147.0 ms | `7fa8a1dc` | `e4c9e73f6628` |
| en-lived-still | 46 | 11 | 1.00000001 | 125.9 ms | `cea5a46b` | `39252ccc506e` |
| fr-depuis-example | 29 | 9 | 0.99999996 | 129.5 ms | `5e381322` | `40d93b13857e` |
| en-not-anymore | 35 | 9 | 0.99999995 | 129.3 ms | `9e08027d` | `ca182bef780f` |
| fr-ne-plus-example | 15 | 6 | 1.00000006 | 128.1 ms | `9dde6bc1` | `5b3a76e90264` |

- **Totals:** 209 characters and **60 input tokens**. The body token count
  equals the `x-amzn-bedrock-input-token-count` header for every call.
- **Vector validation** happened **in process**, before each call was
  recorded `ok`. Every response had:
  - exactly 512 values, all finite and numeric;
  - a nonzero vector, with norm within 1e-3 of 1 (observed 0.99999995 to
    1.00000006);
  - `embeddingsByType.float` equal to `embedding`;
  - a positive `inputTextTokenCount`.

  The six vector hashes are distinct.
- **Raw vectors were not retained,** only their SHA-256 and norms. These
  checks therefore cannot be recomputed from the evidence without calling the
  model again, which was not done.
- The report's pairwise cosine values are exploratory observations on
  synthetic sentences. They are not relevance, quality or SAME judgments.

## Ledger and accounting (read locally after the run)

- **Calls:** 41 in total. The first 35 records equal the original FLH-064
  ledger exactly.
- **InvokeModel records:**
  - seq 29 `failed`: FLH-064, still charged, `failed_by_category:
    {"unrecorded": 1}`;
  - seqs 36–41 `ok`, one per input.
- **Binding:** each `ok` record carries the full `flh068_titan_request_v1`
  binding, matching its exact text and request.
- **Bedrock usage:**

  | Counter | Used | Remaining | Cap |
  | --- | --- | --- | --- |
  | Invocations | 7 | **3** | 10 |
  | Input characters | 253 | 7,747 | 8,000 |
  | Request bytes | 842 | 64,694 | 65,536 |

  Caps are unchanged from FLH-064.
- **History:** 7 attempted, 6 ok (6 bound, 0 legacy), 1 failed, 0 unfinished.
- **Completed continuation plan** (local only, no model call): 6 done, 0 to
  send, nothing reported as not reusable.
- **S3:** no S3 request was made in this task. The S3 counters are FLH-064's,
  including its cleanup.

## Stack record

`flh063-74ca91fbb3d3` remains **`verification_unavailable`**. FLH-064 recorded
no StackId, so `DELETE_COMPLETE` cannot be confirmed. No `recover` was run, and
no `ListStacks` permission was requested.

**Human step to settle it:**
1. Open the CloudFormation console, region `ca-central-1`, Stacks, filter
   **Deleted**, and copy the Stack ID of `flh063-74ca91fbb3d3`.
2. Run the read-only command:

   ```sh
   recover --state ~/flh066/state-aws --profile flh --stack-id '<that ARN>'
   ```

## Evidence (outside the repository)

| File | SHA-256 |
| --- | --- |
| `~/flh066/titan-smoke.json` (CLI output) | `0510334f…367556` |
| `~/flh066/state-aws/evidence/titan-smoke-2026-10-14T212018944241Z.json` | `8b703659…78b850` |
| `~/flh066/state-aws/ledger.json` (after the run) | `8826af5c…b7bc90bd` |

Also kept: `~/flh066/auth-check-2.json`, `~/flh066/preflight.json`,
`~/flh066/status-before.json`, the earlier refusal
(`~/flh066/auth-check.err`), and the tool's own `evidence/*auth-check*` and
`*titan-preflight*` records.
