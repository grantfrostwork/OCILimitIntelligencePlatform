resource "oci_bastion_bastion" "lip" {
  bastion_type                 = "STANDARD"
  compartment_id               = local.compartment_ocid
  target_subnet_id             = oci_core_subnet.private.id
  name                         = "oci-lip-bastion"
  client_cidr_block_allow_list = var.bastion_client_cidrs
  max_session_ttl_in_seconds   = 10800
  freeform_tags                = local.common_tags
}

resource "oci_core_network_security_group_security_rule" "application_from_bastion" {
  network_security_group_id = oci_core_network_security_group.application.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = "${oci_bastion_bastion.lip.private_endpoint_ip_address}/32"
  source_type               = "CIDR_BLOCK"
  description               = "SSH from the OCI Bastion private endpoint"

  tcp_options {
    destination_port_range {
      min = 22
      max = 22
    }
  }
}
