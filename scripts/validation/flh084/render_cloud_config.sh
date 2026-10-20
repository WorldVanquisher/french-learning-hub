#!/bin/bash
# FLH-085: render the instance cloud-init document offline, exactly as
# deploy/aws/terraform/main.tf builds it (local.cloud_config_vars and
# host/cloud-config.yaml.tftpl), with only the not-yet-known bucket name
# replaced by a sample value. Also writes Terraform's own yamldecode() of it.
#
#   TERRAFORM=/path/to/terraform scripts/validation/flh084/render_cloud_config.sh OUT_DIR [arm64|x86_64] [REGION]
#
# Needs `terraform init -backend=false` to have been run in deploy/aws/terraform
# (console loads the provider schema). Runs `terraform console` only: no plan,
# no state, no AWS credentials (configuration files pointed at /dev/null) and,
# where `unshare -rn` works, no network at all.
# Output: OUT_DIR/user-data-<arch>.yaml (the cloud-config text) and
#         OUT_DIR/user-data-<arch>.decoded.json (yamldecode result as JSON).
set -euo pipefail
OUT=${1:?usage: render_cloud_config.sh OUT_DIR [arch] [region]}
ARCH=${2:-arm64}
REGION=${3:-us-east-1}
TF=${TERRAFORM:-terraform}
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
DIR="$REPO/deploy/aws/terraform"
case "$ARCH" in arm64) TYPE=t4g.micro ;; x86_64) TYPE=t3.micro ;; *) echo "arch must be arm64 or x86_64" >&2; exit 2 ;; esac
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
[ -d "$DIR/.terraform" ] || { echo "run terraform init -backend=false in $DIR first" >&2; exit 2; }

EXPR_VARS='merge(local.cloud_config_vars, { bucket = "flh-demo-artifacts-sample" })'
EXPR_DOC="templatefile(\"\${local.host_dir}/cloud-config.yaml.tftpl\", $EXPR_VARS)"
ISOLATE=()
if unshare -rn true 2>/dev/null; then ISOLATE=(unshare -rn); fi

console() { # expression -> stdout (base64 string literal)
  (cd "$DIR" && printf '%s\n' "$1" | env -i PATH="$PATH" HOME="$HOME" TMPDIR="${TMPDIR:-/tmp}" \
    CHECKPOINT_DISABLE=1 AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true \
    "${ISOLATE[@]}" "$TF" console -var "aws_region=$REGION" -var "architecture=$ARCH" -var "instance_type=$TYPE")
}
decode() { python3 -I -c 'import base64,sys; s=sys.stdin.read().strip(); assert s[0]==s[-1]=="\""; sys.stdout.buffer.write(base64.b64decode(s[1:-1]))'; }

console "base64encode($EXPR_DOC)" | decode > "$OUT/user-data-$ARCH.yaml"
console "base64encode(jsonencode(yamldecode($EXPR_DOC)))" | decode > "$OUT/user-data-$ARCH.decoded.json"
echo "isolation: ${ISOLATE[*]:-none (unshare unavailable)}"
echo "rendered:  $OUT/user-data-$ARCH.yaml ($(wc -c < "$OUT/user-data-$ARCH.yaml") bytes)"
echo "decoded:   $OUT/user-data-$ARCH.decoded.json"
