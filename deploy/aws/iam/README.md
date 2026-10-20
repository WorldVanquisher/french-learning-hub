# IAM policies for the FLH demo stack (FLH-086)

**UNTESTED until used against AWS.** Every action, Resource ARN and condition
key was checked offline against AWS's published service reference, but no
request has been made with these policies. An `AccessDenied` names the missing
action or failed condition. Add only that, and record it.

| File | Created as | Attached to | Purpose |
|---|---|---|---|
| `flh-demo-host-boundary-policy.json` | `flh-demo-host-boundary` (exact name; Terraform looks it up) | nobody: it is the **permissions boundary** of the host role | ceiling on the host role: the minimal Session Manager actions and `s3:GetObject` on `flh-demo-artifacts-*/releases/*` |
| `flh-experiment-demo-deploy-policy.json` | `flh-demo-deploy` | `flh-experiment`, only while applying or destroying | create, change and tear down the 19-resource stack. It may create, change or delete `flh-demo-host-*` roles only when they carry `flh-demo-host-boundary`, and it explicitly denies removing or changing any role boundary or editing these policies |
| `flh-experiment-demo-operate-policy.json` | `flh-demo-operate` | `flh-experiment`, while operating | release upload, Session Manager shell and port forwarding, start/stop/reboot of the stack instance |

**Keep `ReadOnlyAccess` on the user.** Terraform's reads and the Session
Manager status calls rely on it.

**Use the exact names.** The deploy policy's denies and its boundary condition
reference these three names.

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
3. Repeat with the filled operate file, named `flh-demo-operate`.
4. Go to **IAM → Users → flh-experiment → Add permissions → Attach policies
   directly**. Select `flh-demo-deploy` and `flh-demo-operate`, then choose
   **Add permissions**.
5. Confirm the user lists `ReadOnlyAccess`, `flh-demo-deploy` and
   `flh-demo-operate`, and nothing else changed.

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
deploy policy's launch statement denies it. Pin the reviewed AMI with
`-var ami_id=...`, or update the ARN in `flh-demo-deploy` deliberately.

## 4. After apply

- **Next steps:** continue with `docs/AWS_DEMO.md` §4 to §7. That includes the
  optional administrator step that strips the default security group's rules,
  which Terraform no longer manages.
- **Detach `flh-demo-deploy`** once the stack is up. Reattach it only to change
  or destroy the stack. `flh-demo-operate` is enough for daily operation.
