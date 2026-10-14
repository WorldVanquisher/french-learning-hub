# FLH-070 validation: live Titan continuation (checkpoint)

Date: 2026-10-14. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64). Procedure:
[CLOUD_EXPERIMENT.md, "Next real run"](../CLOUD_EXPERIMENT.md#next-real-run-flh-066).

**Not used:** Git/GitHub, subagents, Windows, the NAS, a GPU or Docker. No
S3 deployment, new resource, IAM change, cap change, index build, adapter
evaluation or benchmark.

**Not read or printed:** credentials, tokens, private keys or `.env`.

**Status: BLOCKED at sign-in.** The `flh` profile's `aws login` session has
expired. No Titan call was made, and the ledger is unchanged.

## Local preparation (done)

**Environment**
- **Venv:** reused, not rebuilt. It is the isolated scratchpad venv built
  during FLH-068 from `tools/cloud/aws/requirements.txt`.
  - That file's SHA-256 is unchanged (`3e193efe…709b`).
  - Freeze: `awscrt==0.36.0 boto3==1.43.104 botocore==1.43.104
    jmespath==1.1.0 python-dateutil==2.9.0.post0 s3transfer==0.19.2
    six==1.17.0 urllib3==2.8.0`.
  - `pip check`: no broken requirements.
- **Offline suites in it,** with the AWS config, credentials and login cache
  pointed at empty scratchpad paths: **82 tests, OK, 0 skipped**. That
  includes the 7 SDK/Stubber and credential tests.

**Choosing one continuation state**
- **Search:** every `.flh063-state` under `~` and the session scratchpad.
  Three `aws`-backend copies of state `74ca91fbb3d3` existed:
  - the original, `~/flh064/state-aws`;
  - two read-only test copies I made in the scratchpad during FLH-066 and
    FLH-068, for offline `status` checks.
- **The scratchpad copies:** `diff -r` showed both identical to the original
  (35 calls, 1 invocation). Neither had ever been used for a live command. I
  deleted them, so no second live-capable copy exists.
- **No earlier continuation existed:** `~/flh066` was absent.
- **The authoritative continuation state is `~/flh066/state-aws`,** created
  with `cp -Rp` from the original and identical to it (`diff -r`).
- **`~/flh064`:** left unmodified, with no content or permission change. The
  guide's optional `chmod -R a-w` was not applied, to leave the evidence
  untouched. **Never run live commands against `~/flh064/state-aws`.**

**Local status** (`status`, no network; saved as `~/flh066/status-before.json`):

| Item | Value |
| --- | --- |
| Stack | `verification_unavailable` (legacy record, no StackId) |
| Ledger calls | 35 total, 1 failed (FLH-064's Titan account-verification denial), 0 unfinished |
| Bedrock used / remaining | invocations 1 / **9**; characters 44 / 7,956; request bytes 128 / 65,408 |

**Continuation plan** (`continuation_plan`, local only):
- **Already done:** none, and nothing was set aside as not reusable.
- **To send:** `en-weather-child`, `fr-imparfait-example`, `en-lived-still`,
  `fr-depuis-example`, `en-not-anymore`, `fr-ne-plus-example`.
- **Needed:** 6 invocations, 209 characters, 714 bytes. This **fits** the
  remaining budget.
- **History:** 1 attempted, 0 successful, `failed_by_category:
  {"unrecorded": 1}`.

## Live steps

| Step | Result |
| --- | --- |
| Caller identity (`auth-check --profile flh --region ca-central-1`) | **Refused, exit 2:** `expired_credentials: LoginRefreshRequired`, "No AWS resource request was sent". Tried once, not retried. The ledger is byte-identical to the original afterwards |
| Account verification evidence | **NOT CHECKED:** no console or email access from here. The human should confirm the account-verification banner or email before the smoke |
| `titan-preflight` | NOT RUN |
| `titan-smoke --only-missing` | NOT RUN |
| Stack settlement (`recover --stack-id`) | NOT RUN: the exact StackId of `flh063-74ca91fbb3d3` is not available locally |

## To unblock (human)

```sh
aws login --profile flh
```

Then continue from step 3 of the guide (`auth-check`), with
`STATE=$HOME/flh066/state-aws` and the same venv.

Billing is unverified; no charge figure is claimed.
