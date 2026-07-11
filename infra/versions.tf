terraform {
  required_version = ">= 1.5.0"

  # .terraform.lock.hcl = provider dependency lock (committed to git).
  # State (*.tfstate) is remote via Hetzner Object Storage (S3-compatible)
  # for long-lived deploys — never commit state files.
  #
  # Remote (prod):   copy backend.hcl.example → backend.hcl, set AWS_* env,
  #                  then: terraform init -backend-config=backend.hcl
  # Ephemeral/local: terraform init -backend=false
  #                  (laptop throwaway + CI e2e; do not use the prod state key)
  backend "s3" {}

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
  }
}
