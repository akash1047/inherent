terraform {
  required_version = ">= 1.5.0"

  # Local dev:  terraform init -backend=false
  # CI:         terraform init -backend-config="bucket=..." -backend-config="key=..."
  backend "s3" {}

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
  }
}
