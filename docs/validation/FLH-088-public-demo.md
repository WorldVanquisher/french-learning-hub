# FLH-088 — Public HTTPS for the read-only AWS demo (prepared, not applied)

Owner: NAS Claude Code. Builds on FLH-084 to FLH-087.

**Status: PREPARED LOCALLY.**
- Nothing was applied, uploaded or deployed. Public HTTPS is **not**
  demonstrated: that needs live evidence from the human (§9).
- **Not done in this task:**
  - AWS calls, Terraform commands of any kind, DNS changes;
  - uploads, SSM sessions, VPS access;
  - Git, subagents, installations, rebuilds, model or embedding calls.
- **Host name:** confirmed by the owner. Its controlled cutover from the
  VPS is §8. The remaining inputs are the DNS facts and plan review (§2, §8).

**Deployment this builds on (operator-reported, FLH-087):**
- release `flh-public-demo-flh087-rc1`, source
  `dc82235a85b01497957f571ef6870f514ea0cb27`;
- active on `127.0.0.1:18970`, identity match, `real_model=True`;
- previous release `flh-public-demo-flh081-rc1`;
- access only through an SSM port forward.

## 1. Chosen architecture

```
browser ──HTTPS 443──▶ Elastic IP ──▶ EC2 (existing instance)
        ──HTTP 80 (ACME + redirect)─▶   nginx ──▶ 127.0.0.1:18970 flh-server (unchanged, read-only demo)
operator ──SSM (outbound 443 from the host, unchanged)──▶ EC2
```

**Public URL: `https://<host>/` on the standard port 443** (owner requirement).
Visitors never type a port:
- **Port 80** only answers ACME challenges and sends a 301 to the port-less
  HTTPS URL.
- **Application port:** the demo stays on loopback `127.0.0.1:18970`; nginx
  translates ports on the host, with no load balancer.
- **No alternative public port** (8443 or similar) exists anywhere in the
  configuration.

**Port 443 conflict check:**
- **On this instance:** none known. The only listener is `flh-server` on
  `127.0.0.1:18970`, and the SSM agent connects outbound only.
- **The VPS:** its xray/nginx holds 443 on a different machine and address,
  so it does not conflict with this instance's Elastic IP.
  - The confirmed host name currently points at the VPS, which serves it on
    `:8443`.
  - The owner chose a controlled cutover of that one A record (§8). The VPS
    and its `:8443` configuration stay untouched as the recovery target
    (§10).
- **`preflight` re-checks it live:** if anything other than nginx listens on
  80 or 443, it stops and names the holder. It never falls back to another
  port; that would be a new owner decision.

**Option A of FLH-084 plan §3:** nginx with a Let's Encrypt certificate on the
existing instance. It is the smallest supported path:
- **Instance:** reused, not replaced. The change does not touch the instance
  resource or its user data.
- **Packages:** nginx and certbot come from the Amazon Linux repositories. No
  third-party repository, pip or download is used.
- **Proxy configuration:** derived from the package's existing
  `nginx-flh-public-demo.conf.example`. The demo's own Host boundary
  (`HTTP_ALLOWED_HOSTS`) is reused through a systemd drop-in, so the unit
  file is unchanged.
- **No new AWS service:** no CloudFront, ACM, load balancer, Route 53 or WAF.
  Only an Elastic IP and two inbound rules.

**Rejected:**

| Option | Why not |
|---|---|
| CloudFront + ACM | It still needs a non-loopback origin listener on the host, so a proxy is needed anyway. It adds a distribution, an ACM validation record, request and transfer pricing (unverified) and an origin-restriction design |
| ALB + ACM | Hourly plus LCU charges, more than the instance itself (plan §3) |
| Cloudflare Tunnel | Needs DNS served by Cloudflare, which conflicts with Namecheap staying authoritative |
| TLS inside `flh-server` | An application change and a rebuild; it also breaks the loopback-only rule |

**Pieces:**
- **Terraform:** `deploy/aws/terraform/public_https.tf`, gated by
  `public_https_enabled` (default `false`, so the current stack plans
  unchanged). When enabled it adds exactly four resources:
  - `aws_eip.public`, for a stable A record across stop and start;
  - `aws_eip_association.public`;
  - ingress TCP 80 and TCP 443 from `0.0.0.0/0`.

  It adds no IPv6 path. The egress rule (443 only), the instance, its IAM
  role and the S3 path are unchanged. Port 18970 and port 22 are never opened.
- **Host tool:** `deploy/aws/host/flh-public-https`. The operator installs it
  over SSM, deliberately outside cloud-init: `user_data_replace_on_change =
  true` would replace the instance on any user-data change. Its commands:
  - `preflight HOST`: checks the following, and changes nothing:
    - ports 80 and 443 are free, or held by nginx (`ss`);
    - SELinux is not Enforcing;
    - the demo is active and its identity matches;
    - nginx and certbot are available;
    - DNS: exactly one A record, equal to the instance's IMDSv2 public IPv4;
      no CNAME; and a verified empty AAAA answer. A failed lookup is a
      refusal (§12).
  - `enable HOST [--staging] [--email ADDRESS]` runs in three stages:
    1. it installs nginx and certbot, and serves port 80 (ACME webroot
       plus redirect);
    2. it runs `certbot certonly --webroot` (certbot never edits nginx
       files);
    3. it adds the 443 server and sets `HTTP_ALLOWED_HOSTS=HOST` in
       `/etc/systemd/system/flh-public-demo.service.d/50-public-host.conf`.

    It runs `nginx -t` before every reload.
    - **Before replacing `nginx.conf`:** it refuses any foreign or modified
      nginx configuration (§12).
    - **Before HTTPS is served:** the certbot package's own renewal schedule
      must be working, otherwise exit 3 INCOMPLETE (§12).
    - **At the end:** it restarts the demo and checks `flh-release status`
      and HTTPS `/readyz` through nginx on the host.
    - **`--staging`:** uses the Let's Encrypt staging service and the
      separate certificate name `flh-demo-staging`.
  - `status`: the current public configuration, read-only.
  - `disable`: restores the original `nginx.conf`, stops nginx and renewal,
    removes the drop-in and restarts the demo with loopback hosts only.
  - `render`: writes the nginx files for the offline test.
- **nginx policy:**
  - **Listeners:** port 80 and port 443 only.
  - **Other names:** an unknown name on 443 gets a rejected TLS handshake
    (`ssl_reject_handshake`); on 80 it gets `444`.
  - **Methods:** GET and HEAD only (405 otherwise); no request bodies are
    forwarded.
  - **Limits:** 10 requests/s per address, burst 20, 20 connections;
    excess gets 429.
  - **Headers:** client forwarding headers are blanked, and nosniff,
    no-referrer and `X-Frame-Options DENY` are added.
  - **TLS:** 1.2 and 1.3.
  - **Logs:** go to journald, which is capped at 200 MB / 30 days on this
    host.
  - **No HSTS,** so rolling back to private access leaves no browser pin.
- **IAM:** `deploy/aws/iam/flh-experiment-demo-deploy-policy.json` gains:
  - Elastic IP allocate, associate, disassociate and release, tag-scoped to
    the stack;
  - security-group ingress authorize and revoke, tag-scoped;
  - tag-on-create for both;
  - `AssociateAddress`/`DisassociateAddress` on the instance's network
    interface, which carries no stack tag.

  Untested until used (see §7). **Correction (§13):** these statements, with
  every other EC2 statement, now live in the separate policy
  `flh-demo-deploy-ec2` (`flh-experiment-demo-deploy-ec2-policy.json`),
  because the merged policy exceeded IAM's size limit.

**Preserved:**
- read-only public-demo mode and the server-side allowlist
  (`NewPublicDemoBoundary`);
- synthetic data only;
- every provider disabled;
- the artifact identity and pinned model provenance;
- `flh-release` install, identity check and rollback;
- Session Manager management;
- the application on loopback.

**Not changed:** application code, the release package, the systemd unit file,
cloud-init, `flh-release`, the host role and its boundary, and the operate
policy. **No rebuild is required.**

## 2. Prerequisites and exact human inputs

| # | Input | Status |
|---|---|---|
| 1 | **Public host name** `<host>` | **confirmed** by the owner (recorded in the local handoff). It currently points at the owner's VPS (`<vps-ip>`, served on `:8443`); a controlled cutover is intended |
| 2 | The current `<host>` A, AAAA and CNAME values with TTLs, and the authoritative nameservers | operator check §8 D0, before any change |
| 3 | CAA at `<host>` and its parent domain: empty, or allowing `letsencrypt.org` | operator check §8 D0b |
| 4 | Optional ACME contact address for `--email`. Without it, `--register-unsafely-without-email` is used; Let's Encrypt no longer sends expiry emails, and renewal is automatic | owner choice |
| 5 | An IAM administrator creates `flh-demo-deploy-ec2` and saves a new, smaller version of `flh-demo-deploy` (§13; `deploy/aws/iam/README.md` §2b). The account ID is substituted locally, never committed | owner action |
| 6 | Explicit go-ahead for public exposure of the synthetic demo (this task authorises preparation only) | owner decision |
| 7 | Optional: an AWS Budgets alert threshold for data transfer | owner choice |

**Not needed:**
- a certificate purchase, since Let's Encrypt is free;
- a new AWS service, CloudFront, ACM, Route 53 or a load balancer;
- any change to the VPS, its nginx, its xray or its `:8443` configuration;
- any change to the release.

## 3. Browser-visible metadata and the private encoder address

**Finding:** the private encoder address exists only in host-side files:
- `RELEASE.json` → `model_provenance.base_url`;
- `artifact/provenance.json` → `base_url`.

No browser-reachable response contains it.

**How it was established** (run against the verified package
`flh-public-demo-flh087-rc1`, unchanged; its file hashes were identical
before and after):
- **Setup:** the server was started from the package with the existing
  `deploy/ctl.sh`, inside a network namespace with loopback only.
- **Crawl:** 81 requests with a public `Host` (`HTTP_ALLOWED_HOSTS` set as
  nginx will pass it):
  - `/knowledge-library/demo`;
  - all 8 presets × semantic and hybrid search;
  - browse and 6 keyword searches;
  - all 12 Concepts and all 11 unit source records;
  - `/` and every referenced asset;
  - error routes, `/api` and non-demo routes, and `POST/PUT/PATCH/DELETE`.
- **Search:** headers and bodies were matched against private IPv4 ranges
  (10/8, 172.16/12, 192.168/16, 100.64/10), `base_url`, `provenance`,
  `/home/`, `/srv/`, tailnet names and the encoder port.

**Result:**
- **No address, `base_url` or host path** in any response.
- **The only matches:** the word "provenance" in UI message keys and CSS
  class names of the bundle (for example, the "INVALID provenance" label).
- **Not served:** `/RELEASE.json`, `/artifact/provenance.json` and
  `/artifact/manifest.json` return 404. The server serves only `web/` as
  static files, and the demo identity endpoint has no `base_url` field.
- **Positive control:** the same pattern does match `RELEASE.json` on disk.

**Classification:**

| Data | Audience | Action |
|---|---|---|
| `RELEASE.json`, `artifact/provenance.json` on the host and in the tarball | private operator metadata | kept unchanged |
| `/knowledge-library/demo`, search, Concept/source responses, `web/` assets | browser-visible | verified clean; no change needed |

**Why nothing was removed:**
- **`provenance.json`:** its bytes are bound by the artifact manifest and
  checked by the artifact validator. Redacting it would change the artifact
  identity (`d025f217f4d76396` / `dfe6e94d…bcab`).
- **`RELEASE.json`:** copied from it by `package.sh`. Omitting the field
  there would need a packaging change and a rebuild, which this task does not
  require for public HTTPS.

**Follow-up (unchanged from FLH-087):**
- The tarball stays in the private bucket and must not be distributed
  publicly as is.
- A distributable package would need either a packaging change that omits
  `base_url` from `RELEASE.json` plus a new artifact that records a
  non-address encoder identifier, or an explicit decision to publish only the
  hashes. Either way the source change comes first, then a new release label.
- The address is deliberately not reproduced in this repository.

## 4. Changed files

| File | Change |
|---|---|
| `deploy/aws/terraform/public_https.tf` | **new**: gated Elastic IP, association, ingress 80/443 |
| `deploy/aws/terraform/variables.tf` | `public_https_enabled` (bool, default `false`) |
| `deploy/aws/terraform/outputs.tf` | `public_ipv4` (null when disabled) |
| `deploy/aws/host/flh-public-https` | **new**, executable: preflight/enable/status/disable/render |
| `deploy/aws/iam/flh-experiment-demo-deploy-policy.json` | EIP and ingress permissions (§1) |
| `scripts/validation/flh084/static_checks.py` | base-stack guarantees now checked without `public_https.tf`; new public-entry-point checks; locals collected from every file; the new host tool's syntax and its absence from user data |
| `scripts/validation/flh088/public_https_test.py` | **new**: offline render, validation and refusal tests |
| `scripts/validation/flh088/exposure_scan.py` | **new**: the §3 browser-exposure crawl (prints matches without addresses) |
| `docs/AWS_DEMO.md` | status, freeze wording, local checks, stop/start with an EIP, new §11 |
| `deploy/aws/README.md`, `deploy/aws/iam/README.md` | new files and permissions listed |
| `README.md`, `README.zh-CN.md` | AWS runbook row and `deploy/aws` line no longer say "not deployed" |
| `docs/validation/FLH-088-public-demo.md` | this report |

**User-data inputs untouched:**
- `cloud-config.yaml.tftpl`, `flh-public-demo.service.tftpl`, `flh-release`,
  `journald-flh.conf` and `main.tf`;
- their modification times predate this task;
- the static check asserts the host tool is not in the user data.

The human can confirm with `git diff --stat` that these files did not change.

## 5. Commands and observed results (agent-run)

| Command | Result |
|---|---|
| `python3 -B scripts/validation/flh084/static_checks.py` | **253 passed, 0 failed** (includes the new checks: only EIP, association and two ingress rules in `public_https.tf`, all gated; TCP 80/443 IPv4 to the host group; no 22/18970/8080 anywhere; base stack still without ingress, port 80 or EIP; default `false`; instance and user data untouched) |
| `python3 -B scripts/validation/flh088/public_https_test.py` | **58 passed, 0 failed**: every `https://` URL port-less; TLS only on 443; no 8443/8080/4443; `preflight` stops naming the holder when another process holds 443 or 80 (fake `ss`) and accepts nginx on re-run; listeners 80/443 only; single upstream `http://127.0.0.1:18970`; GET/HEAD only; bodies dropped; exact `server_name`; unknown SNI rejected; redirect; webroot; headers; `PORT` from `deploy.env`; 14 bad host names, 4 bad cert names and non-root `enable`/`disable`/`preflight` refused |
| `bash -n deploy/aws/host/flh-public-https` | ok (superseded by §12: 105 passed after the rollout-gap fixes) |
| `python3 -I -c 'json.load(...)'` on the deploy policy | valid JSON, 21 statements |
| `unshare -rn bash -c 'ip link set lo up; GOPROXY=off GOFLAGS=-mod=readonly GOTOOLCHAIN=local go test -count=1 ./internal/transport/http/ ./internal/config/ ./internal/publicdemo/ ./cmd/server/'` | **ok** for all four packages. A first run without `ip link set lo up` failed only because `httptest` could not bind loopback; it is not a code failure |
| `unshare -rn bash -c 'ip link set lo up; PORT=18997 ALLOWED_HOST=demo.example.com sh <pkg>/deploy/ctl.sh start <run>; python3 -I -B scripts/validation/flh088/exposure_scan.py http://127.0.0.1:18997 demo.example.com; sh <pkg>/deploy/ctl.sh stop <run>'` (§3) | 81 requests, 12 Concepts, 11 units, 8 presets; 5 matches, all the word "provenance" in bundle UI strings/CSS; no address, `base_url` or path. Unlisted `Host` → 403. Package file hashes unchanged |
| Write and route restrictions, public `Host` | GET/HEAD `/knowledge-library/demo` → 200; `POST/PUT/PATCH/DELETE` on `/knowledge-library/demo`, `/knowledge-library/concepts`, `/api/knowledge-library/concepts`, `/entries`, `/captures` → **405**; `GET /entries`, `/concepts`, `/RELEASE.json`, `/artifact/provenance.json` → 404; free-text semantic search → 400 |

**Not run, and why:**
- **`terraform fmt -check`, `validate`, `plan`:** AGENTS.md authorised them
  for FLH-085 only. fmt and validate later ran under the readiness review's
  explicit authorisation (§12). `plan` stays with the owner (§8).
- **`render_cloud_config.sh`:** it uses `terraform console`.
- **`nginx -t`, certbot, dnf:** none is installed on the NAS, and no
  installation is allowed. `enable` runs `nginx -t` before every reload on
  the instance.
- **`release_tool_test.py`:** `flh-release` is unchanged; FLH-087 ran it
  against this package with 26 passed.
- **arm64 execution and browser checks:** not run.

## 6. Additional cost estimate

**Assumptions:**
- us-east-1 prices verified in FLH-084 plan §4 (retrieved 2026-10-19), not
  re-verified;
- USD before tax, no free tier or credits;
- continuous operation (the FLH-085 owner decision).

| Item | While running | While stopped |
|---|---|---|
| Elastic IP ($0.005/h) | **+$0.00**: it replaces the auto-assigned public IPv4 already billed at $3.65/month | **+$3.65/month** (the EIP is held; the auto-assigned address would have been released) |
| Ingress rules, nginx, certbot, Let's Encrypt | $0 | $0 |
| Data transfer out | $0.09/GB. A first visit is about 0.35–0.5 MB (314,635 bytes of `index.html` plus assets, uncompressed, plus API JSON), so about **$0.05 per 1,000 first visits** | — |
| DNS record | $0 at AWS. Namecheap pricing for an existing domain is assumed unchanged (not verified) | — |

**Expected total change:** about **$0/month** at low traffic on top of the
current ~$10.42/month, plus transfer at $0.09/GB. A crawler or abuse spike is
bounded per address by nginx, not globally. An AWS Budgets alert notifies; it
does not cap spending.

## 7. Remaining blockers and risks

1. **DNS facts:** human inputs 2 and 3 (§2), checked by the operator before
   the cutover (§8 D0/D0b).
2. **IAM permissions untested:** the new deploy-policy statements were
   checked only as JSON. Whether `AssociateAddress` evaluates the network
   interface (untagged) is not verified. The unconditioned network-interface
   statement is broader than the rest of the policy: it is limited to
   associate/disassociate, and only while the deploy policies are attached.
   Since §13 these statements are in `flh-demo-deploy-ec2`.
   - An `AccessDenied` names the missing action: add only that.
   - Detach both deploy policies after apply. FLH-087's detachment is also still
     unconfirmed.
3. **Plan review by the owner:**
   - the plan must keep the deployed inputs and AMI;
   - it must show exactly **4 to add, 0 to change, 0 to destroy** and no
     replacement (§8 A2);
   - fmt and validate passed locally (§12).
4. **certbot packaging on AL2023 not verified offline:**
   - AWS re:Post documents `dnf install certbot` for AL2023; third-party
     guides report pip.
   - `preflight` stops if `dnf info certbot` fails.
   - `enable` refuses before issuance if the package ships no renewal
     mechanism, and returns INCOMPLETE if that mechanism does not work.
   - No pip or third-party fallback exists; that would be a new owner
     decision.
5. **nginx configuration never executed:** only rendered and structurally
   checked here. The `nginx` version on the AMI must support
   `ssl_reject_handshake` (≥ 1.19.4). `enable` refuses on a failed
   `nginx -t`.
6. **SELinux:** `preflight` refuses if Enforcing. AL2023's default is
   believed permissive, which is not verified here.
7. **Instance replacement:** a future `terraform apply` that replaces the
   instance loses the host's nginx/certbot configuration. After
   re-installing the release, re-run `enable`. Let's Encrypt allows 5
   duplicate certificates per week.
8. **Private encoder address:** host-side only (§3); a follow-up before any
   public tarball distribution.
9. **Stale wording that cannot change here:**
   - AGENTS.md (owner-managed, not edited by agents) still says DNS and
     public exposure "stay frozen";
   - the unit file's comment says the same; editing it would change the user
     data and replace the instance.

   Both describe the default (`public_https_enabled = false`) state.
10. **Abuse exposure:** there is no WAF or global rate limit. The demo is
    read-only, synthetic and provider-free, so the risk is limited to
    availability and transfer cost.

## 8. Human-operated rollout (controlled DNS cutover from the VPS)

**Placeholders.** These values are recorded in the owner's local handoff, not
in Git. The host name must also never appear under `deploy/aws/`, where the
static checks forbid it.
- `<host>`: the confirmed FQDN;
- `<vps-ip>`: its current A destination, the VPS that serves it on `:8443`;
- `<eip>`: `terraform output -raw public_ipv4`;
- `<bucket>`, `<instance-id>`: `terraform output -raw artifact_bucket` and
  `instance_id`;
- `<old-ttl>`: the A record's TTL recorded in D0.

**What the cutover means:**
- **The VPS is not changed.** Its xray, nginx and `:8443` configuration stay
  as the recovery target.
- **Moved:** only the `<host>` A record, from `<vps-ip>` to `<eip>`.
- **`https://<host>:8443/` stops working** from the cutover until a recovery,
  because the AWS security group opens only 80 and 443.
- **VPS certificate renewal:** if the VPS renews its own `<host>`
  certificate by HTTP-01, that renewal also fails while DNS points at AWS.

**NAS (local, no AWS):**
1. **N1.** Review and commit (human Git).
2. **N2.** Run the local checks:
   `python3 -B scripts/validation/flh084/static_checks.py` and
   `python3 -B scripts/validation/flh088/public_https_test.py`. Both must
   report 0 failed.
3. **N3.** Record the tool's hash: `sha256sum deploy/aws/host/flh-public-https`.
   Recompute it after any edit.

**DNS facts before any change (operator workstation, read-only):**
1. **D0.** Record the current values, including TTLs, and keep them for
   recovery:
   ```sh
   dig +noall +answer <host> A        # expect <vps-ip>; note <old-ttl>
   dig +noall +answer <host> AAAA     # record any value (must be empty before certbot)
   dig +noall +answer <host> CNAME    # must be empty: the rollout needs a plain A record
   dig +short NS <parent-domain>      # the authoritative servers (Namecheap)
   ```
2. **D0b. CAA:** it is an explicit operator check; the tool does not parse
   CAA. A CAA lookup starts at `<host>` and climbs to its parents, and the
   first name that has CAA records decides:
   ```sh
   dig +short CAA <host>; dig +short CAA <parent-domain>
   ```
   The result must be empty at every level, or the deciding set must allow
   `letsencrypt.org`.

**AWS (operator workstation):**
1. **A1.** The IAM administrator follows `deploy/aws/iam/README.md` §1 and
   §2b:
   - creates `flh-demo-deploy-ec2`;
   - saves the new, smaller `flh-demo-deploy` version;
   - attaches both to `flh-experiment`.

   The boundary and operate policies are not recreated.
2. **A2.** Keep the deployed Terraform inputs. Use exactly the `-var`/tfvars
   values of the applied FLH-086r2 plan.
   - **AMI:** pin the AMI the instance actually runs. Read it from the state
     the owner holds: `terraform output -raw ami_id`.
   - **Not independently verified:** the earlier reports quote
     `ami-04048e843b318bc37`, but that value is operator-reported. Use the
     output value. If they differ, use the output, and note that the deploy
     policy's launch statement names only the reported AMI.
   ```sh
   cd deploy/aws/terraform
   AWS_PROFILE=flh-plan ~/tools/terraform/1.16.6/terraform plan \
     <the deployed -var/-var-file inputs> -var ami_id=<deployed-ami> \
     -var public_https_enabled=true -out flh088.tfplan
   AWS_PROFILE=flh-plan ~/tools/terraform/1.16.6/terraform show flh088.tfplan
   ```
   **Plan acceptance:**
   - exactly `Plan: 4 to add, 0 to change, 0 to destroy.`;
   - the additions are `aws_eip.public[0]`, `aws_eip_association.public[0]`,
     `aws_vpc_security_group_ingress_rule.http[0]` and `.https[0]`;
   - no "must be replaced" and no update to `aws_instance.host`.

   The owner reviews the full `terraform show` output; anything else means
   stop.
3. **A3.** Apply:
   `AWS_PROFILE=flh-plan ~/tools/terraform/1.16.6/terraform apply flh088.tfplan`.
   Then record `<eip>`.
4. **A4.** SSM is still `Online`:
   `aws ssm describe-instance-information --profile flh-plan --region us-east-1 --query 'InstanceInformationList[].PingStatus'`.
5. **A5.** Detach both `flh-demo-deploy` and `flh-demo-deploy-ec2`, and
   confirm the FLH-087 detachment too.
6. **A6.** Upload the tool:
   `aws s3 cp --profile flh-plan deploy/aws/host/flh-public-https s3://<bucket>/releases/host-tools/flh-public-https`.

**EC2/SSM, before the DNS change**
(`aws ssm start-session --profile flh-plan --region us-east-1 --target <instance-id>`):
1. **H1.** Fetch, check and install the tool:
   ```sh
   aws s3 cp s3://<bucket>/releases/host-tools/flh-public-https /tmp/flh-public-https --region us-east-1
   sha256sum /tmp/flh-public-https          # must equal N3
   sudo install -m 0755 -o root -g root /tmp/flh-public-https /usr/local/sbin/flh-public-https
   ```
2. **H2.** `sudo /usr/local/sbin/flh-public-https preflight <host>`.
   - **Expected now:** it fails at its last check with "A is '`<vps-ip>`',
     expected only `<eip>`". That proves the ports, SELinux, service,
     identity and packages checks passed.
   - **Any earlier failure** is a blocker to fix before touching DNS.

**DNS cutover (owner, Namecheap):**
1. **D1.** Lower the `<host>` A TTL to 300, then wait at least `<old-ttl>`.
2. **D2.** **Replace** the value of the existing `A <host>` record:
   `<vps-ip>` → `<eip>`.
   - Never add a second A record: round-robin would send part of the
     traffic, and Let's Encrypt, to the VPS.
   - Delete any AAAA record for `<host>`, after recording it in D0.
   - Change no nameservers and no other record.
3. **D3. Propagation:** each line must return exactly `<eip>` for A and
   nothing for AAAA:
   ```sh
   for ns in $(dig +short NS <parent-domain>) 1.1.1.1 8.8.8.8; do
     echo "$ns A=$(dig +short A <host> @$ns | tr '\n' ' ') AAAA=$(dig +short AAAA <host> @$ns | tr '\n' ' ')"
   done
   ```
   Allow for caches: resolvers that cached the old record keep it for up to
   the TTL they saw.

**EC2/SSM: certificates:**
1. **H3.** `sudo /usr/local/sbin/flh-public-https preflight <host>` must print
   `preflight ok … (A only, AAAA verified empty, no CNAME)`.
   - It queries the instance's resolver directly.
   - A lookup failure is reported as a failure, never as "no AAAA".
2. **H4. Staging:**
   `sudo /usr/local/sbin/flh-public-https enable <host> --staging`.
   - **Exit 0:** the staging certificate is served. From the workstation,
     `curl -k https://<host>/readyz` returns `{"status":"ready"}`.
   - **Exit 3 (INCOMPLETE):** a certificate was issued, but the package's
     renewal schedule is not working. HTTPS was not enabled. Fix it (see
     `status`), then rerun.
   - **Exit 1:** a refusal with its reason. Nothing beyond what the message
     names was changed.
3. **H5. Production:** `sudo /usr/local/sbin/flh-public-https enable <host>`,
   adding `--email <acme-email>` if one was chosen. A rerun is safe: the
   saved original `nginx.conf` is kept.
4. **H6. Staging cleanup:** `sudo certbot delete --cert-name flh-demo-staging`.
   The production `enable` reminds you of this.
5. **H7. Renewal verification:**
   ```sh
   sudo /usr/local/sbin/flh-public-https status      # renewal: <unit> active, next <time>
   systemctl list-timers --all | grep -i certbot     # the package's timer, with a next run
   sudo certbot certificates                         # only flh-demo, production issuer, expiry ~90 days
   sudo certbot renew --dry-run                      # "Congratulations, all simulated renewals succeeded"
   ```

## 9. Acceptance checks (record each result; until then HTTPS is unproven)

**From the workstation, outside AWS:**
```sh
curl -sS -o /dev/null -w '%{http_code} verify=%{ssl_verify_result}\n' https://<host>/readyz   # 200 verify=0
curl -s https://<host>/readyz                                                                # {"status":"ready"}
curl -s https://<host>/knowledge-library/demo | python3 -m json.tool | grep -E '"version"|"manifest_sha256"|"real_model"'
#   d025f217f4d76396 / dfe6e94de6664c18be2ae65a27ad9b6c107e7ceefb56a1627fe3f54d4788bcab / true
curl -sI http://<host>/ | head -3                                        # 301, Location: https://<host>/
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<host>/knowledge-library/concepts   # 405
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/entries                               # 404
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/RELEASE.json                          # 404
curl -sv --connect-to other.invalid:443:<eip>:443 https://other.invalid/ 2>&1 | grep -iE 'alert|handshake'  # handshake rejected
curl -s -m 5 http://<eip>/ ; echo "exit $?"                             # empty reply (444)
curl -s -m 5 http://<eip>:18970/ ; echo "exit $?"                       # timeout: port not open
echo | openssl s_client -connect <host>:443 -servername <host> 2>/dev/null | openssl x509 -noout -issuer -enddate   # Let's Encrypt (not STAGING)
```

**On the host:**
- `sudo /usr/local/sbin/flh-release status` →
  `current: flh-public-demo-flh087-rc1`, `(match)`;
- `sudo /usr/local/sbin/flh-public-https status` → nginx `active`,
  `renewal: <unit> active, next <time>`;
- H7 passed, including `certbot renew --dry-run`.

**Browser (desktop and phone), each recorded separately:**
1. the page loads over HTTPS with no certificate warning;
2. English on first load;
3. one keyword search;
4. one semantic and one hybrid preset;
5. a Concept;
6. a supporting unit's source record;
7. switch to 简体中文 and back.

An overall impression is not a per-feature acceptance.

## 10. Recovery and rollback

**Recovery to the VPS** (the previous public destination of `<host>`). Run it
in this order. Restoring DNS first keeps visitors with cached answers served
by AWS until their caches expire:
1. **R1, DNS (owner, Namecheap):** restore the records recorded in D0:
   - `A <host>` → `<vps-ip>` with `<old-ttl>`;
   - any AAAA record that was removed.
   Change nothing else.
2. **R2, wait out caches:** wait at least 300 s, the TTL in effect during the
   cutover. Then repeat the D3 loop until every resolver returns `<vps-ip>`.
   Check that `https://<host>:8443/` loads from the workstation.
3. **R3, EC2/SSM:** `sudo /usr/local/sbin/flh-public-https disable`.
   - nginx and the renewal timer stop;
   - the package `nginx.conf` is restored;
   - the drop-in is removed and the demo runs on loopback hosts only;
   - `flh-release status` is checked, and the SSM preview works as before.
4. **R4, AWS, only after R2:**
   - attach `flh-demo-deploy` and `flh-demo-deploy-ec2`;
   - plan with the same deployed inputs and `-var public_https_enabled=false`.
     It must show exactly **4 to destroy**, 0 to add or change; then apply;
   - the instance receives a new auto-assigned public IPv4 (per AWS
     documentation; not verified here), so outbound SSM continues;
   - confirm SSM `Online` and `flh-release status`;
   - detach both policies.

   Releasing the Elastic IP while any resolver can still return it could let
   another AWS customer receive traffic for `<host>`.
5. **R5, optional host cleanup:** `sudo dnf remove nginx certbot`.
   Certificates remain in `/etc/letsencrypt` until removed with
   `sudo certbot delete --cert-name flh-demo`.

**A failed `enable` without a DNS rollback** (for example exit 3 or a
refusal): `sudo /usr/local/sbin/flh-public-https disable` returns the host to
private-only access. Even without a state file, it finds and stops the
package's renewal timer.

**Release rollback is independent.** The drop-in applies to whichever release
is current, and `flh-release`'s identity check uses a loopback `Host`.
`sudo /usr/local/sbin/flh-release rollback` restores
`flh-public-demo-flh081-rc1` with HTTPS still enabled. No production rollback
has been exercised.

## 11. Self-handoff

- **Implementation:** §4 files plus the rollout-gap fixes in §12. No
  application, packaging, unit, cloud-init, IAM, Terraform or lock-file
  change; no rebuild needed.
- **Validation:** §5 and §12.
- **Pending human:**
  - the D0/D0b DNS facts;
  - the IAM policy version;
  - the full plan review and apply;
  - the cutover and host rollout (§8);
  - live acceptance evidence (§9);
  - the FLH-087 policy-detachment confirmation.
- **Frozen:** bilingual concept explanations.
- **Unknowns, checked on the host by `preflight`/`enable`:**
  - which certbot renewal mechanism the AMI's package ships;
  - the nginx version and the SELinux mode.

  Also unknown: the IAM evaluation of `AssociateAddress`.

## 12. Rollout-gap fixes (after the readiness review)

**Host tool (`deploy/aws/host/flh-public-https`):**
- **DNS:** `preflight` sends its own recursive queries to the system resolver
  (Python standard library, UDP with TCP fallback). It requires:
  - exactly one A record equal to the instance's public IPv4;
  - no CNAME;
  - a verified empty AAAA answer: NOERROR from a recursive resolver.

  An AAAA answer, NXDOMAIN, SERVFAIL, a timeout, a non-recursive or a
  malformed reply are all refused, each with its own message. A lookup
  failure never counts as "no AAAA".
- **nginx configuration:** before replacing `nginx.conf`, `enable` requires
  one of two states:
  - this tool's own file (marker line) with the saved original present, for a
    safe rerun;
  - the unmodified package file, checked with `rpm -qf` and `rpm -V`.

  It refuses:
  - any `*.conf` in `conf.d/` or `default.d/`;
  - unexpected files in its site directory;
  - an existing saved original next to a foreign `nginx.conf`.

  It names the conflict and changes nothing.
- **Renewal:**
  - **Mechanism:** a systemd timer, or a cron file plus a running `crond`,
    read from the installed certbot package's own file list (`rpm -ql`). No
    timer name is assumed and no other source is added.
  - **No mechanism:** refused before any certificate is requested.
  - **After issuance:** the schedule must be enabled and active, with a next
    run, and the renewal configuration must use `webroot` with the nginx
    reload hook. Otherwise the result is **exit 3 INCOMPLETE** and HTTPS is
    not enabled.
  - **`status` and `disable`** use the recorded mechanism; `disable` falls
    back to the package's mechanism after an incomplete run.
- **Bug fixed:** the EXIT trap referred to a function-local temporary
  directory. Under `set -u` that turned a successful `enable` into exit 1. It
  is now a global, as in `flh-release`.

**Commands and observed results (agent-run, this task):**

| Command | Result |
|---|---|
| `bash -n deploy/aws/host/flh-public-https` | ok |
| `python3 -B scripts/validation/flh084/static_checks.py` | 253 passed, 0 failed |
| `python3 -B scripts/validation/flh088/public_https_test.py` | **105 passed, 0 failed**. The 58 render/refusal checks, plus 47 behavioural checks against an isolated `FLH_SYSROOT`, fake `dnf`/`rpm`/`nginx`/`certbot`/`systemctl`/`curl`/`ss`, and a fake recursive DNS server on 127.0.0.1 |

**The behavioural checks cover:**
- **11 DNS outcomes** for `preflight`, which changes nothing;
- **staging first run:** the original saved byte for byte, the renewal timer
  enabled before HTTPS, the state file and the drop-in;
- **production rerun:** the original is not overwritten, the production
  certificate is used, and staging cleanup is announced;
- **`disable`:** it restores the package file and stops the timer, and
  `enable` works again afterwards;
- **nginx refusals:** a modified `nginx.conf`, `conf.d` and `default.d`, an
  unowned file, a managed file without its original, an existing original,
  and stray site files. Another modified package file is correctly ignored;
- **renewal:** no mechanism refused before certbot; INCOMPLETE without a next
  run, without the reload hook, and with cron but no `crond`; success with
  cron and `crond`; `disable` after INCOMPLETE;
- **`enable` refused before installation** while A still points elsewhere,
  or while an AAAA record exists.

**Mutation check** (modified copies of the tool in a scratch directory; the
repository untouched):

| Mutation | Result |
|---|---|
| AAAA lookup errors accepted as empty | 3 failures |
| `rpm -V` skipped | 1 failure |
| Renewal failure reduced to a note | 3 failures |

**Readiness-review results (earlier task, not re-run):** Terraform 1.16.6
`fmt -check`, offline `init -backend=false -lockfile=readonly` and `validate`
passed on an isolated copy, with the lock file unchanged. No Terraform file
changed since.

## 13. Correction: IAM managed-policy size limit (after §12)

**What happened (operator-reported):** the AWS console rejected the merged
`flh-demo-deploy` policy because it exceeded the 6,144-character limit for
customer managed policies. That limit counts characters other than
whitespace.

**Fix:** the policy is split in two, without changing any permission:
- **`flh-demo-deploy`** (`deploy/aws/iam/flh-experiment-demo-deploy-policy.json`,
  same file and AWS name) keeps the 9 non-EC2 statements:
  - IAM host role, tags, instance profile and PassRole;
  - the three S3 artifact-bucket statements;
  - both explicit Denies.
- **`flh-demo-deploy-ec2`** (`deploy/aws/iam/flh-experiment-demo-deploy-ec2-policy.json`,
  new) holds the 12 EC2 statements, moved unchanged and in their original
  order.
- **The only content change:** `DenyEditingGuardPolicies` also names
  `arn:aws:iam::__AWS_ACCOUNT_ID__:policy/flh-demo-deploy-ec2`, so
  `flh-experiment` cannot edit the new policy either.
- **Both are attached** while applying or destroying, and both are detached
  afterwards. The boundary and operate policies are unchanged and are not
  recreated.

**Validation (agent-run, synthetic account ID `123456789012`; no AWS):**
- `python3 -I -B <scratch>/check_split.py <copy of the merged policy> deploy/aws/iam/flh-experiment-demo-deploy-policy.json deploy/aws/iam/flh-experiment-demo-deploy-ec2-policy.json`
  → all checks passed:

| Policy | Non-whitespace characters | Limit |
|---|---|---|
| merged `flh-demo-deploy` before the split | 7,037 | over |
| `flh-demo-deploy` | 2,503 | 6,144 |
| `flh-demo-deploy-ec2` | 4,627 | 6,144 |

- **What the check proves:**
  - both files parse with `Version` 2012-10-17, and placeholders remain in
    the repository files;
  - the Sids are unique, and are exactly the original 21;
  - every statement is identical to the original (Effect, Action, Resource,
    Condition) except `DenyEditingGuardPolicies`, which only gains the new
    ARN;
  - the EC2 file holds only `ec2:` Allow statements, and the other file holds
    no `ec2:` action and both Denies;
  - no new wildcard was introduced.
- `python3 -B scripts/validation/flh084/static_checks.py` → **262 passed, 0
  failed**. That is 253 plus the 9 forbidden-pattern scans of the new file,
  which found no account ID or secret.

**Earlier results in this report are unchanged.** The §5 line "valid JSON, 21
statements" described the merged file; the 21 statements are now split 9 + 12.

