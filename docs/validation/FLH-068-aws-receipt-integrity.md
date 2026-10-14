# FLH-068 validation: AWS receipt integrity, persisted ownership and Titan continuation identity

Date: 2026-10-14. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64, system
Python 3.13.5). Contract: [plan](../plans/FLH-068-aws-receipt-integrity.md).
Acceptance oracle: the unchanged FLH-067 harness, run as
`scripts/validation/flh067/accept.py`.

**Not used:** Git/GitHub, additional agents, live AWS, credentials, paid
providers, Windows, the NAS, a GPU or Docker. No cloud resources were created.
The only network use was PyPI, to build the isolated SDK venv.

**Untouched**, with their SHA-256 after the work:
- `scripts/validation/flh067/accept.py` `1af3e482…afaee2`;
- `scripts/validation/flh067/README.md` `5040af67…a171a`;
- the FLH-067 report `c535a47d…c8fe3`;
- the IAM examples: deploy `0945063c…ddd`, runtime `03d6714e…57d`, Bedrock
  `12cc24d7…dbc`;
- `requirements.txt` `3e193efe…709b`;
- FLH-065 files, Go code, `AGENTS.md`;
- `~/flh064`, with 0 files changed since this work began.

Evidence is outside the repository, under `/tmp/flh067-flh068-*` (21
directories, the harness's required location) and `/tmp/flh068-*.txt`.

## Before the fix: the six FLH-067 selectors (unchanged harness)

```sh
python3 -B scripts/validation/flh067/accept.py --case <case> --out /tmp/flh067-flh068-before-<case>
```

| Selector | Exit | Expected → actual |
| --- | --- | --- |
| `foreign-id` | 1 | `{delete_calls: 0, foreign_status: CREATE_COMPLETE}` → `{1, DELETE_COMPLETE}` |
| `foreign-tag` | 1 | `{delete_calls: 0, stack_status: CREATE_COMPLETE}` → `{1, DELETE_COMPLETE}` |
| `stale-receipt` | 1 | `{claims_confirmed: False, bucket_present: True}` → `{True, True}` |
| `changed-text` | 1 | must not reuse success → reused (`planned 0`, skipped `[same-id]`) |
| `changed-region` | 1 | same → reused |
| `changed-model` | 1 | same → reused |

**Full harness before** (`--out /tmp/flh067-flh068-before-all`): exit 1, **56
observations, 50 pass, 6 fail**. These are exactly the six above, matching the
FLH-067 report. `results.json` SHA-256 `42b0462a…61cc83`.

## After the fix: the same selectors, unchanged

| Selector | Exit | Result | Actual CLI behaviour |
| --- | --- | --- | --- |
| `foreign-id` | 0 | PASS: 0 deletes, foreign stack `CREATE_COMPLETE` | cleanup exit 1: "resources.json is malformed or inconsistent (stack.id is not this state's StackId (name, account, region)); nothing was sent…" |
| `foreign-tag` | 0 | PASS: 0 deletes, `CREATE_COMPLETE` | cleanup exit 1, `ownership_refused`: "observed tags do not identify this task and state directory; nothing destructive was sent" |
| `stale-receipt` | 0 | PASS: no confirmation claimed, bucket present | cleanup exit 1, `ReceiptInvalid` (StackId not bound, malformed `bucket_probe`) |
| `changed-text` | 0 | PASS | exit 0: `planned_calls 1`, `skipped []`, `not_reused: different_text_model_region_dimensions_or_convention`; used 2 (the first attempt stays charged) |
| `changed-region` | 0 | PASS | same, for `us-east-1` |
| `changed-model` | 0 | PASS | same |

**Full harness after,** on the final tree (`--out
/tmp/flh067-flh068-final-all`): exit 0, **56 observations, 56 pass, 0 fail**.
`results.json` SHA-256 `379e603c…e1c3e9`. The harness hashed 24 tool files
before and after its run and found them unchanged.

**Unchanged by the fix,** within those 56:
- every **repeated valid cleanup** leaves all fake counters unchanged (5
  scenarios);
- every **unchanged completed continuation** plans 0 and sends 0 calls (3
  scenarios);
- changed dimensions still sends exactly one new call;
- ledger reconciliation, crash durability and the cap-exhaustion refusal
  still pass.

The six selectors were also rerun individually on the final tree: all exit 0.

## Existing and new suites

| File | System python3 (no SDK) | Isolated pinned venv |
| --- | --- | --- |
| `test_flh_aws.py` | 36 OK | 36 OK |
| `test_recovery.py` | 25 OK | 25 OK |
| `test_integrity.py` (new) | 14 OK | 14 OK |
| `test_boto_shapes.py` | 7 **skipped** (not passes) | **7 OK** |
| **Total** | 82: 75 pass, 7 skipped | **82: 82 pass, 0 skipped** |

**The seven SDK/Stubber tests:**
- **Environment:** a fresh scratchpad venv built from the unchanged
  `requirements.txt` (`pip check`: no broken requirements). Freeze:
  `awscrt==0.36.0 boto3==1.43.104 botocore==1.43.104 jmespath==1.1.0
  python-dateutil==2.9.0.post0 s3transfer==0.19.2 six==1.17.0 urllib3==2.8.0`.
- **Isolation:** `AWS_PROFILE` unset; `AWS_CONFIG_FILE` and
  `AWS_SHARED_CREDENTIALS_FILE` pointing at missing scratchpad files; an empty
  `AWS_LOGIN_CACHE_DIRECTORY`; `AWS_EC2_METADATA_DISABLED=true`.
- **Results:** all seven pass:
  - the 4 AuthPrerequisiteTests: CRT pin agreement, unknown profile, pinned
    CRT with an absent login session, LoginProvider without CRT;
  - the 3 BotoShapeTests: the backup workflow, recover by name then StackId,
    and the Titan shapes.
- **One stub changed:** on its first run the backup-workflow test failed with
  `ownership_refused`. Its cleanup `DescribeStacks` stub had no stack `Tags`,
  so the F1 check correctly refused. The stub now carries the creation tags,
  and Stubber validates that shape against the botocore model.

**Other checks:**
- pyflakes 3.2.0 (scratchpad copy) on `flh_aws` and `tests`: clean, after
  removing one unused import.
- `ast.parse(feature_version=(3, 8))` on every module and test: OK.
- One `__pycache__` that my own ad-hoc `python3 -c` check created was removed.

## What `test_integrity.py` adds

**Receipts:**
- **Twelve malformed variants are refused** by `cleanup` (exit 1, fake
  counters unchanged), by `status` (`receipt_invalid`, exit 1) and by
  `recover`:
  - a StackId naming another stack, another account or another region;
  - not an ARN, or a non-string id;
  - an unknown status or schema;
  - bucket/state mismatch, a bad account, objects that are not a list;
  - foreign recorded tags;
  - an id observation without an id.

  Restoring the good receipt still cleans up.
- **Invalid JSON** is refused with zero requests.
- **A bare `DELETE_COMPLETE`** with a valid id, `observed_by` and an absent
  probe, but no confirmation record:
  - `status` reports `verification_unavailable`;
  - cleanup reads by StackId, finds the stack live and owned, and deletes it;
  - the bucket is really gone.
- **An inconsistent confirmation** (wrong `stack_id`, probe time or status, or
  a probe showing `present`) is refused with zero requests.
- **A valid confirmation** repeated 3 times makes zero requests.
- **An FLH-066-era receipt** without a confirmation is re-read once
  (DescribeStacks +1, no new DeleteStack). After that it is cached.

**Ownership:**
- **Observed tags that are foreign, half-foreign or absent:**
  - `ownership_refused` (exit 1);
  - 0 DeleteStack, 0 DeleteObject, 0 HeadObject, and both owned objects still
    recorded;
  - `recover` exits 1.

  Once the tags are restored, cleanup confirms deletion and clears the
  refusal.
- **An answer for a different StackId** gives `ownership_refused` with 0
  deletes.
- **Legacy adoption by name** still reaches `deletion_confirmed`.

**Titan binding:**
- **Record content:** each record carries every binding field.
- **Unchanged continuation:** run twice, it sends 0 calls.
- **What is not reused:**
  - changed text, region or dimensions;
  - a persisted model, `text_convention`, `normalize` or `request_sha256`
    that differs.

  Each of these sends exactly one call.
- **A legacy unbound `ok` record:**
  - it does not qualify (`legacy_unbound_record`);
  - `ok_unbound_legacy: 1`;
  - used 2 with the cap still 10.
- **A failed bound attempt** is not success.

## Compatibility

- **FLH-063/064 legacy receipts** (no schema, no StackId) validate.
  - On a fresh scratchpad copy of `~/flh064/state-aws`, `status` exits 0 with
    `verification_unavailable` and 9 invocations remaining.
  - `continuation_plan` sends all 6 smoke inputs (no prior success).
  - The copy stayed byte-identical (`diff -r`), so the FLH-066 next-run guide
    is unchanged.
- **FLH-066 receipts with a confirmed deletion** are re-read once by StackId,
  then cached. FLH-066 records with a live stack keep working.
- **Titan `ok` records from before FLH-068** never count as done. They remain
  charged, and continuation sends those inputs again, as `not_reused`.
- **Callers:** `titan.invoke` now requires `region=`. The adapter, smoke and
  tests pass it.

## Limitations

- **Trust boundary:** the receipt and ledger are local, unsigned files.
  Validation detects corruption and inconsistent edits, not forgery by
  someone who can rewrite every local file consistently. A consistently forged
  confirmation would be returned from the cache without a read, which the
  zero-request repeat contract requires.
- **Ownership tags on real stacks:** this assumes real DescribeStacks returns
  the stack's creation tags for a live stack, as the botocore model and the
  fakes do. It was not observed against AWS. A live stack missing them is
  refused, never deleted.
- **No real verification:** real AWS behaviour, IAM evaluation and billing
  were NOT RUN. The FLH-067 harness and these tests use filesystem fakes and
  Stubber only.
- **Retained evidence:** the harness keeps synthetic fake buckets in
  `/tmp/flh067-flh068-*` by design. These are local files, not AWS resources.
