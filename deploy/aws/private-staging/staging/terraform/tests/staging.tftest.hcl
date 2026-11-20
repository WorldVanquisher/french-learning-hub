# Run in a workspace other than production (the default one):
#   terraform init -backend=false && terraform test -filter=tests/staging.tftest.hcl
# Mocked provider: nothing is created; `apply` here only fills the in-memory test state.
mock_provider "aws" {
  source = "./tests"
}

variables {
  aws_region            = "us-east-1"
  run_id                = "20261120T080000Z"
  expires_at            = "2026-11-20T20:00:00Z"
  ami_id                = "ami-0123456789abcdef0"
  compose_plugin_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
}

run "staging_keeps_its_bounded_settings" {
  command = apply

  assert {
    condition     = aws_instance.host.instance_initiated_shutdown_behavior == "terminate" && aws_instance.host.disable_api_termination == false
    error_message = "staging must terminate on shutdown and allow API termination"
  }
  assert {
    condition     = aws_s3_bucket.staging.force_destroy == true && aws_s3_bucket.staging.bucket_prefix == "flh-stg-"
    error_message = "staging bucket: prefix flh-stg-, force_destroy"
  }
  assert {
    condition     = aws_vpc.stg.cidr_block == "10.85.0.0/24" && aws_ebs_volume.data.size == 8 && aws_ebs_volume.data.encrypted
    error_message = "staging network and data volume defaults changed"
  }
  assert {
    condition     = aws_iam_role_policy.host.name == "flh-stg-host" && aws_iam_role.host.name_prefix == "flh-stg-host-"
    error_message = "staging IAM names changed"
  }
  assert {
    condition     = length(aws_s3_bucket_lifecycle_configuration.staging.rule) == 1 && aws_s3_bucket_lifecycle_configuration.staging.rule[0].id == "expire-staging-objects" && aws_s3_bucket_lifecycle_configuration.staging.rule[0].expiration[0].days == 14
    error_message = "staging lifecycle: one rule, every object expires after 14 days"
  }
  assert {
    condition     = strcontains(local.user_data, "- [systemctl, enable, --now, flh-staging-expire.timer]") && strcontains(local.user_data, "PARAM_DIR=/flh/staging\n")
    error_message = "staging user data must arm the power-off timer and read /flh/staging"
  }
  assert {
    condition     = aws_security_group.host.description == "FLH staging host: no inbound; outbound HTTPS only" && output.environment == "staging"
    error_message = "staging security group description changed (it forces replacement)"
  }
}

run "staging_needs_an_expiry_time" {
  command = plan
  variables {
    expires_at = "never"
  }
  expect_failures = [aws_vpc.stg]
}

run "production_is_refused_outside_its_workspace" {
  command = plan
  variables {
    environment = "production"
    expires_at  = "never"
  }
  expect_failures = [aws_vpc.stg]
}

run "unknown_environment_is_refused" {
  command = plan
  variables {
    environment = "prod"
  }
  expect_failures = [var.environment]
}
