# PROPOSED (batch 5, release lane): isolated NAS -> AWS staging target for the
# private workbench. Separate root, state and tags from deploy/aws/terraform (the
# public demo), which it never references or changes. Not planned or applied by
# an agent; the owner runs every Terraform command (AWS_STAGING_PLAN.md).
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.69.1" # the version pinned by deploy/aws/terraform/.terraform.lock.hcl (FLH-085)
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project   = "flh"
      Component = "workbench-staging"
      Run       = var.run_id
      ExpiresAt = var.expires_at
      ManagedBy = "terraform"
    }
  }
}
