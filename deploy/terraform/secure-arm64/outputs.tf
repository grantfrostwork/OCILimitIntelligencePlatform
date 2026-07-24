output "load_balancer_id" {
  value = oci_load_balancer_load_balancer.lip.id
}

output "load_balancer_ip" {
  value = oci_load_balancer_load_balancer.lip.ip_address_details[0].ip_address
}

output "temporary_sslip_hostname" {
  value = "${replace(oci_load_balancer_load_balancer.lip.ip_address_details[0].ip_address, ".", "-")}.sslip.io"
}

output "private_instance_id" {
  value = oci_core_instance.lip.id
}

output "private_instance_ip" {
  value = oci_core_instance.lip.private_ip
}

output "private_subnet_id" {
  value = oci_core_subnet.private.id
}

output "bastion_id" {
  value = oci_bastion_bastion.lip.id
}

output "https_enabled" {
  value = var.certificate_id != ""
}
