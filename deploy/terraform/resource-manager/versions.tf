terraform {
  required_version = ">= 1.5.7, < 2.0.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "= 8.24.0"
    }
  }
}
provider "oci" { region = var.region }
provider "oci" {
  alias  = "home"
  region = var.home_region
}
