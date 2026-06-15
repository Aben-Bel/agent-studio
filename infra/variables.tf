variable "region" {
  description = "AWS region (must match where Bedrock + the model + the S3 bucket live)."
  type        = string
  default     = "us-west-2"
}

variable "instance_type" {
  description = "EC2 instance size."
  type        = string
  default     = "t3.small"
}

variable "project" {
  description = "Name prefix for all created resources."
  type        = string
  default     = "joke-platform"
}

variable "ssh_cidr" {
  description = "CIDR allowed to SSH (port 22). Lock to your IP for real use."
  type        = string
  default     = "0.0.0.0/0"
}
