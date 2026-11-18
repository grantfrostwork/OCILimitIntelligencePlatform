variable "tenancy_ocid" {
  type        = string
  description = "Customer tenancy OCID."
  validation {
    condition     = can(regex("^ocid1\\.tenancy\\.", var.tenancy_ocid))
    error_message = "Supply a valid tenancy OCID."
  }
}

variable "parent_compartment_ocid" {
  type        = string
  description = "Parent in which to create the dedicated application compartment."
}

variable "region" {
  type        = string
  description = "Deployment region."
  default     = "us-ashburn-1"
}

variable "home_region" {
  type        = string
  description = "Tenancy home region; IAM resources are created here."
}

variable "deployment_name" {
  type        = string
  description = "Unique name for this installation and tenancy-wide IAM resources."
  default     = "oci-lip"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.deployment_name))
    error_message = "Use 3-25 lowercase letters, digits or hyphens, beginning with a letter."
  }
}

variable "availability_domain" {
  type        = string
  description = "Availability domain containing A1 capacity."
}

variable "image_ocid" {
  type        = string
  description = "Oracle Linux 9 ARM64 platform image for this region; pin to avoid replacement on image refresh."
  validation {
    condition     = can(regex("^ocid1\\.image\\.", var.image_ocid))
    error_message = "Supply a valid image OCID."
  }
}

variable "ssh_public_key" {
  type        = string
  description = "SSH public key contents. Never supply a private key."
  validation {
    condition     = can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+) [A-Za-z0-9+/=]+", var.ssh_public_key))
    error_message = "Paste a valid SSH public key."
  }
}

variable "bastion_client_cidrs" {
  type        = list(string)
  description = "Administrator public source CIDRs, ideally /32."
  validation {
    condition     = length(var.bastion_client_cidrs) > 0 && alltrue([for c in var.bastion_client_cidrs : can(cidrnetmask(c)) && c != "0.0.0.0/0"])
    error_message = "Provide administrator IPv4 CIDRs narrower than 0.0.0.0/0."
  }
}

variable "allowed_client_cidrs" {
  type        = set(string)
  description = "HTTPS client source CIDRs. Use corporate egress ranges or deliberately choose 0.0.0.0/0."
  validation {
    condition     = length(var.allowed_client_cidrs) > 0 && alltrue([for c in var.allowed_client_cidrs : can(cidrnetmask(c))])
    error_message = "Provide at least one valid IPv4 CIDR."
  }
}

variable "vcn_cidr" {
  type        = string
  description = "New VCN CIDR; public and private subnets use cidrsubnet /24."
  default     = "10.96.0.0/16"
  validation {
    condition     = can(cidrnetmask(var.vcn_cidr)) && can(cidrsubnet(var.vcn_cidr, 8, 2)) && endswith(var.vcn_cidr, "/16")
    error_message = "Supply an IPv4 /16 VCN CIDR."
  }
}

variable "public_url" {
  type        = string
  description = "HTTPS origin, e.g. https://limits.example.com; no trailing slash."
  validation {
    condition     = can(regex("^https://[A-Za-z0-9.-]+$", var.public_url))
    error_message = "Use an HTTPS origin without path, port or trailing slash."
  }
}

variable "certificate_ocid" {
  type        = string
  description = "Existing OCI Certificates service certificate in deployment region matching public_url."
  validation {
    condition     = can(regex("^ocid1\\.certificate\\.", var.certificate_ocid))
    error_message = "Supply a valid certificate OCID."
  }
}

variable "oidc_secret_ocid" {
  type        = string
  description = "Existing Vault secret OCID containing the JSON described in README. No secret value enters Terraform."
  validation {
    condition     = can(regex("^ocid1\\.vaultsecret\\.", var.oidc_secret_ocid))
    error_message = "Supply a valid vaultsecret OCID."
  }
}

variable "secret_region" {
  type        = string
  description = "Region holding the existing Vault secret."
}

variable "application_commit" {
  type        = string
  description = "Immutable application Git commit. Updates require the documented guest upgrade procedure."
  default     = "c752c28c22bd29ca87ee55cc401fb6498a2e7df0"
  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.application_commit))
    error_message = "Supply a full immutable Git commit SHA."
  }
}

variable "scan_all_regions" {
  type        = bool
  description = "Scan all subscribed tenancy regions instead of deployment region only."
  default     = false
}

variable "warning_threshold_percent" {
  type        = number
  description = "Initial warning threshold; later managed in application Settings."
  default     = 90
  validation {
    condition     = var.warning_threshold_percent > 0 && var.warning_threshold_percent <= 100
    error_message = "Threshold must be greater than zero and at most 100."
  }
}

variable "critical_threshold_percent" {
  type        = number
  description = "Initial critical threshold; later managed in application Settings."
  default     = 98
  validation {
    condition     = var.critical_threshold_percent > 0 && var.critical_threshold_percent <= 100
    error_message = "Threshold must be greater than zero and at most 100."
  }
}
