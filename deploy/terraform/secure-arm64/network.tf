resource "oci_core_nat_gateway" "lip" {
  compartment_id = local.compartment_ocid
  vcn_id         = var.vcn_id
  display_name   = "oci-lip-nat-gateway"
  freeform_tags  = local.common_tags
}

resource "oci_core_route_table" "private" {
  compartment_id = local.compartment_ocid
  vcn_id         = var.vcn_id
  display_name   = "oci-lip-private-routes"
  freeform_tags  = local.common_tags

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_nat_gateway.lip.id
    description       = "Outbound OCI APIs and software updates through NAT"
  }
}

resource "oci_core_security_list" "private_empty" {
  compartment_id = local.compartment_ocid
  vcn_id         = var.vcn_id
  display_name   = "oci-lip-private-empty-security-list"
  freeform_tags  = local.common_tags

  egress_security_rules {
    protocol         = "6"
    destination      = var.private_subnet_cidr
    destination_type = "CIDR_BLOCK"
    description      = "OCI Bastion private endpoint to application SSH"

    tcp_options {
      min = 22
      max = 22
    }
  }
}

resource "oci_core_subnet" "private" {
  compartment_id             = local.compartment_ocid
  vcn_id                     = var.vcn_id
  cidr_block                 = var.private_subnet_cidr
  display_name               = "oci-lip-private-subnet"
  dns_label                  = "lipprivate"
  prohibit_public_ip_on_vnic = true
  route_table_id             = oci_core_route_table.private.id
  security_list_ids          = [oci_core_security_list.private_empty.id]
  freeform_tags              = local.common_tags
}

resource "oci_core_network_security_group" "load_balancer" {
  compartment_id = local.compartment_ocid
  vcn_id         = var.vcn_id
  display_name   = "oci-lip-load-balancer-nsg"
  freeform_tags  = local.common_tags
}

resource "oci_core_network_security_group" "application" {
  compartment_id = local.compartment_ocid
  vcn_id         = var.vcn_id
  display_name   = "oci-lip-application-nsg"
  freeform_tags  = local.common_tags
}

resource "oci_core_network_security_group_security_rule" "lb_http_ingress" {
  for_each = var.allowed_client_cidrs

  network_security_group_id = oci_core_network_security_group.load_balancer.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = each.value
  source_type               = "CIDR_BLOCK"
  description               = "HTTP validation and HTTPS redirect"

  tcp_options {
    destination_port_range {
      min = 80
      max = 80
    }
  }
}

resource "oci_core_network_security_group_security_rule" "lb_https_ingress" {
  for_each = var.allowed_client_cidrs

  network_security_group_id = oci_core_network_security_group.load_balancer.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = each.value
  source_type               = "CIDR_BLOCK"
  description               = "HTTPS application access"

  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_network_security_group_security_rule" "lb_to_application" {
  network_security_group_id = oci_core_network_security_group.load_balancer.id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = var.private_subnet_cidr
  destination_type          = "CIDR_BLOCK"
  description               = "Load balancer to private frontend"

  tcp_options {
    destination_port_range {
      min = 80
      max = 80
    }
  }
}

resource "oci_core_network_security_group_security_rule" "application_from_lb" {
  network_security_group_id = oci_core_network_security_group.application.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = oci_core_network_security_group.load_balancer.id
  source_type               = "NETWORK_SECURITY_GROUP"
  description               = "Frontend traffic from the OCI Flexible Load Balancer"

  tcp_options {
    destination_port_range {
      min = 80
      max = 80
    }
  }
}

resource "oci_core_network_security_group_security_rule" "application_https_egress" {
  network_security_group_id = oci_core_network_security_group.application.id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  description               = "OCI regional endpoints and software repositories"

  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_network_security_group_security_rule" "application_http_egress" {
  network_security_group_id = oci_core_network_security_group.application.id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  description               = "Package repository redirects during bootstrap"

  tcp_options {
    destination_port_range {
      min = 80
      max = 80
    }
  }
}

resource "oci_core_network_security_group_security_rule" "application_dns_egress" {
  network_security_group_id = oci_core_network_security_group.application.id
  direction                 = "EGRESS"
  protocol                  = "17"
  destination               = "169.254.169.254/32"
  destination_type          = "CIDR_BLOCK"
  description               = "VCN DNS resolver"

  udp_options {
    destination_port_range {
      min = 53
      max = 53
    }
  }
}

resource "oci_core_network_security_group_security_rule" "application_ntp_egress" {
  network_security_group_id = oci_core_network_security_group.application.id
  direction                 = "EGRESS"
  protocol                  = "17"
  destination               = "169.254.169.254/32"
  destination_type          = "CIDR_BLOCK"
  description               = "OCI NTP service"

  udp_options {
    destination_port_range {
      min = 123
      max = 123
    }
  }
}

resource "oci_core_network_security_group_security_rule" "application_iscsi_boot_egress" {
  for_each = toset([
    "169.254.0.2/32",
    "169.254.2.0/24",
  ])

  network_security_group_id = oci_core_network_security_group.application.id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = each.value
  destination_type          = "CIDR_BLOCK"
  description               = "OCI boot and block volume iSCSI endpoints"

  tcp_options {
    destination_port_range {
      min = 3260
      max = 3260
    }
  }
}
