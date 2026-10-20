variable "aws_region" {
  description = "AWS region for every resource, e.g. us-east-1 or ap-northeast-1. Owner choice; no default."
  type        = string
  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.aws_region))
    error_message = "aws_region must look like a region code such as us-east-1."
  }
}

variable "architecture" {
  description = "CPU architecture: arm64 (Graviton, e.g. t4g) or x86_64 (e.g. t3). The release package carries both server binaries."
  type        = string
  validation {
    condition     = contains(["arm64", "x86_64"], var.architecture)
    error_message = "architecture must be arm64 or x86_64."
  }
}

variable "instance_type" {
  description = "EC2 instance type matching architecture. Suggested: t4g.micro (arm64) or t3.micro (x86_64); t4g.nano/t3.nano (0.5 GiB) also fit the measured ~28 MB peak."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*\\.[a-z0-9]+$", var.instance_type))
    error_message = "instance_type must look like t4g.micro."
  }
}

variable "ami_id" {
  description = "Pinned AMI ID. null resolves the current Amazon Linux 2023 AMI for the architecture from the public SSM parameter at plan time; pinning the resolved ID afterwards keeps later plans from replacing the instance when AWS publishes a new AMI."
  type        = string
  default     = null
  validation {
    condition     = var.ami_id == null || can(regex("^ami-[0-9a-f]{8,17}$", var.ami_id))
    error_message = "ami_id must be null or an ami-... ID."
  }
}

variable "name_prefix" {
  description = "Prefix for resource names and the Name tag."
  type        = string
  default     = "flh-demo"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.name_prefix))
    error_message = "name_prefix must be 2-21 lowercase letters, digits or hyphens."
  }
}

variable "vpc_cidr" {
  description = "CIDR of the dedicated VPC. The single public subnet uses the whole range."
  type        = string
  default     = "10.84.0.0/24"
  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0)) && tonumber(split("/", var.vpc_cidr)[1]) >= 16 && tonumber(split("/", var.vpc_cidr)[1]) <= 28
    error_message = "vpc_cidr must be an IPv4 CIDR between /16 and /28."
  }
}

variable "availability_zone" {
  description = "Availability zone for the subnet, e.g. us-east-1a. null lets AWS choose; set it if the chosen instance type is not offered in the zone AWS picks."
  type        = string
  default     = null
}

variable "root_volume_size_gib" {
  description = "Encrypted gp3 root volume size in GiB. Amazon Linux 2023 needs at least 8; a release package is about 70 MB unpacked per kept release."
  type        = number
  default     = 8
  validation {
    condition     = var.root_volume_size_gib >= 8 && var.root_volume_size_gib <= 30
    error_message = "root_volume_size_gib must be between 8 and 30."
  }
}

variable "root_volume_delete_on_termination" {
  description = "Delete the root volume when the instance is terminated. true (default): the host holds no data that is not reproducible from the artifact bucket, so teardown leaves no billable volume behind."
  type        = bool
  default     = true
}

variable "cpu_credits" {
  description = "Burstable CPU credit mode. standard (default) never bills surplus credits; unlimited can add per-vCPU-hour charges."
  type        = string
  default     = "standard"
  validation {
    condition     = contains(["standard", "unlimited"], var.cpu_credits)
    error_message = "cpu_credits must be standard or unlimited."
  }
}

variable "termination_protection" {
  description = "EC2 API termination protection. Must be false before terraform destroy can remove the instance."
  type        = bool
  default     = false
}

variable "artifact_bucket_name" {
  description = "Exact name for the private artifact bucket. null (default) lets Terraform generate a unique name from name_prefix."
  type        = string
  default     = null
  validation {
    condition     = var.artifact_bucket_name == null || can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.artifact_bucket_name))
    error_message = "artifact_bucket_name must be null or a DNS-compatible bucket name without dots."
  }
}

variable "artifact_bucket_force_destroy" {
  description = "Allow terraform destroy to delete a non-empty artifact bucket (all object versions). false (default) makes teardown fail until the bucket is emptied deliberately."
  type        = bool
  default     = false
}

variable "artifact_noncurrent_version_days" {
  description = "Days after which non-current object versions in the artifact bucket expire."
  type        = number
  default     = 30
  validation {
    condition     = var.artifact_noncurrent_version_days >= 1
    error_message = "artifact_noncurrent_version_days must be at least 1."
  }
}

variable "app_port" {
  description = "Loopback port of the demo server on the instance (never opened in the security group)."
  type        = number
  default     = 18970
  validation {
    condition     = var.app_port >= 1024 && var.app_port <= 65535
    error_message = "app_port must be an unprivileged port."
  }
}

variable "extra_tags" {
  description = "Additional tags applied to every resource."
  type        = map(string)
  default     = {}
}
