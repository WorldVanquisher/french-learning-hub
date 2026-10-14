# FLH-069 — Integrated AWS integrity regression

**PASS for the supplied local fake/SDK/Stubber contract.**
Unchanged FLH-067 full harness: **56/56 observations PASS**, no failed expectations.
AWS suites in a temporary environment built from the existing exact pins:
**82 tests PASS, zero failures/errors/skips**. All seven previously blocked
SDK/Stubber checks executed. Real AWS service behavior, IAM evaluation and billing
remain **NOT RUN**; no live-service acceptance is implied.

Owner: NAS Codex. 2026-10-14. AGENTS.md read. Actual `pwd`:
`/home/worldvanquisher/workspace/flh-nas-codex` (Linux).
Supplied branch: `test/flh-069-aws-integrity-regression`, not Git-inspected.
Only this report was edited. No production, harness, pins, IAM or shared-doc edits,
Git/GitHub commands, agents, Windows, GPU, Docker or paid calls. No real credential
files, `.env`, daily data or historical secret directories were read.

## Baseline and six original defect cases

Before testing, confirmed actual FLH-068 code and read its implemented contract:
`load_resources` calls `receipt_problems`; stored StackIds are validated against
receipt name/account/region; deletion confirmation must match its receipt/probe.
Cleanup calls `ownership_problems` before destructive work. Titan invocation
records carry exact `request_binding` fields and continuation compares every
binding field plus label/backend. The baseline matched; no old-tree test was
presented as FLH-068 acceptance.

| Original independent case | Actual integrated outcome | Verdict |
| --- | --- | --- |
| foreign-id | Zero DeleteStack, DeleteObject or HeadObject; unrelated fake stack remains CREATE_COMPLETE | PASS |
| foreign-tag | Zero destructive/object calls; observed foreign-tag stack remains CREATE_COMPLETE | PASS |
| stale-receipt | Malformed receipt rejected; no deletion_confirmed claim, real fake bucket retained | PASS |
| changed-text | New call planned/executed, skipped list empty, old success not reused | PASS |
| changed-region | New regional request planned/executed, skipped list empty | PASS |
| changed-model | Incompatible persisted model record not reused; new current-model call executed | PASS |

For each changed identity case, used invocations increase **1→2** and the report
records `different_text_model_region_dimensions_or_convention`. Independently
recomputed the new ledger's exact text/request-body SHA-256 values and checked
model and region. These checks supplement the harness's “must not reuse” assertions;
they do not rely on harness exit alone.

## Focused follow-up evidence

- **Ownership:** independently inspected retained counters for both foreign
  stored-ID and observed-tag cases: DeleteStack/DeleteObject/HeadObject all zero.
  The integrity suite additionally seeds uploaded objects before foreign/missing
  observed tags and verifies zero object HEAD/DELETE, retained objects, and
  successful cleanup after ownership is restored.
- **Receipt truth/legacy compatibility:** malformed JSON/inconsistent confirmation
  refuses; valid no-schema/no-ID live receipts adopt only tagged stacks.
  Old DELETED receipts with no ID stay unverified despite missing bucket; correct
  operator ID settles them. Harness original legacy copy remains unchanged.
  The integrity suite covers older bare DELETE_COMPLETE receipts: no cached
  success until re-observation/probe creates a valid confirmation.
- **Continuation:** unchanged completed continuations plan/send zero calls.
  Text/region/model/dimensions changes do not reuse incompatible successes;
  integrity tests also cover convention, normalization and request-hash changes.
  No S3 redeployment or counter reset occurs.
- **Charging:** offline reconstruction of nine retained Titan ledgers verifies
  used invocations = reserved amounts = fake API attempts; characters/bytes
  reconcile and invocation cap stays10. Failed attempts remain charged, an
  interrupted attempt remains unfinished/charged, and exhaustion refuses the
  next call. `test_legacy_unbound_success_does_not_qualify_and_stays_charged`
  verifies a pre-FLH-068 success needs a new call, used2/cap10; the old attempt
  is retained. Failed-bound-attempt continuation likewise ends at used2.
- **Repeated cleanup:** valid confirmation repeats send no requests; fresh-process
  response-loss/crash recovery remains conservative. No new concrete uncertainty
  justified an additional scratch reproducer or general audit.

## Pinned SDK environment and exact commands

Temporary venv: `/tmp/flh069-acceptance/venv`, system Python3.14.7.
Installed exact unchanged requirements: boto3/botocore1.43.104, s3transfer0.19.2,
jmespath1.1.0, python-dateutil2.9.0.post0, six1.17.0, urllib3 2.8.0,
awscrt0.36.0. Installed metadata matches all eight pins; `pip check` exits0,
“No broken requirements found.” No global installation or pin change.

Commands executed from actual pwd:

```sh
python3 -B scripts/validation/flh067/accept.py --out /tmp/flh067-flh069-full
python3 -m venv /tmp/flh069-acceptance/venv
/tmp/flh069-acceptance/venv/bin/python -m pip install --disable-pip-version-check --retries 0 --timeout 15 --only-binary :all: -r tools/cloud/aws/requirements.txt
/tmp/flh069-acceptance/venv/bin/python -m pip list --format=json
/tmp/flh069-acceptance/venv/bin/python -m pip check
env -i PATH=/usr/bin:/bin \
  AWS_CONFIG_FILE=/tmp/flh069-acceptance/auth-empty/config \
  AWS_SHARED_CREDENTIALS_FILE=/tmp/flh069-acceptance/auth-empty/credentials \
  AWS_LOGIN_CACHE_DIRECTORY=/tmp/flh069-acceptance/auth-empty/cache \
  AWS_EC2_METADATA_DISABLED=true PYTHONNOUSERSITE=1 \
  /tmp/flh069-acceptance/venv/bin/python -B -m unittest discover -s tools/cloud/aws/tests -p 'test_*.py' -v
```

Every command exits0. Harness ran **once**, using **124 fresh worker processes**;
AWS suites ran **once**, with loopback socket permission for fake adapter tests.
Synthetic config/empty credentials/cache paths were created before execution.
No credentials or ambient AWS profile entered the isolated suite process.
Package installation fetched pinned dependencies from the configured package
index, not AWS. Pip reported its normal cache unavailable; fake adapter tests
printed an implicit HTTPError cleanup ResourceWarning, without a failure.

| Suite | Passed | Skipped |
| --- | ---: | ---: |
| test_flh_aws | 36 | 0 |
| test_recovery | 25 | 0 |
| test_integrity | 14 | 0 |
| test_boto_shapes | 7 | 0 |
| **Total** | **82** | **0** |

Previously blocked checks now passing: real botocore CRT-pin agreement,
unknown profile refusal, absent login session with pinned CRT, missing-CRT
LoginProvider refusal before clients; Stubber backup workflow, name→StackId
recovery and Titan request/response shapes. These use synthetic credential
configuration, placeholder signing values and Stubber, not AWS service calls
or IAM evaluation. The fake adapter's vectors are plumbing evidence only.

## Retained evidence, preservation and cleanup

- `/tmp/flh067-flh069-full/`: full unchanged harness results, child argv/exits,
  receipts, synthetic world/counters, reports, ledger and artifact hashes.
- `/tmp/flh069-acceptance/`: harness/suite/install logs, installed metadata,
  pip-check result, `source-before.json`, `independent-checks.json`,
  `evidence-sha256.json` and the isolated venv.
- Verified **446 evidence-file hashes** (venv files excluded) and **27 inspected
  source/harness/instruction hashes** against current bytes. Harness also matches
  the retained FLH-067 helper snapshot byte-for-byte. No source byte changed.

| Artifact | SHA-256 |
| --- | --- |
| unchanged scripts/validation/flh067/accept.py | `1af3e482c0eec6c3ff24911923adc217caae99e0f2fa6507d7b1bf34e8afaee2` |
| full harness results.json | `379e603c2e05920d8d1f211c844eafa857beeacec05778f9939ca25066e1c3e9` |
| independent-checks.json | `98ceeae890adc63fcd267e08631bf302764c1f140041fb16571eae393c3d4a49` |
| evidence-sha256.json | `584a353c974c4bbe8c14c7b3d7938d6d4b1db6d43219506c81b91811d2ac89dc` |

Cleanup: all worker/suite processes and owned fake listeners exited. **Zero real
AWS resources created or deleted.** Eight synthetic bucket directories remain
intentionally retained across refusal/corruption/unknown-object evidence copies;
`independent-checks.json` lists them. The temporary venv remains under `/tmp` for
reproduction; no global environment was altered. README.zh-CN.md exists; no
shared setup change was needed. Editing stops at delivery.

For the human owner only, not executed:

```sh
git add -- docs/validation/FLH-069-aws-integrity-regression.md
```

Suggested commit message:

```text
test: verify integrated AWS integrity fixes with pinned SDK
```
