# Inherent — Terraform (Hetzner)

Provisions a Hetzner VM with Docker, then starts the full Inherent stack via
Docker Compose. Terraform manages infrastructure only; application services
remain defined in `docker-compose.release.yml`.

## Prerequisites

- [Hetzner account](https://www.hetzner.com) with API token
- SSH key pair (default: `~/.ssh/id_ed25519.pub`)
- For remote state: Hetzner Object Storage bucket + S3 access keys (create in console)

## Setup

```bash
# Authenticate with Hetzner
export HCLOUD_TOKEN="<your-api-token>"

cd infra

# Customise configuration (optional)
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars to set server type, location, etc.
```

### Terraform init (pick one path)

| Path | When | Init |
|------|------|------|
| Hetzner Object Storage | Long-lived prod VM | copy `backend.hcl.example` → `backend.hcl`, set `AWS_*` env, `terraform init -backend-config=backend.hcl` |
| Local ephemeral | CI e2e / throwaway laptop | `terraform init -backend=false` |

- `.terraform.lock.hcl` is the **provider lock** — committed to git.
- `*.tfstate` is **state** — never commit; remote state uses Hetzner Object Storage (S3-compatible).
- Do not point CI at the production state key.
- Operator creates the Object Storage bucket and S3 keys in the Hetzner console (out of band).

#### Remote state (production)

```bash
cp backend.hcl.example backend.hcl
# Edit backend.hcl: bucket, key, endpoints.s3

export AWS_ACCESS_KEY_ID="<hetzner-s3-access-key>"
export AWS_SECRET_ACCESS_KEY="<hetzner-s3-secret-key>"
export AWS_DEFAULT_REGION="eu-central"

terraform init -backend-config=backend.hcl
```

#### Local / CI (ephemeral)

```bash
terraform init -backend=false
```

```bash
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
├── versions.tf              # Terraform & provider versions; partial S3 backend
├── backend.hcl.example      # Hetzner Object Storage backend config template
├── providers.tf              # Provider configuration
├── variables.tf              # Input variables
├── terraform.tfvars.example  # Example variable values
├── server.tf                 # SSH key + server resource
├── firewall.tf               # Firewall + attachment
├── outputs.tf                # Output values
├── cloud-init.yaml.tftpl     # Cloud-init user data template
├── .terraform.lock.hcl       # Provider dependency lock (committed)
├── .gitignore                # Ignores state, backend.hcl, tfvars
└── README.md                 # This file
```

## CI e2e

Workflow: [`.github/workflows/hetzner-e2e.yml`](../.github/workflows/hetzner-e2e.yml).

- **Secret:** `HCLOUD_TOKEN` (repo secret).
- **Triggers:** `workflow_dispatch` + weekly schedule. Not a PR merge gate.
- **Flow:** `terraform init -backend=false` → apply → wait `/health` → bootstrap on VM → public-api `pytest -m compose` → always destroy.
- **Naming:** unique `server_name` / `ssh_key_name` per run (`inherent-ci-${{ github.run_id }}`).
- **State:** ephemeral local state only — never the prod Object Storage key.
- **Long-lived deploys:** use Hetzner Object Storage via `backend.hcl` (see Setup above and [docs/getting-started/production.md](../docs/getting-started/production.md)).

## Out of scope (future iterations)

- DNS / TLS / HTTPS
- Load balancer
- Floating IP
- Persistent volumes
- Multiple environments (dev/staging/prod)
- Multi-node deployments
