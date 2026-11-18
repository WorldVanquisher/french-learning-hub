variable "aws_region" {
  description = "Region. The demo runs in us-east-1 (FLH-087); staging uses the same unless the owner decides otherwise."
  type        = string
  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.aws_region))
    error_message = "aws_region must look like us-east-1."
  }
}

variable "run_id" {
  description = "Rehearsal run identifier, recorded as the Run tag (e.g. 20261117T042813Z)."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{8}T[0-9]{6}Z$", var.run_id))
    error_message = "run_id must look like 20261117T042813Z."
  }
}

variable "expires_at" {
  description = "UTC time after which the stack must be destroyed (ExpiresAt tag, e.g. 2026-11-18T12:00:00Z). The host also powers itself off after max_runtime_hours."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.expires_at))
    error_message = "expires_at must be an RFC 3339 UTC time."
  }
}

variable "ami_id" {
  description = "Reviewed Amazon Linux 2023 x86_64 AMI (resolve once: aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64). Pinned so the plan cannot drift and the deploy policy can name it."
  type        = string
  validation {
    condition     = can(regex("^ami-[0-9a-f]{8,17}$", var.ami_id))
    error_message = "ami_id must be an AMI ID."
  }
}

variable "instance_type" {
  description = "x86_64, so the image tested locally runs byte for byte. t3.small (2 vCPU, 2 GiB) fits the Go server, SQLite and Docker."
  type        = string
  default     = "t3.small"
}

variable "max_runtime_hours" {
  description = "The host powers off (and, with shutdown behaviour terminate, is terminated) this many hours after boot."
  type        = number
  default     = 4
  validation {
    condition     = var.max_runtime_hours >= 1 && var.max_runtime_hours <= 12
    error_message = "max_runtime_hours must be between 1 and 12."
  }
}

variable "data_volume_size_gib" {
  description = "Durable data volume for FLH_DATA_DIR and backups (staging: synthetic data only)."
  type        = number
  default     = 8
}

variable "vpc_cidr" {
  description = "Dedicated staging VPC; must not overlap the demo VPC (10.84.0.0/24 by default). One public subnet uses the whole range."
  type        = string
  default     = "10.85.0.0/24"
}

variable "app_port" {
  description = "Loopback port of the workbench on the host (reached only through an SSM port forward)."
  type        = number
  default     = 8080
}

variable "host_role_permissions_boundary_name" {
  description = "Administrator-created boundary (iam/flh-stg-host-boundary-policy.json)."
  type        = string
  default     = "flh-stg-host-boundary"
}

variable "compose_plugin_version" {
  description = "Docker Compose plugin release installed on the host."
  type        = string
  default     = "v2.29.7"
}

variable "compose_plugin_sha256" {
  description = "SHA-256 of docker-compose-linux-x86_64 for compose_plugin_version, from the release's checksums file. Verified on the host before install; a mismatch stops cloud-init."
  type        = string
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.compose_plugin_sha256))
    error_message = "compose_plugin_sha256 must be 64 hex characters."
  }
}
