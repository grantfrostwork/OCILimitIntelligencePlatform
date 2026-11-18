output "application_url" { value = var.public_url }
output "dns_a_record" { value = oci_core_public_ip.lip.ip_address }
output "compartment_ocid" { value = local.compartment_ocid }
output "instance_ocid" { value = oci_core_instance.lip.id }
output "instance_private_ip" { value = oci_core_instance.lip.private_ip }
output "bastion_ocid" { value = oci_bastion_bastion.lip.id }
output "notification_topic_ocid" { value = oci_ons_notification_topic.alerts.id }
output "next_steps" { value = "Point your hostname A record to dns_a_record, check guest bootstrap status, then complete the real SSO and email acceptance checks in README.md. Terraform completion is not application readiness." }
