#!/usr/bin/env python3
"""FLH-084 static checks of deploy/aws without Terraform, AWS or network.

Text-level policy checks of the Terraform configuration, the rendered systemd
unit and the cloud-init document. They do not replace `terraform validate`
(not run: Terraform is not installed and `init` would download providers).

    python3 -B scripts/validation/flh084/static_checks.py
"""
import gzip
import json
import os
import re
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
AWS = os.path.join(REPO, "deploy", "aws")
TF = os.path.join(AWS, "terraform")
HOST = os.path.join(AWS, "host")
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def strip_comments(text):
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


tf_files = sorted(f for f in os.listdir(TF) if f.endswith(".tf"))
tf = {f: read(os.path.join(TF, f)) for f in tf_files}
code = "\n".join(strip_comments(t) for t in tf.values())
check("terraform files present", tf_files == ["main.tf", "outputs.tf", "public_https.tf", "storage.tf", "variables.tf", "versions.tf"], tf_files)
# FLH-088: the optional public entry point lives only in public_https.tf; the
# FLH-084 base stack (every other file) keeps its private-only guarantees.
base = "\n".join(strip_comments(t) for f, t in tf.items() if f != "public_https.tf")
pub = strip_comments(tf["public_https.tf"])

# Brace balance per file (catches truncated blocks; not a parser).
for f, t in tf.items():
    body = re.sub(r'"(?:\\.|[^"\\])*"', '""', strip_comments(t))
    check(f"{f}: balanced braces/brackets/parens",
          body.count("{") == body.count("}") and body.count("[") == body.count("]") and body.count("(") == body.count(")"))

# Variables: every reference declared, every declaration used.
declared = set(re.findall(r'^variable "([a-z0-9_]+)"', tf["variables.tf"], re.M))
referenced = set(re.findall(r"\bvar\.([a-z0-9_]+)", code))
check("every var.* reference is declared", referenced <= declared, sorted(referenced - declared))
check("every declared variable is used", declared <= referenced, sorted(declared - referenced))
for v in ("aws_region", "architecture", "instance_type"):
    block = re.search(r'variable "%s" \{(.*?)\n\}' % v, tf["variables.tf"], re.S).group(1)
    check(f"variable {v} has no default (owner choice)", not re.search(r"^\s*default\s*=", block, re.M))
local_names = set(n for t in tf.values() for block in re.findall(r"^locals \{(.*?)\n\}", t, re.S | re.M)
                  for n in re.findall(r"^\s{2}([a-z_]+)\s*=", block, re.M))
check("every local.* reference is defined", set(re.findall(r"\blocal\.([a-z_]+)", code)) <= local_names)

# Network exposure.
check("base stack: no ingress rule resources", not re.search(r"aws_vpc_security_group_ingress_rule|aws_security_group_rule|\bingress\s*\{", base))
egress = re.findall(r'resource "aws_vpc_security_group_egress_rule" "[a-z_]+" \{(.*?)\n\}', code, re.S)
check("exactly one egress rule", len(egress) == 1)
check("egress is TCP 443 only", egress and all(re.search(r'from_port\s*=\s*443', e) and re.search(r'to_port\s*=\s*443', e)
                                                and '"tcp"' in e for e in egress))
check("no port 22 / application port in security rules", not re.search(r"(from|to)_port\s*=\s*(22|18970|8080)\b", code))
check("base stack: no port 80 rule", not re.search(r"(from|to)_port\s*=\s*80\b", base))
check("base stack: 0.0.0.0/0 only in the egress rule and the IGW route", base.count('"0.0.0.0/0"') == 2)
check("subnet does not auto-assign public IPs (set per instance)", "map_public_ip_on_launch = false" in code)
check("no load balancer / NAT / RDS / ECS / EKS / interface endpoints; no EIP in the base stack",
      not re.search(r'"aws_(lb|alb|elb|nat_gateway|db_instance|rds_cluster|ecs_|eks_)', code)
      and not re.search(r'"aws_eip', base)
      and 'vpc_endpoint_type = "Interface"' not in code)
check("no Route 53 or DNS records", "aws_route53" not in code)

# FLH-088 public entry point: exactly an EIP, its association and inbound 80/443.
pub_resources = re.findall(r'^resource "([a-z0-9_]+)" "([a-z_]+)"', pub, re.M)
check("public_https.tf: only EIP, EIP association and two ingress rules", sorted(pub_resources) == [
    ("aws_eip", "public"), ("aws_eip_association", "public"),
    ("aws_vpc_security_group_ingress_rule", "http"), ("aws_vpc_security_group_ingress_rule", "https")], pub_resources)
pub_blocks = re.findall(r'^resource "[a-z0-9_]+" "[a-z_]+" \{(.*?)\n\}', pub, re.M | re.S)
check("public_https.tf: every resource gated by public_https_enabled", len(pub_blocks) == 4
      and all(re.search(r"^\s*count\s*=\s*local\.public_https$", b, re.M) for b in pub_blocks)
      and "public_https = var.public_https_enabled ? 1 : 0" in pub)
ingress = re.findall(r'resource "aws_vpc_security_group_ingress_rule" "[a-z_]+" \{(.*?)\n\}', pub, re.S)
check("public ingress: TCP 80 and 443 only, IPv4, to the host group",
      sorted((re.search(r"from_port\s*=\s*(\d+)", i).group(1), re.search(r"to_port\s*=\s*(\d+)", i).group(1)) for i in ingress) == [("443", "443"), ("80", "80")]
      and all('"tcp"' in i and "aws_security_group.host.id" in i and "cidr_ipv6" not in i for i in ingress))
check("public_https.tf: does not touch the instance or its user data",
      not re.search(r'resource "aws_instance"|user_data|aws_security_group" "', pub))
pv = re.search(r'variable "public_https_enabled" \{(.*?)\n\}', tf["variables.tf"], re.S)
check("public_https_enabled is a bool defaulting to false", pv and re.search(r"type\s*=\s*bool", pv.group(1)) and re.search(r"default\s*=\s*false", pv.group(1)))
check("default security group not adopted (needs account-wide revoke; FLH-086)", "aws_default_security_group" not in code)
check("host role requires the administrator-managed permissions boundary",
      "permissions_boundary = data.aws_iam_policy.host_boundary.arn" in code and 'data "aws_iam_policy" "host_boundary"' in code)

# Instance.
check("IMDSv2 required", 'http_tokens                 = "required"' in code)
check("root volume encrypted gp3", "encrypted             = true" in code and 'volume_type           = "gp3"' in code)
check("root delete_on_termination explicit", "delete_on_termination = var.root_volume_delete_on_termination" in code)
check("user data replaced on change and gzipped", "user_data_replace_on_change = true" in code and "base64gzip(local.user_data)" in code)
check("no key pair (no SSH)", "key_name" not in code)
check("detailed monitoring off", "monitoring                  = false" in code)
check("arch precondition", "supported_architectures" in code)
check("AMI lookup uses non-sensitive insecure_value", "insecure_value" in code)

# IAM.
actions = set(re.findall(r'"((?:ssm|ssmmessages|ec2messages|s3|kms|logs|iam|ec2):[A-Za-z*]+)"',
                         re.search(r'data "aws_iam_policy_document" "host" \{(.*?)\n\}', code, re.S).group(1)))
check("instance policy is the documented minimal Session Manager set + s3:GetObject", actions == {
    "ssm:UpdateInstanceInformation", "ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel",
    "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel", "s3:GetObject"}, sorted(actions))
check("GetObject scoped to releases/*", '"${aws_s3_bucket.artifacts.arn}/releases/*"' in code)
check("no managed SSM policy attachment / wildcard actions",
      "AmazonSSMManagedInstanceCore" not in code and not re.search(r'actions\s*=\s*\["\*"\]', code))

# Bucket.
for flag in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
    check(f"bucket {flag}", re.search(flag + r"\s*=\s*true", code))
check("bucket SSE, versioning, owner-enforced, TLS-only",
      '"AES256"' in code and 'status = "Enabled"' in code and "BucketOwnerEnforced" in code and "aws:SecureTransport" in code)
fd = re.search(r'variable "artifact_bucket_force_destroy" \{(.*?)\n\}', tf["variables.tf"], re.S).group(1)
check("force_destroy defaults to false", re.search(r"default\s*=\s*false", fd))

# No secrets, accounts, domains or presigned URLs anywhere under deploy/aws.
forbidden = [r"AKIA[0-9A-Z]{16}", r"aws_secret_access_key", r"X-Amz-(Signature|Credential)", r"presign",
             r"\b\d{12}\b", r"vanquisher", r"\b[a-z0-9-]+\.(world|org|net|io)\b", r"BEGIN [A-Z ]*PRIVATE KEY",
             r"secret_key|access_key\s*=|password\s*=|token\s*=\s*\""]
for root, dirs, files in os.walk(AWS):
    dirs[:] = [d for d in dirs if d != ".terraform"]  # provider binaries from terraform init
    for f in files:
        if f in (".terraform.lock.hcl", "terraform.tfvars") or f.endswith((".tfstate", ".tfplan")):
            continue
        text = read(os.path.join(root, f))
        rel = os.path.relpath(os.path.join(root, f), REPO)
        for pat in forbidden:
            m = re.search(pat, text, re.I)
            check(f"{rel}: no /{pat}/", not m, m.group(0) if m else "")

# Rendered unit (templatefile with the same variables main.tf passes).
tpl = read(os.path.join(HOST, "flh-public-demo.service.tftpl"))
tpl_vars = set(re.findall(r"\$\{([a-z_]+)\}", tpl))
call = re.search(r'templatefile\("\$\{local\.host_dir\}/flh-public-demo\.service\.tftpl", \{(.*?)\}\)', tf["main.tf"], re.S).group(1)
check("unit template variables == templatefile arguments", tpl_vars == set(re.findall(r"^\s*([a-z_]+)\s*=", call, re.M)), sorted(tpl_vars))
for arch in ("arm64", "amd64"):
    unit = tpl.replace("${root}", "/srv/flh-demo").replace("${arch}", arch).replace("${port}", "18970")
    env = dict(re.findall(r"^Environment=([A-Z_]+)=(.*)$", unit, re.M))
    check(f"unit[{arch}]: loopback, providers disabled, empty allowed hosts", env == {
        "LISTEN_HOST": "127.0.0.1", "PORT": "18970", "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled",
        "EMBEDDING_PROVIDER": "disabled", "SEMANTIC_SEARCH": "disabled", "HTTP_ALLOWED_HOSTS": ""}, env)
    check(f"unit[{arch}]: ExecStart uses bin/linux-{arch} and the public-demo artifact",
          f"ExecStart=/srv/flh-demo/current/bin/linux-{arch}/flh-server -public-demo-artifact /srv/flh-demo/current/artifact -web-dir /srv/flh-demo/current/web" in unit)
    for d in ("User=flh-demo", "NoNewPrivileges=true", "ProtectSystem=strict", "ReadOnlyPaths=/srv/flh-demo",
              "IPAddressDeny=any", "IPAddressAllow=localhost", "MemoryMax=256M", "CapabilityBoundingSet=",
              "InaccessiblePaths=-/srv/flh-demo/state"):
        check(f"unit[{arch}]: {d}", re.search("^" + re.escape(d) + "$", unit, re.M))
    check(f"unit[{arch}]: no unrendered placeholders", "${" not in unit)

# cloud-init template wiring: every variable main.tf passes is used by the template.
cc_tpl = read(os.path.join(HOST, "cloud-config.yaml.tftpl"))
cc_vars = set(re.findall(r"^\s{4}([a-z_]+)\s+=", re.search(r"cloud_config_vars = \{(.*?)\n  \}", tf["main.tf"], re.S).group(1), re.M))
check("cloud-config template starts with #cloud-config", cc_tpl.startswith("#cloud-config\n"))
check("cloud_config_vars are exactly the template's inputs", cc_vars == {"release_tool", "unit", "journald", "root", "port", "arch", "region", "bucket"}
      and all(re.search(r"\b%s\b" % v, cc_tpl) for v in cc_vars), sorted(cc_vars))
check("user_data rendered from the template", 'templatefile("${local.host_dir}/cloud-config.yaml.tftpl", local.cloud_config_vars)' in tf["main.tf"])

# cloud-init document size, as main.tf builds it (JSON is valid YAML; yamlencode output is similar in size).
doc = "#cloud-config\n" + json.dumps({"write_files": [
    {"path": "/usr/local/sbin/flh-release", "permissions": "0755", "owner": "root:root", "content": read(os.path.join(HOST, "flh-release"))},
    {"path": "/etc/systemd/system/flh-public-demo.service", "permissions": "0644", "owner": "root:root", "content": tpl},
    {"path": "/etc/systemd/journald.conf.d/50-flh-demo.conf", "permissions": "0644", "owner": "root:root", "content": read(os.path.join(HOST, "journald-flh.conf"))},
    {"path": "/etc/flh-demo/deploy.env", "permissions": "0644", "owner": "root:root", "content": "ROOT=/srv/flh-demo\nPORT=18970\nARCH=arm64\nREGION=ap-southeast-1\nARTIFACT_BUCKET=" + "x" * 63 + "\n"},
], "runcmd": [["useradd", "--system", "flh-demo"]] * 5})
raw, gz = len(doc.encode()), len(gzip.compress(doc.encode()))
check("user data: gzipped document well under the 16384-byte limit", gz < 8192, f"raw {raw} B, gzip {gz} B")
check("user data: raw size needs gzip (documents why it is compressed)", raw > 8000, f"raw {raw} B")
check("user data carries no non-loopback URL or credential",
      not re.search(r"https?://(?!127\.0\.0\.1:)|AKIA|X-Amz", doc))

# Host scripts.
for f in ("flh-release", "flh-public-https"):
    p = subprocess.run(["bash", "-n", os.path.join(HOST, f)], capture_output=True, text=True)
    check(f"bash -n {f}", p.returncode == 0, p.stderr.strip())
    check(f"{f} is executable", os.access(os.path.join(HOST, f), os.X_OK))
check("flh-public-https is not part of the user data (changing it must not replace the instance)",
      "flh-public-https" not in cc_tpl and "flh-public-https" not in tf["main.tf"])

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail not in ("", None) and not ok or (ok and isinstance(detail, str) and detail.startswith("raw")) else ""))
print(f"static checks: {len(results) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
