# Run only in the production workspace:
#   terraform workspace new production   (or: select production)
#   terraform test -filter=tests/production.tftest.hcl
# Mocked provider: nothing is created; `apply` here only fills the in-memory test state.
mock_provider "aws" {
  source = "./tests"
}

variables {
  environment           = "production"
  aws_region            = "us-east-1"
  run_id                = "20261120T080000Z"
  expires_at            = "never"
  ami_id                = "ami-0123456789abcdef0"
  compose_plugin_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
}

run "production_protects_its_data" {
  command = apply

  assert {
    condition     = aws_instance.host.instance_initiated_shutdown_behavior == "stop" && aws_instance.host.disable_api_termination == true
    error_message = "production must stop (never terminate) on shutdown and refuse API termination"
  }
  assert {
    condition     = aws_s3_bucket.staging.force_destroy == false && aws_s3_bucket.staging.bucket_prefix == "flh-prd-"
    error_message = "production bucket: prefix flh-prd-, no force_destroy"
  }
  assert {
    condition     = aws_vpc.stg.cidr_block == "10.86.0.0/24" && aws_ebs_volume.data.size == 20 && aws_ebs_volume.data.encrypted
    error_message = "production network and data volume defaults"
  }
  assert {
    condition     = aws_iam_role_policy.host.name == "flh-prd-host" && aws_iam_role.host.name_prefix == "flh-prd-host-"
    error_message = "production IAM names"
  }
  assert {
    condition = (
      length(aws_s3_bucket_lifecycle_configuration.staging.rule) == 2 &&
      aws_s3_bucket_lifecycle_configuration.staging.rule[0].id == "expire-old-backups" &&
      aws_s3_bucket_lifecycle_configuration.staging.rule[0].filter[0].prefix == "backups/" &&
      aws_s3_bucket_lifecycle_configuration.staging.rule[0].expiration[0].days == 35 &&
      aws_s3_bucket_lifecycle_configuration.staging.rule[1].id == "keep-releases" &&
      length(aws_s3_bucket_lifecycle_configuration.staging.rule[1].expiration) == 0
    )
    error_message = "production lifecycle: backups/ kept 35 days, releases/ never expire"
  }
  assert {
    condition     = strcontains(local.user_data, "- [systemctl, disable, --now, flh-staging-expire.timer]") && strcontains(local.user_data, "PARAM_DIR=/flh/production\n")
    error_message = "production user data must leave the power-off timer disabled and read /flh/production"
  }
  assert {
    condition     = output.environment == "production"
    error_message = "environment output"
  }
}

run "production_keeps_never_as_expiry" {
  command = plan
  variables {
    expires_at = "2026-11-20T20:00:00Z"
  }
  expect_failures = [aws_vpc.stg]
}

run "staging_is_refused_in_the_production_workspace" {
  command = plan
  variables {
    environment = "staging"
    expires_at  = "2026-11-20T20:00:00Z"
  }
  expect_failures = [aws_vpc.stg]
}
