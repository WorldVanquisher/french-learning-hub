# IAM policies for the FLH demo stack (FLH-086; split in FLH-088)

**UNTESTED until used against AWS.** Every action, Resource ARN and condition
key was checked offline against AWS's published service reference, but no
request has been made with these policies. An `AccessDenied` names the missing
action or failed condition. Add only that, and record it.

| File | Created as | Attached to | Purpose |
|---|---|---|---|
| `flh-demo-host-boundary-policy.json` | `flh-demo-host-boundary` (exact name; Terraform looks it up) | nobody: it is the **permissions boundary** of the host role | ceiling on the host role: the minimal Session Manager actions and `s3:GetObject` on `flh-demo-artifacts-*/releases/*` |
| `flh-experiment-demo-deploy-policy.json` | `flh-demo-deploy` | `flh-experiment`, only while applying or destroying, **together with `flh-demo-deploy-ec2`** | the non-EC2 part of create, change and tear down: the `flh-demo-host-*` role (only with `flh-demo-host-boundary`), its instance profile and PassRole, and the artifact bucket. It holds both explicit Deny statements: no role-boundary removal or change, and no editing of the four policies named here |
| `flh-experiment-demo-deploy-ec2-policy.json` | `flh-demo-deploy-ec2` | `flh-experiment`, only while applying or destroying, **together with `flh-demo-deploy`** | the EC2 part, moved unchanged from `flh-demo-deploy` (FLH-088): VPC, subnet, route table, gateway, S3 endpoint, security group and rules, the reviewed instance shape and AMI, tags, and (FLH-088, untested) the optional Elastic IP and inbound 80/443 rules of `public_https.tf`. Allow statements only; the guarding Denies live in `flh-demo-deploy` |
| `flh-experiment-demo-operate-policy.json` | `flh-demo-operate` | `flh-experiment`, while operating | release upload, Session Manager shell and port forwarding, start/stop/reboot of the stack instance |

**Keep `ReadOnlyAccess` on the user.** Terraform's reads and the Session
Manager status calls rely on it.

**Use the exact names.** The deploy policy's denies and its boundary condition
reference these four names: `flh-demo-host-boundary`, `flh-demo-deploy`,
`flh-demo-deploy-ec2` and `flh-demo-operate`.

**Why two deploy policies (FLH-088):** a customer managed policy may hold at
most 6,144 characters, not counting whitespace. With the FLH-088 additions
the merged `flh-demo-deploy` reached 7,037, and the console rejected it. The
EC2 statements moved unchanged into `flh-demo-deploy-ec2`. With a 12-digit
account ID substituted, the two are 2,503 and 4,627 characters.
- **Attach and detach them together.** EC2 work needs the second policy.
- **Not standalone:** `flh-demo-deploy-ec2` carries no Deny of its own. Its
  guard is the `DenyEditingGuardPolicies` statement in `flh-demo-deploy`,
  which also names it.

**`flh086.tfplan` is obsolete.** It predates these corrections: it adopts the
default security group and creates the host role without a boundary. Do not
apply it. Generate and review a replacement plan after step 2.

## 1. Substitute the account ID (locally, never committed)

```sh
ACCOUNT=$(aws sts get-caller-identity --profile flh-plan --query Account --output text)
mkdir -p ~/flh-iam && for f in deploy/aws/iam/*-policy.json; do
  sed "s/__AWS_ACCOUNT_ID__/$ACCOUNT/g" "$f" > ~/flh-iam/"$(basename "$f")"
done
grep -c __AWS_ACCOUNT_ID__ ~/flh-iam/*.json   # must print 0 for every file
```

The boundary file contains no account ID; it is copied unchanged.

## 2. Create and attach (an IAM administrator, in the Console)

`flh-experiment` cannot do this, and must not be able to.

1. Go to **IAM → Policies → Create policy → JSON**. Paste
   `flh-demo-host-boundary-policy.json`, name it `flh-demo-host-boundary`, and
   choose **Create policy**. Do **not** attach it to any user.
2. Repeat with the filled deploy file, named `flh-demo-deploy`.
3. Repeat with the filled EC2 deploy file, named `flh-demo-deploy-ec2`.
4. Repeat with the filled operate file, named `flh-demo-operate`.
5. Go to **IAM → Users → flh-experiment → Add permissions → Attach policies
   directly**. Select `flh-demo-deploy`, `flh-demo-deploy-ec2` and
   `flh-demo-operate`, then choose **Add permissions**.
6. Confirm the user lists `ReadOnlyAccess`, `flh-demo-deploy`,
   `flh-demo-deploy-ec2` and `flh-demo-operate`, and nothing else changed.

## 2b. FLH-088 update of an existing account (an IAM administrator)

This is for the account where FLH-086's `flh-demo-host-boundary`,
`flh-demo-deploy` and `flh-demo-operate` already exist. **Do not recreate the
boundary or the operate policy**: neither changes.

1. **Fill both deploy files:** run §1 again, then confirm that
   `~/flh-iam/flh-experiment-demo-deploy-ec2-policy.json` exists.
2. **Create the EC2 policy first:** **IAM → Policies → Create policy →
   JSON**. Paste `flh-experiment-demo-deploy-ec2-policy.json`, name it
   **`flh-demo-deploy-ec2`**, and create it. Attach it to nobody yet.
3. **Replace the content of `flh-demo-deploy`:** open **IAM → Policies →
   flh-demo-deploy → Edit → JSON**. Paste the filled
   `flh-experiment-demo-deploy-policy.json` (now non-EC2 only) and save it as
   the new default version.
   - IAM keeps at most five versions. If the console says so, delete the
     oldest non-default version first.
   - The deploy policy is the old FLH-086 version until this step.
4. **Attach while applying:** attach `flh-demo-deploy` and
   `flh-demo-deploy-ec2` to `flh-experiment`.
5. **Detach after apply:** detach both once the apply (or a later destroy)
   has finished. `flh-demo-operate` stays for daily operation.

## 3. Replacement plan, review, apply

```sh
cd deploy/aws/terraform
AWS_PROFILE=flh-plan ~/tools/terraform/1.16.6/terraform plan \
  -var aws_region=us-east-1 -var architecture=arm64 -var instance_type=t4g.micro \
  -out flh086r2.tfplan
# review: 19 creates, no aws_default_security_group,
# aws_iam_role.host.permissions_boundary = the flh-demo-host-boundary ARN,
# same AMI (or update the AMI ARN in flh-demo-deploy deliberately)
AWS_PROFILE=flh-plan ~/tools/terraform/1.16.6/terraform apply flh086r2.tfplan
```

**Saved-plan behaviour:** a saved plan applies without a confirmation prompt,
and billing starts. If Terraform reports the plan as stale, re-plan and
re-review; never force it.

**If the plan resolves a different AMI** than `ami-04048e843b318bc37`, the
deploy policy's launch statement (now in `flh-demo-deploy-ec2`) denies it.
Pin the reviewed AMI with `-var ami_id=...`, or update the ARN in
`flh-demo-deploy-ec2` deliberately.

## 4. After apply

- **Next steps:** continue with `docs/AWS_DEMO.md` §4 to §7. That includes the
  optional administrator step that strips the default security group's rules,
  which Terraform no longer manages.
- **Detach `flh-demo-deploy` and `flh-demo-deploy-ec2`** once the stack is up.
  Reattach both only to change or destroy the stack. `flh-demo-operate` is
  enough for daily operation.
