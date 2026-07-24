variable "tenancy_ocid" {
  description = "Tenancy OCID used for OCI API access and as the default deployment compartment."
  type        = string
}

variable "compartment_ocid" {
  description = "Dedicated OCI LIP compartment OCID. Leave empty only for the existing root-compartment migration."
  type        = string
  default     = ""
}

variable "region" {
  description = "OCI region for the LIP control plane."
  type        = string
  default     = "us-ashburn-1"
}

variable "oci_profile" {
  description = "OCI CLI profile used by the Terraform provider."
  type        = string
  default     = "DEFAULT"
}

variable "availability_domain" {
  description = "Availability domain for the Ampere A1 VM."
  type        = string
}

variable "vcn_id" {
  description = "OCID of the existing LIP VCN."
  type        = string
}

variable "public_subnet_id" {
  description = "OCID of the existing regional public subnet used by the public Flexible Load Balancer."
  type        = string
}

variable "private_subnet_cidr" {
  description = "CIDR for the new private application subnet."
  type        = string
  default     = "10.96.2.0/24"
}

variable "allowed_client_cidrs" {
  description = "Client CIDRs permitted to reach the public load balancer. OCI IAM SSO remains mandatory."
  type        = set(string)
  default     = ["0.0.0.0/0"]
}

variable "bastion_client_cidrs" {
  description = "Administrator CIDRs permitted to create OCI Bastion sessions."
  type        = list(string)
}

variable "image_id" {
  description = "ARM64 Oracle Linux image or OCI LIP custom-image OCID."
  type        = string
}

variable "ssh_public_key_path" {
  description = "Local path to the SSH public key installed on the VM."
  type        = string
  default     = "~/.ssh/ssh-key-2023-11-16.key.pub"
}

variable "instance_display_name" {
  description = "Display name of the private ARM64 instance."
  type        = string
  default     = "oci-lip-arm64-private"
}

variable "instance_ocpus" {
  description = "Ampere A1 OCPUs."
  type        = number
  default     = 2
}

variable "instance_memory_gbs" {
  description = "Ampere A1 memory in GB."
  type        = number
  default     = 12
}

variable "boot_volume_size_gbs" {
  description = "Boot volume size in GB."
  type        = number
  default     = 50
}

variable "repository_url" {
  description = "Public OCI LIP Git repository cloned during first boot."
  type        = string
  default     = "https://github.com/grantfrostwork/OCILimitIntelligencePlatform.git"
}

variable "repository_branch" {
  description = "Git branch used by the ARM64 deployment."
  type        = string
  default     = "codex/arm64-a1-deployment"
}

variable "auth_public_url" {
  description = "Final HTTPS origin. Used to prepare the runtime configuration before OIDC is enabled."
  type        = string
  default     = "http://localhost"
}

variable "certificate_id" {
  description = "Bootstrap OCI Certificates Service certificate OCID. Leave empty when using a Load Balancer-managed certificate."
  type        = string
  default     = ""

  validation {
    condition     = var.certificate_id == "" || startswith(var.certificate_id, "ocid1.certificate.")
    error_message = "certificate_id must be empty or an OCI Certificates Service certificate OCID."
  }
}

variable "load_balancer_certificate_name" {
  description = "Bootstrap Load Balancer-managed certificate name. Empty with certificate_id creates an HTTP validation listener only."
  type        = string
  default     = ""

  validation {
    condition     = var.load_balancer_certificate_name == "" || can(regex("^[A-Za-z0-9_-]+$", var.load_balancer_certificate_name))
    error_message = "load_balancer_certificate_name can contain only letters, numbers, underscores, and hyphens."
  }
}

variable "load_balancer_min_bandwidth_mbps" {
  description = "Minimum Flexible Load Balancer bandwidth."
  type        = number
  default     = 10
}

variable "load_balancer_max_bandwidth_mbps" {
  description = "Maximum Flexible Load Balancer bandwidth."
  type        = number
  default     = 10
}

locals {
  compartment_ocid = trimspace(var.compartment_ocid) != "" ? var.compartment_ocid : var.tenancy_ocid
  https_enabled    = var.certificate_id != "" || var.load_balancer_certificate_name != ""
  common_tags = {
    "Application"  = "OCI-LIP"
    "Architecture" = "ARM64"
    "ManagedBy"    = "Terraform"
  }
}
