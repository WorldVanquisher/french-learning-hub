# FLH-084 — First AWS deployment of the read-only demo: decisions and cost

Status: **prepared, not deployed.** This task wrote configuration, host tooling,
tests and documentation. It created no AWS resource and spent nothing. It made
no DNS change and exposed nothing publicly. Running anything below is the human
owner's decision; the procedure is in [docs/AWS_DEMO.md](../AWS_DEMO.md).

## 1. Scope

**First-stage workload: the existing read-only public demo only.** It runs as
`cmd/server -public-demo-artifact` on synthetic data with cached model vectors,
from an FLH-076/078 release package. The FLH-081 rc1 candidate qualifies, as
does a newer package built with the same tooling.

**Not on this host:**
- Windows, GPU, the E5 model service, Qdrant or any provider call;
- the personal database;
- the write-capable workbench.

**Frozen:**
- public exposure: no inbound rule of any kind;
- DNS: Namecheap stays authoritative, and no record is added or changed;
- HTTPS.

Preview is private, over an SSM port forward to the operator's own machine.

## 2. Decisions

| Topic | Decision | Why |
|---|---|---|
| Region | Variable `aws_region`, no default. | Owner choice. Prices differ (§4); the data is synthetic, so there is no residency constraint. |
| Architecture | Variable `architecture` (`arm64` or `x86_64`), no default. The `instance_type` must match, which a plan-time precondition checks. | The package ships `bin/linux-amd64` and `bin/linux-arm64`. Graviton (t4g) costs about 20% less than t3 of the same size. |
| Compute | One EC2 instance. Suggested size `t4g.micro` (2 vCPU, 1 GiB); `t4g.nano` (0.5 GiB) also fits. Burstable credits are `standard`. | Measured (FLH-081): about 21 MB RSS idle, 28 MB peak, 15 threads, 0.27 s to ready. `standard` credits throttle instead of billing surplus. |
| OS / AMI | Amazon Linux 2023, from the public SSM parameter `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-<arch>`, or a pinned `ami_id`. | The SSM Agent, AWS CLI v2, python3 and systemd ship in the AMI, so nothing is installed at boot. Pinning the AMI keeps a new AMI release from replacing the instance on a later plan. |
| Storage | One encrypted gp3 root volume, 8 GiB, with `delete_on_termination=true`. No snapshots. | The host holds nothing that cannot be rebuilt from the bucket and Terraform. A package is about 40 MB packed and 70 MB unpacked. |
| Artifact transfer | A private S3 bucket:<br>- public access blocked, owner-enforced;<br>- SSE-S3 encryption and versioning;<br>- TLS-only;<br>- non-current versions expire after 30 days;<br>- `force_destroy=false`.<br>The instance role may only `s3:GetObject` objects under `releases/`, and only through the VPC's S3 gateway endpoint. | No credentials or presigned URLs reach the host, user-data or state. The expected SHA-256 comes from the operator's local `.sha256` file, never from the bucket. |
| Network | A dedicated VPC with one public subnet, an internet gateway and a free S3 gateway endpoint. The instance gets an auto-assigned public IPv4 address. Its security group has **no inbound rule** and allows outbound TCP 443 only. The VPC default security group is stripped of rules. | SSM needs outbound HTTPS to `ssm`, `ssmmessages` and `ec2messages` in the region. One public IPv4 (about $3.65/month) is cheaper than the three interface endpoints or the NAT gateway a private subnet would need (§4.3). |
| Operator access | AWS Systems Manager Session Manager (shell and port forwarding). No SSH key, no port 22, no bastion. | Session Manager has no extra charge on EC2. Access is authorised by the operator's IAM identity and logged in CloudTrail. |
| Instance IAM | AWS's documented **minimal Session Manager policy**:<br>- `ssm:UpdateInstanceInformation`;<br>- `ssmmessages:Create/OpenControlChannel` and `ssmmessages:Create/OpenDataChannel`;<br>- plus the scoped `s3:GetObject`.<br>Not `AmazonSSMManagedInstanceCore`. | The managed policy also allows reading every SSM parameter in the account, and Run Command and associations, which this deployment does not use. |
| Metadata | IMDSv2 required, hop limit 1, instance tags not exposed. | Standard hardening. |
| Process management | systemd unit `flh-public-demo.service`, rendered per architecture. It derives from the FLH-076 template and the FLH-081 hardened proposal:<br>- runs as `flh-demo`, bound to `127.0.0.1:18970`;<br>- every provider disabled, `HTTP_ALLOWED_HOSTS` empty;<br>- `ProtectSystem=strict`, `IPAddressDeny=any` / `IPAddressAllow=localhost`;<br>- `MemoryMax=256M`, `CPUQuota=100%`, `TasksMax=64`. | The read-only demo boundary (`NewPublicDemoBoundary`) is unchanged. Loopback host names are always accepted, which is all the SSM preview needs. A public host name would be added only after the freeze is lifted. |
| Release install | `flh-release`, installed by cloud-init. It downloads the tarball and verifies the operator-supplied SHA-256. It refuses unsafe tar members, runs the package's own `validate-release.sh` (CANDIDATE required) and makes the release read-only. It then switches `current` atomically, restarts, and requires the live `/knowledge-library/demo` identity to equal the release's own `RELEASE.json` and manifest hash. It rolls back automatically on failure and logs every switch. | Reuses the FLH-076 layout (`releases/<pkg>`, `current` symlink) and the FLH-080 identity rule. BLOCKED (mechanical-vector) packages are refused by name and by validation. |
| Logs | journald, persistent, capped at 200 MB and 30 days, identifier `flh-public-demo`. No CloudWatch Logs. | Bounded and free; CloudWatch ingestion and storage cost money and are not needed for a private preview. |
| Traceability | Each install records a tab-separated line in `/srv/flh-demo/state/deployments.log`: time, action, package, tarball SHA-256, `source_revision`, artifact version and result. `flh-release status` reports these and checks the live identity. | `RELEASE.json` carries the human-supplied source revision; the artifact manifest hash binds the data and vectors. |
| Lifecycle | Teardown is `terraform destroy`. The bucket must be emptied deliberately, by setting `artifact_bucket_force_destroy=true` and applying. Termination protection is off by default. | Explicit, so data is never removed by accident and billable leftovers stay visible (§4.5). |
| State | Local Terraform state with no remote backend; git-ignored. | It holds IDs and ARNs only. Nothing in the configuration creates or reads a secret. |

**Not added, because nothing in the first stage requires them:**
- RDS, ECS, EKS, load balancers, NAT gateways;
- Elastic IPs, interface endpoints;
- Route 53, CloudFront, ACM;
- CloudWatch alarms and logs, AWS Backup, snapshots.

## 3. HTTPS and public exposure (unresolved, frozen)

None of these options is implemented. Each one needs owner decisions first:
- a host name;
- a Namecheap record that preserves the existing records;
- a certificate validation method;
- the inbound path;
- adding the host name to `HTTP_ALLOWED_HOSTS` through a unit drop-in.

| Option | What it adds | Notes |
|---|---|---|
| A. nginx or Caddy on the instance, with a Let's Encrypt certificate | Inbound 80/443 from the internet. An Elastic IP for a stable A record, billed while the instance is stopped. The package's `nginx-flh-public-demo.conf.example` (rate limits) as the starting point. | Cheapest. The instance becomes directly internet-facing, and certificate renewal runs on the host. |
| B. CloudFront, with an ACM certificate in us-east-1 | A distribution and a DNS-validation CNAME at Namecheap. The origin is the instance, restricted to the CloudFront origin-facing prefix list, or a CloudFront VPC origin. | CDN caching of static assets, and the host is not directly exposed. CloudFront request and transfer prices are **not verified** here. |
| C. ALB with ACM | A load balancer at an hourly charge plus LCUs. | Excluded for the first stage: its cost exceeds the instance's, for one target. |
| D. Cloudflare Tunnel (FLH-081 proposal) | An outbound-only connector, no inbound rule. | Needs the zone, or the record, served by Cloudflare. This conflicts with Namecheap remaining authoritative unless the owner accepts that. |

## 4. Cost estimate

**Sources and scope:**
- **Pricing date:** official AWS sources, retrieved 2026-10-19:
  - the EC2 on-demand price feeds behind <https://aws.amazon.com/ec2/pricing/on-demand/> (published 2026-10-15);
  - the AWS Price List bulk offers for AWSDataTransfer (published 2026-09-16) and AmazonS3 (published 2026-10-15), us-east-1;
  - <https://aws.amazon.com/vpc/pricing/> (public IPv4);
  - <https://aws.amazon.com/ebs/pricing/>;
  - <https://aws.amazon.com/systems-manager/pricing/>.
- **Currency and tax:** prices are USD, before tax. Tax may apply and is not estimated.
- **Not assumed:** free tier, credits or Savings Plans.
- **Budgets:** an AWS Budgets alert notifies; it does not cap or stop spending.
- **Calculator:** recompute in the AWS Pricing Calculator (<https://calculator.aws/>) with the inputs in §4.6 before applying.

### 4.1 Unit prices

| Item | us-east-1 | ap-northeast-1 (Tokyo) | ap-southeast-1 (Singapore) | Status |
|---|---|---|---|---|
| t4g.nano (2 vCPU, 0.5 GiB) | $0.0042/h | $0.0054/h | $0.0053/h | verified |
| t4g.micro (2 vCPU, 1 GiB) | $0.0084/h | $0.0108/h | $0.0106/h | verified |
| t4g.small (2 vCPU, 2 GiB) | $0.0168/h | $0.0216/h | $0.0212/h | verified |
| t3.nano / t3.micro / t3.small | $0.0052 / $0.0104 / $0.0208 per h | $0.0068 / $0.0136 / $0.0272 per h | $0.0066 / $0.0132 / $0.0264 per h | verified |
| Unlimited-mode surplus CPU credits | T4g $0.04, T3 $0.05 per vCPU-hour | same page | same page | verified (EC2 on-demand page); not incurred with `cpu_credits=standard` |
| Public IPv4 address | $0.005/h, in use or idle | $0.005/h | $0.005/h | verified (VPC pricing page) |
| gp3 storage | $0.08/GB-month | ? | ? | **unverified per region.** The EBS page shows $0.08 only as an example for an unnamed region; it includes 3,000 IOPS and 125 MB/s |
| EBS snapshots | $0.05/GB-month | ? | ? | **unverified per region** (same example); none are created |
| S3 Standard storage | $0.023/GB-month (first 50 TB) | ? | ? | verified for us-east-1 only |
| Data transfer out to the internet | $0.09/GB (first 10 TB/month) | ? | ? | verified for us-east-1 only. The EC2 page also lists 100 GB/month free, aggregated across services; not relied on here |
| Session Manager | no additional charge on EC2 | same | same | verified |
| Interface VPC endpoint (not used) | ? | ? | ? | **unverified**; not on the pages fetched |

### 4.2 Continuously running month (730 h)

The configuration as delivered:
- one instance with `standard` credits;
- one public IPv4 address;
- 8 GiB gp3;
- one or two package versions (about 0.1 GB) in S3.

| Line | us-east-1, t4g.micro | us-east-1, t4g.nano | us-east-1, t3.micro | Tokyo, t4g.micro | Singapore, t4g.micro |
|---|---|---|---|---|---|
| Instance (730 h) | $6.13 | $3.07 | $7.59 | $7.88 | $7.74 |
| Public IPv4 (730 h) | $3.65 | $3.65 | $3.65 | $3.65 | $3.65 |
| gp3 8 GiB | $0.64* | $0.64* | $0.64* | ≈$0.64–0.80* | ≈$0.64–0.80* |
| S3, about 0.1 GB | < $0.01 | < $0.01 | < $0.01 | < $0.01* | < $0.01* |
| **Subtotal** | **≈ $10.42** | **≈ $7.36** | **≈ $11.88** | **≈ $12.2–12.4** | **≈ $12.0–12.2** |
| Data transfer out | + $0.09 per GB | same | same | regional rate* | regional rate* |

\* Unverified regional rate; confirm in the calculator. The Tokyo and Singapore
gp3 range is an assumption, not a quoted price.

**Data transfer:** private previews move a few MB per session; a page view of the
demo is well under 1 MB. Transfer is cents at this stage. Session Manager
traffic is not separately priced on the pages fetched.

### 4.3 Rejected alternatives for SSM connectivity

**Private subnet with interface endpoints:** three endpoints (`ssm`,
`ssmmessages`, `ec2messages`), billed per endpoint, per AZ, per hour, plus
per-GB processing. The price was **not verified** in this task. Even at a low
hourly rate, three endpoints for 730 h cost several times the $3.65 public IPv4
line.

**NAT gateway:** hourly plus per-GB processing, and it still needs a public IPv4
address. Not verified; much more than the instance itself.

### 4.4 Intermittent trial

The scenario is:
- the stack exists for 7 days (168 h);
- the instance runs 12 h in total;
- it is stopped otherwise;
- then `terraform destroy`.

Costs (us-east-1, t4g.micro):

| Line | Amount |
|---|---|
| Instance: 12 h × $0.0084 | $0.10 |
| Public IPv4: 12 h × $0.005 (an auto-assigned address is released on stop, so it is billed only while running) | $0.06 |
| gp3: 8 GiB × $0.08 × 168/730 | $0.15* |
| S3 | < $0.01 |
| **Total** | **≈ $0.31** |

**Stopped but not destroyed:** EBS plus S3 cost about **$0.65/month**. This is
the most likely forgotten charge.

### 4.5 Charges for stopped resources and teardown obligations

**While the instance is stopped:**
- **EBS:** the root volume is billed per GB-month for as long as it exists,
  running or stopped.
- **Public IPv4:** the auto-assigned address is released on stop and is not
  billed. An Elastic IP (not used here; option A in §3) would be billed while
  stopped.
- **Instance and credits:** no instance-hour or CPU-credit charge.

**Charges that continue until removed:**
- **S3:** objects, including non-current versions, until they are deleted.
  Non-current versions expire after 30 days by the lifecycle rule; current
  versions stay.
- **Snapshots or AMIs:** none are created by this configuration. If an operator
  makes one, it bills until deleted.
- **Left-behind resources:** after `terraform destroy`, run the read-only
  leftover checks in AWS_DEMO.md §9. They cover volumes, addresses, snapshots,
  the bucket and tagged resources.

### 4.6 Calculator inputs

**Amazon EC2:**
- Region: the chosen one.
- Operating system: Linux.
- Tenancy: shared.
- Workload: constant usage.
- Instance type: `t4g.micro` (or the chosen type).
- Pricing: On-Demand.
- Usage: 730 hours per month, or the trial hours.
- Storage: EBS gp3, 8 GB, 3,000 IOPS, 125 MB/s throughput.
- Snapshot frequency: none.
- Detailed monitoring: off.
- Data transfer out to the internet: 1 GB per month.

**Amazon VPC:** public IPv4 addresses, 1 in-use address for 730 hours (or the
trial hours).

**Amazon S3:**
- S3 Standard: 0.1 GB.
- PUT requests: 10 per month.
- GET requests: 50 per month.

**AWS Systems Manager (Session Manager):** none to enter.

**Optional comparisons:**
- **Private subnet with endpoints:** VPC interface endpoints, 3 endpoints × 1 AZ × 730 h.
- **Option A:** an Elastic IP held while stopped.
- **Option B:** CloudFront for the expected monthly requests and GB.

## 5. Scope of a later private workbench and inference migration

This section is not part of this deployment and was not designed here. It only
records constraints, so this stack is not stretched to fit those later needs.

**Separate hosts and stacks:** the write-capable workbench and personal database
must not share the public demo host, its security group or its instance role.

**What the workbench would need:**
- a writable SQLite volume with backups (snapshots or AWS Backup);
- private access only, unless authentication is in scope, which it is not in
  this project;
- the existing Compose release (docs/RELEASE.md) rather than demo mode.

**What E5 inference would need:**
- a CUDA GPU instance type;
- the pinned model files;
- Qdrant.

Each brings costs an order of magnitude above this stack. This stays deferred
until the operational baseline and the owner's budget call for it.
