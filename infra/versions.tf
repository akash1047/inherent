terraform {
  required_version = ">= 1.5.0"

  # .terraform.lock.hcl = provider dependency lock (committed to git).
  # State (*.tfstate) is remote via Hetzner Object Storage (S3-compatible)
  # — never commit state files.
  #
  # Prod / long-lived: copy backend.hcl.example → backend.hcl (stable key,
  #   e.g. inherent/prod/...), set AWS_* env,
  #   then: terraform init -backend-config=backend.hcl
  # CI e2e:            S3 backend with inherent/ci/<run_id>/terraform.tfstate
  #   via workflow-generated backend-ci.hcl; never the prod key.
  # Laptop throwaway:  temporary *_override.tf with backend "local" {},
  #   then: terraform init -reconfigure (local override only; not for CI).
  #   Plain -backend=false is not enough with an empty partial s3 backend.
  backend "s3" {}

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
  }
}
