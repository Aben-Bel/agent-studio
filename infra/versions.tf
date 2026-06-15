terraform {
  required_version = ">= 1.5"

  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    tls     = { source = "hashicorp/tls", version = "~> 4.0" }
    local   = { source = "hashicorp/local", version = "~> 2.0" }
    null    = { source = "hashicorp/null", version = "~> 3.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.0" }
  }
}

# Credentials come from the environment (AWS_ACCESS_KEY_ID / SECRET / SESSION_TOKEN),
# which you load from .env before running terraform — no secrets live in this code.
provider "aws" {
  region = var.region
}
