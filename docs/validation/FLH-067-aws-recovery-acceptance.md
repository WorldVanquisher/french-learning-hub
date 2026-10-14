# FLH-067 — Independent integrated AWS recovery acceptance

**Overall FAIL: three reproducible contract defects.** Fake-client evidence only;
**real AWS service behavior, IAM evaluation and billing NOT RUN**. No Windows,
GPU, Docker, credential files, `.env`, daily databases or `~/flh064` were used.

2026-10-14. Owner: NAS Codex. AGENTS.md read. Actual `pwd`:
`/home/worldvanquisher/workspace/flh-nas-codex`.
Supplied branch: `test/flh-067-aws-recovery-acceptance`, not Git-inspected.
Inspected the integrated FLH-066 contract and relevant implementation only.
Changed only this report and `scripts/validation/flh067/{accept.py,README.md}`.
No production, IAM, dependency-pin or shared-documentation edits; no additional agents.

## Contract adjudication

| Area | Verdict | Independent evidence / limit |
| --- | --- | --- |
| Authentication isolation | **BLOCKED for real SDK credential-chain acceptance; PASS for dependency-free boundaries** | Five independent control checks refuse before client construction/resource creation; seven real SDK/Stubber tests cannot execute because boto3, botocore and awscrt are absent |
| Deployment receipts / response loss | **FAIL ownership boundary; normal recovery PASS** | Full ARN retained; success, lost answer, crash before persistence, unreachable creation and invalid create response tested across processes. Replacement deploy refused after unresolved creation. Persisted foreign StackId bypasses validation in cleanup (F1) |
| Cleanup truthfulness | **FAIL** | Ordinary requested/confirmed/unknown/present outcomes pass. Foreign persisted identifiers/tags permit DeleteStack (F1); malformed saved confirmation reports deleted while bucket remains (F2) |
| Ledger / targeted Titan continuation | **PASS accounting; FAIL evidence binding** | Every attempted/failed/unfinished call charged; unchanged continuation skips completed inputs, never redeploys S3 or resets counters. Changed text/region/model reuses incompatible success (F3) |
| State durability / compatibility | **PASS for tested process interruption/restart; FAIL malformed-state integrity** | Fresh-process create/invoke interruption retained intent/budget; old DELETED copy recovers conservatively, original preserved. Malformed receipt trust fails (F2). No power-loss durability claim |

Final adjudication: **56 observations, 50 PASS, six failed expectations** mapping
to the three defects below. **127 fresh worker processes** retain exact child
argv, CLI exits, stdout/stderr, state, evidence and fake service counters.
Harness exit alone was not used as acceptance.

## Reproducible defects

| ID / severity / location | Expected → actual | Impact and suggested owner verification |
| --- | --- | --- |
| **F1 High — persisted identifier ownership**. `tools/cloud/aws/flh_aws/s3store.py:547–571`, DeleteStack near line 633 | A stored StackId must be validated against receipt name/account/region and the observed live stack's ownership before writing. Replace state A's recorded ID with state B's full ID in the same synthetic account: **expected zero deletes/B CREATE_COMPLETE; actual one DeleteStack/B DELETE_COMPLETE**. Also, with the originally recorded ID but observed foreign task/state tags: expected refusal; actual one DeleteStack and DELETE_COMPLETE | **Extra write/deletion** to unrelated fake resource. The stored-ID path neither calls `check_stack_id` nor checks the observed name/tags; name-based recovery correctly refuses foreign tags. Validate stored IDs and observed ownership before writes, then rerun both variants. This proves tool-side request behavior, not AWS IAM authorization |
| **F2 High — malformed receipt accepted as cleanup proof**. `s3store.py:83–105,551–553` | After fake deploy, set recorded ID to `NOT-A-STACK-ARN`, status DELETE_COMPLETE, observed_by `describe_stacks_by_id`, bucket_probe absent. **Expected refuse or unverified; actual exit 0/deletion_confirmed, no request, while the actual fake stack/bucket remain present** | **Misleading cleanup claim/evidence reuse**. `load_resources`/`stack_report` accept this internally inconsistent receipt and cleanup's cached-confirmation return precedes validation. Validate receipt schema/types/identifier invariants before reporting or returning cached success. Valid repeated cleanup may still send nothing; a read is not inherently required to reject malformed state |
| **F3 High — continuation success is not bound to input/model identity**. `tools/cloud/aws/flh_aws/titan.py:129–136,174–176` | First successful smoke of `same-id`, then keep that label and (a) change its text, (b) change region ca-central-1→us-east-1, or (c) change persisted prior call's model to an unrelated model. **Expected reject incompatible continuation or invoke its missing input; actual exit 0, planned_calls 0, skipped_already_ok [same-id], zero new invocations** | **Incompatible success evidence reuse**, not counter undercharging: the old attempt remains charged, but no new input is tested. Region variant even emits a new region/model identity while skipping old-region evidence. Bind eligibility to exact input/request hash and full model/region/dimensions/normalization/convention/backend identity; old unbound evidence must not silently qualify |

Shortest independent reproducers (new task-local output; **each exits 1** on this baseline):

```sh
python3 -B scripts/validation/flh067/accept.py --case foreign-id --out /tmp/flh067-repro-id
python3 -B scripts/validation/flh067/accept.py --case foreign-tag --out /tmp/flh067-repro-tags
python3 -B scripts/validation/flh067/accept.py --case stale-receipt --out /tmp/flh067-repro-receipt
python3 -B scripts/validation/flh067/accept.py --case changed-text --out /tmp/flh067-repro-text
python3 -B scripts/validation/flh067/accept.py --case changed-region --out /tmp/flh067-repro-region
python3 -B scripts/validation/flh067/accept.py --case changed-model --out /tmp/flh067-repro-model
```

These commands invoke the actual CLI in fresh processes, without implementation
patches. Fault injection uses only filesystem fakes, synthetic receipts and
worker-local mocks/crash points. The foreign-ID reproducer copies two synthetic
stack/bucket records into one fake account/world, then observes the unrelated
stack's deletion there. No real resources or original evidence are touched.

## Passing boundaries and durability evidence

- **Auth controls:** actual `aws_clients` with injected synthetic SDK/session
  failures for missing login dependency, missing credentials, expired refresh
  and absent profile. Each returns CLI2, zero client constructions, no
  resources.json, zero ledger calls; diagnostic categories agree and synthetic
  credential/provider-output markers never appear. Missing explicit profile
  also refuses before SDK import. These mocks exercise control flow, not actual
  LoginProvider/cache parsing. All independent worker network operations are
  prohibited by an audit hook; config/credentials/cache paths are synthetic.
- **Receipts:** successful deploy's full StackId equals the fake service's ARN,
  naming its actual stack/account/region; stdout masks account. Lost answer
  leaves CREATE_UNKNOWN, abrupt process exit86 before StackId save leaves
  CREATE_REQUESTING, foreign creation-answer ARN leaves CREATE_UNKNOWN.
  Subsequent deploy exits2, CreateStack count stays1, fresh `recover` adopts the
  correctly tagged stack and cleanup confirms by ID plus missing bucket.
  Unreachable creation finds no stack by name and NoSuchBucket but stays
  verification_unavailable/CLI4, with no DeleteStack. Original creation receipts
  and recovery results are retained separately.
- **Cleanup:** DescribeStacks AccessDenied → verification_unavailable/4;
  DeleteStack AccessDenied → resources_present/1;
  lost delete answer and forced bounded wait expiry → deletion_requested/4;
  delayed deletion → deletion_confirmed/0. Fresh subsequent cleanup settles
  each; repeated confirmed cleanup leaves all fake counters unchanged.
  Missing bucket alone does not establish DELETE_COMPLETE in the ordinary
  missing-by-name or old DELETED paths. Unknown synthetic key remains intact
  with exit1 and zero stack deletes. Foreign operator account ARN is refused;
  syntactically invalid receipt JSON exits1 without requests/success claim.
- **Old state:** a fresh synthetic copy omits schema/StackId and uses DELETED.
  Cleanup exits4 even with bucket absence. Correct operator full ARN recovers
  DELETE_COMPLETE by ID and deletion_confirmed/0. The separate original legacy
  evidence copy stays byte-identical. No historical real state was read.
- **Titan:** partial success (two OK, third throttled), immediate account-
  verification denial, and ambiguous ReadTimeout each stop with CLI1 and a
  charged failed invocation. Ambiguous transport records
  `may_have_been_processed: true`; account verification records its explicit
  category and false processing indicator. Fresh only-missing continuations
  plan four/six/six calls, ending at **seven charged attempts** per scenario.
  Earlier records stay unchanged; S3 CreateStack count remains0. Each completed
  continuation repeat plans0 and sends0 calls. Dimensions256→512 sends a new
  invocation, reaching used2; unchanged success does not qualify at new dimensions.
- **Abrupt invocation interruption:** worker exits87 after fake InvokeModel
  returns but before ledger outcome persistence; ledger used1/outcome attempted.
  Fresh continuation invokes once, used2, and the unfinished original attempt
  remains charged. Ten ambiguous failed invocations consume cap10; the eleventh
  is refused CLI2 with zero extra calls and no counter reset.

Independent offline ledger reconstruction across **nine Titan states** verifies
`used == sum(reserved amounts) == fake InvokeModel attempts`, including failures
and interruption; characters/bytes also reconcile. Every invocation cap remains
10. Persisted CLI reports, ledger usage and fake counters agree except for the
explicit evidence-binding failures above. No incorrect invocation accounting
was reproduced.

## Existing suites: one run, targeted infrastructure recheck

System interpreter has **no boto3, botocore or awscrt**. No alternative environment
was installed or downloaded. Existing full-suite execution:

```sh
AWS_CONFIG_FILE=/tmp/flh067-acceptance/auth-empty/config \
AWS_SHARED_CREDENTIALS_FILE=/tmp/flh067-acceptance/auth-empty/credentials \
AWS_LOGIN_CACHE_DIRECTORY=/tmp/flh067-acceptance/cache \
AWS_EC2_METADATA_DISABLED=true \
python3 -B -m unittest discover -s tools/cloud/aws/tests -p 'test_*.py' -v
```

**68 discovered: 57 pass, four errors, seven skips; exit1.** The four AdapterTests
failed in setUp because sandbox socket creation was prohibited, before their
assertions. Only those four were rechecked with loopback socket permission:

```sh
AWS_CONFIG_FILE=/tmp/flh067-acceptance/auth-empty/config \
AWS_SHARED_CREDENTIALS_FILE=/tmp/flh067-acceptance/auth-empty/credentials \
AWS_LOGIN_CACHE_DIRECTORY=/tmp/flh067-acceptance/cache \
AWS_EC2_METADATA_DISABLED=true PYTHONPATH=tools/cloud/aws/tests:tools/cloud/aws \
python3 -B -m unittest test_flh_aws.AdapterTests -v
```

**Four pass, exit0** (an implicit HTTPError cleanup ResourceWarning was printed).
Combined existing coverage: **61 distinct passed tests / seven still skipped**:
36 test_flh_aws, 25 test_recovery; no full-suite rerun. Loopback adapter evidence
uses local fake vectors, not AWS or Titan service behavior.

Precisely blocked checks in `test_boto_shapes.py`:

- AuthPrerequisiteTests: requirements/CRT pin agreement; unknown actual SDK
  profile; pinned CRT with absent login session; actual LoginProvider without CRT.
- BotoShapeTests: backup workflow request/response shapes; recover name→StackId
  request shapes; Titan Bedrock request/response shapes.

The skip reason is `boto3 not installed`. These seven are **not passes**;
synthetic exception mocks do not substitute for SDK/Stubber validation.

## Independent commands, retained evidence and cleanup

```sh
python3 -B scripts/validation/flh067/accept.py --out /tmp/flh067-independent
python3 -B scripts/validation/flh067/accept.py --out /tmp/flh067-foreign-tags --case foreign-tag
python3 -B scripts/validation/flh067/accept.py --out /tmp/flh067-invalid-json --case invalid-json
python3 -B scripts/validation/flh067/accept.py --out /tmp/flh067-stale-receipt-final --case stale-receipt
```

Exits **1/1/0/1** respectively; exact raw outputs are retained under
`/tmp/flh067-acceptance/`. Initial 55-observation evidence is preserved. Its two
malformed-receipt observations were replaced in final adjudication by the
narrowed refusal check: an initial separate “must read” expectation was too
strict, because malformed state can be rejected locally. Only that scenario
was rerun; no defect was fixed or concealed. Added foreign-tag and invalid-JSON
checks run separately. Final adjudication is 56 observations/50 pass/six failed
expectations; final harness selectors reproduce all cases without SDK dependencies.

Evidence roots above retain receipts before interruption, fresh-process commands,
state/ledger/evidence JSON, fault specifications, fake-world records and source
hashes. `/tmp/flh067-acceptance/adjudication.json` records expected versus actual,
`ledger-reconstruction.json` independently reconciles accounting, and
`all-artifact-sha256.json` covers **476 artifacts**. All recorded hashes verified;
**23 AWS tool/source/template/IAM-example/pin files** retain their inspected bytes.
IAM files were hashed for preservation, not evaluated. Helper parses under
Python3.11 grammar; owned files have clean whitespace/newlines. README.zh-CN.md
exists; shared setup documentation was not changed.

| Acceptance artifact | SHA-256 |
| --- | --- |
| adjudication.json | `17165732cf55ba50054ddad8fc307efab53588f817d062f2b946c021ea24171e` |
| ledger-reconstruction.json | `90366a61c4ddead3289bf0702c39d6530743f1a5008ef779c5c538ffa05b2dc4` |
| all-artifact-sha256.json | `2a2ca3ca0cfbed55305ffbe96481a0438843a246cdc2a3fc0b2a9a6d81a8a3df` |

Cleanup status: **zero real resources created, zero real cleanup calls**. All
worker processes and targeted fake adapter listeners exited. Seven synthetic
bucket directories remain deliberately retained across evidence copies for
unknown-object, foreign-ownership, malformed-receipt and invalid-JSON scenarios;
these are local files, not AWS resources. `cleanup-status.json` names them.
No claim that every deliberately failing fake scenario was cleaned up.

Owner handoff: fix F1–F3 and rerun their isolated selectors; execute the seven
blocked SDK checks only in an existing approved dependency environment. Real
AWS service behavior, IAM evaluation and billing remain NOT RUN. Editing stops
at delivery; the human owns integration and all Git/GitHub operations.
