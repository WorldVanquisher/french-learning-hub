# Interface notes: Release aws-prep ↔ Extraction and UI (2026-11-21)

These notes are owned by the Release lane. They record contracts this plan relies on. Nothing here asks another
lane to edit a file in this worktree.

## 1. Extraction (runtime)

Asked on 2026-11-21. The answer was checked on the Extraction branch, as reported by the Extraction session; it is
not verified here except for item 1.

| # | Assumption | Answer |
| --- | --- | --- |
| 1 | Staging runs the rule-based service only; `deployment_id flh-extraction-rules@e978b6c2bdb6/flh_extraction_service_v1/flh_practice_drafter_v1` | confirmed; `service_examples.py --check` equal on both trees (this tree verified directly) |
| 2 | 256m memory and memory-swap, 1 CPU, pids 64, read-only, user 10002, cap_drop ALL, no published port, 5 s per request | confirmed (service default `--timeout 5`) |
| 3 | Base `python:3.12-slim@sha256:6c4dd321…fa8e`; pin the `deployment_id`, not the image ID | confirmed |
| 4 | The app does not call the service; the client reports `unavailable` once, no retry, no fallback | confirmed |
| 5 | Qwen3.5-4B rev `851bf6e8…`, 9,319,737,856 bytes, SageMaker only; smoke 0.5 h on ml.g5.xlarge | confirmed; exact $0.704 (cap $0.71). License Apache-2.0, recorded in `models.py` (`"license": "apache-2.0"`; Extraction's correction, verified here) and in `TRAINING_RUNBOOK.md` §1 |
| 6 | E5 is CUDA-only and outside the staging pass | outside Extraction's lane; FLH-054 says optional and CUDA-only |

**Interface Release relies on:**
- the result envelope;
- `GET /healthz`, `/readyz` (self-check) and `/manifest` (`deployment_id`);
- the result codes 503 `busy`, 504 `timeout` and `unavailable`.

A change to any of these, or to the `deployment_id`, needs a message to Release before merge.

## 2. UI (workbench and public demo)

- This task changes no `web/` file; `npm run typecheck` is not needed for it.
- The proposed portal at `flh.vanquisher.world` is a separate static page with no API calls, sign-in or form. If it is
  ever built from `web/`, it needs its own build target, the public demo's rules (no private routes) and both locale
  catalogs (FLH-083).
- The public demo moves to `demo.flh.vanquisher.world` only by DNS and certificate changes (C2, C3); no UI change.
- No pilot UI (sign-in, invitation, account switcher) before authentication exists (plan §10). Until then, anything
  reachable through the SSM port forward is preview access, not pilot access.

## 3. Demo lane (deploy/aws/terraform, host/flh-public-https)

- **Record the live public HTTPS state.** The R5 read-only snapshot shows the demo security group with inbound
  TCP 80/443 open, while `deploy/aws/README.md` and FLH-088 say "prepared, not applied". Whether an Elastic IP exists
  is unreadable to the read-only profile.
- **Ignore every tfvars file.** `deploy/aws/terraform/.gitignore` ignores `terraform.tfvars` only. Adding `*.tfvars`
  and `*.auto.tfvars` (keeping `*.tfvars.example`) would match the staging root; `state_guard.py ignore-check`
  reports this as a NOTE.
- **Rename when chosen.** A move of the demo to `demo.flh.vanquisher.world` (plan §9, C2/C3) uses your
  `flh-public-https --host`, and its rollback is a re-run with the previous name.
