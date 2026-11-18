resource "oci_core_instance" "lip" {
  compartment_id      = local.compartment_ocid
  availability_domain = var.availability_domain
  display_name        = var.deployment_name
  shape               = "VM.Standard.A1.Flex"
  shape_config {
    ocpus         = 2
    memory_in_gbs = 12
  }
  source_details {
    source_type             = "image"
    source_id               = var.image_ocid
    boot_volume_size_in_gbs = 100
  }
  create_vnic_details {
    subnet_id        = oci_core_subnet.private.id
    assign_public_ip = false
    nsg_ids          = [oci_core_network_security_group.application.id]
  }
  instance_options { are_legacy_imds_endpoints_disabled = true }
  agent_config {
    plugins_config {
      name          = "Bastion"
      desired_state = "ENABLED"
    }
  }
  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
      config = base64encode(jsonencode({
        tenancy                  = var.tenancy_ocid, region = var.region,
        secret_region            = var.secret_region, secret = var.oidc_secret_ocid,
        public_url               = var.public_url, commit = var.application_commit,
        notification_compartment = local.compartment_ocid,
        topic                    = oci_ons_notification_topic.alerts.name,
        scan_all_regions         = var.scan_all_regions,
        warning                  = var.warning_threshold_percent, critical = var.critical_threshold_percent
      }))
      ready     = filebase64("${path.module}/ready.sh")
      bootstrap = filebase64("${path.module}/bootstrap.py")
      install   = filebase64("${path.module}/install.sh")
      service   = filebase64("${path.module}/oci-lip.service")
    }))
  }
  depends_on = [
    oci_identity_policy.runtime, oci_core_route_table.private,
    oci_core_network_security_group_security_rule.application_https_egress,
    oci_core_network_security_group_security_rule.application_http_egress,
    oci_core_network_security_group_security_rule.application_dns_egress,
    oci_core_network_security_group_security_rule.application_ntp_egress,
    oci_core_network_security_group_security_rule.application_iscsi_boot_egress
  ]
  lifecycle {
    precondition {
      condition     = var.warning_threshold_percent < var.critical_threshold_percent
      error_message = "Warning threshold must be below the critical threshold."
    }
    # Guest updates are explicit, preserving the database on the boot volume.
    ignore_changes = [metadata["user_data"]]
  }
}
