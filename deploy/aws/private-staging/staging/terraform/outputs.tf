output "instance_id" {
  value = aws_instance.host.id
}

output "bucket" {
  value = aws_s3_bucket.staging.bucket
}

output "data_volume_id" {
  value = aws_ebs_volume.data.id
}

output "port_forward_command" {
  description = "Owner's laptop: the workbench at http://127.0.0.1:18080 while this runs."
  value       = "aws ssm start-session --region ${var.aws_region} --target ${aws_instance.host.id} --document-name AWS-StartPortForwardingSession --parameters portNumber=${var.app_port},localPortNumber=18080"
}

output "environment" {
  value = var.environment
}
