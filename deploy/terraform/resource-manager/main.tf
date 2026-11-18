locals {
  compartment_ocid = oci_identity_compartment.lip.id
  common_tags      = { Application = "OCI-LIP", Deployment = var.deployment_name }
}
resource "oci_identity_compartment" "lip" {
  provider       = oci.home
  compartment_id = var.parent_compartment_ocid
  name           = var.deployment_name
  description    = "Dedicated OCI Limit Intelligence Platform deployment"
  enable_delete  = true
}
resource "oci_core_vcn" "lip" {
  compartment_id = local.compartment_ocid
  cidr_block     = var.vcn_cidr
  display_name   = var.deployment_name
  dns_label      = "ocilip"
}
resource "oci_core_internet_gateway" "lip" {
  compartment_id = local.compartment_ocid
  vcn_id         = oci_core_vcn.lip.id
  display_name   = "${var.deployment_name}-internet"
}
resource "oci_core_route_table" "public" {
  compartment_id = local.compartment_ocid
  vcn_id         = oci_core_vcn.lip.id
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.lip.id
  }
}
resource "oci_core_security_list" "public" {
  compartment_id = local.compartment_ocid
  vcn_id         = oci_core_vcn.lip.id
  display_name   = "${var.deployment_name}-public-empty"
}
resource "oci_core_subnet" "public" {
  compartment_id    = local.compartment_ocid
  vcn_id            = oci_core_vcn.lip.id
  cidr_block        = cidrsubnet(var.vcn_cidr, 8, 1)
  display_name      = "${var.deployment_name}-load-balancer"
  dns_label         = "public"
  route_table_id    = oci_core_route_table.public.id
  security_list_ids = [oci_core_security_list.public.id]
}
resource "oci_ons_notification_topic" "alerts" {
  compartment_id = local.compartment_ocid
  name           = "${var.deployment_name}-limit-alerts"
  description    = "Application-managed limit alert subscriptions"
}
resource "oci_identity_dynamic_group" "runtime" {
  provider       = oci.home
  compartment_id = var.tenancy_ocid
  name           = "${var.deployment_name}-runtime"
  description    = "Only instances in the dedicated application compartment"
  matching_rule  = "ALL {instance.compartment.id = '${local.compartment_ocid}'}"
}
resource "oci_identity_policy" "runtime" {
  provider       = oci.home
  compartment_id = var.tenancy_ocid
  name           = "${var.deployment_name}-runtime"
  description    = "Read limits; use application notifications; fetch only the specified OIDC secret"
  statements = [
    "Allow dynamic-group ${oci_identity_dynamic_group.runtime.name} to read resource-availability in tenancy",
    "Allow dynamic-group ${oci_identity_dynamic_group.runtime.name} to inspect compartments in tenancy",
    "Allow dynamic-group ${oci_identity_dynamic_group.runtime.name} to use ons-topics in compartment id ${local.compartment_ocid}",
    "Allow dynamic-group ${oci_identity_dynamic_group.runtime.name} to inspect ons-subscriptions in compartment id ${local.compartment_ocid}",
    "Allow dynamic-group ${oci_identity_dynamic_group.runtime.name} to read secret-bundles in tenancy where target.secret.id = '${var.oidc_secret_ocid}'"
  ]
}
