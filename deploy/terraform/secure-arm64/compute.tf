resource "oci_core_instance" "lip" {
  availability_domain = var.availability_domain
  compartment_id      = local.compartment_ocid
  display_name        = var.instance_display_name
  shape               = "VM.Standard.A1.Flex"
  freeform_tags       = local.common_tags

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_gbs
  }

  create_vnic_details {
    assign_public_ip = false
    display_name     = "${var.instance_display_name}-vnic"
    hostname_label   = "lip"
    nsg_ids          = [oci_core_network_security_group.application.id]
    subnet_id        = oci_core_subnet.private.id
  }

  source_details {
    source_type             = "image"
    source_id               = var.image_id
    boot_volume_size_in_gbs = var.boot_volume_size_gbs
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

  agent_config {
    are_all_plugins_disabled = false
    is_management_disabled   = false
    is_monitoring_disabled   = false

    plugins_config {
      desired_state = "ENABLED"
      name          = "Bastion"
    }

    plugins_config {
      desired_state = "ENABLED"
      name          = "Compute Instance Run Command"
    }

    plugins_config {
      desired_state = "ENABLED"
      name          = "Fleet Application Management Service"
    }
  }

  metadata = {
    ssh_authorized_keys = file(pathexpand(var.ssh_public_key_path))
    user_data = base64encode(
      templatefile("${path.module}/cloud-init.yaml.tftpl", {
        auth_public_url   = var.auth_public_url
        repository_url    = var.repository_url
        repository_branch = var.repository_branch
        tenancy_ocid      = var.tenancy_ocid
      })
    )
  }

  lifecycle {
    precondition {
      condition     = var.instance_ocpus == 2 && var.instance_memory_gbs == 12
      error_message = "The supported customer ARM64 profile is 2 OCPUs and 12 GB RAM."
    }
  }
}
