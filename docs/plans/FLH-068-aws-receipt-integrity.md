# FLH-068 AWS receipt integrity, persisted ownership and Titan continuation identity

Owner: local Claude Code. Branch label supplied: `fix/flh-068-aws-receipt-integrity`.
No Git/GitHub command or additional agent was used. Evidence:
[validation](../validation/FLH-068-aws-receipt-integrity.md).

**Input:** [FLH-067](../validation/FLH-067-aws-recovery-acceptance.md) defects F1–F3.
Its harness, `scripts/validation/flh067/accept.py`, is the acceptance oracle,
used unchanged. The general audit was not restarted.

**Not changed:**
- `scripts/validation/flh067/` and the FLH-067 report;
- the IAM policies, `requirements.txt` and the template;
- FLH-065 files, Go production code, `AGENTS.md` and `~/flh064`.

## F1: persisted stack ownership

- **Saved StackId:** every receipt load runs `check_stack_id`, which requires
  `arn:aws*:cloudformation:<region>:<account>:stack/<name>/<uuid>`. Those must
  be the receipt's own region, account and name. A foreign id is a
  `ReceiptInvalid`, raised before any client is built.
- **`cleanup`:** before recording the observation or sending anything
  destructive, it requires the stack read by StackId (`ownership_problems`) to
  have:
  - `StackId` equal to the recorded id;
  - `StackName` equal to the recorded name;
  - live stacks only: tags `flh:task=FLH-063` and `flh:state-id=<state_id>`.

  A deleted stack needs only the identity match, because no write follows it.
  On failure the result is `cleanup_state: ownership_refused` (exit 1): no
  HEAD, DELETE, ListObjects or DeleteStack, and the record is kept as
  `stack.ownership_refused`.
- **Polling:** `wait_stack` rejects an answer for a different StackId.
- **`recover`:** by StackId, it refuses a different name or id, or a live
  stack with foreign tags.
- **Unchanged:** adoption by name keeps its tag check. The existing permission
  scope is reused: DescribeStacks already returns tags, and no `ListStacks` or
  new IAM action is needed.

## F2: receipt integrity

`load_resources` parses and validates. `receipt_problems` checks:

| Field | Invariant |
| --- | --- |
| `schema` | absent (legacy) or `flh066_resources_v2` |
| `region` / `account` / `state_id` | AWS region name / 12 digits / 12 hex |
| `bucket`, `stack.name` | both `flh063-<state_id>` |
| `stack.status` | a CloudFormation status or one of the tool's own |
| `stack.observed_by` | a known observer |
| timestamps | UTC format |
| `stack.tags` (if present) | this task and state |
| `stack.id` | absent or bound (F1). A `DELETE_COMPLETE` status, an id observation or a confirmation without an id is invalid |
| `bucket_probe` | `result` in absent/present/unknown, with a UTC time |
| `objects`, `runs`, `delete_attempts` | the right types; object keys under `flh063/` |

- **Invalid JSON** is refused the same way.
- **On failure:** `ReceiptInvalid` (a `VerificationError`, exit 1) is raised
  before any request. `status` reports `receipt_invalid` (exit 1). No cleanup
  state is derived from it.
- **Cached success:** a `deletion_confirmation` record is written only by
  `probe_bucket`, when `NoSuchBucket` follows a `DELETE_COMPLETE` read by
  StackId. It restates the StackId, status, observation time, bucket and probe
  time. Any new observation drops it.
- **`stack_report` returns `deletion_confirmed`** only when that record is
  consistent with the stack and probe. An inconsistent record is
  `ReceiptInvalid`.
- **A bare `DELETE_COMPLETE`** without the record (including receipts written
  by FLH-066) is `verification_unavailable`. Cleanup then re-reads by StackId
  and writes the record. Repeating a valid confirmation sends nothing.
- **Trust boundary:** this detects corruption, partial edits and inconsistent
  fields. It is not tamper-proofing. An operator who can rewrite every local
  file consistently can forge a receipt and ledger. No signature or secret is
  involved, and none is claimed.

## F3: Titan continuation identity

- **Binding:** each InvokeModel ledger record's `detail` now carries the
  binding `flh068_titan_request_v1` plus the label. The binding covers:
  - model, region, dimensions;
  - `normalize`, `embedding_types`, `text_convention`, identity;
  - `input_sha256` and `request_sha256` of the exact text and body.

  The backend is the record's own field. `invoke()` requires `region=`, and
  the adapter passes it.
- **`continuation_plan`:** an input is done only with an `ok` record for the
  same label and backend, matching every binding field. Inputs with a
  same-label record that does not match are sent again and listed in
  `not_reused`:
  - `legacy_unbound_record` for pre-FLH-068 records;
  - otherwise `different_text_model_region_dimensions_or_convention`.
- **Accounting:** every attempt stays charged. Caps, the whole-plan budget
  check and "no automatic retry" are unchanged.
- **Report:** smoke schema `flh068_titan_smoke_v3`. `ledger_history_before`
  gains `ok_bound` and `ok_unbound_legacy`.

## Files

| File | Change |
| --- | --- |
| `tools/cloud/aws/flh_aws/s3store.py` | `ReceiptInvalid`, `receipt_problems`, `_confirmation_ok`, `ownership_problems`; validating `load_resources`; ownership before writes; confirmation record |
| `tools/cloud/aws/flh_aws/titan.py` | `request_binding`, `continuation_plan`, bound ledger detail, `invocation_history` |
| `tools/cloud/aws/flh_aws/adapter.py` | Passes `region=` to `invoke` |
| `tools/cloud/aws/flh_aws/cli.py` | `status` reports `receipt_invalid` |
| `tools/cloud/aws/tests/test_integrity.py` | New focused tests |
| `tools/cloud/aws/tests/test_boto_shapes.py` | Stack tags in the cleanup DescribeStacks stub; `region=` for `invoke` |
| `tools/cloud/aws/README.md`, `docs/CLOUD_EXPERIMENT.md` | Documentation |
| This plan, the validation report | New |
