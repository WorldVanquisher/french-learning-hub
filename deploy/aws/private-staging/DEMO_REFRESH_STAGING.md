# Staging candidate and hosting instructions (items 9–16, updated for the final candidate, items 54–62)

**Final candidate:** `flh-public-demo-fe6-BLOCKED`, tarball SHA-256
`1c6d798e55f8078daf7ca8927df25b2fdf6c146fd3f694c5f1ef3990a156c8dd`;
`RELEASE.json` `web`: build_id `flh-public-demo-fe6-BLOCKED`, api_base `/api`,
entry `/assets/index-DMcFZzPu.js`.
- **Local HTTPS stand-in:** delivery probe 17/17 (`evidence/item55-60/`); the
  JS is gzip and immutable; Speaking and records routes 404; writes 405; the
  identity matches.
- **Packaged gate:** `evidence/gate-fe6.txt`.
- **Private marker:** absent from all 197 public responses.

The rest of this file records handoff 1 (candidate fe2) and the owner commands,
which apply unchanged to fe6 or to a real-E5 CANDIDATE built from the same tree.

## What was tested

**Candidate:** `flh-public-demo-fe2-BLOCKED`.
- Tarball SHA-256: see `evidence/package-fe2.txt` and `packages.sha256`.
- `RELEASE.json` `web`: build_id `flh-public-demo-fe2-BLOCKED`, api_base `/api`,
  entry `/assets/index-C7m4bNbr.js`.
- **BLOCKED** means the vectors are mechanical. The public release, and AWS
  installation, still need a real-E5 artifact (`docs/PUBLIC_DEMO.md`, "Real-E5
  candidate (owner only)"). `flh-release install` refuses anything but
  CANDIDATE with `real_model: true`.

**Where it ran:** on this host, through the repository's own HTTPS edge.
- `deploy/aws/host/flh-public-https render` produced the nginx files; they run
  in `nginx:1.27-alpine` with a self-signed certificate for `staging.flh.test`.
- **The only changes** to the rendered files are container paths and ports:
  `evidence/item12/nginx-local.diff`.
- Commands: `tools/staging_local.sh start|swap|stop`.

| Check | Result | Evidence |
|---|---|---|
| Page identity: `<meta name="flh-build">`, `html[data-flh-build]` and `RELEASE.json` agree; API base `/api` (same origin); `https:` | PASS, desktop and phone | `evidence/item10-15/delivery-main-run{3,4,5}.txt` |
| Deep links (`#q=…`, `#concept=N`, `#concept=N&unit=M`) survive reload through the edge | PASS ×3 runs | same |
| `index.html` `no-cache`; hashed JS/CSS `public, max-age=31536000, immutable` (304 keeps it); a missing asset `404` with no caching header; POST `405`; an unknown path `404`; other SNI refused at the handshake | PASS | `evidence/item12/headers.txt` |
| Second visit loads JS and CSS from the browser cache (0 network loads) | PASS (certificate trusted by its SPKI hash: Chromium caches nothing from a site whose certificate errors were only ignored) | delivery runs |
| Startup placeholder while the bundle is slow; replaced on render | PASS | `startup-loading-390.png` |
| Bundle load fails: after 8 s the page says to check the connection and reload; a reload recovers | PASS | `startup-failed-390.png` |
| Demo description read fails (503): the reason is shown and Try again recovers | PASS | `api-failed-1280.png` |
| Tab open on fe2 while the server switches to fe3: the "newer version" notice appears when the tab is shown again; Reload runs fe3 and keeps `#q=il+faut` | PASS | `delivery-stale.txt`, `stale-notice-1280.png` |
| `validate-release.sh` | exit 3, BLOCKED (mechanical vectors), as designed | `item16-validate.txt` |
| `smoke_package.sh` | PACKAGE SMOKE PASSED | `item16-smoke-package-fe2.txt` |

## AWS staging: not launched

**Limits found** (recorded before any launch):
1. **Budget:** no monetary limit exists for new AWS resources in this run. The
   only approved cost is the continuous t4g.micro demo instance (FLH-085,
   about $10.42/month).
2. **Agent rules:** AGENTS.md says "Agents must not run `terraform
   plan/apply/destroy` or AWS commands; the owner runs `docs/AWS_DEMO.md`."
3. **Permissions, from the repository's policies:**
   - A second stack with another `name_prefix` (for example `flh-demo-stg`)
     is **denied**:
     - `iam:CreateRole` on `role/flh-demo-stg-host-*`, because statement
       `IamHostRoleOnlyWithBoundary` allows only `role/flh-demo-host-*`;
     - `s3:CreateBucket` on `flh-demo-stg-artifacts-*`, because statement
       `S3CreateArtifactBucket` allows only `flh-demo-artifacts-*`.
   - A second stack that keeps `name_prefix = "flh-demo"` in its own state
     appears permitted. Its names get unique suffixes, and the tag conditions
     need only `Project=flh` and `Component=public-demo`.
4. **Package:** the candidate is BLOCKED (mechanical vectors). `flh-release`
   installs only CANDIDATE packages with `real_model: true`.

**No AWS or Terraform command was run, and no AWS resource exists from this
lane.**

### Owner path A: existing private host, no new cost

Prerequisite: a real-E5 candidate packaged from this tree. `package.sh` now
writes the page identity itself.

```sh
# operator machine, deploy/aws/terraform of the existing stack
BUCKET=$(terraform output -raw artifact_bucket)
aws s3 cp /path/to/flh-public-demo-<label>.tar.gz "s3://$BUCKET/releases/"
aws ssm start-session --target "$(terraform output -raw instance_id)"
#   sudo /usr/local/sbin/flh-release install s3://$BUCKET/releases/flh-public-demo-<label>.tar.gz <sha256>
#   sudo /usr/local/sbin/flh-release status
#   curl -s http://127.0.0.1:18970/ | grep -o '<meta name="flh-build"[^>]*>'      # must name flh-public-demo-<label>
#   E=$(curl -s http://127.0.0.1:18970/ | grep -o '/assets/index-[^"]*\.js')
#   curl -sI "http://127.0.0.1:18970$E" | grep -i cache-control                     # public, max-age=31536000, immutable
#   exit
aws ssm start-session --target "$(terraform output -raw instance_id)" \
  --document-name AWS-StartPortForwardingSession --parameters portNumber=18970,localPortNumber=18970
# browser: http://127.0.0.1:18970/  then  /#q=il+faut  (reload)  /#concept=<id>  (reload)
# rollback: sudo /usr/local/sbin/flh-release rollback   (verified as in AWS_DEMO.md §6)
```

### Owner path B: separate staging stack (new cost while it runs)

- **Cost:** about $0.35/day for t4g.micro, EBS and S3 in us-east-1. Destroy it
  the same day.

```sh
cp -r deploy/aws/terraform ~/flh-staging-tf && cd ~/flh-staging-tf      # its own state
cat > terraform.tfvars <<'EOF'
aws_region             = "us-east-1"
architecture           = "arm64"
instance_type          = "t4g.micro"
name_prefix            = "flh-demo"            # the IAM patterns allow only flh-demo-host-* / flh-demo-artifacts-*
vpc_cidr               = "10.84.1.0/24"        # not the live stack's 10.84.0.0/24
termination_protection = false
extra_tags             = { Stage = "staging" } # filter on this tag; Task=FLH-084 is shared with the live stack
EOF
aws sts get-caller-identity
terraform init -lockfile=readonly && terraform plan -out staging.tfplan   # expect 19 to add, 0 to change or destroy
terraform apply staging.tfplan
# then path A's upload, install and checks against this stack's outputs
terraform destroy                                                         # same day
aws resourcegroupstaggingapi get-resources --tag-filters Key=Stage,Values=staging --query 'ResourceTagMappingList[].ResourceARN'
```

**If Terraform reports AccessDenied,** record the action and resource it
names. With `name_prefix = "flh-demo"`, none is expected from the policies as
written.

## Local stand-in commands (reproducible on any Linux host with Docker)

```bash
H=~/flh-handoff/demo-refresh-frontend-20261117T042813Z
bash $H/tools/staging_local.sh start $H/.work/packages/flh-public-demo-fe6-BLOCKED   # server 127.0.0.1:18621 + nginx TLS 127.0.0.1:18643
curl --resolve staging.flh.test:18643:127.0.0.1 --cacert $H/.work/staging/certs/fullchain.pem https://staging.flh.test:18643/readyz
bash $H/tools/staging_local.sh swap $H/.work/packages/flh-public-demo-fe5-BLOCKED    # rollback to the previous package (same port)
bash $H/tools/staging_local.sh stop                                                   # stops the server, removes the nginx container
```

**Rollback on AWS:** `sudo /usr/local/sbin/flh-release rollback` restores the
previous release and verifies it as in `docs/AWS_DEMO.md` §6. Run it again to
swap back.

**A tab open across the swap** shows "A newer version of this demo is on the
server" when it is shown again (verified fe2 → fe3), and never reloads by
itself.
