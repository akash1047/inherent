variable "server_name" {
  description = "Name of the Hetzner server"
  type        = string
  default     = "inherent-prod"
}

variable "server_type" {
  description = "Hetzner server type (e.g., cpx22, cpx32)"
  type        = string
  default     = "cpx22"
}

variable "server_image" {
  description = "OS image for the server"
  type        = string
  default     = "ubuntu-24.04"
}

variable "server_location" {
  description = "Hetzner datacenter location"
  type        = string
  default     = "fsn1"
}

variable "server_backups" {
  description = "Enable automatic backups"
  type        = bool
  default     = false
}

variable "ssh_public_key_path" {
  description = "Path to the SSH public key file"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "ssh_key_name" {
  description = "Name for the SSH key resource in Hetzner"
  type        = string
  default     = "inherent-prod-key"
}

variable "inherent_version" {
  description = "Version of Inherent to deploy (Docker image tag)"
  type        = string
  default     = "latest"
}

variable "env_file_content" {
  description = "Content of the .env file for Docker Compose. Use to inject production secrets at apply time. If empty, safe defaults are used."
  type        = string
  default     = ""
  sensitive   = true
}
