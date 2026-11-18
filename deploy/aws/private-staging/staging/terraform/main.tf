# PROPOSED isolated staging target for the private workbench (batch 5; RUNBOOK.md).
# Mirrors deploy/aws/terraform (the demo) where it can: dedicated VPC, one
# public subnet with no inbound rule (egress 443 only), free S3 gateway
# endpoint, Session Manager instead of SSH, IMDSv2, encrypted gp3, a host role
# under an administrator-made permissions boundary. Differences, because this
# host runs the full private service:
#   - a separate durable data volume (FLH_DATA_DIR and backups);
#   - Docker + Compose, so the exact image tested locally and the supported
#     scripts/daily/flh-daily.sh backup and restore run unchanged;
#   - S3 backups/ read+write and SSM parameters under /flh/staging/ for secrets;
#   - bounded runtime: the host powers off after max_runtime_hours and the
#     instance is then terminated (instance_initiated_shutdown_behavior).
# No Elastic IP, no inbound rule, no DNS record: the workbench has no
# authentication and is reached only through an SSM port forward.

locals {
  name      = "flh-stg"
  root_dir  = "/srv/flh-staging"
  param_dir = "/flh/staging"
  user_data = templatefile("${path.module}/cloud-config.yaml.tftpl", {
    root              = local.root_dir
    region            = var.aws_region
    bucket            = aws_s3_bucket.staging.bucket
    param_dir         = local.param_dir
    port              = var.app_port
    max_runtime_hours = var.max_runtime_hours
    compose_version   = var.compose_plugin_version
    compose_sha256    = var.compose_plugin_sha256
    render_env        = file("${path.module}/../host/flh-staging-env")
    bundle_tool       = file("${path.module}/../host/flh-staging-bundle")
    expire_unit       = file("${path.module}/../host/flh-staging-expire.service")
  })
}

data "aws_ec2_instance_type" "selected" {
  instance_type = var.instance_type
}

# --- Network ---------------------------------------------------------------------
resource "aws_vpc" "stg" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${local.name}-vpc" }
}

resource "aws_internet_gateway" "stg" {
  vpc_id = aws_vpc.stg.id
  tags   = { Name = "${local.name}-igw" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.stg.id
  cidr_block              = var.vpc_cidr
  map_public_ip_on_launch = false
  tags                    = { Name = "${local.name}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.stg.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.stg.id
  }
  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.stg.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.public.id]
  tags              = { Name = "${local.name}-s3" }
}

resource "aws_security_group" "host" {
  name        = "${local.name}-host"
  description = "FLH staging host: no inbound; outbound HTTPS only"
  vpc_id      = aws_vpc.stg.id
  tags        = { Name = "${local.name}-host" }
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.host.id
  description       = "HTTPS to SSM, S3, the OS repositories and the Compose plugin release"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

# --- Storage: one private bucket for releases/ and backups/ ---------------------
resource "aws_s3_bucket" "staging" {
  bucket_prefix = "${local.name}-"
  force_destroy = true # staging holds synthetic data only; destroy must leave nothing billable
}

resource "aws_s3_bucket_public_access_block" "staging" {
  bucket                  = aws_s3_bucket.staging.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "staging" {
  bucket = aws_s3_bucket.staging.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "staging" {
  bucket = aws_s3_bucket.staging.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "staging" {
  bucket = aws_s3_bucket.staging.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "staging" {
  bucket = aws_s3_bucket.staging.id
  rule {
    id     = "expire-staging-objects"
    status = "Enabled"
    filter {}
    expiration {
      days = 14
    }
    noncurrent_version_expiration {
      noncurrent_days = 1
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

data "aws_iam_policy_document" "bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    resources = [aws_s3_bucket.staging.arn, "${aws_s3_bucket.staging.arn}/*"]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "staging" {
  bucket = aws_s3_bucket.staging.id
  policy = data.aws_iam_policy_document.bucket.json
}

# --- IAM: Session Manager, own S3 prefixes, own parameters -----------------------
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_iam_policy" "host_boundary" {
  name = var.host_role_permissions_boundary_name
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "host" {
  name_prefix          = "${local.name}-host-"
  assume_role_policy   = data.aws_iam_policy_document.ec2_assume.json
  permissions_boundary = data.aws_iam_policy.host_boundary.arn
}

data "aws_iam_policy_document" "host" {
  statement {
    sid = "SessionManager"
    actions = [
      "ssm:UpdateInstanceInformation",
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "ReadReleases"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.staging.arn}/releases/*"]
  }
  statement {
    sid       = "ReadWriteBackups"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.staging.arn}/backups/*"]
  }
  statement {
    sid       = "ReadOwnParameters"
    actions   = ["ssm:GetParametersByPath", "ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.param_dir}", "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.param_dir}/*"]
  }
  statement {
    sid       = "DecryptOwnParametersOnly"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm", "arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:key/*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.aws_region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "host" {
  name   = "flh-stg-host"
  role   = aws_iam_role.host.id
  policy = data.aws_iam_policy_document.host.json
}

resource "aws_iam_instance_profile" "host" {
  name_prefix = "${local.name}-host-"
  role        = aws_iam_role.host.name
}

# --- Compute and data volume -----------------------------------------------------
resource "aws_instance" "host" {
  ami                                  = var.ami_id
  instance_type                        = var.instance_type
  subnet_id                            = aws_subnet.public.id
  vpc_security_group_ids               = [aws_security_group.host.id]
  iam_instance_profile                 = aws_iam_instance_profile.host.name
  associate_public_ip_address          = true
  monitoring                           = false
  instance_initiated_shutdown_behavior = "terminate"
  user_data_base64                     = base64gzip(local.user_data)
  user_data_replace_on_change          = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2 # Docker's bridge adds one hop; the containers never use the instance role
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 16
    encrypted             = true
    delete_on_termination = true
    tags                  = { Name = "${local.name}-root" }
  }

  credit_specification {
    cpu_credits = "standard"
  }

  tags = { Name = "${local.name}-host" }

  lifecycle {
    precondition {
      condition     = contains(data.aws_ec2_instance_type.selected.supported_architectures, "x86_64")
      error_message = "The tested image is linux/amd64: instance_type must support x86_64."
    }
  }
}

resource "aws_ebs_volume" "data" {
  availability_zone = aws_instance.host.availability_zone
  size              = var.data_volume_size_gib
  type              = "gp3"
  encrypted         = true
  tags              = { Name = "${local.name}-data" }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.host.id
}
