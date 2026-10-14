# FLH-066 validation: AWS experiment recovery and reproducibility

Date: 2026-10-14. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64). Contract:
[plan](../plans/FLH-066-aws-experiment-recovery.md). Operator guide:
[CLOUD_EXPERIMENT.md](../CLOUD_EXPERIMENT.md#next-real-run-flh-066).

**Not used:** Git/GitHub commands, subagents, Windows, the NAS, a GPU, Docker
or live AWS.

**Not read or printed:** credentials, tokens, private keys or `.env`. The
credential tests use a synthetic config and an empty login cache in a
temporary directory. Account ids in FLH-064 files were masked when displayed.

## Real AWS verification: NOT RUN

No AWS request was made in this task: no paid call, no new resource and no
IAM change. That leaves these unverified against AWS:
- `auth-check` on the real `flh` profile;
- the targeted Titan rerun;
- `recover` on FLH-064's stack;
- a fresh deploy with a StackId receipt.

The next-run guide lists them as steps 3–6. The fakes and Stubber tests prove
plumbing and request shapes. They prove nothing about IAM evaluation,
CloudFormation's retention of deleted stacks, Titan's behaviour or billing.
This report claims no AWS charge figure and no retrieval quality.

## FLH-064 evidence (read-only)

`~/flh064` was only read. A tight check found **0 files changed** there since
this task began.

**Findings:**
- **`raw/preflight.out`:** `MissingDependencyException: Missing Dependency:
  Using the login credential provider requires an additional dependency. You
  will need to pip install "botocore[crt]" before proceeding.`
- **`raw/venv-freeze.txt`:** the venv that worked had `awscrt==0.36.0` in
  addition to the pinned requirements.
- **`evidence/titan-smoke-*.json`:** `AccessDeniedException`, "Your account is
  currently being verified…", truncated at 300 characters with no category.
  The ledger has 35 calls, one failed: that InvokeModel, still charged.
- **`resources.json`:** stack `{"name": "flh063-74ca91fbb3d3", "status":
  "DELETED"}`, with no StackId.
- **`raw/verify-stack.out`:** by name, the stack "does not exist".
- **`raw/verify-stack-deleted.out`:** `ListStacks` AccessDenied.

**Compatibility run.** On a scratchpad **copy** of `~/flh064/state-aws`, the
new `status`, which needs no network:
- exit 0, with no unmasked 12-digit id in its output;
- the stack is `verification_unavailable` ("no StackId was recorded…"),
  with operator steps;
- 35 calls, 1 failed, 0 unfinished; **9 Bedrock invocations remaining**.

The copy was byte-identical to the original afterwards (`diff -r`).
`invocation_history` on the copy reports `failed_by_category:
{"unrecorded": 1}`. An `--only-missing` smoke would plan 6 calls, 209
characters and 714 bytes, which fits the remaining budget.

## Dependency diagnosis (offline, real botocore)

- **Script:** `scratchpad/flh066/repro.py` calls
  `boto3.Session(profile_name=...).get_credentials()`.
- **Isolation:** `env -i`, a synthetic `AWS_CONFIG_FILE` with `login_session =
  arn:aws:iam::111122223333:user/synthetic`, a missing shared-credentials file
  and an empty `AWS_LOGIN_CACHE_DIRECTORY`.

| Venv (scratchpad) | Built from | Result |
| --- | --- | --- |
| `venv-before` | FLH-063 `requirements.txt` | `MissingDependencyException \| … pip install "botocore[crt]"`: FLH-064's error, reproduced |
| `venv-after` | FLH-066 `requirements.txt` (adds `awscrt==0.36.0`) | `LoginTokenLoadError \| … Please reauthenticate with 'aws login'`: the dependency is satisfied, and the empty cache is reported |

- **Why it fails:** botocore 1.43.104's `LoginProvider.load()` raises
  `MissingDependencyException` when `awscrt.crypto.EC` cannot be imported.
- **Which version:** its metadata declares `Requires-Dist: awscrt (==0.36.0) ;
  extra == 'crt'`.
- **Release date:** PyPI's JSON API shows 0.36.0 uploaded on
  2026-07-16T19:35:07Z, with macOS, Linux and Windows wheels. It meets the
  two-week rule.
- **Install:** `venv-after` installed cleanly (`pip check`: no broken
  requirements). Freeze: `awscrt==0.36.0 boto3==1.43.104 botocore==1.43.104
  jmespath==1.1.0 python-dateutil==2.9.0.post0 s3transfer==0.19.2 six==1.17.0
  urllib3==2.8.0`.

## Automated tests

```sh
python3 -B -m unittest discover -s tools/cloud/aws/tests -p 'test_*.py'                  # system 3.13.5, no boto3
$VENV_AFTER/bin/python -B -m unittest discover -s tools/cloud/aws/tests -p 'test_*.py'   # pinned requirements
$VENV_BEFORE/bin/python -B -m unittest discover -s tools/cloud/aws/tests -p 'test_*.py'  # FLH-063 requirements
```

| File | System python3 | `venv-after` |
| --- | --- | --- |
| `test_flh_aws.py` (existing, 2 assertions updated) | 36 OK | 36 OK |
| `test_recovery.py` (new) | 25 OK | 25 OK |
| `test_boto_shapes.py` | 7 skipped (no boto3) | 7 OK |
| **Total** | **68, OK (7 skipped)** | **68, OK** |

**Other runs:**
- **`venv-before`:** 67 pass and **1 fails by design**:
  `test_with_the_pinned_awscrt_…` reports "awscrt is not installed: this
  environment was not built from tools/cloud/aws/requirements.txt…". This
  catches a live venv like FLH-064's first one.
- **Before any edit,** the baseline was 38 tests, OK (2 skipped).
- **pyflakes 3.2.0** (installed into the scratchpad only) on `flh_aws` and
  `tests`: no findings.
- **`ast.parse(..., feature_version=(3, 8))`** on every module and test: OK.
- No `__pycache__` was left in the repository.

## What the new tests cover

**Old-state compatibility:**
- **An FLH-064-shaped `DELETED` record without a StackId:**
  - `cleanup` exits 4 with `verification_unavailable`, the bucket probe
    `absent`, and operator steps naming `--stack-id`;
  - `status` agrees;
  - `recover --stack-id` with another account's ARN is refused (exit 1), and
    nothing is recorded;
  - with the right ARN it reads `DELETE_COMPLETE` by StackId, so the state
    becomes `deletion_confirmed` (exit 0, `id_source: operator`).
- **A live legacy record:**
  - `upload` still works;
  - `cleanup` adopts the StackId by name and reaches `deletion_confirmed`.
- **Foreign tags:** a stack whose tags name another state is not adopted
  (exit 1); there is no StackId and no `DeleteStack`.

**Receipts:**
- **What `deploy` saves:**
  - the full StackId, from the `CreateStack` answer;
  - the token and tags;
  - schema `flh066_resources_v2`;
  - `observed_by: describe_stacks_by_id`;
  - printed output masks the account.
- **Name vs StackId:** once deleted, a stack is invisible by name and still
  `DELETE_COMPLETE` by StackId.
- **Failed creation (`OnFailure=DELETE`):** confirmed by StackId without any
  `DeleteStack`.

**Response loss and interrupted persistence:**
- **`CreateStack` answer lost (the stack is created):**
  - deploy exits 4 with `CREATE_UNKNOWN`, "not resent";
  - a second `deploy` is refused (exit 2);
  - `CreateStack` was called exactly once, and one stack exists;
  - `recover` adopts it, and `verify-bucket` and `cleanup` succeed.
- **`CreateStack` unreachable:** exit 4. `recover` finds nothing by name, and
  the bucket probe says absent. The state stays `verification_unavailable`
  (exit 4), and cleanup sends no `DeleteStack`.
- **`CreateStack` AccessDenied:**
  - exit 1, `iam_denied`, with the account masked in stderr;
  - `CREATE_REJECTED`, so cleanup reports `not_created` (exit 0);
  - redeploy works in the same state, and the old record goes to `history`.
- **Crash after `CreateStack` returned, before the StackId save:**
  - `CREATE_REQUESTING`, with no id;
  - `status` reports `verification_unavailable`;
  - `recover` adopts the stack; one `CreateStack` call.
- **DescribeStacks denied while waiting after create:** exit 4, but the
  StackId was already saved; a later `recover` reads `CREATE_COMPLETE`.

**AccessDenied and repeated cleanup:**
- **DescribeStacks denied:** cleanup gives `verification_unavailable` (exit
  4). No `DeleteStack` is sent, and the status stays `CREATE_COMPLETE`.
- **`DeleteStack` answer lost (the stack is deleted):** `deletion_requested`
  (exit 4). The next cleanup reads `DELETE_COMPLETE` by StackId, giving
  `deletion_confirmed`; `DeleteStack` was called once.
- **`DeleteStack` unreachable:**
  - exit 4;
  - the next cleanup reads `CREATE_COMPLETE`, then sends attempt 2 with token
    `-delete-2`;
  - both attempts are recorded with their `from_status`.
- **`DeleteStack` AccessDenied:** `resources_present` (exit 1). The status is
  restored to `CREATE_COMPLETE`, and the attempt is recorded `rejected`.
- **S3 DELETE answer lost:**
  - `verification_unavailable` (exit 4), and both objects stay recorded;
  - the rerun records `already absent` then `deleted`, reaching
    `deletion_confirmed`;
  - the ledger shows the DELETE outcomes `failed`, `ok`.
- **Slow deletion:** `DELETE_IN_PROGRESS` is waited for by StackId.
- **Repeated cleanup after confirmation:** the fake call counters are
  unchanged.

**Titan:**
- **Account verification, then a targeted rerun:**
  - the exact FLH-064 message gives `account_verification_pending` in stderr,
    the report and the ledger record; 1 invocation is charged;
  - `--only-missing` makes 6 calls (7 of 10 used, 3 left) and reports
    `failed_by_category: {"account_verification_pending": 1}`;
  - a second `--only-missing` makes 0 calls and skips 6;
  - a plain rerun is refused before sending (exit 2);
  - the cap stays 10, and no stack was needed.
- **Partial failure:** throttling at input 3, then `--only-missing` plans 4
  and skips 2. That makes 7 InvokeModel calls in total.
- **Categories, each also charged as a failed invocation:**
  - `account_verification_pending`, `iam_denied`, `model_access_denied`;
  - a bare AccessDenied gives `unknown`;
  - `ExpiredTokenException` and `UnrecognizedClientException` give
    `expired_credentials`;
  - `throttling`;
  - an unrecognized 400 gives `unknown`;
  - a 500 gives `service_unavailable`;
  - a read timeout gives `transport` with `may_have_been_processed: true`, an
    unreachable endpoint `transport` with `false`.
  - No unmasked account id appears in any report or stderr.
- **Diagnostics units:**
  - credential classes by name;
  - sanitizing (account and key ids, length);
  - definite-rejection rules: 4xx yes; `AlreadyExists`, 5xx and transport
    errors no.

**Credentials:**
- **With real botocore** (`test_boto_shapes.AuthPrerequisiteTests`; synthetic
  config, no network):
  - with `EC` patched to `None`, `aws_clients` raises `Refused` naming
    `missing_dependency` / `MissingDependencyException` and
    `requirements.txt`, and stating "No AWS resource request was sent";
  - with awscrt, an absent login session gives `expired_credentials` /
    `LoginTokenLoadError` with `aws login --profile flh-synthetic`;
  - an unknown profile gives `profile_not_found`.
- **Pin check:** `requirements.txt`'s `awscrt` and `botocore` pins equal the
  installed botocore's `crt` extra and version.
- **Without `--profile`:** a live state's `deploy` and `auth-check` are
  refused with no ledger entry and no `resources.json`.
- **Shape tests:** the Stubber deploy, upload, restore and cleanup now use the
  StackId for DescribeStacks and DeleteStack, and expect `NoSuchBucket` from
  `GetBucketLocation`. `recover` is checked by name and then by StackId.

## Limitations

- **Not observed against AWS:**
  - how long CloudFormation keeps deleted stacks readable by StackId (90 days
    is from AWS documentation, as recalled, not checked this session);
  - whether DescribeStacks on a deleted stack returns its tags. `recover`
    does not depend on it, but the tag check for adoption by name needs a
    live stack.
- **Probe permission:** `GetBucketLocation`'s `NoSuchBucket` is taken as
  absence for the expected owner. An AccessDenied gives `unknown`, never
  absent.
- **`aws login` refresh:** the refresh path (`signin:CreateOAuth2Token`) was
  exercised only up to the empty cache. A real expired session was not
  exercised.
- **Ledger copy:** continuing FLH-064's ledger in a copy (guide step 2) relies
  on the operator not using the original again. The optional `chmod -R a-w`
  enforces that.
- **Unchanged:** CloudFormation control-plane calls are still not in the
  ledger, as in FLH-063 (not billed per request).
- **Not repaired:** a smoke failure from before FLH-066 stays `unrecorded` in
  `failed_by_category`. The original evidence file keeps its message.
