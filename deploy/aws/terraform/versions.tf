# FLH-084 first AWS deployment of the read-only public demo (preparation only).
# Not initialised, planned or applied by the agent that wrote it: see
# docs/AWS_DEMO.md for the human-run procedure.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70.0, < 7.0.0"
    }
  }

  # No remote backend: state stays in a local file owned by the operator. It
  # holds resource IDs and ARNs only; nothing in this configuration creates or
  # reads a secret. Keep terraform.tfstate* out of Git (see .gitignore).
}

# Credentials come from the operator's normal AWS configuration (profile, SSO
# or environment). Nothing here names an account, key or role to assume.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge({
      Project   = "flh"
      Component = "public-demo"
      Task      = "FLH-084"
      ManagedBy = "terraform"
    }, var.extra_tags)
  }
}
