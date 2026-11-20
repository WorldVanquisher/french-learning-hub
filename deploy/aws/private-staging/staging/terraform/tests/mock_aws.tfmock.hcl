# Shared mocks for tests/*.tftest.hcl: no AWS call, no credentials (terraform test
# with a mocked provider). Values are synthetic.
mock_data "aws_ec2_instance_type" {
  defaults = {
    supported_architectures = ["x86_64"]
  }
}

mock_data "aws_iam_policy" {
  defaults = {
    arn = "arn:aws:iam::000000000000:policy/mock-host-boundary"
  }
}

mock_data "aws_caller_identity" {
  defaults = {
    account_id = "000000000000"
  }
}

mock_data "aws_iam_policy_document" {
  defaults = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
  }
}

mock_resource "aws_s3_bucket" {
  defaults = {
    arn = "arn:aws:s3:::flh-mock-bucket"
  }
}

mock_resource "aws_instance" {
  defaults = {
    availability_zone = "us-east-1a"
  }
}
