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

| Path | When | State key / backend | Init |
|------|------|---------------------|------|
| **Prod / long-lived** | Stable prod VM | `backend.hcl` stable key (e.g. `inherent/prod/...`) | copy `backend.hcl.example` → `backend.hcl`, set `AWS_*` env, `terraform init -backend-config=backend.hcl` |
| **CI e2e** | GHA Hetzner e2e | Object Storage `inherent/ci/<github.run_id>/terraform.tfstate` via workflow-generated `backend-ci.hcl` | workflow runs `terraform init -reconfigure -backend-config=backend-ci.hcl` |
| **Laptop throwaway** | Local experiments | temporary local backend override | write `backend "local"` override + `terraform init -reconfigure` |

- `.terraform.lock.hcl` is the **provider lock** — committed to git.
- `*.tfstate` is **state** — never commit; remote state uses Hetzner Object Storage (S3-compatible).
- **Hard rule:** never point CI at the production state key.
- Operator creates the Object Storage bucket and S3 keys in the Hetzner console (out of band).

#### Remote state (production)

```bash
cp backend.hcl.example backend.hcl
# Edit backend.hcl: bucket, key (e.g. inherent/prod/...), endpoints.s3

export AWS_ACCESS_KEY_ID="<hetzner-s3-access-key>"
export AWS_SECRET_ACCESS_KEY="<hetzner-s3-secret-key>"
export AWS_DEFAULT_REGION="eu-central"

terraform init -backend-config=backend.hcl
```

#### Laptop throwaway (local override only)

Empty partial `backend "s3" {}` still requires a configured backend for
`plan`/`apply`. For laptop throwaway runs only — not CI — override to local
(do not commit the override):

```bash
cat > zzz_local_backend_override.tf <<'EOF'
terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
EOF
terraform init -input=false -reconfigure
# Review / provision
terraform plan
terraform apply
# Remove override when done so prod init stays S3-oriented
rm zzz_local_backend_override.tf
```

CI e2e does **not** use local state; see [CI e2e](#ci-e2e) below.

## What happens

1. Terraform registers your SSH key with Hetzner.
2. Terraform creates a firewall allowing SSH (22), Public API (18000), and ICMP.
   This firewall is the only network barrier for Docker-published ports;
   set `ssh_allowed_ips` / `api_allowed_ips` to restrict access in production.
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

`env_file_content` is `sensitive = true`: Terraform CLI redacts it from plan/apply
terminal output only. Secrets still land in Terraform state (restrict Object
Storage) and in cloud-init `user_data` / instance metadata (`169.254.169.254`).
Containers on the VM can read metadata — known limitation. If omitted, safe
development defaults are used.

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

### GitHub Actions configuration

Use a **dedicated Hetzner Cloud project** for the CI `HCLOUD_TOKEN` so e2e
blast radius cannot touch production servers or SSH keys.

| Kind | Name | Notes |
|------|------|-------|
| Secret | `HCLOUD_TOKEN` | Hetzner Cloud API token (CI project only) |
| Secret | `AWS_ACCESS_KEY_ID` | Hetzner Object Storage S3 access key |
| Secret | `AWS_SECRET_ACCESS_KEY` | Hetzner Object Storage S3 secret key |
| Variable | `HETZNER_S3_BUCKET` | Object Storage bucket name |
| Variable | `HETZNER_S3_ENDPOINT` | S3 endpoint URL |
| Variable | `AWS_DEFAULT_REGION` | optional; default `eu-central` |

### Behaviour

- **Triggers:**
  - **Release:** successful **Publish images** on a final `vX.Y.Z` tag
    (`workflow_run`). RC tags (`v*-rcN`) skip e2e. Not a PR merge gate.
  - **Manual:** Actions → **Hetzner e2e** → **Run workflow** (see form below).
  - No weekly schedule; does not pull `:latest` by default.
- **Pin:** `inherent_version` (GHCR image tag, e.g. `X.Y.Z`) +
  `compose_git_ref` (same git ref for compose checkout when possible). See
  [docs/maintainers/releasing.md](../docs/maintainers/releasing.md#cutting-an-image-release).
- **State:** Hetzner Object Storage key `inherent/ci/<github.run_id>/terraform.tfstate` via workflow-generated `backend-ci.hcl`. Never the prod key.
- **Server type:** CI defaults to **cpx32** (compose e2e headroom for TEI + stack). Local/prod examples may use `cpx22`.
- **Flow:** generate `backend-ci.hcl` → `terraform init -reconfigure -backend-config=backend-ci.hcl` → apply (`environment=ci`) → export `SERVER_IPV4` from TF state → cloud-init wait → `/health` → bootstrap on VM → public-api `pytest -m compose` → always destroy with retries (same remote state).
- **Naming:** unique `server_name` / `ssh_key_name` per run (`inherent-ci-${{ github.run_id }}`).
- **Image parity:** default env sets `WEAVIATE_API_KEY`, and release compose enables Weaviate API-key auth. The **published** `public-api-svc` image must include Weaviate Bearer client support (see [docs/audit/act-hetzner-e2e-weaviate-401.md](../docs/audit/act-hetzner-e2e-weaviate-401.md)). `/health` alone does not prove Weaviate auth works. Smoke-grep image before long e2e runs ([docs/maintainers/releasing.md](../docs/maintainers/releasing.md)).
- **Long-lived deploys:** use Hetzner Object Storage via `backend.hcl` (see Setup above and [docs/getting-started/production.md](../docs/getting-started/production.md)).

### Manual run (GitHub form)

1. Actions → left sidebar **Hetzner e2e** → **Run workflow**.
2. Fill the dialog (maps to `workflow_dispatch` inputs):

| Form field | Input | What it does | Typical value |
|------------|--------|--------------|---------------|
| **Use workflow from** | (GHA UI only) | Branch that supplies the **workflow YAML** (not the checkout for TF/compose unless you also set `ref` to it) | `main` (or a feature branch that has this workflow) |
| **Git tag/branch/SHA…** | `ref` (required) | `actions/checkout` target; also `compose_git_ref` for the VM stack | Branch/tag that **includes `infra/`** and release compose. Old tags without Terraform fail at init (`infra/` missing). |
| **Docker image tag…** | `inherent_version` | GHCR tag for `public-api-svc` / `ingestion-svc`. Empty → strip one leading `v` from `ref` (`v0.4.1` → `0.4.1`) | Empty when `ref` is a final release tag; or set explicitly (`0.4.1`, `latest`) when `ref` is `main` |
| **Hetzner server type** | `server_type` | Hetzner plan for the CI VM | `cpx32` (default; keep for compose e2e) |

**Do not confuse** “Use workflow from” with `ref`:

- **Use workflow from** = which commit’s `.github/workflows/hetzner-e2e.yml` runs.
- **`ref`** = which commit is checked out on the runner and used for compose/TF tree on the job (must have `infra/`).

**Examples**

| Goal | Use workflow from | `ref` | Docker image tag |
|------|-------------------|-------|------------------|
| Production-path on current e2e workflow + published release images | `main` | `main` | `0.4.1` (or another published tag) |
| Full pin when release tag **includes** `infra/` | `main` | `vX.Y.Z` | *(empty → `X.Y.Z`)* |
| Avoid | any | `v0.4.1` if that tag has no `infra/` | — (init fails: no `infra/backend-ci.hcl` parent dir) |

CLI:

```bash
gh workflow run "Hetzner e2e" -f ref=main -f inherent_version=0.4.1 -f server_type=cpx32
```

### Local simulation (`act`)

[nektos/act](https://github.com/nektos/act) can run the workflow file on a laptop. It is **not** a substitute for GHA secrets/vars setup and still needs real Hetzner credentials if apply is not mocked.

- Image skew / Weaviate 401 lessons from a local `act` run:
  [docs/audit/act-hetzner-e2e-weaviate-401.md](../docs/audit/act-hetzner-e2e-weaviate-401.md)
- Before long e2e (GHA or act): smoke-grep published `public-api-svc` for Weaviate Bearer —
  [docs/maintainers/releasing.md § Hetzner / act e2e image parity](../docs/maintainers/releasing.md#hetzner--act-e2e-image-parity)

There is no committed `act` config or Makefile target; operators pass `workflow_dispatch` inputs and secrets per local act setup.

### Recover orphaned CI resources

Workflow: [`.github/workflows/hetzner-e2e-recover.yml`](../.github/workflows/hetzner-e2e-recover.yml).

This is the **orphan path** when primary destroy fails or the job dies after
state was written — there is no separate age-sweep job.

- **When:** e2e job died after Terraform wrote remote state (e.g. runner killed mid-run) and destroy did not run.
- **UI:** Actions → **Hetzner e2e recover destroy** → **Run workflow**.
- **Inputs:**
  - `run_id` (required) — failed workflow run id (URL `.../actions/runs/<run_id>`; state key `inherent/ci/<run_id>/terraform.tfstate`)
  - `inherent_version` / `server_type` / `compose_git_ref` — match stuck run when known; pure destroy often OK with defaults (`compose_git_ref` defaults to `main`, `server_type` `cpx32`)
- Re-inits with that CI key and runs `terraform destroy` (with retries).
- **If the job dies before the first state write**, remote state cannot help: delete servers named `inherent-ci-*` in the Hetzner console/API manually (CI project).

## Out of scope (future iterations)

- DNS / TLS / HTTPS
- Load balancer
- Floating IP
- Persistent volumes
- Multiple environments (dev/staging/prod)
- Multi-node deployments
