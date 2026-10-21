output "instance_id" {
  description = "Target for aws ssm start-session."
  value       = aws_instance.host.id
}

output "ami_id" {
  description = "AMI in use; copy it into ami_id to pin it."
  value       = aws_instance.host.ami
}

output "artifact_bucket" {
  description = "Private bucket for release tarballs (upload under releases/)."
  value       = aws_s3_bucket.artifacts.bucket
}

output "package_arch" {
  description = "Package binary directory used on the host (bin/linux-<arch>)."
  value       = local.package_arch
}

output "preview_command" {
  description = "Private preview over SSM port forwarding; then open http://127.0.0.1:<local port>/ locally."
  value       = "aws ssm start-session --region ${var.aws_region} --target ${aws_instance.host.id} --document-name AWS-StartPortForwardingSession --parameters portNumber=${var.app_port},localPortNumber=${var.app_port}"
}

output "public_ipv4" {
  description = "FLH-088: Elastic IP for the public host name's DNS A record; null while public_https_enabled is false."
  value       = var.public_https_enabled ? aws_eip.public[0].public_ip : null
}
