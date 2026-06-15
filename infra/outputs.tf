output "app_url" {
  description = "Open this in a browser to use the deployed app."
  value       = "http://${aws_instance.app.public_ip}"
}

output "public_ip" {
  value = aws_instance.app.public_ip
}

output "ssh_command" {
  description = "SSH into the host."
  value       = "ssh -i ${local_sensitive_file.pem.filename} ec2-user@${aws_instance.app.public_ip}"
}
