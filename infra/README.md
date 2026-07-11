# Inherent — Terraform (Hetzner)

Provisions a Hetzner VM with Docker, then starts the full Inherent stack via
Docker Compose. Terraform manages infrastructure only; application services
remain defined in `docker-compose.release.yml`.

## Prerequisites

- [Hetzner account](https://www.hetzner.com) with API token
- SSH key pair (default: `~/.ssh/id_ed25519.pub`)

## Setup

```bash
# Authenticate with Hetzner
export HCLOUD_TOKEN="<your-api-token>"

cd infra

# Customise configuration (optional)
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars to set server type, location, etc.

# Initialise Terraform
terraform init

# Review the plan
terraform plan

# Provision
terraform apply
```

## What happens

1. Terraform registers your SSH key with Hetzner.
2. Terraform creates a firewall allowing SSH (22), Public API (18000), and ICMP.
3. Terraform provisions a server with cloud-init user data.
4. Cloud-init installs Docker, creates `/opt/inherent`, downloads the release
   compose file, writes `.env`, and starts all containers.

## After provisioning

The server is ready when cloud-init completes. Check status:

```bash
ssh root@$(terraform output -raw server_ipv4)
docker compose -f /opt/inherent/docker-compose.release.yml ps
```

The Public API is available at `http://<server-ip>:18000`.

## Updating the application

SSH into the server and use Docker Compose as usual:

```bash
ssh root@<server-ip>
cd /opt/inherent
# Update images
docker compose -f docker-compose.release.yml pull
docker compose -f docker-compose.release.yml up -d
```

## Secrets

Application secrets (database passwords, API keys) live in
`/opt/inherent/.env` on the server. Set them via `terraform.tfvars`:

```hcl
env_file_content = <<-EOF
POSTGRES_PASSWORD=strong-password
INGESTION_API_KEY=strong-api-key
...
EOF
```

The `env_file_content` variable is marked `sensitive` and will not appear in
logs or state output. If omitted, safe development defaults are used.

## Clean up

```bash
terraform destroy
```

This removes the server, firewall, and SSH key from Hetzner.

## File layout

```
infra/
├── versions.tf              # Terraform & provider versions
├── providers.tf              # Provider configuration
├── variables.tf              # Input variables
├── terraform.tfvars.example  # Example variable values
├── server.tf                 # SSH key + server resource
├── firewall.tf               # Firewall + attachment
├── outputs.tf                # Output values
├── cloud-init.yaml.tftpl     # Cloud-init user data template
├── .gitignore                # Terraform ignores
└── README.md                 # This file
```

## Out of scope (future iterations)

- DNS / TLS / HTTPS
- Load balancer
- Floating IP
- Persistent volumes
- Remote Terraform state
- Multiple environments (dev/staging/prod)
- Multi-node deployments
