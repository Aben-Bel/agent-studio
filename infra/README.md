# Deploy (Infrastructure as Code)

Provisions an EC2 host running the full stack (`docker compose`) and ships the
repo — including `.env` — to it. Frontend is served on port 80.

## Prerequisites
- Terraform installed
- Valid AWS creds in the repo's `.env` (the same ones the app uses)

## Deploy
```bash
cd infra
set -a; . ../.env; set +a        # load AWS creds into the environment
terraform init
terraform apply                  # prints app_url when done
```

`terraform output app_url` → `http://<public-ip>`

## Update the app after code changes
```bash
set -a; . ../.env; set +a
terraform apply                  # re-zips + re-deploys onto the same host
```

## Tear down (stop billing)
```bash
set -a; . ../.env; set +a
terraform destroy
```

## Notes
- Credentials are read from the environment — none are stored in the `.tf` files.
- The host uses the `.env` temporary workshop creds; when they expire, refresh
  `.env` and `terraform apply` again (or SSH in and update `/home/ec2-user/app/.env`).
- SSH: `terraform output ssh_command`.
