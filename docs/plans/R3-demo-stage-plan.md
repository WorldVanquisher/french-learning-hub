# R3: public-demo staging plan, `demo-stage-r3` (plan only)

**Status:** plan and local stand-in only.
- **Access:** AWS is read-only in us-east-1. Cloud writes need separate owner approval. This
  repository's rule keeps AWS commands with the owner, so the inventory below is a set of
  commands for the owner to run.
- **Not decided here:** production DNS, the public host name, production promotion and real
  learner data are separate owner decisions.

## 1. Coordination with Release (R3-021)

Agreed with the Release lane on 2026-11-20 (cross-session message):
- **The demo stage reuses the public-demo stack** (`deploy/aws/terraform`, `Component=public-demo`,
  the existing t4g.micro arm64 instance). Release holds no demo slot.
- **Names the demo stage must avoid** (Release reservations):
  - `flh-stg-*`, `flh-prd-*`;
  - `/flh/staging/*`, `/flh/production/*`;
  - `10.85.0.0/24`, `10.86.0.0/24`;
  - `Component=workbench-staging` and `workbench-production`.
  The demo stack uses `flh-demo-*`, `10.84.0.0/24` and `Component=public-demo`.
- **Single web origin.** The page, `/assets/` and `/api` come from one origin: nginx in front of the
  package's own server on 127.0.0.1. There is no CDN, no S3 web origin and no second host name.
  The private workbench is single-origin too.

## 2. What the stage reuses (R3-022)

| Resource (`deploy/aws/terraform`) | Reused as | Note |
|---|---|---|
| VPC `10.84.0.0/24`, public subnet, internet gateway, S3 gateway endpoint | as is | |
| `aws_instance.host` (t4g.micro, arm64, IMDSv2 required, encrypted gp3 8 GiB) | the stage host | Release reports it exists, with inbound 80/443 open |
| `aws_security_group.host` | as is | Egress TCP 443 only. Inbound 80/443 from anywhere **only** with `public_https_enabled` |
| `aws_eip.public` + association | the stage address | Only with `public_https_enabled` |
| `aws_s3_bucket.artifacts` (private, versioned, encrypted, all public access blocked) | release tarballs under `releases/` | The instance role may read `releases/*` |
| IAM role, instance profile and boundary (`deploy/aws/iam`) | as is | |
| Host tools `flh-release`, `flh-public-https` | install, switch, roll back; TLS | `flh-release` checks only the artifact after a switch; follow it with `check_served.py` |

**Owner-run read-only inventory** (us-east-1; nothing changes):

```sh
aws sts get-caller-identity
aws ec2 describe-instances --region us-east-1 --filters Name=tag:Component,Values=public-demo \
  --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name,PublicIpAddress,MetadataOptions.HttpTokens]'
aws ec2 describe-security-groups --region us-east-1 --filters Name=tag:Component,Values=public-demo \
  --query 'SecurityGroups[].[GroupId,IpPermissions,IpPermissionsEgress]'
aws ec2 describe-addresses --region us-east-1 --filters Name=tag:Component,Values=public-demo
aws s3api list-object-versions --bucket <artifact bucket> --prefix releases/ --query 'Versions[].[Key,VersionId,LastModified,Size]'
```

**Before any stage use:** the instance already accepts 80/443, so check over SSM what it serves:

```sh
sudo flh-release status
sudo flh-release list
```

1. If `current` or the previous release is a package built before the public-provenance rule, retire
   it. That covers every demo package except `pkg-ba2ff1b23210`.
2. `check_package.sh` now refuses such packages.
3. Its `RELEASE.json` and `artifact/provenance.json` hold the private embedding host. They are never
   served, but they must not remain a rollback target.

## 3. The versioned target (R3-023)

| | |
|---|---|
| Environment | `demo-stage-r3` (staging; not production) |
| Release directory | `/srv/flh-demo/releases/flh-public-demo-<label>`; `current` switched by `flh-release` |
| S3 key | `releases/flh-public-demo-<label>.tar.gz`, with bucket versioning on |
| Host name | **owner-chosen**, for example `demo-stage-r3.<owner domain>`. The local stand-in uses `demo-stage-r3.example.org` |
| Package | the final R3 candidate (its digest is in the R3 handoff), CANDIDATE, public provenance |
| Rollback target | `flh-public-demo-pkg-ba2ff1b23210` (public provenance, gate PASS); never a package with private provenance |

## 4. Routing, compression and caching (R3-024, R3-025)

All of it was checked through the local TLS stand-in: the rendered `flh-public-https` nginx files with
only ports, certificate paths and the upstream changed. Evidence:
`r3-026-proxy/proxy-checks.txt` and `headers-per-class.txt`.

| File class | Served by | Cache-Control | Compression | Fallback |
|---|---|---|---|---|
| `/` (the page) | demo server via nginx | `no-cache` (revalidate with `Last-Modified`) | none (3 KB) | none: any other path is 404 |
| `/assets/*.js`, `/assets/*.css` (hashed names) | same | `public, max-age=31536000, immutable` | gzip when asked (`Vary: Accept-Encoding`) | a missing asset is 404, never the page |
| `/api/knowledge-library/*` (JSON) | same | none, and no validators, so not stored by browsers or shared caches | none (owner decision since FLH-084: the warm visit would drop from about 12.8 KB to 2.9 KB with gzip for JSON) | private routes are 404 |
| Anything but GET/HEAD | nginx | | | 405 |
| Another host name | nginx | | | TLS handshake refused; HTTP returns 444 |

## 5. Expected exposure (R3-027)

A static review of `deploy/aws/terraform` and the rendered nginx files.

**Inbound:** none unless `public_https_enabled`. With it, TCP 80 and 443 are open to the world:
- port 80 serves only ACME challenges and a redirect;
- port 443 serves only the stage name, GET and HEAD, with rate and connection limits;
- the demo server listens on 127.0.0.1 only.

**Outbound:** TCP 443 only (SSM, S3 through the gateway endpoint, Let's Encrypt, OS packages).

**On the instance and storage:**
- no SSH, no inbound rule for SSM, IMDSv2 required;
- encrypted root volume;
- the artifact bucket blocks all public access.

**What the public sees:** the read-only demo's allowlisted routes (R3-031) and nothing else.

## 6. Deploy (R3-028) and stage checks (R3-029)

**Not performed:** cloud writes need separate approval. When approved, for this environment and cap:
1. `aws s3 cp <tarball> s3://<bucket>/releases/` (versioned).
2. Over SSM: `sudo flh-release install s3://<bucket>/releases/<tarball> <tarball sha256>`.
3. `sudo flh-public-https preflight <host>`, then `enable <host> --staging` first. The staging CA is
   untrusted, which suits a dry run; then enable without `--staging`.
4. From the owner's machine:
   - `check_served.py https://<host> <package>` must give 7/7;
   - `proxy_checks.sh 443 80 <host> <CA bundle> <package>`;
   - `openssl s_client -connect <host>:443 -servername <host>` must show the certificate's name, its
     issuer and a TLS 1.2 or 1.3 version.

**Cost envelope** (us-east-1 prices retrieved 2026-10-19, FLH-084 §4; recheck in the AWS Pricing
Calculator):

| Shape | Estimate |
|---|---|
| Stage run continuously, t4g.micro + public IPv4 or EIP + gp3 8 GiB + S3 | ≈ $10.42 a month + $0.09 per GB out |
| 7-day stage, instance running 12 h in total, then stopped and destroyed | ≈ $0.31 |
| Stopped but not destroyed | ≈ $0.65 a month (EBS + S3) |

Proposed ceiling for the stage: **$5 and 7 days**. The owner sets the actual ceiling.

## 7. Teardown and rollback (R3-030)

**Roll back the release:**
1. `sudo flh-release rollback`, then confirm the previous release with `check_served.py` (7/7 against
   the previous package; FAIL against the new one).
2. If the previous release is not `pkg-ba2ff1b23210` or another public-provenance package, install
   `pkg-ba2ff1b23210` by its tarball SHA-256 instead.

**Close the stage without destroying it:**
- `sudo flh-public-https disable`. This removes the nginx site and the host from
  `HTTP_ALLOWED_HOSTS`; the instance is private again.
- Then apply `public_https_enabled = false`. This removes inbound 80/443 and the EIP.

**Remove the stage's objects:**
- `aws s3api delete-object --bucket <bucket> --key releases/<tarball> --version-id <id>`, for the
  stage's versions only;
- `certbot delete --cert-name <name>` on the host.

**Destroy the whole stack:** `terraform destroy` (owner). The bucket keeps its objects unless
`artifact_bucket_force_destroy` is true; empty it first.

**Record each time:** what was torn down, when, and that it is confirmed by read-only
`describe-instances`, `describe-addresses` and `list-object-versions`.
