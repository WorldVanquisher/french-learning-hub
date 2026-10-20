locals {
  package_arch = var.architecture == "arm64" ? "arm64" : "amd64"
  root_dir     = "/srv/flh-demo"
  ami_id       = var.ami_id != null ? var.ami_id : data.aws_ssm_parameter.al2023[0].insecure_value
  name         = var.name_prefix

  host_dir = "${path.module}/../host"
  unit = templatefile("${local.host_dir}/flh-public-demo.service.tftpl", {
    root = local.root_dir
    arch = local.package_arch
    port = var.app_port
  })

  # cloud-init (gzip-compressed, see user_data_base64): create the service
  # account and directories, install the host tools, journald limits, unit and
  # non-secret configuration. It downloads and starts nothing: a release is
  # installed later by the operator over SSM. Rendered from a template so the
  # same document can be produced offline with a sample bucket name
  # (scripts/validation/flh084/render_cloud_config.sh).
  cloud_config_vars = {
    release_tool = file("${local.host_dir}/flh-release")
    unit         = local.unit
    journald     = file("${local.host_dir}/journald-flh.conf")
    root         = local.root_dir
    port         = var.app_port
    arch         = local.package_arch
    region       = var.aws_region
    bucket       = aws_s3_bucket.artifacts.bucket
  }
  user_data = templatefile("${local.host_dir}/cloud-config.yaml.tftpl", local.cloud_config_vars)
}

data "aws_ssm_parameter" "al2023" {
  count = var.ami_id == null ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-${var.architecture}"
}

data "aws_ec2_instance_type" "selected" {
  instance_type = var.instance_type
}

# --- Network: one public subnet, no inbound path -------------------------------
# The instance needs outbound HTTPS only (SSM endpoints, S3, OS repositories).
# One auto-assigned public IPv4 address is cheaper than the three interface VPC
# endpoints (ssm, ssmmessages, ec2messages) or a NAT gateway a private subnet
# would need. The security group admits nothing inbound.

resource "aws_vpc" "demo" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${local.name}-vpc" }
}

resource "aws_internet_gateway" "demo" {
  vpc_id = aws_vpc.demo.id
  tags   = { Name = "${local.name}-igw" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.demo.id
  cidr_block              = var.vpc_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = false
  tags                    = { Name = "${local.name}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.demo.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.demo.id
  }
  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Free S3 gateway endpoint: artifact downloads stay on the AWS network and the
# bucket policy can require it.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.demo.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.public.id]
  tags              = { Name = "${local.name}-s3" }
}

# Strip the VPC default security group of its default rules.
resource "aws_default_security_group" "demo" {
  vpc_id = aws_vpc.demo.id
  tags   = { Name = "${local.name}-default-unused" }
}

resource "aws_security_group" "host" {
  name        = "${local.name}-host"
  description = "FLH demo host: no inbound; outbound HTTPS only"
  vpc_id      = aws_vpc.demo.id
  tags        = { Name = "${local.name}-host" }
}

# No aws_vpc_security_group_ingress_rule exists for this group, deliberately:
# no SSH, no application port, no HTTP/HTTPS during this phase.
resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.host.id
  description       = "HTTPS to SSM, S3 and OS package endpoints"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

# --- IAM: Session Manager only, plus read of release objects -------------------

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "host" {
  name_prefix        = "${local.name}-host-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

# AWS's documented minimal Session Manager instance policy (no session logging,
# no KMS session encryption). Deliberately not AmazonSSMManagedInstanceCore,
# which also grants ssm:GetParameter(s) on every parameter in the account and
# Run Command/association access this deployment does not use.
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
    sid       = "ReadReleaseObjects"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.artifacts.arn}/releases/*"]
  }
}

resource "aws_iam_role_policy" "host" {
  name   = "flh-demo-host"
  role   = aws_iam_role.host.id
  policy = data.aws_iam_policy_document.host.json
}

resource "aws_iam_instance_profile" "host" {
  name_prefix = "${local.name}-host-"
  role        = aws_iam_role.host.name
}

# --- Instance -------------------------------------------------------------------

resource "aws_instance" "host" {
  ami                         = local.ami_id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.host.id]
  iam_instance_profile        = aws_iam_instance_profile.host.name
  associate_public_ip_address = true
  monitoring                  = false
  disable_api_termination     = var.termination_protection
  # Gzipped: the raw document exceeds EC2's 16 KB user-data limit uncompressed.
  user_data_base64            = base64gzip(local.user_data)
  user_data_replace_on_change = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size_gib
    encrypted             = true
    delete_on_termination = var.root_volume_delete_on_termination
    tags                  = { Name = "${local.name}-root" }
  }

  dynamic "credit_specification" {
    for_each = startswith(var.instance_type, "t") ? [1] : []
    content {
      cpu_credits = var.cpu_credits
    }
  }

  tags = { Name = "${local.name}-host" }

  lifecycle {
    precondition {
      condition     = contains(data.aws_ec2_instance_type.selected.supported_architectures, var.architecture)
      error_message = "instance_type does not support the chosen architecture."
    }
  }
}
