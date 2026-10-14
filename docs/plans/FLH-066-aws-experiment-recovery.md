# FLH-066 AWS experiment recovery and reproducibility

Owner: local Claude Code. Branch label supplied: `fix/flh-066-aws-experiment-recovery`.
No Git/GitHub command or subagent was used. Evidence:
[validation](../validation/FLH-066-aws-experiment-recovery.md). Operator
guide: [CLOUD_EXPERIMENT.md](../CLOUD_EXPERIMENT.md#next-real-run-flh-066).

**Scope:** local only, with no Windows, NAS, GPU, Docker or live AWS. It
fixes the three operational gaps FLH-064's live run exposed, in the
FLH-063 tools.

**Not changed:**
- the FLH-065 files and the FLH-064 report and evidence (`~/flh064` was read
  only);
- Go production code, migrations, the IAM policy examples and `AGENTS.md`;
- the CloudFormation template.

## Observed in FLH-064 (read from `~/flh064`, read-only)

| Gap | Evidence |
| --- | --- |
| Credentials | `raw/preflight.out`: `MissingDependencyException: Using the login credential provider requires an additional dependency … pip install "botocore[crt]"`. The working venv then had `awscrt==0.36.0` (`raw/venv-freeze.txt`), installed outside `requirements.txt` |
| Titan | `evidence/titan-smoke-*.json`: 1 InvokeModel, `AccessDeniedException` "Your account is currently being verified…", truncated at 300 characters of `str(e)`, no category. The ledger keeps it as failed and charged (9 of 10 left) |
| Deletion | `resources.json` holds `{"name": "flh063-74ca91fbb3d3", "status": "DELETED"}` with no StackId. `raw/verify-stack.out`: DescribeStacks by name says "does not exist", which is also what a never-created stack returns. `raw/verify-stack-deleted.out`: `ListStacks` AccessDenied (not granted, and not needed) |

**Root cause of the first gap,** verified offline:
- botocore 1.43.104's `LoginProvider.load()` raises `MissingDependencyException`
  when the profile has `login_session` and `awscrt.crypto.EC` cannot be
  imported.
- botocore's `crt` extra pins `awscrt (==0.36.0)`.
- Reproduced with the old requirements and a synthetic `login_session`
  profile.

## Contracts

### 1. Authentication prerequisites

- **Requirements:** `requirements.txt` adds `awscrt==0.36.0`, exactly
  botocore's `crt` pin. It was uploaded to PyPI on 2026-07-16, with wheels for
  macOS, Linux and Windows. No other dependency changes.
- **`aws_clients`:**
  - resolves the profile in memory with `get_credentials()` and
    `get_frozen_credentials()` before returning any client;
  - any failure is a `Refused` (exit 2) naming a category and the fix, and
    stating that no AWS resource request was sent;
  - no credential value, token or account id is printed.
- **`auth-check`:** SDK versions, the credential method, the principal ARN with
  the account masked, and the account's last 4 digits. Its only request is
  `GetCallerIdentity`.

### 2. Resource receipts (`resources.json` schema `flh066_resources_v2`)

- **Before `CreateStack`:** the record saves `status: CREATE_REQUESTING`, the
  name, the `ClientRequestToken` and the tags.
- **Right after its answer**, before any wait: `id` (the full StackId, checked
  to name this stack, account and region) and `id_source`.
- **Observations:** `status`, `observed_by` and `observed_utc`. Only
  `describe_stacks_by_id` can establish `DELETE_COMPLETE`.
- **DeleteStack:** each attempt is a `delete_attempts` entry (token, time,
  status it was sent from, outcome). Every request uses the StackId.
- **Bucket probe:** `bucket_probe` holds the `GetBucketLocation` +
  `ExpectedBucketOwner` result; `NoSuchBucket` means absent.
- **Old records:** no `schema`, no `id`; `CREATING` / `CREATE_COMPLETE` /
  `DELETED`. They remain readable and usable:
  - live ones adopt their StackId by name, only with matching `flh:task` and
    `flh:state-id` tags;
  - `DELETED` ones need an operator-supplied StackId.
- **Permissions:** no new ones. `DescribeStacks`/`DeleteStack` on
  `stack/flh063-*/*` and `s3:GetBucketLocation` on `flh063-*` were already
  granted, and `ListStacks` is never used.

### 3. Honest cleanup states (`cleanup_state`)

| State | Requires | Exit |
| --- | --- | --- |
| `deletion_confirmed` | `DELETE_COMPLETE` read by StackId and `NoSuchBucket` | 0 |
| `not_created` / `none_recorded` | `CreateStack` answered 4xx / nothing recorded | 0 |
| `resources_present` | Observed present: unknown keys, changed objects, refused `DeleteStack`, or the bucket still there | 1 |
| `deletion_requested` | `DeleteStack` sent (answer lost or completion unobserved) | 4 |
| `verification_unavailable` | AccessDenied or network failure on a read, or no StackId | 4 |

- **Never treated as deletion:** a missing stack by name, AccessDenied or a
  network failure.
- **Unchanged protections:** unknown objects, ETag/run-metadata ownership
  checks and the bucket tag check.
- **Repeated cleanup** after `deletion_confirmed` sends nothing.

### 4. Interrupted operations

- **`CreateStack`:**
  - an AWS 4xx answer (other than AlreadyExists-type) means `CREATE_REJECTED`
    (redeploy allowed in the same state; the ledger is kept and the old record
    moved to `history`);
  - anything else means `CREATE_UNKNOWN` (exit 4). It is not resent, and
    `deploy` refuses.
- **A crash between the answer and the save** leaves `CREATE_REQUESTING`
  without an id. It is settled the same way.
- **`recover` (read-only):**
  1. checks an operator `--stack-id`;
  2. otherwise adopts by name, with the tag check;
  3. reads by StackId;
  4. probes the bucket when nothing is found or the stack is deleted.

  If nothing is found, the state stays unverified and `operator_steps` names
  the console and CloudTrail lookup.
- **DeleteStack:** a lost answer means `deletion_requested`. The next cleanup
  reads the stack by StackId first, and sends another request (new token) only
  if the stack is still there and not deleting.
- **Lost S3 DELETE:** the object stays recorded. The next run re-reads it with
  HEAD and either records `already absent` or deletes it under the same
  `If-Match`.
- **Exit code 4** ("outcome not verified") is new.

### 5. Titan diagnostics and targeted continuation

- **`diagnostics.classify`:** a category comes only from explicit evidence (a
  documented code, class or message phrase):
  - `account_verification_pending`, `iam_denied`, `model_access_denied`;
  - `expired_credentials`, `throttling`, `service_unavailable`, `validation`;
  - `transport` (with `may_have_been_processed`), `response_invalid`;
  - `unknown` otherwise; a bare AccessDenied stays `unknown`.
- **Sanitized messages:** the AWS error message only, with 12-digit ids and
  access-key ids masked, bounded at 300 characters.
- **Ledger:** each failed InvokeModel record gains `error_category`,
  `error_code`, `request_id` and `may_have_been_processed`. It stays charged.
- **Smoke report:** schema `flh066_titan_smoke_v2` adds `ledger_history_before`
  and `skipped_already_ok`.
- **`titan-smoke --only-missing`** skips inputs with an `ok` record at the same
  dimensions and backend. It never resets counters, raises caps, retries or
  needs S3. The whole-plan budget check is unchanged.

## Files (exact edit set)

| File | Change |
| --- | --- |
| `tools/cloud/aws/requirements.txt` | `awscrt==0.36.0` |
| `tools/cloud/aws/flh_aws/diagnostics.py` | New: categories, sanitizing, definite-rejection test |
| `tools/cloud/aws/flh_aws/awsclients.py` | Credential resolution before clients; `sdk_versions` |
| `tools/cloud/aws/flh_aws/s3store.py` | Receipts, `describe_stack`, `recover`, `probe_bucket`, `stack_report`, `operator_steps`, new `cleanup` |
| `tools/cloud/aws/flh_aws/titan.py` | Categorized failures, `invocation_history`, `only_missing` |
| `tools/cloud/aws/flh_aws/cli.py` | `recover`, `auth-check`, `--only-missing`, exit 4, sanitized errors, masked output |
| `tools/cloud/aws/flh_aws/fakes.py` | StackIds, name vs id visibility, fault injection |
| `tools/cloud/aws/tests/test_recovery.py` | New deterministic recovery/diagnostics tests |
| `tools/cloud/aws/tests/test_flh_aws.py` | Two assertions for the new cleanup result |
| `tools/cloud/aws/tests/test_boto_shapes.py` | StackId shapes, `recover` shapes, real-botocore credential tests |
| `tools/cloud/aws/README.md`, `docs/CLOUD_EXPERIMENT.md` | Documentation and the next-run guide |
| This plan, the validation report | New |
