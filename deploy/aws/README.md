# deploy/aws — read-only public demo on one EC2 instance (FLH-084)

Prepared configuration only; nothing here has been initialised, planned or
applied. Procedure: [docs/AWS_DEMO.md](../../docs/AWS_DEMO.md). Decisions and
cost: [docs/plans/FLH-084-aws-demo-deployment.md](../../docs/plans/FLH-084-aws-demo-deployment.md).

| Path | Purpose |
|---|---|
| `terraform/` | VPC with one public subnet (no inbound rule, egress 443), S3 gateway endpoint, minimal Session Manager instance role, private versioned artifact bucket, one encrypted gp3 instance with IMDSv2. Region, architecture, instance type and AMI are variables. |
| `host/flh-release` | Installed by cloud-init as `/usr/local/sbin/flh-release`: verified install, identity check, automatic and manual rollback, status, deployment log. |
| `host/flh-public-demo.service.tftpl` | systemd unit rendered per architecture: loopback only, providers disabled, hardened sandbox. |
| `host/journald-flh.conf` | Journal size and retention limits. |

Local checks without AWS: `python3 -B scripts/validation/flh084/static_checks.py`
and `scripts/validation/flh084/release_tool_test.py` (see the runbook §2).
