###############################################################################
# Joke Platform — EC2 deployment as code.
# Provisions: SSH key pair, security group, an EC2 host with Docker, and ships
# the repo (incl. .env) to it, then runs `docker compose up`.
###############################################################################

# ---- Network: use the account's default VPC + a public subnet ----
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ---- Latest Amazon Linux 2023 AMI ----
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# ---- SSH key pair (generated here, private key saved locally) ----
resource "tls_private_key" "key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "key" {
  key_name   = "${var.project}-key"
  public_key = tls_private_key.key.public_key_openssh
}

resource "local_sensitive_file" "pem" {
  content         = tls_private_key.key.private_key_pem
  filename        = "${path.module}/${var.project}-key.pem"
  file_permission = "0400"
}

# ---- Security group: 80 (app) open to the world, 22 (SSH) per var ----
resource "aws_security_group" "app" {
  name        = "${var.project}-sg"
  description = "Joke Platform app"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP (frontend)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-sg" }
}

# ---- The host. user_data installs Docker + the Compose plugin on first boot ----
resource "aws_instance" "app" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = var.instance_type
  key_name                    = aws_key_pair.key.key_name
  subnet_id                   = tolist(data.aws_subnets.default.ids)[0]
  vpc_security_group_ids      = [aws_security_group.app.id]
  associate_public_ip_address = true

  # Re-run the boot script (and thus pick up buildx/compose changes) by
  # replacing the instance whenever user_data changes — otherwise edits to the
  # boot script silently never execute on the running host.
  user_data_replace_on_change = true

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -e
    dnf update -y
    dnf install -y docker git unzip
    systemctl enable --now docker
    usermod -aG docker ec2-user
    mkdir -p /usr/local/lib/docker/cli-plugins
    # Compose plugin
    curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    # Buildx plugin — REQUIRED by `docker compose --build` (>= 0.17). Resolve the
    # latest release tag (buildx assets are version-named, unlike compose).
    BX=$(curl -fsSL https://api.github.com/repos/docker/buildx/releases/latest \
      | grep -oE '"tag_name": *"v[^"]+"' | grep -oE 'v[0-9.]+' | head -1)
    curl -SL "https://github.com/docker/buildx/releases/download/$${BX}/buildx-$${BX}.linux-amd64" \
      -o /usr/local/lib/docker/cli-plugins/docker-buildx
    chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx
    touch /home/ec2-user/USERDATA_DONE
  EOF

  tags = { Name = var.project }
}

# ---- Package the repo (incl. .env) for upload. Re-zips when files change ----
data "archive_file" "app" {
  type        = "zip"
  source_dir  = "${path.module}/.."
  output_path = "${path.module}/app.zip"

  excludes = [
    "infra",
    ".git",
    ".github",
    "node_modules",
    "frontend/node_modules",
    "frontend/dist",
    "dist",
    "AWSCLIV2.pkg",
    ".venv",
    "venv",
  ]
}

# ---- Ship the app to the host and bring it up. Re-runs when the app changes ----
resource "null_resource" "deploy" {
  triggers = {
    instance = aws_instance.app.id
    app      = data.archive_file.app.output_md5
  }

  connection {
    type        = "ssh"
    host        = aws_instance.app.public_ip
    user        = "ec2-user"
    private_key = tls_private_key.key.private_key_pem
    timeout     = "8m"
  }

  # Wait until the boot script has finished installing Docker + Compose.
  provisioner "remote-exec" {
    inline = [
      "echo 'waiting for Docker install (cloud-init)...'",
      "until [ -f /home/ec2-user/USERDATA_DONE ] && sudo docker compose version >/dev/null 2>&1; do sleep 5; done",
      "rm -rf /home/ec2-user/app && mkdir -p /home/ec2-user/app",
    ]
  }

  # Upload the zipped repo (contains .env).
  provisioner "file" {
    source      = data.archive_file.app.output_path
    destination = "/home/ec2-user/app.zip"
  }

  # Unzip and launch (frontend on :80 via the prod override). `set -e` so a build
  # failure fails the apply instead of being masked by a trailing command.
  provisioner "remote-exec" {
    inline = [
      "set -e",
      "cd /home/ec2-user/app",
      "unzip -o ../app.zip >/dev/null",
      "sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build",
      "sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml ps",
    ]
  }
}
